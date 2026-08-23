/**
 * Stealth gate presets (backlog step 6, revised 2026-08-23).
 *
 * Seven raw numeric boxes is a control panel for whoever wrote §16.1, not for
 * whoever trades it. The presets name the real argument instead of hiding it
 * behind "tight/loose".
 *
 * What changed on 2026-08-23: the gate stopped being a conjunction. Measured
 * over the whole 13,470-row panel, all five §16.1 conditions held at once on
 * 0.3% of rows and the longest consecutive all-five run across 15 sectors in
 * 3.5 years was **2 sessions** — against a requirement of 3. So the old Chặt
 * (doctrine) and Vừa (code) presets were not a disagreement worth pricing:
 * both returned zero sectors at every threshold. `analysis/stealth.py` now
 * scores 0-5 and fires at ≥4 held ≥3 sessions, and `api/routers/stealth.py`
 * reads the same two knobs.
 *
 * So `min_conditions` is the knob that matters now, and the presets are three
 * points on it. Chặt is what the old doctrine literally asked for and is kept
 * precisely so you can see it still returns nothing.
 */
export type StealthParams = {
  flow_z_hot: number;
  foreign_hit_min: number;
  breadth_min: number;
  atr_rank_max: number;
  close_pct_60d_max: number;
  min_sessions: number;
  min_conditions: number;
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
    hint: 'Doctrine §16.1 nguyên bản — đủ cả 5 điều kiện, 5 phiên. Đo trên toàn lịch sử: 0 ngành.',
    params: {
      flow_z_hot: 1.0, foreign_hit_min: 0.6, breadth_min: 0.5,
      atr_rank_max: 0.5, close_pct_60d_max: 0.4,
      min_sessions: 5, min_conditions: 5,
    },
  },
  {
    key: 'code',
    label: 'Vừa',
    hint: 'Ngưỡng đang chạy — ≥4/5 điều kiện giữ ≥3 phiên. 23 sự kiện / 11 ngành trong 3,5 năm.',
    params: {
      flow_z_hot: 1.0, foreign_hit_min: 0.6, breadth_min: 0.5,
      atr_rank_max: 0.5, close_pct_60d_max: 0.4,
      min_sessions: 3, min_conditions: 4,
    },
  },
  {
    key: 'wide',
    label: 'Rộng',
    hint: 'Dò — hạ mọi ngưỡng để xem ngành nào gần đạt, không phải để mua',
    params: {
      flow_z_hot: 0.5, foreign_hit_min: 0.4, breadth_min: 0.4,
      atr_rank_max: 0.8, close_pct_60d_max: 0.8,
      min_sessions: 1, min_conditions: 3,
    },
  },
];

// Vừa, not Chặt: the page must open on the gate that is actually running.
export const DEFAULT_PRESET = STEALTH_PRESETS[1];

/** Which preset do these params match, or 'custom'. */
export function matchPreset(p: StealthParams): string {
  const hit = STEALTH_PRESETS.find((preset) =>
    (Object.keys(preset.params) as (keyof StealthParams)[])
      .every((k) => Math.abs(preset.params[k] - p[k]) < 1e-9));
  return hit ? hit.key : 'custom';
}
