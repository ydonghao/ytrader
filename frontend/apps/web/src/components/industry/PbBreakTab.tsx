/** 宏观择时:全市场/行业破净率历史,>10% 区间标红「阶段性底部参考区」。 */
import {useMemo, useState} from 'react';
import {Card, StateView} from '../ui';
import {EChart} from '../../pages/ntLive/EChart';
import {usePbBreak} from '../../hooks/useIndustryAnalysis';
import {chartBorder, chartTextSecondary, colorWarning} from '../../lib/chartTheme';

interface Props {
  industries: {sw_code: string; name: string}[];
  onPick: (swCode: string) => void;
}

export function PbBreakTab({industries, onPick}: Props) {
  const [scopeCode, setScopeCode] = useState('');        // '' = market
  const [years, setYears] = useState(10);
  const scope = scopeCode ? 'industry' : 'market';
  const {data, loading, error} = usePbBreak(scope, scopeCode, years);

  const option = useMemo(() => {
    if (!data?.series.length) return {};
    const series = data.series;
    const dates = series.map((p) => p.trade_date.slice(0, 10));
    const rates = series.map((p) => (p.break_rate ?? 0) * 100);
    // 连续 >10% 的区段 → markArea
    const areas: any[] = [];
    let start = -1;
    rates.forEach((v, i) => {
      const over = v > data.threshold * 100;
      if (over && start < 0) start = i;
      if (!over && start >= 0) {
        areas.push([{xAxis: dates[start]}, {xAxis: dates[i - 1]}]);
        start = -1;
      }
    });
    if (start >= 0) {
      areas.push([{xAxis: dates[start]},
                  {xAxis: dates[dates.length - 1]}]);
    }
    return {
      tooltip: {trigger: 'axis'},
      xAxis: {type: 'category', data: dates, axisLine: {lineStyle: {color: chartBorder}}},
      yAxis: {type: 'value',
        max: (v: any) => Math.max(60, Math.ceil(v.max / 10) * 10),
        axisLabel: {formatter: '{value}%'},
        splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      dataZoom: [{type: 'inside', start: 55, end: 100}],
      series: [{
        type: 'line', name: '破净率', data: rates.map((v) => +v.toFixed(2)),
        showSymbol: false, lineStyle: {width: 1.5},
        markLine: {silent: true, symbol: 'none', lineStyle: {color: colorWarning, type: 'dashed'},
          label: {formatter: '10% 底部参考线', color: chartTextSecondary},
          data: [{yAxis: data.threshold * 100}]},
        markArea: {silent: true, itemStyle: {color: 'rgba(255,69,58,0.10)'},
          // 标签只挂在第一段(38段重复 label 重叠问题)
          data: areas.map((a, i) => i === 0
            ? [{...a[0], label: {show: true, position: 'insideTop',
                color: colorWarning, formatter: '阶段性底部参考区'}}, a[1]]
            : a)},
      }],
    } as any;
  }, [data]);

  const cur = data?.current;

  return (
    <div className="ia-tab">
      <div className="ia-toolbar">
        <select className="ia-select" value={scopeCode}
          onChange={(e) => setScopeCode(e.target.value)}>
          <option value="">全市场(market · 择时主信号)</option>
          {industries.map((i) => (
            <option key={i.sw_code} value={i.sw_code}>{i.name}(行业)</option>
          ))}
        </select>
        <select className="ia-select" value={years}
          onChange={(e) => setYears(Number(e.target.value))}>
          <option value={5}>近5年</option>
          <option value={10}>近10年</option>
          <option value={35}>全历史</option>
        </select>
        {scope === 'industry' && (
          <span className="ia-hint">⚠ 行业口径=当前成分回溯,含成分漂移偏差;择时只看全市场</span>
        )}
      </div>
      <div className="ia-cards">
        <Card><div className="ia-card">
          <div className="ia-card-label">当前破净率</div>
          <div className={`ia-card-value ${data?.over_threshold_now ? 'is-up' : ''}`}>
            {cur?.break_rate != null ? `${(cur.break_rate * 100).toFixed(2)}%` : '—'}
          </div>
          <div className="ia-card-sub">{cur ? `${cur.trade_date} · 破净 ${cur.break_count}/${cur.total_count} 家` : ''}</div>
        </div></Card>
        <Card><div className="ia-card">
          <div className="ia-card-label">历史分位(窗口内)</div>
          <div className="ia-card-value">
            {data?.current_percentile != null ? `${data.current_percentile.toFixed(0)}%` : '—'}
          </div>
          <div className="ia-card-sub">中位PB {cur?.median_pb?.toFixed(2) ?? '—'}</div>
        </div></Card>
        <Card><div className="ia-card">
          <div className="ia-card-label">信号状态</div>
          <div className={`ia-card-value ${data?.over_threshold_now ? 'is-up' : ''}`}>
            {data?.over_threshold_now ? '>10% 底部参考区' : '未触及'}
          </div>
          <div className="ia-card-sub">阈值:破净率 10%(宏观择时,非个股机会)</div>
        </div></Card>
      </div>
      <Card>
        {loading && !data ? <StateView state="loading" /> :
         error ? <StateView state="error" text={error} /> :
         !data?.series.length ? <StateView state="empty" text="暂无破净率数据(先跑回填)" /> :
         <EChart option={option} height={360} />}
      </Card>
      {scopeCode && (
        <button className="ia-linklike" onClick={() => onPick(scopeCode)}>
          查看 {industries.find((i) => i.sw_code === scopeCode)?.name} 行业详情 →
        </button>
      )}
    </div>
  );
}
