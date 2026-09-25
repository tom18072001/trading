# `daily_watch/` — báo cáo, đề xuất mua, đề xuất bán

Module riêng, tách khỏi `services/` ngày 2026-09-16. **Ba việc, không hơn:**

| # | việc | ở đâu |
|---|---|---|
| 1 | **Báo cáo** sổ hôm nay | `service.render()` mục 2 |
| 2 | **Đề xuất mua** — ứng viên | `service._shortlist()` → `long_shortlist` (luật chung với Daily Insight + email) |
| 3 | **Đề xuất bán** — cửa sổ + range | `sell_range.advise()` |

```bash
uv run python main.py --daily-watch             # chạy, ghi 3 file
uv run python daily_watch/audit.py --hold 20    # chấm lại khuyến nghị cũ (20 hoặc 40)
```

Task `SectorFlow_daily_watch` chạy lệnh đầu lúc **17:30, T2–T6**.

## File

| file | trả lời |
|---|---|
| `service.py` | dựng bản tin + ghi ra đĩa |
| `positions.py` | chấm sổ theo giá gần nhất, đường giá từ ngày vào lệnh |
| `sell_range.py` | bán lúc nào — cửa sổ (luật) + range (tham chiếu) |
| `holdings.py` | giá cho mã **đang nắm ngoài universe** — `refresh()` gọi mạng (chỉ job), `load()` chỉ đọc đĩa |
| `audit.py` | đọc kho lưu trữ, chấm lại khuyến nghị cũ — luật đang chạy **và** luật cũ (ngưỡng 2,5, `shortlist_with_cutoff`) trên cùng base |

## Đầu ra: markdown + JSON, **không HTML**

```
report/watch_<ngày>.md     bản đọc được, cũng là thứ skill tóm tắt vào chat
data/watch_latest.json     bản mới nhất, cho máy đọc
data/watch/<ngày>.json     KHO LƯU TRỮ — một file một ngày, để audit về sau
```

Không sinh HTML và không gửi email. Bản tin này để **trả lời trong chat**;
`generate_report.py` là đường HTML/PDF riêng và module này không đụng tới nó.

`data/watch/` **gitignore** — nó chứa sổ của Tom và repo này public.

## Ba luật của module

1. **Hướng phụ thuộc một chiều.** `daily_watch/` đọc `services/`, không bao giờ
   ngược lại. Có test giữ (`test_services_never_import_the_daily_watch_module`);
   đảo chiều là tạo đúng cái cycle mà bảng phân tầng ở `services/` tồn tại để
   chặn. Đây cũng là cái giá của việc rời `services/`: module này **không** còn
   được bảng phân tầng kiểm, nên guard hướng là thứ duy nhất còn lại.

2. **Cửa sổ thời gian là LUẬT, range giá là THAM CHIẾU.** Đo trên 3.446 lệnh:
   giữ hết khung thắng mọi hình học thoát bằng mức giá, và càng chặt càng tệ,
   đơn điệu. Không có stop-loss ở đây, và đó là có chủ ý (`CLAUDE.md` §26.10).

3. **Bộ lọc mua không phải danh sách theo dõi.** Universe 54 mã là bộ lọc
   *mua*. Mã đang nắm mà nằm ngoài nó vẫn phải được nhìn thấy — `holdings.py`
   lấy giá riêng, **không** áp ngưỡng thanh khoản hay room (đó là điều kiện để
   mua, không phải để được theo dõi). Gọi mạng chỉ ở job; `mark_book()` được
   route API gọi nên chỉ đọc cache.

4. **`give_back` chỉ có nghĩa sau khi đã có sóng lên.** Nó chỉ báo khi đỉnh đã
   vượt giá vào ≥ `ARM_ATR`×ATR — đúng điều kiện bench đã đo. Không có điều
   kiện đó thì nó là một stop-loss 3,5×ATR dưới giá vào.

5. **Không dự báo hướng giá.** `projection()` trả lịch và biên độ ATR. Không
   rule nào trong repo thắng VNINDEX risk-adjusted (§26.9), nên một con số
   "giá sẽ là X" là bịa — và bịa một cách thuyết phục, vì nó đứng cạnh những
   con số có bằng chứng.

## Sửa gì thì đo lại bằng gì

| sửa | đo lại bằng |
|---|---|
| hình học thoát / range | `scripts/tplus_strategy_bench.py --trail` |
| luật xếp hạng ứng viên | `scripts/ticker_alpha_bench.py --verdict` (chỉ nhận 20/40) |
| khung giữ | `docs/reviews/algo_review_2026-09-24/followup.py` (quét 10-120 phiên, ngoài bench — hệ thống chỉ dùng 20/40) |
| bỏ ngưỡng 2,5, ngoài mẫu | `daily_watch/audit.py --hold 20` / `--hold 40` |

Skill `.claude/skills/theo-doi-hang-ngay/` gọi module này và **không chứa logic
phân tích nào** — một phân tích sinh lại mỗi lần chạy là một phân tích khác nhau
mỗi lần chạy.
