"""Tests for PicksUniverseService — dynamic constituent universe +
freshness contract + caching.

These tests stub out the vnstock network layer so the suite is deterministic
and does not depend on an external data provider being up.
"""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pandas as pd
import pytest

from services.picks_universe_service import (
    FreshnessReport,
    PickEntry,
    PicksUniverseService,
    TickerRow,
    UniverseSnapshot,
    _classify_sector,
    _snapshot_from_json,
    _snapshot_to_json,
    _technical_bits,
    get_picks_universe,
)


# -------------------- dataclasses --------------------


def test_ticker_row_as_picks_dict_shape():
    """The adapter dict is consumed by generate_report.py — its keys must stay stable."""
    r = TickerRow(
        symbol="HPG", sector_code="STEEL", close=28.0, ret_5d=2.5, ret_20d=10.0,
        atr_pct=2.5, rsi_14=55, macd_hist=0.1, bb_upper=30.0, bb_lower=26.0,
        price_to_sma_20=0.03, price_to_sma_50=0.05, volume_ratio_20=1.3,
        adx_14=22, bb_position=0.6, volatility_20d=0.2, dv_20d=500e9,
        foreign_room_pct=500e6, score=5, stop=26.5, target=30.0, rr=1.8,
        is_valid_buy=True,
    )
    d = r.as_picks_dict()
    for key in ("sym", "sector", "close", "ret_5d", "score", "rsi", "macd_h",
                "adx", "vr20", "atr_pct", "bb_upper", "bb_lower"):
        assert key in d, f"missing key {key} (generate_report.py depends on it)"
    assert d["sym"] == "HPG"


def test_freshness_report_to_dict_is_json_safe():
    fr = FreshnessReport(
        as_of=date(2026, 4, 17),
        built_at=datetime(2026, 4, 18, 7, 19),
        universe_size=75,
        capability_pass_count=58,
        capability_fail_count=17,
        ohlcv_fail_pct=0.226,
        sectors_with_picks={"STEEL", "TECH"},
        sectors_missing_picks=[],
        errors=[],
        warnings=["219 HOSE symbols unclassified"],
    )
    d = fr.to_dict()
    # All JSON-serializable
    import json
    json.dumps(d)  # should not raise
    assert d["as_of"] == "2026-04-17"
    assert sorted(d["sectors_with_picks"]) == ["STEEL", "TECH"]


# -------------------- classification --------------------


def test_classify_prefers_override_over_icb():
    """sector_constituents override always wins, even if ICB says otherwise."""
    overrides = {"CMG": "TECH"}
    # ICB code 5 == Chứng khoán (BROK), but override says TECH → TECH wins
    assert _classify_sector("CMG", "Công ty XYZ", "5", overrides) == "TECH"


def test_classify_falls_back_to_icb_when_no_override():
    assert _classify_sector("VCB", "Ngan hang XYZ", "11", {}) == "BANK"


def test_classify_falls_back_to_keyword_when_icb_missing():
    assert _classify_sector("DPG", "Công ty Dầu khí DPG", None, {}) == "OIL"


def test_classify_returns_none_when_nothing_matches():
    assert _classify_sector("ZZZ", "Unknown Ltd", None, {}) is None


# -------------------- technical_bits --------------------


def test_technical_bits_captures_all_signals():
    r = TickerRow(
        symbol="X", sector_code="TECH", close=50.0,
        rsi_14=55, macd_hist=0.2, price_to_sma_20=0.01,
        price_to_sma_50=-0.02, adx_14=25, volume_ratio_20=1.5, atr_pct=3.0,
    )
    bits = _technical_bits(r)
    assert any("above SMA20" in b for b in bits)
    assert any("below SMA50" in b for b in bits)
    assert any("RSI" in b for b in bits)
    assert any("MACD+" in b for b in bits)
    assert any("ADX" in b for b in bits)
    assert any("Vol" in b for b in bits)
    assert any("ATR%" in b for b in bits)


def test_technical_bits_flags_overbought_rsi():
    bits = _technical_bits(TickerRow(symbol="X", sector_code="X", close=1, rsi_14=75))
    assert any("OB" in b for b in bits)


# -------------------- service singleton + cache --------------------


