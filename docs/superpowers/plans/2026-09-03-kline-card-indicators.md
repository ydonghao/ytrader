# 看板 K 线卡技术指标(MACD/RSI/BOLL)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 看板 K 线卡支持 MACD/RSI 独立副图 + BOLL 叠加主图,⋯菜单勾选开关、参数弹窗可调,随布局自动保存。

**Architecture:** 指标纯前端计算(新纯函数模块,算法逐条对齐后端 `strategy/indicators.py`);KlineCard 用 lightweight-charts 5.2 多窗格渲染,序列随 config 增删、图表实例常驻;配置存进卡片 config,经 `normalizeLayout` 规范化、防抖 PUT 持久化。

**Tech Stack:** React 18 + TypeScript + lightweight-charts 5.2.0(已有);rsbuild dev server(12000,代理 /api→12100);验证用 node 22 type-stripping + headless Chrome CDP(项目无 jest/vitest)。

**设计文档:** `docs/superpowers/specs/2026-09-03-kline-card-indicators-design.md`

## Global Constraints

- 前端根:`frontend/apps/web/`;后端零改动。
- 涨跌色必须用 `lib/chartTheme.ts` 常量:`colorUp = '#ff453a'`(红涨)、`colorDown = '#30d158'`(绿跌)。
- 指标配色(设计文档锁定):BOLL `#22d3ee`、MACD dif `#f59e0b`、MACD dea `#0a84ff`、RSI `#ec4899`。
- 指标算法必须与后端一致:EMA 用 SMA 种子;MACD 的 DEA = EMA(DIF 序列 None→0 填充, signal);RSI Wilder 平滑;BOLL 样本标准差(n-1 分母)。
- 默认参数:MACD 12/26/9,RSI 14,BOLL 20/2;钳制范围:整数参数 2–250,stdDev 0.5–5,fast<slow 否则回默认。
- 预热:fetch start 前扩 `WARMUP_CALENDAR_DAYS = 200` 自然日(仅 range.start 非空时);展示切片回 `trade_date >= range.start`。
- 旧卡片兼容:config 缺失 → 指标全关、默认参数。
- 每任务一 commit,消息格式沿用仓库惯例 `feat(board-web): …`。
- 工作区有大量他人未提交改动(backend/frontend 多文件):**只 `git add` 本计划明确列出的文件**,绝不 `git add -A`。

---

### Task 1: 指标纯函数模块 + 与后端数值互验

**Files:**
- Create: `frontend/apps/web/src/pages/Board/indicators.ts`

**Interfaces:**
- Consumes: 无(零依赖纯函数)
- Produces(后续任务依赖的精确签名):
  - `type Series = (number | null)[]`
  - `ema(values: number[], period: number): Series`
  - `interface MacdResult { dif: Series; dea: Series; hist: Series }`
  - `macd(values: number[], fast: number, slow: number, signal: number): MacdResult`
  - `rsiWilder(values: number[], period: number): Series`
  - `interface BollResult { upper: Series; mid: Series; lower: Series }`
  - `boll(values: number[], period: number, stdDev: number): BollResult`

- [ ] **Step 1: 写 indicators.ts(完整代码)**

```ts
/**
 * 看板技术指标纯函数 — 算法与后端 strategy/indicators.py 逐条对齐:
 * EMA 用 SMA 种子;MACD 的 DEA 对 DIF 序列 None→0 填充后做 EMA;
 * RSI 用 Wilder 平滑;BOLL 用样本标准差(n-1 分母)。
 * 输入序列按时间升序;输出与输入等长,不足周期位为 null。
 */
export type Series = (number | null)[];

export function ema(values: number[], period: number): Series {
  const n = values.length;
  const result: Series = new Array(n).fill(null);
  if (period < 1 || n < period) return result;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  result[period - 1] = sum / period;
  const k = 2 / (period + 1);
  for (let i = period; i < n; i++) {
    result[i] = (values[i] - (result[i - 1] as number)) * k + (result[i - 1] as number);
  }
  return result;
}

export interface MacdResult { dif: Series; dea: Series; hist: Series }

export function macd(values: number[], fast: number, slow: number, signal: number): MacdResult {
  const n = values.length;
  const fastE = ema(values, fast);
  const slowE = ema(values, slow);
  const dif: Series = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (fastE[i] != null && slowE[i] != null) dif[i] = (fastE[i] as number) - (slowE[i] as number);
  }
  // 对齐后端:DEA = EMA(DIF 的 None→0 填充序列, signal)
  const dea = ema(dif.map((x) => x ?? 0), signal);
  const hist: Series = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (dif[i] != null && dea[i] != null) hist[i] = (dif[i] as number) - (dea[i] as number);
  }
  return {dif, dea, hist};
}

export function rsiWilder(values: number[], period: number): Series {
  const n = values.length;
  const result: Series = new Array(n).fill(null);
  if (period < 2 || n < period + 1) return result;
  const gains: number[] = [];
  const losses: number[] = [];
  for (let i = 1; i < n; i++) {
    const diff = values[i] - values[i - 1];
    gains.push(Math.max(diff, 0));
    losses.push(Math.max(-diff, 0));
  }
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 0; i < period; i++) { avgGain += gains[i]; avgLoss += losses[i]; }
  avgGain /= period;
  avgLoss /= period;
  const rsiOf = (g: number, l: number) => (l === 0 ? 100 : 100 - 100 / (1 + g / l));
  result[period] = rsiOf(avgGain, avgLoss);
  for (let i = period; i < gains.length; i++) {
    avgGain = (avgGain * (period - 1) + gains[i]) / period;
    avgLoss = (avgLoss * (period - 1) + losses[i]) / period;
    result[i + 1] = rsiOf(avgGain, avgLoss);
  }
  return result;
}

export interface BollResult { upper: Series; mid: Series; lower: Series }

export function boll(values: number[], period: number, stdDev: number): BollResult {
  const n = values.length;
  const mid: Series = new Array(n).fill(null);
  const upper: Series = new Array(n).fill(null);
  const lower: Series = new Array(n).fill(null);
  if (period < 2 || n < period) return {upper, mid, lower};
  for (let i = period - 1; i < n; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += values[j];
    const m = sum / period;
    let sq = 0;
    for (let j = i - period + 1; j <= i; j++) sq += (values[j] - m) ** 2;
    // 样本标准差(n-1 分母),对齐后端 statistics.stdev
    const sd = Math.sqrt(sq / (period - 1));
    mid[i] = m;
    upper[i] = m + stdDev * sd;
    lower[i] = m - stdDev * sd;
  }
  return {upper, mid, lower};
}
```

