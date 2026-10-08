/** fetchCache 纯核心单测（node 环境，不碰 window）。 */
import {afterEach, describe, expect, it, vi} from 'vitest';
import {
  CACHE_TTL_MS,
  cachedGetJson,
  clearFetchCache,
  shouldCacheUrl,
} from './fetchCache';

describe('shouldCacheUrl', () => {
  it('缓存自家幂等 GET', () => {
    expect(shouldCacheUrl('http://x/api/v1/thesis')).toBe(true);
    expect(shouldCacheUrl('http://x/api/v1/management-promises/sh600519'))
      .toBe(true);
  });
  it('排除轮询/盲盒/非 API', () => {
    expect(shouldCacheUrl('http://x/api/v1/replay/advance?x=1')).toBe(false);
    expect(shouldCacheUrl('http://x/api/v1/market/indices')).toBe(false);
    expect(shouldCacheUrl('http://x/api/v1/trade/orders')).toBe(false);
    expect(shouldCacheUrl('/static/js/main.js')).toBe(false);
  });
});

describe('cachedGetJson', () => {
  afterEach(() => {
    clearFetchCache();
    vi.restoreAllMocks();
  });

  it('新鲜期内重复请求不打网络', async () => {
    let calls = 0;
    const fetcher = async () => ({v: ++calls});
    const a = await cachedGetJson('/api/v1/t1', fetcher);
    const b = await cachedGetJson('/api/v1/t1', fetcher);
    expect(a).toEqual({v: 1});
    expect(b).toEqual({v: 1});      // 命中缓存
    expect(calls).toBe(1);
  });

  it('过期后 SWR：先回旧值，后台刷新', async () => {
    let calls = 0;
    const fetcher = async () => ({v: ++calls});
    await cachedGetJson('/api/v1/t2', fetcher);      // v=1 入缓存
    const now = vi.spyOn(Date, 'now');
    now.mockReturnValue(Date.now() + CACHE_TTL_MS + 1);       // 强制过期
    const stale = await cachedGetJson('/api/v1/t2', fetcher);
    expect(stale).toEqual({v: 1});                    // 立即回旧值
    await new Promise((r) => setTimeout(r, 5));       // 等后台刷新
    expect(calls).toBe(2);
    const fresh = await cachedGetJson('/api/v1/t2', fetcher);
    expect(fresh).toEqual({v: 2});                    // 刷新后的缓存
  });

  it('并发同 URL 共享一次网络请求', async () => {
    let calls = 0;
    const fetcher = () => new Promise<{v: number}>((resolve) => {
      calls += 1;
      setTimeout(() => resolve({v: calls}), 10);
    });
    const [a, b, c] = await Promise.all([
      cachedGetJson('/api/v1/t3', fetcher),
      cachedGetJson('/api/v1/t3', fetcher),
      cachedGetJson('/api/v1/t3', fetcher),
    ]);
    expect(calls).toBe(1);
    expect(a).toEqual(b);
    expect(b).toEqual(c);
  });

  it('clearFetchCache 后重新走网络', async () => {
    let calls = 0;
    const fetcher = async () => ({v: ++calls});
    await cachedGetJson('/api/v1/t4', fetcher);
    clearFetchCache();
    const again = await cachedGetJson('/api/v1/t4', fetcher);
    expect(again).toEqual({v: 2});
    expect(calls).toBe(2);
  });
});
