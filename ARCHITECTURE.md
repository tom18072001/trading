# ARCHITECTURE — VN Sector Money-Flow Rotation System

> Target architecture for the approved redesign (2026-04-08). Replaces the legacy
> 170-symbol prediction system. Read this file before any development. Every
> change must be logged in `MODIFICATION_LOG.md`.

## CHANGELOG
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
- **2026-04-23 — SecV5: unified picks briefing.** `generate_secv5.py` replaces
  `generate_secv4.py` as the active daily-email generator. Reason: Daily Insight
  page and SecV4 email were recommending different tickers — Daily Insight
  renders `snapshot.top_buys`/`top_sells` directly (no ranker gate) while SecV4
  filtered through the ranker BUY/ACCUMULATE gate and dropped everything when
  the ranker stayed silent. SecV5 computes a **union**, de-duped by symbol,
  each entry tagged `source ∈ {BOTH, DAILY_INSIGHT, RANKER}` so the email and
  dashboard always agree. Adds an Expert Trader Memo section at the top of
  the HTML + PDF and a plain-text email body (buy symbols + reasons + Dashboard +
  news links). Default recipients grown to 3: `tka2001@gmail.com,
  anhchitruong18@gmail.com, hill.nguyen.1373@gmail.com`. Scheduler contract
  unchanged (same 17:00 slot in `scripts/jobs/job_sector_signal_publish.bat`;
  bat now calls secv5). `generate_secv4.py` and `generate_secv3.py` stay on
  disk as manual rollback paths (no scheduler hook). Helper:
  `scripts/pause_secv3_secv4_email.ps1` evicts stale Task Scheduler entries
  still invoking secv3/secv4. See `MODIFICATION_LOG.md` entry 2026-04-23.
- **2026-04-18 — Phase 12: OpenClaw retired, TraderAgent "Minh" in.** In-process
  agent via `claude_agent_sdk` replaces the external OpenClaw worker for both the
  Gmail briefing (via `generate_secv4.py`, now `generate_secv5.py`) and the
  `/api/insight/refresh` endpoint. See `specs/trader_agent.md`.
- **2026-04-17 — PicksUniverseService introduced.** One dynamic HOSE universe
  (from vnstock Listing) replaces the per-script reads of `_legacy_stock_*` in
  `generate_secv3.py`, `generate_secv4.py`, and `api/routers/insight.py`.
- **2026-04-09 — Phase 15: Trader-First View Redesign (doc-first, intent only).**
  7 views → 5. Delete `/backtest` and `/regime`, merge `/ranking` into `/flow`. New
  `/rotation` (Sankey + pair table), `/stealth` (5-cond gate + Gantt), `/pulse`
  (live tape replaces Risk), `/insight` (LLM narrative replaces Briefing). Binding
  contracts: interval toggle `1D/1W/2W/1M/1Q` (server-side resample), configurable
  thresholds via `ThresholdInput` + localStorage, feature-sliced frontend folder
  rename. Blocker in scope: real `close_idx` backfill removes `STEALTH_SYNTHETIC_CLOSE`
  escape hatch. See `CLAUDE.md` §17 and `specs/REDESIGN_PHASE15.md` + 6 feature specs.
  No code landed yet — this changelog entry is intent. Legacy `pages/*.tsx`, the
  Backtest/Regime/Ranking pages, and their matching services/routers are scheduled
  for deletion as each replacement feature ships.
- **2026-04-08 — Phase 8: Sector Money-Flow Redesign (APPROVED).** Architecture
  rewritten end-to-end. Legacy symbol-prediction stack archived (`_legacy_`
  prefix on tables, retained until 2-week shadow run completes). New primary key
  is `sector_code`, not `symbol`. See `CLAUDE.md` for the strategy spec.
- Phase 1–7 history retained in `docs/CHANGELOG.md`.

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
  → trader_agent "Minh" (claude_agent_sdk, in-process)
  → generate_secv5.py → Gmail briefing (was secv4 until 2026-04-23)
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
| Email Report | Daily unified-picks HTML + PDF → Gmail | `generate_secv5.py` (active; +`generate_secv4.py`, `generate_secv3.py` as rollback) |
| API | FastAPI, 12 routers | `api/main.py`, `api/routers/*` |
| Frontend | React 19 feature-sliced pages (Phase 15) | `frontend/src/features/*` |

---

## 2. TECHNOLOGY STACK (inherited)
Python 3.11, FastAPI, SQLAlchemy 2.0 + SQLite (WAL), vnstock ≥3.2, LightGBM, hmmlearn, scikit-learn, React 19 + Vite + TypeScript, Tailwind. Models persisted to `models/saved/`.

---

