/** 预警中心统一收件箱：价格/指标/论点事件合并时间流。 */
import React, {useEffect, useState} from 'react';
import {getApiBase} from '../lib/api';

const API = getApiBase();

interface Item {
  kind: 'price' | 'metric' | 'thesis';
  symbol: string | null;
  message: string;
  time: string;
  read?: boolean;
  event_id?: number;
}

const KIND_LABEL: Record<string, string> = {
  price: '价格', metric: '指标', thesis: '论点',
};
const KIND_TONE: Record<string, string> = {
  price: 'var(--color-accent)', metric: 'var(--color-warning)',
  thesis: 'var(--color-success)',
};

export const UnifiedInbox: React.FC = () => {
  const [items, setItems] = useState<Item[]>([]);

  const load = () => {
    fetch(`${API}/alerts/unified?limit=50`).then(r => r.json())
      .then(d => d.code === 0 && setItems(d.data)).catch(() => {});
  };
  useEffect(load, []);

  const markRead = async (id: number) => {
    await fetch(`${API}/thesis/events/${id}/read`, {method: 'PUT'});
    load();
  };

  if (items.length === 0) return null;
  return (
    <section className="alerts-page__section">
      <h3 className="alerts-thesis__title">统一收件箱（最近 {items.length} 条）</h3>
      <table className="thesis-table">
        <thead><tr><th>时间</th><th>类型</th><th>标的</th><th>消息</th><th></th></tr></thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={i} style={it.read ? {opacity: .55} : undefined}>
              <td>{it.time?.slice(5, 16)}</td>
              <td>
                <span style={{color: KIND_TONE[it.kind]}}>
                  {KIND_LABEL[it.kind]}
                </span>
              </td>
              <td className="mono">{it.symbol ?? '—'}</td>
              <td>{it.message}</td>
              <td>
                {it.kind === 'thesis' && !it.read && it.event_id && (
                  <button onClick={() => markRead(it.event_id!)}>已读</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
};
