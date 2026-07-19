# ============================================
# database/models.py — Sector Money-Flow Schema
# ============================================
# Source of truth: CLAUDE.md §5. Primary key everywhere is `sector_code`,
# never `symbol`. Symbol-level tables from the legacy 170-symbol design are
# REMOVED. Constituents survive only as a reference table.

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ============================================
# 1. SECTORS — 15 VN sectors
# ============================================
class Sector(Base):
    __tablename__ = "sectors"

    sector_code = Column(String(16), primary_key=True)        # e.g. "BANK"
    name = Column(String(100), nullable=False)                # display name
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    constituents = relationship(
        "SectorConstituent", back_populates="sector",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Sector {self.sector_code} {self.name}>"


# ============================================
# 2. SECTOR_CONSTITUENTS — proxy basket reference
# ============================================
class SectorConstituent(Base):
    __tablename__ = "sector_constituents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sector_code = Column(String(16), ForeignKey("sectors.sector_code"), nullable=False)
    symbol = Column(String(20), nullable=False)
    weight = Column(Float, default=0.0)
    active = Column(Boolean, default=True)

    __table_args__ = (
        UniqueConstraint("sector_code", "symbol", name="uq_constituent_sector_symbol"),
        Index("ix_constituent_sector", "sector_code"),
    )

    sector = relationship("Sector", back_populates="constituents")


# ============================================
# 3. SECTOR_FLOW_TS — intraday money flow time series
# ============================================
class SectorFlowTS(Base):
    __tablename__ = "sector_flow_ts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sector_code = Column(String(16), ForeignKey("sectors.sector_code"), nullable=False)
    time = Column(DateTime, nullable=False)

    net_dollar_flow = Column(Float)        # Σ price·volume·sign(tick)
    up_vol = Column(Float)
    down_vol = Column(Float)
    foreign_net = Column(Float)            # vnstock foreign net buy
    foreign_buy_val = Column(Float)        # gross foreign buy value
    foreign_sell_val = Column(Float)       # gross foreign sell value
    foreign_intensity = Column(Float)      # foreign_net / total_turnover
    breadth_sma20 = Column(Float)          # % of basket above SMA20
    breadth_sma50 = Column(Float)          # % of basket above SMA50
    rs_vnindex_5d = Column(Float)
    rs_vnindex_20d = Column(Float)
    atr_pct = Column(Float)

    __table_args__ = (
        UniqueConstraint("sector_code", "time", name="uq_flow_ts_sector_time"),
        Index("ix_flow_ts_sector_time", "sector_code", "time"),
    )

    def __repr__(self) -> str:
        return f"<SectorFlowTS {self.sector_code} {self.time} flow={self.net_dollar_flow}>"


# ============================================
# 4. SECTOR_FLOW_DAILY — daily rollups
# ============================================
class SectorFlowDaily(Base):
    __tablename__ = "sector_flow_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sector_code = Column(String(16), ForeignKey("sectors.sector_code"), nullable=False)
    date = Column(String(20), nullable=False)              # YYYY-MM-DD

    open_idx = Column(Float)                                # synthetic sector index
    close_idx = Column(Float)
    high_idx = Column(Float)
    low_idx = Column(Float)
    return_1d = Column(Float)

    net_dollar_flow = Column(Float)
    foreign_net = Column(Float)
    foreign_buy_val = Column(Float)
    foreign_sell_val = Column(Float)
    foreign_intensity = Column(Float)
    up_down_vol_ratio = Column(Float)
    breadth_sma20 = Column(Float)
    breadth_sma50 = Column(Float)
    rs_vnindex_5d = Column(Float)
    rs_vnindex_20d = Column(Float)
    rs_vnindex_60d = Column(Float)
    atr_pct = Column(Float)
    vol_20d = Column(Float)

    # --- §16 leading-flow / stealth detection columns (migration 9) ---
    flow_z20 = Column(Float)
    flow_z60 = Column(Float)
    foreign_streak = Column(Integer)
    foreign_hit_20d = Column(Float)
    stealth_score = Column(Float)
    flow_price_divergence = Column(Float)
    accumulation_age = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("sector_code", "date", name="uq_flow_daily_sector_date"),
        Index("ix_flow_daily_sector_date", "sector_code", "date"),
    )


# ============================================
# 4b. SECTOR_ACCUMULATION_EVENTS — stealth-phase journal (§16.7)
# ============================================
class SectorAccumulationEvent(Base):
    __tablename__ = "sector_accumulation_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sector_code = Column(String(16), ForeignKey("sectors.sector_code"), nullable=False)
    start_date = Column(String(20), nullable=False)
    end_date = Column(String(20))
    peak_return_pct = Column(Float)
    lead_days_to_price = Column(Integer)
    resolved = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("sector_code", "start_date", name="uq_accum_sector_start"),
        Index("ix_accum_events_sector", "sector_code", "start_date"),
    )


