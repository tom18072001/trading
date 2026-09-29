"""Sổ lệnh từ dòng lệnh — để Claude (hoặc Tom) ghi đúng điều Tom báo, rồi đọc lại kết luận.

Tom, 2026-09-29: *"tôi sẽ báo bạn tôi mua con nào giá thế nào · khi tôi bán tôi
sẽ báo bạn · việc của bạn cập nhật những con tôi đang hold và đưa đề xuất"*.

    python -m daily_watch.book buy  VIC 45.2 1000 [--date 2026-09-29] [--note ...]
    python -m daily_watch.book sell VIC 48.5 [500] [--date 2026-10-20]
    python -m daily_watch.book date VIC 2026-09-15
    python -m daily_watch.book show

`buy` mua thêm một mã đang giữ thì cộng vào, giá vốn bình quân. `sell` không ghi
khối lượng = bán hết. `date` đặt ngày mua cho một vị thế chưa có — ước lượng là
đủ. `show` in kết luận GIỮ / BÁN của từng mã, từ đúng hàm bản tin 17:30 dùng.

Giá theo nghìn đồng, như bảng giá (45.2 = 45.200đ). Một con số ≥ 1.000 được hiểu
là đồng và chia 1.000 — không mã HOSE nào giá trên một triệu đồng, và hệ thống
không bao giờ đoán thầm: dòng in ra luôn nói nó đã hiểu giá thế nào.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any


def price_k(x: str | float) -> tuple[float, str]:
    """(price in thousand VND, how it was read)."""
    v = float(str(x).replace(",", ""))
    if v <= 0:
        raise ValueError("giá phải dương")
    if v >= 1000:
        return v / 1000.0, f"{v:,.0f}đ → {v / 1000.0:,.2f} nghìn"
    return v, f"{v:,.2f} nghìn"


def _date(s: str | None) -> str | None:
    if s is None:
        return None
    from utils.clock import to_market_date
    return to_market_date(s).isoformat()


def summary(payload: dict[str, Any]) -> str:
    """Kết luận từng vị thế, gọn — cùng số với mục 1-2 của bản tin."""
    b = payload["book"]
    n = (payload.get("shortlist_meta") or {}).get("ranked_count") or 0
    if not b["positions"]:
        return "Sổ trống."
    lines = [f"Dữ liệu phiên {payload.get('data_as_of') or 'không rõ'}"]
    for p in b["positions"]:
        v = p.get("verdict") or {}
        sr = p.get("sell_range") or {}
        rank = p.get("rank")
        pnl = p.get("pnl_pct")
        parts = [f"{p['symbol']:5s}"]
        if p.get("qty") is not None:
            parts.append(f"{p['qty']:,.0f} cp")
        if p.get("entry_price"):
            parts.append(f"giá vốn {p['entry_price']:,.2f}")
        if p.get("last"):
            parts.append(f"gần nhất {p['last']:,.2f}")
        parts.append(f"lãi/lỗ {pnl:+.1f}%" if pnl is not None else "lãi/lỗ —")
        rk = (f"hạng {rank}/{n}" + (" (tương đương)" if p.get("rank_equivalent") else "")
              if rank is not None else "chưa xếp hạng")
        parts.append(f"{rk} → {v.get('verdict', '—')}" + (f" {v['when']}" if v.get("when") else ""))
        nxt = p.get("next_check") or sr.get("next_review")
        parts.append(f"xem lại {nxt}" if nxt else "chưa có ngày mua")
        lines.append(" · ".join(parts))
        if v.get("why"):
            lines.append(f"      {v['why']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m daily_watch.book")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("buy")
    b.add_argument("symbol")
    b.add_argument("price")
    b.add_argument("qty", type=float)
    b.add_argument("--date")
    b.add_argument("--note", default="")
    s = sub.add_parser("sell")
    s.add_argument("symbol")
    s.add_argument("price")
    s.add_argument("qty", type=float, nargs="?")
    s.add_argument("--date")
    s.add_argument("--note")
    d = sub.add_parser("date")
    d.add_argument("symbol")
    d.add_argument("day")
    sub.add_parser("show")
    a = ap.parse_args(argv)

    from services import trading_state
    try:
        if a.cmd == "buy":
            px, how = price_k(a.price)
            trading_state.record_buy(a.symbol, px, a.qty, bought_at=_date(a.date), note=a.note)
            row = next(p for p in trading_state.get_state()["positions"]
                       if p["symbol"] == a.symbol.strip().upper() and p["side"] == "BUY")
            print(f"Đã ghi MUA {a.symbol.upper()} {a.qty:,.0f} cp giá {how}. Vị thế: "
                  f"{row['qty']:,.0f} cp, giá vốn bình quân {row['entry_price']:,.3f}, "
                  f"ngày mua {row.get('opened_at') or 'chưa có'}.")
        elif a.cmd == "sell":
            px, how = price_k(a.price)
            st = trading_state.close_position(a.symbol, exit_price=px, qty=a.qty,
                                              closed_at=_date(a.date), note=a.note)
            last = st["closed"][-1]
            left = next((p for p in st["positions"]
                         if p["symbol"] == a.symbol.strip().upper() and p["side"] == "BUY"), None)
            pnl = last.get("pnl_pct")
            print(f"Đã ghi BÁN {a.symbol.upper()} {last.get('qty') or 0:,.0f} cp giá {how}"
                  + (f", lãi/lỗ sau phí {pnl:+.2f}%" if pnl is not None else "")
                  + (f". Còn giữ {left['qty']:,.0f} cp." if left else ". Đã đóng vị thế."))
        elif a.cmd == "date":
            trading_state.update_position(a.symbol, opened_at=_date(a.day))
            print(f"Đã đặt ngày mua {a.symbol.upper()} = {_date(a.day)}.")
    except ValueError as e:
        print(f"Không ghi được: {e}", file=sys.stderr)
        return 2

    from daily_watch import service
    print()
    print(summary(service.build()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
