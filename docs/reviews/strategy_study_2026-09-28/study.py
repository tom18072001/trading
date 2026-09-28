"""The study on the extended panel (2017+ stocks, VNINDEX from 2018-10).

DEV 2019-07-01 .. 2025-09-15 chooses. HOLDOUT 2025-09-16 .. end is read once,
by `holdout.py`, for the rule chosen here -- never by this file.
Every variant run here is counted; the count goes into the report.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

LAB = str(Path(__file__).resolve().parent)
OUT = Path(LAB) / "out"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, LAB)
sys.path.insert(0, str(Path(LAB).parents[2]))
from lab import DEV_END, bench, features, load, simulate_phases, stats, yearly  # noqa: E402
from signals import families  # noqa: E402

PANEL = str(Path(LAB).parents[2] / "data" / "price_panel.db")   # built with --start 2017-01-01
START = pd.Timestamp("2019-07-01")

P, vn = load(PANEL)
f = features(P, vn)
C = P["close"]
liquid = (f["dv20"] >= 5e6) & (f["n_obs"] >= 130) & P["open"].notna()
up = C > f["sma200"]
fam = families(f)

from config import PROXY_BASKETS  # noqa: E402
CONS = sorted({s for v in PROXY_BASKETS.values() for s in v})   # the live 75-name basket
in75 = pd.DataFrame({c: (c in CONS) for c in C.columns}, index=C.index)
UNIV = {"U143": liquid, "U75": liquid & in75}


def hysteresis(on: pd.Series, off: pd.Series) -> pd.Series:
    """True from an `on` day until the next `off` day (state machine)."""
    state, out = True, []
    for a, b in zip(on.fillna(False).values, off.fillna(False).values, strict=True):
        if state and b:
            state = False
        elif not state and a:
            state = True
        out.append(state)
    return pd.Series(out, index=on.index)


vnv, s200, s100 = f["vn"], f["vn_sma200"], f["vn_sma100"]
REGIMES = {
    "none": None,
    "vn>sma200": vnv > s200,
    "vn>sma100": vnv > s100,
    "breadth>0.4": f["breadth50"] > 0.4,
    "hyst200_3%": hysteresis(vnv > s200, vnv < s200 * 0.97),
    "hyst200_5%": hysteresis(vnv > s200, vnv < s200 * 0.95),
    "sma50>sma200": f["vn_sma50"] > s200,
}

rows: list[dict] = []
N_VAR = [0]


def run(name, score, el, K=10, R=20, buffer=None, regime=None, nph=5, start=START, end=DEV_END,
        tag=""):
    N_VAR[0] += 1
    buffer = K if buffer is None else buffer
    ph = sorted({int(round(x)) for x in np.linspace(0, R - 1, nph)})
    daily, cagrs, to, ex = simulate_phases(score, el, P, K=K, R=R, buffer=buffer, phases=ph,
                                           regime=regime, start=start, end=end)
    st = stats(daily)
    b = stats(bench(vn, daily.index))
    yr = yearly(daily)
    row = dict(name=name, tag=tag, K=K, R=R, buf=buffer,
               **{k: round(v, 4) for k, v in st.items()},
               vn_cagr=round(b["cagr"], 4), excess=round(st["cagr"] - b["cagr"], 4),
               ph_min=round(float(cagrs.min()), 3), ph_max=round(float(cagrs.max()), 3),
               turnover=round(to, 2), expo=round(ex, 2),
               **{f"y{y}": round(v, 3) for y, v in yr.items()})
    rows.append(row)
    return row, daily


def show(df, cols=None, n=60, by="sharpe"):
    pd.set_option("display.width", 280)
    pd.set_option("display.max_rows", 400)
    pd.set_option("display.max_columns", 40)
    cols = cols or [c for c in df.columns if c != "tag"]
    print(df.sort_values(by, ascending=False)[cols].head(n).to_string(index=False))


if __name__ == "__main__":
    t0 = time.time()
    stage = sys.argv[1] if len(sys.argv) > 1 else "a"
    if stage == "a":
        # references + every family, K10 R20 bufK, no regime, both universes, gate on/off
        for un, el in UNIV.items():
            run(f"ALL {un}", el.astype(float), el, K=100, R=20, buffer=100, tag="ref")
            for sname, sc in fam.items():
                for gate in (False, True):
                    e2 = el & up if gate else el
                    run(f"{sname}{'+G' if gate else ''} {un}", sc, e2, tag="a")
    elif stage == "b":
        sigs = sys.argv[2].split(",")
        for un in ("U143", "U75"):
            el = UNIV[un]
            for sname in sigs:
                gate = sname.endswith("+G")
                base = sname[:-2] if gate else sname
                e2 = el & up if gate else el
                for rn, reg in REGIMES.items():
                    run(f"{sname} {un} | {rn}", fam[base], e2, regime=reg, tag="b")
            run(f"ALL {un}", el.astype(float), el, K=100, R=20, buffer=100, tag="ref")
            for rn in ("vn>sma200", "hyst200_5%"):
                run(f"ALL {un} | {rn}", el.astype(float), el, K=100, R=20, buffer=100,
                    regime=REGIMES[rn], tag="ref")
    elif stage == "c":
        cands = [("c_ramom_hi_obv", False, "U75", "hyst200_3%"),
                 ("ramom126", False, "U75", "hyst200_3%"),
                 ("c_mom_lowvol", True, "U75", "hyst200_3%")]
        for sname, gate, un, rn in cands:
            el = UNIV[un] & up if gate else UNIV[un]
            for K in (5, 8, 10, 15):
                for R in (20, 40):
                    for buf in sorted({0, K // 2, K}):
                        run(f"{sname}{'+G' if gate else ''} {un} | {rn}", fam[sname], el,
                            K=K, R=R, buffer=buf, regime=REGIMES[rn], tag="c")
    df = pd.DataFrame(rows)
    print(f"DEV {START.date()} .. {DEV_END.date()}  stage {stage}: {N_VAR[0]} variants "
          f"({time.time()-t0:.0f}s)")
    show(df)
    json.dump(rows, open(OUT / f"study_{stage}.json", "w"), default=float)
