# ============================================
# api/routers/sectors_ranking.py
# ============================================
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.connection import get_session_dependency
from services.sector_signal_service import SectorSignalService

router = APIRouter(prefix="/api/sectors", tags=["sectors-ranking"])


@router.get("/ranking")
def latest_ranking(db: Session = Depends(get_session_dependency)):
    df = SectorSignalService(db).latest()
    if df.empty:
        return []
    return df.to_dict(orient="records")


@router.post("/ranking/publish")
def publish_now(db: Session = Depends(get_session_dependency)):
    df = SectorSignalService(db).publish()
    return {"published": int(len(df)), "rows": df.to_dict(orient="records")}
