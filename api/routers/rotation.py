"""Phase 15 — /api/rotation/* (Feature B Rotation Map).

Minimal first-cut implementing specs/rotation-map.md §4. Pair detection
lives inline here until the codebase grows large enough to warrant a
services/rotation/ package.
"""
from __future__ import annotations

from typing import Optional
import math

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from config import SECTORS
from database.connection import SessionLocal
from database.models import SectorFlowDaily
from services.flow.aggregation import normalize_interval

router = APIRouter(prefix="/api/rotation", tags=["rotation-map"])

_WINDOW_DAYS = {"1d": 2, "1w": 7, "2w": 14, "1m": 30, "1q": 90}


def _load_window(days: int) -> pd.DataFrame:
    sess = SessionLocal()
    try:
        rows = (
            sess.query(SectorFlowDaily)
            .order_by(SectorFlowDaily.date.desc())
            .limit(days * 20)
            .all()
        )
    finally:
        sess.close()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([{
        "sector_code": r.sector_code,
        "date": r.date,
        "net_dollar_flow": r.net_dollar_flow or 0.0,
        "flow_z20": r.flow_z20 or 0.0,
    } for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["sector_code", "date"])


def _detect_pairs(interval: str, threshold: float, limit: int):
    days = _WINDOW_DAYS[interval]
    df = _load_window(days + 5)
    if df.empty:
        return {"window": None, "nodes": [], "links": [], "pairs": []}

    end = df["date"].max()
    start = end - pd.Timedelta(days=days)
    win = df[df["date"] >= start]
    if win.empty:
        return {"window": None, "nodes": [], "links": [], "pairs": []}

    # flow share start vs end
    start_snap = win.groupby("sector_code").first()
    end_snap = win.groupby("sector_code").last()

    def _shares(snap):
        total = snap["net_dollar_flow"].abs().sum() or 1.0
        return snap["net_dollar_flow"] / total

    s0 = _shares(start_snap)
    s1 = _shares(end_snap)
    delta = (s1 - s0).fillna(0.0)
    sigma = float(delta.std() or 1e-9)

    sources = delta[delta < -threshold * sigma].sort_values().index.tolist()
    targets = delta[delta > +threshold * sigma].sort_values(ascending=False).index.tolist()

    # correlation matrix on daily flow over the window
    pivot = win.pivot_table(
        index="date", columns="sector_code", values="net_dollar_flow", aggfunc="sum"
    ).fillna(0.0)
    corr = pivot.corr() if pivot.shape[0] >= 2 else None

    pairs = []
    for src in sources:
        for tgt in targets:
            weight = min(abs(delta[src]), abs(delta[tgt]))
            c = float(corr.loc[src, tgt]) if corr is not None and src in corr and tgt in corr.columns else 0.0
            score = weight * (abs(c) + 0.1)
            if not math.isfinite(score):
                continue
            pairs.append({
                "from": src,
                "to": tgt,
                "delta_share_source": float(delta[src]),
                "delta_share_target": float(delta[tgt]),
                "weight": float(score),
                "corr": c,
                "lag_days": 0,  # not estimated in first cut
            })

    pairs.sort(key=lambda p: p["weight"], reverse=True)
    pairs = pairs[:limit]

    nodes = [{"id": s, "side": "source", "delta_share": float(delta[s])} for s in sources]
    nodes += [{"id": s, "side": "target", "delta_share": float(delta[s])} for s in targets]

    return {
        "window": {"start": str(start.date()), "end": str(end.date())},
        "nodes": nodes,
        "links": pairs,
        "pairs": pairs,
    }


@router.get("/sankey")
def rotation_sankey(interval: str = Query("1w"), threshold: float = Query(1.5)):
    try:
        interval = normalize_interval(interval)
    except ValueError as e:
        raise HTTPException(400, str(e))
    data = _detect_pairs(interval, threshold, limit=50)
    return {"interval": interval, **{k: v for k, v in data.items() if k != "pairs"}}


@router.get("/pairs")
def rotation_pairs(
    interval: str = Query("1w"),
    threshold: float = Query(1.5),
    limit: int = Query(20),
):
    try:
        interval = normalize_interval(interval)
    except ValueError as e:
        raise HTTPException(400, str(e))
    data = _detect_pairs(interval, threshold, limit=limit)
    rows = []
    for i, p in enumerate(data["pairs"], 1):
        dzs = p["delta_share_source"]
        dzt = p["delta_share_target"]
        action = "CONFIRMED" if (p["corr"] or 0) >= 0.4 else "EMERGING"
        rows.append({
            "rank": i,
            "from": p["from"],
            "to": p["to"],
            "from_name": SECTORS.get(p["from"], p["from"]),
            "to_name": SECTORS.get(p["to"], p["to"]),
            "delta_share_source": dzs,
            "delta_share_target": dzt,
            "corr": p["corr"],
            "weight": p["weight"],
            "action": action,
        })
    return {"interval": interval, "window": data["window"], "rows": rows}
