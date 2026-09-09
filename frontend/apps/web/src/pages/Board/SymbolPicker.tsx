/**
 * 标的选择器 — 输入即搜(/market/search 300ms 防抖),
 * 结果合并核心指数兜底(stock_info 搜索可能不含指数)。
 */
import React, {useEffect, useRef, useState} from 'react';
import {searchSymbols} from '../../components/MarketPage/api';
import {CORE_INDEX_SYMBOLS} from './boardTypes';

export interface SymbolPick {
  symbol: string;
  name: string;
}

interface SymbolPickerProps {
  value: SymbolPick | null;
  onChange: (v: SymbolPick) => void;
  placeholder?: string;
}

const DEBOUNCE_MS = 300;

export const SymbolPicker: React.FC<SymbolPickerProps> = ({
  value, onChange, placeholder = '输入代码/名称/拼音搜索',
}) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SymbolPick[]>([]);
  const [searching, setSearching] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const reqIdRef = useRef(0);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, []);

  useEffect(() => {
    const q = query.trim();
    if (!open || q.length < 1) {
      reqIdRef.current++;  // 作废在途响应
      setResults([]);
      setSearching(false);
      return;
    }
    // 进入防抖即置 searching,避免下拉先闪「无匹配标的」
    setSearching(true);
    const t = setTimeout(async () => {
      const reqId = ++reqIdRef.current;
      const lower = q.toLowerCase();
      const indexHits = CORE_INDEX_SYMBOLS.filter(
        (i) =>
          i.symbol.toLowerCase().includes(lower) ||
          i.name.toLowerCase().includes(lower) ||
          i.symbol.slice(2).startsWith(q),
      );
      let hits: SymbolPick[] = [];
      try {
        hits = await searchSymbols(q, 'A', 20);
      } catch { hits = []; }
      if (reqId !== reqIdRef.current) return;
      // 指数在前,去重
      const seen = new Set(indexHits.map((i) => i.symbol));
      setResults([...indexHits, ...hits.filter((h) => !seen.has(h.symbol))]);
      setSearching(false);
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(t);
      reqIdRef.current++;  // 作废上一 query 的在途响应
    };
  }, [query, open]);

  const pick = (v: SymbolPick) => {
    onChange(v);
    setOpen(false);
    setQuery('');
    setResults([]);
  };

  const q = query.trim();
  const showDefault =
    open && q.length < 1 && !!value;
  const noResults =
    !searching && q.length >= 1 && results.length === 0;

  return (
    <div className="board-symbolpick" ref={wrapperRef}>
      <input
        className="board-input"
        placeholder={placeholder}
        value={open ? query : value ? `${value.name}(${value.symbol})` : ''}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
      />
      {value && !open && (
        <div className="board-symbolpick__picked">已选:{value.name}({value.symbol})</div>
      )}
      {showDefault && (
        <div className="board-symbolpick__hint">输入代码或名称搜索标的</div>
      )}
      {open && q.length >= 1 && (
        <div className="board-symbolpick__dropdown">
          {searching && <div className="board-symbolpick__empty">搜索中…</div>}
          {noResults && <div className="board-symbolpick__empty">无匹配标的</div>}
          {results.map((r) => (
            <button
              key={r.symbol}
              type="button"
              className="board-symbolpick__option"
              onClick={() => pick(r)}
            >
              <span className="board-symbolpick__code">{r.symbol}</span>
              <span className="board-symbolpick__name">{r.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
