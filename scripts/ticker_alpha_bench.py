"""Cross-sectional ticker-ranking bench: does a ranking rule beat picking at random?

The system has never measured its per-ticker picks. `picks_scoring.score_ticker`
is a hand-built 0..7 trend score that nobody has scored against a base rate, and
the picks are then tie-broken by dollar volume, which systematically selects the
largest and slowest name inside each score bucket.

This is the ticker-level twin of `stealth_leadtime_experiment.py`, and it carries
the same discipline CLAUDE.md 16.12 forced on the sector gate:

  * EVERY run prints the BASE RATE row -- the equal-weight eligible universe over
    the same entry/exit window. A rule that does not beat that row is not a
    signal, whatever its absolute return looks like.
  * Results are split BY YEAR. Pooling is what let the sector gate's pre-2026
    strength mask a 2026 that matched random.
  * Returns are net of the 18.2/10 cost stack, imported from config, never
    retyped.
  * Entry is the NEXT session's open. The report goes out after the close; you
    cannot buy the close you ranked on.
  * Exit is h sessions after entry, and h >= BACKTEST_SETTLEMENT_LAG, because
    T+2 means a position opened on day d cannot be sold before d+2.

Usage:
    python scripts/ticker_alpha_bench.py
    python scripts/ticker_alpha_bench.py --topk 5 --min-dv 5e6 --horizons 2,3,5
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

PANEL_DB = ROOT / "data" / "price_panel.db"

from config import (  # noqa: E402
    BACKTEST_FEE_BPS,
    BACKTEST_SELL_TAX_BPS,
    BACKTEST_SETTLEMENT_LAG,
    BACKTEST_SLIPPAGE_MIN_PCT,
)

ROUND_TRIP = (2 * BACKTEST_FEE_BPS + BACKTEST_SELL_TAX_BPS) / 10_000.0
SLIPPAGE = 2 * BACKTEST_SLIPPAGE_MIN_PCT          # paid on the way in and out
TOTAL_COST = ROUND_TRIP + SLIPPAGE

HORIZONS = (2, 3, 5, 10, 20)


# ============================== panel ========================================

def load_panel(min_history: int = 260) -> dict[str, pd.DataFrame]:
    con = sqlite3.connect(PANEL_DB)
    # "^" prefixes an index (^VNINDEX). It lives in the same table so the
    # benchmark shares the panel's calendar, but it is not a tradeable name and
    # must never enter a cross-section.
    df = pd.read_sql(
        "SELECT symbol, time, open, high, low, close, volume FROM prices "
        "WHERE close > 0 AND symbol NOT LIKE '^%' ORDER BY time",
        con, parse_dates=["time"])
    con.close()
    n = df.groupby("symbol")["close"].count()
    df = df[df["symbol"].isin(n[n >= min_history].index)]
    out = {}
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = df.pivot(index="time", columns="symbol", values=col).sort_index()
    return out


# ============================== indicators ===================================

def _rsi(close: pd.DataFrame, n: int) -> pd.DataFrame:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def _true_range(p: dict) -> pd.DataFrame:
    hi, lo, c = p["high"], p["low"], p["close"]
    pc = c.shift(1)
    return pd.concat([hi - lo, (hi - pc).abs(), (lo - pc).abs()]).groupby(level=0).max()


def _adx(p: dict, n: int = 14) -> pd.DataFrame:
    hi, lo = p["high"], p["low"]
    up, dn = hi.diff(), -lo.diff()
    plus = up.where((up > dn) & (up > 0), 0.0)
    minus = dn.where((dn > up) & (dn > 0), 0.0)
    atr = _true_range(p).ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, np.nan)
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def build_features(p: dict) -> dict[str, pd.DataFrame]:
    c, o, hi, lo, v = p["close"], p["open"], p["high"], p["low"], p["volume"]
    f: dict[str, pd.DataFrame] = {"close": c}
    f["sma20"] = c.rolling(20).mean()
    f["sma50"] = c.rolling(50).mean()
    f["sma200"] = c.rolling(200).mean()
    f["ret1"] = c.pct_change(1)
    f["ret5"] = c.pct_change(5)
    f["ret20"] = c.pct_change(20)
    f["ret60"] = c.pct_change(60)
    f["rsi14"] = _rsi(c, 14)
    f["rsi2"] = _rsi(c, 2)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    f["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
    f["adx14"] = _adx(p)
    f["atr_pct"] = _true_range(p).ewm(alpha=1 / 14, adjust=False).mean() / c * 100
    f["vr20"] = v / v.rolling(20).mean().replace(0, np.nan)
    f["dv20"] = (c * v).rolling(20).mean()
    f["std20"] = c.pct_change().rolling(20).std()
    sd = c.rolling(20).std()
    f["pctb"] = (c - (f["sma20"] - 2 * sd)) / (4 * sd).replace(0, np.nan)
    f["z20"] = (c - f["sma20"]) / sd.replace(0, np.nan)
    f["amihud"] = (c.pct_change().abs() / (c * v).replace(0, np.nan)).rolling(20).mean()
    f["hl_pos"] = (c - o) / (hi - lo + 1e-9)          # Kakushadze Alpha#101
    f["mkt_ret5"] = c.pct_change(5).mean(axis=1)      # equal-weight market
    f["gap"] = o / c.shift(1) - 1
    f["near_52w"] = c / c.rolling(252, min_periods=120).max()
    mkt1 = c.pct_change().mean(axis=1)
    f["ivol"] = c.pct_change().sub(mkt1, axis=0).rolling(20).std()
    obv = (np.sign(c.diff()) * v).fillna(0).cumsum()
    f["obv_chg20"] = obv.diff(20) / v.rolling(20).mean().replace(0, np.nan)
    return f


# ============================== factors ======================================
# Every factor returns a score frame. HIGHER = more attractive long.

FACTORS: dict = {}


def register(name):
    def deco(fn):
        FACTORS[name] = fn
        return fn
    return deco


@register("A_shipped_score")
def _shipped(f):
    """Exact replica of services.picks_scoring.score_ticker -- the live rule."""
    c = f["close"]
    s = pd.DataFrame(0.0, index=c.index, columns=c.columns)
    s += (c > f["sma20"]).astype(float)
    s += (c > f["sma50"]).astype(float)
    s += (f["macd_hist"] > 0).astype(float)
    s += (f["adx14"] > 20).astype(float)
    r = f["rsi14"]
    s += 2 * ((r >= 50) & (r <= 70)).astype(float)
    s -= 1 * (r > 70).astype(float)
    s += 1 * (r < 30).astype(float)
    vr = f["vr20"]
    s += 2 * (vr > 1.3).astype(float)
    s -= 1 * (vr < 0.7).astype(float)
    return s.where(f["sma50"].notna())


@register("A_shipped_score_dv")
def _shipped_dv(f):
    """The live rule AS ACTUALLY RANKED: sort by (score, dv_20d) descending."""
    return _shipped(f) + 0.5 * f["dv20"].rank(axis=1, pct=True)


@register("B_reversal_5d")
def _(f):
    """Jegadeesh 1990 / Lehmann 1990 short-term reversal: buy last week's losers."""
    return -f["ret5"]


