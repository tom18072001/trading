# Nghiên cứu luật mua — 2026-09-28

> Tom, 28/09: *"Cả luật chọn (cổng SMA200 rồi xếp hạng) đo được 7,2%/năm nếu giữ
> 20 phiên và 11,7%/năm nếu giữ 40 phiên. Cả hai mức đều thấp hơn VNINDEX cùng kỳ
> (17,5%/năm). Nếu như thế này thì không ổn, tôi cần bạn tối ưu hơn, mức kỳ vọng
> của tôi là 20-30% năm"* và *"tôi cho bạn toàn quyền quyết định"*. Cùng ngày:
> *"tạo layer nữa dựa vào phân tích, gợi ý nên mua gì, accept range, expect lên
> bao nhiêu trong các chu kỳ 4 tuần 8 tuần"*.
>
> Bộ script tái lập: `docs/reviews/strategy_study_2026-09-28/`. Không phải lời
> khuyên đầu tư — mọi con số là phân phối đo được trên dữ liệu quá khứ.

## Tóm tắt

1. **Luật cũ hỏng ở gốc, không phải ở tham số.** Nó xếp mã bằng một tín hiệu
   1-3 ngày (RSI2 quá bán, nhịp giảm hôm nay tính theo ATR) rồi giữ 4-8 tuần.
   Trên 2019-07 → 2026-09, top-5 của nó làm được **4,6%/năm**. Cùng kỳ VNINDEX
   làm 8,9%/năm, còn rổ 75 mã chia đều làm 13,1%/năm.
2. **Luật mới** xếp theo **lãi 6 tháng (bỏ tuần gần nhất) chia cho biến động
   của chính mã đó**.
   - Mua 8 mã đầu, chia đều. Xem lại mỗi 4 tuần; mã còn trong top 16 thì giữ.
   - Cùng kỳ 2019-07 → 2026-09: **31%/năm**, VNINDEX 8,9%.
   - Vượt VNINDEX 7/8 năm dương lịch, vượt rổ chia đều 7/8 năm.
   - Cái giá: năm 2022 lỗ **−31%**, sụt giảm tối đa **−47%**.
3. **Con số 31% là lạc quan**, vì ba lý do:
   - rổ 75 mã được chọn năm 2026, nên toàn mã sống sót;
   - luật được chọn trên chính dữ liệu này, trong khoảng **394 biến thể**;
   - 2020-2021 đóng góp phần lớn.

   Riêng 2022-01 → 2026-09, luật làm **14,3%/năm**, VNINDEX 3,7%. Kỳ vọng trung
   thực là **VNINDEX + khoảng 10 điểm %/năm, dao động rất lớn**. 20-30%/năm là
   mức của năm tốt, không phải năm nào cũng đạt.
4. **Kiểm tra ngoài mẫu làm đổi quyết định.**
   - Luật tôi chọn trước trên dữ liệu 2019-07 → 2025-09 có thêm một **công tắc
     thị trường**: ra tiền mặt khi VNINDEX thủng 97% SMA200.
   - Trên 12 tháng để riêng (16/09/2025 → 28/09/2026), luật đó **lỗ 21,5%**,
     trong khi VNINDEX **lãi 5,9%**. Công tắc bị bỏ.
   - Luật không công tắc làm **−3%** nếu bắt đầu từ tiền mặt ngày 16/09/2025, và
     **+16,5%** nếu đã chạy liên tục từ 2019.
   - Walk-forward (mỗi 6 tháng chọn lại luật theo quá khứ): 22-29%/năm trên
     2021-2026.
5. **Đã ship** thành luật chung của Daily Insight, email 17:00 và bản theo dõi
   17:30, kèm **layer mới**: vùng giá chấp nhận, và dải kết quả 4/8 tuần đo được
   cho từng mã. Luật cũ vẫn được ghi vào kho mỗi ngày như một bóng, để
   `daily_watch/audit.py` chấm hai luật trên dữ liệu chưa từng dùng để chọn.

## 1. Dữ liệu và thước đo — cố định trước khi xem kết quả

- **Panel giá.** `data/price_panel.db`, dựng lại tối 28/09 bằng
  `build_price_panel.py --start 2017-01-01`. Gồm 143 mã và ^VNINDEX, nguồn KBS
  (giá điều chỉnh). Bản cộng đồng chỉ cho 8 năm, nên cổ phiếu và VNINDEX cùng bắt
  đầu từ 2018-10-01.
