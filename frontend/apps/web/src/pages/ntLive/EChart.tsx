/**
 * EChart — echarts-for-react 薄封装,统一暗色主题 + A股配色(红涨绿跌)。
 * 只在国家队「实时全景」新视图用;既有 recharts 图表不受影响。
 */
import React from 'react';
import ReactECharts from 'echarts-for-react';
import type {EChartsOption} from 'echarts';
import { CHART_COLORS, colorOrange, chartText, chartTextSecondary, chartSurface, chartBorder } from '../../lib/chartTheme';

const BASETextStyle = {
  color: chartTextSecondary,
  fontFamily: 'inherit',
};

interface Props {
  option: EChartsOption;
  height?: number;
  onEvents?: Record<string, (params: any) => void>;
  style?: React.CSSProperties;
}

export const EChart: React.FC<Props> = ({option, height = 280, onEvents, style}) => {
  const merged: EChartsOption = {
    backgroundColor: 'transparent',
    textStyle: BASETextStyle as any,
    grid: {left: 50, right: 20, top: 30, bottom: 30, containLabel: true},
    tooltip: {
      trigger: 'item',
      backgroundColor: chartSurface,
      borderColor: chartBorder,
      textStyle: {color: chartText, fontSize: 12},
    },
    ...option,
    // A股:涨红跌绿。candlestick / kline 红涨绿跌
    color: option.color || [CHART_COLORS[0], CHART_COLORS[3], CHART_COLORS[1], colorOrange, CHART_COLORS[4]],
  };
  return (
    <ReactECharts
      option={merged}
      notMerge
      lazyUpdate
      style={{height, width: '100%', ...style}}
      onEvents={onEvents}
    />
  );
};

export default EChart;
