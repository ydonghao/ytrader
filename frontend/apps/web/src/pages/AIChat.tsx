/**
 * AI Chat Trading Copilot Page
 * Natural language portfolio & market queries with inline data cards.
 */
import React, {useState, useRef, useEffect, useCallback} from 'react';
import { getApiBase } from '../lib/api';
import {Button, PageHeader} from '../components/ui';
import './AIChat.css';

interface Message {
  id: string;
  role: 'user' | 'ai';
  text: string;
  timestamp: string;
  cards?: ChatCard[];
  actions?: ChatAction[];
  intent?: string;
}

interface ChatCard {
  type: 'positions' | 'metric' | 'signals' | 'strategies';
  title: string;
  data?: any[];
  value?: string;
  sub?: string;
}

interface ChatAction {
  label: string;
  href?: string;
}

function formatTime(): string {
  const now = new Date();
  return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
}

function genId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

function MetricCard({card}: {card: ChatCard}) {
  const isPositive = card.value?.startsWith('+') || !card.value?.startsWith('-');
  const displayValue = card.value || '';
  const valueClass =
    displayValue.startsWith('+') ? 'text-positive' :
    displayValue.startsWith('-') ? 'text-negative' :
    'text-neutral';

  return (
    <div className="chat-card chat-card--metric">
      <div className="chat-card__title">{card.title}</div>
      <div className={`chat-card__value ${valueClass}`}>{displayValue}</div>
      {card.sub && <div className="chat-card__sub">{card.sub}</div>}
    </div>
  );
}

function PositionsCard({card}: {card: ChatCard}) {
  const positions = card.data || [];
  return (
    <div className="chat-card chat-card--positions">
      <div className="chat-card__title">{card.title}</div>
      {positions.map((p: any, i: number) => (
        <div key={i} className="chat-card__row">
          <span className="chat-card__row-symbol">{p.symbol || p.strategy_name || p.signal_type}</span>
          {p.quantity != null && <span className="chat-card__row-meta">{p.quantity}股</span>}
          {p.daily_return != null && (
            <span className={p.daily_return >= 0 ? 'text-positive' : 'text-negative'}>
              {p.daily_return >= 0 ? '+' : ''}{Number(p.daily_return).toFixed(2)}%
            </span>
          )}
          {p.total_return != null && (
            <span className={p.total_return >= 0 ? 'text-positive' : 'text-negative'}>
              {p.total_return >= 0 ? '+' : ''}{Number(p.total_return).toFixed(1)}%
            </span>
          )}
          {p.direction && (
            <span className={`chat-badge chat-badge--${p.direction.toLowerCase()}`}>{p.direction}</span>
          )}
          {p.strength != null && (
            <span className="chat-card__row-meta">强度 {Number(p.strength * 100).toFixed(0)}%</span>
          )}
          {p.sector && <span className="chat-card__row-meta">{p.sector}</span>}
        </div>
      ))}
    </div>
  );
}

function SignalsCard({card}: {card: ChatCard}) {
  const signals = card.data || [];
  return (
    <div className="chat-card chat-card--signals">
      <div className="chat-card__title">{card.title}</div>
      {signals.map((s: any, i: number) => (
        <div key={i} className="chat-card__row">
          <span className="chat-card__row-symbol">{s.symbol}</span>
          <span className="chat-badge chat-badge--signal">{s.signal_type}</span>
          <span className={`chat-badge chat-badge--${s.direction.toLowerCase()}`}>{s.direction}</span>
          <span className="chat-card__row-meta">强度 {Number(s.strength * 100).toFixed(0)}%</span>
        </div>
      ))}
    </div>
  );
}

function StrategiesCard({card}: {card: ChatCard}) {
  const strategies = card.data || [];
  return (
    <div className="chat-card chat-card--strategies">
      <div className="chat-card__title">{card.title}</div>
      {strategies.map((s: any, i: number) => (
        <div key={i} className="chat-card__row">
          <span className="chat-card__row-symbol">{s.strategy_name}</span>
          <span className={s.total_return >= 0 ? 'text-positive' : 'text-negative'}>
            {s.total_return >= 0 ? '+' : ''}{Number(s.total_return).toFixed(1)}%
          </span>
          <span className="chat-card__row-meta">夏普 {Number(s.sharpe_ratio).toFixed(2)}</span>
          <span className="chat-card__row-meta">胜率 {Number(s.win_rate).toFixed(1)}%</span>
        </div>
      ))}
    </div>
  );
}

function renderCard(card: ChatCard) {
  switch (card.type) {
    case 'positions': return <PositionsCard card={card} />;
    case 'signals':   return <SignalsCard card={card} />;
    case 'strategies': return <StrategiesCard card={card} />;
    default:          return <MetricCard card={card} />;
  }
}

