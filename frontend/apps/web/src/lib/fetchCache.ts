/**
 * GET 请求 SWR-lite 缓存层（2026-10 切菜单闪烁修复）。
 *
 * 背景：路由无 keep-alive，每次切菜单页面重挂载并全量重新 fetch，
 * loading spinner 闪一屏。本层对幂等 GET 做 stale-while-revalidate：
 * 新鲜期内直接回缓存；过期则先回旧值、后台静默刷新；并发同 URL 去重。
 * 页面代码零改动（install 补丁 window.fetch）。
 *
 * 正确性边界（优先于体验）：
 * - 只缓存 GET；
 * - 轮询/实时/含副作用的 GET 按前缀排除（replay 盲盒的 advance 是
 *   mutating GET，market/trade/logs/jobs/system 是轮询语义，
 *   缓存会让轮询看起来冻结）；
 * - 任何非 GET 请求成功（2xx）后整体失效缓存——"保存后刷新列表"
 *   永远读到刚写入的数据，不靠 TTL 赌运气。
 */
import {getApiBase} from './api';

const CACHE_TTL_MS = 20_000;
const MAX_ENTRIES = 300;

/** 不可缓存前缀（匹配 URL 中任意位置出现的 API 段）。 */
const NO_CACHE = [
  '/api/v1/replay', '/api/v1/market', '/api/v1/trade',
  '/api/v1/logs', '/api/v1/jobs', '/api/v1/system',
];

type Entry = { at: number; data: unknown };
const cache = new Map<string, Entry>();
const inflight = new Map<string, Promise<unknown>>();

export function shouldCacheUrl(url: string): boolean {
  if (!url.includes('/api/v1/')) return false;   // 只管自家 API
  return !NO_CACHE.some((p) => url.includes(p));
}

export function clearFetchCache(): void {
  cache.clear();
  inflight.clear();
}

export function cachedGetJson<T>(url: string,
                                 doFetch: () => Promise<T>): Promise<T> {
  const hit = cache.get(url);
  if (hit) {
    if (Date.now() - hit.at < CACHE_TTL_MS) {
      return Promise.resolve(hit.data as T);
    }
    // 过期：先回旧值，后台静默刷新（失败保留旧值）
    doFetch().then((d) => note(url, d)).catch(() => {});
    return Promise.resolve(hit.data as T);
  }
  const pending = inflight.get(url);
  if (pending) return pending as Promise<T>;
  const p = (async () => {
    try {
      const data = await doFetch();
      note(url, data);
      return data;
    } finally {
      inflight.delete(url);
    }
  })();
  inflight.set(url, p);
  return p as Promise<T>;
}

function note(url: string, data: unknown): void {
  cache.set(url, {at: Date.now(), data});
  if (cache.size > MAX_ENTRIES) {
    // FIFO 淘汰最旧条目
    cache.delete(cache.keys().next().value as string);
  }
}

/**
 * 安装 fetch 补丁（幂等，浏览器环境专用）。GET+可缓存 URL 走
 * cachedGetJson，其余原样透传；非 GET 成功后失效全部缓存。
 */
export function installFetchCache(): void {
  if (typeof window === 'undefined'
      || (window as unknown as Record<string, unknown>).__fetchCache) {
    return;
  }
  (window as unknown as Record<string, unknown>).__fetchCache = true;
  const orig = window.fetch.bind(window);
  const apiBase = getApiBase();

  const fakeResponse = (data: unknown): Response => {
    const body = JSON.stringify(data);
    const headers = new Headers({'content-type': 'application/json'});
    return {
      ok: true, status: 200, statusText: 'OK',
      url: '', redirected: false, type: 'basic', bodyUsed: false,
      headers,
      json: async () => JSON.parse(body),
      text: async () => body,
      clone: () => fakeResponse(data),
    } as unknown as Response;
  };

  window.fetch = ((
    input: RequestInfo | URL, init?: RequestInit,
  ): Promise<Response> => {
    const url = typeof input === 'string' ? input
      : input instanceof URL ? input.href : input.url;
    const method = String(
      init?.method
      ?? (typeof input === 'object' && 'method' in input
        ? (input as Request).method : 'GET'),
    ).toUpperCase();
    if (method === 'GET' && shouldCacheUrl(url)) {
      return cachedGetJson(url, async () => {
        const r = await orig(input, init);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()) as unknown;
      }).then((data) => fakeResponse(data));
    }
    return orig(input, init).then((r) => {
      if (method !== 'GET' && r.ok && url.startsWith(apiBase)) {
        clearFetchCache();   // 保存类请求成功 → 下次读必拿新数据
      }
      return r;
    });
  }) as typeof fetch;
}
