"""Event-style bench: entry rule + exit geometry, walked bar by bar.

The file name is historical: it was written on 2026-09-16 to measure the T+
(3-5 session) trade, and kept its name when that mode was removed on 2026-09-25
(Tom: "bỏ T+2, chỉ sử dụng 4 tuần và 8 tuần") because docs point at it. It now
measures only 20- and 40-session holds -- config.HOLD_SESSIONS.

`ticker_alpha_bench.py` ranks the cross-section and exits on a fixed clock. That
is the right shape for measuring a factor and the wrong shape for measuring an
exit rule: a price level (target, stop, trailing band) ends the trade at
whichever comes first, and a fixed-clock exit cannot see which one fires.

So this walks each trade forward bar by bar:

    entry  = next session's OPEN (the report is written after the close)
    exit   = first of  (high >= target) | (low <= stop) | max_hold sessions
    a session touching both is booked as a STOP  (conservative; no intrabar path)

and every variant is scored against a RANDOM-ENTRY CONTROL drawn from the same
eligible universe on the same dates with the same geometry. 16.12's rule applies
here too: a rule that does not beat its own control is not a rule.

Usage:
    python scripts/tplus_strategy_bench.py                 # 40 sessions
    python scripts/tplus_strategy_bench.py --max-hold 20 --trail
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PANEL_DB = ROOT / "data" / "price_panel.db"

from analysis.bench import SLIPPAGE_BPS_PER_SIDE  # noqa: E402
from config import BACKTEST_FEE_BPS, BACKTEST_SELL_TAX_BPS, HOLD_SESSIONS  # noqa: E402
from scripts.ticker_alpha_bench import build_features, load_panel  # noqa: E402

FEE_ROUND_TRIP = (2 * BACKTEST_FEE_BPS + BACKTEST_SELL_TAX_BPS) / 10_000.0


# ============================ entry rules ====================================
# Each returns a boolean frame: True where a long is opened at the next open.

RULES: dict = {}


def rule(name):
    def deco(fn):
        RULES[name] = fn
        return fn
    return deco


@rule("shipped_score_ge5")
def _(f):
    """What ships today: the 0..7 trend score, taken where it is strong."""
    from scripts.ticker_alpha_bench import FACTORS
    return FACTORS["A_shipped_score"](f) >= 5


@rule("shipped_score_top5")
def _(f):
    """What ships today, ranked: the 5 highest (score, dv) names each day."""
    from scripts.ticker_alpha_bench import FACTORS
    s = FACTORS["A_shipped_score_dv"](f)
    return s.rank(axis=1, ascending=False) <= 5


@rule("rsi2_oversold")
def _(f):
    """Connors RSI(2) < 10 -- the canonical short-horizon entry."""
    return f["rsi2"] < 10


@rule("rsi2_oversold_uptrend")
def _(f):
    """Connors' full published rule: RSI(2) < 10 AND price above its SMA200."""
    return (f["rsi2"] < 10) & (f["close"] > f["sma200"])


@rule("rsi2_uptrend_quiet")
def _(f):
    """The same, restricted to names whose 20d vol is in the calmer half.

    ATR sets the target and stop distance, so a wild name gets a wide target it
    cannot reach inside the hold. Quiet names make the geometry reachable."""
    quiet = f["std20"].rank(axis=1, pct=True) < 0.5
    return (f["rsi2"] < 10) & (f["close"] > f["sma200"]) & quiet


@rule("comp_top5")
def _(f):
    """Top 5 of the composite the ranking bench picked: RSI(2) + 1d reversal +
    low vol + weak close, blended by rank."""
    from scripts.ticker_alpha_bench import FACTORS
    s = FACTORS["I_comp_rev_qual"](f)
    return s.rank(axis=1, ascending=False) <= 5


@rule("comp_top5_uptrend")
def _(f):
    from scripts.ticker_alpha_bench import FACTORS
    s = FACTORS["I_comp_rev_qual"](f).where(f["close"] > f["sma200"])
    return s.rank(axis=1, ascending=False) <= 5


