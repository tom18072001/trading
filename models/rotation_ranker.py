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

        # Chronological split 80/20 with a PURGE/EMBARGO gap.
        #
        # Review 2026-08-22, P0-6 (CLAUDE.md §18.3/13, marked BLOCKER):
        # the target is a forward N-day return, so the last N training dates
        # carry labels drawn from inside the test window. A plain 80/20 cut
        # therefore leaks N sessions of future information across the boundary
        # and every reported metric is optimistic. Lopez de Prado's fix is to
        # drop (purge) the overlapping dates entirely and add a small embargo.
        unique_dates = sorted(df["date"].unique())
        cut = int(len(unique_dates) * 0.8)
        embargo = ROTATION_TARGET_HORIZON_DAYS + 2
        purge_from = max(cut - embargo, 1)

        # The purge must not eat the training window. Require at least as many
        # surviving train dates as the gap itself -- below that the "model" is
        # fitted on a handful of days and any metric from it is noise.
        min_train_dates = max(embargo, 10)
        if cut - embargo < min_train_dates:
            raise ValueError(
                f"not enough history for a purged split: {len(unique_dates)} dates "
                f"leaves {max(cut - embargo, 0)} training dates after a "
                f"{embargo}-day embargo (need {min_train_dates}). "
                f"Backfill more sector_flow_daily before training."
            )

        train_dates = set(unique_dates[:purge_from])
        test_dates = set(unique_dates[cut:])
        train = df[df["date"].isin(train_dates)]
        test = df[df["date"].isin(test_dates)]
        if train.empty or test.empty:
            raise ValueError(
                f"not enough history for a purged split: {len(unique_dates)} dates, "
                f"embargo {embargo}. Backfill more sector_flow_daily before training."
            )
        purged_dates = len(unique_dates[purge_from:cut])

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
            print(f"[RotationRanker] *** DEGRADED *** LightGBM unavailable ({e}); "
                  f"falling back to mean-flow ranking, which is close to "
                  f"'sort sectors by size'. Signals produced from this run are "
                  f"NOT ranker-gated. Install lightgbm to restore.")
            self.model = _MeanFlowRanker(feature_cols)
            backend = "mean_flow_fallback"

        metrics = self._evaluate(test, feature_cols)
        metrics.update({
            "backend": backend,
            "n_dates_test": int(test["date"].nunique()),
            "embargo_days": embargo,
            "purged_dates": purged_dates,
        })

        # 2026-06-18 fix: persist the ACTUAL trained estimator (was only saving
        # a JSON of feature_names+metrics, so the model could never be reloaded
        # → RotationModelService retrained on EVERY predict). Now pickle the
        # fitted model and point model_path at the .pkl. The sidecar JSON is
        # kept for human inspection only.
        path = os.path.join(SAVED_MODELS_DIR, "rotation_ranker.pkl")
        with open(path, "wb") as f:
            pickle.dump({"model": self.model, "feature_names": feature_cols, "backend": backend}, f)
        with open(os.path.join(SAVED_MODELS_DIR, "rotation_ranker.json"), "w") as f:
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

    def _evaluate(self, test: pd.DataFrame, feature_cols: list[str]) -> dict:
        """Out-of-sample metrics that actually measure ranking skill.

        Review 2026-08-22, P0-6. The old `top1_hit_rate` counted "did the
        top-ranked sector have a positive forward return". In a rising market
        a coin flip scores ~60% on that, so the number recorded in
        `model_runs.metrics` said nothing about the model. These do:

        top1_excess_hit   -- how often the top pick beats the MEDIAN sector
                             that day. 0.5 is the no-skill line, always.
        decile_monotonic  -- CLAUDE.md §18.7: mean forward return must rise
                             monotonically across score quintiles. Reported as
                             Spearman correlation between quintile and mean
                             return; non-monotone means the model is guessing.
        ndcg_at_3         -- ranking quality of the top 3, which is what
                             MAX_LONG_SECTORS actually trades.
        """
        if test.empty:
            return {}

        excess_hits = 0
        n_days = 0
        scored: list[tuple[float, float]] = []   # (score, forward return)
        ndcgs: list[float] = []

        for _, group in test.groupby("date"):
            if len(group) < 3:
                continue
            scores = np.asarray(self.predict(group[feature_cols]), dtype=float)
            targets = group["target"].to_numpy(dtype=float)
            if np.isnan(targets).all():
                continue

            order = np.argsort(-scores)
            if targets[order[0]] > np.nanmedian(targets):
                excess_hits += 1
            n_days += 1

            scored.extend(zip(scores.tolist(), targets.tolist()))
            ndcgs.append(_ndcg_at_k(targets[order], targets, k=3))

        metrics: dict = {
            "top1_excess_hit": (excess_hits / n_days) if n_days else float("nan"),
            "ndcg_at_3": float(np.mean(ndcgs)) if ndcgs else float("nan"),
            "n_eval_days": n_days,
        }

        if len(scored) >= 25:
            sdf = pd.DataFrame(scored, columns=["score", "target"]).dropna()
            if len(sdf) >= 25 and sdf["score"].nunique() > 4:
                sdf["bucket"] = pd.qcut(sdf["score"].rank(method="first"), 5,
                                        labels=False, duplicates="drop")
                means = sdf.groupby("bucket")["target"].mean()
                if len(means) > 2:
                    rho = pd.Series(means.index, dtype=float).corr(
                        pd.Series(means.to_numpy()), method="spearman")
                    metrics["decile_monotonic"] = float(rho) if pd.notna(rho) else float("nan")
                    metrics["quintile_means"] = [round(float(v), 5) for v in means.to_numpy()]
        return metrics

    # ----- prediction -----
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("model not trained")
        return np.asarray(self.model.predict(X))

    @property
    def is_degraded(self) -> bool:
        """True when scores come from the mean-flow fallback, not LightGBM."""
        return bool(getattr(self.model, "is_degraded", False))


def _ndcg_at_k(gains_in_pred_order: np.ndarray, all_gains: np.ndarray, k: int = 3) -> float:
    """NDCG@k over forward returns, shifted so gains are non-negative."""
    shift = float(np.nanmin(all_gains))
    shift = -shift if shift < 0 else 0.0
    pred = np.nan_to_num(gains_in_pred_order[:k], nan=0.0) + shift
    ideal = np.sort(np.nan_to_num(all_gains, nan=0.0) + shift)[::-1][:k]
    discount = 1.0 / np.log2(np.arange(2, len(pred) + 2))
    dcg = float(np.sum(pred * discount))
    idcg = float(np.sum(ideal * discount[: len(ideal)]))
    return dcg / idcg if idcg > 0 else 0.0


class _MeanFlowRanker:
    """Degraded fallback: rank by the mean of all feature values.

    Review 2026-08-22, P1-2 -- this is NOT a mild degradation. FEATURE_COLS
    mixes net_dollar_flow (billions of VND) with breadth (0-1), so the
    arithmetic mean of the row is dominated by raw flow. In practice this
    ranker is "sort the sectors by size", which is close to a constant
    portfolio. It used to activate silently on any LightGBM import error and
    the daily email still called the output "ranker-gated picks".

    `is_degraded` is what callers check so the condition can be surfaced.
    """

    is_degraded = True

    def __init__(self, feature_cols):
        self.feature_cols = feature_cols

    def predict(self, X):
        return X[self.feature_cols].mean(axis=1).values
