"""Chấm lại các khuyến nghị cũ bằng chính những bản lưu sau nó.

    uv run python daily_watch/audit.py --hold 20
    uv run python daily_watch/audit.py --hold 40

## Vì sao script này tồn tại

§26.1: khi Tom hỏi *"picks của bạn có tốt không"*, **không có gì trong repo trả
lời được** — không bảng nào lưu một pick, nên phải viết `extract_past_picks.py`
để bới 174 pick ra khỏi kho HTML báo cáo, và phải dựng thêm một panel giá vì
`_legacy_stock_prices` dừng ở 2026-04. Cả hai đều là công việc đáng lẽ không cần.

`data/watch/<ngày>.json` sửa điều đó ở đầu nguồn. Và nó **tự chấm được**: mỗi bản
lưu ghi cả khuyến nghị lẫn `marks` — từ 2026-09-25 là giá đóng của **cả
universe**, không chỉ các mã được nhắc tới — nên N bản lưu tự cho một chuỗi giá,
kể cả base rate. Không cần nguồn giá thứ hai, không cần panel cập nhật tay.

## Hai luật, chấm cạnh nhau (2026-09-25)

Tom bỏ ngưỡng `MIN_BUY_SCORE` 2,5 và giữ cổng SMA200 ("bỏ ngay, giữ cổng
SMA200"). Phép đo cho quyết định đó là in-sample, t ≈ 1,5 (review 2026-09-24
§2.2). Nên mỗi bản lưu ghi cả danh sách luật cũ LẼ RA cho ra
(`shortlist_with_cutoff`), và script này chấm cả hai trên cùng ngày, cùng base:

  - **luật đang chạy** — `shortlist`: cổng SMA200 → blend.
  - **luật cũ** — `shortlist_with_cutoff`; với bản lưu trước 2026-09-25 thì
    chính `shortlist` (khi đó đang chạy luật có ngưỡng).
  - **base** — mọi mã của universe có giá ở cả hai bản lưu (NO GATE, §16.12).

Đây là phép đo **ngoài mẫu** đầu tiên của việc bỏ ngưỡng — dữ liệu chưa từng
được dùng để chọn luật.

## Cái script này KHÔNG làm

Nó không tuyên bố một biên độ alpha. Giá vào là giá đóng của ngày khuyến nghị
(lệnh thật khớp ATO phiên sau), và "sau N bản lưu" chỉ xấp xỉ N phiên (job chạy
T2-T6; một ngày job hỏng là một bản lưu thiếu). Cỡ mẫu vài tháng quá nhỏ để kết
luận: §26.8 ghi một sổ ~100 lệnh trong 3,7 năm còn đổi dấu hai lần. Đây là
**nhật ký có chấm điểm** — nguyên liệu cho `ticker_alpha_bench.py`, không phải
bản thay thế nó.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import HOLD_SESSIONS  # noqa: E402

ARCHIVE = ROOT / "data" / "watch"

#: Cần ít nhất bấy nhiêu bản lưu sau một khuyến nghị mới chấm được nó. Dưới mức
#: này, in ra một con số là mời người đọc tin vào nhiễu.
MIN_FORWARD = 2

RUNNING, CUTOFF = "luật đang chạy (cổng SMA200)", "luật cũ (điểm ≥ 2,5)"


def load() -> list[dict]:
    out = []
    for f in sorted(ARCHIVE.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            print(f"[audit] bỏ qua bản lưu hỏng: {f.name}", file=sys.stderr)
    return out


def rule_lists(snap: dict) -> dict[str, list[str]]:
    """{luật: [mã]} cho một bản lưu.

    Bản lưu trước 2026-09-25 không có `shortlist_with_cutoff` — khi đó
    `shortlist` CHÍNH LÀ luật có ngưỡng, nên nó được chấm vào luật cũ, không
    phải luật đang chạy.
    """
    syms = [p["symbol"] for p in snap.get("shortlist") or []]
    if "shortlist_with_cutoff" not in snap:
        return {CUTOFF: syms}
    return {RUNNING: syms,
            CUTOFF: [p["symbol"] for p in snap.get("shortlist_with_cutoff") or []]}


def _ret(m0: dict, m1: dict, sym: str) -> float | None:
    a, b = m0.get(sym), m1.get(sym)
    return (b / a - 1.0) if (a and b) else None


def forward(snaps: list[dict], hold: int) -> tuple[list[dict], int]:
    """Một dòng cho mỗi bản lưu đã đủ `hold` bản phía sau: lợi suất trung bình
    của từng luật và của base, cùng cặp ngày, cùng giá đóng."""
    rows, pending = [], 0
    for i, s in enumerate(snaps):
        j = i + hold
        if j >= len(snaps):
            pending += len(s.get("shortlist") or [])
            continue
        m0, m1 = s.get("marks") or {}, snaps[j].get("marks") or {}
        held = {p.get("symbol") for p in (s.get("book") or {}).get("positions", [])}
        base = [r for sym in m0 if sym not in held and (r := _ret(m0, m1, sym)) is not None]
        row = {"date": s.get("generated_at"),
               "base": st.mean(base) if len(base) >= 10 else None, "n_base": len(base)}
        for rule, syms in rule_lists(s).items():
            rs = [r for sym in syms if (r := _ret(m0, m1, sym)) is not None]
            row[rule] = st.mean(rs) if rs else None
            row[f"n:{rule}"] = len(rs)
        rows.append(row)
    return rows, pending


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=int, default=HOLD_SESSIONS[0], choices=HOLD_SESSIONS,
                    help="chấm sau bao nhiêu BẢN LƯU (xấp xỉ phiên, vì job chạy T2-T6)")
    args = ap.parse_args()

    snaps = load()
    if not snaps:
        print(f"chưa có bản lưu nào ở {ARCHIVE}. Chạy `main.py --daily-watch`.")
        return 0

    dates = [s.get("generated_at") for s in snaps]
    print(f"{len(snaps)} bản lưu, {dates[0]} .. {dates[-1]}")

    rows, pending = forward(snaps, args.hold)
    print(f"\nĐỀ XUẤT MUA — chấm sau {args.hold} bản lưu, giá đóng → giá đóng")
    if len(snaps) <= MIN_FORWARD or not rows:
        print(f"  chưa chấm được: cần đủ {args.hold} bản lưu sau mỗi khuyến nghị "
              f"({pending} mã đang chờ).")
    else:
        print(f"  {'luật':34s} {'ngày':>5s} {'lệnh':>5s} {'TB/lệnh':>9s} {'vượt base':>10s}")
        for rule in (RUNNING, CUTOFF):
            got = [r for r in rows if r.get(rule) is not None]
            if not got:
                print(f"  {rule:34s} {'—':>5s}")
                continue
            mean = st.mean(r[rule] for r in got)
            ex = [r[rule] - r["base"] for r in got if r["base"] is not None]
            print(f"  {rule:34s} {len(got):>5d} {sum(r[f'n:{rule}'] for r in got):>5d} "
                  f"{mean*100:>+8.2f}% "
                  + (f"{st.mean(ex)*100:>+9.2f}%" if ex else f"{'—':>10s}"))
        based = [r for r in rows if r["base"] is not None]
        if based:
            print(f"  {'base: cả universe (NO GATE)':34s} {len(based):>5d} {'':>5s} "
                  f"{st.mean(r['base'] for r in based)*100:>+8.2f}%")
        both = [r[RUNNING] - r[CUTOFF] for r in rows
                if r.get(RUNNING) is not None and r.get(CUTOFF) is not None]
        if both:
            print(f"\n  hiệu cặp (đang chạy − cũ), cùng ngày: {st.mean(both)*100:+.2f}%/lệnh "
                  f"trên {len(both)} ngày. Review 2026-09-24 §2.2 dự đoán dương "
                  f"(+0,39 / +0,44 ở khung 20 / 40), đo in-sample.")
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
