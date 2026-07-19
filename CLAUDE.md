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
- **Per-ticker picks (2026-04-17 onward):** `generate_secv5.py` and `api/routers/insight.py` read per-ticker BUY/ACCUMULATE picks exclusively from `services.picks_universe_service.PicksUniverseService` (dynamic HOSE universe from vnstock Listing). They no longer read `_legacy_stocks`, `_legacy_stock_prices`, or `_legacy_stock_features`. These three tables stay in the DB during a 2-week shadow window then drop in migration 10.
- **Email report (2026-04-23 onward):** `generate_secv5.py` is the **sole** daily email generator. It unifies the picks surfaced in the Daily Insight page (`snapshot.top_buys`/`top_sells` — no ranker gate) with the ranker-gated BUY/ACCUMULATE picks into a single de-duped list, each entry tagged with its source (`BOTH` / `DAILY_INSIGHT` / `RANKER`). The HTML/PDF gains an Expert Trader Memo section at the top; the email body is plain text (buy symbols + reasons + Dashboard + news links). Default recipients: `tka2001@gmail.com, anhchitruong18@gmail.com, hill.nguyen.1373@gmail.com`. `scripts/jobs/job_sector_signal_publish.bat` calls `generate_secv5.py`.
- **SecV3/SecV4 deleted (2026-06-18):** `generate_secv3.py` and `generate_secv4.py` removed from the repo — they were carried only as manual rollback paths and had drifted from secv5 (duplicate-but-divergent helpers). secv5 is now the single source of truth for the daily report. If a stale Task Scheduler entry still invokes secv3/secv4, run `scripts/pause_secv3_secv4_email.ps1` (elevated PowerShell) to evict it.
- **SecV2 retired (2026-04-20):** `generate_secv2.py` + `run_secv2_daily.bat` deleted from the repo. The Windows 17:00 scheduled task that invoked them is obsolete — run `scripts/cleanup_scheduled_tasks.ps1` (elevated PowerShell) to unregister it and dedupe the SecV4 task.

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

## 13. Migration Order (execution sequence)
1. Freeze legacy tables with `_legacy_` prefix.
2. Migration 8: add new schema.
3. Build `sector_ingest_service` + `macro_service` + 2 schedulers.
4. Backfill 5y `sector_flow_daily` from vnstock.
5. Build `flow_feature_service` + `rotation_model_service` + train v0.
6. Retrofit backtest + risk services.
7. Rewrite briefing + Gmail template. **[2026-04-18 SUPERSEDED]** OpenClaw removed; replaced by in-process `services.trader_agent.TraderAgent` via `claude_agent_sdk` (see `specs/trader_agent.md`).
8. Replace frontend pages.
8.5. **Introduce `PicksUniverseService`** — consolidate per-ticker picks under one dynamic HOSE universe; retire `_legacy_stock_*` reads from `generate_secv3.py` and `api/routers/insight.py` (see `specs/picks_universe.md`, 2026-04-17).
9. Shadow-run 2 weeks.
10. Drop `_legacy_` tables + delete symbol code.

## 14. Decided Defaults (chosen in absence of user override)
- Proxy basket size: **top 5 by market cap** per sector.
- Backfill depth: **5 years** (or max vnstock available).
- Execution universe: **top-3 constituents basket** (ETF liquidity in VN is thin).
- OpenClaw agent Trung: **retired 2026-04-18** — replaced by `services.trader_agent.TraderAgent` ("Minh"), powered by `claude_agent_sdk` (uses your Claude Code subscription, no separate API key). Invoked from `POST /api/insight/refresh`. Output rendered inline on the Daily Insight page.
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
| flow_regime_report | 30 17 * * 5 | Friday EOD: export a "sector flow heatmap" (z20 grid) to Gmail via `trader_agent` + `generate_secv4`. |

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
| Backend (pytest) | 88 | `python -m pytest tests/` |
| Frontend (vitest) | 13 | `cd frontend && npm test` |
| **Total** | **101** | — |

Backend modules covered:
- `config.py`, `database/models.py` schema (21 pre-existing).
- `services/picks_scoring.py` — 20 tests (NVL-style regression guard, SWING/TPLUS profiles, is_valid_long_pick parametric matrix).
- `services/picks_universe_service.py` — 14 tests (classification priority, cache lifecycle, degraded-mode fallback). vnstock calls mocked.
- `services/trader_agent.py` — 15 tests (JSON parse variants, prompt trimming, cache invalidation). No live Claude SDK call.
- `services/insight_refresh.py` — 5 tests (happy path, idempotent start while running, error propagation, stale run_id lookup, worker-thread progress plumbing). Uses an injected fake pipeline; no KBS / Claude / DB.
- `api/routers/insight.py` refresh endpoints — 3 tests via FastAPI `TestClient` (POST returns run_id; polling completes with payload; second click while running returns same run_id + already_running).
- `services/unified_picks.py` — 10 tests (NEW 2026-04-23). Anchors the SecV5 union-merge rule: consensus sort to top with `source=BOTH`; empty ranker → fallback to pure DAILY_INSIGHT (regression guard for the SecV4 silent-ranker bug); input lists not mutated; extra fields flow through; missing-score sort tiebreaker. Pure; no DB / vnstock / Claude dependencies.

Frontend modules covered:
- `pages/DailyInsightPage.tsx` — `fmtNum`, `fmtPct`, `AgentReport`, `PickGroup`, `PickCard` (valid + fallback + news toggle + SELL variant).

Test runners:
- Backend: pytest 9.x, anyio plugin. No network access required (mocked).
- Frontend: vitest 4.x + @testing-library/react + jsdom + @testing-library/jest-dom.

Live integration (not in pytest): `POST /api/insight/refresh` — exercises vnstock KBS + Claude Agent SDK end-to-end; run manually after meaningful changes to those paths. Since 2026-04-20 this endpoint is async: it returns a `run_id` immediately and the UI polls `GET /api/insight/refresh/status` for stage + progress. See `specs/daily-insight.md` §4.5 for the full contract.