@rule("comp_top3_uptrend")
def _(f):
    from scripts.ticker_alpha_bench import FACTORS
    s = FACTORS["I_comp_rev_qual"](f).where(f["close"] > f["sma200"])
    return s.rank(axis=1, ascending=False) <= 3


@rule("proposed_top5")
def _(f):
    """The candidate for `picks_scoring.score_ticker`: oversold RSI(2) plus a
    one-day drop measured in the stock's own ATRs, above SMA50, penalised for a
    wide ATR, gated on SMA200. Top 5 each session."""
    from scripts.ticker_alpha_bench import FACTORS
    s = FACTORS["P2_proposed_gated_quiet"](f)
    return s.rank(axis=1, ascending=False) <= 5


@rule("proposed_top3")
def _(f):
    from scripts.ticker_alpha_bench import FACTORS
    s = FACTORS["P2_proposed_gated_quiet"](f)
    return s.rank(axis=1, ascending=False) <= 3


@rule("shipped_rule_top5")
def _(f):
    """THE BUY RULE AS SHIPPED since 2026-09-25 (`long_shortlist`): SMA200 gate,
    then the production rank blend over the whole liquid universe. Top 5."""
    from scripts.ticker_alpha_bench import FACTORS
    return FACTORS["X_shipped_rule"](f).rank(axis=1, ascending=False) <= 5


@rule("swing_prop_obv_top5")
def _(f):
    """2-4 week candidate: the shipped score blended with on-balance-volume
    trend. Best information coefficient of anything measured (t = 4.3 at +20)
    and positive in every year it can be evaluated."""
    from scripts.ticker_alpha_bench import FACTORS
    return FACTORS["X_prop_obv"](f).rank(axis=1, ascending=False) <= 5


@rule("swing_prop_small_obv_top5")
def _(f):
    """The same plus a size tilt. Higher pooled return, but 2025 is negative --
    which is the whole reason 16.12 asks for the within-year split."""
    from scripts.ticker_alpha_bench import FACTORS
    return FACTORS["X_prop_small_obv"](f).rank(axis=1, ascending=False) <= 5


@rule("swing_obv_only_top5")
def _(f):
    from scripts.ticker_alpha_bench import FACTORS
    return FACTORS["V_obv_trend"](f).rank(axis=1, ascending=False) <= 5


@rule("pullback_in_uptrend")
def _(f):
    """A plain, well-worn swing entry: uptrend intact (above SMA50 and SMA200),
    price pulled back below its SMA20, and the tape is not in free fall."""
    return ((f["close"] > f["sma50"]) & (f["close"] > f["sma200"])
            & (f["close"] < f["sma20"]) & (f["ret5"] > -0.10))


# ============================ geometry =======================================

GEOMETRIES = {
    # name:            (target_atr, stop_atr)   -- ATR multiples, as picks_scoring does
    "SWING 2.5/1.8 (screening geometry)": (2.5, 1.8),
    "tight 1.0/1.0": (1.0, 1.0),
    "tight 1.2/0.8": (1.2, 0.8),
    "wide-stop 1.5/2.5": (1.5, 2.5),
    "wide-stop 2.0/3.0": (2.0, 3.0),
    "no stop, time exit": (99.0, 99.0),
}


