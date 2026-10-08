/**
 * 买入体检(课程21集《股票投资前的检查清单》)。
 * 四区21项:自动12(状态点 ok/watch/risk/missing)+手动9(可编辑表单)。
 * 设计决策:只展示不下结论——无总体红绿灯/买不买判定。
 * 手动项研究清楚了再填(糊弄的数据不如不填);>90天未更新提示复检。
 * 手动项状态用小徽章(C17);自动项保持状态点。防抖 800ms 自动保存。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PageHeader, StateView } from '../components/ui';
import { StockSearch } from '../components/StockSearch';
import { getApiBase } from '../lib/api';
import { ensurePrefixed } from '../lib/symbol';
import { daysSince, formatDaysAgo } from './checklistHelpers';
import './Checklist.css';

export interface ChecklistItem {
  key: string;
  type: 'auto' | 'manual';
  section: string;
  title: string;
  status: string;              // auto: ok/watch/risk/missing; manual: filled/pending
  value?: string | null;
  detail?: string | null;
  hint?: string;
  course?: string;             // 手动项课程口径
  input_type?: 'text' | 'choice' | 'choice+text';
  choices?: string[];
  value_text?: string | null;
  value_choice?: string | null;
  updated_at?: string | null;
  editable?: boolean;          // 2.5 议价专属
  note_key?: string;
  note_text?: string | null;
}

export interface ChecklistSection { key: string; title: string; items: ChecklistItem[]; }

/** 参考区数据(Important#1):后端 GET 响应 references 键,纯展示、全部可缺省。 */
export interface ChecklistReferences {
  profile?: { name?: string; market?: string; total_mv?: number; industry?: string } | null;
  moat?: {
    pricing_power_score?: number;            // spec 假设字段
    pricing_power?: { score?: number } | null; // moat_report 实际序列化形状
    moat_score?: number;
  } | null;
  shareholders?: { name: string; ratio: number; type?: string | null }[] | null;
  industry_latest?: { cr4?: number; hhi?: number; report_date?: string } | null;
}
export interface ChecklistData {
  symbol: string;
  sections: ChecklistSection[];
  manual_progress: { filled: number; total: number };
  auto_progress: { ok: number; watch: number; risk: number; missing: number };
  references?: ChecklistReferences;
  note?: string;
}

const STATUS_DOT: Record<string, string> = {
  ok: 'chk-dot chk-dot--ok', watch: 'chk-dot chk-dot--watch',
  risk: 'chk-dot chk-dot--risk', missing: 'chk-dot chk-dot--missing',
};
const STATUS_TEXT: Record<string, string> = {
  ok: '✓', watch: '⚠', risk: '✗', missing: '—',
};

/** 参考区(Important#1):按手动项 key 注入后端已供参考数据(灰字 hint)。
 *  全部字段判空,缺失不渲染;不加新依赖、不新增网络请求。 */
function ItemReference({ itemKey, refs }: {
  itemKey: string;
  refs?: ChecklistReferences;
}) {
  if (!refs) return null;
  if (itemKey === 'pricing_power') {
    // 1.4 定价权:兼容两种字段形状(见 ChecklistReferences.moat 注释)
    const score = refs.moat?.pricing_power_score ?? refs.moat?.pricing_power?.score;
    if (typeof score === 'number') {
      return <div className="chk-item__hint">参考:定价权评分 {score}(0-100)</div>;
    }
    return null;
  }
  if (itemKey === 'competitive_pattern') {
    // 2.3 竞争格局:CR4 有值才渲染,HHI 缺失时只显示 CR4
    const il = refs.industry_latest;
    if (!il || typeof il.cr4 !== 'number') return null;
    const hhi = typeof il.hhi === 'number' ? ` HHI=${il.hhi}` : '';
    return <div className="chk-item__hint">参考:行业CR4={il.cr4}{hhi}</div>;
  }
  if (itemKey === 'ownership_type') {
    // 1.6 股权架构:前十大股东前三行
    const holders = refs.shareholders ?? [];
    if (!holders.length) return null;
    return (
      <div className="chk-item__hint">
        {holders.slice(0, 3).map((h, i) => (
          <div key={`${h.name}-${i}`}>{h.name} {h.ratio}%</div>
        ))}
      </div>
    );
  }
  return null;
}