def test_get_picks_universe_returns_singleton():
    a = get_picks_universe()
    b = get_picks_universe()
    assert a is b, "module-level accessor must return the same instance"


def test_invalidate_clears_cache():
    svc = PicksUniverseService()
    # seed with a dummy snapshot
    svc._cache = UniverseSnapshot(
        as_of=date(2026, 4, 17),
        built_at=datetime(2026, 4, 18),
        tickers={}, by_sector={},
        freshness=FreshnessReport(as_of=date(2026, 4, 17), built_at=datetime.now()),
        is_valid=True,
    )
    assert svc._cache is not None
    svc.invalidate()
    assert svc._cache is None


def test_get_snapshot_returns_cache_when_as_of_unchanged():
    """Second call with same as_of must not trigger a rebuild."""
    svc = PicksUniverseService()
    fixed = UniverseSnapshot(
        as_of=date(2026, 4, 17),
        built_at=datetime(2026, 4, 18),
        tickers={}, by_sector={},
        freshness=FreshnessReport(as_of=date(2026, 4, 17), built_at=datetime.now()),
        is_valid=True,
    )
    svc._cache = fixed
    with patch("services.picks_universe_service._latest_signal_date",
               return_value=date(2026, 4, 17)):
        snap = svc.get_snapshot()
    assert snap is fixed  # identity — no rebuild


def test_get_snapshot_rebuilds_when_as_of_changed():
    """New signal date invalidates cache automatically."""
    svc = PicksUniverseService()
    stale = UniverseSnapshot(
        as_of=date(2026, 4, 16),
        built_at=datetime(2026, 4, 17),
        tickers={}, by_sector={},
        freshness=FreshnessReport(as_of=date(2026, 4, 16), built_at=datetime.now()),
        is_valid=True,
    )
    svc._cache = stale
    called = {}
    def fake_build(as_of, on_progress=None):
        # `on_progress` kwarg added 2026-04-20 so the async /insight/refresh
        # runner can stream stage progress to the UI; accept-and-ignore here.
        called["hit"] = as_of
        return UniverseSnapshot(
            as_of=as_of, built_at=datetime.now(),
            tickers={}, by_sector={},
            freshness=FreshnessReport(as_of=as_of, built_at=datetime.now()),
            is_valid=True,
        )
    with patch("services.picks_universe_service._latest_signal_date",
               return_value=date(2026, 4, 17)), \
         patch.object(svc, "_build", side_effect=fake_build):
        snap = svc.get_snapshot()
    assert called["hit"] == date(2026, 4, 17)
    assert snap.as_of == date(2026, 4, 17)


def test_get_snapshot_surfaces_prior_cache_on_build_failure():
    """If _build raises, the previous cache (with degraded freshness) is returned."""
    svc = PicksUniverseService()
    prior = UniverseSnapshot(
        as_of=date(2026, 4, 15),
        built_at=datetime(2026, 4, 15),
        tickers={}, by_sector={},
        freshness=FreshnessReport(as_of=date(2026, 4, 15), built_at=datetime.now()),
        is_valid=True,
    )
    svc._cache = prior
    with patch("services.picks_universe_service._latest_signal_date",
               return_value=date(2026, 4, 17)), \
         patch.object(svc, "_build", side_effect=RuntimeError("vnstock down")):
        snap = svc.get_snapshot()
    assert snap is prior
    assert snap.is_valid is False, "must be flagged stale on rebuild failure"
    assert any("build failed" in e for e in snap.freshness.errors)


def test_get_snapshot_synthesizes_empty_snapshot_when_no_prior_cache():
    svc = PicksUniverseService()
    assert svc._cache is None
    with patch("services.picks_universe_service._latest_signal_date",
               return_value=date(2026, 4, 17)), \
         patch.object(svc, "_build", side_effect=RuntimeError("vnstock down")):
        snap = svc.get_snapshot()
    assert snap.is_valid is False
    assert snap.tickers == {}
    # all 15 sector buckets present with empty lists
    assert len(snap.by_sector) == 15
    assert all(v == [] for v in snap.by_sector.values())

# -------------------- disk persistence (2026-08-23, review A1) --------------------
# The in-memory cache was the only part of the daily pipeline with no durable
# store, so every backend restart emptied the homepage until someone clicked
# Refresh and sat through the 18 req/min KBS throttle.

