"""Final comparison table for the write-up: DEV / HOLDOUT / FULL, per year.

Rows marked (post-holdout) were formed AFTER the holdout was read and are
exploratory: their holdout numbers are not out-of-sample.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

LAB = str(Path(__file__).resolve().parent)
OUT = Path(LAB) / "out"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, LAB)
from lab import HOLD_START, bench, simulate_phases, stats  # noqa: E402
from study import PANEL, REGIMES, UNIV, fam, P, vn  # noqa: E402
from holdout import ew_index  # noqa: E402

import scripts.ticker_alpha_bench as tab  # noqa: E402
tab.PANEL_DB = PANEL
from signals import baseline  # noqa: E402

el = UNIV["U75"]
fr = tab.build_features(tab.load_panel())
ship = baseline(fr, el.reindex_like(fr["close"]).fillna(False)).reindex_like(P["close"])

START, END = pd.Timestamp("2019-07-01"), P["close"].index[-1]
PH = list(range(0, 20, 2))

RULES = {
    "A ramom126 top8, no switch": {"score": fam["ramom126"], "el": el},
    "B ramom126 top8, cash switch (DEV pick)": {"score": fam["ramom126"], "el": el, "regime": REGIMES["hyst200_3%"]},
    "C ramom126 top8, no new buys < SMA200 (post-holdout)": {"score": fam["ramom126"], "el": el, "regime": REGIMES["vn>sma200"], "regime_mode": "nobuy"},
    "D shipped rule top5 (SMA200 gate -> blend)": {"score": ship, "el": el, "K": 5, "buffer": 0},
    "E shipped rule top8 buffer 16": {"score": ship, "el": el},
}

daily = {}
for name, kw in RULES.items():
    kw = dict(kw)
    sc, e = kw.pop("score"), kw.pop("el")
    K = kw.pop("K", 8)
    buf = kw.pop("buffer", 8)
    d, cagrs, to, ex = simulate_phases(sc, e, P, K=K, R=20, buffer=buf, phases=PH,
                                       start=START, end=END, **kw)
    daily[name] = d
    print(f"{name:55s} turnover {to:4.1f}/yr  invested {ex*100:3.0f}%")
idx = daily["A ramom126 top8, no switch"].index
daily["VNINDEX"] = bench(vn, idx)
daily["Equal weight U75 (no cost)"] = ew_index(el).reindex(idx).fillna(0)
D = pd.DataFrame(daily)

for label, a, b in (("DEV 2019-07..2025-09", START, pd.Timestamp("2025-09-15")),
                    ("HOLDOUT 2025-09-16..2026-09-28", HOLD_START, END),
                    ("FULL 2019-07..2026-09", START, END)):
    print(f"\n==== {label}")
    for c in D.columns:
        x = D.loc[(D.index >= a) & (D.index <= b), c]
        st = stats(x)
        print(f"  {c:55s} CAGR {st['cagr']*100:6.1f}%  Sharpe {st['sharpe']:5.2f}  "
              f"MaxDD {st['maxdd']*100:6.1f}%")
print("\nper year (%):")
yr = (1 + D).groupby(D.index.year).prod() - 1
print((yr * 100).round(1).T.to_string())
