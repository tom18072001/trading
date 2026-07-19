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
    PicksUniverseService,
    TickerRow,
    UniverseSnapshot,
    _classify_sector,
    _technical_bits,
    get_picks_universe,
)


# -------------------- dataclasses --------------------


def test_ticker_row_as_picks_dict_shape():
    """The adapter dict is consumed by generate_secv5 — its keys must stay stable."""
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
        assert key in d, f"missing key {key} (generate_secv5 depends on it)"
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
