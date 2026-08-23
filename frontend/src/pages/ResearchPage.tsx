/**
 * "Nghiên cứu" — Backtest + Xếp hạng ngành + lịch sử regime (review §C).
 *
 * None of these is a daily job. Backtest is a weekend exercise, the ranker
 * table is a diagnostic on top of what Daily Insight already tells you, and
 * regime history is context you read once a month. Grouping them off the daily
 * path is the whole point of the 9 → 5 merge.
 *
 * Lazy: BacktestPage pulls in recharts (346 kB). Keeping the import inside
 * this file would put recharts back on the critical path for the other two
 * tabs, so each tab loads on selection.
 */
import { Suspense, lazy } from 'react';
import { Tabs, useTab } from '../components/Tabs';

const BacktestPage = lazy(() => import('./BacktestPage'));
const RankingPage = lazy(() => import('./RankingPage'));
const RegimePage = lazy(() => import('./RegimePage'));

const TABS = [
  { key: 'ranking', label: 'Xếp hạng ngành' },
  { key: 'regime', label: 'Trạng thái thị trường' },
  { key: 'backtest', label: 'Backtest' },
];

export default function ResearchPage() {
  const [tab, setTab] = useTab(TABS);
  return (
    <>
      <Tabs items={TABS} active={tab} onChange={setTab} />
      <Suspense fallback={<div className="p-8 text-mid text-sm" role="status" aria-live="polite">Đang tải…</div>}>
        {tab === 'ranking' && <RankingPage />}
        {tab === 'regime' && <RegimePage />}
        {tab === 'backtest' && <BacktestPage />}
      </Suspense>
    </>
  );
}
