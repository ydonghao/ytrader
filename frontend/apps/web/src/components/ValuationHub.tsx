/**
 * ValuationHub — 五法估值中心（Financial 页「估值」Tab）。
 *
 * 《股票投资课程》15 集估值方法全集，五法各测一遍、交叉验证：
 *   绝对估值：① 现金流折现 DCF  ② 股利折现 DDM  ③ 净资产分析
 *   相对估值：④ 类比估值（跟同类型公司比）  ⑤ 乘数估值（和自己的过去比）
 *
 * 总览页五卡汇总（默认参数下的结论），子页可调假设细算；
 * ⑤ 乘数估值即原「估值分位」面板（PE/PB/PS/股息率 × 多窗口历史分位）。
 */
import {useEffect, useMemo, useState} from 'react';
import {getApiBase} from '../lib/api';
import {DcfPanel} from './DcfPanel';
import {DdmPanel} from './valuation/DdmPanel';
import {AssetValuePanel} from './valuation/AssetValuePanel';
import {CompsPanel} from './valuation/CompsPanel';
import {ValuationPercentileChart, windowLabel} from './ValuationPercentileChart';
import {StateView, Tabs} from './ui';
import {useValuationPercentile} from '../hooks/useValuationPercentile';
import {useKlineCloseMap} from '../hooks/useFinancialOverlays';
import {CHART_COLORS} from '../lib/chartTheme';
import './ValuationHub.css';

const API_BASE = getApiBase();

type SubTab = 'overview' | 'dcf' | 'ddm' | 'asset' | 'comps' | 'multiples';

// ── 总览汇总数据（默认参数并行拉取） ─────────────────────────────────────────

interface SummaryRow {
  key: SubTab;
  cat: '绝对估值' | '相对估值';
  name: string;
  metric: string;
  verdict: string;
  tone: 'good' | 'warn' | 'bad' | 'na';
  hint: string;
}

function mosVerdict(mos: number | null): {v: string; tone: SummaryRow['tone']} {
  if (mos == null) return {v: '不适用', tone: 'na'};
  if (mos > 0.25) return {v: '显著低估', tone: 'good'};
  if (mos > 0) return {v: '低估', tone: 'good'};
  if (mos > -0.15) return {v: '略高于内在价值', tone: 'warn'};
  return {v: '高估', tone: 'bad'};
}

function fetchJson(url: string): Promise<any> {
  return fetch(url).then((r) => r.json()).catch(() => null);
}

