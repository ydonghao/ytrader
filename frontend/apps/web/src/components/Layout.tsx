/**
 * Layout — Professional shell with sidebar + topbar + content area
 */
import React, {useState} from 'react';
import {Link, useLocation} from 'react-router-dom';
import {Icons} from './icons';
import {navGroups} from '../config/navigation';
import {WorkflowBar} from './WorkflowBar';
import './Layout.css';

/* ── Types ── */
interface LayoutProps {
  children: React.ReactNode;
}

// Shared icon set — see components/icons.tsx
const Icon = Icons;

/* ── Component ── */
export const Layout: React.FC<LayoutProps> = ({children}) => {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(
    () => new Set(navGroups.filter((g) => !g.defaultOpen).map((g) => g.id))
  );

  const toggleGroup = (id: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
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
            <div key={group.id} className="sidebar__group">
              {!collapsed && (
                <button
                  className="sidebar__group-title"
                  onClick={() => toggleGroup(group.id)}
                  aria-expanded={!collapsedGroups.has(group.id)}
                >
                  <span>{group.title}</span>
                  {collapsedGroups.has(group.id) ? Icon.chevronRight : Icon.chevronDown}
                </button>
              )}
              {(collapsed || !collapsedGroups.has(group.id)) &&
                group.items.map((item) => {
                  const isActive = location.pathname === item.path;
                  return (
                    <Link
                      key={item.path}
                      to={item.path}
                      className={`sidebar__item ${isActive ? 'sidebar__item--active' : ''}`}
                      title={collapsed ? `${item.label}——${item.desc}` : undefined}
                    >
                      <span className="sidebar__item-icon">
                        {Icons[item.icon]}
                      </span>
                      {!collapsed && (
                        <span className="sidebar__item-text">
                          <span className="sidebar__item-label">{item.label}</span>
                          <span className="sidebar__item-desc">{item.desc}</span>
                        </span>
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
        <main className="layout__content">
          <WorkflowBar />
          {children}
        </main>
      </div>
    </div>
  );
};
