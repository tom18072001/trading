"""Does a learned ranker beat the hand-built blend at the four-week horizon?

`picks_scoring.blended_rank_scores` orders the shortlist with two terms and a
50/50 weight chosen by hand (CLAUDE.md 26.9). The obvious question Tom asked on
2026-09-16 -- "cập nhật code và backend mô hình dự đoán" -- is whether a model
trained on the whole feature set does better.

This answers it under the same rules everything else in 26 was judged by:

  * WALK-FORWARD, not a single split. Train on everything up to a cut, predict
    the next block, roll. A model scored on one test slice of a 4-year panel is
    scored on one market.
  * PURGED + EMBARGOED folds (18.3/13). The target is a forward 20-session
    return, so the last 22 training days overlap the test window and must be
    dropped, or the model reads its own answer.
  * The SAME yardstick as the bench: excess over the equal-weight base rate at
    exit +20, IC, quintile monotonicity, and the within-year split that 16.12
    makes binding. Pooled improvement is not enough.
  * Costs from config, entry at the next open.

Deliberately NOT a production path. Nothing here writes to `models/saved/`;
`RotationRanker.fit()` already does that unconditionally and once cost the
17:00 job a working model (19 -- `tests/conftest.py::_models_go_to_a_tmpdir`).

Usage:
    python scripts/ticker_ranker_experiment.py
    python scripts/ticker_ranker_experiment.py --horizon 20 --leaves 15
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.bench import TOTAL_COST as COST  # noqa: E402
from config import HOLD_SESSIONS  # noqa: E402
from scripts.ticker_alpha_bench import (  # noqa: E402
    FACTORS,
    build_features,
    load_panel,
)

# COST từng là `... + 2 * 0.0015` gõ tay ở đây, trong khi ticker_alpha_bench lấy
# BACKTEST_SLIPPAGE_MIN_PCT = 0.003 từ config. Hai bench chấm cùng một lệnh ở
# 0,70% và 1,00% một vòng — lệch 3,8 điểm %/năm ở khung 20 phiên, lớn hơn cả
# biên +1,0pp mà ensemble tuyên bố vượt VNINDEX. Nay một nguồn: analysis/bench.py.

# Everything build_features produces that is a per-name characteristic. Price
# levels and moving averages are excluded: an absolute price is not a feature,
# it is an identifier, and a tree will happily memorise it.
FEATURE_COLS = [
    "rsi2", "rsi14", "ret1", "ret5", "ret20", "ret60",
    "atr_pct", "std20", "ivol", "vr20", "obv_chg20",
    "pctb", "z20", "hl_pos", "gap", "near_52w", "amihud",
    "macd_hist", "adx14",
    "p_sma20", "p_sma50", "p_sma200", "log_dv20",
]


def build_matrix(f: dict, p: dict, horizon: int, min_dv: float) -> pd.DataFrame:
    """Long-format (date, symbol, features..., fwd) with the forward return
    measured exactly as the bench measures it: next open to close of +horizon."""
    o, c = p["open"], p["close"]
    feats = dict(f)
    feats["p_sma20"] = f["close"] / f["sma20"] - 1
    feats["p_sma50"] = f["close"] / f["sma50"] - 1
    feats["p_sma200"] = f["close"] / f["sma200"] - 1
    feats["log_dv20"] = np.log(f["dv20"].replace(0, np.nan))

    fwd = c.shift(-(1 + horizon)) / o.shift(-1) - 1.0
    elig = f["dv20"] > min_dv

    frames = [feats[name].where(elig).stack().rename(name)
              for name in FEATURE_COLS]
    frames.append(fwd.where(elig).stack().rename("fwd"))
    df = pd.concat(frames, axis=1)
    df.index.names = ["date", "symbol"]
    return df.dropna(subset=["fwd"]).reset_index()


def walk_forward(df: pd.DataFrame, horizon: int, *, n_folds: int, leaves: int,
                 min_leaf: int, seed: int) -> pd.Series:
    """Out-of-sample prediction for every row a fold can reach.

    Returns a Series indexed like `df`, NaN where no fold predicted it (the
    first training window has no out-of-sample counterpart by construction).
    """
    import lightgbm as lgb

    dates = np.array(sorted(df["date"].unique()))
    embargo = horizon + 2
    # Start predicting only once there is a training window worth the name.
    first = int(len(dates) * 0.40)
    edges = np.linspace(first, len(dates), n_folds + 1).astype(int)

    out = pd.Series(np.nan, index=df.index, dtype=float)
    for k in range(n_folds):
        lo, hi = edges[k], edges[k + 1]
        if hi - lo < 5:
            continue
        test_dates = set(dates[lo:hi])
        # Purge: the last `embargo` training dates overlap the test window's
        # forward target. Dropping them is the whole point of 18.3/13.
        train_dates = set(dates[: max(lo - embargo, 0)])
        if len(train_dates) < 120:
            continue

        tr = df[df["date"].isin(train_dates)]
        te = df[df["date"].isin(test_dates)]
        if tr.empty or te.empty:
            continue

        # lambdarank wants integer relevance per group; per-day quintile of the
        # forward return is stable and avoids handing the model raw magnitudes.
        rel = tr.groupby("date")["fwd"].transform(
            lambda s: pd.qcut(s.rank(method="first"), min(5, max(2, s.nunique())),
                              labels=False, duplicates="drop"))
        tr = tr.assign(rel=rel).dropna(subset=["rel"]).sort_values("date")
        groups = tr.groupby("date").size().to_numpy()

        model = lgb.LGBMRanker(
            objective="lambdarank", n_estimators=250, learning_rate=0.05,
            num_leaves=leaves, min_child_samples=min_leaf,
            subsample=0.8, subsample_freq=1, colsample_bytree=0.7,
            reg_lambda=5.0, random_state=seed, verbose=-1,
        )
        model.fit(tr[FEATURE_COLS], tr["rel"].astype(int), group=groups)
        out.loc[te.index] = model.predict(te[FEATURE_COLS])
    return out


def score(df: pd.DataFrame, pred_col: str, topk: int) -> dict:
    """Same yardstick as ticker_alpha_bench: top-k against the day's base rate."""
    rows, ics = [], []
    for d, g in df.groupby("date"):
        g = g.dropna(subset=[pred_col, "fwd"])
        if len(g) < 30:
            continue
        ics.append(g[pred_col].rank().corr(g["fwd"].rank()))
        top = g.nlargest(topk, pred_col)
        rows.append((d, top["fwd"].mean(), g["fwd"].mean()))
    if not rows:
        return {}
    r = pd.DataFrame(rows, columns=["date", "pick", "base"])
    r["date"] = pd.to_datetime(r["date"])
    ic = float(np.nanmean(ics))
    sd = float(np.nanstd(ics))
    q = df.dropna(subset=[pred_col, "fwd"]).groupby("date", group_keys=False).apply(
        lambda g: g.assign(q=pd.qcut(g[pred_col].rank(method="first"), 5,
                                     labels=False, duplicates="drop"))
        if len(g) >= 30 else g.assign(q=np.nan))
    return {
        "n_days": len(r),
        "pick": r["pick"].mean(),
        "base": r["base"].mean(),
        "excess": r["pick"].mean() - r["base"].mean(),
        "net": r["pick"].mean() - COST,
        "ic": ic,
        "ic_t": ic / (sd / np.sqrt(len(ics))) if sd > 0 else np.nan,
        "quint": q.groupby("q")["fwd"].mean(),
        "by_year": r.groupby(r["date"].dt.year).apply(
            lambda g: g["pick"].mean() - g["base"].mean()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=HOLD_SESSIONS[0], choices=HOLD_SESSIONS,
                    help="4 or 8 weeks, in sessions (config.HOLD_SESSIONS)")
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--min-dv", type=float, default=5e6)
    ap.add_argument("--folds", type=int, default=8)
    ap.add_argument("--leaves", type=int, default=15)
    ap.add_argument("--min-leaf", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    p = load_panel()
    f = build_features(p)
    df = build_matrix(f, p, args.horizon, args.min_dv)
    print(f"panel {p['close'].shape[1]} names; matrix {len(df):,} rows, "
          f"{df['date'].nunique()} dates, {len(FEATURE_COLS)} features")
    print(f"target: next open -> close of +{args.horizon}; purge+embargo "
          f"{args.horizon + 2} dates; {args.folds} walk-forward folds")
    print(f"cost {COST*100:.2f}% round trip\n")

    df["ml"] = walk_forward(df, args.horizon, n_folds=args.folds,
                            leaves=args.leaves, min_leaf=args.min_leaf,
                            seed=args.seed)

    # the shipped ordering, on exactly the same rows
    shipped = FACTORS["X_prop_obv"](f).stack().rename("shipped")
    shipped.index.names = ["date", "symbol"]
    df = df.merge(shipped.reset_index(), on=["date", "symbol"], how="left")

    # judge both only where the ML has an out-of-sample prediction
    oos = df[df["ml"].notna()]
    print(f"out-of-sample rows: {len(oos):,} over {oos['date'].nunique()} dates "
          f"({oos['date'].min().date()} .. {oos['date'].max().date()})\n")

    # Ensemble: rank-average of the learned score and the shipped blend. Two
    # weakly-correlated orderings averaged is the cheapest robustness there is,
    # and it is the natural answer when one wins pooled and the other wins the
    # year the first one loses.
    oos = oos.copy()
    oos["ens"] = oos.groupby("date", group_keys=False).apply(
        lambda g: 0.5 * g["ml"].rank(pct=True) + 0.5 * g["shipped"].rank(pct=True)
    ).reindex(oos.index)

    print(f"{'ordering':22s} {'gross%':>8s} {'net%':>8s} {'BASE%':>8s} "
          f"{'excess%':>9s} {'IC':>8s} {'IC_t':>7s} {'days':>6s}")
    print("-" * 82)
    res = {}
    for label, col in [("LEARNED (lambdarank)", "ml"),
                       ("ENSEMBLE 50/50", "ens"),
                       ("shipped blend", "shipped")]:
        s = score(oos, col, args.topk)
        if not s:
            continue
        res[label] = s
        if label.startswith("LEARNED"):
            print(f"{'BASE RATE (no ranking)':22s} {s['base']*100:>8.2f} "
                  f"{s['base']*100 - COST*100:>8.2f} {s['base']*100:>8.2f} "
                  f"{0.0:>+9.2f} {'':>8s} {'':>7s} {s['n_days']:>6d}")
        print(f"{label:22s} {s['pick']*100:>8.2f} {s['net']*100:>8.2f} "
              f"{s['base']*100:>8.2f} {s['excess']*100:>+9.2f} "
              f"{s['ic']:>+8.4f} {s['ic_t']:>+7.2f} {s['n_days']:>6d}")

    print(f"\n{'quintile mean fwd %':22s} " + " ".join(f"{'Q'+str(i+1):>8s}" for i in range(5)))
    for label, s in res.items():
        q = s["quint"].dropna()
        print(f"{label:22s} " + " ".join(f"{v*100:>+8.2f}" for v in q))

    print(f"\n{'within-year excess %':22s} " + " ".join(
        f"{y:>8d}" for y in sorted({int(y) for s in res.values() for y in s["by_year"].index})))
    for label, s in res.items():
        by = s["by_year"]
        print(f"{label:22s} " + " ".join(f"{by[y]*100:>+8.2f}" for y in sorted(by.index)))

    print("\n16.12: pooled improvement is not enough. A learned ranker that "
          "wins overall and loses a year has not earned the shortlist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
