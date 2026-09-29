"""Descriptive follow-up to priority.py (2026-09-29): do the four within-top-8
signals carry separate information, or is it one "trend strength" signal?

Daily cross-sectional regression inside the top 8 (Fama-MacBeth), DEV only:
    excess_i = a + b1*z(-rank) + b2*z(ret5) + b3*established + b4*z(hi250)
z() is the within-day standardisation across the 8 names. The coefficient
series gets a Newey-West t with lag h. Not a selection step: it decides how
the one pre-registered signal that passed (P3) is presented, not whether.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from priority import DEV_END, age, dates, forward, hi, nw_t, rank, ret5, top8  # noqa: E402


def z(s: pd.Series) -> pd.Series:
    sd = s.std()
    return (s - s.mean()) / sd if sd and np.isfinite(sd) else s * 0


for h in (20, 40):
    r, base = forward(h)
    ex = r.sub(base, axis=0)
    coefs, n_fresh = [], []
    for i, t in enumerate(dates):
        if i + 1 + h >= len(dates) or t < pd.Timestamp("2019-07-01") or dates[i + 1 + h] > DEV_END:
            continue
        m = top8.iloc[i]
        syms = m.index[m.values]
        e = ex.iloc[i][syms].dropna()
        if len(e) < 6:
            continue
        s = e.index
        X = pd.DataFrame({"rank": z(-rank.iloc[i][s].astype(float)),
                          "ret5": z(ret5.iloc[i][s]),
                          "estab": (age.iloc[i][s] > 10).astype(float),
                          "hi250": z(hi.iloc[i][s])}).fillna(0.0)
        n_fresh.append(int((age.iloc[i][s] <= 10).sum()))
        A = np.column_stack([np.ones(len(X)), X.values])
        if np.linalg.matrix_rank(A) < A.shape[1]:
            continue
        b, *_ = np.linalg.lstsq(A, e.values, rcond=None)
        coefs.append(pd.Series(b[1:], index=X.columns, name=t))
    B = pd.DataFrame(coefs)
    print(f"\nh={h}: {len(B)} days; fresh names per day: mean {np.mean(n_fresh):.1f} of 8, "
          f"days with none {np.mean(np.array(n_fresh) == 0)*100:.0f}%")
    for c in B.columns:
        yrs = B[c].groupby(B.index.year).mean()
        print(f"   {c:6s} coef {100*B[c].mean():+.2f}%  NW t {nw_t(B[c], h):+.2f}   "
              + " ".join(f"{y}:{100*v:+.1f}" for y, v in yrs.items()))
