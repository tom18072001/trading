"""Chấm sổ vị thế theo giá gần nhất — dùng chung giữa API và job có lịch.

Trước 2026-09-16 toàn bộ phần này nằm trong `api/routers/state.py` dưới dạng
`_track()` + thân hàm `positions_pnl()`. Một job Task Scheduler **không gọi
được** hàm nằm trong một route: process scheduler không có HTTP client (cùng lý
do `trading_state` đọc thẳng đĩa — §22.10). Nên cảnh báo stop hằng ngày sẽ phải
viết lại logic "đã chạm stop chưa", và đó là hai định nghĩa sẽ lệch — §22.11 đã
ghi đúng bài học này cho bar breakout, §16.15 cho đơn vị ATR, và hôm nay
`analysis/bench.py` cho chi phí.

Route giờ gọi `mark_book()`; job cũng vậy.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# `SETTLEMENT_SESSIONS = 2` and the `sellable_on` date it produced were removed
# on 2026-09-25 with the T+ mode (Tom: "bỏ T+2, chỉ sử dụng 4 tuần và 8 tuần").
# At a 20-40 session hold "sellable from T+2" is never the binding date; the
# sell window (`sell_range.advise` -> sell_from / sell_by) is, and printing both
# invited reading the earlier one as permission to sell.


def track(p: dict, daily: list[dict], last: float | None) -> dict:
    """Mọi thứ sổ cần để trả lời "lệnh này còn hợp lệ không".

    `daily` là đuôi 30 phiên OHLCV mà PicksUniverseService vốn đã mang trên mỗi
    TickerRow và vốn đã lưu xuống đĩa — không thêm nguồn dữ liệu. Nó đặt khoá
    ngày là "time", phần còn lại của API gọi là "date", nên việc đổi tên xảy ra
    ở đây, một lần.

    `hit_stop` / `hit_target` là **ĐÃ TỪNG CHẠM kể từ khi MỨC ĐÓ có hiệu lực**,
    không phải "giá đóng hôm nay xuyên mức": một stop bị thủng hôm thứ Ba rồi
    hồi lại vào thứ Sáu vẫn là một stop đã bị thủng, và một cuốn sổ quên điều đó
    đang nói với anh rằng lệnh vẫn ổn.

    "Kể từ khi mức có hiệu lực", không phải "kể từ lúc vào lệnh" — đó là bản sửa
    2026-09-16. Một stop dời lên hôm nay chưa từng bị thủng bởi giá của hai tuần
    trước, vì lúc ấy nó chưa tồn tại. Phiên bản cũ chấm mức mới lên cả quá khứ và
    bắn cảnh báo giả trên đúng những lệnh đang thắng — thứ tệ hơn không cảnh báo,
    vì nó bảo người đọc bán một lệnh đang chạy tốt. `stop_set_at` mặc định None
    và rơi về `opened_at`, nên lệnh đặt stop ngay từ đầu không đổi hành vi.
    """
    from utils.clock import sessions_between, to_market_date

    stop, target = p.get("stop"), p.get("target")
    out: dict = {
        "path": [], "hit_stop": False, "hit_target": False,
        "dist_to_stop_pct": None, "dist_to_target_pct": None,
        "sessions_held": None,
    }

    opened = p.get("opened_at")
    if opened:
        try:
            d0 = to_market_date(opened)
            out["sessions_held"] = sessions_between(d0)
        except (ValueError, TypeError):
            pass   # một opened_at sửa tay không được làm 500 cả cuốn sổ

    for bar in daily:
        d = bar.get("time") or bar.get("date")
        if not d or (opened and str(d)[:10] < str(opened)[:10]):
            continue
        close = bar.get("close")
        if close is None:
            continue
        out["path"].append({"date": str(d)[:10], "close": float(close)})

    # ponytail: chỉ giá đóng — daily_prices có open/close/volume, không có
    # high/low, nên một cú xuyên trong phiên rồi đóng lại trên stop sẽ không được
    # ghi nhận. Mở rộng đuôi thành OHLC trong picks_universe_service nếu điều đó
    # quan trọng; với một sổ swing chấm theo giá đóng thì không.
    # "Đã từng chạm" phải tính từ ngày MỨC ĐÓ có hiệu lực, không phải từ ngày vào
    # lệnh. Một stop dời lên hôm nay chưa từng bị thủng bởi giá của hai tuần
    # trước — nó chưa tồn tại lúc ấy. Thiếu phân biệt này thì mọi lần trail stop
    # đều sinh một cảnh báo giả trên đúng những lệnh đang thắng.
    def _since(set_at: str | None) -> list[float]:
        frm = set_at or opened
        return [b["close"] for b in out["path"]
                if not frm or b["date"] >= str(frm)[:10]]

    if stop:
        c = _since(p.get("stop_set_at"))
        out["hit_stop"] = bool(c) and min(c) <= stop
    if target:
        c = _since(p.get("target_set_at"))
        out["hit_target"] = bool(c) and max(c) >= target

    if last:
        if stop:
            out["dist_to_stop_pct"] = (last / stop - 1) * 100
        if target:
            out["dist_to_target_pct"] = (target / last - 1) * 100
    return out


def _snapshot_prices() -> tuple[str | None, dict[str, float], dict[str, list],
                                dict[str, float], set[str]]:
    """Giá từ snapshot PicksUniverseService — `.peek()`, KHÔNG `get_snapshot()`.

    Cache lạnh phải trả về sổ với `last=None` trong vài mili-giây, không phải
    chặn hàng phút sau throttle 18 req/phút của KBS (cái bẫy
    `api/routers/insight.py` ghi ở handler `/daily`).
    """
    as_of, prices, paths, atrs = None, {}, {}, {}
    from_snapshot: set[str] = set()
    try:
        from services.picks_universe_service import PicksUniverseService
        snap = PicksUniverseService().peek()
        if snap:
            as_of = str(snap.as_of)
            prices = {s: t.close for s, t in snap.tickers.items() if getattr(t, "close", None)}
            paths = {s: (getattr(t, "daily_prices", None) or []) for s, t in snap.tickers.items()}
            atrs = {s: t.atr_pct for s, t in snap.tickers.items() if getattr(t, "atr_pct", None)}
            from_snapshot = set(prices)
    except Exception:  # noqa: BLE001 - tra giá không bao giờ được làm hỏng sổ
        log.exception("[position_tracking] tra giá thất bại; trả sổ chưa chấm")

    # Mã đang nắm nhưng nằm ngoài universe: đọc cache mà job đã làm đầy.
    # CHỈ ĐỌC ĐĨA — route cũng đi qua đây, và gọi mạng ở đây là mang cái treo
    # 2-10 phút sau throttle KBS quay lại (§22.6). Snapshot luôn thắng cache: nó
    # tươi hơn và là cùng một phép tính.
    from daily_watch import holdings
    for sym, r in (holdings.load().get("rows") or {}).items():
        if sym in prices or r.get("close") is None:
            continue
        prices[sym] = r["close"]
        paths[sym] = r.get("daily_prices") or []
        if r.get("atr_pct"):
            atrs[sym] = r["atr_pct"]
    # Tập mã lấy từ snapshot trả về RIÊNG, không suy ra bằng hiệu tập hợp: một mã
    # hôm qua ngoài universe (đã vào cache) mà hôm nay vào universe sẽ lấy giá từ
    # snapshot, và phép hiệu sẽ gán nhầm nó là "ngoài universe".
    return as_of, prices, paths, atrs, from_snapshot


def mark_book(positions: list[dict] | None = None) -> dict[str, Any]:
    """Sổ được chấm theo giá đóng gần nhất mà app đã biết.

    ponytail: giá đóng, không phải trong phiên, và **chưa trừ** phí + thuế bán
    0,1% của §18.2/10 — đây là bộ theo dõi vị thế, không phải cost model của
    backtest. `close_position()` mới là chỗ trừ chi phí, vì đó là nơi con số
    quyết định lãi/lỗ thật.
    """
    from daily_watch import sell_range
    from services import trading_state

    rows = trading_state.get_state()["positions"] if positions is None else positions
    as_of, prices, paths, atrs, snap_syms = _snapshot_prices()
    from daily_watch import holdings
    held_cache = holdings.load().get("rows") or {}

    out: list[dict] = []
    total_cost = total_value = 0.0
    for p in rows:
        sym = p.get("symbol", "")
        last = prices.get(sym)
        entry, qty = p.get("entry_price"), p.get("qty")
        tr = track(p, paths.get(sym) or [], last)
        cached = held_cache.get(sym)
        price_source = ("snapshot" if sym in snap_syms
                        else f"ngoài universe, giá phiên {cached.get('as_of')}" if cached
                        else None)
        row = {**p, "last": last, "pnl_pct": None, "pnl_vnd": None, "value": None,
               "price_source": price_source, **tr}
        # Khuyến nghị bán thay cho stop-loss (Tom, 2026-09-16). Cửa sổ thời gian
        # là luật đo được; range giá là tham chiếu — xem daily_watch/sell_range.py.
        row["sell_range"] = sell_range.advise(p, tr["path"], atrs.get(sym), last)
        row["_atr_pct"] = atrs.get(sym)   # dùng cho dự phóng; tiền tố _ = nội bộ
        if last and entry:
            # Một mark SELL là vị thế bán khống theo ngôn ngữ của sổ; tiền mặt VN
            # không short được (§18.2/12) nên thực chất nó là "tôi đã thoát" —
            # vẫn gán dấu để con số mang cùng một nghĩa ở cả hai phía.
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
        # Bao nhiêu phần của sổ thực sự đo được — một P&L tính trên 2 trong 9 vị
        # thế không được đọc như P&L của cả sổ.
        "priced": sum(1 for r in out if r["pnl_pct"] is not None),
        "count": len(out),
    }


#: Thứ tự khẩn cấp của cảnh báo. Chỉ ba loại — thêm loại thứ tư là bắt người đọc
#: phân loại thay vì hành động.
_URGENCY = {"quá hạn": 0, "nhả quá sâu": 1, "trong cửa sổ bán": 2}


def alerts(book: dict[str, Any] | None = None) -> list[dict]:
    """Vị thế cần Tom quyết định hôm nay.

    **Không còn cảnh báo stop-loss** (bỏ 2026-09-16). Đo trên 3.446 lệnh: mọi
    luật thoát bằng mức giá — kể cả băng neo ở đỉnh — đều thua việc giữ hết
    khung, và càng chặt càng tệ, đơn điệu. Nên thứ đáng đánh thức người đọc là
    **hết khung giữ**, không phải giá chạm một mức nào đó.

    `nhả quá sâu` vẫn được báo vì nó là tin tức về *luận điểm* ("sóng lên đã
    kết thúc"), không phải một lệnh bán cơ học — và nó dùng mức ít tốn nhất
    trong các băng đo được, chứ không phải mức tốt nhất, vì không có mức nào tốt.
    """
    b = book or mark_book()
    out = []
    for r in b["positions"]:
        sr = r.get("sell_range") or {}
        phase = sr.get("phase")
        kind = None
        if phase == "quá hạn":
            kind = "quá hạn"
        elif (sr.get("armed") and r.get("last") and sr.get("give_back")
              and r["last"] <= sr["give_back"]):
            # Chỉ khi ĐÃ ARM — xem sell_range.ARM_ATR. Không có điều kiện này thì
            # đây là cảnh báo stop-loss trên lệnh đang lỗ, thứ Tom đã bỏ.
            kind = "nhả quá sâu"
        elif phase == "trong cửa sổ bán":
            kind = "trong cửa sổ bán"
        if kind:
            out.append({**r, "alert_kind": kind})
    return sorted(out, key=lambda r: _URGENCY.get(r["alert_kind"], 9))


def breaches(book: dict[str, Any] | None = None) -> list[dict]:
    """Tên cũ, giữ lại cho caller cũ. Dùng `alerts()`."""
    return alerts(book)
