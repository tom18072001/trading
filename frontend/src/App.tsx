import { Suspense, lazy, type ReactNode } from 'react';
import { Navigate, Route, Routes, useParams } from 'react-router-dom';
import Layout from './components/Layout';
import DailyInsightPage from './pages/DailyInsightPage';
import FlowPage from './pages/FlowPage';
import RotationPage from './pages/RotationPage';

// 2026-08-23 (review §C): nav merged 9 → 5. Four routes became tabs inside
// two pages (FlowPage, RotationPage) and three became tabs inside ResearchPage.
// The old paths still resolve — see the redirects below — because they are in
// four months of bookmarks and in MODIFICATION_LOG.md.
//
// Lazy, and for the same reason as before: BacktestPage pulls in recharts,
// which nothing on the daily path needs. PositionsPage and ResearchPage are
// opened occasionally; keeping them off the main bundle keeps the page you
// open every morning at ~376 kB.
const PositionsPage = lazy(() => import('./pages/PositionsPage'));
const ResearchPage = lazy(() => import('./pages/ResearchPage'));

function RouteFallback() {
  return (
    <div className="p-8 text-mid text-sm" role="status" aria-live="polite">
      Đang tải…
    </div>
  );
}

const lazyRoute = (el: ReactNode) => <Suspense fallback={<RouteFallback />}>{el}</Suspense>;

/** /flow/BANK → /flow?tab=detail&code=BANK. Old per-sector links keep working. */
function SectorDetailRedirect() {
  const { code } = useParams<{ code: string }>();
  return <Navigate to={`/flow?tab=detail&code=${code}`} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/insight" replace />} />
        <Route path="/insight" element={<DailyInsightPage />} />
        <Route path="/flow" element={<FlowPage />} />
        <Route path="/rotation" element={<RotationPage />} />
        <Route path="/positions" element={lazyRoute(<PositionsPage />)} />
        <Route path="/research" element={lazyRoute(<ResearchPage />)} />

        {/* Pre-merge paths. */}
        <Route path="/flow/:code" element={<SectorDetailRedirect />} />
        <Route path="/stealth" element={<Navigate to="/rotation?tab=stealth" replace />} />
        <Route path="/pulse" element={<Navigate to="/positions?tab=pulse" replace />} />
        <Route path="/risk" element={<Navigate to="/positions?tab=risk" replace />} />
        <Route path="/ranking" element={<Navigate to="/research?tab=ranking" replace />} />
        <Route path="/regime" element={<Navigate to="/research?tab=regime" replace />} />
        <Route path="/backtest" element={<Navigate to="/research?tab=backtest" replace />} />

        <Route path="*" element={<Navigate to="/insight" replace />} />
      </Route>
    </Routes>
  );
}
