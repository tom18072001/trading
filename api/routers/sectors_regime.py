# ============================================
# api/routers/sectors_regime.py
# ============================================
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.connection import get_session_dependency
from database.models import SectorRegime
from services.rotation_model_service import RotationModelService

router = APIRouter(prefix="/api/sectors", tags=["sectors-regime"])


@router.get("/regime")
def latest_regime(db: Session = Depends(get_session_dependency)):
    row = db.query(SectorRegime).order_by(SectorRegime.date.desc()).first()
    if not row:
        return {"regime_label": "unknown", "confidence": 0.0}
    return {"date": row.date, "regime_label": row.regime_label, "confidence": row.confidence}


@router.get("/regime/history")
def regime_history(limit: int = 60, db: Session = Depends(get_session_dependency)):
    rows = (
        db.query(SectorRegime)
        .order_by(SectorRegime.date.desc())
        .limit(limit)
        .all()
    )
    return [{"date": r.date, "regime_label": r.regime_label, "confidence": r.confidence} for r in rows]


@router.post("/regime/classify")
def classify(db: Session = Depends(get_session_dependency)):
    rec = RotationModelService(db).classify_regime()
    return {"date": rec.date, "regime_label": rec.regime_label, "confidence": rec.confidence}
