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

**Confidence 0.50**: Độ tin cậy của model về regime hiện tại (0–1). 0.5 nghĩa là model chỉ "hơi nghiêng" về CHOP, chưa chắc chắn.

---

## 2. ⭐ STEALTH — Khái niệm trọng tâm

### Stealth Accumulation là gì?

Đây là khái niệm **"tích lũy âm thầm"** xuất phát từ học thuyết Wyckoff/Tom Williams (VSA — Volume Spread Analysis). Ý tưởng: **dòng tiền thông minh (smart money / tổ chức) gom hàng từ từ ở vùng đáy mà không tạo biến động giá lớn** — họ cố tình "ẩn dấu vết" để không kéo giá lên trước khi gom đủ.

Mục tiêu của trader: **phát hiện dấu vết âm thầm này TRƯỚC khi breakout** → "mua gốc" thay vì "fomo vào cành cao" (mua đỉnh).

### 5 Điều kiện Stealth (§16.1 — "Tom's doctrine")

Một ngành chỉ được gọi là **STEALTH ACCUMULATION** khi đồng thời thỏa **cả 5**:

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

- **PRE-STEALTH (watch)**: Đạt một phần điều kiện, đang theo dõi (Hóa chất, Thủy sản, Điện, Dệt may)
- **early signal**: Mới chớm tín hiệu, chưa đủ chín
- **STEALTH (đầy đủ)**: Đủ 5/5 điều kiện → vào lệnh "mua gốc"

> Báo cáo hôm nay nói rõ: **"chưa sector nào đạt đủ 5 điều kiện §16.1"** → giữ tiền mặt, không mua mới.

**Accum. Age**: Số ngày liên tiếp ngành duy trì trạng thái stealth. Càng cao → tín hiệu càng "trưởng thành" (mature).

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
| **T+2.5 Settlement** | Cổ phiếu mua hôm nay chỉ bán được sau 2.5 ngày → mọi backtest Sharpe phải trừ lag này |
| **Fees** | 15bps phí + 10bps thuế = ~40bps round-trip (1bp = 0.01%) |
| **Price band** | Biên độ giá: HOSE ±7%, HNX ±10%, UPCoM ±15%. Chạm trần → skip fill |
| **ATR stops** | Stop loss = giá - 1.8×ATR20 (BUY) hoặc 2.5×ATR20 (ACCUMULATE) |
| **Kill-switch** | Nếu sector_risk_sentinel kích hoạt 3 lần/phiên → dừng toàn bộ lệnh ACCUMULATE mới |
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

- **OpenClaw bot**: Bot tự động crawl tin từ vnstock, CafeF, VietstockFinance
- **vnstock**: API/thư viện dữ liệu chứng khoán Việt Nam phổ biến
- **Catalyst**: Yếu tố xúc tác (tin tức, sự kiện) có thể đẩy giá

---

## Tóm gọn triết lý báo cáo

> Trong **CHOP regime** → **không gồng lệnh, chỉ "mua gốc" khi STEALTH chín đủ 5/5 điều kiện**.
>
> Hôm nay 16/04/2026 chưa có ngành nào đạt → **giữ tiền mặt là thượng sách**, chỉ có 1 lệnh BUY nhỏ NVL với stop sát.

---

*Lưu ý: Đây là giải thích thuật ngữ kỹ thuật, không phải khuyến nghị đầu tư.*
