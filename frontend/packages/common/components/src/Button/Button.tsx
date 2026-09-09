import React, {ButtonHTMLAttributes, forwardRef} from 'react';
import clsx from 'clsx';
import './Button.css';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'success' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  fullWidth?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      children,
      className,
      variant = 'primary',
      size = 'md',
      loading = false,
      fullWidth = false,
      disabled,
      ...props
    },
    ref
  ) => {
    return (
      <button
        ref={ref}
        className={clsx(
          'btn',
          `btn--${variant}`,
          `btn--${size}`,
          {
            'btn--loading': loading,
            'btn--full-width': fullWidth,
          },
          className
        )}
        disabled={disabled || loading}
        {...props}
      >
        {loading && <span className="btn__spinner" />}
        <span className={clsx({'btn__content--hidden': loading})}>{children}</span>
      </button>
    );
  }
);

Button.displayName = 'Button';
