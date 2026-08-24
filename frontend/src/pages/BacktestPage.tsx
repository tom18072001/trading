import { useEffect, useState } from 'react';
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import {
  sectorsApi,
  type BacktestResult, type BacktestRunRow, type BacktestStrategy,
} from '../api/client';

// The selector is the whole point of backlog step 5. All three strategies have
// existed in services/backtest_service.py since 2026-08-22 (P0-4), but
// BacktestRequest carried no `strategy`, so every run the UI could trigger was
// the default one — the most valuable filter in the app, unreachable.
const STRATEGIES: { key: BacktestStrategy; label: string; hint: string }[] = [
  { key: 'signals', label: 'Tín hiệu đã phát', hint: 'Chạy lại đúng ACCUMULATE/BUY hệ thống đã công bố' },
  { key: 'flow_z', label: 'Flow Z20 (so với chính nó)', hint: 'Đối chứng: top-N theo flow_z20 — ngành đang được mua bất thường so với lịch sử của chính nó' },
  { key: 'flow_raw', label: 'Flow thô (cũ)', hint: 'Hành vi trước 2026-08-22 — xếp theo VND thô, thực chất là "giữ ngành to nhất"' },
];

const STRATEGY_LABEL: Record<BacktestStrategy, string> = {
  signals: 'Tín hiệu đã phát', flow_z: 'Flow Z20', flow_raw: 'Flow thô',
};

const vnd = (n: number) => n.toLocaleString('vi-VN', { maximumFractionDigits: 0 });