- [ ] **Step 2: 写后端基准数据生成脚本(python,生成含平台期/单边段的随机游走)**

写 `/tmp/gen_indicator_fixture.py`:

```python
"""生成指标互验基准:随机游走 600 点(含平台期/单边段),输出 JSON。"""
import json
import random
import sys

sys.path.insert(0, 'src')
from domain.market.strategy.indicators import macd, rsi, bollinger_bands

random.seed(42)
values = []
price = 100.0
for i in range(600):
    if 100 <= i < 180:      # 平台期
        price += random.uniform(-0.05, 0.05)
    elif 300 <= i < 450:    # 单边上行
        price += abs(random.gauss(0.8, 0.4))
    else:
        price += random.gauss(0, 1.0)
    values.append(round(price, 4))

dif, dea, hist = macd(values, 12, 26, 9)
rsi14 = rsi(values, 14)
upper, mid, lower = bollinger_bands(values, 20, 2.0)

out = {
    "values": values,
    "py": {
        "macd": {"dif": dif, "dea": dea, "hist": hist},
        "rsi14": rsi14,
        "boll": {"upper": upper, "mid": mid, "lower": lower},
    },
}
with open('/tmp/indicator_fixture.json', 'w') as f:
    json.dump(out, f)
print('fixture written: 600 points')
```

Run(在 `backend/` 目录,用项目 venv):

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && cp /tmp/gen_indicator_fixture.py ./gen_tmp.py && .venv/bin/python3 gen_tmp.py && rm gen_tmp.py
```

Expected: `fixture written: 600 points`

- [ ] **Step 3: 写 node 对比脚本并运行(允许失败一次:确认能捕获差异)**

写 `/tmp/check_indicators.mjs`:

```js
/** 前端 indicators.ts vs 后端 python 逐位比对,max|Δ|<1e-9 才算通过。 */
import {readFileSync} from 'node:fs';
import {macd, rsiWilder, boll} from '/home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web/src/pages/Board/indicators.ts';

const fx = JSON.parse(readFileSync('/tmp/indicator_fixture.json', 'utf8'));
const py = fx.py;
const maxAbs = (a, b) => {
  let m = 0;
  for (let i = 0; i < a.length; i++) {
    const x = a[i], y = b[i];
    if (x == null && y == null) continue;
    if (x == null || y == null) { console.log(`MISMATCH null at ${i}: ts=${x} py=${y}`); m = Infinity; continue; }
    m = Math.max(m, Math.abs(x - y));
  }
  return m;
};

const jsMacd = macd(fx.values, 12, 26, 9);
const jsRsi = rsiWilder(fx.values, 14);
const jsBoll = boll(fx.values, 20, 2.0);

const rows = [
  ['macd.dif', jsMacd.dif, py.macd.dif],
  ['macd.dea', jsMacd.dea, py.macd.dea],
  ['macd.hist', jsMacd.hist, py.macd.hist],
  ['rsi14', jsRsi, py.rsi14],
  ['boll.upper', jsBoll.upper, py.boll.upper],
  ['boll.mid', jsBoll.mid, py.boll.mid],
  ['boll.lower', jsBoll.lower, py.boll.lower],
];
let ok = true;
for (const [name, a, b] of rows) {
  const d = maxAbs(a, b);
  console.log(`${name}: max|Δ|=${d < 1e-9 ? d.toExponential(2) : d}`);
  if (!(d < 1e-9)) ok = false;
}
console.log(ok ? 'ALL MATCH (<1e-9)' : 'FAILED');
process.exit(ok ? 0 : 1);
```

Run:

```bash
node --experimental-strip-types /tmp/check_indicators.mjs
```

Expected: 每行 `max|Δ|=` 极小值,末行 `ALL MATCH (<1e-9)`,exit 0。
(说明:node 22.22 支持类型剥离;若报 erasable 语法错,检查文件是否含 enum/namespace——实现里不应有。)

- [ ] **Step 4: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add frontend/apps/web/src/pages/Board/indicators.ts
git commit -m "feat(board-web): 指标纯函数模块——EMA/MACD/RSI/BOLL对齐后端算法,数值互验<1e-9"
```

---

### Task 2: config 数据模型 + normalizeLayout 不再清空 kline config

**Files:**
- Modify: `frontend/apps/web/src/pages/Board/boardTypes.ts`(KlineCardData 定义约 34-38 行、normalizeLayout kline 分支约 250 行)
- Modify: `frontend/apps/web/src/pages/Board/AddCardModal.tsx`(kline 建卡 config,约 71 行)

**Interfaces:**
- Consumes: 无
- Produces(Task 3/4 依赖):
  - `interface KlineIndicatorConfig { indicators: { macd: boolean; rsi: boolean; boll: boolean }; params: { macd: { fast: number; slow: number; signal: number }; rsi: { period: number }; boll: { period: number; stdDev: number } } }`
  - `defaultKlineConfig(): KlineIndicatorConfig`(工厂函数,防共享引用被误改)
  - `normalizeKlineConfig(raw: unknown): KlineIndicatorConfig`
  - `KlineCardData['config']` 类型从 `Record<string, unknown>` 变为 `KlineIndicatorConfig`

- [ ] **Step 1: boardTypes.ts — 类型+工厂+规范化函数**

在 `boardTypes.ts` 的 `KlineCardData` 定义**之前**插入:

