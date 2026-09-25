# Review thuật toán — 2026-09-24

> **Phạm vi.** Toàn bộ thuật toán đang chạy. Đào sâu phần sinh ra thứ Tom giao
> dịch hằng ngày: chấm điểm mã, blend OBV, bộ lọc universe, khuyến nghị bán.
> Tầng ngành (ranker, regime, stealth, backtest) được kiểm lỗi và so với base rate.
>
> **Không sửa code production** — Tom chọn "báo cáo + đo". Mọi con số được đo
> lại trên `data/price_panel.db` (143 mã, 2022-01-04 → 2026-09-15, có
> `^VNINDEX`) và `vnstock_market.db` (bản 2026-09-24). Script tái lập nằm ở
> `docs/reviews/algo_review_2026-09-24/` (xem Phụ lục). Mọi số của picks đã được
> một agent kiểm độc lập (tự viết lại harness), lệch ≤ 0,03 điểm %/lệnh.
>
> Đây là phân tích dữ liệu lịch sử, không phải tư vấn đầu tư. Các quyết định
> ở §8 là của Tom.

---

## 0. Đọc nhanh

1. **Thước đo đang phóng đại edge của picks.** Chấm lại cho đúng thì **không
   luật nào dương đủ mọi năm**, kể cả `X_prop_obv`. Chấm đúng nghĩa là: một base
   NO GATE cho mọi luật, chấm mọi phiên, t-stat Newey-West, và mô phỏng thành danh
   mục cùng ngày với VNINDEX. Câu "1/41 factor sống sót" (§26.9) sinh ra từ hai
   lựa chọn trong bench, và phải có **cả hai** mới lật được năm 2023:
   - factor có cổng SMA200 được so với base cũng có cổng;
   - bench bỏ các phiên có dưới 30 mã trên SMA200 — đúng những phiên luật này
     thua nặng.
2. **Luật đang ship chưa từng được đo đúng như ship, và ngưỡng `MIN_BUY_SCORE`
   = 2,5 làm nó tệ đi.**
   - Luật như ship thắng chọn ngẫu nhiên +0,29%/lệnh ở khung 20 phiên (t 0,86)
     và +0,62% ở 40 phiên (t 1,06), **âm năm 2023** ở cả hai khung.
   - Giữ cổng SMA200 nhưng bỏ ngưỡng 2,5 thì được +0,69% (t 1,55) và +1,02%
     (t 1,93), năm 2023 xấp xỉ 0.
   - Ngưỡng này chưa từng được đo lợi nhuận. Đo rồi thì nó tốn ~0,4%/lệnh.
3. **Như một danh mục, mọi cấu hình đều thua VNINDEX** trên 2023-01 → 2026-09.

   | | giữ 20 phiên | giữ 40 phiên | VNINDEX |
   |---|---|---|---|
   | lợi nhuận/năm, luật ship | 2,7% | 9,3% | 17,5% |
   | lợi nhuận/năm, bỏ ngưỡng 2,5 | 7,2% | 11,7% | 17,5% |
   | Sharpe | ≤ 0,65 | ≤ 0,65 | 0,98 |
   | MaxDD | −28 đến −31% | −28 đến −29% | −18% |

   - Khoảng cách dồn gần hết vào **2025**: VNINDEX +40,9% nhờ vài mã vốn hoá
     lớn. Năm 2024 picks thắng; 2023 xấp xỉ hoà.
   - Survivorship và chi phí nhẹ đều đang làm đẹp picks, nên kết luận "thua
     index" là phía thận trọng.
4. **Thứ dịch chuyển kết quả là cấu trúc, không phải công thức:**
   - **Giữ tới ~40 phiên.** Phiên 20 không phải tín hiệu bán: 9,3% vs 2,7%/năm.
   - **Bỏ ngưỡng 2,5**: +2,4 điểm %/năm ở 40 phiên. Nếu giữ ngưỡng thì
     **phiên không có mã nào nên mua ETF chỉ số** thay vì để tiền mặt: +1,4 điểm
     %/năm, tốt hơn ở mọi năm.
   - **Bán ở phiên ATO ngày thoát**: +0,06 đến +0,09%/lệnh.
5. **Tầng ngành đang phát tín hiệu từ dữ liệu hỏng:**
   - ranker chấm trên số 0 từ 2026-08-25;
   - ATR ngành nhỏ đúng 5 lần (bị chia n hai lần);
   - `close_idx` nhảy +62% rồi −39% khi rổ thiếu mã;
   - `macro_anchors` có 613 dòng VNINDEX = 1,82, và regime ngày 2026-09-22
     được publish từ chính các dòng đó.

   **Kể cả khi dữ liệu sạch**, ranker, regime và cổng stealth đều không có edge
   out-of-sample. Email 17:00 lại dùng ranker làm **cổng cứng** cho danh sách mua.
6. **ML ensemble (plan đang chờ):** lợi thế so với thứ đang ship không phân biệt
   được với 0 (t 1,7 ở 20 phiên, −0,3 ở 40). Đừng dựng production; nếu muốn biết
   thì chạy shadow test đăng ký trước (§5).
7. **Đã kiểm và đúng** (chi tiết §7):
   - không feature nào nhìn trước;
   - score và blend production khớp bench từng số;
   - phí, thuế, T+2 đúng; purge/embargo 22 phiên đúng;
   - posterior HMM là filtered (causal);
   - `foreign_net` đúng đơn vị và dấu.

---

## 1. Cách đo lại, và vì sao ra số khác bench cũ

| điểm | bench cũ (`scripts/ticker_alpha_bench.py`) | đo lại | hệ quả |
|---|---|---|---|
| **base rate** | mỗi factor một base: factor có cổng SMA200 bị so với **chính các mã trên SMA200** (`evaluate()`, `m = row_s.notna() & …`) | **một** base NO GATE cho mọi luật: mọi mã đủ thanh khoản cùng phiên | §16.12 định nghĩa NO GATE là toàn panel. Base có cổng xoá luôn phần đóng góp của chính cái cổng |
| **phiên được chấm** | bỏ phiên có dưới 30 mã *trong cross-section của factor* (`min_names=30`). Với factor có cổng là bỏ **109/898 phiên** từ 2023: 51 phiên năm 2023, 1 năm 2024, 17 năm 2025, 40 năm 2026 | chấm mọi phiên có ≥ 30 mã đủ thanh khoản | phiên bị bỏ là nhịp thị trường yếu, mà production **vẫn ra shortlist** những ngày đó (2026-09-23: 1 mã, GAS) |
| **t-stat** | IC t coi các cửa sổ 20 phiên chồng nhau là độc lập | Newey-West, lag = h | IC t giảm ~3 lần (thứ tự ship: 6,1 → 2,2 trên tập ngày của thí nghiệm ML). Excess t ≈ 1 |
| **so với VNINDEX** | quy năm số học (%/lệnh × số vòng) so với hằng số `VNINDEX_CAGR = 0,157` | danh mục staggered (Jegadeesh-Titman): mỗi phiên mở 1/(h+1) vốn, giữ h phiên → đường vốn ngày → CAGR/Sharpe/MaxDD **cùng ngày** với VNINDEX | 9,3% vs 17,5%, chứ không phải 11,7% vs 15,7% |
| **luật được chấm** | `X_prop_obv`: top-5 theo blend, **không** có ngưỡng `MIN_BUY_SCORE` | luật như ship: điểm ≥ 2,5 → blend trên cả universe (kể cả mã bị sàn −20) → top-5 | ngưỡng 2,5 chưa từng được đo (§2.2) |

