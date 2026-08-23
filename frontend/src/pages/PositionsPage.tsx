/**
 * "Rủi ro & Vị thế" — Risk + Flow Pulse (review §C).
 *
 * The merge also settles review §A4: both pages showed an exposure panel, and
 * Flow Pulse's used to read the hardcoded `{"rows": []}` stub in
 * api/routers/pulse.py. Now there is one surface, one source
 * (/api/sectors/risk/exposure), and no way for the two to disagree.
 *
 * The kill-switch for config.TRADING_HALT belongs on this page — it is step 4
 * of the review backlog, not this one.
 */
import { Tabs, useTab } from '../components/Tabs';
import RiskPage from './RiskPage';
import FlowPulsePage from './FlowPulsePage';

const TABS = [
  { key: 'risk', label: 'Vị thế & VaR' },
  { key: 'pulse', label: 'Nhịp dòng tiền + cảnh báo' },
];

export default function PositionsPage() {
  const [tab, setTab] = useTab(TABS);
  return (
    <>
      <Tabs items={TABS} active={tab} onChange={setTab} />
      {tab === 'risk' ? <RiskPage /> : <FlowPulsePage />}
    </>
  );
}
