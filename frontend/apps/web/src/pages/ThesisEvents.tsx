/** 预警中心"持仓论点"分区：重估/破位/到价事件流。 */
import React, {useEffect, useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {getApiBase} from '../lib/api';
import {ensurePrefixed} from '../lib/symbol';

const API = getApiBase();

interface TEvent {
  id: number;
  thesis_id: number;
  symbol: string | null;
  kind: string;
  detail: any;
  read: boolean;
  created_at: string;
}

const KIND_LABEL: Record<string, string> = {
  reeval_done: '财报重估',
  condition_breached: '论点破位',
  price_band_reached: '估值带到价',
  mine_detected: '排雷告警',
};
const VERDICT_TONE: Record<string, string> = {
  pass: 'var(--color-success)', review: 'var(--color-warning)',
  sell_signal: 'var(--color-danger)',
};

export const ThesisEventsSection: React.FC = () => {
  const navigate = useNavigate();
  const [events, setEvents] = useState<TEvent[]>([]);

  const load = () => {
    fetch(`${API}/thesis/events/list`).then(r => r.json())
      .then(d => d.code === 0 && setEvents(d.data)).catch(() => {});
  };
  useEffect(load, []);

  const markRead = async (id: number) => {
    await fetch(`${API}/thesis/events/${id}/read`, {method: 'PUT'});
    load();
  };

  if (events.length === 0) return null;
  return (
    <section className="alerts-thesis">
      <h3 className="alerts-thesis__title">
        持仓论点（{events.filter(e => !e.read).length} 未读）
      </h3>
      <table className="thesis-table">
        <thead>
          <tr><th>时间</th><th>标的</th><th>事件</th><th>详情</th><th></th></tr>
        </thead>
        <tbody>
          {events.map(e => (
            <tr key={e.id} style={e.read ? {opacity: .55} : undefined}>
              <td>{e.created_at?.slice(5, 16)}</td>
              <td className="mono">
                {e.symbol
                  ? <a style={{color: 'var(--color-accent)', cursor: 'pointer'}}
                       onClick={() => navigate(`/financial?symbol=${ensurePrefixed(e.symbol)}`)}>
                      {e.symbol}{e.name ? ` ${e.name}` : ''}
                    </a>
                  : e.thesis_id}
              </td>
              <td>{KIND_LABEL[e.kind] || e.kind}</td>
              <td>
                {e.kind === 'reeval_done' && (
                  <span style={{color: VERDICT_TONE[e.detail?.verdict] || undefined}}>
                    {e.detail?.verdict}
                  </span>
                )}
                {e.kind === 'condition_breached' &&
                  `${(e.detail?.breached || []).join('、')} 破位`}
                {e.kind === 'price_band_reached' &&
                  `现值 ${e.detail?.current} 进入卖出带`}
                {e.kind === 'mine_detected' &&
                  (e.detail?.reasons || []).join('；')}
              </td>
              <td>{!e.read && <button onClick={() => markRead(e.id)}>已读</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
};
