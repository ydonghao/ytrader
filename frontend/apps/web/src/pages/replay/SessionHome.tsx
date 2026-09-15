import {useCallback, useEffect, useState} from 'react';
import {StateView} from '../../components/ui';
import * as api from './api';
import {useReplayStore} from './store';
import type {SessionMeta} from './types';

const fmtMoney = (v: number) =>
  v.toLocaleString('zh-CN', {maximumFractionDigits: 0});

export const SessionHome: React.FC = () => {
  const openSession = useReplayStore((s) => s.openSession);
  const [list, setList] = useState<SessionMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [startDate, setStartDate] = useState('2020-01-02');
  const [endDate, setEndDate] = useState('');
  const [capital, setCapital] = useState(1000000);

  const refresh = useCallback(async () => {
    const r = await api.listSessions();
    if (r.code === 0) setList(r.data);
    else setError(r.msg || '加载失败');
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = async () => {
    if (!name.trim()) {
      setError('给旅程起个名字');
      return;
    }
    const r = await api.createSession({
      name: name.trim(),
      start_date: startDate,
      initial_capital: capital,
      ...(endDate ? {end_date: endDate} : {}),
    });
    if (r.code !== 0) {
      setError(r.msg || '创建失败');
      return;
    }
    setError(null);
    await openSession(r.data.id);
  };

  const remove = async (id: number) => {
    if (!window.confirm('删除这段旅程？不可恢复。')) return;
    await api.deleteSession(id);
    await refresh();
  };

  return (
    <div className="replay-page">
      <h3 style={{marginTop: 0}}>✈ 时光机 · 选择或开启一段旅程</h3>
      <div className="replay-panel" style={{marginBottom: 10}}>
        <h4>开启新旅程</h4>
        <div style={{display: 'flex', gap: 8, flexWrap: 'wrap'}}>
          <input className="replay-input" style={{width: 180}}
            placeholder="旅程名称" value={name}
            onChange={(e) => setName(e.target.value)} />
          <input className="replay-input" style={{width: 150}}
            type="date" value={startDate}
            onChange={(e) => setStartDate(e.target.value)} />
          <input className="replay-input" style={{width: 150}}
            type="date" value={endDate} placeholder="终点(可选)"
            onChange={(e) => setEndDate(e.target.value)} />
          <input className="replay-input" style={{width: 130}}
            type="number" step={100000} value={capital}
            onChange={(e) => setCapital(Number(e.target.value))} />
          <button className="replay-btn primary" onClick={() => void create()}>
            起飞 ▶
          </button>
        </div>
        <div className="replay-hint">
          起始日非交易日会自动顺延到下一交易日；终点仅限定复盘数据范围（到点不会自动揭晓），留空则一路开到数据尽头。
        </div>
        {error && <div className="replay-error">{error}</div>}
      </div>
      <div className="replay-panel">
        <h4>历史旅程</h4>
        {list === null ? (
          <StateView state="loading" />
        ) : list.length === 0 ? (
          <StateView state="empty" />
        ) : (
          <table className="replay-table">
            <thead>
              <tr>
                <th>名称</th><th>起始</th><th>当前</th><th>初始资金</th>
                <th>现金</th><th>状态</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {list.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td>{s.start_date}</td>
                  <td>{s.current_date}</td>
                  <td>{fmtMoney(s.initial_capital)}</td>
                  <td>{fmtMoney(s.cash)}</td>
                  <td>{s.status === 'revealed' ? '已揭晓' : '航行中'}</td>
                  <td>
                    <button className="replay-btn"
                      onClick={() => void openSession(s.id)}>
                      {s.status === 'revealed' ? '查看复盘' : '继续'}
                    </button>{' '}
                    <button className="replay-btn"
                      onClick={() => void remove(s.id)}>
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