function useSummary(symbol: string) {
  const [rows, setRows] = useState<SummaryRow[] | null>(null);

  useEffect(() => {
    if (!symbol) { setRows(null); return; }
    let alive = true;
    Promise.all([
      fetchJson(`${API_BASE}/financial/dcf/${symbol}`),
      fetchJson(`${API_BASE}/financial/ddm/${symbol}`),
      fetchJson(`${API_BASE}/financial/asset-value/${symbol}`),
      fetchJson(`${API_BASE}/financial/comps/${symbol}`),
      fetchJson(`${API_BASE}/financial/valuation-percentile/${symbol}?windows=10y&metrics=pe_ttm`),
    ]).then(([dcf, ddm, asset, comps, pct]) => {
      if (!alive) return;
      const d = (j: any) => (j && j.code === 0 ? j.data : null);
      const D = d(dcf), M = d(ddm), A = d(asset), C = d(comps), P = d(pct);

      const dcfM = mosVerdict(D?.margin_of_safety ?? null);
      const ddmM = mosVerdict(M?.margin_of_safety ?? null);

      let assetV = {v: '无 PB 序列', tone: 'na' as const};
      if (A?.below_book) assetV = {v: '破净', tone: 'good'};
      else if (A?.band?.state) {
        const s = A.band.state as string;
        assetV = {
          v: s,
          tone: s === '超跌' || s === '合理偏低' ? 'good' : s === '合理偏高' ? 'warn' : 'bad',
        };
      }

      const peUp = C?.multiples?.pe_ttm?.upside ?? null;
      const compsV = peUp == null
        ? {v: '样本不足', tone: 'na' as const}
        : peUp > 0.2
          ? {v: '低于同行', tone: 'good' as const}
          : peUp < -0.2
            ? {v: '高于同行', tone: 'bad' as const}
            : {v: '接近同行', tone: 'warn' as const};

      const p10 = P?.metrics?.pe_ttm?.windows?.['10y']?.percentile ?? null;
      const pctV = p10 == null
        ? {v: '无数据', tone: 'na' as const}
        : p10 < 20
          ? {v: `历史低位 ${Math.round(p10)}%`, tone: 'good' as const}
          : p10 > 80
            ? {v: `历史高位 ${Math.round(p10)}%`, tone: 'bad' as const}
            : {v: `历史中位 ${Math.round(p10)}%`, tone: 'warn' as const};

      setRows([
        {
          key: 'dcf', cat: '绝对估值', name: '① 现金流折现 DCF',
          metric: D?.intrinsic_value != null && D?.market_value != null
            ? `内在 ${Math.round(D.intrinsic_value / 1e8)} 亿 vs 市值 ${Math.round(D.market_value / 1e8)} 亿`
            : '暂无 FCF 数据',
          verdict: dcfM.v, tone: dcfM.tone,
          hint: '未来自由现金流按 WACC 折现，两阶段 + 蒙特卡洛',
        },
        {
          key: 'ddm', cat: '绝对估值', name: '② 股利折现 DDM',
          metric: M?.intrinsic_value != null && M?.market_value != null
            ? `内在 ${Math.round(M.intrinsic_value / 1e8)} 亿 vs 市值 ${Math.round(M.market_value / 1e8)} 亿`
            : '暂无分红数据',
          verdict: ddmM.v, tone: ddmM.tone,
          hint: 'Gordon 模型，适用于分红稳定的红利型公司',
        },
        {
          key: 'asset', cat: '绝对估值', name: '③ 净资产分析',
          metric: A?.current_pb != null
            ? `PB ${A.current_pb.toFixed(2)}${A.band ? `（μ ${A.band.mean.toFixed(2)} ±σ ${A.band.std.toFixed(2)}）` : ''}`
            : '暂无 PB 数据',
          verdict: assetV.v, tone: assetV.tone,
          hint: '账面净资产为底线，PB 通道 μ±1σ 判四态',
        },
        {
          key: 'comps', cat: '相对估值', name: '④ 类比估值（跟同类公司比）',
          metric: C?.industry?.name
            ? `${C.industry.name} ${C.industry.member_count} 家 · PE ${C.multiples?.pe_ttm?.own ?? '—'} vs 中位 ${C.multiples?.pe_ttm?.median ?? '—'}`
            : '无行业归属',
          verdict: compsV.v, tone: compsV.tone,
          hint: '同行中位乘数反推隐含市值；全行业系统性偏差时失效',
        },
        {
          key: 'multiples', cat: '相对估值', name: '⑤ 乘数估值（和自己的过去比）',
          metric: P?.metrics?.pe_ttm?.current != null
            ? `PE ${P.metrics.pe_ttm.current.toFixed(2)} · 10 年分位 ${p10 != null ? Math.round(p10) + '%' : '—'}`
            : '暂无分位数据',
          verdict: pctV.v, tone: pctV.tone,
          hint: 'PE/PB/PS/股息率 × 3~20 年历史分位与估值带',
        },
      ]);
    });
    return () => { alive = false; };
  }, [symbol]);

  return rows;
}

// ── ⑤ 乘数估值子面板（原「估值分位」） ─────────────────────────────────────

const PCT_METRICS: Array<{key: string; label: string; unit: string; color: string}> = [
  {key: 'pe_ttm', label: '市盈率 TTM', unit: '', color: CHART_COLORS[0]},
  {key: 'pb', label: '市净率', unit: '', color: CHART_COLORS[1]},
  {key: 'ps_ttm', label: '市销率 TTM', unit: '', color: '#9333ea'},
  {key: 'dv_ttm', label: '股息率 TTM', unit: '%', color: '#ea580c'},
];

