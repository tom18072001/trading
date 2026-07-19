# CHANGELOG — LEGACY (per-symbol era) — ARCHIVED

> **Status:** frozen 2026-04-08 when the system pivoted to sector money-flow
> (`CLAUDE.md` §1). Entries below refer to the retired 170-symbol codebase:
> `data_service`, `feature_service`, `prediction_model`, `trade_service`, the
> T+3 scanner, and the OpenClaw agent. Those modules are either deleted or
> live under `_legacy_*` tables scheduled for drop in migration 10.
>
> **Live change log:** `MODIFICATION_LOG.md` at the repo root (append-only,
> per `CLAUDE.md` §15). Do NOT add new entries here.

---

## [2026-03-31] Performance Optimization — Phase 6

### Changed
- **`services/data_service.py`**:
  - `fetch_and_store_sector()`: Sequential API calls → ThreadPoolExecutor with 4 workers for concurrent vnstock API fetching (~3-4× faster)
  - `get_sector_prices()`: N+1 per-symbol query loop → single `WHERE symbol IN(...)` query
  - `fetch_and_store_intraday()`: Row-by-row iterrows upsert → bulk pre-check existing timestamps + bulk INSERT for new records
- **`services/feature_service.py`**:
  - `_upsert_features()`: Row-by-row `session.add()` → bulk `INSERT` for new records (existing rows still updated individually)
- **`models/prediction_model.py`**:
  - `train()`: Added `_cross_validate()` with TimeSeriesSplit — now reports CV avg±std metrics alongside holdout metrics
  - New method `_cross_validate(X_train, y_train, n_splits)` for training robustness assessment
- **`database/connection.py`**: Added SQLite performance pragmas: `synchronous=NORMAL`, `cache_size=64MB`, `mmap_size=256MB`, `temp_store=MEMORY`
- **`database/models.py`**: Added composite indexes on `ModelRun(target_col, is_active, status)`, `Prediction(symbol, prediction_date)`, `Stock(sector)`
- **`database/migrations.py`**: Added migration 7 for composite indexes (applied automatically on next startup)

### Resolved Known Limitations
- Data: Sequential API calls → ThreadPoolExecutor (concurrent fetch)
- ML: No cross-validation in default training → TimeSeriesSplit CV metrics
- DB: No composite indexes → Migration 7 adds 4 performance indexes

---

## [2026-03-18] T+3 Short Trade Page — Phase 1

### Added
- **`database/models.py`**: Added `TradeSetup` (T+3 trade opportunities) and `BacktestRun` (backtesting results) ORM models
- **`services/trade_service.py`**: NEW — Core T+3 trade engine with:
  - `get_earliest_exit_date()`: T+2.5 settlement calendar (3 business days)
  - `compute_confidence()`: Composite score 0-100 (ML 40% + Technical 30% + Volume 20% + Sector 10%)
  - `calculate_entry_exit()`: ATR-based stop-loss (1.5×ATR) and target price
  - `calculate_position_size()`: Risk-based sizing with Vietnam 100-share lots
  - `scan_trades()`: Master scanner combining ML + technical + volume + sector signals
  - `get_return_distribution()`: Historical N-day return analysis with percentiles and histogram
  - `get_trade_detail()`: Detailed single-stock analysis with return distribution
  - Calendar, history, stats methods
- **`api/schemas.py`**: Added Trade schemas (TradeSetupResponse, PositionSizeRequest/Response, TradeCalendarItem, TradeStatsResponse, etc.)
- **`api/routers/trade.py`**: NEW — REST endpoints: /scan, /scan/{symbol}, /calendar, /position-size, /history, /update-status/{id}, /stats, /return-distribution/{symbol}
- **`api/main.py`**: Registered trade router
- **`frontend/src/api/client.ts`**: Added `tradeApi` with all trade endpoint methods
- **`frontend/src/pages/ShortTradePage.tsx`**: NEW — Full T+3 trade page with:
  - Scanner tab: filters (confidence, sector), results table, expandable detail panel
  - Detail panel: T+3 timeline, entry/exit visual bar, confidence breakdown bars, position sizing calculator, return distribution histogram
  - Calendar tab: active trades with entry → earliest sell timeline
  - Performance tab: stats cards + trade history table
  - T+3 risk warning about stop-loss limitations
- **`frontend/src/App.tsx`**: Added `/trade` route
- **`frontend/src/components/Layout.tsx`**: Added "T+3 Trade" nav link with ⚡ icon
- **`docs/CHANGELOG.md`**: NEW — This changelog file

