# ============================================
# api/routers/sectors_backtest.py
# ============================================
from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.connection import get_session_dependency
from database.models import BacktestRun
from services.backtest_service import SectorBacktestService

router = APIRouter(prefix="/api/sectors", tags=["sectors-backtest"])


class BacktestRequest(BaseModel):
    name: str = "rotation_default"
    start_date: str
    end_date: str
    initial_capital: float = 100_000_000


@router.post("/backtest")
def run_backtest(req: BacktestRequest, db: Session = Depends(get_session_dependency)):
    svc = SectorBacktestService(db)
    result = svc.run(req.name, req.start_date, req.end_date, req.initial_capital)
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