```ts
/** K线卡技术指标配置(⋯菜单勾选+参数弹窗写入,随布局自动保存) */
export interface KlineIndicatorConfig {
  indicators: { macd: boolean; rsi: boolean; boll: boolean };
  params: {
    macd: { fast: number; slow: number; signal: number };
    rsi: { period: number };
    boll: { period: number; stdDev: number };
  };
}

/** 工厂函数(非共享常量,防调用方就地修改污染默认值) */
export function defaultKlineConfig(): KlineIndicatorConfig {
  return {
    indicators: {macd: false, rsi: false, boll: false},
    params: {
      macd: {fast: 12, slow: 26, signal: 9},
      rsi: {period: 14},
      boll: {period: 20, stdDev: 2},
    },
  };
}

const clampInt = (v: unknown, dflt: number): number => {
  const n = Number(v);
  return Number.isInteger(n) && n >= 2 && n <= 250 ? n : dflt;
};

/** GET 回来的 kline config 兜底:非法/缺字段回默认 */
export function normalizeKlineConfig(raw: unknown): KlineIndicatorConfig {
  const o = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const obj = (v: unknown): Record<string, unknown> =>
    v && typeof v === 'object' ? (v as Record<string, unknown>) : {};
  const ind = obj(o.indicators);
  const prm = obj(o.params);
  const macdP = obj(prm.macd);
  const rsiP = obj(prm.rsi);
  const bollP = obj(prm.boll);
  const d = defaultKlineConfig();
  let fast = clampInt(macdP.fast, d.params.macd.fast);
  let slow = clampInt(macdP.slow, d.params.macd.slow);
  if (fast >= slow) { fast = d.params.macd.fast; slow = d.params.macd.slow; }
  const sd = Number(bollP.stdDev);
  return {
    indicators: {
      macd: ind.macd === true,
      rsi: ind.rsi === true,
      boll: ind.boll === true,
    },
    params: {
      macd: {fast, slow, signal: clampInt(macdP.signal, d.params.macd.signal)},
      rsi: {period: clampInt(rsiP.period, d.params.rsi.period)},
      boll: {
        period: clampInt(bollP.period, d.params.boll.period),
        stdDev: isFinite(sd) && sd >= 0.5 && sd <= 5 ? sd : d.params.boll.stdDev,
      },
    },
  };
}
```

`KlineCardData` 改为:

```ts
export interface KlineCardData extends CardBase {
  type: 'kline';
  symbol: string;
  config: KlineIndicatorConfig;
}
```

- [ ] **Step 2: normalizeLayout kline 分支修复(不再 config:{})**

`boardTypes.ts` normalizeLayout 内 kline 分支:

```ts
} else if (type === 'kline') {
  cards.push({
    ...base,
    type,
    symbol: typeof o.symbol === 'string' ? o.symbol : '',
    config: normalizeKlineConfig(o.config),
  });
}
```

- [ ] **Step 3: AddCardModal 建卡用工厂**

`AddCardModal.tsx` kline 分支:

```ts
if (type === 'kline') {
  card = {...base, type, title: pick!.name, symbol: pick!.symbol, config: defaultKlineConfig()};
}
```

同时在文件顶部 import 块的 `uuid,` 之后加 `defaultKlineConfig,`。

- [ ] **Step 4: 编译冒烟**

```bash
sleep 2 && curl -s "http://127.0.0.1:12000/static/js/async/src_pages_Board_index_tsx.js" | grep -c "normalizeKlineConfig"
```

Expected: ≥1(dev server 热编译无报错;若 0,查 rsbuild 进程输出)。浏览器无报错可跳过——本任务无 UI 变化。

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/Board/boardTypes.ts frontend/apps/web/src/pages/Board/AddCardModal.tsx
git commit -m "feat(board-web): kline卡片config类型化+normalizeKlineConfig兜底,修复normalizeLayout清空config"
```

---

### Task 3: ⋯菜单勾选 + 指标参数弹窗(config 写链路)

**Files:**
- Modify: `frontend/apps/web/src/pages/Board/BoardCardShell.tsx`(props 约 17-28 行、菜单列表约 163-166 行后)
- Modify: `frontend/apps/web/src/pages/Board/BoardCanvas.tsx`(props 转发)
- Create: `frontend/apps/web/src/pages/Board/KlineIndicatorMenu.tsx`
- Modify: `frontend/apps/web/src/pages/Board/index.tsx`(接线)
- Modify: `frontend/apps/web/src/pages/Board/Board.css`(样式追加)

**Interfaces:**
- Consumes: `KlineIndicatorConfig`、`defaultKlineConfig`、`normalizeKlineConfig`(Task 2);`updateCard`、`Modal`、`Button`(现有)
- Produces(Task 4/5 依赖):
  - `BoardCardShellProps.menuExtras?: (close: () => void) => React.ReactNode`
  - `BoardCanvasProps.renderMenuExtras?: (card: BoardCard, close: () => void) => React.ReactNode`
  - `KlineIndicatorMenuItems: React.FC<{card: KlineCardData; onToggle: (k: 'macd'|'rsi'|'boll') => void; onOpenParams: () => void}>`
  - `KlineIndicatorParamsModal: React.FC<{open: boolean; config: KlineIndicatorConfig; onClose: () => void; onSave: (c: KlineIndicatorConfig) => void}>`

- [ ] **Step 1: BoardCardShell 加 menuExtras 插槽**

props 接口加一行:

```ts
  onRefresh?: () => void;
  menuExtras?: (close: () => void) => React.ReactNode;
  children: React.ReactNode;
```

组件参数解构加 `menuExtras`(放在 `onRefresh` 之后)。「复制卡片」按钮(约 163-166 行)之后插入:

```tsx
              {menuExtras && (
                <>
                  <div className="board-card__menu-sep" />
                  {menuExtras(() => setMenuOpen(false))}
                </>
              )}
```

- [ ] **Step 2: BoardCanvas 透传**

`BoardCanvasProps` 加:

```ts
  renderMenuExtras?: (card: BoardCard, close: () => void) => React.ReactNode;
```

`<BoardCardShell …>` 调用加:

```tsx
            menuExtras={renderMenuExtras && ((close) => renderMenuExtras(card, close))}
```

- [ ] **Step 3: 写 KlineIndicatorMenu.tsx(完整文件)**

```tsx
/**
 * K线卡技术指标菜单区 — 勾选行写 config 即时生效;"指标参数…"由 index.tsx
 * 持有弹窗状态(弹窗 portal 在 body,若挂菜单内会被菜单外点关闭连带卸载)。
 */