@pytest.fixture(autouse=True)
def _isolate_snapshot_file(tmp_path, monkeypatch):
    """Never touch the real data/snapshots/picks_universe.json from tests."""
    monkeypatch.setattr(
        "services.picks_universe_service.SNAPSHOT_PATH",
        tmp_path / "picks_universe.json",
    )

def _sample_snapshot(as_of=date(2026, 8, 23)) -> UniverseSnapshot:
    tr = TickerRow(symbol="HPG", sector_code="STEEL", close=27.5, score=71, dv_20d=4e10)
    pick = PickEntry(
        symbol="HPG", sector_code="STEEL", sector_name="Thép & VLXD", action="BUY",
        close=27.5, stop=25.0, target=32.0, rr=2.0, score=71, atr_pct=2.1,
        upside_pct=16.0, downside_pct=-9.0, foreign_room_pct=12.0, dv_20d=4e10,
        technical_bits=["RSI 58"], thesis="test",
    )
    return UniverseSnapshot(
        as_of=as_of, built_at=datetime(2026, 8, 23, 16, 5),
        tickers={"HPG": tr}, by_sector={"STEEL": [tr]},
        freshness=FreshnessReport(as_of=as_of, built_at=datetime.now(),
                                  universe_size=1, sectors_with_picks={"STEEL"}),
        is_valid=True, top_buys=[pick],
    )

def test_snapshot_json_roundtrip_preserves_rows_and_identity():
    import json as _json
    snap = _sample_snapshot()
    back = _snapshot_from_json(_json.loads(_json.dumps(_snapshot_to_json(snap))))
    assert back.as_of == snap.as_of and back.is_valid
    assert back.tickers["HPG"].score == 71
    # by_sector stores symbols and re-points at the same TickerRow objects, so
    # the file does not carry every row twice.
    assert back.by_sector["STEEL"][0] is back.tickers["HPG"]
    assert back.top_buys[0].symbol == "HPG"
    assert back.freshness.sectors_with_picks == {"STEEL"}

def test_peek_serves_snapshot_from_disk_on_cold_cache():
    """The A1 regression guard: a restarted process must not show an empty page."""
    svc = PicksUniverseService()
    svc._save_to_disk(_sample_snapshot())

    cold = PicksUniverseService()          # fresh process, empty memory
    assert cold._cache is None
    with patch("services.picks_universe_service._latest_signal_date",
               return_value=date(2026, 8, 23)):
        snap = cold.peek()
    assert snap is not None
    assert snap.is_valid, "as_of matches the latest signal date — still valid"
    assert list(snap.tickers) == ["HPG"]

def test_disk_snapshot_older_than_latest_signal_is_flagged_not_dropped():
    svc = PicksUniverseService()
    svc._save_to_disk(_sample_snapshot(as_of=date(2026, 8, 20)))

    cold = PicksUniverseService()
    with patch("services.picks_universe_service._latest_signal_date",
               return_value=date(2026, 8, 23)):
        snap = cold.peek()
    assert snap is not None and snap.tickers, "stale picks beat no picks"
    assert snap.is_valid is False
    assert any("cũ" in e for e in snap.freshness.errors)

def test_corrupt_snapshot_file_degrades_to_none_and_never_raises():
    from services.picks_universe_service import SNAPSHOT_PATH
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text("{not json at all", encoding="utf-8")
    assert PicksUniverseService().peek() is None

def test_missing_snapshot_file_returns_none():
    assert PicksUniverseService().peek() is None

def test_empty_build_is_not_persisted():
    """A source outage must not overwrite a good file with zero tickers."""
    svc = PicksUniverseService()
    svc._save_to_disk(_sample_snapshot())
    empty = UniverseSnapshot(
        as_of=date(2026, 8, 24), built_at=datetime.now(),
        tickers={}, by_sector={},
        freshness=FreshnessReport(as_of=date(2026, 8, 24), built_at=datetime.now()),
    )
    with patch("services.picks_universe_service._latest_signal_date",
               return_value=date(2026, 8, 24)), \
         patch.object(svc, "_build", return_value=empty):
        svc.get_snapshot(force=True)
    assert PicksUniverseService()._load_from_disk().tickers, "good file must survive"
