import { useEffect, useState } from 'react';
import { sectorsApi, type SectorSignalRow } from '../api/client';
import { ActionBadge } from '../lib/actions';

export default function RankingPage() {
  const [rows, setRows] = useState<SectorSignalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    sectorsApi.latestRanking()
      .then((r) => setRows(r.data))
      .catch((e) => setError(e?.message || 'failed'))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const publish = async () => {
    setPublishing(true);
    try {
      const res = await sectorsApi.publishRanking();
      setRows(res.data.rows);
    } catch (e: any) {
      setError(e?.message || 'publish failed');
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="px-8 py-8 max-w-[1240px] mx-auto space-y-[22px]">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-[29px] font-bold text-hi tracking-tight">
            Xếp hạng ngành
          </h1>
          <p className="text-[13px] text-mid mt-1">
            Kết quả ranker hằng ngày · top-3 Mua, đáy-2 Bán · lọc bền tín hiệu ≥3 phiên
          </p>
        </div>
        <button
          onClick={publish}
          disabled={publishing}
          className="px-4 py-2 rounded-xl bg-buy/[0.13] text-buy border border-buy/30 hover:bg-buy/[0.2] disabled:opacity-50 text-[13px] font-semibold shrink-0"
        >
          {publishing ? 'Đang publish…' : 'Publish ngay'}
        </button>
      </header>

      {loading && <div className="text-mid text-sm">Đang tải…</div>}
      {error && (
        <div className="p-3 bg-sell/[0.12] border border-sell/40 text-sell rounded-xl text-sm">
          Lỗi: {error}
        </div>
      )}

      {!loading && !error && (
        <section className="rounded-2xl bg-panel border border-line overflow-hidden">
          <table className="w-full text-[13px]">
            <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
              <tr>
                <th className="p-2.5 text-left w-16">#</th>
                <th className="p-2.5 text-left">Ngành</th>
                <th className="p-2.5 text-right">Score</th>
                <th className="p-2.5 text-center">Bền tín hiệu</th>
                <th className="p-2.5 text-left">Hành động</th>
                <th className="p-2.5 text-left">Ngày</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.sector_code} className="border-b border-line hover:bg-panel2/60">
                  <td className="p-2.5 font-mono font-bold text-mid tabular">#{r.rank}</td>
                  <td className="p-2.5 font-semibold text-hi">{r.sector_code}</td>
                  <td className="p-2.5 text-right font-mono tabular text-hi">
                    {r.score.toFixed(4)}
                  </td>
                  <td className="p-2.5 text-center">
                    {r.persistence_ok
                      ? <span className="text-buy">✓</span>
                      : <span className="text-lo">—</span>}
                  </td>
                  <td className="p-2.5"><ActionBadge action={r.action} showHint /></td>
                  <td className="p-2.5 font-mono text-lo tabular">{r.date}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="p-8 text-center text-mid text-[13px]">
                    Chưa có tín hiệu. Bấm <span className="text-buy font-semibold">Publish ngay</span> để
                    chạy ranker cho phiên gần nhất.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
