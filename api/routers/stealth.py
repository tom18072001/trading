"""Phase 15 — /api/stealth/* (Feature C Stealth Watch).

Uses pre-computed columns from sector_flow_daily (flow_z20, foreign_hit_20d,
breadth_sma20, atr_pct, close_idx, stealth_score, accumulation_age) rather
than recomputing on every request.
"""
from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Query
from sqlalchemy import func

from config import SECTORS
from database.connection import SessionLocal
from database.models import SectorFlowDaily

router = APIRouter(prefix="/api/stealth", tags=["stealth-watch"])


def _build_gate(flow_z, foreign_hit, breadth, atr_pct, close_pct,
                flow_z_hot, foreign_hit_min, breadth_min, atr_rank_max, close_pct_60d_max):
    gate = {}

    c1 = flow_z >= flow_z_hot
    gate["cond1_flow"] = {
        "pass": c1, "value": round(flow_z, 3), "threshold": flow_z_hot,
        "label": "Flow Z20 >= hot",
        "reason": f"flow_z20 = {flow_z:+.2f} {'≥' if c1 else '<'} {flow_z_hot}"
                  + ("" if c1 else f" — thiếu {flow_z_hot - flow_z:.2f}"),
    }

    c2 = foreign_hit >= foreign_hit_min
    gate["cond2_foreign"] = {
        "pass": c2, "value": round(foreign_hit, 3), "threshold": foreign_hit_min,
        "label": "Foreign Hit 20d >= min",
        "reason": f"foreign_hit = {foreign_hit:.0%} {'≥' if c2 else '<'} {foreign_hit_min:.0%}"
                  + ("" if c2 else f" — thiếu {(foreign_hit_min - foreign_hit):.0%}"),
    }

    c3 = breadth >= breadth_min
    gate["cond3_breadth"] = {
        "pass": c3, "value": round(breadth, 3), "threshold": breadth_min,
        "label": "Breadth SMA20 rising",
        "reason": f"breadth = {breadth:.2f} {'≥' if c3 else '<'} {breadth_min}"
                  + ("" if c3 else f" — thiếu {breadth_min - breadth:.2f}"),
    }

    # atr_pct: lower = quieter. Use percentile rank within sector as proxy.
    # For now: atr_pct < atr_rank_max means quiet tape
    c4 = atr_pct <= atr_rank_max
    gate["cond4_atr_quiet"] = {
        "pass": c4, "value": round(atr_pct, 3), "threshold": atr_rank_max,
        "label": "ATR quiet (low vol)",
        "reason": f"atr_pct = {atr_pct:.2f} {'≤' if c4 else '>'} {atr_rank_max}"
                  + ("" if c4 else f" — vượt {atr_pct - atr_rank_max:.2f}"),
    }

    # close_pct: position within 60d range. 0 = bottom, 1 = top.
    # If close_idx is 0 or null, we can't compute this — flag it.
    close_data_ok = (close_pct is not None and close_pct > 0.001)
    c5 = close_pct <= close_pct_60d_max if close_data_ok else False
    gate["cond5_price_cheap"] = {
        "pass": c5, "value": round(close_pct, 3) if close_data_ok else 0.0,
        "threshold": close_pct_60d_max,
        "label": "Price cheap (bottom of 60d range)",
        "reason": (
            f"close_pct = {close_pct:.2f} {'≤' if c5 else '>'} {close_pct_60d_max}"
            + ("" if c5 else f" — vượt {close_pct - close_pct_60d_max:.2f}")
        ) if close_data_ok else "⚠ close_idx chưa backfill — không thể đánh giá cond 5",
    }

    return gate


