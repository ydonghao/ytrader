import {useCallback, useEffect, useState} from 'react';
import {StateView} from '../../components/ui';
import {ensurePrefixed} from '../../lib/symbol';
import * as api from './api';
import type {TrainingLogResp} from './api';
import {useReplayStore} from './store';
import type {LeaderboardRow, SessionMeta} from './types';

const fmtMoney = (v: number) =>
  v.toLocaleString('zh-CN', {maximumFractionDigits: 0});

const LENGTHS = [
  {v: 120, label: '半年(120日)'},
  {v: 250, label: '一年(250日)'},
  {v: 500, label: '两年(500日)'},
];
const ERAS = [
  {v: 'random', label: '完全随机'},
  {v: 'bull_top', label: '牛顶区'},
  {v: 'bear_bottom', label: '熊底区'},
  {v: 'range', label: '震荡区'},
];

export const SessionHome: React.FC = () => {
  const openSession = useReplayStore((s) => s.openSession);
  const [list, setList] = useState<SessionMeta[] | null>(null);
  const [board, setBoard] = useState<LeaderboardRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'free' | 'exam'>('free');
  // free 表单
  const [name, setName] = useState('');
  const [startDate, setStartDate] = useState('2020-01-02');
  const [endDate, setEndDate] = useState('');
  const [capital, setCapital] = useState(1000000);
  // exam 表单
  const [exCapital, setExCapital] = useState(100000);
  const [exLength, setExLength] = useState(250);
  const [exEra, setExEra] = useState('random');
  const [exName, setExName] = useState('');
  const [busy, setBusy] = useState(false);
  // 训练册 + 深链预填（/replay?symbol=sh600519&start=2024-01-05）
  const [training, setTraining] = useState<TrainingLogResp | null>(null);
  const [showTraining, setShowTraining] = useState(false);
  const [presetSymbol] = useState(() =>
    ensurePrefixed(
      new URLSearchParams(window.location.search).get('symbol') || '',
    ).toLowerCase());
  const [presetStart] = useState(() =>
    new URLSearchParams(window.location.search).get('start') || '');

  const refresh = useCallback(async () => {
    const r = await api.listSessions();
    if (r.code === 0) setList(r.data);
    else setError(r.msg || '加载失败');
    const b = await api.fetchLeaderboard();
    if (b.code === 0) setBoard(b.data);
    const t = await api.fetchTrainingLog();
    if (t.code === 0) setTraining(t.data);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // 从放弃决策"时光机重演"等深链进入:预填 free 表单
  useEffect(() => {
    if (!presetSymbol) return;
    setTab('free');
    setName((n) => n || `重演 ${presetSymbol}`);
    if (presetStart) setStartDate(presetStart);
  }, [presetSymbol, presetStart]);

  const createFree = async () => {
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
    if (presetSymbol) {
      // 深链带了标的:起飞后自动入池选中,省去手动搜索
      await useReplayStore.getState().addSymbol(presetSymbol);
    }
  };

  const createExam = async () => {
    setBusy(true);
    try {
      const r = await api.createExamSession({
        initial_capital: exCapital,
        length_days: exLength,
        era_pref: exEra,
        ...(exName.trim() ? {name: exName.trim()} : {}),
      });
      if (r.code !== 0) {
        setError(r.msg || '开局失败');
        return;
      }
      setError(null);
      await openSession(r.data.id);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    if (!window.confirm('删除这段旅程？不可恢复。')) return;
    await api.deleteSession(id);
    await refresh();
  };

  const dateCell = (s: SessionMeta) =>
    s.mode === 'exam' && s.status === 'active'
      ? `盲盒 第${s.day_ordinal}/${s.length_days}天`
      : `${s.start_date ?? '—'} ~ ${s.current_date ?? '—'}`;

  return (
    <div className="replay-page">
      <h3 style={{marginTop: 0}}>✈ 时光机 · 选择或开启一段旅程</h3>
      <div className="replay-panel" style={{marginBottom: 10}}>
        <h4>
          开启新旅程
          <span style={{display: 'inline-flex', gap: 6, marginLeft: 12}}>
            {(['free', 'exam'] as const).map((t) => (
              <button key={t}
                className={`replay-btn${tab === t ? ' primary' : ''}`}
                style={{padding: '1px 10px', fontSize: 12}}
                onClick={() => setTab(t)}>
                {t === 'free' ? '自由模式' : '🎯 拟真考核'}
              </button>
            ))}
          </span>
        </h4>
        {tab === 'free' ? (
          <>
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
              <button className="replay-btn primary"
                onClick={() => void createFree()}>
                起飞 ▶
              </button>
            </div>
            <div className="replay-hint">
              起始日非交易日会自动顺延到下一交易日；终点仅限定复盘数据范围,留空则一路开到数据尽头。
              {presetSymbol && '（已从链接预填标的与日期，起飞后自动入池）'}
            </div>
          </>
        ) : (
          <>
            <div style={{display: 'flex', gap: 8, flexWrap: 'wrap'}}>
              <input className="replay-input" style={{width: 130}}
                type="number" step={10000} value={exCapital}
                title="初始资金"
                onChange={(e) => setExCapital(Number(e.target.value))} />
              <select className="replay-input" style={{width: 130}}
                value={exLength}
                onChange={(e) => setExLength(Number(e.target.value))}>
                {LENGTHS.map((o) => (
                  <option key={o.v} value={o.v}>{o.label}</option>
                ))}
              </select>
              <select className="replay-input" style={{width: 110}}
                value={exEra}
                onChange={(e) => setExEra(e.target.value)}>
                {ERAS.map((o) => (
                  <option key={o.v} value={o.v}>{o.label}</option>
                ))}
              </select>
              <input className="replay-input" style={{width: 140}}
                placeholder="旅程名(可空)" value={exName}
                onChange={(e) => setExName(e.target.value)} />
              <button className="replay-btn primary" disabled={busy}
                onClick={() => void createExam()}>
                {busy ? '抽签中…' : '盲盒起飞 🎲'}
              </button>
            </div>
            <div className="replay-hint">
              随机抽一个你不知道的年代:全程隐藏日期(第N天)、一天8个时段逐段看盘、
              下单必须写理由、限价单收盘自动撤、分红送转自动落账;
              揭晓后评分入榜,一局定档不可重开。
            </div>
          </>
        )}
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
                <th>名称</th><th>模式</th><th>区间</th>
                <th>初始资金</th><th>现金</th><th>状态</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {list.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td>{s.mode === 'exam' ? '🎯 拟真' : '自由'}</td>
                  <td>{dateCell(s)}</td>
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
      <div className="replay-panel" style={{marginTop: 10}}>
        <h4>🏆 拟真榜(总分 = 超额收益 80 + 换手纪律 20)</h4>
        {board === null ? (
          <StateView state="loading" />
        ) : board.length === 0 ? (
          <div className="replay-hint">还没有已揭晓的拟真旅程——开一局试试。</div>
        ) : (
          <table className="replay-table">
            <thead>
              <tr>
                <th>#</th><th>名称</th><th>总分</th><th>超额分</th>
                <th>纪律分</th><th>年化超额</th><th>天数</th><th>期末</th>
              </tr>
            </thead>
            <tbody>
              {board.map((r, i) => (
                <tr key={r.id}>
                  <td>{i + 1}</td>
                  <td>{r.name}</td>
                  <td><b>{r.score.toFixed(1)}</b></td>
                  <td>{r.excess_score.toFixed(1)}</td>
                  <td>{r.turnover_score.toFixed(1)}</td>
                  <td>{r.annual_excess_pct >= 0 ? '+' : ''}
                    {r.annual_excess_pct}%</td>
                  <td>{r.days}</td>
                  <td>{r.final == null ? '—'
                    : fmtMoney(r.final)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="replay-panel" style={{marginTop: 10}}>
        <h4>
          📚 训练册（跨旅程下单理由沉淀）
          {training && training.trades.length > 0 && (
            <button className="replay-btn"
              style={{padding: '1px 10px', fontSize: 12, marginLeft: 12}}
              onClick={() => setShowTraining(!showTraining)}>
              {showTraining ? '收起 ▴' : `展开 ${training.trades.length} 笔 ▾`}
            </button>
          )}
        </h4>
        {training == null ? (
          <StateView state="loading" />
        ) : training.trades.length === 0 ? (
          <div className="replay-hint">
            还没有已揭晓拟真旅程的下单记录——拟真考核里必填的下单理由会沉淀到这里,
            跨旅程翻阅,复盘判断的演变。
          </div>
        ) : showTraining && (
          <table className="replay-table">
            <thead>
              <tr>
                <th>旅程</th><th>日期</th><th>标的</th><th>方向</th>
                <th>价</th><th>信心</th><th>理由</th>
              </tr>
            </thead>
            <tbody>
              {training.trades.slice(0, 200).map((t) => (
                <tr key={t.id}>
                  <td>{t.session_name}</td>
                  <td>{t.trade_date}</td>
                  <td className="mono">{t.symbol}</td>
                  <td>{t.side === 'buy' ? '买' : '卖'}</td>
                  <td className="mono">{t.price.toFixed(2)}</td>
                  <td>{t.confidence ?? '—'}</td>
                  <td className="dim">{t.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
