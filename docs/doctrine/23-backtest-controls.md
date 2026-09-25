# §23 — Backtest controls, và flow_z chính là flow_raw

> Tách khỏi `CLAUDE.md` ngày 2026-09-16 để doctrine trở lại ngân sách context
> (135.718 B nạp lại **mỗi lượt**; ngân sách của `claude/CLAUDE.md` mẹ là 10 KB).
> **Nội dung dưới đây nguyên văn** — không tóm tắt, không sửa số, không sửa ngày.
> `CLAUDE.md` giữ lại: kết luận: 3 chiến lược phân biệt được, chi phí đã mô hình hoá, và §23.5 còn mở, và trỏ về file này.

## 23. Backtest controls — and `flow_z` was `flow_raw` in disguise — 2026-08-23

> **2026-09-25 — slippage is 0.3% per side, flat.** The `max(0.3%, 0.5×ATR%)`
> below never left its floor: the sector `atr_pct` it read was 1/5 of the real
> basket ATR (review 2026-09-24 §4.1/3). Fixed, the formula charged ~1.4% per
> side; on the repaired 2026-09-24 database `flow_z` 2024-01 → 2026-09 paid 66.1%
> of capital in costs at a 20-session hold (−58.4%) and 50.2% at 40 (−18.6%),
> against 26.2% (−22.1%) and 16.9% (+14.3%) at a flat 0.3%. Tom chose the flat
> figure — the one `analysis/bench.py` already charged the ticker rules — so
> `config.BACKTEST_SLIPPAGE_ATR_MULT = 0`. VNINDEX did +60.0% over the same
> window; neither assumption changes the verdict on the sector strategies.

### 23.1 What was unreachable
`services/backtest_service.py` has modelled the whole of §18.2/7–10 since
2026-08-22 — T+2 settlement, per-side broker fee, the 0.1% sell tax, slippage
`max(0.3%, 0.5×ATR%)` and the ±7% HOSE band — and returns each of them on the
result. None of it reached a human:

| existed in the service | why nobody saw it |
|---|---|
| three strategies (`signals` / `flow_z` / `flow_raw`) | the router's request model carried no `strategy`, so every run the UI could trigger was the default |
| per-run fee / tax / settlement overrides | same — no field in |
| ten realism fields on the result | `client.ts`'s `BacktestResult` type omitted them |
| `trade_log` | fetched and discarded by the page |
| VNINDEX | returned as a **scalar total only**, so the chart could draw one line |

All five are now surfaced (`api/routers/sectors_backtest.py`, `client.ts`,
`BacktestPage.tsx`). `strategy` is a Pydantic `Literal`, not `str`: unvalidated,
a typo fell through the `if/elif` to the `flow_raw` branch — the one behaviour
nobody wants by accident. Costs are clamped at the service (`max(0.0, …)`); a
negative fee would otherwise pay the trader to trade.

### 23.2 The defect shipping the selector exposed
`flow_z` and `flow_raw` were **the same strategy**. Measured over
2026-04-09→08-23: both −25.06%, both 330 trades, byte-identical.

`_cross_sectional_z` computes `(v − mean)/sd` **within the same day the rows are
then sorted in**. That is a positive affine map, and a positive affine map
preserves order — so it always produced the raw-VND permutation. Verified twice:
a five-row worked example and 2000/2000 random days identical.

So §20.2's P0-4 row was half true. The signals replay was real; the size-bias
fix it claimed for the flow baseline never changed a single ordering.

`flow_z` now ranks on **`flow_z20`** — the z of a sector against *its own* 20d
history, which is what §16.2 means by flow z and the only version that can make
a small sector reachable. Three genuinely distinct strategies now:
`signals −6.14% / flow_z −26.07% / flow_raw −25.06%`. Two tests pin both the fix
and the proof.

### 23.3 The false caveat, removed
The Sharpe tile said T+2, fees, tax and the price band were **not** modelled.
That was written from §18.6's open-BLOCKER list without reading the service,
which had modelled all four for a day. It now names the resolved figures the run
actually used. A caveat that is false is worse than none: it teaches the reader
to discount a number that is already net.

Consequence for doctrine: **§18.2/7, 9, 10 and §18.6's P0 row for them are
closed in the backtest engine.** They remain open in `risk_service`, which sizes
positions without a cost model.

### 23.4 The default range guaranteed a silent fallback
The page opened on `2025-01-01 → 2025-12-31`. `sector_signals` starts
2026-04-09, so the default range had zero of them and the page opened on a
strategy it could not run — falling back to the flow baseline with only a
`print()` to say so. Defaults are now `2026-04-09 → today`, and a fallback
raises a visible banner instead of a server-side log line.

### 23.5 Open, logged, not fixed
- **45% friction on 844 trades a year** at default costs. Not a cost-model bug —
  daily rebalance turnover. It says the simulated strategy is uninvestable, and
  no §18.7 net-of-cost Sharpe target is credible until it changes.
- `macro_anchors` has **no VNINDEX rows for 2025**, so those ranges label the
  benchmark `sector_mean` rather than the §11-mandated VNINDEX.
- Zero-VND trade-log rows want a minimum-allocation floor.
- `_cross_sectional_z` is kept only because `_persist` and the P0-4 tests refer
  to it; it has no caller that depends on its ordering.

