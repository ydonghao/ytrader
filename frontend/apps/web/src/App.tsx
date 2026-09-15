/**
 * YTrader Web Application
 * Main App component with routing
 */
import React, {useEffect} from 'react';
import {Routes, Route, Navigate, useLocation} from 'react-router-dom';
import {useTheme} from '@ytrader/arch-hooks';
import {initI18n} from '@ytrader/arch-i18n';
import {Layout} from './components/Layout';
import {ErrorBoundary} from './components/ErrorBoundary';
import {Dashboard} from './pages/Dashboard';
import {Market} from './pages/Market';
import {Indices} from './pages/Indices';
import {Trading} from './pages/Trading';
import {Analytics} from './pages/Analytics';
import {Alerts} from './pages/Alerts';
import {Settings} from './pages/Settings';
import {SystemLogs} from './pages/SystemLogs';
import {AIChat} from './pages/AIChat';
import {RiskPage} from './pages/Risk';
import {LongTermBacktest} from './pages/LongTermBacktest';
import {Financial} from './pages/Financial';
import {Screener} from './pages/Screener';
import {Reports} from './pages/Reports';
import {Macro} from './pages/Macro';
import {Watchlist} from './pages/Watchlist';
import {lazy, Suspense} from 'react';
// AI workspace pages (lazy — they're heavy: chat UI, consoles, logs)
const NationalTeam = lazy(() => import('./pages/NationalTeam').then(m => ({default: m.NationalTeam})));
const PermPortfolio = lazy(() => import('./pages/PermPortfolio').then(m => ({default: m.PermPortfolio})));
const Replay = lazy(() => import('./pages/replay/ReplayPage').then(m => ({default: m.ReplayPage})));
const Board = lazy(() => import('./pages/Board').then(m => ({default: m.Board})));
const EarningsRadar = lazy(() => import('./pages/EarningsRadar').then(m => ({default: m.EarningsRadar})));
import './App.css';

// Initialize i18n
initI18n();

export const App: React.FC = () => {
  const {applyTheme} = useTheme();
  const location = useLocation();

  useEffect(() => {
    applyTheme();
  }, [applyTheme]);

  return (
    <Layout>
      <ErrorBoundary key={location.pathname}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/market" element={<Market />} />
          <Route path="/indices" element={<Indices />} />
          <Route path="/trading" element={<Trading />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/system-logs" element={<SystemLogs />} />
          <Route path="/ai-chat" element={<Navigate to="/ai-workspace/trader" replace />} />
          <Route path="/risk" element={<RiskPage />} />
          <Route path="/t-trading" element={<Navigate to="/lt-backtest?tab=ttrading" replace />} />
          <Route path="/lt-backtest" element={<LongTermBacktest />} />
          <Route path="/financial" element={<Financial />} />
          <Route path="/screener" element={<Screener />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/macro" element={<Macro />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/national-team" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><NationalTeam /></Suspense>} />
          <Route path="/perm-portfolio" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><PermPortfolio /></Suspense>} />
          <Route path="/replay" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><Replay /></Suspense>} />
          <Route path="/board" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><Board /></Suspense>} />
          <Route path="/earnings-radar" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><EarningsRadar /></Suspense>} />
          <Route path="/agent-config" element={<Navigate to="/settings" replace />} />
          {/* ── AI 工作台 ── */}
          <Route path="/ai-workspace/trader" element={<AIChat />} />
        </Routes>
      </ErrorBoundary>
    </Layout>
  );
};