def run(entries: pd.DataFrame, f: dict, p: dict, *, target_atr: float,
        stop_atr: float, max_hold: int, min_dv: float,
        cost: float) -> pd.DataFrame:
    op, hi, lo, cl = p["open"], p["high"], p["low"], p["close"]
    atr = f["atr_pct"] / 100.0
    elig = (f["dv20"] > min_dv) & entries.fillna(False) & atr.notna()

    OP, HI, LO, CL = op.values, hi.values, lo.values, cl.values
    A = atr.values
    E = elig.values
    dates = op.index
    syms = list(op.columns)

    out = []
    n_t = len(dates)
    for i in range(n_t - max_hold - 2):
        row = np.flatnonzero(E[i])
        if row.size == 0:
            continue
        for j in row:
            entry = OP[i + 1, j]
            a = A[i, j]
            if not np.isfinite(entry) or entry <= 0 or not np.isfinite(a) or a <= 0:
                continue
            tgt = entry * (1 + target_atr * a)
            stp = entry * (1 - stop_atr * a)
            held, px, why = max_hold, CL[i + max_hold, j], "time"
            for k in range(1, max_hold + 1):
                bar_hi, bar_lo, bar_op = HI[i + k, j], LO[i + k, j], OP[i + k, j]
                if np.isfinite(bar_lo) and bar_lo <= stp:  # stop first: no intrabar path
                    # A session that OPENS through the level fills at the open,
                    # not at the level (2026-09-25, same fix as run_trail).
                    gap = np.isfinite(bar_op) and bar_op <= stp
                    held, px, why = k, (bar_op if gap else stp), "stop"
                    break
                if np.isfinite(bar_hi) and bar_hi >= tgt:
                    gap = np.isfinite(bar_op) and bar_op >= tgt
                    held, px, why = k, (bar_op if gap else tgt), "target"
                    break
            if not np.isfinite(px):
                continue
            out.append((dates[i], syms[j], entry, px / entry - 1 - cost, held, why))
    return pd.DataFrame(out, columns=["date", "symbol", "entry", "ret", "held", "exit"])


def random_control(entries: pd.DataFrame, f: dict, p: dict, seed: int = 7, **kw):
    """Same number of trades, same days, same geometry -- names drawn at random
    from the eligible universe. This is the base rate 16.12 demands."""
    rng = np.random.default_rng(seed)
    per_day = entries.fillna(False).sum(axis=1)
    pool = (f["dv20"] > kw["min_dv"]) & f["atr_pct"].notna()
    fake = pd.DataFrame(False, index=entries.index, columns=entries.columns)
    for d, k in per_day[per_day > 0].items():
        cand = pool.columns[pool.loc[d].values]
        if len(cand) == 0:
            continue
        pick = rng.choice(cand, size=min(int(k), len(cand)), replace=False)
        fake.loc[d, pick] = True
    return run(fake, f, p, **kw)


def summarise(t: pd.DataFrame, label: str, years: float) -> dict:
    if t.empty:
        return {"label": label, "n": 0}
    return {
        "label": label,
        "n": len(t),
        "per_yr": len(t) / years,
        "mean": t["ret"].mean() * 100,
        "median": t["ret"].median() * 100,
        "win": (t["ret"] > 0).mean(),
        "held": t["held"].mean(),
        "tgt": (t["exit"] == "target").mean(),
        "stp": (t["exit"] == "stop").mean(),
        "exit_band": (t["exit"].isin(["band", "gap", "trend"])).mean(),
        "total": t["ret"].sum() * 100,
        "by_year": t.groupby(t["date"].dt.year)["ret"].mean() * 100,
    }



# ---------------------------------------------------------------------------
# Range ban truot len (2026-09-16, theo yeu cau cua Tom: "bo stop nhung phai
# dua khuyen nghi range ban ... range co the thay doi theo thoi gian neu no van
# co song len").
#
# DAY KHONG PHAI STOP LO, va su khac biet la ca van de:
#   - stop lo  neo o GIA VAO, ton tai tu phien dau, gioi han khoan LO.
#   - range ban neo o DINH da dat duoc, chi ton tai SAU khi da lai >= arm_atr,
#     va gioi han phan NHA LAI. Truoc khi arm, lenh khong co muc thoat nao ca —
#     dung nghia "bo stop": mot lenh am khong bao gio bi quet ra.
#
# `hi_atr` la canh tren cua range (muc cang gia de ban vao). No khong phai dieu
# kien thoat trong phep do nay: khi con trend, dinh tu dich len nen canh tren
# cung dich len, va "ban vao canh tren" la mot quyet dinh cua nguoi doc chu
# khong phai mot luat co the do bang gia dong cua.
# ---------------------------------------------------------------------------

