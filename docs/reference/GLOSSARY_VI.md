# Từ điển thuật ngữ — Báo cáo dòng tiền ngành (tiếng Việt)

> **Nguồn:** VN Market — Sector Money-Flow & Rotation Briefing.
> **Mục đích:** Tra cứu thuật ngữ dùng trong báo cáo hằng ngày và trên web app.
> Báo cáo do `generate_report.py` sinh ra (`report/daily_report_<ngày>.html`).
> Định nghĩa mang tính giải thích; hợp đồng chính thức nằm ở `CLAUDE.md`
> (§16 stealth, §18 các mục review) — khi hai bên lệch nhau, `CLAUDE.md` đúng.

---

## 1. Khung thị trường & Chế độ (Regime)

**HMM Regime = CHOP**: HMM (Hidden Markov Model) là mô hình thống kê dùng để phân loại trạng thái thị trường. **CHOP** = thị trường đi ngang/giật cục, không có xu hướng rõ. Trong CHOP: tương quan giữa các mã/ngành tăng cao, không có "edge" bền vững → khuyến nghị giảm size, chỉ vào lệnh khi có tín hiệu chất lượng cao.

Các regime khác thường thấy: `TREND_UP`, `TREND_DOWN`, `RISK_OFF`.

**Confidence 0.50**: **Không phải** "model chắc bao nhiêu %". Từ 2026-08-24
(`CLAUDE.md` §25.2) nó là **xác suất nhãn regime này còn giữ trong 5 phiên tới**
— posterior đã lọc, nhân qua ma trận chuyển trạng thái. Khoảng thực tế 0.46–0.91.

Trước đó nó là posterior trạng thái và **luôn hiển thị 1.00**, không phải vì
model tự tin mà vì model **sập**: feature chưa chuẩn hoá nên 3/4 state chạm trần
covariance, chỉ còn một state sống → posterior 1.0 theo định nghĩa.

Đọc thế nào: dưới **0.55** thì con số này **nói quá** — đo trên 900 phiên, mức
"0.49" thực tế chỉ giữ được ~0.37. Đầu cao thì khớp (0.895 dự báo / 0.906 thực).
Câu chữ trên báo cáo do `analysis.regime.confidence_phrase()` sinh, ví dụ
"~65% khả năng giữ 5 phiên tới".

---

## 2. ⭐ STEALTH — Khái niệm trọng tâm

### Stealth Accumulation là gì?

Đây là khái niệm **"tích lũy âm thầm"** xuất phát từ học thuyết Wyckoff/Tom Williams (VSA — Volume Spread Analysis). Ý tưởng: **dòng tiền thông minh (smart money / tổ chức) gom hàng từ từ ở vùng đáy mà không tạo biến động giá lớn** — họ cố tình "ẩn dấu vết" để không kéo giá lên trước khi gom đủ.

Mục tiêu của trader: **phát hiện dấu vết âm thầm này TRƯỚC khi breakout** → "mua gốc" thay vì "fomo vào cành cao" (mua đỉnh).

### 5 Điều kiện Stealth (§16.1 — "Tom's doctrine")

> **Sửa 2026-08-23: không còn là "cả 5".** Yêu cầu đủ 5 điều kiện cùng lúc là
> **bất khả thi** trên dữ liệu thật — đo trên 13.470 dòng (2023-03 → 2026-08),
> cả 5 chỉ đúng ở **0,3%** số dòng, và chuỗi liên tiếp dài nhất trong 3,5 năm là
> **2 phiên** trong khi luật đòi 3. Vì vậy `accumulation_age` bằng 0 ở **mọi**
> dòng từng ghi. Nay là **điểm**: đạt **≥ 4 trong 5** điều kiện trong ≥ 3 phiên.
> Điều kiện không đánh giá được thì bị loại khỏi **cả tử số lẫn mẫu số**, nên
> thiếu dữ liệu không âm thầm nâng chuẩn. Kết quả: 23 event / 11 ngành.
>
> **Nhưng gate này chưa có edge đo được** (§16.14). So với việc **không lọc gì**,
> 20 lần nó bắn ra lại breakout *ít* hơn, *muộn* hơn và vào giá *tệ* hơn một
> ngày-ngành lấy ngẫu nhiên. Coi `ACCUMULATE` hiện tại là **watchlist, không
> phải lệnh mua**, và đừng dùng sizing §16.9 (1.5× vol target, stop 2.5×ATR)
> trên nó.

Năm điều kiện:

