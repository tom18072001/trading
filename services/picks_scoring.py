"""Shared ticker scoring + stop/target/validity helpers.

Lifted from the two divergent call sites (the report generator's score_symbol
and compute_stop_target/is_valid_buy — then SecV3, now generate_report.py —
and api/routers/insight.py::_is_valid_long_pick) into one module consumed by
PicksUniverseService + both renderers (email report + Daily Insight).

Invariants enforced:
  target > entry  (no NVL-style targets below close)
  stop   < entry
  upside ≥ 2%
  R:R    ≥ 1.5
"""
from __future__ import annotations

import math

from datetime import date
from enum import Enum
from typing import Any

from config import HOLD_SESSIONS


class PickProfile(str, Enum):
    """Sizing profile for a long pick.

    One member since 2026-09-25. TPLUS (3-5 sessions, 2.0x/1.0x ATR) was
    removed with the T+ trading mode -- Tom: "bỏ T+2, chỉ sử dụng 4 tuần và 8
    tuần". The enum stays so the stop/target call sites keep one explicit
    argument instead of an implicit default.
    """
    SWING = "swing"   # 2.5x ATR target, 1.8x ATR stop -- a SCREENING geometry


# --- Profile → ATR multipliers ---
_PROFILE_PARAMS: dict[PickProfile, dict[str, float]] = {
    PickProfile.SWING: {"target_atr": 2.5, "stop_atr": 1.8},
}

# --- Holding period: 4 or 8 weeks, and nothing shorter ------------------------
# 2026-09-25, Tom: "bỏ T+2, chỉ sử dụng 4 tuần và 8 tuần". The horizon lives in
# config.HOLD_SESSIONS so the sell window, the bulletin, the benches and the
# sector backtest cannot drift apart.
#
# Why these two, measured (docs/reviews/ALGO_REVIEW_2026-09-24.md §3.1): as a
# staggered book, 2023-01..2026-09, 1.00% round trip, the SMA200-gated blend
# ordering earns -2.1%/yr at 10 sessions, 7.2% at 20 and 11.7% at 40, then goes
# flat -- 10.6% at 60, 10.9% at 120 (VNINDEX: 17.5% on the same dates). Most of
# that climb is the cost being spread over fewer round trips (12.6%/yr at 20
# sessions, 6.3% at 40), which is why the default is to hold to ~40 and why
# session 20 is not a sell signal.
#
# The stop/target that `compute_stop_target_rr` returns is NOT part of the
# instruction. It is a screening by-product (`is_valid_long_pick` needs a stop
# below entry to compute its R:R floor); the book has had no stop since
# 2026-09-16 (CLAUDE.md §26.10).


def horizon_note() -> str:
    """One VN sentence naming the holding period, printed on every BUY card.

    It lives beside the scoring, not in a renderer, so whoever changes the
    horizon owns the sentence describing it -- the same placement argument
    25.6 made for `confidence_phrase`.
    """
    lo, hi = HOLD_SESSIONS
    return (f"Giữ {lo}-{hi} phiên (4-8 tuần), mặc định tới ~{hi} phiên; "
            f"phiên {lo} không phải tín hiệu bán. Mua ATO phiên sau, bán ATO ngày thoát.")


def hold_window(as_of: date) -> dict[str, str | None]:
    """Sell window for a buy filled at the ATO of the session after `as_of`.

    `sell_from` opens the window (4 weeks), `sell_by` closes it (8 weeks).
    Counted in trading SESSIONS with the holiday-aware calendar, never calendar
    days: a Thursday buy plus 20 days is not 20 sessions.
    """
    try:
        from utils.clock import next_trading_day
        lo, hi = HOLD_SESSIONS
        d0 = next_trading_day(as_of, 1)
        return {"sell_from": next_trading_day(d0, lo).isoformat(),
                "sell_by": next_trading_day(d0, hi).isoformat()}
    except (ValueError, TypeError, ImportError):
        return {"sell_from": None, "sell_by": None}


# --- Validity invariants ---
MIN_STOP_PCT    = 0.015   # stop must be at least 1.5% below entry
MIN_UPSIDE_PCT  = 0.02    # target must be at least 2% above entry
MIN_TGT_PCT     = 0.03    # BB-anchored target must clear this or fall back to ATR
MIN_RR          = 1.5     # reward/risk floor for a BUY


