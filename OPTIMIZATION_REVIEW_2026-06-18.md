# Trading Bot — Review Tối Ưu Toàn Bộ Flow

> Ngày: 2026-06-18 · Phạm vi: Code & kiến trúc · Chiến lược & alpha · Pipeline & scheduler
> Trạng thái: **BÁO CÁO — chưa sửa code.** Chờ Tom duyệt thứ tự fix.
> Cách đọc: ưu tiên giảm dần. **P0 = đang trực tiếp làm hỏng output**, sửa trước. P1 = sai lệch alpha/độ chân thực. P2 = vệ sinh code.

---

## TL;DR (3 câu)
1. Tín hiệu chủ lực của cả hệ thống — **ACCUMULATE (§16, "mua ở gốc")** — về mặt cấu trúc **không bao giờ chạy được**, vì `foreign_net = 0` ở mọi sector (ingest đọc sai cột) và `net_dollar_flow = 0` do bug trùng dòng vnstock.
2. Ranker thật sự **không hoạt động đúng**: model không được lưu nên train lại mỗi lần predict, và khi thiếu LightGBM nó rơi về "mean-flow" xếp hạng vô nghĩa (log: REAL #1 dù dòng tiền âm nặng). Các feature dẫn của §16.2 cũng **không** được nối vào model.
3. Backtest đang cho Sharpe **ảo**: thiếu T+2, thiếu thuế/phí, slippage phẳng, không price-band, vẫn short (VN cash không short được). Cộng thêm hạ tầng đơn nguồn (vnstock) + WAL-on-mount fail khiến mỗi run là một lần vật lộn thủ công.

**4 fix nhỏ nhưng đổi cục diện (làm ngay):** (1) đọc đúng foreign volume→value, (2) khử trùng dòng vnstock 1 dòng code, (3) persist/load model ranker, (4) nối feature §16.2 + đổi target 20d.

---

## P0 — Đang làm hỏng output (sửa đầu tiên)

### P0-1. `foreign_net = 0` → ACCUMULATE bất khả thi  ⭐ #1
**File:** `services/sector_ingest_service.py` → `_fetch_foreign_net`, `_fetch_foreign_buy_sell`
**Triệu chứng:** Log ghi nhận `foreign_net=0` mọi sector **từ 2026-04-16 đến nay**, lặp lại mỗi run.
**Nguyên nhân:** Hai hàm chỉ đọc cột `foreign_net_value` / `foreign_buy_value` / `foreign_sell_value`. Nguồn KBS (`price_board`) chỉ trả `foreign_buy_volume` / `foreign_sell_volume` (khối lượng, không phải giá trị). → trả 0 → stealth `cond2_foreign` fail cho **toàn bộ** 15 sector → ACCUMULATE không thể bật.
**Tác động:** Đây là tín hiệu cốt lõi của §16 (Edge Doctrine). Log cho thấy BANK (z20 +2.52), TECH (z20 +2.25) nhiều ngày đạt **4/5 cổng**, chỉ kẹt đúng cái này. Tức là edge "mua ở gốc" đang bị tắt 100%.
**Fix đề xuất:** Đọc `foreign_buy_volume`/`foreign_sell_volume`, quy đổi value ≈ volume × close (hoặc dùng `trading.foreign_trade` / `quote_history` của KBS nếu có cột value). Thêm fallback chuỗi cột để không phụ thuộc 1 schema.
**Chi phí:** ~20 dòng. **Tác động: rất cao.**

### P0-2. Bug trùng dòng cuối vnstock → `net_dollar_flow = 0`
**File:** `services/sector_ingest_service.py` → `_fetch_constituent_daily`
**Triệu chứng:** Log 2026-04-30: vnstock trả bar ngày mới nhất **2 lần** → `close == prev_close` → `sign = 0` trong `_net_dollar_flow` → flow/up/down = 0 cho mọi row nếu không vá.
**Hiện trạng:** Chỉ được vá bằng monkey-patch ngoài (`/tmp/.../ingest_dedup.py`), **chưa vào source**. Mỗi sandbox mới lại dính lại.
**Fix:** Một dòng trong `_fetch_constituent_daily`:
```python
df = df[~df.index.duplicated(keep="last")]
```
**Chi phí:** 1 dòng. **Tác động: cao** (không có nó, toàn bộ flow = 0).

### P0-3. Ranker không được lưu → train lại mỗi predict; fallback vô nghĩa
**File:** `models/rotation_ranker.py`, `services/rotation_model_service.py`
**Vấn đề:**
- `RotationRanker.fit()` chỉ ghi **JSON chứa `feature_names` + `metrics`**, KHÔNG lưu booster LightGBM. `model_path` trỏ tới file không tái tạo được model.
- `RotationModelService.__init__` tạo mới `RotationRanker()` (model=None) mỗi lần → `predict_today()` **train lại từ đầu mỗi lần gọi** (lazy-train). Lãng phí + không tái lập.
- Khi thiếu LightGBM (nhiều sandbox), rơi về `_MeanFlowRanker` = trung bình cộng các feature → xếp hạng vô nghĩa. Log 2026-04-30: REAL #1 dù `flow_z20 = -3.276` (xả mạnh).
**Fix:** `booster.save_model()` / `joblib.dump` khi train; load model active lúc khởi tạo; bỏ retrain trong predict; trên prod **fail loud** nếu thiếu LightGBM thay vì âm thầm fallback.
**Tác động: cao** (ranker là bộ não xếp hạng).

### P0-4. Feature dẫn §16.2 KHÔNG nối vào model
**File:** `services/flow_feature_service.py` (`FEATURE_COLS`)
**Vấn đề:** `flow_z20, flow_z60, foreign_streak, foreign_hit_20d, stealth_score, flow_price_divergence, accumulation_age` được tính trong `analysis/stealth.py` và ghi vào `sector_flow_daily`, nhưng `FEATURE_COLS` chỉ gồm 12 feature cơ bản. → Ranker **không nhìn thấy** tín hiệu "early". Stealth chỉ chạy như một cổng tách rời.
**Fix:** Thêm các cột §16.2 vào `FEATURE_COLS` và `_load_daily`. Đảm bảo backfill đủ trên panel.
**Tác động: cao** (đây là phần lớn alpha của doctrine).

### P0-5. Target vẫn 5 ngày, chưa 20 ngày (§16.4)
**File:** `config.py` (`ROTATION_TARGET_HORIZON_DAYS = 5`), `services/flow_feature_service.py`, `rotation_model_service.py` (`target_col="fwd_5d_sector_return"`)
**Vấn đề:** §16.4 yêu cầu **thay** target sang `fwd_20d` (5d thưởng cho chase nhiễu) + thêm **classifier head** "breakout trong 15 phiên tới?" + ensemble target (§18.3/14). Hiện chưa có gì trong số này.
**Fix:** Đổi horizon = 20, thêm head phân loại, hoặc ít nhất ensemble 10/20/40d. Retrain hàng tháng (không phải hàng đêm — flow regime đổi chậm).

### P0-6. Đơn nguồn vnstock, không fallback (§18.4/17 — BLOCKER)
**Triệu chứng:** VCI hỏng lặp lại (`KeyError 'data'`), KBS guest giới hạn 20 rpm. Mỗi sự cố nguồn làm **cả pipeline fail thầm lặng** (ingest chỉ `except` rồi bỏ qua).
**Fix:** Thêm scraper phụ (cafef hoặc SSI iBoard) làm fallback + circuit-breaker + cảnh báo Gmail khi miss 2 phiên liên tiếp. Đăng ký API key community vnstock (60 rpm) để hết retry thủ công.

### P0-7. WAL trên mount fail → vũ điệu copy DB thủ công (§18.4/18)
**Triệu chứng:** virtiofs/network mount từ chối `PRAGMA journal_mode=WAL` (disk I/O error). Mỗi run phải copy DB → local disk, làm việc, copy lại; nếu quên rename → run hôm sau dựng từ state cũ.
**Fix:** Bắt buộc DB ở local disk; thêm startup-check **từ chối network path**; nightly `sqlite3 .backup` ra file timestamp trên local disk làm bảo hiểm.

---

## P1 — Sai lệch alpha & độ chân thực (theo §18)

### P1-8. Backtest cho Sharpe ảo
**File:** `services/backtest_service.py`
Thiếu hầu hết yêu cầu §18.2:
- **Không T+2 settlement** (§18.2/7) — vốn tái sử dụng tức thì → Sharpe thổi phồng.
- **Không thuế bán 0.1% + phí round-trip** (§18.2/10) — chỉ trừ 1 hằng số commission+slippage/ngày.
- **Slippage phẳng** thay vì `max(0.3%, 0.5×ATR%)` (§18.2/9); **không price-band ±7%** (gap trần không khớp lệnh).
- **Vẫn long/short** dù VN cash không short được (§18.2/12) — chỉ nên "reduce long" hoặc hedge qua VN30F1M.
- **Không dùng ranker / không target 20d** — chỉ xếp top theo `net_dollar_flow` rồi lấy `return_1d`.
- **Không entry-timing attribution / root-capture ratio** (§16.6) — không đo được luận điểm "mua ở gốc".
→ Mọi con số Sharpe/DD hiện tại không dùng để ra quyết định được.

### P1-9. Risk sizing & §16.9 chưa có
**File:** `services/risk_service.py`, `services/sector_signal_service.py`
- Exposure equal-weight `1/n`, **không vol-target / portfolio-marginal** theo ma trận tương quan (§18.2/11).
- Quy tắc §16.9 (ACCUMULATE 1.5× size, stop 2.5×ATR, tối đa 4 vị thế ACCUMULATE, auto-exit sau 30 phiên) **chưa implement**.
- `current_exposure()` bỏ qua action `ACCUMULATE` (chỉ lọc BUY/SELL).
- Action `TRIM` (§16.3) chưa được implement trong `sector_signal_service`.

### P1-10. Survivorship / point-in-time / breadth
- **PROXY_BASKETS tĩnh top-5**, không point-in-time → back-paint lịch sử (§18.1/1 BLOCKER). Cần rebuild basket theo tháng + đóng dấu `constituent_asof`.
- **Breadth tính trên 5 mã** → gần như nhị phân, không phải "breadth" (§18.1/6). Nên tính breadth trên toàn bộ dân số sector.
- **Thiếu ETF rebalance mask** (§18.1/2 BLOCKER) và **FOL downweight** (§18.2/8): `foreign_room` đã được dùng trong `picks_universe_service` nhưng **không** dùng để hạ trọng số `foreign_net` sector.
- `foreign_net` lấy từ snapshot `price_board` **hiện tại** rồi gán cho mọi timestamp → vi phạm point-in-time; thiếu `source_ts` (§18.4/19).

### P1-11. Validation & guard rails
- **CV không purged/embargo** (§18.3/13) — chỉ split chrono 80/20 → rò rỉ qua target forward 5–20d.
- **Kill-switch `config.trading_halt`** thiếu (§18.4/20).
- **Distribution guard** §18.5/22 (giết stealth sớm khi up/down<0.5 & foreign<0) — thiếu.
- **Dual foreign check** §18.5/21 (`foreign_hit_20d≥0.6` AND `foreign_net_z20≥+0.5`) — hiện chỉ check hit-rate, dễ bị 1 block trade đánh lừa.
- **Regime-conditioned z** §18.1/3 — chưa có; +1.0 z20 trong risk_off khác hẳn risk_on.

---

## P2 — Code & kiến trúc

### P2-12. Trùng lặp khổng lồ secv3/secv4/secv5  ⭐ vấn đề code lớn nhất
**File:** `generate_secv3.py` (967) · `generate_secv4.py` (1162) · `generate_secv5.py` (1623) = **3.752 dòng**
- **~30+ hàm copy-paste qua cả 3 file**: `make_sector_flow_chart`, `make_mini_chart`, `make_correlation_heatmap`, `fetch_vnstock_news`, `compute_stop_target`, `buy_thesis/sell_thesis/watch_thesis`, `build_*`, `fmtNum/fmtM`, `_open_db`, `_latest_*`, `_render_pdf`…
- Đã **drift**: `compute_stop_target`, `fetch_vnstock_news`, `make_mini_chart` đã KHÁC nhau giữa v4 và v5 → sửa 1 chỗ không lan, dễ phát sinh bug lệch giữa email và rollback path.
- secv3 đã bị supersede **2 lần** (4/18 → secv4, 4/23 → secv5) nhưng vẫn nằm full trên disk.
**Fix đề xuất:** Tách `report_common.py` (charts, theses, news, fmt, db helpers, pdf) làm module chung; mỗi generator chỉ giữ phần layout khác biệt. Cân nhắc **xóa hẳn secv3** (giữ secv4 là rollback duy nhất). Giảm ~2.000 dòng.

### P2-13. Train lại model mỗi lần publish (lãng phí nặng)
Liên quan P0-3: `--publish` gọi `predict_today()` → nếu model=None thì train; mà model luôn None lúc process start → mỗi run scheduler train lại toàn panel. Sửa cùng P0-3 (persist/load).

### P2-14. Dead code / router legacy còn sót
- Thư mục `_trash_20260422/` còn trong repo.
- Bộ test `test_routers_stocks/trade/ml`, `test_prediction_model`, `test_data_service`, `test_trade_service` vẫn còn — thuộc hệ legacy đã REMOVE theo §2. Cần xác nhận `api/main.py` không còn đăng ký router cũ, rồi dọn.
- N+1 query nhỏ trong `risk_service.stoploss_breaches` / `sector_signal._stealth_sectors` (chỉ 15 sector nên không nghiêm trọng, để P2).

---

## Thứ tự fix đề xuất (quick wins trước)

| # | Việc | File | Công sức | Tác động |
|---|------|------|----------|----------|
| 1 | Đọc foreign volume→value | `sector_ingest_service.py` | Thấp | ⭐⭐⭐ Mở khoá ACCUMULATE |
| 2 | Khử trùng dòng vnstock | `sector_ingest_service.py` | 1 dòng | ⭐⭐⭐ Flow != 0 |
| 3 | Persist/load model ranker | `rotation_ranker.py`, `rotation_model_service.py` | Trung bình | ⭐⭐⭐ Ranker thật |
| 4 | Nối feature §16.2 + target 20d | `flow_feature_service.py`, `config.py` | Trung bình | ⭐⭐⭐ Alpha early |
| 5 | DB local-disk + startup-check + .backup | config/startup | Thấp | ⭐⭐ Hết mất data |
| 6 | Fallback nguồn + circuit-breaker + alert | ingest | Cao | ⭐⭐ Hết fail thầm |
| 7 | Backtest realism (T+2, thuế/phí, band, bỏ short) | `backtest_service.py`, `config.py` | Cao | ⭐⭐ Sharpe thật |
| 8 | Refactor secv3/4/5 → `report_common.py` | generators | Cao | ⭐ Bảo trì |

**Đề xuất:** Làm batch **1–4 trước** (đều nhỏ–vừa, gỡ thẳng vào lý do hệ thống không ra tín hiệu). Mình có thể bắt đầu ngay khi Tom duyệt — mỗi fix sẽ kèm 1 entry trong `MODIFICATION_LOG.md` theo §15.

---
*Mọi mã §16/§18 ở trên tham chiếu trực tiếp tới CLAUDE.md. Báo cáo này chưa thay đổi code nào.*
