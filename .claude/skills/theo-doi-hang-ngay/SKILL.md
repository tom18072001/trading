---
name: theo-doi-hang-ngay
description: Ba việc — báo cáo sổ, đề xuất mua, đề xuất bán. Chạy bản theo dõi hằng ngày cho sổ cổ phiếu của Tom và tóm tắt lại; khuyến nghị bán (cửa sổ 20-40 phiên + range giá trượt lên) cho các mã đang nắm, danh sách ứng viên mới, và ghi nhận khi Tom mua hoặc bán. Dùng khi Tom hỏi "hôm nay thế nào", "nên bán mã nào chưa", "quét cho tôi", "tôi vừa mua X", "tôi đã bán X", hoặc khi cần đọc lại kết quả của scheduled task daily_watch. Không dùng stop-loss — đã bỏ có chủ ý kèm phép đo.
---

# Theo dõi hằng ngày

**Ba việc, không hơn** (Tom, 2026-09-16):

| # | việc | nguồn |
|---|---|---|
| 1 | **Báo cáo** — sổ hôm nay ra sao | mục 2 bản tin |
| 2 | **Đề xuất mua** — mã nào đáng xem | mục 3 bản tin (`shortlist`) |
| 3 | **Đề xuất bán** — mã đang nắm, bán khi nào | `sell_range` từng vị thế |

Mọi thứ khác — giải thích thuật toán, bàn về chi phí, đo một ý tưởng mới — là
việc của tài liệu và của bench, không phải của bản tin hằng ngày.

**Skill này không phân tích. Nó chạy code đã có và tóm tắt kết quả.**

Toàn bộ logic nằm ở **`daily_watch/`** — một module riêng, đã commit, đã test,
chạy lần nào cũng ra cùng một số. Đọc `daily_watch/README.md` trước khi sửa gì.

| module | trả lời |
|---|---|
| `daily_watch/service.py` | dựng bản tin: sổ + cảnh báo + ứng viên |
| `daily_watch/positions.py` | chấm sổ theo giá gần nhất, đường giá từ ngày vào lệnh |
| `daily_watch/sell_range.py` | **bán lúc nào** — cửa sổ thời gian (luật) + range giá (tham chiếu) |
 Đừng viết lại phép tính nào ở đây: một phân tích được sinh lại mỗi lần
chạy là một phân tích khác nhau mỗi lần chạy, và hai kết quả không so được với
nhau. Nếu công thức cần đổi thì sửa module, không sửa prompt.

## 1. Chạy

```bash
uv run python main.py --daily-watch
```

Ghi ra hai file:
- `report/watch_<ngày>.md` — bản cho người đọc
- `data/watch_latest.json` — bản cho máy đọc

Scheduled task `SectorFlow_daily_watch` chạy lệnh này lúc **17:30, T2-T6**. Nếu
Tom hỏi vào lúc khác, cứ chạy lại — nó rẻ và không gửi gì đi đâu.

### Lưu trữ để audit — mỗi lần chạy đều ghi, đừng bỏ qua

Bản thứ ba, `data/watch/<ngày>.json`, là **kho lưu trữ**: một file một ngày,
không ghi đè ngày khác. Nó tồn tại vì §26.1 — khi Tom hỏi *"picks có tốt
không"*, repo **không trả lời được**, phải bới 174 pick ra khỏi kho HTML.

Kho **tự chấm được**: mỗi bản lưu ghi cả khuyến nghị lẫn `marks` (giá đóng mọi
mã nó nhắc tới), nên N bản lưu tự cho một chuỗi giá.

```bash
uv run python daily_watch/audit.py --hold 20
```

Khi Tom hỏi *"khuyến nghị trước đây thế nào"*, chạy lệnh này — **đừng tự nhớ và
đừng tự tính lại**. Nếu nó nói chưa đủ dữ liệu thì trả lời đúng như thế; một con
số dựng từ 2 bản lưu là nhiễu, không phải câu trả lời (§26.8).

Kho **gitignore** vì nó chứa sổ của Tom và repo này public.

## 2. Tóm tắt cho Tom

Đọc `report/watch_<ngày>.md` rồi tóm tắt **theo đúng thứ tự này**, vì nó là thứ
tự khẩn cấp:

1. **Quá hạn** — đã giữ quá 40 phiên. Ngoài khung đó không factor nào sống sót
   phép đo, nên đây là mục khẩn nhất.
2. **Nhả quá sâu** — giá đã rơi hơn 3,5×ATR từ đỉnh. Đây là tin về *luận điểm*
   ("sóng lên đã kết thúc"), **không phải lệnh bán cơ học**.
