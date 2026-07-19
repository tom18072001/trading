import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { flowApi } from '../api/client';
import type { FlowRankingResponse, FlowHeatResponse, FlowSeriesResponse, Interval } from '../api/client';

const INTERVALS: Interval[] = ['1d', '1w', '2w', '1m', '1q'];

// Multi-line sector palette (redesign handoff) + fallbacks for the rest.
const SECTOR_COLORS: Record<string, string> = {
  CHEM: '#33D49A', REAL: '#46C9E6', OIL: '#7FB2FF', POWER: '#B98BFF', INSUR: '#F5B13D',
  TECH: '#7A8696', FOOD: '#5CCFB8', STEEL: '#E08A6B', BANK: '#FF8FA0', TEXT: '#FF5D73',
  BROK: '#9C8BFF', RETAIL: '#E6C84A', LOGIS: '#6BD0E0', RUBBER: '#C98B6B', FISH: '#5C9CCF',
};
const colorFor = (s: string) => SECTOR_COLORS[s] ?? '#7A8696';

function IndexPanel() {
  const [data, setData] = useState<any>(null);
  useEffect(() => { flowApi.index(60).then((r) => setData(r.data)).catch(() => {}); }, []);
  if (!data?.points?.length) return null;
  const pts = data.points;
  const latest = pts[pts.length - 1];
  const prev = pts.length >= 2 ? pts[pts.length - 2] : latest;
  const chg = latest.vnindex - prev.vnindex;
  const chgPct = prev.vnindex ? (chg / prev.vnindex) * 100 : 0;
  const vals = pts.map((p: any) => p.vnindex);
  const min = Math.min(...vals), max = Math.max(...vals), range = max - min || 1;
  const w = 320, h = 44;
  const path = vals.map((v: number, i: number) =>
    `${i === 0 ? 'M' : 'L'} ${(i / (vals.length - 1) * w).toFixed(1)} ${(h - ((v - min) / range) * (h - 4) - 2).toFixed(1)}`
  ).join(' ');
  const up = chg >= 0;
  return (
    <div className="rounded-2xl bg-panel border border-line p-4 flex items-center gap-5">
      <div>
        <div className="section-label">VNINDEX</div>
        <div className="font-display text-[24px] font-bold text-hi tabular">{latest.vnindex.toLocaleString()}</div>
        <div className={`text-[13px] font-mono ${up ? 'text-buy' : 'text-sell'}`}>
          {up ? '+' : ''}{chg.toFixed(2)} ({up ? '+' : ''}{chgPct.toFixed(2)}%)
        </div>
      </div>
      <svg width={w} height={h} className="shrink-0">
        <path d={path} fill="none" stroke={up ? '#33D49A' : '#FF5D73'} strokeWidth="1.6" />
      </svg>
      <div className="text-[11px] text-lo ml-auto font-mono text-right">
        {pts[0].date} → {latest.date}<br />src: {data.source}
      </div>
    </div>
  );
}

