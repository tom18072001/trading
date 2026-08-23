# CODE_REVIEW_2026-08-22 — VN Sector Money-Flow

> Reviewed at commit `6364a10`. Static read of the full Python backend + frontend config.
> 22 findings. Severity: 6 × P0, 6 × P1, 4 × P2, 6 × P3.
> Companion artifact (formatted, same content): see MODIFICATION_LOG entry for 2026-08-22.

## Executive summary

One causal chain runs through most of the P0s, and it starts at one table: `sector_flow_daily`.

The 16:00 EOD job writes a row to that table **without** `close_idx`. The second ingest path — the
only one that knows how to write `close_idx` — runs only from a UI button, and it skips any date
that already has a row. So the EOD job **permanently locks** that date in a price-less state. From
there: the ML target (`fwd_20d_return`) is computed over an empty column, stealth condition 5 has to
be disabled by an env flag, and the backtest loses its price anchor.

Separately, the EOD job can stamp *yesterday's* numbers as *today's* row whenever the intraday job
was rate-limited. Together these mean every number the system surfaces — z-scores, stealth flags,
rankings, backtest Sharpe — currently rests on a daily table that is not yet trustworthy.

What is good: `utils/vnstock_gate.py` is clean and written by someone who understood the problem.
The discipline of "why" comments with dates and post-mortems beats most codebases. Frontend has
`strict` TS, ESLint and vitest. This project does not need a rewrite; it needs five or six targeted
fixes.

---

## P0 — Wrong data or wrong conclusions

### P0-1 — `rollup_to_daily()` stamps stale rows with today's date
`services/sector_ingest_service.py:266-300`

Takes the newest `sector_flow_ts` row per sector and writes it as `date = today` without checking
that `r.time` falls on that date.

```python
rows = (self.session.query(SectorFlowTS)
        .order_by(SectorFlowTS.sector_code, SectorFlowTS.time.desc())
        .all())                      # no date filter
for r in rows:
    ...
    self.session.add(SectorFlowDaily(sector_code=r.sector_code, date=date, ...))
```

