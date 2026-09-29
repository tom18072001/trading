"""Tom reports his buys and sells; the book keeps them straight (2026-09-29).

Tom: *"tôi sẽ báo bạn tôi mua con nào giá thế nào · khi tôi bán tôi sẽ báo bạn"*.
Two gaps in the book this closes:

  * a second buy of a name already held OVERWROTE the first (`add_position`
    is idempotent -- right for the Daily Insight button, wrong for a trader
    adding to a position): now quantities sum at the weighted average cost;
  * a sale was all-or-nothing: now `qty` sells part, at the same average cost,
    without restarting the position's review clock.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from config import BACKTEST_FEE_BPS, BACKTEST_SELL_TAX_BPS
from services import trading_state


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    p = tmp_path / "trading_state.json"
    monkeypatch.setattr(trading_state, "STATE_PATH", p)
    yield p


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _pos(sym="VIC"):
    return next(p for p in trading_state.get_state()["positions"] if p["symbol"] == sym)


# ------------------------------------------------------------------- buying

def test_a_first_buy_opens_a_dated_position():
    trading_state.record_buy("vic", 45.2, 1000, bought_at="2026-09-15")
    p = _pos()
    assert (p["entry_price"], p["qty"], p["opened_at"]) == (45.2, 1000, "2026-09-15")
    assert p["lots"] == [{"price": 45.2, "qty": 1000, "date": "2026-09-15"}]


def test_buying_more_averages_the_cost_and_keeps_the_first_date():
    trading_state.record_buy("VIC", 40.0, 1000, bought_at="2026-09-15")
    trading_state.record_buy("VIC", 50.0, 500, bought_at="2026-09-29")
    p = _pos()
    assert p["qty"] == 1500
    assert p["entry_price"] == pytest.approx((40.0 * 1000 + 50.0 * 500) / 1500)
    assert p["opened_at"] == "2026-09-15", "the review clock is the first buy's"
    assert len(p["lots"]) == 2


def test_the_old_mark_button_still_overwrites_on_purpose():
    """Negative control: `add_position` is the idempotent pick marker. If it
    started summing, a double click on Daily Insight would double a position."""
    trading_state.add_position("VIC", entry_price=40.0, qty=1000)
    trading_state.add_position("VIC", entry_price=50.0, qty=500)
    assert _pos()["qty"] == 500


def test_adding_to_a_row_with_no_price_is_refused_not_guessed():
    trading_state.add_position("VIC", entry_price=None, qty=1000)
    with pytest.raises(ValueError, match="without a price or qty"):
        trading_state.record_buy("VIC", 50.0, 500)


def test_adding_to_an_undated_row_keeps_it_undated():
    """Taking the new lot's date would invent one for the earlier shares."""
    trading_state.add_position("VIC", entry_price=40.0, qty=1000, opened_at="")
    trading_state.record_buy("VIC", 50.0, 500, bought_at="2026-09-29")
    assert _pos()["opened_at"] is None


@pytest.mark.parametrize("price,qty", [(0, 100), (-1, 100), (10, 0)])
def test_a_buy_needs_a_positive_price_and_qty(price, qty):
    with pytest.raises(ValueError):
        trading_state.record_buy("VIC", price, qty)


# ------------------------------------------------------------------ selling

def test_a_partial_sale_leaves_the_rest_at_the_same_cost_and_date():
    trading_state.record_buy("VIC", 40.0, 1000, bought_at="2026-09-15")
    s = trading_state.close_position("VIC", exit_price=44.0, qty=400, closed_at="2026-10-20")
    p = _pos()
    assert p["qty"] == 600 and p["entry_price"] == 40.0 and p["opened_at"] == "2026-09-15"
    sold = s["closed"][-1]
    assert sold["partial"] is True and sold["qty"] == 400
    fees = ((40.0 + 44.0) * 400 * BACKTEST_FEE_BPS / 10_000
            + 44.0 * 400 * BACKTEST_SELL_TAX_BPS / 10_000)
    assert sold["pnl_vnd"] == pytest.approx((44.0 - 40.0) * 400 - fees)


def test_selling_the_rest_closes_the_position():
    trading_state.record_buy("VIC", 40.0, 1000)
    trading_state.close_position("VIC", exit_price=44.0, qty=400)
    s = trading_state.close_position("VIC", exit_price=45.0)
    assert s["positions"] == [] and [c["qty"] for c in s["closed"]] == [400, 600]


def test_selling_exactly_everything_is_a_full_close():
    trading_state.record_buy("VIC", 40.0, 1000)
    s = trading_state.close_position("VIC", exit_price=44.0, qty=1000)
    assert s["positions"] == [] and not s["closed"][-1].get("partial")


def test_selling_more_than_held_is_refused():
    trading_state.record_buy("VIC", 40.0, 1000)
    with pytest.raises(ValueError, match="only 1000 held"):
        trading_state.close_position("VIC", exit_price=44.0, qty=1500)
    assert _pos()["qty"] == 1000, "a refused sale changes nothing"


# ---------------------------------------------------------------------- API

def test_the_buy_route_adds_and_the_close_route_sells_part(client):
    r = client.post("/api/state/positions/VIC/buy", json={"price": 40.0, "qty": 1000})
    assert r.status_code == 200
    r = client.post("/api/state/positions/VIC/buy", json={"price": 50.0, "qty": 1000})
    assert _pos()["entry_price"] == pytest.approx(45.0)
    r = client.post("/api/state/positions/VIC/close", json={"exit_price": 46.0, "qty": 500})
    assert r.status_code == 200 and _pos()["qty"] == 1500
    r = client.post("/api/state/positions/VIC/close", json={"exit_price": 46.0, "qty": 9999})
    assert r.status_code == 422
    r = client.post("/api/state/positions/NOPE/close", json={"exit_price": 46.0})
    assert r.status_code == 404


# ---------------------------------------------------------------------- CLI

@pytest.mark.parametrize("raw,want", [("45.2", 45.2), ("45200", 45.2), ("45,200", 45.2),
                                      ("241.3", 241.3)])
def test_prices_are_read_in_thousand_dong(raw, want):
    from daily_watch.book import price_k
    v, how = price_k(raw)
    assert v == pytest.approx(want) and "nghìn" in how


def test_the_cli_records_and_then_prints_the_verdicts(monkeypatch, capsys):
    from daily_watch import book, service
    shown = {}
    monkeypatch.setattr(service, "build", lambda top_n=8: shown.setdefault("p", {
        "data_as_of": "2026-09-29", "shortlist_meta": {"ranked_count": 52},
        "book": {"positions": [{"symbol": "VIC", "qty": 1000, "entry_price": 45.2,
                                "last": 46.0, "pnl_pct": 1.8, "rank": 3,
                                "verdict": {"verdict": "GIỮ", "why": "hạng 3/52, trong top 16"},
                                "sell_range": {"next_review": "2026-10-27"}}]}}))
    assert book.main(["buy", "VIC", "45200", "1000", "--date", "2026-09-29"]) == 0
    out = capsys.readouterr().out
    assert "Đã ghi MUA VIC 1,000 cp giá 45,200đ → 45.20 nghìn" in out
    assert "hạng 3/52 → GIỮ" in out and "xem lại 2026-10-27" in out
    assert _pos()["opened_at"] == "2026-09-29"
    assert book.main(["sell", "VIC", "47", "400"]) == 0
    assert "Còn giữ 600 cp" in capsys.readouterr().out
    assert book.main(["sell", "VIC", "47", "9999"]) == 2, "a refused sale is an exit code"
