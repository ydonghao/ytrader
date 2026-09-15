/**
 * Layout — Professional shell with sidebar + topbar + content area
 */
import React, {useState} from 'react';
import {Link, useLocation} from 'react-router-dom';
import {Icons} from './icons';
import './Layout.css';

/* ── Types ── */
interface NavItem {
  path: string;
  label: string;
  icon: React.ReactNode;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

interface LayoutProps {
  children: React.ReactNode;
}

// Shared icon set — see components/icons.tsx
const Icon = Icons;

/* ── Inline SVG Icons (16×16 viewBox) — moved to components/icons.tsx ── */

/* ── Navigation Definition (grouped) ── */
const navGroups: NavGroup[] = [
  {
    title: '总览',
    items: [
      {path: '/dashboard', label: '总览', icon: Icon.dashboard},
      {path: '/market', label: '行情', icon: Icon.market},
      {path: '/indices', label: '指数', icon: Icon.globe},
      {path: '/watchlist', label: '自选股', icon: Icon.star},
    ],
  },
  {
    title: '研究',
    items: [
      {path: '/financial', label: '财务报表', icon: Icon.financial},
      {path: '/earnings-radar', label: '财报雷达', icon: Icon.analytics},
      {path: '/screener', label: '选股器', icon: Icon.strategies},
      {path: '/macro', label: '宏观政策', icon: Icon.analytics},
      {path: '/national-team', label: '国家队', icon: Icon.analytics},
      {path: '/reports', label: '报告', icon: Icon.reports},
    ],
  },
  {
    title: '交易',
    items: [
      {path: '/trading', label: '交易', icon: Icon.trading},
      {path: '/lt-backtest', label: '回测实验室', icon: Icon.backtest},
      {path: '/replay', label: '时光机', icon: Icon.star},
      {path: '/perm-portfolio', label: '永久组合', icon: Icon.portfolio},
    ],
  },
  {
    title: '分析',
    items: [
      {path: '/analytics', label: '分析', icon: Icon.analytics},
      {path: '/board', label: '看板', icon: Icon.dashboard},
      {path: '/risk', label: '风险', icon: Icon.risk},
      {path: '/alerts', label: '预警', icon: Icon.alerts},
    ],
  },
  {
    title: 'AI / 系统',
    items: [
      {path: '/ai-workspace/trader', label: 'AI交易助手', icon: Icon.intel},
      {path: '/settings', label: '设置', icon: Icon.settings},
      {path: '/system-logs', label: '系统日志', icon: Icon.terminal},
    ],
  },
];

/* ── Component ── */
export const Layout: React.FC<LayoutProps> = ({children}) => {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  const toggleGroup = (title: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(title)) {
        next.delete(title);
      } else {
        next.add(title);
      }
      return next;
    });
  };

  return (
    <div className={`layout ${collapsed ? 'layout--collapsed' : ''}`}>
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar__header">
          <Link to="/" className="sidebar__brand">
            <span className="sidebar__logo-mark">Y</span>
            {!collapsed && <span className="sidebar__logo-text">YTrader</span>}
          </Link>
          <button
            className="sidebar__toggle"
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? Icon.expand : Icon.collapse}
          </button>
        </div>

        <nav className="sidebar__nav">
          {navGroups.map((group) => (
            <div key={group.title} className="sidebar__group">
              {!collapsed && (
                <button
                  className="sidebar__group-title"
                  onClick={() => toggleGroup(group.title)}
                >
                  <span>{group.title}</span>
                  {collapsedGroups.has(group.title)
                    ? Icon.chevronRight
                    : Icon.chevronDown}
                </button>
              )}
              {!collapsedGroups.has(group.title) &&
                group.items.map((item) => {
                  const isActive = location.pathname === item.path;
                  return (
                    <Link
                      key={item.path}
                      to={item.path}
                      className={`sidebar__item ${isActive ? 'sidebar__item--active' : ''}`}
                      title={collapsed ? item.label : undefined}
                    >
                      <span className="sidebar__item-icon">{item.icon}</span>
                      {!collapsed && (
                        <span className="sidebar__item-label">{item.label}</span>
                      )}
                      {isActive && <span className="sidebar__item-indicator" />}
                    </Link>
                  );
                })}
            </div>
          ))}
        </nav>

        <div className="sidebar__footer">
          <span className="sidebar__version">{collapsed ? 'v0' : 'v0.0.1'}</span>
        </div>
      </aside>

      {/* ── Main Area ── */}
      <div className="layout__main-area">
        {/* ── Content ── */}
        <main className="layout__content">{children}</main>
      </div>
    </div>
  );
};
