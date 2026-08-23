import { useState } from 'react';
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { sectorsApi, type BacktestResult } from '../api/client';

export default function BacktestPage() {
  const [name, setName] = useState('rotation_default');
  const [start, setStart] = useState('2025-01-01');
  const [end, setEnd] = useState('2025-12-31');
  const [capital, setCapital] = useState(100_000_000);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const r = await sectorsApi.runBacktest({
        name, start_date: start, end_date: end, initial_capital: capital,
      });
      setResult(r.data);
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
          Chiến lược luân chuyển ngành — xếp hạng theo dòng tiền ròng mỗi phiên
        </p>
      </header>

      <section className="rounded-2xl bg-panel border border-line p-5 grid grid-cols-2 md:grid-cols-4 gap-4">
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
        <div className="md:col-span-4 flex justify-end">
          <button
            onClick={run}
            disabled={running}
            className="px-5 py-2 rounded-xl bg-acc/[0.13] text-acc border border-acc/30 hover:bg-acc/[0.2] disabled:opacity-50 text-[13px] font-semibold"
          >
            {running ? 'Đang chạy…' : 'Chạy backtest'}
          </button>
        </div>
      </section>

      {error && (
        <div className="p-3 bg-sell/[0.12] border border-sell/40 text-sell rounded-xl text-sm">
          Lỗi: {error}
        </div>
      )}

      {result && (
        <div className="space-y-[22px]">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Metric label="Tổng lợi suất" value={`${result.total_return_pct.toFixed(2)}%`} positive={result.total_return_pct >= 0} />
            <Metric label="Benchmark" value={`${result.benchmark_return_pct.toFixed(2)}%`} />
            {/* 2026-08-23 (review A7): Sharpe was rendered bare. CLAUDE.md
                §18.2/7-10 lists T+2 settlement, broker fees, the 0.1% sell tax
                and the ±7% price band as open [BLOCKER]s — none is modelled, so
                this number is gross, not net. |Sharpe| > 5 is not a great
                strategy, it is a data problem; say so rather than print it. */}
            <Metric
              label="Sharpe (gộp)"
              value={Math.abs(result.sharpe_ratio) > 5 ? 'n/a' : result.sharpe_ratio.toFixed(2)}
              positive={Math.abs(result.sharpe_ratio) > 5 ? undefined : result.sharpe_ratio >= 1}
              note={Math.abs(result.sharpe_ratio) > 5 ? 'kiểm tra dữ liệu' : 'chưa gồm T+2, phí, thuế, price-band'}
            />
            <Metric label="Sụt giảm tối đa" value={`${result.max_drawdown_pct.toFixed(2)}%`} positive={result.max_drawdown_pct > -15} />
            <Metric label="Số lệnh" value={String(result.total_trades)} />
            <Metric label="Tỷ lệ thắng" value={`${(result.win_rate * 100).toFixed(0)}%`} positive={result.win_rate >= 0.5} />
            <Metric label="Vốn cuối" value={result.final_capital.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
            <Metric label="Vốn đầu" value={result.initial_capital.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
          </div>

          <section className="rounded-2xl bg-panel border border-line p-4 h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={result.equity_curve}>
                {/* colours mirror index.css @theme — recharts takes strings, not classes */}
                <CartesianGrid stroke="#1C222D" strokeDasharray="3 3" />
                <XAxis dataKey="date" stroke="#5A6573" fontSize={11} />
                <YAxis stroke="#5A6573" fontSize={11} domain={['auto', 'auto']} />
                <Tooltip
                  contentStyle={{ background: '#11151C', border: '1px solid rgba(255,255,255,0.13)', borderRadius: 12 }}
                  labelStyle={{ color: '#909DAF' }}
                />
                <Line type="monotone" dataKey="equity" stroke="#33D49A" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </section>
        </div>
      )}
    </div>
  );
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
