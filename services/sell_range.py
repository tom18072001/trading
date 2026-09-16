"""Khuyến nghị bán: một **cửa sổ thời gian** và một **range giá** trượt lên.

Thay cho stop-loss, bỏ ngày 2026-09-16 theo quyết định của Tom (§26.10 lần hai).

## Cái gì được đo, cái gì không — đọc trước khi tin con số nào

`scripts/tplus_strategy_bench.py --trail` chấm 7 hình học thoát trên 3.446 lệnh,
luật vào lệnh đang ship, chi phí 1,00%/vòng:

    khung 40 phiên            mean%    excess   theo năm
    KHÔNG stop, giữ hết khung  +1,77    +0,59    24:+0,59  25:+1,25  26:+1,25
    range nhả 3,5xATR          +1,07    +0,49    24:+0,92  25:+1,15  26:+1,05
    chỉ gãy trend thì bán      +0,87    +0,37
    range nhả 2,5xATR          +0,18    +0,18
    range nhả 1,5xATR          −1,29    +0,09

**Giữ hết khung thắng mọi biến thể range, và càng chặt càng tệ — đơn điệu.**
Cùng kết quả ở khung 20. Nói thẳng: một luật thoát bằng mức giá, dù neo ở đỉnh
thay vì ở giá vào, vẫn là một cái stop và vẫn tốn tiền. §26.10 đã đo điều đó cho
stop neo ở giá vào; đây là cùng kết luận cho băng neo ở đỉnh.

Nên module này tách bạch hai thứ, và chỉ MỘT trong hai là luật đo được:

  - `sell_from` / `sell_by` — **cửa sổ thời gian. ĐÂY là luật.** Giữ 20-40 phiên
    rồi bán. Dưới 20 và trên 40 phiên không factor nào sống sót phép đo (§26.9).
  - `band_lo` / `band_hi` — **range tham chiếu, KHÔNG phải luật.** Nó trả lời
    "giá đang ở đâu so với nhịp thường của chính mã này", để Tom quyết định bán
    vào vùng nào trong cửa sổ. Thoát tự động tại `band_lo` đã được đo và **thua**
    việc giữ hết khung.

`give_back` là ngoại lệ có bằng chứng: 3,5×ATR dưới đỉnh là băng **ít tốn nhất**
trong các băng đo được (+1,07 so với +1,77 của không-băng). Nếu Tom vẫn muốn một
mức cơ học thì đó là mức ít hại nhất — không phải mức tốt.
"""
from __future__ import annotations

from typing import Any

#: Cửa sổ giữ, đo được (§26.9 + quét 10/20/40/60 ngày 2026-09-16).
#: Ngoài khoảng này không factor nào qua được hai tiêu chí bắt buộc.
HOLD_MIN_SESSIONS = 20
HOLD_MAX_SESSIONS = 40

#: Range tham chiếu: ±1 ATR quanh ĐỈNH đã đạt. Một ATR là "một nhịp thường của
#: chính mã đó", nên vùng này đọc được ngay: dưới đáy range là đã nhả hơn một
#: nhịp, trên đỉnh range là đang mạnh hơn một nhịp. Nó **không** là luật thoát.
BAND_ATR = 1.0

#: Mức nhả lại ít tốn nhất trong các băng ĐO ĐƯỢC — vẫn thua không dùng băng.
GIVE_BACK_ATR = 3.5


def _atr_frac(atr_pct: float | None) -> float | None:
    """`atr_pct` đi lẫn lộn hai đơn vị trong repo — chuẩn hoá về phân số.

    `TickerRow.atr_pct` là phần trăm (3.13 = 3,13%); `sector_flow_daily.atr_pct`
    là phân số (0.0313). Cùng tên, hai đơn vị — đúng thứ đã gây ra §16.15, nơi
    bar breakout hoá ra là 1,15% thay vì 8%.
    """
    if atr_pct is None or atr_pct <= 0:
        return None
    return atr_pct / 100.0 if atr_pct >= 0.5 else float(atr_pct)


def advise(position: dict, path: list[dict], atr_pct: float | None,
           last: float | None) -> dict[str, Any]:
    """Khuyến nghị bán cho một vị thế. Thuần hàm — không đọc đĩa, không gọi API.

    `path` là đường giá đóng kể từ ngày vào lệnh (`position_tracking.track`).
    """
    from utils.clock import next_trading_day, sessions_between, to_market_date

    out: dict[str, Any] = {
        "peak": None, "peak_basis": None, "band_lo": None, "band_hi": None,
        "give_back": None, "sell_from": None, "sell_by": None,
        "sessions_held": None, "phase": "unknown", "note": "",
    }

    entry = position.get("entry_price")
    closes = [b["close"] for b in path if b.get("close")]
    peak = max(closes + ([entry] if entry else [])) if (closes or entry) else None
    out["peak"] = peak

    # Range neo ở ĐỈNH KỂ TỪ KHI MUA. Không biết ngày mua thì `track()` trả cả
    # đuôi 30 phiên, nên "đỉnh" là đỉnh 30 phiên — một con số khác hẳn, và với
    # một vị thế đang lỗ nó nằm TRÊN giá hiện tại và đọc ra thành target. Đánh
    # dấu cơ sở thay vì im lặng: một dải tính sai vẫn in ra đẹp như dải tính đúng.
    out["peak_basis"] = "since_entry" if position.get("opened_at") else "recent_window"

    a = _atr_frac(atr_pct)
    if peak and a and out["peak_basis"] == "since_entry":
        out["band_lo"] = round(peak * (1 - BAND_ATR * a), 2)
        out["band_hi"] = round(peak * (1 + BAND_ATR * a), 2)
        out["give_back"] = round(peak * (1 - GIVE_BACK_ATR * a), 2)

    opened = position.get("opened_at")
    if opened:
        try:
            d0 = to_market_date(opened)
            held = sessions_between(d0)
            out["sessions_held"] = held
            out["sell_from"] = next_trading_day(d0, HOLD_MIN_SESSIONS).isoformat()
            out["sell_by"] = next_trading_day(d0, HOLD_MAX_SESSIONS).isoformat()
            if held < HOLD_MIN_SESSIONS:
                out["phase"] = "giữ"
                out["note"] = (f"còn {HOLD_MIN_SESSIONS - held} phiên nữa mới tới "
                               "cửa sổ bán. Luật đo được là giữ hết khung.")
            elif held <= HOLD_MAX_SESSIONS:
                out["phase"] = "trong cửa sổ bán"
                out["note"] = (f"đang trong cửa sổ {HOLD_MIN_SESSIONS}-"
                               f"{HOLD_MAX_SESSIONS} phiên. Còn "
                               f"{HOLD_MAX_SESSIONS - held} phiên tới hạn.")
            else:
                out["phase"] = "quá hạn"
                out["note"] = (f"đã giữ {held} phiên, quá khung {HOLD_MAX_SESSIONS}. "
                               "Ngoài khung này không factor nào sống sót phép đo.")
        except (ValueError, TypeError):
            pass

    if out["peak_basis"] != "since_entry":
        out["note"] = ("chưa biết ngày mua — không tính được cửa sổ bán, và range "
                       "giá cũng không tính (đỉnh phải đo từ lúc vào lệnh).")

    if last and out["give_back"] and last <= out["give_back"]:
        out["note"] += (f"  Giá đã nhả quá {GIVE_BACK_ATR}×ATR từ đỉnh "
                        f"({peak:,.2f}) — sóng lên nhiều khả năng đã kết thúc.")
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
