# ============================================
# database/connection.py
# SQLAlchemy engine, session factory, DB init
# ============================================

import os

from config import DATABASE_URL

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager


# SQLite WAL mode cho concurrent reads trong khi write
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL mode, foreign keys, and performance pragmas for SQLite."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")       # Faster writes (safe with WAL)
    cursor.execute("PRAGMA cache_size=-64000")         # 64MB cache (default is 2MB)
    cursor.execute("PRAGMA mmap_size=268435456")       # 256MB memory-mapped I/O
    cursor.execute("PRAGMA temp_store=MEMORY")         # Temp tables in memory
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_session():
    """Context manager for DB sessions. Auto-commits on success, rollback on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_dependency():
    """FastAPI dependency that yields a DB session."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _migrate_db():
    """Run versioned migrations from database/migrations.py."""
    from database.migrations import run_migrations
    run_migrations()


def checkpoint_wal():
    """Checkpoint WAL file to reduce disk usage."""
    import sqlite3
    from config import DATABASE_PATH
    if not os.path.exists(DATABASE_PATH):
        return
    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    print("[DB] WAL checkpoint completed")


def init_db():
    """Create all sector tables, run migrations, seed sectors."""
    from database.models import Base
    Base.metadata.create_all(bind=engine)
    _migrate_db()
    try:
        from database.migrations import seed_sectors
        seed_sectors()
    except Exception as e:
        print(f"[DB] seed_sectors skipped: {e}")
    checkpoint_wal()
    print(f"[DB] Database initialized: {engine.url}")


# ===== TEST =====
if __name__ == "__main__":
    init_db()
    with get_session() as session:
        print(f"[DB] Session created successfully: {session.bind.url}")
