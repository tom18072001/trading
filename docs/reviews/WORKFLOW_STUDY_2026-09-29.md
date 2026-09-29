# Luật mua / bán cho cách Tom thật sự giao dịch — 2026-09-29

Tom, 29/09:

> *"luật chơi của tôi rất đơn giản: bạn khuyến nghị mã nào nên mua hằng ngày (có các
> priority, con nào khả năng lên cao) · tôi sẽ báo bạn tôi mua con nào giá thế nào ·
> khi tôi bán tôi sẽ báo bạn · việc của bạn cập nhật những con tôi đang hold và đưa đề
> xuất dựa vào giá mua, có nên bán hay không"*
>
> *"dựa vào yếu tố này có giúp bạn cải thiện luật toán cho phù hợp với strategy của tôi
> không"*

Harness: `docs/reviews/workflow_study_2026-09-29/` (`priority.py`, `priority_joint.py`,
`exits.py`). Dùng chung lab, panel giá và protocol của
`STRATEGY_STUDY_2026-09-28.md`.

## 1. Ba chỗ cách chơi của Tom khác với cái backtest đang đo

Luật 28/09 được đo như một **sổ 8 mã đồng bộ**: mua cả 8 cùng ngày, xem lại cả sổ mỗi
20 phiên. Tom thì khác ở ba chỗ, và mỗi chỗ là một câu hỏi đo được:

| cách Tom chơi | câu hỏi cho luật |
|---|---|
| mua **vài mã**, không mua cả 8 | thứ tự trong danh sách có nghĩa không — mã nào mua trước? |
| mua vào **ngày của anh**, giá của anh | mỗi vị thế cần **đồng hồ riêng**, tính từ ngày mua |
| muốn đề xuất bán **dựa vào giá mua** | lãi/lỗ so với giá mua (chốt lời, cắt lỗ) có giúp gì không? |

Thêm hai lỗ trong sổ, không cần đo, chỉ cần sửa:

- Mua thêm một mã đang giữ thì **ghi đè** giá và khối lượng cũ.
- Chưa bán được một phần vị thế.

## 2. Protocol — viết ra trước khi đọc kết quả

- **DEV:** tín hiệu từ 2019-07-01, và ngày bán ≤ 2025-09-15.
- **HOLDOUT:** 2025-09-16 → 2026-09-28. Chỉ đọc một lần, cho những gì qua DEV.
- **Phí:** 1,0%/vòng, như bench.
- **Mức nhiễu:** 11 biến thể mới (4 giả thuyết ưu tiên + 7 luật bán). Con số này cộng
  thêm vào 394 biến thể của study 28/09.
- **Holdout đã dùng một lần** để bỏ công tắc thị trường (study 28/09 §7). Vì vậy chỉ hỏi
  **dấu** của holdout, không hỏi độ lớn.

## 3. Thứ tự ưu tiên trong danh sách mua (`priority.py`)

**Đơn vị đo.** Một pick là một mã trong top 8 ở giá đóng ngày t, mua giá mở t+1, bán giá
đóng t+1+h. Kết quả tính sau phí, trừ đi trung bình rổ U75 cùng cửa sổ.

**Cách tính t-stat.** Mỗi ngày cho một chênh lệch giữa hai nhóm. Các ngày liên tiếp
chồng cửa sổ lên nhau, nên dùng Newey-West lag h.

**Ngưỡng nhận:** trên DEV, dương ở cả h = 20 và 40, t ≥ 2 ở ít nhất một khung, và đúng
chiều ở ≥ 4/6 năm trọn (2020-2025).

| giả thuyết (đăng ký trước) | DEV 4 tuần | DEV 8 tuần | năm đúng chiều | holdout 4 / 8 tuần | kết luận |
|---|---|---|---|---|---|
| P1 hạng 1-4 hơn 5-8 | +0,91% (t 1,3) | +1,71% (t 1,5) | 3/6 | +1,8% / +3,4% | chưa qua |
| P2 mã vừa điều chỉnh 5 phiên hơn | **−0,94%** (t −2,2) | **−2,13%** (t −3,1) | 1/6 | −1,5% / −1,4% | **ngược chiều** |
| P3 mã mới vào top 8 (≤ 10 phiên) so với mã đã ở lâu (hai phía) | −1,55% (t −2,2) | −2,03% (t −1,6) | 5/6, 4/6 (lâu hơn) | −2,5% / −3,4% | **qua: mã ở lâu hơn** |
| P4 gần đỉnh 52 tuần hơn | +0,88% (t 1,7) | +0,84% (t 0,8) | 5/6, 3/6 | +3,5% / +4,2% | chưa qua |

**Theo hạng**, DEV. Đây là mô tả, không phải phép thử.

