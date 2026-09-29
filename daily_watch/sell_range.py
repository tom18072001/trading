"""Khuyến nghị bán cho từng vị thế: **lịch xem lại** (luật) và **range giá** (tham chiếu).

## Luật — từ 2026-09-29, đo trong docs/reviews/WORKFLOW_STUDY_2026-09-29.md

Tom mua vào ngày của anh ấy, không theo một sổ 8 mã đồng bộ, nên mỗi vị thế có
**đồng hồ riêng, tính từ ngày mua**: xem lại ở phiên thứ 20, 40, 60… Đến kỳ mà
mã nằm ngoài top 16 của thứ tự động lượng thì bán ATO phiên kế; còn trong top
16 thì giữ tới kỳ sau, không giới hạn số phiên. `verdict()` là nơi duy nhất nói
GIỮ / BÁN.

Bảy biến thể, đăng ký trước, sổ 8 chỗ, DEV 2019-07 → 2025-09 (`exits.py`):

    xem lại mỗi 20 phiên, giữ khi còn top 16   33,0%/năm   <- luật này
    kiểm hạng mỗi ngày                          30,6%
    bán cứng ở phiên 40                         26,5%   <- cảnh báo "quá hạn" cũ
    chốt lời +20% / +30% so với giá mua         25,1% / 27,7%
    cắt lỗ −10% / −15% so với giá mua           35,4% / 32,5%

Không biến thể nào qua ngưỡng đăng ký trước (+1 điểm/năm, Sharpe không thấp
hơn, không tệ hơn ở ≥ 4/6 năm). Cắt lỗ −10% cao hơn nhưng tệ hơn ở 3/6 năm và
mức −15% không giúp — không đưa vào luật. **Giá mua không quyết định bán**; nó
được in ra để anh biết mình lời lỗ bao nhiêu.

Cửa sổ 20-40 phiên + "quá hạn" + "nhả quá sâu" là luật của thứ tự CŨ (quá bán
1-3 ngày, 2026-09-16). Với luật động lượng, bán cứng ở phiên 40 mất ~6,5
điểm/năm, nên cả ba đã bỏ khỏi phần luật.

## Tham chiếu, không phải luật

`band_lo` / `band_hi` — ±1×ATR quanh đỉnh đã đạt (Tom 2026-09-16: *"phải đưa
khuyến nghị range bán"*). Nó trả lời "giá đang ở đâu so với nhịp thường của
chính mã này", để anh chọn giá khi bán — không trả lời "có bán không".
"""
from __future__ import annotations

from datetime import date
from typing import Any

from config import HOLD_SESSIONS

#: 4 và 8 tuần — config.HOLD_SESSIONS. Nay là hai kỳ xem lại đầu tiên; kỳ sau
#: cứ thêm REVIEW phiên.
HOLD_MIN_SESSIONS, HOLD_MAX_SESSIONS = HOLD_SESSIONS

#: Range tham chiếu: ±1 ATR quanh ĐỈNH đã đạt. Một ATR là "một nhịp thường của
#: chính mã đó". Nó **không** là luật thoát.
BAND_ATR = 1.0


def _review() -> int:
    from services.buy_layer import REVIEW_SESSIONS
    return REVIEW_SESSIONS


def _keep() -> int:
    from services.buy_layer import KEEP_TOP
    return KEEP_TOP


def _atr_frac(atr_pct: float | None) -> float | None:
    """`atr_pct` đi lẫn lộn hai đơn vị trong repo — chuẩn hoá về phân số.

    `TickerRow.atr_pct` là phần trăm (3.13 = 3,13%); `sector_flow_daily.atr_pct`
    là phân số (0.0313). Cùng tên, hai đơn vị — đúng thứ đã gây ra §16.15.
    """
    if atr_pct is None or atr_pct <= 0:
        return None
    return atr_pct / 100.0 if atr_pct >= 0.5 else float(atr_pct)


