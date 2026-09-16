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
from datetime import date
from pathlib import Path
from typing import Any

from config import BASE_DIR
from services import position_tracking, trading_state

log = logging.getLogger(__name__)

WATCH_JSON = Path(BASE_DIR) / "data" / "watch_latest.json"
WATCH_DIR = Path(BASE_DIR) / "report"

#: Khung giữ được trình bày, và **cùng một danh sách mã cho cả hai** — đây là
#: kết quả đo, không phải lười. Quét 41 factor ở 4 khung
#: (`ticker_alpha_bench.py --horizons 10,20,40,60 --verdict`, 2026-09-16):
#:
#:     10 phiên  không factor nào qua 2 tiêu chí bắt buộc
#:     20 phiên  X_prop_obv   +5,9%/năm   excess +0,49%/lệnh
#:     40 phiên  X_prop_obv  +11,7%/năm   excess +0,77%/lệnh   <- tốt nhất
#:     60 phiên  không factor nào qua
#:
#: Cùng một factor thắng ở 20 và 40, nên hai khung KHÔNG cho hai danh sách khác
#: nhau — chỉ khác thời gian giữ. Dựng ra hai bảng khác nhau sẽ là bịa.
#: Khoảng dùng được hẹp: dưới 20 và trên 40 đều không có gì sống sót.
HORIZONS = (20, 40)

#: Quy năm đo được ở mỗi khung, để bản tin nói bằng tiền chứ không bằng %/lệnh.
HORIZON_ANNUALISED = {20: 0.059, 40: 0.117}


def _shortlist(top_n: int) -> tuple[list[dict], dict[str, Any]]:
    """Ứng viên tốt nhất theo đúng thứ tự production đang dùng.

    Dùng `.peek()` chứ không `get_snapshot()`: job có lịch chạy SAU pipeline
    hằng ngày nên cache đã ấm; nếu lạnh thì trả rỗng kèm cờ, chứ không đứng chờ
    2-10 phút sau throttle KBS (cái bẫy `api/routers/insight.py` ghi ở `/daily`).

    Thứ tự là `_rank_key` — **cùng một hàm** trang Daily Insight dùng, không
    phải một bản chép. Nó mới là thứ được đo ở §26.9 (`X_prop_obv`, factor duy
    nhất trong 41 cái qua được hai tiêu chí bắt buộc).
    """
    meta: dict[str, Any] = {"as_of": None, "universe": 0, "cold_cache": False}
    try:
        from services.picks_scoring import MIN_BUY_SCORE
        from services.picks_universe_service import PicksUniverseService, _rank_key
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

    rows = [r for r in snap.tickers.values()
            if r.is_valid_buy and r.score >= MIN_BUY_SCORE and r.symbol not in held]
    rows.sort(key=_rank_key)

    meta["qualified"] = len(rows)
    meta["min_buy_score"] = MIN_BUY_SCORE
    meta["excluded_held"] = sorted(held)
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
    """Cửa sổ bán cho một lệnh mở ở phiên giao dịch kế tiếp."""
    try:
        from services.sell_range import HOLD_MAX_SESSIONS, HOLD_MIN_SESSIONS
        from utils.clock import next_trading_day, today
        d0 = next_trading_day(today(), 1)
        return {"sell_from": next_trading_day(d0, HOLD_MIN_SESSIONS).isoformat(),
                "sell_by": next_trading_day(d0, HOLD_MAX_SESSIONS).isoformat()}
    except (ValueError, TypeError, ImportError):
        return {"sell_from": None, "sell_by": None}


def build(top_n: int = 5) -> dict[str, Any]:
    """Toàn bộ payload của bản theo dõi. Thuần dữ liệu — không in, không gửi."""
    book = position_tracking.mark_book()
    alerts = position_tracking.alerts(book)
    _attach_projection(book)
    picks, meta = _shortlist(top_n)

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
        "shortlist_meta": meta,
        "horizons": list(HORIZONS),
    }


