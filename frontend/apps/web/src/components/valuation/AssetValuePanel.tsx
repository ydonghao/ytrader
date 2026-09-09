/**
 * AssetValuePanel — 净资产分析法面板，五法估值之一（绝对估值）。
 *
 * 《股票投资课程》15 集：账面净资产是底线价值（品牌/商誉/商业信用
 * 不在账上）；对上市公司落点是市净率——8 年 PB 趋势 + 均值±1σ 参考
 * 线（课程茅台案例：μ=4.33、σ=2.41），隐含市值 = 净资产 × 历史PB中枢。
 */
import {useEffect, useState} from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, ReferenceArea,
} from 'recharts';
import {getApiBase} from '../../lib/api';
import {StateView} from '../ui';
import {axisProps, tooltipProps} from '../../lib/chartTheme';
import '../DcfPanel.css';

const API_BASE = getApiBase();

interface AssetValueData {
  symbol: string;
  years: number;
  equity_parent: number | null;
  equity_report_date: string | null;
  bps: number | null;
  shares: number | null;
  current_pb: number | null;
  current_pb_date: string | null;
  sample_size: number;
  band: {mean: number; std: number; z_score: number; state: string} | null;
  market_value: number | null;
  price: number | null;
  below_book: boolean;
  implied_value: number | null;
  implied_basis: string | null;
  margin_of_safety: number | null;
  pb_series: Array<{date: string; pb: number}>;
  note?: string;
  error?: string;
}

const STATE_COLOR: Record<string, string> = {
  '超跌': '#3fb950',
  '合理偏低': '#3fb950',
  '合理偏高': '#d29922',
  '虚高': '#f85149',
};

function fmtYi(v: number | null) {
  if (v == null || Number.isNaN(v)) return '—';
  return (v / 1e8).toFixed(1) + ' 亿';
}

function fmtPct(v: number | null) {
  if (v == null || Number.isNaN(v)) return '—';
  return (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
}

export function AssetValuePanel({symbol}: {symbol: string}) {
  const [years, setYears] = useState(8);
  const [data, setData] = useState<AssetValueData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/financial/asset-value/${symbol}?years=${years}`)
      .then((r) => r.json())
      .then((j) => {
        if (!alive) return;
        if (j.code === 0) setData(j.data ?? null);
        else { setData(null); setError(j.msg || '查询失败'); }
      })
      .catch((e) => alive && setError(e.message || '网络错误'))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [symbol, years]);

  const band = data?.band;
  const mos = data?.margin_of_safety;
  const mosColor =
    mos == null ? 'var(--color-text-secondary)' : mos > 0.25 ? '#3fb950' : mos > 0 ? '#d29922' : '#f85149';
  const stateColor = band ? (STATE_COLOR[band.state] || 'var(--color-text-secondary)') : 'var(--color-text-secondary)';

  return (
    <div className="dcf-panel">
      <div className="dcf-panel__assumptions">
        <h3 className="dcf-panel__title">净资产分析（PB 历史窗口可调，课程默认 8 年）</h3>
        <div className="dcf-assump">
          <label>
            窗口(年)
            <input type="number" min={1} max={30} step={1} value={years}
              onChange={(e) => setYears(Math.min(30, Math.max(1, Math.round(+e.target.value) || 8)))} />
          </label>
        </div>
      </div>

      {loading && <StateView state="loading" />}
      {error && <div className="dcf-panel__error">❌ {error}</div>}

      {data && !loading && (
        <div className="dcf-panel__result">
          <div className="dcf-mos" style={{color: stateColor}}>
            <div className="dcf-mos__label">PB 通道状态</div>
            <div className="dcf-mos__value" style={{fontSize: 20}}>{band?.state || '—'}</div>
            {band && <div className="vh-subnote">z = {band.z_score.toFixed(2)}</div>}
          </div>
          <div className="dcf-vals">
            <div className="dcf-val"><span>归母净资产</span><b>{fmtYi(data.equity_parent)}</b></div>
            <div className="dcf-val">
              <span>每股净资产</span>
              <b>{data.bps != null ? data.bps.toFixed(2) + ' 元' : '—'}</b>
            </div>
            <div className="dcf-val">
              <span>当前 PB{data.below_book ? '（破净）' : ''}</span>
              <b style={{color: data.below_book ? '#3fb950' : undefined}}>
                {data.current_pb != null ? data.current_pb.toFixed(2) : '—'}
              </b>
            </div>
            <div className="dcf-val"><span>当前市值</span><b>{fmtYi(data.market_value)}</b></div>
            <div className="dcf-val">
              <span>隐含市值（净资产×μ）</span>
              <b>{fmtYi(data.implied_value)}</b>
            </div>
            <div className="dcf-val">
              <span>隐含安全边际</span>
              <b style={{color: mosColor}}>{fmtPct(mos)}</b>
            </div>
          </div>
          {band && (
            <div className="vh-subnote">
              {data.years} 年 PB：μ={band.mean.toFixed(2)} · σ={band.std.toFixed(2)} ·
              低估参考线 {(band.mean - band.std).toFixed(2)} · 高估参考线 {(band.mean + band.std).toFixed(2)} ·
              样本 {data.sample_size} 日 · 净资产报告期 {data.equity_report_date || '—'}
            </div>
          )}
        </div>
      )}

      {data?.pb_series?.length ? (
        <div className="dcf-chart">
          <div className="dcf-chart__title">
            市净率 PB 趋势（月度）与 μ±1σ 参考线 · 课程口径
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={data.pb_series} margin={{top: 18, right: 16, left: 0, bottom: 5}}>
              {band && (
                <ReferenceArea
                  y1={band.mean - band.std} y2={band.mean + band.std}
                  fill="#58a6ff" fillOpacity={0.06}
                  strokeOpacity={0}
                />
              )}
              {band && <ReferenceLine y={band.mean} stroke="#8b949e" strokeDasharray="6 4"
                label={{value: `μ ${band.mean.toFixed(2)}`, fontSize: 10, fill: '#8b949e', position: 'insideTopLeft'}} />}
              {band && <ReferenceLine y={band.mean + band.std} stroke="#f85149" strokeDasharray="4 4"
                label={{value: `μ+σ ${(band.mean + band.std).toFixed(2)}`, fontSize: 10, fill: '#f85149', position: 'insideTopRight'}} />}
              {band && <ReferenceLine y={band.mean - band.std} stroke="#3fb950" strokeDasharray="4 4"
                label={{value: `μ−σ ${(band.mean - band.std).toFixed(2)}`, fontSize: 10, fill: '#3fb950', position: 'insideBottomRight'}} />}
              <XAxis dataKey="date" {...axisProps} interval="preserveStartEnd" minTickGap={48} />
              <YAxis {...axisProps} domain={['auto', 'auto']} />
              <Tooltip {...tooltipProps} formatter={(v: number) => [v?.toFixed(2), 'PB']} />
              <Line type="monotone" dataKey="pb" stroke="#58a6ff" strokeWidth={1.8}
                dot={false} name="市净率" isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : !loading && !error && <StateView state="empty" text="暂无 PB 历史数据" />}

      {data?.note && <div className="dcf-panel__note">{data.note}</div>}
    </div>
  );
}