def run_trail(entries, f, p, *, lo_atr: float, max_hold: int, min_dv: float,
              cost: float, arm_atr: float = 1.0, trend_exit: bool = False,
              ) -> pd.DataFrame:
    """Walk each trade with a trailing band anchored at the peak CLOSE.

    Fixed 2026-09-25 (review 2026-09-24 §3.2), two look-aheads that made every
    band look 2-3x more expensive than it is, the tight ones most of all:
      - the peak was raised with bar k's CLOSE before bar k's LOW was compared
        with the band -- a strong session lifted the band, then "touched" it
        with a low printed earlier in that same session. The band on bar k is
        now set by the closes up to k-1 only, and the peak moves after;
      - a session that OPENED below the band was filled at the band. It is
        filled at the open now ("gap").
    """
    op, lo, cl = p["open"], p["low"], p["close"]
    atr = f["atr_pct"] / 100.0
    sma20 = f["sma20"]
    elig = (f["dv20"] > min_dv) & entries.fillna(False) & atr.notna()

    OP, LO, CL = op.values, lo.values, cl.values
    S20 = sma20.values
    A, E = atr.values, elig.values
    dates, syms = op.index, list(op.columns)

    out = []
    for i in range(len(dates) - max_hold - 2):
        row = np.flatnonzero(E[i])
        if row.size == 0:
            continue
        for j in row:
            entry, a = OP[i + 1, j], A[i, j]
            if not np.isfinite(entry) or entry <= 0 or not np.isfinite(a) or a <= 0:
                continue
            arm_at = entry * (1 + arm_atr * a)
            peak, armed = entry, False
            held, px, why = max_hold, CL[i + max_hold, j], "time"
            for k in range(1, max_hold + 1):
                c, low_k, open_k = CL[i + k, j], LO[i + k, j], OP[i + k, j]
                # Band and arming from the PRIOR closes: bar k's close is not
                # known when its low prints.
                if peak >= arm_at:
                    armed = True
                if armed:
                    band_lo = peak * (1 - lo_atr * a)
                    if np.isfinite(open_k) and open_k <= band_lo:
                        held, px, why = k, open_k, "gap"   # opened through it
                        break
                    if np.isfinite(low_k) and low_k <= band_lo:
                        held, px, why = k, band_lo, "band"
                        break
                    # Trend gay = ban, du chua cham canh duoi. Day la nghia cua
                    # "neu no van co song len" doc nguoc lai.
                    if trend_exit and np.isfinite(c) and np.isfinite(S20[i + k, j]) \
                            and c < S20[i + k, j]:
                        held, px, why = k, c, "trend"
                        break
                if np.isfinite(c):
                    peak = max(peak, c)
            if not np.isfinite(px):
                continue
            out.append((dates[i], syms[j], entry, px / entry - 1 - cost, held, why))
    return pd.DataFrame(out, columns=["date", "symbol", "entry", "ret", "held", "exit"])


def random_control_trail(entries, f, p, seed: int = 7, **kw):
    rng = np.random.default_rng(seed)
    per_day = entries.fillna(False).sum(axis=1)
    pool = (f["dv20"] > kw["min_dv"]) & f["atr_pct"].notna()
    fake = pd.DataFrame(False, index=entries.index, columns=entries.columns)
    for d, k in per_day[per_day > 0].items():
        cand = pool.columns[pool.loc[d].values]
        if len(cand) == 0:
            continue
        pick = rng.choice(cand, size=min(int(k), len(cand)), replace=False)
        fake.loc[d, pick] = True
    return run_trail(fake, f, p, **kw)


TRAIL_VARIANTS = {
    # ten                         (lo_atr, arm_atr, trend_exit)
    "khong stop, thoat theo gio":  (None,   None,   False),   # nen so sanh (26.10)
    "range nha 1.5xATR":           (1.5,    1.0,    False),
    "range nha 2.5xATR":           (2.5,    1.0,    False),
    "range nha 3.5xATR":           (3.5,    1.0,    False),
    "range nha 2.5 + arm 2.0":     (2.5,    2.0,    False),
    "range nha 2.5 + gay trend":   (2.5,    1.0,    True),
    "chi gay trend thi ban":       (99.0,   1.0,    True),
}


