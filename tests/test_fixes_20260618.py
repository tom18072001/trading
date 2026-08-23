# tests/test_fixes_20260618.py
# Regression guards for the 2026-06-18 P0 fixes (foreign volume→value,
# vnstock dedup, ranker persistence, §16.2 features + 20d target).
from __future__ import annotations

import pandas as pd
import pytest

from config import ROTATION_TARGET_HORIZON_DAYS
from services.flow_feature_service import FEATURE_COLS
from services.rotation_model_service import TARGET_COL
from services import foreign_flow
from services.sector_ingest_service import SectorIngestService


# ---- Fix 1: foreign volume -> value -------------------------------------
# 2026-08-23: the parser moved from SectorIngestService._parse_foreign_board to
# services.foreign_flow.from_price_board, and it no longer returns a silent
# zero when it cannot do the conversion -- that silence is what hid the fact
# that sector_flow_ts held 0 non-zero foreign rows out of 12,175.
def test_foreign_parser_converts_volume_to_value():
    """KBS price_board exposes *_volume not *_value. The parser must convert
    via price so net != 0 (the bug that blocked every ACCUMULATE signal)."""
    board = pd.DataFrame([{
        "foreign_buy_volume": 100_000,
        "foreign_sell_volume": 40_000,
        "match_price": 25_000,
    }])
    buy, sell, net = foreign_flow.from_price_board(board)
    assert buy == 100_000 * 25_000
    assert sell == 40_000 * 25_000
    assert net == (100_000 - 40_000) * 25_000
    assert net != 0


def test_foreign_parser_prefers_value_columns():
    board = pd.DataFrame([{
        "foreign_buy_value": 2.5e9,
        "foreign_sell_value": 1.0e9,
    }])
    buy, sell, net = foreign_flow.from_price_board(board)
    assert (buy, sell, net) == (2.5e9, 1.0e9, 1.5e9)


def test_foreign_parser_empty_board_raises_instead_of_returning_zero():
    with pytest.raises(foreign_flow.ForeignFlowUnavailable):
        foreign_flow.from_price_board(pd.DataFrame())


def test_foreign_parser_says_so_when_it_cannot_find_a_price():
    """The live failure: KBS gives volumes, the old price lookup matched none
    of its column names, and the result was reported as 0.0 for months."""
    board = pd.DataFrame([{
        "foreign_buy_volume": 100_000,
        "foreign_sell_volume": 40_000,
        "some_unrelated_column": "x",
    }])
    with pytest.raises(foreign_flow.ForeignFlowUnavailable, match="price"):
        foreign_flow.from_price_board(board)


def test_foreign_parser_finds_a_price_under_other_names():
    """The price lookup is deliberately broad now."""
    for price_col in ("last_price", "close", "ref_price", "price"):
        board = pd.DataFrame([{
            "foreign_buy_volume": 10,
            "foreign_sell_volume": 4,
            price_col: 1_000,
        }])
        buy, sell, net = foreign_flow.from_price_board(board)
        assert net == 6 * 1_000, f"failed to find price column {price_col!r}"


# ---- Fix 2: vnstock duplicate-trailing-row dedup -----------------------
def test_dedup_restores_nonzero_flow():
    """A duplicated last bar makes close==prev_close → sign 0 → flow 0.
    Dedup (keep last) must restore the real sign."""
    from analysis.flow_aggregation import _net_dollar_flow
    idx = pd.to_datetime(["2026-04-28", "2026-04-29", "2026-04-30", "2026-04-30"])
    dup = pd.DataFrame({
        "open": 10.0, "high": 11.0, "low": 10.0,
        "close": [10.0, 10.5, 11.0, 11.0], "volume": [1e6, 1e6, 2e6, 2e6],
    }, index=idx)
    assert _net_dollar_flow(dup) == 0.0  # the bug
    fixed = dup[~dup.index.duplicated(keep="last")].sort_index()
    assert _net_dollar_flow(fixed) > 0   # restored


