import { useEffect, useState } from 'react';
import { agentApi } from '../api/client';

type Briefing = {
  date?: string;
  regime?: { label: string; confidence: number };
  top_long?: { sector_code: string; score: number; rank: number }[];
  top_short?: { sector_code: string; score: number; rank: number }[];
  narrative?: string;
  [k: string]: unknown;
};

export default function BriefingPage() {
  const [data, setData] = useState<Briefing | null>(null);
  const [raw, setRaw] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    agentApi
      .briefing()
      .then((r) => {
        setData(r.data as Briefing);
        setRaw(JSON.stringify(r.data, null, 2));
      })
      .catch((e) => setError(e?.message || 'failed'))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <div className="p-6 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">OpenClaw Briefing</h1>
          <p className="text-sm text-slate-500">Agent Trung's sector-centric daily note.</p>
        </div>
        <button
          onClick={load}
          className="px-3 py-1.5 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-sm hover:bg-emerald-500/30"
        >
          Refresh
        </button>
      </header>

      {loading && <div className="text-slate-400 text-sm">Loading…</div>}
      {error && <div className="text-rose-400 text-sm">Error: {error}</div>}

      {!loading && !error && data && (
        <>
          {data.regime && (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
              <div className="text-xs text-slate-500 uppercase tracking-wider">Regime</div>
              <div className="mt-1 text-xl font-semibold text-emerald-300">
                {data.regime.label}
              </div>
              <div className="text-xs text-slate-500">
                confidence {(data.regime.confidence * 100).toFixed(1)}%
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-xl border border-emerald-900/50 bg-emerald-950/20 p-4">
              <div className="text-xs text-emerald-400 uppercase tracking-wider mb-2">
                Top longs
              </div>
              <ul className="space-y-1 text-sm">
                {(data.top_long || []).map((r) => (
                  <li key={r.sector_code} className="flex justify-between">
                    <span className="text-slate-200">#{r.rank} {r.sector_code}</span>
                    <span className="tabular-nums text-emerald-300">{r.score.toFixed(3)}</span>
                  </li>
                ))}
                {(!data.top_long || data.top_long.length === 0) && (
                  <li className="text-slate-500">—</li>
                )}
              </ul>
            </div>

            <div className="rounded-xl border border-rose-900/50 bg-rose-950/20 p-4">
              <div className="text-xs text-rose-400 uppercase tracking-wider mb-2">
                Top shorts
              </div>
              <ul className="space-y-1 text-sm">
                {(data.top_short || []).map((r) => (
                  <li key={r.sector_code} className="flex justify-between">
                    <span className="text-slate-200">#{r.rank} {r.sector_code}</span>
                    <span className="tabular-nums text-rose-300">{r.score.toFixed(3)}</span>
                  </li>
                ))}
                {(!data.top_short || data.top_short.length === 0) && (
                  <li className="text-slate-500">—</li>
                )}
              </ul>
            </div>
          </div>

          {data.narrative && (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
              <div className="text-xs text-slate-500 uppercase tracking-wider mb-2">Narrative</div>
              <p className="text-sm text-slate-200 whitespace-pre-wrap leading-relaxed">
                {data.narrative}
              </p>
            </div>
          )}

          <details className="rounded-xl border border-slate-800 bg-slate-900/40">
            <summary className="cursor-pointer px-4 py-2 text-xs text-slate-500 uppercase tracking-wider">
              Raw JSON
            </summary>
            <pre className="px-4 pb-4 text-xs text-slate-400 overflow-x-auto">{raw}</pre>
          </details>
        </>
      )}
    </div>
  );
}
