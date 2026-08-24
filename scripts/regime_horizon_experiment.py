"""Measure CONF_HORIZON and test whether calibration is worth adding.

Two questions CLAUDE.md §25.7 left open, both answered by running this:

  1. `CONF_HORIZON = 5` was asserted, not derived. Nothing measured said one
     trading week was the right horizon for a regime call.
  2. "The top confidence bucket needs isotonic calibration" — recorded as a
     known defect on the strength of a single 300-session window.

Run it:

    python scripts/regime_horizon_experiment.py

It fits the live classifier once on 1500 days of VNINDEX, then walks the
filtered posterior forward bar by bar — `predict_proba(Z[:t+1])[-1]`, the same
call `RegimeClassifier.predict` makes — so every number here is causal. A
smoothed decode would leak the future into the score and flatter every result.

Reported per horizon: base rate, Brier, Brier of the base-rate-only forecast,
Brier skill (1 - B/Bref), AUC. Then the same split three ways by time, because
a horizon that only wins on one stretch of tape has not won.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analysis.regime as R  # noqa: E402
from services.macro_service import fetch_vnindex_daily  # noqa: E402

HORIZONS = (1, 2, 3, 4, 5, 6, 8, 10, 13, 15, 20)
WINDOW = 900          # bars of walk-forward. ~3.5y, all the panel supports.


def _walk(clf, Z, lo):
    """Filtered posterior + argmax label for every bar from `lo` on."""
    filt = np.array([clf.model.predict_proba(Z[: t + 1])[-1] for t in range(lo, len(Z))])
    labels = [clf._state_to_label.get(int(f.argmax()), "chop") for f in filt]
    return filt, labels


def _conf(clf, filt, labels, i, horizon):
    lab = labels[i]
    same = np.array([1.0 if clf._state_to_label.get(j) == lab else 0.0
                     for j in range(clf.n_states)])
    ahead = np.linalg.matrix_power(clf.model.transmat_, horizon)
    return float(filt[i] @ (ahead @ same))


def _scores(y, p):
    """Brier, reference Brier, skill, AUC. Returns NaNs on a degenerate split."""
    from sklearn.metrics import brier_score_loss, roc_auc_score
    if len(set(y)) < 2:
        return float("nan"), float("nan"), float("nan"), float("nan")
    b = brier_score_loss(y, p)
    bref = brier_score_loss(y, np.full_like(p, y.mean(), dtype=float))
    return b, bref, 1 - b / bref, roc_auc_score(y, p)


def main() -> None:
    m = fetch_vnindex_daily(days=1500).to_frame()
    clf = R.RegimeClassifier().fit(m)
    if clf.model is None:
        print("fit was refused (short panel or collapse) — nothing to measure")
        return

    Z = clf._scale(clf._features(m))
    lo = max(1, len(Z) - WINDOW)
    filt, labels = _walk(clf, Z, lo)
    print(f"fitted on {len(Z)} bars; walking the last {len(labels)}\n")

    # ---- 1. which horizon -------------------------------------------------
    print("PER HORIZON (pooled)")
    print(f"{'H':>3} {'n':>5} {'base':>6} {'pred':>6} {'Brier':>7} {'skill':>7} {'AUC':>6}")
    for h in HORIZONS:
        idx = range(len(labels) - h)
        y = np.array([labels[i] == labels[i + h] for i in idx]).astype(int)
        p = np.array([_conf(clf, filt, labels, i, h) for i in idx])
        b, _, skill, auc = _scores(y, p)
        print(f"{h:>3} {len(y):>5} {y.mean():>6.3f} {p.mean():>6.3f} "
              f"{b:>7.4f} {skill:>+7.3f} {auc:>6.3f}")

    # ---- 2. does it hold across time --------------------------------------
    # The pooled table above picks H=13. It should not be believed: that win
    # comes entirely from the middle third. Only a horizon positive in all
    # three is a horizon, and that is 5.
    print("\nSAME, SPLIT IN THIRDS  (a horizon that wins on one stretch has not won)")
    n = len(labels)
    thirds = [(0, n // 3, "early"), (n // 3, 2 * n // 3, "mid"), (2 * n // 3, n, "late")]
    print(f"{'H':>3} " + "".join(f"{nm:>17}" for _, _, nm in thirds))
    print(f"{'':>3} " + "".join(f"{'skill':>8}{'AUC':>9}" for _ in thirds))
    for h in (3, 5, 8, 10, 13, 20):
        cells = []
        for a, b_, _ in thirds:
            idx = range(a, min(b_, n - h))
            y = np.array([labels[i] == labels[i + h] for i in idx]).astype(int)
            p = np.array([_conf(clf, filt, labels, i, h) for i in idx])
            _, _, skill, auc = _scores(y, p)
            cells.append("      n/a        " if np.isnan(skill)
                         else f"{skill:>+8.3f}{auc:>9.3f}")
        print(f"{h:>3} " + "".join(cells))

    # ---- 3. is calibration worth adding -----------------------------------
    # Fit on the past, score the next 100 bars, never the reverse. Fitting a
    # calibrator on the whole panel and admiring the fit is how the "top
    # bucket is overconfident" claim survived as long as it did.
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss

    h = R.CONF_HORIZON
    idx = range(len(labels) - h)
    p = np.array([_conf(clf, filt, labels, i, h) for i in idx])
    y = np.array([labels[i] == labels[i + h] for i in idx]).astype(int)

    print(f"\nCALIBRATION, WALK-FORWARD (H={h}; fit on past, score next 100)")
    print(f"{'test span':>14} {'raw':>8} {'isotonic':>9} {'Platt':>8} {'winner':>8}")
    acc = {"raw": [], "isotonic": [], "Platt": []}
    for start in range(300, len(y) - 100 + 1, 100):
        tr, te = slice(0, start), slice(start, start + 100)
        if len(set(y[tr])) < 2 or len(set(y[te])) < 2:
            continue
        iso = IsotonicRegression(out_of_bounds="clip").fit(p[tr], y[tr])
        platt = LogisticRegression().fit(p[tr].reshape(-1, 1), y[tr])
        got = {
            "raw": brier_score_loss(y[te], p[te]),
            "isotonic": brier_score_loss(y[te], np.clip(iso.predict(p[te]), 0, 1)),
            "Platt": brier_score_loss(y[te], platt.predict_proba(p[te].reshape(-1, 1))[:, 1]),
        }
        for k, v in got.items():
            acc[k].append(v)
        best = min(got, key=got.get)
        print(f"{start:>6}-{start + 100:<7} {got['raw']:>8.4f} "
              f"{got['isotonic']:>9.4f} {got['Platt']:>8.4f} {best:>8}")
    if acc["raw"]:
        print(f"{'MEAN':>14} " + "".join(
            f"{np.mean(acc[k]):>{w}.4f}" for k, w in
            (("raw", 8), ("isotonic", 9), ("Platt", 8))))
        print("\nLower is better. If raw wins the mean, shipping a calibrator "
              "adds a fitted layer that loses money out of sample.")


if __name__ == "__main__":
    main()
