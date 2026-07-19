import { useEffect, useState } from 'react';
import { sectorsApi, type SectorFlowDaily, type SectorFlowTick } from '../api/client';

function Sparkline({ data }: { data: SectorFlowTick[] }) {
  if (!data.length) return <div className="text-slate-500 text-xs">No history.</div>;
  const pts = data.slice().reverse(); // oldest → newest
  const values = pts.map((p) => p.net_dollar_flow ?? 0);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const range = max - min || 1;
  const w = 760;
  const h = 140;
  const stepX = w / Math.max(pts.length - 1, 1);
  const y = (v: number) => h - ((v - min) / range) * (h - 10) - 5;
  const path = pts
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${(i * stepX).toFixed(1)} ${y(p.net_dollar_flow ?? 0).toFixed(1)}`)
    .join(' ');
  const zeroY = y(0);
  return (
    <svg width={w} height={h} className="w-full">
      <line x1={0} x2={w} y1={zeroY} y2={zeroY} stroke="#334155" strokeDasharray="3 3" />
      <path d={path} fill="none" stroke="#34d399" strokeWidth={1.5} />
      <text x={4} y={12} fill="#64748b" fontSize={10}>{pts[0]?.time?.slice(0,10)}</text>
      <text x={w - 60} y={12} fill="#64748b" fontSize={10}>{pts[pts.length-1]?.time?.slice(0,10)}</text>
      <text x={4} y={h - 4} fill="#64748b" fontSize={10}>min {min.toLocaleString()}</text>
      <text x={w - 110} y={h - 4} fill="#64748b" fontSize={10}>max {max.toLocaleString()}</text>
    </svg>
  );
}

function fmt(n: number | null | undefined, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function FlowCell({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <td className="px-3 py-2 text-slate-500">—</td>;
  const cls = value > 0 ? 'text-emerald-400' : value < 0 ? 'text-rose-400' : 'text-slate-300';
  return <td className={`px-3 py-2 tabular-nums ${cls}`}>{fmt(value)}</td>;
}

// sector flow dashboard with yearly filter + per-sector history sparkline
export default function FlowPage() {
  const [rows, setRows] = useState<SectorFlowDaily[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [year, setYear] = useState<string>('all');
  const [openSector, setOpenSector] = useState<string | null>(null);
  const [history, setHistory] = useState<SectorFlowTick[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    sectorsApi.listFlow(20000)
      .then((r) => setRows(r.data))
      .catch((e) => setError(e?.message || 'failed'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!openSector) return;
    setHistoryLoading(true);
    sectorsApi.sectorFlow(openSector, 400)
      .then((r) => setHistory(r.data))
      .finally(() => setHistoryLoading(false));
  }, [openSector]);

  const years = Array.from(new Set(rows.map((r) => r.date.slice(0, 4)))).sort().reverse();
  const filtered = year === 'all' ? rows : rows.filter((r) => r.date.startsWith(year));

  // Pivot: keep one row per sector (most recent date in the filter)
  const latestBySector = new Map<string, SectorFlowDaily>();
  for (const r of filtered) {
    const cur = latestBySector.get(r.sector_code);
    if (!cur || r.date > cur.date) latestBySector.set(r.sector_code, r);
  }
  const latest = Array.from(latestBySector.values()).sort(
    (a, b) => (b.net_dollar_flow ?? 0) - (a.net_dollar_flow ?? 0),
  );

  return (
    <div className="p-6 space-y-5">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Flow Dashboard</h1>
          <p className="text-sm text-slate-500">
            Latest money flow per sector — click a row to expand history chart.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">Year</span>
          <select
            value={year}
            onChange={(e) => setYear(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
          >
            <option value="all">All</option>
            {years.map((y) => (<option key={y} value={y}>{y}</option>))}
          </select>
          <span className="text-xs text-slate-500 tabular-nums">{rows.length} rows loaded</span>
        </div>
      </header>

      {loading && <div className="text-slate-400 text-sm">Loading…</div>}
      {error && <div className="text-rose-400 text-sm">Error: {error}</div>}

      {!loading && !error && (
        <div className="rounded-xl border border-slate-800 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/60 text-slate-400 text-xs uppercase tracking-wider">
              <tr>
                <th className="px-3 py-2 text-left">Sector</th>
                <th className="px-3 py-2 text-left">Date</th>
                <th className="px-3 py-2 text-right">Net $ Flow</th>
                <th className="px-3 py-2 text-right">Foreign Net</th>
                <th className="px-3 py-2 text-right">Up/Down Vol</th>
                <th className="px-3 py-2 text-right">Breadth SMA20</th>
                <th className="px-3 py-2 text-right">ATR%</th>
                <th className="px-3 py-2 text-right">Return 1d</th>
              </tr>
            </thead>
              {latest.map((r) => (
                <tbody key={r.sector_code} className="divide-y divide-slate-800">
                <tr
                  onClick={() => setOpenSector(openSector === r.sector_code ? null : r.sector_code)}
                  className={`cursor-pointer hover:bg-slate-900/40 ${openSector === r.sector_code ? 'bg-slate-900/60' : ''}`}
                >
                  <td className="px-3 py-2 font-semibold text-slate-200">
                    {openSector === r.sector_code ? '▾ ' : '▸ '}{r.sector_code}
                  </td>
                  <td className="px-3 py-2 text-slate-400">{r.date}</td>
                  <FlowCell value={r.net_dollar_flow} />
                  <FlowCell value={r.foreign_net} />
                  <td className="px-3 py-2 text-right tabular-nums text-slate-300">
                    {fmt(r.up_down_vol_ratio, 2)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-300">
                    {r.breadth_sma20 != null ? `${(r.breadth_sma20 * 100).toFixed(0)}%` : '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-300">
                    {r.atr_pct != null ? `${(r.atr_pct * 100).toFixed(2)}%` : '—'}
                  </td>
                  <FlowCell value={r.return_1d != null ? r.return_1d * 100 : null} />
                </tr>
                {openSector === r.sector_code && (
                  <tr>
                    <td colSpan={8} className="px-4 py-3 bg-slate-950/60 border-t border-slate-800">
                      <div className="text-xs text-slate-400 mb-2">Net $ flow history — last 400 sessions</div>
                      {historyLoading ? (
                        <div className="text-slate-500 text-xs">Loading…</div>
                      ) : (
                        <Sparkline data={history} />
                      )}
                    </td>
                  </tr>
                )}
                </tbody>
              ))}
              {latest.length === 0 && (
                <tbody>
                  <tr>
                    <td colSpan={8} className="px-3 py-6 text-center text-slate-500">
                      No flow data yet. Run <code className="text-emerald-400">python main.py --ingest</code>.
                    </td>
                  </tr>
                </tbody>
              )}
          </table>
        </div>
      )}
    </div>
  );
}
