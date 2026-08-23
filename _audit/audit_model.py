"""_audit/audit_model.py -- real-data health + model-quality audit.

Run:  uv run python _audit/audit_model.py

Reads the live vnstock_market.db. Read-only: it never writes to the DB.
Answers three questions with numbers rather than opinion:

  1. Is the daily panel actually populated? (close_idx / foreign_net / return_1d)
  2. Why has LightGBM never trained? (the dtype the nightly log complains about)
  3. What is the ranker actually worth once it CAN train?
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "vnstock_market.db"
SEP = "=" * 78


def hdr(t):
    print(f"\n{SEP}\n  {t}\n{SEP}")


con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

# ---------------------------------------------------------------- 1. panel
hdr("1. sector_flow_daily -- is the panel real?")

df = pd.read_sql_query("SELECT * FROM sector_flow_daily ORDER BY sector_code, date", con)
print(f"rows={len(df):,}  sectors={df.sector_code.nunique()}  "
      f"dates={df.date.nunique():,}  range={df.date.min()} .. {df.date.max()}")

cols = ["close_idx", "return_1d", "net_dollar_flow", "foreign_net", "atr_pct",
        "breadth_sma20", "rs_vnindex_5d", "rs_vnindex_20d", "flow_z20",
        "stealth_score", "accumulation_age"]
print(f"\n{'column':<20}{'null%':>8}{'zero%':>8}{'distinct':>10}{'sql type':>12}")
print("-" * 58)
sqltypes = {r[1]: r[2] for r in con.execute("PRAGMA table_info(sector_flow_daily)")}
for c in cols:
    if c not in df:
        continue
    s = df[c]
    nz = pd.to_numeric(s, errors="coerce")
    print(f"{c:<20}{s.isna().mean()*100:>7.1f}%{(nz == 0).mean()*100:>7.1f}%"
          f"{s.nunique():>10}{sqltypes.get(c, '?'):>12}")

# freshness per sector
last = df.groupby("sector_code")["date"].max()
print(f"\nlatest date per sector: {last.min()} .. {last.max()}"
      + ("  [ALIGNED]" if last.nunique() == 1 else f"  [{last.nunique()} DIFFERENT -- some sectors are stale]"))

# duplicate-value runs = the P0-1 symptom (a stale bar re-stamped as a new day)
hdr("2. Stale-bar detection (review P0-1)")
runs = []
for code, g in df.sort_values("date").groupby("sector_code"):
    v = pd.to_numeric(g["net_dollar_flow"], errors="coerce")
    same = (v.diff() == 0) & v.notna() & (v != 0)
    if same.any():
        # longest consecutive run of identical non-zero flow
        grp = (~same).cumsum()
        longest = same.groupby(grp).sum().max()
        if longest >= 1:
            runs.append((code, int(longest), int(same.sum())))
if runs:
    print(f"{'sector':<10}{'longest repeat run':>20}{'total repeated days':>22}")
    for code, longest, tot in sorted(runs, key=lambda r: -r[1])[:15]:
        print(f"{code:<10}{longest:>20}{tot:>22}")
    print("\nIdentical consecutive net_dollar_flow means the same bar was written twice.")
else:
    print("no repeated consecutive net_dollar_flow values -- clean")

# ------------------------------------------------------- 3. the dtype bug
hdr("3. Why LightGBM never trains (nightly log: 'bad pandas dtypes')")
for c in ("rs_vnindex_5d", "rs_vnindex_20d"):
    s = df[c]
    bad = s[pd.to_numeric(s, errors="coerce").isna() & s.notna()]
    print(f"\n{c}: pandas dtype={s.dtype}  sqlite decl={sqltypes.get(c)!r}")
    print(f"  non-null={s.notna().sum():,}  non-numeric={len(bad):,}")
    kinds = {}
    for v in s.dropna().head(5000):
        kinds[type(v).__name__] = kinds.get(type(v).__name__, 0) + 1
    print(f"  python types present: {kinds}")
    if len(bad):
        print(f"  examples of non-numeric values: {list(dict.fromkeys(map(repr, bad)))[:5]}")

# ------------------------------------------------------- 4. model quality
hdr("4. Ranker quality on the real panel")

from config import ROTATION_TARGET_HORIZON_DAYS  # noqa: E402
from models.rotation_ranker import RotationRanker  # noqa: E402
from services.flow_feature_service import FEATURE_COLS  # noqa: E402

panel = df.copy()
panel["flow_lag_1"] = panel.groupby("sector_code")["net_dollar_flow"].shift(1)
panel["flow_lag_3"] = panel.groupby("sector_code")["net_dollar_flow"].shift(3)
panel["flow_lag_5"] = panel.groupby("sector_code")["net_dollar_flow"].shift(5)
panel["macro_vn_ret_5d"] = 0.0
for c in FEATURE_COLS:
    if c not in panel:
        panel[c] = 0.0

close = pd.to_numeric(panel["close_idx"], errors="coerce")
panel["close_idx"] = close
panel["target"] = (panel.groupby("sector_code")["close_idx"]
                        .shift(-ROTATION_TARGET_HORIZON_DAYS) / panel["close_idx"] - 1)

usable = panel.dropna(subset=["target"])
print(f"rows with a {ROTATION_TARGET_HORIZON_DAYS}d forward target: {len(usable):,} "
      f"({usable.date.nunique():,} dates)")
if usable.empty:
    print("\n*** NO TRAINABLE ROWS -- close_idx is empty, so the target cannot exist. ***")
    con.close()
    sys.exit(0)


def run(label, frame):
    print(f"\n--- {label} ---")
    t0 = time.perf_counter()
    r = RotationRanker()
    try:
        res = r.fit(frame, FEATURE_COLS)
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        return None
    dt = time.perf_counter() - t0
    m = res.metrics
    print(f"  backend            : {m.get('backend')}")
    print(f"  train / test rows  : {res.n_train:,} / {res.n_test:,}")
    print(f"  embargo (purged)   : {m.get('embargo_days')}d, {m.get('purged_dates')} dates dropped")
    print(f"  fit wall-clock     : {dt*1000:,.0f} ms")
    print(f"  top1_excess_hit    : {m.get('top1_excess_hit')!r}   (0.50 = no skill)")
    print(f"  ndcg_at_3          : {m.get('ndcg_at_3')!r}")
    print(f"  decile_monotonic   : {m.get('decile_monotonic')!r}   (+1 = perfectly ordered)")
    qm = m.get("quintile_means")
    if qm:
        print(f"  quintile mean fwd  : {['%+.3f%%' % (v*100) for v in qm]}")
    t1 = time.perf_counter()
    r.predict(frame[FEATURE_COLS].fillna(0).head(15))
    print(f"  predict 15 sectors : {(time.perf_counter()-t1)*1000:,.1f} ms")
    return m


m_asis = run("AS SHIPPED (rs_* left as object dtype)", usable)

fixed = usable.copy()
for c in FEATURE_COLS:
    fixed[c] = pd.to_numeric(fixed[c], errors="coerce").fillna(0.0).astype("float64")
m_fixed = run("WITH rs_* COERCED TO float64", fixed)

hdr("5. Verdict")
if m_asis and m_fixed:
    a, b = m_asis.get("backend"), m_fixed.get("backend")
    print(f"as-shipped backend = {a}")
    print(f"coerced   backend = {b}")
    if a != b:
        print("\n=> One dtype coercion is the whole difference between a real ranker")
        print("   and 'sort the sectors by size'. Fix belongs in FlowFeatureService.")
    for k in ("top1_excess_hit", "ndcg_at_3", "decile_monotonic"):
        print(f"  {k:<18} {m_asis.get(k)!r}  ->  {m_fixed.get(k)!r}")

con.close()
print("\ndone.")
