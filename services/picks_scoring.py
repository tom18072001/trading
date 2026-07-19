"""Shared ticker scoring + stop/target/validity helpers.

Lifted from the two divergent call sites (generate_secv3.py::score_symbol,
generate_secv3.py::compute_stop_target/is_valid_buy, and
api/routers/insight.py::_is_valid_long_pick) into one module consumed by
PicksUniverseService + both renderers (email report + Daily Insight).

Invariants enforced:
  target > entry  (no NVL-style targets below close)
  stop   < entry
  upside ≥ 2%
  R:R    ≥ 1.5
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class PickProfile(str, Enum):
    """Sizing profile for a long pick."""
    SWING = "swing"   # 3-4 week horizon: 2.5× ATR target, 1.8× ATR stop
    TPLUS = "tplus"   # 3-5 day horizon:  2.0× ATR target, 1.0× ATR stop


# --- Profile → ATR multipliers ---
_PROFILE_PARAMS: dict[PickProfile, dict[str, float]] = {
    PickProfile.SWING: {"target_atr": 2.5, "stop_atr": 1.8},
    PickProfile.TPLUS: {"target_atr": 2.0, "stop_atr": 1.0},
}

# --- Validity invariants ---
MIN_STOP_PCT    = 0.015   # stop must be at least 1.5% below entry
MIN_UPSIDE_PCT  = 0.02    # target must be at least 2% above entry
MIN_TGT_PCT     = 0.03    # BB-anchored target must clear this or fall back to ATR
MIN_RR          = 1.5     # reward/risk floor for a BUY


def score_ticker(row: dict[str, Any]) -> int:
    """Composite technical score (lifted from generate_secv3.score_symbol).

    Reads from a dict shaped like a TickerRow (price_to_sma_20, price_to_sma_50,
    macd_hist, adx_14, rsi_14, volume_ratio_20). Missing fields are treated as
    neutral (no score contribution).

    Max realistic range: roughly -4 .. +7.
    """
    score = 0
    rsi = row.get("rsi_14")
    macd_h = row.get("macd_hist")
    p_sma20 = row.get("price_to_sma_20")
    p_sma50 = row.get("price_to_sma_50")
    adx = row.get("adx_14")
    vr20 = row.get("volume_ratio_20")

    if p_sma20 is not None and p_sma20 > 0:
        score += 1
    if p_sma50 is not None and p_sma50 > 0:
        score += 1
    if macd_h is not None and macd_h > 0:
        score += 1
    if adx is not None and adx > 20:
        score += 1
    if rsi is not None:
        if 50 <= rsi <= 70:
            score += 2
        elif rsi > 70:
            score -= 1
        elif rsi < 30:
            score += 1
    if vr20 is not None:
        if vr20 > 1.3:
            score += 2
        elif vr20 < 0.7:
            score -= 1
    return score


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
    # Normalize: generate_secv3 used atr_pct as percent (e.g. 2.5 for 2.5%); we
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
        target = close + MIN_RR * downside
        rr = MIN_RR

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
    if rr < MIN_RR:
        return False, f"r_r {rr:.2f} < {MIN_RR}"
    return True, None


__all__ = [
    "PickProfile",
    "score_ticker",
    "compute_stop_target_rr",
    "is_valid_long_pick",
    "MIN_STOP_PCT",
    "MIN_UPSIDE_PCT",
    "MIN_TGT_PCT",
    "MIN_RR",
]
