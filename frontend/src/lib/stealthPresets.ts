/**
 * Stealth gate presets (backlog step 6).
 *
 * Six raw numeric boxes is a control panel for whoever wrote §16.1, not for
 * whoever trades it. The presets are not arbitrary "tight/loose" settings —
 * two of them are the two numbers the system actually disagrees with itself
 * about, which is CLAUDE.md §20.3 P1-1:
 *
 *   Doctrine §16.1 says   N = 5 sessions, price in the bottom 40% of 60d.
 *   analysis/stealth.py   ships N = 3 and bottom 60% (STEALTH_MIN_SESSIONS,
 *                         STEALTH_RETURN_BOTTOM_FRAC), unlogged per §15.
 *   api/routers/stealth.py defaults to the doctrine numbers.
 *
 * So the offline scanner that writes accumulation_age and the endpoint this
 * page reads are gated differently. Naming the presets after that — instead of
 * hiding it behind "tight/loose" — is the point: switching between Chặt and
 * Vừa shows you exactly what the disagreement is worth in sectors.
 */
export type StealthParams = {
  flow_z_hot: number;
  foreign_hit_min: number;
  breadth_min: number;
  atr_rank_max: number;
  close_pct_60d_max: number;
  min_sessions: number;
};

export type StealthPreset = {
  key: string;
  label: string;
  hint: string;
  params: StealthParams;
};

export const STEALTH_PRESETS: StealthPreset[] = [
  {
    key: 'strict',
    label: 'Chặt',
    hint: 'Đúng doctrine §16.1 — 5 phiên, giá ở đáy 40% của 60 ngày',
    params: {
      flow_z_hot: 1.0, foreign_hit_min: 0.6, breadth_min: 0.5,
      atr_rank_max: 0.5, close_pct_60d_max: 0.4, min_sessions: 5,
    },
  },
  {
    key: 'code',
    label: 'Vừa',
    hint: 'Đúng số đang chạy trong analysis/stealth.py — 3 phiên, đáy 60%',
    params: {
      flow_z_hot: 1.0, foreign_hit_min: 0.6, breadth_min: 0.5,
      atr_rank_max: 0.5, close_pct_60d_max: 0.6, min_sessions: 3,
    },
  },
  {
    key: 'wide',
    label: 'Rộng',
    hint: 'Dò — hạ mọi ngưỡng để xem ngành nào gần đạt, không phải để mua',
    params: {
      flow_z_hot: 0.5, foreign_hit_min: 0.4, breadth_min: 0.4,
      atr_rank_max: 0.8, close_pct_60d_max: 0.8, min_sessions: 1,
    },
  },
];

export const DEFAULT_PRESET = STEALTH_PRESETS[0];

/** Which preset do these params match, or 'custom'. */
export function matchPreset(p: StealthParams): string {
  const hit = STEALTH_PRESETS.find((preset) =>
    (Object.keys(preset.params) as (keyof StealthParams)[])
      .every((k) => Math.abs(preset.params[k] - p[k]) < 1e-9));
  return hit ? hit.key : 'custom';
}
