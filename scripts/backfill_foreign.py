"""Backfill foreign_net (buy/sell) from VNDirect historical foreign API.

For each sector proxy basket, fetches per-constituent daily foreign buy/sell/net
from api-finfo.vndirect.com.vn, sums to sector level, and updates sector_flow_daily.

Usage:
    python scripts/backfill_foreign.py [--years 3] [--force] [--sleep 0.3]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from database.connection import SessionLocal
from database.models import SectorFlowDaily
from config import PROXY_BASKETS

VNDIRECT_URL = "https://api-finfo.vndirect.com.vn/v4/foreigns"
PAGE_SIZE = 200
SLEEP = 0.3


def _fetch_foreign_history(symbol: str, start: str, end: str, sleep: float) -> pd.DataFrame:
    """Fetch all foreign trading data for one symbol from VNDirect."""
    frames = []
    page = 1
    while True:
        try:
            r = requests.get(VNDIRECT_URL, params={
                "q": f"code:{symbol}~tradingDate:gte:{start}~tradingDate:lte:{end}",
                "size": PAGE_SIZE,
                "sort": "tradingDate:desc",
                "page": page,
            }, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            d = r.json()
            rows = d.get("data", [])
            if not rows:
                break
            frames.extend(rows)
            total_pages = d.get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1
            time.sleep(sleep)
        except Exception as e:
            print(f"    ! {symbol} page {page}: {type(e).__name__}: {e}")
            break
    if not frames:
        return pd.DataFrame()
    df = pd.DataFrame(frames)
    df["date"] = pd.to_datetime(df["tradingDate"]).dt.strftime("%Y-%m-%d")
    return df


def run(years: int = 3, force: bool = False, sleep: float = SLEEP) -> dict:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=365 * years + 30)).strftime("%Y-%m-%d")

    sess = SessionLocal()
    report = {"window": {"start": start, "end": end}, "sectors": {}, "total_updated": 0}

    try:
        for code, symbols in PROXY_BASKETS.items():
            print(f"\n[{code}] {len(symbols)} constituents")

            # Aggregate foreign per date across constituents
            sector_foreign: dict[str, dict] = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "net": 0.0})
            for sym in symbols:
                df = _fetch_foreign_history(sym, start, end, sleep)
                if df.empty:
                    print(f"  SKIP {sym}: no foreign data")
                    continue
                print(f"  OK {sym}: {len(df)} rows")
                for _, row in df.iterrows():
                    d = row["date"]
                    sector_foreign[d]["buy"] += float(row.get("buyVal") or 0.0)
                    sector_foreign[d]["sell"] += float(row.get("sellVal") or 0.0)
                    sector_foreign[d]["net"] += float(row.get("netVal") or 0.0)
                time.sleep(sleep)

            if not sector_foreign:
                report["sectors"][code] = 0
                continue

            # Update DB
            rows = sess.query(SectorFlowDaily).filter_by(sector_code=code).all()
            by_date = {r.date: r for r in rows}
            updated = 0
            for d, vals in sector_foreign.items():
                row = by_date.get(d)
                if row is None:
                    continue
                if not force and row.foreign_net is not None and row.foreign_net != 0:
                    continue
                row.foreign_net = vals["net"]
                row.foreign_buy_val = vals["buy"]
                row.foreign_sell_val = vals["sell"]
                updated += 1

            sess.commit()
            report["sectors"][code] = updated
            report["total_updated"] += updated
            print(f"  DONE: {updated} rows with foreign data")
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