@register("B_reversal_1d")
def _(f):
    return -f["ret1"]


@register("B_reversal_resid5")
def _(f):
    """Blitz/Huij/Lansdorp/Verbeek residual reversal: strip the market move first."""
    return -(f["ret5"].sub(f["mkt_ret5"], axis=0))


@register("C_rsi2")
def _(f):
    """Connors RSI(2) -- the canonical 3-5 session mean-reversion oscillator."""
    return -f["rsi2"]


@register("C_rsi2_above200")
def _(f):
    """Connors' full rule: oversold RSI(2), but only inside an uptrend."""
    return (-f["rsi2"]).where(f["close"] > f["sma200"])


@register("C_pctb")
def _(f):
    return -f["pctb"]


@register("C_z20")
def _(f):
    return -f["z20"]


@register("D_rev5_x_volsurge")
def _(f):
    """Gervais/Kaniel/Mingelgrin 2001: a selloff on heavy volume reverts harder."""
    return (-f["ret5"]) * f["vr20"].clip(0.3, 3.0)


@register("D_rev5_x_illiq")
def _(f):
    """Avramov/Chordia/Goyal 2006: reversal concentrates in illiquid names."""
    return (-f["ret5"]) * f["amihud"].rank(axis=1, pct=True)


@register("E_alpha101")
def _(f):
    """Kakushadze Alpha#101: (close-open)/(high-low), intraday close strength."""
    return f["hl_pos"]


