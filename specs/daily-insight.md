# Feature E — Daily Insight

> Route `/insight` • replaces Briefing • Phase 15.

## 1. Question this view answers
**"Hôm nay có gì đáng chú ý tôi chưa biết, và tôi nên làm gì?"**

## 2. Why this exists (trader value)
- The legacy Briefing page dumped the same ranking/regime the other pages
  already show. It was a duplicate, not an insight.
- Expert traders don't want "BANK rank 13". They want: *"BANK flow z dropped
  to −1.1 after 3 days of foreign selling; similar setup in Oct 2024
  preceded a −6% move."* Narrative, context, and a recommended action.
- This view is the one place where **LLM narrative output** is acceptable,
  because narrative is exactly the value.

## 3. Layout (top-to-bottom)
1. **Headline narrative** (LLM-composed, top of page): 4–8 sentences,
   written by OpenClaw "Trung" agent. Must reference specific sectors, z
   values, and (if applicable) historical analogues.
2. **Top 3 deltas vs yesterday** — cards:
   - Biggest `flow_z20` change
   - Biggest regime/breadth change
   - New stealth entrant or rotation pair
   Each card has 1-line "what changed", 1-line "why it matters", 1-line
   "what to do".
3. **Action list** — 3 bullet points the trader should execute/check today.
4. **Raw data drawer** (collapsed): the old Briefing JSON for users who want
   to verify.
5. **Send to Gmail button** — same OpenClaw Gmail template, kept for
   compatibility.

## 4. Backend contract

### 4.1 Narrative generation (`services/insight/narrative.py`)
- Inputs: latest flow series, ranking, stealth active list, rotation pairs,
  and the previous day's snapshot (cached in `insight_cache` table).
- Template: deterministic skeleton filled by LLM only where prose is needed.
  (No "hallucinated" data — numbers come from the snapshot, LLM just writes
  the connective prose.)
- Cached per day; regenerated on demand.

### 4.2 `GET /api/insight/daily`
```
response:
  {
    date: "2026-04-09",
    narrative: "FISH's flow z20 reached 1.73 this morning, a 3-month high. Breadth has been rising for 4 sessions but foreign buy is only 2/20 so the stealth gate has not fully fired. Historical analogues from 2024 suggest ~8–14 days to potential breakout if foreign hit crosses 60%. On the other side, BROK flow z has collapsed to −1.07 — confirm the rotation toward STEEL before adding broker shorts.",
    deltas: [
      {
        kind: "flow_z_change",
        sector: "FISH",
        from: 1.21,
        to: 1.73,
        what_changed: "Flow z20 +0.52 overnight",
        why_it_matters: "Largest single-day jump in 3 months",
        what_to_do: "Watch for foreign hit ≥ 60% before adding"
      },
      ...
    ],
    actions: [
      "Monitor FISH foreign flow this afternoon",
      "Close BROK long if flow z stays below −1.0 tomorrow",
      "Review rotation pair BANK→STEEL in Rotation Map"
    ],
    raw: { /* the old briefing JSON for verification */ }
  }
```

### 4.3 `GET /api/insight/delta?since=YYYY-MM-DD` (used by the card strip)
```
response:
  {
    rows: [ { kind, sector, from, to, what_changed, why_it_matters, what_to_do } ]
  }
```

### 4.4 `POST /api/insight/send-gmail` (keeps legacy OpenClaw Gmail flow)

### 4.5 Async refresh (2026-04-20)
The old `POST /api/insight/refresh` ran the full pipeline (publish signals →
rebuild HOSE universe via KBS → call Claude agent → reassemble /daily)
synchronously. On a cold cache this routinely exceeded the frontend's 5-minute
axios timeout, leaving the UI with no recovery path beyond a blind retry.

The endpoint is now fire-and-poll, backed by
`services.insight_refresh.InsightRefreshRunner` (one daemon thread, singleton).
```
POST /api/insight/refresh              → 200 {run_id, stage, stage_label,
                                              started_at, already_running}
GET  /api/insight/refresh/status[?run_id=…]
                                       → 200 {run_id, stage, stage_label,
                                              progress: {done, total, pct},
                                              elapsed_sec, is_running, is_done,
                                              is_error, payload?, history,
                                              published_signals, publish_error,
                                              agent_error, error}
```
Stages in order: `queued → publishing_signals → rebuilding_universe →
trader_agent → assembling → done` (or `error`). The `rebuilding_universe`
stage reports live `done/total` counts from the OHLCV fan-out so the UI can
render a real progress bar.

Idempotency: a second `POST` while a run is in flight returns the *same*
`run_id` with `already_running=true`. No duplicate KBS calls, no wasted
Claude tokens.

Polling contract: the UI polls `/refresh/status` every 2 seconds. When the
response flips to `is_done=true`, `status.payload` carries the full /daily
JSON (same shape the old sync endpoint returned) and the UI drops it
straight into page state. Hard client-side ceiling: 20 minutes.

## 5. UI components (under `features/daily-insight/components/`)
- `NarrativeCard.tsx`
- `DeltaCards.tsx`
- `ActionList.tsx`
- `RawDataDrawer.tsx`

## 6. Acceptance
- Narrative contains ≥3 specific numbers (not generic phrasing).
- Delta cards always show the top 3 changes vs yesterday — never empty,
  because "no significant change" is itself a delta worth stating.
- Action list is derived from signals, not hand-written.
- Send-to-Gmail button posts the same narrative + delta cards as the page.
- Clicking "Refresh" returns control to the UI within ~100 ms (async pipeline, see §4.5). Stage label + progress % surface during the rebuild; final payload lands once `is_done=true` from the status poll.

## 7. Out of scope
- Free-form LLM chat.
- Cross-asset insight (fx, commodities, bonds) — stay sector-focused.
- Multi-language narrative (VN + EN) — VN only for now, defer EN.
