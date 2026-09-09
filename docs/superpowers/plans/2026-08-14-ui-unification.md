# UI 统一化实施计划（消灭"四不像"）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把全站 61 页前端从"三套色板+每页重写组件"收敛到 global.css 单一令牌体系 + 共享 UI 组件 + 中文统一导航，零功能/路由/后端变更。

**Architecture:** 自底向上：先补齐设计令牌与涨跌语义色（Task 1-4），再脚本化收敛颜色/排版（Task 5-7），然后建共享组件并重组导航（Task 8-10），最后逐页迁移（Task 11-13）与图表主题统一（Task 14），终验（Task 15）。每任务独立可验证（grep 断言 + build）。

**Tech Stack:** React 18 + 手写 CSS（无 Tailwind）、recharts 2 + echarts 5、rsbuild + rush + pnpm、TypeScript 5。

**Spec:** `docs/superpowers/specs/2026-08-14-ui-unification-design.md`

## Global Constraints

- 工作目录：`/home/yuandonghao/sidejob/sources/trader/ytrader`，前端根 `frontend/apps/web`（下文 `src/` = `frontend/apps/web/src/`）
- 零功能变更、零路由变更、零后端变更
- A股涨跌色：**红涨绿跌**。`--color-up`=#ff453a 系红、`--color-down`=#30d158 系绿，唯一定义点在 `global.css`
- 估值分位（低/中/高）不使用涨跌色，用 `--color-success/--color-warning/--color-danger`
- 禁改以下未提交文件（另一工作流正在修改）：`backend/src/api/handler/financial_detail_handler.py`、`backend/src/domain/market/fundamental/dcf.py`、`frontend/apps/web/src/components/DcfPanel.tsx`、`frontend/apps/web/src/hooks/useDcf.ts`、`backend/tests/domain/test_dcf_monte_carlo.py`。`DcfPanel.css` 可改，`DcfPanel.tsx` 整体跳过迁移
- 提交时必须选择性 `git add <具体文件>`，禁止 `git add -A` / `git add .`
- CSS/TSX 中颜色最终状态：映射表内外来 hex 出现次数为 0；`var(--color-up` / `var(--color-down` 带内联 fallback 的次数为 0
- 图表色一律来自 `src/lib/chartTheme.ts` 常量（ECharts 是 canvas 渲染，不能用 CSS var；recharts 一并统一用常量）
- 构建验证命令：`cd frontend/apps/web && pnpm build`；类型检查：`cd frontend/apps/web && npx tsc --noEmit`（若 tsconfig 报配置性错误而非本次引入，记录并继续，以 build 为准）
- 每个任务完成后必须 commit（中文 conventional commit）

---

### Task 1: 设计令牌补齐（global.css）

**Files:**
- Modify: `src/styles/global.css`（在 `--color-flat` 语义区后、Typography 区前插入）

**Interfaces:**
- Produces: `--color-up/--color-up-light/--color-down/--color-down-light/--color-flat`、`--chart-1..8`、`.is-up/.is-down/.is-flat` 工具类（后续所有任务引用这些名字）

- [ ] **Step 1: 插入涨跌语义色与图表色板令牌**

在 `global.css` 的 `--color-wechat: #07c160;` 行后插入：

```css
  /* Price direction — A股红涨绿跌，全站唯一定义点 */
  --color-up: #ff453a;
  --color-up-light: rgba(255, 69, 58, 0.12);
  --color-down: #30d158;
  --color-down-light: rgba(48, 209, 88, 0.12);
  --color-flat: #a1a1a6;

  /* Chart palette — 供 lib/chartTheme.ts 与内联图表色引用 */
  --chart-1: #0a84ff;
  --chart-2: #30d158;
  --chart-3: #ff9f0a;
  --chart-4: #bf5af2;
  --chart-5: #64d2ff;
  --chart-6: #ff453a;
  --chart-7: #ffd60a;
  --chart-8: #5e5ce6;
```

在文件末尾 Utility classes 区（`.animate-enter` 之后、`@media (prefers-reduced-motion` 之前）插入：

```css
/* ── Price direction utilities — A股红涨绿跌 ── */
.is-up { color: var(--color-up); }
.is-down { color: var(--color-down); }
.is-flat { color: var(--color-flat); }
```

- [ ] **Step 2: 验证**

```bash
cd frontend/apps/web && grep -c 'color-up' src/styles/global.css && pnpm build
```
Expected: grep ≥ 2；build 成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/styles/global.css
git commit -m "feat(ui-unify): 补齐涨跌语义色/图表色板令牌与 .is-up/.is-down 工具类"
```

---

### Task 2: 图表主题模块（chartTheme.ts）

**Files:**
- Create: `src/lib/chartTheme.ts`

**Interfaces:**
- Produces: `CHART_COLORS: string[]`、`colorUp = '#ff453a'`、`colorDown = '#30d158'`、`colorFlat = '#a1a1a6'`、`axisProps`、`tooltipProps`（Task 6/14 消费）

- [ ] **Step 1: 写入完整实现**

```ts
/**
 * 图表主题 — 全站唯一图表色板/样式来源。
 * 值与 styles/global.css 令牌保持同步（canvas 渲染无法使用 CSS var）。
 */
export const CHART_COLORS = [
  '#0a84ff', '#30d158', '#ff9f0a', '#bf5af2',
  '#64d2ff', '#ff453a', '#ffd60a', '#5e5ce6',
] as const;

export const colorUp = '#ff453a';    // A股红涨
export const colorDown = '#30d158';  // A股绿跌
export const colorFlat = '#a1a1a6';

/** recharts XAxis/YAxis 统一属性 */
export const axisProps = {
  tick: {fill: '#a1a1a6', fontSize: 11},
  stroke: 'rgba(255,255,255,0.14)',
  tickLine: false,
} as const;

/** recharts CartesianGrid 统一属性 */
export const gridProps = {
  stroke: 'rgba(255,255,255,0.06)',
  strokeDasharray: '3 3',
  vertical: false,
} as const;

/** recharts Tooltip 统一内容样式 */
export const tooltipProps = {
  contentStyle: {
    background: '#2c2c2e',
    border: '1px solid rgba(255,255,255,0.14)',
    borderRadius: 10,
    fontSize: 12,
    color: '#f5f5f7',
  },
  labelStyle: {color: '#a1a1a6'},
} as const;

/** 按序取系列色（超过 8 个循环） */
export const seriesColor = (i: number): string => CHART_COLORS[i % CHART_COLORS.length];
```

- [ ] **Step 2: 验证**

```bash
cd frontend/apps/web && npx tsc --noEmit 2>&1 | grep -c chartTheme; pnpm build
```
Expected: 0 错误提及 chartTheme；build 成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/lib/chartTheme.ts
git commit -m "feat(ui-unify): 新增全站图表主题模块 chartTheme(色板/坐标轴/tooltip)"
```

