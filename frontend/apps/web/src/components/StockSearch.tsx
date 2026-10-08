/**
 * 股票搜索下拉（原 Financial.tsx 内组件抽出共享，买入体检页复用）。
 * 数据源 /market/search；防抖 200ms；reqId 守卫丢弃过期响应。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { getApiBase } from '../lib/api';
import './StockSearch.css';

export function StockSearch({ value, onSelect }: { value: string; onSelect: (sym: string) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<{ symbol: string; name: string }[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const reqIdRef = useRef(0);

  const search = useCallback(async (q: string) => {
    if (q.trim().length < 1) { setResults([]); setLoading(false); return; }
    const reqId = ++reqIdRef.current;
    setLoading(true);
    try {
      const res = await fetch(`${getApiBase()}/market/search?q=${encodeURIComponent(q)}&limit=10`);
      const json = await res.json();
      if (reqId !== reqIdRef.current) return;
      if (json.code === 0 && json.data) {
        setResults(json.data.map((s: any) => ({ symbol: s.symbol, name: s.name || s.symbol })));
      }
    } catch { /* ignore */ }
    if (reqId === reqIdRef.current) setLoading(false);
  }, []);

  useEffect(() => {
    const q = query;
    const t = setTimeout(() => search(q), 200);
    return () => clearTimeout(t);
  }, [query, search]);

  return (
    <div className="fin-search">
      <input
        className="fin-search__input"
        placeholder="搜索股票代码/名称（如 600519 或 茅台）"
        value={query}
        onChange={e => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 200)}
      />
      {open && results.length > 0 && (
        <div className="fin-search__dropdown">
          {results.map(r => (
            <div
              key={r.symbol}
              className="fin-search__item"
              onClick={() => { onSelect(r.symbol); setQuery(`${r.symbol} ${r.name}`); setOpen(false); }}
            >
              <span className="fin-search__symbol">{r.symbol}</span>
              <span className="fin-search__name">{r.name}</span>
            </div>
          ))}
        </div>
      )}
      {open && !loading && results.length === 0 && query.length >= 1 && (
        <div className="fin-search__dropdown"><div className="fin-search__empty">无匹配结果</div></div>
      )}
    </div>
  );
}