# --- Ranking coefficients (measured, see below) -------------------------------
# These live here, in one place, and `scripts/ticker_alpha_bench.py` imports
# them to build its vectorised twin. A formula defined in two files is two
# formulas, and they drift silently -- the same reasoning that moved the stealth
# breakout bar into `analysis/stealth.py` (CLAUDE.md 22.11).
W_OVERSOLD_DIV  = 10.0   # (50 - RSI2) / this  ->  roughly +5 .. -5
W_PULLBACK_CLIP = 2.0    # today's move measured in the stock's own ATRs, clipped
W_ABOVE_SMA50   = 2.0    # medium-term trend still intact
W_WIDE_ATR_PEN  = 1.5    # penalty for a name too wild for its own target
WIDE_ATR_PCT    = 3.5    # "too wild" threshold, in percent
SCORE_CONST     = -1.0   # rank-irrelevant; kept so the shipped score and the
                         # bench factor are the same number, not just the same order
# No confirmed uptrend -> must sort below EVERY gated name. The worst score a
# gated name can reach is -9.5 (-1 const, -5 oversold, -2 pullback, -1.5 ATR),
# so the floor sits clear of it; -9.0 would have let a badly-scored gated name
# rank below an ungated one, which is the opposite of the gate's intent.
UNTRENDED_FLOOR = -20.0

# --- Shortlist thresholds, both measured on the same panel ---------------------
# MIN_BUY_SCORE: the 78th percentile of gated scores over 143 names x 1,168
# sessions (p80 = +2.91, p90 = +4.12), and the 5th-best name on a median day
# scores +3.64 -- so this admits a full shortlist on a normal day and thins it
# on a bad one, which is the behaviour wanted. It replaces a literal `>= 3` on
# the old 0..7 integer scale, which means nothing on this one.
MIN_BUY_SCORE = 2.5

# MAX_5D_DROP_PCT: a free-fall guard, NOT a momentum filter. The rule it
# replaces was `ret_5d > -1`, which excluded every name that had pulled back --
# i.e. exactly the names the scoring rewrite is built to find. But the extreme
# tail is genuinely toxic: `B_rev5_trimmed` in the bench shows the worst weekly
# losers keep falling (they are down on news, not on liquidity demand), so the
# floor stays, an order of magnitude lower.
MAX_5D_DROP_PCT = -12.0

# --- Cross-sectional ordering (2026-09-16, second pass) -----------------------
# `score_ticker` answers "is this name worth owning" from one row. It cannot
# answer "which of the worthy ones first" as well, because the term that most
# improves the ORDER -- on-balance-volume trend -- only works once it is ranked
# against the rest of the day's cross-section.
#
# Measured at exit +20 sessions over 143 names x 1,168 sessions:
#
#   ordering                       excess   IC (t)   quintiles      by year
#   score alone                    +0.13%   2.6      NOT monotone   3 of 4 +
#   score + OBV, added per row     +0.23%   3.0      NOT monotone   3 of 4 +
#   score + OBV, blended by RANK   +0.49%   4.4      monotone       4 of 4 +
#
# and at exit +40 the same ordering gives +0.77% excess, IC t = 3.6, monotone
# (+1.60 / +1.78 / +2.17 / +2.34 / +2.56), again positive in all four years.
#
# The rank form is the only one monotone Q1->Q5 and the only one positive in
# every year it can be evaluated. Adding the raw value instead lets one day's
# dispersion decide whether the term dominates or vanishes; ranking removes
# that. The gap between the per-row and rank rows is also why `_pct_rank` puts
# a missing value mid-pack: with ranks, "unknown" has a natural neutral.
#
# Weights are 50/50 on purpose. A fitted weight vector over ~48 independent
# 20-session windows is a curve fit nobody could defend -- the same argument
# 16.1 makes about leaving the five stealth conditions unweighted.
W_RANK_SCORE = 0.5
W_RANK_OBV = 0.5


def _pct_rank(values: list[float | None]) -> list[float]:
    """Percentile rank in 0..1, ties averaged. A missing value ranks mid-pack
    (0.5) rather than last: absent data is not evidence against a name, and
    sending it to the bottom would quietly re-create the gate asymmetry
    16.1 had to fix in the stealth conditions."""
    present = [(v, i) for i, v in enumerate(values) if v is not None and v == v]
    out = [0.5] * len(values)
    if len(present) < 2:
        return out
    present.sort(key=lambda t: t[0])
    n = len(present)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and present[j + 1][0] == present[i][0]:
            j += 1
        avg = (i + j) / 2.0 / (n - 1)          # 0..1
        for k in range(i, j + 1):
            out[present[k][1]] = avg
        i = j + 1
    return out


