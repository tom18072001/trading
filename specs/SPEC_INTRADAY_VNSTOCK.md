# SYSTEM PROMPT: Intraday vnstock Upgrade (1m/5m/15m/1H)

> **Status: NOT IMPLEMENTED** (marked 2026-08-24). Nothing in this file has
> shipped. It is kept because it specifies a problem that is still open, not
> because it describes the system.
>
> The gap it addresses is `CLAUDE.md` §20.3 **P2-3**: the job called
> `sector_intraday_flow` fetches `interval="1D"` and re-downloads 120 days
> every 15 minutes — roughly 3,750 calls/day against an 18/min gate. So the
> "intraday" pipeline is an EOD pipeline wearing an intraday name, and §4/§8 of
> `CLAUDE.md` describe a cadence the code does not run. P2-3's decision is
> binary: build this, or rename the job and fix the doctrine. Neither has been
> done.
>
> Related and also unbuilt: §18.5/23's `morning_share` (institutions trade the
> 09:15–10:30 window; retail dominates the afternoon) needs real 15m bars,
> which is this spec.

## OBJECTIVE
Upgrade the Trading system from daily-only data to multi-timeframe intraday data (1m, 5m, 15m, 1H, 1D) using vnstock API. Minimize token usage — work incrementally, one module at a time.

## CONSTRAINTS
- Budget: Keep each session under 50K tokens
- Approach: Edit existing files, never rewrite from scratch
- Testing: Verify each change before moving to next
- Database: Migrate schema additively (no DROP TABLE)

## PHASE 1: Data Layer (Session 1-2)

### 1.1 Config Changes (`config.py`)
```
SUPPORTED_INTERVALS = ["1m", "5m", "15m", "1H", "1D"]
DEFAULT_INTERVAL = "1D"

# Intraday data retention (days of history to keep)
INTRADAY_RETENTION = {
    "1m": 7,      # vnstock limit: ~7 days for 1m
    "5m": 30,
    "15m": 60,
    "1H": 180,
    "1D": 1095,   # 3 years (current)
}

# Scheduler intervals for auto-fetch
FETCH_SCHEDULE = {
    "1m": 60,       # every 60 seconds during market hours
    "5m": 300,
    "15m": 900,
    "1H": 3600,
    "1D": 86400,
}

# Vietnam market hours (UTC+7)
MARKET_OPEN = "09:00"
MARKET_CLOSE = "15:00"
MARKET_BREAK_START = "11:30"
MARKET_BREAK_END = "13:00"
```

### 1.2 Data Fetcher Changes (`data/data_fetcher.py`)
- Modify `get_stock_history()` to accept `interval` parameter
- vnstock call: `stock.quote.history(start=start_date, end=end_date, interval=interval)`
- Valid intervals for vnstock 3.x: `'1m'`, `'5m'`, `'15m'`, `'30m'`, `'1H'`, `'1D'`, `'1W'`, `'1M'`
- Add `get_intraday_history(symbol, interval='5m', days_back=7)` helper
- Rate limit: increase to 1.0s for intraday (more data per call)
- Add market hours check: skip fetch outside 09:00-15:00 UTC+7

### 1.3 Database Schema (`database/models.py`)
Add new table — do NOT modify `stock_prices` (keep daily intact):
```python
class StockPricesIntraday(Base):
    __tablename__ = "stock_prices_intraday"
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), ForeignKey("stocks.symbol"), nullable=False)
    time = Column(DateTime, nullable=False)
    interval = Column(String(10), nullable=False)  # "1m", "5m", "15m", "1H"
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger)
    __table_args__ = (
        UniqueConstraint("symbol", "time", "interval"),
        Index("idx_intraday_symbol_interval_time", "symbol", "interval", "time"),
    )
```

### 1.4 Migration
- Add migration version for `stock_prices_intraday` table
- Add composite index on (symbol, interval, time DESC) for fast latest-bar queries

## PHASE 2: Service Layer (Session 3-4)

### 2.1 Data Service (`services/data_service.py`)
- Add `fetch_and_store_intraday(symbol, interval, days_back)` method
- Incremental upsert: only fetch bars newer than latest in DB
- Add `cleanup_old_intraday()` — delete bars older than retention config
- Add `fetch_intraday_batch(symbols, interval)` for bulk fetch

