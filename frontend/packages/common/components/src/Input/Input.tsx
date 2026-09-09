import React, {InputHTMLAttributes, forwardRef} from 'react';
import clsx from 'clsx';
import './Input.css';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
  leftAddon?: React.ReactNode;
  rightAddon?: React.ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({className, label, error, hint, leftAddon, rightAddon, id, ...props}, ref) => {
    const inputId = id || `input-${Math.random().toString(36).slice(2, 9)}`;

    return (
      <div className={clsx('input-wrapper', {'input-wrapper--error': error}, className)}>
        {label && (
          <label htmlFor={inputId} className="input__label">
            {label}
          </label>
        )}
        <div className="input__container">
          {leftAddon && <span className="input__addon input__addon--left">{leftAddon}</span>}
          <input ref={ref} id={inputId} className="input" {...props} />
          {rightAddon && <span className="input__addon input__addon--right">{rightAddon}</span>}
        </div>
        {error && <span className="input__error">{error}</span>}
        {hint && !error && <span className="input__hint">{hint}</span>}
      </div>
    );
  }
);

Input.displayName = 'Input';

export interface NumberInputProps extends Omit<InputProps, 'type' | 'onChange'> {
  value: number | string;
  onChange: (value: number | string) => void;
  min?: number;
  max?: number;
  step?: number;
}

export const NumberInput = forwardRef<HTMLInputElement, NumberInputProps>(
  ({value, onChange, min, max, step = 1, ...props}, ref) => {
    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.value;
      if (val === '') {
        onChange('');
        return;
      }
      const num = parseFloat(val);
      if (!isNaN(num)) {
        if (min !== undefined && num < min) return;
        if (max !== undefined && num > max) return;
        onChange(num);
      }
    };

    return (
      <Input
        ref={ref}
        type="text"
        inputMode="decimal"
        value={value}
        onChange={handleChange}
        {...props}
      />
    );
  }
);

NumberInput.displayName = 'NumberInput';
