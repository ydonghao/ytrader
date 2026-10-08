import { describe, expect, it } from 'vitest';
import { daysSince, formatDaysAgo } from '../checklistHelpers';

describe('daysSince', () => {
  it('今天为 0', () => {
    expect(daysSince(new Date().toISOString())).toBe(0);
  });
  it('25小时前为 1 天', () => {
    expect(daysSince(new Date(Date.now() - 25 * 3600_000).toISOString())).toBe(1);
  });
  it('空值返回 null', () => {
    expect(daysSince(null)).toBeNull();
    expect(daysSince('')).toBeNull();
    expect(daysSince('not-a-date')).toBeNull();
  });
  it('70天前为 70 天', () => {
    expect(daysSince(new Date(Date.now() - 70 * 86400_000).toISOString())).toBe(70);
  });
});

describe('formatDaysAgo', () => {
  it('今天', () => {
    expect(formatDaysAgo(new Date().toISOString())).toBe('今天');
  });
  it('1 天前', () => {
    expect(formatDaysAgo(new Date(Date.now() - 30 * 3600_000).toISOString())).toBe('1 天前');
  });
  it('45天→1 个月前', () => {
    expect(formatDaysAgo(new Date(Date.now() - 45 * 86400_000).toISOString())).toBe('1 个月前');
  });
  it('空值→空串', () => {
    expect(formatDaysAgo(null)).toBe('');
  });
  it('2 天前', () => {
    expect(formatDaysAgo(new Date(Date.now() - 2 * 86400_000).toISOString())).toBe('2 天前');
  });
  it('370天→1 年前', () => {
    expect(formatDaysAgo(new Date(Date.now() - 370 * 86400_000).toISOString())).toBe('1 年前');
  });
});
