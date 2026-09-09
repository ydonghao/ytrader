import React from 'react';
import './ui.css';

interface ButtonProps {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md';
  loading?: boolean;
  disabled?: boolean;
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void;
  className?: string;
  title?: string;
  type?: 'button' | 'submit';
  children: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'secondary', size = 'md', loading = false, disabled = false,
  onClick, className = '', title, type = 'button', children,
}) => (
  <button
    type={type}
    className={`ui-btn ui-btn--${variant} ui-btn--${size} ${className}`.trim()}
    onClick={onClick} disabled={disabled || loading} title={title}
  >
    {loading && <span className="ui-btn__spinner" />}
    {children}
  </button>
);
