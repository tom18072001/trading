/**
 * What the column names mean (backlog step 6).
 *
 * `flow_z20`, `stealth_score` and `breadth_sma20` are column headers on three
 * pages and are explained nowhere in the app — the only definitions live in
 * CLAUDE.md §16.2 and docs/reference/GLOSSARY_VI.md, neither of which is open
 * while you are reading the table.
 *
 * A native `title` attribute, not a popover component: it needs no state, no
 * portal and no library, and it is the one tooltip that works on a table
 * header without fighting `overflow-hidden`.
 *
 * ponytail: native title = no touch support and ~1s delay. Swap for a real
 * popover if these ever need to hold a formula or a link.
 */
import type { ReactNode } from 'react';

export const GLOSSARY: Record<string, string> = {
  flow_z20:
    'Dòng tiền 20 phiên của ngành, quy về z-score so với CHÍNH NÓ trong quá khứ. '
    + '+1 = đang được mua mạnh bất thường so với thói quen của ngành đó. '
    + 'Vì so với chính nó nên ngành nhỏ cũng lên được top — khác hẳn xếp theo VND thô.',
  flow_z60:
    'Như flow_z20 nhưng cửa sổ 60 phiên — chậm hơn, cho biết chế độ dòng tiền vĩ mô.',
  stealth_score:
    'Điểm tích luỹ âm thầm: (flow_z20) × (breadth đang tăng) × 1/(1+xếp hạng ATR). '
    + 'Cao = tiền vào đều, số mã tham gia tăng, tape vẫn im — dấu hiệu gom trước khi tin ra.',
  breadth_sma20:
    'Tỷ lệ mã trong rổ ngành đang nằm trên SMA20. Cao = nhiều mã cùng lên (lan toả), '
    + 'không phải một mã kéo. Rổ chỉ có 5 mã nên chỉ số này chỉ nhận 6 giá trị rời rạc.',
  breadth_sma50: 'Tỷ lệ mã trong rổ ngành nằm trên SMA50 — phiên bản chậm của breadth.',
  foreign_hit_20d:
    'Tỷ lệ phiên trong 20 phiên gần nhất có khối ngoại mua ròng. '
    + 'Doctrine §16.1 đòi ≥ 60%. Dữ liệu foreign_net đã backfill 2026-08-23 '
    + '(12.616/13.470 dòng, từ 2023-03), nên điều kiện này bắt đầu có tác dụng thật.',
  atr_pct:
    'Biên độ dao động trung bình của ngành, tính theo % giá. Thấp = tape im, '
    + 'chưa hưng phấn — điều kiện 4 của §16.1.',
  close_pct_60d:
    'Vị trí giá hiện tại trong biên độ 60 phiên. 0 = đáy, 1 = đỉnh. '
    + 'Doctrine §16.1 đòi ≤ 0,4 (vẫn còn rẻ).',
  min_sessions:
    'Số phiên liên tiếp phải đạt đủ điểm thì mới coi là tích luỹ thật, '
    + 'không phải nhiễu một phiên. Doctrine 5; code đang chạy 3.',
  conditions_met:
    'Số điều kiện §16.1 đang đạt (0-5). Từ 2026-08-23 cổng chấm điểm chứ không '
    + 'AND: cần ≥4/5 giữ ≥3 phiên. Bắt buộc cả 5 là bất khả thi — đo trên toàn bộ '
    + 'lịch sử, chuỗi 5/5 dài nhất chỉ 2 phiên.',
  accumulation_age: 'Số phiên liên tiếp ngành đạt ngưỡng điểm §16.1 (≥4/5).',
  net_dollar_flow:
    'Giá trị mua ròng ước tính của rổ ngành trong phiên, đơn vị VND. '
    + 'Là số thô — ngành to luôn lớn hơn ngành nhỏ, nên đừng xếp hạng bằng cột này.',
  persistence_ok: 'Dấu hiệu dòng tiền giữ cùng dấu ≥3 phiên (§10 persistence filter).',
  score: 'Điểm của ranker LightGBM — kỳ vọng lợi suất 20 phiên tới, chỉ dùng để xếp thứ tự.',
};

/** Underlined term with the glossary text as its tooltip. */
export function Hint({ term, children }: { term: string; children?: ReactNode }) {
  const text = GLOSSARY[term];
  if (!text) return <>{children ?? term}</>;
  return (
    <span title={text} className="underline decoration-dotted decoration-lo/60 underline-offset-2 cursor-help">
      {children ?? term}
    </span>
  );
}