**Tách hai hiệu ứng** trên `X_prop_obv`, khung 20 phiên, năm 2023 — năm quyết
định pass/fail:

| cách chấm | excess 2023 |
|---|---|
| bench cũ: base có cổng, bỏ phiên có dưới 30 mã trên SMA200 | **+0,39** |
| chỉ đổi base sang NO GATE | +0,36 |
| chỉ chấm mọi phiên, base có cổng | +0,07 |
| **cả hai: base NO GATE, mọi phiên** | **−0,21** |
| riêng các phiên bị bỏ trong 2023, so với NO GATE | −2,41 (40 phiên: −4,93) |

Trên những phiên bị bỏ, base NO GATE cao bất thường: +1,86%/20 phiên, so với
+0,95% ở các phiên được chấm. Đó là các nhịp hồi sau khi thị trường giảm, khi mã
bị đạp mạnh hồi nhanh nhất — còn cổng SMA200 thì chỉ cho mua mã *chưa* bị đạp.

---

## 2. Picks mã — đo lại

### 2.1 Bảng chính

Quy ước: vào lệnh ở giá mở phiên sau, top-5, chi phí 1,00%/vòng, từ 2023.
Excess là %/lệnh so với NO GATE (trước phí — phí triệt tiêu trong hiệu số).
"vs VNI" là so với VNINDEX cùng cửa sổ, trước phí. Danh mục là staggered, để
tiền mặt khi không có mã, tính **sau** phí.

| luật | h | excess | NW t | 2023 | 2024 | 2025 | 2026 | vs VNI | CAGR | Sharpe | MaxDD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **đang ship** | 20 | +0,29 | 0,86 | **−0,90** | +0,88 | +0,77 | +0,45 | +0,18 | 2,7% | 0,24 | −30,5% |
| **cổng SMA200, bỏ ngưỡng 2,5** | 20 | +0,69 | 1,55 | −0,07 | +0,90 | +1,10 | +0,90 | +0,55 | 7,2% | 0,44 | −27,9% |
| `X_prop_obv` (bench twin) | 20 | +0,44 | 1,09 | −0,21 | +0,82 | +0,68 | +0,50 | +0,31 | 4,8% | 0,33 | −28,8% |
| `P2` (điểm, không OBV) | 20 | +0,11 | 0,37 | −0,91 | +0,56 | +0,71 | +0,07 | −0,02 | 1,6% | 0,18 | −30,5% |
| `V_obv_trend` (OBV, không cổng) | 20 | +1,22 | 1,61 | −0,42 | +1,07 | +2,43 | +2,18 | +1,09 | 12,8% | 0,62 | −28,7% |
| `S_small_size` | 20 | +0,60 | 1,13 | +1,01 | +0,60 | +1,44 | **−1,48** | +0,47 | 6,9% | 0,42 | −34,2% |
| NO GATE (mọi mã đủ thanh khoản) | 20 | 0 | — | — | — | — | — | — | 0,1% | 0,11 | −32,1% |
| **đang ship** | 40 | +0,62 | 1,06 | **−1,55** | +1,84 | +0,89 | +1,79 | +0,38 | 9,3% | 0,58 | −29,1% |
| **cổng SMA200, bỏ ngưỡng 2,5** | 40 | +1,02 | 1,93 | −0,21 | +1,25 | +1,81 | +1,39 | +0,77 | 11,7% | 0,65 | −27,7% |
| `X_prop_obv` | 40 | +0,66 | 1,20 | −0,51 | +1,18 | +1,21 | +0,88 | +0,42 | 10,0% | 0,58 | −28,2% |
| `V_obv_trend` | 40 | +1,47 | 1,50 | −0,40 | +0,66 | +4,09 | +1,57 | +1,22 | 13,7% | 0,68 | −28,9% |
| `S_small_size` | 40 | +1,47 | 1,31 | +2,40 | +2,12 | +1,55 | **−1,70** | +1,22 | 15,5% | 0,79 | −28,3% |
| `M_ivol_low` | 40 | +0,33 | 0,61 | −1,23 | +0,51 | +1,09 | +1,51 | +0,08 | 9,1% | 0,62 | −17,7% |
| NO GATE | 40 | 0 | — | — | — | — | — | — | 7,0% | 0,43 | −28,9% |

**VNINDEX mua & giữ**, cùng giai đoạn: **CAGR 17,5%, Sharpe 0,98, MaxDD −18,1%**.
Theo năm: +12,2% (2023), +12,1% (2024), +40,9% (2025), +1,5% (2026, tới 09-15).

Luật ship ở 40 phiên theo năm, so với VNINDEX:

| năm | luật ship | VNINDEX |
|---|---|---|
| 2023 | 11,0% | 12,2% |
| 2024 | 19,1% | 12,1% |
| 2025 | 10,7% | 40,9% |
| 2026 | −5,5% | +1,5% |

Đọc bảng:

- **Không dòng nào có t ≥ 2, không dòng nào dương đủ 4 năm, và không danh mục
  nào vượt VNINDEX** cả về lợi nhuận lẫn Sharpe. `M_ivol_low` là dòng duy nhất
  có drawdown ngang index (−17,7%), nhưng lợi nhuận chỉ bằng một nửa.
- `V_obv_trend` và `S_small_size` đẹp nhất về số tuyệt đối, nhưng mỗi cái âm
  một năm, và chúng được lọc ra từ 41 factor trên cùng dữ liệu. Chọn chúng là
  chọn theo may. **Không khuyến nghị đổi sang chúng.**
