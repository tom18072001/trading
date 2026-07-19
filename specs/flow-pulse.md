# Feature D — Flow Pulse

> Route `/pulse` • replaces Risk • Phase 15.

## 1. Question this view answers
**"NGAY LÚC NÀY sector nào tiền đang vào/ra mạnh nhất, có alert gì tôi cần hành động?"**

## 2. Why this exists (trader value)
- The legacy Risk page was a static VaR/CVaR snapshot. Expert traders don't
  look at VaR during the session — they look at **momentum right now** and
  ask "should I act?".
- Tom asked: "risk phải xem được thời điểm hiện tại sector dòng tiền nào lên
  hay xuống". This view is a live tape, not a report.
- VaR is not deleted — it moves into a secondary panel (still useful for
  end-of-day review) but is no longer the headline.

## 3. Layout (top-to-bottom)
1. **Live tape** (headline) — 15 sectors, one row each:
   - Sector code
   - Arrow ↑/↓ with color (green/red) and magnitude (%Δ share vs yesterday)
   - Current `flow_z20` with a delta vs 1h ago
   - Foreign net streak badge
   - Action chip (ALERT if crosses user's `pulse_alert_z`, neutral otherwise)
   - Sparkline of last 20 bars of `net_dollar_flow`
2. **Alerts strip** — persistent ticker of all triggered pings in the last
   session, newest first. Click an alert → opens the sector in Flow Monitor.
3. **Open exposure panel** — held sector positions (from `sector_signals`
   where action = BUY/ACCUMULATE). Columns: sector, side, weight, entry date,
   unrealized return, stop distance.
4. **Risk secondary panel** (collapsed by default): VaR/CVaR table + drawdown
   curve — same data as legacy Risk page, just demoted.

## 4. Backend contract

### 4.1 `GET /api/pulse/live`
```
params:
  alert_z: float (default 1.5)
response:
  {
    as_of: "...",
    rows: [
      {
        sector: "STEEL",
        arrow: "up" | "down" | "flat",
        delta_share_pct: 3.2,
        flow_z20: 1.42,
        flow_z20_delta_1h: +0.3,
        foreign_streak: 4,
        alert: true,
        sparkline: [ ... 20 floats ... ]
      },
      ...
    ]
  }
```
Polled every 30s from the frontend.

### 4.2 `GET /api/pulse/alerts`
```
params:
  since: ISO timestamp (default start-of-session 09:00 Asia/Ho_Chi_Minh)
response:
  {
    rows: [
      { ts, sector, event: "z_cross_hot" | "z_cross_extreme" | "foreign_streak_5+", value, message }
    ]
  }
```

### 4.3 `GET /api/pulse/exposure`
```
response:
  {
    rows: [ { sector, side, weight_pct, entry_date, entry_score, unrealized_return_pct, stop_distance_pct } ]
  }
```

### 4.4 `GET /api/pulse/var` (secondary panel)
```
response: (same as legacy /api/sectors/risk/var)
```

## 5. UI components (under `features/flow-pulse/components/`)
- `LiveTape.tsx` — the 15-row headline.
- `AlertsTicker.tsx`.
- `ExposurePanel.tsx`.
- `VarPanel.tsx` (collapsed by default).
- `Sparkline.tsx` — lifts the one from legacy FlowPage into `shared/ui/`.

## 6. Acceptance
- Live tape polls `/api/pulse/live` every 30s and updates arrows/deltas
  without a full re-render.
- A sector whose `flow_z20` crosses user's `pulse_alert_z` appears in the
  Alerts strip within 1 poll cycle.
- Clicking a live-tape row navigates to Flow Monitor with that sector
  preselected in the drill-down.
- VaR panel remains queryable but is collapsed on first load.

## 7. Out of scope
- Actual order routing / broker integration.
- Multi-leg alerts (e.g. "BANK z down AND STEEL z up simultaneously") —
  interesting, defer.
