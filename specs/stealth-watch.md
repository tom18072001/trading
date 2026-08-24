# Feature C — Stealth Watch

> Route `/stealth` • replaces Accumulation • Phase 15.

## 1. Question this view answers
**"Sector nào đang tích luỹ âm thầm, tôi có thể mua ở gốc, và dự đoán breakout khi nào?"**

## 2. Why this exists (trader value)
- Tom's Edge Doctrine (CLAUDE.md §16): in VN, news lags real money by ~1
  month. Smart money accumulates quietly before any narrative forms. The
  goal is to detect this 2–4 weeks ahead of the breakout.
- The previous Accumulation page showed a flat list with no timeline, no
  condition gate, and no lead-time estimate. Traders couldn't see WHY a
  sector was flagged or WHEN to act.

## 3. Layout (top-to-bottom)
1. **Global header** (shared): interval toggle (`1D 1W 2W 1M 1Q`), threshold
   inputs for `foreign_hit_min`, `breadth_min`, `atr_rank_max`,
   `accumulation_min_sessions`.
2. **Flow z20 heatmap** (same component as Flow Monitor, but restricted to
   warming/active sectors and color-graded by `stealth_score`).
3. **Active stealth timeline** — horizontal Gantt-style bar chart. One row
   per sector in active or warming state. Bar starts at `start_date`, width
   = `accumulation_age`, color intensity = `stealth_score`.
4. **Active panel** — for each active sector, a card showing the 5-condition
   gate with ✓/✗:
   - cond 1: `flow_z20 > +flow_z_hot` (value shown)
   - cond 2: `foreign_hit_20d ≥ foreign_hit_min`
   - cond 3: `breadth_sma20` rising
   - cond 4: `atr_rank_20d ≤ atr_rank_max` (quiet tape)
   - cond 5: `close_idx` in bottom 40% of 60d range
   - Persistence counter: `X / accumulation_min_sessions` sessions
5. **Lead-time estimate** — for each active: historical median lead-time to
   breakout for that sector's past stealth events. "Est. breakout: ~8–14d".
6. **History log** — resolved stealth events with outcome (peak return, lead
   days to price, whether the trade was a hit).

## 4. Backend contract

### 4.1 Detector refinement (`services/stealth/detector.py`)
Existing `analysis/stealth.py` is kept but wrapped:
- All thresholds come from the request, not from env or module constants.
- Cond 5 (price cheap) now uses **real** `close_idx` (after Phase 15's
  close_idx backfill). The `STEALTH_SYNTHETIC_CLOSE` escape hatch is removed.
- The detector returns per-condition booleans **and** the raw numbers, so
  the UI can render the gate panel without recomputation.

### 4.2 `GET /api/stealth/active`
```
params:
  interval: 1d | 1w | 2w | 1m | 1q (default 1d)
  flow_z_hot: float (default 1.0)
  foreign_hit_min: float (default 0.6)
  breadth_min: float (default 0.5)
  atr_rank_max: float (default 0.5)
  min_sessions: int (default 5)
response:
  {
    as_of: "...",
    active: [
      {
        sector: "FISH",
        start_date: "2026-03-20",
        accumulation_age: 15,
        stealth_score: 1.57,
        flow_z20: 1.73,
        gate: {
          cond1_flow: { pass: true, value: 1.73, threshold: 1.0 },
          cond2_foreign_hit: { pass: true, value: 0.65, threshold: 0.6 },
          cond3_breadth: { pass: true, value: 0.60, trend: "rising" },
          cond4_atr_quiet: { pass: true, value: 0.35, threshold: 0.5 },
          cond5_price_cheap: { pass: true, close_pct_of_60d: 0.28, threshold: 0.40 }
        },
        lead_time_estimate_days: { median: 11, p25: 7, p75: 18 }
      },
      ...
    ],
    warming: [ { sector, conditions_passing: 3, highest_z: 1.2, ... }, ... ]
  }
```

### 4.3 `GET /api/stealth/timeline`
```
params: interval, lookback_days (default 180)
response:
  {
    rows: [
      {
        sector: "FISH",
        events: [
          { start: "2026-03-20", end: null, age: 15, peak_score: 1.57, resolved: false },
          { start: "2025-11-01", end: "2025-11-20", age: 14, peak_score: 2.1, resolved: true, outcome: { peak_return_pct: 12.3, lead_days: 9 } }
        ]
      },
      ...
    ]
  }
```

### 4.4 `GET /api/stealth/history`

> **Shipped 2026-08-24** — it had returned a hardcoded `{"rows": []}` since it
> was written. Response below is what runs; the shape above it in git history
> was a sketch.

```
params: limit (default 50, 1..500)
response:
  {
    rows: [ {
      sector_code, name, start_date, end_date, sessions,
      peak_score, peak_return_pct, lead_days_to_price,
      classification, resolved
    } ],
    summary: { events, scored, hit_rate, median_lead_days, early_share }
  }
```

`classification` is `"HIT" | "FALSE POSITIVE" | "DRY-POWDER TIMEOUT"` **or
`null`** — the display strings, mapped in the router; the underlying enum stays
snake_case in `analysis.stealth.stealth_events()`.

Three things the sketch did not say, each load-bearing:

- **`classification` is nullable, and `null` is not a failure.** A run still
  going, or one whose 40-session forward window has not elapsed, has no verdict.
  Scoring it as a miss would understate the gate on every refresh, permanently.
  `resolved` mirrors this; `summary.scored` counts only the judged ones, so
  `hit_rate` is not diluted by events that have not had their chance.
- **`end_date` is `null` for an open run**, not today's date.
- **Derived from `sector_flow_daily.accumulation_age`, not from
  `sector_accumulation_events`.** That table has had no writer since migration 9
  created it, so reading it returns the same empty list by a longer route — and
  once something does write it, the same fact lives in two places that can
  disagree.

Breakout is `analysis.stealth.breakout_bar_scaled` — the same function
`scripts/stealth_leadtime_experiment.py` scores with, by identity, pinned by
`test_the_bench_and_the_endpoint_share_one_breakout_definition`. See §16.15 for
why the daily `2 × atr_pct` bar was a liveness test.

Live on the 13,485-row panel: **21 events, 20 scored, hit_rate 0.40, median lead
21 sessions, 75% at ≥10** — matching the bench's shipped-gate row exactly, which
is the point of the shared definition. Read against §16.14: the unconditional
base rate is 43% / 74%, so the gate still does not beat not filtering.

## 5. UI components (under `features/stealth-watch/components/`)
- `StealthTimeline.tsx` — Gantt-style horizontal bars.
- `GatePanel.tsx` — the 5-condition ✓/✗ card.
- `LeadTimeBadge.tsx` — shows `{median} · {p25}–{p75} days`.
- `StealthHistoryTable.tsx`.

## 6. Acceptance
- After `close_idx` backfill lands, the active list is non-empty for the
  2024 Q4 bank rally replay window.
- Each active sector card shows all 5 conditions with real numbers — no
  "—" placeholders.
- Timeline renders ≥1 resolved event from historical replay.
- Threshold change re-fetches within 500ms.
- Dry-powder-timeout events (>30 sessions without breakout) show up as a
  distinct classification in the history log, not as "hit".

## 7. Out of scope
- Retraining the ranker from scratch — that's a model phase, not a view phase.
- Portfolio sizing logic — Flow Pulse handles live exposure; sizing is a
  strategy concern for a future phase.