- **Đối chứng ngẫu nhiên** (chọn 5 mã ngẫu nhiên mỗi ngày, 20 seed, khung 40):
  - excess +0,03% ± 0,25%, danh mục 6,4-9,5%/năm;
  - luật ship (9,3%) nằm **trong** khoảng đó ở mức danh mục, dù excess/lệnh
    +0,62% cao hơn khoảng seed (z ≈ 2,3);
  - nghĩa là luật chọn không ngẫu nhiên và nghiêng đúng chiều trên đúng các
    ngày này, nhưng mức lệch dao động theo thời gian đủ lớn (NW t 1,1) để chưa
    nói được nó sẽ lặp lại.

### 2.2 Ngưỡng `MIN_BUY_SCORE = 2,5` — phần chưa từng được đo

Luật ship lọc điểm ≥ 2,5 **rồi** mới xếp theo blend. Ngưỡng này được đặt ở
phân vị 78 của điểm (§26.4), không phải từ lợi nhuận.

So cùng một thứ tự production, có và không có ngưỡng. Phương án không ngưỡng
**vẫn giữ cổng SMA200**: 0/4.832 lệnh là mã dưới SMA200.

| h | có ngưỡng − không ngưỡng | NW t | theo năm 2023 / 24 / 25 / 26 | danh mục có → không |
|---|---|---|---|---|
| 20 | **−0,39%/lệnh** | −1,60 | −0,89 / −0,01 / −0,21 / −0,53 | 2,7% → **7,2%** |
| 40 | **−0,44%/lệnh** | −1,48 | −1,42 / +0,60 / −0,87 / +0,20 | 9,3% → **11,7%** |

- Chiều âm ở khung 20 phiên trong **cả 4 năm** (2024 ≈ 0). Ở khung 40 thì lẫn lộn.
  t chưa tới 2, và đây là đo in-sample.
- Tuy vậy, gánh chứng minh thuộc về luật được **thêm vào**. Một bộ lọc chưa từng
  được đo, khi đo lại cho chiều âm, thì không nên là mặc định. Bỏ ngưỡng chính là
  quay về thứ tự mà §26.9 đã thực sự đo.
- **Tính chất danh sách sẽ đổi.** Không có ngưỡng thì shortlist luôn đủ 5 mã, và
  một nửa số mã có điểm dưới 2,5: mã **đang trong uptrend, OBV mạnh nhưng chưa
  quá bán**. Hôm 2026-09-23: có ngưỡng thì chỉ còn GAS; không ngưỡng thì danh
  sách đủ 5 mã, có cả mã quá mua (NTP, RSI(2) ≈ 92), và GAS rơi xuống thứ 8.
- Cách chấm với bench cũ, nếu cần: ship so với twin là −0,19%/lệnh (t −0,86).
  Số này che mất hiệu ứng thật, vì twin còn xếp hạng trên một tập mã khác
  (không tính mã bị sàn) — phần đó bù lại khoảng +0,2.

### 2.3 Universe production (75 mã constituent) so với panel 143 mã

Production chỉ xếp hạng trong ~53 mã constituent đủ thanh khoản; bench xếp
trong ~100 mã. Đo luật ship trên universe production:

| h | excess (NW t) | theo năm 2023 / 24 / 25 / 26 | danh mục |
|---|---|---|---|
| 20 | +0,45 (1,26) | −0,48 / +1,02 / +1,22 / −0,27 | 3,6%/năm |
| 40 | +0,51 (0,95) | −0,80 / +1,75 / +0,68 / +0,16 | 7,5%/năm |

Không chiều nào rõ ràng, nên kết luận §2.1 không đổi.

### 2.4 Ba bề mặt, ba luật mua khác nhau

| bề mặt | luật |
|---|---|
| `daily_watch` shortlist | điểm ≥ 2,5 → `_rank_key` (blend) → top-5, bỏ mã đang nắm. **Không** dùng tín hiệu ngành. Đây là luật được đo ở trên |
| Daily Insight (`_select_top`) | mã của ngành BUY/ACCUMULATE **xếp trước**, rồi mới lấp từ cả universe; điểm ≥ 2,5; blend |
| Email 17:00 (`generate_report.py:354-360`) | **chỉ** mã của ngành BUY/ACCUMULATE (cổng cứng; ranker không có BUY thì email không có mua); điểm ≥ 2,5; `ret_5d > −12%`; xếp theo **điểm thô** (không blend); top-6; rồi gộp với danh sách Daily Insight |

- Tín hiệu ngành không có edge (§4), và từ 2026-08-25 còn chấm trên số 0. Hai
  bề mặt sau vì thế đang xếp và lọc picks theo nhiễu.
- Email xếp theo điểm thô, tức đúng `P2` — thứ đo ra yếu nhất trong bảng §2.1.
- Không backtest được hai luật sau, vì lịch sử `sector_signals` chỉ bắt đầu từ
  2026-04-09. Đây đúng là họ lỗi §22.11: một luật, nhiều bản cài.

`daily_watch/service.py::HORIZON_ANNUALISED = {20: 0.059, 40: 0.117}` là số
học quy năm của bench twin, và bản tin mục 5 in chúng kèm "VNINDEX 15,7%,
Sharpe 0,91". Số danh mục của luật ship là **2,7% và 9,3%**, VNINDEX cùng kỳ
là **17,5%, Sharpe 0,98**. Mục 5 của bản tin còn nhắc "stop/target in ra là
hình học SWING", trong khi bảng ứng viên đã bỏ cột đó.

---

## 3. Khung giữ và khuyến nghị bán

### 3.1 Giữ bao lâu

Danh mục staggered; mọi luật cùng mở lệnh từ 2022-10-24 (ngày đầu luật ship
chọn được mã). Mỗi ô ghi lợi nhuận/năm tính từ 2023-01 | tính từ 2023-07, lúc
mọi khung đã vào đủ vốn.

| h (phiên) | luật ship | cổng SMA200, bỏ ngưỡng | NO GATE |
|---|---|---|---|
| 10 | −5,2 \| −6,3 | −2,1 \| −3,7 | −11,7 \| −15,0 |
| 20 | 2,7 \| 1,7 | 7,2 \| 6,4 | 0,1 \| −3,8 |
| 30 | 6,1 \| 5,5 | 10,1 \| 9,3 | 4,6 \| 0,5 |
| **40** | **9,3 \| 8,7** | **11,7 \| 10,7** | 7,0 \| 2,7 |
| 60 | 9,1 \| 8,8 | 10,6 \| 9,9 | 9,4 \| 5,2 |
| 80 | 8,7 \| 8,8 | 9,3 \| 9,0 | 10,3 \| 6,4 |
| 120 | 9,2 \| 10,0 | 10,9 \| 11,3 | 11,1 \| 7,5 |
| VNINDEX | 17,5 \| 16,4 | | |

