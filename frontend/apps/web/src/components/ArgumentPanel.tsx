/**
 * ArgumentPanel — AI 陪练论证库（Financial 页 Tab）。
 *
 * 六层第⑥件：LLM 用库内真实数据产 bull/bear 初稿 → 用户逐条核对
 * 修订 → 归档为该公司的论证库。AI 只产初稿与反方论证，
 * 事实一律回原始材料核对。
 */
import {useCallback, useEffect, useReducer, useState} from 'react';
import {getApiBase} from '../lib/api';
import {AiInsightPanel} from './AiInsightPanel';
import {aiTaskReducer} from '../lib/aiTask';

const API_BASE = getApiBase();
const ARG_API = `${API_BASE}/arguments`;

const SIDE_LABEL: Record<string, string> = {bull: '多头', bear: '空头'};
const SIDE_COLOR: Record<string, string> = {
  bull: 'var(--color-danger)',    // A股红涨
  bear: 'var(--color-success)',   // 绿跌
};

interface ArgRow {
  id: number;
  symbol: string;
  side: 'bull' | 'bear';
  status: 'draft' | 'archived';
  content: string;
  evidence: string | null;
  generated_by: string | null;
  created_at: string;
  updated_at: string;
}

export function ArgumentPanel({symbol}: {symbol: string}) {
  const [rows, setRows] = useState<ArgRow[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, ArgRow>>({});
  const [task, dispatch] = useReducer(aiTaskReducer, {status: 'idle'});
  // generating 语义 = 正在为某 side 生成初稿；保留 side 记录，加载/错误态由 reducer 管
  const [genSide, setGenSide] = useState<'bull' | 'bear' | null>(null);
  // 编辑态（核对修订）
  const [editId, setEditId] = useState<number | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editEvidence, setEditEvidence] = useState('');
  // 手动录入
  const [mSide, setMSide] = useState('bull');
  const [mContent, setMContent] = useState('');

  const load = useCallback(() => {
    if (!symbol) { setRows(null); setDrafts({}); return; }
    fetch(`${ARG_API}/${symbol}`).then((r) => r.json())
      .then((j) => {
        if (j.code === 0) {
          setRows(j.data.rows);
          setDrafts(j.data.drafts || {});
        }
      })
      .catch(() => {});
  }, [symbol]);
  useEffect(load, [load]);

  const generate = async (side: 'bull' | 'bear') => {
    setGenSide(side);
    dispatch({type: 'start'});
    try {
      const r = await fetch(`${ARG_API}/${symbol}/generate`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({side}),
      });
      const j = await r.json();
      if (j.code !== 0) {
        // 失败保留 genSide，供壳的重试按钮再次触发该侧生成
        dispatch({type: 'fail', error: j.msg || '生成失败'});
        return;
      }
      load();
      setGenSide(null);
      dispatch({type: 'done'});
    } catch (e) {
      dispatch({type: 'fail', error: e instanceof Error ? e.message : '生成失败'});
    }
  };

  const startEdit = (row: ArgRow) => {
    setEditId(row.id);
    setEditContent(row.content);
    setEditEvidence(row.evidence || '');
  };

  const saveEdit = async () => {
    if (editId == null) return;
    await fetch(`${ARG_API}/${editId}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({content: editContent, evidence: editEvidence}),
    });
    setEditId(null);
    load();
  };

  const archive = async (row: ArgRow) => {
    const evidence = window.prompt(
      '核实依据（可空）：逐条核对过哪些数据/材料？', '') ?? '';
    await fetch(`${ARG_API}/${row.id}/archive`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({evidence}),
    });
    load();
  };

  const remove = async (id: number) => {
    if (!window.confirm('删除这条论证？')) return;
    await fetch(`${ARG_API}/${id}`, {method: 'DELETE'});
    load();
  };

  const addManual = async () => {
    if (!mContent.trim()) return;
    await fetch(`${ARG_API}/${symbol}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({side: mSide, content: mContent.trim()}),
    });
    setMContent('');
    load();
  };

  // loading/error 由 AiInsightPanel 壳统一渲染；空态亦包壳保持页面结构一致
  if (!symbol) {
    return (
      <AiInsightPanel
        title="AI 陪练论证库" source="LLM 初稿·人工核对"
        loading={task.status === 'loading'}
        error={task.status === 'error' ? task.error : null}
      >
        <div className="fin-hint">输入股票代码使用论证库。</div>
      </AiInsightPanel>
    );
  }
  const archived = (rows || []).filter((r) => r.status === 'archived');

  return (
    <AiInsightPanel
      title="AI 陪练论证库" source="LLM 初稿·人工核对"
      loading={task.status === 'loading'}
      error={task.status === 'error' ? task.error : null}
      onRetry={genSide ? () => void generate(genSide) : undefined}
    >
      {/* 业务内容原样迁入壳内容槽（草稿编辑/多空列表/手动新增/归档历史），零业务改动 */}
      <div style={{display: 'flex', flexDirection: 'column', gap: 12}}>
      <div className="fin-hint">
        AI 陪练：基于库内真实财报/估值数据生成多空初稿，你逐条核对修订后
        归档——事实一律回原始材料核对，AI 只产初稿与反方论证。
      </div>
      <div style={{display: 'flex', gap: 8, flexWrap: 'wrap'}}>
        <button className="dcf-copy-btn" style={{color: SIDE_COLOR.bull}}
          disabled={task.status === 'loading'}
          onClick={() => void generate('bull')}>
          生成多头初稿 ▲</button>
        <button className="dcf-copy-btn" style={{color: SIDE_COLOR.bear}}
          disabled={task.status === 'loading'}
          onClick={() => void generate('bear')}>
          生成空头初稿 ▼</button>
      </div>

      {/* 草稿区：bull/bear 并排 */}
      <div style={{display: 'flex', gap: 12, flexWrap: 'wrap'}}>
        {(['bull', 'bear'] as const).map((side) => {
          const d = drafts[side];
          return (
            <div key={side} style={{
              flex: '1 1 380px', minWidth: 300,
              border: '1px dashed var(--color-border, #30363d)',
              borderRadius: 8, padding: 12,
            }}>
              <h4 style={{margin: '0 0 8px', color: SIDE_COLOR[side]}}>
                {SIDE_LABEL[side]}论证
                {d && <span style={{fontSize: 11, marginLeft: 8,
                                     color: 'var(--color-text-secondary)'}}>
                  草稿 · {d.generated_by || ''} ·
                  {' '}{(d.updated_at || '').slice(0, 16)}
                </span>}
              </h4>
              {!d && <div className="fin-hint">
                暂无草稿——点击上方按钮生成。</div>}
              {d && editId !== d.id && (
                <>
                  <div style={{whiteSpace: 'pre-wrap', fontSize: 13,
                               lineHeight: 1.7}}>{d.content}</div>
                  {d.evidence && <p className="fin-hint">
                    核实依据：{d.evidence}</p>}
                  <div style={{display: 'flex', gap: 6, marginTop: 8}}>
                    <button className="dcf-copy-btn"
                      onClick={() => startEdit(d)}>核对修订</button>
                    <button className="dcf-copy-btn"
                      onClick={() => void archive(d)}>验证归档</button>
                    <button className="dcf-copy-btn"
                      onClick={() => void remove(d.id)}>删</button>
                  </div>
                </>
              )}
              {d && editId === d.id && (
                <>
                  <textarea style={{width: '100%', minHeight: 200}}
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)} />
                  <input style={{width: '100%'}} placeholder="核实依据（可空）"
                    value={editEvidence}
                    onChange={(e) => setEditEvidence(e.target.value)} />
                  <div style={{display: 'flex', gap: 6, marginTop: 8}}>
                    <button className="dcf-copy-btn"
                      onClick={() => void saveEdit()}>保存修订</button>
                    <button className="dcf-copy-btn"
                      onClick={() => setEditId(null)}>取消</button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>

      {/* 手动录入 */}
      <div style={{display: 'flex', gap: 8, flexWrap: 'wrap'}}>
        <select value={mSide} onChange={(e) => setMSide(e.target.value)}>
          <option value="bull">多头</option>
          <option value="bear">空头</option>
        </select>
        <input style={{flex: 1, minWidth: 240}} placeholder="手动录入一条论证（直接归档）"
          value={mContent} onChange={(e) => setMContent(e.target.value)} />
        <button className="dcf-copy-btn" disabled={!mContent.trim()}
          onClick={() => void addManual()}>归档</button>
      </div>

      {/* 归档历史 */}
      {archived.length > 0 && (
        <div>
          <h4 style={{margin: '0 0 6px'}}>论证库（已归档 {archived.length} 条）</h4>
          {archived.map((r) => (
            <details key={r.id} style={{
              borderBottom: '1px solid var(--color-border, #21262d)',
              padding: '6px 0',
            }}>
              <summary style={{cursor: 'pointer', fontSize: 13}}>
                <span style={{color: SIDE_COLOR[r.side]}}>
                  [{SIDE_LABEL[r.side]}]</span>
                {' '}{(r.content || '').slice(0, 50)}…
                <span style={{color: 'var(--color-text-secondary)',
                             fontSize: 11}}>
                  {' '}· {r.generated_by === 'manual' ? '手写'
                    : (r.generated_by || 'AI')} ·
                  {' '}{(r.updated_at || '').slice(0, 10)}
                </span>
              </summary>
              <div style={{whiteSpace: 'pre-wrap', fontSize: 13,
                           lineHeight: 1.7, padding: '6px 12px'}}>
                {r.content}
                {r.evidence && <p className="fin-hint">
                  核实依据：{r.evidence}</p>}
                <button className="dcf-copy-btn"
                  onClick={() => void remove(r.id)}>删</button>
              </div>
            </details>
          ))}
        </div>
      )}
      </div>
    </AiInsightPanel>
  );
}
