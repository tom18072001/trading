import { useState } from 'react';
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { sectorsApi, type BacktestResult } from '../api/client';

export default function BacktestPage() {
  const [name, setName] = useState('rotation_default');
  const [start, setStart] = useState('2025-01-01');
  const [end, setEnd] = useState('2025-12-31');
  const [capital, setCapital] = useState(100_000_000);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const r = await sectorsApi.runBacktest({
        name, start_date: start, end_date: end, initial_capital: capital,
      });
      setResult(r.data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'failed');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-100">Sector Backtest</h1>
        <p className="text-sm text-slate-500">
          Long/short rotation strategy — ranks sectors daily by net dollar flow.
        </p>
      </header>

      <div className="rounded-xl border border-slate-800 p-5 bg-slate-900/40 grid grid-cols-2 md:grid-cols-4 gap-4">
        <label className="text-xs text-slate-400 space-y-1">
          <div>Name</div>
          <input
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200"
            value={name} onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="text-xs text-slate-400 space-y-1">
          <div>Start date</div>
          <input
            type="date"
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200"
            value={start} onChange={(e) => setStart(e.target.value)}
          />
        </label>
        <label className="text-xs text-slate-400 space-y-1">
          <div>End date</div>
          <input
            type="date"
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200"
            value={end} onChange={(e) => setEnd(e.target.value)}
          />
        </label>
        <label className="text-xs text-slate-400 space-y-1">
          <div>Initial capital (VND)</div>
          <input
            type="number"
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200"
            value={capital} onChange={(e) => setCapital(Number(e.target.value))}
          />
        </label>
        <div className="md:col-span-4 flex justify-end">
          <button
            onClick={run}
            disabled={running}
            className="px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-sm font-medium text-white"
          >
            {running ? 'Running…' : 'Run backtest'}
          </button>
        </div>
      </div>

      {error && <div className="text-rose-400 text-sm">Error: {error}</div>}

      {result && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Metric label="Total return" value={`${result.total_return_pct.toFixed(2)}%`} positive={result.total_return_pct >= 0} />
            <Metric label="Benchmark" value={`${result.benchmark_return_pct.toFixed(2)}%`} />
            <Metric label="Sharpe" value={result.sharpe_ratio.toFixed(2)} positive={result.sharpe_ratio >= 1} />
            <Metric label="Max DD" value={`${result.max_drawdown_pct.toFixed(2)}%`} positive={result.max_drawdown_pct > -15} />
            <Metric label="Trades" value={String(result.total_trades)} />
            <Metric label="Win rate" value={`${(result.win_rate * 100).toFixed(0)}%`} positive={result.win_rate >= 0.5} />
            <Metric label="Final" value={result.final_capital.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
            <Metric label="Initial" value={result.initial_capital.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
          </div>

          <div className="rounded-xl border border-slate-800 p-4 bg-slate-900/40 h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={result.equity_curve}>
                <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                <XAxis dataKey="date" stroke="#64748b" fontSize={11} />
                <YAxis stroke="#64748b" fontSize={11} domain={['auto', 'auto']} />
                <Tooltip
                  contentStyle={{ background: '#0f172a', border: '1px solid #334155' }}
                  labelStyle={{ color: '#94a3b8' }}
                />
                <Line type="monotone" dataKey="equity" stroke="#10b981" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  const color =
    positive === undefined
      ? 'text-slate-200'
      : positive
      ? 'text-emerald-400'
      : 'text-rose-400';
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`text-xl font-bold tabular-nums mt-1 ${color}`}>{value}</div>
    </div>
  );
}
