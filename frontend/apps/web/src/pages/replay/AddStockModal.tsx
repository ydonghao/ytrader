import {useEffect, useState} from 'react';
import * as api from './api';
import {useReplayStore, viewDate} from './store';
import type {BoardRow} from './types';

type TabKey = 'search' | 'screener' | 'watchlist' | 'board';

const SCREENER_MODES: {key: string; label: string}[] = [
  {key: 'magic_formula', label: '神奇公式'},
  {key: 'dividend', label: '红利'},
  {key: 'fscore', label: 'F-Score'},
  {key: 'dividend_value', label: '红利低估'},
  {key: 'quality', label: '质量'},
];

export const AddStockModal: React.FC<{open: boolean; onClose: () => void}> = ({
  open, onClose,
}) => {
  const vd = useReplayStore(viewDate);
  const addSymbol = useReplayStore((s) => s.addSymbol);
  const [tab, setTab] = useState<TabKey>('search');
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<{symbol: string; name: string}[]>([]);
  const [mode, setMode] = useState('dividend_value');
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [groups, setGroups] = useState<{id: number; name: string}[]>([]);
  const [items, setItems] = useState<{symbol: string}[]>([]);
  const [boardRows, setBoardRows] = useState<BoardRow[]>([]);
  const [boardType, setBoardType] = useState<'gainers' | 'amount'>('gainers');
  const [hint, setHint] = useState<string | null>(null);

  const add = async (symbol: string, name?: string) => {
    await addSymbol(symbol, name);
    setHint(null);
    onClose();
  };

  useEffect(() => {
    if (!open || tab !== 'watchlist') return;
    let off = false;
    void api.listWatchGroups().then((r) => {
      if (!off && r.code === 0) setGroups(r.data);
    });
    return () => { off = true; };
  }, [open, tab]);

  useEffect(() => {
    if (!open || tab !== 'board' || !vd) return;
    let off = false;
    void api.fetchBoard(vd, boardType).then((r) => {
      if (off) return;
      if (r.code === 0) setBoardRows(r.data);
      else setHint(r.msg);
    });
    return () => { off = true; };
  }, [open, tab, boardType, vd]);

  if (!open) return null;

  const doSearch = async () => {
    if (!q.trim()) return;
    const r = await api.searchSymbols(q.trim());
    if (r.code === 0) setHits(r.data);
  };

  const doScreen = async () => {
    if (!vd) return;
    setHint('以当日口径筛选中（财报为报告期滞后60天近似）…');
    const r = await api.runScreener(mode, 30, vd);
    if (r.code === 0) {
      setRows(r.data.ranked_list ?? []);
      setHint(null);
    } else setHint(r.msg || '筛选失败');
  };

  return (
    <div className="replay-modal-mask" onClick={onClose}>
      <div className="replay-modal" onClick={(e) => e.stopPropagation()}>
        <div className="replay-tabs">
          {([['search', '搜索'], ['screener', '当时选股器'],
             ['watchlist', '自选股导入'], ['board', '当日榜单']] as const)
            .map(([k, label]) => (
              <button key={k}
                className={`replay-btn${tab === k ? ' primary' : ''}`}
                onClick={() => setTab(k)}>
                {label}
              </button>
            ))}
          <span style={{flex: 1}} />
          <button className="replay-btn" onClick={onClose}>关闭</button>
        </div>
        <div className="replay-hint" style={{marginBottom: 8}}>
          当前日期 {vd}：只使用这一天真实可得的信息。
          {tab === 'watchlist' && ' ⚠ 自选股是你“现在”的收藏，含轻微未来泄漏。'}
          {tab === 'screener' && ' 财报口径：报告期 ≤ 当日−60天（库无披露日列）。'}
        </div>
        {hint && <div className="replay-error">{hint}</div>}

        {tab === 'search' && (
          <>
            <div style={{display: 'flex', gap: 8, marginBottom: 8}}>
              <input className="replay-input" style={{marginBottom: 0}}
                placeholder="代码 / 名称" value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void doSearch()} />
              <button className="replay-btn primary"
                onClick={() => void doSearch()}>搜索</button>
            </div>
            {hits.map((x) => (
              <div key={x.symbol} className="replay-pool-item"
                onClick={() => void add(x.symbol, x.name)}>
                <span>{x.name} {x.symbol}</span>
                <span className="replay-hint">加入 →</span>
              </div>
            ))}
          </>
        )}

        {tab === 'screener' && (
          <>
            <div style={{display: 'flex', gap: 8, marginBottom: 8}}>
              <select className="replay-input" style={{width: 160, marginBottom: 0}}
                value={mode} onChange={(e) => setMode(e.target.value)}>
                {SCREENER_MODES.map((m) => (
                  <option key={m.key} value={m.key}>{m.label}</option>
                ))}
              </select>
              <button className="replay-btn primary"
                onClick={() => void doScreen()}>运行</button>
            </div>
            <table className="replay-table">
              <thead>
                <tr><th>标的</th><th>评分</th><th>PE_TTM</th><th>ROE</th><th /></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={String(r.symbol)}>
                    <td>{String(r.symbol)}</td>
                    <td>{typeof r.score === 'number' ? r.score.toFixed(1) : '—'}</td>
                    <td>{typeof r.pe_ttm === 'number' ? r.pe_ttm.toFixed(1) : '—'}</td>
                    <td>{typeof r.roe === 'number' ? `${r.roe.toFixed(1)}%` : '—'}</td>
                    <td>
                      <button className="replay-btn"
                        onClick={() => void add(String(r.symbol))}>
                        加入
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        {tab === 'watchlist' && (
          <>
            <div style={{display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap'}}>
              {groups.map((g) => (
                <button key={g.id} className="replay-btn"
                  onClick={() => void api.listWatchItems(g.id).then((r) => {
                    if (r.code === 0) setItems(r.data);
                  })}>
                  {g.name}
                </button>
              ))}
            </div>
            {items.map((it) => (
              <div key={it.symbol} className="replay-pool-item"
                onClick={() => void add(it.symbol)}>
                <span>{it.symbol}</span>
                <span className="replay-hint">加入 →</span>
              </div>
            ))}
          </>
        )}

        {tab === 'board' && (
          <>
            <div style={{display: 'flex', gap: 8, marginBottom: 8}}>
              {(['gainers', 'amount'] as const).map((t) => (
                <button key={t}
                  className={`replay-btn${boardType === t ? ' primary' : ''}`}
                  onClick={() => setBoardType(t)}>
                  {t === 'gainers' ? '涨幅榜' : '成交额榜'}
                </button>
              ))}
            </div>
            <table className="replay-table">
              <thead>
                <tr><th>标的</th><th>名称</th><th>收盘</th><th>涨幅</th><th /></tr>
              </thead>
              <tbody>
                {boardRows.map((r) => (
                  <tr key={r.symbol}>
                    <td>{r.symbol}</td>
                    <td>{r.name}</td>
                    <td>{r.close.toFixed(2)}</td>
                    <td className={r.pct_chg >= 0 ? 'is-up' : 'is-down'}>
                      {r.pct_chg >= 0 ? '+' : ''}{r.pct_chg.toFixed(2)}%
                    </td>
                    <td>
                      <button className="replay-btn"
                        onClick={() => void add(r.symbol, r.name)}>
                        加入
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
};
