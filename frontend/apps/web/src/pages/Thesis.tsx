/**
 * 持仓体检 — Thesis
 * 路径：/thesis（侧边栏"持仓体检"）
 *
 * 论点即持仓：登记买入论点+可证伪假设+目标估值带；
 * 卖出体检四区报告；财报联动重估历史。
 */
import React, {useState, useEffect, useCallback} from 'react';
import {Link, useNavigate} from 'react-router-dom';
import {Button, Badge} from '@ytrader/common-components';
import {getApiBase} from '../lib/api';
import {ensurePrefixed} from '../lib/symbol';
import {PageHeader, StateView} from '../components/ui';
import {StockSearch} from '../components/StockSearch';
import {ThermometerCard} from '../components/ThermometerCard';
import './Thesis.css';

const API = `${getApiBase()}/thesis`;
const MP_API = `${getApiBase()}/management-promises`;
const PROMISE_STATUS: Record<string, string> = {
  fulfilled: '兑现', beat: '超预告', broken: '未达', pending: '待验证',
};
const fmtYiRaw = (v: number | null | undefined) =>
  v == null ? '—' : (v / 1e8).toFixed(2) + '亿';

// ── 类型 ─────────────────────────────────────────────────────────────────
interface Condition {
  id: number;
  metric_key: string;
  operator: string;
  threshold: number;
  label: string;
  status: string;
  current?: number | null;
}
interface Thesis {
  id: number;
  symbol: string;
  status: string;
  buy_date: string | null;
  buy_price: number | null;
  shares: number | null;
  thesis_text: string;
  snapshot: any;
  target_band: any;
  decision: string | null;
  decision_note: string | null;
  last_reviewed_at: string | null;
  close_reason: string | null;
  close_price: number | null;
  current_price?: number | null;
  pnl_pct?: number | null;
  condition_summary?: {total: number; breached: number; unknown: number};
  last_reeval_verdict?: string | null;
  stale?: boolean;
}
interface Reeval {
  id: number;
  report_date: string | null;
  trigger: string;
  verdict: string;
  created_at: string;
}
interface SellCheck {
  sections: {
    thesis: {title: string; items: Condition[]; recommend_sell: boolean; stale: boolean};
    valuation: {title: string; band: any; margin_then: number | null; margin_now: number | null; margin_consumed: number | null};
    fundamentals: {title: string; quality_now: any; quality_then: any; score_diff: number | null; new_red_flags: string[]};
    decision: {title: string; questions: string[]; decision: string | null; decision_note: string | null};
  };
  recommend_sell: boolean;
  stale_days: number | null;
}

