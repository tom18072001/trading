# ============================================
# services/rotation_model_service.py
# ============================================
# Trains and serves the rotation ranker. Also runs the HMM regime classifier.

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from analysis.regime import RegimeClassifier
from services.macro_service import fetch_vnindex_daily
from config import ROTATION_TARGET_HORIZON_DAYS
from database.models import MacroAnchor, ModelRun, SectorRegime
from models.rotation_ranker import RotationRanker
from services.flow_feature_service import FEATURE_COLS, FlowFeatureService

# Dynamic target label (§16.4: 20d). Used for ModelRun bookkeeping + to
# deactivate the right prior runs on retrain.
TARGET_COL = f"fwd_{ROTATION_TARGET_HORIZON_DAYS}d_sector_return"


class RotationModelService:
    def __init__(self, session: Session):
        self.session = session
        self.ranker = RotationRanker()
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
        return run

    # ----- prediction -----
    def predict_today(self) -> pd.DataFrame:
        feat_svc = FlowFeatureService(self.session)
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
        rows = self.session.query(MacroAnchor).order_by(MacroAnchor.time).all()
        macro_df = pd.DataFrame([{
            "time": r.time, "vnindex": r.vnindex, "usdvnd": r.usdvnd,
            "brent": r.brent, "us10y": r.us10y, "gold": r.gold,
        } for r in rows]).set_index("time") if rows else pd.DataFrame()

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
        vn_daily = fetch_vnindex_daily(days=1500)
        if not vn_daily.empty and vn_daily.notna().sum() > 5:
            macro_df = vn_daily.to_frame()  # date-indexed 'vnindex' column

        if macro_df.empty or "vnindex" not in macro_df.columns or macro_df["vnindex"].notna().sum() <= 5:
            label, conf = "chop", 0.0
        else:
            clf = RegimeClassifier().fit(macro_df)
            label, conf = clf.predict(macro_df)

        today = datetime.now().strftime("%Y-%m-%d")
        rec = self.session.query(SectorRegime).filter_by(date=today).one_or_none()
        if rec is None:
            rec = SectorRegime(date=today, regime_label=label, confidence=conf, model_version="hmm")
            self.session.add(rec)
        else:
            rec.regime_label = label
            rec.confidence = conf
            rec.model_version = "hmm"
        self.session.commit()
        return rec