export default function BacktestPage() {
  const [name, setName] = useState('rotation_default');
  // Defaulted to 2025 until 2026-08-23, which guaranteed the "Tín hiệu đã phát"
  // option silently fell back: sector_signals only starts 2026-04-09, so the
  // default range had zero of them and the page opened on a strategy it could
  // not run. Start where the signals do.
  const [start, setStart] = useState('2026-04-09');
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const [capital, setCapital] = useState(100_000_000);
  const [strategy, setStrategy] = useState<BacktestStrategy>('signals');
  const [feeBps, setFeeBps] = useState(15);
  const [sellTaxBps, setSellTaxBps] = useState(10);
  const [settlementLag, setSettlementLag] = useState(2);
  const [result, setResult] = useState<BacktestResult | null>(null);
  // Compare = pin the run you just looked at, then run another. Kept in page
  // state rather than re-fetched: the stored runs table has no equity curve,
  // and the only comparison a trader actually makes is "this vs. the last one".
  const [pinned, setPinned] = useState<BacktestResult | null>(null);
  const [history, setHistory] = useState<BacktestRunRow[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadHistory = () => {
    sectorsApi.listBacktests(10).then((r) => setHistory(r.data)).catch(() => {});
  };
  useEffect(loadHistory, []);

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const r = await sectorsApi.runBacktest({
        name, start_date: start, end_date: end, initial_capital: capital,
        strategy, fee_bps: feeBps, sell_tax_bps: sellTaxBps,
        settlement_lag: settlementLag,
      });
      setResult(r.data);
      loadHistory();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'failed');
    } finally {
      setRunning(false);
    }
  };

  const inputCls =
    'w-full bg-panel2 border border-line rounded-lg px-3 py-2 text-[13px] text-hi font-mono';

  return (
    <div className="px-8 py-8 max-w-[1240px] mx-auto space-y-[22px]">
      <header>
        <h1 className="font-display text-[29px] font-bold text-hi tracking-tight">Backtest</h1>
        <p className="text-[13px] text-mid mt-1">
          Mô phỏng luân chuyển ngành — chọn chiến lược, nhập phí, so với VNINDEX
        </p>
      </header>

      <section className="rounded-2xl bg-panel border border-line p-5 space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <label className="space-y-1">
            <div className="section-label">Tên lần chạy</div>
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="space-y-1">
            <div className="section-label">Từ ngày</div>
            <input type="date" className={inputCls} value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="space-y-1">
            <div className="section-label">Đến ngày</div>
            <input type="date" className={inputCls} value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
          <label className="space-y-1">
            <div className="section-label">Vốn ban đầu (VND)</div>
            <input
              type="number" className={inputCls}
              value={capital} onChange={(e) => setCapital(Number(e.target.value))}
            />
          </label>
        </div>

        <div className="space-y-1.5">
          <div className="section-label">Chiến lược mô phỏng</div>
          <div className="grid md:grid-cols-3 gap-2">
            {STRATEGIES.map((s) => {
              const on = strategy === s.key;
              return (
                <button
                  key={s.key}
                  onClick={() => setStrategy(s.key)}
                  className={`text-left rounded-xl border px-3 py-2.5 transition ${
                    on ? 'bg-acc/[0.12] border-acc/40' : 'bg-panel2 border-line hover:border-line2'
                  }`}
                >
                  <div className={`text-[13px] font-semibold ${on ? 'text-acc' : 'text-hi'}`}>{s.label}</div>
                  <div className="text-[10.5px] text-lo leading-snug mt-0.5">{s.hint}</div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 items-end">
          <label className="space-y-1">
            <div className="section-label">Phí môi giới (bps/lượt)</div>
            <input type="number" min={0} max={500} className={inputCls}
              value={feeBps} onChange={(e) => setFeeBps(Number(e.target.value))} />
          </label>
          <label className="space-y-1">
            <div className="section-label">Thuế bán (bps)</div>
            <input type="number" min={0} max={500} className={inputCls}
              value={sellTaxBps} onChange={(e) => setSellTaxBps(Number(e.target.value))} />
          </label>
          <label className="space-y-1">
            <div className="section-label">Thanh toán T+</div>
            <input type="number" min={0} max={10} className={inputCls}
              value={settlementLag} onChange={(e) => setSettlementLag(Number(e.target.value))} />
          </label>
          <div className="flex justify-end gap-2">
            {result && (
              <button
                onClick={() => setPinned(result)}
                className="px-3 py-2 rounded-xl bg-panel2 text-mid border border-line hover:text-hi text-[12.5px] font-semibold"
                title="Ghim kết quả này để so với lần chạy sau"
              >
                Ghim để so sánh
              </button>
            )}
            <button
              onClick={run}
              disabled={running}
              className="px-5 py-2 rounded-xl bg-acc/[0.13] text-acc border border-acc/30 hover:bg-acc/[0.2] disabled:opacity-50 text-[13px] font-semibold"
            >
              {running ? 'Đang chạy…' : 'Chạy backtest'}
            </button>
          </div>
        </div>
        <p className="text-[10.5px] text-lo leading-snug">
          Trượt giá (max 0,3% / 0,5×ATR) và biên độ ±7% HOSE là cấu trúc thị trường, không sửa được ở đây —
          chỉ phí, thuế và chu kỳ thanh toán là thoả thuận với môi giới.
        </p>
      </section>

      {error && (
        <div className="p-3 bg-sell/[0.12] border border-sell/40 text-sell rounded-xl text-sm">
          Lỗi: {error}
        </div>
      )}

      {result && (
        <div className="space-y-[22px]">
          {result.strategy_source !== strategy && (
            <div className="p-3 bg-warn/[0.10] border border-warn/40 text-warn rounded-xl text-[12.5px]">
              Đã chọn <b>{STRATEGY_LABEL[strategy]}</b> nhưng khoảng ngày này không có tín hiệu nào đã
              công bố — hệ thống tự chuyển sang <b>{STRATEGY_LABEL[result.strategy_source]}</b>.
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Metric label="Tổng lợi suất" value={`${result.total_return_pct.toFixed(2)}%`} positive={result.total_return_pct >= 0} />
            <Metric
              label={result.benchmark_source === 'vnindex' ? 'Benchmark (VNINDEX)' : 'Benchmark (TB ngành)'}
              value={`${result.benchmark_return_pct.toFixed(2)}%`}
              note={result.benchmark_source === 'vnindex' ? undefined : 'thiếu VNINDEX — dùng trung bình 15 ngành'}
            />
            {/* 2026-08-23 (backlog step 5): the note here used to say T+2, fees,
                tax and the price band were NOT modelled. That was written from
                CLAUDE.md §18.6's open-BLOCKER list without reading the service,
                which has modelled all four since 2026-08-22 and returns the
                figures below as proof. A caveat that is false is worse than no
                caveat: it teaches the reader to discount a number that is
                already net. */}
            <Metric
              label="Sharpe (ròng)"
              value={Math.abs(result.sharpe_ratio) > 5 ? 'n/a' : result.sharpe_ratio.toFixed(2)}
              positive={Math.abs(result.sharpe_ratio) > 5 ? undefined : result.sharpe_ratio >= 1}
              note={Math.abs(result.sharpe_ratio) > 5
                ? 'kiểm tra dữ liệu'
                : `đã trừ phí ${result.fee_bps}bps, thuế ${result.sell_tax_bps}bps, T+${result.settlement_lag}, trượt giá, biên ±7%`}
            />
            <Metric label="Sụt giảm tối đa" value={`${result.max_drawdown_pct.toFixed(2)}%`} positive={result.max_drawdown_pct > -15} />
            <Metric label="Số lệnh" value={String(result.total_trades)} />
            <Metric label="Tỷ lệ thắng" value={`${(result.win_rate * 100).toFixed(0)}%`} positive={result.win_rate >= 0.5} />
            <Metric label="Vốn cuối" value={vnd(result.final_capital)} />
            <Metric
              label="Chi phí ma sát"
              value={`${result.total_cost_pct.toFixed(2)}%`}
              note="phí + thuế + trượt giá, tính trên vốn ban đầu"
            />
            <Metric
              label="Bỏ lệnh do trần/sàn"
              value={String(result.ceiling_floor_skips)}
              note="phiên kịch biên ±7% — không khớp được"
            />
            <Metric
              label="Root capture"
              value={result.root_capture_ratio == null ? '—' : result.root_capture_ratio.toFixed(2)}
              positive={result.root_capture_ratio == null ? undefined : result.root_capture_ratio <= 0.85}
              note="§16.6 — mục tiêu ≤ 0,85 (mua ở gốc)"
            />
            <Metric
              label="Phiên có tín hiệu"
              value={String(result.signal_dates_covered)}
              note={result.strategy_source === 'signals' ? 'số phiên đã công bố tín hiệu' : 'không dùng ở chiến lược này'}
            />
            <Metric label="Chiến lược" value={STRATEGY_LABEL[result.strategy_source]} note={result.long_only ? 'chỉ mua (long-only)' : 'có bán khống'} />
          </div>

          <section className="rounded-2xl bg-panel border border-line p-4">
            <div className="section-label mb-2">
              Đường vốn vs benchmark{pinned && ' · so với lần ghim'}
            </div>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={mergeCurves(result, pinned)}>
                  {/* colours mirror index.css @theme — recharts takes strings, not classes */}
                  <CartesianGrid stroke="#1C222D" strokeDasharray="3 3" />
                  <XAxis dataKey="date" stroke="#5A6573" fontSize={11} />
                  <YAxis stroke="#5A6573" fontSize={11} domain={['auto', 'auto']}
                    tickFormatter={(v: number) => `${(v / 1e6).toFixed(0)}tr`} />
                  <Tooltip
                    contentStyle={{ background: '#11151C', border: '1px solid rgba(255,255,255,0.13)', borderRadius: 12 }}
                    labelStyle={{ color: '#909DAF' }}
                    formatter={(v: any) => (typeof v === 'number' ? vnd(v) : v)}
                  />
                  <Legend wrapperStyle={{ fontSize: 11, color: '#909DAF' }} />
                  <Line type="monotone" dataKey="equity" name="Chiến lược" stroke="#33D49A" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="benchmark" name={result.benchmark_source === 'vnindex' ? 'VNINDEX' : 'TB ngành'}
                    stroke="#7A8696" strokeWidth={1.6} strokeDasharray="4 4" dot={false} connectNulls />
                  {pinned && (
                    <Line type="monotone" dataKey="pinned" name={`Đã ghim · ${STRATEGY_LABEL[pinned.strategy_source]}`}
                      stroke="#46C9E6" strokeWidth={1.8} dot={false} connectNulls />
                  )}
                </LineChart>
              </ResponsiveContainer>
            </div>
            {pinned && (
              <div className="flex items-center gap-3 mt-2 text-[11.5px] font-mono text-mid">
                <span>
                  Ghim: {STRATEGY_LABEL[pinned.strategy_source]} · {pinned.total_return_pct.toFixed(2)}% ·
                  Sharpe {pinned.sharpe_ratio.toFixed(2)}
                </span>
                <span className={result.total_return_pct >= pinned.total_return_pct ? 'text-buy' : 'text-sell'}>
                  chênh {(result.total_return_pct - pinned.total_return_pct >= 0 ? '+' : '')}
                  {(result.total_return_pct - pinned.total_return_pct).toFixed(2)}%
                </span>
                <button onClick={() => setPinned(null)} className="ml-auto text-lo hover:text-hi">Bỏ ghim</button>
              </div>
            )}
          </section>

          {/* trade_log was fetched and thrown away. Without it the metrics above
              are unauditable — you cannot see which sector cost you the money. */}
          <section className="rounded-2xl bg-panel border border-line overflow-hidden">
            <div className="p-3 border-b border-line flex items-center justify-between">
              <span className="section-label">Nhật ký lệnh</span>
              <span className="text-[11px] text-lo font-mono">
                {result.trade_log.length} dòng{result.total_trades > result.trade_log.length && ` / ${result.total_trades} (200 dòng đầu)`}
              </span>
            </div>
            {result.trade_log.length === 0 ? (
              <div className="p-6 text-center text-lo text-sm">Không có lệnh nào trong khoảng này.</div>
            ) : (
              <div className="max-h-[420px] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid sticky top-0">
                    <tr>
                      <th className="p-2.5 text-left">Ngày</th>
                      <th className="p-2.5 text-left">Ngành</th>
                      <th className="p-2.5 text-left">Chiều</th>
                      <th className="p-2.5 text-right">Giá trị (VND)</th>
                      <th className="p-2.5 text-right">Chi phí (VND)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trade_log.map((t, i) => {
                      const buy = t.side === 'BUY';
                      const amount = buy ? t.alloc : t.proceeds;
                      return (
                        <tr key={`${t.date}-${t.sector}-${t.side}-${i}`} className="border-b border-line hover:bg-panel2/60">
                          <td className="p-2.5 font-mono text-mid">{t.date}</td>
                          <td className="p-2.5 font-semibold text-hi">{t.sector}</td>
                          <td className={`p-2.5 font-semibold ${buy ? 'text-buy' : 'text-sell'}`}>{buy ? 'MUA' : 'BÁN'}</td>
                          <td className="p-2.5 text-right font-mono text-hi tabular">{amount == null ? '—' : vnd(amount)}</td>
                          <td className="p-2.5 text-right font-mono text-lo tabular">{vnd(t.cost)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}

      {history.length > 0 && (
        <section className="rounded-2xl bg-panel border border-line overflow-hidden">
          <div className="p-3 border-b border-line section-label">Các lần chạy gần đây</div>
          <table className="w-full text-sm">
            <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
              <tr>
                <th className="p-2.5 text-left">Tên</th>
                <th className="p-2.5 text-left">Chiến lược</th>
                <th className="p-2.5 text-left">Khoảng</th>
                <th className="p-2.5 text-right">Lợi suất</th>
                <th className="p-2.5 text-right">Sharpe</th>
                <th className="p-2.5 text-right">MaxDD</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id} className="border-b border-line hover:bg-panel2/60">
                  <td className="p-2.5 text-hi">{h.name}</td>
                  <td className="p-2.5 text-[11px] font-mono text-lo">{h.strategy}</td>
                  <td className="p-2.5 text-[11px] font-mono text-mid">{h.start_date} → {h.end_date}</td>
                  <td className={`p-2.5 text-right font-mono tabular ${h.total_return_pct >= 0 ? 'text-buy' : 'text-sell'}`}>
                    {h.total_return_pct.toFixed(2)}%
                  </td>
                  <td className="p-2.5 text-right font-mono text-mid tabular">{h.sharpe_ratio.toFixed(2)}</td>
                  <td className="p-2.5 text-right font-mono text-mid tabular">{h.max_drawdown_pct.toFixed(2)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

/**
 * Align the pinned run's equity onto the current run's dates. The two runs can
 * cover different ranges, so this joins by date rather than by index — an
 * index join would silently slide one curve against the other and draw a
 * comparison that never happened.
 */
function mergeCurves(current: BacktestResult, pinned: BacktestResult | null) {
  if (!pinned) return current.equity_curve;
  const byDate = new Map(pinned.equity_curve.map((p) => [p.date, p.equity]));
  return current.equity_curve.map((p) => ({ ...p, pinned: byDate.get(p.date) ?? null }));
}

function Metric({ label, value, positive, note }: { label: string; value: string; positive?: boolean; note?: string }) {
  const color =
    positive === undefined ? 'text-hi' : positive ? 'text-buy' : 'text-sell';
  return (
    <div className="rounded-2xl bg-panel border border-line px-4 py-3">
      <div className="section-label">{label}</div>
      <div className={`text-xl font-bold font-mono tabular mt-1 ${color}`}>{value}</div>
      {note && <div className="text-[10px] text-lo mt-1 leading-tight">{note}</div>}
    </div>
  );
}
