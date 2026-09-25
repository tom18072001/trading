"""Tests for services.picks_scoring — the shared scoring + validity module
consumed by generate_report.py, PicksUniverseService, and insight.py.

These tests anchor the invariants that the NVL-style "target below close"
bug must never return. Any change to the scoring/stop/target rules must
keep these green.
"""
from __future__ import annotations

import pytest

from services.picks_scoring import (
    MIN_BUY_SCORE,
    UNTRENDED_FLOOR,
    WIDE_ATR_PCT,
    W_WIDE_ATR_PEN,
    MIN_RR,
    MIN_STOP_PCT,
    MIN_UPSIDE_PCT,
    PickProfile,
    compute_stop_target_rr,
    is_valid_long_pick,
    score_ticker,
)


# -------------------- score_ticker --------------------


def test_an_empty_row_is_floored_not_crashed_and_not_neutral():
    """No inputs at all must not read as an average candidate.

    The rule this replaced returned 0 for `{}` -- the same number a genuinely
    middling stock got -- so a name with no data could outrank a real one that
    happened to score slightly negative. With no SMA200 there is no confirmed
    uptrend, so the gate floors it.
    """
    assert score_ticker({}) == UNTRENDED_FLOOR


def test_the_gate_floors_a_downtrend_however_oversold_it_is():
    """A falling knife is the failure mode un-gated mean reversion has.

    RSI(2) of 2 is as oversold as the oscillator goes, and it still must not
    outrank a mildly oversold name in a confirmed uptrend.
    """
    knife = {"close": 10.0, "rsi_2": 2.0, "ret_1d": -6.0, "atr_pct": 2.0,
             "price_to_sma_50": -0.08, "price_to_sma_200": -0.20}
    healthy = {"close": 10.0, "rsi_2": 40.0, "ret_1d": -0.5, "atr_pct": 2.0,
               "price_to_sma_50": 0.03, "price_to_sma_200": 0.10}
    assert score_ticker(knife) == UNTRENDED_FLOOR
    assert score_ticker(healthy) > score_ticker(knife)


def test_a_gated_name_can_never_sink_to_the_floor():
    """The floor must sit clear of the worst reachable gated score.

    -1 const, -5 oversold, -2 pullback, -1.5 ATR = -9.5, so a floor of -9 would
    have let the worst trending name rank BELOW an untrended one -- the exact
    inversion the gate exists to prevent.
    """
    worst = {"close": 10.0, "rsi_2": 100.0, "ret_1d": 99.0, "atr_pct": 9.0,
             "price_to_sma_50": -0.01, "price_to_sma_200": 0.01}
    assert score_ticker(worst) > UNTRENDED_FLOOR


def test_oversold_beats_extended_which_is_the_whole_point_of_the_rewrite():
    """The direction the old rule had backwards.

    The old score paid +2 for RSI(14) between 50 and 70 and +2 more for a
    volume surge, so it ranked the extended name top. Measured over 1,168
    sessions that ranking was worse than random (CLAUDE.md 26.2).
    """
    pulled_back = {"close": 10.0, "rsi_2": 8.0, "ret_1d": -2.0, "atr_pct": 2.0,
                   "price_to_sma_50": 0.02, "price_to_sma_200": 0.08}
    extended = {"close": 10.0, "rsi_2": 95.0, "ret_1d": 3.0, "atr_pct": 2.0,
                "price_to_sma_50": 0.02, "price_to_sma_200": 0.08}
    assert score_ticker(pulled_back) > score_ticker(extended)


def test_the_pullback_term_is_measured_in_the_stock_own_atr():
    """A 2% drop is a big move for a bank and a quiet day for a broker.

    Both rows fall 2% with identical oscillator readings; only ATR differs.
    The quiet name must score higher, or the term is just a return and the
    cross-section is back to comparing incomparable scales.
    """
    quiet = {"close": 10.0, "rsi_2": 20.0, "ret_1d": -2.0, "atr_pct": 1.0,
             "price_to_sma_50": 0.02, "price_to_sma_200": 0.08}
    wild = {"close": 10.0, "rsi_2": 20.0, "ret_1d": -2.0, "atr_pct": 3.0,
            "price_to_sma_50": 0.02, "price_to_sma_200": 0.08}
    assert score_ticker(quiet) > score_ticker(wild)