@register("E_alpha101_rev")
def _(f):
    return -f["hl_pos"]


@register("F_mom20")
def _(f):
    return f["ret20"]


@register("F_mom60")
def _(f):
    return f["ret60"]


@register("G_lowvol")
def _(f):
    return -f["std20"]


@register("H_combo_rev_trend")
def _(f):
    """Reversal inside an uptrend, blended by RANK so no single scale dominates."""
    r = (-f["ret5"]).rank(axis=1, pct=True)
    q = (-f["rsi2"]).rank(axis=1, pct=True)
    t = (f["close"] / f["sma50"]).rank(axis=1, pct=True)
    return (0.4 * r + 0.4 * q + 0.2 * t).where(f["close"] > f["sma200"])


# --- second pass: the crash tail, and composites of what actually had IC ------

@register("B_rev5_trimmed")
def _(f):
    """Reversal with the crash tail cut out.

    Plain 5d reversal has the highest IC of any single factor here and yet its
    top-5 makes nothing -- the classic signature of a toxic extreme: the very
    worst weekly losers are down on news, not on liquidity demand, and they keep
    falling. Buy the moderate losers, not the free-fallers.
    """
    return (-f["ret5"]).where(f["ret5"] > -0.12)


@register("O_rev5_no_floor")
def _(f):
    """Reversal excluding names that sat on the +-7% HOSE band yesterday.

    A floor-locked name cannot be bought at any size and a ceiling-locked one
    gaps away from you -- 18.2/9 already models this in the backtest; the
    ranking never knew about it."""
    band = f["ret1"].abs() > 0.065
    return (-f["ret5"]).where(~band)


@register("K_gap_reversal")
def _(f):
    """Overnight gap reversal: fade the open, a pure liquidity-demand effect."""
    return -f["gap"]


@register("L_dist_52w_high")
def _(f):
    """George & Hwang 2004 52-week-high proximity (a momentum proxy)."""
    return f["near_52w"]


@register("M_ivol_low")
def _(f):
    """Ang/Hodrick/Xing/Zhang 2006: low idiosyncratic vol earns more."""
    return -f["ivol"]


@register("I_comp_rev_qual")
def _(f):
    """Equal-weight rank blend of every single factor that showed a positive,
    t>4 information coefficient at the T+2/T+3 horizon: RSI(2) oversold,
    one-day reversal, low realised vol, and a weak close (Alpha#101 reversed).
    Ranks, not raw values, so no one scale dominates the blend."""
    parts = [(-f["rsi2"]), (-f["ret1"]), (-f["std20"]), (-f["hl_pos"])]
    return sum(x.rank(axis=1, pct=True) for x in parts) / len(parts)


@register("I_comp_rev_qual_nofloor")
def _(f):
    """The same blend, with the +-7% band names dropped."""
    parts = [(-f["rsi2"]), (-f["ret1"]), (-f["std20"]), (-f["hl_pos"])]
    s = sum(x.rank(axis=1, pct=True) for x in parts) / len(parts)
    return s.where(f["ret1"].abs() <= 0.065)


