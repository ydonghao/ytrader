/**
 * Stock Select - Async searchable dropdown for A-share stock symbols.
 *
 * Searches server-side via /market/search (debounced) instead of loading the
 * full ~5000-symbol list, so the dropdown never freezes the page.
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { searchSymbols, type StockSearchResult } from './api';
import './StockSelect.css';

interface StockSelectProps {
  value: string;
  onChange: (symbol: string) => void;
  market?: string;
}

const MIN_QUERY = 1;
const SEARCH_LIMIT = 50;
const DEBOUNCE_MS = 200;

export const StockSelect: React.FC<StockSelectProps> = ({
  value,
  onChange,
  market = 'A',
}) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<StockSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const reqIdRef = useRef(0);

  const runSearch = useCallback(
    async (q: string) => {
      if (q.trim().length < MIN_QUERY) {
        setResults([]);
        setSearching(false);
        return;
      }
      const reqId = ++reqIdRef.current;
      setSearching(true);
      try {
        const hits = await searchSymbols(q, market, SEARCH_LIMIT);
        // Drop stale responses (a newer keystroke superseded this one).
        if (reqId === reqIdRef.current) setResults(hits);
      } catch {
        if (reqId === reqIdRef.current) setResults([]);
      } finally {
        if (reqId === reqIdRef.current) setSearching(false);
      }
    },
    [market],
  );

  // Close dropdown when clicking outside.
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // Focus input + reset state when opening.
  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus();
      setQuery('');
      setResults([]);
    }
  }, [open]);

  // Debounced search on query change.
  useEffect(() => {
    if (!open) return;
    if (query.trim().length < MIN_QUERY) {
      setResults([]);
      return;
    }
    const t = setTimeout(() => runSearch(query), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [query, open, runSearch]);

  const handleSelect = (symbol: string) => {
    onChange(symbol);
    setOpen(false);
    setQuery('');
    setResults([]);
  };

  const noResults =
    !searching && results.length === 0 && query.trim().length >= MIN_QUERY;

  return (
    <div className="stock-select" ref={wrapperRef}>
      <button
        type="button"
        className="stock-select__trigger"
        onClick={() => setOpen(!open)}
      >
        <span className="stock-select__value">{value || '选择股票'}</span>
        <span className="stock-select__arrow">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="stock-select__dropdown">
          <div className="stock-select__search-wrapper">
            <input
              ref={inputRef}
              type="text"
              className="stock-select__search"
              placeholder="搜索股票代码/名称..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <ul className="stock-select__list">
            {searching && <li className="stock-select__empty">搜索中...</li>}
            {noResults && <li className="stock-select__empty">未找到匹配股票</li>}
            {!searching &&
              !noResults &&
              query.trim().length < MIN_QUERY && (
                <li className="stock-select__empty">输入代码或名称开始搜索</li>
              )}
            {results.map((r) => (
              <li key={r.symbol}>
                <button
                  type="button"
                  className={`stock-select__option ${
                    r.symbol === value ? 'stock-select__option--active' : ''
                  }`}
                  onClick={() => handleSelect(r.symbol)}
                >
                  <span className="stock-select__symbol">{r.symbol}</span>
                  {r.name && r.name !== r.symbol && (
                    <span className="stock-select__name">{r.name}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
