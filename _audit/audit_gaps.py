"""_audit/audit_gaps.py -- pin down the two things the first audit left ambiguous.

  A. WHICH dates are the 26-day stale runs? (review P0-1)
  B. Is foreign_net really empty, or only empty in sector_flow_ts? (review P0-5)
  C. Has ACCUMULATE ever fired, and what do the published signals look like?
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
con = sqlite3.connect(f"file:{ROOT / 'vnstock_market.db'}?mode=ro", uri=True)
SEP = "=" * 78


def hdr(t):
    print(f"\n{SEP}\n  {t}\n{SEP}")


# ------------------------------------------------------------------ A
hdr("A. Where are the duplicated bars?")
d = pd.read_sql_query(
    "SELECT sector_code, date, net_dollar_flow FROM sector_flow_daily "
    "ORDER BY sector_code, date", con)
g = d[d.sector_code == "BANK"].reset_index(drop=True)
same = (g.net_dollar_flow.diff() == 0) & g.net_dollar_flow.notna() & (g.net_dollar_flow != 0)
grp = (~same).cumsum()
sizes = same.groupby(grp).sum()
best = sizes.idxmax()

run = g[(grp == best) & (same | same.shift(-1).fillna(False))]
print(f"BANK longest run = {int(sizes.max())} repeated days")
print(f"  from {run.date.iloc[0]} to {run.date.iloc[-1]}")
print(f"  repeated value = {run.net_dollar_flow.iloc[0]:,.0f}")
print("\nsample of those rows:")
print(run.head(8).to_string(index=False))

print("\nper-sector windows:")
for code, gg in d.groupby("sector_code"):
    gg = gg.reset_index(drop=True)
    s = (gg.net_dollar_flow.diff() == 0) & gg.net_dollar_flow.notna() & (gg.net_dollar_flow != 0)
    if not s.any():
        continue
    gr = (~s).cumsum()
    sz = s.groupby(gr).sum()
    b = sz.idxmax()
    w = gg[gr == b]
    print(f"  {code:<8} {int(sz.max()):>3} days   {w.date.iloc[0]} -> {w.date.iloc[-1]}")

# ------------------------------------------------------------------ B
hdr("B. foreign_net -- daily vs intraday table")
for tbl, tcol in (("sector_flow_daily", "date"), ("sector_flow_ts", "time")):
    try:
        f = pd.read_sql_query(
            f"SELECT {tcol} AS t, foreign_net FROM {tbl}", con)
    except Exception as e:
        print(f"{tbl}: {e}")
        continue
    v = pd.to_numeric(f.foreign_net, errors="coerce")
    nonzero = (v.fillna(0) != 0)
    print(f"\n{tbl}: rows={len(f):,}  null={v.isna().mean()*100:.1f}%  "
          f"zero={(v == 0).mean()*100:.1f}%  nonzero={nonzero.sum():,}")
    if nonzero.any():
        nz = f[nonzero]
        print(f"  non-zero span: {nz.t.min()} .. {nz.t.max()}")
        print(f"  magnitude: median|x|={v[nonzero].abs().median():,.0f}  max|x|={v[nonzero].abs().max():,.0f}")
    else:
        print("  *** every row is zero or null ***")

# ------------------------------------------------------------------ C
hdr("C. Signals actually published")
try:
    s = pd.read_sql_query("SELECT * FROM sector_signals", con)
    print(f"rows={len(s):,}  dates={s.date.nunique():,}  "
          f"range={s.date.min()} .. {s.date.max()}")
    print("\naction counts over all history:")
    print(s.action.value_counts().to_string())
    if "ACCUMULATE" not in set(s.action):
        print("\n*** ACCUMULATE has NEVER been published. The entire section-16 ***")
        print("*** stealth doctrine has produced zero signals.                 ***")
    print("\nlast published date:")
    print(s[s.date == s.date.max()][["sector_code", "rank", "action", "score"]]
          .sort_values("rank").to_string(index=False))
except Exception as e:
    print(f"sector_signals: {e}")

hdr("D. model_runs -- which backend has ever been active?")
try:
    m = pd.read_sql_query(
        "SELECT id, model_name, target_col, train_size, metrics, is_active, status, created_at "
        "FROM model_runs ORDER BY id DESC LIMIT 8", con)
    for _, r in m.iterrows():
        import json
        try:
            met = json.loads(r.metrics or "{}")
        except Exception:
            met = {}
        print(f"  id={r.id:<4} active={bool(r.is_active)!s:<5} target={r.target_col:<28} "
              f"train={r.train_size or 0:<7} backend={met.get('backend')}")
    print(f"\n  total model_runs: {pd.read_sql_query('SELECT COUNT(*) n FROM model_runs', con).n[0]}")
except Exception as e:
    print(f"model_runs: {e}")

con.close()
print("\ndone.")