### Algorithm: Confidence Score Formula
```
confidence = ml_score × 0.40 + technical_score × 0.30 + volume_score × 0.20 + sector_score × 0.10

ml_score: predicted_pct mapped to 0-100 (>3% = 90+, 2-3% = 70-89, 1-2% = 50-69)
technical_score: RSI<30 +25, MACD_hist>0 +25, ADX>25 with DI+ > DI- +25, BB_position<0.25 +25
volume_score: min(100, volume_ratio_5 × 40)
sector_score: top-3 momentum sector = 100, top-6 = 60, other = 30
```

### Algorithm: Entry/Exit Strategy
```
entry = current_close
stop_loss = entry - 1.5 × ATR_14
target = min(entry × (1 + ml_predicted_pct), entry + 2.0 × ATR_14)
R:R ratio must be >= 1.5 (adjusted if needed)
```

---

## [2026-03-18] Hyperparameter Tuning & Diagnostics

### Added
- **`models/prediction_model.py`**: Added `train_with_tuning()` method using RandomizedSearchCV, `_build_diagnostics()` for y_test/y_pred/residuals, `TUNING_SPACES` and `TUNING_SPACES_REGRESSION`
- **`services/ml_service.py`**: Added `get_diagnostics()`, passes tuning params in `train_model()` and `train_and_compare()`
- **`api/schemas.py`**: Added `enable_tuning`, `tuning_iter`, `tuning_cv` to TrainRequest
- **`api/routers/ml.py`**: Added tuning params to /train and /train-sync endpoints, added GET /api/ml/models/{id}/diagnostics
- **`frontend/src/api/client.ts`**: Updated train/trainSync with tuning params, added diagnostics() method
- **`frontend/src/pages/MLPage.tsx`**: Added tuning toggle UI, diagnostics visualizations (Actual vs Predicted scatter, Residuals histogram, Confusion Matrix, Tuning banner)

---

## [2026-03-18] Data Upsert Without Override

### Changed
- **`services/data_service.py`**:
  - `_upsert_prices()`: Changed to skip existing dates entirely (no override)
  - Added `_get_last_date()` helper method
  - `fetch_and_store_stock()`: Now only fetches from last available date in DB (smart incremental fetch)

---

## [2026-03-03] ML Regression Support (Price Estimation ±)

### Added
- **`models/prediction_model.py`**: Auto-detect task_type (regression vs classification), RandomForestRegressor, XGBRegressor, LGBMRegressor, Ridge support, MAE/RMSE/R²/MAPE metrics, residual_std for confidence intervals
- **`database/models.py`**: Added regression metric columns (mae, rmse, r2_score_val, mape, residual_std, task_type) to ModelRun, added price estimation columns to Prediction
- **`services/ml_service.py`**: Updated train_model/predict/get_signals for regression, added predict_with_active_model, get_signals methods
- **`api/schemas.py`**: Updated ModelRunResponse with regression metrics, PredictionItem with price fields, added SignalItem and ScreenerItem
- **`frontend/src/pages/MLPage.tsx`**: Added regression target buttons, conditional metrics display, radar chart for regression
- **`frontend/src/pages/SignalPage.tsx`**: NEW — Signal Dashboard with price estimation cards, filters
- **`frontend/src/pages/ScreenerPage.tsx`**: NEW — Stock screener with technical/ML filters

---

## [2026-03-02] Expert Trader Improvements

### Added
- Sector analysis (performance, momentum, correlation, breadth)
- Walk-forward validation
- Feature importance ranking
- Chart drawing tools (trendlines, Fibonacci, horizontal lines)
- Dashboard with customizable widgets (mini chart, sector performance, signal overview)

---

## [2026-03-01] Initial System

### Built
- Data pipeline: vnstock API → SQLite with OHLCV data
- 48+ technical indicators (SMA, EMA, RSI, MACD, Bollinger, ADX, ATR, OBV, etc.)
- ML models: Logistic Regression, Random Forest, XGBoost, LightGBM
- Binary classification targets (target_bin_1d/3d/5d/10d/20d)
- Regression targets (target_reg_1d/3d/5d/10d/20d)
- FastAPI backend with RESTful endpoints
- React + Vite + Tailwind frontend with dark theme
- Candlestick chart with lightweight-charts
- 12 sector classification with 150+ Vietnam stocks
