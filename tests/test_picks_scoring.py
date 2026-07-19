"""Tests for services.picks_scoring — the shared scoring + validity module
consumed by generate_secv3.py, PicksUniverseService, and insight.py.

These tests anchor the invariants that the NVL-style "target below close"
bug must never return. Any change to the scoring/stop/target rules must
keep these green.
"""
from __future__ import annotations

import pytest

from services.picks_scoring import (
    MIN_RR,
    MIN_STOP_PCT,
    MIN_UPSIDE_PCT,
    PickProfile,
    compute_stop_target_rr,
    is_valid_long_pick,
    score_ticker,
)


# -------------------- score_ticker --------------------


def test_score_ticker_all_fields_missing_returns_zero():
    # When every indicator is None the score is trivially 0 (neutral), not a crash.
    assert score_ticker({}) == 0


def test_score_ticker_strong_bullish_setup():
    row = {
        "rsi_14": 58,            # +2 (50..70 range)
        "macd_hist": 0.15,       # +1
        "price_to_sma_20": 0.02, # +1 (above SMA20)
        "price_to_sma_50": 0.04, # +1 (above SMA50)
        "adx_14": 28,            # +1 (trend strength)
        "volume_ratio_20": 1.4,  # +2 (volume surge)
    }
    # 2 + 1 + 1 + 1 + 1 + 2 = 8
    assert score_ticker(row) == 8


def test_score_ticker_overbought_penalised():
    row = {"rsi_14": 78}       # > 70 → -1
    assert score_ticker(row) == -1


def test_score_ticker_oversold_credited():
    row = {"rsi_14": 25}       # < 30 → +1 (contrarian long setup)
    assert score_ticker(row) == 1


def test_score_ticker_low_volume_penalised():
    row = {"volume_ratio_20": 0.5}
    assert score_ticker(row) == -1


# -------------------- compute_stop_target_rr --------------------


def test_compute_stop_target_nvl_style_target_always_above_close():
    """Regression guard: the NVL bug was bb_upper < close leaking into target.

    Close 16, bb_upper 15 (below close!). Target must NOT end up at 15.
    """
    p = {"close": 16.0, "atr_pct": 0.5, "bb_upper": 15.0, "bb_lower": 14.0}
    stop, target, rr, err = compute_stop_target_rr(p, PickProfile.SWING)
    assert err is None
    assert target > p["close"], f"target {target} must be > close {p['close']}"
    assert stop < p["close"], f"stop {stop} must be < close {p['close']}"
    assert rr >= MIN_RR


def test_compute_stop_target_healthy_case():
    p = {"close": 28.0, "atr_pct": 2.0, "bb_upper": 30.0, "bb_lower": 26.0}
    stop, target, rr, err = compute_stop_target_rr(p, PickProfile.SWING)
    assert err is None
    assert stop is not None and target is not None
    assert stop < 28.0 < target
    assert rr >= MIN_RR


def test_compute_stop_target_zero_close_returns_error():
    stop, target, rr, err = compute_stop_target_rr({"close": 0}, PickProfile.SWING)
    assert err == "no close"
    assert stop is None and target is None and rr is None


def test_compute_stop_target_tplus_vs_swing_profile():
    """TPLUS uses tighter ATR multipliers → tighter stop, smaller target."""
    p = {"close": 100.0, "atr_pct": 3.0, "bb_upper": None, "bb_lower": None}
    s_swing, t_swing, rr_swing, _ = compute_stop_target_rr(p, PickProfile.SWING)
    s_tplus, t_tplus, rr_tplus, _ = compute_stop_target_rr(p, PickProfile.TPLUS)
    # SWING = 1.8× ATR stop, 2.5× ATR target
    # TPLUS = 1.0× ATR stop, 2.0× ATR target
    # Both stops must be below close; TPLUS stop is CLOSER to close.
    assert s_swing < s_tplus < p["close"]
    # Both targets above close; SWING target is FURTHER from close.
    assert t_tplus < t_swing
    assert t_tplus > p["close"]


def test_compute_stop_target_accepts_fractional_atr_input():
    """If caller accidentally passes atr as a fraction (0.025 == 2.5%), the
    function should auto-detect and coerce — prevents silent wrong stops."""
    p_pct = {"close": 100.0, "atr_pct": 2.5, "bb_upper": None, "bb_lower": None}
    p_frac = {"close": 100.0, "atr_pct": 0.025, "bb_upper": None, "bb_lower": None}
    s_pct, t_pct, _, _ = compute_stop_target_rr(p_pct, PickProfile.SWING)
    s_frac, t_frac, _, _ = compute_stop_target_rr(p_frac, PickProfile.SWING)
    assert s_pct == s_frac
    assert t_pct == t_frac


def test_compute_stop_target_enforces_min_rr_via_stretch():
    """If the naive math yields RR < 1.5, target is stretched (not dropped)."""
    # Tiny ATR → tiny target → tiny RR. Function should stretch to MIN_RR.
    p = {"close": 100.0, "atr_pct": 0.5, "bb_upper": None, "bb_lower": None}
    stop, target, rr, err = compute_stop_target_rr(p, PickProfile.SWING)
    assert err is None
    assert rr >= MIN_RR - 1e-6


# -------------------- is_valid_long_pick --------------------


@pytest.mark.parametrize("entry,target,stop,expected_ok", [
    (100.0, 106.0, 97.0, True),          # healthy
    (100.0, 99.0, 97.0, False),          # target <= entry (NVL-style)
    (100.0, 106.0, 101.0, False),        # stop >= entry
    (100.0, 100.5, 97.0, False),         # upside < 2%
    (100.0, 101.0, 99.0, False),         # RR < 1.5
    (0.0, 10.0, 5.0, False),             # zero entry
    (None, 10.0, 5.0, False),            # missing entry
])
def test_is_valid_long_pick_gate(entry, target, stop, expected_ok):
    ok, reason = is_valid_long_pick(entry, target, stop)
    assert ok is expected_ok, f"expected {expected_ok}, got {ok} ({reason})"
    if not expected_ok:
        assert reason, "invalid pick must carry a reason"


def test_is_valid_long_pick_reasons_are_human_readable():
    """Reasons are shown in logs — ensure they're informative, not cryptic codes."""
    _, reason = is_valid_long_pick(100.0, 99.0, 97.0)
    assert "target" in reason.lower()
    assert "entry" in reason.lower()


# -------------------- invariants --------------------


def test_invariant_constants_are_sane():
    """Guard against accidental regressions that loosen the risk gate."""
    assert MIN_STOP_PCT >= 0.01, "stop cannot be looser than 1%"
    assert MIN_UPSIDE_PCT >= 0.01, "required upside floor cannot be below 1%"
    assert MIN_RR >= 1.0, "R:R floor must keep losers small"
