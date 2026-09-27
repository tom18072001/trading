import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)


import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from picks_eval import (MIN_BUY_SCORE, MIN_DV, TOTAL_COST, UNTRENDED_FLOOR,  # noqa: E402
    jt_portfolio, load_all, nw_t, per_trade, perf, production_rank, production_score,
    topk, vn_daily)  # noqa: E402
p, f, vn = load_all()
elig = (f["dv20"] > MIN_DV) & f["sma50"].notna()
sc = production_score(f).round(2)
rk = production_rank(sc, f["obv_chg20"], elig).round(4)
up = sc > UNTRENDED_FLOOR                       # SMA200 gate only
ship = topk(rk.where((sc >= MIN_BUY_SCORE) & elig), 5, tiebreak=sc)
gate_only = topk(rk.where(up & elig), 5, tiebreak=sc)
FIRST = pd.Timestamp("2022-10-24")               # first day the shipped rule can pick
O, C = p["open"], p["close"]  # noqa: E741

def jt_empty_to_index(sel, h, cost=TOTAL_COST):
    """1/n across available picks; a tranche with NO pick buys VNINDEX (same cost)."""
    Ov, Cv, S = O.values, C.values, sel.values
    VO, VC = vn["open"].values, vn["close"].values
    T = len(C); acc = np.zeros(T)
    for t in range(T - 1):
        if C.index[t] < FIRST:
            continue
        i0, i1 = t + 1, min(t + 1 + h, T - 1)
        paths = []
        for j in np.flatnonzero(S[t]):
            e = Ov[i0, j]
            if np.isfinite(e) and e > 0:
                paths.append(pd.Series(Cv[i0:i1 + 1, j] / e).ffill().fillna(1.0).values)
        if not paths:
            paths = [VC[i0:i1 + 1] / VO[i0]]
        v = np.mean(np.vstack(paths), axis=0)
        r = v / np.concatenate([[1.0], v[:-1]]) - 1.0
        r[0] -= cost
        acc[i0:i0 + len(r)] += r / (h + 1)
    return pd.Series(acc, index=C.index)

def jt_from(sel, h):
    s = sel.copy(); s.loc[s.index < FIRST] = False
    return jt_portfolio(s & elig, p, vn, h)

print("A. rule comparison (per trade vs NO GATE from 2023, NW t)")
for h in (20, 40):
    for lab, s in (("shipped (score>=2.5)", ship), ("SMA200 gate only, no 2.5 cutoff", gate_only)):
        x = per_trade(s, p, f, vn, h, elig=elig, start="2023-01-01"); e = (x.pick - x.base).dropna()
        print(f"  h={h} {lab:32s} {e.mean()*100:+.2f}%  t {nw_t(e,h):+.2f}  yrs", (e.groupby(e.index.year).mean()*100).round(2).to_dict())
print("B. horizon sweep, both rules start tranches 2022-10-24; CAGR measured from 2023-01-01 | from 2023-07-01 (fully ramped)")
vnr = vn_daily(vn)
print(f"  VNINDEX: {perf(vnr, start='2023-01-01')['cagr']*100:.1f}% | {perf(vnr, start='2023-07-01')['cagr']*100:.1f}%")
for h in (10, 20, 30, 40, 60, 80, 120):
    cells = []
    for lab, s in (("ship", ship), ("gate-only", gate_only), ("NOGATE", elig)):
        r = jt_from(s, h)
        cells.append(f"{lab} {perf(r, start='2023-01-01')['cagr']*100:5.1f}|{perf(r, start='2023-07-01')['cagr']*100:5.1f}")
    print(f"  h={h:3d}  " + "   ".join(cells))
print("C. empty tranche -> VNINDEX (1/n sizing across available picks), from 2023-01-01")
for h in (20, 40):
    for lab, s in (("ship", ship), ("gate-only", gate_only)):
        r0 = jt_from(s, h); r1 = jt_empty_to_index(s & elig, h)
        a, b = perf(r0, start="2023-01-01"), perf(r1, start="2023-01-01")
        print(f"  h={h} {lab:10s} cash: {a['cagr']*100:5.1f}% Sh {a['sharpe']:.2f} DD {a['maxdd']*100:.1f}% {a['by_year']}")
        print(f"  h={h} {lab:10s} idx : {b['cagr']*100:5.1f}% Sh {b['sharpe']:.2f} DD {b['maxdd']*100:.1f}% {b['by_year']}")
