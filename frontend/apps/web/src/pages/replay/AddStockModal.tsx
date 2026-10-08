import {useEffect, useState} from 'react';
import * as api from './api';
import {useBlind, useDayLabel} from './BlindMask';
import {useReplayStore, viewDate} from './store';
import type {BoardRow} from './types';

type TabKey = 'search' | 'screener' | 'watchlist' | 'board' | 'portfolio';

const SCREENER_MODES: {key: string; label: string}[] = [
  {key: 'magic_formula', label: '神奇公式'},
  {key: 'dividend', label: '红利'},
  {key: 'fscore', label: 'F-Score'},
  {key: 'dividend_value', label: '红利低估'},
  {key: 'quality', label: '质量'},
];

// AI 建组合: 档位(股息/蓝筹/成长 配额)与类别中文映射
const PROFILES: [string, string][] = [
  ['defensive', '防御(股息70/蓝筹30)'],
  ['balanced', '均衡(50/40/10)'],
  ['aggressive', '进取(30/50/20)'],
  ['radical', '激进(成长70)'],
];

const CATEGORY_ZH: Record<string, string> = {
  dividend: '股息', bluechip: '蓝筹', growth: '成长',
};

export const AddStockModal: React.FC<{open: boolean; onClose: () => void}> = ({
  open, onClose,
}) => {
  const vd = useReplayStore(viewDate);
  const dayLabel = useDayLabel(); // 盲盒期真实日期脱敏为「第N天」
  const blind = useBlind();       // 拟真航行中:禁含当日信息的页签(防未来泄漏)
  const addSymbol = useReplayStore((s) => s.addSymbol);
  const addSymbolsBatch = useReplayStore((s) => s.addSymbols);
  const cash = useReplayStore((s) => s.cash);
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
  // portfolio 页签(组件挂载时 Cockpit 已带会话, cash 即会话现金; 只取初值)
  const [profile, setProfile] = useState('balanced');
  const [count, setCount] = useState(6);
  const [capital, setCapital] = useState(cash);
  const [plan, setPlan] = useState<api.GeneratePortfolioResp | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  // 入池/提案操作 in-flight 防重：双击不再并发触发 addSymbols/addSymbol
  const [busy, setBusy] = useState(false);

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

  // I4: 拟真航行中禁「自选股导入/AI建组合」——两者都建立在"现在"的信息
  // (当前收藏/当前沪深300成分)上,在盲盒里等于偷看未来
  const gatedTab = (k: TabKey): boolean =>
    blind && (k === 'watchlist' || k === 'portfolio');
  const tabGated = gatedTab(tab);

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

  const doGenerate = async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (!vd) return;
      setHint('以当日口径生成提案中（收盘价与估值/PE带均截至当日）…');
      const r = await api.generatePortfolio({
        total_capital: capital, risk_profile: profile,
        stock_count: count, as_of: vd,
      });
      if (r.code === 0) {
        setPlan(r.data);
        setPicked(new Set(r.data.legs.map((l) => l.symbol)));
        setHint(null);
      } else setHint(r.msg || '生成失败');
    } finally {
      setBusy(false);
    }
  };

  const togglePick = (symbol: string, on: boolean) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(symbol);
      else next.delete(symbol);
      return next;
    });
  };

  const addTop10 = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const syms = rows.slice(0, 10).map((r) => String(r.symbol));
      const r = await addSymbolsBatch(syms);
      setHint(`已入池 ${r.added} 只${r.failed.length
        ? `,失败 ${r.failed.length} 只(${r.failed.join(',')})` : ''}`);
    } finally {
      setBusy(false);
    }
  };

  const addPicked = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await addSymbolsBatch([...picked]);
      setHint(`已入池 ${r.added} 只${r.failed.length
        ? `,失败 ${r.failed.length} 只(${r.failed.join(',')})` : ''}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="replay-modal-mask" onClick={onClose}>
      <div className="replay-modal" onClick={(e) => e.stopPropagation()}>
        <div className="replay-tabs">
          {([['search', '搜索'], ['screener', '当时选股器'],
             ['watchlist', '自选股导入'], ['board', '当日榜单'],
             ['portfolio', 'AI建组合']] as const)
            .map(([k, label]) => (
              <button key={k}
                className={`replay-btn${tab === k ? ' primary' : ''}`}
                disabled={gatedTab(k)}
                title={gatedTab(k)
                  ? '盲盒航行中已禁用（含当日信息，防未来泄漏）'
                  : undefined}
                onClick={() => setTab(k)}>
                {label}
              </button>
            ))}
          <span style={{flex: 1}} />
          <button className="replay-btn" onClick={onClose}>关闭</button>
        </div>
        <div className="replay-hint" style={{marginBottom: 8}}>
          视角日 {dayLabel(vd)}：只使用此日真实可得的信息。
          {tab === 'watchlist' && ' ⚠ 自选股是你“现在”的收藏，含轻微未来泄漏（盲盒航行中已禁用此页签）。'}
          {tab === 'screener' && ' 财报口径：报告期 ≤ 当日−60天（库无披露日列）。'}
          {tab === 'portfolio' && ' 提案现价/估值/PE带均为当日口径，蓝筹类按当前沪深300成分近似（快照口径，含轻微未来泄漏），可勾选后批量入池；盲盒航行中已禁用此页签。'}
        </div>
        {hint && <div className="replay-error">{hint}</div>}
        {tabGated && (
          <div className="replay-hint" style={{padding: 20}}>
            盲盒航行中已禁用（含当日信息，防未来泄漏）——揭晓后可用。
          </div>
        )}

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
              <button className="replay-btn"
                disabled={busy || !rows.length}
                onClick={() => void addTop10()}>
                一键入池 Top10
              </button>
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

        {tab === 'watchlist' && !tabGated && (
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

        {tab === 'portfolio' && !tabGated && (
          <>
            <div style={{display: 'flex', gap: 8, marginBottom: 8,
                         alignItems: 'center', flexWrap: 'wrap'}}>
              <select className="replay-input" style={{width: 170, marginBottom: 0}}
                value={profile} onChange={(e) => setProfile(e.target.value)}>
                {PROFILES.map(([k, label]) => (
                  <option key={k} value={k}>{label}</option>
                ))}
              </select>
              <select className="replay-input" style={{width: 70, marginBottom: 0}}
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}>
                {[5, 6, 7, 8].map((n) => (
                  <option key={n} value={n}>{n}只</option>
                ))}
              </select>
              <input className="replay-input" style={{width: 120, marginBottom: 0}}
                type="number" title="总资金(默认会话现金)"
                value={capital}
                onChange={(e) => setCapital(Number(e.target.value))} />
              <button className="replay-btn primary"
                disabled={busy || !(capital > 0)}
                onClick={() => void doGenerate()}>生成提案</button>
            </div>
            {plan && (
              <>
                {plan.warnings.length > 0 && (
                  <div className="replay-hint" style={{marginBottom: 8}}>
                    ⚠ {plan.warnings.join('；')}
                  </div>
                )}
                <table className="replay-table">
                  <thead>
                    <tr>
                      <th /><th>标的</th><th>类别</th><th>权重</th>
                      <th>当日价</th><th>PE带</th>
                    </tr>
                  </thead>
                  <tbody>
                    {plan.legs.map((l) => (
                      <tr key={l.symbol}>
                        <td>
                          <input type="checkbox"
                            checked={picked.has(l.symbol)}
                            onChange={(e) =>
                              togglePick(l.symbol, e.target.checked)} />
                        </td>
                        <td>{l.symbol} {l.name}</td>
                        <td>{CATEGORY_ZH[l.category] ?? l.category}</td>
                        <td>{(l.target_weight * 100).toFixed(1)}%</td>
                        <td>{l.current_price.toFixed(2)}</td>
                        <td>{l.pe_band?.state ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{display: 'flex', gap: 8, marginTop: 8,
                             alignItems: 'center'}}>
                  <button className="replay-btn primary"
                    disabled={busy || !picked.size}
                    onClick={() => void addPicked()}>
                    勾选入池 ({picked.size})
                  </button>
                  <span className="replay-hint">
                    可投 {plan.investable_capital.toLocaleString()}（现金储备10%）
                  </span>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
};
