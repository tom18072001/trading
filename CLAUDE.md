# CLAUDE.md — Sector Money-Flow Redesign (Approved Plan)

> Status: **APPROVED** — 2026-04-08
> Supersedes: legacy 170-symbol prediction system
> Owner: Tom (anhchitruong18@gmail.com)
> Rule: every future modification MUST append an entry to `MODIFICATION_LOG.md`.

## 1. Mission
Pivot the VN Trading system from per-symbol prediction to **sector-level money-flow tracking and rotation prediction** across the 15 inherited VN sectors. Goal: fewer, higher-signal records; slower, more persistent edge; lower compute.

## 2. Inheritance Rules (from legacy)
- KEEP: Python/FastAPI/SQLAlchemy/SQLite(WAL), migrations, service-layer pattern, router pattern, backtest engine skeleton, risk math, scheduler heartbeat (Asia/Ho_Chi_Minh), vnstock integration.
- REMOVE: 170-symbol universe, `stock_prices`, `stock_features`, `trade_setups`, `predictions`, symbol screener, T+3 scanner, symbol pages in frontend, per-symbol ML.
- REPLACE: primary key `symbol` → `sector_code` everywhere.
- **Per-ticker picks (2026-04-17 onward):** `generate_report.py` and `api/routers/insight.py` read per-ticker BUY/ACCUMULATE picks exclusively from `services.picks_universe_service.PicksUniverseService` (dynamic HOSE universe from vnstock Listing). They no longer read `_legacy_stocks`, `_legacy_stock_prices`, or `_legacy_stock_features`. These three tables stay in the DB during a 2-week shadow window then drop in migration 10.
- **Email report (2026-04-23 onward):** `generate_report.py` is the **sole** daily email generator. It unifies the picks surfaced in the Daily Insight page (`snapshot.top_buys`/`top_sells` — no ranker gate) with the ranker-gated BUY/ACCUMULATE picks into a single de-duped list, each entry tagged with its source (`BOTH` / `DAILY_INSIGHT` / `RANKER`). The HTML/PDF gains an Expert Trader Memo section at the top; the email body is plain text (buy symbols + reasons + Dashboard + news links). Default recipients: `tka2001@gmail.com, anhchitruong18@gmail.com, hill.nguyen.1373@gmail.com`. `scripts/jobs/job_sector_signal_publish.bat` calls `generate_report.py`.
- **One report generator, no versioned copies.** `generate_report.py` is the only
  daily-report generator in the repo. Every earlier numbered copy is gone:
  SecV2 on 2026-04-20, SecV3 + SecV4 on 2026-06-18 (they were kept only as
  manual rollback paths and had drifted into duplicate-but-divergent helpers),
  and SecV5 was renamed to `generate_report.py` on 2026-08-22 (§21 — version
  numbers do not belong in names). If a stale Task Scheduler entry still points
  at one of them, run `scripts/pause_legacy_email_task.ps1` (elevated
  PowerShell) to evict it, then `scripts/cleanup_scheduled_tasks.ps1` to
  re-register the 8 canonical jobs.

## 3. The 15 Sectors (inherited from legacy SECTOR_MAP)
Ngân hàng, Chứng khoán, Bất động sản, Thép & VLXD, Bán lẻ, Thực phẩm, Dầu khí, Điện & NL, Công nghệ, Hàng không & Logistics, Bảo hiểm, Hóa chất & Phân bón, Dệt may, Cao su & Nhựa, Thủy sản.

Each sector defined by a **proxy basket of top 5 constituents by market cap**, used only to compute sector aggregates. Raw constituent OHLCV is fetched transiently and discarded after aggregation (rolling 60-day window retained).

## 4. Money-Flow Metrics per Sector per Interval
Net Dollar Flow, Up/Down Volume Ratio, **Foreign Net Buy** (vnstock foreign flow — killer VN signal), Breadth (% above SMA20/SMA50), Relative Strength vs VNINDEX (5/20/60d), ATR% (sector aggregate), Cross-sector correlation (rolling 20d). Shared macro anchors: VNINDEX, USD/VND, Brent, US10Y, Gold.

Record-count impact vs legacy: **~98% reduction** (15 sectors × ~12 features vs 170 symbols × 40 features).

## 5. New Database Schema
- `sectors (sector_code PK, name, description)`
- `sector_constituents (sector_code FK, symbol, weight, active)` — reference only
- `sector_flow_ts (sector_code, time, net_dollar_flow, up_vol, down_vol, foreign_net, breadth_sma20, breadth_sma50, rs_vnindex_5d, rs_vnindex_20d, atr_pct, UQ(sector_code,time))`
- `sector_flow_daily` — daily rollups
- `macro_anchors (time, vnindex, usdvnd, brent, us10y, gold)`
- `sector_regime (date, regime_label, confidence)`
- `sector_signals (date, sector_code, score, rank, action, model_run_id)`
- Retained: `model_runs`, `backtest_runs`, `dashboard_layouts`.

## 6. New Service Layer
`sector_ingest_service`, `macro_service`, `flow_feature_service`, `rotation_model_service`, `sector_signal_service`, `picks_universe_service` (2026-04-18), `trader_agent` (2026-04-18). Retrofit: `backtest_service`, `risk_service`. Delete: `trade_service`, symbol parts of `ml_service` and `data_service`, legacy `openclaw/` agent (retired 2026-04-18, replaced by `trader_agent`).

## 7. New API Routers
`/api/sectors/flow`, `/api/sectors/ranking`, `/api/sectors/regime`, `/api/sectors/backtest`, `/api/sectors/risk`, retrofitted `/api/agent/briefing`. Remove: `/api/stocks/*`, `/api/trade/*`, symbol `/api/ml/*`.

## 8. Scheduled Jobs (Asia/Ho_Chi_Minh)
| Job | Cron | Purpose |
|---|---|---|
| sector_intraday_flow | */15 9-15 * * 1-5 | Proxy OHLCV + foreign flow → `sector_flow_ts` |
| sector_eod_rollup | 0 16 * * 1-5 | Daily rollup |
| macro_ingest | 0 * * * * | Macro anchors hourly |
| regime_classify | 30 16 * * 1-5 | HMM regime label |
| rotation_train | 0 2 * * * | Nightly LightGBM ranker retrain |
| rotation_predict | 45 16 * * 1-5 | Next-day sector ranking |
| sector_signal_publish | 0 17 * * 1-5 | Write signals + Gmail briefing |
| sector_risk_sentinel | */30 9-15 * * 1-5 | Stop-loss alerts on held sectors |

## 9. Data Sources
Primary: **vnstock** (proxy OHLCV, foreign flow, VNINDEX). Macro: FRED (US10Y), stooq (Brent, Gold), SBV/exchangerate.host (USD/VND). Optional: HOSE order-book deltas, ETFs FUEVFVND/E1VFVND.