### 2.2 Feature Service (`services/feature_service.py`)
- Adapt indicators for intraday:
  - 1m/5m: Use shorter periods — SMA(10,20), RSI(9), MACD(6,13,5)
  - 15m/1H: Standard periods work — SMA(10,20,50), RSI(14)
  - 1D: Keep current config unchanged
- Add `INDICATOR_PRESETS` per interval in config
- Store features with interval column in a new `stock_features_intraday` table

### 2.3 Scheduler Service (NEW: `services/scheduler_service.py`)
```python
class MarketDataScheduler:
    """Fetch intraday data on schedule during market hours."""

    async def start(self, intervals=["1m", "5m"]):
        # Only run during market hours (09:00-15:00 UTC+7, skip 11:30-13:00)
        # Use asyncio.create_task for non-blocking fetch
        # Symbols: VN30 only for 1m (30 stocks), full SECTOR_MAP for 5m+

    async def fetch_cycle(self, interval):
        # Fetch latest bars for configured symbols
        # Compute features incrementally (append, don't recompute all)
        # Emit WebSocket event on new data
```

## PHASE 3: API Layer (Session 5)

### 3.1 New/Modified Endpoints
```
GET  /api/stocks/{symbol}/prices?interval=5m&days_back=7
GET  /api/stocks/{symbol}/features?interval=15m
POST /api/stocks/fetch-intraday  {symbol, interval, days_back}
GET  /api/market/status           → {is_open, next_open, current_session}
WS   /ws/prices/{symbol}          → Real-time price stream
```

### 3.2 WebSocket for Live Data
```python
@app.websocket("/ws/prices/{symbol}")
async def ws_prices(websocket: WebSocket, symbol: str):
    await websocket.accept()
    # Subscribe to scheduler events for this symbol
    # Push new bars as they arrive
    # Include: {time, open, high, low, close, volume, interval}
```

## PHASE 4: Frontend (Session 6-7)

### 4.1 Chart Timeframe Selector
- Add timeframe buttons: 1m | 5m | 15m | 1H | 1D
- On timeframe change: fetch data with new interval, re-render chart
- lightweight-charts handles all intervals natively

### 4.2 WebSocket Client
```typescript
// api/ws.ts
export function connectPriceStream(symbol: string, onBar: (bar) => void) {
    const ws = new WebSocket(`ws://localhost:8000/ws/prices/${symbol}`);
    ws.onmessage = (e) => onBar(JSON.parse(e.data));
    return ws;
}
```

### 4.3 Multi-Timeframe View
- Add split-view option: 2 charts side by side with different intervals
- Sync crosshair between charts (lightweight-charts `subscribeCrosshairMove`)

## PHASE 5: ML Adaptation (Session 8)

### 5.1 Intraday ML Considerations
- **DO NOT** train on 1m data — too noisy, overfit guaranteed
- Recommended: Train on 15m or 1H for intraday signals
- Reduce prediction horizons for intraday: [3, 6, 12] bars instead of days
- Feature selection: Drop SMA_50 for intraday, add VWAP deviation
- Walk-forward window: 20 bars for 15m (≈ 1 trading day)

### 5.2 Adjusted Confidence Score for Intraday
```
Intraday Composite = Technical(45%) + Volume(30%) + ML(15%) + Momentum(10%)
```
ML weight reduced — intraday prediction less reliable than daily.

## DATA VOLUME ESTIMATES

| Interval | Bars/Day/Stock | VN30 Daily | Full 170 Stocks Daily | Monthly (VN30) |
|----------|---------------|------------|----------------------|----------------|
| 1m       | 270           | 8,100      | 45,900               | 162,000        |
| 5m       | 54            | 1,620      | 9,180                | 32,400         |
| 15m      | 18            | 540        | 3,060                | 10,800         |
| 1H       | 5             | 150        | 850                  | 3,000          |
| 1D       | 1             | 30         | 170                  | 600            |

**Recommendation:** 1m → VN30 only. 5m+ → all 170 stocks. SQLite OK for first month, migrate to PostgreSQL + TimescaleDB when DB exceeds 500MB.

## TOKEN OPTIMIZATION RULES
1. Each session: focus on ONE phase only
2. Read only the files being modified (targeted reads)
3. Don't re-read config.py or models.py — they're cached
4. Test after each file change before moving to next
5. Use /compact after completing each phase
6. No docstrings on new code unless logic is non-obvious