- **Lợi nhuận tăng dốc tới ~40 phiên rồi đi ngang.** Chủ yếu vì phí khấu hao trên
  ít vòng hơn: 12,6%/năm ở khung 20 phiên, 6,3%/năm ở khung 40.
- Sau 40 phiên, so với chọn ngẫu nhiên thì **phụ thuộc giai đoạn**. Tính từ
  2023-01, rổ ngẫu nhiên đuổi kịp ở 60 phiên trở lên; tính từ 2023-07, picks dẫn
  ở mọi khung.
  - Câu "sau 40 phiên không factor nào sống sót" (§26.9, `sell_range.py`) vì thế
    không đứng vững như một luật.
  - Điều đứng vững: **giữ lâu hơn 40 phiên không thêm gì đo được**.
- Hệ quả cho luật bán:
  - cửa sổ 20-40 phiên đúng về hình dạng;
  - **mặc định nên giữ tới gần 40 phiên**;
  - phiên 20 không phải tín hiệu bán.

### 3.2 `give_back` và range — đo đúng như production chạy

Production báo `give_back` theo **giá đóng cửa**: đỉnh tính trên các phiên
trước, và chỉ báo sau khi đã arm (+1×ATR). Tom hành động phiên sau. Mô phỏng
đúng như vậy, bán ở ATO phiên kế, danh mục staggered:

| khung 40 phiên | CAGR | Sharpe | MaxDD |
|---|---|---|---|
| **giữ hết khung** | **9,3%** | **0,58** | −29,1% |
| give_back 3,5×ATR, tiền bán ra để tiền mặt | 7,3% | 0,52 | −27,2% |
| give_back 3,5×ATR, tiền bán ra mua VNINDEX\* | 8,6% | 0,55 | −29,3% |
| give_back 2,5×ATR, tiền mặt | 6,0% | 0,48 | −24,0% |
| give_back 2,5×ATR, VNINDEX\* | 8,4% | 0,54 | −27,6% |

\* chưa tính phí cho lệnh mua VNINDEX, nên hai dòng này hơi lạc quan.

- Kết luận doctrine **đứng vững về chiều**: giữ hết khung có Sharpe tốt nhất.
- Nhưng **độ lớn nhỏ hơn nhiều**. Nếu tiền bán ra được đặt vào index, give_back
  3,5×ATR chỉ tốn ~0,7 điểm %/năm.
- Để `give_back` là *tin về luận điểm*, như hiện tại, là đúng.

**Lỗi trong bench đã tạo ra kết luận cũ** — `scripts/tplus_strategy_bench.py:299-308`,
hàm `run_trail()`:

- Đỉnh được cập nhật bằng **giá đóng cửa phiên k trước khi** so **giá thấp nhất
  phiên k** với băng. Một phiên tăng mạnh kéo băng lên, rồi "chạm" bằng chính
  mức giá thấp đã xảy ra trước đó trong phiên.
- Phiên mở cửa dưới băng vẫn được tính là khớp ở băng.

Sửa cả hai:

| entries `swing_prop_obv_top5`, %/lệnh | khung 20 | khung 40 |
|---|---|---|
| băng 1,5×ATR: bench cũ → sửa | | −1,29 → **+0,45** |
| băng 2,5×ATR: bench cũ → sửa | −0,38 → **+0,08** | +0,18 → **+0,87** |
| băng 3,5×ATR: bench cũ → sửa | +0,10 → +0,20 | +1,07 → +1,14 |
| giữ hết khung | +0,42 | +1,77 |

Thứ tự giữa các biến thể vẫn giữ nguyên, nhưng cái giá của việc dùng băng bị
phóng đại 2-3 lần. "Càng chặt càng tệ, đơn điệu" (§26.10) phần lớn do lỗi này:
băng chặt bị phạt nặng nhất vì nó nằm sát giá nhất.

**Một lỗ logic trong `sell_range.advise()` với vị thế thiếu ngày mua.**

- `armed = peak ≥ entry × (1 + ARM×ATR)` nhưng không xét `peak_basis`. Khi thiếu
  ngày mua, đỉnh là đỉnh ~30 phiên gần nhất, **có thể có trước lúc Tom mua**.
- Khi đó `give_back` lại thành đúng thứ bản sửa 2026-09-17 đã loại: báo "sóng lên
  đã kết thúc" cho một con sóng Tom không có mặt.
- Bản tin 2026-09-23 có đúng trường hợp này: một vị thế **không có ngày mua** bị
  báo "NHẢ QUÁ SÂU", với đỉnh ~30 phiên gần nhất cao hơn giá vào ~11%.
- Sửa: chỉ arm khi `peak_basis == "since_entry"`; nếu không thì nói rõ "không xác
  định được đã có sóng lên sau khi mua hay chưa".

**Phần lớn vị thế trong sổ chưa có ngày mua** (danh sách ở `report/watch_<ngày>.md`;
không ghi ở đây vì repo public). Nghĩa là luật
bán duy nhất có đo lường — cửa sổ thời gian — không chạy được cho các mã đó. Một
ngày ước lượng là đủ, như bản tin đã nói.

### 3.3 Thời điểm khớp lệnh — cùng picks, cặp đôi

Sự thật của thị trường trong panel:

- mã đủ thanh khoản trung bình **tăng qua đêm** (ATO so với ATC hôm trước):
  +0,10% trên 2022-26, +0,15% từ 2023;
- **giảm trong phiên** (ATC so với ATO): −0,08%;
- VNINDEX: +0,09% qua đêm, −0,07% trong phiên.

Đo trên picks thật, so với mặc định "mua ATO t+1, bán ATC":

| thay đổi | khung 20 | NW t | khung 40 | NW t |
|---|---|---|---|---|
| **bán ở ATO ngày thoát** | **+0,085%/lệnh** | 2,22 | +0,058 | 1,22 |
| mua ở ATC t+1 thay vì ATO | −0,041 | −0,81 | −0,045 | −0,84 |
| mua ATC t+1 và bán ATO | +0,046 | 0,75 | +0,013 | 0,20 |
| mua ATC ngày tín hiệu (cần chấm điểm trước 14:30) | +0,058 | 1,84 | +0,050 | 1,49 |

- **Bán ở phiên ATO ngày thoát** là thay đổi rẻ nhất có chiều dương. Hiệu ứng nhỏ,
  và ở khung 40 phiên thì chưa chắc chắn.
- **Đừng dời lệnh mua sang ATC phiên sau.** Với mã quá bán, phiên t+1 thường hồi
  ngay trong phiên.
- §26.7 ghi 0,145%/lệnh cho việc vào lệnh ở ATC ngày tín hiệu. Trên luật ship
  đo được +0,05-0,06%.

### 3.4 Phiên không có mã nào: tiền mặt hay ETF chỉ số

