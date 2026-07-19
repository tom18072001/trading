# PicksUniverseService — spec

Status: ACTIVE (2026-04-17).
Doctrine owner: `services/picks_universe_service.py`.
Consumers: `generate_secv3.py` (email report) and `api/routers/insight.py`
(Daily Insight API).

## 1. Purpose & non-goals

**Purpose.** One validated, in-memory snapshot per trading day containing every
HOSE ticker that clears the capability filter, with composite score,
stop/target/RR, and a validity flag. Both the email report and the Daily
Insight page consume this single snapshot so they stop disagreeing on picks.

**Non-goals.**
- Persisting per-ticker OHLCV (the snapshot is transient in-memory).
- Reading `_legacy_stock_prices`, `_legacy_stock_features`, or `_legacy_stocks`
  (banned per CLAUDE.md §2).
- Predicting per-symbol returns (that remains the ranker's concern at sector
  level).
- Producing signals for non-HOSE boards (HNX, UPCoM) in the current cut.

## 2. Public API

```python
from services.picks_universe_service import (
    get_picks_universe, UniverseSnapshot, TickerRow, FreshnessReport,
)

svc = get_picks_universe()           # module-level singleton
snap = svc.get_snapshot()            # cached once per signal date
snap = svc.get_snapshot(force=True)  # force rebuild
svc.invalidate()                     # drop cache; next call rebuilds
```

Dataclasses (all in the same module): see docstrings for field-level docs.
`snap.is_valid` is `True` only when all freshness checks pass (§9).

## 3. Universe source

`vnstock.Listing()`:
- `symbols_by_exchange()` → filter `exchange` in `{HOSE, HSX}`.
- `symbols_by_industries()` → `industry_code` per symbol, left-joined onto the
  HOSE listing.

`data.data_fetcher.get_all_symbols()` is NOT used here — it omits the
`exchange` column.

## 4. Sector classification

Priority chain, first hit wins:
1. **Override** — `sector_constituents(sector_code, symbol, active=1)`.
2. **ICB** — `config.ICB_TO_SECTOR` maps vnstock's top-level `industry_code`
   (integer values like 11 for Ngân hàng) to our 15 sector codes. Current
   mapping covers BANK, BROK, INSUR, REAL, STEEL, RETAIL, FOOD, FISH, CHEM,
   RUBBER, POWER, LOGIS, TECH.
3. **VN keyword** — regex match on `organ_name` for the ~15 sectors. Captures
   OIL (Dầu khí) and TEXT (Dệt may), which vnstock's top-level industry
   classification doesn't surface cleanly.
4. **Unclassified** → dropped, counted in `freshness.warnings`.

## 5. Capability filter

All three must hold (per `config.MIN_*`):
- `dv_20d ≥ MIN_DV_20D_VND` (5B VND default).
- `len(ohlcv) ≥ MIN_HISTORY_SESSIONS` (60 sessions).
- `foreign_room_pct > MIN_FOREIGN_ROOM_PCT` (strictly > 0; `None` accepted
  in degraded mode).

Foreign-room comes from a batched `price_board(chunk=50)` probe; ticker OHLCV
is fetched in a `ThreadPoolExecutor(max_workers=UNIVERSE_BUILD_WORKERS)`
with a 30s per-future timeout. An early-abort fires after 20/20 consecutive
failures (upstream down) to stop wasting retries.

## 6. Indicators

Reuse of `analysis/feature_engineering.py` — one call per ticker produces
RSI_14, MACD_hist, BB_upper/lower/position, ATR_14_pct, ADX_14, return_5d,
return_20d, volume_ratio_20, volatility_20d, price_to_SMA_{20,50}. Nothing is
reimplemented.

Every indicator is computed in memory from fresh OHLCV; nothing persists.

## 7. Composite score

Lifted from `generate_secv3.score_symbol` into
`services.picks_scoring.score_ticker(row) -> int`. Same rules both surfaces.
Sectors rank candidates desc by `(score, dv_20d)`.

## 8. Stop / target / RR

`services.picks_scoring.compute_stop_target_rr(row, profile)`:
- `PickProfile.SWING` — 2.5× ATR target, 1.8× ATR stop. Used by the email
  report (`generate_secv3.py`).