def blended_rank_scores(
    scores: list[float | None], obv_trends: list[float | None]
) -> list[float]:
    """Final ordering key for a day's shortlist. Higher = buy first.

    Takes two parallel lists rather than objects so it stays pure and the
    measurement bench can call it on panel columns without constructing rows.

    CALLERS MUST GATE FIRST. With equal weights the best score paired with the
    worst flow ties the worst score paired with the best flow (0.5 + 0 either
    way), so this is an ordering for names already judged worth owning, not a
    filter. `_select_top` applies MIN_BUY_SCORE before consulting it, and
    `test_flow_cannot_rescue_a_name_the_score_gate_rejects` pins that.
    """
    rs = _pct_rank(list(scores))
    ro = _pct_rank(list(obv_trends))
    # strict: the two lists describe the same names in the same order, so a
    # length mismatch is a caller bug and must not be silently truncated
    # into a shortlist that quietly drops its tail.
    return [W_RANK_SCORE * a + W_RANK_OBV * b
            for a, b in zip(rs, ro, strict=True)]


def score_ticker(row: dict[str, Any]) -> float:
    """Composite ranking score for a long candidate. Higher = better. Range ~ -9 .. +7.

    MEASURED, 2026-09-16. The rule this replaced was a 0..7 count of
    trend-continuation conditions (above SMA20, above SMA50, MACD>0, ADX>20,
    RSI 50-70, volume surge), tie-broken by 20d dollar volume. Scored over
    143 HOSE names x 1,168 sessions by `scripts/ticker_alpha_bench.py`:

        rule                    excess vs base rate, exit +3 sessions
        old score               -0.06%   quintiles NOT monotone (Q5 < Q4)
        old score + dv tiebreak -0.15%   the worst variant measured
        this score              +0.21%   monotone, IC t = +7.9

    and by calendar year the old score was NEGATIVE in four of five
    (2023 -0.16, 2024 -0.15, 2025 -0.02, 2026 -0.48) while this one is
    positive in every year it can be evaluated (+0.21, +0.22, +0.15, +0.29).
    2022 is blank for both gated variants: SMA200 needs 200 sessions and the
    panel starts in 2022-01.

    Why these terms, and not the old ones: the product is a 1-4 week trade, and
    at that horizon Vietnamese cross-sectional returns are dominated by
    short-horizon MEAN REVERSION, not continuation. The old score bought names
    that had already run -- above both averages, MACD positive, RSI 50-70, on a
    volume spike -- which is the canopy 16 explicitly tells this system not to
    buy. Three terms survived measurement:

      * `oversold`  -- RSI(2), the Connors oscillator. Single strongest factor
        in the bench (IC +0.037, t = 7.3 at +3 sessions).
      * `pullback`  -- today's move divided by the stock's own ATR. Self-
        normalising, so a 2% drop in a quiet bank and a 2% drop in a wild
        broker are not treated as the same event. No cross-section needed.
      * `above SMA50` / `above SMA200` -- direction. Un-gated mean reversion
        buys falling knives; it was measurably worse in every table.

    The ATR penalty is the term that carries 2026: without it the score is
    -0.11% in that year and +0.29% with it, which matches 25.9's finding that
    high volatility is where these models degrade.

    Missing inputs are treated as neutral, EXCEPT a missing SMA200, which cannot
    confirm an uptrend and therefore sorts the name to the floor rather than
    silently passing the gate.
    """
    close = row.get("close") or 0.0
    rsi2 = row.get("rsi_2")
    ret_1d = row.get("ret_1d")          # percent units, e.g. -1.8 for -1.8%
    atr_pct = row.get("atr_pct")        # percent units, e.g. 2.5 for 2.5%
    p_sma50 = row.get("price_to_sma_50")
    p_sma200 = row.get("price_to_sma_200")

    score = SCORE_CONST

    if rsi2 is not None:
        score += (50.0 - float(rsi2)) / W_OVERSOLD_DIV

    if ret_1d is not None and atr_pct:
        atr_frac = float(atr_pct) / 100.0
        if atr_frac > 0:
            drop_in_atrs = -(float(ret_1d) / 100.0) / atr_frac
            score += max(-W_PULLBACK_CLIP, min(W_PULLBACK_CLIP, drop_in_atrs))

    if p_sma50 is not None and p_sma50 > 0:
        score += W_ABOVE_SMA50

    if atr_pct is not None and float(atr_pct) > WIDE_ATR_PCT:
        score -= W_WIDE_ATR_PEN

    # Trend gate. Not a multiplier and not an exclusion: an ungated name still
    # gets a number, so nothing downstream has to handle a missing score, but
    # it sorts below every name whose uptrend is confirmed.
    if not (p_sma200 is not None and p_sma200 > 0 and close > 0):
        score = min(score, UNTRENDED_FLOOR)

    return round(score, 2)


