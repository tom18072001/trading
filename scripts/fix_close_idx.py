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


# One implementation of the leading-feature rebuild, shared with the scheduled
# rollup (2026-09-25). Re-exported here because other scripts import it from
# this module.
from services.fast_ingest import rebuild_leading_features  # noqa: E402, F401


if __name__ == "__main__":
    s = SessionLocal()
    try:
        n1 = rebuild_close_idx(s)
        print(f"[fix] close_idx updated rows: {n1}")
        n2 = rebuild_leading_features(s)
        print(f"[fix] leading features updated rows: {n2}")
    finally:
        s.close()
