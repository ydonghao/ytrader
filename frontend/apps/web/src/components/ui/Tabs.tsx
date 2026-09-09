import React from 'react';
import './ui.css';

export interface TabItem { key: string; label: React.ReactNode; }

interface TabsProps {
  tabs: TabItem[];
  active: string;
  onChange: (key: string) => void;
  className?: string;
}

export const Tabs: React.FC<TabsProps> = ({tabs, active, onChange, className = ''}) => (
  <div className={`ui-tabs ${className}`.trim()} role="tablist">
    {tabs.map(t => (
      <button
        key={t.key} role="tab" aria-selected={t.key === active}
        type="button"
        className={`ui-tab ${t.key === active ? 'ui-tab--active' : ''}`}
        onClick={() => onChange(t.key)}
      >
        {t.label}
      </button>
    ))}
  </div>
);