## 10. Models
- **Regime classifier:** Gaussian HMM on macro + VNINDEX returns → {risk_on, risk_off, rotation, chop}
- **Sector ranker:** LightGBM lambdarank, target = forward 5d sector return
- **Persistence filter:** flow sign held ≥3 sessions
- **Sizing:** vol-targeted, max 3 long / 2 short

## 11. Backtest Targets
Benchmark VNINDEX B&H. Sharpe > 1.0, MaxDD < 15%, top-rank hit-rate > 55%.

## 12. Frontend
Replace 9 symbol pages with 5 sector pages: Flow Dashboard, Rotation Ranking, Regime Monitor, Sector Backtest, Risk.

> **2026-08-23 — reconciled with what actually shipped.** Four of the five
> pages above (Ranking, Regime, Backtest, Risk) had been *built and working*
> for months but had no `<Route>`, so the only way to reach them was to edit
> the source. They are wired now, lazily, under a second nav group
> ("Ra quyết định"), giving nine nav items.
>
> Twelve page components were deleted rather than wired: nine were one-line
> stubs, and `FlowPage`, `BriefingPage` and `AccumulationPage` were superseded
> (by FlowMonitorPage, by the in-page trader agent, and by StealthWatchPage
> respectively — and `/accumulation` would have rendered permanently empty
> since `accumulation_age` is zero on every row).
>
> **Later the same day those nine merged back to five — see §22.9 for the
> current nav.** The name `FlowPage.tsx` was reused for the merged
> Money Flow Monitor + Sector Detail page; it is not the deleted one.

## 13. Migration Order (execution sequence)
1. Freeze legacy tables with `_legacy_` prefix.
2. Migration 8: add new schema.
3. Build `sector_ingest_service` + `macro_service` + 2 schedulers.
4. Backfill 5y `sector_flow_daily` from vnstock.
5. Build `flow_feature_service` + `rotation_model_service` + train v0.
6. Retrofit backtest + risk services.
7. Rewrite briefing + Gmail template. **[2026-04-18 SUPERSEDED]** OpenClaw removed; replaced by in-process `services.trader_agent.TraderAgent` via `claude_agent_sdk` (see `specs/trader_agent.md`).
8. Replace frontend pages.
8.5. **Introduce `PicksUniverseService`** — consolidate per-ticker picks under one dynamic HOSE universe; retire `_legacy_stock_*` reads from the report generator (then SecV3, now `generate_report.py`) and `api/routers/insight.py` (see `specs/picks_universe.md`, 2026-04-17).
9. Shadow-run 2 weeks.
10. Drop `_legacy_` tables + delete symbol code.

## 14. Decided Defaults (chosen in absence of user override)
- Proxy basket size: **top 5 by market cap** per sector.
- Backfill depth: **5 years** (or max vnstock available).
- Execution universe: **top-3 constituents basket** (ETF liquidity in VN is thin).
- OpenClaw agent Trung: **retired 2026-04-18** — replaced by `services.trader_agent.TraderAgent` ("Minh"). **2026-07-20: default provider is now `local`** — plain HTTP to an OpenAI-compatible `/chat/completions` endpoint, no `claude_agent_sdk`. **2026-08-23: `local` names the transport, not where the model runs.** It points at 9Router (`LOCAL_BASE_URL` default `http://localhost:20128/v1`, dashboard `http://localhost:20128/dashboard`), a local router fronting hosted Claude models; `LOCAL_MODEL` default `claude-opus-5`. The previous Ollama defaults (`:11434`, `qwen3:8b`) were dropped — Ollama was never running on this box, so the agent had been failing on every run. Alternatives via `AGENT_PROVIDER`: `glm` (Z.ai Anthropic-compatible endpoint, model `glm-5.2`, needs `GLM_API_KEY`) or `claude` (Claude Code subscription). The SDK is imported lazily, so a local-only install does not need it. Invoked from `POST /api/insight/refresh`. Output rendered inline on the Daily Insight page.
- Frontend: **feature flag** during shadow run, hard-cut after.

Change any of these by editing this file and logging in `MODIFICATION_LOG.md`.

## 15. Modification Protocol
Every code or schema change must:
1. Append entry in `MODIFICATION_LOG.md` with date, files touched, reason, summary.
2. Update `ARCHITECTURE.md` if layer/contract/schema changes.
3. Update this `CLAUDE.md` if strategy/defaults change.

## 16. Early Money-Flow Detection (Tom's Edge Doctrine) — APPROVED 2026-04-09

> **Thesis:** In the VN market, public news/analyst coverage lags real money movement by **~1 month**. By the time a sector is "on the news", smart money has already accumulated. The system's job is therefore **not** to predict next-day return — it is to **detect stealth accumulation 2-4 weeks before the breakout**, so Tom can buy "at the root" (gốc) or at worst "high on the branch" (cành cao), never at the canopy (ngọn).

### 16.1 What "early" means, formally
> **⚠ Doctrine vs. code (2026-08-22).** The thresholds below are the approved
> doctrine. `analysis/stealth.py` currently ships **N=3** and **bottom 60%**,
> and drops condition 2 entirely whenever `foreign_net` is all-zero — which it
> is across the whole history (see §20, P0-5). The gate can therefore run on 3
> conditions, not 5. This was never logged per §15. **Decide which numbers are
> real and make both places agree** — see `docs/reviews/CODE_REVIEW_2026-08-22.md` P1-1.

A sector is in **stealth accumulation** when ALL of these hold simultaneously for ≥ N sessions (default N=5):
1. **Rolling 20d net dollar flow z-score > +1.0** (flow regime shift vs own history)
2. **Foreign net buy positive on ≥ 60% of sessions in the last 20d** (smart-money persistence)
3. **Breadth SMA20 rising** (diffusion — more constituents joining, not one whale)
4. **ATR% below 20d median** (quiet tape — no euphoria yet)
5. **Price return (close_idx) in bottom 40% of its 60d range** (still cheap, not extended)

When all five flip, emit a new `ACCUMULATE` action — this is the "gốc" (root) buy. The existing `BUY` action stays but is downgraded to "cành cao" (late-cycle) confirmation.

### 16.2 New leading features (add to FEATURE_COLS)
- `flow_z20` — 20d rolling z-score of `net_dollar_flow` per sector
- `flow_z60` — 60d version (slower, macro flow regime)
- `foreign_streak` — number of consecutive sessions of positive `foreign_net` (cap 20)
- `foreign_hit_20d` — fraction of last 20 sessions with `foreign_net > 0`
- `stealth_score` — composite: `(flow_z20) × (breadth_sma20 rising) × (1 / (1 + atr_rank_20d))`
- `flow_price_divergence` — `flow_z20 − return_20d_zscore` (positive = flow leading price)
- `flow_leadtime_proxy` — lag (in days) between flow z crossing +1 and price return turning positive; stored per crossing event
- `accumulation_age` — days since the 5 conditions in §16.1 first flipped on (0 if not active)

