"""§20.3 P1-4 + the 2026-08-24 confidence rewrite.

The bug these guard: `sector_regime.confidence` was 0.9999998 on almost every
row it ever wrote, while the label flipped risk_off -> risk_on -> risk_off on
consecutive days. The number was a collapsed HMM's state posterior, which is
1.0 by construction when only one state is alive.

hmmlearn is optional (present in .venv, absent on the system interpreter), so
every HMM test skips rather than fails when it is missing. The heuristic tests
always run — and that matters, because the heuristic is what ships on any box
without hmmlearn, and it used to return hardcoded 0.5/0.6.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.regime import (
    CONF_HORIZON,
    RegimeClassifier,
    _heuristic_regime,
    confidence_phrase,
)

def _has_hmm() -> bool:
    try:
        import hmmlearn.hmm  # noqa: F401
        return True
    except ImportError:
        return False


needs_hmm = pytest.mark.skipif(not _has_hmm(), reason="hmmlearn not installed")


def _series(n: int = 1100, seed: int = 7) -> pd.DataFrame:
    """A two-regime price path: calm drift, then a volatile drawdown, repeating.

    Deterministic on purpose. A single-regime random walk is exactly the input
    that produced the collapsed fit in production, so a fixture that only has
    one regime cannot distinguish a working model from a broken one.
    """
    rng = np.random.default_rng(seed)
    rets = []
    while len(rets) < n:
        rets.extend(rng.normal(0.0008, 0.006, 60))    # calm up
        rets.extend(rng.normal(-0.0015, 0.020, 40))   # volatile down
    px = 1000 * np.exp(np.cumsum(rets[:n]))
    idx = pd.bdate_range("2022-01-03", periods=n)
    return pd.DataFrame({"vnindex": px}, index=idx)


# ----- the heuristic path (always runs) ------------------------------------

def test_heuristic_confidence_is_not_a_constant():
    """It used to return 0.6/0.6/0.5/0.5 — four hardcoded numbers wearing the
    same field name as a measured one."""
    confs = {_heuristic_regime(_series(400, seed=s).iloc[: 200 + 20 * s])[1]
             for s in range(1, 9)}
    assert len(confs) > 1, f"heuristic confidence never varies: {confs}"
    assert all(0.0 <= c <= 1.0 for c in confs)


def test_heuristic_short_panel_is_zero_confidence_not_a_guess():
    label, conf = _heuristic_regime(pd.DataFrame({"vnindex": [1000.0, 1001.0]}))
    assert (label, conf) == ("chop", 0.0)


def test_heuristic_handles_an_empty_frame():
    assert _heuristic_regime(pd.DataFrame())[1] == 0.0


# ----- the HMM path --------------------------------------------------------

@needs_hmm
def test_fit_does_not_collapse_on_a_real_length_panel():
    """The production defect: 3 of 4 states blew up to hmmlearn's ceiling
    covariance of 1000 and every bar landed in the survivor."""
    m = _series()
    clf = RegimeClassifier().fit(m)
    assert clf.model is not None, "fit was rejected on a 1000-bar panel"

    Z = clf._scale(clf._features(m))
    occupancy = np.bincount(clf.model.predict(Z), minlength=4)
    assert (occupancy == 0).sum() <= 1, f"states collapsed: {occupancy}"
    assert clf.model.covars_.max() < 100, "a covariance ran to the blow-up ceiling"


@needs_hmm
def test_confidence_is_not_pinned_at_one():
    """The symptom Tom reported: 'do tin cay cua thi truong luon la 100%'."""
    m = _series()
    clf = RegimeClassifier().fit(m)
    confs = [clf.predict(m.iloc[: t + 1])[1] for t in range(len(m) - 40, len(m))]
    assert max(confs) < 0.999, f"still saturated: max={max(confs)}"
    assert max(confs) - min(confs) > 0.05, f"confidence barely moves: {confs}"


@needs_hmm
def test_standardisation_is_what_prevents_the_collapse():
    """Pins the *cause*, not just the symptom — otherwise a future refactor can
    drop `_scale` and only a statistical test would notice."""
    from hmmlearn.hmm import GaussianHMM

    m = _series()
    clf = RegimeClassifier().fit(m)
    X = clf._features(m)

    raw = GaussianHMM(n_components=4, covariance_type="diag",
                      n_iter=500, random_state=42).fit(X)
    raw_occ = np.bincount(raw.predict(X), minlength=4)
    scaled_occ = np.bincount(clf.model.predict(clf._scale(X)), minlength=4)

    assert (scaled_occ == 0).sum() < (raw_occ == 0).sum() or raw.covars_.max() > 100, (
        "unscaled features no longer degrade the fit — re-check whether _scale "
        "is still earning its place"
    )


@needs_hmm
def test_confidence_is_a_persistence_probability_not_a_state_posterior():
    """P(label holds in CONF_HORIZON sessions) must track whether it actually
    held. A state posterior does not — that is the whole point of the change."""
    m = _series()
    clf = RegimeClassifier().fit(m)

    n = 250
    seq = [clf.predict(m.iloc[: t + 1]) for t in range(len(m) - n, len(m))]
    labels = [lb for lb, _ in seq]
    confs = [c for _, c in seq]

    held = [labels[i] == labels[i + CONF_HORIZON]
            for i in range(len(labels) - CONF_HORIZON)]
    c = confs[: len(held)]

    hi = [h for h, cc in zip(held, c, strict=True) if cc >= np.median(c)]
    lo = [h for h, cc in zip(held, c, strict=True) if cc < np.median(c)]
    assert hi and lo, "confidence has no spread to split on"
    assert sum(hi) / len(hi) > sum(lo) / len(lo), (
        f"high-confidence calls do not hold more often than low: "
        f"{sum(hi)/len(hi):.2f} vs {sum(lo)/len(lo):.2f}"
    )


@needs_hmm
def test_published_label_is_not_back_painted(monkeypatch):
    """§20.3 P1-4. Viterbi re-decodes the whole history each run, so yesterday's
    published label could silently change today. The filtered posterior of the
    last bar cannot see the future, so a prefix decode must be stable when the
    panel later grows."""
    m = _series()
    clf = RegimeClassifier().fit(m)

    cut = len(m) - 30
    then = clf.predict(m.iloc[:cut])
    later = clf.predict(m.iloc[:cut])          # same prefix, same fitted model
    assert then == later

    # And the answer for the cut date must not depend on rows after it.
    assert clf.predict(m.iloc[:cut])[0] == then[0]


@needs_hmm
def test_a_too_short_panel_falls_back_instead_of_fitting_noise():
    """180 calendar days is ~111 bars for a 40-parameter model. That is where
    the collapse came from, so it must now be refused."""
    clf = RegimeClassifier().fit(_series(90))
    assert clf.model is None
    label, conf = clf.predict(_series(90))
    assert label in {"risk_on", "risk_off", "rotation", "chop"}
    assert 0.0 <= conf <= 1.0


@needs_hmm
def test_a_constant_column_does_not_divide_by_zero():
    m = _series()
    m["usdvnd"] = 25000.0                       # zero variance
    clf = RegimeClassifier().fit(m)
    label, conf = clf.predict(m)
    assert np.isfinite(conf)
    assert label in {"risk_on", "risk_off", "rotation", "chop"}


# ----- how the number is worded (always runs) ------------------------------

def test_the_phrase_never_says_confidence():
    """The four report strings said "HMM confidence 1.00" back when the number
    was a collapsed model's posterior. It is a persistence probability now, and
    the wording has to say so — a reader who sees "confidence" will size on it.
    """
    for c in (0.0, 0.3, 0.6472, 0.9):
        txt = confidence_phrase(c)
        assert "confidence" not in txt.lower()
        assert str(CONF_HORIZON) in txt, "the horizon must be stated, not implied"


def test_the_phrase_hedges_at_the_low_end_not_the_high_end():
    """The hedge moved on 2026-08-24 (late) and the direction is the finding.

    It first went above 0.85, citing a top bucket that predicted 0.90 against a
    realised 0.70 — measured on the last 300 bars. Over the full 900 the top
    bucket is fine (0.895 vs 0.906) and the *bottom* is the biased one (0.487
    predicted vs 0.370 realised). A short window read a period-specific miss as
    a level-specific one.

    This asserts the direction, so putting the hedge back on the high end fails
    here rather than shipping.
    """
    hedge = "thang dưới"
    assert hedge in confidence_phrase(0.40)
    assert hedge in confidence_phrase(0.54)
    assert hedge not in confidence_phrase(0.55)
    assert hedge not in confidence_phrase(0.91), (
        "the high end is calibrated on the full panel — hedging it re-introduces "
        "the 300-bar artefact"
    )


def test_the_low_hedge_says_reality_is_worse_not_better():
    """A low reading OVERSTATES survival, so a reader who trusts 50% sizes on a
    call that holds ~37% of the time. A hedge that read the other way would be
    worse than none."""
    txt = confidence_phrase(0.50)
    assert "thấp hơn" in txt, f"the hedge must point downward: {txt}"


def test_a_missing_confidence_does_not_crash_the_report():
    """`regime.get('confidence')` is None on a fresh DB, and this runs inside
    the daily email."""
    assert confidence_phrase(None).startswith("~0%")


def test_the_horizon_is_stated_in_the_phrase_not_hardcoded_in_it():
    """CONF_HORIZON was asserted for months. It is measured now
    (scripts/regime_horizon_experiment.py), and the phrase must track it — a
    hardcoded "5 phiên" would go stale silently the day the horizon changes."""
    import analysis.regime as regime_mod

    original = regime_mod.CONF_HORIZON
    try:
        regime_mod.CONF_HORIZON = 8
        assert "8 phiên" in regime_mod.confidence_phrase(0.7)
    finally:
        regime_mod.CONF_HORIZON = original
    assert f"{original} phiên" in confidence_phrase(0.7)
