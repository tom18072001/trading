"""Following a position after you have entered it.

The defect this closes: `compute_stop_target_rr` computed a stop and a target,
`PickEntry` carried them, the Daily Insight card rendered them — and the one
line that marked the position sent only `entry_price`. Both numbers were
destroyed at the click, so the book could not answer the only question worth
asking the day after a buy: is this trade still valid?

The load-bearing tests are `test_stop_and_target_survive_the_round_trip` (the
defect itself) and `test_hit_stop_is_ever_touched_not_just_today` (a stop that
was breached on Tuesday and recovered by Friday is still a stop that was
breached; a book that forgets that is telling you the trade is fine).
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.routers.state import SETTLEMENT_SESSIONS, _track
from services import trading_state
from utils.clock import next_trading_day, sessions_between


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    p = tmp_path / "trading_state.json"
    monkeypatch.setattr(trading_state, "STATE_PATH", p)
    yield p


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _bars(*pairs):
    """`daily_prices` as picks_universe_service writes it — the date key is
    "time", not "date". That rename is exactly the kind of thing that only
    shows up in a test."""
    return [{"time": d, "open": c, "close": c, "volume": 1} for d, c in pairs]


# ----- 1. the defect -------------------------------------------------------

def test_stop_and_target_survive_the_round_trip():
    """Mark a pick with the levels the card showed; read the book back."""
    trading_state.add_position("BVH", "INSUR", entry_price=65.9,
                               stop=62.0, target=71.8, thesis="flow + breadth")
    p = trading_state.get_state()["positions"][0]

    assert p["stop"] == 62.0
    assert p["target"] == 71.8
    assert p["thesis"] == "flow + breadth"


def test_an_old_position_without_stop_still_loads(isolated_state):
    """No migration, same as `closed` on 2026-08-24: _read() merges _DEFAULT,
    and a row predating this feature simply has no key."""
    isolated_state.write_text(json.dumps({
        "positions": [{"symbol": "HPG", "side": "BUY", "entry_price": 26.0,
                       "qty": 1000, "note": "", "opened_at": "2026-08-01"}],
    }), encoding="utf-8")

    p = trading_state.get_state()["positions"][0]
    assert p["symbol"] == "HPG"
    # Present and null, not absent: the TS `Position` type says `stop: number |
    # null`, and a row that omits the key entirely violates it.
    assert "stop" in p and p["stop"] is None
    assert p["thesis"] == ""
    assert _track(p, [], 27.0)["dist_to_stop_pct"] is None


def test_the_levels_are_editable_in_place():
    """A stop you cannot correct is a stop you will ignore. `None` leaves the
    field alone; a negative clears it — the convention update_position already
    uses for entry_price and qty."""
    trading_state.add_position("HPG", stop=24.0, target=30.0)

    trading_state.update_position("HPG", stop=25.0)
    p = trading_state.get_state()["positions"][0]
    assert (p["stop"], p["target"]) == (25.0, 30.0), "target must not be touched"

    trading_state.update_position("HPG", target=-1)
    assert trading_state.get_state()["positions"][0]["target"] is None


# ----- 2. the path ---------------------------------------------------------

def test_the_path_starts_at_entry_not_at_the_start_of_the_tail():
    """daily_prices carries 30 sessions; only the ones since you bought are
    yours."""
    p = {"symbol": "HPG", "opened_at": "2026-08-19", "stop": None, "target": None}
    out = _track(p, _bars(("2026-08-17", 25.0), ("2026-08-18", 25.5),
                          ("2026-08-19", 26.0), ("2026-08-20", 26.4)), 26.4)

    assert [b["date"] for b in out["path"]] == ["2026-08-19", "2026-08-20"]
    assert out["path"][0]["close"] == 26.0


def test_hit_stop_is_ever_touched_not_just_today():
    """Breached Tuesday, recovered Friday — still a breach."""
    p = {"symbol": "HPG", "opened_at": "2026-08-17", "stop": 24.0, "target": 30.0}
    out = _track(p, _bars(("2026-08-17", 26.0), ("2026-08-18", 23.5),
                          ("2026-08-19", 26.5)), 26.5)

    assert out["hit_stop"] is True, "today's close being fine does not undo it"
    assert out["hit_target"] is False


def test_a_breach_before_entry_is_not_your_breach():
    """The same low, one session before you bought, must not flag the row."""
    p = {"symbol": "HPG", "opened_at": "2026-08-18", "stop": 24.0, "target": None}
    out = _track(p, _bars(("2026-08-17", 23.5), ("2026-08-18", 26.0)), 26.0)

    assert out["hit_stop"] is False


def test_distance_to_the_levels_is_signed_from_the_last_price():
    p = {"symbol": "HPG", "opened_at": "2026-08-17", "stop": 24.0, "target": 30.0}
    out = _track(p, _bars(("2026-08-17", 26.0)), 27.0)

    assert out["dist_to_stop_pct"] == pytest.approx((27.0 / 24.0 - 1) * 100)
    assert out["dist_to_target_pct"] == pytest.approx((30.0 / 27.0 - 1) * 100)


def test_a_cold_cache_gives_a_path_free_row_not_an_exception():
    """`.peek()` returns None on a cold process (§22.6). The book must still
    render — with no path, not with a 500."""
    p = {"symbol": "HPG", "opened_at": "2026-08-17", "stop": 24.0, "target": 30.0}
    out = _track(p, [], None)

    assert out["path"] == []
    assert out["hit_stop"] is False
    assert out["dist_to_stop_pct"] is None


def test_a_hand_edited_opened_at_does_not_break_the_whole_book():
    """opened_at is a free-text PATCH field. Garbage in it must cost that row
    its dates, not the endpoint."""
    p = {"symbol": "HPG", "opened_at": "hôm qua", "stop": None, "target": None}
    out = _track(p, _bars(("2026-08-17", 26.0)), 26.0)

    assert out["sessions_held"] is None
    assert out["sellable_on"] is None


# ----- 3. sessions, not calendar days --------------------------------------

def test_sellable_on_skips_weekends():
    """T+2 counts SESSIONS. A Thursday buy settles Monday, not Saturday —
    which is the bug tPlusDays() shipped with (`setDate(+i)`)."""
    thu = date(2026, 8, 20)
    assert thu.strftime("%a") == "Thu"
    assert next_trading_day(thu, SETTLEMENT_SESSIONS) == date(2026, 8, 24)


def test_sellable_on_skips_holidays_too():
    """2026-04-30 and 05-01 are HOSE holidays; Wed 29th settles Tuesday 5th."""
    assert next_trading_day(date(2026, 4, 29), SETTLEMENT_SESSIONS) == date(2026, 5, 5)


def test_sessions_held_counts_trading_days_and_never_goes_negative():
    assert sessions_between(date(2026, 8, 17), date(2026, 8, 24)) == 5
    assert sessions_between(date(2026, 8, 24), date(2026, 8, 17)) == 0


# ----- 4. the endpoint -----------------------------------------------------

def test_pnl_still_works_when_stop_is_missing(client, monkeypatch):
    """The new fields must not disturb the P&L path that already shipped."""
    import services.picks_universe_service as pus
    from utils.clock import today_str

    # add_position() stamps opened_at = today, and _track() drops pre-entry
    # bars — so a fixture dated last week would legitimately produce an empty
    # path and prove nothing.
    d = today_str()

    class _Ticker:
        close = 27.0
        daily_prices = _bars((d, 26.5), (d, 27.0))

    class _Snap:
        as_of = d
        tickers = {"HPG": _Ticker()}

    monkeypatch.setattr(pus.PicksUniverseService, "peek", lambda self: _Snap())
    trading_state.add_position("HPG", "STEEL", entry_price=26.0, qty=1000)

    r = client.get("/api/state/positions/pnl")
    assert r.status_code == 200
    row = r.json()["positions"][0]

    assert row["pnl_pct"] == pytest.approx((27.0 / 26.0 - 1) * 100)
    assert row["stop"] is None and row["dist_to_stop_pct"] is None
    assert len(row["path"]) == 2
    assert row["sellable_on"] and row["sessions_held"] is not None