- **Universe.**
  - U75 là 75 mã rổ ngành (`config.PROXY_BASKETS`), đúng tập mà snapshot live
    xếp hạng.
  - U143 là cả panel.
  - Cả hai đều lọc thanh khoản trung bình 20 phiên ≥ 5 tỷ/ngày.
- **Khớp lệnh.** Tín hiệu lấy ở giá đóng phiên t; mua và bán ở giá mở phiên t+1
  (ATO).
- **Chi phí.** 0,15% phí mỗi chiều + 0,3% trượt giá mỗi chiều + 0,1% thuế khi
  bán, tức **1,0%/vòng**. Đây là mô hình của `analysis.bench`, và vẫn là phía nhẹ
  so với thực tế: phí VPS 0,2%.
- **Danh mục.** K mã chia đều, xem lại mỗi R phiên. Mã đang giữ còn trong top
  K + buffer thì giữ, không tốn phí; tiền từ mã bán ra chia cho mã mới, mỗi mã
  tối đa 1/K vốn.
- **Pha chu kỳ.** Kết quả là trung bình trên nhiều ngày bắt đầu chu kỳ, vì một
  danh mục 8 mã xem lại mỗi 20 phiên chỉ có vài lần rút mẫu mỗi năm. Khoảng
  giữa pha tốt nhất và xấu nhất được in kèm; ở luật chọn nó là 34,1-35,5%.
- **Chia dữ liệu.**
  - DEV (2019-07-01 → 2025-09-15) dùng để chọn luật.
  - HOLDOUT (2025-09-16 → 2026-09-28) chỉ đọc **một lần**, cho luật đã chọn.
- **Mốc so sánh.** VNINDEX mua và giữ trên cùng các ngày (chỉ số giá, không cổ
  tức), và rổ chia đều (không phí), để tách phần "chọn mã" khỏi phần "thị
  trường".

## 2. Tìm kiếm: 394 biến thể, tất cả trên DEV

| bước | cái gì thay đổi | số biến thể |
|---|---|---|
| 1 | 20 họ tín hiệu × có/không cổng SMA200, K10 R20, panel ngắn 2023-01 → 2025-09 | 50 |
| 2a | 7 họ tốt nhất × cổng × 5 cách lọc thị trường, panel ngắn | 76 |
| a | 20 họ × cổng × U75/U143, panel dài 2019-07 → 2025-09 | 86 |
| b | 6 họ tốt nhất × 7 cách lọc thị trường × U75/U143 | 90 |
| c | 3 ứng viên × K (5/8/10/15) × R (20/40) × buffer | 72 |
| — | kiểm tra độ bền: trễ 1 phiên, phí ×2, chia giai đoạn, tham số lân cận | 20 |

Bước 1 và 2a chạy trên panel cũ (từ 2022) trước khi panel được mở rộng. Chúng
chỉ dùng để khoanh vùng và không nằm trong bộ script (dữ liệu nền đã thay).

**Kết quả chính** (panel dài, U75, K8 R20, buffer 8, sau phí):

- **Động lượng 6 tháng chia biến động (`ramom126`)** tốt và đều nhất.
- Cả vùng lân cận của nó đều tốt: lookback 126-250 phiên cho 30-36%/năm.
- Đổi K, R hay buffer, Sharpe đều nằm trong khoảng 1,3-1,6 (có công tắc).
- Mua trễ 1 phiên: 34,4%, gần như không đổi (34,9%).
- Nhân đôi trượt giá: 33,2%, vì vòng quay chỉ ~4,4 lần/năm.
- **Các họ khác thì kém:**
  - Đảo chiều ngắn hạn (lãi 5 ngày âm) và dòng tiền theo khối lượng (`vratio`)
    thua cả rổ chia đều.
  - Đỉnh 52 tuần và biến động thấp cho lợi nhuận thấp hơn.

## 3. Holdout — vì sao luật ship khác luật chọn trên DEV

Trên DEV, luật tốt nhất có thêm **công tắc thị trường**: vào khi VNINDEX trên
SMA200, ra hết khi VNINDEX dưới 97% SMA200. Nó cho 34,9%/năm, Sharpe 1,54 và sụt
tối đa −28%, gần như toàn bộ nhờ tránh được năm 2022.

Holdout (16/09/2025 → 28/09/2026), đọc một lần, bắt đầu từ tiền mặt:

| | tổng lãi 12 tháng | Sharpe | sụt tối đa |
|---|---|---|---|
| luật chọn trên DEV (có công tắc) | **−21,5%** | −0,74 | −30% |
| cùng luật, không công tắc | −3,0% | 0,04 | −24% |
| VNINDEX | +5,9% | 0,38 | −16% |
| rổ 75 mã chia đều | −10,3% | −0,45 | −22% |