---

### Task 3: 修复 34 个未定义 CSS 变量引用

**Files:**
- Modify: `src/**/*.css`（约 30 个文件中的零散引用）

**Interfaces:**
- Consumes: global.css 既有令牌名
- Produces: 无未定义 var() 引用的 CSS 仓

- [ ] **Step 1: 脚本替换错误变量名**

在仓库根运行（幂等，dry-run 先看清单）：

```bash
cd frontend/apps/web/src
python3 - <<'EOF'
import re, pathlib
VAR_MAP = {
  '--text-primary': '--color-text', '--text': '--color-text',
  '--text-secondary': '--color-text-secondary', '--text-muted': '--color-text-tertiary',
  '--surface': '--color-surface', '--surface-active': '--color-surface-hover',
  '--surface-hover': '--color-surface-hover', '--surface-raised': '--color-surface-elevated',
  '--card-bg': '--color-surface', '--hover-bg': '--color-surface-hover',
  '--active-bg': '--color-surface-hover', '--color-bg': '--color-background',
  '--border': '--color-border', '--border-color': '--color-border',
  '--border-subtle': '--color-border', '--color-border-subtle': '--color-border',
  '--color-separator': '--color-border',
  '--accent': '--color-accent', '--primary-color': '--color-accent',
  '--color-primary': '--color-accent', '--color-error': '--color-danger',
  '--color-success-hover': '--color-success',
  '--font-sans': '--font-body', '--font-weight-regular': '--font-weight-normal',
  '--mono-font': '--font-mono',
  '--space-7': '--space-6',
}
pat = re.compile(r'var\((--[\w-]+)')
changed = []
for p in pathlib.Path('.').rglob('*.css'):
    s = p.read_text(); orig = s
    for wrong, right in sorted(VAR_MAP.items(), key=lambda kv: -len(kv[0])):
        s = re.sub(re.escape(wrong) + r'(?=[,\)\s])', right, s)
    if s != orig:
        p.write_text(s); changed.append(str(p))
print('\n'.join(changed) or 'no changes')
EOF
```

注意：`--text-secondary` 键比 `--text` 长，按长度降序替换避免误伤；`--space-7` 归到 `--space-6`（视觉差 4px 可接受）。

- [ ] **Step 2: 移除 var() 的内联 fallback 硬编码（自保写法）**

```bash
cd frontend/apps/web/src
grep -rln 'var(--[a-z-]*, #' --include='*.css' | xargs -r sed -i -E 's/var\((--[a-z0-9-]+),[^)]+\)/var(\1)/g'
grep -rn 'var(--[a-z-]*, rgba' --include='*.css' | head   # 手工逐处同法清理（数量少）
```

- [ ] **Step 3: 验证（断言）**

```bash
cd frontend/apps/web/src && grep -rn 'var(--text[,)]\|var(--surface[,).-]\|var(--accent[,)]\|var(--border[,)]\|var(--font-sans\|var(--space-7\|var(--card-bg\|var(--primary-color\|var(--mono-font' --include='*.css' | wc -l
```
Expected: `0`。若非 0，对残留项按 VAR_MAP 手工替换后重跑。