Có ngưỡng 2,5 thì 43/919 phiên không có mã nào và 245 phiên có dưới 5 mã. Đặt
riêng phần của **các phiên không có mã** vào VNINDEX (các phiên có 1-4 mã vẫn
chia đều cho các mã đó):

| luật ship | CAGR | Sharpe | MaxDD | 2023 / 24 / 25 / 26 |
|---|---|---|---|---|
| khung 20, tiền mặt | 2,7% | 0,24 | −30,5% | 4,6 / 9,0 / 9,0 / −11,4 |
| khung 20, **VNINDEX** | 3,3% | 0,27 | −30,4% | 4,1 / 9,6 / 10,6 / −10,8 |
| khung 40, tiền mặt | 9,3% | 0,58 | −29,1% | 11,0 / 19,1 / 10,7 / −5,5 |
| khung 40, **VNINDEX** | **10,7%** | **0,63** | −28,9% | **12,5 / 19,7 / 12,6 / −4,4** |

- Ở khung 40, phương án VNINDEX tốt hơn ở mọi năm.
- Nếu bỏ ngưỡng 2,5 thì gần như không còn phiên trống, và chính sách này không
  còn tác dụng.
- Bản đầu tiên tôi thử chia 5 suất giữa mã và index, và nó thua năm 2024. Lợi ích
  đến **chỉ** từ các phiên không có mã nào — agent kiểm chứng đã chỉ ra điểm này.
- Bộ lọc thị trường (chỉ mua khi VNINDEX > SMA200):
  - **làm hại** nếu phần bị lọc để tiền mặt: khung 40 còn 2,0%/năm;
  - trung tính nếu phần đó mua index: 10,0%;
  - lọc breadth ≥ 50% rồi để index cho 11,0%, trong 6 biến thể đã thử — không
    đủ để khuyến nghị.

---

## 4. Tầng ngành — lỗi và edge

Không ảnh hưởng shortlist `daily_watch`. Có ảnh hưởng tới:

- email 17:00 (cổng mua cứng) và trang Daily Insight (thứ tự picks, nhãn regime,
  BUY/SELL ngành);
- sentinel stop và backtest.

### 4.1 Lỗi

**Nghiêm trọng**

1. **Ranker đang chấm trên số 0.**
   - Ở đâu: `sector_ingest_service.py:250-343`, `rotation_model_service.py:100`.
   - Lỗi: job 16:00 không tính các cột stealth (`flow_z20` … `accumulation_age`);
     chỉ `fast_ingest.py` (chạy từ UI) tính. Khi dự đoán, `fillna(0)` biến chỗ
     trống thành 0.
   - Chứng cứ: `flow_z20` NULL trên **cả 15 ngành, mọi phiên từ 2026-08-25**
     (kiểm bằng SQL).
   - Tác động: ranker chấm trên số 0 suốt một tháng. So với xếp hạng tính đúng:
     Spearman 0,70, top-3 chỉ trùng 1,55/3. ACCUMULATE không thể bắn.
2. **Ranker không có edge nhưng vẫn phát BUY/SELL.**
   - Ở đâu: `models/rotation_ranker.py`, `sector_signal_service.py`.
   - Chứng cứ: walk-forward 32 lần refit, purge 22 phiên. IC −0,010; theo năm
     2024 +0,015 (t 0,5), 2025 −0,044 (t −1,1), 2026 +0,004. Quintile không đơn
     điệu. Chính `model_runs` id 110 tự ghi `decile_monotonic −0,90`.
   - Tác động: BUY/SELL ngành là nhiễu. Một chuẩn đơn giản, `foreign_hit_20d`,
     có IC +0,097 (t 2,5), nhưng sau phí xoay vòng chỉ còn +0,2%/20 phiên và
     phẳng năm 2026.

**Cao**

3. **ATR ngành nhỏ đúng 5 lần.**
   - Ở đâu: `analysis/flow_aggregation.py:173` và `:224` — ATR được nhân
     `w = 1/n` rồi lại chia cho `atr_n = n`.
   - Chứng cứ: trong code; `atr_pct` ≈ 0,0055 trong khi ATR rổ thật ≈ 2,7%.
   - Tác động:
     - sentinel stop (`risk_service.py:106`) báo CRITICAL trên 21,7% số
       ngành-ngày, đúng ra chỉ 0,7%;
     - tiền đề của §16.15 ("ATR ngày trung vị 0,57%") sai 5 lần — với ATR thật,
       bar `atr_scaled` ≈ 35% và không bao giờ chạm tới;
     - slippage trong backtest thực chất chỉ còn mức sàn 0,3%.
4. **VNINDEX rác trong `macro_anchors`.**
   - Ở đâu: `backtest_service.py:123-138`, `rotation_model_service.py:109`,
     `macro_service.py:52`.
   - Lỗi: 613 dòng `vnindex` ≈ 1,82 (2026-04-16 → 08-23). Không có kiểm tra
     từng giá trị — `macro_service.py:52` chỉ xét trung vị.
   - Chứng cứ: kiểm bằng SQL. Nhãn regime 2026-09-22 = `risk_off 0,9961` tái lập
     đúng từ nhánh fallback dùng các dòng này.
   - Tác động: benchmark backtest in VNINDEX "+97.432%"; một ngày nhãn regime
     được publish từ dữ liệu rác.
5. **`close_idx` nhảy khi rổ thiếu mã.**
   - Ở đâu: `flow_aggregation.py:179` — đây là trung bình **giá thô** của những
     mã lấy được hôm đó.
   - Chứng cứ: STEEL ngày 2026-09-22 **+62%**, ngày 09-23 **−39%**, trong khi
     `return_1d` chỉ +0,5% / −0,1% (kiểm bằng SQL). `return_1d` NULL cho mọi
     ngành từ 2026-04-10 tới 06-22.
   - Tác động: target của ranker, điều kiện 5 của §16.1 và P&L backtest đều bị
     nhiễm.
6. **Backtest chiến lược `signals` bán hết mỗi khi thiếu tín hiệu.**
   - Ở đâu: `backtest_service.py:258`.
   - Lỗi: ngày không có dòng tín hiệu → tập mục tiêu rỗng → bán hết. Lệnh còn
     khớp ở giá đóng ngày tín hiệu, điều không làm được khi tín hiệu publish lúc
     17:00.
   - Chứng cứ: trên khoảng mặc định, −10,1% như hiện tại so với +1,8% khi giữ
     tín hiệu gần nhất và khớp ở t+1.
   - Tác động: số backtest trên UI sai.