// ---- multi-line z-chart ----
function ZChart({ series, selected, onSelect }: {
  series: FlowSeriesResponse | null; selected: string | null; onSelect: (s: string | null) => void;
}) {
  const W = 1000, H = 320, yZero = 160, yScale = 46.667;
  const lines = useMemo(() => {
    if (!series?.series?.length) return [];
    return series.series.map((entry) => {
      const pts = entry.points.filter((p) => p.flow_z20 != null);
      const n = pts.length;
      const d = pts.map((p, i) => {
        const x = n > 1 ? (i / (n - 1)) * W : 0;
        const y = yZero - (p.flow_z20 as number) * yScale;
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${clampY(y).toFixed(1)}`;
      }).join(' ');
      return { sector: entry.sector, d };
    });
  }, [series]);

  function clampY(y: number) { return Math.max(6, Math.min(H - 6, y)); }
  const yOf = (z: number) => yZero - z * yScale;

  if (!series?.series?.length) {
    return <div className="rounded-2xl bg-panel border border-line p-6 text-center text-lo text-sm">Chưa có dữ liệu chuỗi flow_z.</div>;
  }

  return (
    <section className="rounded-2xl bg-panel border border-line p-[22px]">
      <div className="flex items-center justify-between mb-3">
        <div className="section-label">Flow Z20 theo thời gian</div>
        <div className="flex flex-wrap gap-1.5">
          {series.series.map((e) => {
            const on = selected === e.sector;
            const dim = selected != null && !on;
            return (
              <button
                key={e.sector}
                onClick={() => onSelect(on ? null : e.sector)}
                className={`px-1.5 py-0.5 rounded text-[10px] font-mono border transition ${dim ? 'opacity-40' : ''}`}
                style={{ borderColor: colorFor(e.sector), color: colorFor(e.sector) }}
              >
                {e.sector}
              </button>
            );
          })}
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-[280px]">
        {/* threshold lines */}
        <line x1="0" y1={yZero} x2={W} y2={yZero} stroke="rgba(255,255,255,.18)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {[1, -1].map((z) => (
          <line key={z} x1="0" y1={yOf(z)} x2={W} y2={yOf(z)} stroke="#F5B13D" strokeWidth="1" strokeDasharray="5 5" opacity="0.45" vectorEffect="non-scaling-stroke" />
        ))}
        {[2, -2].map((z) => (
          <line key={z} x1="0" y1={yOf(z)} x2={W} y2={yOf(z)} stroke="#FF5D73" strokeWidth="1" strokeDasharray="5 5" opacity="0.4" vectorEffect="non-scaling-stroke" />
        ))}
        {lines.map((l) => {
          const on = selected === l.sector;
          const dim = selected != null && !on;
          return (
            <path key={l.sector} d={l.d} fill="none" stroke={colorFor(l.sector)}
              strokeWidth={on ? 3 : 1.5} opacity={dim ? 0.18 : 0.92}
              vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
          );
        })}
      </svg>
      <div className="flex justify-between text-[10px] text-lo font-mono mt-1">
        <span>±1σ (amber) · ±2σ (red)</span>
        <span>interval {series.interval.toUpperCase()}</span>
      </div>
    </section>
  );
}

// ---- heat strip grid ----
function HeatStrip({ heat }: { heat: FlowHeatResponse | null }) {
  if (!heat?.cells?.length) return null;
  const sectors = [...new Set(heat.cells.map((c) => c.sector))];
  const buckets = heat.buckets;
  const byKey = new Map(heat.cells.map((c) => [`${c.sector}|${c.bucket}`, c.flow_z20]));
  const cellColor = (z: number | null | undefined) => {
    if (z == null) return 'transparent';
    const a = 0.08 + Math.min(1, Math.abs(z) / 3) * 0.62;
    return z >= 0 ? `rgba(51,212,154,${a})` : `rgba(255,93,115,${a})`;
  };
  return (
    <section className="rounded-2xl bg-panel border border-line p-[22px]">
      <div className="section-label mb-3">Heat strip — flow_z20 ({sectors.length}×{buckets.length})</div>
      <div className="space-y-1">
        {sectors.map((s) => (
          <div key={s} className="flex items-center gap-2">
            <span className="w-12 text-[10px] font-mono text-mid shrink-0">{s}</span>
            <div className="flex gap-[2px] flex-1">
              {buckets.map((b) => {
                const z = byKey.get(`${s}|${b}`);
                return (
                  <div key={b} className="h-4 flex-1 rounded-[2px]"
                    title={`${s} · ${b} · z ${z != null ? z.toFixed(2) : '—'}`}
                    style={{ background: cellColor(z), minWidth: 6 }} />
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

const ACTION_CHIP: Record<string, string> = {
  HOT: 'bg-buy/[0.13] text-buy', COOL: 'bg-sell/[0.13] text-sell', NEUTRAL: 'bg-raise text-mid',
};

export default function FlowMonitorPage() {
  const [interval, setInterval] = useState<Interval>('1d');
  const [flowZHot, setFlowZHot] = useState(1.0);
  const [ranking, setRanking] = useState<FlowRankingResponse | null>(null);
  const [heat, setHeat] = useState<FlowHeatResponse | null>(null);
  const [series, setSeries] = useState<FlowSeriesResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const [freshness, setFreshness] = useState<any>(null);

  const load = () => {
    setErr(null);
    Promise.all([
      flowApi.ranking(interval, flowZHot),
      flowApi.heat(interval, 60),
      flowApi.series(interval, 400),
      flowApi.freshness(),
    ])
      .then(([r, h, s, f]) => { setRanking(r.data); setHeat(h.data); setSeries(s.data); setFreshness(f.data); })
      .catch((e) => setErr(String(e?.message || e)));
  };
  useEffect(load, [interval, flowZHot]);

  const pollStatus = () => {
    const pollId = window.setInterval(() => {
      flowApi.refreshStatus().then(({ data }: { data: any }) => {
        if (data.running) {
          const p = data.progress;
          setRefreshMsg(`⟳ ${p?.sector || '...'} (${p?.step || 0}/${p?.total || 15})`);
        } else {
          window.clearInterval(pollId);
          setRefreshing(false);
          const r = data.result;
          if (r?.status === 'updated') { setRefreshMsg(`✓ +${r.total_new_rows} rows (${r.latest_date_before}→${r.latest_date_after})`); setTimeout(load, 100); }
          else if (r?.status === 'error') setRefreshMsg(`✗ ${r.error}`);
          else if (r?.status === 'already_fresh') setRefreshMsg(`✓ Đã cập nhật đến ${r.latest_date}`);
          else { setRefreshMsg('✓ Done'); setTimeout(load, 100); }
        }
      }).catch(() => { window.clearInterval(pollId); setRefreshing(false); setRefreshMsg('✗ Mất kết nối'); });
    }, 2000);
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    setRefreshMsg('⟳ Đang kiểm tra...');
    try {
      const { data } = await flowApi.refresh();
      if (data.status === 'already_fresh') { setRefreshMsg(`✓ Mới nhất: ${data.latest_date}${data.is_weekend ? ' (cuối tuần)' : ''}`); setRefreshing(false); }
      else { setRefreshMsg('⟳ Bắt đầu fetch...'); pollStatus(); }
    } catch (e: any) { setRefreshMsg(`✗ ${e?.message || e}`); setRefreshing(false); }
  };

  return (
    <div className="px-8 py-8 max-w-[1240px] mx-auto space-y-[22px]">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-[29px] font-bold text-hi tracking-tight">Money Flow Monitor</h1>
          <p className="text-[13px] text-mid mt-0.5">Dòng tiền vào/ra ngành nào, mạnh đến đâu</p>
        </div>
        <div className="text-[11px] text-lo font-mono text-right self-center">
          DB: {freshness?.latest_date || ranking?.as_of || '—'}
          {freshness && !freshness.is_fresh && freshness.gap_days > 0 && (
            <span className="text-warn ml-1">({freshness.gap_days}d behind)</span>
          )}
        </div>
      </header>

      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-3 rounded-2xl bg-panel border border-line p-3">
        <span className="section-label">Interval</span>
        <div className="flex rounded-lg bg-panel2 border border-line p-0.5">
          {INTERVALS.map((i) => (
            <button key={i} onClick={() => setInterval(i)}
              className={`px-3 py-1 rounded-md text-[12px] font-medium transition ${interval === i ? 'bg-raise text-hi shadow-sm' : 'text-mid hover:text-hi'}`}>
              {i.toUpperCase()}
            </button>
          ))}
        </div>
        <label className="ml-2 text-[12px] text-mid flex items-center gap-2">flow_z_hot
          <input type="number" step={0.1} value={flowZHot} onChange={(e) => setFlowZHot(parseFloat(e.target.value) || 0)}
            className="bg-panel2 border border-line rounded-md px-2 py-1 w-16 text-[12px] text-hi font-mono" />
        </label>
        <button onClick={handleRefresh} disabled={refreshing}
          className="ml-2 px-3 py-1.5 rounded-lg text-[12px] font-semibold text-bg disabled:opacity-50"
          style={{ background: 'linear-gradient(135deg,#46C9E6,#2C9C8E)' }}>
          {refreshing ? '⟳ Đang fetch...' : '⟳ Refresh hôm nay'}
        </button>
        {refreshMsg && (
          <span className={`text-[11px] font-mono ${refreshMsg.startsWith('✗') ? 'text-sell' : refreshMsg.startsWith('⟳') ? 'text-acc' : 'text-buy'}`}>{refreshMsg}</span>
        )}
      </div>

      {err && <div className="p-3 bg-sell/[0.12] border border-sell/40 text-sell rounded-xl text-sm">{err}</div>}

      <IndexPanel />
      <ZChart series={series} selected={selected} onSelect={setSelected} />
      <HeatStrip heat={heat} />

      {/* ranking table */}
      <section className="rounded-2xl bg-panel border border-line overflow-hidden">
        <div className="p-3 border-b border-line section-label">Xếp hạng dòng tiền</div>
        <table className="w-full text-sm">
          <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
            <tr>
              <th className="p-2.5 text-left">#</th>
              <th className="p-2.5 text-left">Ngành</th>
              <th className="p-2.5 text-right">Score</th>
              <th className="p-2.5 text-right">Flow Z20</th>
              <th className="p-2.5 text-right">Net Flow (tỷ)</th>
              <th className="p-2.5 text-right">Breadth</th>
              <th className="p-2.5 text-left">Action</th>
              <th className="p-2.5 text-left">Why</th>
            </tr>
          </thead>
          <tbody>
            {ranking?.rows.map((r) => {
              const on = selected === r.sector;
              return (
                <tr key={r.sector}
                  onClick={() => setSelected(on ? null : r.sector)}
                  className={`border-b border-line cursor-pointer transition ${on ? 'bg-acc/[0.06]' : 'hover:bg-panel2/60'}`}>
                  <td className="p-2.5 text-lo font-mono">{r.rank}</td>
                  <td className="p-2.5">
                    <span className="inline-block w-2 h-2 rounded-full mr-2 align-middle" style={{ background: colorFor(r.sector) }} />
                    <Link to={`/flow/${r.sector}`} onClick={(e) => e.stopPropagation()} className="font-semibold text-hi hover:text-acc transition">{r.sector}</Link>
                    <span className="text-lo text-xs ml-2">{r.name}</span>
                  </td>
                  <td className="p-2.5 text-right font-mono text-hi">{r.score.toFixed(2)}</td>
                  <td className={`p-2.5 text-right font-mono ${r.flow_z20 > 0 ? 'text-buy' : 'text-sell'}`}>{r.flow_z20 >= 0 ? '+' : ''}{r.flow_z20.toFixed(2)}</td>
                  <td className="p-2.5 text-right font-mono text-mid">{(r.net_dollar_flow / 1e9).toFixed(2)}</td>
                  <td className="p-2.5 text-right font-mono text-mid">{r.breadth_sma20.toFixed(2)}</td>
                  <td className="p-2.5"><span className={`px-2 py-0.5 rounded-md text-[11px] font-semibold ${ACTION_CHIP[r.action] || 'bg-raise text-mid'}`}>{r.action}</span></td>
                  <td className="p-2.5 text-[11px] text-mid">{r.why}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}
