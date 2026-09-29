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
  closed     (2026-08-24) Exits, with realised P&L net of the §18.2/10 costs.
             Until this existed the only verb was remove_position(), i.e. a
             sale was indistinguishable from a mis-click, and the system could
             not answer whether its own picks made money.

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
    "closed": [],           # same shape + {exit_price, closed_at, pnl_vnd, pnl_pct, fees_vnd}
    "watchlist": [],        # [symbol]
}

#: Fields a position row gained after rows had already been written. Merged on
#: read (see _read) instead of migrated — same reason `closed` was: this is one
#: JSON file for one operator, and a missing key is indistinguishable from a
#: null one once it is filled.
# stop_set_at / target_set_at (2026-09-16): NGÀY mức đó bắt đầu có hiệu lực.
# Thiếu nó thì `hit_stop` ("đã từng chạm kể từ lúc vào lệnh") sẽ chấm một mức
# vừa đặt hôm nay lên cả quãng giá TRƯỚC khi nó tồn tại — back-painting, đúng
# họ lỗi §25.3. Nó nổ thật ngay lần đầu dùng: một lệnh đang lãi, giá trên stop, mà bản
# tin báo ĐÃ CHẠM STOP chỉ vì hai tuần trước giá từng xuống dưới mức vừa đặt.
# None = rơi về `opened_at`, nên mọi dòng ghi trước hôm nay vẫn đúng: mức của
# chúng quả thật có hiệu lực từ lúc mở lệnh.
_POSITION_DEFAULT: dict[str, Any] = {"stop": None, "target": None, "thesis": "",
                                     "stop_set_at": None, "target_set_at": None,
                                     # 2026-09-29: each buy that built the position
                                     # ({price, qty, date}); empty = one lot, the row.
                                     "lots": []}

_lock = threading.Lock()


def _today_str() -> str:
    """Hôm nay theo giờ thị trường — utils.clock là định nghĩa duy nhất (§20.2 P1-6)."""
    from utils.clock import today
    return today().isoformat()


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
    s = {**_DEFAULT, **raw}
    # _DEFAULT merges at the top level only, so a row written before stop /
    # target existed has no such key at all — and `{**p}` then ships a JSON
    # object the TS `Position` type says cannot exist. Fill per row, so every
    # reader sees one shape and "not set" is null rather than absent.
    for key in ("positions", "closed"):
        s[key] = [{**_POSITION_DEFAULT, **p} for p in s[key]]
    return s


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
                 note: str = "", stop: float | None = None,
                 target: float | None = None, thesis: str = "",
                 opened_at: str | None = None) -> dict[str, Any]:
    """Idempotent on (symbol, side): re-marking a pick updates it, not duplicates.

    `stop` / `target` / `thesis` are the recommendation the pick was made on.
    They were computed (services/picks_scoring.compute_stop_target_rr), carried
    into the PickEntry and rendered on the card — and then dropped at the one
    line that marked the position, so the book could not answer "is this trade
    still valid" the day after. They are stored now.
    """
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
        "stop": float(stop) if stop is not None else None,
        "target": float(target) if target is not None else None,
        "thesis": thesis.strip(),
        # Mở lệnh: mức có hiệu lực ngay từ đầu, nên None là đúng (track() rơi về
        # opened_at). Chỉ khi SỬA mức mới cần đóng dấu ngày.
        "stop_set_at": None,
        "target_set_at": None,
        # `opened_at` quyết định cửa sổ bán 20-40 phiên, nên đóng dấu hôm nay cho
        # một lệnh đã mua từ lâu là **bịa một ngày**: cửa sổ sẽ nói "mở sau 20
        # phiên" cho một vị thế đáng lẽ đã tới hạn. Nhận ngày thật nếu caller
        # biết; chuỗi rỗng = "không biết", và `sell_range.advise()` để cửa sổ là
        # None thay vì đoán.
        "opened_at": today_str() if opened_at is None else (opened_at.strip() or None),
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
                    note: str | None = None, opened_at: str | None = None,
                    stop: float | None = None,
                    target: float | None = None,
                    thesis: str | None = None) -> dict[str, Any]:
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
            # Sửa một mức là đặt một mức MỚI, và nó chỉ có hiệu lực từ hôm nay.
            # Đóng dấu ngày, nếu không `hit_stop` sẽ chấm nó lên quá khứ.
            if stop is not None:
                new_stop = None if stop < 0 else float(stop)
                if new_stop != p.get("stop"):
                    p["stop_set_at"] = _today_str()
                p["stop"] = new_stop
            if target is not None:
                new_target = None if target < 0 else float(target)
                if new_target != p.get("target"):
                    p["target_set_at"] = _today_str()
                p["target"] = new_target
            if note is not None:
                p["note"] = note.strip()
            # thesis được thêm 2026-09-16: trước đó nó chỉ ghi được lúc MỞ lệnh
            # và không sửa được ở đâu cả — mà luận điểm là đúng thứ phải sửa khi
            # lệnh tiến triển (vào lệnh rồi, giờ sát target). Một trường viết-một-lần
            # rồi cũ đi là một trường sẽ nói dối. Cùng lỗi §22.10 đã ghi cho giá
            # vào lệnh: đánh dấu được nhưng không sửa được.
            if thesis is not None:
                p["thesis"] = thesis.strip()
            if opened_at is not None:
                # Chuỗi rỗng = xoá về "không biết", cùng quy ước với số âm ở các
                # trường giá. Không có nó thì một ngày đã đóng dấu nhầm là vĩnh viễn.
                p["opened_at"] = opened_at.strip() or None
        if not found:
            raise ValueError(f"no open {side} position for {sym}")
        _write(s)
    return get_state()


