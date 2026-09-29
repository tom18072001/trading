---
name: theo-doi-hang-ngay
description: Ba việc — báo cáo sổ, đề xuất mua (có thứ tự ưu tiên), đề xuất bán. Chạy bản theo dõi hằng ngày cho sổ cổ phiếu của Tom và tóm tắt lại; kết luận GIỮ / BÁN cho từng mã đang nắm (xem lại mỗi 20 phiên từ ngày mua, bán nếu ngoài top 16), danh sách mua theo ưu tiên A/B, và ghi đúng khi Tom báo mua hoặc bán (mua thêm = giá vốn bình quân, bán một phần). Dùng khi Tom hỏi "hôm nay thế nào", "nên bán mã nào chưa", "quét cho tôi", "tôi vừa mua X giá Y", "tôi đã bán X", hoặc khi cần đọc lại kết quả của scheduled task daily_watch. Không dùng stop-loss hay chốt lời theo giá mua — đã đo, thua.
---

# Theo dõi hằng ngày

**Ba việc, không hơn** (Tom, 2026-09-16):

| # | việc | nguồn |
|---|---|---|
| 1 | **Báo cáo** — sổ hôm nay ra sao | mục 2 bản tin |
| 2 | **Đề xuất mua** — mã nào, mua mã nào trước | mục 3 bản tin (`shortlist`, cột ưu tiên A/B) |
| 3 | **Đề xuất bán** — GIỮ hay BÁN từng mã đang nắm | mục 1-2 bản tin (`verdict` từng vị thế) |

**Luật chơi của Tom (2026-09-29):** *"bạn khuyến nghị mã nào nên mua hằng ngày (có các
priority) · tôi báo bạn mua con nào giá thế nào · khi tôi bán tôi báo · bạn cập nhật
những con tôi đang hold và đề xuất có nên bán hay không"*. Mỗi lần Tom báo mua/bán:
ghi ngay (mục 4-5), rồi trả lời bằng kết luận mới của cả sổ.

Mọi thứ khác — giải thích thuật toán, bàn về chi phí, đo một ý tưởng mới — là
việc của tài liệu và của bench, không phải của bản tin hằng ngày.

**Skill này không phân tích. Nó chạy code đã có và tóm tắt kết quả.**

Toàn bộ logic nằm ở **`daily_watch/`** — một module riêng, đã commit, đã test,
chạy lần nào cũng ra cùng một số. Đọc `daily_watch/README.md` trước khi sửa gì.

