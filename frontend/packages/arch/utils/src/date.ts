/**
 * Date utilities
 */

export type DateUnit = 'ms' | 's' | 'm' | 'h' | 'd';

const MS_PER_SECOND = 1000;
const MS_PER_MINUTE = 60 * MS_PER_SECOND;
const MS_PER_HOUR = 60 * MS_PER_MINUTE;
const MS_PER_DAY = 24 * MS_PER_HOUR;

export const convertTimeUnit = (value: number, from: DateUnit, to: DateUnit): number => {
  const conversions: Record<DateUnit, number> = {
    ms: 1,
    s: MS_PER_SECOND,
    m: MS_PER_MINUTE,
    h: MS_PER_HOUR,
    d: MS_PER_DAY,
  };

  return (value * conversions[from]) / conversions[to];
};

/**
 * Get start of day for a given date
 */
export const startOfDay = (date: Date = new Date()): Date => {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
};

/**
 * Get end of day for a given date
 */
export const endOfDay = (date: Date = new Date()): Date => {
  const d = new Date(date);
  d.setHours(23, 59, 59, 999);
  return d;
};

/**
 * Get start of week (Monday)
 */
export const startOfWeek = (date: Date = new Date()): Date => {
  const d = new Date(date);
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  d.setDate(diff);
  d.setHours(0, 0, 0, 0);
  return d;
};

/**
 * Get start of month
 */
export const startOfMonth = (date: Date = new Date()): Date => {
  const d = new Date(date);
  d.setDate(1);
  d.setHours(0, 0, 0, 0);
  return d;
};

/**
 * Add time to a date
 */
export const addTime = (date: Date, value: number, unit: DateUnit): Date => {
  const ms = convertTimeUnit(value, unit, 'ms');
  return new Date(date.getTime() + ms);
};

/**
 * Get the difference between two dates in specified unit
 */
export const diff = (date1: Date, date2: Date, unit: DateUnit): number => {
  const diffMs = Math.abs(date2.getTime() - date1.getTime());
  return convertTimeUnit(diffMs, 'ms', unit);
};

/**
 * Check if two dates are on the same day
 */
export const isSameDay = (date1: Date, date2: Date): boolean => {
  return (
    date1.getFullYear() === date2.getFullYear() &&
    date1.getMonth() === date2.getMonth() &&
    date1.getDate() === date2.getDate()
  );
};

/**
 * Generate time range array
 */
export const generateTimeRange = (
  start: Date,
  end: Date,
  interval: number,
  unit: DateUnit
): Date[] => {
  const ranges: Date[] = [];
  let current = new Date(start);

  while (current <= end) {
    ranges.push(new Date(current));
    current = addTime(current, interval, unit);
  }

  return ranges;
};

/**
 * Get K-line interval in milliseconds
 */
export const getKlineIntervalMs = (interval: string): number => {
  const intervalMap: Record<string, number> = {
    '1m': MS_PER_MINUTE,
    '5m': 5 * MS_PER_MINUTE,
    '15m': 15 * MS_PER_MINUTE,
    '30m': 30 * MS_PER_MINUTE,
    '1h': MS_PER_HOUR,
    '4h': 4 * MS_PER_HOUR,
    '1d': MS_PER_DAY,
    '1w': 7 * MS_PER_DAY,
  };

  return intervalMap[interval] || MS_PER_HOUR;
};
