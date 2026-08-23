import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { insightApi, stateApi, type InsightRefreshStatus, type ReportStatus } from '../api/client';
import { ActionBadge } from '../lib/actions';
import { isHeld, tradingState, useTradingState } from '../lib/tradingState';

// Polls /insight/refresh/status until the background run completes. Used by
// the Refresh button so the UI can surface stage + progress % instead of
// hitting axios's 5-minute timeout on the old sync endpoint.
const REFRESH_POLL_INTERVAL_MS = 2000;
const REFRESH_MAX_WAIT_MS = 20 * 60_000; // hard ceiling: 20 minutes

const STAGE_LABELS: Record<string, string> = {
  queued:                'Đang khởi tạo…',
  publishing_signals:    'Xuất tín hiệu xếp hạng…',
  rebuilding_universe:   'Dựng universe HOSE (KBS)…',
  trader_agent:          'Minh đang phân tích…',
  assembling:            'Tổng hợp kết quả…',
  done:                  'Hoàn tất',
  error:                 'Lỗi',
  idle:                  'Chưa chạy',
  unknown:               'Không xác định',
};

export function fmtNum(v: number | null | undefined, digits = 2) {
  if (v == null || Number.isNaN(v)) return '—';
  return v.toLocaleString('vi-VN', { maximumFractionDigits: digits });
}