@register("I_comp_rsi2_lowvol")
def _(f):
    """The two strongest halves of the blend on their own."""
    return ((-f["rsi2"]).rank(axis=1, pct=True)
            + (-f["std20"]).rank(axis=1, pct=True)) / 2


# --- candidates for what actually ships -------------------------------------
# These must be ELEMENTWISE: `picks_scoring.score_ticker` scores one ticker from
# one dict and has no cross-section to rank inside. Every term is therefore
# expressed either as an absolute oscillator reading or in units of the stock's
# OWN ATR, which self-normalises scale without needing the panel.

def _proposed(f, *, trend_gate: bool, vol_penalty: bool):
    """Vectorised twin of services.picks_scoring.score_ticker.

    The COEFFICIENTS are imported, never retyped. Two copies of a formula are
    two formulas and they drift without anyone noticing -- the bench would go
    on reporting a number the product had stopped using. `tests/
    test_picks_scoring_v2.py::test_the_bench_and_the_service_agree_row_by_row`
    pins the two implementations to the same answer on real panel rows.
    """
    from services.picks_scoring import (
        SCORE_CONST, W_ABOVE_SMA50, W_OVERSOLD_DIV, W_PULLBACK_CLIP,
        W_WIDE_ATR_PEN, WIDE_ATR_PCT,
    )
    atr = (f["atr_pct"] / 100.0).replace(0, np.nan)
    s = SCORE_CONST + (50.0 - f["rsi2"]) / W_OVERSOLD_DIV
    s = s + (-f["ret1"] / atr).clip(-W_PULLBACK_CLIP, W_PULLBACK_CLIP)
    s = s + W_ABOVE_SMA50 * (f["close"] > f["sma50"]).astype(float)
    if vol_penalty:
        s = s - W_WIDE_ATR_PEN * (f["atr_pct"] > WIDE_ATR_PCT).astype(float)
    if trend_gate:
        s = s.where(f["close"] > f["sma200"])
    return s.where(f["sma50"].notna())


@register("P1_proposed_gated")
def _(f):
    return _proposed(f, trend_gate=True, vol_penalty=False)


@register("P2_proposed_gated_quiet")
def _(f):
    return _proposed(f, trend_gate=True, vol_penalty=True)


@register("P3_proposed_ungated")
def _(f):
    return _proposed(f, trend_gate=False, vol_penalty=True)


@register("P4_oversold_only_gated")
def _(f):
    return ((50.0 - f["rsi2"]) / 10.0).where(f["close"] > f["sma200"])


@register("P5_proposed_with_obv")
def _(f):
    """P2 plus an on-balance-volume term, expressed PER ROW.

    `X_prop_obv` measured better than P2 at every horizon, but it is a rank
    blend and `picks_scoring.score_ticker` scores one ticker with no
    cross-section to rank inside. `obv_chg20` is already divided by the name's
    own 20d average volume, so it is comparable across names without ranking:
    sd 5.3, p1/p99 at -11.6/+12.5. Dividing by 5 and clipping at +-2 puts it on
    the same scale as the other terms (oversold +-5, pullback +-2, SMA50 +2,
    ATR penalty -1.5) rather than letting it dominate them.
    """
    return _proposed(f, trend_gate=True, vol_penalty=True) + \
        (f["obv_chg20"] / 5.0).clip(-2.0, 2.0)


# --- 2026-09-16 (2): leads taken from the literature, tested here ------------
# Sources are named so a later reader can tell which claim each one is, and
# every one of them is scored against the same base rate as everything above.
# A published coefficient on a different sample is a hypothesis, not evidence.

@register("S_small_size")
def _(f):
    """Size. `Factors and anomalies in the Vietnamese stock market` (Pacific-Basin
    Finance Journal 82, 2023) reports ln(ME) at -0.11, p<0.01, in Fama-MacBeth
    on HOSE/HNX -- the strongest characteristic in their table. No market cap in
    this panel, so 20d dollar volume is the proxy; inside a liquidity-filtered
    universe the two are tightly related.

    Directly relevant to what shipped today: the old tie-break sorted toward
    LARGE, which this says is the wrong sign."""
    return -f["dv20"].rank(axis=1, pct=True)


