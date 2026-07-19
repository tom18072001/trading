# ============================================
# models/rotation_ranker.py — LightGBM lambdarank
# ============================================
# Sector rotation ranker. Trained per day-group: features describe each
# sector on day t, target is forward 5d sector return ranked within day.
# Falls back to mean-flow ranker if LightGBM is unavailable.

from __future__ import annotations

import json
import os
import pickle
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from config import LIGHTGBM_RANKER_PARAMS, ROTATION_TARGET_HORIZON_DAYS, SAVED_MODELS_DIR


@dataclass
class TrainResult:
    n_train: int
    n_test: int
    metrics: dict
    model_path: str
    feature_names: list[str]


class RotationRanker:
    def __init__(self):
        self.model = None
        self.feature_names: list[str] = []

    # ----- training -----
    def fit(self, df: pd.DataFrame, feature_cols: Iterable[str]) -> TrainResult:
        """`df` must contain columns: date, sector_code, <features>, target.
        target = forward N-day return ranked WITHIN each date.
        """
        feature_cols = list(feature_cols)
        self.feature_names = feature_cols
        df = df.dropna(subset=feature_cols + ["target"]).sort_values(["date", "sector_code"])
        if df.empty:
            raise ValueError("no training data")

        # Convert target to per-day ranks (lambdarank expects integer relevance)
        df["relevance"] = df.groupby("date")["target"].rank(method="dense").astype(int)

        # Chronological split 80/20
        unique_dates = sorted(df["date"].unique())
        cut = int(len(unique_dates) * 0.8)
        train_dates = set(unique_dates[:cut])
        train = df[df["date"].isin(train_dates)]
        test = df[~df["date"].isin(train_dates)]

        try:
            from lightgbm import LGBMRanker
            self.model = LGBMRanker(**LIGHTGBM_RANKER_PARAMS)
            self.model.fit(
                train[feature_cols],
                train["relevance"],
                group=train.groupby("date").size().values,
            )
            backend = "lightgbm"
        except Exception as e:
            print(f"[RotationRanker] LightGBM unavailable ({e}); using mean-flow fallback")
            self.model = _MeanFlowRanker(feature_cols)
            backend = "mean_flow_fallback"

        # Hit-rate of top-1 sector
        hit = self._top1_hit_rate(test, feature_cols)
        metrics = {"backend": backend, "top1_hit_rate": hit, "n_dates_test": int(test["date"].nunique())}

        # 2026-06-18 fix: persist the ACTUAL trained estimator (was only saving
        # a JSON of feature_names+metrics, so the model could never be reloaded
        # → RotationModelService retrained on EVERY predict). Now pickle the
        # fitted model and point model_path at the .pkl. The sidecar JSON is
        # kept for human inspection only.
        path = os.path.join(SAVED_MODELS_DIR, "rotation_ranker_v0.pkl")
        with open(path, "wb") as f:
            pickle.dump({"model": self.model, "feature_names": feature_cols, "backend": backend}, f)
        with open(os.path.join(SAVED_MODELS_DIR, "rotation_ranker_v0.json"), "w") as f:
            json.dump({"feature_names": feature_cols, "metrics": metrics}, f)
        return TrainResult(
            n_train=len(train), n_test=len(test),
            metrics=metrics, model_path=path, feature_names=feature_cols,
        )

    # ----- persistence -----
    def load(self, path: str) -> bool:
        """Load a pickled estimator saved by fit(). Returns True on success."""
        try:
            if not path or not os.path.exists(path):
                return False
            with open(path, "rb") as f:
                blob = pickle.load(f)
            self.model = blob["model"]
            self.feature_names = blob.get("feature_names", [])
            return self.model is not None
        except Exception as e:
            print(f"[RotationRanker] load failed ({e}); will retrain")
            return False

    def _top1_hit_rate(self, test: pd.DataFrame, feature_cols: list[str]) -> float:
        if test.empty:
            return float("nan")
        hits = 0
        n = 0
        for date, group in test.groupby("date"):
            scores = self.predict(group[feature_cols])
            top_idx = int(np.argmax(scores))
            if group.iloc[top_idx]["target"] > 0:
                hits += 1
            n += 1
        return hits / n if n else float("nan")

    # ----- prediction -----
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("model not trained")
        return np.asarray(self.model.predict(X))


class _MeanFlowRanker:
    """Trivial fallback: rank by mean of all numeric features."""
    def __init__(self, feature_cols):
        self.feature_cols = feature_cols
    def predict(self, X):
        return X[self.feature_cols].mean(axis=1).values