function AutoItem({ it, symbol, onSaved }: {
  it: ChecklistItem;
  symbol: string;
  onSaved: (key: string, symbol: string, filled?: boolean) => void;
}) {
  // 2.5 议价备注:自动结论保留在上方,下方可编辑补充(同一防抖保存口径)
  const [note, setNote] = useState(it.note_text ?? '');
  const dirtyRef = useRef(false);
  useEffect(() => {
    if (!dirtyRef.current || !it.note_key) return;
    const t = setTimeout(() => {
      dirtyRef.current = false;
      fetch(`${getApiBase()}/checklist/${symbol}/items`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: [{ item_key: it.note_key!, value_text: note }] }),
      })
        .then(r => (r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status))))
        .then(j => { if (j.code === 0 && onSaved) onSaved(it.key, symbol); })
        .catch(() => { /* 静默:下次编辑再存 */ });
    }, 800);
    return () => clearTimeout(t);
  }, [note, it.note_key, it.key, symbol, onSaved]);

  return (
    <div className="chk-item">
      <span className={STATUS_DOT[it.status]} title={it.status}>{STATUS_TEXT[it.status]}</span>
      <div className="chk-item__body">
        <div className="chk-item__head">
          <span className="chk-item__title">{it.title}</span>
          {it.value && <span className="chk-item__value">{it.value}</span>}
        </div>
        {it.detail && <div className="chk-item__detail">{it.detail}</div>}
        {it.hint && <div className="chk-item__hint">{it.hint}</div>}
        {it.editable && it.note_key && (
          <textarea className="chk-textarea" rows={2}
            placeholder="补充自己的判断(可选,自动结论保留在上方)"
            value={note} onChange={e => { dirtyRef.current = true; setNote(e.target.value); }} />
        )}
      </div>
    </div>
  );
}

/** 手动项表单:text→textarea;choice→单选组;choice+text→单选+备注。
 *  防抖 800ms 自动保存;保存后回填 updated_at(乐观)。
 *  状态指示为小徽章(C17:18px 圆点→chk-badge)。 */
function ManualItem({ it, symbol, onSaved, references }: {
  it: ChecklistItem;
  symbol: string;
  onSaved: (key: string, symbol: string, filled?: boolean) => void;
  references?: ChecklistReferences;
}) {
  const [text, setText] = useState(it.value_text ?? '');
  const [choice, setChoice] = useState(it.value_choice ?? '');
  const dirtyRef = useRef(false);

  // C20:徽章口径与后端 manual_filled 对齐——按 input_type 判定,
  // choice+text 只填备注不算已填(后端也只认 value_choice)
  const filled = it.input_type === 'text' ? !!text.trim() : !!choice;

  // 防抖保存(800ms 静默后触发;对齐 Financial 页 compare 防抖先例)
  useEffect(() => {
    if (!dirtyRef.current) return;
    const t = setTimeout(() => {
      dirtyRef.current = false;
      const savedFilled = it.input_type === 'text' ? !!text.trim() : !!choice;
      fetch(`${getApiBase()}/checklist/${symbol}/items`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: [{ item_key: it.key, value_text: text, value_choice: choice }],
        }),
      })
        .then(r => (r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status))))
        .then(json => { if (json.code === 0) onSaved(it.key, symbol, savedFilled); })
        .catch(() => { /* 静默:下次编辑再存 */ });
    }, 800);
    return () => clearTimeout(t);
  }, [text, choice, it.key, it.input_type, symbol, onSaved]);

  const edit = (setter: (v: string) => void) => (v: string) => {
    dirtyRef.current = true;
    setter(v);
  };

  return (
    <div className="chk-item chk-item--manual">
      <span className={filled ? 'chk-badge chk-badge--filled' : 'chk-badge chk-badge--pending'}>
        {filled ? '已填' : '待填'}
      </span>
      <div className="chk-item__body">
        <div className="chk-item__head">
          <span className="chk-item__title">{it.title}</span>
          {it.updated_at && (
            <span className={`chk-item__date${(daysSince(it.updated_at) ?? 0) > 90 ? ' chk-item__date--stale' : ''}`}>
              上次填写 {formatDaysAgo(it.updated_at)}
              {(daysSince(it.updated_at) ?? 0) > 90 ? ' · 建议复检' : ''}
            </span>
          )}
        </div>
        {it.choices && (
          <div className="chk-choices">
            {it.choices.map(c => (
              <label key={c} className={`chk-choice${choice === c ? ' chk-choice--on' : ''}`}>
                <input
                  type="radio"
                  name={`${symbol}-${it.key}`}
                  checked={choice === c}
                  onChange={() => edit(setChoice)(c)}
                />
                {c}
              </label>
            ))}
          </div>
        )}
        {(it.input_type === 'text' || it.input_type === 'choice+text') && (
          <textarea
            className="chk-textarea"
            rows={it.input_type === 'text' ? 3 : 1}
            placeholder={it.input_type === 'choice+text' ? '备注(可选)' : '研究清楚了再填'}
            value={text}
            onChange={e => edit(setText)(e.target.value)}
          />
        )}
        {it.course && <div className="chk-item__hint">课程口径:{it.course}</div>}
        <ItemReference itemKey={it.key} refs={references} />
      </div>
    </div>
  );
}

