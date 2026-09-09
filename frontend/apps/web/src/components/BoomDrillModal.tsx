/** 财报雷达候选下钻:日K行情 + 财务报表跳转 + 命中原文 + LLM 景气分析。 */
import {useEffect, useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {KlineChart} from '@ytrader/trading-market-data';
import {getApiBase} from '../lib/api';
import {Button, Modal, StateView} from './ui';
import type {BoomCandidate, BoomHit} from '../hooks/useBoomRadar';

const API_BASE = getApiBase();

/** 纯6位 → sh/sz 前缀(与 Market/Financial 页一致)。 */
const prefixed = (s: string) => (/^[695]/.test(s) ? 'sh' : 'sz') + s;

interface Detail extends BoomCandidate {
  hits: BoomHit[];
}

interface Props {
  symbol: string;
  reportDate: string;
  onClose: () => void;
}

export function BoomDrillModal({symbol, reportDate, onClose}: Props) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [adding, setAdding] = useState(false);
  const [addMsg, setAddMsg] = useState<string | null>(null);

  useEffect(() => {
    const qs = new URLSearchParams({report_date: reportDate});
    fetch(`${API_BASE}/boom/radar/${symbol}?${qs.toString()}`)
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0) {
          setDetail(j.data);
          setState('ready');
        } else {
          setState('error');
        }
      })
      .catch(() => setState('error'));
  }, [symbol, reportDate]);

  const addWatchlist = async () => {
    if (adding) return;
    setAdding(true);
    setAddMsg(null);
    try {
      const r = await fetch(`${API_BASE}/boom/radar/${symbol}/watchlist`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({report_date: reportDate}),
      });
      const j = await r.json();
      setAddMsg(j.code === 0 ? '已加入自选「财报季雷达」分组' : j.msg || '添加失败');
    } catch {
      setAddMsg('网络错误');
    } finally {
      setAdding(false);
    }
  };

  const navigate = useNavigate();

  const title = detail
    ? `${detail.company_name ?? ''} ${detail.symbol} · ${detail.forecast_type_label ?? ''} ${detail.change_pct != null ? detail.change_pct.toFixed(1) + '%' : ''}`
    : `${symbol} 详情`;

  return (
    <Modal open onClose={onClose} title={title} width={760}>
      {state !== 'ready' ? (
        <StateView state={state === 'error' ? 'error' : 'loading'} onRetry={onClose} />
      ) : detail ? (
        <div className="bdm">
          <div className="bdm-actions">
            <Button variant="secondary" size="sm" onClick={addWatchlist} loading={adding}>
              加入自选
            </Button>
            <Button variant="secondary" size="sm"
                    onClick={() => navigate(`/financial?symbol=${prefixed(symbol)}`)}>
              财务报表
            </Button>
            {addMsg && <span className="bdm-addmsg">{addMsg}</span>}
          </div>
          <div className="bdm-section">
            <div className="bdm-section-title">日K行情</div>
            <KlineChart symbol={prefixed(symbol)} interval="1d" height={320} />
          </div>
          {detail.llm_score != null && (
            <div className="bdm-section">
              <div className="bdm-section-title">
                LLM 景气分析 · {detail.llm_score} 分 · {detail.llm_verdict}
              </div>
              <p className="bdm-llm">{detail.llm_summary}</p>
            </div>
          )}
          <div className="bdm-section">
            <div className="bdm-section-title">命中明细({detail.hits.length})</div>
            {detail.hits.length === 0 ? (
              <StateView state="empty" text="无关键词命中" />
            ) : (
              detail.hits.map((h, i) => (
                <div className="bdm-hit" key={i}>
                  <span className="bdm-hit-tag">{h.category_label}</span>
                  <span className="bdm-hit-kw">{h.keyword}</span>
                  <span className="bdm-hit-src">
                    {h.source_type === 'forecast' ? '业绩预告' : h.source_type === 'survey' ? '调研' : '新闻'}
                    {h.source_date ? ` · ${h.source_date}` : ''}
                  </span>
                  <p className="bdm-hit-snippet">{h.snippet}</p>
                </div>
              ))
            )}
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
