import { useEffect, useState, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { flowApi } from '../api/client';
import type { Interval } from '../api/client';

const INTERVALS: Interval[] = ['1d', '1w', '2w', '1m', '1q'];

type Point = {
  date: string;
  net_dollar_flow: number;
  foreign_net: number;
  foreign_buy_val: number;
  foreign_sell_val: number;
  flow_z20: number | null;
  flow_z60: number | null;
  close_idx: number | null;
  breadth_sma20: number | null;
  breadth_sma50: number | null;
  atr_pct: number | null;
  up_down_vol_ratio: number | null;
  foreign_hit_20d: number | null;
  foreign_streak: number | null;
  stealth_score: number | null;
};

// ===== SVG Chart components =====

function MiniStat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-slate-800/60 rounded-lg p-3">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</div>
      <div className="text-lg font-bold text-white">{value}</div>
      {sub && <div className="text-xs text-slate-400">{sub}</div>}
    </div>
  );
}

// Generic line/bar chart using SVG
function Chart({
  points,
  getY,
  type = 'line',
  color = '#34d399',
  negColor = '#fb7185',
  label,
  height = 160,
  formatY = (v: number) => v.toFixed(2),
}: {
  points: Point[];
  getY: (p: Point) => number | null;
  type?: 'line' | 'bar';
  color?: string;
  negColor?: string;
  label: string;
  height?: number;
  formatY?: (v: number) => string;
}) {
  const W = 800;
  const H = height;
  const PAD = { top: 24, right: 10, bottom: 30, left: 60 };

  const vals = points.map(getY).map(v => v ?? 0);
  const yMin = Math.min(...vals, 0);
  const yMax = Math.max(...vals, 0.001);
  const yRange = yMax - yMin || 1;

  const xStep = (W - PAD.left - PAD.right) / Math.max(points.length - 1, 1);
  const scaleY = (v: number) => PAD.top + (1 - (v - yMin) / yRange) * (H - PAD.top - PAD.bottom);
  const zeroY = scaleY(0);

  // Y-axis ticks
  const yTicks = [yMin, yMin + yRange * 0.25, yMin + yRange * 0.5, yMin + yRange * 0.75, yMax];

  // X-axis labels (show ~8)
  const step = Math.max(1, Math.floor(points.length / 8));
  const xLabels = points.filter((_, i) => i % step === 0 || i === points.length - 1);

  const [hover, setHover] = useState<number | null>(null);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
      <div className="text-xs text-slate-400 mb-1 font-medium">{label}</div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ maxHeight: height }}
        onMouseLeave={() => setHover(null)}
      >
        {/* Grid lines */}
        {yTicks.map((t, i) => (
          <g key={i}>
            <line
              x1={PAD.left} x2={W - PAD.right}
              y1={scaleY(t)} y2={scaleY(t)}
              stroke="#334155" strokeWidth="0.5"
            />
            <text x={PAD.left - 4} y={scaleY(t) + 3} textAnchor="end" fill="#64748b" fontSize="9">
              {formatY(t)}
            </text>
          </g>
        ))}

        {/* Zero line */}
        {yMin < 0 && yMax > 0 && (
          <line
            x1={PAD.left} x2={W - PAD.right}
            y1={zeroY} y2={zeroY}
            stroke="#475569" strokeWidth="1" strokeDasharray="4,3"
          />
        )}

        {/* Data */}
        {type === 'bar' ? (
          vals.map((v, i) => {
            const x = PAD.left + i * xStep;
            const barW = Math.max(xStep * 0.7, 1);
            const top = scaleY(Math.max(v, 0));
            const bot = scaleY(Math.min(v, 0));
            return (
              <rect
                key={i}
                x={x - barW / 2}
                y={top}
                width={barW}
                height={Math.max(bot - top, 0.5)}
                fill={v >= 0 ? color : negColor}
                opacity={hover === i ? 1 : 0.75}
                onMouseEnter={() => setHover(i)}
              />
            );
          })
        ) : (
          <>
            <polyline
              points={vals.map((v, i) => `${PAD.left + i * xStep},${scaleY(v)}`).join(' ')}
              fill="none"
              stroke={color}
              strokeWidth="1.5"
            />
            {/* Dots on hover region */}
            {vals.map((v, i) => (
              <circle
                key={i}
                cx={PAD.left + i * xStep}
                cy={scaleY(v)}
                r={hover === i ? 4 : 0}
                fill={color}
                onMouseEnter={() => setHover(i)}
              />
            ))}
            {/* Invisible hover rects */}
            {vals.map((_, i) => (
              <rect
                key={`h${i}`}
                x={PAD.left + i * xStep - xStep / 2}
                y={PAD.top}
                width={xStep}
                height={H - PAD.top - PAD.bottom}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
              />
            ))}
          </>
        )}

        {/* X labels */}
        {xLabels.map((p) => {
          const i = points.indexOf(p);
          return (
            <text
              key={p.date}
              x={PAD.left + i * xStep}
              y={H - 6}
              textAnchor="middle"
              fill="#64748b"
              fontSize="8"
            >
              {p.date.slice(5)}
            </text>
          );
        })}

        {/* Hover tooltip */}
        {hover !== null && points[hover] && (
          <g>
            <line
              x1={PAD.left + hover * xStep} x2={PAD.left + hover * xStep}
              y1={PAD.top} y2={H - PAD.bottom}
              stroke="#94a3b8" strokeWidth="0.5" strokeDasharray="3,2"
            />
            <rect
              x={Math.min(PAD.left + hover * xStep + 8, W - 140)}
              y={PAD.top}
              width="130" height="36" rx="4"
              fill="#1e293b" stroke="#475569" strokeWidth="0.5"
            />
            <text
              x={Math.min(PAD.left + hover * xStep + 14, W - 134)}
              y={PAD.top + 14}
              fill="#e2e8f0" fontSize="10"
            >
              {points[hover].date}
            </text>
            <text
              x={Math.min(PAD.left + hover * xStep + 14, W - 134)}
              y={PAD.top + 28}
              fill={vals[hover] >= 0 ? color : negColor}
              fontSize="11"
              fontWeight="bold"
            >
              {formatY(vals[hover])}
            </text>
          </g>
        )}
      </svg>
    </div>
  );
}