def compute_stop_target_rr(
    row: dict[str, Any],
    profile: PickProfile = PickProfile.SWING,
) -> tuple[float | None, float | None, float | None, str | None]:
    """Return (stop, target, rr, err) for a long pick.

    Enforces:
      stop  ≤ close × (1 − MIN_STOP_PCT)
      target ≥ close × (1 + MIN_TGT_PCT)
      rr = (target − close) / (close − stop) ≥ MIN_RR  (target stretched if needed)

    err is non-None only when no valid pick can be constructed (missing close).
    Target is stretched to meet MIN_RR rather than dropping the pick — callers
    decide whether to accept or reject via is_valid_long_pick().
    """
    close = row.get("close") or 0
    if close <= 0:
        return None, None, None, "no close"

    atr_pct = row.get("atr_pct") or 0     # already a percent (0..100) or a fraction?
    # Normalize: the report generator used atr_pct as percent (e.g. 2.5 for 2.5%); we
    # keep that convention here too. If callers pass a fraction (0.025), detect
    # and coerce.
    if 0 < atr_pct < 0.5:
        atr_pct *= 100.0  # caller passed a fraction

    params = _PROFILE_PARAMS[profile]
    bb_l = row.get("bb_lower")
    bb_u = row.get("bb_upper")

    # --- stop: profile-ATR below close; anchor near BB lower if it lies below ---
    stop = close * (1 - params["stop_atr"] * (atr_pct / 100)) if atr_pct else None
    if bb_l and stop is not None and bb_l < close:
        stop = max(stop, bb_l * 0.995)
    if stop is None or stop >= close * (1 - MIN_STOP_PCT):
        stop = close * (1 - MIN_STOP_PCT)

    # --- target: higher of BB upper (if above MIN_TGT) and ATR target; floor MIN_TGT ---
    atr_target = close * (1 + params["target_atr"] * (atr_pct / 100)) if atr_pct else None
    bb_target = bb_u if (bb_u and bb_u > close * (1 + MIN_TGT_PCT)) else None
    candidates = [t for t in (bb_target, atr_target) if t and t > close * (1 + MIN_TGT_PCT)]
    target = max(candidates) if candidates else close * (1 + MIN_TGT_PCT)

    # --- enforce MIN_RR: stretch target (do not drop pick here) ---
    downside = close - stop
    upside = target - close
    rr = (upside / downside) if downside > 0 else 0
    if rr < MIN_RR and downside > 0:
        # Round the stretched target UP to the cent. The values returned below
        # are rounded to 2dp, and is_valid_long_pick RECOMPUTES r:r from those
        # rounded numbers -- so rounding the target down here shaves the ratio
        # to 1.4999... and the pick is then rejected by its own floor with the
        # self-contradictory message "r_r 1.50 < 1.5". Observed 2026-08-22:
        # five BUY picks (SSI, SHS, DGW, FPT, PNJ) were dropped from the daily
        # email this way. Rounding up keeps the stretch intact through the
        # rounding step.
        target = math.ceil((close + MIN_RR * downside) * 100.0) / 100.0
        rr = (target - close) / downside

    return round(stop, 2), round(target, 2), round(rr, 2), None


def is_valid_long_pick(
    entry: float | None, target: float | None, stop: float | None
) -> tuple[bool, str | None]:
    """Guard rail for a long (BUY/ACCUMULATE) pick. Returns (ok, reason_if_invalid)."""
    if entry is None or target is None or stop is None:
        return False, "missing entry/target/stop"
    if entry <= 0:
        return False, "invalid entry"
    if target <= entry:
        return False, f"target {target} <= entry {entry}"
    if stop >= entry:
        return False, f"stop {stop} >= entry {entry}"
    upside = (target - entry) / entry
    if upside < MIN_UPSIDE_PCT:
        return False, f"upside only {upside*100:.1f}%"
    downside = entry - stop
    rr = (target - entry) / downside if downside > 0 else 0
    # Compare at the precision the numbers are actually carried at. entry /
    # target / stop arrive rounded to 2dp, so a ratio built from them can sit a
    # hair under the floor purely from rounding -- which produced the absurd
    # "r_r 1.50 < 1.5" rejections. Judge it on the same 2dp the message prints.
    if round(rr, 2) < MIN_RR:
        return False, f"r_r {rr:.2f} < {MIN_RR}"
    return True, None


__all__ = [
    "PickProfile",
    "horizon_note",
    "hold_window",
    "MIN_BUY_SCORE",
    "MAX_5D_DROP_PCT",
    "UNTRENDED_FLOOR",
    "score_ticker",
    "compute_stop_target_rr",
    "is_valid_long_pick",
    "MIN_STOP_PCT",
    "MIN_UPSIDE_PCT",
    "MIN_TGT_PCT",
    "MIN_RR",
]
