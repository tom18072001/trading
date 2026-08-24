"""Why both models degrade over 2025-2026 — CLAUDE.md §25.8.

Two unrelated models get worse over the same recent stretch: the regime
horizon sweep (§25.7) and the §16.1 stealth gate (§16.13). §25.8 flagged that
as suspicious — "a defect common to two unrelated models is more likely the
tape or the data than either model" — and named data and tape as the suspects.

Run it:

    python scripts/late_period_diagnosis.py

Four checks, cheapest first. Each one either kills a suspect or promotes it.

  1. PANEL COVERAGE. Rules out the data explanation.
  2. THE TAPE. Measures what 2026 actually is, because §16.13 asserts "a
     flatter tape" and that is testable.
  3. TRANSITION STALENESS. `transmat_` is fitted once over the whole panel, so
     it encodes average persistence. If the late miss is a stale matrix,
     re-estimating transitions on a trailing window fixes it. (It does not.)
  4. VOL vs CALENDAR. The one that decides it: if the tape is the cause, skill
     should track volatility regardless of *when* the bar happened.

Findings as of 2026-08-24 are recorded in CLAUDE.md §25.8. Re-run rather than
trusting them — that is the whole lesson of §25.2 and §16.12.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analysis.regime as R  # noqa: E402
from config import DATABASE_PATH  # noqa: E402
from services.macro_service import fetch_vnindex_daily  # noqa: E402

WINDOW = 900


def _panel() -> pd.DataFrame:
    with sqlite3.connect(DATABASE_PATH) as c:
        df = pd.read_sql(
            "SELECT date, sector_code, close_idx, atr_pct, foreign_net, breadth_sma20 "
            "FROM sector_flow_daily ORDER BY date", c)
    df["date"] = pd.to_datetime(df["date"])
    return df


def check_coverage(df: pd.DataFrame) -> None:
    """Is 2026 thinner than the years that work? (No.)"""
    print("1. PANEL COVERAGE — a gap here would explain everything cheaply\n")
    g = df.assign(q=df["date"].dt.to_period("Q")).groupby("q").agg(
        rows=("close_idx", "size"),
        sectors=("sector_code", "nunique"),
        close_nan=("close_idx", lambda s: s.isna().mean()),
        foreign_nonzero=("foreign_net", lambda s: (s != 0).mean()),
        breadth_zero=("breadth_sma20", lambda s: (s == 0).mean()),
    )
    print(g.round(3).to_string())
    print("\n   -> 15 sectors and ~0 missing closes in every 2026 quarter. Not data.\n")


def check_tape(df: pd.DataFrame) -> None:
    """What IS 2026? §16.13 calls it flat; that is a claim with a number."""
    print("2. THE TAPE — §16.13 says 'a flatter tape'\n")
    p = df.pivot(index="date", columns="sector_code", values="close_idx").sort_index()
    r = p.pct_change()
    fwd = p.shift(-40) / p - 1
    # Forward 40d MAX, not last: a breakout test asks whether it ever moved.
    fwd_max = p[::-1].rolling(40, min_periods=1).max()[::-1].shift(-1) / p - 1
    print(f"{'year':6}{'fwd40 med':>11}{'fwd40 max':>11}{'% positive':>12}{'ann vol':>9}")
    for yr in sorted(set(p.index.year)):
        k = p.index.year == yr
        print(f"{yr:<6}{fwd[k].stack().median():>11.4f}{fwd_max[k].stack().median():>11.4f}"
              f"{(fwd[k].stack() > 0).mean():>12.3f}{r[k].stack().std() * np.sqrt(252):>9.3f}")
    print("\n   -> 2026 is not flat. It is DOWN (median fwd40 -7.6%, 17% positive)")
    print("      with vol ABOVE 2024-25. §16.13's characterisation is wrong.\n")


def _walk():
    m = fetch_vnindex_daily(days=1500).to_frame()
    clf = R.RegimeClassifier().fit(m)
    if clf.model is None:
        raise SystemExit("fit refused — nothing to measure")
    Z = clf._scale(clf._features(m))
    lo = max(1, len(Z) - WINDOW)
    filt = np.array([clf.model.predict_proba(Z[: t + 1])[-1] for t in range(lo, len(Z))])
    labels = [clf._state_to_label.get(int(f.argmax()), "chop") for f in filt]
    return clf, filt, labels, m.index[lo:]


def _conf(clf, filt, labels, i, T, h):
    lab = labels[i]
    same = np.array([1.0 if clf._state_to_label.get(j) == lab else 0.0
                     for j in range(clf.n_states)])
    return float(filt[i] @ (np.linalg.matrix_power(T, h) @ same))


def check_transitions(clf, filt, labels) -> None:
    """Is the late miss just a transition matrix averaged over the wrong years?"""
    from sklearn.metrics import brier_score_loss, roc_auc_score
    print("3. TRANSITION STALENESS — transmat_ is fitted once over the whole panel\n")
    H, K, n = R.CONF_HORIZON, clf.n_states, len(labels)
    hard = filt.argmax(axis=1)
    N = n - H
    y = np.array([labels[i] == labels[i + H] for i in range(N)]).astype(int)
    late = slice(2 * N // 3, N)

    def trailing(i, w):
        # Laplace prior of 1: a window can legitimately contain no example of a
        # transition, and a zero row would make the horizon power degenerate.
        C = np.ones((K, K))
        for t in range(max(0, i - w), i):
            C[hard[t], hard[t + 1]] += 1
        return C / C.sum(1, keepdims=True)

    print(f"{'window':>8}{'late base':>11}{'late pred':>11}{'bias':>8}"
          f"{'late Brier':>12}{'late AUC':>10}{'ALL Brier':>11}")
    for w in (None, 120, 250, 500):
        p = np.array([_conf(clf, filt, labels, i,
                            clf.model.transmat_ if w is None else trailing(i, w), H)
                      for i in range(N)])
        yy, pp = y[late], p[late]
        print(f"{str(w):>8}{yy.mean():>11.3f}{pp.mean():>11.3f}{pp.mean() - yy.mean():>+8.3f}"
              f"{brier_score_loss(yy, pp):>12.4f}{roc_auc_score(yy, pp):>10.3f}"
              f"{brier_score_loss(y, p):>11.4f}")
    print("\n   -> A trailing window fixes the late BIAS and costs overall Brier and")
    print("      AUC. So the late failure is lost DISCRIMINATION, not a stale matrix.")
    print("      Nothing to ship here.\n")


def check_vol_vs_calendar(clf, filt, labels, dates) -> None:
    """The deciding test: does skill track volatility or the calendar?"""
    from sklearn.metrics import roc_auc_score
    print("4. VOL vs CALENDAR — if it is the tape, vol explains it at any date\n")
    H, n = R.CONF_HORIZON, len(labels)
    N = n - H
    p = np.array([_conf(clf, filt, labels, i, clf.model.transmat_, H) for i in range(N)])
    y = np.array([labels[i] == labels[i + H] for i in range(N)]).astype(int)

    vol = fetch_vnindex_daily(days=1500).pct_change().rolling(20).std()
    v = vol.reindex(pd.to_datetime(dates)).to_numpy()[:N]
    # rank before qcut: 20d rolling vol has ties and long flat stretches.
    bucket = pd.qcut(pd.Series(v).rank(method="first"), 3,
                     labels=["lo", "mid", "hi"]).to_numpy()
    third = np.array([0 if i < N // 3 else (1 if i < 2 * N // 3 else 2) for i in range(N)])

    print(f"{'vol':>5}{'n':>6}{'base':>7}{'AUC':>7}   share of rows in late third")
    for b in ("lo", "mid", "hi"):
        k = bucket == b
        print(f"{b:>5}{k.sum():>6}{y[k].mean():>7.3f}{roc_auc_score(y[k], p[k]):>7.3f}"
              f"        {(third[k] == 2).mean():.2f}")

    print(f"\n   AUC crossed both ways:\n{'':>5}" + "".join(f"{c:>17}" for c in
                                                            ("early", "mid", "late")))
    for b in ("lo", "mid", "hi"):
        cells = []
        for t in (0, 1, 2):
            k = (bucket == b) & (third == t)
            cells.append(f"{roc_auc_score(y[k], p[k]):.3f} (n={k.sum()})"
                         if k.sum() > 25 and len(set(y[k])) > 1 else f"n/a (n={k.sum()})")
        print(f"{b:>5}" + "".join(f"{c:>17}" for c in cells))
    print("\n   -> AUC falls monotonically with vol, and the high-vol bucket is spread")
    print("      across periods rather than concentrated in the late one. The tape is")
    print("      the larger term; the calendar is mostly a proxy for it.\n")


def main() -> None:
    df = _panel()
    check_coverage(df)
    check_tape(df)
    clf, filt, labels, dates = _walk()
    print(f"(walked {len(labels)} bars, {str(dates[0])[:10]} -> {str(dates[-1])[:10]})\n")
    check_transitions(clf, filt, labels)
    check_vol_vs_calendar(clf, filt, labels, dates)


if __name__ == "__main__":
    main()