// Distribution histogram
function DistChart({ values, label, bins = 30 }: { values: number[]; label: string; bins?: number }) {
  if (!values.length) return null;
  const W = 400, H = 120;
  const PAD = { top: 20, right: 10, bottom: 20, left: 10 };

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const binW = range / bins;

  const counts = new Array(bins).fill(0);
  values.forEach(v => {
    const idx = Math.min(Math.floor((v - min) / binW), bins - 1);
    counts[idx]++;
  });
  const maxCount = Math.max(...counts, 1);

  const barW = (W - PAD.left - PAD.right) / bins;
  const scaleH = (c: number) => (c / maxCount) * (H - PAD.top - PAD.bottom);

  // Where is zero?
  const zeroIdx = min < 0 && max > 0 ? Math.floor((0 - min) / binW) : -1;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
      <div className="text-xs text-slate-400 mb-1 font-medium">{label}</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: H }}>
        {counts.map((c, i) => {
          const x = PAD.left + i * barW;
          const h = scaleH(c);
          const binCenter = min + (i + 0.5) * binW;
          return (
            <rect
              key={i}
              x={x + 0.5}
              y={H - PAD.bottom - h}
              width={Math.max(barW - 1, 1)}
              height={h}
              fill={binCenter >= 0 ? '#34d399' : '#fb7185'}
              opacity={0.7}
            />
          );
        })}
        {zeroIdx >= 0 && (
          <line
            x1={PAD.left + zeroIdx * barW}
            x2={PAD.left + zeroIdx * barW}
            y1={PAD.top} y2={H - PAD.bottom}
            stroke="#fbbf24" strokeWidth="1" strokeDasharray="3,2"
          />
        )}
        <text x={PAD.left + 2} y={H - 4} fill="#64748b" fontSize="8">
          {min.toFixed(2)}
        </text>
        <text x={W - PAD.right - 2} y={H - 4} fill="#64748b" fontSize="8" textAnchor="end">
          {max.toFixed(2)}
        </text>
        <text x={W / 2} y={H - 4} fill="#64748b" fontSize="8" textAnchor="middle">
          n={values.length}
        </text>
      </svg>
    </div>
  );
}

