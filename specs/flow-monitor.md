# Feature A — Money Flow Monitor

> Route `/` • replaces Flow Dashboard + Rotation Ranking • Phase 15.

## 1. Question this view answers
**"Dòng tiền đang vào/ra sector nào, cường độ bao nhiêu, có bất thường không?"**

One sentence, one view. Everything on this page is subordinate to that
question. If an element does not help a trader answer it in ≤3 seconds, the
element is out of scope.

## 2. Why this exists (trader value)
- The trader's first action every morning is scanning "where's the money?".
  Today they either read 15 separate sector tickers or skim news (which lags
  real money by ~1 month per Tom's Edge Doctrine). This view replaces both.
- Rotation Ranking as a separate page forced the trader to flip between
  "flow" and "rank" to form one decision. Merging them removes a click and
  keeps context.

## 3. Layout (top-to-bottom)
1. **Global header bar** (shared across all features):
   - Interval toggle: `1D 1W 2W 1M 1Q` (default `1D`)
   - Threshold inputs: `flow_z_hot` (default ±1.0), `flow_z_extreme` (±2.0)
   - Regime badge (pill): `RISK_ON / RISK_OFF / ROTATION / CHOP / unknown`
   - "As of" timestamp
2. **Multi-line chart** — `flow_z20` of all 15 sectors over the selected
   interval window (default 90 bars back).
   - Horizontal threshold lines at user's `±flow_z_hot` and `±flow_z_extreme`.
   - Sectors above `+flow_z_hot` highlighted green; below `-flow_z_hot` red.
   - Hover = crosshair with all 15 sector values at that timestamp.
3. **Heat strip** — matrix (15 rows × N bars). Each cell color-coded by
   `flow_z20`. Compact, one glance → "who's been hot lately".
4. **Ranking table** — merged from the old Ranking page.
   Columns: `#`, `Sector`, `Score`, `Flow z20`, `Foreign hit 20d`, `Breadth`,
   `ATR%`, `Action`, `Why`. `Why` is a chip list showing which gate
   conditions triggered.
5. **Sector drill-down panel** (appears on row click): overlay full history
   chart of that sector's `net_dollar_flow`, `foreign_net`, and `close_idx`,
   plus a list of the proxy basket constituents and their contribution.

## 4. Backend contract

### 4.1 `GET /api/flow/series`
```
params:
  interval: 1d | 1w | 2w | 1m | 1q  (default 1d)
  lookback: int (default 90, max 500)
  sectors:  csv of codes (default = all 15)
response:
  {
    interval: "1d",
    points: [
      { ts: "2025-12-01", sector: "BANK", net_dollar_flow: -1.3e8, flow_z20: -0.42, ... },
      ...
    ],
    as_of: "2026-04-09T00:00:00"
  }
```
Resampled server-side per Phase 15 §4.1 rules.

### 4.2 `GET /api/flow/ranking`
```
params:
  interval: (as above)
  threshold_hot: float (default 1.0)
response:
  {
    as_of: "...",
    rows: [
      {
        rank: 1,
        sector: "STEEL",
        score: 91007954.6,
        flow_z20: 1.42,
        foreign_hit_20d: 0.05,
        breadth: 0.80,
        atr_pct: 0.0142,
        action: "HOLD" | "BUY" | "SELL" | "ACCUMULATE",
        why: ["flow_z20 > +1.0", "breadth rising"]
      },
      ...
    ]
  }
```
`why` is the list of gate conditions that fired. This is non-negotiable — it
is how the view satisfies principle §1.4 ("show the why").

### 4.3 `GET /api/flow/heat`
```
params: interval, lookback
response:
  {
    columns: ["2025-12-01", "2025-12-02", ...],
    rows: [
      { sector: "BANK", values: [0.12, -0.44, ...] },
      ...
    ]
  }
```
Values are `flow_z20`. Null = missing bar.

### 4.4 `GET /api/flow/sector/{code}`
```
params: interval, lookback
response:
  { sector, points: [{ts, net_dollar_flow, foreign_net, close_idx, flow_z20, breadth, atr_pct}, ...] }
```

## 5. UI components (under `features/flow-monitor/components/`)
- `FlowChart.tsx` — multi-line z-score chart with threshold lines.
- `HeatStrip.tsx` — 15×N matrix, color-graded.
- `RankingTable.tsx` — sortable, `why` as chip list, click opens drill-down.
- `SectorDrillPanel.tsx` — full-history overlay.
- `IntervalToggle.tsx` — shared (lives under `shared/ui/`).
- `ThresholdInput.tsx` — shared (lives under `shared/ui/`).

## 6. Acceptance
- Opening `/` with default settings shows a legible 15-line z-score chart
  within 1s on the 3y-backfilled DB.
- Changing interval from `1D` to `1W` re-fetches and re-renders within 500ms
  (server resamples; client does not).
- Clicking a ranking row opens the drill-down **without** full page reload.
- Hovering the chart shows crosshair values for all 15 sectors.
- The regime pill reads from `/api/insight/regime-badge` (or equivalent) and
  is visually distinct for each of the 4 labels + `unknown`.

## 7. Out of scope
- Intraday tick stream (defer to Flow Pulse).
- Predicting next-day return (that's a ranker model, not a monitor view).
- Multi-sector pair comparison on the main chart (that's Rotation Map).
