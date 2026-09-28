"""Walk-forward: does "pick the rule with the best recent backtest" work here?

The single DEV/HOLDOUT split said no for one rule (DEV 34.9%/yr, holdout -21.5%).
This tests the PROCESS instead: every 6 months, choose among a fixed menu the
rule with the best trailing Sharpe, trade it for the next 6 months, repeat.
Nothing after a decision date is used for that decision. A switch pays 1%.
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
from lab import bench, simulate_phases, stats  # noqa: E402
from study import REGIMES, UNIV, fam, P, up, vn  # noqa: E402

START = pd.Timestamp("2019-07-01")
END = P["close"].index[-1]
el = UNIV["U75"]

MENU = {
    "ramom126": (fam["ramom126"], el, "none"),
    "ramom126|hyst": (fam["ramom126"], el, "hyst200_3%"),
    "ramom126|vn>sma200": (fam["ramom126"], el, "vn>sma200"),
    "c_ramom_hi_obv|hyst": (fam["c_ramom_hi_obv"], el, "hyst200_3%"),
    "c_mom_lowvol+G|hyst": (fam["c_mom_lowvol"], el & up, "hyst200_3%"),
    "c_mom_lowvol": (fam["c_mom_lowvol"], el, "none"),
    "mom126_5|hyst": (fam["mom126_5"], el, "hyst200_3%"),
    "c_multi_mom|hyst": (fam["c_multi_mom"], el, "hyst200_3%"),
    "lowvol+G": (fam["lowvol"], el & up, "none"),
    "hi250": (fam["hi250"], el, "none"),
    "trend200+G|hyst": (fam["trend200"], el & up, "hyst200_3%"),
    "mom21_0": (fam["mom21_0"], el, "none"),
    "rev5": (fam["rev5"], el, "none"),
}

series = {}
for name, (sc, e, rn) in MENU.items():
    d, *_ = simulate_phases(sc, e, P, K=8, R=20, buffer=8, regime=REGIMES[rn],
                            phases=[0, 5, 10, 15], start=START, end=END)
    series[name] = d
d, *_ = simulate_phases(el.astype(float), el, P, K=100, R=20, buffer=100, phases=[0],
                        start=START, end=END)
series["ALL(EW)"] = d
S = pd.DataFrame(series)
vnr = bench(vn, S.index)


def sharpe(x):
    return x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else -9


def walk(lookback_months: int | None, metric=sharpe, first="2021-01-01"):
    dates = pd.date_range(first, END, freq="6MS")
    out, picks, prev = [], [], None
    for i, d0 in enumerate(dates):
        d1 = dates[i + 1] if i + 1 < len(dates) else END + pd.Timedelta(days=1)
        lo = START if lookback_months is None else d0 - pd.DateOffset(months=lookback_months)
        hist = S[(S.index >= lo) & (S.index < d0)]
        scores = {c: metric(hist[c]) for c in S.columns}
        best = max(scores, key=scores.get)
        seg = S.loc[(S.index >= d0) & (S.index < d1), best].copy()
        if prev is not None and best != prev and len(seg):
            seg.iloc[0] -= 0.01
        prev = best
        picks.append((d0.date(), best, round(scores[best], 2),
                      round(float((1 + seg).prod() - 1) * 100, 1),
                      round(float((1 + vnr.reindex(seg.index)).prod() - 1) * 100, 1)))
        out.append(seg)
    return pd.concat(out), picks


def line(name, x):
    st = stats(x)
    print(f"{name:32s} CAGR {st['cagr']*100:6.1f}%  Sharpe {st['sharpe']:5.2f}  "
          f"MaxDD {st['maxdd']*100:6.1f}%")


if __name__ == "__main__":
    oos_start = pd.Timestamp("2021-01-01")
    for lb in (12, 24, None):
        r, picks = walk(lb)
        print(f"\n=== walk-forward, trailing {lb or 'all'} months, re-chosen every 6 months")
        for p in picks:
            print("   ", p)
        line("walk-forward OOS", r)
        line("VNINDEX same days", vnr.reindex(r.index))
        line("ALL(EW) same days", S["ALL(EW)"].reindex(r.index))
    print("\n=== each menu item on the same OOS days (2021-01 ..), for reference only")
    for c in S.columns:
        line(c, S.loc[S.index >= oos_start, c])
    print("\nper-year, each menu item vs VNINDEX (%):")
    yr = (1 + S).groupby(S.index.year).prod() - 1
    yr["VNINDEX"] = (1 + vnr).groupby(vnr.index.year).prod() - 1
    print((yr * 100).round(1).T.to_string())
