# ============================================
# analysis/regime.py — HMM regime classifier
# ============================================
# Gaussian HMM over VNINDEX/macro returns. Falls back to a heuristic if
# hmmlearn is missing.
#
# ---------------------------------------------------------------------------
# 2026-08-24 — rewritten. `sector_regime.confidence` was 0.9999998 on almost
# every row it ever wrote, while the label flipped risk_off -> risk_on ->
# risk_off on consecutive days. Three separate defects, compounding:
#
#   1. **The fit had collapsed.** Features were fed raw, and their scales
#      differ by ~6x (r5 sd 0.028 vs v20 sd 0.005). EM blew up three of the
#      four states to the hmmlearn ceiling covariance of 1000 and parked all
#      111 observations in the survivor. With one live state the posterior is
#      1.0 by construction — the number was not confident, it was degenerate.
#      Standardising the feature matrix gives an occupancy of [154 177 470 251]
#      and a max covariance of 2.7.
#
#   2. **Too little history.** 180 calendar days is ~111 usable bars for a
#      40-parameter model. Now 1500 (~1050 bars, back to 2022), which spans
#      more than one regime — a model fitted inside a single regime cannot
#      label regimes.
#
#   3. **The number answered the wrong question.** Even after 1 and 2, the
#      state posterior sits at ~0.95: a Gaussian HMM is near-certain which
#      state a bar belongs to whenever the states are separable at all. That
#      is a statement about the fit, not about whether the regime call is worth
#      acting on — 26 label flips per 260 sessions at "95% confidence".
#
# `confidence` now means **P(the label still holds in 5 sessions)**, computed
# as the filtered posterior propagated through the transition matrix. Measured
# over the last 300 sessions: predicted 0.69, realised 0.60, and calibrated
# within a few points across the middle three buckets (the top bucket is
# overconfident — 0.90 predicted vs 0.70 actual — so read >0.85 as "likely",
# not "certain"). Range 0.46-0.91, which is the point: a confidence that never
# leaves 1.0 carries no information.
#
# Filtered, not smoothed, also closes CLAUDE.md §20.3 P1-4: `predict_proba`
# over the whole panel is forward-backward, so it re-decodes history with
# hindsight and yesterday's published label can silently change. The last bar
# of a prefix has no future to smooth over, so `predict_proba(X[:t+1])[-1]` IS
# the filtered posterior using only public API (hmmlearn 0.3.3 has no
# `_do_forward_pass`).
# ---------------------------------------------------------------------------

from __future__ import annotations

import numpy as np
import pandas as pd

from config import REGIME_STATES

# How far ahead "confidence" looks. 5 sessions = one trading week, which is the
# horizon over which a regime label is actually used (position sizing, the
# §16.1 stealth read). Longer horizons drift toward the stationary distribution
# and stop discriminating.
CONF_HORIZON = 5


def confidence_phrase(conf: float | None) -> str:
    """Render `confidence` in Vietnamese as the thing it now measures.

    Lives here rather than in the report generator because the wording is a
    property of the formula: whoever changes what the number means owns the
    sentence describing it. Every renderer that used to print
    "HMM confidence 1.00" calls this instead.

    The hedge above 0.85 is not decoration — it is the measured miscalibration
    of the top bucket (0.90 predicted vs 0.70 realised over 300 sessions).
    Remove it when isotonic calibration lands, not before.
    """
    c = float(conf or 0.0)
    base = f"~{c:.0%} khả năng giữ {CONF_HORIZON} phiên tới"
    if c >= 0.85:
        return f"{base} (thang trên còn lạc quan — đọc là 'nhiều khả năng')"
    return base


# Labels ordered by mean 1d return, ascending — index i is the i-th coldest
# state. Keeps the mapping deterministic across refits.
_LABELS_BY_RETURN = ["risk_off", "chop", "rotation", "risk_on"]


def _heuristic_regime(macro: pd.DataFrame) -> tuple[str, float]:
    """Fallback when hmmlearn is missing or the panel is too short.

    The confidence used to be hardcoded (0.6/0.6/0.5/0.5), which is a made-up
    number wearing the same field name as a real one. It is now the share of
    the last 10 sessions that carry the same label — the same question the HMM
    path answers, measured directly. Same semantics, so the two paths are
    comparable and neither lies about its own certainty.
    """
    if macro.empty or "vnindex" not in macro:
        return "chop", 0.0

    px = pd.to_numeric(macro["vnindex"], errors="coerce").dropna()
    if len(px) < 25:
        return "chop", 0.0

    ret20 = px.pct_change(20)
    vol = px.pct_change().rolling(20).std()

    def _label(i: int) -> str:
        r, v = ret20.iloc[i], vol.iloc[i]
        if pd.isna(r) or pd.isna(v):
            return "chop"
        if r > 0.03 and v < 0.02:
            return "risk_on"
        if r < -0.03 and v > 0.02:
            return "risk_off"
        return "rotation" if v > 0.025 else "chop"

    label = _label(-1)
    window = [_label(i) for i in range(-min(10, len(px)), 0)]
    return label, round(sum(x == label for x in window) / len(window), 4)


