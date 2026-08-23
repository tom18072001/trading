/**
 * One vocabulary for the whole app (review §B, 2026-08-23).
 *
 * Before this file there were three overlapping alphabets: Money Flow Monitor
 * said HOT/COOL/NEUTRAL, Xếp hạng ngành said BUY/SELL/HOLD, Daily Insight said
 * BUY/ACCUMULATE/SELL — and no page used the five states CLAUDE.md §16.3
 * actually defines.
 *
 * Two distinct things were being conflated, so they are two exports here:
 *
 *   ACTION — what to do with money. The §16.3 enum, written by
 *            services/sector_signal_service.py. ACCUMULATE > BUY > SELL > HOLD;
 *            TRIM is defined in doctrine but not yet emitted by the service.
 *   FLOW   — what the tape is doing. api/routers/flow.py:176 derives it from
 *            flow_z alone. It is an observation, not an instruction, so it must
 *            never be styled like a BUY.
 */

export const ACTION_LABEL: Record<string, string> = {
  ACCUMULATE: 'Gom sớm',
  BUY: 'Mua',
  TRIM: 'Giảm bớt',
  SELL: 'Bán',
  HOLD: 'Đứng ngoài',
};

/** §16.1 "gốc / cành cao / ngọn" — where in the move this entry sits. */
export const ACTION_HINT: Record<string, string> = {
  ACCUMULATE: 'gốc — tiền vào sớm, giá chưa chạy',
  BUY: 'cành cao — xác nhận momentum',
  TRIM: 'giá căng, dòng tiền chững — cắt nửa',
  SELL: 'dòng tiền đảo chiều — thoát',
  HOLD: 'chưa đủ điều kiện',
};

const ACTION_CLASS: Record<string, string> = {
  ACCUMULATE: 'bg-buy/[0.22] text-buy ring-1 ring-buy/40',
  BUY: 'bg-buy/[0.13] text-buy',
  TRIM: 'bg-warn/[0.13] text-warn',
  SELL: 'bg-sell/[0.13] text-sell',
  HOLD: 'bg-raise text-mid',
};

export const FLOW_LABEL: Record<string, string> = {
  HOT: 'Tiền vào',
  COOL: 'Tiền ra',
  NEUTRAL: 'Trung tính',
};

const FLOW_CLASS: Record<string, string> = {
  HOT: 'bg-buy/[0.13] text-buy',
  COOL: 'bg-sell/[0.13] text-sell',
  NEUTRAL: 'bg-raise text-mid',
};

const CHIP = 'inline-block px-2 py-0.5 rounded-md text-[11px] font-semibold whitespace-nowrap';

/** Trade instruction (§16.3). */
export function ActionBadge({ action, showHint }: { action: string; showHint?: boolean }) {
  const a = (action || 'HOLD').toUpperCase();
  return (
    <span
      className={`${CHIP} ${ACTION_CLASS[a] || ACTION_CLASS.HOLD}`}
      title={ACTION_HINT[a] ? `${a} — ${ACTION_HINT[a]}` : a}
    >
      {ACTION_LABEL[a] || a}
      {/* HOLD is 13 of 15 rows — spelling out "chưa đủ điều kiện" on each one
          is noise. The tooltip still carries it. */}
      {showHint && a !== 'HOLD' && ACTION_HINT[a] && (
        <span className="font-normal opacity-70"> · {ACTION_HINT[a]}</span>
      )}
    </span>
  );
}

/** Tape observation, deliberately styled flatter than an ActionBadge. */
export function FlowBadge({ state }: { state: string }) {
  const s = (state || 'NEUTRAL').toUpperCase();
  return (
    <span className={`${CHIP} ${FLOW_CLASS[s] || FLOW_CLASS.NEUTRAL}`} title={`flow_z20 → ${s}`}>
      {FLOW_LABEL[s] || s}
    </span>
  );
}
