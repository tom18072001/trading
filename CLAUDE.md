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
- **Email report (2026-04-23 onward):** `generate_report.py` is the **sole** daily email generator. It unifies the picks surfaced in the Daily Insight page (`snapshot.top_buys`/`top_sells` — no ranker gate) with the ranker-gated BUY/ACCUMULATE picks into a single de-duped list, each entry tagged with its source (`BOTH` / `DAILY_INSIGHT` / `RANKER`). The HTML/PDF gains an Expert Trader Memo section at the top; the email body is plain text (buy symbols + reasons + Dashboard + news links). Recipients come from `REPORT_EMAIL_TO` in the local `.env` — **no list is committed and there is no fallback in code** (removed 2026-08-24 when the repo went public; a source file is the wrong place to publish an inbox). Empty means the HTML/PDF are written and no mail is sent. `scripts/jobs/job_sector_signal_publish.bat` calls `generate_report.py`.
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

> **AMENDED 2026-08-23 — the gate is a score, not a conjunction.** The five
> conditions below stand; requiring *all five at once* does not, because it was
> measured to be arithmetically unreachable.
>
> Over the full 13,470-row panel (2023-03 → 2026-08), individual pass rates are
> c1 17.5% · c2 20.4% · c3 34.7% · c4 52.1% · c5 47.7%. All five held
> simultaneously on **0.3%** of rows (42), and the **longest consecutive
> all-five run across 15 sectors in 3.5 years was 2 sessions** — against a
> requirement of 3 in code and 5 in this document. So `accumulation_age` was 0
> on every row ever written, and §22.1's "§16 has never fired" was right about
> the symptom and wrong about the cause: the gate was over-specified, not
> data-starved.
>
> **The rule now:** a sector is in stealth accumulation when it meets
> **≥ `STEALTH_MIN_CONDITIONS` of the 5** (default **4**) for ≥
> `STEALTH_MIN_SESSIONS` sessions (default **3**). The conditions are
> deliberately **unweighted** — §16 gives no basis to rank them, and an invented
> weight vector is a number nobody could defend. A condition that *cannot be
> evaluated* is dropped from **both** the numerator and the denominator, so
> missing data never silently raises the bar.
>
> Result on the live panel: **23 events across 11 sectors**, 53 rows with
> `accumulation_age > 0` (max 7) — the first non-zero values in the system's
> history. **It does not yet meet §16.11** — see the honest numbers there.
>
> This retires the doctrine-vs-code conflict logged as §20.3 P1-1, in the
> direction of neither number: both gave zero. `analysis/stealth.py`,
> `api/routers/stealth.py` and `frontend/src/lib/stealthPresets.ts` now read the
> same two knobs. `RETURN_BOTTOM_FRAC` is back to the doctrine **0.40**.

A sector is in **stealth accumulation** when ≥ 4 of these hold for ≥ 3 sessions (was: ALL, for ≥ N=5):
1. **Rolling 20d net dollar flow z-score > +1.0** (flow regime shift vs own history)
2. **Foreign net buy positive on ≥ 60% of sessions in the last 20d** (smart-money persistence)
3. **Breadth SMA20 rising** (diffusion — more constituents joining, not one whale)
4. **ATR% below 20d median** (quiet tape — no euphoria yet)
5. **Price return (close_idx) in bottom 40% of its 60d range** (still cheap, not extended)

When the score clears the bar, emit a new `ACCUMULATE` action — this is the "gốc" (root) buy. The existing `BUY` action stays but is downgraded to "cành cao" (late-cycle) confirmation.

### 16.2 New leading features (add to FEATURE_COLS)
- `flow_z20` — 20d rolling z-score of `net_dollar_flow` per sector
- `flow_z60` — 60d version (slower, macro flow regime)
- `foreign_streak` — number of consecutive sessions of positive `foreign_net` (cap 20)
- `foreign_hit_20d` — fraction of last 20 sessions with `foreign_net > 0`
- `stealth_score` — composite: `(flow_z20) × (breadth_sma20 rising) × (1 / (1 + atr_rank_20d))`
- `flow_price_divergence` — `flow_z20 − return_20d_zscore` (positive = flow leading price)
- `flow_leadtime_proxy` — lag (in days) between flow z crossing +1 and price return turning positive; stored per crossing event
- `conditions_met` — how many of the 5 §16.1 conditions hold today (0-5)
- `accumulation_age` — consecutive sessions the §16.1 score has cleared the bar (0 if not active)

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

> **First actual measurement — 2026-08-23. The gate fires and FAILS this
> section.** Now that §16.1 can fire at all, the 23 events it produces over the
> full panel were scored against the three criteria above:
>
> | criterion | target | measured (≥4/5, N=3) |
> |---|---|---|
> | breakout within 40d | — | 74% (17/23) |
> | lead time ≥ 10 trading days | ≥ 60% | **24%** — median lead **3 days** |
> | median root-capture ratio | ≤ 0.85 | **0.910** |
> | false positives | ≤ 30% | 26% |
>
> Tightening does not rescue it: ≥4/5 with N=5 gives 12 events, 92% breakout,
> 36% at ≥10d lead, root capture 0.913. Loosening is worse: ≥3/5 N=5 gives 130
> events, 79% breakout, 17% at ≥10d, 0.944.
>
> Read plainly: the gate now identifies sectors that **are about to move**
> (74-92% breakout is a real hit rate) but it identifies them **~3 days early,
> not ~2 weeks**, and it enters at 91% of the eventual peak. That is a momentum
> confirmation signal — §16.3's `BUY`, "cành cao" — wearing the `ACCUMULATE`
> label. **The "gốc" claim is not yet earned**, and no ACCUMULATE sizing rule
> (§16.9: 1.5× vol target, 2.5×ATR stop) should be trusted on it until the lead
> time is fixed.
>
> The conditions are the suspects, not the aggregation: c1 (`flow_z20 > 1`) is
> a *contemporaneous* flow spike, so it tends to fire with the move rather than
> ahead of it. The leading candidates in §16.2 that would actually buy lead time
> — `flow_price_divergence`, `foreign_streak`, `flow_leadtime_proxy` — are
> computed and stored but are in **no** condition. That is the next experiment.