def _attach_projection(book: dict[str, Any]) -> None:
    """Gắn dự phóng biên độ + lịch cho từng vị thế.

    Mốc phiên lấy theo lịch CỦA TỪNG LỆNH, không phải một bộ mốc cố định: lệnh
    giữ 16 phiên thì "mở cửa sổ bán" là 4 phiên nữa, lệnh giữ 30 phiên thì đã
    qua. Một bảng mốc cố định sẽ in ra ngày vô nghĩa cho nửa số lệnh.
    """
    from services.sell_range import (HOLD_MAX_SESSIONS, HOLD_MIN_SESSIONS,
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
        a("| mã | vào | gần nhất | P&L | phiên | range bán (tham chiếu) | cửa sổ bán |")
        a("|---|---|---|---|---|---|---|")
        for p in b["positions"]:
            sr = p.get("sell_range") or {}
            a(f"| **{p.get('symbol')}** | {_fmt(p.get('entry_price'))} "
              f"| {_fmt(p.get('last'))} | {_fmt(p.get('pnl_pct'), '%')} "
              f"| {sr.get('sessions_held') or '—'} "
              f"| {_fmt(sr.get('band_lo'))} – {_fmt(sr.get('band_hi'))} "
              f"| {sr.get('sell_from') or '—'} → {sr.get('sell_by') or '—'} |")
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
        a("Không mã nào qua ngưỡng hôm nay. **Đó là câu trả lời, không phải lỗi** — "
          "danh sách được phép ngắn, và rỗng khi cả bảng đang quá mua (§26.4).")
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
        a(f"Lọc từ {m.get('universe', 0)} mã · {m.get('qualified', 0)} mã qua ngưỡng "
          f"điểm ≥ {m.get('min_buy_score', '—')}"
          + (f" · đã loại {len(m.get('excluded_held') or [])} mã anh đang nắm"
             if m.get("excluded_held") else ""))

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
    a("")
    a("## 5. Đọc bảng trên thế nào")
    a("")
    a("- **Giữ 8 tuần đáng gấp đôi giữ 4 tuần.** Quét 41 factor ở 4 khung:")
    a("")
    a("  | giữ | factor sống sót | quy năm |")
    a("  |---|---|---|")
    a("  | 10 phiên (2 tuần) | *không cái nào* | — |")
    a("  | 20 phiên (4 tuần) | `X_prop_obv` | +5,9% |")
    a("  | **40 phiên (8 tuần)** | `X_prop_obv` | **+11,7%** |")
    a("  | 60 phiên (12 tuần) | *không cái nào* | — |")
    a("")
    a("  **Cùng một factor thắng ở cả 20 và 40**, nên bảng ứng viên ở trên dùng "
      "được cho cả hai khung — không có \"danh sách 4 tuần\" và \"danh sách 8 "
      "tuần\" riêng, chỉ có thời gian giữ khác nhau. Dưới 20 và trên 40 phiên "
      "thì không factor nào sống sót, nên khoảng dùng được là **20-40 phiên**.")
    a("- **Stop/target in ra là hình học SWING** (2,5×ATR / 1,8×ATR) — chỉnh cho "
      "khung 20 phiên. Giữ tới 40 phiên thì target thường đã chạm trước đó; "
      "hình học cho 8 tuần **chưa được dựng**, đừng coi cột stop/target là đã "
      "hiệu chỉnh cho khung dài. Đây **không phải** lệnh T+3: đóng nó trên đồng "
      "hồ T+3 biến cuộc đua 15%-vs-50% thành 4%-vs-24% (§26.3).")
    a("- **Thứ tự** dùng đúng hàm production (`_rank_key`) — điểm quyết định được "
      "vào danh sách, blend rank (score + OBV) quyết định thứ tự (§26.9).")
    a("- **Trần trung thực:** VNINDEX buy-and-hold +15,7%/năm, Sharpe 0,91. Cấu "
      "hình tốt nhất đo được ≈ +5,9%/năm ở chi phí đúng 1,00%/vòng. **Chưa luật "
      "nào thắng index risk-adjusted** — đây là shortlist cho người đã quyết định "
      "tự chọn mã, không phải lý do chọn mã thay vì mua index (§26.9).")
    a("- **Xoay vòng là thuế.** T+3 tốn 84%/năm chi phí; 4 tuần tốn 12,6%; 8 tuần "
      "6,3%. Giữ lâu hơn đáng giá hơn mọi cải tiến thuật toán đo được (§26.6).")
    return "\n".join(L) + "\n"


def run(top_n: int = 5, write: bool = True) -> dict[str, Any]:
    """Dựng, ghi ra đĩa, trả payload. Đây là thứ `main.py --daily-watch` gọi."""
    payload = build(top_n=top_n)
    if write:
        WATCH_DIR.mkdir(parents=True, exist_ok=True)
        WATCH_JSON.parent.mkdir(parents=True, exist_ok=True)
        md = WATCH_DIR / f"watch_{payload['generated_at']}.md"
        md.write_text(render(payload), encoding="utf-8")
        WATCH_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                                         default=str), encoding="utf-8")
        payload["_written"] = [str(md), str(WATCH_JSON)]
    return payload
