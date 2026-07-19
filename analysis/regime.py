# ============================================
# analysis/regime.py — HMM regime classifier
# ============================================
# Lightweight wrapper around hmmlearn.GaussianHMM. Falls back to a heuristic
# regime if hmmlearn is not installed.

from __future__ import annotations

import numpy as np
import pandas as pd

from config import REGIME_STATES


def _heuristic_regime(macro: pd.DataFrame) -> tuple[str, float]:
    """Fallback if hmmlearn unavailable. Inputs assumed sorted ascending."""
    if macro.empty:
        return "chop", 0.0
    last = macro.iloc[-1]
    vn_ret = macro["vnindex"].pct_change(20).iloc[-1] if "vnindex" in macro else 0.0
    vol = macro["vnindex"].pct_change().rolling(20).std().iloc[-1] if "vnindex" in macro else 0.0
    if pd.isna(vn_ret):
        vn_ret = 0.0
    if pd.isna(vol):
        vol = 0.0
    if vn_ret > 0.03 and vol < 0.02:
        return "risk_on", 0.6
    if vn_ret < -0.03 and vol > 0.02:
        return "risk_off", 0.6
    if vol > 0.025:
        return "rotation", 0.5
    return "chop", 0.5


class RegimeClassifier:
    """Gaussian HMM over macro returns; 4 hidden states mapped to labels."""

    def __init__(self, n_states: int = 4, random_state: int = 42):
        self.n_states = n_states
        self.random_state = random_state
        self.model = None
        self._state_to_label: dict[int, str] = {}

    def _features(self, macro: pd.DataFrame) -> np.ndarray:
        df = macro.copy().sort_index()
        # Convert object columns to numeric, coercing errors to NaN
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

    def fit(self, macro: pd.DataFrame) -> "RegimeClassifier":
        try:
            from hmmlearn.hmm import GaussianHMM
        except ImportError:
            self.model = None
            return self

        X = self._features(macro)
        if len(X) < self.n_states * 5:
            self.model = None
            return self

        m = GaussianHMM(
            n_components=self.n_states,
            covariance_type="diag",
            n_iter=200,
            random_state=self.random_state,
        )
        m.fit(X)
        self.model = m

        # Map hidden states → labels by ranking mean VN return per state
        means = m.means_[:, 0] if m.means_.shape[1] > 0 else np.zeros(self.n_states)
        order = np.argsort(means)  # ascending
        # Lowest mean → risk_off, highest → risk_on, middles → rotation/chop
        labels = ["risk_off", "chop", "rotation", "risk_on"]
        for rank, state_idx in enumerate(order):
            self._state_to_label[int(state_idx)] = labels[rank] if rank < len(labels) else "chop"
        return self

    def predict(self, macro: pd.DataFrame) -> tuple[str, float]:
        if self.model is None:
            return _heuristic_regime(macro)
        X = self._features(macro)
        if len(X) == 0:
            return _heuristic_regime(macro)
        states = self.model.predict(X)
        last = int(states[-1])
        label = self._state_to_label.get(last, "chop")
        # confidence = posterior of last bar
        try:
            post = self.model.predict_proba(X)
            conf = float(post[-1, last])
        except Exception:
            conf = 0.5
        if label not in REGIME_STATES:
            label = "chop"
        return label, conf