### 16.3 New signal actions
Extend `SectorSignal.action` enum:
- `ACCUMULATE` — stealth phase (§16.1). Position size = **full target weight**, early entry, widest stop.
- `BUY` — momentum confirmation (flow AND price both rising). Smaller size-add, tighter stop.
- `TRIM` — price extended (return_20d > 90th pctile) while flow_z20 rolling over. Cut half.
- `SELL` — flow z20 flips negative AND price still high. Full exit.
- `HOLD` — default.

### 16.4 New target / training change
- **Replace** `fwd_5d_sector_return` with `fwd_20d_sector_return` as the primary ranker target. 5d rewards noise chasing; 20d rewards real rotations.
- Add a **second ranker head**: classifier for "did this sector enter breakout within next 15 sessions?" (`1` if `fwd_15d_max_return > 2 × atr_pct`). Two-stage: ranker sorts by expected return, classifier filters noise.
- Training window: rolling 2y, monthly retrain (not nightly — flow regimes change slowly).

### 16.5 New scheduler jobs
| Job | Cron | Purpose |
|---|---|---|
| stealth_scanner | 0 17 * * 1-5 | Evaluate §16.1 conditions per sector, emit `ACCUMULATE` signals when they flip. |
| lead_time_audit | 0 3 * * 1 | Weekly: for each past breakout, measure how many days earlier `flow_z20` crossed +1; store in `flow_leadtime_proxy`. Use as model diagnostic. |
| flow_regime_report | 30 17 * * 5 | Friday EOD: export a "sector flow heatmap" (z20 grid) to Gmail via `trader_agent` + `generate_report.py`. |

### 16.6 Backtest extension
Add an **entry-timing attribution** report to `SectorBacktestService`:
- For each closed trade, compute `entry_lag_days` = days between `ACCUMULATE` trigger and eventual price breakout.
- Metric: **median entry lag** (target: ≥ 10 trading days — meaning Tom bought at least 2 weeks before the move).
- Metric: **"root capture ratio"** — (price at entry) / (price at trade peak). Target: ≤ 0.85 (you bought in the bottom 15% of the move).

### 16.7 New database fields
- `sector_flow_daily`: add `flow_z20`, `flow_z60`, `foreign_streak`, `foreign_hit_20d`, `stealth_score`, `flow_price_divergence`.
- New table `sector_accumulation_events (id, sector_code, start_date, end_date, peak_return_pct, lead_days_to_price, resolved)` — one row per stealth event, closed when the sector either breaks out or the stealth conditions invalidate.

### 16.8 Frontend surface
- **Flow Dashboard:** add a `flow_z20` column with a green halo when ≥ +1.0 for ≥ 5 sessions (visual stealth badge).
- **New page `/accumulation`:** live list of sectors currently in stealth phase, with `accumulation_age`, `stealth_score`, and the estimated `days_until_breakout` (historical median lead time).
- **Ranking page:** new `ACCUMULATE` badge (deeper green than BUY) with a "root/branch/canopy" label per sector.

### 16.9 Execution rules (risk-adjusted for early entry)
Because early entries mean wider stops and more time at risk:
- `ACCUMULATE` position: 1.5× normal vol-target, stop = 2.5 × ATR20 (wide).
- Maximum concurrent `ACCUMULATE` positions = 4 (vs 3 for BUY).
- If a sector spends > 30 sessions in stealth without breaking out, auto-exit with no loss/gain ("dry powder reclaimed").

