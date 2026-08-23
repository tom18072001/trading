import { useEffect, useState } from 'react';
import { sectorsApi, type VaRReport, type ExposureRow, type StopLossAlert } from '../api/client';
import { ActionBadge } from '../lib/actions';

export default function RiskPage() {
  const [vars, setVars] = useState<VaRReport[]>([]);
  const [exposure, setExposure] = useState<ExposureRow[]>([]);
  const [alerts, setAlerts] = useState<StopLossAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([sectorsApi.varAll(), sectorsApi.exposure(), sectorsApi.stoploss()])
      .then(([v, e, s]) => {
        setVars(v.data);
        setExposure(e.data);
        setAlerts(s.data);
      })
      .catch((e) => setError(e?.message || 'failed'))
      .finally(() => setLoading(false));
  }, []);

  const fmtPct = (n: number) => `${(n * 100).toFixed(2)}%`;

  return (
    <div className="px-8 py-8 max-w-[1240px] mx-auto space-y-[22px]">
      <header>
        <h1 className="font-display text-[29px] font-bold text-hi tracking-tight">
          Rủi ro &amp; Vị thế
        </h1>
        <p className="text-[13px] text-mid mt-1">
          VaR/CVaR theo ngành · tỷ trọng đang nắm · cảnh báo cắt lỗ
        </p>
      </header>

      {loading && <div className="text-mid text-sm">Đang tải…</div>}
      {error && (
        <div className="p-3 bg-sell/[0.12] border border-sell/40 text-sell rounded-xl text-sm">
          Lỗi: {error}
        </div>
      )}

      {!loading && !error && (
        <>
          <section className="rounded-2xl bg-panel border border-line overflow-hidden">
            <div className="px-4 py-3 border-b border-line section-label">Cảnh báo cắt lỗ</div>
            {alerts.length === 0 ? (
              <div className="p-8 text-center text-mid text-[13px]">
                Không có vi phạm — mọi ngành đang nắm vẫn trên ngưỡng stop.
              </div>
            ) : (
              <div>
                {alerts.map((a) => (
                  <div
                    key={`${a.sector_code}-${a.date}`}
                    className="p-3 flex items-center justify-between border-b border-line bg-sell/[0.06]"
                  >
                    <div>
                      <div className="font-semibold text-sell">{a.sector_code}</div>
                      <div className="text-[11px] font-mono text-mid tabular">
                        {a.severity} · {a.date}
                      </div>
                    </div>
                    <div className="text-right text-[11px] font-mono tabular text-hi">
                      <div>lợi suất {fmtPct(a.return_1d)}</div>
                      <div className="text-lo">ngưỡng {fmtPct(a.threshold)}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="rounded-2xl bg-panel border border-line overflow-hidden">
            <div className="px-4 py-3 border-b border-line section-label">Vị thế đang mở</div>
            <table className="w-full text-[13px]">
              <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
                <tr>
                  <th className="p-2.5 text-left">Ngành</th>
                  <th className="p-2.5 text-left">Hành động</th>
                  <th className="p-2.5 text-right">Tỷ trọng</th>
                  <th className="p-2.5 text-right">Hạng</th>
                </tr>
              </thead>
              <tbody>
                {exposure.map((e) => (
                  <tr key={e.sector_code} className="border-b border-line hover:bg-panel2/60">
                    <td className="p-2.5 font-semibold text-hi">{e.sector_code}</td>
                    <td className="p-2.5"><ActionBadge action={e.side} /></td>
                    <td className="p-2.5 text-right font-mono tabular text-hi">{fmtPct(e.weight)}</td>
                    <td className="p-2.5 text-right font-mono tabular text-lo">#{e.rank}</td>
                  </tr>
                ))}
                {exposure.length === 0 && (
                  <tr>
                    <td colSpan={4} className="p-8 text-center text-mid text-[13px]">
                      Chưa có vị thế ngành nào đang mở.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>

          <section className="rounded-2xl bg-panel border border-line overflow-hidden">
            <div className="px-4 py-3 border-b border-line section-label">
              VaR / CVaR (95%)
            </div>
            <table className="w-full text-[13px]">
              <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
                <tr>
                  <th className="p-2.5 text-left">Ngành</th>
                  <th className="p-2.5 text-right">N</th>
                  <th className="p-2.5 text-right">Trung bình</th>
                  <th className="p-2.5 text-right">Độ lệch</th>
                  <th className="p-2.5 text-right">VaR 95%</th>
                  <th className="p-2.5 text-right">CVaR 95%</th>
                </tr>
              </thead>
              <tbody>
                {vars.map((v) => (
                  <tr key={v.sector_code} className="border-b border-line hover:bg-panel2/60">
                    <td className="p-2.5 font-semibold text-hi">{v.sector_code}</td>
                    <td className="p-2.5 text-right font-mono tabular text-mid">{v.n_obs}</td>
                    <td className="p-2.5 text-right font-mono tabular text-hi">{fmtPct(v.mean)}</td>
                    <td className="p-2.5 text-right font-mono tabular text-hi">{fmtPct(v.std)}</td>
                    <td className="p-2.5 text-right font-mono tabular text-sell">{fmtPct(v.var_95)}</td>
                    <td className="p-2.5 text-right font-mono tabular text-sell">{fmtPct(v.cvar_95)}</td>
                  </tr>
                ))}
                {vars.length === 0 && (
                  <tr>
                    <td colSpan={6} className="p-8 text-center text-mid text-[13px]">
                      Chưa có dữ liệu VaR.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
