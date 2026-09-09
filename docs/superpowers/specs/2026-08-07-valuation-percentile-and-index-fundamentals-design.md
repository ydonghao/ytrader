# 估值分位 + 指数/行业财务聚合 + 多指标叠加图 设计文档

> **批次**：第一批（P0a + P0b + P3）
> **日期**：2026-08-07
> **背景**：理杏仁对比分析中提出的 P0–P3 借鉴项，本批为最高优先级（P0 估值研究深化 + P3 展示增强）。完整 P0–P3 共 6 个功能，按依赖分 3 批交付，此为第 1 批。

## 目标与范围

### 本批交付（3 个功能）

1. **P0a 个股历史估值分位点** —— 展示"当前 PE_TTM 处于过去 10 年的 X% 分位"，支持 PE_TTM / PB / PS_TTM / 股息率，3/5/10 年窗口。
2. **P0b 指数/行业估值 + 财务聚合** —— 把指数（沪深300/上证50/中证500/1000）和申万一级行业当作整体，展示其估值历史分位 + ROE/净利率等季度财务聚合。
3. **P3 多指标叠加对比图** —— 在个股页支持多指标同图叠加对比（归一化）。

### 不做（YAGNI 边界）

- ❌ restated/回溯值口径（akshare 源不返回修正标记，仓库零基础，工作量与价值不匹配）
- ❌ 自定义作图引擎（与"交易工作站"定位不符）
- ❌ 全部宽基指数（只做 4 大宽基 + 申万一级 31 个行业）
- ❌ B 股、债券、基金（留给后续批次或暂不做）
- ❌ 指数成分股变动的历史回溯（用当前成分近似，标注口径）

### 后续批次（本批不做）

- **第二批**：P1a 筛选器结果导出 + P1b 指标级告警
- **第三批**：P2 H 股个股基本面

---

## 总体架构

三个功能共享"估值指标在历史时序中的位置"这一核心概念，数据层统一规划：

```
stock_valuation (已有, 日频 PE/PB/PS/dv)     ──┬─→ P0a 个股估值分位(实时算+缓存)
                                               │
index_valuation_daily (新建, 落盘积累)         ──┤
sw_index_valuation_daily (新建, 落盘积累)      ──┼─→ P0b 指数/行业估值分位
                                               │
stock_financial_detail (已有, 三大报表)        ──┴─→ P0b 行业/指数财务聚合(成分股加总/市值加权)

P0a/P0b 产出的时序数据 ──→ P3 多指标叠加图(纯展示层组合)
```

**设计原则**：
- P0a 的分位算法提取为通用工具函数，P0b 复用同一算法（参数化 scope）。
- P3 不引入新数据，纯前端展示层组合已有/本批新增的时序。
- P0a 独立成页（`/valuation`），避免 `Financial.tsx`（已 1159 行）继续臃肿。

---

## P0a：个股历史估值分位点

### 目标

在独立 `/valuation` 页面输入个股，展示其当前 PE_TTM/PB/PS_TTM/股息率在 3/5/10 年历史中的分位，并画出分位带历史图。

### 关键决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 计算方式 | **实时计算 + 1 小时缓存** | `stock_valuation` 表已齐备；预聚合表引入双数据源与同步复杂度，YAGNI；缓存规避重复计算。参考行业快照 `_INDUSTRY_SNAPSHOT_TTL=3600` 模式 |
| 分位窗口 | **3 年 / 5 年 / 10 年** 三档可切 | 理杏仁标准口径；10 年覆盖一轮牛熊 |
| 指标 | **PE_TTM / PB / PS_TTM / 股息率(dv_ttm)** 四个 | 与理杏仁对齐；数据已在 `stock_valuation` 表 |
| 负值处理 | PE/PS 为负或缺失 → 该日不纳入分位样本 | 理杏仁口径，避免负值污染分位 |
| 样本下限 | 窗口内有效样本 < 30 → 该窗口返回 null（不展示） | 与现有 `_pe_percentile` 一致 |
| 回溯值(restated) | **本期不做** | 见 YAGNI 边界 |

### 后端实现

#### 新增通用工具函数

**文件**：`backend/src/domain/market/fundamental/percentile.py`（新建）

```python
def calc_percentile(samples: list[float], current: float) -> float | None:
    """当前值在样本中的分位 (0~1)。样本<30返回None。负值/None应在传入前过滤。"""

def percentile_stats(samples: list[float], current: float) -> dict | None:
    """返回 {current, percentile, sample_size, min, max, p25, p50, p75}。"""
```