import React, {useState} from 'react';
import {Button, Modal} from '../../components/ui';
import {KlineCardData, KlineIndicatorConfig, normalizeKlineConfig} from './boardTypes';

/** ⋯菜单内的勾选行 + 参数入口(经 BoardCardShell.menuExtras 注入) */
export const KlineIndicatorMenuItems: React.FC<{
  card: KlineCardData;
  onToggle: (k: 'macd' | 'rsi' | 'boll') => void;
  onOpenParams: () => void;
}> = ({card, onToggle, onOpenParams}) => {
  const ind = card.config.indicators;
  const rows: {key: 'macd' | 'rsi' | 'boll'; label: string}[] = [
    {key: 'macd', label: 'MACD'},
    {key: 'rsi', label: 'RSI'},
    {key: 'boll', label: '布林带'},
  ];
  return (
    <>
      {rows.map((r) => (
        <button
          key={r.key}
          type="button"
          className={`board-card__menu-item board-card__menu-check ${ind[r.key] ? 'board-card__menu-check--on' : ''}`}
          onClick={() => onToggle(r.key)}
        >
          <span className="board-card__menu-checkmark">{ind[r.key] ? '✓' : ''}</span>
          {r.label}
        </button>
      ))}
      <button type="button" className="board-card__menu-item" onClick={onOpenParams}>
        指标参数…
      </button>
    </>
  );
};

interface ParamFieldProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
}

const ParamField: React.FC<ParamFieldProps> = ({label, value, onChange}) => (
  <label className="board-param__field">
    <span>{label}</span>
    <input
      className="board-input"
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  </label>
);

/** 指标参数弹窗(index.tsx 持状态渲染;非法输入禁用确定并红字提示) */
export const KlineIndicatorParamsModal: React.FC<{
  open: boolean;
  config: KlineIndicatorConfig;
  onClose: () => void;
  onSave: (c: KlineIndicatorConfig) => void;
}> = ({open, config, onClose, onSave}) => {
  const [macd, setMacd] = useState({fast: '', slow: '', signal: ''});
  const [rsiP, setRsiP] = useState('');
  const [bollP, setBollP] = useState({period: '', stdDev: ''});
  const [error, setError] = useState<string | null>(null);
  const [loadedFor, setLoadedFor] = useState<boolean | null>(null);

  // 弹窗每次打开,用当前 config 回填
  if (open && loadedFor !== true) {
    setMacd({
      fast: String(config.params.macd.fast),
      slow: String(config.params.macd.slow),
      signal: String(config.params.macd.signal),
    });
    setRsiP(String(config.params.rsi.period));
    setBollP({period: String(config.params.boll.period), stdDev: String(config.params.boll.stdDev)});
    setError(null);
    setLoadedFor(true);
  }
  if (!open && loadedFor !== false) setLoadedFor(false);

  const save = () => {
    const next = normalizeKlineConfig({
      ...config,
      params: {
        macd: {fast: Number(macd.fast), slow: Number(macd.slow), signal: Number(macd.signal)},
        rsi: {period: Number(rsiP)},
        boll: {period: Number(bollP.period), stdDev: Number(bollP.stdDev)},
      },
    });
    // normalize 后与输入不一致 = 有非法值被回默认,提示而非静默吞掉
    const inMacd = Number(macd.fast) === next.params.macd.fast
      && Number(macd.slow) === next.params.macd.slow
      && Number(macd.signal) === next.params.macd.signal;
    const inRsi = Number(rsiP) === next.params.rsi.period;
    const sdOk = isFinite(Number(bollP.stdDev)) && Number(bollP.stdDev) === next.params.boll.stdDev;
    const bollPeriodOk = Number(bollP.period) === next.params.boll.period;
    if (!inMacd || !inRsi || !sdOk || !bollPeriodOk) {
      setError('参数需为整数 2–250(fast<slow),stdDev 0.5–5');
      return;
    }
    onSave(next);
    onClose();
  };

  return (
    <Modal
      open={open}
      title="指标参数"
      onClose={onClose}
      width={360}
      footer={
        <>
          <Button size="sm" onClick={onClose}>取消</Button>
          <Button size="sm" variant="primary" onClick={save}>确定</Button>
        </>
      }
    >
      <div className="board-param">
        <div className="board-param__group">
          <div className="board-param__group-title">MACD</div>
          <ParamField label="快线" value={macd.fast} onChange={(v) => setMacd((s) => ({...s, fast: v}))} />
          <ParamField label="慢线" value={macd.slow} onChange={(v) => setMacd((s) => ({...s, slow: v}))} />
          <ParamField label="信号" value={macd.signal} onChange={(v) => setMacd((s) => ({...s, signal: v}))} />
        </div>
        <div className="board-param__group">
          <div className="board-param__group-title">RSI</div>
          <ParamField label="周期" value={rsiP} onChange={setRsiP} />
        </div>
        <div className="board-param__group">
          <div className="board-param__group-title">布林带</div>
          <ParamField label="周期" value={bollP.period} onChange={(v) => setBollP((s) => ({...s, period: v}))} />
          <ParamField label="标准差倍数" value={bollP.stdDev} onChange={(v) => setBollP((s) => ({...s, stdDev: v}))} />
        </div>
        {error && <div className="board-dialog-error">{error}</div>}
      </div>
    </Modal>
  );
};
```

- [ ] **Step 4: index.tsx 接线**

import 加:

```ts
import {
  KlineIndicatorMenuItems,
  KlineIndicatorParamsModal,
} from './KlineIndicatorMenu';
```

组件内(约 42 行 refreshMap state 之后)加:

```ts
  const [paramsCardId, setParamsCardId] = useState<string | null>(null);
```

`<BoardCanvas` 加 prop(与 onRefreshCard 同级):

```tsx
          renderMenuExtras={(card, close) => {
            if (card.type !== 'kline') return null;
            return (
              <KlineIndicatorMenuItems
                card={card}
                onToggle={(k) => updateCard(card.id, {
                  config: {
                    ...card.config,
                    indicators: {...card.config.indicators, [k]: !card.config.indicators[k]},
                  },
                })}
                onOpenParams={() => { setParamsCardId(card.id); close(); }}
              />
            );
          }}
