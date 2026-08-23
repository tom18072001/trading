"""Freshness sentinel — fail loudly when the ingestion pipeline stalls.

Post-mortem 2026-07-19: every SectorFlow_* job silently failed for 25 days
(orphaned venv) and nobody noticed until the /insight page went blank. This
script is the guard against a repeat: it checks the newest row in
`sector_flow_daily` and exits non-zero when the gap exceeds the threshold,
so Task Scheduler surfaces LastTaskResult != 0 and the log carries a clear,
greppable STALE line.

Run:  uv run python scripts/check_freshness.py [--max-gap-days N]
Exit: 0 fresh · 1 stale · 2 cannot read DB
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATABASE_PATH  # noqa: E402

# Weekends + VN public-holiday clusters mean 3-4 calendar days of silence is
# normal; beyond DEFAULT_MAX_GAP the pipeline is assumed broken.
DEFAULT_MAX_GAP = 5


def latest_flow_date(db_path: str) -> date | None:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT MAX(date) FROM sector_flow_daily").fetchone()
    finally:
        con.close()
    if not row or row[0] is None:
        return None
    return datetime.strptime(str(row[0])[:10], "%Y-%m-%d").date()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-gap-days", type=int, default=DEFAULT_MAX_GAP)
    args = ap.parse_args()

    try:
        latest = latest_flow_date(DATABASE_PATH)
    except Exception as e:  # noqa: BLE001 — sentinel must never crash silently
        print(f"[freshness] ERROR cannot read {DATABASE_PATH}: {e}")
        return 2

    today = date.today()
    if latest is None:
        print("[freshness] STALE: sector_flow_daily is empty")
        return 1

    gap = (today - latest).days
    status = "STALE" if gap > args.max_gap_days else "ok"
    print(f"[freshness] {status}: latest={latest} today={today} gap={gap}d "
          f"(threshold {args.max_gap_days}d)")
    return 1 if gap > args.max_gap_days else 0


if __name__ == "__main__":
    sys.exit(main())