3. **Trong cửa sổ bán** — đã qua 20 phiên, chưa tới 40. Nêu range tham chiếu.
4. **Sổ** — một dòng: mấy vị thế, tổng P&L.
5. **Các ngày tới** — mốc nào sắp tới (mở cửa sổ bán / hết khung) và ngày của nó.
6. **Ứng viên** — tối đa 5 mã, kèm giá/điểm.

Nếu không có cảnh báo nào thì nói thẳng "không có gì cần làm hôm nay" ở câu đầu
thay vì bắt Tom đọc hết bảng mới biết.

### Không còn stop-loss (2026-09-16)

Tom bỏ stop và thay bằng khuyến nghị bán. Đo trên 3.446 lệnh: **giữ hết khung
thắng mọi hình học thoát bằng mức giá, và càng chặt càng tệ, đơn điệu** — kể cả
băng neo ở đỉnh. Nên khi tóm tắt:

- **Luật là CỬA SỔ THỜI GIAN** (`sell_from` → `sell_by`, 20-40 phiên). Nói nó ra
  như một luật.
- **Range giá là THAM CHIẾU.** Không bao giờ viết "bán ở 52.40" như một lệnh.
  Nói "range tham chiếu 48.00–52.40" và để Tom quyết.
- Nếu Tom hỏi có nên đặt stop không: trả lời bằng bảng đo, đừng tự đặt lại.

### Ba câu phải giữ, không được bỏ khi tóm tắt

- **Danh sách ứng viên là shortlist, không phải lệnh mua.** Chưa luật xếp hạng
  nào thắng VNINDEX risk-adjusted (§26.9).
- **Khung giữ 20-40 phiên.** Không phải T+3. Dưới 20 và trên 40 phiên thì không
  factor nào sống sót phép đo.
- **Danh sách rỗng là câu trả lời, không phải lỗi** — nó rỗng khi cả bảng đang
  quá mua (§26.4).

## 3. Khi Tom hỏi "nên bán lúc nào"

Trả lời bằng **ba con số theo đúng thứ tự này**, lấy từ `sell_range` của vị thế:

1. **Cửa sổ bán** `sell_from → sell_by`. Đây là luật. Nếu chưa tới, nói còn mấy
   phiên nữa và nói thẳng *"luật đo được là giữ hết khung"*.
2. **Range tham chiếu** `band_lo – band_hi`. Nói rõ đây là tham chiếu.
3. **Mức nhả quá sâu** `give_back`. Chỉ nhắc khi giá đang gần hoặc đã dưới nó.

Ba điều không được làm khi trả lời câu này:
- **Không nói "bán ở X"** như một lệnh. Range là vùng, cửa sổ là luật.
- **Không tự đặt lại stop**, kể cả khi lệnh đang lãi to và nghe có vẻ hợp lý.
  Nó bị bỏ có chủ ý, có bảng đo đứng sau — dẫn bảng đó ra.
- **Không quên nói mình không phải nhà tư vấn có giấy phép.** Đây là output hệ
  thống của Tom, quyết định là của Tom.

## 3b. Dịch range lên — phần Tom cho phép dùng phán đoán

Tom: *"range có thể thay đổi theo thời gian nếu bạn cảm thấy nó vẫn có sóng
lên."* Range **tự** trượt lên rồi: nó neo ở đỉnh đã đạt, nên mã lập đỉnh mới là
range lên theo, không cần ai can thiệp.

Ngoài cơ chế đó, được **đề xuất** dịch range, với ba ràng buộc:

1. **Đề xuất, không tự sửa.** Không đụng `daily_watch/sell_range.py`, không đụng
   hằng số. Nói con số đề xuất và lý do, để Tom quyết.
2. **Nói rõ đó là phán đoán, không phải phép đo.** Mọi hằng số trong module đều
   truy được về một bảng đo; một con số anh đề xuất thì không, và phải nói thế.
3. **Không biến nó thành luật thoát.** Đã đo: thoát cơ học ở bất kỳ mức giá nào
   đều thua giữ hết khung, càng chặt càng tệ. Một range dịch lên vẫn chỉ là
   tham chiếu.

Lý do hợp lệ để đề xuất dịch lên: mã lập đỉnh mới liên tiếp, khối lượng xác
nhận, ngành cùng chạy. Lý do **không** hợp lệ: "đang lãi nhiều nên nới ra cho
chắc" — đó là điều chỉnh theo cảm xúc, không theo tape.

## 3c. Dự phóng các ngày tới — được nói gì, cấm nói gì

Mục 4 của bản tin (`projection` trong JSON) có sẵn lịch và biên độ. Tom muốn nó
"để dễ tham chiếu", nên hãy dùng — nhưng giữ đúng ranh giới:

