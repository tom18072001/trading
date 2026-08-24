# Phase 15 Redesign — Trader-First View Architecture

> Status: **SHIPPED, then superseded by §22.9** (annotated 2026-08-24).
> The 7→5 merge below happened, but not to the shape described here: the pages
> were built, four of them shipped with no `<Route>` for months, all nine were
> wired on 2026-08-23 and then merged back to **five nav items** the same day.
> `CLAUDE.md` §22.9 is the current nav; the table below is the 2026-04-09
> diagnosis of the legacy views, kept because it is the reasoning, not the
> outcome (§21: a dated record says when it was written).
>
> Status: **APPROVED intent** (2026-04-09, confirmed by Tom).
> This document is the **umbrella spec** for Phase 15. Individual features live in
> sibling files: `flow-monitor.md`, `rotation-map.md`, `stealth-watch.md`,
> `flow-pulse.md`, `daily-insight.md`, `close-idx-backfill.md`.
> Doc-first rule: no code in Phase 15 ships before the matching spec is updated.

## 0. Why this redesign (problem statement)

The previous frontend exposed 7 pages that were each shallow snapshots of a
table:

| Legacy view | Question it tried to answer | Actual outcome |
|---|---|---|
| Flow Dashboard | "Latest flow" | Static list — no rotation, no threshold, no chart, no interval |
| Rotation Ranking | "Rank sectors" | Score column with no "why", no persistence context |
| Regime Monitor | "Macro regime" | Heuristic fallback because `macro_anchors` is empty → not actionable |
| Sector Backtest | "Strategy sim" | Garbage numbers (−88%) because `close_idx` is synthetic |
| Risk | "VaR" | Static snapshot — doesn't show current-moment momentum |
| Briefing | "Daily note" | Dumps data, no insight, no narrative |
| Accumulation | "Stealth" | Static list — no pair concept, no timestamp, no timeline |

The core diagnosis: **the UI was aggregating the database instead of answering
questions an expert trader asks**.

## 1. UX principles (binding for every feature in this phase)

1. **One question per view.** Each feature page answers exactly one trader
   question in ≤3 seconds of eye-time. If the page cannot state its question
   in a single sentence, it is out of scope for that page.
2. **Interval is a first-class control.** Every time-series view exposes a
   toggle: `1D / 1W / 2W / 1M / 1Q`. The backend resamples; the frontend
   never re-aggregates client-side.
3. **Thresholds are configurable, never hard-coded.** Every z-score, every
   percentage cutoff is exposed as a `ThresholdInput` with a default, stored
   in `localStorage` per user. Defaults are in §5 below.
4. **Show the "why", not just the "what".** Every signal must expose the
   components that triggered it (for stealth: the 5-condition gate with
   ✓/✗; for rotation: the pair-level flow delta; for ranking: the feature
   contributions).
5. **Root cause over symptom.** When a metric is flagged, the UI links to
   the raw component chart — one click, not three.
6. **Fail loudly, not silently.** If a data source is empty (e.g. macro
   anchors), say so explicitly; do not render a fallback that looks like
   real data.

## 2. View inventory (5 views, down from 7)

| # | Name | Route | Replaces | Core question |
|---|---|---|---|---|
| A | Money Flow Monitor | `/` | Flow Dashboard + Rotation Ranking | "Dòng tiền đang vào/ra sector nào, cường độ, bất thường?" |
| B | Rotation Map | `/rotation` | — | "Tiền đang dịch chuyển TỪ sector nào SANG sector nào?" |
| C | Stealth Watch | `/stealth` | Accumulation | "Sector nào đang tích luỹ âm thầm, khi nào breakout?" |
| D | Flow Pulse | `/pulse` | Risk | "NGAY LÚC NÀY sector nào tiền vào/ra mạnh nhất, alert gì?" |
| E | Daily Insight | `/insight` | Briefing | "Hôm nay có gì đáng chú ý tôi chưa biết?" |

