# tests/test_database_schema.py
from database.models import (
    BacktestRun, MacroAnchor, ModelRun, Sector, SectorConstituent,
    SectorFlowDaily, SectorFlowTS, SectorRegime, SectorSignal,
)


def test_seeded_session_has_15_sectors(seeded_session):
    rows = seeded_session.query(Sector).all()
    assert len(rows) == 15


def test_seeded_session_has_constituents(seeded_session):
    n = seeded_session.query(SectorConstituent).count()
    assert n == 15 * 5  # top-5 baskets


def test_insert_flow_ts(seeded_session):
    from datetime import datetime
    seeded_session.add(SectorFlowTS(
        sector_code="BANK", time=datetime(2025, 1, 1, 9, 15),
        net_dollar_flow=1_000_000, up_vol=500, down_vol=200,
        foreign_net=50_000, breadth_sma20=0.7, breadth_sma50=0.6,
        atr_pct=0.012,
    ))
    seeded_session.flush()
    assert seeded_session.query(SectorFlowTS).count() == 1


def test_signal_uniqueness(seeded_session):
    seeded_session.add(SectorSignal(
        date="2025-01-01", sector_code="BANK", score=0.5, rank=1, action="BUY",
    ))
    seeded_session.flush()
    assert seeded_session.query(SectorSignal).count() == 1
