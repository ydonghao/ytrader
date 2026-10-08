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
import {Start} from './pages/Start';
import {Market} from './pages/Market';
import {Indices} from './pages/Indices';
import {Trading} from './pages/Trading';
import {Analytics} from './pages/Analytics';
import {Alerts} from './pages/Alerts';
import {Settings} from './pages/Settings';
import {SystemLogs} from './pages/SystemLogs';
import {RiskPage} from './pages/Risk';
import {LongTermBacktest} from './pages/LongTermBacktest';
import {Financial} from './pages/Financial';
import {Screener} from './pages/Screener';
import {Macro} from './pages/Macro';
import {Watchlist} from './pages/Watchlist';
import {lazy, Suspense} from 'react';
// AI workspace pages (lazy — they're heavy)
// loader 提为可调用对象：lazy() 与空闲预加载共用同一模块 promise
const lazyLoaders = {
  NationalTeam: () => import('./pages/NationalTeam').then((m) => ({default: m.NationalTeam})),
  PermPortfolio: () => import('./pages/PermPortfolio').then((m) => ({default: m.PermPortfolio})),
  Replay: () => import('./pages/replay/ReplayPage').then((m) => ({default: m.ReplayPage})),
  Board: () => import('./pages/Board').then((m) => ({default: m.Board})),
  EarningsRadar: () => import('./pages/EarningsRadar').then((m) => ({default: m.EarningsRadar})),
  IndustryAnalysis: () => import('./pages/IndustryAnalysis').then((m) => ({default: m.IndustryAnalysis})),
  CoursePortfolio: () => import('./pages/CoursePortfolio'),
  Checklist: () => import('./pages/Checklist').then((m) => ({default: m.Checklist})),
  Thesis: () => import('./pages/Thesis').then((m) => ({default: m.Thesis})),
  Compare: () => import('./pages/Compare').then((m) => ({default: m.Compare})),
  Notes: () => import('./pages/Notes').then((m) => ({default: m.Notes})),
};
const NationalTeam = lazy(lazyLoaders.NationalTeam);
const PermPortfolio = lazy(lazyLoaders.PermPortfolio);
const Replay = lazy(lazyLoaders.Replay);
const Board = lazy(lazyLoaders.Board);
const EarningsRadar = lazy(lazyLoaders.EarningsRadar);
const IndustryAnalysis = lazy(lazyLoaders.IndustryAnalysis);
const CoursePortfolio = lazy(lazyLoaders.CoursePortfolio);
const Checklist = lazy(lazyLoaders.Checklist);
const Thesis = lazy(lazyLoaders.Thesis);
const Compare = lazy(lazyLoaders.Compare);
const Notes = lazy(lazyLoaders.Notes);
import './App.css';

// 稳定骨架：与内容区等高，避免 fallback→页面的高度跳变
const PageSkeleton: React.FC = () => (
  <div className="page-loading page-loading--stable" role="status">
    <span className="ui-state__spinner" />
    <span>加载中…</span>
  </div>
);

// Initialize i18n
initI18n();

export const App: React.FC = () => {
  const {applyTheme} = useTheme();
  const location = useLocation();

  useEffect(() => {
    applyTheme();
  }, [applyTheme]);

  // 空闲预加载全部懒路由 chunk：首屏渲染优先，1.5s 后逐个预热，
  // 之后切菜单零 Suspense 占位（dev 下即完成全部按需编译）
  useEffect(() => {
    const loaders = Object.values(lazyLoaders);
    let i = 0;
    const step = () => {
      if (i >= loaders.length) return;
      loaders[i++]().catch(() => {});
      const ric = (window as unknown as {
        requestIdleCallback?: (cb: () => void) => number;
      }).requestIdleCallback;
      if (ric) ric(step);
      else setTimeout(step, 400);
    };
    const t = setTimeout(step, 1500);
    return () => clearTimeout(t);
  }, []);

  return (
    <Layout>
      <ErrorBoundary key={location.pathname}>
        {/* 路由提取正则依赖 path 为 Route 首属性(src/config/__tests__/routes.test.ts) */}
        <Routes>
          <Route path="/" element={<Navigate to="/start" replace />} />
          <Route path="/start" element={<Start />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/market" element={<Market />} />
          <Route path="/indices" element={<Indices />} />
          <Route path="/trading" element={<Trading />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/system-logs" element={<SystemLogs />} />
          <Route path="/ai-chat" element={<Navigate to="/start" replace />} />
          <Route path="/risk" element={<RiskPage />} />
          <Route path="/t-trading" element={<Navigate to="/lt-backtest" replace />} />
          <Route path="/lt-backtest" element={<LongTermBacktest />} />
          <Route path="/thesis" element={<Suspense fallback={<PageSkeleton />}><Thesis /></Suspense>} />
          <Route path="/compare" element={<Suspense fallback={<PageSkeleton />}><Compare /></Suspense>} />
          <Route path="/notes" element={<Suspense fallback={<PageSkeleton />}><Notes /></Suspense>} />
          <Route path="/financial" element={<Financial />} />
          <Route path="/screener" element={<Screener />} />
          <Route path="/course-portfolio" element={<Suspense fallback={<PageSkeleton />}><CoursePortfolio /></Suspense>} />
          <Route path="/macro" element={<Macro />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/national-team" element={<Suspense fallback={<PageSkeleton />}><NationalTeam /></Suspense>} />
          <Route path="/perm-portfolio" element={<Suspense fallback={<PageSkeleton />}><PermPortfolio /></Suspense>} />
          <Route path="/replay" element={<Suspense fallback={<PageSkeleton />}><Replay /></Suspense>} />
          <Route path="/board" element={<Suspense fallback={<PageSkeleton />}><Board /></Suspense>} />
          <Route path="/earnings-radar" element={<Suspense fallback={<PageSkeleton />}><EarningsRadar /></Suspense>} />
          <Route path="/industry-analysis" element={<Suspense fallback={<PageSkeleton />}><IndustryAnalysis /></Suspense>} />
          <Route path="/checklist" element={<Suspense fallback={<PageSkeleton />}><Checklist /></Suspense>} />
          <Route path="/agent-config" element={<Navigate to="/settings" replace />} />
        </Routes>
      </ErrorBoundary>
    </Layout>
  );
};
