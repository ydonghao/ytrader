/**
 * 指数PE卡片 — 复用 useIndexPe(整体法市盈率)。
 * 端点只收整年:按全局范围向上取整 years 取数,再客户端按 start 裁剪;
 * PE 线(蓝,断线不插值) + 均值(黄)/高估(红)/低估(绿)常数参考线。
 * 参考线 stats 为取数窗口(≥显示窗口)统计,窗口越近精确。
 */
import React, {useMemo} from 'react';
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {StateView} from '../../../components/ui';
import {useIndexPe} from '../../../hooks/useIndexPe';
import {
  axisProps,
  colorDown,
  colorUp,
  gridProps,
  tooltipProps,
} from '../../../lib/chartTheme';
import {DateRange, rangeToYears} from '../boardTypes';

const PE_COLOR = '#0a84ff';
const MEAN_COLOR = '#eab308';

export interface IndexPeCardProps {
  config: {code: string};
  range: DateRange;
  refreshKey: number;
}

export const IndexPeCard: React.FC<IndexPeCardProps> = ({
  config, range,
}) => {
  const years = rangeToYears(range);
  const {data, loading, error} = useIndexPe(config.code, years);

  const series = useMemo(() => {
    if (!data) return [];
    if (!range.start) return data.series;
    return data.series.filter((p) => p.date >= range.start!);
  }, [data, range.start]);

  if (loading || error || series.length === 0) {
    return (
      <div className="board-chart">
        <StateView
          state={loading ? 'loading' : error ? 'error' : 'empty'}
          text={error ? error : series.length === 0 && !loading ? '该区间无PE数据' : undefined}
        />
      </div>
    );
  }

  const stats = data?.stats || null;

  return (
    <div className="board-chart">
      {data?.current?.pe != null && (
        <div className="board-pe__current">
          当前 {data.current.pe.toFixed(2)}
        </div>
      )}
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={series} margin={{top: 24, right: 12, bottom: 4, left: 4}}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="date" {...axisProps} />
          <YAxis {...axisProps} domain={['auto', 'auto']} />
          <Tooltip
            {...tooltipProps}
            formatter={(v: unknown) => [
              typeof v === 'number' ? v.toFixed(2) : '—',
              'PE',
            ]}
          />
          <Legend wrapperStyle={{fontSize: 11}} />
          <Line
            type="monotone"
            dataKey="pe"
            name="市盈率"
            stroke={PE_COLOR}
            dot={false}
            strokeWidth={1.5}
            connectNulls={false}
          />
          {stats && (
            <ReferenceLine
              y={stats.mean}
              ifOverflow="extendDomain"
              stroke={MEAN_COLOR}
              strokeDasharray="6 4"
              label={{value: `均值 ${stats.mean.toFixed(1)}`, position: 'insideTopRight', fill: MEAN_COLOR, fontSize: 10}}
            />
          )}
          {stats && (
            <ReferenceLine
              y={stats.high}
              ifOverflow="extendDomain"
              stroke={colorUp}
              strokeDasharray="6 4"
              label={{value: `高估 ${stats.high.toFixed(1)}`, position: 'insideTopRight', fill: colorUp, fontSize: 10}}
            />
          )}
          {stats && (
            <ReferenceLine
              y={stats.low}
              ifOverflow="extendDomain"
              stroke={colorDown}
              strokeDasharray="6 4"
              label={{value: `低估 ${stats.low.toFixed(1)}`, position: 'insideBottomRight', fill: colorDown, fontSize: 10}}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};
