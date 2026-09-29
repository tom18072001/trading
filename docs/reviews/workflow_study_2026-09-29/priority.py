"""Priority inside the buy list (2026-09-29).

Tom: *"bạn khuyến nghị mã nào nên mua hằng ngày (có các priority, con nào khả
năng lên cao)"*. He buys a few names from the daily list, not all eight, so the
order inside the list has to mean something. Four hypotheses, fixed BEFORE
looking at any result:

  P1 rank      ranks 1-4 beat ranks 5-8
  P2 pullback  inside the top 8, the four with the LOWER last-5-session return
               beat the other four (short-term reversal; the score skips exactly
               those 5 sessions)
  P3 fresh     names that entered the top 8 within the last 10 sessions vs names
               there longer (two-sided: no prior on the sign)
  P4 high      inside the top 8, the four CLOSER to their 250-session high beat
               the other four (George & Hwang 2004)

Unit: a pick = a top-8 name at close t, bought at open t+1, sold at close
t+1+h, net of 1.0% round trip. Measured as excess over the equal-weight U75
universe over the same open t+1 -> close t+1+h window, so the market drops out.
Each signal day gives one spread (preferred group minus the other); consecutive
days overlap, so the t-stat is Newey-West with lag h.

Adoption rule, fixed before looking: on DEV (exit <= 2025-09-15) the spread is
> 0 at both h = 20 and h = 40, NW t >= 2 at one of them, and positive in >= 4
of the 6 full DEV years (2020-2025). The holdout is then read once, for the
hypotheses that pass, and only its sign is asked for (12 months has no power).

Run from the repo root:  python docs/reviews/workflow_study_2026-09-29/priority.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LAB = HERE.parent / "strategy_study_2026-09-28"
sys.path.insert(0, str(LAB))
from lab import DEV_END, HOLD_START  # noqa: E402
from study import UNIV, f, fam, P  # noqa: E402

RT = 0.010
HS = (20, 40)
el = UNIV["U75"]
sc = fam["ramom126"].where(el)
rank = sc.rank(axis=1, ascending=False, method="first")
O, C = P["open"], P["close"]  # noqa: E741
dates = C.index
top8 = (rank <= 8) & sc.notna()


def run_age(mask: pd.DataFrame) -> pd.DataFrame:
    """Consecutive sessions each name has been in `mask`, up to and including t."""
    a = mask.values.astype(int)
    out = np.zeros_like(a)
    for i in range(len(a)):
        out[i] = (out[i - 1] + 1) * a[i] if i else a[i]
    return pd.DataFrame(out, index=mask.index, columns=mask.columns)


ret5 = C / C.shift(5) - 1
age = run_age(top8)
hi = f["hi250"]


def forward(h: int) -> tuple[pd.DataFrame, pd.Series]:
    """Net pick return open t+1 -> close t+1+h, and the universe mean (gross)."""
    entry = O.shift(-1)
    exit_ = C.shift(-(1 + h))
    r = exit_ / entry - 1
    base = r.where(el & entry.notna() & (entry > 0)).mean(axis=1)
    return r - RT, base


def nw_t(x: pd.Series, lag: int) -> float:
    x = x.dropna()
    n = len(x)
    if n < 3 * lag:
        return float("nan")
    e = x - x.mean()
    s = (e @ e) / n
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        s += 2 * w * (e.values[k:] @ e.values[:-k]) / n
    return float(x.mean() / np.sqrt(s / n))


def spreads(h: int) -> pd.DataFrame:
    r, base = forward(h)
    ex = r.sub(base, axis=0)
    rows = []
    for i, t in enumerate(dates):
        if i + 1 + h >= len(dates):
            break
        m = top8.iloc[i]
        syms = m.index[m.values]
        e = ex.iloc[i][syms].dropna()
        if len(e) < 6:
            continue
        rk, r5, ag, hh = rank.iloc[i][e.index], ret5.iloc[i][e.index], age.iloc[i][e.index], hi.iloc[i][e.index]
        row = {"t": t, "exit": dates[i + 1 + h], "all": e.mean()}
        row["P1"] = e[rk <= 4].mean() - e[rk > 4].mean()
        lo5 = r5.sort_values().index[:len(e) // 2]
        row["P2"] = e[lo5].mean() - e.drop(lo5).mean()
        fresh = ag <= 10
        row["P3"] = (e[fresh].mean() - e[~fresh].mean()) if 0 < fresh.sum() < len(e) else np.nan
        near = hh.sort_values(ascending=False).index[:len(e) // 2]
        row["P4"] = e[near].mean() - e.drop(near).mean()
        rows.append(row)
    return pd.DataFrame(rows).set_index("t")


def by_rank(h: int) -> pd.DataFrame:
    """Mean excess and win rate by rank bucket over DEV -- descriptive, not a test."""
    r, base = forward(h)
    ex = r.sub(base, axis=0)
    ok = [dates[i] for i in range(len(dates) - 1 - h)
          if dates[i] >= pd.Timestamp("2019-07-01") and dates[i + 1 + h] <= DEV_END]
    buckets = [(1, 2), (3, 4), (5, 8), (9, 16), (17, 24), (25, 32), (33, 999)]
    out = []
    for lo, hi_ in buckets:
        m = (rank >= lo) & (rank <= hi_)
        e = ex.where(m).loc[ok]
        rr = r.where(m).loc[ok]
        daily = e.mean(axis=1)
        out.append({"hạng": f"{lo}-{hi_}" if hi_ < 999 else f"{lo}+",
                    "n": int(e.notna().sum().sum()),
                    "excess_%": 100 * float(np.nanmean(e.values)),
                    "net_%": 100 * float(np.nanmean(rr.values)),
                    "win_%": 100 * float(np.nanmean((rr.values > 0)[~np.isnan(rr.values)])),
                    "NW_t": nw_t(daily, h)})
    return pd.DataFrame(out)


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    for h in HS:
        S = spreads(h)
        dev = S[(S.index >= pd.Timestamp("2019-07-01")) & (S["exit"] <= DEV_END)]
        hold = S[S.index >= HOLD_START]
        print(f"\n===== h = {h} sessions   DEV {dev.index.min().date()}..{dev.index.max().date()} "
              f"({len(dev)} days)   HOLDOUT {len(hold)} days")
        print(f"top-8 mean excess vs universe (net): DEV {100*dev['all'].mean():.2f}%  "
              f"NW t {nw_t(dev['all'], h):.2f}")
        for k in ("P1", "P2", "P3", "P4"):
            x = dev[k]
            yrs = x.groupby(x.index.year).mean()
            full = yrs[(yrs.index >= 2020) & (yrs.index <= 2025)]
            print(f"  {k}: DEV spread {100*x.mean():+.2f}%  NW t {nw_t(x, h):+.2f}  "
                  f"years>0 {int((full > 0).sum())}/{len(full)}  "
                  f"[{' '.join(f'{y}:{100*v:+.1f}' for y, v in yrs.items())}]")
        (HERE / "out").mkdir(exist_ok=True)
        S.to_pickle(HERE / "out" / f"priority_h{h}.pkl")
        print("\n  by rank bucket, DEV (descriptive):")
        print(by_rank(h).round(2).to_string(index=False))
