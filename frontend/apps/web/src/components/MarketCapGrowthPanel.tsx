/**
 * MarketCapGrowthPanel —— 个股「市值业绩」Tab 面板。
 * 营收/归母净利润（单季/累计/TTM）柱 + 总市值折线，单位亿。
 */
import React from 'react';
import { MarketCapGrowthChart } from './MarketCapGrowthChart';
import { useMarketCapGrowth } from '../hooks/useMarketCapGrowth';

export const MarketCapGrowthPanel: React.FC<{ symbol: string | null }> = ({
  symbol,
}) => {
  const { data, loading, error } = useMarketCapGrowth('stock', symbol);
  return (
    <div className="fin-chart-card">
      <MarketCapGrowthChart
        title="市值与业绩增长趋势"
        data={data}
        loading={loading}
        error={error}
      />
    </div>
  );
};
