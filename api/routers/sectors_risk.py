# ============================================
# api/routers/sectors_risk.py
# ============================================
from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config import SECTORS
from database.connection import get_session_dependency
from services.risk_service import SectorRiskService

router = APIRouter(prefix="/api/sectors/risk", tags=["sectors-risk"])


@router.get("/var")
def var_all(db: Session = Depends(get_session_dependency)):
    svc = SectorRiskService(db)
    return [asdict(svc.var_report(code)) for code in SECTORS]


@router.get("/var/{sector_code}")
def var_one(sector_code: str, db: Session = Depends(get_session_dependency)):
    return asdict(SectorRiskService(db).var_report(sector_code))


@router.get("/exposure")
def exposure(db: Session = Depends(get_session_dependency)):
    df = SectorRiskService(db).current_exposure()
    if df.empty:
        return []
    return df.to_dict(orient="records")


@router.get("/stoploss")
def stoploss(db: Session = Depends(get_session_dependency)):
    return SectorRiskService(db).stoploss_breaches()
