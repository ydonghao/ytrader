/**
 * DdmPanel — 股利折现模型（Gordon）面板，五法估值之一（绝对估值）。
 *
 * 《股票投资课程》15 集：适用于确定性高、成长性低的分红型公司
 * （课程案例：长江电力 2024 分红 230 亿、r=5.5%、g=2% → 约 6703 亿）。
 * V = D₀ × (1+g) / (r − g)，安全边际与 DCF 同口径。
 */
import {useEffect, useState} from 'react';
import {LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, LabelList} from 'recharts';
import {getApiBase} from '../../lib/api';
import {axisProps, tooltipProps} from '../../lib/chartTheme';
import '../DcfPanel.css';

const API_BASE = getApiBase();

interface DdmData {
  symbol: string;
  intrinsic_value: number | null;
  intrinsic_per_share: number | null;
  market_value: number | null;
  margin_of_safety: number | null;
  d0: number | null;
  d0_method: string | null;
  dps_ttm: number | null;
  shares: number | null;
  price: number | null;
  valuation_date: string | null;
  assumptions: {growth_rate: number; discount_rate: number};
  note?: string;
  error?: string;
}

function fmtYi(v: number | null) {
  if (v == null || Number.isNaN(v)) return '—';
  return (v / 1e8).toFixed(1) + ' 亿';
}

function fmtPct(v: number | null) {
  if (v == null || Number.isNaN(v)) return '—';
  return (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
}

export function DdmPanel({symbol}: {symbol: string}) {
  const [growthRate, setGrowthRate] = useState(0.02);
  const [discountRate, setDiscountRate] = useState(0.055);
  const [data, setData] = useState<DdmData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setLoading(true);
    setError(null);
    const qs = `growth_rate=${growthRate}&discount_rate=${discountRate}`;
    fetch(`${API_BASE}/financial/ddm/${symbol}?${qs}`)
      .then((r) => r.json())
      .then((j) => {
        if (!alive) return;
        if (j.code === 0) setData(j.data ?? null);
        else { setData(null); setError(j.msg || '查询失败'); }
      })
      .catch((e) => alive && setError(e.message || '网络错误'))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [symbol, growthRate, discountRate]);

  // 折现率敏感性：r 从 discountRate 上下扫 5 档（g 固定）
  const [sens, setSens] = useState<{r: number; v: number | null}[]>([]);
  useEffect(() => {
    if (!symbol) { setSens([]); return; }
    let alive = true;
    const rs = [-0.015, -0.01, -0.005, 0, 0.005, 0.01, 0.015]
      .map((d) => +(discountRate + d).toFixed(4))
      .filter((r) => r > growthRate);
    Promise.all(rs.map(async (r) => {
      try {
        const res = await fetch(
          `${API_BASE}/financial/ddm/${symbol}?growth_rate=${growthRate}&discount_rate=${r}`,
        );
        const j = await res.json();
        return {r, v: j.code === 0 ? (j.data?.intrinsic_value ?? null) : null};
      } catch { return {r, v: null}; }
    })).then((rows) => alive && setSens(rows));
    return () => { alive = false; };
  }, [symbol, growthRate, discountRate]);

  const mos = data?.margin_of_safety;
  const mosColor =
    mos == null ? 'var(--color-text-secondary)' : mos > 0.25 ? '#3fb950' : mos > 0 ? '#d29922' : '#f85149';

  return (
    <div className="dcf-panel">
      <div className="dcf-panel__assumptions">
        <h3 className="dcf-panel__title">DDM 股利折现假设（红利型公司适用）</h3>
        <div className="dcf-assump">
          <label>
            永续增长 g
            <input type="number" step="0.005" value={growthRate}
              onChange={(e) => setGrowthRate(+e.target.value)} />
          </label>
          <label>
            折现率 r
            <input type="number" step="0.005" value={discountRate}
              onChange={(e) => setDiscountRate(+e.target.value)} />
          </label>
        </div>
      </div>

      {loading && <div className="dcf-panel__loading">计算中…</div>}
      {error && <div className="dcf-panel__error">❌ {error}</div>}
      {data && !loading && data.d0 == null && (
        <div className="dcf-panel__hint">
          ⚠️ 暂无 TTM 分红数据（不分红或分红明细未同步），DDM 不适用此类公司。
        </div>
      )}
      {data && !loading && data.d0 != null && (
        <div className="dcf-panel__result">
          <div className="dcf-mos" style={{color: mosColor}}>
            <div className="dcf-mos__label">安全边际</div>
            <div className="dcf-mos__value">{fmtPct(mos)}</div>
          </div>
          <div className="dcf-vals">
            <div className="dcf-val"><span>内在价值</span><b>{fmtYi(data.intrinsic_value)}</b></div>
            <div className="dcf-val"><span>当前市值</span><b>{fmtYi(data.market_value)}</b></div>
            <div className="dcf-val"><span>TTM 分红 D₀</span><b>{fmtYi(data.d0)}</b></div>
            <div className="dcf-val">
              <span>每股内在价值</span>
              <b>{data.intrinsic_per_share != null ? data.intrinsic_per_share.toFixed(2) + ' 元' : '—'}</b>
            </div>
            <div className="dcf-val">
              <span>每股现价(约)</span>
              <b>{data.price != null ? data.price.toFixed(2) + ' 元' : '—'}</b>
            </div>
            <div className="dcf-val">
              <span>TTM 每股派息</span>
              <b>{data.dps_ttm != null ? data.dps_ttm.toFixed(3) + ' 元' : '—'}</b>
            </div>
          </div>
          <div className="vh-subnote">D₀ 口径：{data.d0_method || '—'} · 估值日 {data.valuation_date || '—'}</div>
        </div>
      )}
      {sens.some((s) => s.v != null) && (
        <div className="dcf-chart">
          <div className="dcf-chart__title">折现率敏感性（不同 r 下的内在价值，亿）</div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart
              data={sens.map((s) => ({r: s.r, intrinsic: s.v != null ? s.v / 1e8 : null}))}
              margin={{top: 16, right: 10, left: 0, bottom: 5}}
            >
              <XAxis
                dataKey="r" type="number" domain={['dataMin', 'dataMax']}
                tickFormatter={(v: number) => `${(v * 100).toFixed(1)}%`}
                {...axisProps}
              />
              <YAxis {...axisProps} />
              <Tooltip
                {...tooltipProps}
                formatter={(v: any) => (v == null ? ['—', '内在价值'] : [`${Number(v).toFixed(0)} 亿`, '内在价值'])}
                labelFormatter={(v: number) => `折现率 ${(v * 100).toFixed(1)}%`}
              />
              <ReferenceLine
                x={discountRate} stroke="#f85149" strokeDasharray="3 3" strokeOpacity={0.7}
                label={{value: '当前', fontSize: 10, fill: '#f85149', position: 'insideTopLeft'}}
              />
              <Line type="monotone" dataKey="intrinsic" stroke="#58a6ff" strokeWidth={2}
                dot={{r: 3, fill: '#58a6ff'}} connectNulls name="内在价值">
                <LabelList dataKey="intrinsic" position="top" offset={8}
                  formatter={(v: any) => (v == null ? '' : Number(v).toFixed(0))}
                  style={{fill: '#8b949e', fontSize: 10}} />
              </Line>
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {data?.note && <div className="dcf-panel__note">{data.note}</div>}
    </div>
  );
}
