"""Repair the sector history review 2026-09-24 found broken -- one pass, backup first.

What it fixes (review 2026-09-24 §4.1, §8 P0-2/3/4; the code was fixed
2026-09-25, this repairs what the old code already wrote):

1. `macro_anchors.vnindex` outside 200-5,000 -> NULL. 613 rows are ~1.82; the
   2026-09-22 regime label was fitted on them.
2. `sector_flow_daily.atr_pct` -> the basket's real ATR. The old aggregation
   divided by n twice, so every stored value is ~1/5 of it.
3. `sector_flow_daily.return_1d` -> the basket's close-to-close return (NULL on
   every sector 2026-04-10 .. 06-22), and `close_idx` -> a level CHAINED from
   it. The stored level was a raw price sum that jumped +62% / -39% (STEEL,
   2026-09-22/23) whenever a constituent failed to fetch.
4. The §16.2 leading features, recomputed over the repaired columns
   (`services.fast_ingest.rebuild_leading_features`, the same code the 16:00
   job now runs).

Source: `data/price_panel.db` (read only) for the `config.PROXY_BASKETS`
constituents, with the formulas of `analysis/flow_aggregation.py`: ATR14 / close
per constituent and the constituent's own close-to-close return, each averaged
over the basket with equal weights (at least 2 names). A move beyond ±16% in a
day is a mixed adjustment basis, not a price (`build_price_panel.MAX_DAILY_MOVE`):
that return and every ATR window containing it are left out.

Nothing else is touched: flows, breadth, foreign, the intraday table, signals.

Safe by default:
- DRY RUN unless --apply. Reads both databases, prints what would change,
  writes nothing.
- --apply refuses while the scheduled jobs write (08:45-17:45 on a trading
  day, market time) unless --force-hours, and refuses when the price panel
  ends before the last `sector_flow_daily` session -- run
  `python scripts/build_price_panel.py` first.
- --apply takes a backup with SQLite's backup API (consistent under WAL) to
  `<db>.bak-<YYYYmmdd-HHMMSS>-pre-repair` beside the database, then writes the
  raw columns in ONE transaction. Rerunning is safe: the result is the same.

Windows, from the repo root:
    .venv\\Scripts\\python.exe scripts\\build_price_panel.py
    .venv\\Scripts\\python.exe scripts\\repair_sector_data.py
    .venv\\Scripts\\python.exe scripts\\repair_sector_data.py --apply
Undo: stop the backend, copy the .bak file back over vnstock_market.db.
"""
from __future__ import annotations

# Output is ASCII on purpose: Tom runs this in a Windows console, where a
# redirected stdout uses the ANSI code page.

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import DATABASE_PATH, PROXY_BASKETS  # noqa: E402
from scripts.build_price_panel import MAX_DAILY_MOVE, PANEL_DB  # noqa: E402
from services.macro_service import VNINDEX_MAX_PLAUSIBLE, VNINDEX_MIN_PLAUSIBLE  # noqa: E402

ATR_PERIOD = 14          # analysis.flow_aggregation._atr_pct
MIN_NAMES = 2            # a basket of one is not a basket (sector_ingest backfill)
BASE_LEVEL = 100.0       # analysis.flow_aggregation.chain_close_idx
QUIET_FROM, QUIET_TO = time(8, 45), time(17, 45)


# ---------------------------------------------------------------- the panel

