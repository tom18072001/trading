# ARCHITECTURE — VN Sector Money-Flow Rotation System

> Target architecture for the approved redesign (2026-04-08). Replaces the legacy
> 170-symbol prediction system. Read this file before any development. Every
> change must be logged in `MODIFICATION_LOG.md`.

## CHANGELOG
- **2026-09-25 — 4 and 8 weeks are the only holding periods; the T+ mode and
  T+2 settlement are gone** (Tom: *"bỏ T+2, chỉ sử dụng 4 tuần và 8 tuần"*).
  One constant, `config.HOLD_SESSIONS = (20, 40)`, feeds the sell window, the
  bulletin, the benches and the sector backtest. Contract changes:
  `POST /api/sectors/backtest` drops `settlement_lag` and takes
  `hold_sessions ∈ {20, 40}` (a `Literal` — a 3 is a 422); the result drops
  `settlement_lag` and gains `hold_sessions`, `rebalance_count` and
  `benchmark_origin`. The engine re-cuts the book on session 1 and every
  `hold_sessions` after it instead of every session, decides from what was
  published the session **before** (signals go out at 17:00, after the close
  they used to be filled at), carries the last signal set across sessions that
  published none (it used to sell everything), and refuses a VNINDEX series
  outside 200–5,000 or covering < 90% of the sessions — trying the price
  panel's `^VNINDEX` before the flagged sector mean. `/api/state/positions/pnl`
  rows lose `sellable_on` (T+2); the window is `sell_range.sell_from/sell_by`.
  `PickEntry` gains `sell_from` / `sell_by` (holiday-aware,
  `picks_scoring.hold_window`). `/api/insight/daily` no longer builds "T+3-5"
  cards from ranker sectors when the snapshot is empty — an empty snapshot is
  an empty list. `PickProfile.TPLUS` and seven unused T+3 trade schemas in
  `api/schemas.py` were removed. No schema change.
- **2026-08-24 (3) — Exit price, realised P&L, and a measured `CONF_HORIZON`.**
  Contract change: `/api/state/*` gains `POST /state/positions/{symbol}/close`
  and `GET /state/positions/realised`, and `trading_state.json` gains a
  `closed` list (a key, not a migration — `_read()` merges `_DEFAULT`, so every
  file written before today loads unchanged). `close_position()` is deliberately
  distinct from `remove_position()`: the latter deletes, which is right for a
  mis-click and wrong for a sale, and until now they were the same operation —
  so the system could not answer whether its own picks made money. Realised P&L
  is **net of the §18.2/10 costs** (`BACKTEST_FEE_BPS` per side +
  `BACKTEST_SELL_TAX_BPS` on proceeds, imported from `config.py` rather than
  retyped, ~0.40% round trip), so the book and the backtest cannot disagree.
  `/positions/realised` is a literal sharing a prefix with `/positions/{symbol}`
  — same route-ordering trap as `/positions/pnl`, pinned by a test.
  Also `analysis/regime.py`: `CONF_HORIZON = 5` stops being an assertion.
  `scripts/regime_horizon_experiment.py` walks the filtered posterior over 900
  bars and reports Brier skill per horizon, split in thirds; pooled it picks
  H=13, but that win comes entirely from the middle stretch and every horizon
  above 5 goes negative on the last third. 5 is the longest horizon that stays
  positive throughout. The same script rejects calibration: isotonic and Platt
  both lose to raw out of sample, so no calibrator ships. See `CLAUDE.md` §25.2
  and §25.7.
- **2026-08-24 (2) — Regime confidence: a collapsed model reporting certainty.**
  Behaviour change, no schema change, no contract change (`GET
  /api/sectors/regime` keeps its shape; the `confidence` *value* now spans
  0.46–0.91 instead of sitting at 0.9999998). Three compounding defects in
  `analysis/regime.py`: features fed raw to a diagonal Gaussian HMM collapsed
  3 of 4 states to hmmlearn's ceiling covariance — **with one live state the
  posterior is 1.0 by construction** — on only ~111 bars of history, and the
  number reported was the state posterior, which answers "which state is this
  bar in" rather than "is this call worth acting on". Now: standardised
  features, 1500 days of history (`services/rotation_model_service.py`), a fit
  that **refuses** to publish when >1 state is empty, and `confidence` =
  P(label holds in 5 sessions) via the transition matrix. Uses the **filtered**
  posterior of the last bar, which closes §20.3 P1-4 (labels were back-painted
  by forward-backward decoding). The heuristic fallback's hardcoded
  0.6/0.6/0.5/0.5 is now a measured label-persistence share. Also
  `services/macro_service.py`: both VNINDEX fetchers get a date range and a
  `VNINDEX_MIN_PLAUSIBLE = 200.0` floor — one bad single-day read on 2026-04-16
  was laundered into 613 of 623 `macro_anchors` rows by `ingest_now`'s
  carry-forward, which cannot tell a missing value from a wrong one. See
  `CLAUDE.md` §25.
- **2026-08-24 — Position book gains editing and mark-to-market.** Contract
  change: `/api/state/*` gains `PATCH /state/positions/{symbol}` (partial edit;
  `None` leaves a field, a negative clears it) and `GET
  /state/positions/pnl`. No schema change — `data/trading_state.json` already
  carried `entry_price`/`qty`, they were just unreachable after creation.
  `update_position` is deliberately distinct from `add_position`, which
  restamps `opened_at` and drops the symbol from the watchlist. The P&L handler
  prices from `PicksUniverseService().peek()` — never `get_snapshot()`, which
  would block behind the 18 req/min KBS throttle — and returns `priced` and
  `count` separately so a partial mark cannot be read as the book's P&L.
  Unrealised only; no exit price is stored.
- **2026-08-23 (late, 6) — §16.1 stealth gate: AND → score.** Behaviour change,
  no schema change. `analysis/stealth.py` stops requiring all five §16.1
  conditions and emits a `conditions_met` score (0-5); stealth fires at
  ≥ `STEALTH_MIN_CONDITIONS` (default 4) held ≥ `STEALTH_MIN_SESSIONS`
  (default 3). A condition that cannot be evaluated is dropped from **both**
  numerator and denominator, so missing data cannot silently raise the bar —
  the failure mode that let an all-zero `foreign_net` ship a 3-condition gate.
  Measured cause: the conjunction was unreachable (longest all-five run across
  15 sectors in 3.5 years = 2 sessions), so `accumulation_age` had been 0 on
  every row ever written. Contract change on `GET /api/stealth/active`: new
  `min_conditions` query param, new `atr_rank` field per sector, and
  `min_sessions`/`min_conditions` defaults now **imported from
  `analysis.stealth`** rather than retyped — the endpoint and the offline
  scanner had been gated differently. Its cond4 also stops comparing a raw
  `atr_pct` (~0.006) to a threshold named `atr_rank_max` (0.5), which had been
  passing for free on all 15 sectors. Closes §20.3 P0-5 and P1-1; the gate
  fires but does **not** meet §16.11 (median lead 3 days vs ≥10 target) — see
  `CLAUDE.md` §16.11.