**Được nói:**
- **Lịch.** "Cửa sổ bán mở sau 4 phiên, ngày 22/09; hết khung 20/10." Đây là
  phép đếm, chắc chắn đúng.
- **Biên độ.** "Trong 5 phiên tới XYZ thường dao động trong 46,5 – 53,5 (±7%)."
  Đây là ATR của chính mã đó giãn theo căn số phiên.
- **Cái gì sẽ đổi khi giá đi.** "Range bán tự dịch lên nếu XYZ lập đỉnh mới."

**Cấm nói:**
- **Hướng giá.** Không "XYZ sẽ lên 55", không "nhiều khả năng tăng", không xác
  suất. Không rule nào trong hệ thống thắng VNINDEX risk-adjusted (§26.9) — một
  dự báo hướng là bịa, và bịa một cách nghe rất thuyết phục.
- **Đọc ±% như khoảng tin cậy.** ATR là biên độ *ngày*, không phải độ lệch
  chuẩn. "±15,3% sau 24 phiên" không có nghĩa "68% khả năng nằm trong đó".
- **Biến biên độ thành mức mua/bán.** Cạnh trên của biên độ không phải target.

Nếu Tom hỏi thẳng "mấy ngày tới nó lên hay xuống": trả lời rằng hệ thống không
dự báo hướng và nói tại sao — rồi đưa lịch + biên độ, là thứ nó **có** trả lời
được. Đừng đoán để cho có câu trả lời.

## 4. Khi Tom nói đã mua

```bash
curl -s -X POST localhost:8000/api/state/positions \
  -H "Content-Type: application/json" \
  -d '{"symbol":"VIC","entry_price":241.3,"qty":1000}'
```

**Đừng điền `stop`.** Bỏ từ 2026-09-16 — xem trên. Cảnh báo chạy theo cửa sổ
thời gian, và nó cần `opened_at` (tự đóng dấu) chứ không cần mức giá nào.

Nếu backend không chạy, gọi thẳng module:

```bash
uv run python -c "from services import trading_state; print(trading_state.add_position('VIC', entry_price=241.3))"
```

## 5. Khi Tom nói đã bán

Vị thế **không tự đóng** — nó được theo dõi cho tới khi Tom nói đã bán.

```bash
curl -s -X POST localhost:8000/api/state/positions/VIC/close \
  -H "Content-Type: application/json" -d '{"exit_price":260.0}'
```

`close` ≠ `DELETE`. Close ghi lại lệnh đã đóng kèm P&L thật; DELETE xoá sạch và
chỉ dùng khi Tom bấm nhầm.

> P&L realised trừ **0,40%/vòng** (phí + thuế bán), **không** trừ slippage — nên
> nó lạc quan hơn con số 1,00%/vòng mà bench dùng (§26.6). Khi báo P&L đã đóng,
> đừng trình bày nó như đã net đủ chi phí. Hỏi cho rõ nếu
không chắc Tom muốn cái nào — sai hướng này thì mất luôn lịch sử lãi/lỗ.

## 6. Không làm gì trong số này

- **Không tự đặt lệnh, không tự mua bán.** Skill chỉ ghi lại việc Tom đã làm.
- **Không sửa điểm, ngưỡng hay công thức** để danh sách dài ra. `MIN_BUY_SCORE`
  là phân vị đo được, không phải nút vặn.
- **Không gửi email.** Tom chưa muốn (2026-09-16); task chỉ ghi file.
- **Không tự dựng lại stop.** Nó bị bỏ có chủ ý, có phép đo đứng sau.
- **Không xoá hay sửa file trong `data/watch/`.** Nó là bằng chứng cho phần
  audit sau này; một bản lưu bị sửa là một bản lưu không dùng được.
- **Không viết lại công thức range bán.** Nó ở `daily_watch/sell_range.py`; đổi ý
  nghĩa thì sửa module rồi đo lại bằng `tplus_strategy_bench.py --trail`.
- **Không trích cạnh trên của range như số đã kiểm chứng.** `band_hi` = +1×ATR
  trên đỉnh là chọn cho dễ đọc, không đo được. Cạnh dưới và cửa sổ thời gian thì
  có bằng chứng; cạnh trên thì không.

## 7. Khi cần đo một thuật toán mới

Đó là việc khác, dùng bench: thêm một file ở `scripts/factors/`, chạy
`uv run python scripts/ticker_alpha_bench.py --horizons 20,40 --verdict`.
Xem `scripts/factors/README.md`. Đừng đo bằng cách sửa skill này.
