"""Editing an entry price, and marking the book to market.

Tom's ask: "cho toi sua gia vao lenh va man hinh kiem soat cac lenh da vao".
The reason it needs its own verb rather than re-using add_position: the price
stamped when you press "Da vao lenh" on Daily Insight is the previous close,
which is almost never your fill.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from services import trading_state


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Never touch the operator's real data/trading_state.json."""
    p = tmp_path / "trading_state.json"
    monkeypatch.setattr(trading_state, "STATE_PATH", p)
    yield p


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _add(symbol="HPG", **kw):
    return trading_state.add_position(symbol, kw.pop("sector_code", "STEEL"), **kw)


# ----- the verb itself -----------------------------------------------------

def test_edit_changes_only_the_field_passed():
    _add("HPG", entry_price=26.0, qty=1000, note="from insight")
    trading_state.update_position("HPG", entry_price=27.35)

    p = next(x for x in trading_state.get_state()["positions"] if x["symbol"] == "HPG")
    assert p["entry_price"] == 27.35
    assert p["qty"] == 1000, "an omitted field must not be wiped"
    assert p["note"] == "from insight"


def test_edit_does_not_restamp_the_open_date():
    """The whole reason this is not add_position(): correcting a price you typed
    from memory must not claim you opened the position today."""
    _add("HPG", entry_price=26.0)
    before = next(x for x in trading_state.get_state()["positions"])["opened_at"]

    trading_state.update_position("HPG", entry_price=27.0)
    after = next(x for x in trading_state.get_state()["positions"])["opened_at"]
    assert before == after


def test_edit_does_not_touch_the_watchlist():
    trading_state.toggle_watch("SSI")
    _add("HPG", entry_price=26.0)
    trading_state.update_position("HPG", qty=500)
    assert "SSI" in trading_state.get_state()["watchlist"]


def test_negative_clears_a_field_and_none_leaves_it():
    _add("HPG", entry_price=26.0, qty=1000)
    trading_state.update_position("HPG", entry_price=-1)

    p = next(x for x in trading_state.get_state()["positions"])
    assert p["entry_price"] is None, "-1 is the explicit clear"
    assert p["qty"] == 1000, "None must mean 'leave alone', not 'clear'"


def test_editing_a_missing_position_raises_rather_than_inserting():
    with pytest.raises(ValueError):
        trading_state.update_position("NOPE", entry_price=10.0)
    assert trading_state.get_state()["positions"] == []


def test_side_selects_the_row():
    _add("HPG", side="BUY", entry_price=26.0)
    _add("HPG", side="SELL", entry_price=30.0)
    trading_state.update_position("HPG", "SELL", entry_price=31.0)

    book = {(p["symbol"], p["side"]): p for p in trading_state.get_state()["positions"]}
    assert book[("HPG", "BUY")]["entry_price"] == 26.0
    assert book[("HPG", "SELL")]["entry_price"] == 31.0


def test_edit_survives_a_reload_from_disk(isolated_state):
    _add("HPG", entry_price=26.0)
    trading_state.update_position("HPG", entry_price=27.35)
    on_disk = json.loads(isolated_state.read_text(encoding="utf-8"))
    assert on_disk["positions"][0]["entry_price"] == 27.35


# ----- the endpoints -------------------------------------------------------

def test_patch_returns_the_whole_state(client):
    _add("HPG", entry_price=26.0)
    r = client.patch("/api/state/positions/HPG", json={"entry_price": 27.35})
    assert r.status_code == 200
    body = r.json()
    assert "positions" in body and "halt" in body, "callers replace, never merge"
    assert body["positions"][0]["entry_price"] == 27.35


def test_patch_on_a_missing_symbol_is_404_not_500(client):
    r = client.patch("/api/state/positions/NOPE", json={"entry_price": 1.0})
    assert r.status_code == 404


def test_pnl_route_is_not_shadowed_by_the_symbol_route(client):
    """/positions/pnl and /positions/{symbol} share a prefix. If the literal
    ever loses, this returns a position named "pnl"."""
    r = client.get("/api/state/positions/pnl")
    assert r.status_code == 200
    assert "positions" in r.json() and "priced" in r.json()


def test_pnl_reports_how_much_of_the_book_it_could_price(client, monkeypatch):
    """A P&L over 1 of 3 rows must not be readable as the book's P&L."""
    _add("HPG", entry_price=26.0, qty=1000)
    _add("SSI", entry_price=30.0, qty=1000)
    _add("VCB", entry_price=90.0)                     # no qty

    class _T:
        def __init__(self, c): self.close = c

    class _Snap:
        as_of = "2026-08-24"
        tickers = {"HPG": _T(28.0)}                   # only one price known

    monkeypatch.setattr(
        "services.picks_universe_service.PicksUniverseService.peek",
        lambda self: _Snap(), raising=False,
    )

    body = client.get("/api/state/positions/pnl").json()
    assert body["count"] == 3
    assert body["priced"] == 1
    row = next(r for r in body["positions"] if r["symbol"] == "HPG")
    assert row["pnl_pct"] == pytest.approx((28.0 / 26.0 - 1) * 100)
    assert row["pnl_vnd"] == pytest.approx(2000.0)


def test_pnl_on_a_cold_cache_returns_the_book_unmarked(client, monkeypatch):
    """A cold cache must not block the request behind the KBS throttle."""
    _add("HPG", entry_price=26.0, qty=1000)
    monkeypatch.setattr(
        "services.picks_universe_service.PicksUniverseService.peek",
        lambda self: None, raising=False,
    )
    body = client.get("/api/state/positions/pnl").json()
    assert body["priced"] == 0
    assert body["positions"][0]["last"] is None
    assert body["total_pnl_pct"] is None


def test_a_price_lookup_failure_never_breaks_the_book(client, monkeypatch):
    _add("HPG", entry_price=26.0, qty=1000)
    monkeypatch.setattr(
        "services.picks_universe_service.PicksUniverseService.peek",
        lambda self: (_ for _ in ()).throw(RuntimeError("boom")), raising=False,
    )
    r = client.get("/api/state/positions/pnl")
    assert r.status_code == 200
    assert r.json()["count"] == 1