> **The experiment was run — 2026-08-24 — and the suspect above was wrong.**
> `scripts/stealth_leadtime_experiment.py` scores candidate condition sets over
> the full panel. Every variant containing `flow_price_divergence` made lead
> time **worse** (median 3 → 2-3 days, ≥10d share 20% → 4-17%) while inflating
> the event count 20 → 38-77. It fires more often, not earlier.
>
> What moved was the condition §16.11 did not name: replacing **cond2's 20d hit
> *rate*** with **`foreign_streak ≥ 3`** — consecutive sessions of net foreign
> buying.
>
> | | events | breakout | ≥10d lead | med lead | med RC |
> |---|---|---|---|---|---|
> | shipped §16.1 | 20 | 75% | 20% | 3 | 0.940 |
> | cond2 → `foreign_streak ≥ 3` | 16 | 88% | **50%** | **8** | 0.924 |
>
> This is §18.5/21's argument arriving from the other direction: a hit rate is
> satisfiable by one block trade plus 19 quiet days, and one block trade is not
> accumulation. **Persistence is the part that leads.**
>
> **Not shipped, on purpose.** n=16 over 3.5 years, and the year split puts the
> entire effect before 2026: 2023-25 run 50-67% at ≥10d with median lead 10-14,
> while 2026's three events are 0% / median 3 — the same collapse the shipped
> gate shows in 2026 (0% at ≥10d on six events). Tightening to `streak ≥ 8`
> gives 100% at ≥10d on n=2, which is not a result. Root capture stays ~0.92
> against the 0.85 target either way, so no variant here earns the "gốc" claim.
>
> **The real question this surfaced:** both gates degrade sharply in 2026. A
> defect common to two different condition sets is more likely data or regime
> than condition choice — that is the next thing to look at, ahead of any
> further condition tuning.

### 16.12 The base rate — and why §16.11's criteria are not sufficient

> **2026-08-24, chasing the 2026 collapse.** Adding the missing row to
> `scripts/stealth_leadtime_experiment.py` — score **every** row in the panel,
> i.e. no gate at all — produced the most important number in this section:
>
> | | events | breakout | ≥10d lead | med lead | med RC |
> |---|---|---|---|---|---|
> | **NO GATE (base rate)** | 13,033 | **83%** | **23%** | **4** | **0.944** |
> | shipped §16.1 | 20 | 75% | 20% | 3 | 0.940 |
> | cond2 → `foreign_streak ≥ 3` | 16 | 88% | 50% | 8 | 0.924 |
>
> **The shipped gate is worse than not filtering at all.** Lower breakout rate,
> fewer early signals, shorter lead. Of the six variants only
> `foreign_streak` beats the base rate on any axis.
>
> **Every number in this section and §16.11 uses the old 1.15% bar — see
> §16.15.** Re-measured under a horizon-consistent one, the base rate is 43%
> breakout / 74% at ≥10d, and the shipped gate still fails to beat it. The
> ranking of the variants does not change; the absolute levels do.
>
> **§16.11's three criteria cannot detect this**, which is the doctrine defect.
> They are absolute thresholds ("≥60% at ≥10d", "RC ≤ 0.85", "FP ≤ 30%"), so a
> gate posting a respectable-sounding 75% breakout reads as *underperforming a
> target* when it is in fact **selecting worse-than-random sector-days**. Every
> §16.11 measurement from here on is reported against the NO GATE row, and a
> variant that does not beat it is not a signal regardless of its absolute
> numbers. The bench prints the row on every run.
>
> **Amend §16.11's success criteria accordingly:** each of the three targets is
> now *necessary but not sufficient* — a candidate must also beat the
> unconditional base rate on breakout share and ≥10d share, **within each
> year**, not pooled. Pooling is what let `foreign_streak`'s pre-2026 strength
> mask a 2026 that matches random.

### 16.13 The 2026 collapse is mostly the market

> **Same investigation, 2026-08-24.** Ruled out first, cheaply:
> - **Not data.** 2026 rows are 99% non-zero `foreign_net`, 100% `close_idx`
>   and `atr_pct`, 15 sectors, 156 sessions — coverage matches 2024-25.
>   `breadth_sma20` has **zero NULLs** in 2024-26 (245 in 2023 only); its
>   apparent "76% coverage" was a miscount on my part — a legitimate `0.0` is
>   not a missing value. Its zero *rate* does rise, 14/15/16% in 2023-25 →
>   **24%** in 2026, which is not a gap but the flat tape below showing up in
>   breadth: on a quarter of 2026 sector-days no constituent was above its
>   SMA20. (Breadth takes 9 distinct values over 5 names — §20.3 P1-3.)
> - **Not right-censoring.** Only 1 of 7 shipped-gate events in 2026 has fewer
>   than 40 forward sessions, so "a long lead is unobservable near the panel
>   edge" does not explain it.
>
> What did explain most of it is the tape itself. The **unconditional** base
> rate falls in lockstep:
>
> | year | base breakout | med fwd-40d max | gate breakout | gate ≥10d |
> |---|---|---|---|---|
> | 2023 | 88% | +7.1% | 80% | 25% |
> | 2024 | 84% | +5.4% | 100% | 25% |
> | 2025 | 86% | +7.9% | 80% | 25% |
> | **2026** | **68%** | **+3.2%** | **50%** | **0%** |
>
> 2026 is a flatter tape: half the forward move, and a breakout definition
> pinned to 2×ATR catches far less of it. **But the gate degrades faster than
> the market** — 50% vs a 68% base rate, 0% vs 18% at ≥10d. So regime explains
> the level, not the shortfall. Both remain open; the tape is the larger term.

> **"Flatter" was the wrong word — 2026-08-24 (4).** Measured directly
> (`scripts/late_period_diagnosis.py`, check 2), 2026 is not flat, it is
> **down, and more volatile than the two years before it**:
>
> | year | med fwd-40d | med fwd-40d **max** | % of fwd-40d positive | ann vol |
> |---|---|---|---|---|
> | 2023 | +3.9% | +7.1% | 70% | 0.89 |
> | 2024 | +1.4% | +5.4% | 58% | 0.21 |
> | 2025 | +3.6% | +7.9% | 63% | 0.29 |
> | **2026** | **−7.6%** | **+2.9%** | **17%** | **0.42** |
>
> The `med fwd-40d max` column is what §16.13 was reading, and taken alone it
> does look like a quiet tape. It is not: only the *max* compressed. The median
> forward move went negative and vol went **up**. That distinction matters for
> what to do next — a quiet tape argues for a more sensitive gate, a falling
> one argues that a long-only breakout definition has little to find, which is
> a different problem with a different fix.
>
> The 2×ATR breakout bar also moves with the tape it is measuring: ATR rose,
> so the bar rose, while the moves it must clear shrank. A breakout definition
> that gets harder exactly when the market gets choppier will show a collapse
> in any year like this one, independent of the gate.

