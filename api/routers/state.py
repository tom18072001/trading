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
            stop=body.stop, target=body.target,
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


#: T+2 cash settlement on HOSE — you may sell on the 2nd session after the buy.
SETTLEMENT_SESSIONS = 2


def _track(p: dict, daily: list[dict], last: float | None) -> dict:
    """Everything the book needs to answer "is this trade still valid".

    `daily` is the 30-session OHLCV tail PicksUniverseService already carries on
    every TickerRow and already round-trips to disk — no new data source. It
    keys the date as "time"; the rest of the API says "date", so the rename
    happens here, once.

    `hit_stop` / `hit_target` are EVER TOUCHED since entry, not "today's close
    is through the level": a stop that was breached on Tuesday and recovered by
    Friday is still a stop that was breached, and a book that forgets that is
    telling you the trade is fine.
    """
    from utils.clock import next_trading_day, sessions_between, to_market_date

    stop, target = p.get("stop"), p.get("target")
    out: dict = {
        "path": [], "hit_stop": False, "hit_target": False,
        "dist_to_stop_pct": None, "dist_to_target_pct": None,
        "sessions_held": None, "sellable_on": None,
    }

    opened = p.get("opened_at")
    if opened:
        try:
            d0 = to_market_date(opened)
            out["sessions_held"] = sessions_between(d0)
            out["sellable_on"] = next_trading_day(d0, SETTLEMENT_SESSIONS).isoformat()
        except (ValueError, TypeError):
            pass   # a hand-edited opened_at must not 500 the whole book

    for bar in daily:
        d = bar.get("time") or bar.get("date")
        if not d or (opened and str(d)[:10] < str(opened)[:10]):
            continue
        close = bar.get("close")
        if close is None:
            continue
        out["path"].append({"date": str(d)[:10], "close": float(close)})

    # ponytail: closes only — daily_prices carries open/close/volume, no high or
    # low, so an intraday wick through the stop that closed back above it does
    # not register. Widen the tail to OHLC in picks_universe_service if that
    # matters; on a swing book judged on closes it does not.
    closes = [b["close"] for b in out["path"]]
    if closes:
        if stop:
            out["hit_stop"] = min(closes) <= stop
        if target:
            out["hit_target"] = max(closes) >= target

    if last:
        if stop:
            out["dist_to_stop_pct"] = (last / stop - 1) * 100
        if target:
            out["dist_to_target_pct"] = (target / last - 1) * 100
    return out


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
    paths: dict[str, list] = {}
    as_of = None
    try:
        from services.picks_universe_service import PicksUniverseService
        snap = PicksUniverseService().peek()
        if snap:
            as_of = str(snap.as_of)
            prices = {sym: t.close for sym, t in snap.tickers.items()
                      if getattr(t, "close", None)}
            paths = {sym: (getattr(t, "daily_prices", None) or [])
                     for sym, t in snap.tickers.items()}
    except Exception:  # noqa: BLE001 - a price lookup must never break the book
        log.exception("[state] price lookup failed; returning book unmarked")

    out = []
    total_cost = total_value = 0.0
    for p in rows:
        last = prices.get(p.get("symbol", ""))
        entry, qty = p.get("entry_price"), p.get("qty")
        row = {**p, "last": last, "pnl_pct": None, "pnl_vnd": None, "value": None,
               **_track(p, paths.get(p.get("symbol", "")) or [], last)}
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
