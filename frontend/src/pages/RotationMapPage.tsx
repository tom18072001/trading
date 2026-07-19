import { useEffect, useMemo, useState } from 'react';
import { rotationApi } from '../api/client';
import type { Interval } from '../api/client';

const INTERVALS: Interval[] = ['1d', '1w', '2w', '1m', '1q'];

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
  delta_share_source: number; delta_share_target: number;
  corr: number | null; weight: number; action: string;
};

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
    return <div className="rounded-2xl bg-panel border border-line p-6 text-center text-lo text-sm">Chưa có pair nào vượt ngưỡng.</div>;
  }
  const deltaShare = (code: string, pairsArr: Pair[], side: 'src' | 'tgt') => {
    const row = pairsArr.find((p) => (side === 'src' ? p.from : p.to) === code);
    return side === 'src' ? row?.delta_share_source : row?.delta_share_target;
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
          const p = model.sPos.get(s)!; const ds = deltaShare(s, pairs, 'src');
          return (
            <g key={`s-${s}`}>
              <rect x={SX} y={p.y0} width={NODE_W} height={p.y1 - p.y0} rx="3" fill={colorFor(s)} />
              <text x={SX - 8} y={(p.y0 + p.y1) / 2} textAnchor="end" dominantBaseline="middle"
                fontSize="12" fontFamily="JetBrains Mono" fill="#EAF0F7">
                {s} <tspan fill="#FF5D73">{ds != null ? `${(ds * 100).toFixed(1)}%` : ''}</tspan>
              </text>
            </g>
          );
        })}
        {model.targets.map((t) => {
          const p = model.tPos.get(t)!; const ds = deltaShare(t, pairs, 'tgt');
          return (
            <g key={`t-${t}`}>
              <rect x={TX} y={p.y0} width={NODE_W} height={p.y1 - p.y0} rx="3" fill={colorFor(t)} />
              <text x={TX + NODE_W + 8} y={(p.y0 + p.y1) / 2} dominantBaseline="middle"
                fontSize="12" fontFamily="JetBrains Mono" fill="#EAF0F7">
                {t} <tspan fill="#33D49A">{ds != null ? `+${(ds * 100).toFixed(1)}%` : ''}</tspan>
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
  const [interval, setInterval] = useState<Interval>('1w');
  const [threshold, setThreshold] = useState(1.5);
  const [pairs, setPairs] = useState<any>(null);
  const [sankey, setSankey] = useState<any>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setErr(null);
    Promise.all([rotationApi.pairs(interval, threshold), rotationApi.sankey(interval, threshold)])
      .then(([p, s]) => { setPairs(p.data); setSankey(s.data); })
      .catch((e) => setErr(String(e?.message || e)));
  }, [interval, threshold]);

  const rows: Pair[] = pairs?.rows ?? [];

  return (
    <div className="px-8 py-8 max-w-[1240px] mx-auto space-y-[22px]">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-[29px] font-bold text-hi tracking-tight">Rotation Map</h1>
          <p className="text-[13px] text-mid mt-0.5">Tiền dịch chuyển TỪ ngành nào SANG ngành nào</p>
        </div>
        <div className="text-[11px] text-lo font-mono self-center">
          {sankey?.window?.start || '—'} → {sankey?.window?.end || '—'}
        </div>
      </header>

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
        <label className="ml-2 text-[12px] text-mid flex items-center gap-2">min Δz
          <input type="number" step={0.1} value={threshold} onChange={(e) => setThreshold(parseFloat(e.target.value) || 0)}
            className="bg-panel2 border border-line rounded-md px-2 py-1 w-16 text-[12px] text-hi font-mono" />
        </label>
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
              <th className="p-2.5 text-right">Δz nguồn</th>
              <th className="p-2.5 text-right">Δz đích</th>
              <th className="p-2.5 text-right">Corr</th>
              <th className="p-2.5 text-right">Weight</th>
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
                  <td className="p-2.5 text-right font-mono text-sell">{r.delta_share_source.toFixed(3)}</td>
                  <td className="p-2.5 text-right font-mono text-buy">+{r.delta_share_target.toFixed(3)}</td>
                  <td className="p-2.5 text-right font-mono text-mid">{r.corr != null ? r.corr.toFixed(2) : '—'}</td>
                  <td className="p-2.5 text-right font-mono text-hi">{r.weight.toFixed(3)}</td>
                  <td className="p-2.5"><span className={`px-2 py-0.5 rounded-md text-[11px] font-semibold ${STATUS_CHIP[r.action] || 'bg-raise text-mid'}`}>{r.action}</span></td>
                </tr>
              );
            }) : (
              <tr><td colSpan={7} className="p-6 text-center text-lo">Chưa có pair nào vượt ngưỡng.</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
