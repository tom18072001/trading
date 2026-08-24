"""Closing a position, and realised P&L.

The gap this fills: the book had one verb for removing a row, remove_position(),
so "I sold at 28" and "I mis-clicked" were the same operation. Both deleted the
row, which means the system could never answer the only question a book exists
to answer — did its own picks make money.

The load-bearing test here is
`test_a_close_is_not_a_delete`: closing must LEAVE evidence.
"""
from __future__ import annotations

import json

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


def _add(symbol="HPG", **kw):
    return trading_state.add_position(symbol, kw.pop("sector_code", "STEEL"), **kw)


# ----- the verb ------------------------------------------------------------

def test_a_close_is_not_a_delete():
    """remove_position() throws the row away; this must keep it."""
    _add("HPG", entry_price=26.0, qty=1000)
    s = trading_state.close_position("HPG", exit_price=28.0)

    assert s["positions"] == [], "the position must leave the open book"
    assert len(s["closed"]) == 1
    assert s["closed"][0]["symbol"] == "HPG"
    assert s["closed"][0]["exit_price"] == 28.0
    assert s["closed"][0]["entry_price"] == 26.0, "the entry must survive the close"


def test_realised_pnl_is_net_of_the_backtest_costs():
    """§18.2/10. A book quoting a gross number the backtest would call a loss is
    worse than no book, so the two must charge the same fees."""
    _add("HPG", entry_price=26.0, qty=1000)
    trading_state.close_position("HPG", exit_price=28.0)
    row = trading_state.get_state()["closed"][0]

    fees = ((26.0 + 28.0) * 1000 * BACKTEST_FEE_BPS / 10_000
            + 28.0 * 1000 * BACKTEST_SELL_TAX_BPS / 10_000)
    assert row["fees_vnd"] == pytest.approx(fees)
    assert row["pnl_vnd"] == pytest.approx((28.0 - 26.0) * 1000 - fees)
    assert row["pnl_vnd"] < (28.0 - 26.0) * 1000, "costs must reduce the gain"

    cost_pct = (2 * BACKTEST_FEE_BPS + BACKTEST_SELL_TAX_BPS) / 100
    assert row["pnl_pct"] == pytest.approx((28.0 / 26.0 - 1) * 100 - cost_pct)


def test_a_position_with_no_qty_still_gets_a_percent():
    """Cost in percent terms is size-independent, so an unsized position is not
    an unmeasurable one."""
    _add("VCB", entry_price=90.0)
    trading_state.close_position("VCB", exit_price=95.0)
    row = trading_state.get_state()["closed"][0]

    assert row["pnl_pct"] is not None
    assert row["pnl_vnd"] is None, "no qty means no VND figure to invent"


def test_costs_can_turn_a_small_win_into_a_loss():
    """The reason the costs are here at all: ~0.40% round trip routinely decides
    whether a scalp was a scalp."""
    _add("HPG", entry_price=100.0, qty=1000)
    trading_state.close_position("HPG", exit_price=100.2)   # +0.20% gross
    row = trading_state.get_state()["closed"][0]
    assert row["pnl_pct"] < 0
    assert row["pnl_vnd"] < 0


def test_a_sell_side_close_signs_the_other_way():
    _add("HPG", side="SELL", entry_price=30.0, qty=1000)
    trading_state.close_position("HPG", "SELL", exit_price=28.0)
    row = trading_state.get_state()["closed"][0]
    assert row["pnl_vnd"] > 0, "a short closed lower is a gain in the book's terms"


def test_side_selects_which_row_closes():
    _add("HPG", side="BUY", entry_price=26.0)
    _add("HPG", side="SELL", entry_price=30.0)
    s = trading_state.close_position("HPG", "SELL", exit_price=28.0)

    assert [p["side"] for p in s["positions"]] == ["BUY"]
    assert s["closed"][0]["side"] == "SELL"


def test_closing_a_missing_position_raises():
    with pytest.raises(ValueError, match="no open"):
        trading_state.close_position("NOPE", exit_price=10.0)
    assert trading_state.get_state()["closed"] == []