```

页面尾部 `<AddCardModal …/>` 之后加(paramsCardId 对应卡可能已删,找不到就不渲染):

```tsx
      {(() => {
        const pc = layout.cards.find((c) => c.id === paramsCardId && c.type === 'kline');
        if (!pc || pc.type !== 'kline') return null;
        return (
          <KlineIndicatorParamsModal
            open
            config={pc.config}
            onClose={() => setParamsCardId(null)}
            onSave={(config) => updateCard(pc.id, {config})}
          />
        );
      })()}
```

- [ ] **Step 5: Board.css 追加样式**

文件末尾追加:

```css
/* ⋯菜单:技术指标勾选行/分隔线 */
.board-card__menu-sep {
  height: 1px;
  margin: 4px 8px;
  background: var(--color-border, rgba(255, 255, 255, 0.08));
}
.board-card__menu-check--on {
  color: var(--color-primary, #0a84ff);
}
.board-card__menu-checkmark {
  display: inline-block;
  width: 14px;
  text-align: center;
}

/* 指标参数弹窗 */
.board-param {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.board-param__group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.board-param__group-title {
  width: 44px;
  font-weight: 600;
  font-size: 13px;
}
.board-param__field {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-secondary, #a1a1a6);
}
.board-param__field input {
  width: 64px;
}
```

- [ ] **Step 6: CDP 验证写链路(布局持久化 round-trip)**

启动测试环境(复用 2026-09-03 uuid 回归的方法):

```bash
curl -s -X POST "http://127.0.0.1:12100/api/v1/board/boards" -H "Content-Type: application/json" -d '{"name":"TS_kline指标_勿动"}'
# 记下返回 id 为 $BID
curl -s -X PUT "http://127.0.0.1:12100/api/v1/board/boards/$BID" -H "Content-Type: application/json" -d '{"layout":{"version":1,"timeRange":{"preset":"1y","start":null,"end":null},"maxZ":0,"cards":[{"id":"ts-k1","title":"贵州茅台","type":"kline","symbol":"sh600519","x":0,"y":0,"w":6,"h":14,"z":1,"opacity":1,"config":{}}]}}'
```

写 `/tmp/kline_menu_cdp.mjs`(headless Chrome,导航 `http://127.0.0.1:12000/` 后 `localStorage.setItem('ytrader_board_active','$BID')` 再去 `/board`;打开 ⋯ 菜单,依次点 MACD/RSI/布林带三个勾选行,各等 1.2s;打开"指标参数…",把 RSI 周期改成 7 点确定):

```js
// 关键断言(完整脚本骨架,交互用 Runtime.evaluate 派发 click,
// 输入框赋值用原生 setter + dispatchEvent('input') 触发 React onChange):
// 1. 菜单出现勾选行:document.querySelectorAll('.board-card__menu-check').length === 3
// 2. 逐个点击后:
//    GET http://127.0.0.1:12100/api/v1/board/boards/$BID →
//    layout.cards[0].config.indicators === {macd:true, rsi:true, boll:true}
// 3. 参数弹窗改 RSI period=7 确定后:
//    同 GET → layout.cards[0].config.params.rsi.period === 7
//    且其余 params 保持默认 {macd:{fast:12,slow:26,signal:9}, boll:{period:20,stdDev:2}}
// 4. 控制台零 [EXCEPTION]
```

Run + expected:全部断言通过;`curl GET` 验证持久化 payload。

- [ ] **Step 7: Commit**

```bash
git add frontend/apps/web/src/pages/Board/BoardCardShell.tsx frontend/apps/web/src/pages/Board/BoardCanvas.tsx frontend/apps/web/src/pages/Board/KlineIndicatorMenu.tsx frontend/apps/web/src/pages/Board/index.tsx frontend/apps/web/src/pages/Board/Board.css
git commit -m "feat(board-web): K线卡⋯菜单指标勾选+参数弹窗——menuExtras插槽,config写链路落库"
```

---

### Task 4: KlineCard 多窗格渲染(config 读链路)

**Files:**
- Modify: `frontend/apps/web/src/pages/Board/cards/KlineCard.tsx`(大改)
- Modify: `frontend/apps/web/src/pages/Board/index.tsx`(renderCard kline 分支传 config)
- Modify: `frontend/apps/web/src/pages/Board/Board.css`(legend chips)

**Interfaces:**
- Consumes: `KlineIndicatorConfig`(Task 2)、`macd/rsiWilder/boll`(Task 1)、`colorUp/colorDown`(chartTheme)、lightweight-charts 5.2 `addSeries(def, opts, paneIndex)` / `chart.panes()[i].setStretchFactor(n)` / `series.createPriceLine`
- Produces: `KlineCardProps` 增加 `config: KlineIndicatorConfig`;无下游依赖(Task 5 只验证)

- [ ] **Step 1: 重写 KlineCard.tsx(完整代码)**

```tsx
/**
 * K线卡片 — lightweight-charts 蜡烛图 + 成交量叠底 + MA5/10/20/60;
 * 可选技术指标:BOLL 叠主图,MACD/RSI 独立副图(多窗格,共享时间轴)。
 * 数据由全局时间范围驱动;EMA 类指标左侧需预热,fetch start 前扩 200 自然日,
 * 展示切片回 range.start;开关/参数变化用缓存 bars 重算,不重新请求。
 */
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {
  CandlestickData,
  CandlestickSeries,
  HistogramData,
  HistogramSeries,
  IChartApi,
  ISeriesApi,
  LineData,
  LineSeries,
  LineStyle,
  Time,
  createChart,
} from 'lightweight-charts';
import {StateView} from '../../../components/ui';
import {getApiBase} from '../../../lib/api';
import {DateRange, KlineIndicatorConfig} from '../boardTypes';
import {boll, macd, rsiWilder} from '../indicators';
import {colorDown, colorUp} from '../../../lib/chartTheme';

const API_BASE = getApiBase();
const COLOR_VOLUME_UP = 'rgba(255, 69, 58, 0.4)';
const COLOR_VOLUME_DOWN = 'rgba(48, 209, 88, 0.4)';
const MA_COLORS = ['#f59e0b', '#0a84ff', '#8b5cf6', '#ec4899'];
const BOLL_COLOR = '#22d3ee';
const MACD_DIF_COLOR = '#f59e0b';
const MACD_DEA_COLOR = '#0a84ff';
const RSI_COLOR = '#ec4899';
const REF_LINE_COLOR = 'rgba(161, 161, 166, 0.4)';
/** EMA 类指标预热:覆盖默认参数及 slow≤60 的收敛 */
const WARMUP_CALENDAR_DAYS = 200;

interface KlineBar {
  trade_date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
}

function parseDate(dateStr: string): number {
  const d = new Date(dateStr.includes('T') ? dateStr : dateStr + 'T00:00:00');
  return Math.floor(d.getTime() / 1000);
}

function sma(closes: number[], index: number, period: number): number | null {
  if (index < period - 1) return null;
  let sum = 0;
  for (let i = index - period + 1; i <= index; i++) sum += closes[i];
  return sum / period;
}

/** range.start 前扩 N 自然日(YYYY-MM-DD),供指标预热 */
function warmupStart(start: string | null): string | null {
  if (!start) return null;
  const d = new Date(start + 'T00:00:00');
  d.setDate(d.getDate() - WARMUP_CALENDAR_DAYS);
  const p = (x: number) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export interface KlineCardProps {
  symbol: string;
  range: DateRange;
  refreshKey: number;
  config: KlineIndicatorConfig;
}

export const KlineCard: React.FC<KlineCardProps> = ({symbol, range, refreshKey, config}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const maRefs = useRef<Array<ISeriesApi<'Line'> | null>>([]);
  const bollRefs = useRef<Array<ISeriesApi<'Line'> | null>>([]);
  const macdHistRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const macdDifRef = useRef<ISeriesApi<'Line'> | null>(null);
  const macdDeaRef = useRef<ISeriesApi<'Line'> | null>(null);
  const rsiRef = useRef<ISeriesApi<'Line'> | null>(null);
  const rsiPaneRef = useRef<number | null>(null);
  const barsRef = useRef<KlineBar[]>([]);
  const [state, setState] = useState<{loading: boolean; error: string | null; empty: boolean}>(
    {loading: true, error: null, empty: false},
  );
  const reqIdRef = useRef(0);
  // applySeries 依赖最新 config/load,用 ref 镜像避免 effect 闭包陈值
  const configRef = useRef(config);
  configRef.current = config;
  const rangeRef = useRef(range);
  rangeRef.current = range;

  // 建图(一次) + 尺寸随卡片缩放
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      layout: {background: {color: 'transparent'}, textColor: '#a1a1a6', fontSize: 11},
      grid: {
        vertLines: {color: 'rgba(161, 161, 166, 0.15)'},
        horzLines: {color: 'rgba(161, 161, 166, 0.15)'},
      },
      crosshair: {
        mode: 1,
        vertLine: {color: 'rgba(161, 161, 166, 0.4)', width: 1, style: 2},
        horzLine: {color: 'rgba(161, 161, 166, 0.4)', width: 1, style: 2},
      },
      rightPriceScale: {
        borderColor: 'rgba(161, 161, 166, 0.2)',
        scaleMargins: {top: 0.08, bottom: 0.28},
      },
      timeScale: {
        borderColor: 'rgba(161, 161, 166, 0.2)',
        timeVisible: true,
        secondsVisible: false,
      },
      width: el.clientWidth,
      height: el.clientHeight,
    });
    chartRef.current = chart;
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: colorUp,
      downColor: colorDown,
      borderUpColor: colorUp,
      borderDownColor: colorDown,
      wickUpColor: colorUp,
      wickDownColor: colorDown,
    });
    volumeRef.current = chart.addSeries(HistogramSeries, {
      color: '#6366f1',
      priceFormat: {type: 'volume'},
      priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({scaleMargins: {top: 0.8, bottom: 0}});
    maRefs.current = MA_COLORS.map((c) =>
      chart.addSeries(LineSeries, {
        color: c, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      }),
    );
    const ro = new ResizeObserver(() => {
      chart.applyOptions({width: el.clientWidth, height: el.clientHeight});
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      maRefs.current = [];
      bollRefs.current = [];
      macdHistRef.current = null;
      macdDifRef.current = null;
      macdDeaRef.current = null;
      rsiRef.current = null;
      rsiPaneRef.current = null;
    };
  }, []);

  /** 序列随 config 增删(BOLL 主图;MACD pane1;RSI pane=macd?2:1,窗格变了重建) */
  const ensureSeries = useCallback(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const ind = configRef.current.indicators;

    if (ind.boll && bollRefs.current.length === 0) {
      bollRefs.current = [0, 1, 2].map(() =>
        chart.addSeries(LineSeries, {
          color: BOLL_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        }),
      );
    } else if (!ind.boll && bollRefs.current.length > 0) {
      bollRefs.current.forEach((s) => s?.remove());
      bollRefs.current = [];
    }

    if (ind.macd && !macdDifRef.current) {
      macdHistRef.current = chart.addSeries(HistogramSeries, {}, 1);
      macdDifRef.current = chart.addSeries(LineSeries, {
        color: MACD_DIF_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      }, 1);
      macdDifRef.current.createPriceLine({
        price: 0, color: REF_LINE_COLOR, lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: false, title: '',
      });
      macdDeaRef.current = chart.addSeries(LineSeries, {
        color: MACD_DEA_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      }, 1);
    } else if (!ind.macd && macdDifRef.current) {
      macdHistRef.current?.remove();
      macdDifRef.current?.remove();
      macdDeaRef.current?.remove();
      macdHistRef.current = null;
      macdDifRef.current = null;
      macdDeaRef.current = null;
    }

    const wantRsiPane = ind.macd ? 2 : 1;
    if (ind.rsi && (!rsiRef.current || rsiPaneRef.current !== wantRsiPane)) {
      rsiRef.current?.remove();
      rsiRef.current = chart.addSeries(LineSeries, {
        color: RSI_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      }, wantRsiPane);
      rsiRef.current.createPriceLine({
        price: 30, color: REF_LINE_COLOR, lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: false, title: '',
      });
      rsiRef.current.createPriceLine({
        price: 70, color: REF_LINE_COLOR, lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: false, title: '',
      });
      rsiPaneRef.current = wantRsiPane;
    } else if (!ind.rsi && rsiRef.current) {
      rsiRef.current.remove();
      rsiRef.current = null;
      rsiPaneRef.current = null;
    }

    // 窗格高度比:主图 3 : 副图 1
    chart.panes().forEach((p, i) => p.setStretchFactor(i === 0 ? 3 : 1));
  }, []);

  /** 缓存 bars + 当前 config → 纯渲染(不请求) */
  const applySeries = useCallback(() => {
    const chart = chartRef.current;
    if (!chart) return;
    ensureSeries();
    const cfg = configRef.current;
    const bars = barsRef.current;
    const start = rangeRef.current.start;
    // 展示窗:预热数据只参与计算,不进图
    const dispIdx: number[] = [];
    bars.forEach((b, i) => {
      if (!start || b.trade_date >= start) dispIdx.push(i);
    });
    if (dispIdx.length === 0) {
      candleRef.current?.setData([]);
      volumeRef.current?.setData([]);
      maRefs.current.forEach((m) => m?.setData([]));
      bollRefs.current.forEach((s) => s?.setData([]));
      macdHistRef.current?.setData([]);
      macdDifRef.current?.setData([]);
      macdDeaRef.current?.setData([]);
      rsiRef.current?.setData([]);
      setState((s) => (s.loading ? s : {loading: false, error: null, empty: true}));
      return;
    }
    const closes = bars.map((b) => b.close);
    const t = (i: number) => parseDate(bars[i].trade_date) as Time;
    candleRef.current?.setData(
      dispIdx.map((i) => ({
        time: t(i),
        open: bars[i].open, high: bars[i].high, low: bars[i].low, close: bars[i].close,
      })),
    );
    volumeRef.current?.setData(
      dispIdx.map((i) => ({
        time: t(i),
        value: bars[i].volume,
        color: bars[i].close >= bars[i].open ? COLOR_VOLUME_UP : COLOR_VOLUME_DOWN,
      })),
    );
    [5, 10, 20, 60].forEach((period, pi) => {
      const line: LineData<Time>[] = [];
      dispIdx.forEach((i) => {
        const v = sma(closes, i, period);
        if (v != null) line.push({time: t(i), value: v});
      });
      maRefs.current[pi]?.setData(line);
    });
    const lineOf = (series: ISeriesApi<'Line'> | null, values: (number | null)[]) => {
      if (!series) return;
      const line: LineData<Time>[] = [];
      dispIdx.forEach((i) => {
        const v = values[i];
        if (v != null) line.push({time: t(i), value: v});
      });
      series.setData(line);
    };
    if (cfg.indicators.boll) {
      const bb = boll(closes, cfg.params.boll.period, cfg.params.boll.stdDev);
      lineOf(bollRefs.current[0], bb.upper);
      lineOf(bollRefs.current[1], bb.mid);
      lineOf(bollRefs.current[2], bb.lower);
    }
    if (cfg.indicators.macd) {
      const m = macd(closes, cfg.params.macd.fast, cfg.params.macd.slow, cfg.params.macd.signal);
      if (macdHistRef.current) {
        const hist: HistogramData<Time>[] = [];
        dispIdx.forEach((i) => {
          const v = m.hist[i];
          if (v != null) hist.push({
            time: t(i), value: v,
            color: v >= 0 ? 'rgba(255, 69, 58, 0.55)' : 'rgba(48, 209, 88, 0.55)',
          });
        });
        macdHistRef.current.setData(hist);
      }
      lineOf(macdDifRef.current, m.dif);
      lineOf(macdDeaRef.current, m.dea);
    }
    if (cfg.indicators.rsi) {
      lineOf(rsiRef.current, rsiWilder(closes, cfg.params.rsi.period));
    }
    chart.timeScale().fitContent();
    setState({loading: false, error: null, empty: false});
  }, [ensureSeries]);

  const load = useCallback(async () => {
    const reqId = ++reqIdRef.current;
    const qs = new URLSearchParams({interval: '1d', limit: '3000'});
    const fetchStart = warmupStart(range.start);
    if (fetchStart) qs.set('start', fetchStart);
    if (range.end) qs.set('end', range.end);
    setState({loading: true, error: null, empty: false});
    try {
      const res = await fetch(`${API_BASE}/market/kline/${symbol}?${qs}`);
      if (reqId !== reqIdRef.current) return;
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (reqId !== reqIdRef.current) return;
      const bars: KlineBar[] = json?.data?.bars || [];
      bars.sort((a, b) => a.trade_date.localeCompare(b.trade_date));
      barsRef.current = bars;
      applySeries();
    } catch (e) {
      setState({loading: false, error: String(e), empty: false});
    }
  }, [symbol, range.start, range.end, applySeries]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  // 开关/参数变化:只重算不重拉
  useEffect(() => {
    applySeries();
  }, [config, applySeries]);

  const legendExtras = [
    ...(config.indicators.boll ? [{label: 'BOLL', color: BOLL_COLOR}] : []),
    ...(config.indicators.macd ? [
      {label: 'DIF', color: MACD_DIF_COLOR},
      {label: 'DEA', color: MACD_DEA_COLOR},
    ] : []),
    ...(config.indicators.rsi ? [{label: `RSI(${config.params.rsi.period})`, color: RSI_COLOR}] : []),
  ];

  return (
    <div className="board-chart">
      {(state.loading || state.error || state.empty) && (
        <div className="board-chart__state">
          <StateView
            state={state.loading ? 'loading' : state.error ? 'error' : 'empty'}
            text={state.error ? state.error : state.empty ? '该区间无K线数据' : undefined}
            onRetry={state.error ? () => void load() : undefined}
          />
        </div>
      )}
      <div ref={containerRef} className="board-chart__canvas" />
      <div className="board-chart__legend">
        {['MA5', 'MA10', 'MA20', 'MA60'].map((l, i) => (
          <span key={l} style={{color: MA_COLORS[i]}}>{l}</span>
        ))}
        {legendExtras.map((x) => (
          <span key={x.label} style={{color: x.color}}>{x.label}</span>
        ))}
      </div>
    </div>
  );
};
```

**注意:`paneIndex` 是 `addSeries` 的第三个参数**(v5 API:`addSeries(definition, options?, paneIndex?)`),不要写进 options。

- [ ] **Step 2: index.tsx renderCard 传 config**

kline 分支改为:

```tsx
              case 'kline':
                return (
                  <KlineCard
                    symbol={card.symbol}
                    config={card.config}
                    range={range}
                    refreshKey={refreshKey}
                  />
                );
```

- [ ] **Step 3: Board.css legend 换行兜底**

找到 `.board-chart__legend` 规则,追加 `flex-wrap: wrap;`(无则新增):

```css
.board-chart__legend {
  flex-wrap: wrap;
}
```

- [ ] **Step 4: CDP 验证渲染(可视化 + 零异常 + 参数无重拉)**

继续用 Task 3 的测试看板(已含 config,或 PUT 更新为三个指标全开):

```bash
curl -s -X PUT "http://127.0.0.1:12100/api/v1/board/boards/$BID" -H "Content-Type: application/json" -d '{"layout":{"version":1,"timeRange":{"preset":"1y","start":null,"end":null},"maxZ":0,"cards":[{"id":"ts-k1","title":"贵州茅台","type":"kline","symbol":"sh600519","x":0,"y":0,"w":8,"h":20,"z":1,"opacity":1,"config":{"indicators":{"macd":true,"rsi":true,"boll":true},"params":{"macd":{"fast":12,"slow":26,"signal":9},"rsi":{"period":14},"boll":{"period":20,"stdDev":2}}}}]}}'
```

headless Chrome 脚本断言:

```js
// 1. Page.captureScreenshot → 人工检查:主图蜡烛+BOLL 三线;下方 MACD 副图(DIF/DEA 线+红绿柱+零轴虚线);再下 RSI 副图(粉线+30/70 虚线);窗格高度比≈3:1:1
// 2. legend 文本包含 BOLL/DIF/DEA/RSI(14):
//    document.querySelector('.board-chart__legend').textContent
// 3. 参数弹窗 RSI 周期 14→7 确定后:
//    performance.getEntriesByType('resource').filter(r => r.name.includes('/market/kline/')).length 前后不变(无重拉)
//    legend 文本变为 RSI(7)
// 4. 菜单取消勾选 MACD → MACD/RSI 副图数量变化(RSI 副图顶到 pane1),legend 无 DIF/DEA
// 5. 控制台零 [EXCEPTION]
```

Expected:全部通过;截图存档 `/tmp/kline_ind_render.png`。

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/Board/cards/KlineCard.tsx frontend/apps/web/src/pages/Board/index.tsx frontend/apps/web/src/pages/Board/Board.css
git commit -m "feat(board-web): K线卡多窗格技术指标——BOLL叠主图/MACD/RSI副图,预热前扩200日,参数变化不重拉"
```

---

### Task 5: 端到端回归 + 收尾

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-kline-card-indicators-design.md`(状态行)

**Interfaces:**
- Consumes: 前四个任务的全部产出
- Produces: 无

- [ ] **Step 1: 全链路 CDP 回归**

headless Chrome,`http://127.0.0.1:12000`,按序验证并记录:

1. 旧看板兼容:`localStorage` 清掉 active 后进 `/board`,选「21年牛市熊市分析」加载无异常,已有卡片渲染正常(若其内有 kline 卡,指标默认关、与改动前视觉一致)。
2. 测试看板:刷新页面(reload)→ 三个指标配置持久化(legend 仍有 BOLL/DIF/DEA/RSI(7))——验证自动保存 round-trip。
3. 全区间开关:顶栏切 preset「全部」→ 数据重拉、指标随新数据重算,零异常。
4. 添加链路:AddCardModal 新建 kline 卡(搜索输入用原生 setter 触发 input 事件,选第一个结果)→ 新卡默认无指标,菜单可开。
5. 控制台全程零 [EXCEPTION];rsbuild 编译无报错。

Expected:全部通过。

- [ ] **Step 2: 清理测试看板**

```bash
curl -s -X DELETE "http://127.0.0.1:12100/api/v1/board/boards/$BID"
# 确认列表只剩原有看板
curl -s "http://127.0.0.1:12100/api/v1/board/boards"
```

- [ ] **Step 3: 设计文档状态更新 + Commit**

`docs/superpowers/specs/2026-09-03-kline-card-indicators-design.md` 状态行改为:

```markdown
状态:已落地(2026-09-03,实施计划 docs/superpowers/plans/2026-09-03-kline-card-indicators.md)
```

```bash
git add docs/superpowers/specs/2026-09-03-kline-card-indicators-design.md
git commit -m "docs(board): K线卡技术指标设计标记已落地"
```

---

## Self-Review 记录

- **Spec 覆盖**:指标模块(T1)、config 模型+normalize 修复(T2)、菜单勾选+参数弹窗(T3)、多窗格渲染+预热+重算+legend(T4)、验证方案三条(T1 互验/T3-T5 CDP、旧看板兼容 T5)——spec 各节均有对应任务。
- **占位符**:无 TBD/TODO;Task 3 Step 6 的 CDP 脚本为骨架+断言清单,交互模式与 2026-09-03 uuid 回归脚本同构(Runtime.evaluate 派发 click),执行者可直接展开;`paneIndex` 用法(v5 第三参数)已在 Task 4 显式标注。
- **类型一致性**:`KlineIndicatorConfig`/`defaultKlineConfig()`/`normalizeKlineConfig` 在 T2 定义、T3/T4 消费签名一致;`menuExtras` 在 Shell(`(close) => ReactNode`)与 Canvas(`(card, close) => ReactNode`)的形参差异是转发关系,已在代码中体现;`KlineCardProps.config` T4 定义、index.tsx 同步传参。
- **已知取舍**:T3 参数弹窗用 render-时 setState 回填(`loadedFor` 标志)而非 useEffect——因为 `open` 翻转与回填必须原子;执行者若 lint 报 hook 规则警告,可改为 useEffect 依赖 `[open, config]`,行为等价。
