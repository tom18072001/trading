# Feature B — Rotation Map

> Route `/rotation` • new • Phase 15.

## 1. Question this view answers
**"Tiền đang dịch chuyển TỪ sector nào SANG sector nào trong khoảng thời gian tôi chọn?"**

This is the view Tom wanted when he said "tôi muốn thấy mối quan hệ — các cặp
chuyển dịch dòng tiền". It is pair-centric, time-windowed, and explicit about
direction.

## 2. Why this exists (trader value)
- Rotation is the VN market's dominant regime. "Money leaves bank → enters
  broker" is a common pattern Tom cites. Until this view exists, traders have
  to eyeball 15 sector tickers and infer rotation mentally.
- A Sankey gives the shape of the flow; a pair table gives the actionable
  detail. Tom explicitly asked for both.

## 3. Layout (top-to-bottom)
1. **Global header** (shared): interval toggle, threshold (`rotation_pair_min_delta_z`, default 1.5), as-of.
2. **Sankey diagram** (top half): left column = sectors with negative Δ flow
   share; right column = sectors with positive Δ flow share. Ribbon width ∝
   magnitude of transfer. Color of ribbon = source sector color.
3. **Pair table** (bottom half): top N rotations, columns:
   `Rank`, `From`, `→`, `To`, `Δ flow z`, `Started`, `Age (d)`, `Persistence`,
   `Correlation (lead-lag)`, `Action chip`.
4. **Pair drill-down** (on row click): 2-sector overlay chart — their
   `flow_z20` lines, their `net_dollar_flow` bars, correlation, and the
   estimated lead-lag (in sessions).

## 4. Backend contract

### 4.1 Pair detection algorithm (lives in `services/rotation/pair_detector.py`)
For a window `W` defined by the interval:
1. Compute each sector's **market share of flow**: `share_i = net_dollar_flow_i / Σ|net_dollar_flow|`.
2. Δ share = `share_i(t_end) − share_i(t_start)`.
3. A sector is a **source** if Δ share < `−rotation_pair_min_delta_z · σ(Δshare)`.
4. A sector is a **target** if Δ share > `+rotation_pair_min_delta_z · σ(Δshare)`.
5. For every (source, target) pair, compute a **rotation weight**:
   `weight = min(|Δshare_source|, |Δshare_target|) · corr(flow_source, flow_target) · lag_adjust`
   where `lag_adjust = 1 − (optimal_lag / W)` rewards pairs that actually
   track each other with a 1–3 session lag.
6. Return the top N pairs by weight.

### 4.2 `GET /api/rotation/sankey`
```
params:
  interval: 1d | 1w | 2w | 1m | 1q
  threshold: float (default 1.5)
response:
  {
    interval: "1w",
    window: { start: "...", end: "..." },
    nodes: [{ id: "BANK", side: "source", delta_share: -0.08 }, ...],
    links: [{ source: "BANK", target: "STEEL", weight: 0.054, corr: 0.62, lag_days: 2 }, ...]
  }
```

### 4.3 `GET /api/rotation/pairs`
```
params: interval, threshold, limit (default 20)
response:
  {
    rows: [
      {
        rank: 1,
        from: "BANK",
        to: "STEEL",
        delta_z_source: -1.8,
        delta_z_target: +2.1,
        started: "2026-03-28",
        age_days: 12,
        persistence_sessions: 8,
        corr: 0.62,
        lag_days: 2,
        action: "CONFIRMED" | "EMERGING" | "FADING"
      },
      ...
    ]
  }
```

### 4.4 `GET /api/rotation/pair/{from}/{to}`
```
params: interval
response:
  {
    from, to,
    points: [{ ts, from_flow_z20, to_flow_z20, from_net, to_net }],
    corr: 0.62,
    lag_days: 2,
    started: "..."
  }
```

## 5. UI components (under `features/rotation-map/components/`)
- `SankeyChart.tsx` — uses a small D3 sankey layout; no heavy dep beyond d3-sankey.
- `PairTable.tsx`
- `PairDrillPanel.tsx` — 2-line overlay chart.

## 6. Acceptance
- With 1W interval on the backfilled DB, the Sankey renders ≥3 ribbons
  (non-empty rotation).
- Clicking a ribbon or a pair row opens the same drill-down.
- Threshold change re-fetches and redraws within 500ms.
- For the 2024 Q4 bank-rally-then-rotation ground truth, the pair table
  contains `BANK → STEEL` or `BANK → BROK` within its window.

## 7. Out of scope
- Multi-hop rotation (A → B → C chains) — interesting but defer to Phase 16.
- Intraday rotation — daily resolution minimum for this view.