| hạng | 4 tuần: so với rổ | 4 tuần: lãi/lỗ sau phí | 8 tuần: so với rổ | 8 tuần: lãi/lỗ sau phí | 8 tuần: tỷ lệ lãi |
|---|---|---|---|---|---|
| 1-2 | +1,52% | +3,13% | +2,94% | +6,23% | 55% |
| 3-4 | +0,07% | +1,70% | +1,61% | +4,89% | 55% |
| 5-8 | −0,11% | +1,52% | +0,57% | +3,85% | 56% |
| 9-16 | −0,59% | +1,04% | −0,35% | +2,94% | 53% |
| 17-24 | −1,11% | +0,52% | −1,10% | +2,20% | 52% |
| 33+ | −1,53% | +0,12% | −2,02% | +1,30% | 50% |

**Gộp cả bốn** (hồi quy Fama-MacBeth trong top 8, `priority_joint.py`):

- Không tín hiệu nào tự đứng được khi có ba tín hiệu kia. Mạnh nhất là lãi 5 phiên gần
  nhất, t 1,95 ở 8 tuần.
- Cả bốn đo cùng một thứ: **độ bền của xu hướng**. Hạng cao, vừa tăng trong tuần, ở top
  8 lâu và gần đỉnh 52 tuần đều cùng chiều.
- Điều này khớp với hiệu ứng "frog in the pan" (Da, Gurun & Warachka 2014): động lượng
  đến từ nhiều bước nhỏ đều đặn thì bền hơn động lượng đến từ một cú nhảy.

**Quyết định.**

- P3 là giả thuyết duy nhất qua ngưỡng đăng ký trước, và holdout cùng chiều. Nó được đưa
  vào: **ưu tiên A** = nằm trong top 8 ở cả 11 phiên gần nhất; **B** = mới vào. Mua ít mã
  thì lấy A trước, trong mỗi nhóm theo hạng.
- Đây là thứ tự trong một tập, không phải luật mới. Tập mua vẫn là top 8 động lượng.
- Hiệu ứng nhỏ và không ổn định:
  - năm 2025 của DEV đi ngược (−5,5 / −8,7 điểm trong mô hình gộp);
  - tỷ lệ lãi của một mã lẻ vẫn chỉ ~55% ở mọi hạng.
- Vì vậy lời khuyên lớn hơn vẫn là **cầm vài mã**.
- P2 ngược chiều: mã vừa tăng trong tuần tốt hơn, chứ không phải mã vừa điều chỉnh. Kết
  quả này là post-hoc nên **không** đưa vào luật. Nó cũng không mâu thuẫn với vùng mua
  28/09: "mua sau một phiên mở cửa giảm ≥ 2%" là nói về *giá vào* của cùng một mã, không
  phải về việc *chọn mã nào*.

## 4. Luật bán cho từng vị thế (`exits.py`)

**Mô hình sổ.** Sổ 8 chỗ, tín hiệu ở giá đóng t, giao dịch ở giá mở t+1.

- Mỗi vị thế có đồng hồ riêng, tính từ ngày mua.
- Chỗ trống được lấp ngay phiên sau bằng mã tốt nhất chưa giữ, như Tom làm hằng ngày.
- Đồng hồ đợt đầu dịch 0, 2, …, 18 phiên, và kết quả là trung bình.

**Kiểm tra mô phỏng.** V0 trên toàn giai đoạn cho 30,5%/năm, Sharpe 1,09, sụt −47,6%.
Lab 28/09 cho 31,0%, 1,10, −47,5%.

**Ngưỡng nhận:** +1 điểm CAGR/năm, Sharpe không thấp hơn, và không tệ hơn V0 ở ≥ 4/6
năm.

DEV 2019-07 → 2025-09:

| biến thể (đăng ký trước) | CAGR | Sharpe | sụt tối đa | lệnh/năm | 2020 | 2021 | 2022 | 2023 | 2024 | 2025* |
|---|---|---|---|---|---|---|---|---|---|---|
| **V0 xem lại mỗi 20 phiên từ ngày mua, bán nếu ngoài top 16** | **33,0%** | **1,16** | −47,6% | 41 | 61,1 | 122,5 | −30,7 | 25,5 | 42,4 | 29,0 |
| V1 kiểm hạng mỗi ngày | 30,6% | 1,08 | −39,5% | 68 | 58,2 | 113,5 | −28,5 | 27,6 | 28,2 | 24,4 |
| V2 V0 + bán cứng ở phiên 40 | 26,5% | 0,98 | −48,1% | 108 | 49,5 | 110,5 | −35,2 | 24,2 | 28,9 | 31,3 |
| V3 V0 + chốt lời +20% | 25,1% | 0,98 | −46,0% | 74 | 43,7 | 93,8 | −32,2 | 26,8 | 28,2 | 27,6 |
| V4 V0 + chốt lời +30% | 27,7% | 1,03 | −48,0% | 61 | 49,7 | 95,5 | −33,2 | 25,9 | 39,0 | 27,3 |
| V5 V0 + cắt lỗ −10% | 35,4% | 1,20 | −45,4% | 63 | 59,8 | 114,9 | −24,8 | 28,4 | 52,1 | 25,0 |
| V6 V0 + cắt lỗ −15% | 32,5% | 1,14 | −44,3% | 55 | 53,0 | 120,0 | −28,9 | 23,4 | 46,5 | 29,4 |

