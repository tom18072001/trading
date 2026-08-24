import { useEffect, useState } from 'react';
import { sectorsApi, type SectorSignalRow } from '../api/client';
import { ActionBadge } from '../lib/actions';
import { FilterBar, Th, downloadCsv, passes, useSorter, useTableFilter } from '../lib/filters';
import { Hint } from '../lib/glossary';

const ACTIONS = ['ACCUMULATE', 'BUY', 'TRIM', 'SELL', 'HOLD'];

export default function RankingPage() {
  const [rows, setRows] = useState<SectorSignalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const f = useTableFilter('rk');
  const sorter = useSorter('rank', 'asc', 'rk');

  // Filter, then sort. The other order sorts rows you are about to discard.
  const shown = sorter.apply(
    rows.filter((r) => passes(f, { sector: r.sector_code, action: r.action })));

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
        <>
        <FilterBar
          f={f} actions={ACTIONS} total={rows.length} shown={shown.length}
          onExport={() => downloadCsv(
            `xep_hang_nganh_${rows[0]?.date ?? 'export'}.csv`,
            [
              { key: 'rank', label: 'Hạng' }, { key: 'sector_code', label: 'Ngành' },
              { key: 'score', label: 'Score' }, { key: 'action', label: 'Hành động' },
              { key: 'persistence_ok', label: 'Bền tín hiệu' }, { key: 'date', label: 'Ngày' },
            ],
            shown)}
        />
        <section className="rounded-2xl bg-panel border border-line overflow-hidden">
          <table className="w-full text-[13px]">
            <thead className="bg-panel2 border-b border-line text-[10px] uppercase tracking-wider text-mid">
              <tr>
                <Th s={sorter} col="rank" className="w-16">#</Th>
                <Th s={sorter} col="sector_code">Ngành</Th>
                <Th s={sorter} col="score" align="right"><Hint term="score">Score</Hint></Th>
                <Th s={sorter} col="persistence_ok" align="center">
                  <Hint term="persistence_ok">Bền tín hiệu</Hint>
                </Th>
                <Th s={sorter} col="action">Hành động</Th>
                <Th s={sorter} col="date">Ngày</Th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
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
              {shown.length === 0 && (
                <tr>
                  <td colSpan={6} className="p-8 text-center text-mid text-[13px]">
                    {rows.length === 0 ? (
                      <>Chưa có tín hiệu. Bấm <span className="text-buy font-semibold">Publish ngay</span> để
                      chạy ranker cho phiên gần nhất.</>
                    ) : (
                      <>Không ngành nào khớp bộ lọc ({rows.length} ngành bị ẩn).</>
                    )}
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