export default function SectorDetailPage() {
  const { code } = useParams<{ code: string }>();
  const [interval, setInterval] = useState<Interval>('1d');
  const [lookback, setLookback] = useState(400);
  const [data, setData] = useState<{ sector: string; name: string; points: Point[]; stats: any } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    setErr(null);
    flowApi.sector(code, interval, lookback)
      .then(r => setData(r.data))
      .catch(e => setErr(String(e?.message || e)));
  }, [code, interval, lookback]);

  const pts = data?.points || [];
  const stats = data?.stats;

  // Memoized distributions
  const netFlowDist = useMemo(() => pts.map(p => p.net_dollar_flow / 1e9).filter(v => !isNaN(v)), [pts]);
  const flowZ20Dist = useMemo(() => pts.map(p => p.flow_z20).filter((v): v is number => v !== null), [pts]);
  const foreignNetDist = useMemo(() => pts.map(p => p.foreign_net / 1e9).filter(v => !isNaN(v)), [pts]);

  // Latest values for header
  const latest = pts.length ? pts[pts.length - 1] : null;

  return (
    <div className="p-6 space-y-4 text-slate-200">
      {/* Header */}
      <header className="flex items-baseline gap-3">
        <Link to="/flow" className="text-slate-500 hover:text-slate-300 text-sm">&larr; Back</Link>
        <h1 className="text-2xl font-semibold text-white">
          {data?.sector || code}
          <span className="text-slate-400 text-lg ml-2 font-normal">{data?.name || ''}</span>
        </h1>
      </header>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 border border-slate-800 rounded-lg p-3 bg-slate-900">
        <label className="text-sm text-slate-400">Interval:</label>
        {INTERVALS.map(i => (
          <button
            key={i}
            className={`px-3 py-1 rounded text-xs font-medium transition ${
              interval === i ? 'bg-emerald-500 text-slate-950' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
            }`}
            onClick={() => setInterval(i)}
          >
            {i.toUpperCase()}
          </button>
        ))}
        <label className="ml-4 text-sm text-slate-400">Lookback:</label>
        {[120, 250, 400, 800].map(lb => (
          <button
            key={lb}
            className={`px-3 py-1 rounded text-xs font-medium transition ${
              lookback === lb ? 'bg-cyan-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
            }`}
            onClick={() => setLookback(lb)}
          >
            {lb}d
          </button>
        ))}
        <span className="ml-auto text-xs text-slate-500">{pts.length} data points</span>
      </div>

      {err && <div className="p-3 bg-red-900/40 border border-red-800 text-red-200 rounded text-sm">{err}</div>}

      {/* KPI cards */}
      {latest && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
          <MiniStat
            label="Close Index"
            value={latest.close_idx?.toLocaleString(undefined, { maximumFractionDigits: 1 }) ?? '—'}
          />
          <MiniStat
            label="Flow Z20"
            value={latest.flow_z20?.toFixed(2) ?? '—'}
            sub={latest.flow_z60 !== null ? `z60: ${latest.flow_z60?.toFixed(2)}` : undefined}
          />
          <MiniStat
            label="Net Flow"
            value={`${(latest.net_dollar_flow / 1e9).toFixed(2)}B`}
          />
          <MiniStat
            label="Foreign Net"
            value={`${(latest.foreign_net / 1e9).toFixed(2)}B`}
            sub={`hit20d: ${latest.foreign_hit_20d?.toFixed(0) ?? '—'}% · streak: ${latest.foreign_streak ?? '—'}`}
          />
          <MiniStat
            label="Breadth SMA20"
            value={latest.breadth_sma20?.toFixed(2) ?? '—'}
            sub={`sma50: ${latest.breadth_sma50?.toFixed(2) ?? '—'}`}
          />
          <MiniStat
            label="Stealth Score"
            value={latest.stealth_score?.toFixed(3) ?? '—'}
            sub={`ATR%: ${latest.atr_pct ? (latest.atr_pct * 100).toFixed(2) + '%' : '—'}`}
          />
        </div>
      )}

      {/* Charts */}
      {pts.length > 0 && (
        <div className="space-y-3">
          {/* Close Index + Flow Z20 overlay */}
          <Chart
            points={pts}
            getY={p => p.close_idx}
            type="line"
            color="#60a5fa"
            label="Close Index (giá tổng hợp rổ proxy)"
            height={180}
            formatY={v => v.toFixed(0)}
          />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <Chart
              points={pts}
              getY={p => p.flow_z20}
              type="line"
              color="#34d399"
              negColor="#fb7185"
              label="Flow Z20 (z-score 20 phiên net_dollar_flow)"
              height={150}
            />
            <Chart
              points={pts}
              getY={p => p.flow_z60}
              type="line"
              color="#a78bfa"
              label="Flow Z60 (z-score 60 phiên — slow flow regime)"
              height={150}
            />
          </div>

          <Chart
            points={pts}
            getY={p => p.net_dollar_flow / 1e9}
            type="bar"
            color="#34d399"
            negColor="#fb7185"
            label="Net Dollar Flow (tỷ VND) — dương = tiền vào, âm = tiền ra"
            height={150}
            formatY={v => `${v.toFixed(1)}B`}
          />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <Chart
              points={pts}
              getY={p => p.foreign_net / 1e9}
              type="bar"
              color="#38bdf8"
              negColor="#f472b6"
              label="Foreign Net (tỷ VND) — khối ngoại mua/bán ròng"
              height={150}
              formatY={v => `${v.toFixed(1)}B`}
            />
            <Chart
              points={pts}
              getY={p => p.foreign_hit_20d}
              type="line"
              color="#fbbf24"
              label="Foreign Hit 20d (% phiên ngoại mua ròng trong 20d gần nhất)"
              height={150}
              formatY={v => `${(v * 100).toFixed(0)}%`}
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <Chart
              points={pts}
              getY={p => p.breadth_sma20}
              type="line"
              color="#a3e635"
              label="Breadth SMA20 (tỷ lệ mã trên SMA20)"
              height={130}
              formatY={v => v.toFixed(2)}
            />
            <Chart
              points={pts}
              getY={p => p.atr_pct ? p.atr_pct * 100 : null}
              type="line"
              color="#f97316"
              label="ATR% (biến động trung bình 14 phiên)"
              height={130}
              formatY={v => `${v.toFixed(2)}%`}
            />
          </div>

          <Chart
            points={pts}
            getY={p => p.stealth_score}
            type="line"
            color="#c084fc"
            label="Stealth Score (composite: flow × breadth × 1/(1+atr))"
            height={130}
            formatY={v => v.toFixed(3)}
          />
        </div>
      )}

      {/* Distribution section */}
      {pts.length > 20 && (
        <div>
          <h2 className="text-lg font-semibold text-white mb-3">Distribution</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <DistChart values={netFlowDist} label="Net Dollar Flow (tỷ VND)" />
            <DistChart values={flowZ20Dist} label="Flow Z20" />
            <DistChart values={foreignNetDist} label="Foreign Net (tỷ VND)" />
          </div>

          {/* Stats table */}
          {stats && (
            <div className="mt-3 bg-slate-900 border border-slate-800 rounded-lg p-4">
              <div className="text-xs text-slate-400 mb-2 font-medium">Thống kê tổng hợp</div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-2 text-sm">
                <div>
                  <span className="text-slate-500">Tổng phiên:</span>{' '}
                  <span className="text-white font-mono">{stats.total_days}</span>
                </div>
                <div>
                  <span className="text-slate-500">Phiên dương:</span>{' '}
                  <span className="text-emerald-400 font-mono">{stats.positive_flow_days}</span>
                  <span className="text-slate-600 text-xs ml-1">
                    ({stats.total_days ? ((stats.positive_flow_days / stats.total_days) * 100).toFixed(0) : 0}%)
                  </span>
                </div>
                <div>
                  <span className="text-slate-500">Phiên âm:</span>{' '}
                  <span className="text-rose-400 font-mono">{stats.negative_flow_days}</span>
                  <span className="text-slate-600 text-xs ml-1">
                    ({stats.total_days ? ((stats.negative_flow_days / stats.total_days) * 100).toFixed(0) : 0}%)
                  </span>
                </div>
                <div>
                  <span className="text-slate-500">Net flow trung bình:</span>{' '}
                  <span className="text-white font-mono">{stats.net_flow_mean ? (stats.net_flow_mean / 1e9).toFixed(2) : '—'}B</span>
                </div>
                <div>
                  <span className="text-slate-500">Net flow median:</span>{' '}
                  <span className="text-white font-mono">{stats.net_flow_median ? (stats.net_flow_median / 1e9).toFixed(2) : '—'}B</span>
                </div>
                <div>
                  <span className="text-slate-500">Std dev:</span>{' '}
                  <span className="text-white font-mono">{stats.net_flow_std ? (stats.net_flow_std / 1e9).toFixed(2) : '—'}B</span>
                </div>
                <div>
                  <span className="text-slate-500">Q25 / Q75:</span>{' '}
                  <span className="text-white font-mono">
                    {stats.net_flow_q25 ? (stats.net_flow_q25 / 1e9).toFixed(2) : '—'} / {stats.net_flow_q75 ? (stats.net_flow_q75 / 1e9).toFixed(2) : '—'}B
                  </span>
                </div>
                <div>
                  <span className="text-slate-500">Flow Z20 avg:</span>{' '}
                  <span className="text-white font-mono">{stats.flow_z20_mean?.toFixed(2) ?? '—'}</span>
                  <span className="text-slate-600 text-xs ml-1">
                    (std: {stats.flow_z20_std?.toFixed(2) ?? '—'})
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Raw data table (last 30 rows) */}
      {pts.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
          <div className="p-3 border-b border-slate-800 flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Raw Data (30 phiên gần nhất)</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-800/60">
                <tr>
                  {['Date', 'Close', 'Net Flow (B)', 'Flow Z20', 'Foreign Net (B)', 'Foreign Hit', 'Breadth', 'ATR%', 'Stealth'].map(h => (
                    <th key={h} className="p-2 text-left text-slate-500 font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pts.slice(-30).reverse().map(p => (
                  <tr key={p.date} className="border-t border-slate-800/50 hover:bg-slate-800/30">
                    <td className="p-2 text-slate-300 font-mono">{p.date}</td>
                    <td className="p-2 text-slate-200 font-mono">{p.close_idx?.toFixed(1) ?? '—'}</td>
                    <td className={`p-2 font-mono ${p.net_dollar_flow >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {(p.net_dollar_flow / 1e9).toFixed(2)}
                    </td>
                    <td className={`p-2 font-mono ${(p.flow_z20 ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {p.flow_z20?.toFixed(2) ?? '—'}
                    </td>
                    <td className={`p-2 font-mono ${p.foreign_net >= 0 ? 'text-cyan-400' : 'text-pink-400'}`}>
                      {(p.foreign_net / 1e9).toFixed(2)}
                    </td>
                    <td className="p-2 font-mono text-yellow-400">
                      {p.foreign_hit_20d !== null ? `${(p.foreign_hit_20d * 100).toFixed(0)}%` : '—'}
                    </td>
                    <td className="p-2 font-mono text-lime-400">{p.breadth_sma20?.toFixed(2) ?? '—'}</td>
                    <td className="p-2 font-mono text-orange-400">
                      {p.atr_pct ? `${(p.atr_pct * 100).toFixed(2)}%` : '—'}
                    </td>
                    <td className="p-2 font-mono text-purple-400">{p.stealth_score?.toFixed(3) ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
