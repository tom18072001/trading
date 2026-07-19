# ============================================
# api/schemas.py
# Pydantic models cho request/response validation
# ============================================

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ==========================================
# STOCKS
# ==========================================

class StockBase(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    sector: str
    exchange: Optional[str] = None

class StockResponse(StockBase):
    market_cap: Optional[float] = None
    is_active: bool = True
    last_updated: Optional[datetime] = None

    class Config:
        from_attributes = True

class StockSearchParams(BaseModel):
    q: str = ""
    sector: Optional[str] = None
    limit: int = 50

class PriceRow(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str

class PriceResponse(BaseModel):
    symbol: str
    count: int
    data: list[PriceRow]

class FetchRequest(BaseModel):
    symbols: Optional[list[str]] = None
    sector: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class FetchResponse(BaseModel):
    status: str
    message: str
    rows_fetched: int = 0


class FetchIntradayRequest(BaseModel):
    symbol: str
    interval: str = "1H"
    days_back: int = 7


class IntradayPriceRow(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    interval: str

class DataSummaryItem(BaseModel):
    symbol: str
    sector: str
    num_rows: int
    first_date: Optional[str] = None
    last_date: Optional[str] = None


# ==========================================
# SECTORS
# ==========================================

class SectorPerformanceItem(BaseModel):
    sector: str = ""
    avg_return: Optional[float] = None
    median_return: Optional[float] = None
    best_stock: Optional[float] = None
    worst_stock: Optional[float] = None
    num_stocks: Optional[int] = None
    total_volume: Optional[float] = None

class SectorMomentumItem(BaseModel):
    sector: str = ""
    momentum_return: Optional[float] = None
    positive_pct: Optional[float] = None
    num_stocks: Optional[int] = None
    rank: Optional[int] = None

class SectorCorrelationResponse(BaseModel):
    sectors: list[str] = []
    matrix: list[list[float]] = []

class SectorStockItem(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    sector: str
    exchange: Optional[str] = None
    price_count: int = 0


# ==========================================
# ML
# ==========================================

class TrainRequest(BaseModel):
    model_names: list[str] = Field(
        default=["random_forest", "xgboost", "lightgbm"],
        description="Models to train"
    )
    target_col: str = Field(default="target_bin_5d", description="Target variable")
    symbols: Optional[list[str]] = None
    sector: Optional[str] = None
    enable_tuning: bool = Field(default=False, description="Enable RandomizedSearchCV tuning")
    tuning_iter: int = Field(default=30, ge=5, le=100, description="Number of random search iterations")
    tuning_cv: int = Field(default=3, ge=2, le=10, description="Number of CV folds for tuning")

class ModelRunResponse(BaseModel):
    id: int
    model_name: str
    target_col: str
    trained_at: Optional[datetime] = None
    # Classification metrics
    accuracy: Optional[float] = None
    precision_score: Optional[float] = None
    recall_score: Optional[float] = None
    f1_score: Optional[float] = None
    auc_roc: Optional[float] = None
    # Regression metrics
    mae: Optional[float] = None
    rmse: Optional[float] = None
    r2_score_val: Optional[float] = None
    mape: Optional[float] = None
    # Common
    train_size: Optional[int] = None
    test_size: Optional[int] = None
    is_active: bool = False
    status: str = "completed"
    task_type: Optional[str] = "classification"
    training_scope: Optional[str] = None
    training_scope_value: Optional[str] = None

    class Config:
        from_attributes = True

class PredictRequest(BaseModel):
    model_run_id: int
    symbols: list[str]

class PredictionItem(BaseModel):
    symbol: str = ""
    prediction: int = 0
    probability: float = 0.0
    confidence_label: str = ""
    pred_label: str = ""
    close: float = 0.0
    time: str = ""
    # Regression fields
    predicted_price: Optional[float] = None
    price_change_pct: Optional[float] = None
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None

class FeatureImportanceItem(BaseModel):
    feature: str
    importance: float
    rank: Optional[int] = None

class ComparisonRow(BaseModel):
    id: int
    model: str
    target: str
    task_type: Optional[str] = "classification"
    # Classification
    accuracy: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1: Optional[float] = None
    auc_roc: Optional[float] = None
    # Regression
    mae: Optional[float] = None
    rmse: Optional[float] = None
    r2: Optional[float] = None
    mape: Optional[float] = None
    trained_at: Optional[str] = None
    is_active: bool = False


class SignalItem(BaseModel):
    symbol: str
    current_price: float = 0.0
    predicted_price: float = 0.0
    price_change_pct: float = 0.0
    lower_bound: float = 0.0
    upper_bound: float = 0.0
    signal: str = ""       # BULLISH, BEARISH, NEUTRAL
    strength: str = ""     # STRONG, MODERATE, WEAK


class ScreenerItem(BaseModel):
    symbol: str
    sector: str = ""
    close: float = 0.0
    rsi_14: Optional[float] = None
    macd: Optional[float] = None
    adx_14: Optional[float] = None
    volume_ratio: Optional[float] = None
    predicted_change_pct: Optional[float] = None
    signal: Optional[str] = None


# ==========================================
# FEATURES
# ==========================================

class FeatureRow(BaseModel):
    time: str
    symbol: str
    # All other fields are dynamic, return as dict

class FeatureResponse(BaseModel):
    symbol: str
    count: int
    columns: list[str]
    data: list[dict]

class ComputeFeaturesRequest(BaseModel):
    symbols: Optional[list[str]] = None
    sector: Optional[str] = None

class ComputeFeaturesResponse(BaseModel):
    status: str
    symbols_processed: int
    total_rows: int


# ==========================================
# DASHBOARD
# ==========================================

class DashboardLayoutCreate(BaseModel):
    name: str
    layout_json: str
    is_default: bool = False

class DashboardLayoutResponse(BaseModel):
    id: int
    name: str
    layout_json: str
    is_default: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==========================================
# CHART DRAWINGS
# ==========================================

class ChartDrawingCreate(BaseModel):
    drawing_type: str  # trendline, horizontal, fibonacci, rectangle
    data: str          # JSON: coordinates, color, style

class ChartDrawingResponse(BaseModel):
    id: int
    symbol: str
    drawing_type: str
    data: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==========================================
# GENERIC
# ==========================================

class StatusResponse(BaseModel):
    status: str
    message: str

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str  # running, completed, failed
    message: str = ""
    result: Optional[dict] = None


# ==========================================
# TRADE (T+3 Short Trade)
# ==========================================

class TradeSetupResponse(BaseModel):
    id: Optional[int] = None
    symbol: str
    sector: Optional[str] = None
    scan_date: str = ""
    direction: str = "LONG"
    entry_price: float = 0
    target_price: float = 0
    stop_loss: float = 0
    risk_reward_ratio: float = 0
    confidence_score: float = 0
    ml_prediction_pct: float = 0
    technical_score: float = 0
    volume_score: float = 0
    sector_score: Optional[float] = None
    earliest_exit_date: Optional[str] = None
    expected_hold_days: int = 3
    atr_14: Optional[float] = None
    setup_type: Optional[str] = None
    worst_case_pct: Optional[float] = None
    status: str = "active"
    actual_exit_price: Optional[float] = None
    actual_return_pct: Optional[float] = None

class TradeSetupDetailResponse(TradeSetupResponse):
    return_distribution: Optional[dict] = None

class PositionSizeRequest(BaseModel):
    account_size: float = Field(default=100_000_000, description="Account size in VND")
    risk_pct: float = Field(default=0.02, ge=0.001, le=0.10, description="Risk per trade (0.02 = 2%)")
    entry_price: float
    stop_loss: float

class PositionSizeResponse(BaseModel):
    shares: int = 0
    lots: int = 0
    position_value: float = 0
    position_pct: float = 0
    risk_amount: float = 0
    risk_per_share: float = 0

class TradeCalendarItem(BaseModel):
    id: int
    symbol: str
    sector: Optional[str] = None
    entry_date: str = ""
    earliest_exit_date: Optional[str] = None
    entry_price: float = 0
    target_price: float = 0
    stop_loss: float = 0
    confidence_score: float = 0
    direction: str = "LONG"
    status: str = "active"

class TradeStatsResponse(BaseModel):
    total_trades: int = 0
    active_trades: int = 0
    closed_trades: int = 0
    win_rate: Optional[float] = None
    avg_return_pct: Optional[float] = None
    avg_profit_pct: Optional[float] = None
    avg_loss_pct: Optional[float] = None
    best_trade_pct: Optional[float] = None
    worst_trade_pct: Optional[float] = None
    profit_factor: Optional[float] = None

class TradeUpdateRequest(BaseModel):
    status: str  # hit_target, hit_stop, expired
    actual_exit_price: Optional[float] = None


# ==========================================
# BACKTEST
# ==========================================

class BacktestRequest(BaseModel):
    strategy: str = Field(default="confidence", description="confidence, momentum_breakout, mean_reversion, ml_only")
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_capital: float = Field(default=100_000_000, description="Starting capital VND")
    risk_pct: float = Field(default=0.02, ge=0.005, le=0.10)
    min_confidence: float = Field(default=50, ge=0, le=100)
    max_positions: int = Field(default=5, ge=1, le=20)
    stop_loss_atr: float = Field(default=1.5, ge=0.5, le=5.0)
    take_profit_atr: float = Field(default=2.0, ge=0.5, le=10.0)
    symbols: Optional[list[str]] = None
    sector: Optional[str] = None
    use_ml: bool = Field(default=False, description="Use rolling ML predictions (slower but more accurate)")
    ml_retrain_days: int = Field(default=20, ge=5, le=60, description="Retrain ML model every N trading days")

class BacktestRunSummary(BaseModel):
    id: int
    name: str = ""
    strategy: str = ""
    start_date: str = ""
    end_date: str = ""
    initial_capital: Optional[float] = None
    final_capital: Optional[float] = None
    total_trades: Optional[int] = None
    win_rate: Optional[float] = None
    avg_profit_pct: Optional[float] = None
    avg_loss_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    profit_factor: Optional[float] = None
    total_return_pct: Optional[float] = None
    created_at: Optional[str] = None

class BacktestRunDetail(BacktestRunSummary):
    params: Optional[dict] = None
    equity_curve: Optional[list[dict]] = None
    trade_log: Optional[list[dict]] = None
