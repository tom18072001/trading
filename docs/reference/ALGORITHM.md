# Algorithm Documentation — VN Sector Money-Flow & Rotation

Last updated: 2026-08-25 — §4 and §5 rewritten against the code. They had
taught the retired 5-of-5 stealth conjunction and three sub-rules that exist in
no source file (see §4's closing note).

> Authoritative spec: `CLAUDE.md` (APPROVED 2026-04-08). When this document
> and `CLAUDE.md` disagree, `CLAUDE.md` wins. This file is a walkthrough
> of the live algorithm for engineers tuning it — not a standalone contract.

The pre-2026-04-08 doc described a 170-symbol per-stock ML system (RF/XGBoost
/LightGBM classifiers, T+3 scanner, OpenClaw agent). That system is retired;
the code lives under `_legacy_stock*` tables and is scheduled for deletion
in migration 10 after the 2-week shadow window (see `CLAUDE.md` §2).

## 0. One-paragraph overview

The system tracks **money flow across 15 VN sectors** and predicts the next
**sector rotation**. Every trading day it ingests proxy-basket OHLCV + foreign
flow for each sector, rolls up 12 flow features, classifies the macro regime
(Gaussian HMM), ranks sectors with a LightGBM lambdarank on the 20-day
forward return, and publishes signals plus a Gmail briefing written by the
in-process TraderAgent "Minh". §16.3 defines five actions; the signal service
has a path to four — `ACCUMULATE / BUY / SELL / HOLD`. **`TRIM` is rendered by
the frontend and emitted by nothing** (`CLAUDE.md` §22.8).
Per-ticker BUY/SELL cards in the briefing come from
`services.picks_universe_service` (dynamic HOSE universe). The edge thesis is
**stealth accumulation** — buy at the root, ~2-4 weeks before public news
catches up (`CLAUDE.md` §16).

## 1. Data flow

```
 vnstock (KBS)           FRED / stooq / SBV
      │                        │
      ▼                        ▼
 sector_ingest_service    macro_service
      │                        │
      ▼                        ▼
 sector_flow_ts (15m)    macro_anchors
      │                        │
      └──────┬──────────┬──────┘
             ▼          ▼
     flow_feature_service   regime_classify (HMM)
             │                    │
             ▼                    ▼
      sector_flow_daily    sector_regime
             │                    │
             └────────┬───────────┘
                      ▼
             rotation_model_service (LightGBM)
                      │
                      ▼
             sector_signal_service
                      │
                      ▼
   sector_signals  +  picks_universe_service
                      │
                      ▼
             trader_agent (Minh, HTTP -> 9Router)
                      │
                      ▼
        generate_report.py → Gmail (HTML + PDF)
```

Each arrow is a boundary between two services — `CLAUDE.md` §6/§8 owns the
service list; `ARCHITECTURE.md` §6/§7 owns the method signatures. The
scheduler (§8) invokes them in the order above.

## 2. Sector construction

The 15 sectors are inherited from the legacy `SECTOR_MAP` (`CLAUDE.md` §3).
Each sector's "proxy basket" = **top-5 constituents by market cap**
(`config.PROXY_BASKETS`). Raw constituent OHLCV is fetched transiently and
discarded after aggregation — only the 60-day rolling window is kept on disk.

**Survivorship hazard (P0, §18.1/1).** The current basket is a frozen
snapshot. Real fix: rebuild monthly from point-in-time market cap and stamp
`constituent_asof` on every `sector_flow_ts` row so backtests read the basket
that was live on each historical date. Tracked under §18 in CLAUDE.md; not yet
shipped.

## 3. Per-sector features (12 core + stealth overlay)

Computed by `flow_feature_service` against the 15-minute `sector_flow_ts`
buffer plus the daily rollup (`sector_flow_daily`):

Core (§4):

- `net_dollar_flow` — sum of signed close × volume across basket.
- `up_vol` / `down_vol` — volume on up-ticks vs down-ticks.
- `foreign_net` — vnstock foreign buy minus sell; the "killer VN signal".
- `breadth_sma20` / `breadth_sma50` — % of basket above SMA20 / SMA50.
- `rs_vnindex_5d` / `rs_vnindex_20d` / `rs_vnindex_60d` — relative strength vs
  VNINDEX across three horizons.
- `atr_pct` — basket-aggregate ATR normalized by close.
- `correlation_20d` — rolling 20d correlation matrix (cross-sector, feeds §18.2).

Stealth overlay (§16.2, added 2026-04-09):

- `flow_z20`, `flow_z60` — 20d / 60d z-score of `net_dollar_flow`.
- `foreign_streak` — consecutive sessions with `foreign_net > 0` (cap 20).
- `foreign_hit_20d` — fraction of last 20 sessions with `foreign_net > 0`.
- `stealth_score` — composite: `flow_z20 × (breadth_sma20 rising) × 1 / (1 + atr_rank_20d)`.
- `flow_price_divergence` — `flow_z20 − return_20d_zscore` (positive = flow leading price).
- `accumulation_age` — days since the §16.1 gate first latched (0 when inactive).

**ETF rebalance scrubbing (P0, §18.1/2).** On FUEVFVND / E1VFVND review
windows, `foreign_net` is distorted by mechanical index flow. The planned
`foreign_net_clean` feature masks those days; not yet in the panel.

## 4. Stealth detection (Tom's edge doctrine — §16.1)

Source of truth: `analysis/stealth.py`. The numbers below are its module
constants, all env-overridable.

The gate is a **score, not a conjunction** (§16.1, amended 2026-08-23). A
sector is in stealth accumulation when it meets **≥ `STEALTH_MIN_CONDITIONS`
of the 5** (default **4**) for ≥ `STEALTH_MIN_SESSIONS` sessions (default
**3**). Requiring all five was measured unreachable: it held on 0.3% of a
13,470-row panel and never for more than 2 consecutive sessions, so
`accumulation_age` was 0 on every row the system ever wrote.

| # | condition | code |
|---|---|---|
| 1 | `flow_z20 > +1.0` | `FLOW_Z_THRESHOLD` |
| 2 | `foreign_hit_20d ≥ 0.6` | `FOREIGN_HIT_THRESHOLD` |
| 3 | `breadth_sma20` rising (5d mean of its diff > 0) | — |
| 4 | `atr_pct` below its own rolling 20d **median** | — |
| 5 | `close_idx` in bottom 40% of its 60d range | `RETURN_BOTTOM_FRAC` |

The five are **deliberately unweighted** — §16.1 gives no basis to rank them,
and an invented weight vector is a number nobody could defend.

**An unevaluable condition leaves both the numerator and the denominator**
(`need = min(STEALTH_MIN_CONDITIONS, len(conds))`), so missing data never
silently raises the bar. Two cases do this: an all-zero `foreign_net` column
drops cond2, and `STEALTH_SYNTHETIC_CLOSE=1` drops cond5 (a synthetic
`close_idx` is derived from net flow, which would make cond5 a restatement of
cond1).

**Where the ACCUMULATE actually comes from.** There is no `stealth_scanner`
job — §16.5 planned one and it was never built, and
`scripts/cleanup_scheduled_tasks.ps1` says so. `accumulation_age` is written
into `sector_flow_daily` by the feature pass, and `SectorSignalService.publish()`
(17:00) reads the latest row per sector and promotes it to `ACCUMULATE`.
`sector_accumulation_events` exists in the schema since migration 9 and has
**no writer** — 0 rows. `/api/stealth/history` derives runs from
`accumulation_age` instead, on purpose (`CLAUDE.md` §22.11): one fact stored
twice is two facts that disagree.

**Cap and auto-exit (§16.9), both enforced in `sector_signal_service.py`:**
concurrent ACCUMULATE is capped at `MAX_ACCUMULATE_SECTORS` (4, oldest runs
kept), and a run past `ACCUMULATE_MAX_AGE_SESSIONS` (30) is released flat
("dry powder reclaimed").

> **This gate has no measurable edge yet (§16.14).** Against no filter at all,
> its 20 firings break out *less* often, *later*, and at a *worse* entry than a
> sector-day drawn at random from the same panel. Treat live `ACCUMULATE` as a
> watchlist, and do not apply §16.9's 1.5× vol target / 2.5×ATR stop to it.

**Not implemented, despite appearing in earlier drafts of this section:**
`foreign_net_z20 ≥ +0.5` as a second half of cond2 (§18.5/21), the
sector-specific 2y quantile for cond4 (§18.3/15 — cond4 uses a rolling 20d
median), and the distribution guard (§18.5/22). All three are still on the
§12 open list below, which is where they belong until code exists.

## 5. Regime classifier

`regime_classify` job (16:30 §8). Gaussian HMM over the **daily VNINDEX series
only** (1d and 5d return, 20d vol — `classify_regime()` passes nothing else, and
since 2026-09-25 it publishes nothing rather than fall back to the hourly
`macro_anchors` rows, or on a day without a session) →
one of exactly four labels — `analysis/regime.py:_LABELS_BY_RETURN` =
`["risk_off", "chop", "rotation", "risk_on"]`, ordered by mean 1d return so the
mapping stays deterministic across refits. The label plus confidence is written
to `sector_regime(date, regime_label, confidence)`.

**`confidence` is not "how sure the model is."** Since 2026-08-24 (`CLAUDE.md`
§25.2) it is **P(this label still holds in `CONF_HORIZON` = 5 sessions)** — the
filtered posterior of the last bar, propagated through the transition matrix and
summed over every state sharing the label. Live range 0.46–0.91. Below 0.55 it
overstates survival, so `confidence_phrase()` appends a hedge there. **Every**
reading also ends "chưa kiểm chứng ngoài mẫu" (2026-09-25): the calibration was
measured in sample, and replayed as published 0.69-0.85 held 0.28-0.58
(`CLAUDE.md` §25, review 2026-09-24 §4.1/7). Filtered (`predict_proba(X[:t+1])[-1]`), not smoothed, so yesterday's
published label cannot change tonight (closes §20.3 P1-4).

`fit()` **refuses a collapsed fit** (>1 empty state) and falls back rather than
publishing the 1.0 that a degenerate model produces by construction. The
fallback path reports the share of the last 10 sessions carrying the same label
— the same question, measured directly, so the two paths are comparable.

**Not implemented:** regime-conditioned stealth z-scores (§18.1/3) — the §16.1
conditions use unconditional rolling z. Nor is there any code that throttles
entries under `chop`; the label is published and read by the report, and that is
all it does today.

## 6. Rotation ranker

`rotation_model_service` trains a LightGBM lambdarank once per day at 02:00
(`rotation_train`) and scores sectors at 16:45 (`rotation_predict`).

Training target (§16.4, amended from §18.3/14):

```
target = 0.4 · fwd_10d + 0.4 · fwd_20d + 0.2 · fwd_40d
```

Primary 20d horizon is the ranker's center; the blended horizon prevents the
model from overfitting a single look-ahead.

Secondary classifier head: "did this sector enter breakout within 15
sessions?" (`1` if `fwd_15d_max_return > 2 × atr_pct`). The two-stage rig
lets the ranker sort by expected return and the classifier cull noise.

Feature set = core (§3) + stealth overlay (§16.2) + regime label one-hot +
macro context. Training window = rolling 2y, monthly retrain (not nightly —
flow regimes change slowly).

**Validation.** López de Prado purged k-fold with embargo =
`max(target_horizon) + 2` (§18.3/13). Random splits are forbidden — always
produce data leakage on this kind of target.

**Drift monitor (§18.3/16, pending).** Nightly job logs ranker top-3 hit-rate
over the last 20 sessions; Gmail alert if < baseline − 1σ for 5 consecutive
days.

## 7. Signal publication

`sector_signal_service.publish()` (17:00 §8) reads the latest ranker output,
the stealth events, and the regime label, then assigns per-sector actions:

| Action     | Trigger                                              | Sizing                          | Stop           |
|------------|------------------------------------------------------|---------------------------------|----------------|
| ACCUMULATE | §16.1 gate latched                                   | 1.5× vol-target (§16.9)         | 2.5 × ATR20    |
| BUY        | Ranker top-`MAX_LONG_SECTORS` AND net **inflow** ≥ 3 sessions | 1.0× vol-target                 | 2.0 × ATR20    |
| TRIM       | `return_20d > 90th pctile` AND `flow_z20` rolling over | cut half                        | move stop up   |
| SELL       | Ranker bottom-`MAX_SHORT_SECTORS` AND net **outflow** ≥ 3 sessions (`ALLOW_SHORT_SIGNALS`) | full exit                       | —              |
| HOLD       | default                                               | no change                       | —              |

None of these actions has an out-of-sample edge (walk-forward IC −0.01, review
2026-09-24 §4.2): they are on the `analysis/verification.py` list and printed
"chưa kiểm chứng". Persistence is directional since 2026-09-25 — it accepted
any run of equal signs, and 24 of 96 BUYs had followed three sessions of
outflow. No signal is published on a day without a session, or when a stored
feature column is NULL for every sector (`FeaturesMissingError`).

**Sizing floor (§18.2/11).** Individual ATR sizing ignores that banks +
brokers + realty move together. The planned fix routes every position through
the rolling 20d correlation matrix and sizes on marginal contribution to
portfolio vol. Not yet live.

**Short leg (§18.2/12).** Shorting the VN cash market is impossible. Any
"short" in the ranker output is executed as either (a) cash flat — reduce
long — or (b) VN30F1M hedge. The "max 2 short" cap in `CLAUDE.md` §10 is
superseded.

**Global kill switch (§18.4/20).** `config.trading_halt: bool` is read at the
top of `publish()`. When true, all new ACCUMULATE / BUY entries are skipped;
HOLD / TRIM / SELL continue.

## 8. Per-ticker picks (2026-04-17 onward)

`generate_report.py` surfaces **per-ticker BUY / ACCUMULATE** cards in the briefing. These come exclusively
from `services.picks_universe_service.PicksUniverseService` — a dynamic HOSE
universe sourced from vnstock Listing, scored by `services.picks_scoring`.

The retired readers on `_legacy_stocks` / `_legacy_stock_prices` /
`_legacy_stock_features` are gone (`CLAUDE.md` §2). Those tables persist for
the 2-week shadow window and drop in migration 10.

**The buy rule since 2026-09-28** (`CLAUDE.md` §28,
`docs/reviews/STRATEGY_STUDY_2026-09-28.md`). One function for every surface:
`long_shortlist`.

- **Ordering key.** `services.buy_layer.risk_adjusted_momentum`:
  `(close[t−5] / close[t−126] − 1) / std(daily returns, last 126)`.
- **Book.** Top 8, equal weight. Review every 20 sessions; keep a name while it
  ranks in the top 16.
- **No gates.** No SMA200 gate and no market switch. The switch lost 21.5% in
  the holdout year.
- **Annotation on every BUY** (`buy_layer.annotate`):
  - accept range = [close × (1 − 2σ₆₃), close × 1.01];
  - measured 4- and 8-week outcome band, standardised by the name's own σ and
    split by VNINDEX above / below its 200-session average.
- **Audit shadow.** The previous rule (SMA200 gate → score/OBV blend) is
  `legacy_shortlist`, archived daily for `daily_watch/audit.py`.

**For a trader buying a few names on his own days (2026-09-29,
`docs/reviews/WORKFLOW_STUDY_2026-09-29.md`).**

- **Priority.** The list's set is still the momentum top 8; it is ordered A
  (in the top 8 on each of the last 11 sessions, `buy_layer.top_runs` over
  `TickerRow.momentum_hist`) before B, rank inside each. Pre-registered, passed
  on DEV, same sign on the holdout, small and unsteady.
- **Sell, per position.** `daily_watch/sell_range.schedule` + `verdict`: each
  position is reviewed at sessions 20, 40, 60 … after its own buy date and sold
  at a review where it ranks outside the top 16. No hard cap, no take profit, no
  cut loss — all measured worse or unstable. A missed sale is read back from the
  archive; an undated position is judged on today's rank; a holding outside the
  basket gets an equivalent rank from the same score.
- **Book.** `trading_state.record_buy` adds at the quantity-weighted average
  cost; `close_position(qty=…)` sells part. CLI: `python -m daily_watch.book`.

## 9. TraderAgent "Minh"

`services.trader_agent.TraderAgent` runs **in-process**. Since 2026-07-20 the
default provider is `local` — plain HTTP to an OpenAI-compatible
`/chat/completions` endpoint, no `claude_agent_sdk`. "Local" names the
transport, not where the model runs: it points at 9Router
(`LOCAL_BASE_URL`, default `http://localhost:20128/v1`), a local router
fronting hosted Claude models, with `LOCAL_MODEL` default `claude-opus-5`.
Alternatives via `AGENT_PROVIDER`: `glm` or `claude`. See `CLAUDE.md` §14.
Invoked from
`POST /api/insight/refresh`. Inputs: today's sector rankings, stealth
events, regime label, macro snapshot, picks universe. Output: a
Vietnamese-language briefing rendered inline on the Daily Insight page and
embedded at the top of the email.

When the configured provider is unreachable, the generator falls back to the
algorithmic narrative and logs `[trader-agent] query failed`. This is not a
production regression — the sector tables, cards and PDF are unaffected
(`CLAUDE.md` §19).

## 10. Email delivery

`generate_report.py` renders:

- `report/daily_report_<DATE>.html` — inline-styled HTML with embedded charts.
- `report/daily_report_<DATE>.pdf` — WeasyPrint render of the same HTML.

SMTP: Gmail App Password over SSL:465. `REPORT_EMAIL_TO` is comma-separated and
lives only in the local `.env` — the repo is public, so no recipient list is
committed and there is no fallback in code. Every configured address appears in
the `To:` header (not BCC).

The scheduled-task wrapper is `scripts/jobs/job_sector_signal_publish.bat`;
register it with `scripts/register_report_task.ps1`. Job logs land in
`report/jobs/`.

## 11. Backtest contract

`backtest_service` runs the live pipeline on history and measures against
VNINDEX buy-and-hold. Baseline targets (`CLAUDE.md` §11):

- Sharpe > 1.0
- MaxDD < 15%
- Top-rank hit-rate > 55%

Trader-lens additions (§18.7):

- **Net-of-cost Sharpe ≥ 0.8** — after fees (`fee_bps=15`/side),
  sell tax (`sell_tax_bps=10`), slippage (0.3% per side, flat since
  2026-09-25 — it was `max(0.3%, 0.5 × ATR%)`), and ±7%
  price-band miss modeling, on a book re-cut every 20 or 40 sessions
  (`config.HOLD_SESSIONS`). The T+2 settlement lag was modelled until
  2026-09-25 and removed with the T+ mode — at a 20-session hold it cannot bind.
- **Max adverse excursion on ACCUMULATE ≤ 6%** — early entries cannot bleed
  more than this before working, or the "root" thesis is false.
- **Decile monotonicity** — mean fwd 20d return must be monotone across
  score deciles on out-of-sample data.

Entry-timing attribution (§16.6):

- **Median entry lag ≥ 10 trading days** — Tom bought ≥ 2 weeks before the
  move.
- **Root capture ratio ≤ 0.85** — entered in the bottom 15% of the eventual
  move.

## 12. Known open items (from §18 trader-lens review)

P0 (must ship before live paper-trade):

- §18.1/1 point-in-time constituents
- §18.1/2 ETF rebalance mask
- §18.2/8 FOL (foreign ownership room) check
- §18.4/17 secondary HOSE scraper fallback

Closed since this list was written — **in the backtest engine only**. §18.2/9
(±7% band + slippage) and /10 (fee + sell tax) are modelled and reported on
every run since 2026-08-22, and surfaced in the UI since §23. §18.2/7 (T+2
settlement) was modelled the same day and removed on 2026-09-25 with the T+
mode (Tom: 4- and 8-week holds only). They stay **open in `risk_service`**, which still sizes positions
with no cost model. §18.3/13 (purged k-fold, embargo = horizon + 2) closed the
same day in `models/rotation_ranker.py`.

P1 (before shadow-run metrics matter):

- §18.1/3 regime-conditioned z
- §18.1/4 VN30F1M basis + OI macro features
- §18.1/5 broker margin debt macro feature
- §18.1/6 full-population breadth (two tools: flow on top-5, breadth on all)
- §18.2/11 portfolio-vol sizing
- §18.2/12 short leg via VN30F1M only
- §18.3/14 blended horizon target
- §18.3/15 sector-specific quantile thresholds in §16.1
- §18.5/21 stealth two-check foreign confirmation — **not in `analysis/stealth.py`**;
  cond2 is the hit rate alone. §16.11's 2026-08-24 experiment found the
  persistence form (`foreign_streak ≥ 3`) is the only variant that beat the
  unconditional base rate, and did not ship it either (n=16, and the whole
  effect predates 2026)
- §18.5/22 stealth distribution guard — no code

Every P0 / P1 item must close with evidence (backtest diff, unit test, or
data proof) — not just code — per `CLAUDE.md` §18.8.

## 13. How to tune something

1. Read `CLAUDE.md` §14 to see whether the knob is a decided default.
2. If it is, edit `CLAUDE.md`, log in `MODIFICATION_LOG.md`, update the
   affected spec in `specs/`.
3. If it is an internal hyperparameter (e.g., LightGBM `num_leaves`,
   `STEALTH_MIN_CONDITIONS` / `STEALTH_MIN_SESSIONS`), change it in the
   relevant service,
   re-run backtest, compare net-of-cost Sharpe + decile monotonicity +
   median entry lag.
4. Ship only when the new number beats baseline **on out-of-sample data** —
   in-sample improvement is not evidence (`CLAUDE.md` §18.8).

---
*This document is a walkthrough, not a contract. Contracts live in `CLAUDE.md`,
`ARCHITECTURE.md`, and `specs/`.*