提取自 `backend/src/domain/market/strategy/longterm/strategies/value_averaging.py:130` 的 `_pe_percentile`，泛化为任意指标。

#### 新增端点

**文件**：`backend/src/api/handler/financial_detail_handler.py` 新增 `valuation_percentile()`
**文件**：`backend/src/api/router/financial_router.py` 新增路由

```
GET /api/v1/financial/valuation-percentile/{symbol}
  ?windows=3y,5y,10y        # 默认全三档
  &as_of=<date|默认最新>     # 指定历史某天的分位（用于回看）
  &metrics=pe_ttm,pb,ps_ttm,dv_ttm  # 默认全部
```

**返回结构**：
```json
{
  "symbol": "000001",
  "name": "平安银行",
  "as_of": "2026-08-07",
  "metrics": {
    "pe_ttm": {
      "current": 4.82,
      "windows": {
        "3y":  {"percentile": 0.15, "sample_size": 730, "min": 3.8, "max": 7.2, "p25": 4.5, "p50": 5.1, "p75": 6.0},
        "5y":  {"percentile": 0.12, ...},
        "10y": {"percentile": 0.08, ...}
      },
      "series": [{"date": "2024-01-02", "value": 4.9, "pct": 0.18}, ...]  // 用于画分位带图，按月采样降采样
    },
    "pb": {...},
    "ps_ttm": {...},
    "dv_ttm": {...}
  }
}
```

**实现逻辑**：
1. 调 `StockValuationRepository.get_range(symbol, start, end)`（`backend/src/infra/database/market/valuation.py:120`）拉窗口内日线。
2. 按 metric 过滤负值/None。
3. 调 `calc_percentile` / `percentile_stats`。
4. series 做月度降采样（每月最后一个有效点）以控制前端渲染量。
5. 缓存 key = `valpct:{symbol}:{as_of}:{window}`，TTL 1 小时（参考 `_INDUSTRY_SNAPSHOT_TTL`）。

### 前端实现

#### 新页面

**文件**：`frontend/apps/web/src/pages/Valuation.tsx`（新建）

**结构**（参考 SectorScan.tsx 的"顶部控制条 + 主体"布局）：
- 顶部：`StockSearch` 组件（复用 Financial.tsx 的）+ 窗口切换 chip（3y/5y/10y 多选）+ as_of 日期选择
- 主体：4 个指标卡片，每个含
  - 大字分位值 + 状态徽章（<20% 低估绿 / 20-80% 正常 / >80% 高估红，参考 macro 的 severity 体系）
  - 分位带图（`ValuationPercentileChart` 组件）

#### 新组件

**文件**：`frontend/apps/web/src/components/ValuationPercentileChart.tsx`（新建）

recharts `ComposedChart` 画法（历史值轨迹 + 当前窗口统计参考线）：
- `<Line>` 画当前值历史轨迹（series 中的 value）
- `<ReferenceLine>` 画当前窗口的 p25/p50/p75 三条水平参考线（基于 `windows[选中的窗口]` 的统计值），y 值固定，p50 用实线、p25/p75 用虚线
- `<ReferenceArea>` 可选：在 p25-p75 之间画浅色带（强调中间区间）
- 右上角徽章显示当前分位百分比 + 状态色（参考 macro severity 体系）

> 说明：这里不做"滚动分位"（每个时间点的滚动分位曲线），因为那需要每点都重算全窗口，计算量大且语义复杂。改为"历史绝对值轨迹 + 当前窗口统计参考线"，用户能直观看到当前值相对历史分布的位置。

#### 新 hook

**文件**：`frontend/apps/web/src/hooks/useValuationPercentile.ts`（新建）

复用 `useFinancialOverlays.ts` 的 fetch 范式：`getApiBase()` + `fetch` + `json.code === 0`。

#### 路由 + 菜单

- `App.tsx` 加 `<Route path="/valuation" element={<Valuation />} />`
- `Layout.tsx` 的 Overview 组加 `{path: '/valuation', label: '估值分位', icon: ...}`

---

## P0b：指数/行业估值 + 财务聚合

### 目标

把指数（沪深300/上证50/中证500/中证1000）和申万一级 31 个行业当作整体，展示：
1. 估值（PE_TTM/PB/PS/股息率）历史分位
2. 季度财务聚合（ROE/净利率/毛利率/营收/净利/资产总额）

### 核心挑战与对策

