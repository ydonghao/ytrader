/**
 * PeriodSwitcher —— 财务分析报告期颗粒度切换器（月/季/年）。
 *
 * - 月：原始报告期原样（仅当该股有月报数据时显示此按钮）
 * - 季：单季换算（后端 period=quarter）
 * - 年：只看年报期（后端 period=year）
 *
 * 默认选中「季」。无月报数据时隐藏「月」按钮。
 */
import React from 'react';

export type Period = 'month' | 'quarter' | 'year';

const LABELS: Record<Period, string> = {
  month: '月',
  quarter: '季',
  year: '年',
};

const ORDER: Period[] = ['month', 'quarter', 'year'];

interface Props {
  value: Period;
  onChange: (p: Period) => void;
  /** 是否显示「月」按钮（该股无月报数据时传 false）。默认 false。 */
  hasMonthly?: boolean;
}

export const PeriodSwitcher: React.FC<Props> = ({
  value,
  onChange,
  hasMonthly = false,
}) => {
  const visible = ORDER.filter((p) => p !== 'month' || hasMonthly);
  return (
    <div className="fin-period-switcher" role="group" aria-label="报告期切换">
      {visible.map((p) => (
        <button
          key={p}
          className={`fin-period-switcher__btn ${
            value === p ? 'is-active' : ''
          }`}
          onClick={() => onChange(p)}
          aria-pressed={value === p}
        >
          {LABELS[p]}
        </button>
      ))}
    </div>
  );
};
