import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)


import numpy as np, pandas as pd
from picks_eval import *
p, f, vn = load_all()
elig = (f["dv20"] > MIN_DV) & f["sma50"].notna()
xpo = FACTORS["X_prop_obv"](f)
sel = topk(xpo.where(elig), 5)
sc = production_score(f); rk = production_rank(sc, f["obv_chg20"], elig)
ship = topk(rk.where((sc >= MIN_BUY_SCORE) & elig), 5, tiebreak=sc)
gated_n = (xpo.notna() & elig).sum(axis=1)
for h in (20, 40):
    df = per_trade(sel, p, f, vn, h, elig=elig, start="2023-01-01").dropna(subset=["pick"])
    keep = gated_n.reindex(df.index) >= 30          # the bench's day filter
    rows = {}
    for lab, d in (("bench days (>=30 gated names)", df[keep]), ("skipped days", df[~keep]), ("all days", df)):
        rows[lab] = {"days": len(d),
                     "ex_vs_gated_base": round((d.pick - d.base_gated).mean()*100, 2),
                     "ex_vs_NOGATE": round((d.pick - d.base).mean()*100, 2),
                     "NOGATE_base_mean": round(d.base.mean()*100, 2),
                     "VN_mean": round(d.vn.mean()*100, 2),
                     "2023_vs_gated": round((d.pick - d.base_gated)[d.index.year == 2023].mean()*100, 2),
                     "2023_vs_NOGATE": round((d.pick - d.base)[d.index.year == 2023].mean()*100, 2)}
    print(f"h={h}"); print(pd.DataFrame(rows).T.to_string())
    # MIN_BUY_SCORE effect: shipped vs bench twin, paired
    a = per_trade(ship, p, f, vn, h, elig=elig, start="2023-01-01")["pick"]
    b = df["pick"]
    d = (a - b).dropna()
    print(f"  shipped - bench twin: {d.mean()*100:+.3f}%/trade  NW t {nw_t(d, h):+.2f}  by year",
          (d.groupby(d.index.year).mean()*100).round(2).to_dict())
