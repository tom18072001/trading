/**
 * §18.4/20 kill-switch + the operator's own book.
 *
 * Before this, `TRADING_HALT` was an env var: stopping the 17:00 publish meant
 * editing .env and restarting the process. And the app had no idea which picks
 * you had actually taken, so the "Vị thế đang mở" table below is what the model
 * *suggests* holding, not what you hold — two different things that looked the
 * same. This adds the second one.
 */
import { useEffect, useState } from 'react';
import { stateApi, type PnlResponse, type Position, type RealisedResponse } from '../api/client';
import { tradingState, useTradingState } from '../lib/tradingState';

/** Compact VND. The book is in đồng; 12.400.000 in a table cell is unreadable. */
function fmtVnd(v: number | null | undefined) {
  if (v == null || !Number.isFinite(v)) return '—';
  const a = Math.abs(v), sign = v < 0 ? '-' : '';
  if (a >= 1e9) return `${sign}${(a / 1e9).toFixed(2)} tỷ`;
  if (a >= 1e6) return `${sign}${(a / 1e6).toFixed(1)} tr`;
  if (a >= 1e3) return `${sign}${(a / 1e3).toFixed(0)}k`;
  return `${sign}${a.toFixed(0)}`;
}

export function KillSwitchPanel() {
  const s = useTradingState();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const toggle = async () => {
    setBusy(true);
    try {
      await tradingState.setHalt(!s.halt, reason);
      setReason('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={`rounded-2xl border p-[18px] ${
      s.halt_effective ? 'bg-sell/[0.08] border-sell/40' : 'bg-panel border-line'}`}>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="section-label">Công tắc dừng giao dịch</div>
          <p className="text-[12.5px] text-mid mt-1 max-w-[560px] leading-snug">
            Khi bật, job 17:00 không phát tín hiệu ACCUMULATE/BUY mới — mọi ngành
            thành HOLD. Vị thế đang nắm không bị đóng; đây là phanh cho lệnh mới.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!s.halt && (
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Lý do (tuỳ chọn)"
              className="bg-panel2 border border-line rounded-lg px-3 py-2 text-[12.5px] text-hi w-[200px]"
            />
          )}
          <button
            onClick={toggle}
            disabled={busy || (s.halt_env && !s.halt)}
            title={s.halt_env && !s.halt
              ? 'TRADING_HALT đang bật bằng biến môi trường — sửa .env để tắt'
              : undefined}
            className={`px-4 py-2 rounded-lg text-[12.5px] font-bold transition disabled:opacity-40 ${
              s.halt
                ? 'bg-buy/[0.15] border border-buy/40 text-buy hover:bg-buy/[0.22]'
                : 'bg-sell/[0.15] border border-sell/40 text-sell hover:bg-sell/[0.22]'}`}
          >
            {busy ? '…' : s.halt ? '✓ Cho phép giao dịch lại' : '⏸ Dừng phát tín hiệu mua'}
          </button>
        </div>
      </div>
      {s.halt_effective && (
        <div className="mt-3 pt-3 border-t border-sell/25 text-[12px] font-mono text-sell/85">
          ĐANG DỪNG
          {s.halt_set_at && <> · từ {s.halt_set_at.replace('T', ' ').slice(0, 16)}</>}
          {s.halt_reason && <> · {s.halt_reason}</>}
          {s.halt_env && <> · nguồn: biến môi trường TRADING_HALT</>}
        </div>
      )}
    </section>
  );
}

/** One editable cell. Commits on blur or Enter, reverts on Escape.
 *
 *  Not a form: a book row has two editable numbers, and a save button per row
 *  is more chrome than the edit is worth. Commit-on-blur means the value you
 *  can see is the value on disk. */
function NumCell({ value, onCommit, align = 'right', width = 'w-[86px]', placeholder = '—' }: {
  value: number | null; onCommit: (v: number | null) => void;
  align?: 'right' | 'left'; width?: string; placeholder?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? (value != null ? String(value) : '');

  const commit = () => {
    if (draft === null) return;
    const t = draft.trim();
    setDraft(null);
    // -1 is the API's "clear this field"; an empty box means the same thing.
    const next = t === '' ? -1 : Number(t);
    if (!Number.isFinite(next)) return;                    // typo: revert, don't save
    if (next === value || (t === '' && value == null)) return;
    onCommit(next);
  };

  return (
    <input
      value={shown}
      placeholder={placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
        if (e.key === 'Escape') { setDraft(null); (e.target as HTMLInputElement).blur(); }
      }}
      className={`bg-transparent border border-transparent hover:border-line2 focus:border-acc/50
        focus:bg-panel2 rounded-md px-1.5 py-0.5 font-mono tabular text-hi outline-none
        transition ${width} text-${align}`}
    />
  );
}

/** Closed trades. Hidden until there is at least one — an empty ledger is noise.
 *
 *  Totals come from the endpoint rather than being summed here: win rate and
 *  average are one piece of arithmetic, and a second copy in TypeScript is a
 *  second thing to keep in step with the cost model.
 */
export function ClosedBookPanel() {
  const s = useTradingState();
  const [r, setR] = useState<RealisedResponse | null>(null);

  useEffect(() => {
    stateApi.realised().then((x) => setR(x.data)).catch(() => setR(null));
  }, [s.closed]);

  if (!r || r.count === 0) return null;
  const up = (r.avg_pnl_pct ?? 0) >= 0;

  return (
    <section className="rounded-2xl bg-panel border border-line overflow-hidden">
      <div className="px-4 py-3 border-b border-line flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="section-label">Lệnh đã đóng — lãi/lỗ thực hiện</div>
          <p className="text-[11px] text-lo mt-0.5">
            Đã trừ phí {'≈'}0,40% khứ hồi (phí môi giới 2 chiều + thuế bán 0,1%),
            cùng mức backtest tính — §18.2/10.
            {r.priced < r.count && (
              <span className="text-warn"> · chỉ {r.priced}/{r.count} lệnh có khối lượng
                nên ra được số tiền</span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-5 text-right">
          {r.win_rate != null && (
            <div>
              <div className="section-label">Tỷ lệ thắng</div>
              <div className="font-mono tabular font-bold text-[17px] text-hi">
                {(r.win_rate * 100).toFixed(0)}%
                <span className="text-[12px] text-mid ml-1">({r.count} lệnh)</span>
              </div>
            </div>
          )}
          {r.avg_pnl_pct != null && (
            <div>
              <div className="section-label">Trung bình / lệnh</div>
              <div className={`font-mono tabular font-bold text-[17px] ${up ? 'text-buy' : 'text-sell'}`}>
                {up ? '+' : ''}{r.avg_pnl_pct.toFixed(2)}%
                {r.total_pnl_vnd != null && (
                  <span className="text-[12px] text-mid ml-1.5">({fmtVnd(r.total_pnl_vnd)})</span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      <table className="w-full text-[13px]">
        <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
          <tr>
            <th className="p-2.5 text-left">Mã</th>
            <th className="p-2.5 text-left">Chiều</th>
            <th className="p-2.5 text-right">Giá vào</th>
            <th className="p-2.5 text-right">Giá bán</th>
            <th className="p-2.5 text-right">KL</th>
            <th className="p-2.5 text-right">Phí</th>
            <th className="p-2.5 text-right">Lãi/lỗ ròng</th>
            <th className="p-2.5 text-right">Mở</th>
            <th className="p-2.5 text-right">Đóng</th>
          </tr>
        </thead>
        <tbody>
          {[...r.trades].reverse().map((t, i) => {
            const win = (t.pnl_pct ?? 0) >= 0;
            return (
              <tr key={`${t.symbol}-${t.closed_at}-${i}`} className="border-b border-line hover:bg-panel2/60">
                <td className="p-2.5 font-display font-bold text-hi">{t.symbol}</td>
                <td className={`p-2.5 font-semibold ${t.side === 'BUY' ? 'text-buy' : 'text-sell'}`}>{t.side}</td>
                <td className="p-2.5 text-right font-mono tabular text-mid">
                  {t.entry_price != null ? t.entry_price.toFixed(2) : '—'}
                </td>
                <td className="p-2.5 text-right font-mono tabular text-hi">{t.exit_price.toFixed(2)}</td>
                <td className="p-2.5 text-right font-mono tabular text-mid">{t.qty ?? '—'}</td>
                <td className="p-2.5 text-right font-mono tabular text-lo">{fmtVnd(t.fees_vnd)}</td>
                <td className={`p-2.5 text-right font-mono tabular font-semibold ${
                  t.pnl_pct == null ? 'text-lo' : win ? 'text-buy' : 'text-sell'}`}>
                  {t.pnl_pct != null ? `${win ? '+' : ''}${t.pnl_pct.toFixed(2)}%` : '—'}
                  {t.pnl_vnd != null && (
                    <div className="text-[10.5px] font-normal opacity-75">{fmtVnd(t.pnl_vnd)}</div>
                  )}
                </td>
                <td className="p-2.5 text-right font-mono tabular text-lo">{t.opened_at}</td>
                <td className="p-2.5 text-right font-mono tabular text-lo">{t.closed_at}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

/** Ask for the exit price, then close.
 *
 *  Not NumCell: there, an empty box means "clear this field" (-1), which for a
 *  sale would mean booking a trade at no price. Here empty must mean cancel.
 *
 *  Prefilled with the last close — the nearest thing the app knows to your fill.
 *  It is NOT your fill, which is why this is an editable box and not a one-click
 *  "bán ở giá hiện tại": a wrong exit price is a permanently wrong realised P&L.
 */
function ExitCell({ suggested, onCommit, onCancel }: {
  suggested: number | null;
  onCommit: (v: number) => void;
  onCancel: () => void;
}) {
  const [v, setV] = useState(suggested != null ? String(suggested) : '');
  const commit = () => {
    const n = Number(v.trim());
    if (Number.isFinite(n) && n > 0) onCommit(n);
    else onCancel();
  };
  return (
    <input
      autoFocus
      value={v}
      onChange={(e) => setV(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
        if (e.key === 'Escape') { setV(''); onCancel(); }
      }}
      placeholder="Giá bán"
      title="Giá bán thực tế — Enter để ghi nhận, Esc để huỷ"
      className="bg-panel2 border border-sell/40 rounded-md px-1.5 py-0.5 font-mono tabular
        text-hi outline-none w-[96px] text-right"
    />
  );
}

/** The price path since entry, with the entry / stop / target levels drawn on.
 *
 *  Hand-rolled SVG, not recharts: recharts lives in a 346 kB chunk that only
 *  loads when you open the Backtest tab (§22.3), and a 60x20 polyline is not
 *  worth pulling it onto every page that shows the book.
 */
function Spark({ path, entry, stop, target }: {
  path: { date: string; close: number }[];
  entry: number | null; stop: number | null; target: number | null;
}) {
  if (path.length < 2) return <span className="text-lo text-[11px]">—</span>;
  const W = 64, H = 22;
  // Scale to the levels too, not just the closes: a chart whose stop line sits
  // off-canvas is exactly the chart you cannot read at a glance.
  const vals = [...path.map((p) => p.close),
                ...[entry, stop, target].filter((v): v is number => v != null)];
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || 1;
  const y = (v: number) => H - ((v - lo) / span) * H;
  const pts = path.map((p, i) => `${(i / (path.length - 1)) * W},${y(p.close).toFixed(1)}`).join(' ');
  const rising = path[path.length - 1].close >= path[0].close;

  return (
    <svg width={W} height={H} className="inline-block align-middle overflow-visible">
      {stop != null && <line x1="0" x2={W} y1={y(stop)} y2={y(stop)}
        className="stroke-sell/40" strokeWidth="1" strokeDasharray="2 2" />}
      {target != null && <line x1="0" x2={W} y1={y(target)} y2={y(target)}
        className="stroke-buy/40" strokeWidth="1" strokeDasharray="2 2" />}
      {entry != null && <line x1="0" x2={W} y1={y(entry)} y2={y(entry)}
        className="stroke-line2" strokeWidth="1" />}
      <polyline points={pts} fill="none" strokeWidth="1.4"
        className={rising ? 'stroke-buy' : 'stroke-sell'} />
    </svg>
  );
}

export function MyBookPanel() {
  const s = useTradingState();
  const [sym, setSym] = useState('');
  const [pnl, setPnl] = useState<PnlResponse | null>(null);
  const [closing, setClosing] = useState<string | null>(null);

  // Re-mark whenever the book changes — an edited entry price with a stale P&L
  // beside it is worse than no P&L.
  useEffect(() => {
    stateApi.pnl().then((r) => setPnl(r.data)).catch(() => setPnl(null));
  }, [s.positions]);

  const add = async () => {
    const v = sym.trim().toUpperCase();
    if (!v) return;
    setSym('');
    await tradingState.addPosition({ symbol: v });
  };

  const marked = new Map((pnl?.positions ?? []).map((p) => [`${p.symbol}-${p.side}`, p]));
  const patch = (p: Position, k: 'entry_price' | 'qty' | 'stop' | 'target') => (v: number | null) =>
    tradingState.updatePosition(p.symbol, p.side, { [k]: v });

  return (
    <section className="rounded-2xl bg-panel border border-line overflow-hidden">
      <div className="px-4 py-3 border-b border-line flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="section-label">Danh mục của tôi — đã vào lệnh thật</div>
          {pnl && pnl.count > 0 && (
            <div className="text-[11px] text-lo mt-0.5">
              Định giá theo giá đóng cửa {pnl.as_of ?? 'chưa có'}
              {pnl.priced < pnl.count && (
                <span className="text-warn"> · chỉ {pnl.priced}/{pnl.count} mã tính được lãi/lỗ
                  (thiếu giá vào hoặc khối lượng)</span>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          {pnl?.total_pnl_pct != null && (
            <div className="text-right">
              <div className="section-label">Lãi/lỗ tạm tính</div>
              <div className={`font-mono tabular font-bold text-[17px] ${
                pnl.total_pnl_pct >= 0 ? 'text-buy' : 'text-sell'}`}>
                {pnl.total_pnl_pct >= 0 ? '+' : ''}{pnl.total_pnl_pct.toFixed(2)}%
                <span className="text-[12px] text-mid ml-1.5">
                  ({fmtVnd(pnl.total_pnl_vnd)})
                </span>
              </div>
            </div>
          )}
          <input
            value={sym}
            onChange={(e) => setSym(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && add()}
            placeholder="Mã CK"
            maxLength={8}
            className="bg-panel2 border border-line rounded-lg px-3 py-1.5 text-[12.5px] text-hi font-mono w-[110px] uppercase"
          />
          <button onClick={add}
            className="px-3 py-1.5 rounded-lg bg-raise border border-line2 text-[12.5px] font-semibold text-hi hover:border-acc/40 transition">
            + Thêm
          </button>
        </div>
      </div>

      {s.positions.length === 0 ? (
        <div className="p-8 text-center text-mid text-[13px]">
          Chưa đánh dấu mã nào. Bấm <span className="text-acc font-semibold">“Đã vào lệnh”</span> trên
          thẻ khuyến nghị ở Daily Insight, hoặc thêm tay ở đây.
        </div>
      ) : (
        <table className="w-full text-[13px]">
          <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
            <tr>
              <th className="p-2.5 text-left">Mã</th>
              <th className="p-2.5 text-left">Ngành</th>
              <th className="p-2.5 text-left">Chiều</th>
              <th className="p-2.5 text-right">Giá vào</th>
              <th className="p-2.5 text-right">KL</th>
              <th className="p-2.5 text-right">Giá hiện tại</th>
              <th className="p-2.5 text-right">Lãi/lỗ</th>
              <th className="p-2.5 text-right" title="Cắt lỗ / chốt lời đã đặt khi vào lệnh">Stop / Target</th>
              <th className="p-2.5 text-center" title="Đường giá từ ngày vào lệnh">Diễn biến</th>
              <th className="p-2.5 text-right">Giá trị</th>
              <th className="p-2.5 text-right">Ngày</th>
              <th className="p-2.5 text-right"></th>
            </tr>
          </thead>
          <tbody>
            {s.positions.map((p) => {
              const key = `${p.symbol}-${p.side}`;
              const m = marked.get(key);
              const up = (m?.pnl_pct ?? 0) >= 0;
              // A stop that was breached and recovered is still a breach. The
              // row says so until you act on it — that is the whole point of
              // keeping stop/target on the book.
              const flag = m?.hit_stop ? 'border-l-2 border-l-sell'
                : m?.hit_target ? 'border-l-2 border-l-buy' : '';
              return (
                <tr key={key} className={`border-b border-line hover:bg-panel2/60 ${flag}`}>
                  <td className="p-2.5 font-display font-bold text-hi">{p.symbol}</td>
                  <td className="p-2.5 font-mono text-[11px] text-mid">{p.sector_code || '—'}</td>
                  <td className={`p-2.5 font-semibold ${p.side === 'BUY' ? 'text-buy' : 'text-sell'}`}>{p.side}</td>
                  <td className="p-1.5 text-right">
                    <NumCell value={p.entry_price} onCommit={patch(p, 'entry_price')} />
                  </td>
                  <td className="p-1.5 text-right">
                    <NumCell value={p.qty} onCommit={patch(p, 'qty')} placeholder="KL" />
                  </td>
                  <td className="p-2.5 text-right font-mono tabular text-mid">
                    {m?.last != null ? m.last.toFixed(2) : '—'}
                  </td>
                  <td className={`p-2.5 text-right font-mono tabular font-semibold ${
                    m?.pnl_pct == null ? 'text-lo' : up ? 'text-buy' : 'text-sell'}`}>
                    {m?.pnl_pct != null ? `${up ? '+' : ''}${m.pnl_pct.toFixed(2)}%` : '—'}
                    {m?.pnl_vnd != null && (
                      <div className="text-[10.5px] font-normal opacity-75">{fmtVnd(m.pnl_vnd)}</div>
                    )}
                  </td>
                  <td className="p-1.5 text-right whitespace-nowrap">
                    <div className="flex items-center justify-end gap-1">
                      <NumCell value={p.stop} onCommit={patch(p, 'stop')}
                        width="w-[62px]" placeholder="stop" />
                      <span className="text-lo text-[11px]">/</span>
                      <NumCell value={p.target} onCommit={patch(p, 'target')}
                        width="w-[62px]" placeholder="tgt" />
                    </div>
                    {(m?.hit_stop || m?.hit_target) && (
                      <div className={`text-[10px] font-semibold pr-1.5 ${
                        m.hit_stop ? 'text-sell' : 'text-buy'}`}>
                        {m.hit_stop ? '⚠ đã thủng stop' : '✓ đã chạm target'}
                      </div>
                    )}
                  </td>
                  <td className="p-2.5 text-center">
                    <Spark path={m?.path ?? []} entry={p.entry_price}
                      stop={p.stop} target={p.target} />
                  </td>
                  <td className="p-2.5 text-right font-mono tabular text-mid">
                    {m?.value != null ? fmtVnd(m.value) : '—'}
                  </td>
                  <td className="p-2.5 text-right font-mono tabular text-lo">
                    {p.opened_at}
                    <div className="text-[10px] text-lo/70">
                      {m?.sessions_held != null && <>{m.sessions_held} phiên</>}
                      {m?.sellable_on && m.sellable_on > (m.path.at(-1)?.date ?? '')
                        && <> · bán từ {m.sellable_on.slice(5)}</>}
                    </div>
                  </td>
                  <td className="p-1.5 text-right whitespace-nowrap">
                    {closing === key ? (
                      <ExitCell
                        suggested={m?.last ?? p.entry_price}
                        onCancel={() => setClosing(null)}
                        onCommit={async (v) => {
                          setClosing(null);
                          await tradingState.closePosition(p.symbol, p.side, v);
                        }}
                      />
                    ) : (
                      <>
                        <button
                          onClick={() => setClosing(key)}
                          title="Ghi nhận đã bán — giữ lại lãi/lỗ thực hiện"
                          className="text-[11.5px] text-lo hover:text-hi transition">
                          Đã bán
                        </button>
                        <button
                          onClick={() => tradingState.removePosition(p.symbol, p.side)}
                          title="Bấm nhầm — xoá hẳn, không ghi vào lịch sử"
                          className="text-[11.5px] text-lo/60 hover:text-sell transition ml-2.5">
                          ✕
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {s.watchlist.length > 0 && (
        <div className="px-4 py-3 border-t border-line flex items-center gap-2 flex-wrap">
          <span className="section-label">Đang theo dõi</span>
          {s.watchlist.map((w) => (
            <button key={w} onClick={() => tradingState.toggleWatch(w)}
              title="Bỏ theo dõi"
              className="px-2 py-1 rounded-md bg-raise border border-line text-[11.5px] font-mono text-mid hover:text-sell hover:border-sell/40 transition">
              {w} ×
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
