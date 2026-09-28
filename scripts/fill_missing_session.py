"""Rebuild one sector session the scheduled jobs missed -- backup first.

Why it exists: on 2026-09-25 the machine lost power at 11:53 and stayed off
until the next evening. The intraday job had left a sector_flow_ts bar per
sector with the MORNING session in it; the 16:00 rollup never ran, so
sector_flow_daily has no 2026-09-25 row. Rolling that morning bar up would
file half a day of flow as the day's. This rebuilds the session from its
full-day data instead, through the same code the jobs run:

  1. `SectorIngestService.ingest_intraday_now(as_of=DATE)` -- every
     constituent's daily bars up to DATE, that day's foreign flow,
     `aggregate_sector`, upserted over the partial bar;
  2. `rollup_to_daily(date=DATE)` -- the daily row, `close_idx` chained from
     the session before;
  3. `rebuild_leading_features` -- the §16.2 columns over the whole table.

Later rows keep a level chained past the missing day; run
`scripts/repair_sector_data.py` afterwards to re-chain the whole history.

Safe by default: DRY RUN unless --apply (reports what exists, fetches and
writes nothing). --apply refuses a date that is not a past trading session,
refuses 08:45-17:45 on a trading day unless --force-hours, refuses when a
probe finds the price or foreign-flow source without that day, and takes a
backup first (`<db>.bak-<timestamp>-pre-fill`). If any sector cannot be
rebuilt it stops before step 2 (exit 4): that sector would roll up its
morning bar.

Windows, from the repo root:
    .venv\\Scripts\\python.exe scripts\\fill_missing_session.py --date 2026-09-25
    .venv\\Scripts\\python.exe scripts\\fill_missing_session.py --date 2026-09-25 --apply
"""
from __future__ import annotations

# Output is ASCII on purpose: a redirected Windows console uses the ANSI code page.

import argparse
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import DATABASE_PATH, SECTORS  # noqa: E402
from scripts.repair_sector_data import QUIET_FROM, QUIET_TO  # noqa: E402


def state(db: sqlite3.Connection, day: str) -> dict:
    daily = {r[0] for r in db.execute(
        "SELECT sector_code FROM sector_flow_daily WHERE date = ?", (day,))}
    ts = db.execute("SELECT COUNT(*), MIN(time), MAX(time) FROM sector_flow_ts "
                    "WHERE time >= ? AND time < date(?, '+1 day')", (day, day)).fetchone()
    return {"daily": daily, "ts_rows": ts[0], "ts_first": ts[1], "ts_last": ts[2]}


def refusal(day: date, now: datetime, is_trading, force_hours: bool) -> list[str]:
    why = []
    if not is_trading(day):
        why.append(f"{day} is not a trading session -- there is nothing to rebuild.")
    if day >= now.date():
        why.append(f"{day} is not in the past -- today's session belongs to the "
                   "scheduled jobs.")
    if not force_hours and is_trading(now.date()) and QUIET_FROM <= now.time() <= QUIET_TO:
        why.append(f"{now:%H:%M} on a trading day: the scheduled jobs write to this "
                   f"database between {QUIET_FROM:%H:%M} and {QUIET_TO:%H:%M}. Run it "
                   f"after {QUIET_TO:%H:%M}, or pass --force-hours.")
    return why


def backup(db_path: Path, stamp: str) -> Path:
    dest = db_path.with_name(f"{db_path.name}.bak-{stamp}-pre-fill")
    src = sqlite3.connect(db_path, timeout=60)
    try:
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()
    return dest


PROBE = "VCB"      # liquid, foreign-traded every session, in the BANK basket


