"""Phase 15 — /api/stealth/* (Feature C Stealth Watch).

Uses pre-computed columns from sector_flow_daily (flow_z20, foreign_hit_20d,
breadth_sma20, atr_pct, close_idx, stealth_score, accumulation_age) rather
than recomputing on every request.

2026-08-23: reconciled with `analysis/stealth.py`. This endpoint used to
classify `active` only at `passes == 5` while the offline scanner that writes
`accumulation_age` required 3 conditions — so the page could show a sector the
scanner would never record, and vice versa. Both now read the same two knobs
(`STEALTH_MIN_CONDITIONS`, `STEALTH_MIN_SESSIONS`) and both are scores, not
conjunctions. See CLAUDE.md §16.1.
"""
from __future__ import annotations

from statistics import median

import pandas as pd
from fastapi import APIRouter, Query
from sqlalchemy import func

from analysis.stealth import (
    STEALTH_MIN_CONDITIONS,
    STEALTH_MIN_SESSIONS,
    stealth_events,
)
from config import SECTORS
from database.connection import SessionLocal
from database.models import SectorFlowDaily

router = APIRouter(prefix="/api/stealth", tags=["stealth-watch"])

#: Display strings for `stealth_events()`'s classification. A lookup rather than
#: `.replace("_", " ").upper()`, because that mangling silently produces
#: "DRY POWDER TIMEOUT" while `StealthWatchPage`'s chip map keys on
#: "DRY-POWDER TIMEOUT" — a miss that renders as an unstyled grey chip and looks
#: like a data problem rather than a string problem.
_CLASSIFICATION_LABEL = {
    "hit": "HIT",
    "false_positive": "FALSE POSITIVE",
    "dry_powder_timeout": "DRY-POWDER TIMEOUT",
}


def _build_gate(flow_z, foreign_hit, breadth, atr_rank, close_pct,
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

    # atr_rank is a 0..1 percentile of today's ATR% within the sector's own 60d
    # window (0 = quietest). It used to be the RAW atr_pct — a ~0.006 fraction
    # compared against a 0.5 threshold named "rank", so cond4 passed for free on
    # every sector and the gate was really four conditions here.
    c4 = atr_rank <= atr_rank_max
    gate["cond4_atr_quiet"] = {
        "pass": c4, "value": round(atr_rank, 3), "threshold": atr_rank_max,
        "label": "ATR quiet (low vol)",
        "reason": f"atr_rank = {atr_rank:.2f} {'≤' if c4 else '>'} {atr_rank_max}"
                  + ("" if c4 else f" — vượt {atr_rank - atr_rank_max:.2f}"),
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
    min_sessions: int = Query(STEALTH_MIN_SESSIONS),
    min_conditions: int = Query(STEALTH_MIN_CONDITIONS, ge=1, le=5),
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

    # Build 60d high/low per sector for close_pct computation, and the ATR%
    # sample the cond4 percentile rank is taken against.
    close_range: dict[str, tuple[float, float]] = {}  # sector -> (min_close, max_close)
    atr_window: dict[str, list[float]] = {}
    for r in window_rows:
        code = r.sector_code
        a = r.atr_pct or 0.0
        if a > 0:
            atr_window.setdefault(code, []).append(a)
        c = r.close_idx or 0.0
        if c <= 0:
            continue
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

        # cond4 percentile rank of today's ATR% within the sector's own window.
        sample = atr_window.get(r.sector_code) or []
        atr_rank = (sum(1 for a in sample if a <= atr_pct) / len(sample)) if sample else 1.0

        gate = _build_gate(flow_z, foreign_hit, breadth, atr_rank, close_pct,
                           flow_z_hot, foreign_hit_min, breadth_min, atr_rank_max, close_pct_60d_max)
        passes = sum(1 for g in gate.values() if g["pass"])
        fails = [g["label"] for g in gate.values() if not g["pass"]]

        # Score gate, matching analysis/stealth.py. `passes == 5` was
        # unreachable — the longest all-five run in 3.5 years was 2 sessions.
        if passes >= min_conditions and age >= min_sessions:
            status = "active"
        elif passes >= min_conditions - 1:
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
            "atr_rank": round(atr_rank, 3),
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
            "min_conditions": min_conditions,
        },
        "active": active,
        "warming": warming,
        "inactive": inactive,
    }


@router.get("/history")
def stealth_history(limit: int = Query(50, ge=1, le=500)):
    """Past stealth runs, newest first, each scored against §16.15's bar.

    Until 2026-08-24 this returned a hardcoded `{"rows": []}` — the same shape
    of defect as §22.1's Flow Pulse, and it looked correct for months because
    the §16.1 AND gate really did produce zero events. It does not any more:
    53 rows carry `accumulation_age > 0`.

    Derived from `sector_flow_daily.accumulation_age`, **not** from
    `sector_accumulation_events`. That table has existed since migration 9 and
    has never had a writer, so reading it would return the same empty list by a
    longer route; and once something did write it, the same fact would live in
    two places that can disagree. The column is already the thing the scanner
    writes and the Stealth Watch badge renders.
    """
    sess = SessionLocal()
    try:
        rows = (
            sess.query(SectorFlowDaily)
            .order_by(SectorFlowDaily.sector_code, SectorFlowDaily.date)
            .all()
        )
        panel = [{
            "sector_code": r.sector_code,
            "date": r.date,
            "accumulation_age": r.accumulation_age or 0,
            "close_idx": r.close_idx or 0.0,
            "atr_pct": r.atr_pct or 0.0,
            "stealth_score": r.stealth_score or 0.0,
        } for r in rows]
    finally:
        sess.close()

    events = stealth_events(panel)
    scored = [e for e in events if e["classification"]]
    hits = [e for e in scored if e["classification"] == "hit"]
    leads = [e["lead_days_to_price"] for e in hits if e["lead_days_to_price"]]

    return {
        "rows": [{**e, "name": SECTORS.get(e["sector_code"], e["sector_code"]),
                  "classification": _CLASSIFICATION_LABEL.get(e["classification"])}
                 for e in events[:limit]],
        # §16.11 asks three questions of the gate; a history table that shows
        # events without them invites the reader to eyeball a hit rate off a
        # truncated list. `scored` excludes still-open and edge-of-panel runs —
        # see stealth_events() on why those are not failures.
        "summary": {
            "events": len(events),
            "scored": len(scored),
            "hit_rate": round(len(hits) / len(scored), 3) if scored else None,
            "median_lead_days": float(median(leads)) if leads else None,
            "early_share": round(sum(1 for x in leads if x >= 10) / len(leads), 3) if leads else None,
        },
    }
