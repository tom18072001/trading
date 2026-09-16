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

- **thắng base rate TỪNG NĂM** (§16.12) — gộp lại là thứ đã che được một 2026
  ngang mức ngẫu nhiên. Một rule dương khi gộp mà âm một năm thì chưa là rule.
- **quintile đơn điệu** (§18.7) — không đơn điệu nghĩa là model đang đoán.

`VƯỢT TRẦN` nghĩa là quy năm hơn VNINDEX buy-and-hold (15,7% CAGR). Tính đến
2026-09 **chưa rule nào đạt**, kể cả khi đã đạt hết các tiêu chí còn lại — xem
§26.9.
