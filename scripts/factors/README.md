# Thêm một thuật toán

Một file, một ý tưởng. Bench tự nạp mọi file trong thư mục này (trừ file bắt
đầu bằng `_`), chấm nó theo đúng tiêu chí doctrine, và in phán quyết.

```python
# scripts/factors/my_idea.py
from analysis.bench import register

@register("Z_ten_ngan", source="ý tưởng thô / bài báo X / CLAUDE.md §NN")
def _(f):
    """Một câu: thuật toán này mua cái gì."""
    return -f["ret5"]          # CAO HƠN = đáng mua hơn
```

Chạy:

```
uv run python scripts/ticker_alpha_bench.py --horizons 20 --verdict --only Z_ten_ngan
```

## `f` có gì

`build_features()` trả về dict các DataFrame **ngày × mã**, cùng index:
`close` `open` `high` `low` `vol` · `sma20` `sma50` `sma200` · `rsi2` `rsi14`
`atr` `atrp` `adx14` `macd_hist` · `ret1` `ret5` `ret20` · `vr20` `dv20`
`obv_chg20`. Xem đầu `ticker_alpha_bench.py` cho danh sách đầy đủ.

## Ba luật không thương lượng

1. **Trả về điểm, đừng trả về thứ hạng đã lọc.** Bench lo phần xếp hạng, chọn
   top-k, ngưỡng thanh khoản và chi phí. Factor chỉ chấm điểm.
2. **Đừng nhìn tương lai.** Mọi phép tính chỉ dùng dữ liệu tới hết phiên đó;
   bench đã vào lệnh ở giá mở phiên **sau**, đừng bù thêm shift.
3. **Đừng gõ lại hằng số chi phí.** Nó ở `analysis/bench.py`, và lý do có file
   đó là vì hai bench từng lệch nhau 0,30%/vòng mà không ai thấy.

## Đọc phán quyết thế nào

Hai tiêu chí **bắt buộc**, trượt là loại:

- **thắng base rate TỪNG NĂM** (§16.12) — base là **NO GATE**: mọi mã đủ thanh
  khoản, mọi phiên có ≥ 30 mã như thế. Gộp lại là thứ đã che được một 2026 ngang
  mức ngẫu nhiên. Một rule dương khi gộp mà âm một năm thì chưa là rule.
- **quintile đơn điệu** (§18.7) — không đơn điệu nghĩa là model đang đoán. Đọc
  kèm Q5−Q1 với t Newey-West.

t trong bảng là **Newey-West lag h** (lợi suất h phiên đo mỗi ngày chồng nhau).
`VƯỢT TRẦN` nghĩa là **danh mục staggered của rule** thắng VNINDEX mua & giữ trên
**cùng các ngày**, cả lợi nhuận lẫn Sharpe — không còn so với hằng số 15,7%
(2026-09-25). Tính đến 2026-09 **chưa rule nào đạt**; VNINDEX 2023-01 → 2026-09
là 17,5%/năm, Sharpe 0,98 — xem §26.9. Luật đang ship chấm ở dòng
`X_shipped_rule`, không phải `X_prop_obv`.