**Deletions (confirmed by Tom 2026-04-09):**
- ❌ `/ranking` — merged into Money Flow Monitor as integrated ranking table.
- ❌ `/regime` — deleted entirely. Macro anchors are empty; the HMM has no
  data to fit. Regime is downgraded to a small badge in the global header
  (`RISK_ON / RISK_OFF / ROTATION / CHOP`). When macro ingest is fixed in a
  later phase, regime may earn a page back.
- ❌ `/backtest` — deleted entirely. The synthetic `close_idx` blocker makes
  any backtest a toy. A real backtest will be rebuilt **only** after real
  OHLC is persisted (see `close-idx-backfill.md`). Deletion scope: page +
  router + service (`services/backtest_service.py`) + DB table retained for
  future restoration.

## 3. Folder structure — feature-sliced (renamed in this phase)

### Frontend
```
frontend/src/
├── app/
│   ├── App.tsx
│   ├── Layout.tsx
│   └── routes.tsx
├── features/
│   ├── flow-monitor/          # Money Flow Monitor
│   │   ├── api.ts
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── types.ts
│   │   └── index.tsx
│   ├── rotation-map/
│   ├── stealth-watch/
│   ├── flow-pulse/
│   └── daily-insight/
├── shared/
│   ├── ui/                    # IntervalToggle, ThresholdInput, Card, Table, ChartFrame
│   ├── api/client.ts
│   ├── hooks/
│   └── lib/fmt.ts
└── main.tsx
```

Legacy files **deleted** in this phase: `pages/ChartPage.tsx`,
`DashboardPage.tsx`, `DataPage.tsx`, `MLPage.tsx`, `ScreenerPage.tsx`,
`SectorPage.tsx`, `ShortTradePage.tsx`, `SignalPage.tsx`, `AgentPage.tsx`,
`BacktestPage.tsx`, `RegimePage.tsx`, `RankingPage.tsx`, `FlowPage.tsx`,
`RiskPage.tsx`, `BriefingPage.tsx`, `AccumulationPage.tsx`. All replaced by
`features/*`.

### Backend
```
api/routers/
├── flow.py         # /api/flow/{series,ranking,heat}
├── rotation.py     # /api/rotation/{pairs,sankey}
├── stealth.py      # /api/stealth/{active,warming,timeline}
├── pulse.py        # /api/pulse/{live,alerts,exposure,var}
└── insight.py      # /api/insight/{daily,delta}

services/
├── flow/
│   ├── aggregation.py     # interval resampler (D→W→2W→M→Q)
│   ├── ranking.py         # merged ranker/scorer
│   └── heat.py
├── rotation/
│   ├── pair_detector.py   # pair-level rotation detection
│   └── sankey.py
├── stealth/
│   ├── detector.py        # §16.1 gate
│   └── lead_time.py
├── pulse/
│   ├── live.py
│   ├── alerts.py
│   └── var.py
└── insight/
    ├── narrative.py       # LLM/OpenClaw composer
    └── delta.py

scripts/
└── backfill_close_idx.py  # NEW — fetches real OHLC, writes close_idx
```

Deleted services: `services/backtest_service.py`,
`services/rotation_model_service.py` (HMM half — the ranker logic moves into
`services/flow/ranking.py`), `services/sector_signal_service.py` (replaced
by `flow/ranking.py` + `stealth/detector.py`).

## 4. Cross-cutting backend contract

### 4.1 Interval resampling
Every time-series endpoint accepts `interval` in `{1d, 1w, 2w, 1m, 1q}`,
default `1d`. Resampling is centralized in `services/flow/aggregation.py`
with these rules:
- `net_dollar_flow`, `foreign_net`, `up_vol`, `down_vol`: **sum**
- `breadth_sma20`, `atr_pct`: **mean**
- `flow_z20`, `stealth_score`, `return_1d`: **last** (already a rolling stat)
- `rank`, `score`: **recomputed** on the resampled frame, not averaged