- **2026-08-23 (late, 5) — Global filter, stealth presets, CSV, send-report.**
  Contract change: `/api/state/*` gains `POST /state/report/send` and
  `GET /state/report/status`, backed by the new `services/report_runner.py`.
  It runs `generate_report.py` as a **subprocess**, not an import — the script
  is 1,629 module-level lines driven by `sys.argv` with no `main()`, so an
  import would send mail as an import side effect. One run at a time; a second
  call returns `already_running` rather than starting a second send. It lives
  under `/state` because it is an operator action, the same category as the
  kill-switch and the position book, not a new domain. No schema change.
  Frontend gains three shared modules (`lib/filters.tsx`, `lib/glossary.tsx`,
  `lib/stealthPresets.ts`); table filter, sort and stealth-threshold state now
  live in the URL rather than component state.
- **2026-08-23 (late, 4) — Backtest controls; and `flow_z` was `flow_raw` in disguise.**
  Contract change on `POST /api/sectors/backtest`: the request model gains
  `strategy` (a Pydantic `Literal` — an unvalidated string used to fall through
  to the `flow_raw` branch) plus bounded per-run overrides for `fee_bps`,
  `sell_tax_bps` and `settlement_lag` (replaced by `hold_sessions` 2026-09-25); the response's `equity_curve` gains a
  `benchmark` point per row, so the chart can draw VNINDEX instead of leaving
  "did I beat the index" as mental arithmetic. Everything else the service has
  modelled since 2026-08-22 (§18.2/7–10 frictions, `trade_log`, root capture,
  band skips) was already returned and simply had no type in `client.ts` and no
  renderer — now both. **The defect this surfaced:** `_cross_sectional_z`
  computes `(v − mean)/sd` within the same day the rows are then sorted in, a
  positive affine map, so `flow_z` produced the raw-VND permutation every day —
  the two "different" baselines returned an identical −25.06% over 330 trades.
  `flow_z` now ranks on `flow_z20` (per-sector z vs. its own history). §20.2's
  P0-4 row was accordingly half true; see `CLAUDE.md` §23.
- **2026-08-23 (late, 3) — Operator state: kill-switch, position book, watchlist.**
  New layer, new contract. `services/trading_state.py` is the first piece of
  state the *operator* owns rather than the model: a single JSON file
  (`data/trading_state.json`, gitignored) holding the halt flag, the capital
  slider, the marked positions and the watchlist, exposed as `/api/state/*`
  (router 13). `§18.4/20`'s kill-switch stops being env-only —
  `SectorSignalService.publish()` now ORs the `TRADING_HALT` env var with a
  runtime flag the UI can toggle, reading it once before the loop. Deliberately
  a file and not a table: three keys do not justify a migration, and the
  scheduler process has no HTTP client so it must read the flag directly. On the
  frontend, `lib/tradingState.ts` is a `useSyncExternalStore` module store —
  the halt banner (Layout), the toggle (Risk) and the mark buttons (Daily
  Insight) are three trees that never meet. Layout also gained an app-wide
  data-age bar; `FlowMonitorPage`'s local copy was removed.
- **2026-08-23 (late) — Nav merged 9 → 5, §10 rewritten against the running app.**
  Nine nav doors became five, with the merged halves as URL-backed tabs
  (`components/Tabs.tsx`, `?tab=`): Dòng tiền = Monitor + Sector Detail,
  Luân chuyển = Stealth + Rotation, Rủi ro & Vị thế = Risk + Pulse, Nghiên cứu
  = Xếp hạng + Regime + Backtest. All seven pre-merge paths redirect. §10 of
  this document had described a `features/*` layout that was never built and
  listed `/backtest` and `/regime` as deleted when both work — replaced with
  what actually ships. Earlier the same day: the four decision pages moved onto
  the `@theme` tokens and `lib/actions.tsx` became the single action vocabulary
  (`CLAUDE.md` §22.8–22.9).
- **2026-09-16 — The per-ticker ranking score changed shape, and with it a
  contract.** `picks_scoring.score_ticker` returned an `int` in 0..7 counting
  trend-continuation conditions; it now returns a **`float`** in roughly −9..+7
  with a −20 floor for names whose uptrend cannot be confirmed. `TickerRow.score`
  and `PickEntry.score` are `float`, and `TickerRow` carries three new inputs
  (`rsi_2`, `ret_1d`, `price_to_sma_200`). Anything formatting the score with
  `:+d` raises — two such sites in `generate_report.py` were fixed, and the
  frontend renders `toFixed(1)`. The shortlist tie-break is no longer 20d dollar
  volume (measured harmful, not neutral) but the symbol: stable, and not a
  second unmeasured factor. The OHLCV lookback in `PicksUniverseService` widened
  110 → 400 calendar days so an SMA200 exists; the call **count** is unchanged.
  Reasoning and every measurement in `CLAUDE.md` §26.
  **Later the same day a second contract landed on top:** the shortlist order
  is no longer a function of one row. `PicksUniverseService` gained a
  cross-sectional **Stage E** that runs once per build over the whole
  universe and writes `TickerRow.rank_score` from
  `picks_scoring.blended_rank_scores(scores, obv_trends)` — a 50/50 rank
  blend of the per-row score and on-balance-volume trend. `_rank_key` reads
  `rank_score` and falls back to `score` when the pass has not run, so a row
  built outside the pipeline still sorts. The DISPLAYED score is unchanged,
  which is deliberate: the score decides admission (`MIN_BUY_SCORE`), the
  blend decides order. Callers must gate before ordering — with equal
  weights the blend can tie the best score to the worst. `TickerRow` also
  gained `obv_chg20`. See `CLAUDE.md` §26.9.
- **2026-08-23 — Frontend defect pass + docs purge + repo reorg.** Seven measured
  frontend defects fixed (A1–A7 in `MODIFICATION_LOG.md` 2026-08-23). The one
  that mattered: `PicksUniverseService` was the only stage of the daily pipeline
  with **no durable store**, so every backend restart emptied the homepage until
  someone clicked Refresh. It now persists to `data/snapshots/picks_universe.json`
  and reloads on a cold cache; a corrupt file degrades to the existing empty-state
  banner and never raises. Rotation Map repointed from `/api/rotation/*` (whose
  pair detection is structurally empty, not threshold-limited) to the correct
  `/api/sectors/handoff`. Flow Pulse exposure repointed from the `pulse.py` stub
  to `sectors_risk.py`. Docs: 7 outdated files hard-deleted (two `.docx`
  describing the retired 170-symbol system, `docs/DAILY_REPORT_AUTOMATION.md`,
  `docs/CHANGELOG.md`, `report/template.html`, 5 orphan snapshots, a one-off
  notifier), two rewritten and moved into `docs/reference/`, dated reviews moved
  into `docs/reviews/`. 179 MB of untracked scratch removed. **No Python file
  moved** — `scripts/jobs/*.bat` run from the repo root under Task Scheduler.