### 16.14 What this means for §16 as a whole

> Stated plainly, so no later reader has to re-derive it: **as of 2026-08-24
> the §16.1 gate has no measurable edge.** It fires 20 times in 3.5 years and
> those 20 sector-days break out *less* often, *later*, and at a *worse* entry
> than a sector-day drawn at random from the same panel.
>
> This does not falsify §16's thesis — that VN money flow leads public
> coverage by ~1 month. It falsifies **this implementation** of it. The one
> result pointing back at the thesis is `foreign_streak`: persistence of net
> foreign buying is the only tested condition that beat the base rate
> (88% vs 83% breakout, 50% vs 23% at ≥10d, median lead 8 vs 4), and §18.5/21
> predicted exactly that on different grounds.
>
> **Operational consequence, effective now:** no `ACCUMULATE` sizing rule from
> §16.9 — 1.5× vol target, 2.5×ATR stop, 4 concurrent — should be trusted on
> the current gate. §16.11's warning said the "gốc" claim was *not yet earned*;
> the base rate says the signal is not yet a signal. Treat live `ACCUMULATE`
> output as a watchlist, not an instruction, until a variant beats NO GATE
> within-year.

### 16.15 The breakout bar was 1.15%, not 8% — 2026-08-24 (5)

§25.10 suspected §16.4's `2 × atr_pct` of **scaling with the tape it measures**:
ATR rises in choppy markets, so the bar would rise exactly when the moves
clearing it shrink. `scripts/stealth_leadtime_experiment.py --breakout` now
scores four definitions so that could be tested rather than assumed.