akshare 的 `sw_index_first_info` 只有当天快照、**无历史**。对策：
- **当天起**：每日收盘后落盘快照到 `sw_index_valuation_daily`（从今天积累）。
- **历史回填**：用当前成分股的 `stock_valuation` 加权自算回填过去 5-10 年（理杏仁明确说它们也是"样本加和"简单算法；我们用市值加权，更准）。
- **口径标注**：前端明确标注"基于当前成分股近似"，避免误导。

### 关键决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 行业估值历史来源 | 每日落盘 `sw_index_valuation_daily` + 成分股自算回填 | akshare 无历史；不落盘则永远没分位 |
| 加权方式 | **总市值加权**（PE 用市值加权调和，PB 用净资产加权） | 行业惯例；比简单加和更准 |
| 聚合频率 | 估值日频落盘 + 财务季度聚合 | 估值日频用于分位，财务按报告期 |
| 范围 | 申万一级 31 个 + 4 大宽基指数 | 先核心，避免过度铺开 |
| 成分股来源 | akshare `index_component_stocks` + 申万行业映射（复用 `national_team_symbol_sector` 表 + akshare 补全） | 复用已有映射 |

### 后端实现

#### 新建表（3 张）

**文件**：`backend/src/infra/database/market/index_valuation.py`（新建）

```python
class IndexValuationDailyTable (table="index_valuation_daily"):
    symbol: str          # 指数代码，如 "000300" (沪深300)
    trade_date: date
    pe_ttm: float | None
    pb: float | None
    ps_ttm: float | None
    dv_ttm: float | None
    total_mv: float | None   # 成分股总市值合计
    close: float | None      # 指数收盘
    source: str              # "akshare" | "computed"（自算回填标记）
    # 主键 (symbol, trade_date)

class SwIndexValuationDailyTable (table="sw_index_valuation_daily"):
    sw_code: str         # 申万行业代码，如 "801010"
    trade_date: date
    pe_ttm / pb / ps_ttm / dv_ttm / total_mv / close / source
    # 主键 (sw_code, trade_date)
```

**文件**：`backend/src/infra/database/market/index_financial.py`（新建）

```python
class IndexFinancialQuarterlyTable (table="index_financial_quarterly"):
    scope_type: str      # "index" | "sw"
    scope_code: str      # 指数代码 或 申万行业代码
    report_date: date
    roe: float | None
    net_margin: float | None
    gross_margin: float | None
    revenue_sum: float | None       # 成分股营收加总(亿)
    net_profit_sum: float | None    # 成分股净利加总(亿)
    assets_sum: float | None        # 成分股总资产加总(亿)
    sample_count: int               # 实际纳入计算的成分股数
    # 主键 (scope_type, scope_code, report_date)
```

#### 新建同步 job

**文件**：`backend/src/domain/market/sync/jobs/index_valuation_sync.py`（新建）

参考 `financial_full_sync.py` 的 ThreadPoolExecutor + ProgressTracker + 限流模式。

1. **`sync_sw_index_valuation_daily()`** —— 每日 job
   - 调 `AkshareProvider.fetch_sw_index_valuation_snapshot()`（已有，`sw_index_first_info`）取当天 31 个行业的 PE/PB/PS/dv
   - upsert 到 `sw_index_valuation_daily`，source="akshare"
   - 注册到 `scheduler.py`，工作日 16:00 运行

2. **`backfill_index_valuation_history()`** —— 一次性回填 job
   - 对每个指数/行业，取其当前成分股
   - 用 `stock_valuation` 日线按总市值加权自算 PE/PB（PE = Σ(mv) / Σ(mv/pe) 调和加权；PB = Σ(mv) / Σ(mv/pb)）
   - 回填过去 10 年日线，source="computed"
   - 通过手动触发或单独的 backfill 脚本（参考 `backend/src/domain/market/sync/jobs/sw_index_backfill_all.py` 模式）

3. **`sync_index_financial_quarterly()`** —— 季度 job
   - 对每个指数/行业，取成分股 → JOIN `stock_financial_detail` 按报告期聚合
   - ROE 加权（净资产加权）、净利率/毛利率（净利加总/营收加总）
   - upsert 到 `index_financial_quarterly`
   - 注册到 `scheduler.py`，季报披露季后运行

#### 新增端点

**文件**：`backend/src/api/handler/financial_detail_handler.py` 新增函数
**文件**：`backend/src/api/router/financial_router.py` 新增路由