- **2026-04-22 — Phase 16: legacy sweep + scheduler sync.** (a) Second recipient
  `hill.nguyen.1373@gmail.com` added to `REPORT_EMAIL_TO`. (b) Scheduled jobs
  rewritten from scratch: `main.py` now has one CLI flag per §8 job, matching
  `.bat` wrappers live under `scripts/jobs/`, and `scripts/cleanup_scheduled_tasks.ps1`
  is a full **sync** script (unregister every stale task + register the 8 canonical
  jobs). (c) **90 dead files moved to `_trash_20260422/`** — 71 scratch root files,
  17 scratch `scripts/_*`, 6 stub services (`data_service`, `ml_service`,
  `trade_service`, `feature_service`, `sector_service`, `snapshot_service`),
  `analysis/sector_analysis.py`, `models/prediction_model.py`,
  `generate_sector_flow_enhanced.py`, `send_email_report.py`,
  `scripts/daily_stale_report.py`, plus 2 old templates. All 78 tests still
  green after every wave. OpenClaw references purged.
- **2026-04-23 — SecV5: unified picks briefing.** `generate_report.py` replaces
  `generate_secv4.py` as the active daily-email generator. Reason: Daily Insight
  page and SecV4 email were recommending different tickers — Daily Insight
  renders `snapshot.top_buys`/`top_sells` directly (no ranker gate) while SecV4
  filtered through the ranker BUY/ACCUMULATE gate and dropped everything when
  the ranker stayed silent. SecV5 computes a **union**, de-duped by symbol,
  each entry tagged `source ∈ {BOTH, DAILY_INSIGHT, RANKER}` so the email and
  dashboard always agree. Adds an Expert Trader Memo section at the top of
  the HTML + PDF and a plain-text email body (buy symbols + reasons + Dashboard +
  news links). Default recipients grown to 3 (that hardcoded list was removed
  2026-08-24 when the repo went public — `REPORT_EMAIL_TO` only). Scheduler contract
  unchanged (same 17:00 slot in `scripts/jobs/job_sector_signal_publish.bat`;
  bat now calls the new generator). The two older generators were left on disk
  as manual rollback paths at the time — **both deleted 2026-06-18**, and the
  generator itself was renamed `generate_report.py` on 2026-08-22 (`CLAUDE.md`
  §21). To evict a stale Task Scheduler entry still pointing at a deleted
  generator: `scripts/pause_legacy_email_task.ps1`. See `MODIFICATION_LOG.md`
  entry 2026-04-23.
- **2026-04-18 — Phase 12: OpenClaw retired, TraderAgent "Minh" in.** In-process
  agent replaces the external OpenClaw worker for both the Gmail briefing (the
  report generator, today `generate_report.py`) and the `/api/insight/refresh`
  endpoint. See `specs/trader_agent.md`. (The transport was `claude_agent_sdk`
  then; it is plain HTTP to 9Router since 2026-07-20 — `CLAUDE.md` §14.)
- **2026-04-17 — PicksUniverseService introduced.** One dynamic HOSE universe
  (from vnstock Listing) replaces the per-script reads of `_legacy_stock_*` in
  the report generators of the day (SecV3/SecV4, both deleted 2026-06-18) and
  `api/routers/insight.py`.
- **2026-04-09 — Phase 15: Trader-First View Redesign (doc-first, intent only).**
  7 views → 5. Delete `/backtest` and `/regime`, merge `/ranking` into `/flow`. New
  `/rotation` (Sankey + pair table), `/stealth` (5-cond gate + Gantt), `/pulse`
  (live tape replaces Risk), `/insight` (LLM narrative replaces Briefing). Binding
  contracts: interval toggle `1D/1W/2W/1M/1Q` (server-side resample), configurable
  thresholds via `ThresholdInput` + localStorage, feature-sliced frontend folder
  rename. Blocker in scope: real `close_idx` backfill removes `STEALTH_SYNTHETIC_CLOSE`
  escape hatch. See `CLAUDE.md` §17 *(mục này chưa từng tồn tại — CLAUDE.md nhảy từ §16 sang §18)* and `specs/REDESIGN_PHASE15.md` + 6 feature specs.
  No code landed yet — this changelog entry is intent. Legacy `pages/*.tsx`, the
  Backtest/Regime/Ranking pages, and their matching services/routers are scheduled
  for deletion as each replacement feature ships.
- **2026-04-08 — Phase 8: Sector Money-Flow Redesign (APPROVED).** Architecture
  rewritten end-to-end. Legacy symbol-prediction stack archived (`_legacy_`
  prefix on tables, retained until 2-week shadow run completes). New primary key
  is `sector_code`, not `symbol`. See `CLAUDE.md` for the strategy spec.
- Phase 1–7 history: `docs/CHANGELOG.md` was deleted 2026-08-23 (it had been frozen and self-declared LEGACY since 2026-04-08). `MODIFICATION_LOG.md` is the only change log.

---

## 1. SYSTEM OVERVIEW

**Mục đích:** End-to-end pipeline ingest dòng tiền theo 15 ngành VN, dự đoán xoay vòng (rotation), publish tín hiệu BUY/SELL ngành cho nhà đầu tư.

### Core Pipeline
```
vnstock (proxy basket OHLCV + foreign flow)
  → sector_ingest_service (aggregate → drop raw)
  → sector_flow_ts / sector_flow_daily
  → flow_feature_service
  → rotation_model_service (HMM regime + LightGBM ranker)
  → sector_signal_service → sector_signals
  → picks_universe_service (per-ticker BUY/ACCUMULATE from sector signals)
  → trader_agent "Minh" (in-process; HTTP to 9Router, CLAUDE.md §14)
  → generate_report.py → Gmail briefing (sole generator)
  → FastAPI /api/* → React feature-sliced frontend
```

### Functional Domains
| Domain | Responsibility | Entry Points |
|---|---|---|
| Sector Ingestion | Pull proxy OHLCV + foreign flow, aggregate to sector level | `services/sector_ingest_service.py`, `services/fast_ingest.py` |
| Macro Ingestion | VNINDEX, USD/VND, Brent, US10Y, Gold | `services/macro_service.py` |
| Flow Features | Engineer features from flow + macro | `services/flow_feature_service.py`, `analysis/flow_aggregation.py`, `analysis/flow_handoff.py` |
| Rotation Model | HMM regime + LightGBM ranker | `services/rotation_model_service.py`, `analysis/regime.py`, `models/rotation_ranker.py` |
| Stealth detection | §16.1 five-condition gate + scoring | `analysis/stealth.py` |
| Signal Publish | Daily ranking → `sector_signals` DB rows | `services/sector_signal_service.py` |
| Picks Universe | Dynamic HOSE universe → per-ticker BUY/ACCUMULATE/SELL picks | `services/picks_universe_service.py`, `services/picks_scoring.py`, `services/picks_news.py` |
| Backtest (retrofit) | Long/short sector basket simulation | `services/backtest_service.py` |
| Risk (retrofit) | Sector VaR/exposure/drawdown + stop-loss sentinel | `services/risk_service.py` |
| Trader Agent | In-process Claude agent ("Minh") authoring the daily narrative | `services/trader_agent.py`, `services/insight_refresh.py` |
| Email Report | Daily unified-picks HTML + PDF → Gmail | `generate_report.py` (sole generator since 2026-06-18) |
| API | FastAPI, 12 routers | `api/main.py`, `api/routers/*` |
| Frontend | React 19 feature-sliced pages (Phase 15) | `frontend/src/features/*` |