## 3. DIRECTORY STRUCTURE (as of 2026-04-22)
```
Trading/
├── CLAUDE.md                         # Approved redesign spec (source of truth)
├── ARCHITECTURE.md                   # This file
├── MODIFICATION_LOG.md               # Append-only change log
├── README.md                         # Quickstart
├── config.py                         # SECTORS, PROXY_BASKETS, MACRO_TICKERS, RISK_CONFIG
├── main.py                           # CLI entry (one flag per §8 job)
├── generate_secv5.py                 # Daily SecV5 unified-picks email generator (active)
├── generate_secv4.py                 # Rollback path (pre-union merge) — do not remove
├── generate_secv3.py                 # Rollback path (§2) — do not remove
│
├── data/                             # vnstock wrappers + macro fetchers
├── analysis/
│   ├── flow_aggregation.py           # basket → sector aggregates
│   ├── flow_handoff.py               # sector-to-sector rotation detection
│   ├── feature_engineering.py        # shared TA helpers
│   ├── regime.py                     # Gaussian HMM regime classifier
│   ├── stealth.py                    # §16.1 five-condition gate
│   └── charts/                       # matplotlib renderers used by secv4/secv5
│
├── models/
│   ├── rotation_ranker.py            # LightGBM lambdarank
│   └── saved/                        # pickled models + metadata
│
├── database/
│   ├── connection.py                 # SQLAlchemy engine (WAL pragmas)
│   ├── models.py                     # sector tables + picks_universe snapshot
│   └── migrations.py                 # migrations 1–10
│
├── services/
│   ├── sector_ingest_service.py      # proxy OHLCV ingest + rollup
│   ├── fast_ingest.py                # async/batched variant (API-driven)
│   ├── macro_service.py              # macro_anchors row writer
│   ├── flow_feature_service.py       # flow features + §16.2 leading features
│   ├── rotation_model_service.py     # HMM regime + ranker train/predict
│   ├── sector_signal_service.py      # publishes sector_signals
│   ├── backtest_service.py           # sector-basket backtester
│   ├── risk_service.py               # VaR + stop-loss sentinel
│   ├── picks_universe_service.py     # dynamic HOSE universe → per-ticker picks
│   ├── picks_scoring.py              # SWING / TPLUS validity gate
│   ├── picks_news.py                 # vnstock company news fetch
│   ├── trader_agent.py               # "Minh" (claude_agent_sdk, in-process)
│   └── insight_refresh.py            # async /api/insight/refresh runner
│
├── api/
│   ├── main.py                       # FastAPI app factory
│   ├── schemas.py                    # pydantic models
│   └── routers/
│       ├── flow.py                   # Phase 15 flow monitor
│       ├── rotation.py               # Phase 15 rotation map
│       ├── stealth.py                # Phase 15 stealth watch
│       ├── pulse.py                  # Phase 15 live pulse
│       ├── insight.py                # Phase 15 daily insight + async refresh
│       ├── sectors_flow.py           # legacy-compat sector flow endpoint
│       ├── sectors_ranking.py        # daily ranking table
│       ├── sectors_regime.py         # regime history
│       ├── sectors_backtest.py       # backtest run launcher
│       ├── sectors_risk.py           # VaR + exposure
│       └── sectors_handoff.py        # handoff analytics
│
├── frontend/                         # React 19 + Vite + TypeScript (feature-sliced)
│
├── scripts/
│   ├── cleanup_scheduled_tasks.ps1   # FULL SYNC of Windows Task Scheduler
│   ├── backfill_3y.py                # 3y sector flow backfill
│   ├── backfill_close_idx.py
│   ├── backfill_foreign.py
│   ├── replay_stealth.py             # re-emit stealth events from history
│   ├── seed_data.py                  # seeds sectors + constituents table
│   ├── check_db.py                   # integrity + schema diff
│   ├── create_key.py                 # API key bootstrap
│   ├── fix_close_idx.py              # one-shot close_idx repair
│   ├── rebuild_features_after.py
│   ├── test_auth.py
│   ├── start-tunnel.bat              # cloudflared tunnel for remote dev
│   └── jobs/                         # one wrapper .bat per §8 scheduled job
│       ├── _env.bat
│       ├── job_macro_ingest.bat
│       ├── job_sector_intraday_flow.bat
│       ├── job_sector_eod_rollup.bat
│       ├── job_regime_classify.bat
│       ├── job_rotation_train.bat
│       ├── job_rotation_predict.bat
│       ├── job_sector_signal_publish.bat
│       └── job_sector_risk_sentinel.bat
│
├── specs/                            # one .md per Phase-15 feature + cross-cutting
├── docs/                             # architecture docs, algorithm notes, changelog
├── report/                           # rendered HTML / PDF / templates; `jobs/` sub-logs
├── tests/                            # 78 pytest cases (§19)
└── _trash_20260422/                  # quarantined legacy files — safe to `rmdir /s`
```

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

