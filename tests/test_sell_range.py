"""The sell advice: a review schedule per position (the rule) and a price range
(a reference).

2026-09-29 (Tom: *"cập nhật những con tôi đang hold và đưa đề xuất dựa vào giá
mua, có nên bán hay không"*): every position has its own clock from its buy date
-- reviewed at sessions 20, 40, 60 ...; sold at a review where it ranks outside
the top 16, kept otherwise. docs/reviews/WORKFLOW_STUDY_2026-09-29.md measured
the alternatives Tom's question suggests (take profit / cut loss against the
entry price, a hard cap at 40 sessions, a daily check) and none beat it. So the
load-bearing test here is that the ENTRY PRICE never changes the verdict.
"""
from __future__ import annotations

from datetime import date

import pytest

from daily_watch import positions, sell_range
from daily_watch.sell_range import HOLD_MAX_SESSIONS, HOLD_MIN_SESSIONS, schedule, verdict
from services.buy_layer import KEEP_TOP, REVIEW_SESSIONS
from utils.clock import next_trading_day, previous_trading_day, today

ATR_PCT = 2.0            # percent units, as TickerRow carries it


def _bought(held: int) -> str:
    """A buy date `held` sessions before today."""
    d = today()
    for _ in range(held):
        d = previous_trading_day(d)
    return d.isoformat()


def _path(closes):
    d = date(2026, 8, 3)
    out = []
    for c in closes:
        out.append({"date": d.isoformat(), "close": c})
        d = next_trading_day(d, 1)
    return out


# ----------------------------------------------------------------- schedule

def test_the_first_two_reviews_are_4_and_8_weeks():
    assert (HOLD_MIN_SESSIONS, HOLD_MAX_SESSIONS) == (20, 40) and REVIEW_SESSIONS == 20
    s = schedule(_bought(5))
    d0 = date.fromisoformat(_bought(5))
    assert s["sell_from"] == next_trading_day(d0, 20).isoformat()
    assert s["sell_by"] == next_trading_day(d0, 40).isoformat()