```bash
cd frontend/apps/web && pnpm build
```
Expected: 成功。

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src
git commit -m "fix(ui-unify): 修复未定义CSS变量引用(34处错误令牌名→正确名, 去除fallback硬编码)"
```

---

### Task 4: 涨跌色语义统一（红涨绿跌）

**Files:**
- Modify: `src/pages/NationalTeam.css`（`.is-up/.is-down` 局部定义删除）
- Modify: `src/pages/SectorScan.tsx:73-78`、`src/pages/Indices.tsx:416-421`（估值分位改 success/warning/danger）
- Modify: 全仓其余"涨跌方向"用色（Step 3 grep 定位）

**Interfaces:**
- Consumes: Task 1 的 `--color-up/--color-down/--color-flat`、`.is-up/.is-down/.is-flat`

- [ ] **Step 1: 删除 NationalTeam.css 局部定义（改用全局）**

删除 `src/pages/NationalTeam.css` 中这两行（约 :39-40）：
```css
.is-up { color: var(--color-up, #e54d4d); }
.is-down { color: var(--color-down, #2eb872); }
```
（全局工具类已定义。同文件内 `#e54d4d/#2eb872/rgba(229,77,77,..)` 等遗留色在 Task 5 一并映射。）

- [ ] **Step 2: 估值分位脱离涨跌色（SectorScan.tsx / Indices.tsx）**

`src/pages/SectorScan.tsx:73-78` 的 `pctColor` 改为：

```ts
const pctColor = (p: number | null) => {
  if (p === null) return 'var(--color-text-tertiary)';
  if (p < 0.2) return 'var(--color-success)';   // 低估 — 机会
  if (p > 0.8) return 'var(--color-danger)';    // 高估 — 风险
  return 'var(--color-warning)';
};
```

`src/pages/Indices.tsx:416-421` 内联 style 的 color 改为同一逻辑：

```ts
color: idxPct[q.symbol]! < 0.2 ? 'var(--color-success)'
  : idxPct[q.symbol]! > 0.8 ? 'var(--color-danger)'
  : 'var(--color-warning)',
```

- [ ] **Step 3: 全仓涨跌语义扫描**

```bash
cd frontend/apps/web/src && grep -rn "is-up\|is-down\|color-up\|color-down" --include='*.tsx' --include='*.css' | grep -v 'styles/global.css'
```
逐处核对：表达**价格变动方向**的必须走 `--color-up/--color-down`（红涨绿跌）或 `.is-up/.is-down` 类；发现"涨=绿"的（典型如 `change > 0 ? 'green'`、`#16a34a` 配 `+` 号）一律翻转为红涨绿跌。已知需翻转的候选同时用：

```bash
grep -rn "#16a34a\|#22c55e\|#dc2626\|#ef4444" --include='*.tsx' src/pages src/components | grep -iv "pct\|percentile\|低估\|高估"
```

- [ ] **Step 4: 验证**

```bash
cd frontend/apps/web/src && grep -rn 'var(--color-up, \|var(--color-down, ' --include='*.css' --include='*.tsx' | wc -l
```
Expected: `0`。

```bash
cd frontend/apps/web && pnpm build
```
Expected: 成功。

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/NationalTeam.css frontend/apps/web/src/pages/SectorScan.tsx frontend/apps/web/src/pages/Indices.tsx
# 加上 Step 3 实际修改的其他文件
git commit -m "fix(ui-unify): 涨跌色全站统一A股红涨绿跌; 估值分位改用success/warning/danger"
```

---

### Task 5: 中性色机械映射（CSS 文件）

**Files:**
- Modify: `src/**/*.css`（除 global.css）

**Interfaces:**
- Consumes: global.css 全部令牌

- [ ] **Step 1: 脚本替换（幂等）**

```bash
cd frontend/apps/web/src
python3 - <<'EOF'
import re, pathlib
# hex → CSS 令牌（映射表来自 spec §4 阶段1；大小写不敏感）
HEX_MAP = {
  '#0d1117': 'var(--color-background)', '#0f1216': 'var(--color-background)',
  '#1a1a1a': 'var(--color-background)',
  '#161b22': 'var(--color-surface)', '#21262d': 'var(--color-surface)',
  '#1e1e2e': 'var(--color-surface)', '#1e2a3a': 'var(--color-surface)',
  '#30363d': 'var(--color-border-strong)',
  '#8b949e': 'var(--color-text-secondary)', '#9ca3af': 'var(--color-text-secondary)',
  '#6b7280': 'var(--color-text-secondary)',
  '#c9d1d9': 'var(--color-text)', '#e6edf3': 'var(--color-text)',
  '#58a6ff': 'var(--color-accent)', '#3b82f6': 'var(--color-accent)',
  '#2563eb': 'var(--color-accent)',
  '#f85149': 'var(--color-danger)', '#ef4444': 'var(--color-danger)',
  '#dc2626': 'var(--color-danger)', '#e54d4d': 'var(--color-danger)',
  '#3fb950': 'var(--color-success)', '#22c55e': 'var(--color-success)',
  '#16a34a': 'var(--color-success)', '#2eb872': 'var(--color-success)',
  '#d29922': 'var(--color-warning)', '#fbbf24': 'var(--color-warning)',
  '#d97706': 'var(--color-warning)', '#ca8a04': 'var(--color-warning)',
  '#64748b': 'var(--color-text-tertiary)',
}
pat = {re.escape(k): v for k, v in HEX_MAP.items()}
regex = re.compile('|'.join(pat.keys()), re.IGNORECASE)
changed = []
for p in pathlib.Path('.').rglob('*.css'):
    if p.name == 'global.css': continue
    s = p.read_text()
    ns = regex.sub(lambda m: pat[m.group(0).lower()], s)
    if ns != s: p.write_text(ns); changed.append(str(p))
print(f'{len(changed)} files changed'); print('\n'.join(changed))
EOF
```

- [ ] **Step 2: 语义抽查（防误伤）**

```bash
cd frontend/apps/web/src && git diff --stat && grep -rn 'var(--color-danger)\|var(--color-success)' --include='*.css' . | grep -i 'up\|change\|gain\|loss\|涨\|跌'
```
逐处确认：命中"涨跌语义"的选择器改用 `var(--color-up)/var(--color-down)`。典型：`.signal-strong`(NationalTeam) 是"强信号"非下跌——保持 danger。

- [ ] **Step 3: 验证（断言）**

```bash
cd frontend/apps/web/src && grep -rniE '#(0d1117|161b22|21262d|30363d|8b949e|c9d1d9|e6edf3|58a6ff|f85149|ef4444|dc2626|e54d4d|3fb950|22c55e|16a34a|2eb872|d29922|fbbf24|d97706|ca8a04|3b82f6|2563eb|64748b|9ca3af|6b7280|1a1a1a|1e1e2e)' --include='*.css' | wc -l
```
Expected: `0`（global.css 除外——脚本已跳过）。

```bash
cd frontend/apps/web && pnpm build
```
Expected: 成功。

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src
git commit -m "refactor(ui-unify): CSS外来色板(GitHub Dark/Tailwind)全量映射至设计令牌"
```

---

### Task 6: 中性色机械映射（TSX 内联）

**Files:**
- Modify: `src/**/*.tsx`（约 30+ 文件；跳过 `components/DcfPanel.tsx`）

**Interfaces:**
- Consumes: 令牌名（DOM inline style 可用 `var()`）、`chartTheme.ts`（图表属性用常量）

- [ ] **Step 1: 先处理图表色（ECharts option / recharts 属性 → chartTheme 常量）**

```bash
cd frontend/apps/web/src && grep -rn "'#58a6ff'\|'#f85149'\|'#3fb950'\|'#8b949e'\|'#0d1117'\|'#161b22'\|'#d29922'" --include='*.tsx' . | cut -d: -f1 | sort -u
```
对每个文件：顶部 `import {CHART_COLORS, colorUp, colorDown, axisProps, tooltipProps, gridProps} from '../lib/chartTheme'`（路径按层级），option 里的色值替换为 `CHART_COLORS[i]`/`colorUp`/`colorDown` 或就近令牌常量。已知重点：`pages/ntLive/LiveTabs.tsx:378,574`（两套色带→`CHART_COLORS` 与单一黄橙刻度 `['#ffd60a','#ff9f0a','#ff453a']`）、`pages/Macro.tsx:178-180,285,291`、`pages/lt-backtest/EfficientFrontier.tsx:34`（POINT_COLORS→直接用 CHART_COLORS）。

- [ ] **Step 2: DOM inline style 色值 → var()（脚本）**

```bash
cd frontend/apps/web/src
python3 - <<'EOF'
import re, pathlib
HEX_MAP = {
  '#8b949e':'var(--color-text-secondary)','#9ca3af':'var(--color-text-secondary)',
  '#6b7280':'var(--color-text-secondary)','#64748b':'var(--color-text-tertiary)',
  '#c9d1d9':'var(--color-text)','#e6edf3':'var(--color-text)','#f5f5f7':'var(--color-text)',
  '#1d1d1f':'var(--color-background)','#0d1117':'var(--color-background)','#1a1a1a':'var(--color-background)',
  '#161b22':'var(--color-surface)','#21262d':'var(--color-surface)','#1e1e2e':'var(--color-surface)','#2c2c2e':'var(--color-surface)',
  '#30363d':'var(--color-border-strong)',
  '#58a6ff':'var(--color-accent)','#3b82f6':'var(--color-accent)','#2563eb':'var(--color-accent)','#0a84ff':'var(--color-accent)',
  '#f85149':'var(--color-danger)','#ef4444':'var(--color-danger)','#dc2626':'var(--color-danger)','#e54d4d':'var(--color-danger)','#ff453a':'var(--color-danger)',
  '#3fb950':'var(--color-success)','#22c55e':'var(--color-success)','#16a34a':'var(--color-success)','#2eb872':'var(--color-success)','#30d158':'var(--color-success)',
  '#d29922':'var(--color-warning)','#fbbf24':'var(--color-warning)','#d97706':'var(--color-warning)','#ca8a04':'var(--color-warning)','#ff9f0a':'var(--color-warning)',
  '#a1a1a6':'var(--color-text-secondary)','#86868b':'var(--color-text-tertiary)',
}
pat = {re.escape(k): v for k, v in HEX_MAP.items()}
regex = re.compile('|'.join(pat.keys()), re.IGNORECASE)
changed = []
for p in pathlib.Path('.').rglob('*.tsx'):
    if p.name == 'DcfPanel.tsx': continue
    s = p.read_text()
    ns = regex.sub(lambda m: pat[m.group(0).lower()], s)
    if ns != s: p.write_text(ns); changed.append(str(p))
print(f'{len(changed)} files'); print('\n'.join(changed))
EOF
```

**脚本后必须人工复查两类误伤**（在 git diff 中逐文件看）：
1. 被 ECharts option 使用的色值变成 `var(...)` —— ECharts 是 canvas，var() 无效！用 `git diff` 定位 echarts option 块，改回 chartTheme 常量。
2. 涨跌语义位置（`change/pct/up/down/涨/跌` 附近）被映射成 success/danger —— 改为 `var(--color-up)/var(--color-down)`。

```bash
cd frontend/apps/web/src && git diff -U2 -- '*.tsx' | grep -B2 -A2 "echarts\|option=" | head -50
```

- [ ] **Step 3: 验证（断言 + build）**

```bash
cd frontend/apps/web/src && grep -rn "'#8b949e'\|'#58a6ff'\|'#f85149'\|'#0d1117'\|'#3b82f6'" --include='*.tsx' | wc -l
```
Expected: `0`（跳过文件 DcfPanel.tsx 除外——如有命中需记录豁免）。

```bash
cd frontend/apps/web && npx tsc --noEmit && pnpm build
```
Expected: 通过。

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src
git commit -m "refactor(ui-unify): TSX内联色全量映射——DOM走var()令牌, 图表走chartTheme常量"
```

---

### Task 7: 排版收敛（字号/圆角/阴影/间距）

**Files:**
- Modify: `src/**/*.css`（除 global.css）

- [ ] **Step 1: 脚本替换**

```bash
cd frontend/apps/web/src
python3 - <<'EOF'
import re, pathlib
FS = {  # font-size px/rem → 令牌
  '9px':'var(--text-xs)','10px':'var(--text-xs)','11px':'var(--text-xs)','0.65rem':'var(--text-xs)',
  '0.68rem':'var(--text-xs)','0.6875rem':'var(--text-xs)','0.7rem':'var(--text-xs)','0.72rem':'var(--text-xs)',
  '12px':'var(--text-xs)','0.75rem':'var(--text-xs)',
  '13px':'var(--text-sm)','0.78rem':'var(--text-sm)','0.8rem':'var(--text-sm)','0.8125rem':'var(--text-sm)','0.875rem':'var(--text-sm)',
  '14px':'var(--text-sm)',
  '15px':'var(--text-base)','0.9rem':'var(--text-base)',
  '16px':'var(--text-base)','1rem':'var(--text-base)',
  '17px':'var(--text-lg)','18px':'var(--text-lg)','1.1rem':'var(--text-lg)','1.125rem':'var(--text-lg)',
  '22px':'var(--text-xl)','1.375rem':'var(--text-xl)','1.25rem':'var(--text-xl)','1.5rem':'var(--text-2xl)',
  '24px':'var(--text-2xl)','28px':'var(--text-2xl)','1.75rem':'var(--text-2xl)',
  '36px':'var(--text-3xl)','40px':'var(--text-3xl)','2rem':'var(--text-2xl)','2.25rem':'var(--text-3xl)',
}
BR = {  # border-radius
  '2px':'var(--radius-sm)','3px':'var(--radius-sm)','4px':'var(--radius-sm)','5px':'var(--radius-sm)','6px':'var(--radius-sm)',
  '7px':'var(--radius-md)','8px':'var(--radius-md)','9px':'var(--radius-md)','10px':'var(--radius-md)','11px':'var(--radius-md)','12px':'var(--radius-md)',
  '13px':'var(--radius-lg)','14px':'var(--radius-lg)','15px':'var(--radius-lg)','16px':'var(--radius-lg)',
  '20px':'var(--radius-xl)','999px':'var(--radius-pill)','100px':'var(--radius-pill)',
}
def sub_props(text, mapping, props):
    out = text
    for prop in props:
        for k, v in mapping.items():
            out = re.sub(rf'({prop}\s*:\s*){re.escape(k)}(?=[;\s/)])', rf'\1{v}', out)
    return out
changed = []
for p in pathlib.Path('.').rglob('*.css'):
    if p.name == 'global.css': continue
    s = p.read_text()
    ns = sub_props(s, FS, ['font-size'])
    ns = sub_props(ns, BR, ['border-radius'])
    # box-shadow 硬编码 → 最近似令牌
    SH = {
      r'box-shadow:\s*0 1px 2px rgba\(0,\s*0,\s*0[^)]*\)':'box-shadow: var(--shadow-sm)',
      r'box-shadow:\s*0 4px (?:12|16)px rgba\(0,\s*0,\s*0[^)]*\)':'box-shadow: var(--shadow-md)',
      r'box-shadow:\s*0 8px 24px rgba\(0,\s*0,\s*0[^)]*\)':'box-shadow: var(--shadow-lg)',
      r'box-shadow:\s*0 (?:16px 48|20px 60)px rgba\(0,\s*0,\s*0[^)]*\)':'box-shadow: var(--shadow-xl)',
    }
    for k, v in SH.items(): ns = re.sub(k, v, ns)
    # 卡片类 padding 硬编码 → space 令牌（仅常见页级值）
    for k, v in {'10px 12px':'var(--space-3) var(--space-4)','12px':'var(--space-3)','14px':'var(--space-4)','14px 16px':'var(--space-4)','16px':'var(--space-4)','16px 0':'var(--space-4) 0','0.75rem 1rem':'var(--space-3) var(--space-4)','1.5rem':'var(--space-6)'}.items():
        ns = re.sub(rf'(padding:\s*){re.escape(k)}(?=;)', rf'\1{v}', ns)
    if ns != s: p.write_text(ns); changed.append(str(p))
print(f'{len(changed)} files'); print('\n'.join(changed))
EOF
```

注意：`border-radius: 50%` 不映射（圆形）；`0`(padding:0) 不动。

- [ ] **Step 2: 人工复查长尾**

```bash
cd frontend/apps/web/src && grep -rn 'font-size:\s*[0-9]' --include='*.css' | grep -v global.css
```
对残留逐个归档到最近令牌（手改）。

- [ ] **Step 3: 验证**

```bash
cd frontend/apps/web/src && grep -rEn 'font-size:\s*(1[0-9]|[0-9])px' --include='*.css' | grep -v global.css | wc -l
```
Expected: `0`。

```bash
cd frontend/apps/web && pnpm build
```
Expected: 成功。

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src
git commit -m "refactor(ui-unify): 字号/圆角/阴影/间距全量收敛至设计令牌"
```

---

### Task 8: 共享 UI 组件（components/ui/）

**Files:**
- Create: `src/components/ui/Button.tsx`、`Card.tsx`、`Tabs.tsx`、`Modal.tsx`、`PageHeader.tsx`、`StateView.tsx`、`ui.css`、`index.ts`

**Interfaces:**
- Produces（Task 11-13 消费，签名如下）:

```ts
Button: React.FC<{variant?: 'primary'|'secondary'|'ghost'|'danger'; size?: 'sm'|'md'; loading?: boolean; onClick?; disabled?; children; className?; title?; type?: 'button'|'submit'}>
Card:   React.FC<{padding?: 'compact'|'normal'; interactive?: boolean; className?; onClick?; children}>
Tabs:   React.FC<{tabs: {key: string; label: React.ReactNode}[]; active: string; onChange: (key: string) => void; className?}>
Modal:  React.FC<{open: boolean; title: string; onClose: () => void; width?: number; children; footer?: React.ReactNode}>
PageHeader: React.FC<{title: string; subtitle?: string; actions?: React.ReactNode}>
StateView: React.FC<{state: 'loading'|'empty'|'error'; text?: string; onRetry?: () => void}>
```

- [ ] **Step 1: 写 ui.css**

```css
/* ── Button ── */
.ui-btn {
  display: inline-flex; align-items: center; gap: var(--space-2);
  font-size: var(--text-sm); font-weight: var(--font-weight-medium);
  border-radius: var(--radius-md); border: 1px solid transparent;
  padding: var(--space-2) var(--space-4); cursor: pointer;
  transition: background var(--transition-normal), border-color var(--transition-normal),
              opacity var(--transition-normal), transform var(--transition-fast);
  white-space: nowrap;
}
.ui-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ui-btn--md { padding: var(--space-2) var(--space-4); }
.ui-btn--sm { padding: var(--space-1) var(--space-3); font-size: var(--text-xs); }
.ui-btn--primary { background: var(--color-accent); color: #fff; }
.ui-btn--primary:hover:not(:disabled) { background: #409cff; }
.ui-btn--secondary { background: var(--color-fill); color: var(--color-text); border-color: var(--color-border); }
.ui-btn--secondary:hover:not(:disabled) { background: var(--color-fill-secondary); border-color: var(--color-border-strong); }
.ui-btn--ghost { background: transparent; color: var(--color-text-secondary); }
.ui-btn--ghost:hover:not(:disabled) { background: var(--color-fill); color: var(--color-text); }
.ui-btn--danger { background: var(--color-danger); color: #fff; }
.ui-btn--danger:hover:not(:disabled) { background: #ff6961; }
.ui-btn__spinner {
  width: 12px; height: 12px; border-radius: 50%;
  border: 2px solid currentColor; border-top-color: transparent;
  animation: ui-spin 0.7s linear infinite;
}
@keyframes ui-spin { to { transform: rotate(360deg); } }

/* ── Card ── */
.ui-card { background: var(--color-surface); border-radius: var(--radius-card);
  border: 1px solid var(--color-border); padding: var(--space-5);
  transition: border-color var(--transition-normal), box-shadow var(--transition-normal); }
.ui-card--compact { padding: var(--space-4); }
.ui-card--interactive { cursor: pointer; }
.ui-card--interactive:hover { border-color: var(--color-accent); box-shadow: var(--shadow-glow-accent); }

/* ── Tabs ── */
.ui-tabs { display: inline-flex; gap: var(--space-1); background: var(--color-fill);
  border-radius: var(--radius-md); padding: var(--space-1); }
.ui-tab { border: none; background: transparent; color: var(--color-text-secondary);
  font-size: var(--text-sm); font-weight: var(--font-weight-medium);
  padding: var(--space-1) var(--space-3); border-radius: var(--radius-sm); cursor: pointer; }
.ui-tab:hover { color: var(--color-text); }
.ui-tab--active { background: var(--color-surface-elevated); color: var(--color-text);
  box-shadow: var(--shadow-sm); }

/* ── Modal ── */
.ui-modal-overlay { position: fixed; inset: 0; background: var(--color-overlay);
  z-index: var(--z-modal); display: flex; align-items: center; justify-content: center;
  animation: fade-in var(--transition-normal); }
.ui-modal { background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-xl);
  width: min(90vw, 480px); max-height: 85vh; display: flex; flex-direction: column;
  animation: scale-in var(--transition-normal); }
.ui-modal__header { display: flex; align-items: center; justify-content: space-between;
  padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--color-border); }
.ui-modal__title { font-size: var(--text-lg); font-weight: var(--font-weight-semibold); }
.ui-modal__close { border: none; background: transparent; color: var(--color-text-secondary);
  font-size: var(--text-lg); cursor: pointer; padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm); }
.ui-modal__close:hover { background: var(--color-fill); color: var(--color-text); }
.ui-modal__body { padding: var(--space-5); overflow-y: auto; }
.ui-modal__footer { padding: var(--space-3) var(--space-5); border-top: 1px solid var(--color-border);
  display: flex; justify-content: flex-end; gap: var(--space-2); }

/* ── PageHeader ── */
.ui-page-header { display: flex; align-items: flex-start; justify-content: space-between;
  gap: var(--space-4); margin-bottom: var(--space-6); flex-wrap: wrap; }
.ui-page-header__title { font-size: var(--text-2xl); font-weight: var(--font-weight-bold);
  letter-spacing: -0.02em; }
.ui-page-header__subtitle { color: var(--color-text-secondary); font-size: var(--text-sm);
  margin-top: var(--space-1); }
.ui-page-header__actions { display: flex; gap: var(--space-2); align-items: center; }

/* ── StateView ── */
.ui-state { display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: var(--space-3); padding: var(--space-12) var(--space-4);
  color: var(--color-text-secondary); font-size: var(--text-sm); text-align: center; }
.ui-state__spinner { width: 22px; height: 22px; border-radius: 50%;
  border: 2px solid var(--color-fill-tertiary); border-top-color: var(--color-accent);
  animation: ui-spin 0.8s linear infinite; }
.ui-state--empty .ui-state__icon { font-size: var(--text-2xl); opacity: 0.4; }
.ui-state--error { color: var(--color-danger); }
```

- [ ] **Step 2: 写六个组件 + index.ts**

`src/components/ui/Button.tsx`：
```tsx
import React from 'react';
import './ui.css';

interface ButtonProps {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md';
  loading?: boolean;
  disabled?: boolean;
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void;
  className?: string;
  title?: string;
  type?: 'button' | 'submit';
  children: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'secondary', size = 'md', loading = false, disabled = false,
  onClick, className = '', title, type = 'button', children,
}) => (
  <button
    type={type}
    className={`ui-btn ui-btn--${variant} ui-btn--${size} ${className}`.trim()}
    onClick={onClick} disabled={disabled || loading} title={title}
  >
    {loading && <span className="ui-btn__spinner" />}
    {children}
  </button>
);
```

`src/components/ui/Card.tsx`：
```tsx
import React from 'react';
import './ui.css';

interface CardProps {
  padding?: 'compact' | 'normal';
  interactive?: boolean;
  className?: string;
  onClick?: () => void;
  children: React.ReactNode;
}

export const Card: React.FC<CardProps> = ({
  padding = 'normal', interactive = false, className = '', onClick, children,
}) => (
  <div
    className={`ui-card ${padding === 'compact' ? 'ui-card--compact' : ''} ${interactive ? 'ui-card--interactive' : ''} ${className}`.trim()}
    onClick={onClick}
  >
    {children}
  </div>
);
```

`src/components/ui/Tabs.tsx`：
```tsx
import React from 'react';
import './ui.css';

export interface TabItem { key: string; label: React.ReactNode; }

interface TabsProps {
  tabs: TabItem[];
  active: string;
  onChange: (key: string) => void;
  className?: string;
}

export const Tabs: React.FC<TabsProps> = ({tabs, active, onChange, className = ''}) => (
  <div className={`ui-tabs ${className}`.trim()} role="tablist">
    {tabs.map(t => (
      <button
        key={t.key} role="tab" aria-selected={t.key === active}
        type="button"
        className={`ui-tab ${t.key === active ? 'ui-tab--active' : ''}`}
        onClick={() => onChange(t.key)}
      >
        {t.label}
      </button>
    ))}
  </div>
);
```

`src/components/ui/Modal.tsx`：
```tsx
import React, {useEffect} from 'react';
import {createPortal} from 'react-dom';
import './ui.css';

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  width?: number;
  footer?: React.ReactNode;
  children: React.ReactNode;
}

export const Modal: React.FC<ModalProps> = ({open, title, onClose, width = 480, footer, children}) => {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div className="ui-modal-overlay" onClick={onClose}>
      <div className="ui-modal" style={{width: `min(90vw, ${width}px)`}} onClick={e => e.stopPropagation()}>
        <div className="ui-modal__header">
          <span className="ui-modal__title">{title}</span>
          <button type="button" className="ui-modal__close" onClick={onClose} aria-label="关闭">✕</button>
        </div>
        <div className="ui-modal__body">{children}</div>
        {footer && <div className="ui-modal__footer">{footer}</div>}
      </div>
    </div>,
    document.body
  );
};
```

`src/components/ui/PageHeader.tsx`：
```tsx
import React from 'react';
import './ui.css';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

export const PageHeader: React.FC<PageHeaderProps> = ({title, subtitle, actions}) => (
  <header className="ui-page-header">
    <div>
      <h1 className="ui-page-header__title">{title}</h1>
      {subtitle && <p className="ui-page-header__subtitle">{subtitle}</p>}
    </div>
    {actions && <div className="ui-page-header__actions">{actions}</div>}
  </header>
);
```

`src/components/ui/StateView.tsx`：
```tsx
import React from 'react';
import {Button} from './Button';
import './ui.css';

interface StateViewProps {
  state: 'loading' | 'empty' | 'error';
  text?: string;
  onRetry?: () => void;
}

const DEFAULT_TEXT = {loading: '加载中…', empty: '暂无数据', error: '加载失败'} as const;

export const StateView: React.FC<StateViewProps> = ({state, text, onRetry}) => (
  <div className={`ui-state ui-state--${state}`}>
    {state === 'loading' && <span className="ui-state__spinner" />}
    {state === 'empty' && <span className="ui-state__icon">◍</span>}
    <span>{text ?? DEFAULT_TEXT[state]}</span>
    {state === 'error' && onRetry && <Button variant="secondary" size="sm" onClick={onRetry}>重试</Button>}
  </div>
);
```

`src/components/ui/index.ts`：
```ts
export {Button} from './Button';
export {Card} from './Card';
export {Tabs} from './Tabs';
export {Modal} from './Modal';
export {PageHeader} from './PageHeader';
export {StateView} from './StateView';
```

- [ ] **Step 3: 验证**

```bash
cd frontend/apps/web && npx tsc --noEmit && pnpm build
```
Expected: 通过（组件尚未被引用，无副作用）。

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/components/ui
git commit -m "feat(ui-unify): 新增共享UI组件 Button/Card/Tabs/Modal/PageHeader/StateView"
```

---

### Task 9: 导航重组（全中文 + AI 工作台可见）

**Files:**
- Modify: `src/components/Layout.tsx:31-82`（navGroups 整体替换）

**Interfaces:**
- Consumes: 现有路由（全部不变）
- Produces: 新 navGroups（6 组全中文）

- [ ] **Step 1: 替换 navGroups 定义**

```tsx
const navGroups: NavGroup[] = [
  {
    title: '总览',
    items: [
      {path: '/dashboard', label: '总览', icon: Icon.dashboard},
      {path: '/market', label: '行情', icon: Icon.market},
      {path: '/indices', label: '指数', icon: Icon.globe},
      {path: '/watchlist', label: '自选股', icon: Icon.star},
    ],
  },
  {
    title: '研究',
    items: [
      {path: '/financial', label: '财务报表', icon: Icon.financial},
      {path: '/screener', label: '选股器', icon: Icon.strategies},
      {path: '/factors', label: '因子', icon: Icon.factors},
      {path: '/macro', label: '宏观政策', icon: Icon.analytics},
      {path: '/national-team', label: '国家队', icon: Icon.analytics},
      {path: '/intel', label: '情报', icon: Icon.intel},
      {path: '/reports', label: '报告', icon: Icon.reports},
      {path: '/celebrities', label: '名人持仓', icon: Icon.reports},
      {path: '/blog', label: '博客', icon: Icon.blog},
    ],
  },
  {
    title: '交易与策略',
    items: [
      {path: '/trading', label: '交易', icon: Icon.trading},
      {path: '/t-trading', label: '做T实验室', icon: Icon.flask},
      {path: '/strategies', label: '策略', icon: Icon.strategies},
      {path: '/portfolio', label: '组合', icon: Icon.portfolio},
      {path: '/backtest', label: '回测', icon: Icon.backtest},
      {path: '/lt-backtest', label: '长期回测', icon: Icon.backtest},
      {path: '/perm-portfolio', label: '永久组合', icon: Icon.portfolio},
    ],
  },
  {
    title: '分析',
    items: [
      {path: '/analytics', label: '分析', icon: Icon.analytics},
      {path: '/risk', label: '风险', icon: Icon.risk},
      {path: '/alerts', label: '预警', icon: Icon.alerts},
    ],
  },
  {
    title: 'AI 工作台',
    items: [
      {path: '/ai-workspace/trader', label: 'AI交易助手', icon: Icon.intel},
      {path: '/ai-workspace/writer', label: '写作助手', icon: Icon.blog},
      {path: '/ai-workspace/llm-logs', label: 'LLM日志', icon: Icon.terminal},
      {path: '/ai-workspace/settings', label: '工作台设置', icon: Icon.settings},
    ],
  },
  {
    title: '系统',
    items: [
      {path: '/settings', label: '设置', icon: Icon.settings},
      {path: '/system-logs', label: '系统日志', icon: Icon.terminal},
    ],
  },
];
```

- [ ] **Step 2: 验证**

```bash
cd frontend/apps/web && npx tsc --noEmit && pnpm build
```
Expected: 通过；原 navGroups 中出现的每个 path 都仍在新定义中（对照 `grep -o "path: '[^']*'" src/components/Layout.tsx | sort -u` 两次输出一致）。

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/components/Layout.tsx
git commit -m "feat(ui-unify): 侧边栏重组——全中文分组+AI工作台入口可见化"
```

---

### Task 10: 文案/加载态/主题开关统一

**Files:**
- Modify: `src/App.tsx`（4 处 Suspense fallback 文案统一）
- Modify: `src/pages/Settings.tsx`（隐藏亮/暗切换块）

- [ ] **Step 1: App.tsx 统一 fallback**

将 `App.tsx` 中 4 个 Suspense fallback（`加载中…`/`加载写作助手…`/`加载日志…`/`加载设置…`）统一改为 `<div className="page-loading">加载中…</div>`（`page-loading` 类已在各页 CSS 定义；若该类仅在页面级 CSS 中，则同时把 `.page-loading` 定义移入 global.css）。

- [ ] **Step 2: Settings 隐藏主题切换**

定位 `Settings.tsx` 中含 `toggleTheme`/`theme.isDark` 的渲染块（约 :1511-1521），整块注释删除并留一行：
```tsx
// 亮色主题待令牌体系全量落地后开放（见 docs/superpowers/specs/2026-08-14-ui-unification-design.md §6）
```
若删除后 `toggleTheme`/`isDark` 成为未使用变量，一并从解构中移除（保留 `useTheme` import 若仍被 `applyTheme` 使用）。

- [ ] **Step 3: 验证**

```bash
cd frontend/apps/web && npx tsc --noEmit && pnpm build && grep -c "page-loading" src/App.tsx
```
Expected: 通过；grep = 4。

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/App.tsx frontend/apps/web/src/pages/Settings.tsx frontend/apps/web/src/styles/global.css
git commit -m "feat(ui-unify): 加载态文案统一+隐藏未完成的亮色主题开关"
```

---

### Task 11-13: 页面迁移（三批次）

**统一迁移配方**（每页依次执行；以批次内每页为 checklist 行）：

1. **标题**：页面主标题（`xxx__title` 或裸 h1/h2）→ `<PageHeader title="中文名" subtitle={…} actions={…}>`，标题文字中文、去 emoji；CSS 中对应 `.xxx__title` 删除
2. **按钮**：页面自造按钮类（`grep -n "className=.*btn" 页面.tsx`）→ `<Button variant/size>`；页面 CSS 对应类删除
3. **Loading/空态/错误**：`加载中|暂无|加载失败|loading|empty` 的 JSX 块 → `<StateView state={...} text={...} onRetry={...}>`；页面 CSS 对应类删除
4. **Modal**：自制 overlay+box → `<Modal open title onClose footer>`
5. **Tabs**：自制 tab 按钮 → `<Tabs tabs active onChange>`
6. **emoji 清除**：`grep -nP '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]' 页面.tsx` 命中处删 emoji 保留文字
7. **数字列**：涨跌幅/金额单元格 className 追加 `num`（如 `is-up` → `num is-up`）
8. 验证：`cd frontend/apps/web && npx tsc --noEmit && pnpm build`
9. Commit：`git add <该页 tsx+css>` + `git commit -m "refactor(ui-unify): <页面>迁移至共享组件"`

> 注意：不重命名页面根类名、不重构页面布局逻辑；只替换上述 7 类目标。若某页无某类目标则跳过该步。`DcfPanel.tsx` 跳过。

### Task 11: 批次A — 高频页

**页面清单（每页一行 checklist）：**
- [ ] `pages/Dashboard.tsx` + `Dashboard.css`
- [ ] `pages/Market.tsx` + `Market.css`（含 `components/MarketPage/*` 的按钮/loading）
- [ ] `pages/Indices.tsx` + `Indices.css`
- [ ] `pages/Watchlist.tsx` + `Watchlist.css`
- [ ] `pages/NationalTeam.tsx` + `NationalTeam.css`
- [ ] `pages/Macro.tsx` + `Macro.css`
- [ ] `pages/Financial.tsx` + `Financial.css`
- [ ] 批末验证：`pnpm build` 通过后统一提交（或每页一 commit）

**Dashboard 完整示例**（其余页照此模式）：

迁移前（典型片段，实际以文件为准）：
```tsx
<h2 className="dashboard__title">📊 市场总览</h2>
...
{loading ? <div className="dashboard-loading">加载中…</div> : ...}
<button className="dashboard-refresh-btn" onClick={refresh}>🔄 刷新</button>
```
迁移后：
```tsx
import {PageHeader, Button, StateView} from '../components/ui';
...
<PageHeader
  title="市场总览"
  subtitle="全市场核心指标一览"
  actions={<Button variant="secondary" size="sm" onClick={refresh}>刷新</Button>}
/>
...
{loading ? <StateView state="loading" /> : ...}
```
并删除 `Dashboard.css` 中 `.dashboard__title`、`.dashboard-loading`、`.dashboard-refresh-btn` 定义。

- [ ] 批末 Commit（若未逐页提交）：
```bash
git add frontend/apps/web/src/pages frontend/apps/web/src/components/MarketPage
git commit -m "refactor(ui-unify): 批次A高频页迁移至共享组件(PageHeader/Button/StateView)"
```

### Task 12: 批次B — 交易与策略族

- [ ] `pages/Trading.tsx` + `Trading.css`
- [ ] `pages/TTrading.tsx` + `TTrading.css`
- [ ] `pages/Strategies.tsx` + `Strategies.css`
- [ ] `pages/Portfolio.tsx` + `Portfolio.css`
- [ ] `pages/Backtest.tsx` + `Backtest.css`
- [ ] `pages/LongTermBacktest.tsx` + `LongTermBacktest.css` + `lt-backtest/` 子组件
- [ ] `pages/PermPortfolio.tsx` + `PermPortfolio.css`
- [ ] `pages/Alerts.tsx` + `Alerts.css`
- [ ] 批末验证 + Commit：`refactor(ui-unify): 批次B交易策略页迁移至共享组件`

### Task 13: 批次C — 分析/研究/AI族

- [ ] `pages/Analytics.tsx` + `Analytics.css`
- [ ] `pages/Risk.tsx` + `Risk.css`
- [ ] `pages/Factors.tsx` + `Factors.css`
- [ ] `pages/Intel.tsx` + `Intel.css`
- [ ] `pages/Reports.tsx` + `Reports.css`
- [ ] `pages/Celebrity.tsx` + `Celebrity.css`
- [ ] `pages/BlogDraft.tsx` + `BlogDraft.css`
- [ ] `pages/Screener.tsx` + `Screener.css` + `components/ScreenerDrillModal.*`（Modal 迁移重点）
- [ ] `pages/Subscriptions.tsx`/`SubscriptionResults.tsx`（Modal 迁移重点）
- [ ] `pages/AIChat.tsx` + `AIChat.css`
- [ ] `pages/FundFlow.tsx`、`pages/SectorScan.tsx`、`pages/Valuation.tsx`（无独立 CSS 的查引用方式）
- [ ] `pages/blog/*` 与 `pages/ai-workspace/*`（仅做配方 1/3/6 步，按钮体系保持 blog-btn 若体量大——记录豁免）
- [ ] 批末验证 + Commit：`refactor(ui-unify): 批次C分析研究AI页迁移至共享组件`

---

### Task 14: 图表主题统一（recharts/echarts 全量）

**Files:**
- Modify: 全部 import recharts / echarts 的 tsx（`grep -rln "from 'recharts'\|from 'echarts" src`）

- [ ] **Step 1: recharts 页面接入 chartTheme**

每个文件的 `<XAxis {...}/><YAxis {...}/>` 展开 `axisProps`，`<CartesianGrid>` 展开 `gridProps`，`<Tooltip>` 展开 `tooltipProps`（原有 contentStyle 覆盖项在其后展开保留），系列 `stroke/fill` 硬编码 → `seriesColor(i)` / `colorUp` / `colorDown`（涨跌线用语义色）。

- [ ] **Step 2: echarts 页面接入**

`pages/ntLive/EChart.tsx`（封装层）注册统一 option 合并：`color: CHART_COLORS`；LiveTabs 两套热力图色带统一为 `['#ffd60a','#ff9f0a','#ff453a']`（低→高）。

- [ ] **Step 3: 验证**

```bash
cd frontend/apps/web/src && grep -rn "stroke=\"#\|fill=\"#" --include='*.tsx' | grep -v chartTheme | wc -l
```
Expected: ≤ 10（确属特殊的逐处注释豁免）。

```bash
cd frontend/apps/web && npx tsc --noEmit && pnpm build
```

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src
git commit -m "refactor(ui-unify): 图表全量接入chartTheme统一色板与轴/网格/tooltip样式"
```

---

### Task 15: 终验

- [ ] **Step 1: 静态断言全跑**

```bash
cd frontend/apps/web/src
echo "外来hex(CSS): $(grep -rniE '#(0d1117|161b22|21262d|30363d|8b949e|c9d1d9|e6edf3|58a6ff|f85149|ef4444|dc2626|e54d4d|3fb950|22c55e|16a34a|2eb872|d29922|fbbf24|d97706|ca8a04|3b82f6|2563eb|64748b|9ca3af|6b7280)' --include='*.css' | grep -v global.css | wc -l)（期望0）"
echo "up/down带fallback: $(grep -rn 'var(--color-up, \|var(--color-down, ' | wc -l)（期望0）"
echo "页面主标题emoji: $(grep -nP '[\x{1F300}-\x{1FAFF}]' --include='*.tsx' pages components | wc -l)（期望0，icons.tsx等豁免除外）"
```

- [ ] **Step 2: build + 路由可达性**

```bash
cd frontend/apps/web && npx tsc --noEmit; pnpm build
```
对照 `src/App.tsx` 路由表逐条确认新导航能到达（AI 工作台 4 条、隐藏路由 `/ai-chat` 重定向仍有效）。

- [ ] **Step 3: 浏览器视觉抽查**

`cd frontend/apps/web && pnpm dev`（后台），用 browser-use 打开：侧边栏（分组全中文、AI 工作台可见）、`/dashboard`、`/indices`、`/national-team`、`/sector-scan`（若经 Market 可达）、`/settings`（无主题开关）、`/ai-workspace/trader`。核对：涨跌色全站红涨绿跌一致、无花屏、console 无新报错。截图留档 `docs/temp/ui-unify-screenshots/`。

- [ ] **Step 4: 收尾提交**

```bash
git add docs/temp/ui-unify-screenshots 2>/dev/null; git commit -m "chore(ui-unify): 终验截图留档" --allow-empty
```

---

## Self-Review 记录

- **Spec 覆盖**：spec §4 阶段0→Task 1-3；阶段1→Task 4-6；阶段2→Task 7；阶段3→Task 8+11-13；阶段4→Task 9-10；阶段5→Task 14；阶段6→Task 15。§5 风险（DCF 豁免、选择性 add）入 Global Constraints。§6 不做项与约束一致。
- **占位符**：批次任务以"配方+完整示例+页面 checklist"形式给出，无 TBD；Task 8 中曾出现的 index.ts 笔误已在正文更正。
- **类型一致**：ui 组件签名在 Task 8 Interfaces 与 Task 11 示例引用一致（`PageHeader/Button/StateView` props 同名）。
