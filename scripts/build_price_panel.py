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


def fetched_symbols(con: sqlite3.Connection) -> set[str]:
    """Symbols the live source has already delivered a history for."""
    return {s for (s,) in con.execute("SELECT symbol FROM fetch_log WHERE status='ok'")}


def seed_from_legacy(con: sqlite3.Connection, src_db: Path | None = None) -> int:
    """Copy _legacy_stock_prices in -- free, and covers 2022-2026-04 -- but ONLY
    for symbols the live source has not delivered yet.

    It used to run on every build with INSERT OR IGNORE, so on every date the
    fresh source had no row for (a session with no match on an illiquid name)
    the legacy row -- adjusted on a DIFFERENT basis -- came back and stayed.
    Review 2026-09-24 §6: 145 such rows in 8 symbols, SRC alternating 19.20 <->
    25.15. Harmless there only because all 8 sit under the liquidity floor.
    """
    src = sqlite3.connect(src_db or (ROOT / "vnstock_market.db"))
    rows = src.execute(
        "SELECT symbol, time, open, high, low, close, volume FROM _legacy_stock_prices"
    ).fetchall()
    src.close()
    done = fetched_symbols(con)
    clean = [(s.strip().upper(), str(t)[:10], o, hi, lo, c, v)
             for (s, t, o, hi, lo, c, v) in rows
             if c and c > 0 and s.strip().upper() not in done]
    con.executemany(
        "INSERT OR IGNORE INTO prices(symbol,time,open,high,low,close,volume) "
        "VALUES (?,?,?,?,?,?,?)", clean)
    con.commit()
    return len(clean)


def store_fetch(con: sqlite3.Connection, sym: str, recs: list[tuple],
                start: str, end: str) -> None:
    """Replace `sym`'s rows in [start, end] with exactly what the source sent.

    Delete-then-insert, not INSERT OR REPLACE: a date the source does NOT return
    inside the span it was asked for is a date with no trading, and a row left
    there from an earlier load (legacy, other adjustment basis) is wrong.
    """
    con.execute("DELETE FROM prices WHERE symbol=? AND time>=? AND time<=?",
                (sym, start, end))
    con.executemany(
        "INSERT OR REPLACE INTO prices(symbol,time,open,high,low,close,volume) "
        "VALUES (?,?,?,?,?,?,?)", recs)


#: Largest one-session move a listed VN stock can make: UPCoM's ±15% band, plus
#: slack for the rounding of a price step. Anything beyond it is not a price —
#: it is two adjustment bases, a split, or a bad print.
MAX_DAILY_MOVE = 0.16


def band_violations(con: sqlite3.Connection, limit: float = MAX_DAILY_MOVE) -> list[tuple]:
    """(symbol, time, return) for every close-to-close move beyond `limit`.

    Not every hit is an error -- a corporate action with no price adjustment
    also lands here -- but a panel with many is a panel mixing bases.
    """
    out = []
    prev: dict[str, float] = {}
    for sym, t, c in con.execute("SELECT symbol, time, close FROM prices "
                                 "WHERE close > 0 AND symbol NOT LIKE '^%' "
                                 "ORDER BY symbol, time"):
        pc = prev.get(sym)
        if pc and abs(c / pc - 1.0) > limit:
            out.append((sym, t, c / pc - 1.0))
        prev[sym] = c
    return out


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
    ap.add_argument("--refetch", default="",
                    help="comma-separated symbols to re-fetch over the whole span, "
                         "replacing every stored row (repairs mixed-basis history)")
    args = ap.parse_args()
    refetch = {x.strip().upper() for x in args.refetch.split(",") if x.strip()}

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
        needs_head = ((not lo) or lo > (date.fromisoformat(args.start) + timedelta(days=200)).isoformat()
                      or s in refetch)
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
                store_fetch(con, s, recs, start, args.end)
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
    bad = band_violations(con)
    if bad:
        syms = sorted({b[0] for b in bad})
        print(f"WARNING: {len(bad)} close-to-close moves beyond ±{MAX_DAILY_MOVE:.0%} "
              f"in {len(syms)} symbols — mixed adjustment bases or corporate actions. "
              f"Repair with --refetch {','.join(syms[:12])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
