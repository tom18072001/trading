import { useEffect, useState } from 'react';
import {
  sectorsApi,
  type StealthResponse,
  type StealthEntry,
  type HeatmapCell,
} from '../api/client';

function fmt(n: number | null | undefined, d = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, { maximumFractionDigits: d });
}

function zColor(z: number | null | undefined) {
  if (z == null) return 'bg-slate-900 text-slate-600';
  if (z >= 1.5) return 'bg-emerald-500/80 text-slate-950';
  if (z >= 1.0) return 'bg-emerald-600/60 text-emerald-100';
  if (z >= 0.5) return 'bg-emerald-800/40 text-emerald-200';
  if (z <= -1.0) return 'bg-rose-600/60 text-rose-100';
  if (z <= -0.5) return 'bg-rose-800/40 text-rose-200';
  return 'bg-slate-800 text-slate-400';
}

function StealthTable({ title, rows, tone }: { title: string; rows: StealthEntry[]; tone: 'root' | 'branch' | 'past' }) {
  const toneCls =
    tone === 'root'
      ? 'border-emerald-500/40 bg-emerald-500/5'
      : tone === 'branch'
      ? 'border-amber-500/40 bg-amber-500/5'
      : 'border-slate-700 bg-slate-900/40';
  return (
    <section className={`rounded-xl border ${toneCls} overflow-hidden`}>
      <header className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-200">{title}</h2>
        <span className="text-xs text-slate-500">{rows.length} sectors</span>
      </header>
      <table className="w-full text-sm">
        <thead className="bg-slate-900/60 text-xs uppercase tracking-wider text-slate-500">
          <tr>
            <th className="px-3 py-2 text-left">Sector</th>
            <th className="px-3 py-2 text-left">Since</th>
            <th className="px-3 py-2 text-right">Age (d)</th>
            <th className="px-3 py-2 text-right">Stealth Score</th>
            <th className="px-3 py-2 text-right">Flow z20</th>
            <th className="px-3 py-2 text-right">Foreign hit 20d</th>
            <th className="px-3 py-2 text-right">Breadth</th>
            <th className="px-3 py-2 text-right">ATR%</th>
            <th className="px-3 py-2 text-right">Est. breakout</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((r) => (
            <tr key={r.sector_code + (r.start_date ?? '')} className="hover:bg-slate-900/40">
              <td className="px-3 py-2 font-semibold text-slate-100">{r.sector_code}</td>
              <td className="px-3 py-2 text-slate-400">{r.start_date ?? '—'}</td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-300">{fmt(r.accumulation_age, 0)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-emerald-300">{fmt(r.stealth_score, 3)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-300">{fmt(r.flow_z20, 2)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-300">
                {r.foreign_hit_20d != null ? `${(r.foreign_hit_20d * 100).toFixed(0)}%` : '—'}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-300">
                {r.breadth_sma20 != null ? `${(r.breadth_sma20 * 100).toFixed(0)}%` : '—'}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-300">
                {r.atr_pct != null ? `${(r.atr_pct * 100).toFixed(2)}%` : '—'}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-amber-300">
                {r.days_until_breakout != null ? `${r.days_until_breakout}d` : '—'}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={9} className="px-3 py-6 text-center text-slate-500">
                No sectors in this phase.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

function Heatmap({ cells }: { cells: HeatmapCell[] }) {
  const sectors = Array.from(new Set(cells.map((c) => c.sector_code))).sort();
  const latestBySector = new Map<string, HeatmapCell>();
  for (const c of cells) {
    const cur = latestBySector.get(c.sector_code);
    if (!cur || c.date > cur.date) latestBySector.set(c.sector_code, c);
  }
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-200 mb-3">
        Flow z20 heatmap (latest)
      </h2>
      <div className="grid grid-cols-5 gap-2">
        {sectors.map((s) => {
          const c = latestBySector.get(s);
          return (
            <div
              key={s}
              className={`rounded-lg px-3 py-3 text-center ${zColor(c?.flow_z20)}`}
              title={`z20=${fmt(c?.flow_z20, 2)} · score=${fmt(c?.stealth_score, 3)}`}
            >
              <div className="text-xs font-bold">{s}</div>
              <div className="text-sm tabular-nums mt-1">{fmt(c?.flow_z20, 2)}</div>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-slate-500 mt-3">
        Green halo ≥ +1.0 = potential stealth accumulation. Needs ≥5 sessions persistence per §16.1.
      </p>
    </section>
  );
}

export default function AccumulationPage() {
  const [data, setData] = useState<StealthResponse | null>(null);
  const [cells, setCells] = useState<HeatmapCell[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([sectorsApi.stealth(), sectorsApi.heatmap()])
      .then(([s, h]) => {
        setData(s.data);
        setCells(h.data.cells ?? []);
      })
      .catch((e) => setError(e?.message || 'failed'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 15000); // auto-refresh every 15s
    return () => clearInterval(id);
  }, []);

  return (
    <div className="p-6 space-y-5">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Stealth Accumulation</h1>
          <p className="text-sm text-slate-500">
            "Mua ở gốc" — sectors showing quiet smart-money accumulation before the breakout (§16).
          </p>
        </div>
        <button
          onClick={load}
          className="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-900 text-sm text-slate-200 hover:bg-slate-800"
        >
          Refresh
        </button>
      </header>

      {loading && <div className="text-slate-400 text-sm">Loading…</div>}
      {error && <div className="text-rose-400 text-sm">Error: {error}</div>}

      {!loading && !error && data && (
        <>
          <Heatmap cells={cells} />
          <StealthTable title="🌱 Gốc — Active accumulation" rows={data.active} tone="root" />
          <StealthTable title="🌿 Warming — conditions partially met" rows={data.warming} tone="branch" />
          <StealthTable title="📜 History — resolved stealth events" rows={data.history} tone="past" />
        </>
      )}
    </div>
  );
}
