"""Build (and cache) a per-ticker daily OHLCV panel for factor research.

Why this exists: the system has no per-ticker price history it can research on.
`_legacy_stock_prices` stops at 2026-04-08, and PicksUniverseService keeps 30
sessions of one snapshot. Every question of the form "would this ranking rule
have worked" needs a panel, so this builds one once and caches it to SQLite.

Universe = legacy stocks UNION the symbols this system actually picked UNION
the current sector constituents. Incremental: re-running only fetches dates
after what is already stored, so the 18 req/min gate is paid once.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PANEL_DB = ROOT / "data" / "price_panel.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT NOT NULL,
    time   TEXT NOT NULL,
    open   REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (symbol, time)
);
CREATE INDEX IF NOT EXISTS ix_prices_time ON prices(time);
CREATE TABLE IF NOT EXISTS fetch_log (
    symbol TEXT PRIMARY KEY, last_fetch TEXT, rows INTEGER, status TEXT
);
"""


def universe() -> list[str]:
    syms: set[str] = set()
    src = sqlite3.connect(ROOT / "vnstock_market.db")
    for (s,) in src.execute("SELECT DISTINCT symbol FROM _legacy_stock_prices"):
        syms.add(s.strip().upper())
    for (s,) in src.execute("SELECT DISTINCT symbol FROM sector_constituents"):
        syms.add(s.strip().upper())
    src.close()
    picks = ROOT / "data" / "past_picks.csv"
    if picks.exists():
        import csv
        for r in csv.DictReader(picks.open(encoding="utf-8")):
            syms.add(r["symbol"].strip().upper())
    return sorted(s for s in syms if len(s) == 3 and s.isalnum())


def seed_from_legacy(con: sqlite3.Connection) -> int:
    """Copy _legacy_stock_prices in wholesale -- it is free and covers 2022-2026-04."""
    src = sqlite3.connect(ROOT / "vnstock_market.db")
    rows = src.execute(
        "SELECT symbol, time, open, high, low, close, volume FROM _legacy_stock_prices"
    ).fetchall()
    src.close()
    clean = [(s.strip().upper(), str(t)[:10], o, hi, lo, c, v)
             for (s, t, o, hi, lo, c, v) in rows if c and c > 0]
    con.executemany(
        "INSERT OR IGNORE INTO prices(symbol,time,open,high,low,close,volume) "
        "VALUES (?,?,?,?,?,?,?)", clean)
    con.commit()
    return len(clean)


def fetch_symbol(sym: str, start: str, end: str):
    from data.data_fetcher import get_stock_history
    from utils.vnstock_gate import throttle
    throttle()
    return get_stock_history(sym, start_date=start, end_date=end, interval="1D")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--limit", type=int, default=0, help="max symbols to fetch this run")
    ap.add_argument("--seed-only", action="store_true")
    args = ap.parse_args()

    PANEL_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(PANEL_DB)
    con.executescript(SCHEMA)

    n = seed_from_legacy(con)
    print(f"seeded {n} legacy rows")
    if args.seed_only:
        print(con.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(time), MAX(time) "
                          "FROM prices").fetchone())
        return 0

    syms = universe()
    print(f"universe: {len(syms)} symbols")

    todo = []
    for s in syms:
        lo, hi = con.execute(
            "SELECT MIN(time), MAX(time) FROM prices WHERE symbol=?", (s,)).fetchone()
        # Two different gaps, and only chasing the tail leaves the panel
        # 21 names wide before 2025 -- too narrow a cross-section to rank in.
        # A symbol whose history STARTS late needs the head fetched as well,
        # so fetch the whole span whenever either end is missing.
        needs_head = (not lo) or lo > (date.fromisoformat(args.start) + timedelta(days=200)).isoformat()
        needs_tail = (not hi) or hi < args.end
        if not (needs_head or needs_tail):
            continue
        start = args.start if needs_head else (
            date.fromisoformat(hi) - timedelta(days=5)).isoformat()
        todo.append((s, start))
    if args.limit:
        todo = todo[: args.limit]
    print(f"to fetch: {len(todo)}")

    ok = fail = 0
    t0 = time.time()
    for i, (s, start) in enumerate(todo, 1):
        try:
            df = fetch_symbol(s, start, args.end)
            if df is None or df.empty:
                con.execute("INSERT OR REPLACE INTO fetch_log VALUES (?,?,?,?)",
                            (s, date.today().isoformat(), 0, "empty"))
                fail += 1
            else:
                df.columns = [c.lower().strip() for c in df.columns]
                recs = [(s, str(rec["time"])[:10], float(rec.get("open") or 0),
                         float(rec.get("high") or 0), float(rec.get("low") or 0),
                         float(rec["close"]), float(rec.get("volume") or 0))
                        for _, rec in df.iterrows() if rec.get("close")]
                con.executemany(
                    "INSERT OR REPLACE INTO prices(symbol,time,open,high,low,close,volume) "
                    "VALUES (?,?,?,?,?,?,?)", recs)
                con.execute("INSERT OR REPLACE INTO fetch_log VALUES (?,?,?,?)",
                            (s, date.today().isoformat(), len(recs), "ok"))
                ok += 1
            con.commit()
        except Exception as e:  # noqa: BLE001 - one bad symbol must not kill the panel
            con.execute("INSERT OR REPLACE INTO fetch_log VALUES (?,?,?,?)",
                        (s, date.today().isoformat(), 0, f"err:{type(e).__name__}"))
            con.commit()
            fail += 1
        if i % 10 == 0:
            el = time.time() - t0
            print(f"  {i}/{len(todo)}  ok={ok} fail={fail}  {el/60:.1f}m", flush=True)

    print(con.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(time), MAX(time) "
                      "FROM prices").fetchone())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
