# Trading — VN Sector Money-Flow System

Hệ thống tracking **dòng tiền theo 15 ngành VN** và dự đoán **xoay vòng sector**, thay thế cho hệ 170-symbol legacy. Nguồn đặc tả: [`CLAUDE.md`](./CLAUDE.md) (APPROVED 2026-04-08, cập nhật liên tục).

## Yêu cầu

- Python 3.11, Node 20 (cho frontend)
- Windows cho Task Scheduler (pipeline production chạy trên máy Tom)
- Tài khoản Gmail có App Password (cho email report)

## Cài đặt

```bash
git clone … Trading && cd Trading
python -m venv .venv
.venv\Scripts\activate         # Windows
# source .venv/bin/activate    # Linux/macOS
pip install -r requirements.txt

# Frontend
cd frontend && npm install && cd ..

# Cấu hình
cp .env.example .env           # điền DATA_SOURCE, REPORT_EMAIL_*
```

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

Email report (chỉ SecV4 là active, SecV3 giữ làm rollback):

```bash
python generate_secv4.py                    # today, email + attachments
python generate_secv4.py 2026-04-21          # specific date
python generate_secv4.py --no-email          # chỉ render HTML/PDF
```

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
python -m pytest tests/      # 78 tests — backend
cd frontend && npm test       # 13 tests — frontend (vitest)
```

Xem `CLAUDE.md` §19 cho module coverage. Live integration (`POST /api/insight/refresh` — gọi vnstock + Claude Agent SDK thật) **không nằm trong pytest**, chạy tay sau khi đụng chạm các path đó.

## Tài liệu

- [`CLAUDE.md`](./CLAUDE.md) — đặc tả chiến lược (SOT)
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — layer / pipeline / dir tree
- [`MODIFICATION_LOG.md`](./MODIFICATION_LOG.md) — append-only change log (mọi sửa đổi **phải** log ở đây)
- [`specs/`](./specs/) — feature specs theo Phase 15 + cross-cutting (picks_universe, trader_agent, …)
- [`docs/`](./docs/) — changelog, thuật toán chi tiết, notes nội bộ

## Nhóm ngành (15 sectors)

Ngân hàng, Chứng khoán, Bất động sản, Thép & VLXD, Bán lẻ, Thực phẩm, Dầu khí, Điện & NL, Công nghệ, Hàng không & Logistics, Bảo hiểm, Hóa chất & Phân bón, Dệt may, Cao su & Nhựa, Thủy sản. Proxy basket = top 5 constituents theo market cap (xem `config.SECTORS`, `config.PROXY_BASKETS`).

## Lưu ý

Hệ thống là **công cụ phân tích**, không phải khuyến nghị đầu tư. Mọi kết quả dự đoán mang tính tham khảo. Rủi ro cuối cùng do người giao dịch chịu — xem `CLAUDE.md` §18 cho blockers realism trước khi live paper-trade.
