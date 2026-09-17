"""Giá cho những mã Tom ĐANG NẮM nhưng nằm ngoài universe 54 mã.

## Defect nó sửa

Universe (`PicksUniverseService`) là **bộ lọc MUA**: 54 large-cap qua ngưỡng
thanh khoản, room ngoại, độ dài lịch sử. Sổ vị thế lại lấy giá **từ chính
universe đó** — tức bộ lọc mua đang bị dùng làm **danh sách theo dõi**. Hệ quả
đo được trên sổ thật ngày 2026-09-16: hai vị thế không có giá, và một trong hai
là **mã lỗ nặng nhất sổ**. Hệ thống mù đúng chỗ nó cần nhìn nhất.

Một mã đã nằm trong tay phải được theo dõi **bất kể nó còn đủ điều kiện để mua
hay không**. Nên ở đây KHÔNG áp bộ lọc thanh khoản hay room — đó là điều kiện
để *mua*, không phải để *được nhìn thấy*.

## Hai nửa, và tách chúng ra là toàn bộ thiết kế

- `refresh()` **gọi mạng** (vnstock/KBS, sau throttle 18 req/phút). **Chỉ job
  có lịch được gọi.** Nó ghi kết quả ra `CACHE`.
- `load()` **chỉ đọc đĩa.** Route `/api/state/positions/pnl` dùng được.

Không được gộp: `mark_book()` được cả route lẫn job gọi, và route đó cố ý chỉ
`.peek()` snapshot để không treo 2-10 phút sau throttle (cái bẫy §22.6 và
`api/routers/insight.py` đã ghi). Gọi mạng trong đường đọc là mang cái treo đó
quay lại.

## Không có định nghĩa thứ hai

Giá, ATR và đuôi 30 phiên được tính bằng **đúng** `_fetch_ohlcv` +
`_build_ticker_row` mà universe dùng. Import hàm private qua module là một mùi
nhỏ; viết một fetcher và một bộ tính indicator thứ hai là lỗi đã ghi ba lần
trong repo này (§22.11, §16.15, `analysis/bench.py`).

`CACHE` nằm ở `data/`, **không** ở `data/watch/`: `audit.py` glob mọi `*.json`
trong thư mục đó và sẽ đọc nhầm cache thành một bản lưu trữ.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import BASE_DIR

log = logging.getLogger(__name__)

CACHE = Path(BASE_DIR) / "data" / "holdings_prices.json"

#: Cùng cửa sổ lịch với universe (~270 phiên) — SMA200 cần 200 bar, và điểm số
#: bị sàn nếu không xác nhận được SMA200 (§26.4).
LOOKBACK_DAYS = 400


def missing(held: set[str], universe: set[str]) -> list[str]:
    """Mã đang nắm mà snapshot không có giá."""
    return sorted(held - universe)


def refresh(symbols: list[str], sectors: dict[str, str] | None = None) -> dict[str, Any]:
    """Lấy giá cho `symbols` và ghi `CACHE`. **Gọi mạng — chỉ job được dùng.**

    Không bao giờ raise: một mã hỏng không được làm hỏng cả bản tin. Mã lấy
    thất bại được ghi lại cùng lý do, để bản tin nói "không lấy được giá XYZ"
    thay vì im lặng như thể mã đó không tồn tại.
    """
    from services.picks_universe_service import _build_ticker_row, _fetch_ohlcv

    sectors = sectors or {}
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    prev = load()
    rows: dict[str, Any] = dict(prev.get("rows", {}))
    failed: dict[str, str] = {}

    for sym in symbols:
        try:
            df = _fetch_ohlcv(sym, start, end)
        except Exception as e:  # noqa: BLE001 - một mã hỏng không làm hỏng bản tin
            failed[sym] = f"fetch lỗi: {e}"
            continue
        if df.empty or "close" not in df.columns:
            failed[sym] = "nguồn không trả dữ liệu"
            continue
        # KHÔNG lọc thanh khoản — xem docstring module. dv chỉ để truyền cho
        # builder, không để loại.
        dv = float((df["close"] * 1000 * df.get("volume", 0)).tail(20).mean() or 0.0)
        row = _build_ticker_row(sym, sectors.get(sym, ""), df, None, dv)
        if row is None:
            # Builder chỉ trả None khi tính indicator hỏng (lịch sử quá ngắn).
            # Giá đóng vẫn dùng được cho P&L, nên giữ nó thay vì bỏ cả mã.
            last = df.iloc[-1]
            rows[sym] = {"close": float(last["close"]), "atr_pct": None,
                         "daily_prices": [], "as_of": str(last.get("time", end))[:10],
                         "partial": True}
            failed[sym] = f"chỉ có giá đóng — {len(df)} phiên, không đủ tính ATR"
            continue
        rows[sym] = {
            "close": row.close,
            "atr_pct": row.atr_pct,
            "daily_prices": row.daily_prices,
            "as_of": str(row.daily_prices[-1].get("time", end))[:10]
            if row.daily_prices else end,
            "partial": False,
        }

    out = {"refreshed_at": datetime.now().isoformat(timespec="seconds"),
           "rows": rows, "failed": failed}
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                         encoding="utf-8")
    except OSError:
        log.exception("[holdings] không ghi được cache")
    return out


def load() -> dict[str, Any]:
    """Đọc `CACHE`. **Không gọi mạng** — route API dùng được."""
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"rows": {}, "failed": {}}
