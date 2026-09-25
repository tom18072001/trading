"""/api/state/* — operator state: kill-switch, positions, watchlist.

Backed by services.trading_state (one JSON file, not a table — see that
module's docstring for why). Every endpoint returns the FULL state, so the
client never has to merge partial responses or re-fetch after a mutation.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from daily_watch import positions as position_tracking
from services import report_runner, trading_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/state", tags=["state"])


class HaltBody(BaseModel):
    halt: bool
    reason: str = ""


class PositionBody(BaseModel):
    symbol: str
    sector_code: str = ""
    side: str = "BUY"
    entry_price: float | None = None
    qty: float | None = None
    note: str = ""
    stop: float | None = None
    target: float | None = None
    thesis: str = ""


class PositionPatch(BaseModel):
    """Partial edit. `None` = leave alone; a negative number clears the field."""
    entry_price: float | None = None
    qty: float | None = None
    note: str | None = None
    opened_at: str | None = None
    stop: float | None = None
    target: float | None = None
    thesis: str | None = None


class PositionClose(BaseModel):
    """Book an exit. `exit_price` is required — that is the point of the verb."""
    exit_price: float
    closed_at: str | None = None
    note: str | None = None


class SymbolBody(BaseModel):
    symbol: str


class CapitalBody(BaseModel):
    capital_mn: float


@router.get("")
def get_state():
    return trading_state.get_state()


@router.post("/halt")
def set_halt(body: HaltBody):
    return trading_state.set_halt(body.halt, body.reason)


@router.post("/capital")
def set_capital(body: CapitalBody):
    return trading_state.set_capital(body.capital_mn)


@router.post("/positions")
def add_position(body: PositionBody):
    try:
        return trading_state.add_position(
            body.symbol, body.sector_code, body.side,
            body.entry_price, body.qty, body.note,
            stop=body.stop, target=body.target, thesis=body.thesis,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.patch("/positions/{symbol}")
def update_position(symbol: str, body: PositionPatch, side: str = "BUY"):
    try:
        return trading_state.update_position(
            symbol, side, entry_price=body.entry_price, qty=body.qty,
            note=body.note, opened_at=body.opened_at,
            stop=body.stop, target=body.target, thesis=body.thesis,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/positions/{symbol}/close")
def close_position(symbol: str, body: PositionClose, side: str = "BUY"):
    """Sell it. Distinct from DELETE, which is for a mis-click.

    DELETE throws the row away; this keeps it in `closed` with realised P&L, so
    the book can eventually answer whether the picks made money.
    """
    try:
        return trading_state.close_position(
            symbol, side, exit_price=body.exit_price,
            closed_at=body.closed_at, note=body.note,
        )
    except ValueError as e:
        # "no open position" is a 404; "exit_price must be positive" is a 422.
        status = 422 if "exit_price" in str(e) else 404
        raise HTTPException(status_code=status, detail=str(e)) from e


@router.delete("/positions/{symbol}")
def remove_position(symbol: str, side: str = "BUY"):
    return trading_state.remove_position(symbol, side)


@router.get("/positions/pnl")
def positions_pnl():
    """Sổ được chấm theo giá đóng gần nhất — logic ở daily_watch/positions.py.

    Nó rời khỏi file này ngày 2026-09-16 vì job cảnh báo stop hằng ngày cần đúng
    định nghĩa "đã chạm stop chưa", mà một job Task Scheduler không gọi được một
    route. Viết lại ở hai chỗ là hai định nghĩa sẽ lệch (§22.11).
    """
    return position_tracking.mark_book()


@router.get("/positions/realised")
def positions_realised():
    """Closed trades, net of the §18.2/10 costs the backtest charges.

    Declared next to /positions/pnl for the same reason that one is: a literal
    path segment that shares a prefix with /positions/{symbol} must not end up
    matched as a symbol named "realised".
    """
    return trading_state.realised_pnl()


@router.post("/watchlist")
def toggle_watch(body: SymbolBody):
    try:
        return trading_state.toggle_watch(body.symbol)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


# ----- send the daily report now (backlog step 6) --------------------------
# Not part of the state file; it lives here because it is the same thing —
# an operator action, not model output.

class ReportBody(BaseModel):
    report_date: str | None = None
    send_email: bool = True


@router.post("/report/send")
def send_report(body: ReportBody):
    try:
        return report_runner.send_report(body.report_date, body.send_email)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/report/status")
def report_status():
    return report_runner.get_status()
