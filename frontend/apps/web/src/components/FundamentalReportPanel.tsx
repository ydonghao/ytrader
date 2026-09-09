/**
 * FundamentalReportPanel — 个股基本面深度分析报告（Financial 页 Tab）。
 *
 * 后端注入真实三大报表 + 估值分位 + 衍生指标，LLM 产出结构化报告。
 * 展示：综合评分 / 一句话结论 / 盈利质量 / 财务健康 / 估值 /
 * 资本回报效率 / 护城河 / 风险点。
 */
import {useState} from 'react';
import {LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine} from 'recharts';
import {getApiBase} from '../lib/api';
import {useFundamentalAnalysis} from '../hooks/useFundamentalAnalysis';
import {useFundamentalAnalysisHistory} from '../hooks/useFundamentalAnalysisHistory';
import './FundamentalReportPanel.css';
import { CHART_COLORS, axisProps, chartBorderStrong, tooltipProps } from '../lib/chartTheme';

const API_BASE = getApiBase();

function scoreColor(s?: number) {
  if (s == null) return 'var(--color-text-secondary)';
  if (s >= 75) return 'var(--color-success)';
  if (s >= 50) return 'var(--color-warning)';
  return 'var(--color-danger)';
}

function cheapColor(c?: string) {
  if (c === 'cheap') return 'var(--color-success)';
  if (c === 'expensive') return 'var(--color-danger)';
  return 'var(--color-text-secondary)';
}

const SEVERITY_LABEL: Record<string, string> = {
  high: '高危',
  medium: '中等',
  low: '低',
};
const SEVERITY_COLOR: Record<string, string> = {
  high: 'var(--color-danger)',
  medium: 'var(--color-warning)',
  low: 'var(--color-text-secondary)',
};

// 枚举值 → 中文标签（盈利趋势 / 负债水平）
const TREND_LABEL: Record<string, string> = {
  growth: '↑ 增长',
  decline: '↓ 下滑',
  volatile: '↕ 波动',
  stagnant: '→ 停滞',
  loss: '亏损',
};

const DEBT_LEVEL_LABEL: Record<string, string> = {
  high: '偏高',
  medium: '中等',
  low: '较低',
};

// section 子字段细节行（文本字段详展，只在有值时渲染）
function DetailRow({label, value}: {label: string; value?: string | null}) {
  if (!value) return null;
  return (
    <div className="fa-detail">
      <span className="fa-detail__label">{label}</span>
      <span className="fa-detail__value">{value}</span>
    </div>
  );
}

// 风险点分组（高危默认展开，中低危默认折叠）
const RISK_GROUPS = [
  {key: 'high', label: '高危', color: 'var(--color-danger)', defaultOpen: true},
  {key: 'medium', label: '中等', color: 'var(--color-warning)', defaultOpen: false},
  {key: 'low', label: '低危', color: 'var(--color-text-secondary)', defaultOpen: false},
];