If the intraday job was rate-limited (documented in `vnstock_gate.py`'s post-mortem) or the market
was closed, the prior session's numbers become the new session's row. A flat repeated series
collapses `std` in `_rolling_z`, which inflates `flow_z20` → **false stealth triggers**. The ML
target is then computed across duplicated bars.

**Fix:** filter `SectorFlowTS.time` to `[date 00:00, date 23:59]`. Skip and log loudly when a sector
has no bar for that date. A missing row beats a wrong row.

### P0-2 — The scheduled pipeline never writes `close_idx`, and it blocks the path that would
`services/sector_ingest_service.py` · `services/fast_ingest.py:184,231`

Two ingest paths with different semantics:

- `SectorIngestService.rollup_to_daily()` / `backfill_sector()` — runs on Task Scheduler, writes
  `SectorFlowDaily` with **no** `close_idx`, **no** `return_1d`.
- `services/fast_ingest.py:231` — reachable only from `POST /api/flow/ingest`, does write
  `close_idx=agg.close_idx`.

And `fast_ingest` only processes dates that don't already have a row:

```python
new_dates = sorted(all_dates - existing_dates)
if not new_dates:
    continue
```

So: EOD job writes the price-less row → that date enters `existing_dates` → `fast_ingest` skips it
forever → `close_idx` stays `NULL` permanently.

Evidence this is a known-but-patched wound: `scripts/backfill_close_idx.py`,
`scripts/fix_close_idx.py`, and the `STEALTH_SYNTHETIC_CLOSE` escape hatch in `analysis/stealth.py`.
All three exist only to compensate.

Readers of `close_idx`: the ML target (`flow_feature_service.py:117`), stealth cond5
(`stealth.py:105`), the entire backtest P&L (`backtest_service.py:136`), and the composite index
chart on the Flow page.

**Fix:** one ingest path that always writes `close_idx` + `return_1d`. Change `fast_ingest` from
skip to upsert so it can repair damaged dates. Then delete both `*_close_idx.py` scripts and the
`STEALTH_SYNTHETIC_CLOSE` flag.

### P0-3 — `close_idx` is a raw price sum, not an index
`analysis/flow_aggregation.py:152`

```python
# Synthetic sector index = weighted last-close (not normalized)
close_idx += float(df["close"].iloc[-1]) * w
```

`w` is always `1/n` — `weights` is never passed from `PROXY_BASKETS`, so "weighted by market cap"
(CLAUDE.md §3) does not exist in code.

A 2:1 split in VCB halves the BANK "index" overnight: a fake −50% `return_1d`, a fake `fwd_20d`
target, a fake backtest loss. Changing a constituent produces the same jump.

**Fix:** chain-link it — `index_t = index_{t-1} × (1 + Σ wᵢ·rᵢ,ₜ)`, base 100. Immune to splits and to
basket changes. Weights should be point-in-time market cap, not `1/n`.

### P0-4 — The backtest tests a different strategy than the system publishes
`services/backtest_service.py:141`

```python
ranked = group.sort_values("net_dollar_flow", ascending=False)
```

It never reads `sector_signals`, never uses the ranker score, never uses
`ACCUMULATE`/`BUY`/`TRIM`/`SELL`, never applies the stop-loss from `risk_service`.

Two consequences:

1. Every success criterion in CLAUDE.md §16.11 and §18.7 — ACCUMULATE lead time ≥ 10 sessions,
   root-capture ≤ 0.85, decile monotonicity, net-of-cost Sharpe ≥ 0.8 — is being measured against a
   strategy nobody trades.
2. `net_dollar_flow` is un-normalized VND. "Top 3 by flow" is structurally "the 3 largest sectors"
   (BANK, REAL, STEEL) on nearly every day. This is a near-static portfolio dressed as rotation.

The VN friction model (T+2, sell tax, ATR slippage, ±7% band) is well written and faithful to
§18.2. It is simply applied to the wrong strategy.

Also: `benchmark_return_pct` is the equal-weighted mean of 15 sector `return_1d` values, not VNINDEX
buy-and-hold as §11 specifies.

**Fix:** drive the backtest off persisted `sector_signals` (or replay the ranker point-in-time). If a
flow baseline is still wanted, rank on cross-sectional z-score, not raw VND — then compare the two.
The gap between them is the answer to "does the ranker add anything".

### P0-5 — `foreign_net` is zero across the entire history
`services/sector_ingest_service.py:245` · `analysis/stealth.py:113-117`

```python
agg = aggregate_sector(code, sliced, foreign_net_by_symbol={})   # empty
```

All backfilled data has `foreign_net = 0.0`. The live path `_fetch_foreign()` reads
`trading.price_board` — today's board only, no history. So the column is effectively a constant zero
for any training purpose.

The stealth detector silently drops condition 2 when it notices:

```python
foreign_available = foreign.abs().sum() > 0
conds = [cond1, cond3, cond4]
if foreign_available:
    conds.append(cond2)
```

Meanwhile `foreign_net`, `foreign_streak`, `foreign_hit_20d` are all in `FEATURE_COLS` — the ranker
trains on three constant columns. CLAUDE.md §4 calls this the decisive VN signal; it has never
contributed anything.

**Fix:** pick one explicitly. (a) Source a historical foreign-flow series — vnstock exposes daily
foreign data for some sources, or scrape CafeF/SSI as §18.4/17 already proposes; or (b) drop the
three features from `FEATURE_COLS` and record in CLAUDE.md that the gate is 4 conditions. What is not
acceptable is letting it degrade in silence.

### P0-6 — No purge/embargo in ranker CV
`models/rotation_ranker.py:52-56`

```python
unique_dates = sorted(df["date"].unique())
cut = int(len(unique_dates) * 0.8)
train_dates = set(unique_dates[:cut])      # no embargo
```

Target is a forward 20-day return (`ROTATION_TARGET_HORIZON_DAYS = 20`). The last 20 training dates'
labels are drawn from the test window. CLAUDE.md §18.3/13 marks this a **BLOCKER**; it is not done.

The evaluation metric also measures nothing (`rotation_ranker.py:100-110`): it counts "did the top-1
sector have a positive forward return". In a rising market a random pick scores ~60%. That number is
written to `model_runs` and is not informative.

**Fix:** embargo = horizon + 2 sessions between train and test (López de Prado, exactly as §18.3/13
states). Replace the metric with out-of-sample decile monotonicity, NDCG@3, and hit-rate *relative to
the median sector* rather than relative to zero.

---

## P1 — Model not trustworthy

### P1-1 — Stealth thresholds loosened below doctrine; docs still show the old numbers
`analysis/stealth.py:20-21`

```python
RETURN_BOTTOM_FRAC   = env("STEALTH_RETURN_BOTTOM_FRAC", "0.60")
STEALTH_MIN_SESSIONS = env("STEALTH_MIN_SESSIONS", "3")
```

CLAUDE.md §16.1 mandates bottom **40%** of the 60-day range and **≥ 5 sessions**. Code defaults to
60% and 3. Combined with P0-5 (cond2 dropped) and `STEALTH_SYNTHETIC_CLOSE` (cond5 dropped), the
worst case is a **3-condition** gate with a looser price cut and a shorter persistence window.

This also violates §15 (log every change, update CLAUDE.md). Anyone reading CLAUDE.md today believes
in a stricter system than the one running.

**Fix:** decide the real numbers and make both places agree. If 0.60/3 is a justified VN calibration,
it *is* the new doctrine — amend §16.1 and log it. Have `publish()` record how many conditions were
actually evaluated, so a 3-condition ACCUMULATE never looks like a 5-condition one.

### P1-2 — The ranker degrades to "rank by raw flow" with no alert
`models/rotation_ranker.py:70-74,128-133` · `services/rotation_model_service.py:96`

```python
except Exception as e:
    print(f"[RotationRanker] LightGBM unavailable ({e}); using fallback")
    self.model = _MeanFlowRanker(feature_cols)
...
class _MeanFlowRanker:
    def predict(self, X):
        return X[self.feature_cols].mean(axis=1).values
```

Features mix billions of VND with 0–1 breadth, so their arithmetic mean effectively *is*
`net_dollar_flow`. Same logic in `predict_today()` when no model is loaded.

`backend` is recorded in `model_runs.metrics` but nothing reads it. The email still says
"ranker-gated picks" and looks like any normal day.

**Fix:** make the fallback loud — flag it on `sector_signals`, banner it in the email, and have
`scripts/check_freshness.py` fail when `backend != "lightgbm"`. If LightGBM is required, let it throw
rather than guess.

### P1-3 — Breadth over 5 names is not breadth
`analysis/flow_aggregation.py:81-85`

```python
def _pct_above_sma(close, period):
    sma = close.rolling(period).mean().iloc[-1]
    return 1.0 if close.iloc[-1] > sma else 0.0   # binary per symbol
```

Sector breadth takes 6 values: 0 / 0.2 / 0.4 / 0.6 / 0.8 / 1. `stealth.py` then takes a 5-day mean of
the *diff* of that series to conclude "breadth rising" — mostly noise. CLAUDE.md §18.1/6 names this
exactly and it is still open.

**Fix:** as §18.1/6 proposes — compute breadth over the *full* sector population (already available
in `PicksUniverseService`), keep flow on the top-5 basket. Two different tools for two different
jobs.

### P1-4 — Regime labels are back-painted; the state→label map is fragile
`services/rotation_model_service.py:110-125` · `analysis/regime.py:78`

`classify_regime()` refits the HMM on the entire history every run, and `predict()` uses
`model.predict(X)` — Viterbi, a *global smoothed* decode. Yesterday's label can change when today's
bar arrives. Any historical use of this series is look-ahead.

```python
means = m.means_[:, 0]        # assumes column 0 is vn_ret_1d
order = np.argsort(means)
labels = ["risk_off", "chop", "rotation", "risk_on"]
```

`_features()` only adds `vn_ret_1d` when `vnindex` has > 5 non-null values. Otherwise column 0
becomes `fx_chg` and all four regime labels become arbitrary — with no error raised.

**Fix:** use the filtered forward posterior for the last bar instead of full-sequence Viterbi. Map
states by explicit column name, and raise if `vn_ret_1d` is absent rather than silently changing what
the labels mean.

### P1-5 — Still publishing `SELL` into a market that cannot short; three §16/§18 safeties missing
`services/sector_signal_service.py:78`

```python
elif rank > n - MAX_SHORT_SECTORS and persistence:
    action = "SELL"
```

`BACKTEST_LONG_ONLY = True` and §18.2/12 says delete the "2 short" concept from the cash leg. But
`MAX_SHORT_SECTORS = 2` still produces SELL every day, and those SELLs flow into the email.

Promised in the plan, absent from the code:

- §16.9 — cap of **4 concurrent ACCUMULATE** positions: checked nowhere.
- §16.9 — auto-exit after **30 sessions** of stealth without breakout: absent.
- §18.4/20 — `config.trading_halt` kill-switch: does not exist.

**Fix:** either rename `SELL` → `REDUCE` (trim the long) to match market reality, or drop it if you
don't hedge with VN30F1M. The other three are a few lines each in `publish()` — cheap, and worth
having before real money.

### P1-6 — Naive `datetime.now()` everywhere "today" is decided
`sector_signal_service.py:63` · `rotation_model_service.py:126` ·
`sector_ingest_service.py:150,236,268` · `generate_secv5.py:66`

`config.TIMEZONE = "Asia/Ho_Chi_Minh"` is declared and **used nowhere**. A 17:00 ICT publish job on a
UTC box stamps the previous date. `aggregate_sector` also has a fallback using
`pd.Timestamp.utcnow()`, mixing two frames of reference in the same table.

**Fix:** one `utils/clock.py::trading_date()` returning the date in `Asia/Ho_Chi_Minh`, called
everywhere. Add a test that pins the behaviour under `TZ=UTC`.

---

## P2 — Security & operations

### P2-1 — Auth and rate-limiting exist in code and are both switched off
`api/auth.py` · `api/rate_limit.py` · `api/main.py:41-52`

`api/auth.py` (134 lines) defines `require_api_key` — **no router uses it**. `api/rate_limit.py`
defines `limiter` — `api/main.py` never sets `app.state.limiter`, never adds the middleware, never
registers the handler.

Wide open: `POST /api/insight/refresh`, `/api/sectors/ranking/publish`,
`/api/sectors/regime/classify`, `/api/sectors/backtest/run`, `/api/flow/ingest`.

```python
_cors_origins = FRONTEND_URLS + [
    "https://*.ngrok-free.app",       # not a wildcard — inert
    "https://*.trycloudflare.com",
]
app.add_middleware(CORSMiddleware,
    allow_origin_regex=r"https://.*\.(ngrok-free\.app|trycloudflare\.com)",
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
```

With `API_HOST = "0.0.0.0"` and a history of cloudflared tunnels (visible in git log): anyone who
learns the tunnel URL can trigger repeated universe rebuilds — burning the KBS quota and LLM budget,
and corrupting your snapshot. This is a real abuse vector, not a theoretical one.

**Fix:** add `dependencies=[Depends(require_api_key)]` to the POST-bearing routers, attach `limiter`
to the app, and drop the two inert wildcard strings. If auth is not wanted, **delete** `api/auth.py` —
security code that does not run is worse than none, because it manufactures false confidence.

### P2-2 — Two independent rate-limit buckets in one process
`utils/vnstock_gate.py` · `services/picks_universe_service.py:374`

The gate holds 18 calls/min. `picks_universe_service` has its own `_kbs_throttle()` with a separate
bucket — the gate's own header admits this ("left alone deliberately").

But `job_lock()` only wraps the CLI commands in `main.py`. The FastAPI `/insight/refresh` path
**takes no lock at all**. So one Refresh click overlapping the scheduled intraday job runs at twice
the KBS ceiling — precisely the scenario the 2026-08-22 patch set out to end.

**Fix:** have `picks_universe_service` call `vnstock_gate.call()` and wrap `insight_refresh` in
`guarded()`. One budget, one lock, one place to tune.

### P2-3 — The "intraday" job is not intraday, and re-downloads 120 days every 15 minutes
`services/sector_ingest_service.py:38,150` · `config.py:INTRADAY_INTERVAL`

```python
return stock.quote.history(start=start, end=end, interval="1D")
...
start = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
```

`config.INTRADAY_INTERVAL = "15m"` is declared and never used. Per run: 75 constituents × (one
120-day history call + one price_board call) ≈ **150 calls**. Times ~25 runs/day under cron
`*/15 9-15` ≈ **3,750 calls/day** against an 18/min gate.

This is the fire `vnstock_gate` is holding back. The gate treats the symptom; the cause is
re-downloading the whole window every cycle to obtain one bar. It also makes §18.5/23's
`morning_share` impossible — there is no intraday data to compute it from.

**Fix:** either (a) fetch genuinely at `interval="15m"` and take only what is new since the last
stored bar, or (b) admit this is an EOD pipeline, move the cron to once daily, and amend CLAUDE.md
§4/§8 to match. Option (b) takes 10 minutes and immediately frees ~95% of the quota.

### P2-4 — `except BaseException` swallows Ctrl-C
15 sites; `main.py:142` is the worst

Justified at `vnstock_gate.py:82` — vnstock raises `SystemExit` on a 429, and the comment says so.
But the pattern spread to 15 places including the backfill loop:

```python
except BaseException as e:
    print(f"[backfill] {code} error: {e}")
```

Ctrl-C during a 5-year backfill will not stop it — `KeyboardInterrupt` is caught, printed, and the
loop moves to the next sector.

**Fix:** keep `BaseException` at the gate layer only. Everywhere else use `except Exception`, and
re-raise `KeyboardInterrupt` explicitly if a broad catch is still wanted.

---

## P3 — Maintainability

### P3-1 — Two "single sources of truth", already drifted
`AGENTS.md` is a 26 KB copy of `CLAUDE.md`. The diff shows they have separated in 5 passages: the
agent-provider paragraph, three test descriptions, and the live-integration note — one says "Claude",
the other says "Codex". Both open with "Rule: every future modification MUST append an entry to
MODIFICATION_LOG.md", which cannot hold with two copies.

**Fix:** keep `CLAUDE.md` canonical; reduce `AGENTS.md` to a 3-line pointer.

### P3-2 — The most important output is a 1,629-line module-level script with no tests
`generate_secv5.py`

Opens a raw `sqlite3` connection at import (line 118), bypassing the SQLAlchemy models entirely, and
keeps all state in module globals. Scoring, thesis prose, chart rendering, HTML assembly and SMTP all
live in one file. It re-implements logic that already exists in `services/picks_scoring.py` and
`services/unified_picks.py`.

CLAUDE.md §19 lists 105 backend tests. None touch SecV5 — the one thing actually read every day.

**Fix:** no rewrite needed. Extract the *decision* layer (pick selection, conviction bucketing, memo
assembly) into a pure, tested module; leave rendering and mail in the script. About 300 lines
relocated, and the daily output becomes verifiable.

### P3-3 — `.env.example` is stale; a fresh clone cannot be configured
Says `DATA_SOURCE=VCI` while `config.py:34` defaults to KBS and the comment above it notes VCI has
returned empty since mid-April. Missing every variable added since:

```
AGENT_PROVIDER          LOCAL_BASE_URL          LOCAL_MODEL
GLM_API_KEY             AGENT_TIMEOUT_SEC       AGENT_MAX_BUYS
REPORT_EMAIL_FROM       REPORT_EMAIL_PASSWORD   REPORT_EMAIL_TO
REPORT_DASHBOARD_URL    VNSTOCK_MAX_PER_MIN     VNSTOCK_LOCK_WAIT
ROTATION_TARGET_HORIZON_DAYS                    UNIVERSE_PICKS_FLOOR
STEALTH_MIN_SESSIONS    STEALTH_RETURN_BOTTOM_FRAC
STEALTH_SYNTHETIC_CLOSE
```

### P3-4 — Four performance bottlenecks, each a small fix
- `rollup_to_daily()` loads the **entire** `sector_flow_ts` table into RAM (`.all()`, unfiltered)
  just to find the newest row per sector.
- `_stealth_sectors()` issues one query per sector — N+1, 15 round-trips for one statement's work.
- `backfill_sector()` re-slices and re-aggregates every constituent frame for *every* day —
  O(days × symbols) full recomputes.
- `_rebuild_leading_features_fast()` rewrites every row of `sector_flow_daily` after each ingest,
  even when one day was added.

### P3-5 — 666 lint findings, 174 auto-fixable
Nothing dangerous, but it drowns real signal: 21 unused imports, 4 dead variables, 7 `raise`-inside-
`except` losing the original cause, 4 silent `try/except/pass`. Worth one `ruff check --fix` pass and
a pre-commit hook, after which each new finding means something.

### P3-6 — Frontend is sound; two items to clear
TypeScript runs `strict` + `noUnusedLocals`, with ESLint and vitest — more disciplined than the
backend. Two things: `ShortTradePage.tsx` and `SignalPage.tsx` are 1-line dead stubs, and
`@rollup/rollup-linux-x64-gnu` is pinned as a hard `dependency` in `package.json` on a Windows
machine, which will break `npm ci` anywhere else.

---

## Plan vs. code divergence

Each row needs a decision: change the code to match the doc, or change the doc to match reality.

| Topic | CLAUDE.md says | Code does |
|---|---|---|
| Intraday flow | §4, §8 — 15-minute bars, cron `*/15 9-15` | `interval="1D"`; `INTRADAY_INTERVAL` unused |
| Constituent basket | §3 — top 5 by market cap, weighted | Hard-coded static list, equal `1/n` weights |
| Stealth gate | §16.1 — 5 conditions, ≥ 5 sessions, bottom 40% | 3–5 conditions data-dependent, ≥ 3 sessions, bottom 60% |
| Ranker retrain | §16.4 — monthly, rolling 2y window | Nightly cron `0 2 * * *`, full history |
| Short leg | §18.2/12 — delete from cash leg | `MAX_SHORT_SECTORS = 2`, still publishes `SELL` |
| Backtest benchmark | §11 — VNINDEX buy & hold | Equal-weighted mean of 15 sector `return_1d` |
| Kill-switch | §18.4/20 — `config.trading_halt` | Does not exist |
| ACCUMULATE cap | §16.9 — max 4 positions, auto-exit at 30 sessions | Checked nowhere |
| Purged CV | §18.3/13 — BLOCKER, embargo required | Chronological 80/20, no embargo |
| Data-source fallback | §18.4/17 — BLOCKER, second scraper + alert | vnstock only; degrades silently |

---

## Suggested order of work

Data first, then model, then alpha. Each step is verifiable with a test.

1. **Fix the daily table** — merge the two ingest paths, always write `close_idx` and `return_1d`,
   stop stamping stale bars as new dates. Then re-backfill and delete the three workarounds.
   *(P0-1, P0-2)*
2. **Chain-link `close_idx`** — base 100, compounded weighted returns. Immune to splits and basket
   changes. Required before trusting any return number. *(P0-3)*
3. **Decide `foreign_net`'s fate** — source history, or drop it from the feature set and say so in
   the doctrine. Prerequisite for §16.11 to mean anything. *(P0-5, P1-1)*
4. **Make the ranker measurable** — 22-session embargo, decile monotonicity + NDCG@3, and a loud
   fallback. *(P0-6, P1-2)*
5. **Run the backtest on real signals** — the only door to "does this system have an edge". Steps
   1–4 exist to make that answer trustworthy. *(P0-4)*
6. **Lock the API, merge the rate limiters** — about 20 minutes. *(P2-1, P2-2)*
7. **Reconcile the doctrine** — merge CLAUDE.md and AGENTS.md, close or reopen each §18 item against
   reality, and shrink the divergence table above until it is empty. *(P3-1, P1-5, P1-6, P2-3)*

---

## Verification status

Static review only. The test suite was **not** executed — the in-repo `.venv` is a Windows build and
cannot run from the review environment. Next step is a Linux venv and a pytest baseline before any
line is changed.
