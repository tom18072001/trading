"""Phase 15 — /api/flow/* router for Feature A Money Flow Monitor.

Implements specs/flow-monitor.md §4. All time-series endpoints accept
an `interval` query param (1d/1w/2w/1m/1q) and resample server-side via
services.flow.aggregation.

Endpoints:
    GET /api/flow/series
    GET /api/flow/ranking
    GET /api/flow/heat
    GET /api/flow/sector/{code}
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from config import SECTORS
from database.connection import SessionLocal
from database.models import SectorFlowDaily
from services.flow.aggregation import normalize_interval, resample

router = APIRouter(prefix="/api/flow", tags=["flow-monitor"])


# --------------------------- helpers ---------------------------
def _load_daily(
    sector: Optional[str] = None,
    days: int = 400,
) -> pd.DataFrame:
    sess = SessionLocal()
    try:
        # `days` counts SESSIONS, not rows. This used to be `.limit(days * 20)`,
        # a row cap that always exceeded the table (15 sectors x ~900 sessions),
        # so every lookback value returned the identical 1319 points and the
        # UI's lookback buttons did nothing (review 2026-08-23, A5). Bound the
        # distinct dates first, then take every row on or after the oldest one.
        dq = sess.query(SectorFlowDaily.date).distinct()
        if sector:
            dq = dq.filter(SectorFlowDaily.sector_code == sector)
        dates = [d[0] for d in dq.order_by(SectorFlowDaily.date.desc()).limit(days).all()]
        if not dates:
            return pd.DataFrame()

        q = sess.query(SectorFlowDaily).filter(SectorFlowDaily.date >= min(dates))
        if sector:
            q = q.filter(SectorFlowDaily.sector_code == sector)
        rows = q.order_by(SectorFlowDaily.date.desc()).all()
    finally:
        sess.close()

    if not rows:
        return pd.DataFrame()
    records = []
    for r in rows:
        records.append({
            "sector_code": r.sector_code,
            "date": r.date,
            "net_dollar_flow": r.net_dollar_flow or 0.0,
            "foreign_net": r.foreign_net or 0.0,
            "close_idx": r.close_idx or 0.0,
            "flow_z20": r.flow_z20,
            "flow_z60": r.flow_z60,
            "stealth_score": r.stealth_score,
            "breadth_sma20": r.breadth_sma20,
            "atr_pct": r.atr_pct,
            "return_1d": r.return_1d,
            "foreign_hit_20d": r.foreign_hit_20d,
            "foreign_streak": r.foreign_streak,
        })
    return pd.DataFrame(records)


def _as_of(df: pd.DataFrame) -> Optional[str]:
    if df.empty:
        return None
    return str(df["date"].max())


# --------------------------- endpoints ---------------------------
@router.get("/series")
def flow_series(
    interval: str = Query("1d"),
    sectors: Optional[str] = Query(None, description="Comma-separated sector codes; default = all 15"),
    lookback: int = Query(120, ge=20, le=2000),
):
    """Multi-sector time series of net_dollar_flow, flow_z20, close_idx,
    resampled to the requested interval. Shape driven by flow-monitor.md §3.

    2026-08-23: the default lookback was 400 sessions x 15 sectors, which made
    this the slowest route in the API by an order of magnitude -- measured at
    **3,338 ms and 1.19 MB** while every other route sat between 10 and 200 ms.
    A chart shows months, not years. 120 sessions (~6 months) is the default
    now; ask for more explicitly with ?lookback= when you actually need it.
    Values are also rounded on the way out -- full float64 repr was spending
    ~17 characters per number to express noise well below display precision.
    """
    try:
        interval = normalize_interval(interval)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    codes = [c.strip().upper() for c in sectors.split(",")] if sectors else list(SECTORS.keys())
    df = _load_daily(days=lookback)
    if df.empty:
        return {"interval": interval, "as_of": None, "sectors": [], "series": []}
    df = df[df["sector_code"].isin(codes)]
    res = resample(df, interval)

    series = []
    for code, g in res.groupby("sector_code", sort=False):
        g = g.sort_values("date")
        series.append({
            "sector": code,
            "points": [
                {
                    "date": row["date"],
                    "net_dollar_flow": round(float(row.get("net_dollar_flow") or 0.0), 2),
                    "flow_z20": None if pd.isna(row.get("flow_z20")) else round(float(row["flow_z20"]), 4),
                    "close_idx": None if pd.isna(row.get("close_idx")) else round(float(row["close_idx"]), 3),
                }
                for _, row in g.iterrows()
            ],
        })
    return {
        "interval": interval,
        "as_of": _as_of(res),
        "sectors": codes,
        "series": series,
    }


@router.get("/ranking")
def flow_ranking(
    interval: str = Query("1d"),
    flow_z_hot: float = Query(1.0),
):
    """Sector ranking table for Feature A (merges legacy /ranking).
    One row per sector with the 'why' components spec §3 calls out."""
    try:
        interval = normalize_interval(interval)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    df = _load_daily(days=400)
    if df.empty:
        return {"interval": interval, "as_of": None, "rows": []}

    res = resample(df, interval)
    latest_date = res["date"].max()
    snap = res[res["date"] == latest_date]

    rows = []
    for _, r in snap.iterrows():
        z = r.get("flow_z20")
        z = float(z) if pd.notna(z) else 0.0
        net = float(r.get("net_dollar_flow") or 0.0)
        breadth = r.get("breadth_sma20")
        breadth = float(breadth) if pd.notna(breadth) else 0.0
        atr = r.get("atr_pct")
        atr = float(atr) if pd.notna(atr) else 0.0

        # composite score — simple + transparent, surfaced in 'why'
        score = z * 0.6 + (1.0 if net > 0 else -1.0) * min(abs(net) / 1e9, 1.0) * 0.4

        why_bits = []
        if abs(z) >= flow_z_hot:
            why_bits.append(f"flow_z20 {'+' if z>=0 else ''}{z:.2f}")
        if net != 0:
            why_bits.append(f"net_flow {net/1e9:+.2f}B")
        if breadth:
            why_bits.append(f"breadth {breadth:.2f}")

        action = "HOT" if z >= flow_z_hot else ("COOL" if z <= -flow_z_hot else "NEUTRAL")
        rows.append({
            "sector": r["sector_code"],
            "name": SECTORS.get(r["sector_code"], r["sector_code"]),
            "score": round(score, 3),
            "flow_z20": round(z, 3),
            "net_dollar_flow": net,
            "breadth_sma20": breadth,
            "atr_pct": atr,
            "action": action,
            "why": ", ".join(why_bits) or "—",
        })
    rows.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    return {"interval": interval, "as_of": latest_date, "flow_z_hot": flow_z_hot, "rows": rows}


@router.get("/heat")
def flow_heat(
    interval: str = Query("1d"),
    lookback: int = Query(60, ge=10, le=500),
):
    """Heat strip: [sector × bucket] grid of flow_z20 for the header viz."""
    try:
        interval = normalize_interval(interval)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    df = _load_daily(days=lookback)
    if df.empty:
        return {"interval": interval, "as_of": None, "buckets": [], "cells": []}
    res = resample(df, interval)
    buckets = sorted(res["date"].unique().tolist())
    cells = []
    for _, r in res.iterrows():
        z = r.get("flow_z20")
        cells.append({
            "sector": r["sector_code"],
            "bucket": r["date"],
            "flow_z20": None if pd.isna(z) else float(z),
        })
    return {
        "interval": interval,
        "as_of": _as_of(res),
        "buckets": buckets,
        "cells": cells,
    }


@router.get("/index")
def flow_index(lookback: int = Query(60, ge=5, le=500)):
    """VNINDEX price series for the index tracker panel.
    Uses macro_anchors if available, falls back to a lightweight aggregate
    of all sector close_idx values."""
    from sqlalchemy import text
    sess = SessionLocal()
    try:
        # Try macro_anchors first
        rows = sess.execute(
            text("SELECT time, vnindex FROM macro_anchors WHERE vnindex IS NOT NULL ORDER BY time DESC LIMIT :n"),
            {"n": lookback}
        ).fetchall()
        if rows and len(rows) >= 2:
            points = [{"date": str(r[0])[:10], "vnindex": float(r[1])} for r in reversed(rows)]
            return {"source": "macro_anchors", "points": points}

        # Fallback: compute a synthetic market index from the average close_idx across sectors
        all_rows = (
            sess.query(SectorFlowDaily)
            .filter(SectorFlowDaily.close_idx.isnot(None))
            .filter(SectorFlowDaily.close_idx > 0)
            .order_by(SectorFlowDaily.date.desc())
            .limit(lookback * 15)
            .all()
        )
        if not all_rows:
            return {"source": "none", "points": []}

        df = pd.DataFrame([{"date": r.date, "close_idx": r.close_idx} for r in all_rows])
        agg = df.groupby("date")["close_idx"].mean().sort_index()
        points = [{"date": d, "vnindex": round(float(v), 2)} for d, v in agg.items()]
        return {"source": "sector_avg_close_idx", "points": points[-lookback:]}
    finally:
        sess.close()


@router.post("/refresh")
def flow_refresh():
    """Manual refresh — fast incremental ingest via VCI+VNDirect (no vnstock).

    1. Check freshness: if latest_date == last trading day → already_fresh.
    2. Otherwise launch background ingest job (returns immediately).
    3. Frontend polls GET /flow/refresh/status until done.
    """
    from services.fast_ingest import get_freshness, start_ingest_job
    from database.connection import SessionLocal as _SL
    sess = _SL()
    try:
        fresh = get_freshness(sess)
        if fresh["is_fresh"]:
            return {"status": "already_fresh", **fresh}
        result = start_ingest_job(_SL)
        return result
    except Exception as e:
        raise HTTPException(500, f"refresh failed: {type(e).__name__}: {e}")
    finally:
        sess.close()


@router.get("/refresh/status")
def flow_refresh_status():
    """Poll incremental ingest job progress."""
    from services.fast_ingest import get_ingest_status
    return get_ingest_status()


@router.get("/freshness")
def flow_freshness():
    """Check DB freshness without triggering ingest."""
    from services.fast_ingest import get_freshness
    sess = SessionLocal()
    try:
        return get_freshness(sess)
    finally:
        sess.close()


@router.get("/sector/{code}")
def flow_sector_detail(code: str, interval: str = Query("1d"), lookback: int = Query(400, ge=20, le=2000)):
    code = code.upper()
    if code not in SECTORS:
        raise HTTPException(status_code=404, detail=f"Unknown sector {code}")
    try:
        interval = normalize_interval(interval)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    df = _load_daily(sector=code, days=lookback)
    if df.empty:
        return {"sector": code, "interval": interval, "points": []}
    res = resample(df, interval).sort_values("date")
    points = []
    for _, row in res.iterrows():
        points.append({
            "date": row["date"],
            "net_dollar_flow": float(row.get("net_dollar_flow") or 0.0),
            "foreign_net": float(row.get("foreign_net") or 0.0),
            "foreign_buy_val": float(row.get("foreign_buy_val") or 0.0),
            "foreign_sell_val": float(row.get("foreign_sell_val") or 0.0),
            "flow_z20": None if pd.isna(row.get("flow_z20")) else float(row["flow_z20"]),
            "flow_z60": None if pd.isna(row.get("flow_z60")) else float(row["flow_z60"]),
            "close_idx": None if pd.isna(row.get("close_idx")) else float(row["close_idx"]),
            "breadth_sma20": None if pd.isna(row.get("breadth_sma20")) else float(row["breadth_sma20"]),
            "breadth_sma50": None if pd.isna(row.get("breadth_sma50")) else float(row["breadth_sma50"]),
            "atr_pct": None if pd.isna(row.get("atr_pct")) else float(row["atr_pct"]),
            "up_down_vol_ratio": None if pd.isna(row.get("up_down_vol_ratio")) else float(row["up_down_vol_ratio"]),
            "foreign_hit_20d": None if pd.isna(row.get("foreign_hit_20d")) else float(row.get("foreign_hit_20d", 0)),
            "foreign_streak": None if pd.isna(row.get("foreign_streak")) else int(row.get("foreign_streak", 0)),
            "stealth_score": None if pd.isna(row.get("stealth_score")) else float(row.get("stealth_score", 0)),
        })

    # Distribution stats for the sector
    ndf = df["net_dollar_flow"].dropna()
    fz = df["flow_z20"].dropna()
    stats = {
        "net_flow_mean": float(ndf.mean()) if len(ndf) else None,
        "net_flow_std": float(ndf.std()) if len(ndf) else None,
        "net_flow_median": float(ndf.median()) if len(ndf) else None,
        "net_flow_q25": float(ndf.quantile(0.25)) if len(ndf) else None,
        "net_flow_q75": float(ndf.quantile(0.75)) if len(ndf) else None,
        "flow_z20_mean": float(fz.mean()) if len(fz) else None,
        "flow_z20_std": float(fz.std()) if len(fz) else None,
        "total_days": len(df),
        "positive_flow_days": int((ndf > 0).sum()) if len(ndf) else 0,
        "negative_flow_days": int((ndf < 0).sum()) if len(ndf) else 0,
    }

    return {
        "sector": code,
        "name": SECTORS.get(code, code),
        "interval": interval,
        "as_of": _as_of(res),
        "points": points,
        "stats": stats,
    }