---

## 2. TECHNOLOGY STACK (inherited)
Python 3.11, FastAPI, SQLAlchemy 2.0 + SQLite (WAL), vnstock ≥3.2, LightGBM, hmmlearn, scikit-learn, React 19 + Vite + TypeScript, Tailwind. Models persisted to `models/saved/`.

---

## 3. DIRECTORY STRUCTURE

> Enumerated from disk, not remembered. **No "as of" stamp on purpose**: a fixed
> date in a living document ages without anyone noticing — this section carried
> `as of 2026-04-22` for four months while listing three deleted paths, six
> missing services and a test count off by 186. If you change the tree, change
> this. The cheap check is `ls`, and `scripts/_doc_audit.py` covers the API
> half of the same problem.

```
Trading/
├── CLAUDE.md                         # Approved redesign spec (source of truth)
├── docs/doctrine/                    # Chứng cứ tách khỏi CLAUDE.md (§27), một file một mục §
├── daily_watch/                      # Module riêng (2026-09-16): báo cáo, đề xuất mua, đề xuất bán.
│                                  #   Đọc services/, không bao giờ ngược lại (có test giữ).
├── ARCHITECTURE.md                   # This file
├── MODIFICATION_LOG.md               # Append-only change log
├── README.md                         # Quickstart
├── config.py                         # SECTORS, PROXY_BASKETS, MACRO_TICKERS, RISK_CONFIG
├── main.py                           # CLI entry (one flag per §8 job)
├── generate_report.py                # Daily unified-picks email generator (the only one)
│
├── data/
│   └── data_fetcher.py               # vnstock wrapper (KBS/VCI/TCBS)
├── analysis/                         # pure functions — no DB, no IO
│   ├── flow_aggregation.py           # basket → sector aggregates + basket_return
│   ├── flow_handoff.py               # sector-to-sector rotation detection
│   ├── feature_engineering.py        # shared TA helpers
│   ├── regime.py                     # Gaussian HMM + confidence_phrase()
│   └── stealth.py                    # §16.1 gate + the breakout bar (§16.15)
│
├── models/
│   ├── rotation_ranker.py            # LightGBM lambdarank + purged/embargoed CV
│   └── saved/                        # pickled models + metadata (gitignored)
│
├── database/
│   ├── connection.py                 # SQLAlchemy engine (WAL pragmas)
│   ├── models.py                     # sector tables + picks_universe snapshot
│   └── migrations.py                 # migrations 1–12 (§11)
│
├── services/
│   ├── sector_ingest_service.py      # proxy OHLCV ingest + rollup
│   ├── fast_ingest.py                # async/batched variant (see §9 note)
│   ├── foreign_flow.py               # foreign buy/sell split + intensity
│   ├── macro_service.py              # macro_anchors row writer
│   ├── flow_feature_service.py       # flow features + §16.2 leading features
│   ├── flow/aggregation.py           # extracted aggregation helpers
│   ├── rotation_model_service.py     # HMM regime + ranker train/predict
│   ├── sector_signal_service.py      # publishes sector_signals; owns the halt read
│   ├── backtest_service.py           # sector-basket backtester (20/40-session book, fees, band)
│   ├── risk_service.py               # VaR + stop-loss sentinel (no cost model yet)
│   ├── picks_universe_service.py     # dynamic HOSE universe → per-ticker picks
│   ├── picks_scoring.py              # ranking score (measured, §26) + stop/target gate
│   ├── picks_news.py                 # vnstock company news fetch
│   ├── unified_picks.py              # union(DailyInsight, Ranker), de-duped
│   ├── trader_agent.py               # "Minh" — HTTP to 9Router (§14)
│   ├── insight_refresh.py            # async /api/insight/refresh runner
│   ├── report_runner.py              # subprocess driver for /state/report/send
│   ├── report/                       # the pure half of generate_report.py
│   │   ├── charts.py                 # matplotlib renderers
│   │   ├── data.py                   # the six SQL reads (cursor passed in)
│   │   └── format.py                 # formatters
│   └── trading_state.py              # operator state: halt / book / watchlist
│
├── api/
│   ├── main.py                       # FastAPI app factory, key guard, limiter
│   ├── schemas.py                    # pydantic models
│   └── routers/                      # 12 routers — see §9 for the endpoint map
│       ├── flow.py  insight.py  pulse.py  rotation.py  stealth.py
│       ├── sectors_flow.py  sectors_ranking.py  sectors_regime.py
│       ├── sectors_backtest.py  sectors_risk.py  sectors_handoff.py
│       └── state.py                  # operator state (file-backed, not DB)
│
├── frontend/                         # React 19 + Vite + TS — flat `src/pages/*.tsx`
│                                     # (NOT feature-sliced — see §10)
├── scripts/
│   ├── cleanup_scheduled_tasks.ps1   # FULL SYNC of Windows Task Scheduler (§8)
│   ├── register_report_task.ps1  pause_legacy_email_task.ps1
│   ├── smoketest.py                  # does THIS machine work — see README
│   ├── check_freshness.py            # DB staleness; smoketest imports its threshold
│   ├── check_db.py                   # integrity + schema diff
│   ├── backfill_3y.py  backfill_close_idx.py  backfill_foreign.py
│   ├── fix_close_idx.py  rebuild_features_after.py  replay_stealth.py
│   ├── stealth_leadtime_experiment.py    # §16.11/§16.15 bench
│   ├── regime_horizon_experiment.py      # §25.7 CONF_HORIZON sweep
│   ├── late_period_diagnosis.py          # §25.9 vol-tercile diagnosis
│   ├── _doc_audit.py                 # .md endpoints vs. the live openapi spec
│   ├── test_auth.py                  # a script, not a pytest file
│   ├── tasks/                        # older task-registration variants
│   └── jobs/                         # wrapper .bat per job + hidden-run shims
│       ├── _env.bat  run_hidden.vbs  run_hidden_wait.vbs
│       ├── apply_hidden_jobs.{bat,ps1}
│       ├── job_macro_ingest.bat  job_sector_intraday_flow.bat
│       ├── job_sector_eod_rollup.bat  job_regime_classify.bat
│       ├── job_rotation_train.bat  job_rotation_predict.bat
│       ├── job_sector_signal_publish.bat  job_sector_risk_sentinel.bat
│       ├── job_daily_watch.bat       # 2026-09-16: so + canh bao stop + shortlist
│       └── job_freshness_check.bat   # ORPHAN — written, never registered (§8)
│
├── specs/                            # one .md per feature + cross-cutting
├── docs/
│   ├── PATCHES.md                    # which plan is running / done
│   ├── reference/                    # ALGORITHM.md, GLOSSARY_VI.md
│   └── reviews/                      # dated code / optimization reviews
├── utils/                            # clock.py (market-local today, next_trading_day),
│                                     # vnstock_gate.py (rate limit), vn_api.py
├── report/                           # rendered HTML / PDF / templates; `jobs/` sub-logs
├── .github/workflows/ci.yml          # clean-clone install + tests (§ README)
└── tests/                            # 342 pytest cases (§19)
```

**Deleted, in case an old doc still points at them:** `analysis/charts/` (moved
to `services/report/charts.py`), `scripts/create_key.py`,
`scripts/start-tunnel.bat`, `scripts/seed_data.py` (2026-08-24 — it seeded the
retired 170-symbol `stocks` table through a module gone since Phase 16),
`requirements.txt` (2026-08-24 — a manifest missing `hmmlearn` and
`matplotlib`).

---

## 4. LAYER ARCHITECTURE
```
┌─────────────────────────────────────────────┐
│  FRONTEND — 5 Sector Pages (React 19)        │
│  Flow / Ranking / Regime / Backtest / Risk   │
└──────────────────────┬──────────────────────┘
                       │ HTTP/JSON
┌──────────────────────▼──────────────────────┐
│  API — FastAPI sectors routers + agent       │
└──────────────────────┬──────────────────────┘
                       │
┌──────────────────────▼──────────────────────┐
│  SERVICE LAYER                                │
│  ingest │ macro │ features │ model │ signal  │
│  backtest │ risk                              │
└──────┬───────────────────────────┬───────────┘
       │                           │
┌──────▼──────────┐         ┌─────▼────────────┐
│ ANALYSIS LAYER  │         │ MODEL LAYER       │
│ flow_aggregation│         │ rotation_ranker   │
│ regime          │         │ HMM regime        │
└──────┬──────────┘         └─────┬────────────┘
       │                          │
┌──────▼──────────────────────────▼───────────┐
│  DATA LAYER — sector tables + macro          │
│  vnstock + macro fetchers                    │
└──────────────────────────────────────────────┘
```

### 4.1 Service-layer boundaries — enforced, not aspirational (2026-08-24)

The box labelled SERVICE LAYER above is 17 modules, and until now the arrows
inside it were folklore. They are a **contract** now, declared in
`tests/test_module_boundaries.py` and checked by an AST walk on every test run.

| layer | modules | may import from |
|---|---|---|
| `ingest` | `sector_ingest_service` · `fast_ingest` · `macro_service` · `foreign_flow` | — |
| `features` | `flow_feature_service` · `flow/` | `ingest` |
| `decide` | `rotation_model_service` · `sector_signal_service` · `picks_universe_service` · `picks_scoring` · `picks_news` · `unified_picks` · `backtest_service` | `ingest`, `features`, `decide` |
| `book` | `trading_state` · `risk_service` | — |
| `report` | `report_runner` | `decide`, `book` |
| `agent` | `trader_agent` · `insight_refresh` | `decide`, `agent` |

Two rules beyond the table:

- **No module under `services/` may import `api`, `main` or `generate_report`.**
- **Every `from services.X import …` anywhere in the repo must resolve.**

Non-`services` packages — `config`, `database`, `analysis`, `utils`, `models` —
are unrestricted. They are shared leaves, not layers; gating them would be
ceremony.

**The table is descriptive first.** It was read off the graph that already
existed rather than imposed on it, so no module moved and no import path
changed. That is the finding, not a shortcut: the service layer was already a
shallow DAG (17 modules, max depth 2). What it lacked was a way to *stay* one.

**Two real defects fell out on the first run:**

1. `services/insight_refresh.py` did `from api.routers.insight import
   insight_daily` **inside** a function, and `api/routers/insight.py` imports
   `insight_refresh` — a genuine `services → api → services` cycle, quiet only
   because both ends were lazy. Its own module docstring claimed "this file
   deliberately has no dependency on FastAPI". Inverted: the router now calls
   `insight_refresh.set_payload_builder(insight_daily)` at import time, so the
   arrow points one way and stage 4 degrades to the refresh block alone when no
   builder is registered (a unit test, or a script importing the runner without
   the API).
2. `scripts/seed_data.py` imported `services.data_service`, deleted 2026-04-22
   in Phase 16 — broken for four months because nothing runs it. The whole
   script targeted the retired 170-symbol `stocks` table, so it was deleted
   rather than repaired. Ruff cannot catch this: `F401` finds imports that are
   *unused*, not imports that are *unresolvable*.

The `book` layer's emptiness is load-bearing rather than tidy, and has its own
test saying why: `trading_state` holds the kill-switch, and the scheduler reads
it straight off disk with no HTTP client (`CLAUDE.md` §22.10). If it grew a
dependency on the model layer, halting the 17:00 publish would start to require
the model layer to import cleanly — exactly the situation you are in when you
want to halt it.

---

## 5. DATABASE SCHEMA

Read off the live `vnstock_market.db`, not the target design. **23 tables**;
row counts are a snapshot (2026-08-26) and are here to show which tables are
*written* — an empty one with a writer and an empty one without are very
different facts.

### Sector core

```
sectors                (sector_code PK, name, description, is_active, created_at)   15
 └─→ sector_constituents (id, sector_code, symbol, weight, active)                  75

sector_flow_ts         (id, sector_code, time, net_dollar_flow, up_vol, down_vol,
                        foreign_net, breadth_sma20, breadth_sma50,
                        rs_vnindex_5d, rs_vnindex_20d, atr_pct,
                        foreign_buy_val, foreign_sell_val, foreign_intensity,
                        close_idx, basket_return)                              16,200

sector_flow_daily      (id, sector_code, date,
                        open_idx, close_idx, high_idx, low_idx, return_1d,
                        net_dollar_flow, foreign_net, up_down_vol_ratio,
                        breadth_sma20, breadth_sma50,
                        rs_vnindex_5d, rs_vnindex_20d, rs_vnindex_60d,
                        atr_pct, vol_20d,
                        flow_z20, flow_z60, foreign_streak, foreign_hit_20d,
                        stealth_score, flow_price_divergence, accumulation_age,
                        foreign_buy_val, foreign_sell_val, foreign_intensity)  13,500

macro_anchors          (id, time, vnindex, usdvnd, brent, us10y, gold)            656
sector_regime          (id, date, regime_label, confidence, model_version)        840
sector_signals         (id, date, sector_code, score, rank, action,
                        persistence_ok, model_run_id)                             615
```

`sector_flow_daily` is 28 columns, not the "daily rollups" the earlier version
of this section elided. The last eleven are §16.2's leading features plus
migration 10's foreign split — they are what the stealth gate and the ranker
read, so a doc that hides them hides the model's inputs.

**Two tables were dropped here on 2026-08-26 (migration 12), and the reason is
worth keeping:** `sector_accumulation_events` (migration 9) and
`sector_flow_handoff` (migration 10) had 0 rows from the day they were created
and **never had a writer**. Both facts are derived instead — stealth runs from
`accumulation_age` on `sector_flow_daily` (`CLAUDE.md` §22.11), the handoff
matrix by `analysis/flow_handoff.compute_handoff` at request time. A table
nobody writes is not inert: reading `sector_accumulation_events` is exactly what
made `/api/sectors/stealth` answer "0 events" from a panel holding 21, for
months, indistinguishably from the truth.

**Dropping a table means deleting its ORM class in the same commit.**
`init_db()` runs `Base.metadata.create_all` *before* `run_migrations()`, so a
model left behind recreates the table on the next start while the migration has
already recorded itself as applied — a schema change that reverts silently and,
being versioned, never runs again. This is a property of the startup order, not
of these two tables; every future drop hits it.
`tests/test_database_schema.py` pins it through the real sequence.

### Kept from legacy

```
model_runs             26 cols; model_name, target_col, metrics, is_active         78
backtest_runs          21 cols; equity_curve, trade_log, benchmark_return_pct      37
dashboard_layouts      (id, name, layout_json, …)                                   1
api_users / api_keys   (API_REQUIRE_KEY guard)                                    1/1
schema_migrations      (version, description, applied_at)                          11
```

### Frozen legacy (`_legacy_*`) — 9 tables, migration 10 pending

`_legacy_stocks` 144 · `_legacy_stock_prices` 56,994 · `_legacy_stock_features`
15,199 · `_legacy_trade_setups` 256 · `_legacy_predictions` 265 ·
`_legacy_feature_importance` 756 · `_legacy_sector_analysis` 18 ·
`_legacy_chart_drawings` 5 · `_legacy_stock_prices_intraday` 0.

Nothing reads them (`CLAUDE.md` §2, since 2026-04-17). They are ~72k rows of
disk waiting on §11 step 10.

WAL mode + composite indexes on `(sector_code, time)`, `(date, rank)`,
`(sector_code, start_date)`.

---

## 6. DATA FLOW

### 6.1 Ingestion
```
vnstock proxy basket (top 5/sector) + foreign flow
  → sector_ingest_service.aggregate()
  → drop raw constituent rows (rolling 60d window only)
  → sector_flow_ts
```

### 6.2 Macro
```
FRED + stooq + SBV/exchangerate.host  → macro_service  → macro_anchors
```

### 6.3 Feature & Model
```
sector_flow_daily + macro_anchors
  → flow_feature_service (lags, rolling z-scores, regime one-hot)
  → rotation_model_service
      ├── HMM regime classify → sector_regime
      └── LightGBM lambdarank → sector ranking
  → sector_signal_service → sector_signals
```

### 6.4 Publication
```
sector_signals  →  /api/sectors/ranking
                →  picks_universe_service  (per-ticker picks from signals)
                →  trader_agent "Minh"     (in-process claude_agent_sdk)
                →  generate_report.py       (union(DailyInsight, Ranker) merge
                                            + Expert Trader Memo → HTML + PDF)
                →  smtplib → Gmail (REPORT_EMAIL_TO, comma-separated list)
```
Recipients: `REPORT_EMAIL_TO` in the local `.env` only. No list is committed and
there is no fallback in code (2026-08-24, repo went public); empty writes the
HTML/PDF and skips the send.

---

## 7. MODELS

### Regime classifier
- hmmlearn `GaussianHMM`, 4 states {risk_on, risk_off, rotation, chop}
- Inputs: VNINDEX returns (1d/5d/20d), USDVND %chg, Brent %chg, US10Y level, gold %chg

### Sector ranker
- LightGBM `LGBMRanker` (lambdarank), group = day
- Primary target = **forward 20d sector return** (ranked) — CLAUDE.md §16.4 switched from 5d to 20d; 5d rewarded noise-chasing.
- Optional second head = classifier "did this sector enter breakout within 15 sessions?" (§16.4). Two-stage: ranker sorts by expected return, classifier filters noise.
- Training window: rolling 2y, monthly retrain (flow regimes change slowly — CLAUDE.md §16.4).
- Features: flow metrics + 1/3/5d lags, z-scored breadth, RS vs VNINDEX, ATR%, regime one-hot, prior-day rank, and the §16.2 leading features (`flow_z20`, `flow_z60`, `foreign_streak`, `foreign_hit_20d`, `stealth_score`, `flow_price_divergence`).
- Persistence filter: ≥3 sessions of consistent flow sign.

### Stealth detector (§16.1)
- A **score, not a conjunction**: ≥ `STEALTH_MIN_CONDITIONS` of 5 (default 4)
  held for ≥ `STEALTH_MIN_SESSIONS` sessions (default 3). All five at once was
  measured unreachable — 0.3% of rows, never 3 in a row.
  1. `flow_z20 > +1.0`
  2. `foreign_hit_20d ≥ 0.6`
  3. `breadth_sma20` rising — **top-5 basket, not the full population**;
     §18.1/6 is still open, so breadth takes ~9 discrete values (§20.3 P1-3)
  4. `atr_pct` below its own rolling 20d median
  5. `close_idx` in bottom 40% of 60d range
- An unevaluable condition leaves numerator **and** denominator, so missing data
  cannot silently raise the bar.
- Contract and caveats: `docs/reference/ALGORITHM.md` §4. **The gate has no
  measurable edge over no filter at all** (`CLAUDE.md` §16.14) — `ACCUMULATE` is
  a watchlist, not an instruction.
- §18.5/21's second foreign check, §18.3/15's sector 2y quantile and §18.5/22's
  distribution guard are **not implemented**.

### Sizing
- Vol-targeted: weight ∝ 1 / portfolio-marginal-vol (NOT per-sector ATR — §18.2/11 uses the rolling 20d correlation matrix).
- Long side cap: 3 `BUY` + 4 `ACCUMULATE` concurrent. Short side (§18.2/12): VN cash market is long-only, so shorts collapse to "reduce long" or go through VN30F1M futures.
- Execution universe: top-3 constituents per chosen sector (§14 default).

---

## 8. SCHEDULED JOBS (Asia/Ho_Chi_Minh)

All jobs are invoked by Windows Task Scheduler via the wrappers in
`scripts/jobs/job_*.bat`. Each wrapper simply calls `main.py` with the matching
CLI flag. The PowerShell sync script `scripts/cleanup_scheduled_tasks.ps1`
is the single source of truth for registration.

| # | Job (TaskName: `SectorFlow_<name>`) | Cron | CLI | Service method |
|---|---|---|---|---|
| 1 | `macro_ingest` | `0 * * * *` | `main.py --macro` | `MacroService.ingest_now()` |
| 2 | `sector_intraday_flow` | `*/15 9-15 * * 1-5` | `main.py --intraday` | `SectorIngestService.ingest_intraday_now()` |
| 3 | `sector_eod_rollup` | `0 16 * * 1-5` | `main.py --eod-rollup` | `SectorIngestService.rollup_to_daily()` |
| 4 | `regime_classify` | `30 16 * * 1-5` | `main.py --regime` | `RotationModelService.classify_regime()` |
| 5 | `rotation_predict` | `45 16 * * 1-5` | `main.py --rotation-predict` | `RotationModelService.predict_today()` |
| 6 | `sector_signal_publish` | `0 17 * * 1-5` | `main.py --publish` → `generate_report.py` | `SectorSignalService.publish()` + unified-picks email |
| 7 | `sector_risk_sentinel` | `*/30 9-15 * * 1-5` | `main.py --risk-sentinel` | `SectorRiskService.stoploss_breaches()` |
| 8 | `rotation_train` | `0 2 * * *` | `main.py --train` | `RotationModelService.train_ranker()` |
| 9 | `daily_watch` | `30 17 * * 1-5` | `main.py --daily-watch` | `daily_watch.service.run()` -> `report/watch_<date>.md` + `data/watch/<date>.json` |

Verified 2026-09-16 against `Get-ScheduledTask -TaskPath '\SectorFlow\'`:
exactly these 9 are registered, no more and no fewer.