### 4.2 Threshold contract
Thresholds are passed as query params on every detection endpoint. Defaults
(confirmed by Tom):
- `flow_z_hot = 1.0`, `flow_z_extreme = 2.0`
- `foreign_hit_min = 0.6`
- `breadth_min = 0.5`
- `atr_rank_max = 0.5`

### 4.3 Error surfacing
If a required table is empty (e.g. `macro_anchors`), the endpoint returns
HTTP 200 with `{ "status": "empty", "reason": "macro_anchors has 0 rows" }`.
Frontend renders an explicit banner, not a spinner.

## 5. Default thresholds (exposed to user via `ThresholdInput`)

| Threshold | Default | Where used |
|---|---|---|
| `flow_z_hot` | +1.0 / −1.0 | Flow Monitor halo, Rotation pair detection |
| `flow_z_extreme` | +2.0 / −2.0 | Flow Pulse alert, Stealth override |
| `foreign_hit_min` | 0.60 | Stealth cond 2 |
| `breadth_min` | 0.50 | Stealth cond 3, Flow Monitor filter |
| `atr_rank_max` | 0.50 | Stealth cond 4 (quiet tape) |
| `accumulation_min_sessions` | 5 | Stealth cond persistence |
| `rotation_pair_min_delta_z` | 1.5 | Rotation Map pair visibility |
| `pulse_alert_z` | 1.5 | Flow Pulse ping threshold |

User overrides stored in `localStorage` under key `phase15:thresholds`.

## 6. Implementation order (binding)

1. **Doc-first**: this file + 5 feature specs + `close-idx-backfill.md`, then
   `ARCHITECTURE.md` + `CLAUDE.md §17` updated, then Phase 15 logged in
   `MODIFICATION_LOG.md` as intent. **No code merged at step 1.**
2. **Backend foundation**: `services/flow/aggregation.py` interval resampler
   + `flow.py` router + threshold contract tests.
3. **Close_idx backfill**: `scripts/backfill_close_idx.py` — unblocks real
   backtest and cond 5 of stealth. (See dedicated spec.)
4. **Feature A — Money Flow Monitor**: the anchor view. Must ship first
   because every other view reuses its chart frame + interval toggle.
5. **Feature B — Rotation Map**: depends on A's aggregation layer.
6. **Feature C — Stealth Watch**: depends on close_idx backfill.
7. **Feature D — Flow Pulse**: depends on A.
8. **Feature E — Daily Insight**: depends on A, B, C (consumes their signals).
9. **Delete legacy**: only after all 5 features are green in preview, delete
   the legacy files/routes/services listed in §3.
10. **Phase 15 close**: final `MODIFICATION_LOG.md` entry with before/after
    view table and a pointer to this spec.

## 7. Success criteria

- Every one of the 5 pages answers its §2 question in ≤3s eye-time (self-test
  with Tom).
- Every time-series chart has interval toggle + threshold line.
- Rotation Map renders a Sankey + pair table for the current interval.
- Stealth Watch shows ≥1 active sector on the 2024 Q4 bank rally replay
  (ground-truth test).
- Flow Pulse pings within 30s of a z-crossing.
- Daily Insight narrative names the top 3 changes vs yesterday with specific
  numbers.
- `close_idx` column is non-synthetic for ≥90% of sector-days in 2024-2026.
- Backtest page, regime page, ranking page, and all legacy symbol pages are
  deleted from the repo.

## 8. Non-goals for Phase 15

- Re-introducing a backtest engine (deferred until real OHLC is persisted
  and trader has a clear strategy to test).
- Re-introducing a regime model (deferred until macro anchors are ingested).
- Live intraday (<15 min) ticks — still 15-min bars for intraday + EOD.
- Multi-user personalization beyond `localStorage` thresholds.
