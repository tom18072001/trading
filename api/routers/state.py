"""/api/state/* — operator state: kill-switch, positions, watchlist.

Backed by services.trading_state (one JSON file, not a table — see that
module's docstring for why). Every endpoint returns the FULL state, so the
client never has to merge partial responses or re-fetch after a mutation.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import report_runner, trading_state

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
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.delete("/positions/{symbol}")
def remove_position(symbol: str, side: str = "BUY"):
    return trading_state.remove_position(symbol, side)


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