@pytest.mark.parametrize("held,decide,phase", [
    (0, False, "trước kỳ xem lại đầu"), (18, False, "trước kỳ xem lại đầu"),
    (19, True, "quyết định hôm nay"), (20, False, "giữa hai kỳ"),
    (39, True, "quyết định hôm nay"), (59, True, "quyết định hôm nay"), (61, False, "giữa hai kỳ"),
])
def test_the_decision_falls_on_the_close_before_each_review(held, decide, phase):
    """Bought at the open of session e, ranked at the close of e+19, sold at the
    open of e+20 -- exactly what exits.py simulated."""
    s = schedule(_bought(held))
    assert s["sessions_held"] == held
    assert s["decide_today"] is decide and s["phase"] == phase
    d0 = date.fromisoformat(_bought(held))
    k = max(1, -(-(held + 1) // REVIEW_SESSIONS))
    assert s["next_review"] == next_trading_day(d0, k * REVIEW_SESSIONS).isoformat()


def test_the_last_decision_is_remembered_between_reviews():
    s = schedule(_bought(25))
    d0 = date.fromisoformat(_bought(25))
    assert s["last_decision"] == next_trading_day(d0, 19).isoformat()
    assert schedule(_bought(10))["last_decision"] is None
    assert schedule(_bought(19))["last_decision"] is None, "today's decision is not a past one"


def test_without_a_buy_date_there_is_no_schedule():
    s = schedule(None)
    assert s["sessions_held"] is None and s["next_review"] is None
    assert schedule("not a date")["sessions_held"] is None, "a hand-edited date must not raise"


# ------------------------------------------------------------------ verdict

def test_a_name_that_cannot_be_ranked_gets_no_advice():
    v = verdict(schedule(_bought(19)), None)
    assert v["verdict"] == "CHƯA XẾP ĐƯỢC"


def test_at_a_review_out_of_the_top_16_is_a_sale_and_in_it_is_a_hold():
    s = schedule(_bought(19))
    sell = verdict(s, KEEP_TOP + 1, 52)
    keep = verdict(s, KEEP_TOP, 52)
    assert sell["verdict"] == "BÁN" and s["next_review"] in sell["when"]
    assert keep["verdict"] == "GIỮ"


def test_before_the_first_review_even_a_weak_name_is_held():
    """The rule reviews at session 20; a daily check measured worse (30.6% vs
    33.0%/yr) and trades 1.7x as often."""
    v = verdict(schedule(_bought(5)), 40, 52)
    assert v["verdict"] == "GIỮ" and "Chưa tới kỳ xem lại" in v["why"]


def test_a_missed_sale_does_not_vanish_the_day_after_the_review():
    s = schedule(_bought(22))
    assert verdict(s, 30, 52, rank_at_last_decision=25)["verdict"] == "BÁN"
    # back inside the top 16 since the review: nothing to sell any more
    assert verdict(s, 12, 52, rank_at_last_decision=25)["verdict"] == "GIỮ"
    # kept at the review: out of the top now, but the next review decides
    assert verdict(s, 30, 52, rank_at_last_decision=10)["verdict"] == "GIỮ"
    # no archive for that day: no memory, so the strict rule (hold)
    assert verdict(s, 30, 52, rank_at_last_decision=None)["verdict"] == "GIỮ"


def test_without_a_buy_date_the_rank_today_decides():
    s = schedule(None)
    assert verdict(s, KEEP_TOP + 5, 52)["verdict"] == "BÁN"
    assert verdict(s, 3, 52)["verdict"] == "GIỮ"


def test_a_holding_outside_the_basket_says_its_rank_is_equivalent():
    v = verdict(schedule(None), 20, 52, equivalent=True)
    assert "tương đương" in v["why"]


@pytest.mark.parametrize("entry", [5.0, 10.0, 20.0])
def test_the_entry_price_never_changes_the_verdict(entry):
    """Tom asked for advice "dựa vào giá mua". Measured: take profit at +20% /
    +30% cost 8 / 5 points a year, cut loss at -10% was unstable, -15% nothing.
    So a 50% loss and a 100% gain on the same rank get the same verdict -- the
    book prints the P&L, it does not act on it."""
    from daily_watch.positions import track
    p = {"entry_price": entry, "opened_at": _bought(19)}
    sr = sell_range.advise(p, track(p, [], 10.0)["path"], ATR_PCT, 10.0)
    assert verdict(sr, 20, 52)["verdict"] == "BÁN"
    assert verdict(sr, 10, 52)["verdict"] == "GIỮ"


# ---------------------------------------------------------- reference range

def test_the_range_is_a_property_of_the_stock_not_of_the_trade():
    closes = [100.0, 104.0, 110.0, 107.0]
    dated = sell_range.advise({"entry_price": 100.0, "opened_at": "2026-08-03"},
                              _path(closes), ATR_PCT, closes[-1])
    undated = sell_range.advise({"entry_price": 100.0}, _path(closes), ATR_PCT, closes[-1])
    assert dated["band_lo"] == undated["band_lo"] == pytest.approx(110.0 * 0.98)
    assert dated["peak_basis"] == "since_entry" and undated["peak_basis"] == "recent_window"
    assert "ngày mua" in undated["note"]


def test_the_peak_leaves_out_the_latest_close():
    """Otherwise band_hi is unreachable: the peak is always >= today's close."""
    closes = [100.0, 101.0, 120.0]
    out = sell_range.advise({"entry_price": 100.0}, _path(closes), ATR_PCT, 120.0)
    assert out["peak"] == 101.0 and out["band_status"] == "trên vùng bán"


# ------------------------------------------------------------------- alerts

def test_alerts_are_the_sales_and_the_unrankable():
    book = {"positions": [
        {"symbol": "AAA", "verdict": {"verdict": "GIỮ"}},
        {"symbol": "BBB", "verdict": {"verdict": "CHƯA XẾP ĐƯỢC"}},
        {"symbol": "CCC", "verdict": {"verdict": "BÁN"}},
    ]}
    assert [a["symbol"] for a in positions.alerts(book)] == ["CCC", "BBB"]


def test_a_book_without_verdicts_raises_no_alert():
    """The old phases ("quá hạn", "trong cửa sổ bán", "nhả quá sâu") are gone:
    a hard sale at session 40 cost ~6.5 points a year under the momentum rule."""
    book = {"positions": [{"symbol": "AAA", "sell_range": {"phase": "quá hạn"}}]}
    assert positions.alerts(book) == []


def test_a_name_kept_at_a_review_is_next_looked_at_one_review_later():
    s = schedule(_bought(19))
    v = verdict(s, 3, 52)
    assert v["verdict"] == "GIỮ" and s["following_review"] in v["why"]
    assert s["following_review"] > s["next_review"]
