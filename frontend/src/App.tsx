import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import FlowMonitorPage from './pages/FlowMonitorPage';
import RotationMapPage from './pages/RotationMapPage';
import StealthWatchPage from './pages/StealthWatchPage';
import FlowPulsePage from './pages/FlowPulsePage';
import DailyInsightPage from './pages/DailyInsightPage';
import SectorDetailPage from './pages/SectorDetailPage';

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/insight" replace />} />
        <Route path="/flow" element={<FlowMonitorPage />} />
        <Route path="/flow/:code" element={<SectorDetailPage />} />
        <Route path="/rotation" element={<RotationMapPage />} />
        <Route path="/stealth" element={<StealthWatchPage />} />
        <Route path="/pulse" element={<FlowPulsePage />} />
        <Route path="/insight" element={<DailyInsightPage />} />
        <Route path="*" element={<Navigate to="/flow" replace />} />
      </Route>
    </Routes>
  );
}