**The suspicion was wrong.** Sector ATR barely moves across years — median
0.58 / 0.53 / 0.57 / 0.67% in 2023-26 — so `atr_now` (today's reading) and
`atr_baseline` (the sector's trailing 2y median, no feedback) produce
near-identical tables. The feedback is real in direction and negligible in size.

**The actual defect is units.** `atr_pct` is a **daily** range, median 0.57%, so
the bar is ~**1.15%**. Asking whether a **40-session forward maximum** ever
exceeded 1.15% is not a breakout test — it is a liveness test, and **83% of all
sector-days pass it**. Every §16.11 and §16.12 breakout number recorded so far
was measured against that.

`atr_scaled` = `2 × median ATR × √40` ≈ **7.2%** keeps §16.4's "two normal
moves" intent while being horizon-consistent (a random walk's expected maximum
grows with √n), stays sector-relative, and takes the trailing median so it has
no feedback.

| | events | breakout | ≥10d lead | med lead | med RC |
|---|---|---|---|---|---|
| NO GATE, old bar | 13,033 | 83% | 23% | 4 | 0.944 |
| **NO GATE, `atr_scaled`** | 13,048 | **43%** | **74%** | **17** | 0.944 |
| shipped §16.1, `atr_scaled` | 20 | 40% | 75% | 21 | 0.940 |
| cond2 → `foreign_streak ≥ 3` | 16 | **62%** | **90%** | **34** | 0.924 |

**§16.11's lead-time criterion does not survive this.** Under a real bar the
unconditional base rate already clears "≥10d on ≥60%" — 74%, median lead 17
sessions — which is not the system detecting anything, it is what "40 sessions
to move 7%" mechanically implies. The criterion was satisfiable by noise and was
never the right test. **Only the margin over NO GATE means anything**, which is
what §16.12 already said and this makes unavoidable.

What survives the change, unchanged: the shipped gate is still no better than no
gate (40% vs 43%), `foreign_streak` is still the only variant clearly ahead on
every axis, and **every variant still collapses in 2026** under every definition
(shipped 0% at ≥10d on n=6; `foreign_streak` 33% breakout / 0% at ≥10d on n=3).
So §25.9's "it is the tape" conclusion stands and §16.14's "no measurable edge"
verdict stands. The bar being wrong was a second, independent defect.

**Not shipped into the scanner.** `analysis/stealth.py` does not use a breakout
definition — this is a measurement bench only, and no live signal changes.
Root capture is untouched at ~0.94 either way, so no variant has earned the
"gốc" claim.

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
| Backend (pytest) | 252 | `python -m pytest tests/` |
| Frontend (vitest) | 13 | `cd frontend && npm test` |
| **Total** | **265** | — |

> 2026-08-24 (12): +11, and one of them found a live production defect.
> `tests/test_report_import.py` (+8) pins that `import generate_report` sends no
> mail, opens no DB and writes no file — the property the §20.3 P3-2 split
> exists for. Three of those are behavioural and one is structural
> (`test_the_work_lives_inside_main_not_at_module_level`), because the first
> three can pass by luck and the last cannot: measured against the pre-split
> file it is 113 module-level statements versus 4, so the `< 40` threshold
> discriminates. `smtplib.SMTP` is replaced with a raising bomb rather than a
> recording mock — a mock lets the import finish and reports afterwards, which
> is exactly the behaviour that shipped for months.
>
> `tests/test_model_artifacts.py` (+3) guards something worse and unrelated to
> the refactor: **running pytest overwrote the production ranker.**
> `RotationRanker.fit()` writes `rotation_ranker.pkl` to
> `config.SAVED_MODELS_DIR` unconditionally, six tests call it with 2-3
> synthetic features, and `models/saved/` is gitignored — so the 17:00 publish
> job died with *"number of features in data (19) is not the same as it was in
> training data (3)"*, `git status` was clean, and no test failed. A silent
> suite that breaks production is the worst shape a defect can take.
> `tests/conftest.py::_models_go_to_a_tmpdir` is autouse for the reason an
> opt-in fixture would fail: the tests that forget to ask are the dangerous
> ones. Verified by negative control — de-autousing it fails 2 of the 3 guards
> (and re-broke the live model, which is the bug reproducing itself).
>
> 2026-08-24 (9): +13. `tests/test_position_track.py` — stop/target on the book
> and the price path since entry (§22.10). The two that carry the feature are
> `test_stop_and_target_survive_the_round_trip` (the defect itself: both numbers
> were destroyed at the mark) and
> `test_hit_stop_is_ever_touched_not_just_today`. Its mirror,
> `test_a_breach_before_entry_is_not_your_breach`, is what stops the fix
> over-firing on the 30-session tail that predates the trade.
> `test_sellable_on_skips_holidays_too` pins the reason `next_trading_day`
> exists at all rather than `setDate(+2)`.
>
> One fixture detail is the test: `_bars()` keys the date as `"time"`, because
> that is what `picks_universe_service` writes and `generate_report.py:164` has
> to rename. A test that used `"date"` would pass against code that never
> matches a real bar.
>
> 2026-08-24 (3): +19. `tests/test_position_close.py` (+17) and two more in
> `test_regime_confidence.py`.
>
> The load-bearing one is `test_a_close_is_not_a_delete`: closing must *leave
> evidence*. Until `close_position()` existed the only verb was
> `remove_position()`, so a sale and a mis-click were the same operation and the
> book could never answer whether the picks made money.
> `test_costs_can_turn_a_small_win_into_a_loss` is the reason the §18.2/10
> figures are imported rather than retyped — a +0.20% gross scalp is a loss net
> of a ~0.40% round trip, and a book that disagrees with the backtest about that
> is worse than no book. `test_a_break_even_book_reports_zero_not_none` guards a
> `sum(...) or None` that would have erased an exactly-flat book, and
> `test_an_old_state_file_without_closed_still_loads` pins the reason this
> needed no migration.
>
> 2026-08-24 (2): +26. `tests/test_regime_confidence.py` (+13) and
> `tests/test_position_edit.py` (+13).
>
> Three of the regime tests guard *wording*, not arithmetic, which is unusual
> enough to justify: `confidence_phrase()` is the only reader-facing sentence
> that says what the number means, and the four strings it replaced said "HMM
> confidence 1.00" for months. `test_the_phrase_hedges_at_the_low_end_not_the_
> high_end` pins the *direction* of the hedge — it first sat above 0.85 on a
> 300-bar measurement that turned out to be a period artefact (§25.2), so
> asserting the direction is what stops that regressing quietly.
>
> **`hmmlearn` was missing from the interpreter that runs pytest**, while
> production runs through `uv run` and resolves `.venv`, where it is installed.
> So every regime test before this date exercised the heuristic fallback while
> the scheduled job ran the HMM — a suite agreeing with itself about a code path
> nobody ships. Installed now; the HMM tests `skipif` rather than silently pass
> when it is absent.
>
> The load-bearing regime test is
> `test_fit_does_not_collapse_on_a_real_length_panel`, which pins the *cause*
> (three of four states at hmmlearn's ceiling covariance) rather than the
> symptom Tom reported (confidence stuck at 1.0) — the symptom is a consequence
> and a future refactor could reproduce it a different way. The fixture is a
> deliberate two-regime path: a single-regime random walk is exactly the input
> that collapsed in production, so it cannot tell a working model from a broken
> one.
>
> On the book: `test_edit_does_not_restamp_the_open_date` is the one carrying
> the feature — it is the whole reason `update_position` exists separately from
> `add_position`. `test_pnl_route_is_not_shadowed_by_the_symbol_route` guards
> FastAPI route ordering: `/positions/pnl` and `/positions/{symbol}` share a
> prefix, and if the literal ever loses you get a position named "pnl".

> 2026-08-23 (late, 6): +14 in `tests/test_stealth_gate.py` — §16.1 after it
> stopped being a conjunction. The load-bearing one is
> `test_four_of_five_fires_where_all_five_cannot`: a panel that clears four
> conditions and never the fifth must produce an event, which the old gate
> could not. `test_unevaluable_condition_does_not_raise_the_bar` guards the
> numerator/denominator symmetry — the bug that let an all-zero `foreign_net`
> column silently ship a 3-condition gate while the doctrine said 5. Two more
> pin the endpoint to the scanner: that `/api/stealth/active`'s Query defaults
> come from `analysis.stealth`'s constants rather than being retyped, and that
> its cond4 ranks ATR instead of comparing a raw 0.006 fraction to 0.5.
>
> The fixture is deterministic on purpose: flat flow gives sd=0 → z is NaN → c1
> is reliably False, and a *ramp* (not a step) is what holds z above +1, since
> a step's z decays to 0 once the 20d mean catches up. An earlier `rng.normal`
> version produced random z-spikes that made the cold case fire intermittently.

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

> **2026-08-24 — the "30" above is stale; the baseline is 66.** Measured, not
> re-broken: `F401` 14 · `E402` 11 · `B904` 8 · `B905` 5 · `S608` 5 · `E401` 4
> · `PERF401` 4, then a tail of ones and twos. The 30 was counted before
> several later features landed, and nobody re-measured it — which is the
> failure mode a hardcoded count in a document always has. Treat 66 as the
> number a change must not grow, and re-measure rather than trusting this line.
>
> **65 as of 2026-08-24 (12)** — three `F841` dead locals in
> `generate_report.py` (`sector_prior_dv`, never even written to;
> `sector_stats_map`; `flow_in_secs`) fell out of the `main()` wrap. They were
> not new: ruff analyses function scope properly and module scope barely, so
> moving the body inside a function is what made them visible. That is worth
> knowing before the next count moves — a refactor can raise this number without
> breaking anything, and lower it without fixing anything.

**Defaults chosen to preserve live behaviour:** `API_REQUIRE_KEY=0`,
`ALLOW_SHORT_SIGNALS=1`, `TRADING_HALT=0`. Nothing in the daily email changes
until you flip these. `MAX_ACCUMULATE_SECTORS=4` and the 30-session release
DO change behaviour — they implement §16.9, which was never enforced.

### 20.3 Still open — needs a decision, not just code

| Id | Question |
|---|---|
| ~~P0-5~~ | **CLOSED 2026-08-23** — `foreign_net` was backfilled by commit `b4d1d90`. Measured: **12,616 / 13,470 rows non-zero**, spanning 2023-03-13 → 2026-08-21; `foreign_hit_20d` spans 0.0 → 1.0 with 2,742 rows clearing the §16.1 0.6 threshold. The three `FEATURE_COLS` entries are no longer constant. **Consequence nobody logged at the time:** `analysis/stealth.py` drops cond2 whenever `foreign_net` is all-zero, so the backfill silently took the stealth gate from 3 evaluable conditions to 5 — a behaviour change that arrived as a side effect of a data change. That asymmetry is now explicit in the code (numerator *and* denominator) and pinned by `test_unevaluable_condition_does_not_raise_the_bar`. |
| ~~P1-1~~ | **CLOSED 2026-08-23**, in the direction of neither number. Doctrine said N=5 / bottom 40%, `analysis/stealth.py` shipped N=3 / bottom 60% — but under a five-way AND **both give zero sectors over 3.5 years**, so the disagreement was never worth what it cost to argue about. §16.1 is a score now; the scanner, `api/routers/stealth.py` and the UI presets read the same two knobs. |
| P1-3 | Breadth over 5 names takes 6 discrete values (§18.1/6, still open). |
| ~~P1-4~~ | **CLOSED 2026-08-24** (§25.3). The published label is the filtered posterior of the last bar — `predict_proba(X[:t+1])[-1]`, which has no future to smooth over — so it no longer changes with hindsight. Found while chasing a different symptom: confidence pinned at 1.0. The back-painting was the *third* defect in that chain; the first was a collapsed fit that made the posterior 1.0 by construction. |
| P2-2 | Two rate-limit buckets in one process: `utils/vnstock_gate` and `picks_universe_service._kbs_throttle`. `/insight/refresh` takes no `job_lock` at all, so a UI refresh overlapping the intraday job runs at 2× the KBS ceiling. |
| P2-3 | The "intraday" job fetches `interval="1D"` and re-downloads 120 days every 15 minutes (~3,750 calls/day against an 18/min gate). Either fetch real 15m bars or admit it is an EOD pipeline and fix §4/§8. |
| ~~P3-2~~ | **CLOSED 2026-08-24.** `import generate_report` is inert: 113 module-level statements → 4, everything else inside `main(argv=None)`. `services/report/` took the genuinely pure pieces — chart builders, the six SQL reads (which now take the cursor as an argument instead of closing over a module global, the actual reason nothing could be tested) and the two formatters. **The HTML weave deliberately did not move**: ~700 lines of `X = build_x()` where each builder reads several others' globals is a rewrite, not an extraction, and the harm was `import` sending mail — which is fixed. `ponytail:` in `services/report/__init__.py` names the trigger for finishing it (a second output format). `/api/state/report/send` still shells out; it no longer has to, and that is its own commit. |

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
| Stealth Watch | `/api/stealth/active`, `/api/stealth/history` | `accumulation_age` is 0 on all 13k rows; §16 has never fired — **cause corrected 2026-08-23**: not missing data, an unreachable AND gate (§16.1). 53 rows are non-zero now. |
| Rotation Map | `/api/rotation/pairs` | ~~no pair clears the 1.5 threshold~~ — **wrong, corrected below** |
| Flow Pulse | `/api/pulse/exposure` | ~~no positions are tracked~~ — **wrong, corrected below** |

Fixing Stealth Watch means fixing §16 (see §20.3), not the UI — which is what
§16.1's 2026-08-23 amendment did. The other two
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
docs/PATCHES.md         ← plan lifecycle: what is running, what is done (2026-08-24)
specs/                  ← one topic per file, referenced from 5 .py docstrings; untouched
docs/reference/         ← ALGORITHM.md, GLOSSARY_VI.md
docs/reviews/           ← the dated reviews (§21: dated records keep their names)
```

**No Python file moved.** `scripts/jobs/*.bat` invoke `main.py` from the repo
root under Task Scheduler, and `MODIFICATION_LOG.md` 2026-07-19 already records
one path move that left shortcuts pointing at a dead directory.

> **2026-08-24 (10) — the four documents now divide cleanly.** Tom asked for
> "một file update patch chung" and for the repo to say **what the current plan
> is**, which nothing did: a finished plan left a `MODIFICATION_LOG.md` entry
> and a `CLAUDE.md` section, and an *unfinished* one left nothing at all. So
> "what are we doing now" was only answerable by reading a plan file outside the
> repo, in `~/.claude/plans/`, which no reviewer or agent would ever find.
>
> | file | answers | shape |
> |---|---|---|
> | `CLAUDE.md` | what the system **must** be | doctrine, amended in place |
> | `ARCHITECTURE.md` | what the contracts **are** | layers + dated changelog |
> | `MODIFICATION_LOG.md` | what **changed**, and why | append-only, one entry per change |
> | `docs/PATCHES.md` | which plan is **running**, which is **done** | two tables, one line per plan |
>
> `PATCHES.md` deliberately holds **one line per plan** and points elsewhere for
> the reasoning. A patch index that grows into a second changelog is a second
> changelog, and two changelogs disagree — which is the exact failure §21 logged
> for versioned filenames and §20.4 logged for plan-vs-code drift.
>
> **The audit that came with it found the retired docs were mostly not retired.**
> Of 23 stale-looking matches, 19 are dated changelog entries in
> `ARCHITECTURE.md` / `CLAUDE.md` / `ALGORITHM.md` recording that OpenClaw *was*
> retired and the 170-symbol system *was* replaced — §21 protects those, and
> rewriting them would erase the record that the change happened. The genuinely
> wrong content was concentrated elsewhere and is fixed: two specs describing
> things that never shipped or shipped differently (`SPEC_INTRADAY_VNSTOCK.md`,
> `REDESIGN_PHASE15.md`), one spec carrying Ollama defaults dropped a day
> earlier (`trader_agent.md`), one spec naming an endpoint that was never built
> (`daily-insight.md` §4.4 `send-gmail`), and `GLOSSARY_VI.md`.
>
> **`GLOSSARY_VI.md` was the dangerous one**, because it is the file written for
> the person who is not reading the code. It still taught the 5/5 stealth gate
> (unreachable — §16.1), still defined `confidence` as "how sure the model is"
> (it is P(label survives 5 sessions) — §25.2), described the kill-switch as
> firing *automatically* after three sentinel hits (it is manual — §22.10), and
> said T+2.5 in calendar days (it is 2 *sessions*, holiday-aware). Every one of
> those would have led a reader to act. Corrected, each pointing at the section
> that governs it.


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

> **2026-08-24 — half of that is now done.** The book was a list, not a control:
> you could mark a pick but not correct the price, and the price it stamped is
> the *previous close*, which is almost never your fill. `PATCH
> /api/state/positions/{symbol}` edits entry price and quantity in place, and
> `GET /api/state/positions/pnl` marks the book against the picks snapshot.
>
> `update_position` is deliberately **not** `add_position`: that one restamps
> `opened_at` to today and drops the symbol from the watchlist, both wrong when
> you are fixing a typo. `None` means "leave this field alone", so clearing one
> takes an explicit negative — the alternative silently wipes `qty` on every
> price edit.
>
> The response carries `priced` and `count` separately, because a P&L over 1 of
> 3 rows is not the book's P&L, and the header says so when they differ.
> Unrealised only: **still no exit price**, so realised attribution remains the
> next thing to add.

> **2026-08-24 (3) — and now it is added, which finishes the book.**
> `POST /api/state/positions/{symbol}/close` moves a row from `positions` to a
> new `closed` list with realised P&L; `GET /api/state/positions/realised`
> totals it. The UI gets an "Đã bán" button that asks for the fill price, and a
> closed-trades panel that hides itself when empty.
>
> **The distinction that makes this worth a second verb:** `DELETE` still
> deletes. "I mis-clicked" and "I sold at 28" were the same operation before
> today, and both destroyed the row — so the app was structurally incapable of
> answering the one question a book exists to answer. The ✕ is still there,
> smaller, for the mis-click.
>
> Realised P&L is **net of the §18.2/10 costs**, imported from `config.py`
> (`BACKTEST_FEE_BPS` × 2 + `BACKTEST_SELL_TAX_BPS`, ≈0.40% round trip) rather
> than retyped. A book quoting a gross number the backtest would call a loss is
> worse than no book, and at these levels the costs routinely decide whether a
> small win is a win — a +0.20% gross scalp books at −0.20%.
> `pnl_pct` is computed even without `qty`, because cost-in-percent is
> size-independent; `pnl_vnd` is not, and stays null rather than being invented.
>
> `closed` is a key, not migration 12 — `_read()` merges `_DEFAULT`, so every
> state file written before today loads unchanged. Still no partial exits: a
> close takes the whole position (`ponytail:` in the source names the upgrade).

> **2026-08-24 (9) — the book can now follow a trade, not only record one.**
> Tom: *"chưa có view để … tiếp tục theo dõi các ngày sau đó."* The data existed
> at every layer and was destroyed at exactly one line.
> `picks_scoring.compute_stop_target_rr` computes a stop and a target,
> `PickEntry` carries them, the Daily Insight card renders them and draws a
> stop→target ladder — and the "Đã vào lệnh" button sent `entry_price` alone,
> into a `trading_state` row with no field to receive them. **So the book could
> not answer the one question worth asking the day after a buy: is this trade
> still valid.** `stop` / `target` / `thesis` are stored now, and editable in
> place on the same `NumCell` the entry price uses.
>
> `GET /positions/pnl` gained `path`, `hit_stop`, `hit_target`,
> `dist_to_*_pct`, `sessions_held`, `sellable_on`. **No new endpoint on
> purpose:** `/pnl` already read the book, already called `.peek()`, already
> looped the positions, and `MyBookPanel` already called it — a second route is
> two route-ordering tests and two places to drift. **No new data source
> either:** the price path is `TickerRow.daily_prices`, 30 sessions the
> snapshot already carries and already persists.
>
> Two definitions that are load-bearing rather than incidental:
> - **`hit_stop` is "ever touched since entry"**, not "today's close is
>   through the level". A stop breached on Tuesday and recovered by Friday is
>   still a breach, and a book that forgets that tells you the trade is fine.
> - **T+ counts sessions.** `tPlusDays()` used `setDate(+i)`, so a Thursday buy
>   claimed a Sunday settlement; it is also T+**2** now, not T+3, matching
>   `BACKTEST_SETTLEMENT_LAG` and §18.2/7. The book row takes the
>   holiday-aware date from the new `utils/clock.next_trading_day`.
>
> Not migration 12 — but `_DEFAULT` merges at the *top level only*, so rows
> written before today omitted the key entirely and shipped a shape the TS
> `Position` type forbids. `_POSITION_DEFAULT` is merged per row in `_read()`.
>
> The sparkline is hand-rolled SVG: recharts sits in a 362 kB chunk that only
> loads on the Backtest tab (§22.3), and a 64×22 polyline must not drag it onto
> every page — the built chunk list is unchanged.
>
> **Deliberately not built** (Tom picked two of four): stop/target *alerts* and
> a full T+ calendar panel. Both fields are computed already, so the UI is
> cheap when wanted. `path` is closes only — `daily_prices` has no high/low — so
> an intraday wick through a stop that closed back above does not register.

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
**Chặt / Vừa / Rộng**, not tight/loose. The presets were shipped to price the
§20.3 P1-1 doctrine-vs-code disagreement **in sectors** — the only unit in which
anyone would care enough to close it.

**They did their job on the day they shipped, and the answer killed the
question.** Running all three returned `active: []` at *every* setting,
including maximally-wide. Both sides of P1-1 were worth zero sectors, because
the AND gate underneath them was unreachable (§16.1). The conflict was
three-way, not two — `api/routers/stealth.py` had its own third set of defaults
— so the page could show a sector the scanner would never record.

Rewritten 2026-08-23 around the knob that now matters, `min_conditions`:

| preset | numbers | what it is |
|---|---|---|
| Chặt | 5/5, N=5 | the original doctrine, **kept so you can watch it return 0** |
| Vừa | ≥4/5, N=3 | what runs now — 23 events / 11 sectors in 3.5 years |
| Rộng | ≥3/5, N=1, mọi ngưỡng hạ | a probe — "ngành nào gần đạt", not a buy list |

The page **opens on Vừa**, not Chặt: a default that shows a gate nobody is
running is a default that misleads. Selecting Chặt raises the warning now,
naming the 2-session measurement that retired it.

Two other things this pass reconciled:
- `api/routers/stealth.py` classified `active` only at `passes == 5`. Both
  knobs are now imported from `analysis/stealth.py`, so the page and the
  scanner cannot drift apart again without a test failing.
- The endpoint's cond4 compared a **raw** `atr_pct` (~0.006) against a
  threshold literally named `atr_rank_max` (0.5) — it passed for free on all 15
  sectors, so the endpoint's "five-condition" gate was really four. It takes a
  0..1 percentile within the sector's own window now, which is what §16.1
  condition 4 means.

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

`foreign_hit_20d`'s entry said out loud that `foreign_net` was zero across the
whole history (§20.3 P0-5) — a tooltip that explains a column doing nothing,
without saying so, is worse than no tooltip. **That warning was already false
when it shipped**: the backfill had landed the same morning. Corrected the same
day, along with a new `conditions_met` entry for the §16.1 score.

### 24.5 Not done
- `Th` / `FilterBar` are on two tables. Risk, Stealth and Regime still have
  their own headers.
- Native `title`: no touch support, ~1s delay. Fine for a definition, not for
  a formula or a link.
- Report run history is in memory only. It survives no restart; the log file on
  disk is the durable record.

## 25. Regime confidence — a collapsed model reporting certainty — 2026-08-24

Tom: *"do tin cay cua thi truong luon la 100% la sai"*. Correct, and the
reported symptom was the **third** defect in the chain, not the first.

### 25.1 What was actually wrong

| # | defect | consequence |
|---|---|---|
| 1 | features fed **raw** to a diagonal Gaussian HMM | 3 of 4 states blew up to hmmlearn's ceiling covariance (1000); all 111 bars landed in the survivor |
| 2 | **180 days** of history (~111 bars) for a 40-parameter model | fitted inside a single regime — a regime model that has never seen a regime change |
| 3 | `confidence` = the **state posterior** | answers "which state is this bar in", not "is this call worth acting on" |

Defect 1 is why the number was 1.0: **with one live state the posterior is 1.0
by construction.** The model was not confident, it was degenerate. Feature
scales differ ~6× (5d return sd 0.028 vs 20d vol sd 0.005) and diagonal
Gaussian EM is not scale-invariant — the wide column dominates the likelihood,
the narrow states never win an observation, their covariances run to the
ceiling. Standardising gives occupancy `[154 177 470 251]`, max covariance 2.7.

History is now 1500 days (~1050 bars, back to 2022). `fit()` **refuses** a
collapsed fit (>1 empty state) and falls back rather than publishing its 1.0.

### 25.2 The formula

Even with 1 and 2 fixed, the state posterior sits at ~0.95 — a Gaussian HMM is
near-certain which state a bar is in whenever the states separate at all. That
is a property of the fit, not a reason to size a position. Meanwhile the label
flipped 26 times in 260 sessions.

`confidence` now means **P(this label still holds in `CONF_HORIZON` = 5
sessions)** — the filtered posterior propagated through the transition matrix,
summed over every state sharing the label.

| | value |
|---|---|
| range over 300 sessions | 0.46 – 0.91 (was: 0.9999998 on nearly every row) |
| mean predicted | 0.69 |
| mean realised (label actually held) | 0.60 |
| live 2026-08-24 | `risk_on 0.6472` |

Calibration by bucket: `[0.55,0.70)` predicted 0.64 / actual 0.63,
`[0.70,0.85)` 0.81 / 0.79 — good in the middle. **The top bucket is
overconfident: 0.90 predicted, 0.70 actual.** Read >0.85 as "likely", not
"certain". Isotonic calibration would fix it and needs more than 300 sessions
to fit honestly.

> **2026-08-24 (3) — that last paragraph was measured on too short a window and
> is wrong.** Re-run over the full 900 walk-forward bars
> (`scripts/regime_horizon_experiment.py`), the top bucket is fine — 0.895
> predicted vs **0.906** realised, n=406 — and the *bottom* is the biased end:
> below 0.55 it predicts 0.487 against a realised **0.370**. That gap widens the
> nearer you get to today (+0.012 early, +0.110 mid, +0.243 late), which is what
> the 300-bar window was actually seeing: it put the whole degrading stretch
> under a magnifying glass and read a **period**-specific miss as a **level**-
> specific one. The lesson generalises past this number: a calibration curve
> fitted on the most recent slice of a non-stationary series measures the slice.
>
> Direction matters more than size here. A low reading **overstates** survival,
> so "50%" means less than half — a reader who trusts it sizes on a call that
> holds ~37% of the time. The hedge in `confidence_phrase()` moved accordingly:
> it fires below 0.55 and points downward. The high end carries none.
>
> **And no calibrator ships.** Isotonic and Platt were both fitted walk-forward
> (train on the past, score the next 100 bars) against raw: raw wins the mean
> Brier — 0.1464 vs 0.1540 isotonic, 0.1479 Platt — and each method wins some
> folds. A calibrator that loses out of sample is a fitted layer that costs
> money. The mitigation stays a sentence, on purpose.

### 25.3 Filtered, not smoothed — this closes §20.3 P1-4

P1-4: *"Regime labels are back-painted — Viterbi re-decodes the whole history
each run, so yesterday's label can change. Use the filtered posterior for the
last bar."*

`predict_proba` over the whole panel is forward-backward, so it re-decodes
history with hindsight. The last bar of a **prefix** has no future to smooth
over, so `predict_proba(X[:t+1])[-1]` *is* the filtered posterior — using
public API only (hmmlearn 0.3.3 has no `_do_forward_pass`).

### 25.4 The heuristic fallback was lying too

It returned hardcoded 0.6 / 0.6 / 0.5 / 0.5 — four made-up numbers wearing the
same field name as a measured one. It now reports the share of the last 10
sessions carrying the same label: the same question the HMM path answers,
measured directly, so the two are comparable.

This matters more than it looks: **`hmmlearn` was absent from the interpreter
running pytest** while production resolves `.venv` through `uv run`, where it is
installed. Every regime test before 2026-08-24 exercised the fallback while the
scheduled job ran the HMM.

### 25.5 A correction, and the narrower defect underneath it

Mid-investigation this session I claimed `config.DATA_SOURCE = KBS` answers
"VNINDEX" with ~1.79 and that this poisoned the classifier. **Both halves were
wrong.** Measured: KBS returns 1784.24 and VCI 1784.29 for the same day *when
given a date range*. And `classify_regime` overwrites `macro_df` with
`fetch_vnindex_daily()` before use, so `macro_anchors.vnindex` never reached the
classifier at all.

The real defect is narrower and still worth fixing. `MacroService._fetch_vnindex`
asked for `today..today`; one bad read on 2026-04-16 returned 1.82; and
`ingest_now`'s carry-forward — which **cannot distinguish a missing value from a
wrong one** — copied it into the next 613 of 623 rows. Fixed with a 10-day
window plus `VNINDEX_MIN_PLAUSIBLE = 200.0`, so a bad read returns None and
carry-forward keeps the last *good* value. The 613 existing rows are left as-is
and marked `ponytail:`: nothing reads that column, so a backfill would be
tidying, not repair.

### 25.6 The wording — closed 2026-08-24 (late)

The four stance strings in `generate_report.py` plus the banner and the plain
-text body rendered `"HMM confidence {:.2f}"`. After the rewrite they printed
0.65 instead of 1.00, which is the intended change and also the dangerous one:
the word "confidence" invites a reader to size on it, and the number is no
longer a confidence. It is P(this label survives 5 sessions).

`analysis.regime.confidence_phrase()` is the one renderer now — six call sites
across the banner, the memo and the email body:

```
was:  Tape đang risk-on (HMM confidence 0.65)
now:  Tape đang risk-on (~65% khả năng giữ 5 phiên tới)
```

**It lives in `analysis/regime.py`, not in the report generator**, and that
placement is the point: the sentence is a property of the formula, so whoever
changes what the number means owns the words describing it. It is also the only
way it could be tested — `generate_report.py` is 1,629 module-level lines that
send mail on `import` (§20.3 P3-2).

~~Above 0.85 the phrase appends a hedge.~~ **Below 0.55** — see §25.2's
correction. The direction is pinned by
`test_the_phrase_hedges_at_the_low_end_not_the_high_end`, which asserts the
*side* rather than the boundary, so putting it back on the high end fails a test
instead of shipping.

### 25.7 `CONF_HORIZON` — derived 2026-08-24 (3), and the pooled answer rejected

It was an assertion for months. `scripts/regime_horizon_experiment.py` walks the
filtered posterior over 900 bars and scores every horizon by Brier skill against
a base-rate forecast.

Pooled, skill rises to a flat plateau at H=8-13 (+0.207…+0.212) and **H=13
wins**. Split in thirds it does not:

| H | early | mid | late (2025-06 → 2026-08) |
|---|---|---|---|
| 5 | +0.223 | +0.229 | **+0.060** |
| 8 | +0.262 | +0.224 | −0.003 |
| 13 | +0.172 | +0.297 | −0.020 |
| 20 | +0.161 | +0.298 | **−0.166** (AUC 0.510 — a coin) |

The entire H≥8 advantage comes from the middle stretch. **5 is the only horizon
positive in all three thirds**, so it stays — not because it is optimal, but
because it is the longest horizon that has not been shown to break. Same
methodological point as §16.12: pooling let one strong stretch mask a recent one
that matches random.

AUC is ~0.80 across H=1-13 and carries no opinion — it ranks, it does not
calibrate, which is why skill is the deciding metric here.

### 25.9 The late-third degradation — diagnosed 2026-08-24 (4)

§25.8 flagged it as the highest-value open question: the horizon sweep here and
the §16.1 stealth gate (§16.13) both fall apart over the same recent stretch,
and *"a defect common to two unrelated models is more likely the tape or the
data than either model."* `scripts/late_period_diagnosis.py` runs the four
checks. Result: **it is the tape, and the calendar was a proxy for it.**

**Not data.** Every 2026 quarter carries 15 sectors, ~0 missing `close_idx`,
96-100% non-zero `foreign_net`. Coverage matches the years that work. The one
thin quarter in the panel is 2023Q1 (36% missing closes), at the opposite end.

**Not a stale transition matrix.** `transmat_` is fitted once over the whole
panel, so it encodes average persistence — a plausible reason the late third
overpredicts survival by +9.3pt (0.695 predicted vs 0.602 realised). Testing it
by re-estimating transitions on a trailing window, emissions untouched:

| window | late bias | late Brier | late AUC | Brier, all 900 |
|---|---|---|---|---|
| whole panel (shipped) | **+0.093** | 0.2266 | **0.678** | **0.1607** |
| 250 bars | −0.045 | 0.2196 | 0.665 | 0.1916 |
| 500 bars | **+0.018** | 0.2289 | 0.637 | 0.1887 |
| 120 bars | −0.103 | 0.2615 | 0.583 | 0.2118 |

A trailing window fixes the *bias* and costs *discrimination* and overall Brier.
So the late failure is not miscalibration that a fresher matrix repairs — it is
**lost discrimination**: late AUC 0.673 against 0.816/0.828 earlier. Nothing
ships from this check; it is recorded so nobody re-runs it hoping.

**It is volatility.** Bucketing all 900 bars by 20d VNINDEX vol, ignoring date:

| vol tercile | n | base rate | AUC | share of rows in the late third |
|---|---|---|---|---|
| low | 298 | 0.836 | **0.827** | 0.12 |
| mid | 298 | 0.735 | 0.790 | 0.46 |
| high | 299 | 0.592 | **0.694** | 0.42 |

Monotone, and the high-vol bucket is spread across periods rather than being a
relabelling of "late". Crossed both ways, low-vol *late* bars still score 0.699
while high-vol *early* bars score 0.619 — vol tracks the failure, the calendar
does not. 2026 is simply where the high-vol bars concentrate (§16.13's amended
table: ann vol 0.42 vs 0.21-0.29).

**What this means, stated so it is not over-read.** A regime model is least
certain when regimes are least stable, which is not a defect — it is the
model reporting a harder problem. The honest response is to let confidence fall
in choppy tape, which it does. But it means:

- **`CONF_HORIZON` is not one number.** 5 is the longest horizon positive in all
  three thirds *pooled across vol*; in the high-vol bucket even 5 is marginal.
  A vol-conditioned horizon is the obvious next experiment and is **not** shipped
  — it needs its own walk-forward, and §25.2 is the standing warning about
  fitting a layer on a recent slice.
- **§16's story is different from this one.** The stealth gate's 2026 collapse
  shares a cause *class* (the tape) but not the mechanism: §16.13's breakout
  test is pinned to 2×ATR, so a rising ATR raises the bar exactly when the moves
  it must clear are shrinking. That is a definition that moves with what it
  measures — a real defect in the metric, worth fixing on its own terms, and it
  is not fixed by anything here.

### 25.10 Open
- **A vol-conditioned `CONF_HORIZON`** (§25.9). Measured as needed, not shipped.
- ~~**§16.13's 2×ATR breakout definition scales with the tape it measures.**~~
  **Measured 2026-08-24 (5) — the suspicion was wrong and the real defect is
  worse. See §16.15.**
- `CONF_HORIZON` should be re-measured when the panel grows; 900 bars split
  three ways is 300 per cell, and §25.9 now wants it split by vol as well.
