"""_audit/probe_foreign.py -- why does sector_flow_ts.foreign_net never get a value?

The scheduled ingest reads foreign flow from vnstock's price_board.
The UI-triggered fast_ingest reads it from VNDirect's /v4/foreigns.
One of them works. This shows which, and what the other actually returns.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pd.set_option("display.width", 200)
SEP = "=" * 78

from config import DATA_SOURCE  # noqa: E402
from services.sector_ingest_service import SectorIngestService  # noqa: E402

SYM = "VCB"

print(SEP)
print(f"  A. price_board  (what the SCHEDULED job uses)  source={DATA_SOURCE}")
print(SEP)
try:
    from vnstock import Vnstock
    board = Vnstock().stock(symbol=SYM, source=DATA_SOURCE).trading.price_board([SYM])
    print(f"shape={board.shape}")
    flat = SectorIngestService._flatten_board(board)
    foreign_cols = {k: v for k, v in flat.items() if "foreign" in k}
    print(f"\ncolumns containing 'foreign': {len(foreign_cols)}")
    for k in sorted(foreign_cols):
        try:
            val = board.iloc[0][foreign_cols[k]]
        except Exception as e:
            val = f"<{e}>"
        print(f"   {k:<46} = {val!r}")
    if not foreign_cols:
        print("   *** NONE. price_board exposes no foreign columns at all. ***")
        print(f"\n   all {len(flat)} columns it DOES expose:")
        for k in sorted(flat):
            print(f"     {k}")
    b, s, n = SectorIngestService._parse_foreign_board(board)
    print(f"\n_parse_foreign_board -> buy={b:,.0f}  sell={s:,.0f}  net={n:,.0f}")
    if n == 0:
        print("*** returns 0 -- this is why every sector_flow_ts row is zero ***")
except Exception as e:
    print(f"price_board FAILED: {type(e).__name__}: {e}")

print()
print(SEP)
print("  B. VNDirect /v4/foreigns  (what fast_ingest uses)")
print(SEP)
try:
    from services.fast_ingest import _fetch_foreign_vndirect
    df = _fetch_foreign_vndirect(SYM, "2026-06-01", "2026-08-22")
    if df.empty:
        print("*** empty ***")
    else:
        print(f"rows={len(df)}  span={df.date.min()} .. {df.date.max()}")
        print(df[["date", "buyVal", "sellVal", "netVal"]].head(6).to_string(index=False))
        print("\n=> the source is ALIVE and has history. The gap is not upstream.")
except Exception as e:
    print(f"vndirect FAILED: {type(e).__name__}: {e}")

print()
print(SEP)
print("  C. When did each writer last run?")
print(SEP)
import sqlite3  # noqa: E402
con = sqlite3.connect(f"file:{ROOT / 'vnstock_market.db'}?mode=ro", uri=True)
q = """
SELECT MAX(date) FROM sector_flow_daily WHERE foreign_net IS NOT NULL AND foreign_net != 0
"""
print(f"last non-zero foreign_net in sector_flow_daily : {con.execute(q).fetchone()[0]}")
print(f"last row in sector_flow_daily                  : "
      f"{con.execute('SELECT MAX(date) FROM sector_flow_daily').fetchone()[0]}")
print(f"non-zero foreign rows in sector_flow_ts        : "
      f"{con.execute('SELECT COUNT(*) FROM sector_flow_ts WHERE foreign_net IS NOT NULL AND foreign_net != 0').fetchone()[0]}")
con.close()
print("""
Reading:
  fast_ingest (VNDirect) only runs when someone clicks Refresh in the UI.
  The nightly job uses price_board, which returns nothing usable.
  So foreign_net stops on the day of the last manual refresh -- not on the day
  the data stopped existing.
""")
