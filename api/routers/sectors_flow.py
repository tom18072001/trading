# ============================================
# api/routers/sectors_flow.py
# ============================================
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.connection import get_session_dependency
from database.models import SectorAccumulationEvent, SectorFlowDaily, SectorFlowTS

router = APIRouter(prefix="/api/sectors", tags=["sectors-flow"])


@router.get("/flow")
def list_flow(limit: int = 100, db: Session = Depends(get_session_dependency)):
    rows = (
        db.query(SectorFlowDaily)
        .order_by(SectorFlowDaily.date.desc(), SectorFlowDaily.sector_code)
        .limit(limit)
        .all()
    )
    return [
        {
            "sector_code": r.sector_code, "date": r.date,
            "net_dollar_flow": r.net_dollar_flow,
            "foreign_net": r.foreign_net,
            "up_down_vol_ratio": r.up_down_vol_ratio,
            "breadth_sma20": r.breadth_sma20,
            "atr_pct": r.atr_pct,
            "return_1d": r.return_1d,
            # --- §16 leading-flow columns ---
            "flow_z20": r.flow_z20,
            "flow_z60": r.flow_z60,
            "foreign_streak": r.foreign_streak,
            "foreign_hit_20d": r.foreign_hit_20d,
            "stealth_score": r.stealth_score,
            "flow_price_divergence": r.flow_price_divergence,
            "accumulation_age": r.accumulation_age,
        }
        for r in rows
    ]


@router.get("/stealth")
def stealth_now(db: Session = Depends(get_session_dependency)):
    """Sectors currently in stealth-accumulation phase (§16.1).

    Returns the latest daily row per sector whose accumulation_age > 0,
    plus a count of historical stealth events per sector.
    """
    from sqlalchemy import func
    latest_dates = dict(
        db.query(SectorFlowDaily.sector_code, func.max(SectorFlowDaily.date))
          .group_by(SectorFlowDaily.sector_code).all()
    )
    active = []
    for code, d in latest_dates.items():
        row = db.query(SectorFlowDaily).filter_by(sector_code=code, date=d).one_or_none()
        if row is None or (row.accumulation_age or 0) <= 0:
            continue
        active.append({
            "sector_code": row.sector_code, "date": row.date,
            "flow_z20": row.flow_z20, "stealth_score": row.stealth_score,
            "accumulation_age": row.accumulation_age,
            "foreign_hit_20d": row.foreign_hit_20d,
            "flow_price_divergence": row.flow_price_divergence,
        })
    # "Warming" sectors: high flow_z20 but not yet persisted — early warning list
    warming = []
    for code, d in latest_dates.items():
        row = db.query(SectorFlowDaily).filter_by(sector_code=code, date=d).one_or_none()
        if row is None or (row.flow_z20 or 0) < 1.0 or (row.accumulation_age or 0) > 0:
            continue
        warming.append({
            "sector_code": row.sector_code, "date": row.date,
            "flow_z20": row.flow_z20, "stealth_score": row.stealth_score,
        })
    warming.sort(key=lambda r: -(r["flow_z20"] or 0))
    # Recent closed events for attribution
    events = (
        db.query(SectorAccumulationEvent)
          .order_by(SectorAccumulationEvent.start_date.desc())
          .limit(20).all()
    )
    history = [
        {
            "sector_code": e.sector_code, "start_date": e.start_date,
            "end_date": e.end_date, "resolved": bool(e.resolved),
            "peak_return_pct": e.peak_return_pct,
            "lead_days_to_price": e.lead_days_to_price,
        }
        for e in events
    ]
    return {"active": active, "warming": warming, "history": history}


@router.get("/{sector_code}/flow")
def sector_flow(sector_code: str, limit: int = 60, db: Session = Depends(get_session_dependency)):
    rows = (
        db.query(SectorFlowTS)
        .filter(SectorFlowTS.sector_code == sector_code)
        .order_by(SectorFlowTS.time.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "time": r.time.isoformat() if r.time else None,
            "net_dollar_flow": r.net_dollar_flow,
            "foreign_net": r.foreign_net,
            "breadth_sma20": r.breadth_sma20,
            "atr_pct": r.atr_pct,
        }
        for r in rows
    ]