Điều đã xảy ra trong 12 tháng này:

- **Thị trường hẹp.** VIC +244%, BSR +93%, VHM +41%, trong khi mã trung vị của
  rổ **−12,5%**; chỉ 32% số mã tăng. VNINDEX tăng là nhờ VIC.
- **Công tắc bị giật hai lần.**
  - Tháng 3/2026: ra ngày 24/03, vào lại 26/03.
  - Tháng 7/2026: ra ngày 23/07, vào lại 05/08.
  - Mỗi lần mất một vòng phí và bỏ lỡ nhịp hồi.

**Quyết định:** bỏ công tắc, và ship luật không có nó.

Quyết định này được đưa ra **sau khi đọc holdout**, nên con số holdout của luật
ship (−3% đến +16,5%) không còn là số ngoài mẫu sạch. Hai bằng chứng khác đỡ
cho quyết định:

- Luật không công tắc vượt rổ chia đều ở **7/8 năm**, và vượt VNINDEX ở 7/8 năm.
- Trên toàn giai đoạn, Sharpe của hai phiên bản gần nhau (1,10 và 1,22). Công
  tắc chỉ đổi lợi nhuận lấy sụt giảm qua một sự kiện duy nhất là 2022, rồi thua
  trong 2 trên 3 năm gần nhất.

Thông tin thị trường vẫn được in ra, như bối cảnh chứ không phải lệnh: mã mới mua
khi VNINDEX dưới SMA200 chỉ có khoảng 1/3 lợi thế (mục 5).

## 4. Theo năm, và walk-forward

Chạy liên tục từ 2019-07, sau phí (%):

| | 2019* | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|
| **luật mới (ship)** | 1,5 | 63,0 | 122,4 | −30,6 | 25,5 | 43,3 | 56,0 | −3,2 |
| luật mới + công tắc | 1,5 | 52,9 | 132,0 | 13,3 | 5,9 | 26,6 | 38,1 | −25,7 |
| luật cũ, top-5 | −4,0 | 12,8 | 41,7 | −35,9 | 14,9 | 26,7 | 17,6 | −17,9 |
| VNINDEX | −0,5 | 14,9 | 35,7 | −32,8 | 12,2 | 12,1 | 40,9 | −0,2 |
| rổ 75 mã chia đều | −3,5 | 32,3 | 71,4 | −32,5 | 30,5 | 15,9 | 15,6 | −6,5 |

\* 2019 từ tháng 7; 2026 tới 28/09.

Toàn giai đoạn 2019-07 → 2026-09:

- luật mới: **31,0%/năm**, Sharpe 1,10, sụt tối đa −47,5%;
- luật cũ: 4,6%/năm;
- VNINDEX: 8,9%/năm;
- rổ chia đều: 13,1%/năm.

**Walk-forward** kiểm tra cả *quy trình* chứ không chỉ một luật.

- Cách làm: cứ 6 tháng, chọn trong một thực đơn cố định 14 luật cái có Sharpe
  quá khứ tốt nhất, rồi giao dịch nó 6 tháng tiếp theo, trừ 1% mỗi lần đổi.
- Kết quả trên 2021-01 → 2026-09:
  - nhìn lại 12 tháng: **23,4%/năm**;
  - nhìn lại 24 tháng: **28,7%**;
  - nhìn lại toàn bộ: **22,3%**;
  - cùng kỳ VNINDEX 8,8%, rổ chia đều 7,4%.
- Hạn chế: thực đơn được soạn *sau* khi xem DEV, nên walk-forward cũng lạc quan.
  Điều nó cho thấy là "luôn chọn một biến thể động lượng" không phải may một lần.

## 5. Layer: nên mua gì, giá nào, kỳ vọng bao nhiêu

Đo bằng `layer.py` trên mọi phiên 2019-07 → 2026-08. Mỗi mã trong top 8 ở giá
đóng phiên t được mua ở ATO phiên t+1 và bán ở giá đóng t+20 / t+40, trừ 1% phí.
Có khoảng 14.000 lượt mã-ngày cho mỗi khung giữ.

| giữ | trung vị | trung bình | P25 | P75 | xác suất lãi |
|---|---|---|---|---|---|
| 4 tuần (20 phiên) | +0,1% | +1,5% | −6,5% | +7,9% | 50% |
| 8 tuần (40 phiên) | +1,0% | +3,9% | −8,4% | +12,4% | 53% |