Two things about job 9 that do not generalise from the other eight. Its trigger
is `-Weekly Mon..Fri`, genuinely -- jobs 1-8 print `1-5` in the Cron column but
register a `-Daily` trigger, so they *do* fire at weekends (harmlessly: there is
no new session). And it registers at `RunLevel = Limited` rather than `Highest`,
because it only runs python and writes files -- which is also why it could be
registered **without an elevated shell**. `cleanup_scheduled_tasks.ps1` now
takes an optional per-job `RunLevel`, defaulting to `Highest`.

Each wrapper **self-detaches through `run_hidden.vbs`** so the console lives
~0.2 s instead of the whole run. That deliberately gives up Task Scheduler's
"do not start a new instance" guard; `utils/vnstock_gate.job_lock()` enforces it
across processes instead.

**`job_freshness_check.bat` is an orphan.** It exists in `scripts/jobs/`, is
written and self-hiding like the rest, declares `cron: 0 18 * * *`, and runs
`scripts/check_freshness.py` — but it is **not in `$CanonicalJobs`, not
registered with Task Scheduler, and has never written a log**. A job nobody runs
is worse than no job: it reads as coverage the system does not have. Decide it,
do not leave it — either add the `$CanonicalJobs` row and re-run the sync
script, or delete the `.bat`. (`scripts/smoketest.py` checks the same staleness
on demand, which is why nothing has missed it.)

