"""Sell rules per position, counted from each position's own entry (2026-09-29).

Tom: *"việc của bạn cập nhật những con tôi đang hold và đưa đề xuất dựa vào giá
mua, có nên bán hay không"*. The shipped rule reviews a synchronised 8-name book
every 20 sessions. Tom buys on his own days, so each position needs its own clock,
and he asks for advice anchored on his entry price. Seven variants, fixed BEFORE
looking at any result:

  V0  review at sessions 20, 40, 60 ... from entry; sell if rank > 16  (shipped rule)
  V1  check the rank every day; sell the first day it is > 16
  V2  V0, plus a hard cap: sell at 40 sessions whatever the rank
      (what the bulletin's "quá hạn" alert says today)
  V3  V0, plus take profit at +20% over the entry price
  V4  V0, plus take profit at +30%
  V5  V0, plus cut loss at -10% under the entry price
  V6  V0, plus cut loss at -15%

A variant replaces or extends V0 only if on DEV it adds >= 1 point of CAGR a
year, its Sharpe is not lower, and it is not worse than V0 in >= 4 of the 6
full DEV years (2020-2025). The holdout is read once, for variants that pass.

Book: 8 equal slots, signal at close t, trade at open t+1, costs as the lab
(1.0% round trip). An emptied slot is refilled at the next open from the best
names not held -- Tom checks the list every day. Initial clocks are shifted by
0, 2, ..., 18 sessions and the equity curves averaged, as `simulate_phases`
does, so the result does not hang on the start day.

Run from the repo root:  python docs/reviews/workflow_study_2026-09-29/exits.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LAB = HERE.parent / "strategy_study_2026-09-28"
sys.path.insert(0, str(LAB))
from lab import BUY_COST, DEV_END, HOLD_START, SELL_COST, bench, stats, yearly  # noqa: E402
from study import UNIV, fam, P, vn  # noqa: E402

START = pd.Timestamp("2019-07-01")
PH = list(range(0, 20, 2))

VARIANTS = {
    "V0 xem lại mỗi 20 phiên, bán khi rơi khỏi top 16": {},
    "V1 kiểm hạng mỗi ngày": {"daily_check": True},
    "V2 V0 + bán cứng ở phiên 40": {"max_hold": 40},
    "V3 V0 + chốt lời +20%": {"tp": 0.20},
    "V4 V0 + chốt lời +30%": {"tp": 0.30},
    "V5 V0 + cắt lỗ -10%": {"sl": 0.10},
    "V6 V0 + cắt lỗ -15%": {"sl": 0.15},
}


def simulate_book(score: pd.DataFrame, eligible: pd.DataFrame, *, K: int = 8,
                  keep_top: int = 16, review: int = 20, daily_check: bool = False,
                  max_hold: int | None = None, tp: float | None = None,
                  sl: float | None = None, start=START, end=None, phase: int = 0):
    """Daily book with per-position clocks. Returns (daily returns, trades/yr, exits by reason)."""
    O, C = P["open"].values, P["close"].values  # noqa: E741
    dates = P["close"].index
    S = score.reindex(index=dates, columns=P["close"].columns).values
    E = eligible.reindex(index=dates, columns=P["close"].columns).fillna(False).values.astype(bool)
    i0 = int(dates.searchsorted(start))
    i1 = len(dates) - 1 if end is None else int(dates.searchsorted(end, side="right")) - 1

    cash, eq_prev = 1.0, 1.0
    pos: dict[int, dict] = {}    # col -> {value, px (last mark), entry_px, e (clock start)}
    rets, n_trades = [], 0
    reasons: dict[str, int] = {}
    first = True
    for i in range(i0, i1 + 1):
        t = i - 1
        s = S[t]
        ok = E[t] & np.isfinite(s)
        order = [j for j in np.argsort(-np.where(ok, s, -np.inf)) if ok[j]]
        rk = {j: r + 1 for r, j in enumerate(order)}
        # 1) exits decided at close t, executed at open i
        for j in list(pos):
            p = pos[j]
            o = O[i, j]
            if not (np.isfinite(o) and o > 0):
                continue                               # cannot trade today; decide tomorrow
            held = t - p["e"] + 1                      # sessions whose close we have seen
            why = None
            c_t = C[t, j]
            if tp is not None and np.isfinite(c_t) and c_t >= p["entry_px"] * (1 + tp):
                why = "chốt lời"
            elif sl is not None and np.isfinite(c_t) and c_t <= p["entry_px"] * (1 - sl):
                why = "cắt lỗ"
            elif max_hold is not None and held >= max_hold:
                why = "hết khung"
            elif (daily_check or (held > 0 and held % review == 0)) and rk.get(j, 10**9) > keep_top:
                why = "rơi khỏi top 16"
            if why:
                p = pos.pop(j)
                cash += p["value"] * (o / p["px"]) * (1 - SELL_COST)
                n_trades += 1
                reasons[why] = reasons.get(why, 0) + 1
        # mark survivors to the open (for sizing)
        for j, p in pos.items():
            o = O[i, j]
            if np.isfinite(o) and o > 0:
                p["value"] *= o / p["px"]
                p["px"] = o
        # 2) fill empty slots from the best names not held
        free = K - len(pos)
        if free > 0 and t >= 0:
            new = [j for j in order if j not in pos][:free]
            new = [j for j in new if np.isfinite(O[i, j]) and O[i, j] > 0]
            if new:
                equity = cash + sum(p["value"] for p in pos.values())
                per = min(equity / K, cash / len(new))
                for j in new:
                    cash -= per
                    # the first cohort's clock is shifted by `phase`, like simulate_phases
                    e = i - phase if first else i
                    pos[j] = {"value": per * (1 - BUY_COST), "px": O[i, j],
                              "entry_px": O[i, j], "e": e}
                    n_trades += 1
        first = False
        # 3) mark to close i
        for j, p in pos.items():
            c = C[i, j]
            if np.isfinite(c) and c > 0:
                p["value"] *= c / p["px"]
                p["px"] = c
        equity = cash + sum(p["value"] for p in pos.values())
        rets.append(equity / eq_prev - 1.0)
        eq_prev = equity
    idx = dates[i0:i1 + 1]
    return pd.Series(rets, index=idx), n_trades / (len(idx) / 252), reasons


def run(kw: dict, start=START, end=None):
    curves, cagrs, trades, why = [], [], [], {}
    for ph in PH:
        d, tr, rs = simulate_book(fam["ramom126"], UNIV["U75"], start=start, end=end,
                                  phase=ph, **kw)
        curves.append((1 + d).cumprod())
        cagrs.append(stats(d)["cagr"])
        trades.append(tr)
        for k, v in rs.items():
            why[k] = why.get(k, 0) + v
    eq = pd.concat(curves, axis=1).mean(axis=1)
    daily = eq.pct_change().fillna(eq.iloc[0] - 1.0)
    return daily, np.array(cagrs), float(np.mean(trades)), why


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    which = sys.argv[1] if len(sys.argv) > 1 else "dev"
    rows, yrs = [], {}
    for name, kw in VARIANTS.items():
        if which == "dev":
            d, cagrs, tr, why = run(kw, START, DEV_END)
        else:  # "holdout": only for the variants named on the command line
            if name.split()[0] not in sys.argv[2:] and not name.startswith("V0"):
                continue
            d, cagrs, tr, why = run(kw, HOLD_START, None)
        st = stats(d)
        b = stats(bench(vn, d.index))
        rows.append({"biến thể": name, "CAGR": 100 * st["cagr"], "Sharpe": st["sharpe"],
                     "MaxDD": 100 * st["maxdd"], "VNINDEX": 100 * b["cagr"],
                     "pha min": 100 * cagrs.min(), "pha max": 100 * cagrs.max(),
                     "lệnh/năm": tr,
                     "lý do bán": ", ".join(f"{k} {v / len(PH):.0f}" for k, v in sorted(why.items()))})
        yrs[name.split()[0]] = (100 * yearly(d)).round(1)
    print(f"=== {which.upper()} ===")
    print(pd.DataFrame(rows).round(2).to_string(index=False))
    print("\ntheo năm (%):")
    print(pd.DataFrame(yrs).T.to_string())