7. **Calibration regime là in-sample.**
   - Ở đâu: `analysis/regime.py:215-237`, `scripts/regime_horizon_experiment.py:66-73`.
   - Lỗi: calibration §25 đo trên fit **toàn mẫu**. Replay đúng cách publish
     (refit hằng tuần, filtered) thì lệch hẳn.
   - Chứng cứ, trên VNINDEX thật:
     - dự báo "giữ nhãn 5 phiên" 0,69-0,85, thực tế 0,28-0,58;
     - Brier skill **âm mọi năm**: −0,94 / −0,42 / −0,24 / −0,05;
     - nhãn đổi 33,8 lần mỗi 250 phiên;
     - 10% lần refit tệ nhất gán lại 93% lịch sử.
   - Tác động: sau ngày `risk_on`, VNINDEX 20 phiên tới thấp hơn các ngày khác
     −1,55% (t −1,7); long `risk_on` / short `risk_off` thì lỗ. Tuần này nhãn đổi
     gần như mỗi ngày.

**Trung bình**

8. Lọc bền "≥3 phiên cùng dấu" **không xét chiều** (`sector_signal_service.py:38-39`):
   24/96 lệnh BUY đã publish đi sau 3 phiên **rút** ròng.
9. `up_down_vol_ratio` NULL ở ngày toàn tăng (`rotation_ranker.py:43`): lúc train
   bỏ 18% số dòng, lúc predict lại điền 0 — tức "toàn giảm".
10. Model bị ghi đè mỗi đêm và `model_run_id` NULL trên cả 929 tín hiệu
    (`rotation_ranker.py:75-93`), nên không truy được tín hiệu nào về model nào.
    Model live chỉ train trên 2023-01 → 2025-10-31.
11. 14/62 ngày tín hiệu là cuối tuần hoặc ngày lễ, dùng feature cũ
    (`sector_signal_service.py:80`).
12. Stealth (`analysis/stealth.py:141-144`, `api/routers/stealth.py:67,79,89,184`):
    - `fillna(False)` trái với §16.1, vốn yêu cầu bỏ điều kiện thiếu dữ liệu khỏi
      cả tử lẫn mẫu;
    - trang Stealth Watch dùng c3/c4/c5 **khác** scanner: 53 dòng scanner gọi là
      stealth thì trang hiện 11 active, 38 warming, 4 inactive.
13. `foreign_net` = 0 cho cả 15 ngành trên 39 ngày (tháng 1-3/2023) vì **thiếu**
    dữ liệu, không phải vì khối ngoại đứng ngoài. Nó làm lệch `foreign_hit_20d`
    và `foreign_streak`.

**Thấp**

- `foreign_intensity` lệch ~5000× (chỉ dùng để hiển thị).
- `macro_vn_ret_5d` = 0 trên 99,6% số dòng.
- `rs_vnindex_*` so với trung bình `close_idx`, không phải với VNINDEX.
- `_fetch_foreign` trả (0,0,0) khi cả hai nguồn hỏng.
- `fetch_history` lấy size 500 mà không phân trang.

### 4.2 Edge, trên dữ liệu sạch

| | 2024 | 2025 | 2026 | gộp |
|---|---|---|---|---|
| base: mọi ngành, fwd 20 phiên | +1,17% | +2,13% | −1,56% | +0,91% |
| ranker IC (NW t) | +0,015 (0,5) | −0,044 (−1,1) | +0,004 (0,1) | −0,010 (−0,5) |
| ranker top-3 so với mọi ngành | +0,54% | −0,34% | +0,26% | +0,14% (t 0,6) |
| `foreign_hit_20d` IC | +0,145 (2,1) | +0,100 (2,0) | +0,013 (0,2) | +0,097 (2,5) |
| `flow_z20` IC | −0,016 | −0,053 | −0,034 | −0,034 (−2,7) |

**Cổng stealth §16.1** vẫn trượt §16.12:

| | số event | excess 20 phiên | p |
|---|---|---|---|
| dữ liệu đang lưu | 20 | −0,10% | 0,50 |
| dữ liệu sạch | 23 | +0,98% | 0,17 |

Năm 2026 âm trong cả hai trường hợp.

Biến thể thay c2 bằng `foreign_streak` là biến thể duy nhất dương cả 4 năm:
+2,39%, p 0,01 trước hiệu chỉnh, ~0,06 sau khi tính 6 biến thể đã thử. Đúng như
§16.14 nói — và vẫn mong manh: năm 2026 chỉ +0,2%, n = 3.

---

## 5. ML ensemble — plan đầu bảng "Đang làm"

Đã tái lập đúng từng số: 73.754 dòng OOS, theo năm +3,73 / +1,98 / +0,12 /
+1,38. Ở chi phí đúng 1,00%/vòng:

| khung 20, cùng 619 phiên | top-5 | excess NO GATE (NW t) | vs VNI | net/lệnh | 2023 / 24 / 25 / 26 |
|---|---|---|---|---|---|
| ML | 1,46 | +0,86 (1,29) | +0,11 | +0,46 | +0,53 / +2,64 / +0,29 / **−1,87** |
| đang ship | 1,31 | +0,71 (1,56) | −0,04 | +0,31 | +3,59 / +0,81 / +0,14 / +0,93 |
| ensemble 50/50 | 1,93 | +1,32 (2,46) | +0,57 | +0,93 | +4,22 / +2,23 / +0,12 / +1,07 |

- **Ensemble − ship = +0,62 điểm/lệnh, NW t 1,74.** Mô phỏng cho thấy NW ở lag
  20 hụt sai số chuẩn khoảng 22%, nên t thật chỉ ~1,2-1,5.
- 52% phần lợi của năm 2024 đến từ 3 mã (CSV, HVN, CMG).
- **Ở khung 40: −0,20 (t −0,30)**, và ensemble âm năm 2025.
- Khi áp ngưỡng `MIN_BUY_SCORE` của production: +0,27 (t 1,22).
- Mức capacity "leaves=7" được chọn trên chính các fold OOS, và chênh lệch giữa
  các setting chỉ bằng nhiễu seed. Nửa "công thức" của ensemble cũng in-sample:
  nó chính là factor được chọn 1/41 trên toàn giai đoạn.
- Không tìm thấy leakage:
  - 23 feature giống hệt khi cắt dữ liệu ở 4 mốc;
  - target đúng `close[t+1+h]/open[t+1]`;
  - embargo đúng.

**Khuyến nghị: không dựng production.** Nếu vẫn muốn biết, đăng ký trước một
shadow test:

- **Đóng băng spec hôm nay:** feature, leaves 7 / min_leaf 500, nhịp retrain,
  blend 50/50, khung 20, top-5, vào lệnh ở ATO.