```
GET /api/v1/financial/index-valuation-percentile
  ?scope=sw              # "index" | "sw"
  &code=801010           # 指数代码或申万行业代码
  &window=10y            # 单窗口
  &metrics=pe_ttm,pb     # 默认全部

GET /api/v1/financial/index-financial-agg
  ?scope=sw&code=801010  # 返回季度财务聚合时序

GET /api/v1/financial/index-valuation-percentile/batch
  ?scope=sw&window=10y&metric=pe_ttm   # 批量返回所有行业的分位（用于排行）
```

**实现逻辑**：
- `index-valuation-percentile`：从 `sw_index_valuation_daily` / `index_valuation_daily` 拉窗口，复用 P0a 的 `calc_percentile`。
- `index-financial-agg`：从 `index_financial_quarterly` 拉时序返回。
- `batch`：遍历所有 scope_code 算单指标分位，排序返回。

### 前端实现

#### 扩展 SectorScan.tsx

- 每个行业行新增列：PE_TTM 分位、PB 分位（10y）、DV 分位
- 点击行业行 → 下钻展示该行业的 `ValuationPercentileChart`（复用 P0a 组件，scope 参数化）+ 财务聚合时序图

#### 扩展 Indices.tsx

- 宽基指数卡片加估值分位徽章（PE 10y 分位）
- 点击 → 展开估值分位图

#### 新组件

**文件**：`frontend/apps/web/src/components/IndexFinancialChart.tsx`（新建）

recharts 双轴图：左轴营收/净利加总（Bar），右轴 ROE/净利率（Line）。参考 `FinancialOverlayChart` 的双轴模式。

---

## P3：多指标叠加对比图

### 目标

在个股页支持多指标同图叠加对比，如 PE vs 股息率 vs 归一化股价，发现指标相关性。

### 关键决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 叠加位置 | **独立 recharts 时序图**，不改 KlineChart | KlineChart 用 lightweight-charts，与 recharts 体系不同；硬加 overlays 破坏 K 线交互 |
| 实现方式 | **升级现有 `FinancialOverlayChart`** | 它已是"主指标+多叠加层"模型，只差"用户自选叠加项" |
| 叠加项 | PE_TTM/PB/PS/股息率/ROE/营收/净利 + 归一化股价 | 与理杏仁"随意组合"对齐 |
| 归一化 | 各指标各自 min-max 到 0-100，右轴标"归一化值" | 不同量纲无法同图 |
| 数据来源 | 复用 `useFinancialOverlays` + P0a 的估值时序 + 现有财务时序 | 不引入新数据 |

### 前端实现

#### 升级 FinancialOverlayChart.tsx

**文件**：`frontend/apps/web/src/components/FinancialOverlayChart.tsx`（现有 324 行）

改造点：
1. 新增"叠加指标多选 chip 组"（参考 Indices.tsx 的筛选 chip 范式）：可选 PE/PB/PS/股息率/ROE/营收/净利/归一化股价
2. 叠加指标可选左右轴 + 归一化开关（min-max 到 0-100）
3. 现有的硬编码叠加项（行业 PE/PB ReferenceLine）保留为"参考线"模式

#### MetricDef 扩展

现有 `MetricDef`（FinancialOverlayChart.tsx:33）= `{key, label, color, isPercent?}`，扩展为：
```ts
interface MetricDef {
  key: string;
  label: string;
  color: string;
  isPercent?: boolean;
  axis?: 'left' | 'right';     // 新增：归属轴
  normalize?: boolean;          // 新增：是否归一化
}
```

#### 归一化工具函数

**文件**：`frontend/apps/web/src/lib/normalize.ts`（新建）

```ts
export function minMaxNormalize(values: number[]): number[] {
  const min = Math.min(...values), max = Math.max(...values);
  return values.map(v => max === min ? 50 : ((v - min) / (max - min)) * 100);
}
```

---

## 数据流总结

```
[akshare sw_index_first_info] ──每日16:00──→ sw_index_valuation_daily (落盘积累)
[stock_valuation × 成分股]     ──一次性回填──→ sw/index_valuation_daily (computed, 历史)
[stock_financial_detail × 成分股] ──季报后──→ index_financial_quarterly

stock_valuation ──实时──→ P0a percentile endpoint ──→ /valuation 页面
sw/index_valuation_daily ──实时──→ P0b percentile endpoint ──→ SectorScan/Indices 扩展
index_financial_quarterly ──实时──→ P0b financial-agg endpoint ──→ 行业下钻图

[P0a/P0b 估值时序 + 现有财务时序] ──前端组合──→ P3 多指标叠加图
```

