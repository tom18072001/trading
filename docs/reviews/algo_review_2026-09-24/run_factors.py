"""Old verdict method (repo bench) vs corrected method, same factors, same data."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

import json  # noqa: E402
import sys  # noqa: E402


import pandas as pd  # noqa: E402

from picks_eval import (FACTORS, MIN_BUY_SCORE, MIN_DV, jt_portfolio, load_all, nw_t,  # noqa: E402
                        per_trade, perf, production_rank, production_score, topk)

START = "2023-01-01"
p, f, vn = load_all()
elig = (f["dv20"] > MIN_DV) & f["sma50"].notna()
sc = production_score(f)
rk = production_rank(sc, f["obv_chg20"], elig)

sel = {
    "SHIPPED (score>=2.5, blend rank)": topk(rk.where((sc >= MIN_BUY_SCORE) & elig), 5, tiebreak=sc),
}
for n in ("X_prop_obv", "P2_proposed_gated_quiet", "V_obv_trend", "S_small_size",
          "M_ivol_low", "Y_shipped_plus_small", "X_prop_small_obv", "C_rsi2_above200"):
    sel[n] = topk(FACTORS[n](f).where(elig), 5)

_old = HERE.parents[2] / "data" / "bench_all_h20_40.json"   # from: scripts/ticker_alpha_bench.py --horizons 20,40 --verdict --json data/bench_all_h20_40.json
old = json.load(open(_old))["factors"] if _old.exists() else {}
rows = []
for h in (20, 40):
    for name, s in sel.items():
        df = per_trade(s, p, f, vn, h, elig=elig, start=START).dropna(subset=["pick"])
        e = df["pick"] - df["base"]
        ev = df["pick"] - df["vn"]
        by = (e.groupby(e.index.year).mean() * 100).round(2)
        # paired difference vs the shipped rule on common days
        r = jt_portfolio(s & elig, p, vn, h)
        pf = perf(r, start=START)
        o = old.get(name, {}).get("horizons", {}).get(str(h))
        rows.append({
            "h": h, "rule": name,
            "OLD excess (own base)": None if o is None else round(o["excess"] * 100, 2),
            "OLD by-year": None if o is None else {k: round(v * 100, 2) for k, v in o["by_year"].items()},
            "OLD IC t": None if o is None else round(o["ic_t"], 2),
            "OLD verdict": None if o is None else o["verdict"],
            "NEW excess vs NO-GATE": round(e.mean() * 100, 2),
            "NEW NW t": round(nw_t(e, h), 2),
            "NEW by-year": {int(k): v for k, v in by.items()},
            "NEW all years +": bool((by > 0).all()),
            "vs VNINDEX gross": round(ev.mean() * 100, 2),
            "vs VNINDEX NW t": round(nw_t(ev, h), 2),
            "JT CAGR": round(pf["cagr"] * 100, 1), "JT Sharpe": round(pf["sharpe"], 2),
            "JT MaxDD": round(pf["maxdd"] * 100, 1),
        })
out = pd.DataFrame(rows)
pd.set_option("display.width", 320)
pd.set_option("display.max_colwidth", 60)
print(out.to_string())
out.to_json(OUT / "factors_old_vs_new.json", orient="records", indent=1)