- **Log hằng ngày** top-5 của cả ba thứ tự (ML, ship, ensemble).
- **Tiêu chí nhận:** hiệu số cặp đôi (ensemble − ship) có NW t ≥ 2,8 sau 12
  tháng, hoặc ≥ 2,0 sau 24 tháng, và dương trong mọi khối 6 tháng.
- **Lực kiểm, nói trước:** một edge thật +0,6 điểm chỉ có **19%** khả năng được
  phát hiện sau 12 tháng, 33% sau 24 tháng. Vì vậy "chưa kết luận được" nên có
  nghĩa là không ship.

---

## 6. Dữ liệu

- **`data/price_panel.db` trộn hai mức điều chỉnh giá.**
  - Nguyên nhân: `build_price_panel.py` gọi `seed_from_legacy()` (INSERT OR
    IGNORE) ở **mỗi lần chạy**. Ngày nào nguồn mới không có dữ liệu (phiên không
    khớp lệnh) thì giá legacy — khác cơ sở điều chỉnh — nằm lại.
  - Phạm vi: 8 mã (SRC, POM, NFC, GMC, PTI, VSH, ACL, DNP), 145 dòng. Ví dụ SRC
    nhảy xen kẽ 19,20 ↔ 25,15.
  - Tác động lên kết quả ≈ 0, vì cả 8 mã hầu như luôn dưới ngưỡng thanh khoản
    (agent ML train lại không có chúng: +1,33 so với +1,32). Nhưng đó là may,
    không phải thiết kế.
- **Survivorship.** Panel là danh sách *hiện tại* (legacy + constituent + mã đã
  pick), nên thiếu các mã bị huỷ niêm yết 2022-2025. Sai lệch nghiêng về phía
  làm đẹp chiến lược mua mã yếu hoặc mã nhỏ, và làm đẹp rổ đều-trọng-số so với
  VNINDEX. Tức là khoảng cách thật với index **có thể còn lớn hơn** bảng §2.1.
- **Panel không chỉ có mã HOSE.** Có cả mã HNX/UPCoM (biên độ ±10% / ±15%).
  Tài liệu ghi "143 mã HOSE", và `O_rev5_no_floor` dùng biên 6,5% cho mọi mã.
- **Slippage.** `analysis/bench.py` chú thích công thức `max(0,3%, 0,5×ATR%)`
  nhưng thực tế chỉ áp mức sàn 0,3%/chiều.
  - Với mã có ATR 3-4%, công thức nguyên văn cho 3,6-4,3%/vòng — không thực tế
    cho lệnh nhỏ trên mã thanh khoản.
  - Giữ 1,00%/vòng là hợp lý; chỉ cần sửa chú thích cho khớp thứ đang áp.

---

## 7. Đã kiểm và đúng

- **Score và blend production khớp** bản vector hoá dùng để đo: blend chênh đúng
  0 trên 5 ngày ngẫu nhiên; score chênh ≤ 0,005 (do làm tròn 2 chữ số).
- **Không feature picks nào nhìn trước:**
  - 23 feature giống hệt khi cắt dữ liệu ở 4 mốc;
  - target là `close[t+1+h]/open[t+1]`;
  - h ≥ 2 nên T+2 được tôn trọng.
- **Chi phí:** phí 0,15%/chiều + thuế 0,1% + slippage 0,3%/chiều = 1,00%/vòng.
  Mọi bench import từ một chỗ (`analysis/bench.py`).
- **`daily_watch`:** shortlist dùng **đúng** `_rank_key` của Daily Insight và
  không dùng tín hiệu ngành; `sell_range.ARM_ATR` khớp bench; `give_back` không
  còn là stop trá hình khi **có** ngày mua.
- **Tầng ngành:**
  - purge 22 phiên đúng, và target chưa hiện thực bị loại;
  - posterior HMM là filtered (khớp bộ lọc chỉ-chạy-tiến tới sai số 2e-13);
  - phí, thuế, T+2 và công thức Sharpe trong backtest đúng;
  - `foreign_net` = mua − bán, đơn vị VND, đúng ngày;
  - `net_dollar_flow` và breadth khớp khi tính lại từ dữ liệu sạch.
- **Harness đo lại qua negative control:** chọn toàn bộ universe → excess đúng 0;
  chọn ngẫu nhiên → +0,03% ± 0,25%.
- **Kiểm độc lập:** một agent tự viết lại toàn bộ phép đo mà không dùng harness
  này. Lệch ≤ 0,03 điểm %/lệnh và ≤ 0,2 điểm CAGR.

---

## 8. Khuyến nghị — Tom quyết

**P0 — dừng phát số sai**

| # | việc | vì sao (đo được) | đo lại bằng |
|---|---|---|---|
| 1 | job 16:00 tính cột stealth; `predict_today` từ chối chạy khi một cột feature NULL toàn bộ ở ngày mới nhất | ranker đang chấm trên số 0 | xếp hạng live = xếp hạng tính lại offline |
| 2 | ATR ngành: `Σ atr·w / Σ w`; backfill | nhỏ 5 lần, sentinel báo động giả 21,7% số ngày | `atr_pct` ≈ ATR rổ tính từ panel |
| 3 | xoá dòng `vnindex < 200`; kiểm từng giá trị; regime **không publish** từ nhánh fallback | nhãn 2026-09-22 dựng từ rác | replay ngày 09-22 không còn ra 0,996 |
| 4 | `close_idx` nối từ `basket_return`; backfill; train lại | nhảy ±40-60% khi rổ thiếu mã | không còn ngày nào \|Δclose_idx\| vượt biên sàn |
| 5 | backtest `signals`: giữ tín hiệu gần nhất, khớp ở t+1 | đang bán hết ở 66/114 phiên | khoảng mặc định: −10,1% → +1,8% |
| 6 | tới khi ranker/regime/stealth qua walk-forward từng năm: ghi "chưa kiểm chứng" cạnh BUY/SELL/ACCUMULATE/nhãn regime; **bỏ cổng ngành khỏi danh sách mua** trong email và Daily Insight, dùng chung luật của `daily_watch` | không có edge OOS; email đang lọc mua theo nhiễu | email = Daily Insight = shortlist |

**P1 — sửa thước đo, để các quyết định sau đúng**