**Đọc bảng trên thế nào:**

- **Một mã lẻ gần như lời lỗ chia đôi.** Lợi thế nằm ở đuôi phải (mã thắng chạy
  xa), ở cả rổ, và ở việc giữ mã còn mạnh.
- **Cả rổ 8 mã**, trên mọi cửa sổ 2019-07 → 2026-09:
  - 4 tuần: trung vị +2,7% (P25 −2,3%, P75 +9,1%), lãi 64% số lần;
  - 8 tuần: trung vị +3,9% (−2,6% … +14,6%), lãi 64%, vượt VNINDEX 63% số lần.
- **Lợi thế so với một mã thanh khoản bất kỳ, trước phí:**
  - ~1,1% mỗi 4 tuần, ~2,1% mỗi 8 tuần;
  - khi VNINDEX **dưới** SMA200 chỉ còn khoảng 1/3: 8 tuần +0,8%, so với +2,8%
    khi trên.

**Vùng mua** = [giá tham chiếu × (1 − 2σ), giá tham chiếu × 1,01], với σ là biến
động ngày 63 phiên của mã đó.

- **Mức trên.** Trả thêm x% trên giá tham chiếu làm mất đúng x% lợi thế:
  - ở +1%, lợi thế 4 tuần so với mặt bằng còn −0,9% sau phí;
  - ở +1%, lợi thế 8 tuần còn +0,1%.
- **Mức dưới** không phải stop. Mã mua sau một phiên mở cửa giảm ≥ 2% cho kết quả
  **tốt hơn** (+3,0% so với mặt bằng trong 4 tuần, n = 717). Mức dưới chỉ là hai
  phiên dao động bình thường; thấp hơn thì chờ danh sách phiên sau.

**Kỳ vọng từng mã.**

- Cách tính: phân phối chuẩn hoá z = lãi / (σ × √phiên), đo riêng cho VNINDEX
  trên hoặc dưới SMA200, rồi co giãn theo σ của chính mã đó.
- Hiệu chỉnh: ở cả ba nhóm biến động, 47-52% số mã rơi vào đúng khoảng
  P25-P75 dự đoán cho chúng.
- Code: `services/buy_layer.py` (`Z`, `EDGE`, `BOOK`, `outlook`, `accept_range`).

## 6. Hôm nay (28/09/2026) theo luật mới — từ panel

VNINDEX 1.780,7 nằm **dưới** trung bình 200 phiên 1.795,4 (−0,8%). Top 8 trong 54
mã đủ điều kiện:

1. VIC — 6 tháng +80,8%
2. HCM — +33,2%
3. QNS — +11,1%
4. VHM — +39,9%
5. NTP — +18,1%
6. BMP — +21,3%
7. VJC — +15,8%
8. BSR — +17,1%

Danh sách live có thể lệch nhẹ vì snapshot còn lọc room khối ngoại. Bản theo dõi
17:30 và Daily Insight in danh sách chính thức, kèm vùng mua và kỳ vọng.

## 7. Giới hạn — đọc trước khi tin các con số

- **Survivorship.** Rổ 75 mã là rổ của năm 2026, và mọi luật đều được lợi từ nó.
  Rổ chia đều chỉ làm 13%/năm, cho thấy lợi thế đó có nhưng không lớn; phần vượt
  của động lượng so với rổ mới là phần đáng tin hơn.
- **Chọn nhiều lần.** 394 biến thể trên DEV. Vùng lân cận ổn định (mục 2) và 7/8
  năm vượt rổ giúp đỡ phần nào, nhưng với ~20 họ tín hiệu, "7/8 năm" vẫn có thể có
  phần may.
- **Holdout chỉ 12 tháng**, và đã bị dùng một lần để ra quyết định (mục 3).
- **Phí thật cao hơn mô hình.** Ở VPS 0,2%/chiều thay vì 0,15%, luật mất thêm
  ~0,2 điểm %/năm. Mức mất nhỏ vì vòng quay thấp: giá trị mua cộng bán chỉ khoảng
  4,5 lần vốn mỗi năm.
- **Mất 2022 là chuyện có thể lặp lại.** Không công tắc, một năm như 2022 là −30%
  hoặc hơn. Người không chịu được mức đó nên giảm tỷ trọng, hoặc giữ phần lõi
  bằng ETF chỉ số.

## 8. Tái lập

