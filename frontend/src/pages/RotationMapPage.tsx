import { useEffect, useMemo, useState } from 'react';
import { sectorsApi } from '../api/client';
import type { HandoffRow } from '../api/client';

// 2026-08-23: this page used to call /api/rotation/{pairs,sankey}, which
// returned an empty pair list at every threshold — see the module docstring in
// api/routers/rotation.py for why that is structural, not a tuning problem.
// It now reads /api/sectors/handoff, which computes the same rotation from
// flow_z20 with each side clipped at zero independently.
//
// The controls change with the data source: the old "interval" + "min Δz"
// meant nothing to the handoff endpoint. `window` is the Δ lookback in
// sessions; `lookback_days` is how much history to scan.
const WINDOWS = [3, 5, 10, 20];
const LOOKBACKS = [30, 60, 120];

const SECTOR_COLORS: Record<string, string> = {
  CHEM: '#33D49A', REAL: '#46C9E6', OIL: '#7FB2FF', POWER: '#B98BFF', INSUR: '#F5B13D',
  TECH: '#7A8696', FOOD: '#5CCFB8', STEEL: '#E08A6B', BANK: '#FF8FA0', TEXT: '#FF5D73',
  BROK: '#9C8BFF', RETAIL: '#E6C84A', LOGIS: '#6BD0E0', RUBBER: '#C98B6B', FISH: '#5C9CCF',
};
const colorFor = (s: string) => SECTOR_COLORS[s] ?? '#7A8696';

const STATUS_CHIP: Record<string, string> = {
  CONFIRMED: 'bg-buy/[0.13] text-buy', EMERGING: 'bg-warn/[0.13] text-warn', FADING: 'bg-sell/[0.13] text-sell',
};

type Pair = {
  rank: number; from: string; to: string;
  weight: number;       // summed handoff_score over the window
  sessions: number;     // how many sessions this pair showed up in
  lastDate: string;     // most recent session it appeared
  action: string;
};

// The endpoint returns one row per (date, from, to). A pair that appears on
// many sessions is a persistent rotation; one that appears once is noise. Sum
// the score and count the sessions, then label:
//   CONFIRMED = seen on >=3 sessions   EMERGING = 2   FADING = 1
function aggregate(rows: HandoffRow[]): Pair[] {
  const acc = new Map<string, { from: string; to: string; weight: number; sessions: number; lastDate: string }>();
  for (const r of rows) {
    const k = `${r.from_sector}->${r.to_sector}`;
    const cur = acc.get(k);
    if (cur) {
      cur.weight += r.handoff_score;
      cur.sessions += 1;
      if (r.date > cur.lastDate) cur.lastDate = r.date;
    } else {
      acc.set(k, { from: r.from_sector, to: r.to_sector, weight: r.handoff_score, sessions: 1, lastDate: r.date });
    }
  }
  return [...acc.values()]
    .sort((a, b) => b.weight - a.weight)
    .map((p, i) => ({
      ...p,
      rank: i + 1,
      action: p.sessions >= 3 ? 'CONFIRMED' : p.sessions === 2 ? 'EMERGING' : 'FADING',
    }));
}