@register("S_proposed_plus_small")
def _(f):
    """The shipped score with a small-size tilt added by rank."""
    base = FACTORS["P2_proposed_gated_quiet"](f)
    return base.rank(axis=1, pct=True) - 0.5 * f["dv20"].rank(axis=1, pct=True)


@register("R_resid_mom20")
def _(f):
    """Residual momentum (Blitz/Huij/Martens 2011): rank on the part of the
    20d return the market does not explain. Plain momentum was flat here; the
    claim is that stripping market beta sharpens it."""
    return f["ret20"].sub(f["ret20"].mean(axis=1), axis=0)


@register("R_resid_mom60")
def _(f):
    return f["ret60"].sub(f["ret60"].mean(axis=1), axis=0)


@register("V_obv_trend")
def _(f):
    """On-balance-volume slope: volume signed by the day's direction,
    accumulated, then its 20d change. Money-flow persistence at ticker level --
    the same thing 16 looks for at sector level."""
    return f["obv_chg20"]


# --- combinations, for the 2-4 week horizon Tom authorised on 2026-09-16 -----
# Every one is a RANK blend so no single scale dominates, and each is scored
# within-year at the horizon it is meant for. Weights are round numbers on
# purpose: a fitted weight vector on 1,100 days is a curve fit nobody could
# defend, which is the argument 16.1 already made about condition weights.

def _blend(f, parts, gate=True):
    s = sum(w * x.rank(axis=1, pct=True) for w, x in parts)
    return s.where(f["close"] > f["sma200"]) if gate else s


@register("X_small_obv")
def _(f):
    return _blend(f, [(0.5, -f["dv20"]), (0.5, f["obv_chg20"])], gate=False)


@register("X_prop_small_obv")
def _(f):
    return _blend(f, [(0.4, FACTORS["P2_proposed_gated_quiet"](f)),
                      (0.3, -f["dv20"]), (0.3, f["obv_chg20"])], gate=False)


@register("X_prop_obv")
def _(f):
    """THE SHIPPED ORDERING. Calls `picks_scoring.blended_rank_scores` itself,
    day by day, rather than reimplementing the blend in pandas.

    It is slower than a vectorised copy and that is the point: the bench and the
    product must be one implementation, or the bench keeps reporting a number
    the product has stopped using (22.11). `test_the_bench_ordering_is_the_
    shipped_function` pins the call site.
    """
    from services.picks_scoring import blended_rank_scores

    base = FACTORS["P2_proposed_gated_quiet"](f)
    obv = f["obv_chg20"]
    out = pd.DataFrame(np.nan, index=base.index, columns=base.columns)
    for i in range(len(base)):
        srow = base.iloc[i]
        orow = obv.iloc[i]
        live = srow.notna()
        if live.sum() < 2:
            continue
        cols = srow.index[live]
        blended = blended_rank_scores(
            [float(srow[c]) for c in cols],
            [(None if pd.isna(orow[c]) else float(orow[c])) for c in cols])
        out.iloc[i, [out.columns.get_loc(c) for c in cols]] = blended
    return out


@register("X_swing_4wk")
def _(f):
    """Candidate for a 2-4 week shortlist: money-flow persistence (OBV), a size
    tilt toward the smaller half, residual 20d momentum, and the oversold
    entry-timing term that the 3-session work established -- all gated on an
    intact uptrend."""
    return _blend(f, [
        (0.30, f["obv_chg20"]),
        (0.25, -f["dv20"]),
        (0.25, f["ret20"].sub(f["ret20"].mean(axis=1), axis=0)),
        (0.20, -f["rsi2"]),
    ])


