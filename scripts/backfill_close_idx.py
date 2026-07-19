"""Phase 15 — Real close_idx backfill using VCI TradingView API directly.

Bypasses vnstock library (which hangs due to vnai telemetry) and hits the
VCI histdatafeed endpoint directly. Equal-weight close_idx across the
proxy basket.

Usage:
    python scripts/backfill_close_idx.py [--years 3] [--force] [--sleep 0.5]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

from database.connection import SessionLocal
from database.models import SectorFlowDaily
from config import PROXY_BASKETS

VCI_URL = "https://histdatafeed.vps.com.vn/tradingview/history"
SLEEP = float(os.environ.get("INGEST_SLEEP", "0.5"))


def _fetch_close(symbol: str, start_ts: int, end_ts: int) -> pd.Series:
    """Fetch daily close via VCI TradingView endpoint. Returns Series indexed by YYYY-MM-DD."""
    try:
        r = requests.get(VCI_URL, params={
            "symbol": symbol,
            "resolution": "D",
            "from": start_ts,
            "to": end_ts,
        }, timeout=15)
        r.raise_for_status()
        d = r.json()
        if d.get("s") == "no_data" or "c" not in d or "t" not in d:
            return pd.Series(dtype=float)
        dates = pd.to_datetime(d["t"], unit="s").strftime("%Y-%m-%d")
        return pd.Series(d["c"], index=dates, dtype=float)
    except Exception as e:
        print(f"  ! {symbol}: {type(e).__name__}: {e}")
        return pd.Series(dtype=float)


def run(years: int = 3, force: bool = False, sleep: float = SLEEP) -> dict:
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=365 * years + 30)
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    sess = SessionLocal()
    report = {
        "window": {"start": start_dt.strftime("%Y-%m-%d"), "end": end_dt.strftime("%Y-%m-%d")},
        "sectors": {},
        "total_updated": 0,
    }

    try:
        for code, symbols in PROXY_BASKETS.items():
            print(f"\n[{code}] {len(symbols)} constituents")

            frames: dict[str, pd.Series] = {}
            for sym in symbols:
                s = _fetch_close(sym, start_ts, end_ts)
                if not s.empty:
                    frames[sym] = s
                    print(f"  OK {sym}: {len(s)} bars")
                else:
                    print(f"  SKIP {sym}")
                time.sleep(sleep)

            if not frames:
                report["sectors"][code] = 0
                continue

            # Equal-weight close_idx
            closes = pd.concat(frames, axis=1).sort_index().ffill()
            close_idx = closes.mean(axis=1).dropna()
            print(f"  index: {len(close_idx)} dates ({close_idx.index[0]} -> {close_idx.index[-1]})")

            # Upsert
            rows = sess.query(SectorFlowDaily).filter_by(sector_code=code).all()
            by_date = {r.date: r for r in rows}
            updated = 0
            last_val = None
            for d in sorted(close_idx.index):
                row = by_date.get(d)
                if row is None:
                    continue
                v = float(close_idx[d])
                if not force and row.close_idx is not None and row.close_idx > 0:
                    last_val = row.close_idx
                    continue
                row.close_idx = v
                if last_val is not None and last_val != 0:
                    row.return_1d = (v / last_val) - 1.0
                last_val = v
                updated += 1

            sess.commit()
            report["sectors"][code] = updated
            report["total_updated"] += updated
            print(f"  DONE: {updated} rows")
    finally:
        sess.close()

    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--sleep", type=float, default=SLEEP)
    args = ap.parse_args()
    rep = run(years=args.years, force=args.force, sleep=args.sleep)
    print("\n=== REPORT ===")
    print(json.dumps(rep, indent=2, default=str))
