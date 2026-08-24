/**
 * "Luân chuyển" — Rotation Map + Stealth Watch (review §C).
 *
 * Both answer "tiền đang đi đâu tiếp"; they differ only in how early you are
 * looking. Stealth is the accumulation phase (§16.1, before price moves),
 * Rotation is the handoff that has already happened. Two tabs, one question.
 */
import { Tabs, useTab } from '../components/Tabs';
import RotationMapPage from './RotationMapPage';
import StealthWatchPage from './StealthWatchPage';

const TABS = [
  { key: 'stealth', label: 'Tích luỹ ngầm (sớm)' },
  { key: 'handoff', label: 'Đã chuyển giao' },
];

export default function RotationPage() {
  const [tab, setTab] = useTab(TABS);
  return (
    <>
      <Tabs items={TABS} active={tab} onChange={setTab} />
      {tab === 'stealth' ? <StealthWatchPage /> : <RotationMapPage />}
    </>
  );
}