def constituent_series(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    """(return, atr_pct) wide frames [date x symbol], each symbol on its OWN
    calendar like `_last_bar_return` / `_atr_pct`, plus the band violations.

    `prices`: symbol, date, high, low, close.
    """
    rets, atrs, bad = {}, {}, []
    for sym, g in prices.sort_values(["symbol", "date"]).groupby("symbol"):
        g = g.set_index("date")
        c = g["close"].astype(float).where(g["close"] > 0)
        pc = c.shift(1)
        r = c / pc - 1.0
        tr = pd.concat([g["high"] - g["low"], (g["high"] - pc).abs(), (g["low"] - pc).abs()],
                       axis=1).max(axis=1)
        jump = r.abs() > MAX_DAILY_MOVE
        bad += [(sym, d, float(v)) for d, v in r[jump].items()]
        r = r.mask(jump)
        tr = tr.mask(jump)                        # a basis jump is not a true range
        rets[sym] = r
        atrs[sym] = tr.rolling(ATR_PERIOD).mean() / c   # NaN if the window holds a jump
    return pd.DataFrame(rets).sort_index(), pd.DataFrame(atrs).sort_index(), bad


def _asof(s: pd.Series, d: str) -> float:
    """Last value at or before date string `d` of a sorted, NaN-free series.
    (`Series.asof` turns a string into a Timestamp and fails on a string index.)"""
    i = s.index.searchsorted(d, side="right") - 1
    return float(s.iloc[i]) if i >= 0 else float("nan")


def basket(wide: pd.DataFrame, syms: list[str]) -> pd.Series:
    """Equal-weighted mean over the names present that day; NaN under MIN_NAMES."""
    cols = [s for s in syms if s in wide.columns]
    if not cols:
        return pd.Series(np.nan, index=wide.index)
    x = wide[cols]
    return x.mean(axis=1).where(x.notna().sum(axis=1) >= MIN_NAMES)


# ------------------------------------------------------------------- the plan

@dataclass
class Plan:
    macro_null: list = field(default_factory=list)       # [(rowid, value)]
    updates: list = field(default_factory=list)          # [(atr, ret, idx, code, date)]
    before: pd.DataFrame | None = None
    after: pd.DataFrame | None = None
    panel_end: str | None = None
    db_end: str | None = None
    band: list = field(default_factory=list)
    kept_ret: int = 0          # rows whose return the panel could not compute
    off_calendar: int = 0      # rows dated a day the panel has no session on


def build_plan(db: sqlite3.Connection, panel: sqlite3.Connection,
               baskets: dict[str, list[str]] = PROXY_BASKETS) -> Plan:
    plan = Plan()
    lo, hi = VNINDEX_MIN_PLAUSIBLE, VNINDEX_MAX_PLAUSIBLE
    plan.macro_null = db.execute(
        "SELECT rowid, vnindex FROM macro_anchors WHERE vnindex IS NOT NULL "
        "AND (vnindex < ? OR vnindex > ?)", (lo, hi)).fetchall()

    sfd = pd.read_sql("SELECT sector_code, date, atr_pct, return_1d, close_idx "
                      "FROM sector_flow_daily ORDER BY sector_code, date", db)
    plan.before = sfd.copy()
    plan.db_end = sfd["date"].max() if len(sfd) else None

    syms = sorted({s for v in baskets.values() for s in v})
    marks = ",".join("?" * len(syms))          # placeholders only; values are bound
    sql = f"SELECT symbol, substr(time, 1, 10) AS date, high, low, close FROM prices WHERE symbol IN ({marks})"  # noqa: S608, E501
    prices = pd.read_sql(sql, panel, params=syms)
    plan.panel_end = prices["date"].max() if len(prices) else None
    ret_w, atr_w, plan.band = constituent_series(prices)

    out = []
    for code, g in sfd.groupby("sector_code", sort=False):
        members = baskets.get(code, [])
        ret = basket(ret_w, members)
        atr = basket(atr_w, members)
        atr_ok = atr.dropna()
        first = g["date"].min()
        # Chain on the PANEL's calendar from the sector's first stored session,
        # so a session missing from the table still moves the level.
        seg = ret[ret.index > first].fillna(0.0)
        level = BASE_LEVEL * (1.0 + seg).cumprod()
        level.loc[first] = BASE_LEVEL
        level = level.sort_index()
        for d, old_ret in zip(g["date"], g["return_1d"], strict=True):
            if d in ret.index:
                r = ret[d]
                if np.isnan(r):                   # < MIN_NAMES names that day
                    plan.kept_ret += 1
                    r = old_ret
            else:                                 # no session in the panel
                plan.off_calendar += 1
                r = None
            # Last valid basket ATR at or before d (ATR moves slowly; a window
            # holding a basis jump is skipped, not zeroed).
            a = _asof(atr_ok, d)
            lv = _asof(level, d)
            out.append((None if np.isnan(a) else float(a),
                        None if r is None or np.isnan(r) else float(r),
                        float(lv), code, d))
    plan.updates = out
    plan.after = pd.DataFrame(out, columns=["atr_pct", "return_1d", "close_idx",
                                            "sector_code", "date"])
    return plan


# ----------------------------------------------------------------- reporting

def _max_jump(df: pd.DataFrame) -> tuple[float, int]:
    j = df.sort_values(["sector_code", "date"]).groupby("sector_code")["close_idx"].pct_change()
    return float(j.abs().max() or 0.0), int((j.abs() > MAX_DAILY_MOVE).sum())


def report(plan: Plan) -> str:
    b, a = plan.before, plan.after
    lines = [f"price panel ends {plan.panel_end}; sector_flow_daily ends {plan.db_end}"]
    vals = [v for _, v in plan.macro_null]
    lines.append(f"macro_anchors: {len(vals)} vnindex value(s) outside "
                 f"{VNINDEX_MIN_PLAUSIBLE:.0f}-{VNINDEX_MAX_PLAUSIBLE:.0f} -> NULL"
                 + (f" (min {min(vals):.2f}, max {max(vals):.2f})" if vals else ""))
    if b is None or not len(b):
        lines.append("sector_flow_daily: empty -- nothing to repair")
        return "\n".join(lines)
    lines.append(f"sector_flow_daily: {len(b)} rows")
    lines.append(f"  atr_pct median   {b['atr_pct'].median():.4f} -> {a['atr_pct'].median():.4f}"
                 f"   (NULL {b['atr_pct'].isna().sum()} -> {a['atr_pct'].isna().sum()})")
    lines.append(f"  return_1d NULL   {b['return_1d'].isna().sum()} -> {a['return_1d'].isna().sum()}")
    if plan.kept_ret:
        lines.append(f"    {plan.kept_ret} row(s) keep their stored return: fewer than "
                     f"{MIN_NAMES} basket names in the panel that day")
    if plan.off_calendar:
        lines.append(f"    {plan.off_calendar} row(s) are dated a day the panel has no session "
                     "for (weekend, holiday, or after the panel ends): return NULL, level "
                     "and ATR carried from the session before")
    jb, nb = _max_jump(b)
    ja, na = _max_jump(a)
    lines.append(f"  close_idx: largest day-over-day move {jb:.1%} -> {ja:.1%}; "
                 f"moves beyond +/-{MAX_DAILY_MOVE:.0%}: {nb} -> {na}")
    m = b.merge(a, on=["sector_code", "date"], suffixes=("_old", "_new"))
    changed = np.zeros(len(m), dtype=bool)
    for c in ("atr_pct", "return_1d", "close_idx"):
        o, n = m[f"{c}_old"], m[f"{c}_new"]
        changed |= (o.isna() != n.isna()) | ((o - n).abs() > 1e-9 * (1 + n.abs())).fillna(False)
    lines.append(f"  rows that change: {int(changed.sum())} of {len(m)}")

    def pct(v):
        return "NULL" if pd.isna(v) else f"{v:+.2%}"
    for code, d in (("STEEL", "2026-09-22"), ("STEEL", "2026-09-23")):
        row = m[(m.sector_code == code) & (m.date == d)]
        if len(row):
            r = row.iloc[0]
            lines.append(f"  {code} {d}: close_idx {r.close_idx_old:.2f} -> {r.close_idx_new:.2f}, "
                         f"return_1d {pct(r.return_1d_old)} -> {pct(r.return_1d_new)}")
    if plan.band:
        names = sorted({s for s, _, _ in plan.band})
        lines.append(f"price panel: {len(plan.band)} basket move(s) beyond +/-{MAX_DAILY_MOVE:.0%} "
                     f"left out ({', '.join(names)}). If they are basis jumps, refresh them: "
                     f"python scripts/build_price_panel.py --refetch {','.join(names)}")
    return "\n".join(lines)


# -------------------------------------------------------------------- guards

def refusal(plan: Plan, now: datetime, is_trading_day: bool, force_hours: bool) -> list[str]:
    """Every reason --apply must not run now (empty = go)."""
    why = []
    if not force_hours and is_trading_day and QUIET_FROM <= now.time() <= QUIET_TO:
        why.append(f"{now:%H:%M} on a trading day: the scheduled jobs write to this database "
                   f"between {QUIET_FROM:%H:%M} and {QUIET_TO:%H:%M}. Run it after "
                   f"{QUIET_TO:%H:%M}, or pass --force-hours.")
    if plan.panel_end is None or (plan.db_end and plan.panel_end < plan.db_end):
        why.append(f"the price panel ends {plan.panel_end}, the sector table {plan.db_end}: "
                   "rows after the panel cannot be recomputed and would keep a flat level "
                   "and a stale ATR. Run `python scripts/build_price_panel.py` first.")
    return why


def backup(db_path: Path, stamp: str) -> Path:
    dest = db_path.with_name(f"{db_path.name}.bak-{stamp}-pre-repair")
    src = sqlite3.connect(db_path, timeout=60)
    try:
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()
    return dest


def apply(db: sqlite3.Connection, plan: Plan) -> None:
    with db:                                    # one transaction
        db.executemany("UPDATE macro_anchors SET vnindex = NULL WHERE rowid = ?",
                       [(rid,) for rid, _ in plan.macro_null])
        db.executemany("UPDATE sector_flow_daily SET atr_pct = ?, return_1d = ?, close_idx = ? "
                       "WHERE sector_code = ? AND date = ?", plan.updates)


def rebuild_features(db_path: Path) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from services.fast_ingest import rebuild_leading_features
    eng = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 60})
    s = sessionmaker(bind=eng)()
    try:
        return rebuild_leading_features(s)
    finally:
        s.close()
        eng.dispose()