- `PickProfile.TPLUS`  — 2.0× ATR target, 1.0× ATR stop. Used by Daily
  Insight (`api/routers/insight.py`).

Enforced invariants (single source of truth in `picks_scoring`):
- `stop ≤ close × (1 − 1.5%)`
- `target ≥ close × (1 + 3%)` (BB-anchored if BB upper clears 3%; else ATR)
- `R:R ≥ 1.5` (target stretched adaptively, not dropped).

`is_valid_long_pick(entry, target, stop)` is the final gate — rejects
`target ≤ entry`, `stop ≥ entry`, `upside < 2%`, `rr < 1.5`.

## 9. Freshness contract

`UniverseSnapshot.is_valid = True` iff ALL:
- `as_of == latest_signal_date()`, AND `date.today() − as_of ≤ 2` cal days.
- `ohlcv_fail_pct < UNIVERSE_OHLCV_FAIL_PCT_MAX` (20%).
- `capability_pass_count ≥ 50`.
- For every sector with `SectorSignal.action ∈ {BUY, ACCUMULATE}` on
  `as_of`: `len([r for r in by_sector[code] if r.is_valid_buy]) ≥ 1`.

Sectors failing the last check land in `freshness.sectors_missing_picks`
and surface in `freshness.errors`.

## 10. Failure modes & degraded-mode rendering

| Failure | Behavior |
|---|---|
| `Listing()` unavailable | `_build` returns empty snapshot, `is_valid=False`. |
| ≥ 20% OHLCV failures | Build aborts; prior cache retained; next caller sees `is_valid=False`. |
| < 20% OHLCV failures | Build proceeds; failures go into `freshness.warnings`. |
| Ranker hasn't run | `freshness.errors += ["no SectorSignal row"]`, `is_valid=False`. |
| Classification gaps | Counted in `freshness.warnings`; not fatal. |

Email report: subject prefixed `[STALE]`; red banner injected above the
regime narrative listing the error list.

Daily Insight response: `freshness` block included in every `/daily`
response; UI renders stale banner when `freshness.is_valid == false`.

## 11. Observability & logs

Logger: `[picks-universe]`. Always emitted:
- `build start as_of=YYYY-MM-DD`
- `stage A: N HOSE symbols`
- `stage B: N classified, K unclassified`
- `stage C1: N pass foreign_room filter`
- `stage D: N pass capability, K fail (ohlcv_fail_pct=X.XX)`
- `build done: N tickers in M.Ms, is_valid=<bool>`
- On invalidation: `cache invalidated`.

## 12. Shadow run & legacy DROP timeline

Approved window (user decision 2026-04-17): **2 weeks shadow run**, ending
2026-05-01 at the earliest.

During shadow:
- `_legacy_stocks`, `_legacy_stock_prices`, `_legacy_stock_features` remain
  in the DB but are NOT read by either surface.
- `PROXY_BASKETS` + `EXECUTION_BASKETS` remain in `config.py` with a
  deprecation comment; still used as seed for `sector_constituents` aggregates
  (sector_flow_daily), NOT for picks.
- Email + Insight produce picks exclusively via `PicksUniverseService`.

Exit criteria for DROP migration (migration 10):
- At least 10 trading days of parity logs showing the new pipeline's BUY
  list is stable.
- Zero unexpected `is_valid=False` days attributable to our code (vnstock
  outages excluded).
- No engineering escalations citing missing features from the legacy feature
  table.

On meeting the criteria, migration 10 drops the three legacy tables and a
follow-up PR removes `PROXY_BASKETS`/`EXECUTION_BASKETS` if nothing else
consumes them.

## 13. Open items

- **OIL / TEXT ICB mapping** — vnstock's top-level `industry_code` doesn't
  surface these cleanly; we rely on VN-keyword fallback. When vnstock exposes
  sub-industry codes, extend `ICB_TO_SECTOR`.
- **Foreign room accuracy** — vnstock's column naming for foreign_room drifts
  between versions; we probe a priority list (`foreign_room_percent`,
  `foreign_room`, `room_outstanding`, …). Treat `None` as "unknown", not 0.
- **Price-board batching** — currently serial by chunks of 50; future work
  could parallelize across chunks.