function RiskGroup({group}: {group: {label: string; color: string; defaultOpen: boolean; risks: FaRisk[]}}) {
  const [open, setOpen] = useState(group.defaultOpen);
  return (
    <div className="fa-risk-group">
      <button type="button" className="fa-risk-group__header" onClick={() => setOpen((o) => !o)}>
        <span className="fa-risk-group__dot" style={{background: group.color}} />
        <span style={{color: group.color}}>{group.label}</span>
        <span className="fa-risk-group__count">{group.risks.length}</span>
        <span className="fa-risk-group__arrow">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="fa-risk-group__list">
          {group.risks.map((r, i) => (
            <div key={i} className="fa-risk">
              <span className="fa-risk__desc">{r.description}</span>
              {r.category && <span className="fa-risk__cat">{r.category}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function FundamentalReportPanel({symbol}: {symbol: string}) {
  const {data, loading, error} = useFundamentalAnalysis(symbol);
  const {data: history} = useFundamentalAnalysisHistory(symbol);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const toggleHistory = (id: number) => {
    if (expandedId === id) {
      setExpandedId(null);
      setDetail(null);
      return;
    }
    setExpandedId(id);
    setDetail(null);
    setDetailLoading(true);
    fetch(`${API_BASE}/financial/fundamental-analysis/report/${id}`)
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0) setDetail(j.data?.report);
      })
      .catch(() => {})
      .finally(() => setDetailLoading(false));
  };
  const [moatExpanded, setMoatExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const copyReport = () => {
    if (!data) return;
    const text =
      `${symbol} 基本面分析（评分 ${data.overall_score ?? '—'}/100）\n` +
      `${data.one_line_conclusion || ''}\n\n` +
      (data.profitability?.summary ? `【盈利质量】${data.profitability.summary}\n` : '') +
      (data.financial_health?.summary ? `【财务健康】${data.financial_health.summary}\n` : '') +
      (data.valuation?.summary ? `【估值】${data.valuation.summary}\n` : '') +
      (data.capital_efficiency?.summary ? `【资本回报】${data.capital_efficiency.summary}\n` : '') +
      (data.moat?.summary ? `【护城河】${data.moat.summary}` : '');
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  if (loading) {
    return (
      <div className="fa-panel__loading">
        AI 分析中（读取真实财报 + 推理，约 10-30 秒）…
      </div>
    );
  }
  if (error) return <div className="fa-panel__error">{error}</div>;
  if (!data) {
    return <div className="fa-panel__empty">输入股票代码生成基本面报告</div>;
  }

  return (
    <div className="fa-panel">
      <div className="fa-panel__header">
        <div className="fa-score" style={{color: scoreColor(data.overall_score)}}>
          <div className="fa-score__label">基本面评分</div>
          <div className="fa-score__value">
            {data.overall_score ?? '—'}
            <span>/100</span>
          </div>
        </div>
        <div className="fa-conclusion">{data.one_line_conclusion || '—'}</div>
        <button type="button" className="fa-copy-btn" onClick={copyReport}>
          {copied ? '已复制' : '复制报告'}
        </button>
      </div>

      {!data.data_available && (
        <div className="fa-panel__warn">
          财务数据不足，分析基于有限信息
        </div>
      )}

      <div className="fa-sections">
        {data.profitability && (
          <div className="fa-section">
            <h4>盈利质量</h4>
            <div className="fa-tags">
              {data.profitability.revenue_trend && (
                <span className="fa-mini-tag">
                  营收 {TREND_LABEL[data.profitability.revenue_trend] || data.profitability.revenue_trend}
                </span>
              )}
              {data.profitability.profit_trend && (
                <span className="fa-mini-tag">
                  净利 {TREND_LABEL[data.profitability.profit_trend] || data.profitability.profit_trend}
                </span>
              )}
            </div>
            <p className="fa-section__summary">{data.profitability.summary}</p>
            <div className="fa-details">
              <DetailRow label="毛利率变化" value={data.profitability.margin_change} />
              <DetailRow label="现金流/利润匹配" value={data.profitability.cashflow_profit_match} />
            </div>
          </div>
        )}
        {data.financial_health && (
          <div className="fa-section">
            <h4>财务健康</h4>
            <div className="fa-tags">
              {data.financial_health.debt_level && (
                <span className="fa-mini-tag">
                  负债水平 {DEBT_LEVEL_LABEL[data.financial_health.debt_level] || data.financial_health.debt_level}
                </span>
              )}
            </div>
            <p className="fa-section__summary">{data.financial_health.summary}</p>
            <div className="fa-details">
              <DetailRow label="有息负债" value={data.financial_health.interest_bearing_debt} />
              <DetailRow label="偿债能力" value={data.financial_health.solvency} />
            </div>
          </div>
        )}
        {data.valuation && (
          <div className="fa-section">
            <h4>
              估值
              <span
                className="fa-tag"
                style={{color: cheapColor(data.valuation.cheap_or_expensive)}}
              >
                {data.valuation.cheap_or_expensive}
              </span>
            </h4>
            <p className="fa-section__summary">{data.valuation.summary}</p>
            <div className="fa-details">
              <DetailRow label="PE 分位" value={data.valuation.pe_percentile} />
              <DetailRow label="PB 分位" value={data.valuation.pb_percentile} />
            </div>
          </div>
        )}
        {data.capital_efficiency && (
          <div className="fa-section">
            <h4>资本回报效率</h4>
            <p className="fa-section__summary">{data.capital_efficiency.summary}</p>
            <div className="fa-details">
              <DetailRow label="ROIC 趋势" value={data.capital_efficiency.roic_trend} />
              <DetailRow label="ROE 趋势" value={data.capital_efficiency.roe_trend} />
              <DetailRow label="ROA 趋势" value={data.capital_efficiency.roa_trend} />
            </div>
          </div>
        )}
        {data.moat && (
          <div className="fa-section">
            <h4>
              护城河
              {data.moat.has_moat ? (
                <span className="fa-tag fa-tag--green">有</span>
              ) : (
                <span className="fa-tag fa-tag--red">弱</span>
              )}
            </h4>
            {data.moat.evidence && data.moat.evidence.length > 0 && (
              <>
                <ul className="fa-evidence">
                  {(moatExpanded ? data.moat.evidence : data.moat.evidence.slice(0, 3)).map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
                {data.moat.evidence.length > 3 && (
                  <button type="button" className="fa-evidence-toggle" onClick={() => setMoatExpanded((x) => !x)}>
                    {moatExpanded ? '收起依据' : `展开全部依据 (${data.moat.evidence.length})`}
                  </button>
                )}
              </>
            )}
            <p className="fa-section__summary">{data.moat.summary}</p>
          </div>
        )}
      </div>

      {data.risks && data.risks.length > 0 && (
        <div className="fa-risks">
          <h4>风险点（按严重程度分组）</h4>
          {RISK_GROUPS.map((g) => {
            const rs = data.risks!.filter((r) => (r.severity || 'low') === g.key);
            return rs.length > 0 ? (
              <RiskGroup key={g.key} group={{label: g.label, color: g.color, defaultOpen: g.defaultOpen, risks: rs}} />
            ) : null;
          })}
        </div>
      )}

      {history && history.length > 0 && (
        <div className="fa-history">
          <h4>历史评分趋势（共 {history.length} 份）</h4>
          <ResponsiveContainer width="100%" height={140}>
            <LineChart data={[...history].reverse().map((h) => ({time: (h.created_at || '').slice(0, 10), score: h.overall_score}))}>
              <XAxis dataKey="time" {...axisProps} />
              <YAxis domain={[0, 100]} {...axisProps} />
              <Tooltip {...tooltipProps} />
              <ReferenceLine y={50} stroke={chartBorderStrong} strokeDasharray="3 3" />
              <Line type="monotone" dataKey="score" stroke={CHART_COLORS[0]} strokeWidth={2} dot={{r: 3, fill: CHART_COLORS[0]}} connectNulls name="评分" />
            </LineChart>
          </ResponsiveContainer>
          <div className="fa-history-list">
            {history.slice(0, 5).map((h) => (
              <div key={h.id}>
                <div className="fa-history-item" onClick={() => toggleHistory(h.id)} style={{cursor: 'pointer'}}>
                  <span className="fa-history-time">{(h.created_at || '').slice(0, 16).replace('T', ' ')}</span>
                  <span className="fa-history-score" style={{color: scoreColor(h.overall_score)}}>{h.overall_score ?? '—'}</span>
                  <span className="fa-history-concl">{h.one_line_conclusion || '—'}</span>
                  <span className="fa-history-toggle">{expandedId === h.id ? '▾' : '▸'}</span>
                </div>
                {expandedId === h.id && (
                  <div className="fa-history-detail">
                    {detailLoading ? (
                      <span className="fa-history-detail-loading">加载完整报告…</span>
                    ) : detail ? (
                      <>
                        {detail.profitability?.summary && <div className="fa-history-detail-row"><b>盈利质量</b>：{detail.profitability.summary}</div>}
                        {detail.financial_health?.summary && <div className="fa-history-detail-row"><b>财务健康</b>：{detail.financial_health.summary}</div>}
                        {detail.valuation?.summary && <div className="fa-history-detail-row"><b>估值</b>：{detail.valuation.summary}</div>}
                        {detail.capital_efficiency?.summary && <div className="fa-history-detail-row"><b>资本回报</b>：{detail.capital_efficiency.summary}</div>}
                        {detail.moat?.summary && <div className="fa-history-detail-row"><b>护城河</b>：{detail.moat.summary}</div>}
                      </>
                    ) : (
                      <span className="fa-history-detail-empty">无详细内容</span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
