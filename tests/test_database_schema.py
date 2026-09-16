# tests/test_database_schema.py
import sqlite3

from database.models import (
    BacktestRun, MacroAnchor, ModelRun, Sector, SectorConstituent,
    SectorFlowDaily, SectorFlowTS, SectorRegime, SectorSignal,
)

#: Dropped in migration 12 — see database/migrations.py. Both were created for
#: features that shipped deriving the fact instead of storing it.
_DROPPED_TABLES = ("sector_accumulation_events", "sector_flow_handoff")


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


# --------------------------------------------------------------------------
# Migration 12 — dropping two tables nothing ever wrote
# --------------------------------------------------------------------------

def _run_migrations_on(path, monkeypatch):
    from database import migrations as M
    monkeypatch.setattr(M, "DATABASE_PATH", str(path))
    M.run_migrations()


def test_migration_12_drops_both_write_less_tables(tmp_path, monkeypatch):
    """The migration itself, against a database that still has them."""
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE sector_accumulation_events (id INTEGER PRIMARY KEY);"
        "CREATE TABLE sector_flow_handoff (id INTEGER PRIMARY KEY);"
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
        " description TEXT NOT NULL, applied_at TIMESTAMP);"
    )
    conn.executemany(
        "INSERT INTO schema_migrations (version, description) VALUES (?, 'x')",
        [(v,) for v in range(1, 12)],
    )
    conn.commit()
    conn.close()

    _run_migrations_on(db, monkeypatch)

    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    conn.close()
    assert not (names & set(_DROPPED_TABLES))
    assert 12 in versions


def test_a_dropped_table_has_no_orm_model_left_to_recreate_it():
    """The half of the change that is easy to forget, and undoes the other half.

    `init_db()` calls `Base.metadata.create_all` BEFORE `run_migrations()`. A
    model left behind therefore recreates its table on the very next start, and
    the migration records itself as applied while the table is back — a schema
    change that silently reverts and never runs again.
    """
    from database.models import Base

    assert not (set(Base.metadata.tables) & set(_DROPPED_TABLES))


def test_the_drop_survives_a_restart(tmp_path, monkeypatch):
    """create_all + migrate, twice — the actual startup sequence."""
    from sqlalchemy import create_engine

    from database.models import Base
    db = tmp_path / "t.db"
    for _ in range(2):
        eng = create_engine(f"sqlite:///{db}")
        Base.metadata.create_all(bind=eng)
        eng.dispose()
        _run_migrations_on(db, monkeypatch)

    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert not (names & set(_DROPPED_TABLES))