**Never built (§16.5):** `stealth_scanner` (`0 17 * * 1-5`), `lead_time_audit`
(`0 3 * * 1`), `flow_regime_report` (`30 17 * * 5`). ACCUMULATE is emitted by
`sector_signal_publish` reading `accumulation_age`, not by a scanner job — see
`docs/reference/ALGORITHM.md` §4. Add a `$CanonicalJobs` row if one ever lands.

**Deploy:** open elevated PowerShell, then:
```
powershell -ExecutionPolicy Bypass -File scripts\cleanup_scheduled_tasks.ps1
```
`-WhatIf` previews; `-KeepLegacy` skips the unregister step.

---

## 9. API ROUTERS

**Enumerated from `/openapi.json`, not from memory.** The previous version of
this section named eight endpoints that do not exist and omitted fifteen that
do — including everything the Stealth and Pulse pages call. Re-generate with:

```bash
PYTHONPATH=. uv run python scripts/_doc_audit.py
```

which flags any `.md` in the repo naming a route the app does not serve.

12 routers, **46 paths**.

### Trader views

| Router | Endpoints |
|---|---|
| `flow.py` | `GET /api/flow/{series,heat,index,ranking,freshness}`, `GET /api/flow/sector/{code}`, `POST /api/flow/refresh`, `GET /api/flow/refresh/status` |
| `insight.py` | `GET /api/insight/{daily,delta}`, `POST /api/insight/refresh` (async, returns `run_id`), `GET /api/insight/refresh/status` |
| `stealth.py` | `GET /api/stealth/active`, `GET /api/stealth/history` |
| `pulse.py` | `GET /api/pulse/{live,alerts,exposure}` |
| `rotation.py` | `GET /api/rotation/{pairs,sankey}` |

