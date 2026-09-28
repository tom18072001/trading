"""Strategy lab (2026-09-28): can a buy rule beat VNINDEX, and by how much?

Protocol, fixed BEFORE looking at results:
  * data: data/price_panel.db (143 names + ^VNINDEX), prices in thousand VND.
  * signal at close t, trade at open t+1 (the live ATO), costs per side:
    fee 0.15% + slippage 0.30%, plus 0.10% tax on sells  (= bench's 1.0%/round trip).
  * DEV window: first tradable day .. 2025-09-15.  HOLDOUT: 2025-09-16 .. end.
    Variants are compared on DEV only. The holdout is read once, for the rule
    chosen on DEV, and never used to choose.
  * benchmark: VNINDEX buy & hold on the SAME days (price index, no dividends).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
PANEL = REPO / "data" / "price_panel.db"
DEV_END = pd.Timestamp("2025-09-15")
HOLD_START = pd.Timestamp("2025-09-16")

FEE = 0.0015
SLIP = 0.003
TAX = 0.001
BUY_COST = FEE + SLIP
SELL_COST = FEE + SLIP + TAX
SESSIONS = 252


def load(panel: Path = PANEL):
    con = sqlite3.connect(panel)
    df = pd.read_sql("SELECT symbol, time, open, high, low, close, volume FROM prices "
                     "WHERE close > 0 ORDER BY time", con, parse_dates=["time"])
    con.close()
    vn = (df[df.symbol == "^VNINDEX"].set_index("time")["close"])
    vn = vn[~vn.index.duplicated(keep="last")]
    df = df[~df.symbol.str.startswith("^")]
    P = {c: df.pivot(index="time", columns="symbol", values=c).sort_index()
         for c in ("open", "high", "low", "close", "volume")}
    idx = P["close"].index
    vn = vn.reindex(idx).ffill(limit=5)
    # open==0 or missing -> no trade possible that day
    P["open"] = P["open"].where(P["open"] > 0)
    return P, vn


def features(P, vn):
    C, V, H, L = P["close"], P["volume"], P["high"], P["low"]
    r1 = C.pct_change(fill_method=None)
    f = {"close": C, "ret1": r1}
    f["dv20"] = (C * V).rolling(20, min_periods=15).mean()          # thousand VND
    f["n_obs"] = C.notna().cumsum()
    for L_, S_ in ((21, 0), (63, 0), (63, 5), (126, 5), (126, 21), (250, 21), (250, 5)):
        f[f"mom{L_}_{S_}"] = C.shift(S_) / C.shift(L_) - 1
    f["vol63"] = r1.rolling(63, min_periods=40).std()
    f["vol126"] = r1.rolling(126, min_periods=80).std()
    f["hi250"] = C / C.rolling(250, min_periods=120).max()
    f["hi126"] = C / C.rolling(126, min_periods=80).max()
    for n in (20, 50, 100, 200):
        f[f"sma{n}"] = C.rolling(n, min_periods=int(n * 0.8)).mean()
    f["tr_atr"] = (pd.concat([H - L, (H - C.shift()).abs(), (L - C.shift()).abs()])
                   .groupby(level=0).max().reindex(C.index))
    # OBV-based accumulation: 60d change in OBV scaled by 60d volume
    obv = (np.sign(r1).fillna(0) * V).cumsum()
    f["obv60"] = (obv - obv.shift(60)) / V.rolling(60, min_periods=40).sum()
    f["vratio"] = V.rolling(20, min_periods=15).mean() / V.rolling(120, min_periods=80).mean()
    # market
    f["vn"] = vn
    for n in (50, 100, 200):
        f[f"vn_sma{n}"] = vn.rolling(n, min_periods=int(n * 0.8)).mean()
    above50 = (C > f["sma50"]).where(f["sma50"].notna())
    f["breadth50"] = above50.mean(axis=1)
    return f


def rank_pct(df: pd.DataFrame, mask: pd.DataFrame | None = None) -> pd.DataFrame:
    x = df.where(mask) if mask is not None else df
    return x.rank(axis=1, pct=True)


@dataclass
class Result:
    daily: pd.Series           # daily portfolio returns
    turnover: float            # one-side traded value / equity, per year
    exposure: float            # mean fraction invested
    trades: int
    holdings: list             # (date, tuple(symbols)) at each rebalance


def simulate(score: pd.DataFrame, eligible: pd.DataFrame, P, *, K: int = 8, R: int = 20,
             buffer: int = 0, regime: pd.Series | None = None,
             start: pd.Timestamp | None = None, end: pd.Timestamp | None = None,
             phase: int = 0, regime_mode: str = "cash") -> Result:
    """Rebalance every R sessions (signal at close t, trade at open t+1).

    Holdings still ranked within K+buffer are kept (no trade); the rest are
    sold and the freed cash is split equally over the best new names, each
    capped at 1/K of equity. `regime` False at close t -> go to cash at t+1
    (checked daily); True again -> rebuild at the next open.
    """
    O = P["open"].values  # noqa: E741
    C = P["close"].values
    dates = P["close"].index
    syms = np.array(P["close"].columns)
    S = score.reindex(index=dates, columns=syms).values
    E = eligible.reindex(index=dates, columns=syms).fillna(False).values.astype(bool)
    G = (regime.reindex(dates).fillna(False).values.astype(bool)
         if regime is not None else np.ones(len(dates), bool))
    i0 = 0 if start is None else int(dates.searchsorted(start))
    i1 = len(dates) - 1 if end is None else int(dates.searchsorted(end, side="right")) - 1

    cash = 1.0
    pos: dict[int, float] = {}          # column -> value at last mark
    last_px: dict[int, float] = {}      # column -> last price used to mark
    eq_prev = 1.0
    rets = []
    traded = 0.0
    n_trades = 0
    invested = []
    hold_log = []
    since = R                           # invest on the first day ...
    first = True                        # ... then shift the cycle by `phase`
    prev_regime = None

    for i in range(i0, i1 + 1):
        # 1) decide at close i-1 whether to trade at open i
        t = i - 1
        trade = False
        if t >= 0:
            reg = G[t]
            if reg != prev_regime and prev_regime is not None and regime_mode == "cash":
                trade = True
            if since >= R:
                trade = True
            prev_regime = reg
        if trade and t >= 0:
            # mark to open
            for j in list(pos):
                o = O[i, j]
                if np.isfinite(o) and o > 0:
                    pos[j] *= o / last_px[j]
                    last_px[j] = o
            equity = cash + sum(pos.values())
            if G[t] or regime_mode == "nobuy":
                s = S[t].copy()
                ok = E[t] & np.isfinite(s)
                order = [j for j in np.argsort(-np.where(ok, s, -np.inf)) if ok[j]]
                rank = {j: r for r, j in enumerate(order)}
                keep = [j for j in pos if rank.get(j, 10**9) < K + buffer]
                keep = sorted(keep, key=lambda j: rank[j])[:K]
                target_new = [j for j in order if j not in keep][: K - len(keep)]
                if not G[t]:
                    target_new = []          # "nobuy": hold what still ranks, open nothing
            else:
                keep, target_new = [], []
            # sell what is not kept (only if it can trade today)
            for j in list(pos):
                if j in keep:
                    continue
                o = O[i, j]
                if not (np.isfinite(o) and o > 0):
                    continue                 # cannot sell today; stays held
                v = pos.pop(j)
                last_px.pop(j)
                cash += v * (1 - SELL_COST)
                traded += v / equity
                n_trades += 1
            # buy new names
            buyable = [j for j in target_new if np.isfinite(O[i, j]) and O[i, j] > 0]
            if buyable:
                equity = cash + sum(pos.values())
                per = min(equity / K, cash / len(buyable))
                for j in buyable:
                    v = per
                    cash -= v
                    pos[j] = v * (1 - BUY_COST)
                    last_px[j] = O[i, j]
                    traded += v / equity
                    n_trades += 1
            hold_log.append((dates[i], tuple(syms[j] for j in pos)))
            since = (R - phase) % R if first else 0
            first = False
        # 2) mark to close i
        for j in list(pos):
            c = C[i, j]
            if np.isfinite(c) and c > 0:
                pos[j] *= c / last_px[j]
                last_px[j] = c
        equity = cash + sum(pos.values())
        rets.append(equity / eq_prev - 1.0)
        invested.append(sum(pos.values()) / equity if equity > 0 else 0.0)
        eq_prev = equity
        since += 1

    idx = dates[i0:i1 + 1]
    daily = pd.Series(rets, index=idx)
    yrs = len(idx) / SESSIONS
    return Result(daily, traded / max(yrs, 1e-9), float(np.mean(invested)), n_trades, hold_log)


def simulate_phases(score, eligible, P, *, K=8, R=20, phases=None, **kw):
    """The same rule started on each phase of its R-session cycle.

    One concentrated portfolio rebalanced every R sessions is ~R/252 draws a
    year: its result depends on which day the cycle started. The mean over
    phases is the rule's expected result; the spread is the luck of the start
    day. Returns (mean-of-equity-curves daily returns, per-phase CAGRs, mean turnover, mean exposure).
    """
    phases = range(R) if phases is None else phases
    curves, cagrs, tos, exps = [], [], [], []
    for ph in phases:
        res = simulate(score, eligible, P, K=K, R=R, phase=ph, **kw)
        eq = (1 + res.daily).cumprod()
        curves.append(eq)
        cagrs.append(stats(res.daily)["cagr"])
        tos.append(res.turnover)
        exps.append(res.exposure)
    eq = pd.concat(curves, axis=1).mean(axis=1)
    daily = eq.pct_change().fillna(eq.iloc[0] - 1.0)
    return daily, np.array(cagrs), float(np.mean(tos)), float(np.mean(exps))


def stats(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 20:
        return {"cagr": np.nan, "sharpe": np.nan, "maxdd": np.nan, "vol": np.nan}
    eq = (1 + r).cumprod()
    yrs = len(r) / SESSIONS
    sd = r.std()
    return {"cagr": eq.iloc[-1] ** (1 / yrs) - 1,
            "sharpe": r.mean() / sd * np.sqrt(SESSIONS) if sd > 0 else np.nan,
            "maxdd": (eq / eq.cummax() - 1).min(), "vol": sd * np.sqrt(SESSIONS)}


def bench(vn: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    return vn.reindex(idx).pct_change(fill_method=None).fillna(0.0)


def yearly(r: pd.Series) -> pd.Series:
    return (1 + r).groupby(r.index.year).prod() - 1
