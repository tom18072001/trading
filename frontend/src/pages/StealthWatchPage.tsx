import { useEffect, useState, useCallback } from 'react';
import { stealthApi15 } from '../api/client';

const GATE_KEYS = ['cond1_flow', 'cond2_foreign', 'cond3_breadth', 'cond4_atr_quiet', 'cond5_price_cheap'] as const;
const GANTT_WINDOW = 30;

const HIST_CHIP: Record<string, string> = {
  HIT: 'bg-buy/[0.13] text-buy',
  'FALSE POSITIVE': 'bg-sell/[0.13] text-sell',
  'DRY-POWDER TIMEOUT': 'bg-raise text-mid',
};

function GateRow({ g }: { g: any }) {
  if (!g) return null;
  return (
    <div className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg border text-[11px] ${
      g.pass ? 'bg-buy/[0.08] border-buy/25' : 'bg-sell/[0.05] border-sell/20'
    }`}>
      <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold ${
        g.pass ? 'bg-buy/20 text-buy' : 'bg-sell/15 text-sell'
      }`}>{g.pass ? '✓' : '✗'}</span>
      <span className={`font-semibold min-w-[120px] ${g.pass ? 'text-buy' : 'text-sell'}`}>{g.label}</span>
      <span className="font-mono text-hi">{Number(g.value).toFixed(3)}</span>
      <span className="text-lo">/</span>
      <span className="font-mono text-mid">{Number(g.threshold).toFixed(2)}</span>
      <span className={`ml-auto text-[10px] ${g.pass ? 'text-lo' : 'text-sell/80'}`}>{g.reason}</span>
    </div>
  );
}

function StealthCard({ e }: { e: any }) {
  const passes = e.conditions_passing ?? 0;
  const isActive = e.status === 'active';
  return (
    <div className="rounded-2xl bg-panel border border-line p-4 flex flex-col gap-3 animate-fade-up">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-display text-[18px] font-bold text-hi leading-none">{e.sector}</div>
          <div className="text-[11px] text-lo mt-1">{e.name}</div>
        </div>
        <div className="text-right">
          <div className="section-label">Stealth score</div>
          <div className="font-mono text-warn text-[18px] font-bold tabular">{(e.stealth_score ?? 0).toFixed(2)}</div>
        </div>
      </div>

      <div className="space-y-1">
        {GATE_KEYS.map((k) => <GateRow key={k} g={e.gate?.[k]} />)}
      </div>

      {/* persistence bar */}
      <div>
        <div className="flex justify-between text-[10px] text-mid mb-1">
          <span>Điều kiện đạt</span><span className="font-mono">{passes}/5 · age {e.accumulation_age ?? 0}d</span>
        </div>
        <div className="h-1.5 rounded-full bg-raise overflow-hidden">
          <div className="h-full bg-warn" style={{ width: `${(passes / 5) * 100}%`, transition: 'width .5s' }} />
        </div>
      </div>

      {isActive && e.days_until_breakout != null && (
        <div className="rounded-xl bg-acc/[0.1] border border-acc/30 text-acc text-[12px] px-3 py-2">
          Dự kiến breakout ~{e.days_until_breakout}d (theo lead-time lịch sử)
        </div>
      )}
    </div>
  );
}