class RegimeClassifier:
    """Gaussian HMM over macro returns; 4 hidden states mapped to labels."""

    def __init__(self, n_states: int = 4, random_state: int = 42):
        self.n_states = n_states
        self.random_state = random_state
        self.model = None
        self._state_to_label: dict[int, str] = {}
        # Fitted standardisation, reused at predict time so the same bar maps
        # to the same point in feature space on both passes.
        self._mu: np.ndarray | None = None
        self._sd: np.ndarray | None = None

    def _features(self, macro: pd.DataFrame) -> np.ndarray:
        df = macro.copy().sort_index()
        for col in ["vnindex", "usdvnd", "brent", "us10y", "gold"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        feats = pd.DataFrame(index=df.index)
        if "vnindex" in df and df["vnindex"].notna().sum() > 5:
            feats["vn_ret_1d"] = df["vnindex"].pct_change()
            feats["vn_ret_5d"] = df["vnindex"].pct_change(5)
            feats["vn_vol_20d"] = feats["vn_ret_1d"].rolling(20).std()
        if "usdvnd" in df and df["usdvnd"].notna().sum() > 5:
            feats["fx_chg"] = df["usdvnd"].pct_change()
        if "brent" in df and df["brent"].notna().sum() > 5:
            feats["brent_chg"] = df["brent"].pct_change()
        if "us10y" in df and df["us10y"].notna().sum() > 5:
            feats["us10y_chg"] = df["us10y"].diff()
        if "gold" in df and df["gold"].notna().sum() > 5:
            feats["gold_chg"] = df["gold"].pct_change()
        feats = feats.dropna()
        return feats.values

    def _scale(self, X: np.ndarray) -> np.ndarray:
        """Standardise. This is what stops EM collapsing three of four states.

        Feature scales differ by ~6x (5d returns vs 20d vol), and diagonal
        Gaussian EM with a shared init is not scale-invariant: the wide column
        dominates the likelihood, the narrow states never win an observation,
        and their covariances run to the hmmlearn ceiling of 1000.
        """
        if self._mu is None or self._sd is None:
            return X
        return (X - self._mu) / self._sd

    def fit(self, macro: pd.DataFrame) -> "RegimeClassifier":
        try:
            from hmmlearn.hmm import GaussianHMM
        except ImportError:
            self.model = None
            return self

        X = self._features(macro)
        # 4 states x n features x 2 moments + 16 transitions. Below ~20 bars
        # per parameter the fit is memorising, not classifying.
        if len(X) < max(self.n_states * 25, 100):
            self.model = None
            return self

        self._mu = X.mean(axis=0)
        sd = X.std(axis=0)
        self._sd = np.where(sd > 0, sd, 1.0)   # a constant column must not divide by 0
        Z = self._scale(X)

        m = GaussianHMM(
            n_components=self.n_states,
            covariance_type="diag",
            n_iter=500,
            random_state=self.random_state,
        )
        m.fit(Z)

        # Refuse a collapsed fit rather than publishing its 1.0 posterior. This
        # is the exact failure that produced 613 rows of "99.99998% confident".
        occupancy = np.bincount(m.predict(Z), minlength=self.n_states)
        if (occupancy == 0).sum() > 1:
            self.model = None
            return self

        self.model = m

        # Map hidden states -> labels by ranking mean 1d VN return per state.
        means = m.means_[:, 0] if m.means_.shape[1] > 0 else np.zeros(self.n_states)
        for rank, state_idx in enumerate(np.argsort(means)):
            self._state_to_label[int(state_idx)] = (
                _LABELS_BY_RETURN[rank] if rank < len(_LABELS_BY_RETURN) else "chop"
            )
        return self

    def predict(self, macro: pd.DataFrame) -> tuple[str, float]:
        if self.model is None:
            return _heuristic_regime(macro)
        X = self._features(macro)
        if len(X) == 0:
            return _heuristic_regime(macro)

        Z = self._scale(X)

        # Filtered posterior of the final bar: the last row of a prefix decode
        # sees no future, so this is forward-only even though predict_proba is
        # forward-backward. Published labels stop being back-painted (P1-4).
        filt = self.model.predict_proba(Z)[-1]

        label = self._state_to_label.get(int(filt.argmax()), "chop")
        if label not in REGIME_STATES:
            label = "chop"

        # P(still this label in CONF_HORIZON sessions). Sum over every state
        # sharing the label, because two hidden states can map to one label.
        same = np.array(
            [1.0 if self._state_to_label.get(j) == label else 0.0
             for j in range(self.n_states)]
        )
        ahead = np.linalg.matrix_power(self.model.transmat_, CONF_HORIZON)
        conf = float(filt @ (ahead @ same))
        return label, round(min(max(conf, 0.0), 1.0), 4)