def _realise(row: dict[str, Any], side: str, *, exit_price: float, qty: float | None,
             closed_at: str, note: str | None) -> dict[str, Any]:
    """The `closed` record for selling `qty` of `row` at `exit_price`, net of costs.

    Costs are the §18.2/10 figures the backtest already uses (BACKTEST_FEE_BPS
    per side, BACKTEST_SELL_TAX_BPS on proceeds), imported rather than retyped:
    a book that reports a gross number the backtest would call a loss is worse
    than no book. On a round trip that is ~0.40% of notional, which routinely
    decides whether a small win is a win. P&L is against the AVERAGE cost.
    """
    from config import BACKTEST_FEE_BPS, BACKTEST_SELL_TAX_BPS

    entry = row.get("entry_price")
    direction = 1 if side == "BUY" else -1
    closed = {**row, "qty": qty, "exit_price": exit_price, "closed_at": closed_at,
              "pnl_pct": None, "pnl_vnd": None, "fees_vnd": None}
    if note is not None:
        closed["note"] = note.strip()
    if entry:
        gross_pct = direction * (exit_price / entry - 1) * 100
        # Cost in percent terms is independent of size, so a position with
        # no qty still gets an honest net figure.
        cost_pct = (2 * BACKTEST_FEE_BPS + BACKTEST_SELL_TAX_BPS) / 100
        closed["pnl_pct"] = gross_pct - cost_pct
        if qty:
            fees = ((entry + exit_price) * qty * BACKTEST_FEE_BPS / 10_000
                    + exit_price * qty * BACKTEST_SELL_TAX_BPS / 10_000)
            closed["fees_vnd"] = fees
            closed["pnl_vnd"] = direction * (exit_price - entry) * qty - fees
    return closed


def close_position(symbol: str, side: str = "BUY", *,
                   exit_price: float, closed_at: str | None = None,
                   note: str | None = None, qty: float | None = None) -> dict[str, Any]:
    """Book an exit: all of it, or `qty` of it (2026-09-29, Tom: *"khi tôi bán tôi
    sẽ báo bạn"* -- a sale is not always the whole position).

    Deliberately NOT remove_position(). That one deletes, which is right for
    "I mis-clicked" and wrong for "I sold" — deleting a closed trade throws away
    the only record of whether the system's picks made money, which is the whole
    reason to track a book.

    A partial sale writes a `closed` row for the part sold (`partial: True`) and
    leaves the rest open at the same average cost and the same buy date: selling
    some does not restart the position's review clock.
    """
    sym = symbol.strip().upper()
    side = side.strip().upper()
    exit_price = float(exit_price)
    if exit_price <= 0:
        raise ValueError("exit_price must be positive")
    if qty is not None:
        qty = float(qty)
        if qty <= 0:
            raise ValueError("qty must be positive")

    with _lock:
        s = _read()
        row = next((p for p in s["positions"]
                    if p.get("symbol") == sym and p.get("side") == side), None)
        if row is None:
            raise ValueError(f"no open {side} position for {sym}")
        held = row.get("qty")
        partial = False
        if qty is not None:
            if held is None:
                raise ValueError(f"{sym} has no qty on record -- set it before a partial sale")
            if qty > held + 1e-9:
                raise ValueError(f"cannot sell {qty:g} of {sym}: only {held:g} held")
            partial = qty < held - 1e-9
        closed = _realise(row, side, exit_price=exit_price,
                          qty=qty if partial else held,
                          closed_at=(closed_at or today_str()).strip(), note=note)
        if partial:
            closed["partial"] = True
            row["qty"] = held - qty
        else:
            s["positions"] = [p for p in s["positions"]
                              if not (p.get("symbol") == sym and p.get("side") == side)]
        s["closed"] = [*s["closed"], closed]
        _write(s)
    log.info("[state] closed %s %s %s @ %s", side, sym, "part" if partial else "all", exit_price)
    return get_state()


