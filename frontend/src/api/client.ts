// ============================================
// api/client.ts — Sector Money-Flow API client
// ============================================
// All endpoints map 1:1 to the sector routers in api/routers/sectors_*.
// See CLAUDE.md for the API surface. Legacy symbol/ML/trade endpoints are
// intentionally absent — they have been removed on the backend.

import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
});

const LONG_TIMEOUT = 300_000;

export type SectorSignalRow = {
  date: string;
  sector_code: string;
  score: number;
  rank: number;
  // CLAUDE.md §16.3. sector_signal_service.py emits four of the five today —
  // TRIM is defined in doctrine but never written, so the UI renders it if it
  // ever appears rather than falling back to a raw string.
  action: 'ACCUMULATE' | 'BUY' | 'TRIM' | 'SELL' | 'HOLD';
  persistence_ok: boolean;
};

export type RegimeRow = {
  date: string;
  regime_label: 'risk_on' | 'risk_off' | 'rotation' | 'chop' | 'unknown';
  confidence: number;
};

export type VaRReport = {
  sector_code: string;
  n_obs: number;
  mean: number;
  std: number;
  var_95: number;
  cvar_95: number;
};

export type ExposureRow = {
  sector_code: string;
  side: 'BUY' | 'SELL';
  weight: number;
  rank: number;
};

export type StopLossAlert = {
  sector_code: string;
  date: string;
  return_1d: number;
  threshold: number;
  severity: string;
};

export type BacktestRequest = {
  name: string;
  start_date: string;
  end_date: string;
  initial_capital?: number;
};

export type BacktestResult = {
  name: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  final_capital: number;
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  total_trades: number;
  win_rate: number;
  benchmark_return_pct: number;
  equity_curve: { date: string; equity: number }[];
  trade_log: { date: string; sector: string; side: string; ret: number }[];
};

// One handoff row = flow leaving `from_sector` while entering `to_sector` on
// one session. See analysis/flow_handoff.compute_handoff().
export type HandoffRow = {
  date: string;
  from_sector: string;
  to_sector: string;
  handoff_score: number;
};
export type HandoffResponse = { count: number; window: number; handoffs: HandoffRow[] };

// 2026-08-23: six methods removed here — listFlow, sectorFlow, heatmap, varOne,
// listBacktests and stealth. All had zero call sites across frontend/src.
export const sectorsApi = {
  // ----- ranking -----
  latestRanking: () => api.get<SectorSignalRow[]>('/sectors/ranking'),
  publishRanking: () =>
    api.post<{ published: number; rows: SectorSignalRow[] }>('/sectors/ranking/publish'),

  // ----- regime -----
  latestRegime: () => api.get<RegimeRow>('/sectors/regime'),
  regimeHistory: (limit = 60) =>
    api.get<RegimeRow[]>('/sectors/regime/history', { params: { limit } }),
  classifyRegime: () => api.post<RegimeRow>('/sectors/regime/classify'),

  // ----- backtest -----
  runBacktest: (req: BacktestRequest) =>
    api.post<BacktestResult>('/sectors/backtest', req, { timeout: LONG_TIMEOUT }),

  // ----- risk -----
  varAll: () => api.get<VaRReport[]>('/sectors/risk/var'),
  exposure: () => api.get<ExposureRow[]>('/sectors/risk/exposure'),
  stoploss: () => api.get<StopLossAlert[]>('/sectors/risk/stoploss'),

  // ----- rotation (§4 handoff matrix) -----
  // Backs the Rotation Map page since 2026-08-23. /api/rotation/* is left
  // mounted but unread: its pair detection returns a cartesian product of two
  // sets that is empty at every threshold on the live panel. See the module
  // docstring in api/routers/rotation.py.
  handoff: (lookback_days = 60, window = 5, top_k = 5) =>
    api.get<HandoffResponse>('/sectors/handoff', { params: { lookback_days, window, top_k } }),
};

// agentApi (briefing / stoploss-alerts) removed 2026-08-23.
// Both endpoints returned 404: the /api/agent/* router was deleted from the
// backend on 2026-04-18 when OpenClaw was replaced by services.trader_agent,
// which is invoked from POST /api/insight/refresh and rendered inline on the
// Daily Insight page. The client kept calling the dead routes for four months.

// ===== Phase 15 — Feature A Money Flow Monitor =====
export type Interval = '1d' | '1w' | '2w' | '1m' | '1q';

export type FlowSeriesPoint = {
  date: string;
  net_dollar_flow: number;
  flow_z20: number | null;
  close_idx: number | null;
};
export type FlowSeriesEntry = { sector: string; points: FlowSeriesPoint[] };
export type FlowSeriesResponse = {
  interval: Interval;
  as_of: string | null;
  sectors: string[];
  series: FlowSeriesEntry[];
};

