"""Core comparison: shipped picks vs bench twin vs base rates vs VNINDEX."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

import json
import sys


import pandas as pd  # noqa: E402

from picks_eval import (FACTORS, MIN_BUY_SCORE, MIN_DV, constituents, jt_portfolio,  # noqa: E402
                        load_all, per_trade, perf, production_rank, production_score,
                        summarize_trades, topk, vn_daily)

START = "2023-01-01"
p, f, vn = load_all()
sc = production_score(f)
elig143 = (f["dv20"] > MIN_DV) & f["sma50"].notna()
cons = [c for c in constituents() if c in f["close"].columns]
elig75 = elig143 & pd.DataFrame({c: (c in cons) for c in f["close"].columns},
                                index=f["close"].index)

rules = {}
# bench twin (what the doctrine measured)
xpo = FACTORS["X_prop_obv"](f)
rules["bench_X_prop_obv_top5"] = (topk(xpo.where(elig143), 5), elig143)
# production-faithful on the 143-name panel and on the 75 constituents
for tag, el in (("U143", elig143), ("U75", elig75)):
    rk = production_rank(sc, f["obv_chg20"], el)
    gated = rk.where((sc >= MIN_BUY_SCORE) & el)
    rules[f"shipped_{tag}_top5"] = (topk(gated, 5, tiebreak=sc), el)
    rules[f"shipped_{tag}_top10"] = (topk(gated, 10, tiebreak=sc), el)
    rules[f"gate_only_{tag}_all"] = (((sc >= MIN_BUY_SCORE) & el), el)
# score alone (P2 ordering), no gate threshold
p2 = FACTORS["P2_proposed_gated_quiet"](f)
rules["P2_top5"] = (topk(p2.where(elig143), 5), elig143)

out = {"trades": [], "portfolio": {}}
for h in (20, 40):
    for name, (sel, el) in rules.items():
        df = per_trade(sel, p, f, vn, h, elig=el, start=START)
        out["trades"].append(summarize_trades(df, h, name))
    # portfolios
    vnr = vn_daily(vn)
    out["portfolio"][f"VNINDEX_h{h}"] = perf(vnr, start=START)
    for name in ("bench_X_prop_obv_top5", "shipped_U143_top5", "shipped_U75_top5",
                 "shipped_U143_top10", "P2_top5"):
        sel, el = rules[name]
        r = jt_portfolio(sel & el, p, vn, h)
        out["portfolio"][f"{name}_h{h}"] = perf(r, start=START)
    # NO GATE: every eligible name, same turnover and cost (expected value of random picks)
    r0 = jt_portfolio(elig143, p, vn, h)
    out["portfolio"][f"NOGATE_all_U143_h{h}"] = perf(r0, start=START)
    r0g = jt_portfolio(elig143 & (f["close"] > f["sma200"]), p, vn, h)
    out["portfolio"][f"NOGATE_uptrend_U143_h{h}"] = perf(r0g, start=START)

json.dump(out, open(OUT / "core_results.json", "w"), indent=1, default=float)
tr = pd.DataFrame(out["trades"])
pd.set_option("display.width", 250)
cols = ["rule", "h", "days", "days_with_picks_frac", "pick", "net", "ex_base", "t_base", "tno_base",
        "ex_base_gated", "t_base_gated", "ex_vn", "t_vn", "tno_vn"]
print(tr[cols].round(4).to_string())
for _, r in tr.iterrows():
    print(r["rule"], r["h"], "yr_base", r["yr_base"], "yr_vn", r["yr_vn"], "yr_gated", r["yr_base_gated"])
for k, v in out["portfolio"].items():
    print(f"{k:34s} CAGR {v['cagr']*100:6.1f}%  vol {v['vol']*100:5.1f}%  Sharpe {v['sharpe']:5.2f}  "
          f"MaxDD {v['maxdd']*100:6.1f}%  {v['by_year']}")
