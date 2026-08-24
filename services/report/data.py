"""The daily report's reads against the sector schema.

Extracted from `generate_report.py` (§20.3 P3-2). These were closures over a
module-level `cur`, which is exactly why nothing here could be tested: calling
one meant importing the report, and importing the report sent mail.

They take the cursor as an argument now, so a test can hand them an in-memory
SQLite with three rows in it.

Raw `sqlite3`, not SQLAlchemy, because that is what the report has always used
and swapping the driver is a different change with a different risk. The report
is read-only against a DB the rest of the system writes.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

__all__ = [
    "open_db",
    "latest_regime",
    "latest_macro",
    "latest_signals",
    "latest_flow_daily",
    "sector_name_map",
]


def open_db(path: str) -> sqlite3.Connection:
    """Connect, falling back to a temp copy when the file cannot be opened.

    §18.4/18 documents WAL on a network mount as fragile. When the direct open
    raises `OperationalError` the report copies the file to temp and reads that
    — a stale-but-readable report beats no report at 17:00.
    """
    try:
        c = sqlite3.connect(path)
        c.execute("SELECT 1").fetchone()
        return c
    except sqlite3.OperationalError:
        tmp = Path(tempfile.gettempdir()) / "vn_report_db.sqlite"
        shutil.copyfile(path, tmp)
        return sqlite3.connect(str(tmp))


def latest_regime(cur: sqlite3.Cursor) -> dict:
    """Most recent HMM regime row.

    The fallback is `chop` at 0.5 — deliberately the least actionable label the
    system has. An empty table must not read as a stance.
    """
    r = cur.execute(
        "SELECT date, regime_label, confidence FROM sector_regime "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return dict(r) if r else {"date": "n/a", "regime_label": "chop", "confidence": 0.5}


def latest_macro(cur: sqlite3.Cursor) -> dict:
    r = cur.execute("SELECT * FROM macro_anchors ORDER BY time DESC LIMIT 1").fetchone()
    return dict(r) if r else {}


def latest_signals(cur: sqlite3.Cursor) -> list[dict]:
    """Published sector signals for the newest date, in rank order.

    `MAX(date)` first rather than `ORDER BY date DESC LIMIT 15`: the second
    would silently mix two dates if a publish ran short.
    """
    d = cur.execute("SELECT MAX(date) FROM sector_signals").fetchone()[0]
    if not d:
        return []
    return [dict(r) for r in cur.execute(
        "SELECT * FROM sector_signals WHERE date=? ORDER BY rank", (d,))]


def latest_flow_daily(cur: sqlite3.Cursor) -> dict[str, dict]:
    """`{sector_code: row}` for the newest `sector_flow_daily` date."""
    d = cur.execute("SELECT MAX(date) FROM sector_flow_daily").fetchone()[0]
    if not d:
        return {}
    return {
        r["sector_code"]: dict(r)
        for r in cur.execute("SELECT * FROM sector_flow_daily WHERE date=?", (d,))
    }


def sector_name_map(cur: sqlite3.Cursor) -> dict[str, str]:
    return {r["sector_code"]: r["name"] for r in cur.execute(
        "SELECT sector_code, name FROM sectors")}
