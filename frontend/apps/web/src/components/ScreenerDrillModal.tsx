/**
 * 选股器通用下钻弹窗。
 * 点选股结果表任意行触发，展示 5 区块：
 *   a 个股画像 / b 估值分位(可剔除区间) / c 财务趋势 / d K线+股息率 / e 入选拆解
 */
import {useEffect, useState} from 'react';
import {
  ComposedChart, Line, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts';
import {getApiBase} from '../lib/api';
import {useValuationPercentile} from '../hooks/useValuationPercentile';
import {Button, Modal, StateView} from './ui';
import {ValuationPercentileChart, percentileColor} from './ValuationPercentileChart';
import './ScreenerDrillModal.css';
import { CHART_COLORS, axisProps, colorOrange, tooltipProps } from '../lib/chartTheme';

const API_BASE = getApiBase();

interface FactorBreakdown {
  dy_value?: number | null;
  dy_rank?: number | null;
  value_metric?: string;
  value_window?: string;
  value_percentile?: number | null;
  value_percentile_pe?: number | null;
  value_rank?: number | null;
  exclude_applied?: string[][];
}

interface ScreenItemLike {
  rank?: number;
  score?: number;
  pe_ttm?: number | null;
  pb?: number | null;
  dv_ttm?: number | null;
  roe?: number | null;
  roic?: number | null;
  ebit_yield?: number | null;
  debt_ratio?: number | null;
  reason?: string;
}

interface Props {
  symbol: string;
  factorBreakdown: FactorBreakdown | null;
  onClose: () => void;
  item?: ScreenItemLike | null;
}

const fmt = (v: number | null | undefined, digits = 2) =>
  v == null || Number.isNaN(v) ? '-' : v.toFixed(digits);

export function ScreenerDrillModal({symbol, factorBreakdown, onClose, item}: Props) {
  const [profile, setProfile] = useState<any>(null);
  const [finSeries, setFinSeries] = useState<any[]>([]);
  const [bars, setBars] = useState<any[]>([]);
  const [excludeStr, setExcludeStr] = useState('');
  const [excludeStart, setExcludeStart] = useState('');
  const [excludeEnd, setExcludeEnd] = useState('');
  const [excludeList, setExcludeList] = useState<string[]>([]);
  // 全局剔除区间是否已就位（成功或失败都算就位，失败则无 exclude 直查）
  const [rangesLoaded, setRangesLoaded] = useState(false);

  // 加入自选股：分组列表 + 添加状态
  const [groups, setGroups] = useState<{id: number; name: string}[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [addMsg, setAddMsg] = useState<{ok: boolean; text: string} | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/watchlist/groups`)
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0 && Array.isArray(j.data)) {
          const list = j.data.map((g: any) => ({id: g.id, name: g.name}));
          setGroups(list);
          if (list.length > 0) setSelectedGroup(list[0].id);
        }
      })
      .catch(() => {});
  }, []);

  const handleAdd = async () => {
    if (selectedGroup == null || adding) return;
    setAdding(true);
    setAddMsg(null);
    try {
      const r = await fetch(`${API_BASE}/watchlist/groups/${selectedGroup}/items`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({symbol}),
      });
      const j = await r.json();
      if (j.code === 0) {
        setAddMsg({ok: true, text: '已加入自选股'});
        setShowAdd(false);
      } else {
        setAddMsg({ok: false, text: j.msg || '添加失败'});
      }
    } catch {
      setAddMsg({ok: false, text: '网络错误'});
    } finally {
      setAdding(false);
    }
  };

  // 估值分位（带 exclude）——等剔除区间就位再请求，
  // 否则会先无 exclude 拉一次、区间到达后再拉一次（后端重算全历史分位，双倍开销）
  const {data: valPct, loading: valLoading} = useValuationPercentile(symbol, {
    windows: '3y,5y,10y',
    metrics: 'pe_ttm,pb,ps_ttm,dv_ttm',
    exclude: excludeStr || undefined,
    enabled: rangesLoaded,
  });

  // 初始拉全局剔除区间
  useEffect(() => {
    fetch(`${API_BASE}/screener/exclude-ranges`)
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0 && j.data?.ranges) {
          const segs = j.data.ranges.map((r: string[]) => `${r[0]}~${r[1]}`);
          setExcludeList(segs);
          setExcludeStr(segs.join(','));
        }
      })
      .catch(() => {})
      .finally(() => setRangesLoaded(true));
  }, []);

  // 画像
  useEffect(() => {
    fetch(`${API_BASE}/financial/profile/${symbol}`)
      .then((r) => r.json())
      .then((j) => j.code === 0 && setProfile(j.data))
      .catch(() => {});
  }, [symbol]);

  // 财务趋势（利润表近 8 期）
  useEffect(() => {
    fetch(`${API_BASE}/financial/detail/${symbol}?statement_type=income&limit=8&period=year`)
      .then((r) => r.json())
      .then((j) => {
        if (j.code === 0 && j.data?.series) {
          setFinSeries([...j.data.series].reverse()); // 升序画图
        }
      })
      .catch(() => {});
  }, [symbol]);

  // K线（近 1 年）
  useEffect(() => {
    fetch(`${API_BASE}/market/kline/${symbol}?interval=1d&limit=250`)
      .then((r) => r.json())
      .then((j) => j.code === 0 && setBars(j.data?.bars || []))
      .catch(() => {});
  }, [symbol]);

  const addExclude = () => {
    if (!excludeStart || !excludeEnd) return;
    const seg = `${excludeStart}~${excludeEnd}`;
    if (!excludeList.includes(seg)) {
      const next = [...excludeList, seg];
      setExcludeList(next);
      setExcludeStr(next.join(','));
    }
    setExcludeStart('');
    setExcludeEnd('');
  };

  const removeExclude = (seg: string) => {
    const next = excludeList.filter((s) => s !== seg);
    setExcludeList(next);
    setExcludeStr(next.join(','));
  };

  // 股息率时序（从分位接口 series 取）
  const dvSeries = valPct?.metrics?.dv_ttm?.series || [];
  // Build month → dv lookup (series is monthly-downsampled; kline is daily)
  const dvByMonth: Record<string, number> = {};
  dvSeries.forEach((s) => { dvByMonth[s.date.slice(0, 7)] = s.value; });
  const klineMerged = bars.map((b) => {
    const month = String(b.trade_date).slice(0, 7);
    return {...b, dv: dvByMonth[month] ?? null};
  });

  const metrics = valPct?.metrics || {};

  const title = `${profile?.name || symbol}（${symbol}）${profile?.industry ? ' · ' + profile.industry : ''}`;

  return (
    <Modal open onClose={onClose} title={title} width={920}>
      <div style={{display: 'flex', justifyContent: 'flex-end', marginBottom: 'var(--space-2)'}}>
        <Button variant="secondary" size="sm" onClick={() => { setShowAdd((s) => !s); setAddMsg(null); }}>
          自选
        </Button>
      </div>

      {showAdd && (
          <div className="sdm-add-watchlist">
            {groups.length === 0 ? (
              <div className="sdm-add-empty">还没有分组，请先到「自选股」页创建分组后再加入</div>
            ) : (
              <div className="sdm-add-row">
                <select
                  className="sdm-add-select"
                  value={selectedGroup ?? ''}
                  onChange={(e) => setSelectedGroup(Number(e.target.value))}
                >
                  {groups.map((g) => (
                    <option key={g.id} value={g.id}>{g.name}</option>
                  ))}
                </select>
                <Button variant="primary" size="sm" onClick={handleAdd} loading={adding} disabled={selectedGroup == null}>
                  {adding ? '加入中…' : '加入'}
                </Button>
              </div>
            )}
            {addMsg && (
              <div className={addMsg.ok ? 'sdm-add-msg sdm-add-msg--ok' : 'sdm-add-msg sdm-add-msg--err'}>
                {addMsg.text}
              </div>
            )}
          </div>
        )}

        {/* a 个股画像 */}
        <div className="sdm-section">
          <div className="sdm-section-title">个股画像</div>
          <div className="sdm-profile-grid">
            <div className="sdm-profile-item">
              <div className="sdm-profile-label">最新价</div>
              <div className="sdm-profile-value">{fmt(bars[bars.length-1]?.close)}</div>
            </div>
            <div className="sdm-profile-item">
              <div className="sdm-profile-label">总市值(亿)</div>
              <div className="sdm-profile-value">{profile?.total_mv ? (profile.total_mv / 1e8).toFixed(1) : '-'}</div>
            </div>
            <div className="sdm-profile-item">
              <div className="sdm-profile-label">PE_TTM</div>
              <div className="sdm-profile-value">{fmt(profile?.pe_ttm)}</div>
            </div>
            <div className="sdm-profile-item">
              <div className="sdm-profile-label">PB</div>
              <div className="sdm-profile-value">{fmt(profile?.pb)}</div>
            </div>
          </div>
        </div>

        {/* a2 选股指标快照（含 magic_formula 真实 ROIC/EBIT） */}
        {item && (
          <div className="sdm-section">
            <div className="sdm-section-title">选股指标快照</div>
            <div className="sdm-profile-grid">
              <div className="sdm-profile-item">
                <div className="sdm-profile-label">综合排名</div>
                <div className="sdm-profile-value">第 {item.rank ?? '-'} 名</div>
              </div>
              <div className="sdm-profile-item">
                <div className="sdm-profile-label">综合评分</div>
                <div className="sdm-profile-value">{fmt(item.score)}</div>
              </div>
              {item.roic != null && (
                <div className="sdm-profile-item">
                  <div className="sdm-profile-label">ROIC%</div>
                  <div
                    className="sdm-profile-value"
                    style={{
                      color: (item.roic ?? 0) >= 15 ? 'var(--color-success)' : 'inherit',
                      fontWeight: (item.roic ?? 0) >= 15 ? 700 : 400,
                    }}
                  >
                    {fmt(item.roic)}
                  </div>
                </div>
              )}
              {item.ebit_yield != null && (
                <div className="sdm-profile-item">
                  <div className="sdm-profile-label">EBIT收益率%</div>
                  <div className="sdm-profile-value">{fmt(item.ebit_yield)}</div>
                </div>
              )}
              <div className="sdm-profile-item">
                <div className="sdm-profile-label">ROE%</div>
                <div className="sdm-profile-value">{fmt(item.roe)}</div>
              </div>
              <div className="sdm-profile-item">
                <div className="sdm-profile-label">股息率%</div>
                <div className="sdm-profile-value">{fmt(item.dv_ttm)}</div>
              </div>
              <div className="sdm-profile-item">
                <div className="sdm-profile-label">负债率%</div>
                <div className="sdm-profile-value">{fmt(item.debt_ratio)}</div>
              </div>
            </div>
            {item.reason && (
              <div style={{marginTop: 8, fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)'}}>
                入选理由：{item.reason}
              </div>
            )}
          </div>
        )}

        {/* b 估值历史分位（含剔除交互） */}
        <div className="sdm-section">
          <div className="sdm-section-title">估值历史分位（可剔除炒作区间）</div>
          <div className="sdm-exclude-bar">
            <input type="date" value={excludeStart} onChange={(e) => setExcludeStart(e.target.value)} />
            <span style={{color: 'var(--color-text-tertiary)'}}>~</span>
            <input type="date" value={excludeEnd} onChange={(e) => setExcludeEnd(e.target.value)} />
            <Button variant="secondary" size="sm" onClick={addExclude}>+ 剔除该区间</Button>
          </div>
          {excludeList.length > 0 && (
            <div className="sdm-exclude-chips">
              {excludeList.map((seg) => (
                <span key={seg} className="sdm-exclude-chip">
                  {seg}
                  <button onClick={() => removeExclude(seg)}>×</button>
                </span>
              ))}
            </div>
          )}
          {valLoading ? (
            <StateView state="loading" />
          ) : (
            <div className="sdm-charts-grid">
              <ValuationPercentileChart title="市盈率 TTM" metric={metrics.pe_ttm || null} windowKey="10y" color={CHART_COLORS[0]} />
              <ValuationPercentileChart title="市净率" metric={metrics.pb || null} windowKey="10y" color={CHART_COLORS[1]} />
              <ValuationPercentileChart title="市销率 TTM" metric={metrics.ps_ttm || null} windowKey="10y" color={CHART_COLORS[3]} />
              <ValuationPercentileChart title="股息率 TTM" metric={metrics.dv_ttm || null} windowKey="10y" color={colorOrange} />
            </div>
          )}
        </div>

        {/* c 财务趋势 */}
        <div className="sdm-section">
          <div className="sdm-section-title">财务趋势（近 8 期年报）</div>
          {finSeries.length === 0 ? (
            <StateView state="empty" text="无数据" />
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={finSeries.map((s) => ({
                date: (s.report_date || '').slice(0, 4),
                revenue: s.revenue ? s.revenue / 1e8 : null,
                netProfit: s.net_profit ? s.net_profit / 1e8 : null,
                margin: s.net_margin,
              }))}>
                <XAxis dataKey="date" {...axisProps} />
                <YAxis yAxisId="left" {...axisProps} />
                <YAxis yAxisId="right" orientation="right" {...axisProps} />
                <Tooltip {...tooltipProps} />
                <Legend />
                <Bar yAxisId="left" dataKey="revenue" name="营收(亿)" fill={CHART_COLORS[0]} opacity={0.5} />
                <Bar yAxisId="left" dataKey="netProfit" name="净利(亿)" fill={CHART_COLORS[1]} opacity={0.7} />
                <Line yAxisId="right" dataKey="margin" name="净利率%" stroke={colorOrange} strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* d K线 + 股息率 */}
        <div className="sdm-section">
          <div className="sdm-section-title">近 1 年价格 × 股息率</div>
          {klineMerged.length === 0 ? (
            <StateView state="empty" text="无数据" />
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={klineMerged}>
                <XAxis dataKey="trade_date" {...axisProps} tickFormatter={(v) => String(v).slice(5)} />
                <YAxis yAxisId="left" {...axisProps} domain={['auto', 'auto']} />
                <YAxis yAxisId="right" orientation="right" {...axisProps} />
                <Tooltip {...tooltipProps} />
                <Legend />
                <Line yAxisId="left" dataKey="close" name="收盘价" stroke={CHART_COLORS[0]} strokeWidth={1.5} dot={false} />
                <Line yAxisId="right" dataKey="dv" name="股息率%" stroke={colorOrange} strokeWidth={1.5} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* e 入选拆解 */}
        {factorBreakdown && (
          <div className="sdm-section">
            <div className="sdm-section-title">入选拆解（{factorBreakdown.value_metric?.toUpperCase()} · {factorBreakdown.value_window}）</div>
            <div className="sdm-breakdown">
              <div className="sdm-breakdown-item">
                <div className="sdm-breakdown-label">股息率</div>
                <div className="sdm-breakdown-value">{fmt(factorBreakdown.dy_value)}%</div>
                <div className="sdm-profile-label">全市场第 {factorBreakdown.dy_rank ?? '-'} 名</div>
              </div>
              <div className="sdm-breakdown-item">
                <div className="sdm-breakdown-label">低估分位</div>
                <div className="sdm-breakdown-value" style={{color: percentileColor(factorBreakdown.value_percentile ?? null)}}>
                  {fmt(factorBreakdown.value_percentile, 3)}
                </div>
                <div className="sdm-profile-label">全市场第 {factorBreakdown.value_rank ?? '-'} 名</div>
              </div>
              {factorBreakdown.value_metric === 'pb_pe' && (
                <div className="sdm-breakdown-item">
                  <div className="sdm-breakdown-label">PE 子分位</div>
                  <div className="sdm-breakdown-value" style={{color: percentileColor(factorBreakdown.value_percentile_pe ?? null)}}>
                    {fmt(factorBreakdown.value_percentile_pe, 3)}
                  </div>
                </div>
              )}
            </div>
            {factorBreakdown.exclude_applied && factorBreakdown.exclude_applied.length > 0 && (
              <div style={{marginTop: 8, fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)'}}>
                已剔除区间：{factorBreakdown.exclude_applied.map((r) => `${r[0]}~${r[1]}`).join('，')}
              </div>
            )}
          </div>
        )}
    </Modal>
  );
}

export default ScreenerDrillModal;