| Điều kiện | Ý nghĩa |
|---|---|
| `flow z20 > +1.0` | Dòng tiền vào mạnh bất thường (cao hơn TB 20 ngày 1 độ lệch chuẩn) |
| `foreign hit ≥ 60%` | Khối ngoại mua ròng ít nhất 60% số phiên gần đây |
| `breadth rising` | Độ rộng tăng — nhiều mã trong ngành khỏe lên cùng lúc |
| `quiet ATR` | Biến động giá thấp (ATR nhỏ) — dấu hiệu gom êm, không phân phối |
| `price in bottom 40% of 60d range` | Giá vẫn ở vùng thấp (chưa bị kéo lên cao) |

### Stealth Score

Là **điểm tổng hợp số học (composite score)** đo mức độ ngành đang "tiến gần" đến trạng thái stealth. Cách đọc trong báo cáo:

- **Stealth Score > 0**: Có tín hiệu tích lũy
- **Càng cao càng mạnh** (ví dụ Dệt may +1.02 đang dẫn đầu)
- **Âm**: Phân phối / thiếu tín hiệu (Thép -1.41, Ngân hàng -0.40)

### 3 trạng thái Stealth trong bảng watchlist

- **PRE-STEALTH (watch)**: Đạt một phần điều kiện, đang theo dõi
- **early signal**: Mới chớm tín hiệu, chưa đủ chín
- **STEALTH**: Đạt ngưỡng `min_conditions` (mặc định ≥4/5) đủ số phiên

**Accum. Age**: Số phiên liên tiếp ngành giữ được ngưỡng. Càng cao → tín hiệu
càng "trưởng thành". Trước 2026-08-23 cột này bằng 0 ở mọi dòng — xem cảnh báo
ở trên.

**3 preset trên trang Stealth Watch** (§24.2) — tên là **Chặt / Vừa / Rộng**:

| preset | ngưỡng | là gì |
|---|---|---|
| Chặt | 5/5, N=5 | doctrine gốc, **giữ lại để bạn thấy nó trả về 0** |
| Vừa | ≥4/5, N=3 | đang chạy — 23 event / 11 ngành trong 3,5 năm |
| Rộng | ≥3/5, N=1 | dò "ngành nào gần đạt", **không phải danh sách mua** |

---

## 3. Dòng tiền (Money Flow)

| Thuật ngữ | Giải thích |
|---|---|
| **Net-flow** | Dòng tiền ròng vào/ra ngành (mua chủ động − bán chủ động), tính bằng VND/ngày |
| **Δ Flow (Flow Delta)** | Chênh lệch flow giữa cửa sổ 5 ngày gần nhất vs 10 ngày trước → đo **gia tốc** dòng tiền |
| **Flow z20** | Z-score 20 ngày — flow hôm nay lệch bao nhiêu độ lệch chuẩn so với TB 20 ngày. \|z\| > 1 = bất thường |
| **DV Δ** | % thay đổi Dollar Volume (giá trị giao dịch) so với kỳ trước |
| **Signed dollar flow** | Dòng tiền đã gắn dấu mua/bán dựa vào tick rule |

---

## 4. Khối ngoại (Foreign)

- **Foreign Hit (FrgHit)**: % phiên trong cửa sổ mà khối ngoại **mua ròng**. Ví dụ FrgHit 60% = 6/10 phiên ngoại mua ròng.
- **FOL (Foreign Ownership Limit)**: Giới hạn sở hữu nước ngoài. Mã **cạn room (< 3%)** sẽ bị giảm trọng số foreign_net 0.5× vì tín hiệu ngoại không còn tin cậy.

---

## 5. Breadth (Độ rộng)

Đo **tỷ lệ mã trong ngành** cùng đạt một điều kiện kỹ thuật. Breadth rộng = sóng ngành thật; breadth hẹp = chỉ vài mã "kéo" → dễ là pump.

- **RSI > 50**: % mã có RSI vượt 50 (đang khỏe)
- **MACD+**: % mã có MACD dương (đà tăng)
- **>SMA20**: % mã đứng trên đường trung bình 20 ngày

> Báo cáo cảnh báo: Dầu khí, BĐS, Công nghệ flow dương **nhưng breadth yếu** → có thể chỉ là pump 1–2 mã, KHÔNG phải dòng tiền diffusion (lan tỏa).

---

## 6. Chỉ báo kỹ thuật

| Chỉ báo | Ý nghĩa |
|---|---|
| **RSI** (Relative Strength Index) | 0–100. >70 quá mua, <30 quá bán, >50 trend tăng |
| **ADX** (Average Directional Index) | Đo **cường độ** xu hướng. <20 không trend, >25 trend mạnh |
| **MACD** | Đo momentum. MACD dương = đà tăng |
| **ATR** (Average True Range) | Đo biến động tuyệt đối. ATR20 = ATR 20 ngày |
| **ATR%** | ATR / giá → biến động tương đối |
| **BB (Bollinger Bands)** | Dải biến động ±2 độ lệch chuẩn quanh SMA20. "Test BB dưới" = giá chạm dải dưới |
| **SMA20** | Trung bình giá 20 ngày |
| **Vol multiple** | Vol hiện tại / Vol TB. 0.8x = thấp hơn TB 20% |
| **S / R** | Support / Resistance — Hỗ trợ / Kháng cự |

