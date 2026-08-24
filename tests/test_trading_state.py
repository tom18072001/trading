"""services/trading_state.py — the operator store behind the kill-switch,
the position book and the watchlist (review backlog step 4).

The guards that matter: a corrupt file must not take the API down, the env
override must not be clearable from a browser, marking the same pick twice
must not duplicate it, and the publish job must actually honour the flag.
"""
import json

import pandas as pd
import pytest

from services import trading_state as ts


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Point the store at a temp file so tests never touch data/."""
    monkeypatch.setattr(ts, "STATE_PATH", tmp_path / "trading_state.json")
    monkeypatch.setattr(ts, "TRADING_HALT", False)
    yield


def test_missing_file_reads_as_defaults():
    s = ts.get_state()
    assert s["halt"] is False
    assert s["positions"] == []
    assert s["watchlist"] == []
    assert not ts.STATE_PATH.exists()          # a read must not create the file


def test_corrupt_file_degrades_instead_of_raising():
    ts.STATE_PATH.write_text("{not json", encoding="utf-8")
    assert ts.get_state()["halt"] is False
    assert ts.is_halted() is False


def test_file_holding_a_list_is_rejected():
    ts.STATE_PATH.write_text("[1, 2, 3]", encoding="utf-8")
    assert ts.get_state()["positions"] == []


def test_halt_round_trips_to_disk():
    ts.set_halt(True, "chờ số liệu KBS")
    assert ts.is_halted() is True

    on_disk = json.loads(ts.STATE_PATH.read_text(encoding="utf-8"))
    assert on_disk["halt"] is True
    assert on_disk["halt_reason"] == "chờ số liệu KBS"
    assert on_disk["halt_set_at"]

    ts.set_halt(False)
    assert ts.is_halted() is False
    assert ts.get_state()["halt_reason"] == ""


def test_env_var_overrides_a_cleared_runtime_flag(monkeypatch):
    """TRADING_HALT=1 must not be clearable from the UI."""
    monkeypatch.setattr(ts, "TRADING_HALT", True)
    ts.set_halt(False)
    assert ts.is_halted() is True
    assert ts.get_state()["halt_effective"] is True
    assert ts.get_state()["halt_env"] is True


def test_marking_the_same_pick_twice_updates_not_duplicates():
    ts.add_position("HPG", "STEEL", "BUY", entry_price=26.5)
    ts.add_position("HPG", "STEEL", "BUY", entry_price=27.0)
    s = ts.get_state()
    assert len(s["positions"]) == 1
    assert s["positions"][0]["entry_price"] == 27.0

    # A short on the same symbol is a different row.
    ts.add_position("HPG", "STEEL", "SELL")
    assert len(ts.get_state()["positions"]) == 2

    ts.remove_position("HPG", "BUY")
    remaining = ts.get_state()["positions"]
    assert [p["side"] for p in remaining] == ["SELL"]


def test_entering_a_watched_symbol_drops_it_from_the_watchlist():
    ts.toggle_watch("ssi")
    assert ts.get_state()["watchlist"] == ["SSI"]     # normalised upper-case
    ts.add_position("SSI", "BROK")
    s = ts.get_state()
    assert s["watchlist"] == []
    assert ts.held_symbols() == {"SSI"}
    assert ts.held_sectors() == {"BROK"}


def test_toggle_watch_is_a_toggle():
    ts.toggle_watch("VND")
    ts.toggle_watch("VND")
    assert ts.get_state()["watchlist"] == []


@pytest.mark.parametrize("bad", ["", "   "])
def test_blank_symbol_is_rejected(bad):
    with pytest.raises(ValueError):
        ts.add_position(bad)
    with pytest.raises(ValueError):
        ts.toggle_watch(bad)


def test_bad_side_is_rejected():
    with pytest.raises(ValueError):
        ts.add_position("HPG", "STEEL", "LONG")


def test_capital_cannot_go_to_zero():
    assert ts.set_capital(0)["capital_mn"] == 1.0
    assert ts.set_capital(250)["capital_mn"] == 250.0


def test_runtime_halt_stops_the_publish_job(seeded_session, monkeypatch):
    """The point of the whole feature: a flag set from the browser must reach
    SectorSignalService.publish(), which reads it through trading_state."""
    import services.sector_signal_service as sss
    from tests.test_review_20260822 import _seed_daily

    _seed_daily(seeded_session, "BANK", ["2026-02-27", "2026-02-28", "2026-03-02"])
    monkeypatch.setattr(sss, "TRADING_HALT", False)     # env var OFF
    ts.set_halt(True, "kill-switch từ giao diện")       # runtime flag ON

    ranked = pd.DataFrame([{"sector_code": "BANK", "score": 1.0, "rank": 1}])
    monkeypatch.setattr(sss.RotationModelService, "predict_today",
                        lambda self: ranked.copy())

    out = sss.SectorSignalService(seeded_session).publish()
    assert set(out["action"]) == {"HOLD"}