const METRICS = [
  {key: 'roe', label: 'ROE(%)'}, {key: 'revenue_yoy', label: '营收同比(%)'},
  {key: 'net_profit_yoy', label: '净利同比(%)'}, {key: 'gross_margin', label: '毛利率(%)'},
  {key: 'ocf_ratio', label: '现金流/净利(x)'}, {key: 'debt_ratio', label: '资产负债率(%)'},
  {key: 'pe_ttm', label: 'PE(TTM)'}, {key: 'pb', label: 'PB'}, {key: 'dv_ttm', label: '股息率(%)'},
];
const OPS = ['>=', '>', '<=', '<'];
const BAND_METRICS = [
  {key: 'price', label: '价格'}, {key: 'pe_ttm', label: 'PE(TTM)'},
  {key: 'pb', label: 'PB'}, {key: 'dv_ttm', label: '股息率(%)'},
];
const VERDICT_TONE: Record<string, string> = {
  pass: 'var(--color-success)', review: 'var(--color-warning)',
  sell_signal: 'var(--color-danger)',
};
const fmtPct = (n: number | null | undefined) =>
  n == null ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`;

interface SizeSuggestion {
  data_missing: boolean;
  tier: string | null;
  band: {low: number; high: number} | null;
  p: number | null;
  upside_pct: number | null;
  kelly_half_pct: number | null;
  suggested_pct: number | null;
  capped_by: string | null;
  single_cap_pct: number;
  ladder: any[];
}
const TIER_LABEL: Record<string, string> = {
  strong: '强（高确信）', medium: '中', weak: '弱（建议观望）',
};


// ── 登记对话框 ────────────────────────────────────────────────────────────
const CreateDialog: React.FC<{
  initialSymbol?: string;
  initialBuyPrice?: string;
  initialShares?: string;
  onDone: () => void;
  onClose: () => void;
}> = ({initialSymbol = '', initialBuyPrice = '',
       initialShares = '', onDone, onClose}) => {
  const [symbol, setSymbol] = useState(initialSymbol);
  const [buyDate, setBuyDate] = useState('');
  const [buyPrice, setBuyPrice] = useState(initialBuyPrice);
  const [shares, setShares] = useState(initialShares);
  const [text, setText] = useState('');
  const [bandMetric, setBandMetric] = useState('price');
  const [bandLow, setBandLow] = useState('');
  const [bandHigh, setBandHigh] = useState('');
  const [confidence, setConfidence] = useState('');
  const [catalysts, setCatalysts] = useState('');
  const [conds, setConds] = useState<{metric_key: string; operator: string; threshold: string; label: string}[]>([
    {metric_key: 'roe', operator: '>=', threshold: '', label: ''},
  ]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [size, setSize] = useState<SizeSuggestion | null>(null);
  const [calib, setCalib] = useState<any>(null);
  const [calibrating, setCalibrating] = useState(false);

  async function calibrate() {
    const valid = conds.filter(c => c.threshold !== '');
    if (!symbol || valid.length === 0) return;
    setCalibrating(true);
    try {
      const res = await fetch(`${API}/conditions-backtest`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          symbol,
          conditions: valid.map(c => ({
            metric_key: c.metric_key, operator: c.operator,
            threshold: +c.threshold,
          })),
        }),
      });
      const d = await res.json();
      if (d.code === 0) setCalib(d.data);
    } finally {setCalibrating(false);}
  }

  useEffect(() => {
    if (!symbol) {setSize(null); return;}
    fetch(`${API}/position-size/${symbol}?capital=1000000`)
      .then(r => r.json())
      .then(d => d.code === 0 && setSize(d.data))
      .catch(() => setSize(null));
  }, [symbol]);

  async function save() {
    if (!symbol) {setError('请选择股票'); return;}
    setSaving(true); setError(null);
    try {
      const res = await fetch(API, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          symbol,
          buy_date: buyDate || null,
          buy_price: buyPrice ? +buyPrice : null,
          shares: shares ? +shares : null,
          thesis_text: text,
          ...(confidence ? {confidence: +confidence} : {}),
          ...(catalysts.trim() ? {catalysts: catalysts.trim()} : {}),
          target_band: bandLow && bandHigh
            ? {metric: bandMetric, low: +bandLow, high: +bandHigh}
            : null,
          conditions: conds
            .filter(c => c.threshold !== '')
            .map(c => ({
              metric_key: c.metric_key, operator: c.operator,
              threshold: +c.threshold, label: c.label,
            })),
        }),
      });
      const d = await res.json();
      if (d.code !== 0) throw new Error(d.msg || '登记失败');
      onDone();
    } catch (e: any) {
      setError(e.message || '请求失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="thesis-dialog__mask" onClick={onClose}>
      <div className="thesis-dialog" onClick={e => e.stopPropagation()}>
        <h3>登记持仓论点</h3>
        <div className="thesis-dialog__row">
          <label>股票</label>
          <StockSearch value={symbol} onSelect={setSymbol}/>
        </div>
        <div className="thesis-dialog__grid">
          <div><label>买入日期</label><input type="date" value={buyDate} onChange={e => setBuyDate(e.target.value)}/></div>
          <div><label>买入价</label><input type="number" value={buyPrice} onChange={e => setBuyPrice(e.target.value)}/></div>
          <div><label>股数</label><input type="number" value={shares} onChange={e => setShares(e.target.value)}/></div>
        </div>
        {size && !size.data_missing && (
          <div className="thesis-dialog__size">
            <div className="thesis-dialog__size-head">
              <span className={`size-tier size-tier--${size.tier}`}>
                {TIER_LABEL[size.tier || ''] || size.tier}
              </span>
              <span className="size-suggested">
                建议仓位 <b>{size.suggested_pct}%</b>
                （区间 {size.band?.low}~{size.band?.high}%，单票上限 {size.single_cap_pct}%）
              </span>
            </div>
            <p className="dim">
              胜率估计 {size.p != null ? (size.p * 100).toFixed(1) + '%' : '—'} ·
              上行至公允 +{size.upside_pct ?? '—'}% ·
              半凯利参考 {size.kelly_half_pct != null ? size.kelly_half_pct.toFixed(1) + '%' : '—'}
              {size.capped_by === 'kelly_zero' && '（凯利为 0：赔率不足，建议观望）'}
            </p>
            {size.ladder.length > 0 && (
              <table className="thesis-table">
                <thead><tr><th>档位</th><th>较现价</th><th>价格</th><th>占仓位</th><th>金额</th><th>股数</th></tr></thead>
                <tbody>
                  {size.ladder.map((l: any) => (
                    <tr key={l.rung_index}>
                      <td>第{l.rung_index}档</td>
                      <td>{l.drop_pct === 0 ? '现价' : l.drop_pct + '%'}</td>
                      <td className="mono">{l.price_level ?? '—'}</td>
                      <td>{(l.weight_of_position * 100).toFixed(0)}%</td>
                      <td className="mono">{l.amount != null ? (l.amount / 10000).toFixed(1) + '万' : '—'}</td>
                      <td className="mono">{l.shares ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
        {size && size.data_missing && (
          <p className="dim">仓位建议：估值或质量数据缺失，暂无法计算</p>
        )}

        <div className="thesis-dialog__row">
          <label>买入逻辑</label>
          <textarea rows={3} value={text} onChange={e => setText(e.target.value)}
            placeholder="为什么买？核心逻辑一两句话"/>
        </div>
        <div className="thesis-dialog__row">
          <label>信心度与预期催化（决策日志原料，回填后做校准统计）</label>
          <div className="thesis-dialog__band">
            <select value={confidence} onChange={e => setConfidence(e.target.value)}>
              <option value="">信心度(可选)</option>
              {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
            <input placeholder="预期催化(可选)：什么事件兑现这笔买入" value={catalysts}
              onChange={e => setCatalysts(e.target.value)} style={{flex: 1}}/>
          </div>
        </div>
        <div className="thesis-dialog__row">
          <label>目标卖出带（现值进入带内即提醒）</label>
          <div className="thesis-dialog__band">
            <select value={bandMetric} onChange={e => setBandMetric(e.target.value)}>
              {BAND_METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select>
            <input type="number" placeholder="低" value={bandLow} onChange={e => setBandLow(e.target.value)}/>
            <span>~</span>
            <input type="number" placeholder="高" value={bandHigh} onChange={e => setBandHigh(e.target.value)}/>
          </div>
        </div>
        <div className="thesis-dialog__row">
          <label>假设条件（任一破即建议卖出）</label>
          {conds.map((c, i) => (
            <div className="thesis-dialog__cond" key={i}>
              <select value={c.metric_key} onChange={e => {
                const next = [...conds]; next[i] = {...c, metric_key: e.target.value}; setConds(next);
              }}>
                {METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
              </select>
              <select value={c.operator} onChange={e => {
                const next = [...conds]; next[i] = {...c, operator: e.target.value}; setConds(next);
              }}>
                {OPS.map(o => <option key={o}>{o}</option>)}
              </select>
              <input type="number" placeholder="阈值" value={c.threshold} onChange={e => {
                const next = [...conds]; next[i] = {...c, threshold: e.target.value}; setConds(next);
              }}/>
              <input placeholder="备注(可选)" value={c.label} onChange={e => {
                const next = [...conds]; next[i] = {...c, label: e.target.value}; setConds(next);
              }}/>
              <button onClick={() => setConds(conds.filter((_, j) => j !== i))}>删</button>
            </div>
          ))}
          <Button size="sm" onClick={() => setConds([...conds, {metric_key: 'roe', operator: '>=', threshold: '', label: ''}])}>
            + 条件
          </Button>
          <div style={{marginTop: 'var(--space-2)'}}>
            <Button size="sm" loading={calibrating} onClick={calibrate}>校准阈值（16季回测）</Button>
            {calib && (
              <table className="thesis-table" style={{marginTop: 'var(--space-2)'}}>
                <thead><tr><th>条件</th><th>评估期</th><th>破位</th><th>破位率</th><th>首破</th></tr></thead>
                <tbody>
                  {calib.summary.map((c: any, i: number) => (
                    <tr key={i}>
                      <td className="mono">{c.metric_key} {c.operator} {c.threshold}</td>
                      <td>{c.evaluated}</td>
                      <td className={c.breached > 0 ? 'neg' : ''}>{c.breached}</td>
                      <td>{c.breach_rate != null ? (c.breach_rate * 100).toFixed(0) + '%' : '—'}</td>
                      <td>{c.first_breach_report_date ?? '从未'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {calib && calib.valuation_unsupported?.length > 0 && (
              <p className="dim">估值条件（{calib.valuation_unsupported.join('、')}）暂不支持历史回测</p>
            )}
          </div>
        </div>
        {error && <p className="thesis-dialog__error">{error}</p>}
        <div className="thesis-dialog__actions">
          <Button variant="primary" loading={saving} onClick={save}>登记</Button>
          <Button onClick={onClose}>取消</Button>
        </div>
      </div>
    </div>
  );
};


// ── 放弃决策对话框 ────────────────────────────────────────────────────────
const PassDialog: React.FC<{onDone: () => void; onClose: () => void}> = ({
  onDone, onClose,
}) => {
  const [symbol, setSymbol] = useState('');
  const [decisionDate, setDecisionDate] = useState(
    new Date().toISOString().slice(0, 10));
  const [price, setPrice] = useState('');
  const [reason, setReason] = useState('');
  const [revisit, setRevisit] = useState('');
  const [confidence, setConfidence] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!symbol) {setError('请选择股票'); return;}
    if (!reason.trim()) {setError('放弃理由必填：研究后为什么不买'); return;}
    setSaving(true); setError(null);
    try {
      const res = await fetch(`${API}/pass`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          symbol,
          reason: reason.trim(),
          ...(decisionDate ? {decision_date: decisionDate} : {}),
          ...(price ? {price: +price} : {}),
          ...(revisit.trim() ? {revisit_when: revisit.trim()} : {}),
          ...(confidence ? {confidence: +confidence} : {}),
        }),
      });
      const d = await res.json();
      if (d.code !== 0) throw new Error(d.msg || '保存失败');
      onDone();
    } catch (e: any) {
      setError(e.message || '请求失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="thesis-dialog__mask" onClick={onClose}>
      <div className="thesis-dialog" onClick={e => e.stopPropagation()}>
        <h3>记一笔放弃决策</h3>
        <p className="dim">
          研究过但决定不买——这也是决策。记录后自动跟踪"没买之后怎样"，
          与卖飞/卖对镜像对照。
        </p>
        <div className="thesis-dialog__row">
          <label>股票</label>
          <StockSearch value={symbol} onSelect={setSymbol}/>
        </div>
        <div className="thesis-dialog__grid">
          <div><label>放弃日期</label>
            <input type="date" value={decisionDate}
              onChange={e => setDecisionDate(e.target.value)}/></div>
          <div><label>当时价（可空自动取现价）</label>
            <input type="number" value={price}
              onChange={e => setPrice(e.target.value)}/></div>
          <div><label>信心度（对"不买"）</label>
            <select value={confidence}
              onChange={e => setConfidence(e.target.value)}>
              <option value="">可选</option>
              {[1, 2, 3, 4, 5].map(n =>
                <option key={n} value={n}>{n}</option>)}
            </select></div>
        </div>
        <div className="thesis-dialog__row">
          <label>为什么放弃（必填）</label>
          <textarea rows={2} value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="核心原因一两句话，如：估值太贵/护城河存疑/等待更好价格"/>
        </div>
        <div className="thesis-dialog__row">
          <label>什么情况下重新看（可选）</label>
          <input value={revisit} onChange={e => setRevisit(e.target.value)}
            placeholder="例：PE 回到 25 以下 / 新管理层上任 / 财报证实现金流改善"/>
        </div>
        {error && <p className="thesis-dialog__error">{error}</p>}
        <div className="thesis-dialog__actions">
          <Button variant="primary" loading={saving} onClick={save}>保存</Button>
          <Button onClick={onClose}>取消</Button>
        </div>
      </div>
    </div>
  );
};


// ── 详情面板 ─────────────────────────────────────────────────────────────
const Detail: React.FC<{
  id: number;
  onBack: () => void;
  onChanged: () => void;
}> = ({id, onBack, onChanged}) => {
  const [thesis, setThesis] = useState<Thesis | null>(null);
  const [check, setCheck] = useState<SellCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [decision, setDecision] = useState('hold');
  const [note, setNote] = useState('');
  const [confidence, setConfidence] = useState('');
  const [ack, setAck] = useState(false);
  const [reevaling, setReevaling] = useState(false);
  const [jnote, setJnote] = useState('');
  const [capAlloc, setCapAlloc] = useState<any>(null);
  const [capEvents, setCapEvents] = useState<any[]>([]);
  const [promises, setPromises] = useState<any>(null);
  const [importing, setImporting] = useState(false);
  const [importingAnnual, setImportingAnnual] = useState(false);
  const [pCategory, setPCategory] = useState('业绩指引');
  const [pContent, setPContent] = useState('');
  const [btResult, setBtResult] = useState<any>(null);
  const [btLoading, setBtLoading] = useState(false);

  const loadPromises = useCallback((sym: string) => {
    fetch(`${MP_API}/${sym}`).then(r => r.json())
      .then(d => d.code === 0 && setPromises(d.data))
      .catch(() => {});
  }, []);

  async function importPromises() {
    if (!thesis) return;
    setImporting(true);
    try {
      await fetch(`${MP_API}/${thesis.symbol}/import-forecasts`,
        {method: 'POST'});
      loadPromises(thesis.symbol);
    } finally {setImporting(false);}
  }
  async function importAnnualReports() {
    if (!thesis) return;
    if (!window.confirm('从近两年年报 MD&A 抽取管理层承诺？'
      + '含 PDF 下载与 LLM 抽取，约需 1~3 分钟。')) return;
    setImportingAnnual(true);
    try {
      const r = await fetch(
        `${MP_API}/${thesis.symbol}/import-annual-reports`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({years: 2}),
        });
      const j = await r.json();
      if (j.code === 0) {
        window.alert(`年报抽取完成：${j.data.inserted} 条新增`
          + `${j.data.duplicated ? `、${j.data.duplicated} 条重复跳过` : ''}`
          + '，均待人工验证。');
      } else {
        window.alert(`年报抽取失败：${j.msg || '未知错误'}`);
      }
      loadPromises(thesis.symbol);
    } finally {setImportingAnnual(false);}
  }
  async function addPromise() {
    if (!thesis || !pContent.trim()) return;
    await fetch(`${MP_API}/${thesis.symbol}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({category: pCategory, content: pContent.trim()}),
    });
    setPContent('');
    loadPromises(thesis.symbol);
  }
  async function verifyPromise(id: number, status: string) {
    const evidence = window.prompt('验证依据（可空）：年报链接/数据出处', '') ?? '';
    await fetch(`${MP_API}/${id}/verify`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({status, evidence}),
    });
    if (thesis) loadPromises(thesis.symbol);
  }
  async function deletePromise(id: number) {
    if (!window.confirm('删除这条承诺记录？')) return;
    await fetch(`${MP_API}/${id}`, {method: 'DELETE'});
    if (thesis) loadPromises(thesis.symbol);
  }

  const bt = {
    result: btResult, loading: btLoading,
    run: async () => {
      const cs = ((thesis as any).conditions) || [];
      if (!thesis || cs.length === 0) return;
      setBtLoading(true);
      try {
        const res = await fetch(`${API}/conditions-backtest`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            symbol: thesis.symbol,
            conditions: cs.map((c: any) => ({
              metric_key: c.metric_key, operator: c.operator,
              threshold: c.threshold,
            })),
          }),
        });
        const d = await res.json();
        if (d.code === 0) setBtResult(d.data);
      } finally {setBtLoading(false);}
    },
  };

  const load = useCallback(() => {
    fetch(`${API}/${id}`).then(r => r.json()).then(d => {
      if (d.code === 0) {
        setThesis(d.data);
        setDecision(d.data.decision || 'hold');
        setNote(d.data.decision_note || '');
        const sym = d.data.symbol;
        if (sym) {
          fetch(`${API}/capital-allocation/${sym}`)
            .then(r2 => r2.json())
            .then(d2 => d2.code === 0 && setCapAlloc(d2.data))
            .catch(() => {});
          fetch(`${API}/capital-events/${sym}`)
            .then(r3 => r3.json())
            .then(d3 => d3.code === 0 && setCapEvents(d3.data))
            .catch(() => {});
          loadPromises(sym);
        }
      }
    }).catch(() => {});
  }, [id, loadPromises]);
  useEffect(load, [load]);

  async function runCheck() {
    setChecking(true);
    try {
      const d = await (await fetch(`${API}/${id}/sell-check`)).json();
      if (d.code === 0) setCheck(d.data);
    } finally {setChecking(false);}
  }
  async function reeval() {
    setReevaling(true);
    try {
      await fetch(`${API}/${id}/reeval`, {method: 'POST'});
      load(); onChanged();
    } finally {setReevaling(false);}
  }
  async function saveDecision() {
    await fetch(`${API}/${id}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        decision, decision_note: note,
        ...(confidence ? {confidence: +confidence} : {}),
      }),
    });
    setAck(false);
    load(); onChanged();
  }
  async function addNote() {
    if (!jnote.trim()) return;
    await fetch(`${API}/${id}/journal`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({note: jnote}),
    });
    setJnote('');
    load();
  }
  async function fillRung(rung: number, price: number | null,
                          shares: number | null) {
    const p = price ?? 0, sh = shares ?? 0;
    const priceIn = prompt(`第${rung}档成交价`, String(p));
    if (!priceIn) return;
    const sharesIn = prompt(`成交股数`, String(sh));
    if (!sharesIn) return;
    await fetch(`${API}/${id}/ladder-fills`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        rung_index: rung, price: +priceIn, shares: +sharesIn,
      }),
    });
    load();
  }

  async function close(reason: string) {
    await fetch(`${API}/${id}/close`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({reason}),
    });
    onChanged(); onBack();
  }

  if (!thesis) return <StateView state="loading" text="加载中…"/>;
  const conds: Condition[] = (thesis as any).conditions || [];
  const reevals: Reeval[] = (thesis as any).reevals || [];
  const journal: any[] = (thesis as any).journal || [];

  return (
    <div className="thesis-detail">
      <div className="thesis-detail__head">
        <Button size="sm" onClick={onBack}>← 返回列表</Button>
        <h2 className="mono">{thesis.symbol}</h2>
        {thesis.buy_price && (
          <span>成本 {thesis.buy_price} · 现价 {thesis.current_price ?? '—'} ·
            <span className={thesis.pnl_pct != null && thesis.pnl_pct >= 0 ? 'pos' : 'neg'}>
              {fmtPct(thesis.pnl_pct)}
            </span>
          </span>
        )}
        <span>
          <Button size="sm" variant="primary" loading={checking} onClick={runCheck}>卖出体检</Button>{' '}
          <Button size="sm" loading={reevaling} onClick={reeval}>立即重估</Button>
        </span>
      </div>
      {thesis.stale && (
        <div className="thesis-detail__stale">⚠ 已超过 90 天未复检，建议重过体检</div>
      )}

      <section className="thesis-detail__section">
        <h3>买入逻辑</h3>
        <p>{thesis.thesis_text || '—'}</p>
        {thesis.snapshot?.thermometer && (
          <p className="dim">
            登记时市场温度：{thesis.snapshot.thermometer.level_label}
            （ERP {thesis.snapshot.thermometer.erp_pct}%，
            分位 {thesis.snapshot.thermometer.erp_percentile ?? '—'}%）
          </p>
        )}
      </section>

      <section className="thesis-detail__section">
        <h3>假设条件</h3>
        {conds.length === 0 && <p className="dim">未设置条件</p>}
        {conds.length > 0 && (
          <div style={{marginBottom: 'var(--space-2)'}}>
            <Button size="sm" loading={bt.loading} onClick={bt.run}>校准阈值（16季回测）</Button>
          </div>
        )}
        {bt.result && (
          <table className="thesis-table" style={{marginBottom: 'var(--space-2)'}}>
            <thead><tr><th>条件</th><th>评估期</th><th>破位</th><th>破位率</th><th>首破</th></tr></thead>
            <tbody>
              {bt.result.summary.map((c: any, i: number) => (
                <tr key={i}>
                  <td className="mono">{c.metric_key} {c.operator} {c.threshold}</td>
                  <td>{c.evaluated}</td>
                  <td className={c.breached > 0 ? 'neg' : ''}>{c.breached}</td>
                  <td>{c.breach_rate != null ? (c.breach_rate * 100).toFixed(0) + '%' : '—'}</td>
                  <td>{c.first_breach_report_date ?? '从未'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {conds.length > 0 && (
          <table className="thesis-table">
            <thead><tr><th>指标</th><th>条件</th><th>现值</th><th>状态</th></tr></thead>
            <tbody>
              {conds.map(c => (
                <tr key={c.id}>
                  <td>{c.label || c.metric_key}</td>
                  <td className="mono">{c.metric_key} {c.operator} {c.threshold}</td>
                  <td className="mono">{c.current ?? '—'}</td>
                  <td><span className={`cond-status cond-status--${c.status}`}>{c.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {(thesis as any).entry_ladder?.length > 0 && (
        <section className="thesis-detail__section">
          <h3>建仓执行（{(thesis as any).ladder_progress?.rungs_done ??
            0}/{(thesis as any).ladder_progress?.rungs_total ?? 0} 档，
            已投 {(thesis as any).ladder_progress?.invested_pct ?? 0}%）</h3>
          <table className="thesis-table">
            <thead><tr><th>档位</th><th>计划价</th><th>计划股数</th><th>成交价</th><th>成交股数</th><th></th></tr></thead>
            <tbody>
              {((thesis as any).ladder_progress?.rungs ?? []).map((r: any) => (
                <tr key={r.rung_index}>
                  <td>第{r.rung_index}档({r.drop_pct === 0 ? '现价' : r.drop_pct + '%'})</td>
                  <td className="mono">{r.price_level ?? '—'}</td>
                  <td className="mono">{r.shares ?? '—'}</td>
                  <td className="mono">{r.fill_price ?? '—'}</td>
                  <td className="mono">{r.fill_shares ?? '—'}</td>
                  <td>
                    {!r.filled && (
                      <Button size="sm" onClick={() =>
                        fillRung(r.rung_index, r.price_level, r.shares)
                      }>标记成交</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {(thesis as any).ladder_progress?.avg_fill_price != null && (
            <p className="dim">成交均价 {(thesis as any).ladder_progress.avg_fill_price}</p>
          )}
        </section>
      )}

      {check && (
        <section className="thesis-detail__section thesis-sellcheck">
          <h3>卖出体检报告</h3>
          {check.recommend_sell && (
            <div className="thesis-sellcheck__alert">存在破位条件，建议执行卖出决策流程</div>
          )}
          <div className="thesis-sellcheck__grid">
            <div>
              <h4>A {check.sections.thesis.title}</h4>
              <ul>
                {check.sections.thesis.items.map((it, i) => (
                  <li key={i} className={`cond-status--${it.status}`}>
                    {it.label}：{it.operator}{it.threshold}（现值 {it.current ?? '—'}）→ {it.status}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h4>B {check.sections.valuation.title}</h4>
              <p>目标带：{check.sections.valuation.band.metric} {check.sections.valuation.band.low}~{check.sections.valuation.band.high}，
                现值 {check.sections.valuation.band.current ?? '—'}，
                到位：{String(check.sections.valuation.band.reached ?? '无法评估')}</p>
              {check.sections.valuation.margin_consumed != null && (
                <p>安全边际消耗：{check.sections.valuation.margin_consumed.toFixed(1)}%</p>
              )}
            </div>
            <div>
              <h4>C {check.sections.fundamentals.title}</h4>
              <p>质量分：{check.sections.fundamentals.quality_then?.score ?? '—'} →
                {' '}{check.sections.fundamentals.quality_now?.score ?? '—'}
                {check.sections.fundamentals.score_diff != null &&
                  `（${check.sections.fundamentals.score_diff > 0 ? '+' : ''}${check.sections.fundamentals.score_diff}）`}</p>
              {check.sections.fundamentals.new_red_flags.length > 0 && (
                <p className="neg">新增红旗：{check.sections.fundamentals.new_red_flags.join('、')}</p>
              )}
            </div>
            <div>
              <h4>D {check.sections.decision.title}</h4>
              <ul>{check.sections.decision.questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
            </div>
          </div>
        </section>
      )}

      <section className="thesis-detail__section">
        <h3>决策记录</h3>
        {conds.some(c => c.status === 'breached') && (
          <div className="thesis-detail__stale" style={{marginBottom: 'var(--space-2)'}}>
            ⚠ 存在破位条件——保存"持有"前须对照原始买入逻辑
            <p style={{marginTop: 4}}>{thesis.thesis_text || '（无买入逻辑记录）'}</p>
            {decision === 'hold' && (
              <label style={{display: 'flex', gap: 6, alignItems: 'center', marginTop: 6}}>
                <input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)}/>
                已重读买入逻辑，确认论点未破、维持持有
              </label>
            )}
          </div>
        )}
        <div className="thesis-detail__decision">
          <select value={decision} onChange={e => setDecision(e.target.value)}>
            <option value="hold">持有</option><option value="reduce">减仓</option><option value="sell">清仓</option>
          </select>
          <select value={confidence} onChange={e => setConfidence(e.target.value)}>
            <option value="">信心度(可选)</option>
            {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}</option>)}
          </select>
          <input placeholder="决策备注" value={note} onChange={e => setNote(e.target.value)}/>
          <Button size="sm"
            disabled={decision === 'hold'
              && conds.some(c => c.status === 'breached') && !ack}
            onClick={saveDecision}>保存决策</Button>
        </div>
      </section>

      <section className="thesis-detail__section">
        <h3>重估历史</h3>
        {reevals.length === 0 && <p className="dim">暂无（每日 17:35 自动检测新财报触发）</p>}
        {reevals.length > 0 && (
          <table className="thesis-table">
            <thead><tr><th>财报期</th><th>触发</th><th>结论</th><th>时间</th></tr></thead>
            <tbody>
              {reevals.map(r => (
                <tr key={r.id}>
                  <td>{r.report_date ?? '—'}</td>
                  <td>{r.trigger}</td>
                  <td><span style={{color: VERDICT_TONE[r.verdict]}}>{r.verdict}</span></td>
                  <td>{r.created_at?.slice(0, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="thesis-detail__section">
        <h3>管理层与资本配置</h3>
        {!capAlloc && <p className="dim">加载中…</p>}
        {capAlloc && (
          <>
            <p>
              <span style={{
                fontWeight: 600,
                color: capAlloc.verdict === 'shareholder_friendly'
                  ? 'var(--color-success)'
                  : capAlloc.verdict === 'concerning'
                    ? 'var(--color-danger)' : 'var(--color-warning)',
              }}>
                {capAlloc.verdict === 'shareholder_friendly' ? '股东友好' :
                 capAlloc.verdict === 'concerning' ? '需警惕' :
                 capAlloc.verdict === 'neutral' ? '中性' : '数据不足'}
              </span>
              {capAlloc.score != null && ` · 评分 ${capAlloc.score}/100`}
            </p>
            <ul>
              <li>分红：连续 {capAlloc.consecutive_dividend_years} 年
                {capAlloc.iron_rooster && <span className="neg">（铁公鸡：长期零分红）</span>}</li>
              <li>分红率：{capAlloc.payout_pct ?? '—'}%</li>
              <li>ROIC：{capAlloc.roic_pct ?? '—'}%</li>
              <li>股东户数同比：{capAlloc.holder_change?.pct ?? '—'}%
                （{capAlloc.holder_change?.label ?? '—'}）</li>
              {capAlloc.mgmt_behavior && (
                <li>管理层行为（近24月）：{capAlloc.mgmt_behavior.label}
                  {capAlloc.mgmt_behavior.buyback_amount > 0 &&
                    ` · 回购实施 ${(capAlloc.mgmt_behavior.buyback_amount / 1e8).toFixed(1)}亿`}
                  {capAlloc.mgmt_behavior.net_ratio_pct != null &&
                    ` · 净增减持 ${capAlloc.mgmt_behavior.net_ratio_pct}%`}</li>
              )}
            </ul>
            {capAlloc.flags?.length > 0 && (
              <p className="neg">⚠ {capAlloc.flags.join('；')}</p>
            )}
            {capEvents.length > 0 && (
              <div>
                <h4>近期资本事件（近24月）</h4>
                <table className="thesis-table">
                  <thead><tr><th>日期</th><th>类型</th><th>股东</th><th>数量(万股)</th><th>金额</th><th>占股本</th></tr></thead>
                  <tbody>
                    {capEvents.slice(0, 10).map((e: any, i: number) => (
                      <tr key={i}>
                        <td>{e.announce_date}</td>
                        <td>{e.event_type === 'buyback' ? '回购' :
                             e.event_type === 'hold_increase' ? '增持' : '减持'}</td>
                        <td>{e.holder_name || '—'}</td>
                        <td className="mono">{e.shares_wan ?? '—'}</td>
                        <td className="mono">{e.amount != null ? (e.amount / 1e8).toFixed(2) + '亿' : '—'}</td>
                        <td className="mono">{e.ratio_pct != null ? e.ratio_pct.toFixed(2) + '%' : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        <div style={{marginTop: 'var(--space-3)'}}>
          <h4>承诺与兑现（管理层信用档案）</h4>
          {promises && promises.credit && (
            <p className="dim">
              已验证 {promises.credit.verified}/{promises.credit.total} 条 ·
              兑现+超预告 {promises.credit.fulfilled + promises.credit.beat} 条
              {promises.credit.credit_pct != null &&
                `（信用 ${promises.credit.credit_pct}%）`} ·
              未达 {promises.credit.broken} 条 · 待验证 {promises.credit.pending} 条
              —— 业绩预告是公司自己的量化承诺，言行一致率长期偏低则估值应打折
            </p>
          )}
          <div style={{display: 'flex', gap: 'var(--space-2)',
                       flexWrap: 'wrap', marginBottom: 'var(--space-2)'}}>
            <Button size="sm" loading={importing} onClick={importPromises}>
              从业绩预告导入
            </Button>{' '}
            <Button size="sm" loading={importingAnnual}
              onClick={importAnnualReports}>
              {importingAnnual ? '年报抽取中…(1~3分钟)' : '从年报MD&A抽取'}
            </Button>
            <select value={pCategory} onChange={e => setPCategory(e.target.value)}>
              {['业绩指引', '资本开支', '分红', '回购', '增持', '其他'].map(c =>
                <option key={c} value={c}>{c}</option>)}
            </select>
            <input placeholder="手动录入承诺：例：三年内分红率不低于70%"
              style={{flex: 1, minWidth: 220}} value={pContent}
              onChange={e => setPContent(e.target.value)}/>
            <Button size="sm" disabled={!pContent.trim()} onClick={addPromise}>
              添加承诺
            </Button>
          </div>
          {promises && promises.rows?.length > 0 && (
            <table className="thesis-table">
              <thead><tr>
                <th>承诺日</th><th>报告期</th><th>类别</th><th>内容</th>
                <th>预告值</th><th>实际值</th><th>偏差</th><th>状态</th><th></th>
              </tr></thead>
              <tbody>
                {promises.rows.slice(0, 12).map((r: any) => (
                  <tr key={r.id}>
                    <td>{r.promise_date ?? '—'}</td>
                    <td>{r.target_report_date ?? '—'}</td>
                    <td>{r.source === 'forecast' ? '业绩预告' : r.category}</td>
                    <td style={{maxWidth: 220}} title={r.detail || r.evidence || ''}>
                      {r.content}{r.evidence && `（验证：${r.evidence}）`}
                    </td>
                    <td className="mono">{fmtYiRaw(r.forecast_value)}</td>
                    <td className="mono">{fmtYiRaw(r.actual_value)}</td>
                    <td className="mono">{r.deviation_pct != null
                      ? `${r.deviation_pct > 0 ? '+' : ''}${r.deviation_pct}%` : '—'}</td>
                    <td>
                      <span style={{color: r.status === 'broken' ? 'var(--color-danger)'
                        : r.status === 'pending' ? 'var(--color-text-dim, #8b949e)'
                        : 'var(--color-success)'}}>
                        {PROMISE_STATUS[r.status] || r.status}
                      </span>
                    </td>
                    <td style={{whiteSpace: 'nowrap'}}>
                      <Button size="sm" onClick={() => verifyPromise(r.id, 'fulfilled')}>兑现</Button>{' '}
                      <Button size="sm" onClick={() => verifyPromise(r.id, 'broken')}>未达</Button>{' '}
                      <Button size="sm" onClick={() => deletePromise(r.id)}>删</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      <section className="thesis-detail__section">
        <h3>决策日志</h3>
        {journal.length === 0 && <p className="dim">暂无日志</p>}
        {journal.length > 0 && (
          <table className="thesis-table">
            <thead><tr><th>时间</th><th>类型</th><th>决策/备注</th><th>时价</th></tr></thead>
            <tbody>
              {journal.map(j => (
                <tr key={j.id}>
                  <td>{j.created_at?.slice(0, 16)}</td>
                  <td><span className={`journal-kind journal-kind--${j.kind}`}>{j.kind}</span></td>
                  <td>
                    {[j.decision, j.note].filter(Boolean).join(' · ') || '—'}
                    {j.confidence != null && <span className="dim"> · 信心{j.confidence}</span>}
                    {j.catalysts && <span className="dim"> · 催化:{j.catalysts}</span>}
                  </td>
                  <td className="mono">{j.price ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="thesis-detail__decision" style={{marginTop: 'var(--space-2)'}}>
          <input placeholder="记一笔（手记）" value={jnote}
                 onChange={e => setJnote(e.target.value)}/>
          <Button size="sm" onClick={addNote}>记一笔</Button>
        </div>
      </section>

      <div className="thesis-detail__close">
        <Button size="sm" onClick={() => close('thesis_broken')}>论点破位关闭</Button>{' '}
        <Button size="sm" onClick={() => close('valuation_reached')}>估值到位关闭</Button>{' '}
        <Button size="sm" onClick={() => close('better_alt')}>换标的关闭</Button>{' '}
        <Button size="sm" onClick={() => close('manual')}>手动关闭</Button>
      </div>
    </div>
  );
};


// ── 主页面 ───────────────────────────────────────────────────────────────
export const Thesis: React.FC = () => {
  const navigate = useNavigate();
  const qp = new URLSearchParams(window.location.search);
  const [list, setList] = useState<Thesis[]>([]);
  const [closed, setClosed] = useState<Thesis[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(!!qp.get('symbol'));
  // 裸 6 位代码归一(investment_thesis 存前缀码)
  const [prefill] = useState(ensurePrefixed(qp.get('symbol') || ''));
  const [prefillPrice] = useState(qp.get('buy_price') || '');
  const [prefillShares] = useState(qp.get('shares') || '');
  const [showClosed, setShowClosed] = useState(false);
  const [review, setReview] = useState<any>(null);
  const [showReview, setShowReview] = useState(false);
  const [mines, setMines] = useState<any[]>([]);
  const [showMines, setShowMines] = useState(false);
  const [mining, setMining] = useState(false);
  const [pfRisk, setPfRisk] = useState<any>(null);
  const [showPf, setShowPf] = useState(false);
  const [divCal, setDivCal] = useState<any>(null);
  const [showDiv, setShowDiv] = useState(false);
  const [closedPerf, setClosedPerf] = useState<any>(null);
  const [passData, setPassData] = useState<any>(null);
  const [showPass, setShowPass] = useState(false);
  const [showPassForm, setShowPassForm] = useState(false);
  const [calib, setCalib] = useState<any>(null);
  const [pipelineD, setPipelineD] = useState<any>(null);
  const [showPipe, setShowPipe] = useState(false);
  const [stress, setStress] = useState<any>(null);

  const load = useCallback(() => {
    fetch(`${API}?status=active`).then(r => r.json())
      .then(d => d.code === 0 && setList(d.data)).catch(() => {});
    fetch(`${API}?status=closed`).then(r => r.json())
      .then(d => d.code === 0 && setClosed(d.data)).catch(() => {});
    fetch(`${API}/review`).then(r => r.json())
      .then(d => d.code === 0 && setReview(d.data)).catch(() => {});
    fetch(`${API}/mines?limit=50`).then(r => r.json())
      .then(d => d.code === 0 && setMines(d.data)).catch(() => {});
    fetch(`${API}/portfolio-risk`).then(r => r.json())
      .then(d => d.code === 0 && setPfRisk(d.data)).catch(() => {});
    fetch(`${API}/dividend-calendar`).then(r => r.json())
      .then(d => d.code === 0 && setDivCal(d.data)).catch(() => {});
    fetch(`${API}/closed-performance`).then(r => r.json())
      .then(d => d.code === 0 && setClosedPerf(d.data)).catch(() => {});
    fetch(`${API}/pass`).then(r => r.json())
      .then(d => d.code === 0 && setPassData(d.data)).catch(() => {});
    fetch(`${API}/calibration`).then(r => r.json())
      .then(d => d.code === 0 && setCalib(d.data)).catch(() => {});
    fetch(`${API}/pipeline`).then(r => r.json())
      .then(d => d.code === 0 && setPipelineD(d.data)).catch(() => {});
    fetch(`${API}/stress-test`).then(r => r.json())
      .then(d => d.code === 0 && setStress(d.data)).catch(() => {});
  }, []);

  async function scanMines(scope: 'positions' | 'market') {
    setMining(true);
    try {
      await fetch(`${API}/mines/scan`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scope}),
      });
      const d = await (await fetch(`${API}/mines?limit=50`)).json();
      if (d.code === 0) setMines(d.data);
      load();
    } finally {setMining(false);}
  }

  async function markReviewed() {
    await fetch(`${API}/review`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({note: ''}),
    });
    load();
  }
  async function removePass(id: number) {
    if (!window.confirm('删除这条放弃记录？')) return;
    await fetch(`${API}/pass/${id}`, {method: 'DELETE'});
    load();
  }
  useEffect(load, [load]);

  if (selected != null) {
    return <div className="thesis-page">
      <Detail id={selected} onBack={() => setSelected(null)} onChanged={load}/>
    </div>;
  }

  return (
    <div className="thesis-page">
      <PageHeader
        title="持仓体检"
        subtitle="论点即持仓：登记买入逻辑与可证伪假设，财报联动自动重估，论点破即卖。"
        actions={<>
          <Button onClick={() => setShowPassForm(true)}>记一笔放弃</Button>{' '}
          <Button variant="primary" onClick={() => setShowCreate(true)}>+ 登记论点</Button>
        </>}
      />
      <ThermometerCard variant="compact" />

      {review?.stale_review && (
        <div className="thesis-review-banner">
          ⏳ 已超过 30 天未复盘（上次：{review.last_review_at?.slice(0, 10) ?? '从未'}）
          <Button size="sm" onClick={markReviewed}>标记已复盘</Button>
          <Button size="sm" onClick={() => setShowReview(true)}>查看复盘</Button>
        </div>
      )}
      {list.length === 0 && (
        <StateView state="empty" text="还没有登记论点——从自选股或财务分析页进入，或点击右上角登记"/>
      )}
      <div className="thesis-list">
        {list.map(t => (
          <div key={t.id} className={`thesis-card${t.stale ? ' thesis-card--stale' : ''}`}
               onClick={() => setSelected(t.id)}>
            <div className="thesis-card__head">
              <span className="mono">{t.symbol}</span>
              {t.pnl_pct != null && (
                <span className={t.pnl_pct >= 0 ? 'pos' : 'neg'}>{fmtPct(t.pnl_pct)}</span>
              )}
              {t.condition_summary && t.condition_summary.breached > 0 ? (
                <Badge variant="danger">{t.condition_summary.breached} 条破位</Badge>
              ) : t.condition_summary && t.condition_summary.unknown > 0 ? (
                <Badge variant="info">{t.condition_summary.unknown} 条待评估</Badge>
              ) : (
                <Badge variant="success">论点成立</Badge>
              )}
              {t.last_reeval_verdict && (
                <span style={{color: VERDICT_TONE[t.last_reeval_verdict]}}>
                  {t.last_reeval_verdict}
                </span>
              )}
              {t.stale && <Badge variant="warning">90天未复检</Badge>}
            </div>
            <p className="thesis-card__text">{t.thesis_text || '—'}</p>
            {t.target_band && (
              <p className="thesis-card__band dim">
                卖出带 {t.target_band.metric} {t.target_band.low}~{t.target_band.high}
              </p>
            )}
          </div>
        ))}
      </div>

      {closed.length > 0 && (
        <div className="thesis-closed">
          <button className="thesis-closed__toggle" onClick={() => setShowClosed(!showClosed)}>
            已关闭（{closed.length}）{showClosed ? '▴' : '▾'}
          </button>
          {showClosed && (
            <>
            <table className="thesis-table">
              <thead><tr><th>标的</th><th>关闭原因</th><th>关闭价</th><th>时间</th><th>关闭后</th></tr></thead>
              <tbody>
                {closed.map(t => {
                  const perf = closedPerf?.rows?.find(
                    (p: any) => p.id === t.id);
                  return (
                    <tr key={t.id}>
                      <td className="mono">{t.symbol}</td>
                      <td>{t.close_reason}</td>
                      <td>{t.close_price ?? '—'}</td>
                      <td>{t.closed_at?.slice(0, 10)}</td>
                      <td>
                        {perf ? (
                          <span className={perf.since_close_pct >= 0 ? 'neg' : 'pos'}>
                            {perf.since_close_pct >= 0 ? '+' : ''}
                            {perf.since_close_pct}%（{perf.verdict}）
                          </span>
                        ) : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {closedPerf?.summary?.count > 0 && (
              <p className="dim">
                关闭后平均 {closedPerf.summary.avg_pct}% · 卖飞 {closedPerf.summary.sold_early_count}/{closedPerf.summary.count}
                （正=关闭后上涨=卖飞）
              </p>
            )}
            </>
          )}
        </div>
      )}

      {passData && passData.rows?.length > 0 && (
        <div className="thesis-closed">
          <button className="thesis-closed__toggle" onClick={() => setShowPass(!showPass)}>
            放弃决策（{passData.rows.length}）{showPass ? '▴' : '▾'}
          </button>
          {showPass && (
            <>
            <table className="thesis-table">
              <thead><tr>
                <th>标的</th><th>放弃日</th><th>当时价</th><th>现价</th>
                <th>放弃后</th><th>vs基准</th><th>判定</th>
                <th>理由</th><th>信心</th><th></th>
              </tr></thead>
              <tbody>
                {passData.rows.map((r: any) => (
                  <tr key={r.id}>
                    <td className="mono">{r.symbol}{r.name ? ` ${r.name}` : ''}</td>
                    <td>{r.decision_date ?? '—'}</td>
                    <td className="mono">{r.price ?? '—'}</td>
                    <td className="mono">{r.current_price ?? '—'}</td>
                    <td className={r.since_pct != null
                      ? (r.since_pct >= 0 ? 'neg' : 'pos') : ''}>
                      {r.since_pct != null
                        ? `${r.since_pct >= 0 ? '+' : ''}${r.since_pct}%` : '—'}
                    </td>
                    <td className="mono">
                      {r.excess_pct != null
                        ? `${r.excess_pct > 0 ? '+' : ''}${r.excess_pct}%` : '—'}
                    </td>
                    <td>
                      {r.verdict
                        ? <span className={r.verdict === '踏空' ? 'neg' : 'pos'}>
                            {r.verdict}
                          </span>
                        : '—'}
                    </td>
                    <td className="dim" title={r.reason}>
                      {r.reason.length > 16 ? r.reason.slice(0, 16) + '…' : r.reason}
                      {r.revisit_when && `（重看:${r.revisit_when}）`}
                    </td>
                    <td>{r.confidence ?? '—'}</td>
                    <td>
                      {r.decision_date && (
                        <Button size="sm" onClick={() =>
                          navigate(`/replay?symbol=${r.symbol}&start=${r.decision_date}`)
                        }>时光机重演</Button>
                      )}{' '}
                      <Button size="sm" onClick={() => removePass(r.id)}>删</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {passData.summary?.count > 0 && (
              <p className="dim">
                放弃后平均 {passData.summary.avg_since_pct}% vs 基准
                {' '}{passData.summary.avg_bench_pct}%（超额
                {' '}{passData.summary.avg_excess_pct}%）·
                踏空 {passData.summary.missed_count}/{passData.summary.count}
                （正超额=没买跑输基准=踏空）
              </p>
            )}
            </>
          )}
        </div>
      )}

      {mines.length > 0 && (
        <div className="thesis-review">
          <button className="thesis-closed__toggle" onClick={() => setShowMines(!showMines)}>
            排雷雷达（高危 {mines.filter(m => m.risk_level === 'high').length} / 共 {mines.length}）{showMines ? '▴' : '▾'}
          </button>
          {showMines && (
            <table className="thesis-table">
              <thead><tr><th>标的</th><th>Z</th><th>M</th><th>红旗</th><th>等级</th><th>财报期</th></tr></thead>
              <tbody>
                {mines.map(m => (
                  <tr key={`${m.symbol}-${m.report_date}`}>
                    <td className="mono">
                      <a style={{color: 'var(--color-accent)', cursor: 'pointer'}}
                         onClick={() => navigate(`/financial?symbol=${ensurePrefixed(m.symbol)}`)}>
                        {m.symbol}{m.name ? ` ${m.name}` : ''}
                      </a>
                    </td>
                    <td className="mono" title={m.z_verdict ?? ''}>{m.z ?? '—'}</td>
                    <td className="mono" title={m.m_verdict ?? ''}>{m.m ?? '—'}</td>
                    <td>{m.fraud_severity ?? '—'}</td>
                    <td><span style={{color: m.risk_level === 'high' ? 'var(--color-danger)' : 'var(--color-warning)'}}>{m.risk_level}</span></td>
                    <td>{m.report_date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      {divCal && divCal.rows?.length > 0 && (
        <div className="thesis-review">
          <button className="thesis-closed__toggle" onClick={() => setShowDiv(!showDiv)}>
            股息日历（未来12月预期 {((divCal.total_next_12m ?? 0) / 1e4).toFixed(1)} 万元）{showDiv ? '▴' : '▾'}
          </button>
          {showDiv && (
            <table className="thesis-table">
              <thead><tr><th>标的</th><th>股数</th><th>年化每股(元)</th><th>年增速</th><th>未来12月(元)</th><th>排期</th></tr></thead>
              <tbody>
                {divCal.rows.map((r: any) => (
                  <tr key={r.symbol}>
                    <td className="mono">{r.symbol}</td>
                    <td>{r.shares}</td>
                    <td className="mono">{r.latest_annual_dps ?? '—'}</td>
                    <td>{r.growth_pct != null ? r.growth_pct + '%' : '年度未完'}</td>
                    <td className="mono">{r.next_12m ?? '—'}</td>
                    <td className="dim">
                      {(r.monthly ?? []).map((m: any) =>
                        `${m.month.slice(2)}:${m.amount}` +
                        (m.tax_rate_pct != null
                          ? `(税${m.tax_rate_pct}%)` : '')).join(' ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {pfRisk && pfRisk.positions > 0 && (
        <div className="thesis-review">
          <button className="thesis-closed__toggle" onClick={() => setShowPf(!showPf)}>
            组合体检（{pfRisk.positions} 持仓 · 有效仓位 {pfRisk.correlation.effective_positions ?? '—'}）{showPf ? '▴' : '▾'}
          </button>
          {showPf && (
            <div className="thesis-review__body">
              {pfRisk.flags?.length > 0 && (
                <p className="neg">⚠ {pfRisk.flags.join('；')}</p>
              )}
              <table className="thesis-table">
                <thead><tr><th>行业</th><th>持仓数</th><th>权重</th></tr></thead>
                <tbody>
                  {pfRisk.groups.map((g: any) => (
                    <tr key={g.industry}>
                      <td>{g.industry}</td>
                      <td>{g.count}</td>
                      <td className={g.weight_pct > 40 ? 'neg' : ''}>{g.weight_pct}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {pfRisk.correlation.pairs?.length > 0 && (
                <table className="thesis-table">
                  <thead><tr><th>标的对</th><th>相关系数</th></tr></thead>
                  <tbody>
                    {pfRisk.correlation.pairs.map((c: any, i: number) => (
                      <tr key={i}>
                        <td className="mono">{c.a} / {c.b}</td>
                        <td className={c.rho > 0.7 ? 'neg' : ''}>{c.rho}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="dim">
                组合加权 PE {pfRisk.valuation.pe_ttm ?? '—'} · PB {pfRisk.valuation.pb ?? '—'}
                （权重=市值/持仓总市值，不含现金）
              </p>
              {stress?.scenarios?.length > 0 && (
                <div>
                  <h4>压力测试（历史极端窗口）</h4>
                  <table className="thesis-table">
                    <thead><tr><th>场景</th><th>指数</th><th>本组合</th><th>最大拖累</th></tr></thead>
                    <tbody>
                      {stress.scenarios.map((sc: any) => (
                        <tr key={sc.name}>
                          <td>{sc.name}</td>
                          <td className="neg">{sc.index_drop_pct}%</td>
                          <td className="neg">{sc.portfolio_pct}%</td>
                          <td className="mono">{sc.worst_symbol} {sc.worst_pct}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {pipelineD && pipelineD.counts && (
        <div className="thesis-review">
          <button className="thesis-closed__toggle" onClick={() => setShowPipe(!showPipe)}>
            研究管道（持仓 {pipelineD.counts.holding} · 已关闭 {pipelineD.counts.closed} · 待决策 {pipelineD.counts.checked} · 研究中 {pipelineD.counts.noted} · 观察 {pipelineD.counts.watching}）{showPipe ? '▴' : '▾'}
          </button>
          {showPipe && (
            <table className="thesis-table">
              <thead><tr><th>标的</th><th>阶段</th><th>直达</th></tr></thead>
              <tbody>
                {pipelineD.rows.map((r: any) => (
                  <tr key={r.symbol}>
                    <td className="mono">{r.symbol}</td>
                    <td className={r.stage === 'checked' ? 'neg' : ''}>
                      {r.stage_label}{r.stage === 'checked' ? ' ⚠' : ''}
                    </td>
                    <td>
                      <Link to={`/financial?symbol=${r.symbol}`}>财务</Link>
                      {' '}·{' '}
                      <Link to={`/checklist?symbol=${r.symbol}`}>体检</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <div style={{display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-2)'}}>
        <Button size="sm" loading={mining} onClick={() => scanMines('positions')}>持仓排雷精查（Z+M+红旗）</Button>
        <Button size="sm" loading={mining} onClick={() => scanMines('market')}>全市场 Z 扫描</Button>
      </div>

      {review && (review.closed_stats?.length > 0 || review.recent_decisions?.length > 0) && (
        <div className="thesis-review">
          <button className="thesis-closed__toggle" onClick={() => setShowReview(!showReview)}>
            复盘{showReview ? '▴' : '▾'}
          </button>
          {showReview && (
            <div className="thesis-review__body">
              <p className="dim">
                决策记分卡：持仓 {list.length} · 已关闭 {closed.length}
                {review.closed_stats?.length > 0 && (
                  <>（合计 {review.closed_stats.reduce((a: number, s: any) => a + s.count, 0)} 笔，
                  胜率 {Math.round(review.closed_stats.reduce((a: number, s: any) => a + s.win_count, 0)
                    / review.closed_stats.reduce((a: number, s: any) => a + s.count, 0) * 100)}%）</>
                )}
                {' '}· 放弃 {passData?.rows?.length ?? 0}
                {passData?.summary?.count > 0 && (
                  <>（踏空 {passData.summary.missed_count}/{passData.summary.count}，
                  平均超额 {passData.summary.avg_excess_pct}%）</>
                )}
              </p>
              {calib?.groups?.length > 0 && (
                <div>
                  <h4>信心度校准（按登记时信心分组，已关闭论点）</h4>
                  <table className="thesis-table">
                    <thead><tr><th>信心度</th><th>笔数</th><th>盈利笔数</th><th>胜率</th><th>平均盈亏</th></tr></thead>
                    <tbody>
                      {calib.groups.map((g: any) => (
                        <tr key={g.confidence}>
                          <td>{g.confidence}</td>
                          <td>{g.count}</td>
                          <td>{g.win_count}/{g.count}</td>
                          <td>{(g.win_rate * 100).toFixed(0)}%</td>
                          <td className={g.avg_pnl_pct >= 0 ? 'pos' : 'neg'}>
                            {g.avg_pnl_pct >= 0 ? '+' : ''}{g.avg_pnl_pct}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="dim">
                    {calib.no_confidence_count > 0 &&
                      `另有 ${calib.no_confidence_count} 笔未记信心度；`}
                    信心与胜率长期无梯度 = 过度自信的信号。
                  </p>
                </div>
              )}
              {review.closed_stats?.length > 0 && (
                <table className="thesis-table">
                  <thead><tr><th>关闭原因</th><th>笔数</th><th>平均盈亏</th><th>盈利笔数</th></tr></thead>
                  <tbody>
                    {review.closed_stats.map((st: any) => (
                      <tr key={st.reason}>
                        <td>{st.reason}</td>
                        <td>{st.count}</td>
                        <td className={st.avg_pnl_pct >= 0 ? 'pos' : 'neg'}>
                          {st.avg_pnl_pct >= 0 ? '+' : ''}{st.avg_pnl_pct}%
                        </td>
                        <td>{st.win_count}/{st.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {review.recent_decisions?.length > 0 && (
                <table className="thesis-table">
                  <thead><tr><th>时间</th><th>标的</th><th>类型</th><th>决策/备注</th><th>时价</th></tr></thead>
                  <tbody>
                    {review.recent_decisions.map((d: any) => (
                      <tr key={d.id}>
                        <td>{d.created_at?.slice(0, 16)}</td>
                        <td className="mono">{d.symbol ?? d.thesis_id}</td>
                        <td>{d.kind}</td>
                        <td>{[d.decision, d.note].filter(Boolean).join(' · ') || '—'}</td>
                        <td className="mono">{d.price ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      )}

      {showCreate && (
        <CreateDialog
          initialSymbol={prefill}
          initialBuyPrice={prefillPrice}
          initialShares={prefillShares}
          onDone={() => {setShowCreate(false); load();}}
          onClose={() => setShowCreate(false)}
        />
      )}
      {showPassForm && (
        <PassDialog
          onDone={() => {setShowPassForm(false); load();}}
          onClose={() => setShowPassForm(false)}
        />
      )}
    </div>
  );
};
