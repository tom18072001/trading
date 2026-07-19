# Algorithm Documentation — VN Sector Money-Flow & Rotation

Last updated: 2026-04-22 (Phase 16 cleanup).

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
forward return, and publishes signals (`ACCUMULATE / BUY / HOLD / TRIM /
SELL`) plus a Gmail briefing written by the in-process TraderAgent "Minh"
(`claude_agent_sdk`). Per-ticker BUY/SELL cards in the briefing come from
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
             trader_agent (Minh, claude_agent_sdk)
                      │
                      ▼
        generate_secv4.py → Gmail (HTML + PDF)
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

A sector is in **stealth accumulation** when ALL five conditions hold
simultaneously for ≥ 5 sessions:

1. `flow_z20 > +1.0`
2. `foreign_hit_20d ≥ 0.6` **AND** `foreign_net_z20 ≥ +0.5` (§18.5/21
   two-check tightening)
3. `breadth_sma20` rising
4. `atr_pct` below its 20d median — evaluated against the **sector's own 2y
   quantile**, not a cross-sector number (§18.3/15)
5. `close_idx` in bottom 40% of its 60d range

When all five latch, `stealth_scanner` (17:00 job, §16.5) emits an
`ACCUMULATE` row into `sector_signals` and opens an event in
`sector_accumulation_events`.

**Distribution guard (§18.5/22).** During an open stealth window, if any
single session posts `up_vol / down_vol < 0.5` AND `foreign_net < 0`, the
event is invalidated immediately — smart money is leaving.

**Auto-exit (§16.9).** If a sector spends > 30 sessions in stealth without
breaking out, the position auto-exits flat ("dry powder reclaimed").

## 5. Regime classifier

`regime_classify` job (16:30 §8). Gaussian HMM over macro + VNINDEX returns →
one of four labels: `risk_on`, `risk_off`, `rotation`, `chop`. The label plus
confidence is written to `sector_regime(date, regime_label, confidence)`.
Downstream, the §16.1 stealth z-scores are evaluated on the
**regime-conditioned** distribution (§18.1/3) — a +1.0 z20 under `risk_off`
is a different beast than under `risk_on`.

`CHOP` behavior is explicitly de-risked: correlations rise, edges shrink, and
the system throttles new entries.

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
| BUY        | Ranker top-3 AND price confirming                     | 1.0× vol-target                 | 2.0 × ATR20    |
| TRIM       | `return_20d > 90th pctile` AND `flow_z20` rolling over | cut half                        | move stop up   |
| SELL       | `flow_z20 < 0` AND price still high                   | full exit                       | —              |
| HOLD       | default                                               | no change                       | —              |

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

`generate_secv4.py` (and the rollback `generate_secv3.py`) surface
**per-ticker BUY / ACCUMULATE** cards in the briefing. These come exclusively
from `services.picks_universe_service.PicksUniverseService` — a dynamic HOSE
universe sourced from vnstock Listing, scored by `services.picks_scoring`.

The retired readers on `_legacy_stocks` / `_legacy_stock_prices` /
`_legacy_stock_features` are gone (`CLAUDE.md` §2). Those tables persist for
the 2-week shadow window and drop in migration 10.

## 9. TraderAgent "Minh"

`services.trader_agent.TraderAgent` runs **in-process** via `claude_agent_sdk`
(uses Tom's Claude Code subscription, no separate API key). Invoked from
`POST /api/insight/refresh`. Inputs: today's sector rankings, stealth
events, regime label, macro snapshot, picks universe. Output: a
Vietnamese-language briefing rendered inline on the Daily Insight page and
embedded at the top of the email.

When the Claude CLI is unavailable (e.g., sandbox, offline), the generator
falls back to the algorithmic narrative and logs `[trader-agent] query
failed`. This is not a production regression — the sector tables, cards, and
PDF are unaffected (`CLAUDE.md` §19 and `docs/DAILY_REPORT_AUTOMATION.md`).

## 10. Email delivery

`generate_secv4.py` renders:

- `report/secv4_<DATE>.html` — inline-styled HTML with embedded charts.
- `report/secv4_<DATE>.pdf` — WeasyPrint render of the same HTML.

SMTP: Gmail App Password over SSL:465. `REPORT_EMAIL_TO` is comma-separated;
current production value = `anhchitruong18@gmail.com,hill.nguyen.1373@gmail.com`.
Both addresses appear in the `To:` header (not BCC).

See `docs/DAILY_REPORT_AUTOMATION.md` for the scheduled-task wrapper,
log paths, and manual re-send procedure.

## 11. Backtest contract

`backtest_service` runs the live pipeline on history and measures against
VNINDEX buy-and-hold. Baseline targets (`CLAUDE.md` §11):

- Sharpe > 1.0
- MaxDD < 15%
- Top-rank hit-rate > 55%

Trader-lens additions (§18.7):

- **Net-of-cost Sharpe ≥ 0.8** — after fees (`fee_bps=15`/side),
  sell tax (`sell_tax_bps=10`), slippage (`max(0.3%, 0.5 × ATR%)`), T+2
  settlement lag, and ±7% price-band miss modeling.
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
- §18.2/7 T+2.5 settlement lag in backtest
- §18.2/8 FOL (foreign ownership room) check
- §18.2/9 price-band + slippage realism
- §18.2/10 fees + sell tax
- §18.3/13 purged k-fold with embargo
- §18.4/17 secondary HOSE scraper fallback

P1 (before shadow-run metrics matter):

- §18.1/3 regime-conditioned z
- §18.1/4 VN30F1M basis + OI macro features
- §18.1/5 broker margin debt macro feature
- §18.1/6 full-population breadth (two tools: flow on top-5, breadth on all)
- §18.2/11 portfolio-vol sizing
- §18.2/12 short leg via VN30F1M only
- §18.3/14 blended horizon target
- §18.3/15 sector-specific quantile thresholds in §16.1
- §18.5/21 stealth two-check foreign confirmation (flagged as implemented in §4 above once feature lands)
- §18.5/22 stealth distribution guard

Every P0 / P1 item must close with evidence (backtest diff, unit test, or
data proof) — not just code — per `CLAUDE.md` §18.8.

## 13. How to tune something

1. Read `CLAUDE.md` §14 to see whether the knob is a decided default.
2. If it is, edit `CLAUDE.md`, log in `MODIFICATION_LOG.md`, update the
   affected spec in `specs/`.
3. If it is an internal hyperparameter (e.g., LightGBM `num_leaves`,
   stealth N=5 session requirement), change it in the relevant service,
   re-run backtest, compare net-of-cost Sharpe + decile monotonicity +
   median entry lag.
4. Ship only when the new number beats baseline **on out-of-sample data** —
   in-sample improvement is not evidence (`CLAUDE.md` §18.8).

---
*This document is a walkthrough, not a contract. Contracts live in `CLAUDE.md`,
`ARCHITECTURE.md`, and `specs/`.*