def main(argv: list[str] | None = None, *, now: datetime | None = None,
         trading_day: bool | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=DATABASE_PATH)
    ap.add_argument("--panel", default=str(PANEL_DB))
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--force-hours", action="store_true",
                    help="allow --apply while the scheduled jobs may be writing")
    args = ap.parse_args(argv)

    from utils import clock
    now = now or clock.now().replace(tzinfo=None)
    trading_day = clock.is_trading_day(now.date()) if trading_day is None else trading_day

    db_path, panel_path = Path(args.db), Path(args.panel)
    for p in (db_path, panel_path):
        if not p.exists():
            print(f"not found: {p}")
            return 2
    db = sqlite3.connect(db_path, timeout=60)
    panel = sqlite3.connect(f"file:{panel_path}?mode=ro", uri=True)
    try:
        plan = build_plan(db, panel)
        print(report(plan))
        why = refusal(plan, now, trading_day, args.force_hours)
        if not args.apply:
            print("\nDRY RUN -- nothing written. Re-run with --apply to write "
                  "(a backup is taken first).")
            for w in why:
                print(f"--apply would refuse right now: {w}")
            return 0
        if why:
            for w in why:
                print(f"\nNOT APPLIED: {w}")
            return 3
        dest = backup(db_path, now.strftime("%Y%m%d-%H%M%S"))
        print(f"\nbackup: {dest}")
        apply(db, plan)
        print(f"written: {len(plan.macro_null)} macro value(s) -> NULL, "
              f"{len(plan.updates)} sector row(s) repaired")
    finally:
        db.close()
        panel.close()
    n = rebuild_features(db_path)
    print(f"leading features rebuilt on {n} rows")
    print("next: the 02:00 rotation_train job retrains the ranker on the repaired "
          "history (or run `python main.py --train` now).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
