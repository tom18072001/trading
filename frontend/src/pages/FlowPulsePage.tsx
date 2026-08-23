import { useEffect, useState } from 'react';
import { pulseApi, sectorsApi } from '../api/client';

export default function FlowPulsePage() {
  const [data, setData] = useState<any>(null);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [exposure, setExposure] = useState<any>(null);
  const [alertZ, setAlertZ] = useState(1.5);
  const [err, setErr] = useState<string | null>(null);
  const [varOpen, setVarOpen] = useState(false);

  // Poll every 30s. That is fast enough to pick up the 16:00 EOD rollup
  // without a reload, and there is nothing faster to pick up: every source
  // below reads sector_flow_daily, one row per sector per DAY.
  useEffect(() => {
    const load = () => {
      pulseApi.live(alertZ).then((r) => setData(r.data)).catch((e) => setErr(String(e?.message || e)));
      pulseApi.alerts(alertZ).then((r: any) => setAlerts(r.data?.alerts || r.data?.rows || [])).catch(() => {});
      // 2026-08-23 (review A4): was pulseApi.exposure(), which is a hardcoded
      // `{"rows": []}` stub in api/routers/pulse.py — this panel had been
      // permanently blank while the real implementation sat one router away
      // in sectors_risk.py. sectorsApi.exposure() returns ExposureRow[].
      sectorsApi.exposure().then((r: any) => setExposure(r.data)).catch(() => {});
    };
    load();
    const t = window.setInterval(load, 30000);
    return () => window.clearInterval(t);
  }, [alertZ]);

  const rows = (data?.rows ?? []).slice().sort((a: any, b: any) => (b.flow_z20 ?? 0) - (a.flow_z20 ?? 0));
  const expRows = exposure?.rows ?? (Array.isArray(exposure) ? exposure : []);
  const varTiles = [
    { label: 'VaR 95%', v: exposure?.var_95, fmt: (x: number) => `${(x * 100).toFixed(2)}%`, tone: 'text-sell' },
    { label: 'CVaR 95%', v: exposure?.cvar_95, fmt: (x: number) => `${(x * 100).toFixed(2)}%`, tone: 'text-sell' },
    { label: 'Max DD 30d', v: exposure?.max_drawdown_pct ?? exposure?.max_drawdown, fmt: (x: number) => `${x.toFixed(1)}%`, tone: 'text-warn' },
    { label: 'Tổng exposure', v: exposure?.total_exposure, fmt: (x: number) => `${(x * 100).toFixed(0)}%`, tone: 'text-acc' },
  ].filter((t) => t.v != null);

  const signalOf = (r: any) => (r.alert ? (r.flow_z20 >= 0 ? 'ALERT↑' : 'ALERT↓') : 'NEUTRAL');

  return (
    <div className="px-8 py-8 max-w-[1240px] mx-auto space-y-[22px]">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-[29px] font-bold text-hi tracking-tight flex items-center gap-3">
            Flow Pulse
            {/* 2026-08-23 (review A6): this was a pinging "LIVE" badge next to a
                1s ticking clock, over a table with one row per sector per DAY.
                The clock advanced; the data did not. Show the session instead. */}
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-raise text-mid text-[11px] font-semibold font-mono">
              Dữ liệu EOD · {data?.as_of || '—'}
            </span>
          </h1>
          <p className="text-[13px] text-mid mt-0.5">Dòng tiền cuối phiên + cảnh báo + exposure</p>
        </div>
        <div className="flex items-center gap-3 self-center">
          <label className="text-[12px] text-mid flex items-center gap-2">alert_z
            <input type="number" step={0.1} value={alertZ} onChange={(e) => setAlertZ(parseFloat(e.target.value) || 0)}
              className="bg-panel2 border border-line rounded-md px-2 py-1 w-16 text-[12px] text-hi font-mono" />
          </label>
        </div>
      </header>

      {err && <div className="p-3 bg-sell/[0.12] border border-sell/40 text-sell rounded-xl text-sm">{err}</div>}

      {/* Alerts ticker */}
      {alerts.length > 0 && (
        <section className="rounded-2xl bg-panel border border-line p-3 space-y-1.5 max-h-44 overflow-y-auto">
          <div className="section-label mb-1">Cảnh báo gần đây</div>
          {alerts.slice(0, 8).map((a: any, i: number) => {
            const up = (a.event || '').includes('up') || (a.flow_z20 ?? 0) >= 0;
            return (
              <div key={i} className="flex items-center gap-3 text-[12px]">
                <span className="font-mono text-lo w-16 shrink-0">{(a.ts || a.time || '').slice(11, 19) || '—'}</span>
                <span className="font-semibold text-hi w-12 shrink-0">{a.sector}</span>
                <span className="text-mid flex-1 truncate">{a.message || a.msg}</span>
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${up ? 'bg-buy/[0.13] text-buy' : 'bg-sell/[0.13] text-sell'}`}>{a.event || (up ? 'up' : 'down')}</span>
              </div>
            );
          })}
        </section>
      )}

      {/* Live tape */}
      <section className="rounded-2xl bg-panel border border-line overflow-hidden">
        <div className="p-3 border-b border-line flex items-center justify-between">
          <span className="section-label">Dòng tiền theo ngành</span>
          <span className="text-[10px] text-lo font-mono">as of {data?.as_of || '—'} · auto 30s</span>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
            <tr>
              <th className="p-2.5 text-left">Ngành</th>
              <th className="p-2.5 text-center">↕</th>
              <th className="p-2.5 text-right">Flow Z20</th>
              <th className="p-2.5 text-right">ΔZ (1h)</th>
              <th className="p-2.5 text-right">Δshare %</th>
              <th className="p-2.5 text-right">Foreign streak</th>
              <th className="p-2.5 text-left">Tín hiệu</th>
              <th className="p-2.5 text-left w-28">Z</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r: any) => {
              const sig = signalOf(r);
              const zBar = Math.min(Math.abs(r.flow_z20 ?? 0) / 3, 1) * 100;
              return (
                <tr key={r.sector} className={`border-b border-line transition ${r.alert ? 'bg-warn/[0.06]' : 'hover:bg-panel2/60'}`}>
                  <td className="p-2.5">
                    <span className="font-semibold text-hi">{r.sector}</span>
                    <span className="text-lo text-xs ml-2">{r.name}</span>
                  </td>
                  <td className={`p-2.5 text-center text-base ${r.arrow === 'up' ? 'text-buy' : r.arrow === 'down' ? 'text-sell' : 'text-lo'}`}>
                    {r.arrow === 'up' ? '▲' : r.arrow === 'down' ? '▼' : '→'}
                  </td>
                  <td className={`p-2.5 text-right font-mono ${r.flow_z20 > 0 ? 'text-buy' : 'text-sell'}`}>{r.flow_z20 >= 0 ? '+' : ''}{r.flow_z20.toFixed(2)}</td>
                  <td className={`p-2.5 text-right font-mono ${r.flow_z20_delta >= 0 ? 'text-buy' : 'text-sell'}`}>{r.flow_z20_delta >= 0 ? '+' : ''}{r.flow_z20_delta.toFixed(2)}</td>
                  <td className="p-2.5 text-right font-mono text-mid">{r.delta_share_pct.toFixed(2)}</td>
                  <td className="p-2.5 text-right font-mono text-mid">{r.foreign_streak}</td>
                  <td className="p-2.5">
                    <span className={`px-2 py-0.5 rounded-md text-[11px] font-semibold ${
                      sig === 'ALERT↑' ? 'bg-buy/[0.13] text-buy' : sig === 'ALERT↓' ? 'bg-sell/[0.13] text-sell' : 'bg-raise text-mid'
                    }`}>{sig}</span>
                  </td>
                  <td className="p-2.5">
                    <div className="h-1.5 rounded-full bg-raise overflow-hidden">
                      <div className="h-full rounded-full" style={{ width: `${zBar}%`, background: (r.flow_z20 ?? 0) >= 0 ? '#33D49A' : '#FF5D73' }} />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      {/* Open exposure */}
      {expRows.length > 0 && (
        <section className="rounded-2xl bg-panel border border-line overflow-hidden">
          <div className="p-3 border-b border-line section-label">Vị thế đang mở</div>
          <table className="w-full text-sm">
            <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
              <tr>
                <th className="p-2.5 text-left">Ngành</th>
                <th className="p-2.5 text-left">Side</th>
                <th className="p-2.5 text-right">Tỉ trọng</th>
                <th className="p-2.5 text-right">Rank</th>
              </tr>
            </thead>
            <tbody>
              {expRows.map((x: any, i: number) => (
                <tr key={i} className="border-b border-line hover:bg-panel2/60">
                  <td className="p-2.5 font-semibold text-hi">{x.sector_code ?? x.sector}</td>
                  <td className="p-2.5"><span className={`px-2 py-0.5 rounded-md text-[11px] font-semibold ${x.side === 'BUY' ? 'bg-buy/[0.13] text-buy' : 'bg-sell/[0.13] text-sell'}`}>{x.side}</span></td>
                  <td className="p-2.5 text-right font-mono text-hi">{x.weight != null ? `${(x.weight * 100).toFixed(0)}%` : '—'}</td>
                  <td className="p-2.5 text-right font-mono text-mid">{x.rank ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {/* VaR / CVaR panel */}
      {varTiles.length > 0 && (
        <section className="rounded-2xl bg-panel border border-line">
          <button onClick={() => setVarOpen((s) => !s)} className="w-full flex items-center justify-between p-3.5 text-left">
            <span className="section-label">Rủi ro danh mục (VaR / CVaR)</span>
            <span className="text-mid text-sm">{varOpen ? '▾' : '▸'}</span>
          </button>
          {varOpen && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-4 pt-0">
              {varTiles.map((t) => (
                <div key={t.label} className="rounded-xl bg-panel2 border border-line p-3.5">
                  <div className="section-label">{t.label}</div>
                  <div className={`font-display text-[22px] font-bold mt-2 tabular ${t.tone}`}>{t.fmt(t.v as number)}</div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