# ============================================
# 4c. SECTOR_FLOW_HANDOFF — rotation matrix (flow leaving A, entering B)
# ============================================
class SectorFlowHandoff(Base):
    __tablename__ = "sector_flow_handoff"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(20), nullable=False)
    from_sector = Column(String(16), nullable=False)
    to_sector = Column(String(16), nullable=False)
    handoff_score = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("date", "from_sector", "to_sector", name="uq_handoff"),
        Index("ix_handoff_date", "date"),
    )


# ============================================
# 5. MACRO_ANCHORS — shared macro features
# ============================================
class MacroAnchor(Base):
    __tablename__ = "macro_anchors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    time = Column(DateTime, nullable=False, unique=True)
    vnindex = Column(Float)
    usdvnd = Column(Float)
    brent = Column(Float)
    us10y = Column(Float)
    gold = Column(Float)

    __table_args__ = (Index("ix_macro_time", "time"),)


# ============================================
# 6. SECTOR_REGIME — HMM regime classification
# ============================================
class SectorRegime(Base):
    __tablename__ = "sector_regime"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(20), nullable=False, unique=True)
    regime_label = Column(String(20), nullable=False)      # risk_on / risk_off / rotation / chop
    confidence = Column(Float)
    model_version = Column(String(40))


# ============================================
# 7. SECTOR_SIGNALS — daily ranked signals
# ============================================
class SectorSignal(Base):
    __tablename__ = "sector_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(20), nullable=False)
    sector_code = Column(String(16), ForeignKey("sectors.sector_code"), nullable=False)
    score = Column(Float, nullable=False)
    rank = Column(Integer, nullable=False)
    action = Column(String(8), nullable=False)             # BUY / SELL / HOLD
    persistence_ok = Column(Boolean, default=False)
    model_run_id = Column(Integer, ForeignKey("model_runs.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint("date", "sector_code", name="uq_signal_date_sector"),
        Index("ix_signal_date_rank", "date", "rank"),
    )


# ============================================
# 8. MODEL_RUNS — retained, retrofitted for sector ranker
# ============================================
class ModelRun(Base):
    __tablename__ = "model_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String(50), nullable=False)        # "rotation_ranker_v0", "regime_hmm_v0"
    target_col = Column(String(50), nullable=False)        # "fwd_5d_sector_return"
    trained_at = Column(DateTime, default=datetime.utcnow)
    train_size = Column(Integer)
    test_size = Column(Integer)
    features_used = Column(Text)                            # JSON
    hyperparams = Column(Text)                              # JSON
    metrics = Column(Text)                                  # JSON: ndcg/hitrate/etc.
    model_path = Column(String(500))
    is_active = Column(Boolean, default=False)
    status = Column(String(20), default="completed")

    __table_args__ = (
        Index("ix_model_run_target_active", "target_col", "is_active", "status"),
    )


# ============================================
# 9. BACKTEST_RUNS — retained, sector basket simulation
# ============================================
class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    strategy = Column(String(50), nullable=False)          # e.g. "rotation_long_short"
    start_date = Column(String(20), nullable=False)
    end_date = Column(String(20), nullable=False)
    initial_capital = Column(Float, default=100_000_000)
    final_capital = Column(Float)
    total_trades = Column(Integer)
    win_rate = Column(Float)
    sharpe_ratio = Column(Float)
    max_drawdown_pct = Column(Float)
    total_return_pct = Column(Float)
    benchmark_return_pct = Column(Float)
    params = Column(Text)
    equity_curve = Column(Text)
    trade_log = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_backtest_created", "created_at"),)


# ============================================
# 10. DASHBOARD_LAYOUTS — retained
# ============================================
class DashboardLayout(Base):
    __tablename__ = "dashboard_layouts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    layout_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_default = Column(Boolean, default=False)


# ============================================
# 11. API_USERS / API_KEYS — retained for public API auth
# ============================================
class APIUser(Base):
    __tablename__ = "api_users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False)
    tier = Column(String(20), default="free")
    created_at = Column(DateTime, default=func.now())
    is_active = Column(Boolean, default=True)


class APIKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("api_users.id"), nullable=False)
    key_prefix = Column(String(8), index=True)
    key_hash = Column(String(255), nullable=False)
    name = Column(String(100))
    created_at = Column(DateTime, default=func.now())
    last_used = Column(DateTime)
    is_active = Column(Boolean, default=True)