// ---- SVG Sankey built from pair weights ----
function Sankey({ pairs, selected, onSelect }: {
  pairs: Pair[]; selected: string | null; onSelect: (k: string | null) => void;
}) {
  const W = 1000, H = 420, NODE_W = 14, SX = 156, TX = 830, PAD = 14;

  const model = useMemo(() => {
    if (!pairs.length) return null;
    const srcW = new Map<string, number>();
    const tgtW = new Map<string, number>();
    for (const p of pairs) {
      srcW.set(p.from, (srcW.get(p.from) || 0) + p.weight);
      tgtW.set(p.to, (tgtW.get(p.to) || 0) + p.weight);
    }
    const sources = [...srcW.keys()];
    const targets = [...tgtW.keys()];
    const totalW = Math.max([...srcW.values()].reduce((a, b) => a + b, 0), 1e-9);
    const usableH = H - PAD * 2;
    const scale = (usableH - PAD * (Math.max(sources.length, targets.length) - 1)) / totalW;

    const place = (keys: string[], wmap: Map<string, number>) => {
      const pos = new Map<string, { y0: number; y1: number; cursor: number }>();
      let y = PAD;
      for (const k of keys) {
        const h = Math.max(8, (wmap.get(k) || 0) * scale);
        pos.set(k, { y0: y, y1: y + h, cursor: y });
        y += h + PAD;
      }
      return pos;
    };
    const sPos = place(sources, srcW);
    const tPos = place(targets, tgtW);

    const ribbons = pairs.map((p) => {
      const s = sPos.get(p.from)!; const t = tPos.get(p.to)!;
      const h = Math.max(2, p.weight * scale);
      const sy = s.cursor; s.cursor += h;
      const ty = t.cursor; t.cursor += h;
      const x0 = SX + NODE_W, x1 = TX;
      const mx = (x0 + x1) / 2;
      const top = `M ${x0} ${sy} C ${mx} ${sy}, ${mx} ${ty}, ${x1} ${ty}`;
      const bot = `L ${x1} ${ty + h} C ${mx} ${ty + h}, ${mx} ${sy + h}, ${x0} ${sy + h} Z`;
      return { key: `${p.from}-${p.to}`, from: p.from, d: `${top} ${bot}` };
    });
    return { sources, targets, sPos, tPos, ribbons, srcW, tgtW };
  }, [pairs]);

  if (!model) {
    return <div className="rounded-2xl bg-panel border border-line p-6 text-center text-lo text-sm">Chưa có cặp luân chuyển nào trong khoảng này.</div>;
  }
  // Node label = that sector's share of total handoff weight on its side.
  const share = (code: string, side: 'src' | 'tgt') => {
    const wmap = side === 'src' ? model.srcW : model.tgtW;
    const total = [...wmap.values()].reduce((a, b) => a + b, 0) || 1;
    return (wmap.get(code) || 0) / total;
  };

  return (
    <section className="rounded-2xl bg-panel border border-line p-[22px]">
      <div className="section-label mb-3">Sơ đồ luân chuyển (Sankey)</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[400px]">
        {model.ribbons.map((r) => {
          const on = selected === r.key;
          const dim = selected != null && !on;
          return (
            <path key={r.key} d={r.d} fill={colorFor(r.from)}
              opacity={on ? 0.7 : dim ? 0.07 : 0.34}
              onClick={() => onSelect(on ? null : r.key)} style={{ cursor: 'pointer' }} />
          );
        })}
        {model.sources.map((s) => {
          const p = model.sPos.get(s)!;
          return (
            <g key={`s-${s}`}>
              <rect x={SX} y={p.y0} width={NODE_W} height={p.y1 - p.y0} rx="3" fill={colorFor(s)} />
              <text x={SX - 8} y={(p.y0 + p.y1) / 2} textAnchor="end" dominantBaseline="middle"
                fontSize="12" fontFamily="JetBrains Mono" fill="#EAF0F7">
                {s} <tspan fill="#FF5D73">{`${(share(s, 'src') * 100).toFixed(0)}%`}</tspan>
              </text>
            </g>
          );
        })}
        {model.targets.map((t) => {
          const p = model.tPos.get(t)!;
          return (
            <g key={`t-${t}`}>
              <rect x={TX} y={p.y0} width={NODE_W} height={p.y1 - p.y0} rx="3" fill={colorFor(t)} />
              <text x={TX + NODE_W + 8} y={(p.y0 + p.y1) / 2} dominantBaseline="middle"
                fontSize="12" fontFamily="JetBrains Mono" fill="#EAF0F7">
                {t} <tspan fill="#33D49A">{`${(share(t, 'tgt') * 100).toFixed(0)}%`}</tspan>
              </text>
            </g>
          );
        })}
      </svg>
      <div className="flex justify-between text-[10px] text-lo font-mono mt-1 px-2">
        <span className="text-sell">Nguồn (tiền ra)</span>
        <span className="text-buy">Đích (tiền vào)</span>
      </div>
    </section>
  );
}

