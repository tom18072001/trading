import { useEffect, useState } from 'react';
import { sectorsApi, type RegimeRow } from '../api/client';

const regimeColor: Record<string, string> = {
  risk_on: 'from-emerald-500 to-cyan-500',
  risk_off: 'from-rose-500 to-orange-500',
  rotation: 'from-amber-500 to-yellow-500',
  chop: 'from-slate-500 to-slate-600',
  unknown: 'from-slate-700 to-slate-800',
};

export default function RegimePage() {
  const [latest, setLatest] = useState<RegimeRow | null>(null);
  const [history, setHistory] = useState<RegimeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [classifying, setClassifying] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([sectorsApi.latestRegime(), sectorsApi.regimeHistory(60)])
      .then(([a, b]) => {
        setLatest(a.data);
        setHistory(b.data);
      })
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const classify = async () => {
    setClassifying(true);
    try {
      await sectorsApi.classifyRegime();
      load();
    } finally {
      setClassifying(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Regime Monitor</h1>
          <p className="text-sm text-slate-500">Gaussian HMM over macro anchors (heuristic fallback).</p>
        </div>
        <button
          onClick={classify}
          disabled={classifying}
          className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-sm font-medium text-white"
        >
          {classifying ? 'Classifying…' : 'Classify now'}
        </button>
      </header>

      {loading && <div className="text-slate-400 text-sm">Loading…</div>}

      {!loading && latest && (
        <div className={`rounded-2xl p-8 bg-gradient-to-br ${regimeColor[latest.regime_label] || regimeColor.unknown} shadow-2xl`}>
          <div className="text-xs uppercase tracking-widest text-white/70">Current regime</div>
          <div className="text-5xl font-bold text-white mt-2">{latest.regime_label.replace('_', ' ')}</div>
          <div className="text-sm text-white/80 mt-2">
            confidence {(latest.confidence * 100).toFixed(0)}% · {latest.date}
          </div>
        </div>
      )}

      <div>
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">History</h2>
        <div className="rounded-xl border border-slate-800 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/60 text-slate-400 text-xs uppercase tracking-wider">
              <tr>
                <th className="px-3 py-2 text-left">Date</th>
                <th className="px-3 py-2 text-left">Regime</th>
                <th className="px-3 py-2 text-right">Confidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {history.map((h) => (
                <tr key={h.date} className="hover:bg-slate-900/40">
                  <td className="px-3 py-2 text-slate-300">{h.date}</td>
                  <td className="px-3 py-2 font-semibold text-slate-100">{h.regime_label}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-400">
                    {(h.confidence * 100).toFixed(0)}%
                  </td>
                </tr>
              ))}
              {history.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-3 py-6 text-center text-slate-500">
                    No history yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
