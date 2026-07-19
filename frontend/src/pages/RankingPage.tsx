import { useEffect, useState } from 'react';
import { sectorsApi, type SectorSignalRow } from '../api/client';

const badge: Record<string, string> = {
  BUY: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
  SELL: 'bg-rose-500/20 text-rose-300 border-rose-500/40',
  HOLD: 'bg-slate-700/40 text-slate-300 border-slate-600/40',
};

export default function RankingPage() {
  const [rows, setRows] = useState<SectorSignalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    sectorsApi.latestRanking()
      .then((r) => setRows(r.data))
      .catch((e) => setError(e?.message || 'failed'))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const publish = async () => {
    setPublishing(true);
    try {
      const res = await sectorsApi.publishRanking();
      setRows(res.data.rows);
    } catch (e: any) {
      setError(e?.message || 'publish failed');
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="p-6 space-y-5">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Rotation Ranking</h1>
          <p className="text-sm text-slate-500">
            Daily ranker output. Top-3 BUY, bottom-2 SELL (persistence filter ≥3 sessions).
          </p>
        </div>
        <button
          onClick={publish}
          disabled={publishing}
          className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-sm font-medium text-white shadow-lg shadow-emerald-600/20"
        >
          {publishing ? 'Publishing…' : 'Publish now'}
        </button>
      </header>

      {loading && <div className="text-slate-400 text-sm">Loading…</div>}
      {error && <div className="text-rose-400 text-sm">Error: {error}</div>}

      {!loading && !error && (
        <div className="rounded-xl border border-slate-800 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/60 text-slate-400 text-xs uppercase tracking-wider">
              <tr>
                <th className="px-3 py-2 text-left w-16">Rank</th>
                <th className="px-3 py-2 text-left">Sector</th>
                <th className="px-3 py-2 text-right">Score</th>
                <th className="px-3 py-2 text-center">Persistence</th>
                <th className="px-3 py-2 text-center">Action</th>
                <th className="px-3 py-2 text-left">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rows.map((r) => (
                <tr key={r.sector_code} className="hover:bg-slate-900/40">
                  <td className="px-3 py-2 font-bold text-slate-300">#{r.rank}</td>
                  <td className="px-3 py-2 font-semibold text-slate-100">{r.sector_code}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-300">
                    {r.score.toFixed(4)}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {r.persistence_ok ? (
                      <span className="text-emerald-400">✓</span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span className={`inline-block px-2 py-0.5 rounded border text-xs font-semibold ${badge[r.action]}`}>
                      {r.action}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-500">{r.date}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-slate-500">
                    No signals yet. Click <span className="text-emerald-400">Publish now</span>.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