---

## 5. DATABASE SCHEMA (target)

```
sectors (sector_code PK, name, description)
 └──→ sector_constituents (sector_code FK, symbol, weight, active)

sector_flow_ts        (sector_code, time, net_dollar_flow, up_vol, down_vol,
                       foreign_net, breadth_sma20, breadth_sma50,
                       rs_vnindex_5d, rs_vnindex_20d, atr_pct,
                       UQ(sector_code, time))

sector_flow_daily     (sector_code, date, daily rollups)
macro_anchors         (time, vnindex, usdvnd, brent, us10y, gold)
sector_regime         (date, regime_label, confidence)
sector_signals        (date, sector_code, score, rank, action, model_run_id)

model_runs            (kept, retrofitted target_col = sector rotation targets)
backtest_runs         (kept; equity_curve_json now sector-basket)
dashboard_layouts     (kept)

_legacy_*             (frozen legacy tables; dropped after shadow run)
```

WAL mode + composite indexes on `(sector_code, time)`, `(date, rank)`.

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
                →  generate_secv5.py       (union(DailyInsight, Ranker) merge
                                            + Expert Trader Memo → HTML + PDF)
                →  smtplib → Gmail (REPORT_EMAIL_TO, comma-separated list)
```
Recipients (`REPORT_EMAIL_TO` in `.env`, updated 2026-04-23 to 3-person list):
`anhchitruong18@gmail.com, hill.nguyen.1373@gmail.com`.

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

### Stealth detector (§16.1 doctrine)
- Five conditions, all true for ≥5 sessions → emit `ACCUMULATE`:
  1. `flow_z20 > +1.0`
  2. `foreign_hit_20d ≥ 0.6` AND `foreign_net_z20 ≥ +0.5` (two independent checks, §18.5/21)
  3. Breadth SMA20 rising (full-sector population, §18.1/6)
  4. `ATR%` below sector-specific 2y quantile (§18.3/15)
  5. Close price in bottom 40% of 60d range
- Distribution guard (§18.5/22): any session with `up_vol/down_vol < 0.5` AND `foreign_net < 0` invalidates the event.

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
| 6 | `sector_signal_publish` | `0 17 * * 1-5` | `main.py --publish` → `generate_secv5.py` | `SectorSignalService.publish()` + unified-picks email |
| 7 | `sector_risk_sentinel` | `*/30 9-15 * * 1-5` | `main.py --risk-sentinel` | `SectorRiskService.stoploss_breaches()` |
| 8 | `rotation_train` | `0 2 * * *` | `main.py --train` | `RotationModelService.train_ranker()` |

**Pending (§16.5 — services not yet implemented, therefore NOT registered):**
`stealth_scanner` (`0 17 * * 1-5`), `lead_time_audit` (`0 3 * * 1`),
`flow_regime_report` (`30 17 * * 5`). See `$CanonicalJobs` in
`scripts/cleanup_scheduled_tasks.ps1` — add a row there when each lands.

**Deploy:** open elevated PowerShell, then:
```
powershell -ExecutionPolicy Bypass -File scripts\cleanup_scheduled_tasks.ps1
```
`-WhatIf` previews; `-KeepLegacy` skips the unregister step.

---

## 9. API ROUTERS (as of 2026-04-22)

12 routers live under `api/routers/`. Phase-15 trader-first views are the
default; the `sectors_*` set remains for backend-only callers (the scheduler,
the email report) and for backward-compat.

**Phase-15 trader views** (`frontend/src/features/*` consumes these):
| Router | Key endpoints |
|---|---|
| `flow.py` | `GET /api/flow/monitor`, `GET /api/flow/freshness`, `POST /api/flow/ingest` |
| `rotation.py` | `GET /api/rotation/map`, `GET /api/rotation/pairs` |
| `stealth.py` | `GET /api/stealth/watch`, `GET /api/stealth/events` |
| `pulse.py` | `GET /api/pulse/tape` (live 15m flow) |
| `insight.py` | `GET /api/insight/daily`, `POST /api/insight/refresh` (async, returns `run_id`), `GET /api/insight/refresh/status` |

**Sector APIs** (used by scheduler, `generate_secv5.py` / `generate_secv4.py`, legacy integrations):
| Router | Key endpoints |
|---|---|
| `sectors_flow.py` | `GET /api/sectors/flow`, `GET /api/sectors/{code}/flow` |
| `sectors_ranking.py` | `GET /api/sectors/ranking`, `GET /api/sectors/ranking/history` |
| `sectors_regime.py` | `GET /api/sectors/regime`, `GET /api/sectors/regime/history` |
| `sectors_backtest.py` | `POST /api/sectors/backtest`, `GET /api/sectors/backtest/{id}` |
| `sectors_risk.py` | `GET /api/sectors/risk/var`, `GET /api/sectors/risk/exposure` |
| `sectors_handoff.py` | `GET /api/sectors/handoff` — sector-to-sector money handoff |

**Removed (legacy, kept in `_trash_20260422/`):** `/api/stocks/*`, `/api/trade/*`, symbol parts of `/api/ml/*`, and the old `/api/agent/*` briefing (replaced by `/api/insight/*` + `trader_agent`).

---

## 10. FRONTEND PAGES (Phase 15 target — supersedes Phase 8 list)
Feature-sliced layout under `frontend/src/features/*`. Each feature owns its
components, hooks, and api slice; shared primitives live in `frontend/src/shared/*`.

| Route | Feature folder | Question answered |
|---|---|---|
| `/flow` | `features/flow-monitor/` | "Dòng tiền vào/ra sector nào?" (merges old Flow Dashboard + Ranking) |
| `/rotation` | `features/rotation-map/` | "Tiền dịch chuyển TỪ đâu SANG đâu?" (Sankey + pair table) |
| `/stealth` | `features/stealth-watch/` | "Sector nào tích luỹ âm thầm?" (5-cond gate + Gantt) |
| `/pulse` | `features/flow-pulse/` | "NGAY LÚC NÀY flow sector nào lên/xuống?" (live tape; VaR → secondary) |
| `/insight` | `features/daily-insight/` | "Hôm nay có gì đáng chú ý, nên làm gì?" (LLM narrative + deltas) |

**Deleted** in Phase 15: `/backtest` (rebuilt only after real `close_idx` lands),
`/regime` (heuristic fallback, non-actionable), standalone `/ranking` (merged into
`/flow`), and the legacy symbol pages from Phase 8. Matching backend routers
`sectors_backtest`, `sectors_regime` and their services are scheduled for
deletion as each replacement feature ships.

New backend routers for Phase 15: `routers/flow.py`, `routers/rotation.py`,
`routers/stealth.py`, `routers/pulse.py`, `routers/insight.py`. New services:
`services/flow/aggregation.py` (interval resampler), `services/rotation/pair_detector.py`,
`services/stealth/detector.py` (wraps existing `analysis/stealth.py`),
`services/insight/narrative.py`. Full contracts in `specs/REDESIGN_PHASE15.md`.

---

## 11. MIGRATION SEQUENCE (status as of 2026-04-22)
1. ✅ Freeze legacy tables (`_legacy_` prefix) — migration 8a.
2. ✅ New sector tables — migration 8b.
3. ✅ Ingest + macro services + schedulers.
4. ✅ Backfill 5y `sector_flow_daily`.
5. ✅ Features + v0 ranker + HMM.
6. ✅ Backtest + risk retrofit.
7. ✅ **OpenClaw retired (2026-04-18)** — replaced by in-process `services/trader_agent.py` via `claude_agent_sdk`. Gmail template = `generate_secv5.py` (active since 2026-04-23; union-merge of Daily Insight + ranker picks). `generate_secv4.py` and `generate_secv3.py` retained as rollback paths.
8. ✅ **Phase 15 frontend** — feature-sliced pages shipped. Old `/backtest` and `/regime` scheduled for deletion after Phase-15 features prove out.
8.5. ✅ **PicksUniverseService (2026-04-17)** — single dynamic HOSE universe; retired `_legacy_stock_*` reads.
9. ⏳ **Shadow-run window** — still active until the 2-week comparison completes.
10. ⏳ **Migration 10** (pending) — drop `_legacy_stocks`, `_legacy_stock_prices`, `_legacy_stock_features`; physical removal (moved to `_trash_20260422/`) complete but the DB migration has NOT been run yet.
11. 🔜 **§16.1 feature back-fill + §16.5 stealth jobs** — next unit of work.
12. 🔜 **§18 trader-lens blockers (P0)** — survivorship, ETF-rebalance mask, T+2 settlement modeling, FOL check, slippage + price bands, fee/tax, purged k-fold CV, secondary HOSE source.

---

## 12. INHERITED DEFAULTS (set in CLAUDE.md §14)
Proxy basket = top 5 by mcap. Backfill = 5 years. Execution = top-3 constituent basket. TraderAgent "Minh" authors the daily narrative. Frontend feature-flagged during shadow run. Report recipients: `anhchitruong18@gmail.com, hill.nguyen.1373@gmail.com` (see `.env: REPORT_EMAIL_TO`).

---

## 13. MODIFICATION PROTOCOL
Every change MUST:
1. Append entry to `MODIFICATION_LOG.md`.
2. Update this file if a layer/contract/schema changes.
3. Update `CLAUDE.md` if strategy or defaults change.

No silent edits. The log is the project memory.
