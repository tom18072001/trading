import { useEffect, useState } from 'react';
import { sectorsApi, type RegimeRow } from '../api/client';

const REGIME: Record<string, { label: string; hint: string; tone: string }> = {
  risk_on:  { label: 'Risk-on',   hint: 'tiền vào thị trường — ưu tiên cổ phiếu dẫn dắt', tone: 'text-buy border-buy/40 bg-buy/[0.10]' },
  risk_off: { label: 'Risk-off',  hint: 'tiền rút ra — hạ tỷ trọng, giữ tiền mặt',        tone: 'text-sell border-sell/40 bg-sell/[0.10]' },
  rotation: { label: 'Luân chuyển', hint: 'dòng tiền đổi ngành, không rời thị trường',   tone: 'text-warn border-warn/40 bg-warn/[0.10]' },
  chop:     { label: 'Đi ngang',  hint: 'không có xu hướng — giảm tần suất giao dịch',    tone: 'text-acc border-acc/40 bg-acc/[0.10]' },
  unknown:  { label: 'Chưa rõ',   hint: 'chưa đủ dữ liệu để phân loại',                   tone: 'text-mid border-line2 bg-raise' },
};
const regimeOf = (k: string) => REGIME[k] || REGIME.unknown;

export default function RegimePage() {
  const [latest, setLatest] = useState<RegimeRow | null>(null);
  const [history, setHistory] = useState<RegimeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [classifying, setClassifying] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([sectorsApi.latestRegime(), sectorsApi.regimeHistory(60)])
      .then(([a, b]) => {
        setLatest(a.data);
        setHistory(b.data);
      })
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const classify = async () => {
    setClassifying(true);
    try {
      await sectorsApi.classifyRegime();
      load();
    } finally {
      setClassifying(false);
    }
  };

  return (
    <div className="px-8 py-8 max-w-[1240px] mx-auto space-y-[22px]">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-[29px] font-bold text-hi tracking-tight">
            Trạng thái thị trường
          </h1>
          <p className="text-[13px] text-mid mt-1">
            HMM Gaussian trên các neo vĩ mô (có fallback heuristic)
          </p>
        </div>
        <button
          onClick={classify}
          disabled={classifying}
          className="px-4 py-2 rounded-xl bg-acc/[0.13] text-acc border border-acc/30 hover:bg-acc/[0.2] disabled:opacity-50 text-[13px] font-semibold shrink-0"
        >
          {classifying ? 'Đang phân loại…' : 'Phân loại lại'}
        </button>
      </header>

      {loading && <div className="text-mid text-sm">Đang tải…</div>}

      {!loading && latest && (
        <section className={`rounded-2xl border p-7 ${regimeOf(latest.regime_label).tone}`}>
          <div className="section-label">Trạng thái hiện tại</div>
          <div className="font-display text-[44px] font-bold leading-tight mt-1">
            {regimeOf(latest.regime_label).label}
          </div>
          <div className="text-[13px] opacity-80 mt-1">{regimeOf(latest.regime_label).hint}</div>
          <div className="text-[12px] font-mono tabular opacity-70 mt-3">
            độ tin cậy {(latest.confidence * 100).toFixed(0)}% · {latest.date}
          </div>
        </section>
      )}

      <section className="rounded-2xl bg-panel border border-line overflow-hidden">
        <div className="px-4 py-3 border-b border-line section-label">Lịch sử 60 phiên</div>
        <table className="w-full text-[13px]">
          <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
            <tr>
              <th className="p-2.5 text-left">Ngày</th>
              <th className="p-2.5 text-left">Trạng thái</th>
              <th className="p-2.5 text-right">Độ tin cậy</th>
            </tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.date} className="border-b border-line hover:bg-panel2/60">
                <td className="p-2.5 font-mono text-mid tabular">{h.date}</td>
                <td className="p-2.5 font-semibold text-hi">{regimeOf(h.regime_label).label}</td>
                <td className="p-2.5 text-right font-mono tabular text-mid">
                  {(h.confidence * 100).toFixed(0)}%
                </td>
              </tr>
            ))}
            {history.length === 0 && (
              <tr>
                <td colSpan={3} className="p-8 text-center text-mid text-[13px]">
                  Chưa có lịch sử. Bấm <span className="text-acc font-semibold">Phân loại lại</span>.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
