import React from 'react';
import './ui.css';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

export const PageHeader: React.FC<PageHeaderProps> = ({title, subtitle, actions}) => (
  <header className="ui-page-header">
    <div>
      <h1 className="ui-page-header__title">{title}</h1>
      {subtitle && <p className="ui-page-header__subtitle">{subtitle}</p>}
    </div>
    {actions && <div className="ui-page-header__actions">{actions}</div>}
  </header>
);