### 16.10 Implementation order (append to §13)
11. Add §16.2 features to `flow_feature_service`, backfill over existing 2.2y panel.
12. Add `StealthDetector` in `analysis/stealth.py` implementing §16.1.
13. Add `ACCUMULATE` path + new sizing rules to `sector_signal_service` and `risk_service`.
14. Add `sector_accumulation_events` table + migration 9.
15. Switch ranker target to 20d + add classifier head in `models/rotation_ranker.py`.
16. Add three new scheduler jobs (§16.5).
17. Extend backtest metrics (§16.6) — validate against 2023-2025 VN rotations (bank rally Q4'23, steel run Q2'24, broker breakout Q1'25 as ground-truth cases).
18. Ship `/accumulation` frontend page + Flow Dashboard halo.

### 16.11 Success criterion
The system is considered successful on this axis if, in out-of-sample backtest across 2024-2026:
- **≥ 60% of `ACCUMULATE` signals** precede a price breakout by **≥ 10 trading days**.
- **Median root-capture ratio ≤ 0.85**.
- **False-positive rate ≤ 30%** (stealth signals that dissolve without a breakout).

Anything worse than this means the thesis is still lagging — go back to features.

## 18. Trader-Lens System Review — APPROVED 2026-04-09

> Reviewer stance: "if I had to trade this book tomorrow with my own money, what would break or bleed me?" Findings are grouped by severity. Items marked **[BLOCKER]** must ship before live paper-trade; **[EDGE]** items are alpha improvements; **[HYGIENE]** items are robustness.

### 18.1 Signal quality gaps
1. **[BLOCKER] Survivorship + constituent drift.** `sector_constituents` is a static top-5 by market cap. In VN, banks and brokers rotate in/out of the top-5 yearly (e.g., VIX, SHS replaced names in 2024). A frozen basket back-paints history. **Fix:** rebuild the basket monthly from point-in-time market cap and stamp `constituent_asof` on every `sector_flow_ts` row. Backtest MUST read the basket valid on each historical date.
2. **[BLOCKER] Foreign-flow noise on ETF rebalance days.** FUEVFVND and E1VFVND monthly rebalances spike `foreign_net` on names like HPG, VHM, VIC without reflecting real directional conviction. **Fix:** add an `etf_rebalance_mask` feature; zero out `foreign_net` contribution for constituents on known index review windows (HOSE quarterly, ETF monthly). Expose as `foreign_net_clean`.
3. **[EDGE] Flow z-score needs regime conditioning.** A +1.0 z20 in `risk_off` means something very different than in `risk_on`. **Fix:** compute `flow_z20_by_regime` — z-score relative to the distribution in the same HMM regime label. Stealth trigger §16.1 should use the regime-conditioned z.
4. **[EDGE] No put/call or derivatives proxy.** VN30F1M open interest and basis (futures − spot) lead the cash index by 1-3 sessions on turns. **Fix:** add `vn30f1m_basis`, `vn30f1m_oi_chg_5d` to macro_anchors; feed into ranker. Cheap win — vnstock exposes it.
5. **[EDGE] Missing margin-debt proxy.** SSI/VND/HCM publish monthly margin balances — leading indicator for broker sector and for systemic leverage. **Fix:** add `broker_margin_total_mom` as a macro anchor (manual CSV refresh monthly until scraped).
6. **[EDGE] Breadth is computed on the 5-stock basket — too narrow to be "breadth".** Breadth SMA20/50 of 5 names is almost binary. **Fix:** compute breadth on the *full sector population* (all listed tickers mapped to sector), while keeping flow on the weighted top-5 basket. Two different tools.

### 18.2 Execution & risk realism
7. **[BLOCKER] T+2.5 settlement not modeled.** VN HOSE is T+2 cash, ~T+2.5 effective. Backtest must lock capital for 2-3 sessions after a buy. Current `SectorBacktestService` assumes instantaneous recycling → overstated Sharpe. **Fix:** add `settlement_lag=2` to the backtest cash engine.
8. **[BLOCKER] No foreign ownership room (FOL) check.** Banks, retail, airports routinely hit FOL and become un-buyable by foreigners — distorts `foreign_net` (it goes to zero not because of conviction but because of cap). **Fix:** pull `foreign_room_pct` per constituent; if median room < 3%, downweight `foreign_net` signal to 0.5× for that sector.
9. **[BLOCKER] Slippage + price-band realism.** VN has ±7% daily price bands (HOSE), ±10% (HNX), ±15% (UPCoM). In strong rotations, sectors gap to ceiling with no fills. **Fix:** backtest must (a) add a `ceiling_floor_hit` flag, (b) skip fills when basket median touched ±7% of prior close, (c) apply slippage = max(0.3%, 0.5 × ATR%). No slippage = fantasy Sharpe.
10. **[BLOCKER] Tax + fee line missing.** VN: 0.1% sell tax on proceeds, 0.15–0.35% broker fee round-trip. On a 20d holding period with 60%+ turnover, this is ~60-80 bps/trade of drag. **Fix:** hardcode `fee_bps=15` per side + `sell_tax_bps=10` in backtest config, expose in risk service too.
11. **[EDGE] Vol-targeting uses sector ATR — should use portfolio vol.** Sizing each position on its own ATR ignores cross-sector correlation (banks + brokers + realty move together in VN). **Fix:** size against portfolio marginal contribution to vol using the rolling 20d correlation matrix you already compute.
12. **[EDGE] Max 3 long / 2 short cap is arbitrary.** 15 sectors × high pairwise correlation → effective independent bets ≈ 3-4. Shorting in VN cash market is impossible (only VN30 futures). **Fix:** either restrict shorts to "reduce long" (cash flat) or model shorts exclusively through VN30F1M hedging. Delete the "2 short" concept from cash leg.

### 18.3 Model & validation
13. **[BLOCKER] No walk-forward with purged/embargoed folds.** Standard CV leaks across 5-20d forward targets. **Fix:** adopt López de Prado purged k-fold with embargo = max(target horizon) + 2 on ranker training.
14. **[EDGE] Single 20d target loses nuance.** Add an ensemble target: weighted blend of `fwd_10d` (0.4) + `fwd_20d` (0.4) + `fwd_40d` (0.2). Prevents the model from overfitting a single horizon.
15. **[EDGE] Stealth §16.1 uses fixed thresholds — should be sector-specific quantiles.** Banks normally run low ATR%; energy is chronically volatile. A global "ATR% < 20d median" is unfair across sectors. **Fix:** every §16.1 cut is evaluated against the **sector's own 2y empirical quantile**, not a cross-sector number.
16. **[HYGIENE] No model drift monitor.** Ranker may silently degrade. **Fix:** nightly job logs ranker top-3 hit-rate on the last 20 sessions; Gmail alert if < baseline − 1σ for 5 consecutive days.

### 18.4 Data & ops
17. **[BLOCKER] Single-source vnstock risk.** If vnstock breaks for a day, the whole pipeline fails silently (ingest just catches). **Fix:** add a secondary HOSE scraper (cafef or ssi-iBoard) as fallback; circuit-breaker + loud Gmail alert on 2 consecutive miss.
18. **[HYGIENE] SQLite for intraday 15m flow will contend.** 15 sectors × 26 intraday bars × 252 days ≈ 100k/yr — fine. But WAL on a network mount is fragile. **Fix:** document that DB must live on a local disk; add a startup check that rejects network paths.
19. **[HYGIENE] No "as of" timestamp discipline.** A flow row should always carry `source_ts` (when the data was observed) + `ingested_ts`. Currently only one timestamp. Required for proper point-in-time backtesting. **Fix:** add `source_ts` column to `sector_flow_ts`.
20. **[HYGIENE] No kill-switch.** If risk sentinel fires repeatedly, there is no global "pause all new ACCUMULATE entries" flag. **Fix:** add `config.trading_halt` bool read at the top of `sector_signal_service.publish()`.

### 18.5 Stealth doctrine sharpening (§16 delta)
21. **[EDGE] "Foreign net ≥ 60% of last 20d" is too coarse.** A single huge block trade on day 1 can satisfy the hit-rate while flow dies for 19 days. **Fix:** require BOTH `foreign_hit_20d ≥ 0.6` AND `foreign_net_z20 ≥ +0.5`. Two independent checks.
22. **[EDGE] Add a "distribution guard" to kill stealth early.** If during stealth window any single session sees `up_vol / down_vol < 0.5` AND `foreign_net < 0`, invalidate the event (smart money is leaving). Currently stealth only resolves on price breakout or 30-day timeout — too slow.
23. **[EDGE] Track "institutional mornings" signal.** VN institutions trade disproportionately in the 09:15–10:30 window; retail dominates afternoons. Intraday 15m flow should compute `morning_share = morning_flow / daily_flow`. Rising `morning_share` during accumulation = high-conviction institutional buying. Add to `stealth_score`.
24. **[EDGE] Lead-time audit must be regime-stratified.** Average lead-time is meaningless across bull/bear. `lead_time_audit` job must bucket by HMM regime on the event start date.

### 18.6 Priority queue (append to §13 + §16.10)
Ship order, blockers first:
- P0: §18.1/1–2, §18.2/7–10, §18.3/13, §18.4/17 — before any live paper trade.
  > **2026-08-23:** §18.2/7, 9, 10 are **closed in the backtest engine** — T+2,
  > slippage, fee, sell tax and the ±7% band are modelled and now reported on
  > every run (§23). They stay open in `risk_service`, which sizes positions
  > with no cost model. §18.3/13 closed 2026-08-22 (§20.2 P0-6).
- P1: §18.1/3–6, §18.2/11–12, §18.3/14–15, §18.5/21–22 — before shadow-run metrics matter.
- P2: remaining HYGIENE + EDGE.

### 18.7 Success re-definition
Current §16.11 targets are necessary but not sufficient. Add:
- **Net-of-cost Sharpe ≥ 0.8** (after fees, taxes, slippage, T+2 lag, price-band misses).
- **Max adverse excursion on ACCUMULATE entries ≤ 6%** — if early entries routinely bleed more than that before working, the "root" claim is false.
- **Decile monotonicity** of the ranker: mean forward 20d return must be monotone across score deciles on out-of-sample data. Non-monotone = model is guessing.

### 18.8 Doctrine
Any future change MUST (a) log a `MODIFICATION_LOG.md` entry referencing the §18 item number it resolves, and (b) update the relevant spec file under `specs/`. Closing a §18 item requires evidence (backtest diff, unit test, or data proof) — not just code.

## 19. Testing

As of 2026-04-23:

| Suite | Count | Command |
|---|---|---|
| Backend (pytest) | 193 | `python -m pytest tests/` |
| Frontend (vitest) | 13 | `cd frontend && npm test` |
| **Total** | **206** | — |

> 2026-08-23 (late, 5): +11 in `tests/test_report_runner.py` — the "Gửi báo cáo
> ngay" button. One test carries the feature:
> `test_second_click_does_not_start_a_second_run` — two clicks must send one
> email, and the button being disabled is cosmetic, the backend is the guard.
> The rest pin argv construction (`--no-email`, the date), rejection of a
> malformed `report_date` **before** anything runs, and that a timeout lands in
> the status instead of killing the daemon thread silently. No subprocess is
> spawned: `send_report(runner=…)` takes the runner as a parameter for this.

> 2026-08-23 (late, 4): +13 in `tests/test_backtest_controls.py` — the backtest
> controls the UI can now reach. Two of them are the interesting ones:
> `test_flow_z_is_not_the_same_strategy_as_flow_raw` (a +2.5σ small sector must
> be reachable by `flow_z` and unreachable by `flow_raw`) and
> `test_cross_sectional_z_preserves_raw_order`, which pins the *proof* that the
> old cross-sectional z was an order-preserving affine map. The rest guard the
> benchmark curve, cost-override clamping (a negative fee must not pay the
> trader), the `Literal` strategy validation (422 on a typo, which used to fall
> through to `flow_raw`) and the `trade_log` row shape the TS type claims.

> 2026-08-23 (late): +13 in `tests/test_trading_state.py` — the operator store
> behind the kill-switch, the position book and the watchlist. The guards that
> matter: a corrupt file must not take the API down, the `TRADING_HALT` env
> override must not be clearable from a browser, marking the same pick twice
> must update rather than duplicate, and — the point of the whole feature — a
> flag set from the browser must reach `SectorSignalService.publish()` and make
> it emit all-HOLD.

> 2026-08-23: +6 in `tests/test_picks_universe_service.py` — the disk-snapshot
> round-trip (identity between `by_sector` and `tickers` preserved), cold-cache
> load from disk, the stale-vs-latest-signal-date flag, and the two degrade
> paths (corrupt file, missing file) that must return `None` rather than raise.
> An empty build is not persisted.

> 2026-08-22: +28 in `tests/test_review_20260822.py`, one guard per finding in
> `docs/reviews/CODE_REVIEW_2026-08-22.md`. The 105 figure above also counted ~9 one-line
> placeholder files under `tests/test_api/`, `tests/test_services/` and
> `tests/test_database/` that contain only "Legacy test removed in sector
> redesign" — real backend coverage before this review was ~101.

Backend modules covered:
- `config.py`, `database/models.py` schema (21 pre-existing).
- `services/picks_scoring.py` — 20 tests (NVL-style regression guard, SWING/TPLUS profiles, is_valid_long_pick parametric matrix).
- `services/picks_universe_service.py` — 14 tests (classification priority, cache lifecycle, degraded-mode fallback). vnstock calls mocked.
- `services/trader_agent.py` — 23 tests (JSON parse variants incl. `<think>` stripping, prompt trimming, cache invalidation, provider routing for local/glm/claude, missing-key guard, local connect-error message, timeout guard). No live LLM call — the local transport is faked at `httpx.AsyncClient`.
- `services/insight_refresh.py` — 5 tests (happy path, idempotent start while running, error propagation, stale run_id lookup, worker-thread progress plumbing). Uses an injected fake pipeline; no KBS / Claude / DB.
- `api/routers/insight.py` refresh endpoints — 3 tests via FastAPI `TestClient` (POST returns run_id; polling completes with payload; second click while running returns same run_id + already_running).
- `services/unified_picks.py` — 10 tests (NEW 2026-04-23). Anchors the SecV5 union-merge rule: consensus sort to top with `source=BOTH`; empty ranker → fallback to pure DAILY_INSIGHT (regression guard for the SecV4 silent-ranker bug); input lists not mutated; extra fields flow through; missing-score sort tiebreaker. Pure; no DB / vnstock / Claude dependencies.

Frontend modules covered:
- `pages/DailyInsightPage.tsx` — `fmtNum`, `fmtPct`, `AgentReport`, `PickGroup`, `PickCard` (valid + fallback + news toggle + SELL variant).

Test runners:
- Backend: pytest 9.x, anyio plugin. No network access required (mocked).
- Frontend: vitest 4.x + @testing-library/react + jsdom + @testing-library/jest-dom.

Live integration (not in pytest): `POST /api/insight/refresh` — exercises vnstock KBS + Claude Agent SDK end-to-end; run manually after meaningful changes to those paths. Since 2026-04-20 this endpoint is async: it returns a `run_id` immediately and the UI polls `GET /api/insight/refresh/status` for stage + progress. See `specs/daily-insight.md` §4.5 for the full contract.



## 20. Code Review — 2026-08-22

Full findings: **`docs/reviews/CODE_REVIEW_2026-08-22.md`** (22 findings: 6 P0, 6 P1, 4 P2, 6 P3).

### 20.1 The central defect

One causal chain ran through most of the P0s and started at one table,
`sector_flow_daily`. The 16:00 EOD job wrote rows **without** `close_idx`. The
only ingest path that writes `close_idx` (`services/fast_ingest.py`, reachable
solely from `POST /api/flow/ingest`) skipped any date that already had a row —
so the scheduler claimed each date first and permanently locked it in a
price-less state. `scripts/backfill_close_idx.py`, `scripts/fix_close_idx.py`
and the `STEALTH_SYNTHETIC_CLOSE` flag all exist only to paper over this.

Because `close_idx` feeds the ML target, stealth condition 5 and the entire
backtest P&L, every number the system surfaced rested on an untrustworthy
daily table.

### 20.2 Fixed in this pass

| Id | Fix | Files |
|---|---|---|
| P0-1 | `rollup_to_daily()` derives each row's date from the bar's own timestamp and refuses to stamp a stale bar as a new session | `services/sector_ingest_service.py` |
| P0-2 | The scheduled path now carries `close_idx` + `return_1d` through; `fast_ingest` upserts instead of skipping, so it can repair damaged dates | `sector_ingest_service.py`, `fast_ingest.py`, migration 11 |
| P0-3 | `SectorAggregate.basket_return` — the split-safe weighted mean of constituent returns. `close_idx` remains a raw price sum and must not be used for returns | `analysis/flow_aggregation.py` |
| P0-4 | Backtest replays published `sector_signals` by default (`strategy="signals"`), with `flow_z` and legacy `flow_raw` baselines for comparison; benchmark is VNINDEX per §11, labelled when it falls back. **Half-true until 2026-08-23** — see §23 | `services/backtest_service.py` |
| P0-6 | Purged/embargoed CV — embargo = horizon + 2 sessions (§18.3/13, was BLOCKER). Metrics replaced with `top1_excess_hit` (vs. median sector), `decile_monotonic` (§18.7) and `ndcg_at_3` | `models/rotation_ranker.py` |
| P1-2 | The mean-flow fallback is flagged `is_degraded` and announced loudly instead of shipping as "ranker-gated" | `rotation_ranker.py`, `sector_signal_service.py` |
| P1-5 | §16.9 ACCUMULATE cap (4) and 30-session auto-exit, §18.4/20 `TRADING_HALT` kill-switch, and `ALLOW_SHORT_SIGNALS` to retire the cash-leg short per §18.2/12 | `config.py`, `services/sector_signal_service.py` |
| P1-5b | **2026-08-23** — the kill-switch stops being env-only. `publish()` ORs `TRADING_HALT` with a runtime flag toggled from `/positions?tab=risk`, read once before the loop so a mid-run toggle cannot split a batch. The env var remains a hard override a browser cannot clear | `services/trading_state.py`, `api/routers/state.py`, `sector_signal_service.py` |
| P1-6 | `utils/clock.py` — one market-local definition of "today". `config.TIMEZONE` was declared and used nowhere | new module + call sites |
| P2-1 | `require_api_key` is wired to every router behind `API_REQUIRE_KEY`; the slowapi limiter is finally attached to the app; the inert `"https://*.ngrok-free.app"` CORS entries are gone | `api/main.py`, `config.py` |
| P3-1 | `AGENTS.md` reduced to a pointer — one source of truth again | `AGENTS.md` |
| P3-3 | `.env.example` regenerated from `config.py` | `.env.example` |
| P3-4 | `rollup_to_daily` no longer loads the whole `sector_flow_ts` table; `_stealth_sectors()` N+1 collapsed to one query | ingest + signal services |
| P3-5 | ruff config in `pyproject.toml`; 666 findings → 30, all of them real | `pyproject.toml` + call sites |

**Defaults chosen to preserve live behaviour:** `API_REQUIRE_KEY=0`,
`ALLOW_SHORT_SIGNALS=1`, `TRADING_HALT=0`. Nothing in the daily email changes
until you flip these. `MAX_ACCUMULATE_SECTORS=4` and the 30-session release
DO change behaviour — they implement §16.9, which was never enforced.

### 20.3 Still open — needs a decision, not just code

| Id | Question |
|---|---|
| P0-5 | `foreign_net` is **zero across the entire history** — `backfill_sector` passes an empty map and `price_board` only exposes today. The "killer VN signal" (§4) has never contributed anything, and three `FEATURE_COLS` entries are constant. Source a historical series (§18.4/17 proposes CafeF/SSI), or drop the features and amend the doctrine. |
| P1-1 | Reconcile §16.1's thresholds with what `analysis/stealth.py` ships. |
| P1-3 | Breadth over 5 names takes 6 discrete values (§18.1/6, still open). |
| P1-4 | Regime labels are back-painted — Viterbi re-decodes the whole history each run, so yesterday's label can change. Use the filtered posterior for the last bar. |
| P2-2 | Two rate-limit buckets in one process: `utils/vnstock_gate` and `picks_universe_service._kbs_throttle`. `/insight/refresh` takes no `job_lock` at all, so a UI refresh overlapping the intraday job runs at 2× the KBS ceiling. |
| P2-3 | The "intraday" job fetches `interval="1D"` and re-downloads 120 days every 15 minutes (~3,750 calls/day against an 18/min gate). Either fetch real 15m bars or admit it is an EOD pipeline and fix §4/§8. |
| P3-2 | `generate_report.py` is 1,629 module-level lines with zero tests, and it is the one output read every day. Extract the decision layer. |

### 20.4 Doctrine drift to close

`docs/reviews/CODE_REVIEW_2026-08-22.md` carries a "plan vs. code" table of ten places where
this document describes a system different from the one running. Per §18.8,
each needs either a code change or a doctrine amendment — not silence.


## 21. Naming — no version suffixes (2026-08-22)

Tom's directive: version numbers do not belong in names. A file called
`generate_secv5.py` tells you there were four before it and nothing about what
it does, and it forces a rename every time it changes.

| was | now |
|---|---|
| `generate_secv5.py` | `generate_report.py` |
| `report/report_template_secv5.html` | `report/report_template.html` |
| `report/secv5_<date>.{html,pdf}` | `report/daily_report_<date>.{html,pdf}` |
| `scripts/register_secv5_task.ps1` | `scripts/register_report_task.ps1` |
| `scripts/pause_secv3_secv4_email.ps1` | `scripts/pause_legacy_email_task.ps1` |
| model_name `rotation_ranker_v0` | `rotation_ranker` |
| `models/saved/rotation_ranker_v0.pkl` | `rotation_ranker.pkl` |
| model_version `hmm_v0` | `hmm` |
| env `SECV3_DB_PATH` | `REPORT_DB_PATH` (old name still honoured) |

Dates are NOT versions and were left alone: `MODIFICATION_LOG.md`,
`docs/reviews/CODE_REVIEW_2026-08-22.md` and the dated post-mortems keep their names,
because a dated record is supposed to say when it was written.

**Consequence to know about:** renaming `model_name` orphans the 74 existing
`model_runs` rows from the active-model lookup. That is intentional -- every
one of them was a degraded mean-flow fallback (see section 20 / P0-8), so
none was worth keeping. The next `--train` writes the first real one.


## 22. Frontend flow audit — 2026-08-23

Every route and every endpoint behind it was exercised against the running
server. Full numbers in the **Sector Flow Bench** artifact.

### 22.1 Flows that render nothing
These return HTTP 200 with an empty collection, so the page draws an empty
state. They are not broken code — they are correct code with no data:

| surface | endpoint | why it is empty |
|---|---|---|
| Stealth Watch | `/api/stealth/active`, `/api/stealth/history` | `accumulation_age` is 0 on all 13k rows; §16 has never fired |
| Rotation Map | `/api/rotation/pairs` | ~~no pair clears the 1.5 threshold~~ — **wrong, corrected below** |
| Flow Pulse | `/api/pulse/exposure` | ~~no positions are tracked~~ — **wrong, corrected below** |

Fixing Stealth Watch means fixing §16 (see §20.3), not the UI. The other two
rows were **misdiagnosed**; both were fixed on 2026-08-23:

- **Rotation Map** was not threshold-limited, it was structurally empty.
  `rotation.py` builds `pairs` as the cartesian product of
  `delta < -threshold*sigma` × `delta > +threshold*sigma`, and a live probe
  returned 10 nodes **all on the target side**. The product is therefore empty
  at *every* threshold — lowering it widens both sets from the same one-sided
  `delta`. The page now reads `/api/sectors/handoff`, which computes the same
  thing correctly (`max(0, -Δz_A) * max(0, +Δz_B)`; the independent clip per
  side is what keeps both sides non-empty) and had 270 rows and no consumer.
  `/api/rotation/*` stays mounted, unread.
- **Flow Pulse** exposure was not "no positions" — `api/routers/pulse.py`
  returns a hardcoded `{"rows": []}` while the real implementation sits in
  `sectors_risk.py`. The client now calls `/api/sectors/risk/exposure`.

### 22.2 Client code pointing at deleted routes
`agentApi.briefing()` and `agentApi.stoplossAlerts()` called `/api/agent/*`,
which was removed from the backend on 2026-04-18 when OpenClaw was replaced by
`services.trader_agent`. Both returned 404 for four months. Removed, along with
`BriefingPage`, which was their only caller.

### 22.3 Performance
- `flowApi.series` and `flowApi.sector` hard-coded `lookback = 400` in the
  **client**, so lowering the backend default to 120 changed nothing until the
  client changed too. Now 120 both ends: **2.8 s / 1.0 MB → 1.3 s / 303 KB**.
  > **2026-08-23: this was only two-thirds true.** The client *default* and
  > `SectorDetailPage` were changed, but `FlowMonitorPage.tsx` passed an
  > explicit `400` that overrode the default, so the route users actually open
  > still shipped 1.0 MB. Fixed now — measured 1,000,870 B / 2.72 s →
  > 304,682 B / 1.61 s. The lesson: changing a default proves nothing until you
  > grep the call sites.
- Wiring the four pages eagerly took the main bundle from 372 kB to 732 kB,
  because `BacktestPage` imports recharts. They are `React.lazy` now: main
  bundle 376 kB, recharts in a 346 kB chunk that only loads when you open
  Backtest.

### 22.4 Dev server bound to every adapter
`vite.config.ts` had `host: true`, which binds 0.0.0.0 and advertises every
network adapter — including `172.20.16.1`, the Hyper-V vEthernet switch WSL and
Docker Desktop create, which nothing outside the machine can reach. Now
`host: 'localhost'`; use `npm run dev:lan` when you want it on the LAN. That is
also the safer default while `API_REQUIRE_KEY=0`: the Vite proxy fronts the
trading API, so putting the dev server on the LAN puts the API there too.

### 22.5 The frontend test suite was red, and §19 said it was green
8 of the 13 vitest tests failed with `TypeError: React.act is not a function`.
React 19.2 ships `act` only in its development build, and Vitest runs with
`NODE_ENV=test`, so Vite resolved React's production entry and
`@testing-library/react` fell back to the removed `react-dom/test-utils.act`.
Fixed in `vitest.config.ts` by asking the resolver for the `development`
condition. **13/13 pass now** — the count in §19 is finally true.

### 22.6 The homepage was empty after every restart — 2026-08-23
The defect the audit above missed, because it only shows up on a cold process.
`PicksUniverseService` kept its snapshot **only in memory**, so a backend
restart blanked Daily Insight until a human clicked Refresh. `/api/insight/daily`
deliberately does a cache-only `.peek()` (a cold `get_snapshot()` would hang the
endpoint for 2–10 minutes behind the 18 req/min KBS throttle), so the endpoint
was correct and the cache was the gap — it was the only stage of the daily
pipeline with no durable store. It now persists to
`data/snapshots/picks_universe.json` and reloads on a cold cache. The file is a
cache, not a source of truth: corrupt, missing or stale degrades to the existing
empty-state banner and never raises; a stale one is loaded anyway and flagged
through `freshness.errors`. See `MODIFICATION_LOG.md` 2026-08-23 (evening) A1.

### 22.7 Docs layout — 2026-08-23
Seven outdated documents were **deleted**, not archived (Tom's call: an archived
wrong doc is still a wrong doc someone will read). `README.md`'s email command
had been running a file deleted on 2026-06-18. What survives:

```
README.md · CLAUDE.md · ARCHITECTURE.md · MODIFICATION_LOG.md · AGENTS.md   ← root, entry points
specs/                  ← one topic per file, referenced from 5 .py docstrings; untouched
docs/reference/         ← ALGORITHM.md, GLOSSARY_VI.md
docs/reviews/           ← the dated reviews (§21: dated records keep their names)
```

**No Python file moved.** `scripts/jobs/*.bat` invoke `main.py` from the repo
root under Task Scheduler, and `MODIFICATION_LOG.md` 2026-07-19 already records
one path move that left shortcuts pointing at a dead directory.


### 22.8 One design system, one action vocabulary — 2026-08-23
The four "Ra quyết định" pages were wired on 2026-08-23 (§12) but had never
been through the redesign, so they still shipped raw Tailwind while the five
"Theo dõi" pages used the `@theme` tokens. They are on the tokens now — class
swaps only, no new design.

The bigger fix is vocabulary. Three pages spoke three alphabets, and none was
the five-state enum §16.3 defines. `frontend/src/lib/actions.tsx` is now the
single source, and it separates two things that were being conflated:

| component | means | source | states |
|---|---|---|---|
| `ActionBadge` | what to do with money | `sector_signal_service.py` (§16.3) | ACCUMULATE · BUY · TRIM · SELL · HOLD |
| `FlowBadge` | what the tape is doing | `api/routers/flow.py:176`, from `flow_z` alone | HOT · COOL · NEUTRAL |

`FlowBadge` is styled flatter on purpose: a HOT tape is an observation, not an
instruction, and it must never read like a BUY. **TRIM is rendered but never
emitted** — the signal service has no path to it, so §16.3 is still four states
in practice. That is a doctrine-vs-code gap of the same family as P1-1.

### 22.9 Nav merged 9 → 5 — 2026-08-23
Nine nav doors for 15 sectors was more navigation than data, and every merge
below removes a context switch rather than a page. Nothing was deleted: every
pre-merge path redirects, including `/flow/:code`.

| nav | contains | why together |
|---|---|---|
| Daily Insight | (unchanged) | the screen you open every morning |
| Dòng tiền | Money Flow Monitor + Sector Detail | clicking a sector used to leave the page and drop your interval, `flow_z_hot` and chart selection |
| Luân chuyển | Stealth Watch + Rotation Map | one question, two phases — §16.1 accumulation (early) vs. the handoff that already happened |
| Rủi ro & Vị thế | Risk + Flow Pulse | also removes the last way the two exposure panels of §22.1/A4 could disagree |
| Nghiên cứu | Xếp hạng + Regime + Backtest | none of the three is a daily job |

Tabs live in the URL (`?tab=`, `components/Tabs.tsx`) with `replace: true` —
a merged page must keep the deep links its old routes had, and switching tabs
must not stack history entries.

`SectorDetailPage` was the last page still on raw Tailwind (37 `slate-*` hits
plus 20 hardcoded SVG hexes); it was tokenised in the same pass, so §22.8's
claim now holds for the whole app.

Daily Insight also gained a sticky jump bar: the buy/sell list — the thing
people open the page for — sat below the gauge, the spectrum and Minh's memo,
about two laptop screens down.

Bundle: main **376.43 → 371.12 kB**. `PositionsPage` (12.7 kB) and
`ResearchPage` (1.05 kB) are lazy, and recharts stays in its own 346 kB chunk
that only loads when you select the Backtest tab.

### 22.10 Operator state — kill-switch, book, watchlist — 2026-08-23

Everything on every page was model output. The app knew what it thought and
nothing about what Tom did, which showed up in four places at once:

| symptom | cause |
|---|---|
| stopping the 17:00 publish meant editing `.env` and restarting | §18.4/20's kill-switch was an env var |
| "Vị thế đang mở" on the Risk page was not your book | `current_exposure()` equal-weights today's BUY/SELL signals — model suggestions wearing a book's name |
| the "Vốn 50-500tr" slider reset to 100tr on every F5 | it only split weights; nothing stored it |
| eight of nine routes never said how old the data was | `FlowMonitorPage` was the only page fetching `/flow/freshness` |

`services/trading_state.py` is one JSON file (`data/trading_state.json`,
gitignored) with four keys — halt, capital, positions, watchlist — behind
`/api/state/*`. **Not a table on purpose:** three keys do not justify migration
12, and the scheduler process has no HTTP client, so it must read the halt flag
directly off disk. If a second machine or a second trader ever appears this
becomes a table and the read path becomes a query; the API shape above it does
not have to change.

The halt has **two sources, OR'd**. `TRADING_HALT` stays a hard override a
browser cannot clear; the runtime flag is what the UI toggles. `halt_env` and
`halt_effective` are returned so that asymmetry is visible rather than
surprising — the toggle disables itself, with a title saying why, when the env
var is the one holding the halt. `publish()` reads the answer **once before the
loop**, so toggling mid-run cannot publish half a batch.

The banner is app-wide and un-dismissable. A halt you can only see on the page
where you set it is a halt you will forget about, and forgetting it means
trading picks the 17:00 job has already stopped publishing. Below it sits a
data-age bar on the same principle: quiet when fresh, warn-coloured with the
session gap when behind.

`lib/tradingState.ts` is a `useSyncExternalStore` module store, not Context —
Layout would otherwise own state it never reads, and one object does not justify
a state library. Marking a pick is idempotent on `(symbol, side)` and drops the
symbol from the watchlist: you cannot be watching something you have bought.

The book stores no exit price, so there is no P&L yet. That is the next thing to
add if performance attribution is wanted — it is a deliberate stop, not an
oversight.

## 23. Backtest controls — and `flow_z` was `flow_raw` in disguise — 2026-08-23

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

## 24. Filters, presets and the P1-1 price tag — 2026-08-23

### 24.1 One filter vocabulary
Every sector table drew all 15 rows in one fixed order. `lib/filters.tsx` is
now the single source for search, action filter, "chỉ ngành tôi đang nắm",
column sorting and CSV, used by Ranking and Money Flow Monitor.

State lives in the **URL**, not in component state (`?rk_act=BUY&rk_sort=score`,
`replace: true`, one prefix per table). A tuned view is a thing you send to
someone, and F5 must not clear it — the same reasoning as §22.9's tabs.

Two details that are load-bearing rather than incidental:
- **Filter, then sort.** The other order sorts rows you are about to discard.
- **CSV carries a UTF-8 BOM.** Without it Excel on a Vietnamese locale opens
  "Ngân hàng" as mojibake, which makes the export useless to its only user.

"Chỉ ngành tôi đang nắm" is answered entirely from the §22.10 store — the app
already knew the book, no page had ever asked it a question.

### 24.2 The stealth presets are an argument, not a convenience
**Chặt / Vừa / Rộng**, not tight/loose:

| preset | numbers | what it is |
|---|---|---|
| Chặt | N=5, đáy 40% | doctrine §16.1 |
| Vừa | N=3, đáy 60% | what `analysis/stealth.py` actually ships |
| Rộng | N=1, mọi ngưỡng hạ | a probe — "ngành nào gần đạt", not a buy list |

Switching between the first two prices the §20.3 P1-1 disagreement **in
sectors**, which is the only unit in which anyone will care enough to close it.
Selecting "Vừa" raises a warning naming both numbers and the section.

The conflict turns out to be **three-way**, not two: `api/routers/stealth.py`'s
own Query defaults (`min_sessions=5`, `close_pct_60d_max=0.4`) already match
doctrine. So the offline scanner that writes `accumulation_age` and the
endpoint this page reads are gated differently — the page can show a sector
that the scanner will never record.

### 24.3 Send the report without a terminal
`POST /api/state/report/send` runs `generate_report.py` as a **subprocess**.
Importing it would send mail as a side effect of the `import` statement, once
per process and never again, because it is 1,629 module-level lines driven by
`sys.argv` with no `main()` (§20.3 P3-2). A subprocess is the honest way to
call a script that is a script.

It sits under `/api/state/*` rather than a new router because it is an operator
action — the same category as the kill-switch and the position book.

The double-click guard is on the **backend** (`already_running`), not on the
disabled button. A disabled button is a hint; two emails is a fact.

### 24.4 Words on the screen
`lib/glossary.tsx` defines 13 column names behind a native `title`. The
definitions existed only in `CLAUDE.md` §16.2 and `docs/reference/GLOSSARY_VI.md`
— neither of which is open while you are reading the table.

`foreign_hit_20d`'s entry says out loud that `foreign_net` is zero across the
whole history (§20.3 P0-5). A tooltip that explains a column doing nothing,
without saying so, is worse than no tooltip.

### 24.5 Not done
- `Th` / `FilterBar` are on two tables. Risk, Stealth and Regime still have
  their own headers.
- Native `title`: no touch support, ~1s delay. Fine for a definition, not for
  a formula or a link.
- Report run history is in memory only. It survives no restart; the log file on
  disk is the durable record.
