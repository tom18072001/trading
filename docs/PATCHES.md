# PATCHES — plan nào đã xong, plan nào đang chạy

> Hai câu file này trả lời: **plan hiện tại là gì**, và **plan nào đã xong**.
> Xong thì chuyển từ bảng trên xuống bảng dưới, không giữ file plan riêng.
>
> Khác `MODIFICATION_LOG.md`: log ghi **thay đổi code** (append-only, chi
> tiết, mỗi entry một lần sửa). File này ghi **vòng đời plan** — một dòng mỗi
> plan. Không chồng nhau; log là chứng cứ, đây là mục lục.
>
> Khác `CLAUDE.md`: `CLAUDE.md` là doctrine — hệ thống *phải* thế nào. File
> này là lịch trình — việc nào đã làm.

---

## Đang làm

| plan | phạm vi | trạng thái |
|---|---|---|
| **Ranh giới module** | Nhóm `services/` theo domain (`ingest / features / decide / report / book / agent`), mỗi package khai báo public API; `tests/test_module_boundaries.py` quét AST chặn import ngược chiều; tách `generate_report.py` (1640 dòng module-level, gửi mail khi `import` — §20.3 P3-2) | **chưa bắt đầu** — rủi ro cao nhất trong 4 phase, cố ý để sau cùng. Mỗi lần move một commit. |
| **Repo clone-được** | `.github/workflows/ci.yml` (pytest + ruff + vitest), `.devcontainer/devcontainer.json`, mục README "Chạy trên máy mới" — DB 22 MB không nằm trong repo nên clone xong app chạy nhưng **rỗng** nếu không backfill | **chưa bắt đầu** — làm sau khi cấu trúc ổn định, CI mới bảo vệ đúng thứ |

---

## Đã xong

| ngày | plan | kết quả | commit |
|---|---|---|---|
| 2026-08-24 | **View theo dõi lệnh** — stop/target sống sót lúc bấm "Đã vào lệnh"; đường giá từ ngày vào lệnh | Ba tầng đều đã có dữ liệu, đứt ở đúng **một dòng**: nút mark chỉ gửi `entry_price`. Nay lưu `stop`/`target`/`thesis`, `/positions/pnl` trả thêm `path`, `hit_stop`, `sessions_held`, `sellable_on`. Không thêm endpoint, không thêm nguồn dữ liệu. 265 test (+13). §22.10 | `90304b7` |
| 2026-08-24 | **Định nghĩa breakout** (§16.15) | Nghi ngờ ban đầu (2×ATR co giãn theo tape) **sai**; lỗi thật là **đơn vị** — `atr_pct` là biên độ *ngày*, bar ~1.15%, áp lên max 40 phiên nên 83% sector-day "breakout". `atr_scaled` ≈ 7.2%. Bench đo, không ship vào scanner | `cd4928f` |
| 2026-08-24 | **Sập ở đoạn gần đây** (§25.9) | Cả gate §16.1 lẫn horizon sweep đều hỏng ở cùng một giai đoạn → **là tape, không phải model**. Chia theo tercile vol: AUC 0.827/0.790/0.694, đơn điệu, và lịch chỉ là proxy cho vol | `262bca6` |
| 2026-08-24 | **Bán ≠ xoá; `CONF_HORIZON` được đo** | `close_position()` tách khỏi `remove_position()` — trước đó "tôi bán ở 28" và "tôi bấm nhầm" là cùng một thao tác, nên sổ không thể trả lời picks có lãi không. P&L realised **net** chi phí §18.2/10. `CONF_HORIZON=5` giữ lại vì là horizon dài nhất dương ở **cả ba** giai đoạn | `4363f0e` |
| 2026-08-24 | **Regime confidence** (§25) | Số 1.00 là **model sập**, không phải model tự tin: 3/4 state chạm trần covariance vì feature chưa chuẩn hoá. Chuẩn hoá + 1500 ngày + `fit()` từ chối fit sập. `confidence` nay = P(nhãn giữ 5 phiên), 0.46–0.91. Đóng §20.3 P1-4 | `ce9c7d1` `501afe9` `52bc11b` |
| 2026-08-24 | **Base rate của gate §16.1** (§16.12) | Thêm dòng "không gate" vào bench: gate **thua cả việc không lọc**. §16.11's ba tiêu chí tuyệt đối không phát hiện được điều đó → sửa doctrine: phải thắng base rate **trong từng năm** | `8959b52` `4962be7` |
| 2026-08-23 | **Gate §16.1 bất khả thi** (§16.1) | AND 5 điều kiện: 0.3% số dòng, chuỗi dài nhất 2 phiên / yêu cầu 3. Đổi thành **điểm** ≥4/5 → 23 event đầu tiên trong lịch sử hệ thống. Đóng §20.3 P1-1 | `c96efc7` |
| 2026-08-23 | **Filter + preset + gửi báo cáo** (§24) | Một bộ từ vựng filter (`lib/filters.tsx`), state nằm trong URL; preset stealth định giá tranh cãi P1-1 **bằng đơn vị ngành**; `POST /state/report/send` chạy subprocess | `6381f89` |
| 2026-08-23 | **Backtest controls** (§23) | Lộ ra 5 thứ service đã làm nhưng UI không với tới. Phát hiện `flow_z` **chính là** `flow_raw`: z cross-sectional là ánh xạ affine dương nên giữ nguyên thứ tự | `3b76f64` |
| 2026-08-23 | **Operator state** (§22.10) | Kill-switch runtime, sổ vị thế, watchlist, thanh tuổi dữ liệu. Trước đó mọi thứ trên màn hình đều là output của model — app không biết Tom đã làm gì | `d873783` |
| 2026-08-23 | **Gộp nav 9 → 5** (§22.9) | Mỗi lần gộp bỏ đi một lần chuyển ngữ cảnh, không bỏ trang nào; tab nằm trong URL | `ea634e1` `c48a684` |
| 2026-08-23 | **Audit frontend** (§22) | 7 defect đo được; trang chủ rỗng sau mỗi lần restart (§22.6); suite vitest đỏ trong khi §19 ghi là xanh | `cc24169` `215be95` `e69aeb6` |
| 2026-08-22 | **Code review** (§20) | 22 finding. Chuỗi nhân quả chính bắt đầu ở `sector_flow_daily` ghi thiếu `close_idx` — nuôi target ML, điều kiện 5 của §16.1 và toàn bộ P&L backtest | xem `docs/reviews/CODE_REVIEW_2026-08-22.md` |

---

## Quy tắc

1. Plan mới → thêm dòng vào **Đang làm**, không tạo file plan riêng trong repo.
2. Plan xong → chuyển xuống **Đã xong** kèm commit hash. Xoá dòng ở bảng trên.
3. Chi tiết *tại sao* nằm ở `MODIFICATION_LOG.md`; doctrine nằm ở `CLAUDE.md`.
   Ở đây chỉ một dòng — nếu cần dài hơn thì nó thuộc về một trong hai file kia.
