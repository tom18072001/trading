"""HOLDOUT -- run once, for the rule chosen on DEV. Do not tune after reading this.

Chosen on DEV 2019-07-01 .. 2025-09-15 (see robust.py), fixed before this file ran:
    ramom126, U75, hysteresis VNINDEX/SMA200 (in > SMA200, out < 97% SMA200),
    K=8, review every 20 sessions, keep while ranked <= 16.
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
from lab import HOLD_START, bench, simulate_phases, stats  # noqa: E402
from study import REGIMES, UNIV, fam, P, vn  # noqa: E402

SIG, UN, REG, K, R, BUF = "ramom126", "U75", "hyst200_3%", 8, 20, 8
el = UNIV[UN]
END = P["close"].index[-1]


def ew_index(el: pd.DataFrame) -> pd.Series:
    """Equal weight over the names eligible at t-1, rebalanced daily, no costs."""
    r = P["close"].pct_change(fill_method=None)
    w = el.shift(1).fillna(False) & r.notna()
    return r.where(w).mean(axis=1).fillna(0.0)


def line(name, daily):
    st = stats(daily)
    tot = (1 + daily).prod() - 1
    print(f"{name:34s} total {tot*100:7.1f}%  CAGR {st['cagr']*100:6.1f}%  Sharpe {st['sharpe']:5.2f}  "
          f"MaxDD {st['maxdd']*100:6.1f}%  vol {st['vol']*100:5.1f}%")


for label, a, b in (("DEV", pd.Timestamp("2019-07-01"), pd.Timestamp("2025-09-15")),
                    ("HOLDOUT", HOLD_START, END)):
    print(f"\n==== {label} {a.date()} .. {b.date()}")
    daily, cagrs, to, ex = simulate_phases(fam[SIG], el, P, K=K, R=R, buffer=BUF,
                                           regime=REGIMES[REG], start=a, end=b)
    line("CHOSEN (mean of 20 phases)", daily)
    print(f"{'':34s} phase CAGR min {cagrs.min()*100:.1f}%  median {np.median(cagrs)*100:.1f}%  "
          f"max {cagrs.max()*100:.1f}%   turnover {to:.1f}/yr  invested {ex*100:.0f}%")
    idx = daily.index
    line("VNINDEX buy & hold", bench(vn, idx))
    line("Equal weight U75 (no cost)", ew_index(el).reindex(idx).fillna(0))
    line("Equal weight U143 (no cost)", ew_index(UNIV["U143"]).reindex(idx).fillna(0))
    d2, c2, _, _ = simulate_phases(fam[SIG], el, P, K=K, R=R, buffer=BUF, start=a, end=b)
    line("same rule, no regime filter", d2)
    ex_d = daily - bench(vn, idx)
    ir = ex_d.mean() / ex_d.std() * np.sqrt(252)
    print(f"{'':34s} information ratio vs VNINDEX {ir:.2f}")
    if label == "HOLDOUT":
        print("monthly, CHOSEN vs VNINDEX:")
        m = pd.DataFrame({"chosen": (1 + daily).groupby(idx.to_period("M")).prod() - 1,
                          "vnindex": (1 + bench(vn, idx)).groupby(idx.to_period("M")).prod() - 1})
        print((m * 100).round(1).T.to_string())
        reg = REGIMES[REG].reindex(idx)
        print("regime ON share in holdout:", round(float(reg.mean()), 2))