| module | trả lời |
|---|---|
| `daily_watch/service.py` | dựng bản tin: sổ + cảnh báo + ứng viên |
| `daily_watch/positions.py` | chấm sổ theo giá gần nhất, đường giá từ ngày vào lệnh |
| `daily_watch/sell_range.py` | **bán lúc nào** — lịch xem lại + kết luận GIỮ/BÁN (luật) + range giá (tham chiếu) |
| `daily_watch/book.py` | **ghi đúng điều Tom báo** — mua (giá vốn bình quân), bán (cả / một phần), ngày mua |

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
uv run python daily_watch/audit.py --hold 20    # hoặc --hold 40
```

Nó chấm cùng lúc luật đang chạy (động lượng, từ 29/09), luật cổng SMA200
trước nó (`shortlist_previous_rule`, ghi vào kho mỗi ngày từ 29/09), luật có
ngưỡng 2,5 (`shortlist_with_cutoff`, 25-28/09) và base NO GATE — phép đo ngoài
mẫu cho cả hai lần đổi luật. Khi Tom hỏi *"khuyến nghị trước đây thế nào"*, chạy lệnh này — **đừng tự nhớ và
đừng tự tính lại**. Nếu nó nói chưa đủ dữ liệu thì trả lời đúng như thế; một con
số dựng từ 2 bản lưu là nhiễu, không phải câu trả lời (§26.8).

Kho **gitignore** vì nó chứa sổ của Tom và repo này public.

## 2. Tóm tắt cho Tom

Đọc `report/watch_<ngày>.md` rồi tóm tắt **theo đúng thứ tự này**, vì nó là thứ
tự khẩn cấp. Từ 29/09 bản tin không còn mục "Quá hạn", "Nhả quá sâu", "Trong cửa sổ
bán" — nơi nào còn nhắc thứ tự cũ đó thì dùng thứ tự dưới đây:

1. **Việc cần làm hôm nay** (mục 1 bản tin) — mã có kết luận **BÁN** (kèm lý do:
   tới kỳ xem lại mà ngoài top 16, hoặc chưa có ngày mua và ngoài top 16), và mã
   **CHƯA XẾP ĐƯỢC** (thiếu giá / thiếu 6 tháng lịch sử).
2. **Sổ** (mục 2) — mỗi mã một dòng: giá vốn, giá gần nhất, lãi/lỗ, hạng, **GIỮ/BÁN**,
   kỳ xem lại tới. Một dòng tổng.
3. **Mua gì** (mục 3) — danh sách theo **ưu tiên**: A (đã ở top 8 ≥ 11 phiên, xu hướng
   bền) trước B (mới vào), trong mỗi nhóm theo hạng; mỗi mã kèm **vùng mua** và **kỳ
   vọng 4 / 8 tuần**. Nói **mua thêm tối đa bao nhiêu mã** (8 trừ số mã đang GIỮ). Kỳ
   vọng là phân phối đo được, không phải dự báo; nếu VNINDEX dưới trung bình 200 phiên
   thì nhắc câu bối cảnh thị trường của bản tin.
4. **Các ngày tới** — kỳ xem lại gần nhất của từng mã và ngày của nó.

Nếu không có mã nào cần bán thì nói thẳng "không có gì cần bán hôm nay" ở câu đầu
thay vì bắt Tom đọc hết bảng mới biết.

### Luật bán (2026-09-29) — đồng hồ của từng vị thế

Đo trong `docs/reviews/WORKFLOW_STUDY_2026-09-29.md`, 7 biến thể đăng ký trước:

- **Mỗi mã có đồng hồ riêng từ ngày Tom mua**: xem lại ở phiên 20, 40, 60… Tới kỳ
  mà mã **ngoài top 16** thì **bán ATO phiên kế**; còn trong top 16 thì giữ tới kỳ
  sau, **không giới hạn** số phiên. Giữa hai kỳ thì giữ, kể cả khi hạng tụt.
- **Giá mua KHÔNG quyết định bán.** Chốt lời +20% / +30% mất 8 / 5 điểm/năm; bán
  cứng ở phiên 40 mất 6,5; cắt lỗ −10% không ổn định (tệ hơn ở 3/6 năm), −15% không
  giúp. Lãi/lỗ so với giá mua được in ra để Tom biết, không phải để quyết.
- Mã **chưa có ngày mua** xét theo hạng hôm nay. Xin Tom ngày mua — ước lượng là đủ.
- Mã **ngoài rổ** có **hạng tương đương** (cùng điểm động lượng) — nói rõ chữ "tương
  đương" khi nhắc.
- **Range giá là THAM CHIẾU** để chọn giá bán, không phải luật. Không bao giờ viết
  "bán ở 52.40" như một lệnh.
- Cảnh báo "quá hạn", "trong cửa sổ bán", "nhả quá sâu" **đã bỏ** — chúng là luật của
  thứ tự cũ (quá bán 1-3 ngày). Nếu thấy chúng trong một bản tin cũ, đừng dùng.
- Nếu Tom hỏi có nên đặt stop hay chốt lời không: trả lời bằng bảng đo, đừng tự đặt.

### Ba câu phải giữ, không được bỏ khi tóm tắt

- **Luật mua từ 2026-09-28 là động lượng** (CLAUDE.md §28): lãi 6 tháng chia biến
  động, top 8 chia đều. Số lịch sử 2019-07 → 2026-09 là 31%/năm (VNINDEX 8,9%) nhưng
  **lạc quan** (rổ chọn năm 2026, chọn trong 394 biến thể), năm 2022 −31%; kỳ vọng
  trung thực là **VNINDEX + khoảng 10 điểm %/năm, dao động lớn**. Không bao giờ hứa
  20-30%/năm như chắc chắn.
- **Xem lại ở phiên 20, 40, 60… tính từ ngày mua của từng mã**: mã còn trong **top 16**
  động lượng thì giữ tiếp, rơi khỏi top 16 thì bán ATO phiên kế. Hạng là thứ quyết
  định, không phải lãi/lỗ. Mua ATO phiên sau, trong vùng mua. Không có chế độ T+.
- **Thứ tự ưu tiên A/B là thứ tự, không phải lời hứa**: A hơn B khoảng 1,6-2,0 điểm %
  mỗi 4-8 tuần trong lịch sử, không năm nào cũng đúng. Tỷ lệ lãi của một mã lẻ ~55% —
  cầm vài mã an toàn hơn dồn vào một mã.
- **Danh sách không rỗng vào ngày thường** — nó xếp mọi mã đủ 6 tháng giá. Nếu rỗng
  thì là lỗi dữ liệu (snapshot), không phải tín hiệu thị trường.
- **Tín hiệu ngành, nhãn regime và stealth là "chưa kiểm chứng"** (không có edge
  ngoài mẫu — `analysis/verification.py`). Bản tin không dựa vào chúng; nếu Tom
  hỏi thì nói đúng như thế, đừng dùng chúng để tăng/giảm tỷ trọng.

## 3. Khi Tom hỏi "nên bán lúc nào"

Trả lời bằng **ba thứ theo đúng thứ tự này**, lấy từ bản tin (`verdict`, `next_check`,
`sell_range` của vị thế) hoặc `python -m daily_watch.book show`:

1. **Kết luận** GIỮ / BÁN và **lý do** (hạng hôm nay, tới kỳ xem lại chưa). Đây là luật.
2. **Kỳ xem lại tới** và còn mấy phiên. **Thiếu ngày mua thì không có lịch** — kết luận
   xét theo hạng hôm nay; xin ngày mua, ước lượng là đủ.
3. **Range tham chiếu** `band_lo – band_hi` kèm `band_status` — để chọn giá khi bán,
   nói rõ là tham chiếu.

Nếu Tom hỏi "đang lãi X% có nên chốt không" / "lỗ Y% có nên cắt không": giá mua không
quyết định bán — dẫn bảng đo (chốt lời mất 5-8 điểm/năm; cắt lỗ không ổn định).

Ba điều không được làm khi trả lời câu này:
- **Không nói "bán ở X"** như một lệnh. Range là vùng, kỳ xem lại + hạng là luật.
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
- **Lịch.** "Kỳ xem lại tới của XYZ sau 4 phiên, ngày 22/10." Đây là phép đếm,
  chắc chắn đúng.
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

Cần **mã, giá, khối lượng**, và **ngày** nếu không phải hôm nay. Thiếu khối lượng thì
hỏi lại — không đoán.

```bash
uv run python -m daily_watch.book buy VIC 45.2 1000               # mua hôm nay
uv run python -m daily_watch.book buy VIC 45200 1000 --date 2026-09-25
```

- Giá theo **nghìn đồng** (45.2); số ≥ 1.000 được hiểu là đồng (45200 → 45.2). Dòng in
  ra luôn nói nó đã hiểu giá thế nào — đọc lại cho Tom.
- **Mua thêm một mã đang giữ thì CỘNG vào**: giá vốn bình quân theo khối lượng, ngày
  mua giữ là ngày lần đầu (đồng hồ xem lại của vị thế).
- **Đừng dùng** `POST /api/state/positions` hay `trading_state.add_position` cho việc
  này: đó là nút đánh dấu idempotent của Daily Insight, nó **ghi đè** giá và khối
  lượng cũ.
- Lệnh tự in kết luận mới của cả sổ — trả lời Tom bằng đúng phần đó.

Tom báo ngày mua cho một mã đã có trong sổ:

```bash
uv run python -m daily_watch.book date VIC 2026-09-15
```

## 5. Khi Tom nói đã bán

Vị thế **không tự đóng** — nó được theo dõi cho tới khi Tom nói đã bán.

```bash
uv run python -m daily_watch.book sell VIC 48.5          # bán hết
uv run python -m daily_watch.book sell VIC 48.5 400      # bán 400 cp, phần còn lại giữ nguyên giá vốn và ngày mua
```

Bán ≠ xoá. Bán ghi lại lệnh đã đóng kèm lãi/lỗ thật (theo giá vốn bình quân); xoá
(`DELETE /api/state/positions/{mã}`) chỉ dùng khi Tom bấm nhầm. Hỏi cho rõ nếu không
chắc Tom muốn cái nào — sai hướng này thì mất luôn lịch sử lãi/lỗ.

Xem lại cả sổ bất cứ lúc nào: `uv run python -m daily_watch.book show`.

> P&L realised trừ **0,40%/vòng** (phí + thuế bán), **không** trừ slippage — nên
> nó lạc quan hơn con số 1,00%/vòng mà bench dùng (§26.6). Khi báo P&L đã đóng,
> đừng trình bày nó như đã net đủ chi phí.

## 6. Không làm gì trong số này

- **Không tự đặt lệnh, không tự mua bán.** Skill chỉ ghi lại việc Tom đã làm.
- **Không sửa công thức, ngưỡng hay bảng số** để danh sách đẹp hơn. Luật mua là
  `picks_universe_service.long_shortlist` (động lượng, `services/buy_layer.py`) —
  một luật cho bản tin, Daily Insight và email. Luật cũ (cổng SMA200 → blend) chỉ
  còn là bóng `legacy_shortlist` để audit. Bảng vùng mua / kỳ vọng chỉ được thay
  bằng cách chạy lại `docs/reviews/strategy_study_2026-09-28/layer.py`.
- **Không gửi email.** Tom chưa muốn (2026-09-16); task chỉ ghi file.
- **Không tự dựng lại stop.** Nó bị bỏ có chủ ý, có phép đo đứng sau.
- **Không xoá hay sửa file trong `data/watch/`.** Nó là bằng chứng cho phần
  audit sau này; một bản lưu bị sửa là một bản lưu không dùng được.
- **Không viết lại luật bán hay công thức range.** Chúng ở `daily_watch/sell_range.py`;
  đổi luật thì sửa module rồi đo lại bằng
  `docs/reviews/workflow_study_2026-09-29/exits.py dev`.
- **Không trích range như số đã kiểm chứng.** ±1×ATR quanh đỉnh là chọn cho dễ đọc;
  thứ có bằng chứng là lịch xem lại và hạng.

## 7. Khi cần đo một thuật toán mới

Đó là việc khác, dùng bench: thêm một file ở `scripts/factors/`, chạy
`uv run python scripts/ticker_alpha_bench.py --horizons 20,40 --verdict`.
Xem `scripts/factors/README.md`. Đừng đo bằng cách sửa skill này.
