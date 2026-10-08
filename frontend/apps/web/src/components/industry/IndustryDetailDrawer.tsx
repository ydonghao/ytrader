/** 行业详情抽屉:知识卡/产业链/景气拆解/估值分布直方图/成分表/AI解读。 */
import {useMemo} from 'react';
import {Button, Modal, StateView} from '../ui';
import {EChart} from '../../pages/ntLive/EChart';
import {useIndustryDetail, useInterpret} from '../../hooks/useIndustryAnalysis';
import {chartBorder, colorUp, colorDown} from '../../lib/chartTheme';
import {fmtN, fmtYi} from '../../lib/heat';

interface Props { swCode: string; onClose: () => void; }

export function IndustryDetailDrawer({swCode, onClose}: Props) {
  const {data, loading, error, reload} = useIndustryDetail(swCode);
  const ai = useInterpret();

  const histOption = (h: {edges: number[]; counts: number[]}, color: string) => ({
    tooltip: {trigger: 'axis'},
    grid: {left: 40, right: 10, top: 16, bottom: 26, containLabel: true},
    xAxis: {type: 'category',
      data: h.edges.slice(0, -1).map((e) => e.toFixed(1)),
      axisLine: {lineStyle: {color: chartBorder}}},
    yAxis: {type: 'value',
      splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
    series: [{type: 'bar', color, barCategoryGap: '10%',
      data: h.counts}],
  });

  const sub = data?.prosperity;
  const subBars = useMemo(() => ([
    ['盈利', sub?.score_profit], ['估值', sub?.score_valuation],
    ['动量', sub?.score_momentum], ['资金', sub?.score_flow],
  ] as [string, number | null][]), [sub]);

  return (
    <Modal open title={data ? `${data.name}(${swCode}) 行业详情` : '行业详情'}
      onClose={onClose} width={900}
      footer={<Button size="sm" onClick={onClose}>关闭</Button>}>
      {loading && !data ? <StateView state="loading" /> :
       error ? <StateView state="error" text={error} onRetry={reload} /> :
       !data ? <StateView state="empty" /> :
       <div>
         <div className="ia-drawer-section">
           <div className="ia-drawer-title">投资卡(用户笔记知识层)</div>
           <div style={{marginBottom: 6}}>
             <span className={`ia-tier ia-tier--${data.knowledge.tier}`}>
               {data.knowledge.tier_label}</span>
             <span className="ia-hint" style={{marginLeft: 8}}>
               散户适宜度:{data.knowledge.retail_suitable}</span>
           </div>
           <div>{data.knowledge.approach}</div>
           <div className="ia-chain" style={{marginTop: 8}}>
             {data.knowledge.upstream.map((u) => (
               <span key={u} className="ia-chain-chip">{u}</span>))}
             <span className="ia-arrow">→</span>
             <span className="ia-chain-chip ia-chain-self">{data.name}</span>
             <span className="ia-arrow">→</span>
             {data.knowledge.downstream.map((d) => (
               <span key={d} className="ia-chain-chip">{d}</span>))}
           </div>
         </div>
         {sub && <div className="ia-drawer-section">
           <div className="ia-drawer-title">
             景气分 {fmtN(sub.score, 0)}(拆解)
           </div>
           {subBars.map(([label, v]) => (
             <div key={label} className="ia-subscore">
               <span style={{width: 36}}>{label}</span>
               <div className="ia-subscore-bar">
                 <div className="ia-subscore-fill"
                   style={{width: `${v ?? 0}%`,
                           opacity: v == null ? 0.15 : 1}} />
               </div>
               <span className="num">{fmtN(v, 0)}</span>
             </div>
           ))}
         </div>}
         <div className="ia-drawer-section">
           <div className="ia-drawer-title">
             成分股估值分布({data.member_count}家,截面 {data.valuation_date})
           </div>
           <div className="ia-strength-grid">
             <EChart option={histOption(data.pb_histogram, colorDown) as any} height={180} />
             <EChart option={histOption(data.pe_histogram, colorUp) as any} height={180} />
           </div>
         </div>
         {data.concentration && <div className="ia-drawer-section">
           <div className="ia-drawer-title">行业截面({data.concentration.report_date})</div>
           <div className="ia-hint">
             CR4 {fmtN(data.concentration.cr4, 1)} · HHI {fmtN(data.concentration.hhi, 0)} ·
             样本 {data.concentration.sample_count} 家
           </div>
         </div>}
         <div className="ia-drawer-section">
           <div className="ia-drawer-title">市值Top20成分</div>
           <div className="ia-heat-wrap">
             <table className="ia-heat">
               <thead><tr><th>代码</th><th>名称</th><th>PE(TTM)</th>
                 <th>PB</th><th>总市值</th></tr></thead>
               <tbody>
                 {data.members.map((m) => (
                   <tr key={m.symbol}>
                     <td><b>{m.symbol}</b></td><td style={{textAlign: 'left'}}>{m.name ?? '—'}</td>
                     <td className="num">{fmtN(m.pe_ttm, 1)}</td>
                     <td className="num">{fmtN(m.pb, 2)}</td>
                     <td className="num">{fmtYi(m.total_mv)}</td>
                   </tr>
                 ))}
               </tbody>
             </table>
           </div>
         </div>
         <div className="ia-drawer-section">
           <Button size="sm" loading={ai.loading} onClick={() => ai.run(swCode)}>
             AI 景气解读
           </Button>
           {ai.error && <div className="ia-hint" style={{marginTop: 6}}>{ai.error}(503=未配置LLM)</div>}
           {ai.result && <div style={{marginTop: 8}}>
             <div>{ai.result.summary}</div>
             {ai.result.drivers.length > 0 && <div style={{marginTop: 6}}>
               <b>驱动:</b>{ai.result.drivers.join('；')}</div>}
             {ai.result.risks.length > 0 && <div style={{marginTop: 4}}>
               <b>风险:</b>{ai.result.risks.join('；')}</div>}
           </div>}
         </div>
       </div>}
    </Modal>
  );
}