@router.get("/active")
def stealth_active(
    flow_z_hot: float = Query(1.0),
    foreign_hit_min: float = Query(0.6),
    breadth_min: float = Query(0.5),
    atr_rank_max: float = Query(0.5),
    close_pct_60d_max: float = Query(0.4),
    min_sessions: int = Query(5),
):
    """Returns ALL 15 sectors classified into active / warming / inactive."""
    sess = SessionLocal()
    try:
        # Get the latest date
        latest_date = sess.query(func.max(SectorFlowDaily.date)).scalar()
        if not latest_date:
            return {"as_of": None, "active": [], "warming": [], "inactive": []}

        # Get latest row per sector
        latest_rows = (
            sess.query(SectorFlowDaily)
            .filter(SectorFlowDaily.date == latest_date)
            .all()
        )

        # Also get 60-day window per sector to compute close_pct
        window_rows = (
            sess.query(SectorFlowDaily)
            .filter(SectorFlowDaily.date >= str(pd.Timestamp(latest_date) - pd.Timedelta(days=90)))
            .all()
        )
    finally:
        sess.close()

    # Build 60d high/low per sector for close_pct computation
    close_range: dict[str, tuple[float, float]] = {}  # sector -> (min_close, max_close)
    for r in window_rows:
        c = r.close_idx or 0.0
        if c <= 0:
            continue
        code = r.sector_code
        if code not in close_range:
            close_range[code] = (c, c)
        else:
            lo, hi = close_range[code]
            close_range[code] = (min(lo, c), max(hi, c))

    active, warming, inactive = [], [], []
    for r in latest_rows:
        flow_z = r.flow_z20 or 0.0
        foreign_hit = r.foreign_hit_20d or 0.0
        breadth = r.breadth_sma20 or 0.0
        atr_pct = r.atr_pct or 0.0
        close_val = r.close_idx or 0.0
        age = r.accumulation_age or 0
        score = r.stealth_score or 0.0

        # compute close_pct from 60d range
        close_pct = None
        if r.sector_code in close_range and close_val > 0:
            lo, hi = close_range[r.sector_code]
            if hi > lo:
                close_pct = (close_val - lo) / (hi - lo)
            else:
                close_pct = 0.5
        if close_pct is None:
            close_pct = 0.0  # no data

        gate = _build_gate(flow_z, foreign_hit, breadth, atr_pct, close_pct,
                           flow_z_hot, foreign_hit_min, breadth_min, atr_rank_max, close_pct_60d_max)
        passes = sum(1 for g in gate.values() if g["pass"])
        fails = [g["label"] for g in gate.values() if not g["pass"]]

        if passes == 5 and age >= min_sessions:
            status = "active"
        elif passes >= 3:
            status = "warming"
        else:
            status = "inactive"

        entry = {
            "sector": r.sector_code,
            "name": SECTORS.get(r.sector_code, r.sector_code),
            "status": status,
            "accumulation_age": age,
            "stealth_score": round(score, 3),
            "flow_z20": round(flow_z, 3),
            "foreign_hit_20d": round(foreign_hit, 3),
            "breadth_sma20": round(breadth, 3),
            "atr_pct": round(atr_pct, 3),
            "close_pct_60d": round(close_pct, 3),
            "gate": gate,
            "conditions_passing": passes,
            "conditions_failing": 5 - passes,
            "fail_summary": ", ".join(fails) if fails else "All pass",
        }
        if status == "active":
            active.append(entry)
        elif status == "warming":
            warming.append(entry)
        else:
            inactive.append(entry)

    for lst in (active, warming, inactive):
        lst.sort(key=lambda x: (x["conditions_passing"], x["stealth_score"]), reverse=True)

    return {
        "as_of": str(latest_date),
        "thresholds": {
            "flow_z_hot": flow_z_hot,
            "foreign_hit_min": foreign_hit_min,
            "breadth_min": breadth_min,
            "atr_rank_max": atr_rank_max,
            "close_pct_60d_max": close_pct_60d_max,
            "min_sessions": min_sessions,
        },
        "active": active,
        "warming": warming,
        "inactive": inactive,
    }


@router.get("/history")
def stealth_history(limit: int = Query(50)):
    return {"rows": []}
