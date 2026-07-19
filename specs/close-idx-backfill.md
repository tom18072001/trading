# Phase 15 Blocker — Real `close_idx` backfill

> Status: **in scope for Phase 15** (confirmed by Tom 2026-04-09).
> Must complete before Stealth Watch cond 5 can be removed from synthetic
> mode, and before any future backtest rebuild is meaningful.

## 1. Problem
`sector_flow_daily.close_idx` is currently either NULL or a synthetic proxy
derived from `sign(flow) × atr`. This makes:
- Stealth cond 5 ("price in bottom 40% of 60d range") tautological — the
  `STEALTH_SYNTHETIC_CLOSE=1` escape hatch is active everywhere.
- Backtest PnL meaningless — the engine simulates trades on a sign-of-flow
  curve, not on real prices. This is why the deleted Sector Backtest page
  returned −88% returns.

## 2. Target
For every `(sector_code, date)` row in `sector_flow_daily` that has a real
calendar session, `close_idx` should be the **weighted aggregate close price
of the sector's proxy basket**, weighted by market cap or by free-float.
Definition:
```
close_idx(sector, t) = Σ_i w_i · close_i(t) / Σ_i w_i
```
where `i` iterates over the sector's top-5 proxy basket (CLAUDE.md §3) and
`w_i` is the constituent's market cap as of `t` (or the latest known cap if
`t` is before our first market-cap snapshot — we do not need intra-history
weight rebalancing for the first cut).

## 3. Data source
Reuse `vnstock.stock.quote.history(symbol, start, end, interval='1D')` —
the same call already in `SectorIngestService._fetch_constituent_daily`.
Market cap: use `vnstock.stock.company.overview(symbol)` once per
constituent (the current market cap as a static weight; acceptable for the
first cut). If `overview` fails, fall back to equal weighting and log it
in the run report.

## 4. Script — `scripts/backfill_close_idx.py`
Skeleton:
```python
import pandas as pd
from database.connection import SessionLocal
from database.models import SectorFlowDaily
from config import PROXY_BASKETS
from data.data_fetcher import fetch_history, fetch_market_cap

def run(years: int = 3, force: bool = False) -> dict:
    sess = SessionLocal()
    report = {"sectors": {}, "total_updated": 0, "fallback_equal_weight": []}
    for code, symbols in PROXY_BASKETS.items():
        weights = {}
        for sym in symbols:
            try:
                weights[sym] = fetch_market_cap(sym) or 0.0
            except Exception:
                weights[sym] = 0.0
        if sum(weights.values()) == 0:
            report["fallback_equal_weight"].append(code)
            weights = {sym: 1.0 for sym in symbols}

        # Fetch OHLC per constituent in one batch
        frames = {}
        for sym in symbols:
            try:
                df = fetch_history(sym, years=years)  # DataFrame indexed by date
                frames[sym] = df["close"]
            except Exception:
                continue
        if not frames:
            continue

        closes = pd.concat(frames, axis=1).ffill()
        w = pd.Series({k: weights.get(k, 0.0) for k in closes.columns}).replace(0, 1e-9)
        close_idx = (closes.mul(w, axis=1).sum(axis=1) / w.sum())

        # Upsert into sector_flow_daily
        updated = 0
        rows = sess.query(SectorFlowDaily).filter_by(sector_code=code).all()
        by_date = {r.date: r for r in rows}
        for d, v in close_idx.dropna().items():
            key = str(d)[:10]
            row = by_date.get(key)
            if row is None:
                continue
            if force or row.close_idx in (None, 0.0):
                row.close_idx = float(v)
                updated += 1
        sess.commit()
        report["sectors"][code] = updated
        report["total_updated"] += updated
    sess.close()
    return report
```

(The real implementation will live in `scripts/backfill_close_idx.py` and
expose a `__main__` block that prints the report.)

## 5. Validation
After running:
1. `SELECT sector_code, COUNT(*), SUM(CASE WHEN close_idx IS NULL OR close_idx = 0 THEN 1 ELSE 0 END) FROM sector_flow_daily GROUP BY sector_code` → target: fill rate ≥ 90% per sector.
2. For a sample sector (e.g. BANK), plot `close_idx` against VNINDEX. They
   should move with strong positive correlation (≥0.7 on daily returns for
   any large-cap sector). If not, weights are wrong — fall back to equal
   and re-run.
3. After backfill, remove the `STEALTH_SYNTHETIC_CLOSE` escape hatch in
   `analysis/stealth.py`. The cond 5 gate must now use real prices.

## 6. Known limitations (documented in the log when the phase closes)
- Market cap is taken as a static snapshot — historical rebalancing is
  punted to Phase 16.
- Foreign holdings / free-float weighting is not applied — raw market cap
  only. Acceptable for a sector proxy but not for precise index replication.
- Delisted / new-listing constituents within the 3y window are not handled;
  the basket is assumed stable. If a sector's basket has changed in that
  window, a manual override per sector will be needed.

## 7. Rollback
If the backfill produces obviously bad prices (e.g. flat lines, zero
correlation with VNINDEX), revert by:
1. `UPDATE sector_flow_daily SET close_idx = NULL WHERE close_idx IS NOT NULL;`
2. Re-enable `STEALTH_SYNTHETIC_CLOSE=1` in the relevant env.
3. File a Phase-15 blocker note in `MODIFICATION_LOG.md`.
