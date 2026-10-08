import {readFileSync} from 'node:fs';
import {describe, expect, it} from 'vitest';
import {navGroups} from '../navigation';

/** 从 App.tsx 源码提取 <Route path="..."> 清单(App.tsx 中 path 均为双引号字面量) */
function extractRoutePaths(): string[] {
  const source = readFileSync(new URL('../../App.tsx', import.meta.url), 'utf-8');
  const matches = [...source.matchAll(/<Route\s+path="([^"]+)"/g)];
  return matches.map((m) => m[1]);
}

/** 提取重定向路由(path 后紧跟 element={<Navigate) */
function extractNavigatePaths(): string[] {
  const source = readFileSync(new URL('../../App.tsx', import.meta.url), 'utf-8');
  return [...source.matchAll(/<Route\s+path="([^"]+)"\s+element=\{<Navigate/g)].map(
    (m) => m[1]
  );
}

/** 重定向路由(Navigate,无页面)与菜单无关,显式豁免 */
const REDIRECT_PATHS = ['/', '/ai-chat', '/t-trading', '/agent-config'];

const menuPaths = navGroups.flatMap((g) => g.items.map((i) => i.path));
const routePaths = extractRoutePaths();

describe('菜单 ↔ 路由双向校验', () => {
  it('护栏:从 App.tsx 提取到足够多路由(正则失配时此处先红)', () => {
    expect(routePaths.length).toBeGreaterThanOrEqual(27);
  });

  it('每个菜单项都有对应路由(无死链)', () => {
    const missing = menuPaths.filter((p) => !routePaths.includes(p));
    expect(missing).toEqual([]);
  });

  it('每条页面路由都有菜单入口或显式豁免(无幽灵页面)', () => {
    const orphans = routePaths.filter(
      (p) => !menuPaths.includes(p) && !REDIRECT_PATHS.includes(p)
    );
    expect(orphans).toEqual([]);
  });

  it('豁免清单与 App.tsx 重定向路由精确一致(防豁免腐化)', () => {
    expect([...extractNavigatePaths()].sort()).toEqual([...REDIRECT_PATHS].sort());
  });
});