### Sector APIs (scheduler, `generate_report.py`, research pages)

| Router | Endpoints |
|---|---|
| `sectors_flow.py` | `GET /api/sectors/flow`, `GET /api/sectors/{sector_code}/flow`, `GET /api/sectors/{heatmap,stealth}` |
| `sectors_ranking.py` | `GET /api/sectors/ranking`, `POST /api/sectors/ranking/publish` |
| `sectors_regime.py` | `GET /api/sectors/regime`, `GET /api/sectors/regime/history`, `POST /api/sectors/regime/classify` |
| `sectors_backtest.py` | `GET`/`POST /api/sectors/backtest` |
| `sectors_risk.py` | `GET /api/sectors/risk/{exposure,stoploss,var}`, `GET /api/sectors/risk/var/{sector_code}` |
| `sectors_handoff.py` | `GET /api/sectors/handoff` |

Plus `GET /` and `GET /api/health`.

### Operator state (2026-08-23) — the only router backed by a file, not the DB

`GET /api/state`; `POST /api/state/{halt,capital,positions,watchlist}`;
`PATCH`/`DELETE /api/state/positions/{symbol}`;
`POST /api/state/positions/{symbol}/close`;
`GET /api/state/positions/{pnl,realised}`;
`POST /api/state/report/send`, `GET /api/state/report/status`.

Every mutating endpoint returns the whole state, so the client never merges.
`/positions/pnl` and `/positions/realised` are literal paths sharing a prefix
with `/positions/{symbol}` — they must stay the only GETs on that prefix, and a
test pins the ordering. `close` books an exit (realised P&L net of §18.2/10
costs); `DELETE` still deletes, for a mis-click. Backed by
`services/trading_state.py` → `data/trading_state.json`.

### Three traps worth knowing before you go looking

- **`POST /api/flow/ingest` does not exist**, and four documents cited it —
  including `CLAUDE.md` §20.1, which called it the only writer of `close_idx`.
  `services/fast_ingest.py` is still there; nothing routes to it. The writer
  today is the scheduled rollup, which carries price through since migration 11.
- **`rotation.py` stays mounted with no consumer.** `/api/rotation/pairs` builds
  a cartesian product of two sets cut from the same one-sided delta, so it is
  empty at *every* threshold. The Rotation Map page reads
  `/api/sectors/handoff` instead (`CLAUDE.md` §22.1).
