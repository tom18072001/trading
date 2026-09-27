# ============================================
# services/rotation_model_service.py
# ============================================
# Trains and serves the rotation ranker. Also runs the HMM regime classifier.

from __future__ import annotations

import json

import pandas as pd
from sqlalchemy.orm import Session

from analysis.regime import RegimeClassifier
from services.macro_service import fetch_vnindex_daily
from config import ROTATION_TARGET_HORIZON_DAYS
from database.models import ModelRun, SectorRegime
from models.rotation_ranker import RotationRanker
from services.flow_feature_service import FEATURE_COLS, FlowFeatureService
from utils import clock
from utils.clock import today_str

# Dynamic target label (§16.4: 20d). Used for ModelRun bookkeeping + to
# deactivate the right prior runs on retrain.
TARGET_COL = f"fwd_{ROTATION_TARGET_HORIZON_DAYS}d_sector_return"


#: Fewest daily VNINDEX bars a label is published from -- the heuristic's own
#: floor (20-session return + 20-session vol). Below it there is no label to give.
REGIME_MIN_BARS = 25


class FeaturesMissingError(RuntimeError):
    """The latest session has a feature column that was never computed."""


class RotationModelService:
    def __init__(self, session: Session):
        self.session = session
        self.ranker = RotationRanker()
        #: `model_runs.id` of the model that will score today -- stored on each
        #: published signal so it can be traced (review 2026-09-24 §4.1/10).
        self.active_run_id: int | None = None
        self._load_active_model()

    def _load_active_model(self) -> None:
        """Load the persisted active ranker so predict_today() doesn't retrain
        on every call (the old behaviour: a fresh RotationRanker each request,
        model=None → lazy-train every predict)."""
        run = (
            self.session.query(ModelRun)
            .filter(ModelRun.model_name == "rotation_ranker",
                    ModelRun.is_active.is_(True),
                    ModelRun.status == "completed")
            .order_by(ModelRun.id.desc())
            .first()
        )
        if run is not None and run.model_path:
            self.ranker.load(run.model_path)
            self.active_run_id = run.id

    # ----- training -----
    def train_ranker(self) -> ModelRun:
        feat_svc = FlowFeatureService(self.session)
        df = feat_svc.build(with_target=True)
        if df.empty:
            raise RuntimeError("no feature data — ingest sectors first")
        # Fill chronically-missing exogenous cols (rs/macro) with 0 so dropna
        # on features+target doesn't wipe the entire dataset.
        for col in ("rs_vnindex_5d", "rs_vnindex_20d", "macro_vn_ret_5d"):
            if col in df.columns:
                df[col] = df[col].fillna(0.0)

        result = self.ranker.fit(df, FEATURE_COLS)

        # Mark previous active runs inactive (any horizon — a 20d run supersedes
        # legacy 5d runs too, so deactivate by model_name not target_col).
        self.session.query(ModelRun).filter(
            ModelRun.model_name == "rotation_ranker",
            ModelRun.is_active.is_(True),
        ).update({"is_active": False})

        run = ModelRun(
            model_name="rotation_ranker",
            target_col=TARGET_COL,
            train_size=result.n_train,
            test_size=result.n_test,
            features_used=json.dumps(result.feature_names),
            hyperparams=json.dumps({"backend": result.metrics.get("backend")}),
            metrics=json.dumps(result.metrics),
            model_path=result.model_path,
            is_active=True,
            status="completed",
        )
        self.session.add(run)
        self.session.commit()
        self.active_run_id = run.id
        return run

    # ----- prediction -----
    def predict_today(self) -> pd.DataFrame:
        feat_svc = FlowFeatureService(self.session)
        # Refuse to rank on columns that were never computed. `build()` fills
        # NULL with 0 so training survives warm-up rows; on the PREDICTION day
        # that turns "not computed" into "exactly average" for every sector,
        # which is how a month of signals came from zeros (review 2026-09-24
        # §4.1/1). Raise, and let the caller decide what to publish instead.
        day, missing = feat_svc.unfilled_columns_on_latest()
        if missing:
            raise FeaturesMissingError(
                f"{day}: {', '.join(missing)} NULL for every sector -- run "
                "`main.py --eod-rollup` (it rebuilds the leading features) "
                "before predicting")
        latest = feat_svc.latest_features()
        if latest.empty:
            return latest
        # Lazy-train fallback if no model has been trained yet
        if self.ranker.model is None:
            try:
                self.train_ranker()
            except Exception:
                pass

        if self.ranker.model is None:
            latest["score"] = latest[FEATURE_COLS].fillna(0).mean(axis=1)
        else:
            X = latest[FEATURE_COLS].fillna(0)
            latest["score"] = self.ranker.predict(X)

        latest = latest.sort_values("score", ascending=False).reset_index(drop=True)
        latest["rank"] = latest.index + 1
        return latest

    # ----- regime -----
    def classify_regime(self) -> SectorRegime:
        """Fit and publish today's regime label -- from a DAILY VNINDEX series only.

        2026-09-25: when the daily fetch failed, this used to fit on the hourly
        `macro_anchors` rows instead. Those are snapshots, not sessions, and
        613 of them were 1.82 -- 2026-09-22's `risk_off 0.9961` was fitted on
        them (review 2026-09-24 §4.1/4, §8 P0-3). No daily series, no new
        label: the latest stored one is returned unchanged, under its own date.
        """
        # The hourly macro_anchors vnindex column is sparse/unreliable here, so
        # the classifier kept falling back to a flat "chop/0.5". Anchor it on a
        # real daily VNINDEX series from vnstock so the label is meaningful.
        # (2026-06-19)
        #
        # 2026-08-24: 180 -> 1500 days. 180 calendar days is ~111 usable bars
        # for a 40-parameter HMM, and the fit collapsed on it: three of four
        # states blew up to the hmmlearn ceiling covariance, every bar landed
        # in the survivor, and the posterior was 1.0 by construction. That is
        # where `confidence = 0.9999998` came from. 1500 days is ~1050 bars
        # back to 2022 and spans more than one regime, which a regime model
        # needs to see. analysis/regime.py now also refuses a collapsed fit.
        closed = clock.closed_today()
        if closed:
            # Same rule as the signals: no session, no new dated row.
            last = (self.session.query(SectorRegime)
                    .order_by(SectorRegime.date.desc()).first())
            print(f"[regime] {closed} is not a trading day -- keeping "
                  f"{last.date if last else 'no'} label")
            if last is not None:
                return last
            return SectorRegime(date=None, regime_label="chop", confidence=0.0,
                                model_version="unavailable")

        vn_daily = fetch_vnindex_daily(days=1500)     # per-value plausibility-filtered
        if vn_daily.notna().sum() < REGIME_MIN_BARS:
            last = (self.session.query(SectorRegime)
                    .order_by(SectorRegime.date.desc()).first())
            print(f"[regime] *** NOT PUBLISHING: {vn_daily.notna().sum()} usable daily "
                  f"VNINDEX bars (need {REGIME_MIN_BARS}); keeping "
                  f"{last.date if last else 'no'} label ***")
            if last is not None:
                return last
            # Nothing stored yet: an unsaved placeholder, so callers that print
            # the result still work. Nothing is written.
            return SectorRegime(date=None, regime_label="chop", confidence=0.0,
                                model_version="unavailable")

        macro_df = vn_daily.to_frame()  # date-indexed 'vnindex' column
        clf = RegimeClassifier().fit(macro_df)
        label, conf = clf.predict(macro_df)
        # The fit refuses a collapsed HMM and predict() then answers from the
        # heuristic -- say which one answered instead of stamping "hmm" on both.
        version = "hmm" if clf.model is not None else "heuristic"

        # Market-local date, like every other published row (P1-6).
        today = today_str()
        rec = self.session.query(SectorRegime).filter_by(date=today).one_or_none()
        if rec is None:
            rec = SectorRegime(date=today, regime_label=label, confidence=conf,
                               model_version=version)
            self.session.add(rec)
        else:
            rec.regime_label = label
            rec.confidence = conf
            rec.model_version = version
        self.session.commit()
        return rec
