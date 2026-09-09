import React from 'react';
import {Button} from './Button';
import './ui.css';

interface StateViewProps {
  state: 'loading' | 'empty' | 'error';
  text?: string;
  onRetry?: () => void;
}

const DEFAULT_TEXT = {loading: '加载中…', empty: '暂无数据', error: '加载失败'} as const;

export const StateView: React.FC<StateViewProps> = ({state, text, onRetry}) => (
  <div className={`ui-state ui-state--${state}`}>
    {state === 'loading' && <span className="ui-state__spinner" />}
    {state === 'empty' && <span className="ui-state__icon">◍</span>}
    <span>{text ?? DEFAULT_TEXT[state]}</span>
    {state === 'error' && onRetry && <Button variant="secondary" size="sm" onClick={onRetry}>重试</Button>}
  </div>
);
