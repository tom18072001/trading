"""_audit/clean_fabricated.py -- remove the fabricated sector_flow_daily rows.

    uv run python _audit\\clean_fabricated.py            # report only
    uv run python _audit\\clean_fabricated.py --apply    # delete + refill

What counts as fabricated (measured 2026-08-23):

  1. A row whose net_dollar_flow is IDENTICAL to the previous session's for the
     same sector. `rollup_to_daily` used to take each sector's newest
     sector_flow_ts bar and stamp it with TODAY's date without checking what
     day that bar belonged to, so during the 2026-07-19 -> 2026-08-21 ingest
     outage the same frozen bar was written 26 times per sector = 390 rows.
  2. A row dated on a weekend or a published HOSE holiday. The market was shut;
     any such row was manufactured by a job that should not have run.

Only runs of length >= 2 count. A genuine repeat of an identical VND figure on
two consecutive days is possible but vanishingly unlikely at this precision --
and the runs here are 26 long, in every sector, over exactly the outage window.

Safety: takes a timestamped .db copy before touching anything, prints the exact
row counts before and after, and does nothing at all without --apply.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "vnstock_market.db"
APPLY = "--apply" in sys.argv
SEP = "=" * 78


def hdr(t):
    print(f"\n{SEP}\n  {t}\n{SEP}")


from config import VN_MARKET_HOLIDAYS_2026  # noqa: E402

HOLIDAYS = set(VN_MARKET_HOLIDAYS_2026)

con = sqlite3.connect(DB)
df = pd.read_sql_query(
    "SELECT id, sector_code, date, net_dollar_flow, close_idx "
    "FROM sector_flow_daily ORDER BY sector_code, date", con)

hdr("Before")
print(f"rows={len(df):,}  sectors={df.sector_code.nunique()}  "
      f"dates={df.date.nunique():,}  range={df.date.min()} .. {df.date.max()}")

# ---- rule 1: repeated-bar runs -------------------------------------------
dup_ids: set[int] = set()
windows: list[tuple[str, str, str, int]] = []
for code, g in df.groupby("sector_code"):
    g = g.reset_index(drop=True)
    v = pd.to_numeric(g.net_dollar_flow, errors="coerce")
    same = (v.diff() == 0) & v.notna() & (v != 0)
    if not same.any():
        continue
    run_id = (~same).cumsum()
    for rid, grp in g[same].groupby(run_id[same]):
        if len(grp) >= 2:
            dup_ids.update(int(i) for i in grp.id)
            windows.append((code, grp.date.iloc[0], grp.date.iloc[-1], len(grp)))

# ---- rule 2: non-trading days --------------------------------------------
dt = pd.to_datetime(df.date, errors="coerce")
weekend = dt.dt.weekday >= 5
holiday = df.date.isin(HOLIDAYS)
closed_ids = set(int(i) for i in df.loc[weekend | holiday, "id"])

hdr("Fabricated rows found")
print(f"  repeated-bar rows      : {len(dup_ids):,}")
print(f"  weekend/holiday rows   : {len(closed_ids):,}")
victims = dup_ids | closed_ids
print(f"  total to delete        : {len(victims):,}"
      f"   ({len(victims) / len(df) * 100:.1f}% of the table)")

if windows:
    print("\n  repeated-bar windows (per sector, longest first):")
    for code, a, b, n in sorted(windows, key=lambda w: -w[3])[:20]:
        print(f"    {code:<8} {n:>3} rows   {a} -> {b}")

if closed_ids:
    closed_dates = sorted(set(df.loc[df.id.isin(closed_ids), "date"]))
    print(f"\n  non-trading dates present: {len(closed_dates)}")
    print(f"    {', '.join(closed_dates[:12])}"
          + (" ..." if len(closed_dates) > 12 else ""))

if not victims:
    print("\nnothing to do.")
    con.close()
    sys.exit(0)

if not APPLY:
    print("\n--- dry run. re-run with --apply to delete. ---")
    con.close()
    sys.exit(0)

# ---- apply ---------------------------------------------------------------
from utils.clock import now as market_now  # noqa: E402

stamp = market_now().strftime("%Y%m%d-%H%M%S")
backup = DB.with_name(f"vnstock_market.db.bak-{stamp}")
con.close()
shutil.copyfile(DB, backup)
print(f"\nbackup written: {backup.name} ({backup.stat().st_size / 1e6:.1f} MB)")

con = sqlite3.connect(DB)
cur = con.cursor()
ids = sorted(victims)
for i in range(0, len(ids), 500):
    chunk = ids[i:i + 500]
    cur.execute(
        f"DELETE FROM sector_flow_daily WHERE id IN ({','.join('?' * len(chunk))})",
        chunk)
con.commit()

after = pd.read_sql_query(
    "SELECT sector_code, date FROM sector_flow_daily", con)
hdr("After")
print(f"rows={len(after):,}  dates={after.date.nunique():,}  "
      f"range={after.date.min()} .. {after.date.max()}")
print(f"deleted {len(df) - len(after):,} rows")

# Leading stealth/z features are derived from the series we just changed, so
# they are stale for every remaining row. Recompute them.
print("\nrecomputing leading features over the cleaned panel...")
con.close()

from database.connection import get_session  # noqa: E402
from services.fast_ingest import _rebuild_leading_features_fast  # noqa: E402

with get_session() as s:
    _rebuild_leading_features_fast(s)
    s.commit()
print("done.")
print("\nNEXT: run  uv run python main.py --backfill --years 3   to refill the")
print("      holes the deletion left, then --train to re-measure the model.")
