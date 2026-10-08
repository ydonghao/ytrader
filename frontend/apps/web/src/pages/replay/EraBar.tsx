import {useEffect, useState} from 'react';
import * as api from './api';
import {useBlind, useDayLabel} from './BlindMask';
import {useReplayStore, viewDate} from './store';
import type {NewsItem} from './types';

interface MacroEvent { date: string; title: string; desc: string; }

let eventsCache: MacroEvent[] | null = null;  // 12 条静态,模块级缓存

const daysBefore = (iso: string, n: number): string => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
};

const mmdd = (iso: string): string => iso.slice(5, 10);

export const EraBar: React.FC = () => {
  const vd = useReplayStore(viewDate);
  const blind = useBlind();
  const dayLabel = useDayLabel();
  const [events, setEvents] = useState<MacroEvent[]>(eventsCache ?? []);
  const [newsItems, setNewsItems] = useState<NewsItem[]>([]);
  const [showNews, setShowNews] = useState(false);

  useEffect(() => {
    if (eventsCache) return;
    void api.fetchMacroEvents().then((r) => {
      if (r.code === 0) { eventsCache = r.data; setEvents(r.data); }
    });
  }, []);

  useEffect(() => {
    if (!vd) return;
    let off = false;
    setNewsItems([]);
    void api.fetchNews(vd, 3).then((r) => {
      if (!off && r.code === 0) setNewsItems(r.data);
    });
    return () => { off = true; };
  }, [vd]);

  if (!vd) return null;
  const cutoff = daysBefore(vd, 60);
  const recent = events
    .filter((e) => e.date <= vd && e.date >= cutoff)
    .sort((a, b) => (a.date < b.date ? 1 : -1))
    .slice(0, 3);
  return (
    <div className="replay-era">
      <span style={{color: '#86868b'}}>时代背景</span>
      {recent.map((e) => (
        <span key={e.date} title={e.desc}
          className={`replay-chip${e.date === vd ? ' today' : ''}`}>
          {dayLabel(e.date)} {e.title}
        </span>
      ))}
      {recent.length === 0 && newsItems.length === 0 && (
        <span className="replay-hint">近 60 天无策划大事件</span>
      )}
      <button className="replay-btn"
        style={{padding: '1px 8px', fontSize: 12}}
        disabled={newsItems.length === 0}
        onClick={() => setShowNews(!showNews)}>
        📰 近3日头条({newsItems.length})
      </button>
      {showNews && (
        <ul className="replay-era-news">
          {newsItems.map((n) => (
            <li key={n.url}>
              {n.title}
              <span style={{color: '#6e6e73'}}> — {n.source}{blind ? '' : ` ${mmdd(n.published_at)}`}</span>
            </li>
          ))}
        </ul>
      )}
      {newsItems.length === 0 && (
        <span className="replay-hint">该时段暂无新闻存档</span>
      )}
    </div>
  );
};
