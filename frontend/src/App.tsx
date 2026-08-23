import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import FlowMonitorPage from './pages/FlowMonitorPage';
import RotationMapPage from './pages/RotationMapPage';
import StealthWatchPage from './pages/StealthWatchPage';
import FlowPulsePage from './pages/FlowPulsePage';
import DailyInsightPage from './pages/DailyInsightPage';
import SectorDetailPage from './pages/SectorDetailPage';
// Wired 2026-08-23. These four were fully built, their APIs return real data,
// and CLAUDE.md section 12 lists them as deliverables -- they simply had no
// <Route>, so the only way to reach them was to edit the source.
//
// Lazy, deliberately. Wiring them eagerly took the main bundle from 372 kB to
// 732 kB: BacktestPage pulls in recharts, which nothing on the daily path
// needs. These four are opened occasionally, so they should not be on the
// critical path for the page you open every morning.
const RankingPage = lazy(() => import('./pages/RankingPage'));
const RegimePage = lazy(() => import('./pages/RegimePage'));
const RiskPage = lazy(() => import('./pages/RiskPage'));
const BacktestPage = lazy(() => import('./pages/BacktestPage'));

function RouteFallback() {
  return (
    <div className="p-8 text-mid text-sm" role="status" aria-live="polite">
      Đang tải…
    </div>
  );
}

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
        <Route
          path="/ranking"
          element={<Suspense fallback={<RouteFallback />}><RankingPage /></Suspense>}
        />
        <Route
          path="/regime"
          element={<Suspense fallback={<RouteFallback />}><RegimePage /></Suspense>}
        />
        <Route
          path="/risk"
          element={<Suspense fallback={<RouteFallback />}><RiskPage /></Suspense>}
        />
        <Route
          path="/backtest"
          element={<Suspense fallback={<RouteFallback />}><BacktestPage /></Suspense>}
        />
        <Route path="/insight" element={<DailyInsightPage />} />
        <Route path="*" element={<Navigate to="/flow" replace />} />
      </Route>
    </Routes>
  );
}