\* 2025 tới 15/09. VNINDEX cùng kỳ: 9,5%/năm.

**Đọc bảng:**

- **Giá mua không nên quyết định bán.** Chốt lời cắt đúng những mã đang chạy, mà động
  lượng kiếm tiền chính từ những mã đó: mất 5-8 điểm/năm.
- **Cắt lỗ −10%** cao hơn V0 2,4 điểm, nhưng không qua ngưỡng: tệ hơn ở 3/6 năm (2020,
  2021, 2025), và mức −15% ngay cạnh đó không giúp gì. Một lợi thế thật thường không
  biến mất khi chỉ nới ngưỡng thêm 5 điểm. Tài liệu có kết quả tương tự (Han, Zhou & Zhu
  2016: cắt lỗ 10% làm động lượng Mỹ ít sập hơn), nên kết quả này đáng theo dõi bằng dữ
  liệu thật, nhưng chưa đủ để thành luật.
- **Bán cứng ở phiên 40** (cảnh báo "quá hạn" của bản tin trước hôm nay) mất 6,5
  điểm/năm. Mã còn mạnh sau 8 tuần là đúng loại mã luật động lượng muốn giữ. Cảnh báo
  này đã bỏ.
- **Kiểm hạng mỗi ngày** sụt ít hơn (−39,5% so với −47,6%) nhưng lãi ít hơn 2,4 điểm và
  giao dịch nhiều gấp 1,7 lần. Không đổi.

**Quyết định:** giữ V0, và chạy nó theo **đồng hồ của từng vị thế**.

## 5. Cái gì đổi trong hệ thống

- **Danh sách mua** trên bản tin 17:30, email 17:00 và Daily Insight: cột **ưu tiên A/B**,
  A lên trước.
  - Tính từ `TickerRow.momentum_hist`, tức điểm động lượng 11 phiên gần nhất.
  - `buy_layer.top_runs` đếm số phiên liên tục trong top 8.
  - Snapshot cũ chưa có lịch sử thì cột ghi "—" và thứ tự giữ theo hạng.
- **Kết luận cho từng mã đang giữ** (`sell_range.schedule` + `verdict`): **GIỮ** / **BÁN
  ATO …** / **CHƯA XẾP ĐƯỢC**, kèm lý do. Mục 1 của bản tin là việc cần làm hôm nay.
  - Có ngày mua: quyết định ở giá đóng phiên thứ 19, 39, 59… sau ngày mua, bán ATO phiên
    kế nếu ngoài top 16.
  - Một kỳ bán bị lỡ được đọc lại từ kho `data/watch/`. Nếu job hôm đó không chạy thì
    trong 2 phiên dùng hạng hôm nay.
  - Chưa có ngày mua: xét theo hạng hôm nay.
  - Mã ngoài rổ: **hạng tương đương**, tức chỗ nó sẽ đứng với cùng điểm động lượng.
    Holdings cache nay lưu cả `momentum`.
  - Lãi/lỗ so với giá mua được in ra, nhưng không quyết định bán.
- **Bỏ:** cửa sổ 20-40 phiên như luật bán, cảnh báo "quá hạn", "trong cửa sổ bán" và
  "nhả quá sâu". Cả bốn thuộc luật quá bán cũ. Range ±1×ATR quanh đỉnh vẫn còn, làm
  tham chiếu để chọn giá bán.
- **Sổ:**
  - `record_buy` cộng dồn theo giá vốn bình quân, giữ ngày của lần mua đầu;
  - `close_position(qty=…)` bán một phần;
  - API `POST /api/state/positions/{mã}/buy`;
  - CLI `python -m daily_watch.book buy|sell|date|show`.

## 6. Tái lập

```bash
python docs/reviews/workflow_study_2026-09-29/priority.py        # P1-P4, DEV (holdout: out/)
python docs/reviews/workflow_study_2026-09-29/priority_joint.py  # Fama-MacBeth, DEV
python docs/reviews/workflow_study_2026-09-29/exits.py dev       # V0-V6, DEV
```

## 7. Còn mở

- **Nhật ký mua bán thật của Tom là phép thử ngoài mẫu tốt nhất.** Nó chấm cả luật, cả
  thứ tự ưu tiên, cả việc Tom có theo luật hay không.
- Cắt lỗ −10%: đo lại khi có thêm một năm dữ liệu. Nếu nó thắng lại thì đề xuất cho Tom
  quyết.
- Chấm ngoài mẫu `daily_watch/audit.py --hold 40`, khoảng cuối 11/2026, như cũ.

Đây là phân tích dữ liệu của hệ thống, không phải tư vấn đầu tư.
