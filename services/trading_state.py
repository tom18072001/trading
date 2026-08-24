"""Operator state that outlives a page reload and a process restart.

Three things the UI could not remember before (review §D, backlog step 4):

  halt       §18.4/20 kill-switch. `config.TRADING_HALT` is an env var, so the
             only way to stop the 17:00 publish from emitting new long exposure
             was to edit .env and restart. It is now also a runtime flag, and
             `SectorSignalService.publish()` halts if EITHER is set — the env
             var stays a hard override you cannot un-set from a browser.
  positions  "Đã vào lệnh". The app showed picks with no idea which ones you
             actually took, so every screen re-recommended what you already own.
  watchlist  Symbols you are tracking but have not entered.

Storage is one JSON file, not a table. Migration 12 for three keys would be
ceremony: this is single-operator state, it is tiny, and it must be readable by
the scheduler process, which has no HTTP client. Same durable-cache pattern as
picks_universe_service.SNAPSHOT_PATH, and it is written the same way —
temp-file + replace, so a crash mid-write cannot leave a half-file behind.

ponytail: single-file store, one operator, one machine. If a second user or a
second machine ever appears, this becomes a table and the read path becomes a
query — the API shape above it does not have to change.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from config import DATA_DIR, TRADING_HALT
from utils.clock import now, today_str

log = logging.getLogger(__name__)

STATE_PATH = Path(DATA_DIR) / "trading_state.json"

_DEFAULT: dict[str, Any] = {
    "halt": False,
    "halt_reason": "",
    "halt_set_at": None,
    "capital_mn": 100,      # the Daily Insight sizing slider, in triệu VND
    "positions": [],        # [{symbol, sector_code, side, entry_price, qty, note, opened_at}]
    "watchlist": [],        # [symbol]
}

_lock = threading.Lock()


def _read() -> dict[str, Any]:
    """Never raises. A corrupt or absent file means 'no state yet'."""
    if not STATE_PATH.exists():
        return dict(_DEFAULT)
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("state file is not an object")
    except Exception as e:
        log.warning("[state] ignoring unreadable %s: %s", STATE_PATH, e)
        return dict(_DEFAULT)
    return {**_DEFAULT, **raw}


def _write(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def get_state() -> dict[str, Any]:
    """Current state, plus the two derived fields the UI banner needs."""
    with _lock:
        s = _read()
    s["halt_env"] = TRADING_HALT
    s["halt_effective"] = bool(TRADING_HALT or s["halt"])
    return s


def is_halted() -> bool:
    """The one question sector_signal_service asks. Env var wins if set."""
    if TRADING_HALT:
        return True
    try:
        return bool(_read()["halt"])
    except Exception:
        # A halt that cannot be read is not a halt — but say so loudly, because
        # the safe direction here is arguable and silence is not.
        log.exception("[state] could not read halt flag; treating as NOT halted")
        return False


def set_halt(halt: bool, reason: str = "") -> dict[str, Any]:
    with _lock:
        s = _read()
        s["halt"] = bool(halt)
        s["halt_reason"] = reason.strip() if halt else ""
        s["halt_set_at"] = now().isoformat(timespec="seconds") if halt else None
        _write(s)
    log.warning("[state] TRADING HALT %s%s", "SET" if halt else "CLEARED",
                f" — {reason}" if reason else "")
    return get_state()


def set_capital(capital_mn: float) -> dict[str, Any]:
    with _lock:
        s = _read()
        s["capital_mn"] = max(1.0, float(capital_mn))
        _write(s)
    return get_state()


def add_position(symbol: str, sector_code: str = "", side: str = "BUY",
                 entry_price: float | None = None, qty: float | None = None,
                 note: str = "") -> dict[str, Any]:
    """Idempotent on (symbol, side): re-marking a pick updates it, not duplicates."""
    sym = symbol.strip().upper()
    if not sym:
        raise ValueError("symbol is required")
    side = side.strip().upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    row = {
        "symbol": sym,
        "sector_code": sector_code.strip().upper(),
        "side": side,
        "entry_price": float(entry_price) if entry_price is not None else None,
        "qty": float(qty) if qty is not None else None,
        "note": note.strip(),
        "opened_at": today_str(),
    }
    with _lock:
        s = _read()
        rest = [p for p in s["positions"]
                if not (p.get("symbol") == sym and p.get("side") == side)]
        s["positions"] = [*rest, row]
        s["watchlist"] = [w for w in s["watchlist"] if w != sym]
        _write(s)
    return get_state()


def update_position(symbol: str, side: str = "BUY", *,
                    entry_price: float | None = None, qty: float | None = None,
                    note: str | None = None, opened_at: str | None = None) -> dict[str, Any]:
    """Edit a position in place. Only the fields passed are touched.

    Deliberately NOT add_position(): that one stamps `opened_at` to today and
    drops the symbol from the watchlist, both of which are wrong when you are
    only correcting a price you typed from memory. The entry price marked from
    Daily Insight is the previous close, which is almost never your fill.

    `None` means "leave alone", so clearing a price needs an explicit -1 rather
    than an omitted field — the alternative is that every partial edit silently
    wipes qty.
    """
    sym = symbol.strip().upper()
    side = side.strip().upper()
    with _lock:
        s = _read()
        found = False
        for p in s["positions"]:
            if p.get("symbol") != sym or p.get("side") != side:
                continue
            found = True
            if entry_price is not None:
                p["entry_price"] = None if entry_price < 0 else float(entry_price)
            if qty is not None:
                p["qty"] = None if qty < 0 else float(qty)
            if note is not None:
                p["note"] = note.strip()
            if opened_at is not None:
                p["opened_at"] = opened_at.strip()
        if not found:
            raise ValueError(f"no open {side} position for {sym}")
        _write(s)
    return get_state()


def remove_position(symbol: str, side: str = "BUY") -> dict[str, Any]:
    sym = symbol.strip().upper()
    side = side.strip().upper()
    with _lock:
        s = _read()
        s["positions"] = [p for p in s["positions"]
                          if not (p.get("symbol") == sym and p.get("side") == side)]
        _write(s)
    return get_state()


def toggle_watch(symbol: str) -> dict[str, Any]:
    sym = symbol.strip().upper()
    if not sym:
        raise ValueError("symbol is required")
    with _lock:
        s = _read()
        s["watchlist"] = ([w for w in s["watchlist"] if w != sym]
                          if sym in s["watchlist"] else [*s["watchlist"], sym])
        _write(s)
    return get_state()


def held_symbols() -> set[str]:
    return {p.get("symbol") for p in get_state()["positions"] if p.get("symbol")}


def held_sectors() -> set[str]:
    return {p.get("sector_code") for p in get_state()["positions"] if p.get("sector_code")}
