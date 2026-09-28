"""Robustness of the DEV choice, still on DEV only (holdout untouched).

Chosen on DEV (stage c plateau, simplest signal):
    ramom126 (6-month return skipping 5 sessions / 126-day volatility)
    universe U75 (the live basket constituents, 5 bn VND/day liquidity)
    regime: VNINDEX > SMA200 to enter, < 97% of SMA200 to leave (hysteresis)
    K=8 names, review every R=20 sessions, keep a holding while it ranks <= 16
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

LAB = str(Path(__file__).resolve().parent)
OUT = Path(LAB) / "out"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, LAB)
import lab  # noqa: E402
from study import REGIMES, UNIV, fam, P, run, rows, show, N_VAR  # noqa: E402

SIG, UN, REG, K, R, BUF = "ramom126", "U75", "hyst200_3%", 8, 20, 8
el = UNIV[UN]

print("== chosen and references (DEV)")
run("CHOSEN", fam[SIG], el, K=K, R=R, buffer=BUF, regime=REGIMES[REG], nph=20)
run("CHOSEN R40", fam[SIG], el, K=K, R=40, buffer=BUF, regime=REGIMES[REG], nph=20)
run("same, no regime", fam[SIG], el, K=K, R=R, buffer=BUF, nph=20)
run("ALL U75", el.astype(float), el, K=100, R=20, buffer=100)
run("ALL U75 | same regime", el.astype(float), el, K=100, R=20, buffer=100, regime=REGIMES[REG])

# execution one day late: shift the score and regime by one session
run("CHOSEN, trade 1 day late", fam[SIG].shift(1), el.shift(1).fillna(False), K=K, R=R,
    buffer=BUF, regime=REGIMES[REG].shift(1).fillna(False), nph=20)

# costs doubled (slippage 0.6%/side)
lab.BUY_COST, lab.SELL_COST = 0.0015 + 0.006, 0.0015 + 0.006 + 0.001
run("CHOSEN, slippage x2", fam[SIG], el, K=K, R=R, buffer=BUF, regime=REGIMES[REG], nph=20)
lab.BUY_COST, lab.SELL_COST = 0.0015 + 0.003, 0.0015 + 0.003 + 0.001

# sub-periods
for a, b in (("2019-07-01", "2021-12-31"), ("2022-01-01", "2025-09-15"),
             ("2022-01-01", "2023-12-31"), ("2024-01-01", "2025-09-15")):
    run(f"CHOSEN {a[:4]}-{b[:4]}", fam[SIG], el, K=K, R=R, buffer=BUF, regime=REGIMES[REG],
        start=pd.Timestamp(a), end=pd.Timestamp(b), nph=20)
    run(f"ALL U75 {a[:4]}-{b[:4]}", el.astype(float), el, K=100, R=20, buffer=100,
        start=pd.Timestamp(a), end=pd.Timestamp(b))

# neighbours of the signal: lookback / skip
for L_, S_ in ((63, 5), (126, 0), (126, 21), (189, 5), (250, 21)):
    c = P["close"]
    m = c.shift(S_) / c.shift(L_) - 1
    v = c.pct_change(fill_method=None).rolling(L_, min_periods=int(L_ * 0.6)).std()
    run(f"ramom{L_}_{S_}", m / v, el, K=K, R=R, buffer=BUF, regime=REGIMES[REG])

df = pd.DataFrame(rows)
show(df, n=80, by="name")
print("variants in this file:", N_VAR[0])