def main_trail(args, f, p, idx, years, cost) -> int:
    print(f"panel {p['close'].shape[1]} symbols, window {idx[0].date()} .. "
          f"{idx[-1].date()} ({years:.1f}y)")
    print(f"cost {cost*100:.2f}% round trip | max hold {args.max_hold} phien")
    print("KHONG co stop lo trong bat ky bien the nao duoi day: muc thoat chi ton "
          "tai SAU khi lenh da lai >= arm_atr x ATR.\n")

    rules = ({args.rule: RULES[args.rule]} if args.rule else RULES)
    for rname, fn in rules.items():
        ent = fn(f).fillna(False).astype(bool)
        ent.loc[ent.index < pd.Timestamp(args.start)] = False
        print("=" * 104)
        print(f"LUAT VAO LENH: {rname}   (max hold {args.max_hold})")
        print("=" * 104)
        print(f"{'hinh hoc thoat':30s} {'n':>6s} {'mean%':>7s} {'med%':>7s} "
              f"{'win':>6s} {'held':>5s} {'band%':>6s} {'excess':>7s}  theo nam")
        rows = []
        for vname, (lo_a, arm_a, tx) in TRAIL_VARIANTS.items():
            if lo_a is None:
                t = run(ent, f, p, target_atr=99.0, stop_atr=99.0,
                        max_hold=args.max_hold, min_dv=args.min_dv, cost=cost)
                c = random_control(ent, f, p, target_atr=99.0, stop_atr=99.0,
                                   max_hold=args.max_hold, min_dv=args.min_dv,
                                   cost=cost)
            else:
                kw = {"lo_atr": lo_a, "arm_atr": arm_a, "trend_exit": tx,
                      "max_hold": args.max_hold, "min_dv": args.min_dv, "cost": cost}
                t = run_trail(ent, f, p, **kw)
                c = random_control_trail(ent, f, p, **kw)
            st, sc = summarise(t, vname, years), summarise(c, vname, years)
            if not st["n"]:
                continue
            st["excess"] = st["mean"] - sc["mean"]
            st["ctrl_by_year"] = sc["by_year"]
            rows.append(st)
        for st in sorted(rows, key=lambda r: -r["excess"]):
            by = st["by_year"] - st["ctrl_by_year"]
            cells = " ".join(f"{int(y) % 100}:{v:+.2f}" for y, v in by.items())
            band = (st["exit_band"] if "exit_band" in st else 0) * 100
            print(f"{st['label']:30s} {st['n']:>6d} {st['mean']:>7.2f} "
                  f"{st['median']:>7.2f} {st['win']:>6.2f} {st['held']:>5.1f} "
                  f"{band:>6.0f} {st['excess']:>+7.2f}  {cells}")
        print()
    return 0

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-hold", type=int, default=HOLD_SESSIONS[-1],
                    choices=HOLD_SESSIONS, help="4 or 8 weeks, in sessions")
    ap.add_argument("--min-dv", type=float, default=5e6)
    # Mặc định lấy từ config qua analysis/bench.py (§18.2/9 = 30bps/chiều), KHÔNG
    # phải 15 gõ tay. Ba script từng chạy ở 15 và một script ở 0, nên cùng một
    # lệnh được chấm ở 0,40% / 0,70% / 1,00% tuỳ script nào chạy.
    ap.add_argument("--slippage-bps", type=float, default=SLIPPAGE_BPS_PER_SIDE,
                    help="per side; 15bps is a liquid HOSE name at the open")
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--geometry", default="")
    ap.add_argument("--trail", action="store_true",
                    help="do range ban truot len thay vi hinh hoc target/stop co dinh")
    ap.add_argument("--rule", default="", help="chi mot luat vao lenh")
    args = ap.parse_args()

    cost = FEE_ROUND_TRIP + 2 * args.slippage_bps / 10_000.0
    p = load_panel()
    f = build_features(p)
    idx = p["close"].index
    idx = idx[idx >= pd.Timestamp(args.start)]
    years = (idx[-1] - idx[0]).days / 365.25

    print(f"panel {p['close'].shape[1]} symbols, window {idx[0].date()} .. {idx[-1].date()} "
          f"({years:.1f}y)")
    print(f"cost {cost*100:.2f}% round trip (fees {FEE_ROUND_TRIP*100:.2f}% + "
          f"slippage {2*args.slippage_bps/100:.2f}%) | max hold {args.max_hold} sessions\n")

    if args.trail:
        return main_trail(args, f, p, idx, years, cost)

    geos = ({args.geometry: GEOMETRIES[args.geometry]} if args.geometry else GEOMETRIES)
    for gname, (ta, sa) in geos.items():
        print("=" * 108)
        print(f"GEOMETRY {gname}   target +{ta}xATR   stop -{sa}xATR   "
              f"max hold {args.max_hold}")
        print("=" * 108)
        print(f"{'entry rule':26s} {'n':>6s} {'/yr':>6s} {'mean%':>7s} {'med%':>7s} "
              f"{'win':>6s} {'held':>5s} {'tgt%':>6s} {'stop%':>6s} {'sum%':>8s}")
        rows = []
        for rname, fn in RULES.items():
            ent = fn(f).fillna(False).astype(bool)
            ent.loc[ent.index < pd.Timestamp(args.start)] = False
            t = run(ent, f, p, target_atr=ta, stop_atr=sa, max_hold=args.max_hold,
                    min_dv=args.min_dv, cost=cost)
            s = summarise(t, rname, years)
            if not s["n"]:
                continue
            ctrl = random_control(ent, f, p, target_atr=ta, stop_atr=sa,
                                  max_hold=args.max_hold, min_dv=args.min_dv,
                                  cost=cost)
            s["ctrl"] = summarise(ctrl, rname + " (random)", years)
            rows.append(s)
        if not rows:
            continue
        ctrl0 = rows[0]["ctrl"]
        print(f"{'RANDOM CONTROL':26s} {ctrl0['n']:>6d} {ctrl0['per_yr']:>6.0f} "
              f"{ctrl0['mean']:>7.2f} {ctrl0['median']:>7.2f} {ctrl0['win']:>6.2f} "
              f"{ctrl0['held']:>5.1f} {ctrl0['tgt']*100:>6.0f} {ctrl0['stp']*100:>6.0f} "
              f"{ctrl0['total']:>8.0f}")
        for s in sorted(rows, key=lambda r: -r["mean"]):
            print(f"{s['label']:26s} {s['n']:>6d} {s['per_yr']:>6.0f} {s['mean']:>7.2f} "
                  f"{s['median']:>7.2f} {s['win']:>6.2f} {s['held']:>5.1f} "
                  f"{s['tgt']*100:>6.0f} {s['stp']*100:>6.0f} {s['total']:>8.0f}")
        print()
        print("EXCESS over the rule's OWN random control, per year "
              "(16.12: pooled is not enough)")
        yrs = sorted({int(y) for r in rows for y in r["by_year"].index})
        print(f"{'entry rule':26s} {'pooled':>8s}  " + " ".join(f"{y:>7d}" for y in yrs))
        for s in sorted(rows, key=lambda r: -(r["mean"] - r["ctrl"]["mean"])):
            cby = s["ctrl"]["by_year"]
            cells = []
            for y in yrs:
                if y in s["by_year"].index and y in cby.index:
                    cells.append(f"{s['by_year'][y] - cby[y]:>+7.2f}")
                else:
                    cells.append(f"{'':>7s}")
            n_pos = sum(1 for c in cells if c.strip().startswith("+"))
            mark = "  ALL YEARS +" if n_pos == len([c for c in cells if c.strip()]) else ""
            print(f"{s['label']:26s} {s['mean'] - s['ctrl']['mean']:>+8.2f}  "
                  + " ".join(cells) + mark)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