function MultiplesPanel({symbol}: {symbol: string}) {
  const [valWindow, setValWindow] = useState('10y');
  const [valShowPrice, setValShowPrice] = useState(false);
  const {data: percentileData, loading: pctLoading} = useValuationPercentile(
    symbol, {windows: '3y,5y,10y,15y,20y,all'},
  );

  const valSeriesDates = useMemo(() => {
    const dates = new Set<string>();
    for (const m of Object.values(percentileData?.metrics || {})) {
      for (const p of m?.series || []) {
        if (p?.date) dates.add(p.date);
      }
    }
    return [...dates].sort();
  }, [percentileData]);
  const {data: valPriceMap} = useKlineCloseMap(symbol, valSeriesDates, valShowPrice);

  return (
    <div>
      <div className="fin-summary__cards" style={{marginBottom: 12}}>
        <div className="fin-metric-card">
          <div className="fin-metric-card__label">当前估值（截至 {percentileData?.as_of || '—'}）</div>
          <div className="fin-metric-card__value" style={{fontSize: 16}}>
            {PCT_METRICS.map((m) => {
              const cur = percentileData?.metrics?.[m.key]?.current;
              return cur != null ? `${m.label.replace(' TTM', '')} ${cur.toFixed(2)}${m.unit}　` : '';
            }).join('') || '—'}
          </div>
        </div>
      </div>

      <div className="fin-metric-chips" style={{marginBottom: 12}}>
        {['3y', '5y', '10y', '15y', '20y', 'all'].map((w) => (
          <button
            key={w}
            className={`fin-metric-chip ${valWindow === w ? 'is-active' : ''}`}
            style={valWindow === w ? {borderColor: 'var(--color-accent)', color: 'var(--color-accent)'} : undefined}
            onClick={() => setValWindow(w)}
          >
            {windowLabel(w)}
          </button>
        ))}
        <span style={{flex: 1}} />
        <button
          className={`fin-metric-chip ${valShowPrice ? 'is-active' : ''}`}
          style={valShowPrice ? {borderColor: CHART_COLORS[5], color: CHART_COLORS[5]} : undefined}
          onClick={() => setValShowPrice((v) => !v)}
        >
          叠加股价
        </button>
      </div>

      {pctLoading ? (
        <StateView state="loading" text="加载分位数据中…" />
      ) : percentileData ? (
        <div style={{display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12}}>
          {PCT_METRICS.map((m) => (
            <ValuationPercentileChart
              key={m.key}
              title={m.label}
              unit={m.unit}
              color={m.color}
              windowKey={valWindow}
              metric={percentileData.metrics[m.key] ?? null}
              showPrice={valShowPrice}
              priceMap={valPriceMap}
            />
          ))}
        </div>
      ) : (
        <StateView state="empty" text="该股票暂无估值分位数据" />
      )}
    </div>
  );
}

// ── 主容器 ───────────────────────────────────────────────────────────────────

const SUB_TABS: Array<{key: SubTab; label: string}> = [
  {key: 'overview', label: '总览'},
  {key: 'dcf', label: '① DCF 现金流折现'},
  {key: 'ddm', label: '② DDM 股利折现'},
  {key: 'asset', label: '③ 净资产分析'},
  {key: 'comps', label: '④ 类比同行'},
  {key: 'multiples', label: '⑤ 乘数历史'},
];

export function ValuationHub({symbol}: {symbol: string}) {
  const [subTab, setSubTab] = useState<SubTab>('overview');
  const summary = useSummary(symbol);

  // 切股票回总览
  useEffect(() => { setSubTab('overview'); }, [symbol]);

  return (
    <div className="vh">
      <Tabs
        active={subTab}
        onChange={(k) => setSubTab(k as SubTab)}
        tabs={SUB_TABS.map((t) => ({key: t.key, label: t.label}))}
      />

      <div className="vh__body">
        {subTab === 'overview' && (
          summary == null
            ? <StateView state="loading" text="五法汇总计算中…" />
            : (
              <>
                <div className="vh-grid">
                  {summary.map((r) => (
                    <button
                      key={r.key}
                      className={`vh-method vh-method--${r.tone}`}
                      onClick={() => setSubTab(r.key)}
                    >
                      <div className="vh-method__cat">{r.cat}</div>
                      <div className="vh-method__name">{r.name}</div>
                      <div className={`vh-method__verdict vh-method__verdict--${r.tone}`}>{r.verdict}</div>
                      <div className="vh-method__metric">{r.metric}</div>
                      <div className="vh-method__hint">{r.hint}</div>
                    </button>
                  ))}
                </div>
                <div className="dcf-panel__note">
                  课程口径：估值只能给出大致正确的范围，五法各测一遍、交叉验证，
                  综合评估出相对合理的价格区间；单法结论不构成投资依据。
                </div>
              </>
            )
        )}
        {subTab === 'dcf' && <DcfPanel symbol={symbol} />}
        {subTab === 'ddm' && <DdmPanel symbol={symbol} />}
        {subTab === 'asset' && <AssetValuePanel symbol={symbol} />}
        {subTab === 'comps' && <CompsPanel symbol={symbol} />}
        {subTab === 'multiples' && <MultiplesPanel symbol={symbol} />}
      </div>
    </div>
  );
}
