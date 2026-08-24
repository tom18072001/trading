# ============================================
# api/routers/sectors_backtest.py
# ============================================
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_session_dependency
from database.models import BacktestRun
from services.backtest_service import SectorBacktestService

router = APIRouter(prefix="/api/sectors", tags=["sectors-backtest"])


class BacktestRequest(BaseModel):
    """`strategy` and the cost overrides existed in the service since
    2026-08-22 (P0-4) but had no way in over HTTP, so every run the UI could
    trigger was the default. Literal, not str: an unknown strategy silently
    fell through to the `flow_raw` branch, which is the one behaviour nobody
    wants by accident.
    """

    name: str = "rotation_default"
    start_date: str
    end_date: str
    initial_capital: float = 100_000_000
    strategy: Literal["signals", "flow_z", "flow_raw"] = "signals"
    # Per-run overrides of the §18.2/7,10 defaults. None = use config.
    fee_bps: float | None = Field(default=None, ge=0, le=500)
    sell_tax_bps: float | None = Field(default=None, ge=0, le=500)
    settlement_lag: int | None = Field(default=None, ge=0, le=10)


@router.post("/backtest")
def run_backtest(req: BacktestRequest, db: Session = Depends(get_session_dependency)):
    svc = SectorBacktestService(db)
    result = svc.run(
        req.name, req.start_date, req.end_date, req.initial_capital,
        strategy=req.strategy,
        fee_bps=req.fee_bps,
        sell_tax_bps=req.sell_tax_bps,
        settlement_lag=req.settlement_lag,
    )
    out = asdict(result)
    out["equity_curve"] = out["equity_curve"][:200]
    out["trade_log"] = out["trade_log"][:200]
    return out


@router.get("/backtest")
def list_runs(limit: int = 20, db: Session = Depends(get_session_dependency)):
    rows = db.query(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id, "name": r.name, "strategy": r.strategy,
            "start_date": r.start_date, "end_date": r.end_date,
            "total_return_pct": r.total_return_pct,
            "sharpe_ratio": r.sharpe_ratio,
            "max_drawdown_pct": r.max_drawdown_pct,
            "win_rate": r.win_rate,
        }
        for r in rows
    ]
