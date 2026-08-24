# Trading — VN Sector Money-Flow System

Hệ thống tracking **dòng tiền theo 15 ngành VN** và dự đoán **xoay vòng sector**, thay thế cho hệ 170-symbol legacy. Nguồn đặc tả: [`CLAUDE.md`](./CLAUDE.md) (APPROVED 2026-04-08, cập nhật liên tục).

## Yêu cầu

- Python ≥ 3.11 (máy production chạy 3.13 qua `uv`), Node 20+ (cho frontend)
- [`uv`](https://docs.astral.sh/uv/) — **không phải tuỳ chọn**: `scripts/jobs/_env.bat`
  gọi `uv run python`, nên môi trường job production do `uv.lock` quyết định
- Windows cho Task Scheduler (pipeline production chạy trên máy Tom)
- Tài khoản Gmail có App Password (cho email report)

## Cài đặt

```bash
git clone … Trading && cd Trading
uv sync                        # tạo .venv theo uv.lock — dùng đúng bản production đang chạy

# Frontend
cd frontend && npm install && cd ..

# Cấu hình
cp .env.example .env           # điền DATA_SOURCE, REPORT_EMAIL_*
```

> `requirements.txt` **đã xoá** (2026-08-24). Nó thiếu `hmmlearn` và
> `matplotlib`, nên máy nào cài theo nó thì regime classifier và report render
> đều chết — mà lỗi chỉ hiện lúc job 17:00 chạy. Một repo hai manifest lệch
> nhau thì manifest không được dùng là manifest sai. `pyproject.toml` +
> `uv.lock` là nguồn duy nhất.

## Chạy trên máy mới — bước dễ quên

`uv sync` xong app **chạy được nhưng rỗng**: `vnstock_market.db` (~22 MB) bị
`.gitignore`, và `models/saved/*.pkl` cũng vậy. Không có hai thứ đó thì UI mở
lên trắng và `--publish` chết.

```bash
uv run python main.py --init                 # tạo schema + seed 15 ngành
uv run python main.py --backfill --years 5   # ~30-60 phút, gọi vnstock thật
uv run python main.py --train                # ranker đầu tiên
uv run python main.py --publish              # kiểm tra: phải in bảng 15 ngành
```

Nhanh hơn: copy `vnstock_market.db` từ máy cũ sang, rồi chỉ chạy `--train`.

Không có `.env` thì `.env.example` đủ để chạy phần đọc dữ liệu; chỉ email và
trader agent cần khoá thật.

Biến môi trường quan trọng (xem `.env`):
- `DATABASE_PATH` — mặc định `vnstock_market.db` ở root
- `DATA_SOURCE` — `KBS` (recommended), `VCI` (restricted), `TCBS` (dead)
- `REPORT_EMAIL_TO` — **comma-separated** list, ví dụ `anhchitruong18@gmail.com,hill.nguyen.1373@gmail.com`
- `REPORT_EMAIL_FROM`, `REPORT_EMAIL_PASSWORD` — Gmail App Password

## Chạy thủ công

Mỗi scheduled job tương ứng một CLI flag của `main.py` (xem `ARCHITECTURE.md` §8):

```bash
python main.py --macro              # macro_ingest   (hourly)
python main.py --intraday           # sector_intraday_flow
python main.py --eod-rollup         # sector_eod_rollup
python main.py --regime             # regime_classify
python main.py --train              # rotation_train
python main.py --rotation-predict   # rotation_predict
python main.py --publish            # sector_signal_publish (writes signals only)
python main.py --risk-sentinel      # sector_risk_sentinel

# Shorthand:
python main.py --all                # init + ingest + regime + train + publish
python main.py --backfill --years 5 # one-shot history backfill
```

Email report (`generate_report.py` là generator duy nhất — SecV2/3/4/5 đã xóa):

```bash
python generate_report.py                    # today, email + attachments
python generate_report.py 2026-08-21         # specific date
python generate_report.py --no-email         # chỉ render HTML/PDF
```

Output: `report/daily_report_<ngày>.html` + `.pdf`.

API server + frontend dev:

```bash
uvicorn api.main:app --reload --port 8000
cd frontend && npm run dev                   # http://localhost:5173
```

## Scheduled Jobs (Windows)

Đăng ký Task Scheduler 1 lần bằng PowerShell elevated:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\cleanup_scheduled_tasks.ps1
```

Script này:
1. **Unregister** mọi task Trading-related cũ (SecV2 leftovers, scratch `_run*.bat`, duplicate SecV4, v.v.).
2. **Register** đúng 8 canonical jobs của §8 dưới TaskPath `\SectorFlow\` với tên prefix `SectorFlow_`. Wrapper `.bat` nằm ở `scripts/jobs/`.

Dry-run: thêm `-WhatIf`. Giữ legacy: `-KeepLegacy`.

## Testing

```bash
python -m pytest tests/      # 156 tests — backend
cd frontend && npm test       # 13 tests — frontend (vitest)
```

Xem `CLAUDE.md` §19 cho module coverage. Live integration (`POST /api/insight/refresh` — gọi vnstock KBS + LLM provider thật) **không nằm trong pytest**, chạy tay sau khi đụng chạm các path đó.

## Tài liệu

- [`CLAUDE.md`](./CLAUDE.md) — đặc tả chiến lược (SOT)
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — layer / pipeline / dir tree
- [`MODIFICATION_LOG.md`](./MODIFICATION_LOG.md) — append-only change log (mọi sửa đổi **phải** log ở đây)
- [`specs/`](./specs/) — feature specs theo Phase 15 + cross-cutting (picks_universe, trader_agent, …)
- [`docs/reference/`](./docs/reference/) — [thuật toán chi tiết](./docs/reference/ALGORITHM.md), [từ điển thuật ngữ VI](./docs/reference/GLOSSARY_VI.md)
- [`docs/reviews/`](./docs/reviews/) — các bản review có ngày tháng (code review, optimization review)

## Nhóm ngành (15 sectors)

Ngân hàng, Chứng khoán, Bất động sản, Thép & VLXD, Bán lẻ, Thực phẩm, Dầu khí, Điện & NL, Công nghệ, Hàng không & Logistics, Bảo hiểm, Hóa chất & Phân bón, Dệt may, Cao su & Nhựa, Thủy sản. Proxy basket = top 5 constituents theo market cap (xem `config.SECTORS`, `config.PROXY_BASKETS`).

## Lưu ý

Hệ thống là **công cụ phân tích**, không phải khuyến nghị đầu tư. Mọi kết quả dự đoán mang tính tham khảo. Rủi ro cuối cùng do người giao dịch chịu — xem `CLAUDE.md` §18 cho blockers realism trước khi live paper-trade.
