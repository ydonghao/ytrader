/**
 * 归一化工具（min-max 到 0-100）。
 * 用于多指标叠加图，把不同量纲的指标拉到同一刻度。
 */
export function minMaxNormalize(values: number[]): number[] {
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) return values.map(() => 50);
  return values.map((v) => ((v - min) / (max - min)) * 100);
}
