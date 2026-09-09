import React, {HTMLAttributes, forwardRef} from 'react';
import clsx from 'clsx';
import './Modal.css';

export interface ModalProps extends HTMLAttributes<HTMLDivElement> {
  open?: boolean;
  onClose?: () => void;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}

export const Modal = forwardRef<HTMLDivElement, ModalProps>(
  ({children, className, open = false, onClose, size = 'md', ...props}, ref) => {
    if (!open) return null;

    const handleBackdropClick = (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) {
        onClose?.();
      }
    };

    return (
      <div className="modal__backdrop" onClick={handleBackdropClick}>
        <div
          ref={ref}
          className={clsx('modal', `modal--${size}`, className)}
          role="dialog"
          aria-modal="true"
          {...props}
        >
          {children}
        </div>
      </div>
    );
  }
);

Modal.displayName = 'Modal';

export interface ModalHeaderProps extends HTMLAttributes<HTMLDivElement> {}

export const ModalHeader = forwardRef<HTMLDivElement, ModalHeaderProps>(
  ({children, className, ...props}, ref) => {
    return (
      <div ref={ref} className={clsx('modal__header', className)} {...props}>
        {children}
      </div>
    );
  }
);

ModalHeader.displayName = 'ModalHeader';

export interface ModalTitleProps extends HTMLAttributes<HTMLHeadingElement> {}

export const ModalTitle = forwardRef<HTMLHeadingElement, ModalTitleProps>(
  ({children, className, ...props}, ref) => {
    return (
      <h2 ref={ref} className={clsx('modal__title', className)} {...props}>
        {children}
      </h2>
    );
  }
);

ModalTitle.displayName = 'ModalTitle';

export interface ModalBodyProps extends HTMLAttributes<HTMLDivElement> {}

export const ModalBody = forwardRef<HTMLDivElement, ModalBodyProps>(
  ({children, className, ...props}, ref) => {
    return (
      <div ref={ref} className={clsx('modal__body', className)} {...props}>
        {children}
      </div>
    );
  }
);

ModalBody.displayName = 'ModalBody';

export interface ModalFooterProps extends HTMLAttributes<HTMLDivElement> {}

export const ModalFooter = forwardRef<HTMLDivElement, ModalFooterProps>(
  ({children, className, ...props}, ref) => {
    return (
      <div ref={ref} className={clsx('modal__footer', className)} {...props}>
        {children}
      </div>
    );
  }
);

ModalFooter.displayName = 'ModalFooter';