| # | việc | vì sao | đo lại bằng |
|---|---|---|---|
| 7 | bench: một base NO GATE; chấm mọi phiên (ngưỡng 30 mã áp cho universe, không cho cross-section của factor); NW t; so với VNINDEX cùng cửa sổ; danh mục staggered; chấm **luật như ship** | §1 | `run_factors.py`, `cutoff.py` |
| 8 | sửa `run_trail()`: băng tính từ đỉnh các phiên trước; phiên mở dưới băng thì khớp ở giá mở | §3.2 | `trail_fix.py` |
| 9 | `sell_range.advise()`: chỉ arm `give_back` khi `peak_basis == "since_entry"` | §3.2 | vị thế thiếu ngày mua không còn báo "nhả quá sâu" |
| 10 | `build_price_panel.py`: không trộn legacy sau khi đã fetch mới; thêm test chặn \|ret\| vượt biên sàn | §6 | 0 dòng lệch cơ sở |
| 11 | `daily_watch`: sửa `HORIZON_ANNUALISED` thành số danh mục; in VNINDEX 17,5% bên cạnh; bỏ đoạn stop/target cũ trong mục 5 | §2.4 | |
| 12 | `analysis/bench.py`: chú thích slippage nói đúng thứ đang áp (0,3%/chiều cố định) | §6 | |

**P2 — luật giao dịch** (đây là phân tích dữ liệu, không phải tư vấn đầu tư)

| # | việc | vì sao (đo được) | đo lại bằng |
|---|---|---|---|
| 13 | **bỏ ngưỡng `MIN_BUY_SCORE` 2,5, giữ cổng SMA200** — tức quay về thứ tự đã được đo | +0,4%/lệnh; danh mục +2,4 điểm %/năm ở khung 40 (9,3 → 11,7%). t 1,5-1,6, đo in-sample | `cutoff.py`; nên shadow-log cả hai danh sách vài tháng trước khi đổi hẳn |
| 14 | nếu giữ ngưỡng: phiên không có mã nào thì phần đó mua ETF chỉ số | +1,4 điểm %/năm ở khung 40, tốt hơn mọi năm | `followup.py` |
| 15 | mặc định giữ tới ~40 phiên; phiên 20 không phải tín hiệu bán | 9,3% so với 2,7%/năm | §3.1 |
| 16 | đặt lệnh bán ở phiên ATO ngày thoát; lệnh mua giữ ở ATO | +0,06-0,09%/lệnh, t 1,2-2,2 | §3.3 |
| 17 | `give_back` giữ vai trò tin về luận điểm, không bán cơ học | bán cơ học tốn 0,7-2,0 điểm %/năm | §3.2 |
| 18 | nhập ngày mua (ước lượng cũng được) cho các vị thế chưa có | không có ngày mua thì không có cửa sổ bán | |
| 19 | cân nhắc mô hình lõi-vệ tinh: phần lớn vốn theo index, shortlist là phần vệ tinh | không luật nào vượt index về lợi nhuận hay Sharpe trên 2023-2026 | §2.1 |
| 20 | ML ensemble: không dựng; nếu muốn thì shadow test đăng ký trước | §5 | |

**Không khuyến nghị:**

- đổi sang `V_obv_trend` hoặc nghiêng theo size — chọn theo may trên 41 factor,
  và mỗi cái âm một năm;
- top-10 thay top-5 — tệ hơn ở cả hai khung;
- lọc thị trường VNINDEX > SMA200 mà để tiền mặt — khung 40 tụt từ 9,3% xuống
  2,0%/năm.

---

## 9. Đề xuất sửa doctrine (`CLAUDE.md`)

- **§16.12:** định nghĩa NO GATE = mọi mã đủ thanh khoản, mọi phiên. Cấm so
  factor có cổng với base có cổng, và cấm lọc phiên theo cross-section của chính
  factor.
- **§18.7:** giữ yêu cầu đơn điệu quintile, nhưng đọc kèm Q5−Q1 với t
  Newey-West. Năm con số trung bình nhiễu rất dễ đổi thứ tự: ensemble chỉ đơn
  điệu ở 4/8 lần chạy, và không năm nào đơn điệu.
- **§26.4:** ngưỡng `MIN_BUY_SCORE` đo ra âm. Hoặc bỏ, hoặc ghi rõ đây là lựa
  chọn *không* dựa trên phép đo.
- **§26.9:**
  - rút câu "1/41 sống sót";
  - thay hằng số `VNINDEX_CAGR` bằng so sánh danh mục cùng cửa sổ;
  - cập nhật 5,9% / 11,7% thành 2,7% / 9,3%;
  - bỏ câu "trên 40 phiên không factor nào sống sót" (§3.1).
- **§26.10:** kết luận giữ nguyên chiều; còn độ lớn, và chữ "đơn điệu", phải đo
  lại sau khi sửa `run_trail()`.
- **§25:** các số calibration là in-sample; replay out-of-sample cho Brier skill
  âm ở mọi năm.
- **§16.15:** tiền đề "ATR ngày trung vị 0,57%" sai 5 lần, do lỗi chia hai lần.

---

## Phụ lục — chạy lại

```bash
# từ gốc repo, khi đã có data/price_panel.db
# (tuỳ chọn) để run_factors.py in được cột "OLD":
uv run python scripts/ticker_alpha_bench.py --horizons 20,40 --verdict --json data/bench_all_h20_40.json

uv run python docs/reviews/algo_review_2026-09-24/run_core.py      # §2.1 (luật ship, twin, universe 75), §2.3
uv run python docs/reviews/algo_review_2026-09-24/run_factors.py   # §2.1 bảng đầy đủ, cách cũ vs cách mới
uv run python docs/reviews/algo_review_2026-09-24/cutoff.py        # §2.2 ngưỡng MIN_BUY_SCORE
uv run python docs/reviews/algo_review_2026-09-24/followup.py      # §3.1 khung giữ, §3.4 phiên trống → index
uv run python docs/reviews/algo_review_2026-09-24/run_variants.py  # §3.2 give_back, §3.3 thời điểm khớp
uv run python docs/reviews/algo_review_2026-09-24/trail_fix.py     # §3.2 lỗi của run_trail()
uv run python docs/reviews/algo_review_2026-09-24/decompose.py     # §1 tách hai hiệu ứng
uv run python docs/reviews/algo_review_2026-09-24/controls.py      # negative control
```

Output JSON được ghi vào `docs/reviews/algo_review_2026-09-24/out/` (gitignore).
Mỗi script chạy trong khoảng một phút trên panel hiện tại.

Kiểm tầng ngành bằng SQL (`vnstock_market.db`):

```sql
-- cột stealth NULL từ 2026-08-25
SELECT date, SUM(flow_z20 IS NULL) FROM sector_flow_daily WHERE date >= '2026-08-18' GROUP BY date;
-- VNINDEX rác trong macro_anchors
SELECT COUNT(*), MIN(time), MAX(time) FROM macro_anchors WHERE vnindex < 200;
-- close_idx nhảy
SELECT date, close_idx, return_1d FROM sector_flow_daily WHERE sector_code='STEEL' AND date >= '2026-09-15';
```
