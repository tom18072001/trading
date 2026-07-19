"""One-shot: rebuild real cap-weighted close_idx for all sectors, then
recompute §16 leading features and persist into sector_flow_daily.

Usage:
    DATABASE_PATH=... python scripts/fix_close_idx.py
"""
from __future__ import annotations
import os
import sys
import time
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import SessionLocal
from database.models import SectorFlowDaily
from services.sector_ingest_service import SectorIngestService
from config import PROXY_BASKETS
CONSTITUENT_WEIGHTS: dict[str, dict[str, float]] = {}
from analysis.stealth import compute_leading_features

SLEEP = float(os.environ.get("INGEST_SLEEP", "3.3"))


def rebuild_close_idx(session) -> int:
    svc = SectorIngestService(session)
    start = "2024-01-01"
    end = pd.Timestamp.now().strftime("%Y-%m-%d")
    updated_total = 0
    for code, symbols in PROXY_BASKETS.items():
        print(f"[fix] {code}: fetching {len(symbols)} constituents...")
        frames: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                df = svc._fetch_constituent_daily(sym, start, end)
            except BaseException as e:
                print(f"  ! {sym}: {e}")
                df = pd.DataFrame()
            if not df.empty:
                frames[sym] = df[["close"]].copy()
            time.sleep(SLEEP)
        if not frames:
            print(f"  ! no data for {code}, skip")
            continue
        # Normalise each series to 100 at first common date, then cap-weight
        weights = CONSTITUENT_WEIGHTS.get(code, {s: 1.0 / len(symbols) for s in symbols})
        norm_parts = []
        for sym, df in frames.items():
            s = df["close"].astype(float)
            if s.iloc[0] == 0 or pd.isna(s.iloc[0]):
                continue
            norm = (s / s.iloc[0]) * 100.0
            w = float(weights.get(sym, 1.0 / len(frames)))
            norm_parts.append(norm * w)
        if not norm_parts:
            continue
        idx_series = pd.concat(norm_parts, axis=1).sum(axis=1, min_count=1)
        idx_series = idx_series.dropna()
        # UPDATE matching daily rows
        rows = (
            session.query(SectorFlowDaily)
            .filter_by(sector_code=code)
            .all()
        )
        by_date = {r.date: r for r in rows}
        last_close = None
        wrote = 0
        for ts in idx_series.index.sort_values():
            d = pd.Timestamp(ts).strftime("%Y-%m-%d")
            row = by_date.get(d)
            if row is None:
                continue
            cv = float(idx_series.loc[ts])
            row.close_idx = cv
            row.return_1d = (cv / last_close - 1.0) if last_close else None
            last_close = cv
            wrote += 1
        print(f"  ✓ {code}: updated {wrote} rows")
        updated_total += wrote
    session.commit()
    return updated_total


def rebuild_leading_features(session) -> int:
    rows = session.query(SectorFlowDaily).order_by(
        SectorFlowDaily.sector_code, SectorFlowDaily.date
    ).all()
    df = pd.DataFrame([{
        "date": r.date, "sector_code": r.sector_code,
        "net_dollar_flow": r.net_dollar_flow or 0.0,
        "foreign_net": r.foreign_net or 0.0,
        "atr_pct": r.atr_pct or 0.0,
        "close_idx": r.close_idx or 0.0,
        "breadth_sma20": r.breadth_sma20 or 0.0,
    } for r in rows])
    feat = compute_leading_features(df)
    by_key = {(r.sector_code, r.date): r for r in rows}
    n = 0
    for _, f in feat.iterrows():
        r = by_key.get((f["sector_code"], f["date"]))
        if r is None:
            continue
        r.flow_z20 = float(f["flow_z20"]) if pd.notna(f["flow_z20"]) else None
        r.flow_z60 = float(f["flow_z60"]) if pd.notna(f["flow_z60"]) else None
        r.foreign_streak = int(f["foreign_streak"]) if pd.notna(f["foreign_streak"]) else 0
        r.foreign_hit_20d = float(f["foreign_hit_20d"]) if pd.notna(f["foreign_hit_20d"]) else 0.0
        r.stealth_score = float(f["stealth_score"]) if pd.notna(f["stealth_score"]) else 0.0
        r.flow_price_divergence = float(f["flow_price_divergence"]) if pd.notna(f["flow_price_divergence"]) else 0.0
        r.accumulation_age = int(f["accumulation_age"])
        n += 1
    session.commit()
    return n


if __name__ == "__main__":
    s = SessionLocal()
    try:
        n1 = rebuild_close_idx(s)
        print(f"[fix] close_idx updated rows: {n1}")
        n2 = rebuild_leading_features(s)
        print(f"[fix] leading features updated rows: {n2}")
    finally:
        s.close()
