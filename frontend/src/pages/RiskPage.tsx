import { useEffect, useState } from 'react';
import { sectorsApi, type VaRReport, type ExposureRow, type StopLossAlert } from '../api/client';

export default function RiskPage() {
  const [vars, setVars] = useState<VaRReport[]>([]);
  const [exposure, setExposure] = useState<ExposureRow[]>([]);
  const [alerts, setAlerts] = useState<StopLossAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([sectorsApi.varAll(), sectorsApi.exposure(), sectorsApi.stoploss()])
      .then(([v, e, s]) => {
        setVars(v.data);
        setExposure(e.data);
        setAlerts(s.data);
      })
      .catch((e) => setError(e?.message || 'failed'))
      .finally(() => setLoading(false));
  }, []);

  const fmtPct = (n: number) => `${(n * 100).toFixed(2)}%`;

  return (
    <div className="p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-100">Risk</h1>
        <p className="text-sm text-slate-500">VaR/CVaR per sector, current exposure, stop-loss sentinel.</p>
      </header>

      {loading && <div className="text-slate-400 text-sm">Loading…</div>}
      {error && <div className="text-rose-400 text-sm">Error: {error}</div>}

      {!loading && !error && (
        <>
          <section>
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Stop-loss alerts
            </h2>
            {alerts.length === 0 ? (
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 text-sm text-slate-500">
                No breaches — all held sectors within stop.
              </div>
            ) : (
              <div className="rounded-xl border border-rose-900/50 bg-rose-950/20 divide-y divide-rose-900/30">
                {alerts.map((a) => (
                  <div key={`${a.sector_code}-${a.date}`} className="p-3 flex items-center justify-between">
                    <div>
                      <div className="font-semibold text-rose-300">{a.sector_code}</div>
                      <div className="text-xs text-slate-400">{a.severity} · {a.date}</div>
                    </div>
                    <div className="text-right text-xs tabular-nums text-slate-300">
                      <div>return {fmtPct(a.return_1d)}</div>
                      <div className="text-slate-500">threshold {fmtPct(a.threshold)}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Current exposure
            </h2>
            <div className="rounded-xl border border-slate-800 overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-900/60 text-slate-400 text-xs uppercase tracking-wider">
                  <tr>
                    <th className="px-3 py-2 text-left">Sector</th>
                    <th className="px-3 py-2 text-left">Side</th>
                    <th className="px-3 py-2 text-right">Weight</th>
                    <th className="px-3 py-2 text-right">Rank</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {exposure.map((e) => (
                    <tr key={e.sector_code} className="hover:bg-slate-900/40">
                      <td className="px-3 py-2 font-semibold text-slate-200">{e.sector_code}</td>
                      <td className="px-3 py-2">
                        <span className={e.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}>
                          {e.side}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-300">
                        {fmtPct(e.weight)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-500">
                        #{e.rank}
                      </td>
                    </tr>
                  ))}
                  {exposure.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-3 py-6 text-center text-slate-500">
                        No open sector positions.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
              VaR / CVaR (95%)
            </h2>
            <div className="rounded-xl border border-slate-800 overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-900/60 text-slate-400 text-xs uppercase tracking-wider">
                  <tr>
                    <th className="px-3 py-2 text-left">Sector</th>
                    <th className="px-3 py-2 text-right">N</th>
                    <th className="px-3 py-2 text-right">Mean</th>
                    <th className="px-3 py-2 text-right">Std</th>
                    <th className="px-3 py-2 text-right">VaR 95%</th>
                    <th className="px-3 py-2 text-right">CVaR 95%</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {vars.map((v) => (
                    <tr key={v.sector_code} className="hover:bg-slate-900/40">
                      <td className="px-3 py-2 font-semibold text-slate-200">{v.sector_code}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-400">{v.n_obs}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-300">
                        {fmtPct(v.mean)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-300">
                        {fmtPct(v.std)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-rose-300">
                        {fmtPct(v.var_95)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-rose-400">
                        {fmtPct(v.cvar_95)}
                      </td>
                    </tr>
                  ))}
                  {vars.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-3 py-6 text-center text-slate-500">
                        No VaR data yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