def test_the_pullback_term_is_clipped_so_one_crash_cannot_dominate():
    """Without the clip, a -20% day outscores every other term combined."""
    crash = {"close": 10.0, "rsi_2": 50.0, "ret_1d": -20.0, "atr_pct": 2.0,
             "price_to_sma_50": 0.02, "price_to_sma_200": 0.08}
    dip = {"close": 10.0, "rsi_2": 50.0, "ret_1d": -4.0, "atr_pct": 2.0,
           "price_to_sma_50": 0.02, "price_to_sma_200": 0.08}
    assert score_ticker(crash) == score_ticker(dip)   # both clipped at 2 ATRs


def test_a_wide_atr_name_is_penalised():
    """The term that carries 2026 -- see the docstring in picks_scoring."""
    base = {"close": 10.0, "rsi_2": 30.0, "ret_1d": 0.0, "atr_pct": 2.0,
            "price_to_sma_50": 0.02, "price_to_sma_200": 0.08}
    wild = dict(base, atr_pct=WIDE_ATR_PCT + 0.1)
    assert score_ticker(wild) == pytest.approx(score_ticker(base) - W_WIDE_ATR_PEN, abs=0.01)


def test_missing_atr_does_not_silently_zero_the_pullback_term():
    """No ATR means the pullback cannot be expressed in ATRs, so it is dropped
    rather than divided by zero -- and dropping it must not raise."""
    row = {"close": 10.0, "rsi_2": 30.0, "ret_1d": -2.0, "atr_pct": None,
           "price_to_sma_50": 0.02, "price_to_sma_200": 0.08}
    assert isinstance(score_ticker(row), float)


def test_min_buy_score_admits_a_normal_shortlist_name():
    """MIN_BUY_SCORE is a measured percentile, not a round number someone liked.
    A mildly oversold name in an uptrend has to clear it or the daily email is
    empty on ordinary days."""
    ordinary = {"close": 10.0, "rsi_2": 25.0, "ret_1d": -1.0, "atr_pct": 2.0,
                "price_to_sma_50": 0.02, "price_to_sma_200": 0.08}
    assert score_ticker(ordinary) >= MIN_BUY_SCORE


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


def test_swing_is_the_only_profile_and_its_geometry_is_unchanged():
    """TPLUS (1.0x stop / 2.0x target, 3-5 sessions) was removed with the T+
    mode on 2026-09-25. SWING must still be 1.8x ATR below and 2.5x ATR above:
    `is_valid_long_pick` screens on it, so a silent change would change which
    names reach the shortlist."""
    assert [m.name for m in PickProfile] == ["SWING"]
    p = {"close": 100.0, "atr_pct": 3.0, "bb_upper": None, "bb_lower": None}
    stop, target, rr, _ = compute_stop_target_rr(p, PickProfile.SWING)
    assert stop == pytest.approx(100.0 * (1 - 1.8 * 0.03))            # 94.6
    # 2.5x ATR gives 107.5, then MIN_RR 1.5 stretches it to 100 + 1.5 * 5.4
    assert target == pytest.approx(108.1) and rr == pytest.approx(1.5)


def test_the_horizon_note_names_4_and_8_weeks_and_no_t_plus():
    """Every BUY card prints this sentence; 26.3 found the card had never
    stated a horizon and was closed on a three-day clock because of it."""
    from config import HOLD_SESSIONS
    from services.picks_scoring import horizon_note
    txt = horizon_note()
    assert f"{HOLD_SESSIONS[0]}-{HOLD_SESSIONS[1]} phiên" in txt
    assert "T+" not in txt


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
