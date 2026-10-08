import {useCallback} from 'react';
import {useReplayStore} from './store';

/**
 * exam+active 期间真实日期 → 旅程相对标签;其余场景原样。
 *
 * 锚定:第1天 = 旅程首日(不是加载的K线历史窗首日)。offset = dates.length
 * - dayOrdinal 为"历史窗长度",日期的旅程序号 = indexOf(d) - offset + 1;
 * 旅程开始前的历史日显示「前N日」。直接用 indexOf 会把 3000 根历史
 * 当成天数(GUI验收实抓:首日显示"第2994天",且构成间接年代泄露)。
 */
export const dayLabelOf = (
  blind: boolean, dates: string[], d: string, offset = 0,
): string => {
  if (!blind) return d;
  const i = dates.indexOf(d);
  if (i < 0) return d;
  const n = i - offset + 1;
  return n >= 1 ? `第${n}天` : `前${1 - n}日`;
};

export const useBlind = (): boolean => {
  const session = useReplayStore((s) => s.session);
  return !!session && session.mode === 'exam' && session.status === 'active';
};

export const useDayLabel = (): ((d: string) => string) => {
  const blind = useBlind();
  const dates = useReplayStore((s) => s.dates);
  const dayOrdinal = useReplayStore((s) => s.dayOrdinal);
  return useCallback(
    (d: string) => dayLabelOf(
      blind, dates, d, blind ? Math.max(0, dates.length - dayOrdinal) : 0),
    [blind, dates, dayOrdinal]);
};
