"""Chấm lại các khuyến nghị cũ bằng chính những bản lưu sau nó.

    uv run python daily_watch/audit.py --hold 20

## Vì sao script này tồn tại

§26.1: khi Tom hỏi *"picks của bạn có tốt không"*, **không có gì trong repo trả
lời được** — không bảng nào lưu một pick, nên phải viết `extract_past_picks.py`
để bới 174 pick ra khỏi kho HTML báo cáo, và phải dựng thêm một panel giá vì
`_legacy_stock_prices` dừng ở 2026-04. Cả hai đều là công việc đáng lẽ không cần.

`data/watch/<ngày>.json` sửa điều đó ở đầu nguồn. Và nó **tự chấm được**: mỗi bản
lưu ghi cả khuyến nghị lẫn `marks` (giá đóng của mọi mã nó nhắc tới), nên N bản
lưu tự cho một chuỗi giá. Không cần nguồn giá thứ hai, không cần panel cập nhật
tay — hai thứ đã từng làm hỏng phép đo trước đây.

## Cái script này KHÔNG làm

Nó không tuyên bố một biên độ alpha. Số lượng khuyến nghị ở đây quá nhỏ và quá
mới để nói bất kỳ điều gì về edge; §26.8 đã ghi rằng một sổ ~100 lệnh trong 3,7
năm còn đổi dấu hai lần khi quét khung giữ. Đây là **nhật ký có chấm điểm**, để
sau này biết hệ thống đã khuyên gì và điều gì đã xảy ra — nguyên liệu cho
`ticker_alpha_bench.py`, không phải bản thay thế nó.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARCHIVE = ROOT / "data" / "watch"

#: Cần ít nhất bấy nhiêu bản lưu sau một khuyến nghị mới chấm được nó. Dưới mức
#: này, in ra một con số là mời người đọc tin vào nhiễu.
MIN_FORWARD = 2


def load() -> list[dict]:
    out = []
    for f in sorted(ARCHIVE.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            print(f"[audit] bỏ qua bản lưu hỏng: {f.name}", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=int, default=20,
                    help="chấm sau bao nhiêu BẢN LƯU (xấp xỉ phiên, vì job chạy T2-T6)")
    args = ap.parse_args()

    snaps = load()
    if not snaps:
        print(f"chưa có bản lưu nào ở {ARCHIVE}. Chạy `main.py --daily-watch`.")
        return 0

    dates = [s.get("generated_at") for s in snaps]
    print(f"{len(snaps)} bản lưu, {dates[0]} .. {dates[-1]}")

    # chuỗi giá gộp từ mọi bản lưu: {mã: {ngày: giá}}
    series: dict[str, dict[str, float]] = {}
    for s in snaps:
        for sym, px in (s.get("marks") or {}).items():
            series.setdefault(sym, {})[s["generated_at"]] = px

    scored, pending = [], 0
    for i, s in enumerate(snaps):
        j = i + args.hold
        if j >= len(snaps):
            pending += len(s.get("shortlist") or [])
            continue
        d0, d1 = s["generated_at"], snaps[j]["generated_at"]
        for p in s.get("shortlist") or []:
            a = series.get(p["symbol"], {}).get(d0)
            b = series.get(p["symbol"], {}).get(d1)
            if a and b:
                scored.append((d0, p["symbol"], p.get("score"), a, b, b / a - 1))

    print(f"\nĐỀ XUẤT MUA — chấm sau {args.hold} bản lưu")
    if len(snaps) <= MIN_FORWARD:
        print(f"  chưa chấm được: mới {len(snaps)} bản lưu, cần > {MIN_FORWARD} "
              f"và đủ {args.hold} bản sau mỗi khuyến nghị.")
    elif not scored:
        print(f"  chưa khuyến nghị nào đủ {args.hold} bản lưu phía sau "
              f"({pending} đang chờ).")
    else:
        import statistics as st
        rets = [r[-1] for r in scored]
        print(f"  n={len(scored)}  trung bình {st.mean(rets)*100:+.2f}%  "
              f"trung vị {st.median(rets)*100:+.2f}%  "
              f"thắng {sum(r > 0 for r in rets)/len(rets):.0%}")
        print(f"  {'ngày':12s} {'mã':6s} {'điểm':>6s} {'vào':>8s} {'ra':>8s} {'%':>8s}")
        for d, sym, sc, a, b, r in scored[-15:]:
            print(f"  {d:12s} {sym:6s} {sc if sc is None else f'{sc:6.2f}'} "
                  f"{a:>8.2f} {b:>8.2f} {r*100:>+7.2f}%")
        print("\n  Đây là nhật ký, KHÔNG phải một biên độ alpha: cỡ mẫu này quá nhỏ")
        print("  để kết luận (§26.8). Dùng ticker_alpha_bench.py để đo edge.")

    held = {p["symbol"] for s in snaps for p in s.get("book", {}).get("positions", [])}
    print(f"\nSỔ — {len(held)} mã từng xuất hiện: {' '.join(sorted(held))}")
    last = snaps[-1]
    closed = last.get("book", {}).get("closed") or []
    if closed:
        print(f"  {len(closed)} lệnh đã đóng trong bản lưu mới nhất")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
