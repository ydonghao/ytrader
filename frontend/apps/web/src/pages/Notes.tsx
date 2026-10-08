/**
 * 研究笔记 — Notes
 * 路径：/notes（菜单"研究笔记"）
 *
 * 年报阅读/调研/思考按标的沉淀——能力圈的实体化。
 */
import React, {useState, useEffect, useCallback} from 'react';
import {getApiBase} from '../lib/api';
import {PageHeader, StateView} from '../components/ui';
import {Button} from '@ytrader/common-components';
import {StockSearch} from '../components/StockSearch';
import './Notes.css';

const API = getApiBase();

interface Note {
  id: number;
  symbol: string;
  title: string;
  content: string;
  updated_at: string;
}

export const Notes: React.FC = () => {
  const qp = new URLSearchParams(window.location.search);
  const [filter, setFilter] = useState(qp.get('symbol') || '');
  const [input, setInput] = useState('');
  const [notes, setNotes] = useState<Note[]>([]);
  const [editing, setEditing] = useState<Partial<Note> | null>(null);

  const load = useCallback(() => {
    const q = filter ? `?symbol=${filter}` : '';
    fetch(`${API}/thesis/notes${q}`).then(r => r.json())
      .then(d => d.code === 0 && setNotes(d.data)).catch(() => {});
  }, [filter]);
  useEffect(load, [load]);

  async function save() {
    if (!editing?.symbol || !editing.title?.trim()) return;
    const body = JSON.stringify({
      symbol: editing.symbol.toLowerCase(),
      title: editing.title, content: editing.content || '',
    });
    if (editing.id) {
      await fetch(`${API}/thesis/notes/${editing.id}`, {
        method: 'PUT', headers: {'Content-Type': 'application/json'},
        body,
      });
    } else {
      await fetch(`${API}/thesis/notes`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body,
      });
    }
    setEditing(null);
    load();
  }

  async function remove(id: number) {
    await fetch(`${API}/thesis/notes/${id}`, {method: 'DELETE'});
    load();
  }

  return (
    <div className="notes-page">
      <PageHeader
        title="研究笔记"
        subtitle="年报阅读、调研记录、投资思考——按标的沉淀，能力圈的实体化。"
        actions={<Button variant="primary" onClick={() =>
          setEditing({symbol: filter})}>+ 新笔记</Button>}
      />
      <div className="notes__filter">
        <StockSearch value={input} onSelect={(s) => {setFilter(s.toLowerCase()); setInput('');}}/>
        {filter && (
          <span className="notes__chip mono"
                onClick={() => setFilter('')}>{filter} ×</span>
        )}
        <span className="dim">共 {notes.length} 条</span>
      </div>
      {notes.length === 0 && !editing && (
        <StateView state="empty" text="还没有笔记——从财务分析页深链进入，或点右上角新建"/>
      )}
      {editing && (
        <div className="notes__editor">
          <div className="notes__editor-row">
            <StockSearch value={editing.symbol || ''}
                         onSelect={(s) => setEditing({...editing, symbol: s})}/>
            <input placeholder="标题" value={editing.title || ''}
                   onChange={e => setEditing({...editing, title: e.target.value})}/>
          </div>
          <textarea rows={8} placeholder="正文"
                    value={editing.content || ''}
                    onChange={e => setEditing({...editing, content: e.target.value})}/>
          <div className="notes__editor-actions">
            <Button variant="primary" onClick={save}>保存</Button>
            <Button onClick={() => setEditing(null)}>取消</Button>
          </div>
        </div>
      )}
      <div className="notes__list">
        {notes.map(n => (
          <div key={n.id} className="notes__item"
               onClick={() => setEditing({...n})}>
            <div className="notes__item-head">
              <span className="mono">{n.symbol}</span>
              <b>{n.title}</b>
              <span className="dim">{n.updated_at?.slice(0, 10)}</span>
              <button className="notes__del"
                      onClick={(e) => {e.stopPropagation(); remove(n.id);}}>
                删
              </button>
            </div>
            {n.content && (
              <p className="notes__item-body">
                {n.content.length > 120
                  ? n.content.slice(0, 120) + '…' : n.content}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};
