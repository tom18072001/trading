"""The sell advice: a 4-8 week window (the rule) and a price range (a reference).

`daily_watch/sell_range.advise()` had no test of its own until 2026-09-25, when
review 2026-09-24 §3.2 found `give_back` armed on a position with no buy date:
the peak was then the ~30-session market high, possibly set BEFORE the buy,
and the 2026-09-23 bulletin told Tom a wave he was not in "had ended".
"""
from __future__ import annotations

from datetime import date

import pytest

from daily_watch import positions, sell_range
from daily_watch.sell_range import ARM_ATR, GIVE_BACK_ATR, HOLD_MAX_SESSIONS, HOLD_MIN_SESSIONS
from utils.clock import next_trading_day, today

ATR_PCT = 2.0            # percent units, as TickerRow carries it
A = ATR_PCT / 100.0


def _path(closes):
    d = date(2026, 8, 3)
    out = []
    for c in closes:
        out.append({"date": d.isoformat(), "close": c})
        d = next_trading_day(d, 1)
    return out


def _gave_back_after_a_wave(entry=100.0):
    """A run from entry to a peak well past the arming level, then a slide to
    below the give-back line. The last close is excluded from the peak."""
    peak = entry * (1 + (ARM_ATR + 2) * A)
    last = peak * (1 - (GIVE_BACK_ATR + 0.5) * A)
    return [entry, entry * 1.02, peak, peak * 0.97, last], peak, last


def test_the_hold_window_is_4_and_8_weeks():
    assert (HOLD_MIN_SESSIONS, HOLD_MAX_SESSIONS) == (20, 40)


def test_give_back_arms_when_the_wave_happened_after_the_buy():
    closes, peak, last = _gave_back_after_a_wave()
    out = sell_range.advise({"entry_price": 100.0, "opened_at": "2026-08-03"},
                            _path(closes), ATR_PCT, last)
    assert out["peak_basis"] == "since_entry"
    assert out["peak"] == pytest.approx(peak)
    assert out["armed"] is True
    assert last <= out["give_back"]
    assert "Giá đã nhả quá" in out["note"]


def test_without_a_buy_date_give_back_never_arms():
    """Same prices, no buy date: the peak may predate the buy, so "the wave is
    over" is a claim about a wave the trader may not have been in."""
    closes, _peak, last = _gave_back_after_a_wave()
    out = sell_range.advise({"entry_price": 100.0}, _path(closes), ATR_PCT, last)
    assert out["peak_basis"] == "recent_window"
    assert out["armed"] is False
    assert "Giá đã nhả quá" not in out["note"]
    assert "không báo" in out["note"]
    # The range is a property of the stock, not of the trade: it still exists.
    assert out["band_lo"] is not None and out["band_hi"] is not None


def test_without_a_buy_date_the_book_raises_no_give_back_alert():
    closes, _peak, last = _gave_back_after_a_wave()
    sr = sell_range.advise({"entry_price": 100.0}, _path(closes), ATR_PCT, last)
    book = {"positions": [{"symbol": "XYZ", "last": last, "sell_range": sr}]}
    assert positions.alerts(book) == []


def test_a_small_rise_does_not_arm_even_with_a_buy_date():
    """Negative control for the test above: the date is not the only condition.
    A peak under entry + ARM_ATR x ATR is not a wave."""
    entry = 100.0
    closes = [entry, entry * (1 + 0.5 * ARM_ATR * A), entry * 0.9]
    out = sell_range.advise({"entry_price": entry, "opened_at": "2026-08-03"},
                            _path(closes), ATR_PCT, closes[-1])
    assert out["armed"] is False


@pytest.mark.parametrize("held,phase", [(5, "giữ"), (25, "trong cửa sổ bán"),
                                        (45, "quá hạn")])
def test_the_window_phase_and_its_advice(held, phase):
    """Session 20 opens the window; it is not a sell signal (review §3.1: the
    book keeps earning to ~40). The note must say so."""
    opened = today()
    for _ in range(held):
        opened = _prev_session(opened)
    out = sell_range.advise({"entry_price": 100.0, "opened_at": opened.isoformat()},
                            _path([100.0, 101.0]), ATR_PCT, 101.0)
    assert out["phase"] == phase
    if phase == "trong cửa sổ bán":
        assert f"~{HOLD_MAX_SESSIONS}" in out["note"] and "ATO" in out["note"]
    if phase == "quá hạn":
        assert "ATO" in out["note"]


def _prev_session(d: date) -> date:
    from utils.clock import previous_trading_day
    return previous_trading_day(d)
