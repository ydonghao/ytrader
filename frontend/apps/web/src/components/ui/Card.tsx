import React from 'react';
import './ui.css';

interface CardProps {
  padding?: 'compact' | 'normal';
  interactive?: boolean;
  className?: string;
  onClick?: () => void;
  children: React.ReactNode;
}

export const Card: React.FC<CardProps> = ({
  padding = 'normal', interactive = false, className = '', onClick, children,
}) => (
  <div
    className={`ui-card ${padding === 'compact' ? 'ui-card--compact' : ''} ${interactive ? 'ui-card--interactive' : ''} ${className}`.trim()}
    onClick={onClick}
  >
    {children}
  </div>
);