export default function RotationMapPage() {
  const [window_, setWindow] = useState(5);
  const [lookback, setLookback] = useState(60);
  const [raw, setRaw] = useState<HandoffRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setErr(null);
    sectorsApi.handoff(lookback, window_, 5)
      .then((r) => setRaw(r.data.handoffs ?? []))
      .catch((e) => setErr(String(e?.message || e)));
  }, [lookback, window_]);

  const rows: Pair[] = useMemo(() => aggregate(raw), [raw]);
  const span = useMemo(() => {
    if (!raw.length) return { start: '—', end: '—' };
    const ds = raw.map((r) => r.date).sort();
    return { start: ds[0], end: ds[ds.length - 1] };
  }, [raw]);

  return (
    <div className="px-8 py-8 max-w-[1240px] mx-auto space-y-[22px]">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-[29px] font-bold text-hi tracking-tight">Rotation Map</h1>
          <p className="text-[13px] text-mid mt-0.5">Tiền dịch chuyển TỪ ngành nào SANG ngành nào</p>
        </div>
        <div className="text-[11px] text-lo font-mono self-center">
          {span.start} → {span.end}
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-3 rounded-2xl bg-panel border border-line p-3">
        <span className="section-label">Cửa sổ Δ</span>
        <div className="flex rounded-lg bg-panel2 border border-line p-0.5">
          {WINDOWS.map((w) => (
            <button key={w} onClick={() => setWindow(w)}
              className={`px-3 py-1 rounded-md text-[12px] font-medium transition ${window_ === w ? 'bg-raise text-hi shadow-sm' : 'text-mid hover:text-hi'}`}>
              {w}p
            </button>
          ))}
        </div>
        <span className="section-label ml-2">Lịch sử</span>
        <div className="flex rounded-lg bg-panel2 border border-line p-0.5">
          {LOOKBACKS.map((l) => (
            <button key={l} onClick={() => setLookback(l)}
              className={`px-3 py-1 rounded-md text-[12px] font-medium transition ${lookback === l ? 'bg-raise text-hi shadow-sm' : 'text-mid hover:text-hi'}`}>
              {l}p
            </button>
          ))}
        </div>
        <span className="ml-auto text-[11px] text-lo font-mono">{rows.length} cặp · {raw.length} dòng</span>
      </div>

      {err && <div className="p-3 bg-sell/[0.12] border border-sell/40 text-sell rounded-xl text-sm">{err}</div>}

      <Sankey pairs={rows} selected={selected} onSelect={setSelected} />

      <section className="rounded-2xl bg-panel border border-line overflow-hidden">
        <div className="p-3 border-b border-line section-label">Cặp luân chuyển</div>
        <table className="w-full text-sm">
          <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
            <tr>
              <th className="p-2.5 text-left">#</th>
              <th className="p-2.5 text-left">From → To</th>
              <th className="p-2.5 text-right">Số phiên</th>
              <th className="p-2.5 text-right">Phiên gần nhất</th>
              <th className="p-2.5 text-right">Handoff score</th>
              <th className="p-2.5 text-left">Trạng thái</th>
            </tr>
          </thead>
          <tbody>
            {rows.length ? rows.map((r) => {
              const key = `${r.from}-${r.to}`;
              const on = selected === key;
              return (
                <tr key={key} onClick={() => setSelected(on ? null : key)}
                  className={`border-b border-line cursor-pointer transition ${on ? 'bg-acc/[0.06]' : 'hover:bg-panel2/60'}`}>
                  <td className="p-2.5 text-lo font-mono">{r.rank}</td>
                  <td className="p-2.5">
                    <span className="inline-block w-2 h-2 rounded-full mr-1.5 align-middle" style={{ background: colorFor(r.from) }} />
                    <span className="font-semibold text-hi">{r.from}</span>
                    <span className="text-lo mx-1.5">→</span>
                    <span className="inline-block w-2 h-2 rounded-full mr-1.5 align-middle" style={{ background: colorFor(r.to) }} />
                    <span className="font-semibold text-hi">{r.to}</span>
                  </td>
                  <td className="p-2.5 text-right font-mono text-mid">{r.sessions}</td>
                  <td className="p-2.5 text-right font-mono text-lo">{r.lastDate}</td>
                  <td className="p-2.5 text-right font-mono text-hi">{r.weight.toFixed(2)}</td>
                  <td className="p-2.5"><span className={`px-2 py-0.5 rounded-md text-[11px] font-semibold ${STATUS_CHIP[r.action] || 'bg-raise text-mid'}`}>{r.action}</span></td>
                </tr>
              );
            }) : (
              <tr><td colSpan={6} className="p-6 text-center text-lo">Chưa có cặp luân chuyển nào trong khoảng này.</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