export default function StealthWatchPage() {
  const [data, setData] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<'active' | 'warming'>('active');

  const [flowZHot, setFlowZHot] = useState(1.0);
  const [foreignHitMin, setForeignHitMin] = useState(0.6);
  const [breadthMin, setBreadthMin] = useState(0.5);
  const [atrRankMax, setAtrRankMax] = useState(0.5);
  const [closePctMax, setClosePctMax] = useState(0.4);
  const [minSessions, setMinSessions] = useState(5);

  const load = useCallback(() => {
    setErr(null);
    stealthApi15.active({
      flow_z_hot: flowZHot, foreign_hit_min: foreignHitMin, breadth_min: breadthMin,
      atr_rank_max: atrRankMax, close_pct_60d_max: closePctMax, min_sessions: minSessions,
    }).then((r) => setData(r.data)).catch((e) => setErr(String(e?.message || e)));
    stealthApi15.history(50).then((r: any) => setHistory(r.data?.rows || r.data?.history || [])).catch(() => {});
  }, [flowZHot, foreignHitMin, breadthMin, atrRankMax, closePctMax, minSessions]);

  useEffect(load, [load]);

  const active = data?.active ?? [];
  const warming = data?.warming ?? [];
  const inactive = data?.inactive ?? [];
  const ganttRows = [...active, ...warming, ...inactive];

  const ctrl = (label: string, value: number, set: (n: number) => void, step: number) => (
    <label className="text-[11px] text-mid flex items-center gap-1.5">{label}
      <input type="number" step={step} value={value} onChange={(e) => set(+e.target.value || 0)}
        className="bg-panel2 border border-line rounded-md px-2 py-1 w-14 text-[11px] text-hi font-mono" />
    </label>
  );

  return (
    <div className="px-8 py-8 max-w-[1240px] mx-auto space-y-[22px]">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-[29px] font-bold text-hi tracking-tight">Stealth Watch</h1>
          <p className="text-[13px] text-mid mt-0.5">Tích luỹ âm thầm + ước lượng lead-time breakout</p>
        </div>
        <span className="text-[11px] text-lo font-mono self-center">as of {data?.as_of || '—'}</span>
      </header>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl bg-panel border border-line p-3">
        {ctrl('flow_z', flowZHot, setFlowZHot, 0.1)}
        {ctrl('foreign_hit', foreignHitMin, setForeignHitMin, 0.05)}
        {ctrl('breadth', breadthMin, setBreadthMin, 0.05)}
        {ctrl('atr_rank', atrRankMax, setAtrRankMax, 0.05)}
        {ctrl('close_pct', closePctMax, setClosePctMax, 0.05)}
        {ctrl('min_sessions', minSessions, setMinSessions, 1)}
      </div>

      {err && <div className="p-3 bg-sell/[0.12] border border-sell/40 text-sell rounded-xl text-sm">{err}</div>}

      {/* Gantt timeline */}
      {ganttRows.length > 0 && (
        <section className="rounded-2xl bg-panel border border-line p-[22px]">
          <div className="section-label mb-3">Dòng thời gian tích luỹ ({GANTT_WINDOW} phiên)</div>
          <div className="space-y-1.5">
            {ganttRows.map((e: any) => {
              const age = Math.min(e.accumulation_age ?? 0, GANTT_WINDOW);
              const left = ((GANTT_WINDOW - age) / GANTT_WINDOW) * 100;
              const width = (age / GANTT_WINDOW) * 100;
              const tone = e.status === 'active' ? '#F5B13D' : e.status === 'warming' ? 'rgba(245,177,61,.45)' : 'rgba(245,177,61,.18)';
              return (
                <div key={e.sector} className="flex items-center gap-2">
                  <span className="w-12 text-[10px] font-mono text-mid shrink-0">{e.sector}</span>
                  <div className="relative flex-1 h-4 rounded bg-panel2">
                    {age > 0 && (
                      <div className="absolute top-0 h-full rounded" style={{ left: `${left}%`, width: `${Math.max(width, 3)}%`, background: tone }}
                        title={`${e.sector} · age ${age}d · ${e.status}`} />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="flex justify-between text-[10px] text-lo font-mono mt-2 pl-14">
            <span>−{GANTT_WINDOW} phiên</span><span>hôm nay</span>
          </div>
        </section>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-2">
        <div className="flex rounded-lg bg-panel2 border border-line p-0.5">
          {(['active', 'warming'] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-3 py-1 rounded-md text-[12px] font-medium transition ${tab === t ? 'bg-raise text-hi shadow-sm' : 'text-mid hover:text-hi'}`}>
              {t === 'active' ? `Active (${active.length})` : `Warming (${warming.length})`}
            </button>
          ))}
        </div>
        <span className="text-[11px] text-lo">Inactive: {inactive.length}</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {(tab === 'active' ? active : warming).map((e: any) => <StealthCard key={e.sector} e={e} />)}
        {(tab === 'active' ? active : warming).length === 0 && (
          <div className="col-span-full rounded-2xl bg-panel border border-line p-6 text-center text-lo text-sm">
            Không có ngành nào ở trạng thái {tab === 'active' ? 'Active' : 'Warming'}.
          </div>
        )}
      </div>

      {/* History */}
      {history.length > 0 && (
        <section className="rounded-2xl bg-panel border border-line overflow-hidden">
          <div className="p-3 border-b border-line section-label">Lịch sử sự kiện tích luỹ</div>
          <table className="w-full text-sm">
            <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
              <tr>
                <th className="p-2.5 text-left">Ngành</th>
                <th className="p-2.5 text-left">Bắt đầu</th>
                <th className="p-2.5 text-left">Kết thúc</th>
                <th className="p-2.5 text-right">Peak return</th>
                <th className="p-2.5 text-right">Lead (phiên)</th>
                <th className="p-2.5 text-left">Kết quả</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h: any, i: number) => (
                <tr key={i} className="border-b border-line hover:bg-panel2/60">
                  <td className="p-2.5 font-semibold text-hi">{h.sector_code ?? h.sector}</td>
                  <td className="p-2.5 font-mono text-mid">{h.start_date ?? '—'}</td>
                  <td className="p-2.5 font-mono text-mid">{h.end_date ?? '—'}</td>
                  <td className={`p-2.5 text-right font-mono ${(h.peak_return_pct ?? 0) >= 0 ? 'text-buy' : 'text-sell'}`}>
                    {h.peak_return_pct != null ? `${h.peak_return_pct >= 0 ? '+' : ''}${h.peak_return_pct.toFixed(1)}%` : '—'}
                  </td>
                  <td className="p-2.5 text-right font-mono text-hi">{h.lead_days_to_price ?? h.lead_days ?? '—'}</td>
                  <td className="p-2.5">
                    {h.classification && (
                      <span className={`px-2 py-0.5 rounded-md text-[11px] font-semibold ${HIST_CHIP[h.classification] || 'bg-raise text-mid'}`}>{h.classification}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
