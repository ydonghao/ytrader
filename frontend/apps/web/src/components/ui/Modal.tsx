import React, {useEffect} from 'react';
import {createPortal} from 'react-dom';
import './ui.css';

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  width?: number;
  footer?: React.ReactNode;
  children: React.ReactNode;
}

export const Modal: React.FC<ModalProps> = ({open, title, onClose, width = 480, footer, children}) => {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div className="ui-modal-overlay" onClick={onClose}>
      <div className="ui-modal" style={{width: `min(90vw, ${width}px)`}} onClick={e => e.stopPropagation()}>
        <div className="ui-modal__header">
          <span className="ui-modal__title">{title}</span>
          <button type="button" className="ui-modal__close" onClick={onClose} aria-label="关闭">×</button>
        </div>
        <div className="ui-modal__body">{children}</div>
        {footer && <div className="ui-modal__footer">{footer}</div>}
      </div>
    </div>,
    document.body
  );
};