# ---- Fix 3: ranker persistence -----------------------------------------
def test_ranker_persists_and_reloads(tmp_path, monkeypatch):
    import models.rotation_ranker as rr
    monkeypatch.setattr(rr, "SAVED_MODELS_DIR", str(tmp_path))
    # Per-day ranking panel. Lengthened from 40 to 150 dates on 2026-08-22:
    # fit() now purges a (horizon + 2) embargo between train and test, and 40
    # dates does not leave enough training history for a 20-day target to be
    # honestly validated. See CODE_REVIEW_2026-08-22.md P0-6.
    from datetime import date as _date, timedelta as _timedelta
    rows = []
    base = _date(2025, 1, 1)
    for d in range(150):
        day = (base + _timedelta(days=d)).isoformat()
        for i, code in enumerate(["A", "B", "C"]):
            rows.append({"date": day, "sector_code": code,
                         "f1": i + d * 0.1, "f2": -i, "target": i + (d % 3)})
    df = pd.DataFrame(rows)
    r1 = rr.RotationRanker()
    res = r1.fit(df, ["f1", "f2"])
    assert res.model_path.endswith(".pkl")
    import os
    assert os.path.exists(res.model_path)
    # Fresh instance can reload the persisted estimator (no retrain)
    r2 = rr.RotationRanker()
    assert r2.load(res.model_path) is True
    assert r2.model is not None


# ---- Fix 4: §16.2 features wired + 20d target --------------------------
def test_leading_features_in_feature_cols():
    for col in ("flow_z20", "flow_z60", "foreign_streak", "foreign_hit_20d",
                "stealth_score", "flow_price_divergence", "accumulation_age"):
        assert col in FEATURE_COLS


def test_target_horizon_is_20d():
    assert ROTATION_TARGET_HORIZON_DAYS == 20
    assert TARGET_COL == "fwd_20d_sector_return"


# ---- P1: backtest realism (§18.2) --------------------------------------
def test_backtest_is_long_only_with_frictions(daily_panel):
    from services.backtest_service import SectorBacktestService
    bt = SectorBacktestService(daily_panel).run(
        name="realism", start_date="2025-01-01", end_date="2025-12-31")
    assert bt.total_trades > 0
    assert bt.long_only is True            # §18.2/12 no short cash leg
    assert bt.settlement_lag == 2          # §18.2/7 T+2
    assert bt.fee_bps == 15 and bt.sell_tax_bps == 10  # §18.2/10
    assert bt.total_cost_pct > 0           # frictions actually charged
    assert all(tr["side"] == "BUY" or tr["side"] == "SELL" for tr in bt.trade_log)
    assert not any(tr["side"] == "SHORT" for tr in bt.trade_log)


def test_backtest_price_band_blocks_gap_fills(seeded_session):
    """A sector that gapped >7% on entry day must be skipped (can't fill)."""
    from datetime import datetime, timedelta
    from database.models import SectorFlowDaily
    from services.backtest_service import SectorBacktestService
    base = datetime(2025, 3, 1)
    # GAP sector jumps +9% every day (always top flow, always gapped → unfillable)
    for i in range(15):
        d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        seeded_session.add(SectorFlowDaily(
            sector_code="BANK", date=d, close_idx=100 + i, return_1d=0.09,
            net_dollar_flow=9e9, atr_pct=0.02))
        seeded_session.add(SectorFlowDaily(
            sector_code="TECH", date=d, close_idx=50 + i * 0.1, return_1d=0.005,
            net_dollar_flow=1e9, atr_pct=0.02))
    seeded_session.flush()
    bt = SectorBacktestService(seeded_session).run(
        name="band", start_date="2025-03-01", end_date="2025-03-31")
    assert bt.ceiling_floor_skips > 0
    # BANK gapped every day → never bought
    assert not any(tr["sector"] == "BANK" for tr in bt.trade_log)