---

## 7. Khuyến nghị & Bias

**Bias**: Hướng dự báo phiên kế tiếp

- ▲ **UP** / **Lean UP** (nghiêng lên)
- ▼ **DOWN** / **Lean DOWN** (nghiêng xuống)
- • **Neutral**

**Confidence**: High / Med / Low — độ tin cậy của bias

**Action types**:

- **BUY** — vào lệnh full size
- **ACCUMULATE** — gom dần, stop rộng hơn (2.5×ATR)
- **HOLD** — giữ vị thế hiện tại
- **WATCH** — theo dõi, chưa đủ confirm
- **SELL/AVOID** — thoát hoặc tránh

**Score (composite)**: Điểm tổng hợp kỹ thuật + dòng tiền (càng cao càng tốt)

---

## 8. Quản trị rủi ro & Thực thi

| Thuật ngữ | Giải thích |
|---|---|
| **T+2 Settlement** | Mua hôm nay, bán được sau **2 phiên giao dịch** (không phải 2 ngày dương lịch — nghỉ lễ và cuối tuần không tính). Backtest khoá vốn đúng 2 phiên (§18.2/7); sổ lệnh trả `sellable_on` tính qua `utils/clock.next_trading_day` nên đã trừ lịch nghỉ HOSE. §18 gọi là "T+2.5" vì tiền về trong ngày T+2 chứ không phải đầu phiên |
| **Fees** | 15bps phí + 10bps thuế = ~40bps round-trip (1bp = 0.01%) |
| **Price band** | Biên độ giá: HOSE ±7%, HNX ±10%, UPCoM ±15%. Chạm trần → skip fill |
| **ATR stops** | Stop loss = giá - 1.8×ATR20 (BUY) hoặc 2.5×ATR20 (ACCUMULATE) |
| **Kill-switch** | **Thủ công, không tự động.** Bật từ `/positions?tab=risk` (hoặc biến môi trường `TRADING_HALT`) → `SectorSignalService.publish()` phát toàn HOLD. Hai nguồn OR với nhau: env là khoá cứng trình duyệt không gỡ được (§22.10) |
| **ETF rebalance mask** | Ngày HOSE/ETF review → bỏ qua tín hiệu foreign_net để tránh nhiễu |
| **Vol-target sizing** | Size lệnh tỷ lệ nghịch với volatility (mã biến động cao → mua ít hơn) |
| **Max concurrent** | Tối đa 4 ACCUMULATE + 3 BUY + short qua VN30F1M only |
| **VN30F1M** | Hợp đồng tương lai VN30 tháng gần nhất (dùng để short) |

---

## 9. Vocabulary "trader Việt" trong báo cáo

- **"Mua gốc"** = mua ở vùng tích lũy đáy (gốc cây)
- **"Fomo vào cành cao"** = mua đuổi khi đã breakout xa, rủi ro cao
- **"Diffusion"** = dòng tiền lan tỏa nhiều mã (sóng ngành thật)
- **"Pump 1–2 mã"** = chỉ vài mã kéo, không phải sóng ngành
- **"Fade dips"** = mua khi điều chỉnh (vì xu hướng còn)
- **"Bottom-fishing"** = bắt đáy
- **"Distribution phase"** = giai đoạn phân phối (smart money bán ra)

---

## 10. Khác

- **TraderAgent ("Minh")**: Agent LLM in-process (`services/trader_agent.py`)
  viết phần bình luận trên Daily Insight và trong email. Thay bot OpenClaw
  ("Trung") đã ngừng 2026-04-18.
- **vnstock**: API/thư viện dữ liệu chứng khoán Việt Nam phổ biến
- **Catalyst**: Yếu tố xúc tác (tin tức, sự kiện) có thể đẩy giá

---

## Tóm gọn triết lý báo cáo

> Trong **CHOP regime** → không gồng lệnh, giảm size, chỉ vào khi tín hiệu chất
> lượng cao.
>
> Với stealth, tính đến 2026-08-24: gate §16.1 **chưa thắng được base rate**
> (§16.14), nên `ACCUMULATE` đọc như danh sách theo dõi. Điều kiện duy nhất từng
> thắng base rate trong thử nghiệm là `foreign_streak ≥ 3` — khối ngoại mua ròng
> **liên tiếp**, không phải "60% số phiên" — và nó cũng chưa ship vì hiệu ứng
> nằm hết ở giai đoạn trước 2026 (§16.11).

---

*Lưu ý: Đây là giải thích thuật ngữ kỹ thuật, không phải khuyến nghị đầu tư.*