def schedule(opened_at: Any, today_: date | None = None) -> dict[str, Any]:
    """Lịch xem lại của một vị thế, đếm PHIÊN kể từ ngày mua.

    Kỳ k: quyết định bằng giá đóng phiên thứ 20k−1 sau ngày mua (`decide_k`),
    bán ATO phiên thứ 20k (`review_k`) — đúng như mô phỏng: vào ở giá mở phiên
    e, chấm hạng ở giá đóng phiên e+19, bán ở giá mở phiên e+20.
    """
    from utils.clock import next_trading_day, sessions_between, to_market_date, today

    out: dict[str, Any] = {"sessions_held": None, "sell_from": None, "sell_by": None,
                           "next_review": None, "following_review": None,
                           "decide_today": False, "last_decision": None, "phase": "unknown"}
    if not opened_at:
        return out
    try:
        d0 = to_market_date(opened_at)
    except (ValueError, TypeError):
        return out
    t = today_ or today()
    R = _review()
    held = sessions_between(d0, t)
    out["sessions_held"] = held
    out["sell_from"] = next_trading_day(d0, HOLD_MIN_SESSIONS).isoformat()
    out["sell_by"] = next_trading_day(d0, HOLD_MAX_SESSIONS).isoformat()
    # Decision closes fall at held = kR - 1 (k = 1, 2, ...).
    k_next = max(1, -(-(held + 1) // R))          # first k with kR - 1 >= held
    out["decide_today"] = held == k_next * R - 1
    out["next_review"] = next_trading_day(d0, k_next * R).isoformat()
    # the review after that: where a name kept today is looked at next
    out["following_review"] = next_trading_day(d0, (k_next + 1) * R).isoformat()
    k_last = held // R                            # last k with kR - 1 < held
    if k_last >= 1:
        out["last_decision"] = next_trading_day(d0, k_last * R - 1).isoformat()
    out["phase"] = ("quyết định hôm nay" if out["decide_today"]
                    else "trước kỳ xem lại đầu" if held < R - 1 else "giữa hai kỳ")
    return out


def verdict(sched: dict[str, Any], rank: int | None, n_ranked: int | None = None, *,
            rank_at_last_decision: int | None = None, equivalent: bool = False) -> dict[str, Any]:
    """GIỮ / BÁN cho một vị thế. Thuần hàm: hạng hôm nay, lịch, và hạng ở kỳ trước.

    `rank_at_last_decision`: hạng ở ngày quyết định gần nhất đã qua (từ kho
    `data/watch/`), để một kỳ bán bị lỡ không biến mất vào hôm sau.
    `equivalent`: mã ngoài rổ — hạng là chỗ nó SẼ đứng với cùng điểm động lượng.
    """
    keep = _keep()
    n = f"/{n_ranked}" if n_ranked else ""
    tag = " (tương đương — mã ngoài rổ)" if equivalent else ""
    if rank is None:
        return {"verdict": "CHƯA XẾP ĐƯỢC", "when": None,
                "why": "chưa đủ 6 tháng giá hoặc không lấy được giá — hệ thống không nói được "
                       "giữ hay bán mã này"}
    where = f"hạng {rank}{n}{tag}"
    out_of = rank > keep
    if sched.get("sessions_held") is None:
        if out_of:
            return {"verdict": "BÁN", "when": "ATO phiên tới",
                    "why": f"{where}, ngoài top {keep}. Chưa có ngày mua nên không có lịch xem "
                           "lại — xét theo hạng hôm nay"}
        return {"verdict": "GIỮ", "when": None,
                "why": f"{where}, trong top {keep}. Chưa có ngày mua nên chưa có lịch xem lại"}
    nxt = sched.get("next_review")
    if sched.get("decide_today"):
        if out_of:
            return {"verdict": "BÁN", "when": f"ATO {nxt}",
                    "why": f"tới kỳ xem lại, {where} — ngoài top {keep}"}
        return {"verdict": "GIỮ", "when": None,
                "why": f"tới kỳ xem lại, {where} — còn trong top {keep}, giữ tới kỳ sau "
                       f"({sched.get('following_review')})"}
    if (out_of and rank_at_last_decision is not None and rank_at_last_decision > keep
            and sched.get("last_decision")):
        return {"verdict": "BÁN", "when": "ATO phiên tới",
                "why": f"kỳ xem lại {sched['last_decision']} đã ở hạng {rank_at_last_decision} "
                       f"(ngoài top {keep}) mà chưa bán; hôm nay {where}"}
    if out_of:
        return {"verdict": "GIỮ", "when": None,
                "why": f"{where} — đang ngoài top {keep}. Chưa tới kỳ xem lại ({nxt}); tới kỳ "
                       "mà vẫn ngoài top thì bán"}
    return {"verdict": "GIỮ", "when": None, "why": f"{where}, trong top {keep}"}


def advise(position: dict, path: list[dict], atr_pct: float | None,
           last: float | None) -> dict[str, Any]:
    """Lịch xem lại + range tham chiếu cho một vị thế. Thuần hàm — không đọc đĩa.

    `path` là đường giá đóng kể từ ngày vào lệnh (`positions.track`). Hạng và
    kết luận GIỮ/BÁN không ở đây: chúng cần cả universe, nên `service.build`
    gắn chúng bằng `verdict()`.
    """
    out: dict[str, Any] = {
        "peak": None, "peak_basis": None, "band_lo": None, "band_hi": None,
        "band_status": None, **schedule(position.get("opened_at")), "note": "",
    }
    closes = [b["close"] for b in path if b.get("close")]
    # Đỉnh tính trên mọi phiên TRỪ phiên gần nhất — nếu không `band_hi` không
    # bao giờ chạm tới được (đỉnh luôn ≥ giá hôm nay). Đỉnh là GIÁ THỊ TRƯỜNG
    # đã đạt, không gộp giá vào lệnh.
    prior = closes[:-1] if len(closes) > 1 else closes
    peak = max(prior) if prior else None
    out["peak"] = peak
    # Range là tính chất của MÃ, không phải của lệnh: thiếu ngày mua thì neo ở
    # đỉnh ~30 phiên gần nhất, và chỉ cần nói ra điều đó.
    out["peak_basis"] = "since_entry" if position.get("opened_at") else "recent_window"
    a = _atr_frac(atr_pct)
    if peak and a:
        out["band_lo"] = round(peak * (1 - BAND_ATR * a), 2)
        out["band_hi"] = round(peak * (1 + BAND_ATR * a), 2)
        if last:
            out["band_status"] = ("trên vùng bán" if last > out["band_hi"]
                                  else "trong vùng bán" if last >= out["band_lo"]
                                  else "dưới vùng bán")
    if out["sessions_held"] is None:
        out["note"] = ("chưa có ngày mua nên chưa có lịch xem lại. Một ngày ƯỚC LƯỢNG là đủ — "
                       "lệch vài phiên gần như không đổi gì.")
    return out


# ---------------------------------------------------------------------------
# Dự phóng các phiên tới (2026-09-16, Tom: "đưa đề xuất và dự đoán trong các
# ngày tới để dễ tham chiếu").
#
# HAI LOẠI, và gộp chúng lại là cách nhanh nhất để biến một công cụ thành một
# lời hứa:
#
#   SUY RA ĐƯỢC   lịch (phiên nào tới hạn gì) và **biên độ** giá theo ATR của
#                 chính mã đó, giãn theo căn bậc hai số phiên — đúng cách
#                 §16.15 dựng `atr_scaled`, và là tính chất của bước ngẫu nhiên
#                 chứ không phải một dự báo.
#
#   KHÔNG SUY RA   **hướng** giá. Không rule nào trong repo thắng VNINDEX
#                  risk-adjusted (§26.9), nên một con số "giá sẽ là X" là bịa.
#                  Module này không trả về hướng, và không nên được sửa để trả.
#
# Biên độ dưới đây là "mã này thường đi bao nhiêu trong n phiên", KHÔNG phải
# khoảng tin cậy: ATR là biên độ NGÀY, không phải độ lệch chuẩn, nên đừng gọi nó
# là 1σ và đừng suy ra xác suất từ nó.
# ---------------------------------------------------------------------------

PROJECT_SESSIONS = (1, 5, 10, 20, 40)


def projection(last: float | None, atr_pct: float | None,
               sessions: tuple[int, ...] = PROJECT_SESSIONS,
               marks: dict[int, str] | None = None) -> list[dict]:
    """Biên độ ATR và ngày, cho từng mốc phiên phía trước.

    `marks` gắn nhãn sự kiện lên mốc phiên (vd {20: "mở cửa sổ bán"}).
    """
    from utils.clock import next_trading_day, today

    a = _atr_frac(atr_pct)
    if not last or not a:
        return []
    d0 = today()
    out = []
    for n in sessions:
        w = a * (n ** 0.5)          # giãn theo căn n — bước ngẫu nhiên, §16.15
        out.append({
            "sessions": n,
            "date": next_trading_day(d0, n).isoformat(),
            "lo": round(last * (1 - w), 2),
            "hi": round(last * (1 + w), 2),
            "width_pct": round(w * 100, 1),
            "mark": (marks or {}).get(n, ""),
        })
    return out
