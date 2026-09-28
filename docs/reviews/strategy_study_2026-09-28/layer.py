"""Numbers for the buy layer, for the rule as it will ship (ramom126, U75, top 8,
no regime switch): per-pick outcome distributions at 4 and 8 weeks, and how
much of it survives paying above the signal close (-> the accept range).

Pick = a name in the top 8 at close t. Entry = open t+1 (or a premium over
close t). Exit = close t+20 / t+40. Costs: 1.0% round trip (bench model).
All signal days 2019-07-01 .. end (overlapping windows: counts are not
independent observations -- percentiles are fine, t-stats would not be).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = str(Path(__file__).resolve().parent)
OUT = Path(LAB) / "out"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, LAB)
from study import UNIV, fam, f, P, vn  # noqa: E402

RT = 0.010
el = UNIV["U75"]
sc = fam["ramom126"].where(el)
rank = sc.rank(axis=1, ascending=False, method="first")
top = (rank <= 8) & sc.notna()
O, C = P["open"], P["close"]  # noqa: E741
vol = f["vol63"]
vn_up = f["vn"] > f["vn_sma200"]
dates = C.index
start = dates.searchsorted(pd.Timestamp("2019-07-01"))

recs = []
for h in (20, 40):
    for i in range(start, len(dates) - 1 - h):
        t = dates[i]
        syms = top.columns[top.iloc[i].values]
        if len(syms) == 0:
            continue
        o1 = O.iloc[i + 1][syms]
        ex = C.iloc[i + 1 + h][syms] if i + 1 + h < len(dates) else None
        c0 = C.iloc[i][syms]
        vn_r = vn.iloc[i + 1 + h] / vn.iloc[i] - 1
        # universe mean over the same window (no-skill base), from close t
        uni = C.iloc[i + 1 + h][el.iloc[i]] / C.iloc[i][el.iloc[i]] - 1
        for s in syms:
            if not (np.isfinite(o1[s]) and np.isfinite(ex[s]) and o1[s] > 0):
                continue
            recs.append({"h": h, "t": t, "sym": s,
                         "gap": o1[s] / c0[s] - 1,              # next open vs signal close
                         "r_close": ex[s] / c0[s] - 1,          # if bought AT the signal close
                         "r_open": ex[s] / o1[s] - 1 - RT,      # bought next open, net of cost
                         "vn": vn_r, "base": float(uni.mean()),
                         "vol": vol.iloc[i][s], "vn_up": bool(vn_up.iloc[i]),
                         "rank": int(rank.iloc[i][s])})
D = pd.DataFrame(recs)
D.to_pickle(OUT / "layer_picks.pkl")


def q(x):
    return pd.Series({"n": len(x), "median": x.median(), "mean": x.mean(),
                      "p25": x.quantile(.25), "p75": x.quantile(.75),
                      "p10": x.quantile(.10), "p90": x.quantile(.90),
                      "win": (x > 0).mean()})


for h in (20, 40):
    d = D[D.h == h]
    print(f"\n===== h={h} sessions  ({d.t.min().date()} .. {d.t.max().date()})")
    print("net return, bought next open:")
    print((q(d.r_open) * [1, 100, 100, 100, 100, 100, 100, 100]).round(2).to_string())
    print(f"  beat VNINDEX same window: {(d.r_open > d.vn).mean():.2f}   "
          f"beat universe mean: {(d.r_open > d.base).mean():.2f}")
    print(f"  mean excess vs VNINDEX {100*(d.r_open - d.vn).mean():.2f}%  "
          f"vs universe {100*(d.r_open - d.base).mean():.2f}%")
    # by year
    print("  by year (median net / mean excess vs universe):")
    g = d.groupby(d.t.dt.year)
    print(pd.DataFrame({"median": g.r_open.median() * 100,
                        "mean_ex_uni": g.apply(lambda x: (x.r_open - x.base).mean()) * 100,
                        "win": g.r_open.apply(lambda x: (x > 0).mean())}).round(2).T.to_string())
    # by regime
    for up_ in (True, False):
        x = d[d.vn_up == up_]
        print(f"  VNINDEX {'above' if up_ else 'below'} SMA200 at signal: n={len(x)}  "
              f"median {100*x.r_open.median():.2f}%  mean {100*x.r_open.mean():.2f}%  "
              f"win {100*(x.r_open>0).mean():.0f}%  excess vs uni {100*(x.r_open-x.base).mean():.2f}%")
    # by vol tercile: dispersion scales with the name's own volatility
    d = d.assign(vt=pd.qcut(d.vol, 3, labels=["low", "mid", "high"]))
    print("  by own 63d volatility tercile:")
    print(d.groupby("vt", observed=True).r_open.apply(
        lambda x: f"n={len(x)} p25 {100*x.quantile(.25):.1f}% med {100*x.median():.1f}% "
                  f"p75 {100*x.quantile(.75):.1f}% win {100*(x>0).mean():.0f}%").to_string())
    # entry premium: return if paying (1+x) x signal close, excess vs universe
    print("  paying x above the signal close (mean excess vs universe, net):")
    for x in (-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03, 0.05):
        r = (1 + d.r_close) / (1 + x) - 1 - RT
        print(f"     x={x:+.0%}: mean {100*r.mean():6.2f}%  excess {100*(r-d.base).mean():6.2f}%  "
              f"median {100*r.median():6.2f}%")
    # does the next-day gap itself predict the outcome (from next open)?
    d = d.assign(gb=pd.cut(d.gap, [-1, -0.02, -0.005, 0.005, 0.02, 1]))
    print("  outcome from next open by the overnight gap:")
    print(d.groupby("gb", observed=True).apply(
        lambda x: pd.Series({"n": len(x), "mean_net": 100 * x.r_open.mean(),
                             "ex_uni": 100 * (x.r_open - x.base).mean()})).round(2).to_string())
