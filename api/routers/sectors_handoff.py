# ============================================
# api/routers/sectors_handoff.py — flow rotation matrix
# ============================================
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import pandas as pd

from database.connection import get_session_dependency
from database.models import SectorFlowDaily, SectorFlowHandoff
from analysis.flow_handoff import compute_handoff

router = APIRouter(prefix="/api/sectors", tags=["sectors-handoff"])


@router.get("/handoff")
def get_handoff(
    lookback_days: int = 60,
    window: int = 5,
    top_k: int = 5,
    db: Session = Depends(get_session_dependency),
):
    """Compute sector-to-sector flow handoffs from the last `lookback_days`
    of `sector_flow_daily.flow_z20`. Returns strongest `top_k` handoffs per day."""
    rows = (
        db.query(SectorFlowDaily.date, SectorFlowDaily.sector_code, SectorFlowDaily.flow_z20)
        .order_by(SectorFlowDaily.date.desc())
        .limit(lookback_days * 20)
        .all()
    )
    if not rows:
        return {"count": 0, "handoffs": []}
    df = pd.DataFrame(rows, columns=["date", "sector_code", "flow_z20"])
    panel = df.pivot_table(index="date", columns="sector_code", values="flow_z20")
    panel = panel.sort_index().tail(lookback_days)
    out = compute_handoff(panel, window=window, top_k=top_k)
    return {
        "count": len(out),
        "window": window,
        "handoffs": out.to_dict(orient="records"),
    }


@router.get("/heatmap")
def get_heatmap(
    lookback_days: int = 30,
    db: Session = Depends(get_session_dependency),
):
    """Return a 15×N z-score grid for the Flow Dashboard."""
    rows = (
        db.query(
            SectorFlowDaily.date, SectorFlowDaily.sector_code,
            SectorFlowDaily.flow_z20, SectorFlowDaily.stealth_score,
        )
        .order_by(SectorFlowDaily.date.desc())
        .limit(lookback_days * 20)
        .all()
    )
    return {
        "count": len(rows),
        "cells": [
            {
                "date": r[0], "sector_code": r[1],
                "flow_z20": r[2], "stealth_score": r[3],
            }
            for r in rows
        ],
    }