@register("Y_shipped_plus_small")
def _(f):
    """SHIPPED ordering + the VN-4 size tilt, at the horizon that now matters.

    `Factors and anomalies in the Vietnamese stock market` (Pacific-Basin Finance
    Journal 82, 2023) puts ln(ME) at -0.11, p<0.01. An earlier test added size to
    the per-row score alone and it failed 2025. This asks the question again
    against what actually ships, which is a different baseline.
    """
    base = FACTORS["X_prop_obv"](f)
    return (base.rank(axis=1, pct=True)
            - 0.5 * f["dv20"].rank(axis=1, pct=True))


@register("Y_shipped_plus_small_light")
def _(f):
    base = FACTORS["X_prop_obv"](f)
    return (base.rank(axis=1, pct=True)
            - 0.25 * f["dv20"].rank(axis=1, pct=True))


# ============================== evaluation ===================================

NQ = 5  # quintiles -- 18.7 wants monotonicity across score buckets


def evaluate(scores, f, p, topk, min_dv, horizons=HORIZONS, min_names=30) -> dict:
    o, c = p["open"], p["close"]
    elig = (f["dv20"] > min_dv) & scores.notna() & o.shift(-1).notna()
    s = scores.where(elig)
    entry = o.shift(-1)
    dates = s.index

    out = {}
    for h in horizons:
        fwd = c.shift(-(1 + h)) / entry - 1.0
        rows, ics, quints = [], [], []
        for i in range(len(dates) - (h + 2)):
            row_s, row_f = s.iloc[i], fwd.iloc[i]
            m = row_s.notna() & row_f.notna()
            # A cross-section narrower than this is not a ranking problem.
            # The panel is only ~21 names wide before 2025; letting those days
            # through means "top 5 of 21", which is a quarter of the market.
            if m.sum() < min_names:
                continue
            ics.append(row_s[m].rank().corr(row_f[m].rank()))
            top = row_s[m].nlargest(topk).index
            rows.append((dates[i], row_f[top].mean(), row_f[m].mean(),
                         float((row_f[top] > 0).mean())))
            q = pd.qcut(row_s[m].rank(method="first"), NQ, labels=False)
            quints.append(row_f[m].groupby(q).mean())
        if not rows:
            continue
        d = pd.DataFrame(rows, columns=["date", "pick", "base", "hit"]).set_index("date")
        qdf = pd.DataFrame(quints)
        ic = float(np.nanmean(ics))
        sd = float(np.nanstd(ics))
        out[h] = {
            "n_days": len(d),
            "pick_gross": d["pick"].mean(),
            "base_gross": d["base"].mean(),
            "excess": d["pick"].mean() - d["base"].mean(),
            "pick_net": d["pick"].mean() - TOTAL_COST,
            "hit": d["hit"].mean(),
            "ic": ic,
            "ic_t": ic / (sd / np.sqrt(len(ics))) if sd > 0 and len(ics) > 2 else np.nan,
            "quintiles": qdf.mean(),
            "by_year": d.groupby(d.index.year).apply(
                lambda g: pd.Series({"excess": g["pick"].mean() - g["base"].mean(),
                                     "n": float(len(g))})),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--min-dv", type=float, default=5e6)
    ap.add_argument("--only", default="")
    ap.add_argument("--horizons", default="2,3,5,10,20")
    args = ap.parse_args()

    horizons = tuple(int(x) for x in args.horizons.split(","))
    bad = [h for h in horizons if h < BACKTEST_SETTLEMENT_LAG]
    if bad:
        print(f"refusing horizons {bad}: T+{BACKTEST_SETTLEMENT_LAG} settlement means "
              f"a position cannot be sold sooner than {BACKTEST_SETTLEMENT_LAG} sessions "
              f"after entry.", file=sys.stderr)
        return 2

    p = load_panel()
    print(f"panel: {p['close'].shape[1]} symbols x {p['close'].shape[0]} sessions "
          f"({p['close'].index.min().date()} .. {p['close'].index.max().date()})")
    print(f"cost: round-trip {ROUND_TRIP*100:.2f}% + slippage {SLIPPAGE*100:.2f}% "
          f"= {TOTAL_COST*100:.2f}%   |  T+{BACKTEST_SETTLEMENT_LAG} settlement honoured")
    f = build_features(p)

    names = [n for n in FACTORS if not args.only or n in args.only.split(",")]
    results = {n: evaluate(FACTORS[n](f), f, p, args.topk, args.min_dv, horizons)
               for n in sorted(names)}

    for h in horizons:
        print(f"\n{'=' * 104}")
        print(f"EXIT +{h} SESSIONS AFTER ENTRY   (entry = next open, top-{args.topk}, "
              f"min dv {args.min_dv:,.0f})")
        print("=" * 104)
        print(f"{'factor':26s} {'gross%':>8s} {'net%':>8s} {'BASE%':>8s} "
              f"{'excess%':>9s} {'hit':>6s} {'IC':>8s} {'IC_t':>7s} {'days':>6s}")
        printed_base = False
        rows = []
        for n in sorted(names):
            r = results[n].get(h)
            if not r:
                continue
            if not printed_base:
                print(f"{'BASE RATE (no ranking)':26s} {r['base_gross']*100:>8.2f} "
                      f"{r['base_gross']*100 - TOTAL_COST*100:>8.2f} "
                      f"{r['base_gross']*100:>8.2f} {0.0:>+9.2f} {'':>6s} {'':>8s} "
                      f"{'':>7s} {r['n_days']:>6d}")
                printed_base = True
            rows.append((r["excess"], n, r))
        for _, n, r in sorted(rows, key=lambda t: -t[0]):
            print(f"{n:26s} {r['pick_gross']*100:>8.2f} {r['pick_net']*100:>8.2f} "
                  f"{r['base_gross']*100:>8.2f} {r['excess']*100:>+9.2f} "
                  f"{r['hit']:>6.2f} {r['ic']:>+8.4f} {r['ic_t']:>+7.2f} "
                  f"{r['n_days']:>6d}")

    h0 = horizons[0]
    print(f"\n{'=' * 104}")
    print(f"QUINTILE MEAN FORWARD RETURN %, exit +{h0}  "
          f"(18.7: a real factor is monotone Q1 -> Q5; Q5 is what gets bought)")
    print("=" * 104)
    print(f"{'factor':26s} " + " ".join(f"{'Q'+str(i+1):>8s}" for i in range(NQ))
          + f" {'Q5-Q1':>9s}")
    qrows = []
    for n in sorted(names):
        r = results[n].get(h0)
        if not r:
            continue
        q = r["quintiles"]
        qrows.append((q.iloc[-1] - q.iloc[0], n, q))
    for _, n, q in sorted(qrows, key=lambda t: -t[0]):
        mono = "  monotone" if list(q) == sorted(q) else ""
        print(f"{n:26s} " + " ".join(f"{v*100:>+8.2f}" for v in q)
              + f" {(q.iloc[-1]-q.iloc[0])*100:>+9.2f}{mono}")

    print(f"\n{'=' * 104}")
    print(f"WITHIN-YEAR EXCESS over base rate, exit +{h0}  "
          f"(16.12: pooling hides a recent stretch that matches random)")
    print("=" * 104)
    yrs = sorted({int(y) for n in names if results[n].get(h0)
                  for y in results[n][h0]["by_year"].index})
    print(f"{'factor':26s} " + " ".join(f"{y:>9d}" for y in yrs))
    for n in sorted(names):
        r = results[n].get(h0)
        if not r:
            continue
        by = r["by_year"]
        cells = [(f"{by.loc[y, 'excess'] * 100:>+9.2f}" if y in by.index else f"{'':>9s}")
                 for y in yrs]
        print(f"{n:26s} " + " ".join(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
