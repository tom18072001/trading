"""Variants on the SHIPPED rule: execution timing, horizon, market filter,
idle-cash policy, exit rule. All paired against the same picks."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

import json
import sys


import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from picks_eval import (MIN_BUY_SCORE, MIN_DV, TOTAL_COST, constituents,  # noqa: E402
                        jt_portfolio, load_all, nw_t, perf, production_rank,
                        production_score, topk, vn_daily)

START = "2023-01-01"
p, f, vn = load_all()
sc = production_score(f)
elig = (f["dv20"] > MIN_DV) & f["sma50"].notna()
rk = production_rank(sc, f["obv_chg20"], elig)
ship = topk(rk.where((sc >= MIN_BUY_SCORE) & elig), 5, tiebreak=sc)
O, C = p["open"], p["close"]
res = {}

# ---------------------------------------------------------------- 1. timing
print("=" * 100)
print("1. EXECUTION TIMING on the shipped top-5 (paired, same picks). Per trade, net of 1.00%.")
rows = []
for h in (20, 40):
    variants = {
        "buy ATO t+1 / sell ATC exit (bench)": C.shift(-(1 + h)) / O.shift(-1),
        "buy ATC t+1 / sell ATC exit": C.shift(-(1 + h)) / C.shift(-1),
        "buy ATO t+1 / sell ATO exit-day": O.shift(-(1 + h)) / O.shift(-1),
        "buy ATC t+1 / sell ATO exit-day": O.shift(-(1 + h)) / C.shift(-1),
        "buy ATC t (needs 14:25 score) / sell ATC exit": C.shift(-(1 + h)) / C,
    }
    base = None
    for name, gross in variants.items():
        r = (gross - 1 - TOTAL_COST).where(ship & elig)
        s = r.mean(axis=1)
        s = s[s.index >= pd.Timestamp(START)].dropna()
        if base is None:
            base = s
        d = (s - base.reindex(s.index))
        by = d.groupby(d.index.year).mean() * 100
        rows.append({"h": h, "variant": name, "net_per_trade%": round(s.mean() * 100, 3),
                     "vs_bench_pp": round(d.mean() * 100, 3), "NW_t": round(nw_t(d, h), 2),
                     "by_year_pp": {int(y): round(v, 3) for y, v in by.items()}})
tdf = pd.DataFrame(rows)
print(tdf.to_string())
res["timing"] = rows

# ------------------------------------------------------------ 2. horizon ---
print("=" * 100)
print("2. HORIZON SWEEP, staggered portfolio from", START, "(cash when no pick)")
vnr = vn_daily(vn)
res["vn"] = perf(vnr, start=START)
print(f"{'VNINDEX buy&hold':38s} CAGR {res['vn']['cagr']*100:6.1f}%  Sharpe {res['vn']['sharpe']:5.2f}  "
      f"MaxDD {res['vn']['maxdd']*100:6.1f}%  {res['vn']['by_year']}")
res["horizon"] = {}
for h in (10, 20, 30, 40, 60, 80, 120):
    for name, sel in (("shipped top5", ship & elig), ("NO GATE all liquid", elig)):
        r = jt_portfolio(sel, p, vn, h)
        pf = perf(r, start=START)
        res["horizon"][f"{name} h{h}"] = pf
        print(f"{name + ' h=' + str(h):38s} CAGR {pf['cagr']*100:6.1f}%  Sharpe {pf['sharpe']:5.2f}  "
              f"MaxDD {pf['maxdd']*100:6.1f}%  {pf['by_year']}")

# ------------------------------------------- 3. market filter + idle policy -
print("=" * 100)
print("3. MARKET FILTER and IDLE-CASH POLICY (shipped top5)")
vn_up = vn["close"] > vn["close"].rolling(200).mean()
breadth = ((f["close"] > f["sma200"]) & elig).sum(axis=1) / elig.sum(axis=1)
filters = {
    "no filter": pd.Series(True, index=vn.index),
    "VNINDEX > SMA200": vn_up,
    "breadth >= 50% above SMA200": breadth >= 0.5,
}


def jt_fill_index(sel, h, fill=True, cost=TOTAL_COST):
    """Tranche buys the picks; if fewer than 5, the rest of the tranche buys
    VNINDEX (an ETF) at the same open and holds it the same h sessions."""
    Ov, Cv = O.values, C.values
    VO, VC = vn["open"].values, vn["close"].values
    S = sel.values
    T = len(C)
    acc = np.zeros(T)
    for t in range(T - 1):
        i0, i1 = t + 1, min(t + 1 + h, T - 1)
        js = np.flatnonzero(S[t])
        paths, w = [], []
        for j in js:
            e = Ov[i0, j]
            if np.isfinite(e) and e > 0:
                pth = pd.Series(Cv[i0:i1 + 1, j] / e).ffill().fillna(1.0).values
                paths.append(pth)
                w.append(1.0)
        n_pick = len(paths)
        if fill and n_pick < 5:
            paths.append(VC[i0:i1 + 1] / VO[i0])
            w.append(5.0 - n_pick)
        if not paths:
            continue
        w = np.array(w) / np.sum(w)
        v = (np.vstack(paths) * w[:, None]).sum(axis=0)
        prev = np.concatenate([[1.0], v[:-1]])
        r = v / prev - 1.0
        r[0] -= cost
        acc[i0:i0 + len(r)] += r / (h + 1)
    return pd.Series(acc, index=C.index)


res["filter"] = {}
for h in (20, 40):
    for fname, flt in filters.items():
        sel = ship & elig & flt.reindex(C.index).fillna(False).values[:, None]
        for fill in (False, True):
            r = jt_fill_index(sel, h, fill=fill)
            pf = perf(r, start=START)
            key = f"h{h} | {fname} | idle->{'VNINDEX' if fill else 'cash'}"
            res["filter"][key] = pf
            print(f"{key:58s} CAGR {pf['cagr']*100:6.1f}%  Sharpe {pf['sharpe']:5.2f}  "
                  f"MaxDD {pf['maxdd']*100:6.1f}%  {pf['by_year']}")

# ---------------------------------------------------------- 4. exit rules --
print("=" * 100)
print("4. EXIT RULES as production runs them (close-based alert, sell next ATO)")
atr_now = (f["atr_pct"] / 100.0).values


def make_giveback(k_atr, arm_atr=1.0):
    def rule(j, i0, i_now, closes, entry, _f):
        # closes = C[i0 .. i_now]; peak over PRIOR closes (sell_range excludes today)
        if len(closes) < 2:
            return False
        a = atr_now[i_now, j]
        if not np.isfinite(a) or a <= 0:
            return False
        peak = np.nanmax(closes[:-1])
        if peak < entry * (1 + arm_atr * a):
            return False
        return closes[-1] <= peak * (1 - k_atr * a)
    return rule


res["exit"] = {}
for h in (20, 40):
    for ename, er in (("time exit (hold full window)", None),
                      ("give_back 3.5xATR (shipped alert)", make_giveback(3.5)),
                      ("give_back 2.5xATR", make_giveback(2.5))):
        for park in ("cash", "vnindex"):
            if er is None and park == "vnindex":
                continue
            r = jt_portfolio(ship & elig, p, vn, h, exit_rule=er, park=park)
            pf = perf(r, start=START)
            key = f"h{h} | {ename} | freed->{park}"
            res["exit"][key] = pf
            print(f"{key:62s} CAGR {pf['cagr']*100:6.1f}%  Sharpe {pf['sharpe']:5.2f}  "
                  f"MaxDD {pf['maxdd']*100:6.1f}%  {pf['by_year']}")

json.dump(res, open(OUT / "variants_results.json", "w"), indent=1, default=float)