---

## 测试策略

### 后端单元测试
- `percentile.py`：`calc_percentile` / `percentile_stats` 的边界（空样本、样本<30、负值、全相等）
- 加权自算逻辑：PE 调和加权、PB 净资产加权的正确性（用小样本手算验证）
- 端点：mock repository 验证返回结构

### 后端集成测试
- 用真实 `stock_valuation` 数据验证 P0a 端点返回合理分位
- 验证 `sw_index_valuation_daily` 落盘幂等（重复运行不重复插入）

### 前端
- `ValuationPercentileChart` 渲染：mock 数据验证分位带、参考线、徽章
- `FinancialOverlayChart` 升级后：验证多叠加层 + 归一化开关交互
- `minMaxNormalize` 工具函数边界

### 手动验收
- `/valuation` 页面输入一只老股（如 000001），验证 10 年分位合理
- SectorScan 行业分位列展示，点击下钻正常
- Financial 页叠加图切换指标正常

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 行业估值历史回填用"当前成分股"近似，与历史真实成分有偏差 | 前端标注口径；这是理杏仁也有的局限；source 字段区分 akshare/computed |
| 新建 3 张表 + 3 个 job 是本批最大工作量 | 分阶段：先落盘当天数据（快速见效），历史回填用一次性 job 异步跑 |
| 分位实时计算查询压力 | 1h 缓存 + series 月度降采样 + 窗口最长 10 年 |
| akshare 接口限流/不可达 | 复用现有降级模式（`success(None)`），前端展示"数据暂不可用" |
| FinancialOverlayChart 升级影响现有 Financial 页 | 升级为向后兼容（默认行为不变），新增能力通过 props 开启 |

---

## 落地顺序（实现阶段建议）

1. **P0a 后端**：`percentile.py` 工具 + 端点（最小可用，立即有价值）
2. **P0a 前端**：`/valuation` 页面 + 分位图组件
3. **P0b 数据层**：3 张表 + 当日落盘 job（开始积累）
4. **P0b 历史回填**：成分股自算回填 job（异步，可后台慢跑）
5. **P0b 端点 + 前端**：SectorScan/Indices 扩展
6. **P0b 财务聚合**：`index_financial_quarterly` 表 + job + 端点
7. **P3**：升级 FinancialOverlayChart + 归一化工具

每步可独立验证、独立提交。

---

## 涉及文件清单

### 新建（后端）
- `backend/src/domain/market/fundamental/percentile.py`
- `backend/src/infra/database/market/index_valuation.py`
- `backend/src/infra/database/market/index_financial.py`
- `backend/src/domain/market/sync/jobs/index_valuation_sync.py`
- `backend/src/domain/market/sync/jobs/index_valuation_backfill.py`（一次性回填）

### 修改（后端）
- `backend/src/api/handler/financial_detail_handler.py`（新增 3 个函数）
- `backend/src/api/router/financial_router.py`（新增 3 条路由）
- `backend/src/infra/scheduler.py`（注册 2 个新 job）
- `backend/main.py`（如需注册新 repository）

### 新建（前端）
- `frontend/apps/web/src/pages/Valuation.tsx`
- `frontend/apps/web/src/components/ValuationPercentileChart.tsx`
- `frontend/apps/web/src/components/IndexFinancialChart.tsx`
- `frontend/apps/web/src/hooks/useValuationPercentile.ts`
- `frontend/apps/web/src/lib/normalize.ts`

### 修改（前端）
- `frontend/apps/web/src/App.tsx`（加路由）
- `frontend/apps/web/src/components/Layout.tsx`（加菜单项）
- `frontend/apps/web/src/components/FinancialOverlayChart.tsx`（P3 升级）
- `frontend/apps/web/src/pages/SectorScan.tsx`（加行业分位列+下钻）
- `frontend/apps/web/src/pages/Indices.tsx`（加指数分位徽章）

### 参考实现（不改动，借鉴）
- `backend/src/domain/market/strategy/longterm/strategies/value_averaging.py:130`（`_pe_percentile`，提取为通用工具）
- `backend/src/infra/database/market/valuation.py:120`（`StockValuationRepository.get_range`）
- `backend/src/domain/market/sync/jobs/financial_full_sync.py`（同步 job 模式）
- `frontend/apps/web/src/hooks/useFinancialOverlays.ts`（fetch 范式）
- `frontend/apps/web/src/pages/SectorScan.tsx`（建页样板）
