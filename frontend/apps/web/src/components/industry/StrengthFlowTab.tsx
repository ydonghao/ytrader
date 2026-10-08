/** 板块强弱:左=东财行业资金流(当日/5日/20日);右=行业RS线 vs 沪深300(≤5叠加)。 */
import {useMemo, useState} from 'react';
import {Card, StateView} from '../ui';
import {EChart} from '../../pages/ntLive/EChart';
import {useIndustryFlow, useStrength} from '../../hooks/useIndustryAnalysis';
import {chartBorder, colorUp, colorDown, seriesColor} from '../../lib/chartTheme';

interface Props {
  industries: {sw_code: string; name: string}[];
  onPick: (swCode: string) => void;
}

export function StrengthFlowTab({industries, onPick}: Props) {
  const flow = useIndustryFlow();
  const [picked, setPicked] = useState<string[]>([]);
  const main = picked[0] || industries[0]?.sw_code || '';
  const strength = useStrength(main || null, picked.slice(1, 5));

  const flowOption = useMemo(() => {
    const rows = (flow.data?.rows ?? []).slice(0, 15);
    return {
      tooltip: {trigger: 'axis'},
      grid: {left: 90, right: 20, top: 20, bottom: 30, containLabel: false},
      xAxis: {type: 'value', axisLine: {lineStyle: {color: chartBorder}}},
      yAxis: {type: 'category', data: rows.map((r) => r.em_industry_name).reverse(),
        axisLabel: {fontSize: 11}},
      series: [{
        type: 'bar',
        data: rows.map((r) => ({
          // 后端 flow20 已是"亿"(summarize_flow 透传表内单位)
          value: +(r.flow20 ?? 0).toFixed(1),
          itemStyle: {color: (r.flow20 ?? 0) >= 0 ? colorUp : colorDown,
            borderRadius: [0, 4, 4, 0]},
        })).reverse(),
      }],
    } as any;
  }, [flow.data]);

  const rsOption = useMemo(() => {
    const s = strength.data;
    if (!s || !Object.keys(s.lines).length) return {};
    const dates = s.lines[main]?.map((p) => p.date) ?? [];
    // 基准线按主行业日期过滤:x 轴取 lines[main] 的日期,行业缺日时
    // 未过滤的基准序列会按索引与错位日期对齐(虚线漂移)
    const mainDates = new Set((s.lines[main] ?? []).map((p) => p.date));
    return {
      tooltip: {trigger: 'axis'},
      legend: {top: 0, textStyle: {fontSize: 11}},
      xAxis: {type: 'category', data: dates,
        axisLine: {lineStyle: {color: chartBorder}}},
      yAxis: {type: 'value', scale: true,
        splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      dataZoom: [{type: 'inside', start: 40, end: 100}],
      series: [
        {name: '沪深300(rebase)', type: 'line', showSymbol: false,
         lineStyle: {type: 'dashed', width: 1},
         data: s.benchmark.filter((p) => mainDates.has(p.date))
           .map((p) => p.close)},
        ...Object.entries(s.lines).map(([code, line], i) => ({
          name: s.names[code] ?? code, type: 'line' as const, showSymbol: false,
          lineStyle: {width: 1.6}, color: seriesColor(i),
          data: line.map((p) => p.rs),
        })),
      ],
    } as any;
  }, [strength.data, main]);

  const toggle = (code: string) => {
    setPicked((prev) => prev.includes(code)
      ? prev.filter((c) => c !== code)
      : [...prev, code].slice(-5));
  };

  return (
    <div className="ia-tab ia-strength-grid">
      <Card>
        <div className="ia-drawer-title">
          行业资金流·20日主力净流入(亿) {flow.data?.snapshot ? `· 至 ${flow.data.snapshot}` : ''}
        </div>
        {flow.loading && !flow.data ? <StateView state="loading" /> :
         !flow.data?.rows.length ? <StateView state="empty" text="暂无资金流历史(等待17:05 job积累)" /> :
         <EChart option={flowOption} height={440} />}
        <div className="ia-hint">东财口径(~90行业);红=净流入 绿=净流出;点击右侧行业名叠加RS线</div>
      </Card>
      <Card>
        <div className="ia-drawer-title">相对强度 RS(标的/沪深300,均rebase 1.0)</div>
        <div className="ia-chip-row">
          {industries.map((i) => (
            <button key={i.sw_code}
              className={`ia-chain-chip ${picked.includes(i.sw_code) ? 'ia-chain-self' : ''}`}
              onClick={() => toggle(i.sw_code)}
              onDoubleClick={() => onPick(i.sw_code)}>{i.name}</button>
          ))}
        </div>
        {strength.loading && !strength.data ? <StateView state="loading" /> :
         !strength.data || !Object.keys(strength.data.lines).length ?
           <StateView state="empty" text="选择行业查看RS线" /> :
         <EChart option={rsOption} height={340} />}
        <div className="ia-hint">单击=加入叠加(≤5);双击=打开行业详情</div>
      </Card>
    </div>
  );
}
