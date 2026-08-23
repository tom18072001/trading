/**
 * §18.4/20 kill-switch + the operator's own book.
 *
 * Before this, `TRADING_HALT` was an env var: stopping the 17:00 publish meant
 * editing .env and restarting the process. And the app had no idea which picks
 * you had actually taken, so the "Vị thế đang mở" table below is what the model
 * *suggests* holding, not what you hold — two different things that looked the
 * same. This adds the second one.
 */
import { useState } from 'react';
import { tradingState, useTradingState } from '../lib/tradingState';

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

export function MyBookPanel() {
  const s = useTradingState();
  const [sym, setSym] = useState('');

  const add = async () => {
    const v = sym.trim().toUpperCase();
    if (!v) return;
    setSym('');
    await tradingState.addPosition({ symbol: v });
  };

  return (
    <section className="rounded-2xl bg-panel border border-line overflow-hidden">
      <div className="px-4 py-3 border-b border-line flex items-center justify-between gap-3">
        <div className="section-label">Danh mục của tôi — đã vào lệnh thật</div>
        <div className="flex gap-2">
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
              <th className="p-2.5 text-right">Ngày</th>
              <th className="p-2.5 text-right"></th>
            </tr>
          </thead>
          <tbody>
            {s.positions.map((p) => (
              <tr key={`${p.symbol}-${p.side}`} className="border-b border-line hover:bg-panel2/60">
                <td className="p-2.5 font-display font-bold text-hi">{p.symbol}</td>
                <td className="p-2.5 font-mono text-[11px] text-mid">{p.sector_code || '—'}</td>
                <td className={`p-2.5 font-semibold ${p.side === 'BUY' ? 'text-buy' : 'text-sell'}`}>{p.side}</td>
                <td className="p-2.5 text-right font-mono tabular text-hi">
                  {p.entry_price != null ? p.entry_price.toFixed(2) : '—'}
                </td>
                <td className="p-2.5 text-right font-mono tabular text-lo">{p.opened_at}</td>
                <td className="p-2.5 text-right">
                  <button
                    onClick={() => tradingState.removePosition(p.symbol, p.side)}
                    className="text-[11.5px] text-lo hover:text-sell transition">
                    Đã thoát
                  </button>
                </td>
              </tr>
            ))}
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