def preflight(day: str) -> list[str]:
    """Do the sources have `day`? Two calls, nothing written.

    A source that is down or lagging would otherwise be filed as data: every
    foreign flow a loud zero, or no name with a bar that day.
    """
    from datetime import timedelta

    from services import foreign_flow
    from services.sector_ingest_service import SectorIngestService

    why = []
    start = (date.fromisoformat(day) - timedelta(days=10)).isoformat()
    bars = SectorIngestService(None)._fetch_constituent_daily(PROBE, start, day)
    if bars.empty or day not in set(bars.index.strftime("%Y-%m-%d")):
        why.append(f"the price source has no {PROBE} bar on {day} (down, or not caught up).")
    flow = foreign_flow.fetch_history(PROBE, day, day)
    if flow.empty or day not in set(flow["date"]):
        why.append(f"the foreign-flow source has no {PROBE} row on {day}; every name "
                   "would be filed as 0.")
    return why


def rebuild(db_path: Path, day: str) -> tuple[list[str], int, int]:
    """Rebuild every sector's bar for `day`; roll up only if all 15 were.

    Returns (sectors not rebuilt, daily rows written, feature rows). A
    sector left without a rebuilt bar still holds the morning bar, and rolling
    THAT up is the error this script exists to avoid -- so any miss stops
    before the rollup. The rebuilt bars stay (they are the day's, not a
    guess); a re-run is idempotent.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from services.fast_ingest import rebuild_leading_features
    from services.sector_ingest_service import SectorIngestService

    eng = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 60})
    s = sessionmaker(bind=eng)()
    try:
        svc = SectorIngestService(s)
        missed = [code for code in SECTORS
                  if svc.ingest_intraday_now(sector_codes=[code], as_of=day) != 1]
        if missed:
            return missed, 0, 0
        daily = svc.rollup_to_daily(date=day)
        feats = rebuild_leading_features(s)
        return [], daily, feats
    finally:
        s.close()
        eng.dispose()


def main(argv: list[str] | None = None, *, now: datetime | None = None,
         is_trading=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", required=True, help="the missed session, YYYY-MM-DD")
    ap.add_argument("--db", default=DATABASE_PATH)
    ap.add_argument("--apply", action="store_true", help="fetch and write (default: dry run)")
    ap.add_argument("--force-hours", action="store_true")
    args = ap.parse_args(argv)

    from utils import clock
    now = now or clock.now().replace(tzinfo=None)
    is_trading = is_trading or clock.is_trading_day
    day = date.fromisoformat(args.date)
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"not found: {db_path}")
        return 2

    db = sqlite3.connect(db_path, timeout=60)
    try:
        st = state(db, args.date)
    finally:
        db.close()
    missing = sorted(set(SECTORS) - st["daily"])
    print(f"{args.date}: sector_flow_daily has {len(st['daily'])}/{len(SECTORS)} sectors"
          + (f" (missing: {', '.join(missing)})" if missing else ""))
    print(f"{args.date}: sector_flow_ts has {st['ts_rows']} bar(s)"
          + (f", {st['ts_first']} .. {st['ts_last']}" if st["ts_rows"] else "")
          + " -- intraday bars hold the session as of their last run, not its close")

    why = refusal(day, now, is_trading, args.force_hours)
    if not args.apply:
        print("\nDRY RUN -- nothing fetched or written. --apply rebuilds all "
              f"{len(SECTORS)} sectors for {args.date} from full-day data "
              "(a backup is taken first).")
        for w in why:
            print(f"--apply would refuse right now: {w}")
        return 0
    if why:
        for w in why:
            print(f"\nNOT APPLIED: {w}")
        return 3
    why = preflight(args.date)
    if why:
        for w in why:
            print(f"\nNOT APPLIED: {w} Nothing written; try again later.")
        return 3

    dest = backup(db_path, now.strftime("%Y%m%d-%H%M%S"))
    print(f"\nbackup: {dest}")
    missed, daily, feats = rebuild(db_path, args.date)
    if missed:
        print(f"\nSTOPPED before the rollup: no bar on {args.date} for "
              f"{', '.join(missed)}. The other sectors' bars were rebuilt; "
              "sector_flow_daily is untouched. Re-run later.")
        return 4
    print(f"written: {len(SECTORS)} intraday bars rebuilt, {daily} daily row(s), "
          f"leading features on {feats} rows")
    print("next: python scripts/repair_sector_data.py (re-chains close_idx past "
          f"{args.date}; needs the price panel to cover it).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
