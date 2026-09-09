import React, {SelectHTMLAttributes, forwardRef} from 'react';
import clsx from 'clsx';
import './Select.css';

export interface SelectOption {
  label: string;
  value: string | number;
  disabled?: boolean;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'onChange'> {
  options: SelectOption[];
  value?: string | number;
  onChange?: (value: string) => void;
  label?: string;
  error?: string;
  placeholder?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({className, options, value, onChange, label, error, placeholder, id, ...props}, ref) => {
    const selectId = id || `select-${Math.random().toString(36).slice(2, 9)}`;

    return (
      <div className={clsx('select-wrapper', {'select-wrapper--error': error}, className)}>
        {label && (
          <label htmlFor={selectId} className="select__label">
            {label}
          </label>
        )}
        <div className="select__container">
          <select
            ref={ref}
            id={selectId}
            className="select"
            value={value}
            onChange={e => onChange?.(e.target.value)}
            {...props}
          >
            {placeholder && (
              <option value="" disabled>
                {placeholder}
              </option>
            )}
            {options.map(option => (
              <option key={option.value} value={option.value} disabled={option.disabled}>
                {option.label}
              </option>
            ))}
          </select>
          <span className="select__arrow" />
        </div>
        {error && <span className="select__error">{error}</span>}
      </div>
    );
  }
);

Select.displayName = 'Select';
