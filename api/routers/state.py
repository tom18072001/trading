"""/api/state/* — operator state: kill-switch, positions, watchlist.

Backed by services.trading_state (one JSON file, not a table — see that
module's docstring for why). Every endpoint returns the FULL state, so the
client never has to merge partial responses or re-fetch after a mutation.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


class PositionPatch(BaseModel):
    """Partial edit. `None` = leave alone; a negative number clears the field."""
    entry_price: float | None = None
    qty: float | None = None
    note: str | None = None
    opened_at: str | None = None


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


@router.patch("/positions/{symbol}")
def update_position(symbol: str, body: PositionPatch, side: str = "BUY"):
    try:
        return trading_state.update_position(
            symbol, side, entry_price=body.entry_price, qty=body.qty,
            note=body.note, opened_at=body.opened_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/positions/{symbol}")
def remove_position(symbol: str, side: str = "BUY"):
    return trading_state.remove_position(symbol, side)


@router.get("/positions/pnl")
def positions_pnl():
    """The book marked to the last close the app already knows.

    Prices come from the PicksUniverseService snapshot — the same cache that
    feeds Daily Insight — via `.peek()`, never `get_snapshot()`. A cold cache
    must return the book with `last=None` in a few milliseconds, not block a
    request for minutes behind the 18 req/min KBS throttle (the trap
    api/routers/insight.py documents at its `/daily` handler).

    ponytail: last close, not intraday, and no fees or the 0.1% sell tax from
    §18.2/10 — this is a position tracker, not the backtest cost model. Add
    them here if this number ever drives a decision rather than describing one.
    """
    state = trading_state.get_state()
    rows = state["positions"]

    prices: dict[str, float] = {}
    as_of = None
    try:
        from services.picks_universe_service import PicksUniverseService
        snap = PicksUniverseService().peek()
        if snap:
            as_of = str(snap.as_of)
            prices = {sym: t.close for sym, t in snap.tickers.items()
                      if getattr(t, "close", None)}
    except Exception:  # noqa: BLE001 - a price lookup must never break the book
        log.exception("[state] price lookup failed; returning book unmarked")

    out = []
    total_cost = total_value = 0.0
    for p in rows:
        last = prices.get(p.get("symbol", ""))
        entry, qty = p.get("entry_price"), p.get("qty")
        row = {**p, "last": last, "pnl_pct": None, "pnl_vnd": None, "value": None}
        if last and entry:
            # A SELL mark is a short in the book's own terms; VN cash cannot
            # short (§18.2/12), so this is really "I exited" — sign it anyway
            # so the number means the same thing on both sides.
            direction = 1 if p.get("side") == "BUY" else -1
            row["pnl_pct"] = direction * (last / entry - 1) * 100
            if qty:
                row["value"] = last * qty
                row["pnl_vnd"] = direction * (last - entry) * qty
                total_cost += entry * qty
                total_value += last * qty
        out.append(row)

    return {
        "as_of": as_of,
        "positions": out,
        "total_cost": total_cost or None,
        "total_value": total_value or None,
        "total_pnl_vnd": (total_value - total_cost) if total_cost else None,
        "total_pnl_pct": ((total_value / total_cost - 1) * 100) if total_cost else None,
        # How much of the book is actually measurable — a P&L computed over 2 of
        # 9 positions must not be read as the book's P&L.
        "priced": sum(1 for r in out if r["pnl_pct"] is not None),
        "count": len(out),
    }


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
