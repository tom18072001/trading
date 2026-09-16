"""Portfolio simulation of a picks rule -- the last gate before anything ships.

`ticker_alpha_bench` measures a factor and `tplus_strategy_bench` measures a
trade. Neither answers the question that decides whether a rule is worth money:
run it as a book, with a cap on concurrent positions, and what does the equity
curve look like next to VNINDEX?

Mechanics, all of them deliberate:
  * entry at the NEXT session's open (the report is written after the close)
  * equal weight across at most MAX_POS concurrent names, one entry per name
  * T+2: capital from a sale is unavailable for BACKTEST_SETTLEMENT_LAG sessions
  * fees + sell tax from config, slippage per side on the parameter
  * exit at max_hold sessions, or a stop if one is asked for

Reported against two baselines, because one is not enough:
  * VNINDEX buy-and-hold (11)
  * the same book construction fed RANDOM eligible names (16.12)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    BACKTEST_FEE_BPS,
    BACKTEST_SELL_TAX_BPS,
    BACKTEST_SETTLEMENT_LAG,
)
from scripts.ticker_alpha_bench import PANEL_DB, build_features, load_panel  # noqa: E402
from scripts.tplus_strategy_bench import RULES  # noqa: E402


def vnindex_curve(idx: pd.DatetimeIndex) -> pd.Series | None:
    """VNINDEX from the price panel.

    NOT from `macro_anchors`: 23.5 logged that the column has no rows before
    2026-04-09, so a benchmark built on it silently covers five months of a
    four-year test and reports a CAGR from a stub. `build_price_panel.py`
    stores the index as ^VNINDEX so the benchmark shares the panel's calendar.
    """
    con = sqlite3.connect(PANEL_DB)
    df = pd.read_sql("SELECT time, close FROM prices WHERE symbol='^VNINDEX' "
                     "AND close > 0 ORDER BY time", con, parse_dates=["time"])
    con.close()
    if df.empty:
        return None
    s = df.set_index("time")["close"]
    s.index = s.index.normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    out = s.reindex(idx.normalize(), method="ffill")
    if out.notna().sum() < 0.9 * len(idx):
        return None        # partial coverage is worse than none -- say so
    return out / out.dropna().iloc[0]


def simulate(entries: pd.DataFrame, f: dict, p: dict, *, max_pos: int,
             max_hold: int, stop_atr: float | None, min_dv: float,
             slip: float, start: str) -> tuple[pd.Series, pd.DataFrame]:
    op, cl = p["open"], p["close"]
    atr = (f["atr_pct"] / 100.0).values
    dates = op.index
    syms = list(op.columns)
    OP, LO, CL = op.values, p["low"].values, cl.values

    rank = f["dv20"].rank(axis=1, ascending=False).values      # deterministic pick order
    elig = ((f["dv20"] > min_dv) & entries.fillna(False)).values
    i0 = int(np.searchsorted(dates, pd.Timestamp(start)))

    fee_in = BACKTEST_FEE_BPS / 10_000.0 + slip
    fee_out = (BACKTEST_FEE_BPS + BACKTEST_SELL_TAX_BPS) / 10_000.0 + slip

    cash, equity = 1.0, []
    book: dict[int, dict] = {}          # column index -> position
    pending: list[tuple[int, float]] = []   # (settles_on_i, amount)
    trades = []

    for i in range(i0, len(dates) - 1):
        for k in range(len(pending) - 1, -1, -1):
            when, amt = pending[k]
            if when <= i:
                cash += amt
                pending.pop(k)

        # --- exits, evaluated on today's bar ---
        for j in list(book):
            pos = book[j]
            px, why = None, None
            if pos["stop"] is not None and np.isfinite(LO[i, j]) and LO[i, j] <= pos["stop"]:
                px, why = pos["stop"], "stop"
            elif i - pos["i"] >= max_hold and np.isfinite(CL[i, j]):
                px, why = CL[i, j], "time"
            if px is None:
                continue
            proceeds = pos["shares"] * px * (1 - fee_out)
            pending.append((i + BACKTEST_SETTLEMENT_LAG, proceeds))
            trades.append({"symbol": syms[j], "in": dates[pos["i"]], "out": dates[i],
                           "ret": px / pos["px"] - 1 - fee_in - fee_out, "why": why})
            del book[j]

        # --- entries, filled at TOMORROW's open ---
        free = max_pos - len(book)
        if free > 0 and cash > 1e-9:
            cand = [j for j in np.flatnonzero(elig[i])
                    if j not in book and np.isfinite(OP[i + 1, j]) and OP[i + 1, j] > 0
                    and np.isfinite(atr[i, j])]
            cand.sort(key=lambda j: rank[i, j])     # most liquid first, no randomness
            cand = cand[:free]
            if cand:
                each = cash / len(cand)
                for j in cand:
                    px = OP[i + 1, j]
                    gross = each * (1 - fee_in)
                    book[j] = {"i": i + 1, "px": px, "shares": gross / px,
                               "stop": px * (1 - stop_atr * atr[i, j]) if stop_atr else None}
                    cash -= each

        mtm = sum(pos["shares"] * CL[i, j] for j, pos in book.items()
                  if np.isfinite(CL[i, j]))
        equity.append((dates[i], cash + mtm + sum(a for _, a in pending)))

    eq = pd.Series(dict(equity)).sort_index()
    return eq, pd.DataFrame(trades)


def stats(eq: pd.Series) -> dict:
    r = eq.pct_change().dropna()
    if r.empty or eq.iloc[0] <= 0:
        return {}
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    return {"total": eq.iloc[-1] / eq.iloc[0] - 1, "cagr": cagr,
            "sharpe": r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan,
            "maxdd": dd}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pos", type=int, default=5)
    ap.add_argument("--max-hold", type=int, default=20)
    ap.add_argument("--stop-atr", type=float, default=0.0, help="0 = no stop")
    ap.add_argument("--min-dv", type=float, default=5e6)
    ap.add_argument("--slippage-bps", type=float, default=15)
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--rules", default="")
    args = ap.parse_args()

    p = load_panel()
    f = build_features(p)
    slip = args.slippage_bps / 10_000.0
    stop = args.stop_atr or None

    names = args.rules.split(",") if args.rules else list(RULES)
    print(f"book: max {args.max_pos} positions, hold {args.max_hold} sessions, "
          f"stop {args.stop_atr or 'none'}xATR, T+{BACKTEST_SETTLEMENT_LAG} settlement")
    print(f"cost: {BACKTEST_FEE_BPS}bps/side + {BACKTEST_SELL_TAX_BPS}bps sell tax + "
          f"{args.slippage_bps}bps slippage/side, from {args.start}\n")
    print(f"{'rule':26s} {'total%':>9s} {'CAGR%':>8s} {'Sharpe':>7s} {'MaxDD%':>8s} "
          f"{'trades':>7s} {'win':>6s}")
    print("-" * 78)

    rows = []
    for n in names:
        eq, tr = simulate(RULES[n](f).fillna(False).astype(bool), f, p,
                          max_pos=args.max_pos, max_hold=args.max_hold,
                          stop_atr=stop, min_dv=args.min_dv, slip=slip,
                          start=args.start)
        st = stats(eq)
        if not st:
            continue
        rows.append((st["cagr"], n, st, tr, eq))

    # random control, built the same way
    rng = np.random.default_rng(11)
    pool = ((f["dv20"] > args.min_dv)).values
    fv = np.zeros(p["close"].shape, dtype=bool)
    for i in range(len(fv)):
        cand = np.flatnonzero(pool[i])
        if len(cand):
            fv[i, rng.choice(cand, size=min(args.max_pos, len(cand)), replace=False)] = True
    fake = pd.DataFrame(fv, index=p["close"].index, columns=p["close"].columns)
    eqc, trc = simulate(fake, f, p, max_pos=args.max_pos, max_hold=args.max_hold,
                        stop_atr=stop, min_dv=args.min_dv, slip=slip, start=args.start)
    stc = stats(eqc)
    print(f"{'RANDOM CONTROL':26s} {stc['total']*100:>9.1f} {stc['cagr']*100:>8.1f} "
          f"{stc['sharpe']:>7.2f} {stc['maxdd']*100:>8.1f} {len(trc):>7d} "
          f"{(trc['ret']>0).mean():>6.2f}")

    vni = vnindex_curve(eqc.index)
    if vni is None:
        print(f"{'VNINDEX buy & hold':26s} {'unavailable -- ^VNINDEX does not cover this window':>9s}")
    else:
        sv = stats(vni.dropna())
        print(f"{'VNINDEX buy & hold':26s} {sv['total']*100:>9.1f} {sv['cagr']*100:>8.1f} "
              f"{sv['sharpe']:>7.2f} {sv['maxdd']*100:>8.1f} {'':>7s} {'':>6s}")

    for _, n, st, tr, eq in sorted(rows, key=lambda t: -t[0]):
        print(f"{n:26s} {st['total']*100:>9.1f} {st['cagr']*100:>8.1f} "
              f"{st['sharpe']:>7.2f} {st['maxdd']*100:>8.1f} {len(tr):>7d} "
              f"{(tr['ret']>0).mean():>6.2f}")

    print("\nper-calendar-year return %")
    yrs = sorted({d.year for d in eqc.index})
    print(f"{'rule':26s} " + " ".join(f"{y:>8d}" for y in yrs))

    def yearly(eq):
        return eq.resample("YE").last().pct_change().fillna(
            eq.resample("YE").last() / eq.iloc[0] - 1)

    yc = yearly(eqc)
    print(f"{'RANDOM CONTROL':26s} " + " ".join(
        f"{yc[yc.index.year == y].iloc[0]*100:>8.1f}" if (yc.index.year == y).any()
        else f"{'':>8s}" for y in yrs))
    for _, n, _st, _tr, eq in sorted(rows, key=lambda t: -t[0]):
        yy = yearly(eq)
        print(f"{n:26s} " + " ".join(
            f"{yy[yy.index.year == y].iloc[0]*100:>8.1f}" if (yy.index.year == y).any()
            else f"{'':>8s}" for y in yrs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