- ~~**`GET /api/sectors/stealth` returns an empty `history`**~~ — **fixed
  2026-08-25.** It read `sector_accumulation_events`, the writer-less table
  (§5), and reported 0 events where `/api/stealth/history` reported 21 from the
  same panel. Both now derive from `stealth_events(panel_from_rows(...))`. The
  reason it outlived the §22.11 fix is worth keeping: every `/api/stealth/*`
  route opened `SessionLocal()` itself rather than taking
  `get_session_dependency`, so a test could not hand it a panel. They take the
  dependency now.

**Removed (legacy):** `/api/stocks/*`, `/api/trade/*`, symbol parts of
`/api/ml/*`, and `/api/agent/*` (replaced 2026-04-18 by `/api/insight/*` +
`trader_agent`; the client kept calling it for four months —§22.2).

---

## 10. FRONTEND PAGES (as shipped — 2026-08-23)

> The previous version of this section described a feature-sliced layout under
> `frontend/src/features/*`. That layout was never built: the app is flat
> `frontend/src/pages/*.tsx` with shared bits in `components/`, `lib/` and
> `api/client.ts`. It also listed `/backtest` and `/regime` as deleted; both
> exist and work. Corrected here against the running app.

Five nav items (`CLAUDE.md` §22.9). Four of them merge what used to be
separate routes into URL-backed tabs (`components/Tabs.tsx`, `?tab=`).

| Nav | Route | Tabs → page component | Question answered |
|---|---|---|---|
| Daily Insight | `/insight` | — `DailyInsightPage` | "Hôm nay mua/bán mã nào?" |
| Dòng tiền | `/flow` | `overview` → `FlowMonitorPage`, `detail` → `SectorDetailPage` | "Dòng tiền vào/ra ngành nào, mạnh đến đâu?" |
| Luân chuyển | `/rotation` | `stealth` → `StealthWatchPage`, `handoff` → `RotationMapPage` | "Tiền đang đi đâu tiếp?" |
| Rủi ro & Vị thế | `/positions` | `risk` → `RiskPage`, `pulse` → `FlowPulsePage` | "Đang nắm gì, rủi ro bao nhiêu?" |
| Nghiên cứu | `/research` | `ranking` → `RankingPage`, `regime` → `RegimePage`, `backtest` → `BacktestPage` | "Chiến lược có dương không?" |

`PositionsPage` and `ResearchPage` are `React.lazy`; recharts (346 kB) loads
only on the Backtest tab. Main bundle 371 kB.

Pre-merge paths still resolve as redirects, `/flow/:code` included:
`/stealth`, `/pulse`, `/risk`, `/ranking`, `/regime`, `/backtest`.

Shared frontend modules:

| module | role |
|---|---|
| `api/client.ts` | every endpoint, one axios instance |
| `lib/actions.tsx` | `ActionBadge` (§16.3 trade action) vs `FlowBadge` (tape state) — see `CLAUDE.md` §22.8 |
| `components/Tabs.tsx` | tab state in the URL |
| `components/Layout.tsx` | sidebar nav |
| `index.css` | Tailwind v4 `@theme` tokens — `bg-panel`, `text-hi/mid/lo`, `border-line`, `text-buy/sell/warn/acc` |

Backend routers behind these pages: `routers/flow.py`, `routers/stealth.py`,
`routers/pulse.py`, `routers/insight.py`, `routers/sectors_*.py`.
`routers/rotation.py` stays mounted but has no consumer — its pair detection
returns an empty cartesian product at every threshold (`CLAUDE.md` §22.1).

---

## 11. MIGRATION SEQUENCE

> Status re-read from `schema_migrations` (12 rows applied) on 2026-08-26. The
> stamp this section used to carry said 2026-04-22 while step 8 described a
> layout that was never built.

1. ✅ Freeze legacy tables (`_legacy_` prefix) — migration 8a.
2. ✅ New sector tables — migration 8b.
3. ✅ Ingest + macro services + schedulers.
4. ✅ Backfill 5y `sector_flow_daily`.
5. ✅ Features + v0 ranker + HMM.
6. ✅ Backtest + risk retrofit.
7. ✅ **OpenClaw retired (2026-04-18)** — replaced by in-process `services/trader_agent.py` (HTTP to 9Router since 2026-07-20, see `CLAUDE.md` §14). Gmail template = `generate_report.py` (sole generator; secv3/secv4 deleted 2026-06-18, secv5 renamed 2026-08-22).
8. ✅ **Frontend** — flat `src/pages/*.tsx`, merged to 5 nav items 2026-08-23 (§10). `/backtest` and `/regime` were never deleted; they are tabs under Nghiên cứu.
8.5. ✅ **PicksUniverseService (2026-04-17)** — single dynamic HOSE universe; retired `_legacy_stock_*` reads.
9. ✅ Shadow run is long over — the sector system has been the only one running since 2026-04.
10. ⏳ **Drop the `_legacy_*` tables** — 9 tables, ~72k rows, no reader. The DB migration has still not been written; §13 of `CLAUDE.md` calls this migration 10, but that number is taken (applied 2026-07: foreign split + handoff), and so is **12** as of 2026-08-26. It lands as **13** — do not hardcode the next free number in prose again; read `schema_migrations`.
11. ✅ Applied 2026-08-22 — carry price into the scheduled rollup (review P0-2/P0-3), the fix at the root of §20.1's causal chain.
12. ✅ Applied 2026-08-26 — drop `sector_accumulation_events` + `sector_flow_handoff`, two tables that never had a writer (§5). The ORM classes went with them; `create_all` runs before migrations, so leaving a model would recreate the table and silently revert the migration.
— 🔜 **§18 P0 remainder** (not a migration — no schema change) — §18.1/1 point-in-time constituents, §18.1/2 ETF-rebalance mask, §18.2/8 FOL check, §18.4/17 secondary HOSE source. Slippage, price bands and fee/tax (§18.2/9, 10) and purged k-fold (§18.3/13) closed 2026-08-22 — **in the backtest engine only**; `risk_service` still sizes with no cost model. §18.2/7 (T+2) was modelled from 2026-08-22 and removed 2026-09-25 with the T+ mode: at a 20-40 session hold it cannot bind.

---

## 12. INHERITED DEFAULTS (set in CLAUDE.md §14)
Proxy basket = top 5 by mcap. Backfill = 5 years. Execution = top-3 constituent basket. TraderAgent "Minh" authors the daily narrative. Frontend feature-flagged during shadow run. Report recipients: `.env: REPORT_EMAIL_TO` only — nothing committed, no code fallback.

---

## 13. MODIFICATION PROTOCOL
Every change MUST:
1. Append entry to `MODIFICATION_LOG.md`.
2. Update this file if a layer/contract/schema changes.
3. Update `CLAUDE.md` if strategy or defaults change.

No silent edits. The log is the project memory.