export function Checklist() {
  // 入口:Financial 头部/自选股行内携带 ?symbol= 直达;无参默认茅台。
  // 裸 6 位代码归一为 sh/sz 前缀,否则体检聚合各接口全查空
  const [searchParams] = useSearchParams();
  const urlSymbol = searchParams.get('symbol');
  const [symbol, setSymbol] = useState(
    urlSymbol ? ensurePrefixed(urlSymbol) : 'sh600519');
  const [data, setData] = useState<ChecklistData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // 路由参数变化时跟随(同路由不同 symbol 的跳转,组件不重挂载)
  useEffect(() => {
    if (urlSymbol) setSymbol(ensurePrefixed(urlSymbol));
  }, [urlSymbol]);

  // 乐观回填:保存成功后把该项 updated_at 更新为现在(不重拉整页)。
  // C19:仅当回填发起时的 symbol 与当前一致才生效(防在途切股误刷新股数据);
  // C21:同步重算顶栏 manual_progress(该项 pending↔filled 变化即时反映)。
  const symbolRef = useRef(symbol);
  useEffect(() => { symbolRef.current = symbol; }, [symbol]);

  const markSaved = useCallback((key: string, savedSymbol: string, filled?: boolean) => {
    if (savedSymbol !== symbolRef.current) return;
    setData(prev => {
      if (!prev) return prev;
      const sections = prev.sections.map(s => ({ ...s, items: s.items.map(i =>
        i.key === key
          ? {
              ...i,
              updated_at: new Date().toISOString(),
              ...(typeof filled === 'boolean' && i.type === 'manual'
                ? { status: filled ? 'filled' : 'pending' }
                : {}),
            }
          : i) }));
      const filledN = sections.reduce(
        (n, s) => n + s.items.filter(i => i.type === 'manual' && i.status === 'filled').length,
        0);
      return { ...prev, sections, manual_progress: { ...prev.manual_progress, filled: filledN } };
    });
  }, []);

  useEffect(() => {
    let stale = false;
    setLoading(true); setError(''); setData(null);
    fetch(`${getApiBase()}/checklist/${symbol}`)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status))))
      .then(json => {
        if (stale) return;
        if (json.code === 0 && json.data) setData(json.data);
        else setError(json.msg || '加载失败');
      })
      .catch(e => { if (!stale) setError(String(e)); })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, [symbol]);

  return (
    <div className="page checklist-page">
      <PageHeader title="买入体检" subtitle="股票投资前的检查清单(课程21集)——只展示不下结论;手动项研究清楚再填" />
      <div className="chk-toolbar">
        <StockSearch value={symbol} onSelect={setSymbol} />
        {data?.references?.profile?.name && (
          <span className="chk-ref">
            {data.references.profile.name}
            {data.references.profile.market ? ` · ${data.references.profile.market}` : ''}
          </span>
        )}
        {data && (
          <div className="chk-progress">
            <span>手动项 {data.manual_progress.filled}/{data.manual_progress.total}</span>
            <span className="chk-dot chk-dot--ok" /> {data.auto_progress.ok}
            <span className="chk-dot chk-dot--watch" /> {data.auto_progress.watch}
            <span className="chk-dot chk-dot--risk" /> {data.auto_progress.risk}
            <span className="chk-dot chk-dot--missing" /> {data.auto_progress.missing}
          </div>
        )}
      </div>
      {loading ? (
        <StateView state="loading" />
      ) : error ? (
        <StateView state="error" text={error} />
      ) : !data ? (
        <StateView state="empty" text="暂无数据" />
      ) : (
        <div className="chk-sections">
          {data.sections.map(sec => (
            <section key={sec.key} className="chk-section">
              <h3 className="chk-section__title">{sec.title}</h3>
              <div className="chk-section__items">
                {sec.items.map(it => it.type === 'auto'
                  ? <AutoItem key={it.key} it={it} symbol={symbol} onSaved={markSaved} />
                  : <ManualItem key={it.key} it={it} symbol={symbol} onSaved={markSaved}
                    references={data.references} />)}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