def record_buy(symbol: str, price: float, qty: float, *, bought_at: str | None = None,
               sector_code: str = "", note: str = "") -> dict[str, Any]:
    """Tom báo đã mua (2026-09-29): *"tôi sẽ báo bạn tôi mua con nào giá thế nào"*.

    Unlike `add_position` (the Daily Insight "Đã vào lệnh" button, idempotent:
    marking twice updates the row), a second buy of a name already held ADDS to
    it: quantities sum and the entry becomes the quantity-weighted average cost,
    the way a VN broker shows "giá vốn bình quân". `add_position` would have
    overwritten the first fill's price and quantity with the second's.

    The position keeps the date of its FIRST buy -- that is its review clock.
    A position whose date was never known stays undated rather than taking the
    new lot's date: that would invent a date for the earlier shares.
    """
    sym = symbol.strip().upper()
    if not sym:
        raise ValueError("symbol is required")
    price, qty = float(price), float(qty)
    if price <= 0 or qty <= 0:
        raise ValueError("price and qty must be positive")
    day = (bought_at or today_str()).strip()
    lot = {"price": price, "qty": qty, "date": day}
    with _lock:
        s = _read()
        row = next((p for p in s["positions"]
                    if p.get("symbol") == sym and p.get("side") == "BUY"), None)
        if row is None:
            s["positions"] = [*s["positions"], {
                **_POSITION_DEFAULT, "symbol": sym, "sector_code": sector_code.strip().upper(),
                "side": "BUY", "entry_price": price, "qty": qty, "note": note.strip(),
                "opened_at": day, "lots": [lot]}]
        else:
            old_p, old_q = row.get("entry_price"), row.get("qty")
            if not old_p or not old_q:
                raise ValueError(f"{sym} is held without a price or qty -- fix it with "
                                 "update_position before adding to it")
            lots = row.get("lots") or [{"price": old_p, "qty": old_q,
                                        "date": row.get("opened_at")}]
            row["entry_price"] = (old_p * old_q + price * qty) / (old_q + qty)
            row["qty"] = old_q + qty
            row["lots"] = [*lots, lot]
            if note:
                row["note"] = note.strip()
        s["watchlist"] = [w for w in s["watchlist"] if w != sym]
        _write(s)
    log.info("[state] bought %s %g @ %s", sym, qty, price)
    return get_state()


def realised_pnl() -> dict[str, Any]:
    """Totals over `closed`. Net of §18.2/10 costs, because close_position is."""
    rows = get_state()["closed"]
    with_vnd = [r for r in rows if r.get("pnl_vnd") is not None]
    with_pct = [r for r in rows if r.get("pnl_pct") is not None]
    wins = [r for r in with_pct if r["pnl_pct"] > 0]
    return {
        "count": len(rows),
        # Same discipline as the unrealised endpoint: a total over 2 of 9 trades
        # is not the book's total, so say how many carried a number.
        "priced": len(with_vnd),
        # `or None` would be wrong here: a book that broke exactly even is not
        # a book with no number.
        "total_pnl_vnd": sum(r["pnl_vnd"] for r in with_vnd) if with_vnd else None,
        "total_fees_vnd": sum(r.get("fees_vnd") or 0 for r in with_vnd) if with_vnd else None,
        "avg_pnl_pct": (sum(r["pnl_pct"] for r in with_pct) / len(with_pct)
                        if with_pct else None),
        "win_rate": (len(wins) / len(with_pct)) if with_pct else None,
        "trades": rows,
    }


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
