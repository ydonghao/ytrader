import React, {HTMLAttributes, forwardRef} from 'react';
import clsx from 'clsx';
import './Badge.css';

export type BadgeVariant = 'default' | 'success' | 'danger' | 'warning' | 'info';
export type BadgeSize = 'sm' | 'md';

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  size?: BadgeSize;
  dot?: boolean;
}

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(
  ({children, className, variant = 'default', size = 'md', dot = false, ...props}, ref) => {
    return (
      <span
        ref={ref}
        className={clsx('badge', `badge--${variant}`, `badge--${size}`, className)}
        {...props}
      >
        {dot && <span className="badge__dot" />}
        {children}
      </span>
    );
  }
);

Badge.displayName = 'Badge';

export interface StatusBadgeProps extends Omit<BadgeProps, 'variant'> {
  status: 'online' | 'offline' | 'pending' | 'error' | 'success';
}

const statusVariantMap: Record<StatusBadgeProps['status'], BadgeVariant> = {
  online: 'success',
  offline: 'default',
  pending: 'warning',
  error: 'danger',
  success: 'success',
};

export const StatusBadge = forwardRef<HTMLSpanElement, StatusBadgeProps>(
  ({status, ...props}, ref) => {
    return <Badge ref={ref} variant={statusVariantMap[status]} dot {...props} />;
  }
);

StatusBadge.displayName = 'StatusBadge';

export interface PnlBadgeProps extends Omit<BadgeProps, 'variant'> {
  value: number;
}

export const PnlBadge = forwardRef<HTMLSpanElement, PnlBadgeProps>(
  ({value, ...props}, ref) => {
    const variant = value > 0 ? 'success' : value < 0 ? 'danger' : 'default';
    const sign = value > 0 ? '+' : '';
    return (
      <Badge ref={ref} variant={variant} {...props}>
        {sign}{typeof value === 'number' ? value.toFixed(2) : value}%
      </Badge>
    );
  }
);

PnlBadge.displayName = 'PnlBadge';