export function fmtPct(v: number | null | undefined, digits = 2) {
  if (v == null || Number.isNaN(v)) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`;
}

// Field accessors — picks come either from PicksUniverseService.top_buys
// (PickEntry shape: close/rr/sector_code) or the legacy _build_picks fallback
// (price/r_r/sector). Normalize so the table binds to one shape.
const pClose   = (p: any) => p.close ?? p.price;
const pRr      = (p: any) => p.rr ?? p.r_r;
const pSecCode = (p: any) => p.sector_code ?? p.sector;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

function convictionOf(p: any): number {
  if (p.conviction != null) return clamp(Math.round(p.conviction), 0, 5);
  const rr = pRr(p) ?? 0;
  if (rr >= 2.5) return 5;
  if (rr >= 2.0) return 4;
  if (rr >= 1.5) return 3;
  return 2;
}
const starStr = (n: number) => '★'.repeat(clamp(n, 0, 5)) + '☆'.repeat(5 - clamp(n, 0, 5));

// ===================================================================
//  Regime gauge — SVG semicircle (red → slate → green), needle by score
// ===================================================================
function polar(cx: number, cy: number, r: number, deg: number) {
  const rad = (deg * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy - r * Math.sin(rad) };
}
function arcPath(cx: number, cy: number, r: number, a0: number, a1: number) {
  const s = polar(cx, cy, r, a0);
  const e = polar(cx, cy, r, a1);
  const large = Math.abs(a1 - a0) > 180 ? 1 : 0;
  // sweep 0 = counter-clockwise in SVG y-down → we go a0(high deg)→a1(low deg)
  return `M ${s.x.toFixed(1)} ${s.y.toFixed(1)} A ${r} ${r} 0 ${large} 1 ${e.x.toFixed(1)} ${e.y.toFixed(1)}`;
}

const REGIME_BASE: Record<string, number> = {
  risk_on: 0.82, rotation: 0.6, chop: 0.5, risk_off: 0.22,
};
const REGIME_VN: Record<string, string> = {
  risk_on: 'Risk-On', rotation: 'Luân chuyển', chop: 'Đi ngang', risk_off: 'Risk-Off',
};

function RegimeGauge({ label, confidence, buy, sell }: {
  label: string; confidence: number; buy: number; sell: number;
}) {
  const base = REGIME_BASE[label] ?? 0.5;
  const tilt = clamp(((buy - sell) / Math.max(buy + sell, 1)) * 0.15, -0.15, 0.15);
  const score = clamp(base + tilt, 0.05, 0.95);
  const needleDeg = 180 - score * 180; // 180°(left/red) → 0°(right/green)
  const n = polar(100, 100, 72, needleDeg);
  const defensive = label === 'risk_off' || label === 'chop';

  return (
    <div className="flex flex-col items-center justify-center">
      <svg viewBox="0 0 200 116" className="w-full max-w-[230px]">
        <path d={arcPath(100, 100, 80, 180, 120)} stroke="#FF5D73" strokeWidth="11" fill="none" strokeLinecap="round" opacity="0.85" />
        <path d={arcPath(100, 100, 80, 120, 60)} stroke="#3B4350" strokeWidth="11" fill="none" />
        <path d={arcPath(100, 100, 80, 60, 0)} stroke="#33D49A" strokeWidth="11" fill="none" strokeLinecap="round" opacity="0.85" />
        <line x1="100" y1="100" x2={n.x.toFixed(1)} y2={n.y.toFixed(1)} stroke="#EAF0F7" strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="100" cy="100" r="5" fill="#EAF0F7" />
      </svg>
      <div className="text-center -mt-2">
        <div className="font-display text-[19px] font-bold text-hi leading-tight">
          {REGIME_VN[label] ?? (label || '—')}
        </div>
        <div className="text-[11px] text-mid font-mono mt-0.5">
          Độ tin cậy {((confidence ?? 0) * 100).toFixed(0)}%
        </div>
        <div
          className={`inline-block mt-2 px-2.5 py-1 rounded-md text-[10.5px] font-semibold ${
            defensive
              ? 'bg-warn/[0.12] text-warn border border-warn/30'
              : 'bg-buy/[0.13] text-buy border border-buy/30'
          }`}
        >
          {defensive ? 'Tư thế phòng thủ' : 'Tư thế tấn công'}
        </div>
      </div>
    </div>
  );
}

// ===================================================================
//  Count tiles  (NÊN MUA / NÊN BÁN / TÍCH LUỸ NGẦM)
// ===================================================================
function CountTile({ n, label, tone }: { n: number; label: string; tone: 'buy' | 'sell' | 'warn' }) {
  const map = {
    buy:  { c: 'text-buy',  wash: 'rgba(51,212,154,.10)' },
    sell: { c: 'text-sell', wash: 'rgba(255,93,115,.10)' },
    warn: { c: 'text-warn', wash: 'rgba(245,177,61,.10)' },
  }[tone];
  return (
    <div
      className="relative overflow-hidden rounded-2xl bg-panel2 border border-line p-5 flex flex-col justify-between"
      style={{ backgroundImage: `linear-gradient(135deg, ${map.wash}, transparent 60%)` }}
    >
      <div className="section-label">{label}</div>
      <div className={`font-display text-[42px] font-bold leading-none mt-3 tabular ${map.c}`}>{n}</div>
    </div>
  );
}

// ===================================================================
//  Sector flow spectrum — dots positioned by flow_z20 + 3 delta cards
// ===================================================================
function FlowSpectrum({ picks, deltas }: { picks: any[]; deltas: any[] }) {
  // Dedupe picks by sector, keep first flow_z20 seen.
  const dots = useMemo(() => {
    const seen = new Map<string, { code: string; z: number; action: string }>();
    for (const p of picks || []) {
      const code = pSecCode(p);
      const z = p.flow_z20;
      if (code && z != null && !seen.has(code)) {
        seen.set(code, { code, z, action: p.action });
      }
    }
    return [...seen.values()];
  }, [picks]);

  const DELTA_META: Record<string, { label: string; tone: string; color: string }> = {
    flow_z_up:   { label: 'Dòng tiền VÀO',  tone: 'text-buy',  color: '#33D49A' },
    flow_z_down: { label: 'Dòng tiền RA',   tone: 'text-sell', color: '#FF5D73' },
    stealth_top: { label: 'Tích luỹ ngầm',  tone: 'text-warn', color: '#F5B13D' },
  };

  return (
    <section className="rounded-2xl bg-panel border border-line p-[22px]">
      <div className="section-label mb-3">Phổ dòng tiền theo ngành</div>

      {/* Axis */}
      <div className="relative h-16">
        <div
          className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full"
          style={{ background: 'linear-gradient(90deg, rgba(255,93,115,.55), rgba(90,101,115,.35) 50%, rgba(51,212,154,.55))' }}
        />
        {dots.map((d) => {
          const left = clamp(((d.z + 3) / 6) * 100, 1, 99);
          const big = Math.abs(d.z) > 2;
          const col = d.z >= 0 ? '#33D49A' : '#FF5D73';
          return (
            <div
              key={d.code}
              className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center"
              style={{ left: `${left}%` }}
              title={`${d.code} · flow_z20 ${d.z >= 0 ? '+' : ''}${d.z.toFixed(2)}`}
            >
              <span
                className="rounded-full"
                style={{
                  width: big ? 14 : 10, height: big ? 14 : 10, background: col,
                  boxShadow: `0 0 0 4px ${col}22`,
                }}
              />
              <span className="mt-1 text-[9.5px] font-mono text-mid">{d.code}</span>
            </div>
          );
        })}
        <span className="absolute left-0 -bottom-1 text-[10px] font-semibold text-sell">◄ DÒNG TIỀN RA</span>
        <span className="absolute right-0 -bottom-1 text-[10px] font-semibold text-buy">DÒNG TIỀN VÀO ►</span>
      </div>

      {/* 3 delta cards */}
      {Array.isArray(deltas) && deltas.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-6">
          {deltas.slice(0, 3).map((d, i) => {
            const meta = DELTA_META[d.kind] || { label: d.kind, tone: 'text-mid', color: '#909DAF' };
            return (
              <div key={i} className="rounded-xl bg-panel2 border border-line p-3.5">
                <div className={`text-[10.5px] font-bold uppercase tracking-[0.12em] ${meta.tone}`}>{meta.label}</div>
                <div className="mt-1.5 flex items-baseline gap-2">
                  <span className="font-display font-bold text-hi text-[15px]">{d.sector}</span>
                  <span className="text-[11px] text-lo truncate">{d.name}</span>
                </div>
                <div className="text-[11px] text-mid mt-1 font-mono">{d.what_changed}</div>
                <div className="text-[11px] mt-1" style={{ color: meta.color }}>→ {d.what_to_do}</div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ===================================================================
//  Trader agent report — "Minh" panel  (test-locked text/structure)
// ===================================================================
export function AgentReport({ report }: { report: any }) {
  if (!report) return null;
  if (!report.is_valid) {
    return (
      <div className="rounded-2xl bg-panel border border-warn/40 p-[18px]">
        <div className="text-[11px] text-warn uppercase tracking-[0.12em] font-bold">
          Trader Agent — Minh (chưa sẵn sàng)
        </div>
        <div className="text-[12px] text-mid mt-1">
          {report.error || 'Agent chưa phân tích phiên hôm nay. Nhấn Refresh để kích hoạt.'}
        </div>
      </div>
    );
  }
  return (
    <div
      className="rounded-2xl border border-acc/40 p-[22px]"
      style={{ background: 'linear-gradient(135deg, #11151C, rgba(70,201,230,.04))' }}
    >
      <div className="flex items-center gap-3 mb-3">
        <div
          className="w-9 h-9 rounded-[9px] flex items-center justify-center font-display font-bold text-bg text-[16px]"
          style={{ background: 'linear-gradient(140deg,#46C9E6,#2C9C8E)' }}
        >
          M
        </div>
        <div className="flex-1">
          <div className="text-[13px] font-bold text-hi font-display">Trader Agent — Minh</div>
          <div className="text-[10px] text-lo font-mono">
            {report.model} · {report.duration_ms}ms
            {report.cost_usd != null && ` · $${report.cost_usd.toFixed(3)}`}
          </div>
        </div>
      </div>
      {report.gist && (
        <div className="text-[15px] text-hi font-semibold leading-snug">{report.gist}</div>
      )}
      {report.regime_comment && (
        <div className="text-[12.5px] text-mid mt-1.5 leading-relaxed">{report.regime_comment}</div>
      )}
      {Array.isArray(report.top_buys) && report.top_buys.length > 0 && (
        <div className="mt-4">
          <div className="text-[10.5px] text-buy uppercase tracking-[0.12em] font-bold mb-1.5">Agent khuyến nghị MUA</div>
          <div className="space-y-2">
            {report.top_buys.map((p: any, i: number) => (
              <div key={i} className="bg-raise/60 border border-buy/25 rounded-xl p-3">
                <div className="flex items-baseline justify-between gap-2 flex-wrap">
                  <div>
                    <span className="text-[15px] font-bold text-hi font-display">{p.symbol}</span>
                    <span className="ml-2 text-[10px] font-mono text-acc">{p.sector}</span>
                    <span className="ml-2 text-[11px] text-warn" title={`Conviction ${p.conviction}/5`}>{starStr(p.conviction)}</span>
                  </div>
                  <div className="text-[11px] font-mono text-mid">
                    Entry {fmtNum(p.entry)} · Target <span className="text-buy">{fmtNum(p.target)}</span> · Stop <span className="text-sell">{fmtNum(p.stop)}</span>
                    {p.rr != null && <> · R:R <span className="text-warn">{p.rr.toFixed(1)}</span></>}
                  </div>
                </div>
                <div className="text-[12.5px] text-hi/90 mt-1 leading-snug">{p.reasoning}</div>
                {Array.isArray(p.risks) && p.risks.length > 0 && (
                  <div className="text-[11px] text-sell/85 mt-1">⚠ {p.risks.join(' · ')}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      {Array.isArray(report.avoid) && report.avoid.length > 0 && (
        <div className="mt-4">
          <div className="text-[10.5px] text-sell uppercase tracking-[0.12em] font-bold mb-1.5">Agent khuyến nghị TRÁNH / CẮT</div>
          <div className="space-y-2">
            {report.avoid.map((p: any, i: number) => (
              <div key={i} className="bg-raise/60 border border-sell/25 rounded-xl p-3">
                <div className="flex items-baseline justify-between gap-2 flex-wrap">
                  <div>
                    <span className="text-[15px] font-bold text-hi font-display">{p.symbol}</span>
                    <span className="ml-2 text-[10px] font-mono text-acc">{p.sector}</span>
                    <span className="ml-2 text-[11px] text-warn">{starStr(p.conviction)}</span>
                  </div>
                  {p.stop != null && (
                    <div className="text-[11px] font-mono text-mid">Stop-out: <span className="text-sell">{fmtNum(p.stop)}</span></div>
                  )}
                </div>
                <div className="text-[12.5px] text-hi/90 mt-1 leading-snug">{p.reasoning}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {report.portfolio_note && (
        <div className="mt-4 text-[12.5px] text-acc bg-acc/[0.1] border border-acc/30 rounded-xl p-3 leading-snug">
          💼 <span className="font-semibold">Gợi ý phân bổ:</span> {report.portfolio_note}
        </div>
      )}
    </div>
  );
}

// ===================================================================
//  Pick cards  (Thẻ — default view): ladder + T+3 + sizing
// ===================================================================
function tPlusDays(date: string | undefined): { label: string; date: string; sub: string; state: 'now' | 'future' | 'sell' }[] {
  const base = date ? new Date(date) : new Date();
  const out: { label: string; date: string; sub: string; state: 'now' | 'future' | 'sell' }[] = [];
  for (let i = 0; i < 4; i++) {
    const d = new Date(base);
    d.setDate(base.getDate() + i);
    out.push({
      label: i === 0 ? 'T0' : `T+${i}`,
      date: `${d.getDate()}/${d.getMonth() + 1}`,
      sub: i === 0 ? 'Mua' : i === 3 ? 'Bán được' : '',
      state: i === 0 ? 'now' : i === 3 ? 'sell' : 'future',
    });
  }
  return out;
}

/**
 * "Đã vào lệnh" / "Theo dõi" — the app had no idea which recommendations you
 * had acted on, so it kept surfacing tomorrow what you bought today. Marking a
 * pick stores it in the operator's book (services/trading_state.py) with the
 * price shown on this card, which is the price the recommendation was made at.
 */
function PickActions({ p, kind, close }: { p: any; kind: 'BUY' | 'SELL'; close: number | null }) {
  const s = useTradingState();
  const sym = p.symbol;
  const held = isHeld(s, sym, kind);
  const watched = s.watchlist.includes(sym);

  return (
    <div className="flex items-center gap-2 pt-1">
      <button
        onClick={() => held
          ? tradingState.removePosition(sym, kind)
          : tradingState.addPosition({ symbol: sym, sector_code: pSecCode(p), side: kind, entry_price: close })}
        className={`flex-1 px-3 py-2 rounded-lg text-[12px] font-bold transition border ${
          held
            ? 'bg-buy/[0.14] border-buy/40 text-buy hover:bg-buy/[0.2]'
            : 'bg-raise border-line2 text-mid hover:text-hi hover:border-acc/40'}`}
      >
        {held ? '✓ Đã vào lệnh — bỏ đánh dấu' : 'Đã vào lệnh'}
      </button>
      {!held && (
        <button
          onClick={() => tradingState.toggleWatch(sym)}
          className={`px-3 py-2 rounded-lg text-[12px] font-semibold transition border ${
            watched
              ? 'bg-acc/[0.12] border-acc/40 text-acc'
              : 'bg-raise border-line2 text-mid hover:text-hi'}`}
        >
          {watched ? '★ Đang theo dõi' : '☆ Theo dõi'}
        </button>
      )}
    </div>
  );
}

function PickCard({ p, kind, alloc }: { p: any; kind: 'BUY' | 'SELL'; alloc: number }) {
  const [openNews, setOpenNews] = useState(false);
  const sym = p.symbol;
  const conv = convictionOf(p);
  const close = pClose(p);
  const rr = pRr(p);
  const bits: string[] = Array.isArray(p.technical_bits) ? p.technical_bits : [];
  const news: any[] = Array.isArray(p.news) ? p.news : [];
  const isBuy = kind === 'BUY';
  const entry = close;
  const risk = (isBuy && entry && p.stop) ? alloc * Math.abs(entry - p.stop) / entry : 0;
  // current dot position on the stop→target ladder (0 bottom = stop, 1 top = target)
  const ladderPos = (p.stop != null && p.target != null && close != null && p.target !== p.stop)
    ? clamp((close - p.stop) / (p.target - p.stop), 0, 1) : 0.5;

  return (
    <div className="rounded-2xl bg-panel border border-line p-[18px] animate-fade-up flex flex-col gap-3">
      {/* header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-display text-[22px] font-bold text-hi leading-none">{sym}</span>
            <span className="px-1.5 py-0.5 rounded-md bg-raise text-[10px] font-mono text-acc">{pSecCode(p)}</span>
          </div>
          <div className="text-[11px] text-lo mt-1">{p.sector_name}</div>
        </div>
        <div className="text-right">
          <ActionBadge action={p.action} />
          <div className="text-[12px] text-warn mt-1 tracking-tight" title={`Conviction ${conv}/5`}>{starStr(conv)}</div>
        </div>
      </div>

      {isBuy ? (
        <>
          {/* price ladder + T+3 */}
          <div className="flex gap-4">
            <div className="relative w-1.5 rounded-full bg-raise self-stretch min-h-[88px]">
              <span className="absolute -left-1 top-0 w-3.5 h-0.5 bg-buy rounded" />
              <span className="absolute -left-1 bottom-0 w-3.5 h-0.5 bg-sell rounded" />
              <span
                className="absolute -left-[5px] w-3 h-3 rounded-full bg-acc border-2 border-bg"
                style={{ bottom: `calc(${(ladderPos * 100).toFixed(0)}% - 6px)` }}
              />
            </div>
            <div className="flex-1 flex flex-col justify-between text-[11px] font-mono py-0.5">
              <div className="flex justify-between"><span className="text-buy">Target</span><span className="text-buy">{fmtNum(p.target)}{p.upside_pct != null && <span className="text-buy/70"> +{p.upside_pct.toFixed(1)}%</span>}</span></div>
              <div className="flex justify-between"><span className="text-mid">Hiện tại</span><span className="text-hi">{fmtNum(close)}</span></div>
              <div className="flex justify-between"><span className="text-sell">Stop</span><span className="text-sell">{fmtNum(p.stop)}{p.downside_pct != null && <span className="text-sell/70"> −{p.downside_pct.toFixed(1)}%</span>}</span></div>
            </div>
          </div>

          {/* T+3 schedule */}
          <div className="grid grid-cols-4 gap-1.5">
            {tPlusDays(undefined).map((d, i) => (
              <div
                key={i}
                className={`rounded-lg px-1.5 py-1.5 text-center border ${
                  d.state === 'now' ? 'border-acc/40 bg-acc/[0.1]'
                  : d.state === 'sell' ? 'border-buy/40 bg-buy/[0.1]'
                  : 'border-line bg-panel2'
                }`}
              >
                <div className={`text-[10px] font-bold font-mono ${d.state === 'now' ? 'text-acc' : d.state === 'sell' ? 'text-buy' : 'text-mid'}`}>{d.label}</div>
                <div className="text-[9px] text-lo font-mono">{d.date}</div>
                {d.sub && <div className={`text-[8.5px] mt-0.5 ${d.state === 'now' ? 'text-acc' : 'text-buy'}`}>{d.sub}</div>}
              </div>
            ))}
          </div>

          {/* sizing */}
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="rounded-lg bg-panel2 border border-line py-1.5">
              <div className="text-[9px] text-lo uppercase tracking-wider">R:R</div>
              <div className={`text-[13px] font-mono font-semibold ${(rr ?? 0) >= 2 ? 'text-buy' : 'text-warn'}`}>{rr != null ? rr.toFixed(1) : '—'}</div>
            </div>
            <div className="rounded-lg bg-panel2 border border-line py-1.5">
              <div className="text-[9px] text-lo uppercase tracking-wider">Phân bổ</div>
              <div className="text-[13px] font-mono font-semibold text-hi">{alloc >= 1 ? `${alloc.toFixed(0)}tr` : '—'}</div>
            </div>
            <div className="rounded-lg bg-panel2 border border-line py-1.5">
              <div className="text-[9px] text-lo uppercase tracking-wider">Rủi ro tối đa</div>
              <div className="text-[13px] font-mono font-semibold text-sell">{risk >= 0.01 ? `${risk.toFixed(1)}tr` : '—'}</div>
            </div>
          </div>
        </>
      ) : (
        <div className="rounded-xl bg-sell/[0.08] border border-sell/30 p-3 text-[12px] text-sell/90 leading-snug">
          ⚠ Cắt/tránh — stop-out <span className="font-mono font-semibold">{fmtNum(p.stop)}</span>
          {p.atr_pct != null && <> · ATR {p.atr_pct.toFixed(1)}%</>}
          {p.score != null && <> · score {p.score >= 0 ? '+' : ''}{p.score}</>}
        </div>
      )}

      {/* technical chips */}
      {bits.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {bits.map((b, bi) => (
            <span key={bi} className="px-1.5 py-0.5 rounded-md bg-raise text-[10px] font-mono text-mid">{b}</span>
          ))}
        </div>
      )}

      {/* thesis */}
      <div className={`text-[12px] leading-snug ${isBuy ? 'text-buy/90' : 'text-sell/90'}`}>{p.thesis}</div>

      {/* risks */}
      {Array.isArray(p.risks) && p.risks.length > 0 && (
        <div className="text-[11px] text-sell/80">⚠ {p.risks.join(' · ')}</div>
      )}

      {/* news drawer */}
      {news.length > 0 && (
        <div>
          <button
            onClick={() => setOpenNews((s) => !s)}
            className="text-[11px] text-mid hover:text-hi transition flex items-center gap-1"
          >
            <span>{openNews ? '▾' : '▸'}</span><span>Tin tức ({news.length})</span>
          </button>
          {openNews && (
            <ul className="mt-1.5 space-y-1.5">
              {news.map((n, ni) => (
                <li key={ni} className="text-[11px] leading-snug">
                  <a href={n.url} target="_blank" rel="noopener noreferrer" className="text-acc hover:underline">{n.title}</a>
                  <span className="ml-2 font-mono text-warn/80 text-[10px]">{n.source}</span>
                  {n.published && <span className="ml-2 text-lo text-[10px]">{String(n.published).slice(0, 16)}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <PickActions p={p} kind={kind} close={close} />
    </div>
  );
}

function PickCards({ picks, kind, capital }: { picks: any[]; kind: 'BUY' | 'SELL'; capital: number }) {
  const convSum = picks.reduce((a, p) => a + convictionOf(p), 0) || 1;
  const deployable = capital * 0.5;
  if (!picks.length) {
    return (
      <div className="rounded-2xl bg-panel border border-line p-6 text-center text-[13px] text-lo italic">
        Không có ngành nào ở trạng thái {kind === 'BUY' ? 'BUY/ACCUMULATE' : 'SELL'} hôm nay.
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {picks.map((p, i) => (
        <PickCard
          key={`${p.symbol}-${i}`}
          p={p}
          kind={kind}
          alloc={kind === 'BUY' ? deployable * convictionOf(p) / convSum : 0}
        />
      ))}
    </div>
  );
}

// ===================================================================
//  Pick table  (Bảng view) — UNCHANGED export, test-locked.
// ===================================================================
type PickKind = 'BUY' | 'SELL';

export function PickTable({ title, subtitle, kind, picks }: {
  title: string; subtitle: string; kind: PickKind; picks: any[];
}) {
  const [openNews, setOpenNews] = useState<Record<string, boolean>>({});

  if (!picks || picks.length === 0) {
    return (
      <div className="bg-panel border border-line rounded-2xl p-4">
        <div className="section-label">{title}</div>
        <div className="text-[11px] text-lo mt-0.5">{subtitle}</div>
        <div className="mt-3 text-sm text-lo italic">
          Không có ngành nào ở trạng thái {kind === 'BUY' ? 'BUY/ACCUMULATE' : 'SELL'} hôm nay.
        </div>
      </div>
    );
  }

  const headClr = kind === 'BUY' ? 'text-buy' : 'text-sell';
  const colCount = 7;

  return (
    <div className="bg-panel border border-line rounded-2xl overflow-hidden">
      <div className="p-3 border-b border-line">
        <div className="section-label">{title}</div>
        <div className={`text-[11px] mt-0.5 ${headClr}`}>{subtitle}</div>
      </div>
      <table className="w-full text-sm">
        <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
          <tr>
            <th className="p-2 text-left">Mã</th>
            <th className="p-2 text-left">Ngành</th>
            <th className="p-2 text-right">Giá</th>
            {kind === 'BUY' ? (
              <>
                <th className="p-2 text-right">Target</th>
                <th className="p-2 text-right">Stop</th>
                <th className="p-2 text-right">R:R</th>
              </>
            ) : (
              <>
                <th className="p-2 text-right">Stop-out</th>
                <th className="p-2 text-right">ATR%</th>
                <th className="p-2 text-right">Score</th>
              </>
            )}
            <th className="p-2 text-left">Tín hiệu / Lý do</th>
          </tr>
        </thead>
        <tbody>
          {picks.map((p, i) => {
            const sym = p.symbol;
            const news: any[] = Array.isArray(p.news) ? p.news : [];
            const isOpen = !!openNews[sym];
            const bits: string[] = Array.isArray(p.technical_bits) ? p.technical_bits : [];
            return (
              <Fragment key={`${sym}-${i}`}>
                <tr className="border-b border-line hover:bg-panel2/60 align-top">
                  <td className="p-2">
                    <div className="font-bold text-hi">{sym}</div>
                    <div className="mt-0.5"><ActionBadge action={p.action} /></div>
                  </td>
                  <td className="p-2 text-xs">
                    <span className="font-mono text-acc">{pSecCode(p)}</span>
                    <div className="text-lo text-[11px]">{p.sector_name}</div>
                  </td>
                  <td className="p-2 text-right font-mono text-hi">{fmtNum(pClose(p))}</td>

                  {kind === 'BUY' ? (
                    <>
                      <td className="p-2 text-right font-mono text-buy">
                        {fmtNum(p.target)}
                        {p.upside_pct != null && (<div className="text-[10px] text-buy/80">+{p.upside_pct.toFixed(1)}%</div>)}
                      </td>
                      <td className="p-2 text-right font-mono text-sell">
                        {fmtNum(p.stop)}
                        {p.downside_pct != null && (<div className="text-[10px] text-sell/80">−{p.downside_pct.toFixed(1)}%</div>)}
                      </td>
                      <td className={`p-2 text-right font-mono ${(pRr(p) ?? 0) >= 2 ? 'text-buy' : 'text-warn'}`}>
                        {pRr(p) != null ? pRr(p).toFixed(1) : '—'}
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="p-2 text-right font-mono text-sell">
                        {fmtNum(p.stop)}
                        {p.downside_pct != null && (<div className="text-[10px] text-sell/80">−{p.downside_pct.toFixed(1)}%</div>)}
                      </td>
                      <td className="p-2 text-right font-mono text-hi">{p.atr_pct != null ? p.atr_pct.toFixed(1) : '—'}</td>
                      <td className={`p-2 text-right font-mono ${p.score < 0 ? 'text-sell' : 'text-hi'}`}>
                        {p.score >= 0 ? '+' : ''}{p.score}
                      </td>
                    </>
                  )}

                  <td className="p-2">
                    {bits.length > 0 && (
                      <div className="flex flex-wrap gap-1 mb-1">
                        {bits.map((b, bi) => (
                          <span key={bi} className="px-1.5 py-0.5 rounded bg-raise text-[10px] text-mid font-mono">{b}</span>
                        ))}
                      </div>
                    )}
                    <div className={`text-[11px] leading-snug ${kind === 'BUY' ? 'text-buy/90' : 'text-sell/90'}`}>{p.thesis}</div>
                    {news.length > 0 && (
                      <button
                        onClick={() => setOpenNews((s) => ({ ...s, [sym]: !s[sym] }))}
                        className="mt-1 text-[11px] text-mid hover:text-hi transition flex items-center gap-1"
                      >
                        <span>{isOpen ? '▾' : '▸'}</span><span>Tin tức ({news.length})</span>
                      </button>
                    )}
                  </td>
                </tr>
                {isOpen && news.length > 0 && (
                  <tr className="border-b border-line bg-bg/40">
                    <td colSpan={colCount} className="px-3 py-2">
                      <ul className="space-y-1.5">
                        {news.map((n, ni) => (
                          <li key={ni} className="text-[11px] leading-snug">
                            <a href={n.url} target="_blank" rel="noopener noreferrer" className="text-acc hover:underline">{n.title}</a>
                            <span className="ml-2 font-mono text-warn/80 text-[10px]">{n.source}</span>
                            {n.published && <span className="ml-2 text-lo text-[10px]">{n.published.slice(0, 16)}</span>}
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ===================================================================
//  Send the daily report now (backlog step 6)
// ===================================================================
// The 17:00 job (§8) is the normal path. This is for the days you want the
// email before then — or after a Refresh changed the picks.
//
// The button disables itself while a run is in flight, but that is cosmetic:
// the backend is the real guard (report_runner returns already_running instead
// of starting a second subprocess), because two clicks must not send two mails.
function SendReportButton() {
  const [st, setSt] = useState<ReportStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  const stopPoll = () => {
    if (timer.current) { window.clearInterval(timer.current); timer.current = null; }
  };
  useEffect(() => stopPoll, []);

  const poll = () => {
    stopPoll();
    timer.current = window.setInterval(() => {
      stateApi.reportStatus()
        .then(({ data }) => {
          setSt(data);
          if (!data.running) { stopPoll(); setBusy(false); }
        })
        .catch(() => { stopPoll(); setBusy(false); });
    }, REFRESH_POLL_INTERVAL_MS);
  };

  const send = async () => {
    setBusy(true);
    try {
      const { data } = await stateApi.sendReport();
      setSt(data);
      poll();
    } catch (e: any) {
      setBusy(false);
      setSt({
        running: false, report_date: null, started_at: null, finished_at: null,
        ok: false, returncode: -1, tail: String(e?.message || e),
      });
    }
  };

  const running = busy || st?.running;
  const failed = st && !st.running && st.ok === false;
  const done = st && !st.running && st.ok === true;

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        onClick={send}
        disabled={!!running}
        title="Chạy generate_report.py và gửi email ngay, không đợi job 17:00"
        className="px-3.5 py-2 rounded-xl bg-warn/[0.13] text-warn border border-warn/30 hover:bg-warn/[0.2] disabled:opacity-50 text-[13px] font-semibold whitespace-nowrap"
      >
        {running
          ? `✉ Đang gửi…${st?.elapsed_sec ? ` ${Math.round(st.elapsed_sec)}s` : ''}`
          : '✉ Gửi báo cáo ngay'}
      </button>
      {done && <span className="text-[11px] text-buy font-mono">✓ Đã gửi</span>}
      {failed && (
        <span
          className="text-[11px] text-sell font-mono max-w-[280px] truncate cursor-help"
          title={st?.tail || ''}
        >
          ✗ Lỗi (exit {st?.returncode}) — di chuột để xem log
        </span>
      )}
    </div>
  );
}

// ===================================================================
//  Page
// ===================================================================
type PickView = 'cards' | 'table';

export default function DailyInsightPage() {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshStatus, setRefreshStatus] = useState<InsightRefreshStatus | null>(null);
  const [pickView, setPickView] = useState<PickView>('cards');
  const [capital, setCapital] = useState(100); // million VND (tr)
  const activeRunRef = useRef<string | null>(null);
  // The slider used to reset to 100tr on every F5. Seed it from the stored
  // value once it arrives, but never fight the user mid-session.
  const persistedCapital = useTradingState().capital_mn;
  const seededCapital = useRef(false);
  useEffect(() => {
    if (!seededCapital.current && persistedCapital) {
      seededCapital.current = true;
      setCapital(persistedCapital);
    }
  }, [persistedCapital]);

  const load = useCallback(() => {
    setLoading(true);
    setErr(null);
    return insightApi.daily()
      .then((r) => setData(r.data))
      .catch((e) => setErr(String(e?.message || e)))
      .finally(() => setLoading(false));
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setErr(null);
    setRefreshStatus(null);
    try {
      const startResp = await insightApi.refresh();
      const runId = startResp.data.run_id;
      activeRunRef.current = runId;

      const deadline = Date.now() + REFRESH_MAX_WAIT_MS;
      // eslint-disable-next-line no-constant-condition
      while (true) {
        if (activeRunRef.current !== runId) return; // superseded
        if (Date.now() > deadline) {
          setErr('Refresh vượt quá 20 phút — huỷ polling. Thử lại sau.');
          break;
        }
        try {
          const statusResp = await insightApi.refreshStatus(runId);
          const s = statusResp.data;
          setRefreshStatus(s);
          if (s.is_done) {
            if (s.payload) setData(s.payload);
            break;
          }
          if (s.is_error) {
            setErr(s.error || 'Refresh failed');
            break;
          }
        } catch (pollErr: any) {
          console.warn('[refresh] poll error', pollErr);
        }
        await new Promise((r) => setTimeout(r, REFRESH_POLL_INTERVAL_MS));
      }
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      if (activeRunRef.current !== null) setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const mc = data?.market_context;
  const genTime = data?.generated_at
    ? new Date(data.generated_at).toLocaleString('vi-VN', { hour12: false })
    : null;

  const buyPicks = Array.isArray(data?.picks)
    ? data.picks.filter((p: any) => p.action === 'BUY' || p.action === 'ACCUMULATE')
    : [];
  const sellPicks = Array.isArray(data?.picks)
    ? data.picks.filter((p: any) => p.action === 'SELL')
    : [];

  const elapsed = refreshStatus?.elapsed_sec ?? 0;
  const pct = refreshStatus?.progress?.pct ?? (refreshStatus?.stage === 'done' ? 100 : 5);
  const etaHint = refreshing ? `~${Math.max(0, Math.ceil((270 - elapsed) / 60))} phút còn lại (tổng ~4-5 phút)` : null;

  return (
    <div className="px-8 py-8 max-w-[1240px] mx-auto space-y-[22px]">
      {/* Header */}
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-[29px] font-bold text-hi tracking-tight">Daily Insight</h1>
          <p className="text-[13px] text-mid mt-0.5">
            Hôm nay nên <span className="text-buy font-semibold">MUA</span> mã nào,{' '}
            <span className="text-sell font-semibold">BÁN</span> mã nào — thực thi trong{' '}
            <span className="text-acc font-semibold">T+3</span>
          </p>
          {genTime && <p className="text-[11px] text-lo mt-1 font-mono">cập nhật {genTime}</p>}
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <div className="flex items-center gap-2">
          <SendReportButton />
          <button
            onClick={refresh}
            disabled={refreshing || loading}
            className={`px-4 py-2 rounded-lg text-[13px] font-semibold border transition flex items-center gap-2 ${
              refreshing ? 'bg-raise text-mid border-line cursor-wait'
              : 'text-bg border-transparent hover:brightness-110'
            }`}
            style={refreshing ? undefined : { background: 'linear-gradient(135deg,#46C9E6,#2C9C8E)' }}
            title="Publish ranking + rebuild HOSE universe + trader agent (~4-5 phút)"
          >
            <span className={refreshing ? 'inline-block animate-spin360' : ''}>↻</span>
            {refreshing ? STAGE_LABELS[refreshStatus?.stage || 'queued'] || 'Đang làm mới…' : 'Refresh'}
          </button>
          </div>
          {refreshing && refreshStatus && (
            <div className="w-60">
              <div className="flex items-baseline justify-between text-[10px] text-mid font-mono">
                <span>{refreshStatus.progress && refreshStatus.progress.total > 0
                  ? `${refreshStatus.progress.done}/${refreshStatus.progress.total}`
                  : refreshStatus.stage_label}</span>
                <span>{elapsed.toFixed(0)}s</span>
              </div>
              <div className="h-1 bg-raise rounded overflow-hidden mt-1">
                <div className="h-full bg-acc" style={{ width: `${pct}%`, transition: 'width .5s cubic-bezier(.4,0,.2,1)' }} />
              </div>
              {etaHint && <div className="text-[10px] text-lo mt-0.5">{etaHint}</div>}
            </div>
          )}
        </div>
      </header>

      {err && <div className="p-3 bg-sell/[0.12] border border-sell/40 text-sell rounded-xl text-sm">{err}</div>}

      {data?.refresh?.publish_error && (
        <div className="p-3 bg-warn/[0.12] border border-warn/40 text-warn rounded-xl text-xs">
          Publish signals lỗi: {data.refresh.publish_error}
        </div>
      )}

      {/* Data-quality banner */}
      {data?.freshness && data.freshness.is_valid === false && (
        <div
          className="p-3.5 rounded-xl border border-warn/50 text-warn"
          style={{ background: 'linear-gradient(135deg, rgba(245,177,61,.14), transparent)' }}
        >
          <div className="flex items-start gap-2.5">
            <span className="text-lg leading-none">⚠</span>
            <div className="flex-1 text-sm">
              <div className="font-semibold">DỮ LIỆU DEGRADED — picks vẫn hiển thị nhưng cần thận trọng</div>
              {Array.isArray(data.freshness.errors) && data.freshness.errors.length > 0 && (
                <ul className="mt-1 list-disc list-inside text-xs text-warn/90 space-y-0.5">
                  {data.freshness.errors.map((e: string, i: number) => (<li key={i}>{e}</li>))}
                </ul>
              )}
              <div className="mt-1 text-[11px] opacity-70 font-mono">
                as_of={data.freshness.as_of} · universe={data.freshness.universe_size} · pass={data.freshness.capability_pass_count} · fetch_fail={(data.freshness.ohlcv_fail_pct * 100).toFixed(0)}%
                {data.freshness.quality_reject_count != null && ` · lọc_thanh_khoản=${data.freshness.quality_reject_count}`}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Jump bar — review §C. The buy/sell list is what people open this page
          for, and it sits below the gauge, the spectrum and Minh's memo: on a
          laptop that is two full screens of scrolling before the first ticker.
          Native anchors + scroll-mt, no scroll listener. */}
      <nav className="sticky top-0 z-20 -mx-8 px-8 py-2.5 bg-bg/95 backdrop-blur border-b border-line flex gap-2">
        {[
          { href: '#pho-dong-tien', label: 'Phổ dòng tiền' },
          { href: '#danh-sach-hanh-dong', label: 'Danh sách hành động' },
        ].map((a) => (
          <a
            key={a.href}
            href={a.href}
            className="px-3 py-1.5 rounded-lg bg-panel2 border border-line text-[12.5px] font-semibold text-mid hover:text-hi hover:border-line2 transition"
          >
            {a.label}
          </a>
        ))}
      </nav>

      {/* Decision cockpit */}
      {mc && (
        <section className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-[22px]">
          <div className="rounded-2xl bg-panel border border-line p-[22px]">
            <div className="section-label mb-2">Regime thị trường</div>
            <RegimeGauge
              label={mc.regime?.label || 'chop'}
              confidence={mc.regime?.confidence ?? 0}
              buy={mc.buy_count ?? 0}
              sell={mc.sell_count ?? 0}
            />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-[22px]">
            <CountTile n={mc.buy_count ?? 0} label="Nên mua" tone="buy" />
            <CountTile n={mc.sell_count ?? 0} label="Nên bán" tone="sell" />
            <CountTile n={mc.stealth_count ?? 0} label="Tích luỹ ngầm" tone="warn" />
          </div>
        </section>
      )}

      {/* Sector flow spectrum */}
      {(buyPicks.length > 0 || sellPicks.length > 0 || (data?.deltas?.length ?? 0) > 0) && (
        <div id="pho-dong-tien" className="scroll-mt-16">
          <FlowSpectrum picks={[...buyPicks, ...sellPicks]} deltas={data?.deltas || []} />
        </div>
      )}

      {/* Trader Agent — Minh */}
      <AgentReport report={data?.agent_report} />

      {/* Action list toolbar */}
      <section id="danh-sach-hanh-dong" className="space-y-4 scroll-mt-16">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="section-label">Danh sách hành động</div>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-[12px] text-mid">
              <span>Vốn</span>
              {/* Persisted on release, not on every drag tick: the slider
                  fires onChange per pixel and each one would be a POST. */}
              <input
                type="range" min={50} max={500} step={10} value={capital}
                onChange={(e) => setCapital(Number(e.target.value))}
                onPointerUp={() => tradingState.setCapital(capital)}
                onKeyUp={() => tradingState.setCapital(capital)}
                className="accent-[#46C9E6] w-32"
              />
              <span className="font-mono text-hi w-12 text-right">{capital}tr</span>
            </label>
            <div className="flex rounded-lg bg-panel2 border border-line p-0.5">
              {(['cards', 'table'] as PickView[]).map((v) => (
                <button
                  key={v}
                  onClick={() => setPickView(v)}
                  className={`px-3 py-1 rounded-md text-[12px] font-medium transition ${
                    pickView === v ? 'bg-raise text-hi shadow-sm' : 'text-mid hover:text-hi'
                  }`}
                >
                  {v === 'cards' ? 'Thẻ' : 'Bảng'}
                </button>
              ))}
            </div>
          </div>
        </div>

        {pickView === 'cards' ? (
          <>
            <div className="section-label text-buy/80">⚡ Nên MUA — Swing 3-5 phiên</div>
            <PickCards picks={buyPicks} kind="BUY" capital={capital} />
            <div className="section-label text-sell/80 mt-2">⚠ Nên BÁN / TRÁNH — stop-out levels</div>
            <PickCards picks={sellPicks} kind="SELL" capital={capital} />
          </>
        ) : (
          <>
            <PickTable title="Nên MUA (T+)" subtitle="⚡ Swing 3-5 phiên — mua tại giá / limit, tôn trọng stop" kind="BUY" picks={buyPicks} />
            <PickTable title="Nên BÁN / TRÁNH" subtitle="⚠ Stop-out levels — thoát nếu đang nắm, tránh mua mới" kind="SELL" picks={sellPicks} />
          </>
        )}
      </section>

      <div className="text-[10.5px] text-lo leading-relaxed pt-2">
        * Đơn vị giá = nghìn VND. R:R = reward/risk, nên ≥ 1.5. Tín hiệu: RSI / MACD / SMA / ADX / Volume / ATR.
        News kết hợp KBS + Google News (CafeF, VnExpress, …). Không phải khuyến nghị đầu tư.
      </div>
    </div>
  );
}
