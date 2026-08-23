# ============================================
# database/migrations.py — Sector Money-Flow Schema
# ============================================
# Migration 8 freezes legacy symbol-prediction tables (rename to _legacy_*)
# and creates the new sector schema. The ORM models in `models.py` describe
# the target state; SQLAlchemy `Base.metadata.create_all` creates the new
# tables on init. This migration also archives any pre-existing legacy
# tables on databases that already had the old schema.

import os
import sqlite3

from config import DATABASE_PATH


# Legacy tables to freeze (rename) so we can shadow-run, then drop later.
LEGACY_TABLES = [
    "stocks", "stock_prices", "stock_features", "stock_prices_intraday",
    "predictions", "feature_importance", "trade_setups", "sector_analysis",
    "chart_drawings",
]


MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (
        8,
        "freeze legacy symbol tables; sector schema created via ORM",
        # Statements run inside `run_migrations` AFTER ORM create_all,
        # so the new sector_* tables are guaranteed to exist before we
        # touch any legacy tables.
        [
            f"ALTER TABLE {t} RENAME TO _legacy_{t}" for t in LEGACY_TABLES
        ],
    ),
    (
        9,
        "stealth detection: leading-flow columns + accumulation events table",
        [
            "ALTER TABLE sector_flow_daily ADD COLUMN flow_z20 REAL",
            "ALTER TABLE sector_flow_daily ADD COLUMN flow_z60 REAL",
            "ALTER TABLE sector_flow_daily ADD COLUMN foreign_streak INTEGER",
            "ALTER TABLE sector_flow_daily ADD COLUMN foreign_hit_20d REAL",
            "ALTER TABLE sector_flow_daily ADD COLUMN stealth_score REAL",
            "ALTER TABLE sector_flow_daily ADD COLUMN flow_price_divergence REAL",
            "ALTER TABLE sector_flow_daily ADD COLUMN accumulation_age INTEGER DEFAULT 0",
            """
            CREATE TABLE IF NOT EXISTS sector_accumulation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sector_code TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                peak_return_pct REAL,
                lead_days_to_price INTEGER,
                resolved INTEGER DEFAULT 0,
                UNIQUE(sector_code, start_date)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_accum_events_sector ON sector_accumulation_events(sector_code, start_date)",
        ],
    ),
    (
        10,
        "split foreign buy/sell + intensity; flow handoff matrix table",
        [
            "ALTER TABLE sector_flow_ts ADD COLUMN foreign_buy_val REAL",
            "ALTER TABLE sector_flow_ts ADD COLUMN foreign_sell_val REAL",
            "ALTER TABLE sector_flow_ts ADD COLUMN foreign_intensity REAL",
            "ALTER TABLE sector_flow_daily ADD COLUMN foreign_buy_val REAL",
            "ALTER TABLE sector_flow_daily ADD COLUMN foreign_sell_val REAL",
            "ALTER TABLE sector_flow_daily ADD COLUMN foreign_intensity REAL",
            """
            CREATE TABLE IF NOT EXISTS sector_flow_handoff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                from_sector TEXT NOT NULL,
                to_sector TEXT NOT NULL,
                handoff_score REAL NOT NULL,
                UNIQUE(date, from_sector, to_sector)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_handoff_date ON sector_flow_handoff(date)",
        ],
    ),
    (
        11,
        "carry price into the scheduled rollup (review 2026-08-22, P0-2/P0-3)",
        # sector_flow_ts had no price column at all, so rollup_to_daily -- the
        # only ingest path that runs on a schedule -- could not populate
        # sector_flow_daily.close_idx / return_1d. Those three columns feed the
        # ML target, stealth condition 5 and the whole backtest P&L, so they
        # were being filled only by the UI-triggered fast_ingest path, and only
        # for dates the scheduler had not already claimed.
        #
        # basket_return is the split-safe companion to close_idx: the weighted
        # mean of each constituent's own 1-day return. close_idx is a raw sum
        # of prices and jumps on any split or basket change.
        [
            "ALTER TABLE sector_flow_ts ADD COLUMN close_idx REAL",
            "ALTER TABLE sector_flow_ts ADD COLUMN basket_return REAL",
        ],
    ),
]


def _table_exists(cursor: sqlite3.Cursor, name: str) -> bool:
    row = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def run_migrations() -> None:
    """Apply any unapplied migrations. Safe to call multiple times."""
    if not os.path.exists(DATABASE_PATH):
        return

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied = {
        row[0] for row in cursor.execute(
            "SELECT version FROM schema_migrations"
        ).fetchall()
    }

    newly_applied = 0
    for version, description, statements in MIGRATIONS:
        if version in applied:
            continue

        if version == 8:
            # Only rename legacy tables that actually exist *and* whose
            # _legacy_ counterpart does not already exist.
            for legacy in LEGACY_TABLES:
                if _table_exists(cursor, legacy) and not _table_exists(cursor, f"_legacy_{legacy}"):
                    try:
                        cursor.execute(f"ALTER TABLE {legacy} RENAME TO _legacy_{legacy}")
                    except sqlite3.OperationalError as e:
                        print(f"  [Migration {version}] skip {legacy}: {e}")
        else:
            for sql in statements:
                try:
                    cursor.execute(sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise

        cursor.execute(
            "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
            (version, description),
        )
        newly_applied += 1
        print(f"  [Migration {version}] {description}")

    conn.commit()
    conn.close()

    if newly_applied:
        print(f"[DB] Applied {newly_applied} migration(s)")


def seed_sectors() -> None:
    """Populate `sectors` and `sector_constituents` from config.

    Idempotent — safe to call on every startup.
    """
    from config import PROXY_BASKETS, SECTORS
    from database.connection import get_session
    from database.models import Sector, SectorConstituent

    with get_session() as session:
        existing = {s.sector_code for s in session.query(Sector).all()}
        for code, name in SECTORS.items():
            if code not in existing:
                session.add(Sector(sector_code=code, name=name))
        session.flush()

        existing_pairs = {
            (c.sector_code, c.symbol)
            for c in session.query(SectorConstituent).all()
        }
        for code, symbols in PROXY_BASKETS.items():
            for sym in symbols:
                if (code, sym) in existing_pairs:
                    continue
                # Equal-weight by default; flow_aggregation re-weights at runtime.
                session.add(SectorConstituent(
                    sector_code=code, symbol=sym,
                    weight=1.0 / len(symbols), active=True,
                ))
