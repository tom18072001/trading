"""Phase 15 — /api/pulse/* (Feature D Flow Pulse)."""
from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Query

from config import SECTORS
from database.connection import SessionLocal
from database.models import SectorFlowDaily

router = APIRouter(prefix="/api/pulse", tags=["flow-pulse"])


@router.get("/live")
def pulse_live(alert_z: float = Query(1.5)):
    sess = SessionLocal()
    try:
        rows = (
            sess.query(SectorFlowDaily)
            .order_by(SectorFlowDaily.date.desc())
            .limit(15 * 40)
            .all()
        )
    finally:
        sess.close()
    if not rows:
        return {"as_of": None, "rows": []}

    df = pd.DataFrame([{
        "sector": r.sector_code,
        "date": r.date,
        "flow": r.net_dollar_flow or 0.0,
        "z": r.flow_z20 or 0.0,
        "streak": r.foreign_streak or 0,
    } for r in rows]).sort_values(["sector", "date"])
    latest_date = df["date"].max()

    out = []
    for sector, g in df.groupby("sector"):
        g = g.sort_values("date").tail(20)
        last = g.iloc[-1]
        prev = g.iloc[-2] if len(g) >= 2 else last
        total = float(g["flow"].abs().sum() or 1.0)
        delta_share = (float(last["flow"]) - float(prev["flow"])) / total * 100.0
        arrow = "up" if last["z"] > prev["z"] else ("down" if last["z"] < prev["z"] else "flat")
        out.append({
            "sector": sector,
            "name": SECTORS.get(sector, sector),
            "arrow": arrow,
            "delta_share_pct": round(delta_share, 3),
            "flow_z20": float(last["z"]),
            "flow_z20_delta": float(last["z"] - prev["z"]),
            "foreign_streak": int(last["streak"]),
            "alert": bool(abs(last["z"]) >= alert_z),
            "sparkline": g["flow"].tolist(),
        })
    out.sort(key=lambda r: r["flow_z20"], reverse=True)
    return {"as_of": str(latest_date), "alert_z": alert_z, "rows": out}


@router.get("/alerts")
def pulse_alerts(alert_z: float = Query(1.5)):
    data = pulse_live(alert_z)
    alerts = [
        {
            "ts": data["as_of"],
            "sector": r["sector"],
            "event": "z_cross_extreme" if abs(r["flow_z20"]) >= 2.0 else "z_cross_hot",
            "value": r["flow_z20"],
            "message": f"{r['sector']} flow_z20 = {r['flow_z20']:.2f}",
        }
        for r in data["rows"] if r["alert"]
    ]
    return {"rows": alerts}


@router.get("/exposure")
def pulse_exposure():
    # No live portfolio feed yet — return empty; page renders empty-state.
    return {"rows": []}
