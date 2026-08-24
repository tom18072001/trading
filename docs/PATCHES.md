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
| **Siết bảo mật sau khi repo public** | `API_REQUIRE_KEY=0` và CORS mở là mặc định — ai đọc code cũng biết endpoint nào ghi được. Rủi ro thật còn thấp vì API bind localhost (§22.4 đã đưa Vite khỏi `0.0.0.0`), nhưng hết thấp ngay khi expose ra ngoài | **ghi nhận, chưa sửa** — Tom chọn không đổi hành vi hôm nay; bật `API_REQUIRE_KEY=1` sẽ làm hỏng frontend dev + 8 job scheduler cho tới khi cấu hình key |

---

## Đã xong

| ngày | plan | kết quả | commit |
|---|---|---|---|
| 2026-08-24 | **Lịch sử stealth là stub, không phải bảng rỗng** (§22.11) | `/api/stealth/history` trả `{"rows": []}` **hardcode** từ ngày viết — §22.1 xếp nhầm vào "code đúng, không có dữ liệu". Nhầm rẻ: khi cổng AND §16.1 thật sự cho 0 event thì stub và sự thật giống hệt nhau. Nay suy ra từ `accumulation_age` (**không** đọc `sector_accumulation_events` — bảng đó chưa từng có writer, và nếu có thì một sự thật nằm ở hai chỗ). `classification` **nullable**: run đang chạy hoặc chưa đủ 40 phiên là *chưa chấm được*, không phải trượt. Bar breakout chuyển từ `scripts/` sang `analysis/` vì đã có 2 caller — hai bản sao sẽ lệch mà không ai thấy. Live: 21 event, 20 chấm được, hit 40%, lead trung vị 21. **Negative control bắt được 1 test vô dụng**: bản đầu của test open-run vẫn xanh khi xoá guard, vì fixture chạm guard khác trước. 342 test (+14), ruff 65 | `(this)` |
| 2026-08-24 | **Repo public — bỏ email khỏi git** | Quét toàn bộ lịch sử trước: không blob nào chứa key thật; `.env.example` là tên file "nhạy cảm" duy nhất từng commit. Hai defect: `generate_report.py` **hardcode 3 địa chỉ thật** làm fallback cho `REPORT_EMAIL_TO` (không đổi hành vi máy này — `.env` đã set nên env thắng, job 17:00 vốn gửi 2 người chứ không phải 3), và một **log runtime lọt qua rule ignore hụt** (`report/jobs/*.log` không khớp `.log.err`). +2 guard, kiểm chứng bằng negative control: tiêm lại địa chỉ fallback thì đúng 2 test đỏ. 328 test, ruff 65. **Địa chỉ vẫn còn trong lịch sử** — Tom chọn không rewrite (đã từng phải purge `cloudflared.exe`), coi như đã lộ | `eab5a1e` |
| 2026-08-24 | **Đẩy lên GitHub** | `chore/2026-08-audit` fast-forward `90304b7 → 0c7a6bb`, rồi merge `--no-ff` vào `master`. **Không force-push** — lịch sử đã từng phải purge `cloudflared.exe` nên viết lại lần nữa là rủi ro thừa; merge-base cho thấy 2 commit `master` đi trước chỉ là merge commit, nội dung là tập con, nên không có gì để rebase. Trước mỗi lần push: `git status`/`git ls-files` không thấy `.env`/`*.db`/`*.bak-*`, và quét nội dung diff chỉ ra 3 khớp — cả ba là **tên biến** (`REPORT_EMAIL_PASSWORD`, `LOCAL_API_KEY`), không phải giá trị. Suite trên `master` sau merge: 326 pass | `293b85d` |
| 2026-08-24 | **Repo clone-được** | CI (`uv`, không phải pip — production chạy `uv run`), devcontainer, mục README "Chạy trên máy mới". Hai defect thật: **`requirements.txt` là tập con thiếu `hmmlearn` + `matplotlib`** (cài theo README thì regime classifier và report render đều chết, mà chỉ lộ lúc job 17:00 chạy) → xoá, giữ `pyproject.toml` + `uv.lock`; và **pytest/ruff chưa từng được khai báo** → clone sạch không chạy nổi test. Suite lần đầu chạy trên interpreter production (3.13): 326 pass. Kiểm chứng bằng bài test duy nhất bắt được lỗi loại này: **clone sạch sang thư mục tạm** → `uv sync --frozen` + `uv run pytest` = **325 pass, 1 skip** (skip là `test_the_live_ranker_still_has_real_features`, đúng thiết kế vì clone sạch chưa có model) | `0c7a6bb` |
| 2026-08-24 | **Ranh giới module** (§20.3 P3-2 + `ARCHITECTURE.md` §4.1) | **Đo trước rồi mới sửa, và phép đo đổi luôn kế hoạch**: graph `services/` vốn đã là DAG nông (17 module, sâu tối đa 2, 0 vi phạm layer) → **không file nào phải move**; thiếu là *cách giữ*, không phải cấu trúc. Bắt được 2 defect: cycle `services → api → services` và `scripts/seed_data.py` import module đã xoá 4 tháng. Nửa sau: `generate_report.py` **113 → 4** câu lệnh module-level, `import` không còn gửi mail; chỉ tách phần thuần (charts, SQL, formatter) — HTML weave **cố ý giữ nguyên**. Lộ ra defect thứ ba, nặng hơn cả hai: **chạy pytest ghi đè model production** (`fit()` ghi thẳng `models/saved/`, gitignore nên git không thấy, job 17:00 chết). 326 test (+19), ruff 67 → 65 | `4aa783a`, `3c2cfd3` |
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