```
python scripts/build_price_panel.py --start 2017-01-01     # ~8 phút, 18 lệnh/phút
cd docs/reviews/strategy_study_2026-09-28
python study.py a      # họ tín hiệu × cổng × universe
python study.py b ramom126,c_ramom_hi_obv,mom126_5,c_multi_mom,c_mom_lowvol,c_mom_lowvol+G
python study.py c      # K × R × buffer
python robust.py       # độ bền, vẫn trên DEV
python holdout.py      # MỘT lần
python walkforward.py
python layer.py        # bảng của services/buy_layer.py
python final.py        # bảng mục 3-4
python benchmark.py    # mục 9: so benchmark, kiểm tra mục tiêu 20-30%/năm
```

## 9. Kiểm tra mục tiêu 20-30%/năm — 2026-09-29

Tom: *"so sánh benchmark và kiểm tra đạt target 20%-30%/năm chưa"*. Số từ
`benchmark.py`, trên panel tới 28/09/2026, luật chạy liên tục từ 2019-07, sau phí 1%/vòng.

**Theo cửa sổ, tới 28/09/2026 (%/năm):**

| bắt đầu | luật mới | VNINDEX | rổ chia đều | luật cũ | mục tiêu |
|---|---|---|---|---|---|
| 2019-07 (7,2 năm) | 31,0 | 8,9 | 13,1 | 4,6 | vượt |
| 2021-01 (5,7 năm) | 28,8 | 8,8 | 11,9 | 4,4 | đạt |
| 2022-01 (4,7 năm) | 14,5 | 3,8 | 2,1 | −2,2 | **chưa** |
| 2023-01 (3,7 năm) | 31,2 | 16,7 | 14,3 | 9,7 | vượt |
| 2024-01 (2,7 năm) | 33,2 | 18,4 | 8,7 | 7,7 | vượt |
| 12 tháng gần nhất | 16,5 | 5,6 | −10,1 | −22,6 | **chưa** |
| 2026 tới nay | −3,2 (tổng) | −0,3 | −6,5 | −17,9 | **chưa** |

**Phân phối:**

- Mọi cửa sổ 12 tháng:
  - trung vị +36,6%;
  - ≥ 20% ở 63% số cửa sổ;
  - rơi đúng vào 20-30% chỉ 9% số cửa sổ;
  - âm ở 20% số cửa sổ;
  - thắng VNINDEX ở 86% số cửa sổ.
- Mọi cửa sổ 3 năm: CAGR trung vị 31,7% (thấp nhất −6,9%, cao nhất 59,9%); ≥ 20%/năm ở
  74% số cửa sổ. Cùng thước đó, VNINDEX chỉ đạt ở 6% số cửa sổ.
- Bắt đầu từ tiền mặt vào đầu mỗi quý (25 ngày, 2019-07 → 2025-07) rồi giữ tới hôm nay:
  - CAGR trung vị 28,8%;
  - thấp nhất 9,4% (bắt đầu 04/2022), cao nhất 44,6%;
  - ≥ 20%/năm ở 76% số ngày bắt đầu;
  - thắng VNINDEX ở 88%.

**Kết luận.**

- Trong backtest, luật mới đạt hoặc vượt mục tiêu trên đa số cửa sổ nhiều năm, nhưng không
  phải năm nào.
  - Lợi nhuận năm rất phân tán: hiếm khi rơi đúng vào 20-30%, thường cao hơn nhiều hoặc
    thấp hơn nhiều.
  - Mục tiêu có ý nghĩa như một **trung bình nhiều năm**, không phải một lời hứa cho từng
    năm.
- Ngoài mẫu, luật **chưa** đạt mục tiêu:
  - 12 tháng để riêng cho kết quả từ −3% (bắt đầu từ tiền mặt) đến +16,5% (chạy liên tục);
  - chưa có ngày chạy thật nào (luật bắt đầu chạy 29/09/2026).
- Số trong mẫu còn lạc quan thêm vì hai lý do:
  - rổ chọn năm 2026 và 394 biến thể thử (mục 7);
  - giá cổ phiếu KBS đã điều chỉnh cổ tức, còn VNINDEX là chỉ số giá — khoảng 1,5-2 điểm
    %/năm lệch về phía luật.
- Kỳ vọng dùng để lập kế hoạch vẫn là **VNINDEX + ~10 điểm %/năm**. Với VNINDEX dài hạn
  ~9-10%/năm, con số đó nằm ở cận dưới của 20-30%.
- Phép kiểm tra thật đầu tiên là `daily_watch/audit.py --hold 40`, khoảng cuối 11/2026.
  Muốn kết luận về một mục tiêu theo năm thì cần 1-2 năm chạy thật.
