"""Bản theo dõi hằng ngày: sổ của Tom + shortlist ứng viên.

**Đây là code, không phải prompt.** Skill `.claude/skills/theo-doi-hang-ngay/`
chỉ gọi `main.py --daily-watch` rồi đọc output — nó không chứa một dòng logic
phân tích nào. Tom, 2026-09-16: *"skill sẽ phải gắn với 1 folder code riêng thay
vì bắt AI gen lại code mỗi lần chạy; AI chỉ có trách nhiệm run schedule và tổng
hợp lại"*. Một phép phân tích được sinh lại mỗi lần chạy là một phép phân tích
khác nhau mỗi lần chạy, và hai kết quả không so được với nhau.

Hai nửa, tách bạch vì chúng trả lời hai câu hỏi khác nhau:
  - **Sổ** — lệnh đang mở còn hợp lệ không, có cái nào chạm stop chưa. Đây là
    phần khẩn; nó đứng đầu bản tin.
  - **Shortlist** — mã nào đáng xem. Đây là phần **tham khảo**: §26.9 đo được
    rằng chưa có luật xếp hạng nào thắng VNINDEX risk-adjusted, nên danh sách
    này là gợi ý cho người tự quyết định mua, không phải lệnh mua.

Không gửi email (Tom: *"tạm thời chưa cần nhận email, để sau"*). Task có lịch
ghi ra file; đọc bằng skill hoặc mở file.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config import BASE_DIR, HOLD_SESSIONS
from daily_watch import positions as position_tracking
from services import trading_state

log = logging.getLogger(__name__)

WATCH_JSON = Path(BASE_DIR) / "data" / "watch_latest.json"
WATCH_DIR = Path(BASE_DIR) / "report"

#: Kho lưu trữ để **audit về sau**. Một file một ngày, không ghi đè ngày khác.
#:
#: Đây là lỗ §26.1 đã ghi và chưa từng vá: *"Không có gì trong repo trả lời được
#: câu hỏi"* — không bảng nào lưu một pick, nên khi Tom hỏi picks có tốt không
#: thì phải viết `extract_past_picks.py` để bới 174 pick ra khỏi kho HTML báo
#: cáo. Lần này lưu có cấu trúc ngay từ đầu.
#:
#: **Kho tự chấm được theo thời gian**: mỗi ngày ghi cả khuyến nghị LẪN giá của
#: mọi mã nó nhắc tới, nên N ngày lưu trữ tự cho một chuỗi giá để đối chiếu
#: khuyến nghị cũ — không cần nguồn giá thứ hai, không cần panel cập nhật tay.
#:
#: Chạy lại trong ngày thì ghi đè ngày đó (bản 17:30 theo lịch là bản cuối).
#: `generated_ts` cho biết bản nào.
ARCHIVE_DIR = Path(BASE_DIR) / "data" / "watch"

#: Khung giữ: 4 và 8 tuần, và **cùng một danh sách mã cho cả hai** — hai khung
#: không cho hai danh sách khác nhau, chỉ khác thời gian giữ; dựng hai bảng
#: khác nhau sẽ là bịa. `config.HOLD_SESSIONS` (Tom 2026-09-25: "chỉ sử dụng 4
#: tuần và 8 tuần").
HORIZONS = HOLD_SESSIONS

#: Lợi nhuận/năm của LUẬT ĐANG CHẠY (cổng SMA200 → blend, top-5) như một danh
#: mục thật: staggered, 2023-01 → 2026-09, chi phí 1,00%/vòng, để tiền mặt khi
#: không có mã (review 2026-09-24 §2.1, §3.1). Đo in-sample — đây là trần của
#: phép đo, không phải lời hứa. Số cũ (5,9% / 11,7%) là quy năm số học của
#: %/lệnh, không phải danh mục, và thuộc về luật có ngưỡng 2,5 (danh mục thật:
#: 2,7% / 9,3%).
HORIZON_ANNUALISED = {20: 0.072, 40: 0.117}
HORIZON_SHARPE = {20: 0.44, 40: 0.65}

#: VNINDEX mua & giữ trên CÙNG các ngày đó — trần trung thực. Chưa luật nào
#: vượt nó, cả lợi nhuận lẫn Sharpe.
VNINDEX_CAGR, VNINDEX_SHARPE, VNINDEX_MAXDD = 0.175, 0.98, -0.181


def _shortlist(top_n: int) -> tuple[list[dict], dict[str, Any]]:
    """Ứng viên tốt nhất theo đúng luật production — `long_shortlist`.

    Dùng `.peek()` chứ không `get_snapshot()`: job có lịch chạy SAU pipeline
    hằng ngày nên cache đã ấm; nếu lạnh thì trả rỗng kèm cờ, chứ không đứng chờ
    2-10 phút sau throttle KBS (cái bẫy `api/routers/insight.py` ghi ở `/daily`).

    **Cùng một hàm** với trang Daily Insight và email 17:00 — không phải bản
    chép (review 2026-09-24 §2.4: ba bề mặt từng chạy ba luật mua khác nhau).
    Luật: cổng SMA200 (điểm trên sàn −20) → thứ tự blend điểm + OBV → top-N,
    bỏ mã anh đang nắm. Ngưỡng `MIN_BUY_SCORE` 2,5 đã bỏ 2026-09-25 (Tom: "bỏ
    ngay, giữ cổng SMA200"); danh sách nó LẼ RA cho ra vẫn được ghi vào
    `meta["shortlist_with_cutoff"]` để `daily_watch/audit.py` so hai luật trên
    dữ liệu chưa từng dùng để chọn luật.
    """
    meta: dict[str, Any] = {"as_of": None, "universe": 0, "cold_cache": False}
    try:
        from services.picks_scoring import MIN_BUY_SCORE
        from services.picks_universe_service import PicksUniverseService, long_shortlist
    except ImportError:
        log.exception("[watch] không import được picks layer")
        return [], meta

    snap = PicksUniverseService().peek()
    if not snap:
        meta["cold_cache"] = True
        return [], meta

    meta["as_of"] = str(snap.as_of)
    meta["universe"] = len(snap.tickers)
    held = trading_state.held_symbols()

    rows = long_shortlist(snap.tickers.values(), len(snap.tickers), exclude=held)
    shadow = long_shortlist(snap.tickers.values(), top_n, exclude=held,
                            min_score=MIN_BUY_SCORE)

    meta["qualified"] = len(rows)
    meta["rule"] = "cổng SMA200 → blend điểm + OBV"
    meta["excluded_held"] = sorted(held)
    meta["retired_min_buy_score"] = MIN_BUY_SCORE
    meta["shortlist_with_cutoff"] = [
        {"symbol": r.symbol, "close": r.close, "score": round(r.score, 2)}
        for r in shadow]
    # Giá đóng của CẢ universe, để kho tự chấm được mọi danh sách — kể cả base
    # rate NO GATE — mà không cần một mã phải được nhắc lại sau 20 phiên. Tiền
    # tố _ = nội bộ; build() gỡ nó khỏi meta trước khi ghi.
    meta["_universe_closes"] = {s: t.close for s, t in snap.tickers.items()
                                if getattr(t, "close", None)}
    return [{
        "symbol": r.symbol,
        "sector_code": r.sector_code,
        "close": r.close,
        "score": round(r.score, 2),
        "rank_score": round(r.rank_score, 4) if r.rank_score is not None else None,
        "stop": r.stop,
        "target": r.target,
        "rr": round(r.rr, 2) if r.rr is not None else None,
        "atr_pct": r.atr_pct,
        "ret_5d": r.ret_5d,
        "rsi_2": r.rsi_2,
        # Cửa sổ bán NẾU mua ở phiên giao dịch kế tiếp — cùng luật 20-40 phiên
        # mà sổ đang dùng, tính sẵn để khỏi phải nhẩm.
        **_window_if_bought(),
    } for r in rows[:top_n]], meta


def _window_if_bought() -> dict[str, str | None]:
    """Cửa sổ bán cho một lệnh mở ở phiên giao dịch kế tiếp.

    Cùng một hàm với thẻ Daily Insight (`picks_scoring.hold_window`) — hai chỗ
    tự đếm phiên là hai định nghĩa sẽ lệch (§22.11).
    """
    try:
        from services.picks_scoring import hold_window
        from utils.clock import today
        return hold_window(today())
    except ImportError:
        return {"sell_from": None, "sell_by": None}


def build(top_n: int = 5) -> dict[str, Any]:
    """Toàn bộ payload của bản theo dõi. Thuần dữ liệu — không in, không gửi."""
    book = position_tracking.mark_book()
    alerts = position_tracking.alerts(book)
    _attach_projection(book)
    picks, meta = _shortlist(top_n)
    universe_closes = meta.pop("_universe_closes", {})
    shadow = meta.pop("shortlist_with_cutoff", [])

    as_of = meta.get("as_of") or book.get("as_of")
    stale = 0
    if as_of:
        try:
            from utils.clock import sessions_between, to_market_date
            stale = sessions_between(to_market_date(as_of))
        except (ValueError, TypeError, ImportError):
            stale = 0

    return {
        "generated_at": date.today().isoformat(),
        "data_as_of": as_of,
        # Độ trễ đếm bằng PHIÊN, không bằng ngày: sáng thứ Hai mà dữ liệu là thứ
        # Sáu thì trễ 1 phiên, không phải 3 ngày, và không đáng cảnh báo.
        "stale_sessions": stale,
        "cold_cache": meta.get("cold_cache", False),
        "alerts": [{
            "symbol": a.get("symbol"),
            "kind": a.get("alert_kind"),
            "entry_price": a.get("entry_price"),
            "last": a.get("last"),
            "pnl_pct": a.get("pnl_pct"),
            "sell_range": a.get("sell_range"),
        } for a in alerts],
        "book": book,
        "shortlist": picks,
        # Luật cũ (ngưỡng 2,5), chỉ để audit: danh sách nó LẼ RA cho ra hôm nay.
        # Không in như một khuyến nghị — `daily_watch/audit.py` chấm cả hai.
        "shortlist_with_cutoff": shadow,
        # Giá đóng của mọi mã kho này nhắc tới, lưu lại để N ngày lưu trữ tự cho
        # một chuỗi giá — `daily_watch/audit.py` chấm khuyến nghị cũ bằng chính
        # các bản lưu sau nó, không cần nguồn giá thứ hai.
        "marks": {**universe_closes, **_marks(book, picks + shadow)},
        "shortlist_meta": meta,
        "horizons": list(HORIZONS),
    }


def _refresh_off_universe_holdings() -> dict[str, Any] | None:
    """Lấy giá cho mã đang nắm mà universe không có. Không bao giờ làm hỏng job."""
    from daily_watch import holdings
    try:
        from services.picks_universe_service import PicksUniverseService
        snap = PicksUniverseService().peek()
        universe = set(snap.tickers) if snap else set()
        positions = trading_state.get_state()["positions"]
        held = {p["symbol"] for p in positions}
        todo = holdings.missing(held, universe)
        if not todo:
            return None
        sectors = {p["symbol"]: p.get("sector_code", "") for p in positions}
        return holdings.refresh(todo, sectors)
    except Exception:  # noqa: BLE001 - thiếu giá một mã không được làm hỏng bản tin
        log.exception("[watch] refresh giá mã ngoài universe thất bại")
        return None


def _attach_projection(book: dict[str, Any]) -> None:
    """Gắn dự phóng biên độ + lịch cho từng vị thế.

    Mốc phiên lấy theo lịch CỦA TỪNG LỆNH, không phải một bộ mốc cố định: lệnh
    giữ 16 phiên thì "mở cửa sổ bán" là 4 phiên nữa, lệnh giữ 30 phiên thì đã
    qua. Một bảng mốc cố định sẽ in ra ngày vô nghĩa cho nửa số lệnh.
    """
    from daily_watch.sell_range import (HOLD_MAX_SESSIONS, HOLD_MIN_SESSIONS,
                                        projection)
    for p in book["positions"]:
        sr = p.get("sell_range") or {}
        held = sr.get("sessions_held")
        marks: dict[int, str] = {}
        sess = {1, 5}
        if held is not None:
            if (d := HOLD_MIN_SESSIONS - held) > 0:
                marks[d] = "mở cửa sổ bán"
                sess.add(d)
            if (d := HOLD_MAX_SESSIONS - held) > 0:
                marks[d] = "hết khung giữ"
                sess.add(d)
        p["projection"] = projection(p.get("last"), p.get("_atr_pct"),
                                     tuple(sorted(sess)), marks)


def _marks(book: dict[str, Any], picks: list[dict]) -> dict[str, float]:
    """Giá đóng của mọi mã xuất hiện trong bản tin hôm nay."""
    m: dict[str, float] = {}
    for p in book.get("positions", []):
        if p.get("last") is not None:
            m[p["symbol"]] = p["last"]
    for p in picks:
        if p.get("close") is not None:
            m[p["symbol"]] = p["close"]
    return m


def _fmt(v: Any, unit: str = "", nd: int = 2) -> str:
    return "—" if v is None else f"{v:,.{nd}f}{unit}"


def render(payload: dict[str, Any]) -> str:
    """Markdown cho người đọc. Skill tóm tắt từ đây hoặc từ JSON."""
    L: list[str] = []
    a = L.append

    a(f"# Theo dõi hằng ngày — {payload['generated_at']}")
    a("")
    a(f"Dữ liệu phiên **{payload['data_as_of'] or 'không rõ'}**"
      + (f"  ⚠️ **trễ {payload['stale_sessions']} phiên**"
         if payload.get("stale_sessions", 0) > 1 else ""))
    if payload["cold_cache"]:
        a("")
        a("> ⚠️ **Cache picks đang lạnh** — chưa quét được ứng viên. Chạy lại sau "
          "pipeline hằng ngày, hoặc bấm Refresh trên trang Daily Insight.")

    # --- 1. Cảnh báo: phần duy nhất đáng đánh thức người đọc -----------------
    a("")
    a("## 1. Cảnh báo")
    if not payload["alerts"]:
        a("")
        a("Không vị thế nào tới cửa sổ bán hay nhả quá sâu. Giữ.")
    _ICON = {"quá hạn": "🔴", "nhả quá sâu": "🟠", "trong cửa sổ bán": "🟡"}
    for al in payload["alerts"]:
        sr = al["sell_range"] or {}
        a("")
        a(f"### {_ICON.get(al['kind'], '•')} {al['symbol']} — {str(al['kind']).upper()}")
        a(f"- giá gần nhất {_fmt(al['last'])} · vào lệnh {_fmt(al['entry_price'])} "
          f"· P&L **{_fmt(al['pnl_pct'], '%')}**")
        a(f"- giữ {sr.get('sessions_held') or '—'} phiên · cửa sổ bán "
          f"**{sr.get('sell_from') or '—'} → {sr.get('sell_by') or '—'}**")
        a(f"- range tham chiếu **{_fmt(sr.get('band_lo'))} – {_fmt(sr.get('band_hi'))}** "
          f"(±1×ATR quanh đỉnh {_fmt(sr.get('peak'))}) · nhả quá sâu dưới "
          f"{_fmt(sr.get('give_back'))}")
        if sr.get("note"):
            a(f"- {sr['note']}")

    # --- 2. Sổ -------------------------------------------------------------
    b = payload["book"]
    a("")
    a("## 2. Sổ của anh")
    if not b["positions"]:
        a("")
        a("Sổ trống. Đánh dấu một lệnh ở trang Daily Insight (nút \"Đã vào lệnh\") "
          "hoặc `POST /api/state/positions`.")
    else:
        a("")
        a("| mã | vào | gần nhất | P&L | range bán (tham chiếu) | giá đang | cửa sổ bán |")
        a("|---|---|---|---|---|---|---|")
        for p in b["positions"]:
            sr = p.get("sell_range") or {}
            star = "" if sr.get("peak_basis") == "since_entry" else " *"
            a(f"| **{p.get('symbol')}** | {_fmt(p.get('entry_price'))} "
              f"| {_fmt(p.get('last'))} | {_fmt(p.get('pnl_pct'), '%')} "
              f"| {_fmt(sr.get('band_lo'))} – {_fmt(sr.get('band_hi'))}{star} "
              f"| {sr.get('band_status') or '—'} "
              f"| {sr.get('sell_from') or '—'} → {sr.get('sell_by') or '—'} |")
        no_date = [p.get("symbol") for p in b["positions"]
                   if (p.get("sell_range") or {}).get("peak_basis") != "since_entry"]
        if no_date:
            a("")
            a(f"> `*` **{', '.join(no_date)} chưa có ngày mua.** Thiếu hai thứ: "
              "**cửa sổ bán** — nó đếm phiên kể từ lúc vào lệnh nên không có gì thay "
              "thế được — và tin **\"nhả quá sâu\"**, vì không biết đỉnh ~30 phiên "
              "gần nhất có trước hay sau lúc anh mua. **Range giá vẫn dùng được**: "
              "nó neo ở đỉnh của thị trường chứ không phải đỉnh kể từ lúc anh vào lệnh.")
            a(">")
            a("> Một ngày mua **ước lượng là đủ** — cửa sổ rộng 20 phiên, lệch vài "
              "ngày gần như không đổi gì. `PATCH /api/state/positions/{symbol}` "
              "với `opened_at`.")
        off = [(p.get("symbol"), p.get("price_source")) for p in b["positions"]
               if p.get("price_source") and p["price_source"] != "snapshot"]
        if off:
            a("")
            a("> ℹ️ **Ngoài universe 54 mã, vẫn được theo dõi:** "
              + " · ".join(f"**{s}** ({src.replace('ngoài universe, ', '')})"
                           for s, src in off)
              + ". Universe là bộ lọc **mua**; một mã đã nằm trong tay phải được "
              "nhìn thấy dù nó còn đủ điều kiện để mua hay không.")
        no_px = [p.get("symbol") for p in b["positions"] if p.get("last") is None]
        if no_px:
            a("")
            a(f"> 🟠 **{', '.join(no_px)} không lấy được giá** — kể cả qua đường "
              "lấy riêng cho mã ngoài universe. Xem `data/holdings_prices.json` "
              "mục `failed` để biết lý do.")
        a("")
        a(f"Chấm được **{b['priced']}/{b['count']}** vị thế"
          + (f" · tổng P&L {_fmt(b['total_pnl_pct'], '%')}" if b["total_pnl_pct"] is not None else ""))
        a("")
        a("> Vị thế ở đây **không tự đóng**. Khi anh bán, bấm \"Đã bán\" hoặc "
          "`POST /api/state/positions/{symbol}/close` — cho tới lúc đó nó vẫn được "
          "theo dõi mỗi ngày.")

    # --- 3. Shortlist ------------------------------------------------------
    m = payload["shortlist_meta"]
    a("")
    a("## 3. Ứng viên")
    if not payload["shortlist"]:
        a("")
        a("Không mã nào trên SMA200 hôm nay (sau khi bỏ mã anh đang nắm). **Đó là "
          "câu trả lời, không phải lỗi.** Phần vốn định mua: đặt vào ETF theo chỉ "
          "số thay vì để tiền mặt — review 2026-09-24 §3.4 đo được cách đó tốt hơn "
          "ở mọi năm.")
    else:
        a("")
        # Cột stop/target CỐ Ý không in ở đây. Chúng là sản phẩm phụ của bộ lọc
        # sàng lọc (`is_valid_long_pick` đòi stop < entry để tính sàn R:R), không
        # phải mức bán — và từ 2026-09-16 sổ không còn dùng stop. In chúng cạnh
        # một sổ không có stop là mời người đọc dùng chúng làm mức bán, đúng thứ
        # phép đo vừa bác (§26.10). ATR% thì có ích thật: nó quyết định range bán
        # rộng bao nhiêu sau khi mua.
        a("| # | mã | ngành | giá | điểm | ATR%/phiên | nếu mua, cửa sổ bán |")
        a("|---|---|---|---|---|---|---|")
        for i, p in enumerate(payload["shortlist"], 1):
            a(f"| {i} | **{p['symbol']}** | {p['sector_code']} | {_fmt(p['close'])} "
              f"| {p['score']} | {_fmt(p.get('atr_pct'), '%')} "
              f"| {p.get('sell_from') or '—'} → {p.get('sell_by') or '—'} |")
        a("")
        a(f"Lọc từ {m.get('universe', 0)} mã · {m.get('qualified', 0)} mã trên SMA200"
          + (f" · đã loại {len(m.get('excluded_held') or [])} mã anh đang nắm"
             if m.get("excluded_held") else ""))
    shadow = payload.get("shortlist_with_cutoff") or []
    if shadow != [] or payload["shortlist"]:
        a("")
        a("<sub>So sánh, **không phải khuyến nghị**: luật cũ (điểm ≥ "
          f"{m.get('retired_min_buy_score', 2.5)}) hôm nay sẽ cho "
          + (", ".join(x["symbol"] for x in shadow) if shadow else "danh sách rỗng")
          + ". Ghi vào kho để `daily_watch/audit.py` so hai luật.</sub>")

    # --- 4. Các ngày tới ---------------------------------------------------
    a("")
    a("## 4. Các ngày tới")
    rows_p = [p for p in b["positions"] if p.get("projection")]
    if not rows_p:
        a("")
        a("Chưa đủ dữ liệu để dựng biên độ (thiếu ATR hoặc giá).")
    for p in rows_p:
        a("")
        a(f"**{p.get('symbol')}** — từ {_fmt(p.get('last'))}, ATR "
          f"{_fmt(p.get('_atr_pct'), '%')}/phiên")
        a("")
        a("| sau | ngày | biên độ ATR | rộng | mốc |")
        a("|---|---|---|---|---|")
        for r in p["projection"]:
            a(f"| {r['sessions']} phiên | {r['date']} | {_fmt(r['lo'])} – "
              f"{_fmt(r['hi'])} | ±{r['width_pct']}% | {r['mark'] or ''} |")
    a("")
    a("> **Đây là biên độ, không phải dự báo hướng.** Cột trên trả lời *\"mã này "
      "thường đi bao nhiêu trong n phiên\"*, giãn theo căn bậc hai số phiên — một "
      "tính chất của bước ngẫu nhiên, không phải một ý kiến về giá. Không rule nào "
      "trong hệ thống thắng VNINDEX risk-adjusted (§26.9), nên bất kỳ con số *\"giá "
      "sẽ là X\"* nào cũng là bịa, và bản tin này cố ý không in ra một con số như thế.")
    a(">")
    a("> ATR là biên độ **ngày**, không phải độ lệch chuẩn — đừng đọc ±% như một "
      "khoảng tin cậy và đừng suy ra xác suất từ nó.")

    # --- 5. Đọc thế nào ----------------------------------------------------
    lo, hi = HORIZONS
    a("")
    a("## 5. Đọc bảng trên thế nào")
    a("")
    a("- **Luật chọn:** cổng xu hướng (giá trên SMA200) → xếp theo blend hạng "
      "điểm + OBV → top-5. **Cùng một hàm** với Daily Insight và email 17:00. "
      "Ngưỡng điểm 2,5 đã bỏ ngày 2026-09-25: đo ra nó tốn ~0,4%/lệnh "
      "(review 2026-09-24 §2.2).")
    a(f"- **Giữ {lo}-{hi} phiên (4-8 tuần), mặc định tới ~{hi} phiên.** Phiên {lo} "
      "chỉ mở cửa sổ bán, không phải tín hiệu bán. Luật này như một danh mục thật "
      "(2023-01 → 2026-09, chi phí 1,00%/vòng, đo in-sample):")
    a("")
    a("  | giữ | lợi nhuận/năm | Sharpe | VNINDEX cùng kỳ |")
    a("  |---|---|---|---|")
    for h in HORIZONS:
        bold = "**" if h == hi else ""
        a(f"  | {bold}{h} phiên ({h // 5} tuần){bold} "
          f"| {bold}{HORIZON_ANNUALISED[h] * 100:+.1f}%{bold} "
          f"| {HORIZON_SHARPE[h]:.2f} "
          f"| {VNINDEX_CAGR * 100:+.1f}%, Sharpe {VNINDEX_SHARPE:.2f} |")
    a("")
    a(f"  Lợi nhuận tăng dốc tới ~{hi} phiên rồi đi ngang — giữ lâu hơn không "
      "thêm gì đo được (review §3.1).")
    a("- **Khớp lệnh:** mua ở phiên ATO phiên sau; khi thoát, bán ở phiên ATO — "
      "+0,06-0,09%/lệnh so với bán ATC (review §3.3).")
    a("- **Trần trung thực:** chưa luật nào thắng VNINDEX, cả lợi nhuận lẫn "
      "Sharpe. Đây là shortlist cho người đã quyết định tự chọn mã. Nếu mục tiêu "
      "là lợi nhuận trên rủi ro, cân nhắc mô hình lõi-vệ tinh: phần lớn vốn theo "
      "index, shortlist là phần vệ tinh.")
    a("- **\"Nhả quá sâu\" là tin về luận điểm, không phải lệnh bán.** Bán cơ học "
      "theo mức giá tốn 0,7-2,0 điểm %/năm so với giữ hết khung (review §3.2).")
    a("- **Xoay vòng là thuế:** chi phí ~12,6%/năm nếu giữ 4 tuần, ~6,3%/năm nếu "
      "giữ 8 tuần.")
    return "\n".join(L) + "\n"


def run(top_n: int = 5, write: bool = True) -> dict[str, Any]:
    """Dựng, ghi ra đĩa, trả payload. Đây là thứ `main.py --daily-watch` gọi.

    Đây là nơi DUY NHẤT gọi `holdings.refresh()` — nó gọi mạng. `build()` và
    `mark_book()` chỉ đọc cache, vì route API cũng đi qua chúng.
    """
    _refresh_off_universe_holdings()
    payload = build(top_n=top_n)
    payload["generated_ts"] = datetime.now().isoformat(timespec="seconds")
    if write:
        WATCH_DIR.mkdir(parents=True, exist_ok=True)
        WATCH_JSON.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(payload, ensure_ascii=False, indent=1, default=str)
        md = WATCH_DIR / f"watch_{payload['generated_at']}.md"
        arch = ARCHIVE_DIR / f"{payload['generated_at']}.json"
        md.write_text(render(payload), encoding="utf-8")
        WATCH_JSON.write_text(blob, encoding="utf-8")
        arch.write_text(blob, encoding="utf-8")
        payload["_written"] = [str(md), str(WATCH_JSON), str(arch)]
    return payload
