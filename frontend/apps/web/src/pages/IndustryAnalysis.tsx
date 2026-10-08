/** 行业分析:行业景气热力图/板块强弱 两Tab+行业详情抽屉。(宏观择时破净率已迁 /indices 市场温度页) */
import {useState} from 'react';
import {PageHeader, Tabs} from '../components/ui';
import {ProsperityHeatmap} from '../components/industry/ProsperityHeatmap';
import {StrengthFlowTab} from '../components/industry/StrengthFlowTab';
import {IndustryDetailDrawer} from '../components/industry/IndustryDetailDrawer';
import {useIndustryOverview, type PctWindow} from '../hooks/useIndustryAnalysis';
import './IndustryAnalysis.css';

export function IndustryAnalysis() {
  const [tab, setTab] = useState<'heatmap' | 'strength'>('heatmap');
  const [win, setWin] = useState<PctWindow>(8);
  const [picked, setPicked] = useState<string | null>(null);
  const overview = useIndustryOverview(win);
  const industries = (overview.data?.rows ?? [])
    .map((r) => ({sw_code: r.sw_code, name: r.name}));

  return (
    <div className="ia-page">
      <PageHeader title="行业分析"
        subtitle="行业景气热力图 · 板块资金强弱(申万一级31行业);破净率择时已并入市场温度页" />
      <Tabs active={tab} onChange={(k) => setTab(k as typeof tab)} tabs={[
        {key: 'heatmap', label: '景气热力图'},
        {key: 'strength', label: '板块强弱'},
      ]} />
      {tab === 'heatmap' &&
        <ProsperityHeatmap win={win} setWin={setWin} overview={overview} onPick={setPicked} />}
      {tab === 'strength' &&
        <StrengthFlowTab industries={industries} onPick={setPicked} />}
      {picked && <IndustryDetailDrawer swCode={picked} onClose={() => setPicked(null)} />}
    </div>
  );
}
