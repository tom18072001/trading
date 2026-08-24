/**
 * "Dòng tiền" — Money Flow Monitor + Sector Detail in one place (review §C).
 *
 * Clicking a sector used to navigate to /flow/:code, which threw away the
 * interval, the flow_z_hot you had typed and the selected line on the chart.
 * Now it swaps a tab; both halves stay mounted-adjacent and the URL carries
 * `?tab=detail&code=BANK`, so the deep link survives.
 *
 * /flow/:code still resolves — it redirects here (App.tsx).
 */
import { useSearchParams } from 'react-router-dom';
import { Tabs, useTab } from '../components/Tabs';
import FlowMonitorPage from './FlowMonitorPage';
import SectorDetailPage from './SectorDetailPage';

const TABS = [
  { key: 'overview', label: 'Tổng quan 15 ngành' },
  { key: 'detail', label: 'Chi tiết một ngành' },
];

export default function FlowPage() {
  const [sp] = useSearchParams();
  const [tab, setTab] = useTab(TABS);
  const code = sp.get('code');

  return (
    <>
      <Tabs items={TABS} active={tab} onChange={setTab} />
      {tab === 'overview' ? (
        <FlowMonitorPage />
      ) : code ? (
        <SectorDetailPage code={code} />
      ) : (
        <div className="px-8 py-12 text-center text-mid text-[13px]">
          Chọn một ngành ở tab <span className="text-acc font-semibold">Tổng quan</span> để xem chi tiết.
        </div>
      )}
    </>
  );
}
