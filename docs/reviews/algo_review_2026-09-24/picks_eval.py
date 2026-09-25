"""Independent evaluation harness for the per-ticker picks (review 2026-09-24).

Reuses the repo's own panel loader, feature builder and scoring coefficients
(so formulas are not retyped), and adds what the existing bench lacks:

  1. ONE base rate for every rule: the full liquid universe (NO GATE), on the
     same signal days, plus VNINDEX over the identical entry->exit window.
  2. Honest t-stats: forward windows overlap day to day, so the mean of a daily
     series of h-session returns is tested with Newey-West (lag = h).
  3. A Jegadeesh-Titman staggered portfolio (capital split in h+1 tranches, one
     tranche opened per day) -> daily equity curve -> CAGR / Sharpe / MaxDD,
     comparable like-for-like with VNINDEX buy-and-hold on the same dates.
  4. The rule AS SHIPPED: score >= MIN_BUY_SCORE, then the production rank
     blend computed over the whole universe (floored names included), top-k.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]   # docs/reviews/<this>/ -> repo root
sys.path.insert(0, str(ROOT))

from analysis.bench import TOTAL_COST  # noqa: E402
# FACTORS and MIN_BUY_SCORE are re-exported: the other scripts in this folder
# import them from here.
from scripts.ticker_alpha_bench import FACTORS, build_features, load_panel  # noqa: E402, F401
from services.picks_scoring import (  # noqa: E402, F401
    MIN_BUY_SCORE, SCORE_CONST, UNTRENDED_FLOOR, W_ABOVE_SMA50, W_OVERSOLD_DIV,
    W_PULLBACK_CLIP, W_RANK_OBV, W_RANK_SCORE, W_WIDE_ATR_PEN, WIDE_ATR_PCT,
)

MIN_DV = 5e6          # thousand VND -> 5 bn VND/day, same as bench + production
LEFTOVER_SYMS = ["SRC", "POM", "NFC", "GMC", "PTI", "VSH", "ACL", "DNP"]


# ------------------------------------------------------------------ data ----

def load_all(drop_leftover: bool = False):
    p = load_panel()
    if drop_leftover:
        for k in p:
            p[k] = p[k].drop(columns=[s for s in LEFTOVER_SYMS if s in p[k].columns])
    f = build_features(p)
    con = sqlite3.connect(ROOT / "data" / "price_panel.db")
    vn = pd.read_sql("SELECT time, open, high, low, close FROM prices "
                     "WHERE symbol='^VNINDEX' ORDER BY time", con,
                     parse_dates=["time"]).set_index("time")
    con.close()
    vn = vn.reindex(p["close"].index)
    return p, f, vn


def constituents() -> list[str]:
    con = sqlite3.connect(ROOT / "vnstock_market.db")
    syms = sorted({s.strip().upper() for (s,) in
                   con.execute("SELECT DISTINCT symbol FROM sector_constituents")})
    con.close()
    return syms


# ------------------------------------------------------------- scoring ------

def production_score(f) -> pd.DataFrame:
    """Vectorised services.picks_scoring.score_ticker INCLUDING the -20 floor
    for names not above SMA200 (production keeps them in the cross-section)."""
    atr = (f["atr_pct"] / 100.0).replace(0, np.nan)
    s = SCORE_CONST + (50.0 - f["rsi2"]) / W_OVERSOLD_DIV
    s = s + (-f["ret1"] / atr).clip(-W_PULLBACK_CLIP, W_PULLBACK_CLIP).fillna(0.0)
    s = s + W_ABOVE_SMA50 * (f["close"] > f["sma50"]).astype(float)
    s = s - W_WIDE_ATR_PEN * (f["atr_pct"] > WIDE_ATR_PCT).astype(float)
    up = (f["close"] > f["sma200"]) & f["sma200"].notna()
    s = s.where(up, np.minimum(s, UNTRENDED_FLOOR))
    # production rounds the score to 2 dp (picks_scoring.py) -- keep the twin faithful
    return s.where(f["sma50"].notna()).round(2)


def pct_rank(df: pd.DataFrame) -> pd.DataFrame:
    """Row-wise twin of picks_scoring._pct_rank: ties averaged, 0..1, NaN->0.5."""
    r = df.rank(axis=1, method="average")
    n = df.notna().sum(axis=1)
    out = (r - 1).div((n - 1).replace(0, np.nan), axis=0)
    out = out.where(df.notna())
    out = out.fillna(0.5)
    out[n < 2] = 0.5
    return out.where(df.notna() | True)


def production_rank(score: pd.DataFrame, obv: pd.DataFrame, universe: pd.DataFrame):
    """rank_score as Stage E computes it: blend over the WHOLE built universe."""
    s = score.where(universe)
    o = obv.where(universe & obv.notna())
    rs = pct_rank(s)
    ro = pct_rank(o)
    blend = W_RANK_SCORE * rs + W_RANK_OBV * ro
    # production stores rank_score rounded to 4 dp (picks_universe_service Stage E)
    return blend.where(universe & s.notna()).round(4)


def topk(key: pd.DataFrame, k: int, tiebreak: pd.DataFrame | None = None) -> pd.DataFrame:
    """Boolean frame: the k largest `key` per row (ties -> tiebreak desc -> symbol)."""
    kk = key.copy()
    if tiebreak is not None:
        # tiny, strictly monotone nudge; key values are ranks in 0..1 or scores
        tb = tiebreak.rank(axis=1, pct=True).fillna(0) * 1e-9
        kk = kk + tb
    r = kk.rank(axis=1, ascending=False, method="first")
    return (r <= k) & kk.notna()


# ------------------------------------------------------------- stats --------

def nw_t(x: pd.Series, lag: int) -> float:
    x = pd.Series(x).dropna().values
    n = len(x)
    if n < 10:
        return float("nan")
    m = x.mean()
    e = x - m
    g0 = (e @ e) / n
    v = g0
    for L in range(1, min(lag, n - 1) + 1):
        w = 1 - L / (lag + 1)
        v += 2 * w * (e[L:] @ e[:-L]) / n
    se = np.sqrt(max(v, 1e-18) / n)
    return m / se


def per_trade(sel: pd.DataFrame, p, f, vn, h: int, elig: pd.DataFrame | None = None,
              start: str | None = None) -> pd.DataFrame:
    """Daily series (indexed by signal day) of: pick mean fwd return, NO-GATE
    universe mean, gated-universe mean, VNINDEX same window, n picks."""
    o, c = p["open"], p["close"]
    fwd = c.shift(-(1 + h)) / o.shift(-1) - 1.0
    vfwd = vn["close"].shift(-(1 + h)) / vn["open"].shift(-1) - 1.0
    if elig is None:
        elig = (f["dv20"] > MIN_DV) & f["sma50"].notna()
    ok = elig & fwd.notna()
    gated = ok & (f["close"] > f["sma200"])
    s = sel & ok
    df = pd.DataFrame({
        "pick": fwd.where(s).mean(axis=1),
        "n": s.sum(axis=1),
        "base": fwd.where(ok).mean(axis=1),
        "base_gated": fwd.where(gated).mean(axis=1),
        "vn": vfwd,
        "n_elig": ok.sum(axis=1),
    })
    df = df[df["n_elig"] >= 30]
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    return df


def summarize_trades(df: pd.DataFrame, h: int, label: str) -> dict:
    d = df.dropna(subset=["pick"])
    out = {"rule": label, "h": h, "days": len(d), "days_with_picks_frac": len(d) / max(len(df), 1),
           "pick": d["pick"].mean(), "net": d["pick"].mean() - TOTAL_COST}
    for b in ("base", "base_gated", "vn"):
        e = d["pick"] - d[b]
        out[f"ex_{b}"] = e.mean()
        out[f"t_{b}"] = nw_t(e, h)
        # non-overlapping subsample (every h+1-th signal day), averaged over offsets
        ts = []
        for off in range(h + 1):
            sub = e.iloc[off::h + 1].dropna()
            if len(sub) > 5:
                ts.append(sub.mean() / (sub.std(ddof=1) / np.sqrt(len(sub))))
        out[f"tno_{b}"] = float(np.mean(ts)) if ts else float("nan")
        by = e.groupby(e.index.year).mean()
        out[f"yr_{b}"] = {int(y): round(v * 100, 2) for y, v in by.items()}
    return out


# ---------------------------------------------------- staggered portfolio ---

def jt_portfolio(sel: pd.DataFrame, p, vn, h: int, cost: float = TOTAL_COST,
                 exit_rule=None, f=None, park: str = "cash") -> pd.Series:
    """Daily returns of a Jegadeesh-Titman portfolio.

    Signal day t -> buy the selected names at open(t+1), equal weight, hold to
    close(t+1+h) (h+1 trading days incl. entry day). Capital is split in h+1
    tranches, one opened per day; a day with no picks leaves its tranche in cash.
    Round-trip cost is charged on the entry day of the tranche.

    exit_rule(j, i_entry, i_now, path_close, entry_px, f) -> bool can close a
    position early at the NEXT open (production acts on an after-close alert);
    freed capital is parked in cash or VNINDEX until the tranche slot ends.
    """
    O = p["open"].values  # noqa: E741
    C = p["close"].values
    S = sel.values
    VC = vn["close"].values
    VO = vn["open"].values
    T, N = C.shape
    slots = h + 1
    # daily returns contributed by each tranche, accumulated per day
    acc = np.zeros(T)
    for t in range(T - 1):
        js = np.flatnonzero(S[t])
        i0 = t + 1
        i1 = min(t + 1 + h, T - 1)
        if js.size == 0 or i0 >= T:
            continue
        # value path of each position relative to entry (buy-and-hold weights)
        vals = []
        for j in js:
            e = O[i0, j]
            if not np.isfinite(e) or e <= 0:
                continue
            path = C[i0:i1 + 1, j] / e
            if not np.all(np.isfinite(path)):
                # forward-fill gaps (suspended days)
                s_ = pd.Series(path).ffill().fillna(1.0).values
                path = s_
            if exit_rule is not None:
                for k in range(len(path) - 1):
                    if exit_rule(j, i0, i0 + k, C[i0:i0 + k + 1, j], e, f):
                        # sell at next open
                        xo = O[i0 + k + 1, j]
                        xv = (xo / e) if np.isfinite(xo) and xo > 0 else path[k]
                        rest = len(path) - (k + 1)
                        if park == "vnindex":
                            base = VO[i0 + k + 1]
                            tail = xv * VC[i0 + k + 1:i0 + k + 1 + rest] / base
                        else:
                            tail = np.full(rest, xv)
                        path = np.concatenate([path[:k + 1], tail])
                        break
            vals.append(path)
        if not vals:
            continue
        v = np.mean(np.vstack(vals), axis=0)          # tranche value path
        prev = np.concatenate([[1.0], v[:-1]])
        r = v / prev - 1.0
        r[0] -= cost                                  # round trip charged at entry
        acc[i0:i0 + len(r)] += r / slots
    return pd.Series(acc, index=p["close"].index)


def perf(r: pd.Series, start=None, end=None) -> dict:
    r = r.copy()
    if start:
        r = r[r.index >= pd.Timestamp(start)]
    if end:
        r = r[r.index <= pd.Timestamp(end)]
    eq = (1 + r).cumprod()
    yrs = len(r) / 252
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    vol = r.std() * np.sqrt(252)
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    by = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1)
    return {"cagr": cagr, "vol": vol, "sharpe": sharpe, "maxdd": dd,
            "by_year": {int(y): round(v * 100, 1) for y, v in by.items()}}


def vn_daily(vn) -> pd.Series:
    return vn["close"].pct_change().fillna(0.0)