def test_a_non_positive_exit_price_is_refused():
    _add("HPG", entry_price=26.0)
    for bad in (0.0, -5.0):
        with pytest.raises(ValueError, match="exit_price"):
            trading_state.close_position("HPG", exit_price=bad)
    assert len(trading_state.get_state()["positions"]) == 1, "nothing partial happened"


def test_reopening_after_a_close_does_not_disturb_the_record():
    """Buying the same name again is a new trade, not an edit of the old one."""
    _add("HPG", entry_price=26.0, qty=1000)
    trading_state.close_position("HPG", exit_price=28.0)
    _add("HPG", entry_price=27.0, qty=500)

    s = trading_state.get_state()
    assert len(s["closed"]) == 1 and len(s["positions"]) == 1
    assert s["closed"][0]["entry_price"] == 26.0


def test_closed_trades_survive_a_reload_from_disk(isolated_state):
    _add("HPG", entry_price=26.0, qty=1000)
    trading_state.close_position("HPG", exit_price=28.0)
    on_disk = json.loads(isolated_state.read_text(encoding="utf-8"))
    assert on_disk["closed"][0]["exit_price"] == 28.0


def test_an_old_state_file_without_closed_still_loads(isolated_state):
    """Every state file written before 2026-08-24 lacks the key. _DEFAULT merge
    must supply it rather than KeyError on the first close."""
    isolated_state.write_text(json.dumps({"halt": False, "positions": []}),
                              encoding="utf-8")
    assert trading_state.get_state()["closed"] == []


# ----- the totals ----------------------------------------------------------

def test_realised_totals_say_how_many_trades_carried_a_number():
    """Same discipline as the unrealised endpoint: a total over 1 of 2 trades is
    not the book's total."""
    _add("HPG", entry_price=26.0, qty=1000)
    _add("VCB", entry_price=90.0)                    # no qty
    trading_state.close_position("HPG", exit_price=28.0)
    trading_state.close_position("VCB", exit_price=95.0)

    r = trading_state.realised_pnl()
    assert r["count"] == 2
    assert r["priced"] == 1, "only the sized trade has a VND figure"
    assert r["win_rate"] == 1.0, "win rate reads percent, so both trades count"
    assert r["avg_pnl_pct"] > 0


def test_an_empty_book_reports_none_not_zero():
    r = trading_state.realised_pnl()
    assert r == {"count": 0, "priced": 0, "total_pnl_vnd": None,
                 "total_fees_vnd": None, "avg_pnl_pct": None,
                 "win_rate": None, "trades": []}


def test_a_break_even_book_reports_zero_not_none():
    """`sum(...) or None` would erase an exactly-flat book. Rare, but the two
    states mean opposite things."""
    _add("HPG", entry_price=100.0, qty=1000)
    trading_state.close_position("HPG", exit_price=100.0)
    r = trading_state.realised_pnl()
    assert r["total_pnl_vnd"] is not None
    assert r["total_pnl_vnd"] < 0, "flat gross is a loss after costs"


# ----- the endpoints -------------------------------------------------------

def test_close_endpoint_returns_the_whole_state(client):
    _add("HPG", entry_price=26.0, qty=1000)
    r = client.post("/api/state/positions/HPG/close", json={"exit_price": 28.0})
    assert r.status_code == 200
    body = r.json()
    assert body["positions"] == [] and len(body["closed"]) == 1


def test_close_endpoint_separates_missing_from_invalid(client):
    """404 means "no such position"; 422 means "that is not a price". Collapsing
    them makes a typo look like a lost row."""
    assert client.post("/api/state/positions/NOPE/close",
                       json={"exit_price": 10.0}).status_code == 404
    _add("HPG", entry_price=26.0)
    assert client.post("/api/state/positions/HPG/close",
                       json={"exit_price": 0}).status_code == 422


def test_realised_route_is_not_shadowed_by_the_symbol_route(client):
    """/positions/realised shares a prefix with /positions/{symbol}, the same
    trap /positions/pnl documents. If the literal loses, POST .../close on a
    position named "realised" is what you get."""
    r = client.get("/api/state/positions/realised")
    assert r.status_code == 200
    assert "trades" in r.json() and "priced" in r.json()