export type FlowRankingRow = {
  rank: number;
  sector: string;
  name: string;
  score: number;
  flow_z20: number;
  net_dollar_flow: number;
  breadth_sma20: number;
  atr_pct: number;
  // NOT a §16.3 trade action — api/routers/flow.py:176 derives this from
  // flow_z alone. It describes the tape, not what to do. Rendered with
  // FlowBadge, deliberately flatter than ActionBadge (lib/actions.tsx).
  action: 'HOT' | 'COOL' | 'NEUTRAL';
  why: string;
};
export type FlowRankingResponse = {
  interval: Interval;
  as_of: string | null;
  flow_z_hot: number;
  rows: FlowRankingRow[];
};

export type FlowHeatCell = { sector: string; bucket: string; flow_z20: number | null };
export type FlowHeatResponse = {
  interval: Interval;
  as_of: string | null;
  buckets: string[];
  cells: FlowHeatCell[];
};

// 2026-08-23: `lookback` defaulted to 400 sessions here, which is what made
// /api/flow/series the slowest route in the system -- 2.8 s and 1.0 MB for a
// chart that shows months. The backend default was lowered to 120 the same
// day, but the client always sent an explicit 400, so the change did nothing
// until this line changed too. Pass a bigger number when you actually want it.
export const flowApi = {
  series: (interval: Interval = '1d', lookback = 120) =>
    api.get<FlowSeriesResponse>('/flow/series', { params: { interval, lookback } }),
  ranking: (interval: Interval = '1d', flow_z_hot = 1.0) =>
    api.get<FlowRankingResponse>('/flow/ranking', { params: { interval, flow_z_hot } }),
  heat: (interval: Interval = '1d', lookback = 60) =>
    api.get<FlowHeatResponse>('/flow/heat', { params: { interval, lookback } }),
  sector: (code: string, interval: Interval = '1d', lookback = 120) =>
    api.get('/flow/sector/' + code, { params: { interval, lookback } }),
  refresh: () => api.post('/flow/refresh'),
  refreshStatus: () => api.get('/flow/refresh/status'),
  freshness: () => api.get('/flow/freshness'),
  index: (lookback = 60) => api.get('/flow/index', { params: { lookback } }),
};

// ===== Phase 15 — Features B/C/D/E =====
// rotationApi (sankey / pairs) removed 2026-08-23. Its only consumer,
// RotationMapPage, now reads sectorsApi.handoff — /api/rotation/* returns an
// empty pair list at every threshold. See api/routers/rotation.py.

export const stealthApi15 = {
  active: (params: Record<string, number> = {}) =>
    api.get('/stealth/active', { params }),
  history: (limit = 50) => api.get('/stealth/history', { params: { limit } }),
};

export const pulseApi = {
  live: (alert_z = 1.5) => api.get('/pulse/live', { params: { alert_z } }),
  alerts: (alert_z = 1.5) => api.get('/pulse/alerts', { params: { alert_z } }),
  // exposure() removed 2026-08-23: /api/pulse/exposure is a hardcoded empty
  // stub. Use sectorsApi.exposure() — /api/sectors/risk/exposure.
};

// Daily Insight refresh is async: POST kicks off a background job and
// returns `run_id` immediately; the UI polls `/insight/refresh/status`
// every ~2s until `is_done` (or `is_error`), then reads the final /daily
// payload from `status.payload`. This avoids the 5-minute axios timeout
// that the previous sync endpoint kept hitting.
export type InsightRefreshStart = {
  run_id: string;
  stage: string;
  stage_label: string;
  started_at: number;
  already_running: boolean;
};

export type InsightRefreshStatus = {
  run_id: string | null;
  stage: string;                           // queued | publishing_signals | rebuilding_universe | trader_agent | assembling | done | error | idle
  stage_label: string;
  progress?: { done: number; total: number; pct: number | null };
  started_at?: number;
  elapsed_sec?: number;
  published_signals?: number | null;
  publish_error?: string | null;
  agent_error?: string | null;
  error?: string | null;
  is_running: boolean;
  is_done: boolean;
  is_error: boolean;
  payload?: any | null;                    // populated once is_done
  history?: Array<{ stage: string; duration_sec: number }>;
};

export const insightApi = {
  daily: () => api.get('/insight/daily'),
  delta: () => api.get('/insight/delta'),
  refresh: () => api.post<InsightRefreshStart>('/insight/refresh'),
  refreshStatus: (runId?: string) =>
    api.get<InsightRefreshStatus>('/insight/refresh/status', {
      params: runId ? { run_id: runId } : undefined,
    }),
};

export default api;