function renderActions(actions: ChatAction[]) {
  return (
    <div className="chat-actions">
      {(actions || []).map((a, i) =>
        a.href ? (
          <a key={i} href={a.href} className="chat-action-btn">{a.label}</a>
        ) : (
          <button key={i} className="chat-action-btn" onClick={() => {}}>{a.label}</button>
        )
      )}
    </div>
  );
}

const WELCOME_MSG: Message = {
  id: 'welcome',
  role: 'ai',
  text: `你好！我是你的 AI 交易助手，可以帮你：\n\n• 查询持仓和收益\n• 分析市场状况\n• 解读交易信号\n• 查看策略表现\n\n直接用中文描述你的问题，我来解答！`,
  timestamp: formatTime(),
  intent: 'greeting',
  cards: [],
  actions: [
    {label: '查询持仓', href: '/portfolio'},
    {label: '市场行情', href: '/market'},
  ],
};

export const AIChat: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([WELCOME_MSG]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom（用 'auto' 而非 'smooth'：流式/快速状态更新时不会堆积多个动画）
  useEffect(() => {
    bottomRef.current?.scrollIntoView({behavior: 'auto'});
  }, [messages, loading]);

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || loading) return;

    const userMsg: Message = {
      id: genId(),
      role: 'user',
      text: text.trim(),
      timestamp: formatTime(),
    };

    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const apiBase = getApiBase();
      const res = await fetch(`${apiBase}/ai/chat`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: text.trim(), context: 'general'}),
      });

      const json = await res.json();
      const data = json?.data;

      const aiMsg: Message = {
        id: genId(),
        role: 'ai',
        text: data?.reply || '抱歉，我没有理解你的问题，请稍后重试。',
        timestamp: formatTime(),
        cards: data?.cards || [],
        actions: data?.actions || [],
        intent: data?.intent || 'unknown',
      };

      setMessages(prev => [...prev, aiMsg]);
    } catch (err) {
      console.error('[AIChat] API error:', err);
      const errMsg: Message = {
        id: genId(),
        role: 'ai',
        text: '网络连接失败，请检查服务是否正常运行。',
        timestamp: formatTime(),
        cards: [],
        actions: [],
        intent: 'error',
      };
      setMessages(prev => [...prev, errMsg]);
    } finally {
      setLoading(false);
    }
  }, [loading]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const clearChat = () => {
    setMessages([WELCOME_MSG]);
  };

  return (
    <div className="aichat">
      {/* Header */}
      <PageHeader
        title="AI 交易助手"
        subtitle="自然语言查询持仓、市场与策略"
        actions={
          <Button variant="secondary" size="sm" onClick={clearChat} title="清空对话">
            清空
          </Button>
        }
      />

      {/* Messages */}
      <div className="aichat__messages">
        {messages.map(msg => (
          <div key={msg.id} className={`aichat__message aichat__message--${msg.role}`}>
            {msg.role === 'ai' && (
              <span className="aichat__message-avatar">AI</span>
            )}
            <div className="aichat__message-content">
              {msg.role === 'user' && (
                <div className="aichat__message-bubble aichat__message-bubble--user">
                  {msg.text}
                </div>
              )}
              {msg.role === 'ai' && (
                <>
                  <div className="aichat__message-bubble aichat__message-bubble--ai">
                    {msg.text.split('\n').map((line, i) => (
                      <span key={i}>
                        {line}
                        {i < msg.text.split('\n').length - 1 && <br />}
                      </span>
                    ))}
                  </div>
                  {msg.cards && msg.cards.length > 0 && (
                    <div className="aichat__cards">
                      {msg.cards.map((card, i) => (
                        <div key={i}>{renderCard(card)}</div>
                      ))}
                    </div>
                  )}
                  {msg.actions && msg.actions.length > 0 && renderActions(msg.actions)}
                </>
              )}
              <div className="aichat__message-time">{msg.timestamp}</div>
            </div>
          </div>
        ))}

        {loading && (
          <div className="aichat__message aichat__message--ai">
            <span className="aichat__message-avatar">AI</span>
            <div className="aichat__message-content">
              <div className="aichat__message-bubble aichat__message-bubble--ai aichat__typing">
                <span className="aichat__typing-dot" />
                <span className="aichat__typing-dot" />
                <span className="aichat__typing-dot" />
                AI 正在思考...
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="aichat__input-area">
        <textarea
          ref={inputRef}
          className="aichat__input"
          placeholder="输入消息，按 Enter 发送..."
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={loading}
        />
        <button
          className="aichat__send-btn"
          onClick={() => sendMessage(input)}
          disabled={loading || !input.trim()}
        >
          发送
        </button>
      </div>
    </div>
  );
};
