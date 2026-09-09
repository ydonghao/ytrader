# 财务分析图表增强：估值/市场叠加层 + 月季年周期切换

**日期**: 2026-08-04
**状态**: 已实现
**影响范围**: 前端 `Financial.tsx` + 后端新增 2 个只读接口（无新表、无回补 job）

---

## 1. 目标

为「财务分析」页（`Financial.tsx`）增强两项能力：

1. **可折叠叠加层**：在所有财务趋势图上，可叠加显示「个股股价 / 所属行业指数价格 / 行业 PE·PB 快照」，并在专门新增的「估值与市场表现」卡片中集中呈现。
2. **月/季/年周期切换**：财务趋势图支持按 月 / 季度 / 年 三种报告期颗粒度切换。季报、年报必显示；月报有则显示，无则隐藏月选项。

---

## 2. 已确认的关键决策

| 决策项 | 选择 |
|---|---|
| 估值叠加范围 | 个股 PE/PB/PS 完整历史曲线 + 行业 PE/PB 仅当前快照值 |
| 周期语义 | 月=原始报告期原样；季=累计值做差算「单季」；年=只取 12-31 年报期。季报、年报必显示；月报有则显示 |
| Y 轴 | 双 Y 轴：左轴=价格量纲（股价+行业指数），右轴=估值倍数（PE/PB/PS） |
| 交互布局 | **方案 A + 方案 B 都做**：A=专门的「估值与市场表现」卡片；B=叠加层应用到所有现有财务图表 |
| 行业选择 | 默认从 `stock_info` 自动读个股所属申万一级行业，支持手动切换到其他行业 |
| 估值取点频率 | 个股估值历史按「报告期末交易日」取点，与财务 x 轴天然对齐 |

---

## 3. 数据现状（已核实，决定可行性）

### 3.1 已就绪、可直接复用

- **个股 PE/PB/PS 历史**：`stock_valuation` 表，PK `(symbol, trade_date)`，**860 万行，2018-01-02 至今，平均每只 1720 个交易日**，PE/PE_TTM/PB/PS/total_mv 100% 覆盖。无需任何回补。
  - 已有读路径：`StockValuation.get_range(symbol, start, end)` / `get_as_of(symbol, date)`。
- **个股股价 K 线**：`/market/kline/{symbol}`（已有）。
- **申万一级行业指数 K 线**：`/market/kline/sw801xxx`（已有，`index_ohlcv` 表，`market='SW'`，2016 至今）。
- **行业目录**：`sw_index_first_info()` 列出 31 个申万一级行业（代码 `801010.SI` → 名称）。
- **个股所属行业**：`stock_info` 表已有行业字段（`stock_profile` 接口已返回 `industry`）。

### 3.2 仅快照、无历史（明确不做历史曲线）

- **行业级 PE/PB**：用 `sw_index_first_info()` 取**当天快照**（静态 PE、TTM PE、PB、股息率）。不回补历史，只显示当前值（一条参考横线或最新点标注）。

### 3.3 明确不包含

- 行业 PE/PB 的历史曲线（需新建表 + 回补，本期不做）。
- 股息率曲线（`dv_ratio`/`dv_ttm` 在 `stock_valuation` 全为 NULL）。
- 2018 年之前的估值数据（`stock_value_em` 源上限）。

---

## 4. 架构设计

### 4.1 后端：新增 2 个只读接口（无新表）

两个新接口都挂在现有 `financial_router.py`（前缀 `/financial`）下，复用现有 repository 层，零数据迁移。

#### 接口 1：个股估值历史（按报告期末对齐）

```
GET /financial/valuation-history/{symbol}?report_dates=2023-12-31,2024-03-31,...
```

**用途**：前端把财务报表的 `report_date` 列表传过来，后端对每个报告期返回「该报告期末最近一个交易日」的估值快照。这样估值曲线与财务 x 轴天然对齐，无需前端做日期合并。

**返回**：
```json
{
  "code": 0,
  "data": {
    "symbol": "sh600519",
    "points": [
      {"report_date": "2023-12-31", "trade_date": "2023-12-29", "pe": 28.5, "pe_ttm": 30.1, "pb": 8.2, "ps": 15.3, "total_mv": 2.15e12},
      ...
    ]
  }
}
```

**实现**：遍历 `report_dates`，对每个调用 `StockValuation.get_as_of(symbol, report_date)`（取 `trade_date <= report_date` 的最大一行）。`report_dates` 数量与财务期数一致（典型 10-40 个），单次请求几十次索引查询，可接受。如需进一步优化可批量 `WHERE symbol=? AND trade_date <= ANY(?) ... DISTINCT ON`，但初版按现成方法实现。

#### 接口 2：行业估值快照（当天）

```
GET /financial/industry-valuation-snapshot?industry=<申万一级行业名称或sw代码>
```

**用途**：返回指定行业的当天 PE/PB 快照。无 `industry` 参数时返回全部 31 个申万一级行业快照列表（供前端「切换行业」下拉）。

**`industry` 参数解析顺序**：先按 sw_code 精确匹配（如 `801780.SI`），再按行业名称精确匹配（如 `银行`），都未命中则返回 `{code: 1, msg: "行业未找到"}`。前端优先传 sw_code（来自 `useIndustryValuationSnapshot` 的列表项），名称作为兜底。

**返回**（单个行业）：
```json
{
  "code": 0,
  "data": {
    "industry": "银行",
    "sw_code": "801780.SI",
    "as_of": "2026-08-04",
    "pe_static": 5.2,
    "pe_ttm": 5.1,
    "pb": 0.55,
    "dividend_yield": 4.8,
    "company_count": 42
  }
}
```

**返回**（无 industry 参数，列表）：
```json
{
  "code": 0,
  "data": {
    "as_of": "2026-08-04",
    "industries": [
      {"industry": "银行", "sw_code": "801780.SI", "pe_ttm": 5.1, "pb": 0.55, ...},
      {"industry": "农林牧渔", "sw_code": "801010.SI", "pe_ttm": 25.3, "pb": 2.1, ...},
      ...31 条...
    ]
  }
}
```

**实现**：调用 `ak.sw_index_first_info()`（已验证可用），缓存 1 小时（行业估值日内不变）。同时维护一个 `industry 名称 → sw_code` 映射，供前端用名称查询。`akshare_provider` 新增 `fetch_sw_index_valuation_snapshot()` 方法。

**降级**：akshare 调用失败时返回 `{code: 0, data: null}`，前端隐藏行业快照行并提示「行业估值暂不可用」。不阻塞主图渲染。

### 4.2 后端：周期切换（单季换算）

**位置**：后端 `financial_detail_handler.py` 的 `detail_series()` 新增 `period` 查询参数。

```
GET /financial/detail/{symbol}?statement_type=income&period=quarter|year|month
```

- `period=quarter`（默认）：单季换算（最常用，见下）。后端默认值与前端 `PeriodSwitcher` 默认值一致。
- `period=quarter`：**单季换算**。对累计型指标（revenue/net_profit/operating_cost 等所有利润表与现金流量表的流量项）做差：`Q单季 = Q当期累计 − 同年上一期累计`。对存量型指标（资产负债表的所有余额项：货币资金/存货/总资产/总负债/权益 等）**不做差**，取当期值。
- `period=year`：只返回 `report_date` 月份为 12 的期（年报）。

**单季换算算法**（后端实现，前端零计算）：
```
对同一 symbol + 同一 statement_type，按 report_date 升序：
  for each row r (从每年第二个报告期开始):
    prev = 同一年份、report_date < r.report_date 的最大一期
    if prev 存在 and r 是流量项:
        r.field = r.field - prev.field   # 单季值
    # 存量项保持不变
```

**单季/累计字段分类**（模块级常量，明确标注）：
- **流量项（做差）**：利润表全部 + 现金流量表全部（revenue, operating_cost, gross_profit, *_expense, *_profit, *_eps, ocf, icf, fcf 等所有发生额）。
- **存量项（不做差）**：资产负债表全部（monetary_funds, accounts_receivable, inventory, fixed_assets, goodwill, total_assets, total_liabilities, equity, *_loan, cash_end 等所有时点余额）。

**派生指标重算**：单季换算后，`gross_margin` / `net_margin` / `debt_ratio` 必须用换算后的值重算（`gross_margin = gross_profit / revenue`），否则比率失真。这在 `compute_derived` 里已有逻辑，换算后重跑一次即可。

**月报可见性**：`period=month` 时，若该股无月报数据（A股普遍只有季报/年报），返回的 `series` 自然不含月报期——前端据此隐藏「月」按钮。具体：前端在拿到 `period=month` 数据后，检查是否存在非季末非年末的 `report_date`（月份不在 {03,06,09,12}），若无则隐藏「月」按钮。

### 4.3 前端：组件结构

#### 4.3.1 提取可复用叠加层组件 `FinancialOverlayChart`

当前 `SelectableChart`（Financial.tsx 238-302）是单轴、纯财务指标的图表。新增一个**增强版** `FinancialOverlayChart`，在 `SelectableChart` 基础上增加：

1. **叠加层开关行**（可折叠）：一组 chip，控制是否叠加「股价 / 行业指数 / 个股PE / 个股PB / 个股PS」。
2. **双 Y 轴**：左轴 `yAxisId="primary"`（财务指标，沿用现有 `亿/%` 量纲）；右轴 `yAxisId="overlay"`（叠加的股价/指数/估值，独立量纲）。仅当有任意叠加开启时显示右轴。
3. **行业快照标注**：若行业 PE/PB 快照可用，在右轴对应位置画一条虚线参考线 + 角标「行业 PE=5.1」。

**props 扩展**（在原 SelectableChart 基础上）：
```ts
interface OverlayData {
  // 每个报告期对应的叠加数据，key = report_date
  [report_date: string]: {
    stock_price?: number;      // 个股报告期末收盘价
    industry_index?: number;   // 行业指数报告期末收盘价
    pe?: number; pb?: number; ps?: number;  // 个股估值
  };
}
interface IndustrySnapshot {
  industry: string; sw_code: string;
  pe_ttm: number | null; pb: number | null;
  as_of: string;
}
interface FinancialOverlayChartProps {
  // 原 SelectableChart 的全部 props
  chartId, title, data, metrics, type, selectedKeys, onToggleMetric,
  // 新增
  overlayData?: OverlayData;          // 叠加层时间序列
  industrySnapshot?: IndustrySnapshot | null;  // 行业快照
  overlaySelection: OverlayKey[];      // 当前开启的叠加项
  onToggleOverlay: (key: OverlayKey) => void;
}
type OverlayKey = 'stock_price' | 'industry_index' | 'pe' | 'pb' | 'ps';
```

**现有 `SelectableChart` 保留不动**，`FinancialOverlayChart` 作为它的超集封装（内部组合使用 `SelectableChart` 的指标 chip 行，叠加层单独一行）。这样不破坏现有图表行为，改动可控。

#### 4.3.2 新增「估值与市场表现」卡片（方案 A）

在摘要 Tab 顶部（或独立 Tab「估值」）新增一个专门卡片：

```
┌─ 估值与市场表现 [行业: 银行 ▼] ──────────────┐
│ 周期: [月] [季✓] [年]                        │
│ 叠加: [✓股价] [✓行业指数] [✓PE] [✓PB] [ PS] │
│ 行业快照(2026-08-04): PE_TTM=5.1 PB=0.55    │
│                                              │
│   左轴(价格)        右轴(估值倍数)           │
│   ╱╲   ╱╲          ─ ─ ─ ─ ─                │
│  ╱  ╲ ╱  ╲╱╲      ─ ─ ─ ─ ─                │
│ ╱    ╳      ╲     ┄┄┄┄ 行业PE=5.1(参考线)  │
└──────────────────────────────────────────────┘
```

这个卡片是 `FinancialOverlayChart` 的独立实例。轴定义：**左轴画股价 + 行业指数**（价格量纲，两者量纲接近，共用左轴），**右轴画个股 PE/PB/PS 历史曲线**（估值倍数）+ 行业 PE/PB 参考虚线。卡片内的可选项（metrics）= `[股价, 行业指数]`（可折叠切换是否在左轴显示），叠加层固定画 PE/PB/PS（右轴，可折叠开关）。即：这是一张「估值视角」的图，财务报表科目不在此卡显示（它们在下方各自的卡片里）。

#### 4.3.3 周期切换器组件 `PeriodSwitcher`

```tsx
type Period = 'month' | 'quarter' | 'year';
<PeriodSwitcher value={period} onChange={setPeriod} hasMonthly={hasMonthlyData} />
```

- 三个按钮 `月 / 季 / 年`。
- `hasMonthly=false` 时隐藏「月」按钮（A股个股默认隐藏；若有月报数据则显示）。
- 默认值 `quarter`（季报最常用、必显示）。
- 放置位置：页面顶部全局一个（控制所有财务图表），叠加层卡片内再放一个独立控制估值图的周期。

#### 4.3.4 叠加层应用到所有现有财务图表（方案 B）

把摘要、利润表、资产负债表、现金流的趋势图从 `SelectableChart` 升级为 `FinancialOverlayChart`，传入相同的 `overlayData` / `industrySnapshot`。用户在任何财务图上都能叠加股价/行业指数/估值，直观看到「财报发布 → 股价/估值如何反应」。

### 4.4 前端：数据获取与状态

新增两个 hook（参考 Macro.tsx 的 `useIndexOverlays` 模式）：

```ts
// 1. 拉个股估值历史（按报告期末对齐）
function useStockValuationHistory(symbol, reportDates) {
  // GET /financial/valuation-history/{symbol}?report_dates=...
  // 返回 Map<report_date, {pe, pb, ps, total_mv, trade_date}>
}

// 2. 拉行业估值快照
function useIndustryValuationSnapshot(industrySwCode) {
  // GET /financial/industry-valuation-snapshot?industry=...
}

// 3. 拉股价 + 行业指数 K 线（复用现有 /market/kline，参考 Macro 的 useIndexOverlays）
function usePriceOverlays(symbol, industrySwCode, startDate, endDate) {
  // 并发: /market/kline/{symbol} + /market/kline/{industrySwCode}
  // 按 report_date 取报告期末收盘价，返回 Map<report_date, {stock_price, industry_index}>
}
```

**合并时机**：所有叠加数据在前端合并成一个 `OverlayData` 对象（key = report_date），传给 `FinancialOverlayChart`。合并逻辑：对每个财务 `report_date`，取估值历史里同 key 的点，取价格数据里「≤ report_date 的最近交易日」收盘价。

**请求时机**：
- 财务三大表数据加载后（拿到 `report_dates`），触发估值历史 + 价格叠加请求。
- 行业确定后（从 profile 或用户切换），触发行业快照 + 行业指数 K 线请求。
- 切换周期时只重拉财务数据（`period` 参数变化），叠加数据不变（仍按原始 report_date 对齐）。

---

## 5. 数据流

```
用户选股 → fetchProfile (含 industry)
         ↓
fetchStatements(period=quarter)  ←── 周期切换只改这里
         ↓ 拿到 report_dates[]
         ├── useStockValuationHistory(report_dates) → 估值点
         ├── usePriceOverlays(symbol, industrySw, start, end) → 价格点
         └── useIndustryValuationSnapshot(industrySw) → 行业快照
                              ↓
                   合并成 OverlayData
                              ↓
              FinancialOverlayChart 渲染（双轴 + 叠加层 + 行业参考线）
```

---

## 6. 错误处理与降级

| 场景 | 降级行为 |
|---|---|
| 估值历史接口失败/空 | 隐藏 PE/PB/PS 叠加 chip，主财务图正常 |
| 行业快照接口失败 | 隐藏行业快照行与参考线，提示「行业估值暂不可用」 |
| 个股无行业映射 | 行业下拉默认空，行业指数/快照禁用，股价叠加仍可用 |
| 价格 K 线接口失败 | 隐藏股价/行业指数叠加 chip |
| 单季换算后某期为负（如单季亏损） | 正常显示负值，y 轴自动适应 |
| 某报告期估值缺失（停牌等） | 该点断线，tooltip 显示「—」 |

所有叠加层**独立降级**，任何一项失败不阻塞主财务图表渲染。

---

## 7. 测试策略

### 后端
- **单季换算**：构造一组累计报告期数据（如 Q1=100, H1=250, Q3=400, 年报=500），断言单季 = [100, 150, 150, 100]。覆盖跨年边界（2023Q4 → 2024Q1 单季重置）。
- **存量项不做差**：断言资产负债表字段单季模式下值不变。
- **派生指标重算**：断言单季毛利率 = 单季毛利 / 单季营收，非累计比率。
- **估值历史对齐**：`get_as_of` 返回 ≤ report_date 的最近交易日。
- **行业快照缓存**：1 小时内第二次调用命中缓存。
- **周期过滤**：`period=year` 只返回 12 月期。

### 前端
- **周期切换**：切到「年」后图表只显示年报期；切到「季」显示单季值。
- **叠加层开关**：开/关股价 chip，右轴与股价 Line 出现/消失。
- **月按钮可见性**：无月报数据的股票，「月」按钮不渲染。
- **行业切换**：下拉切换行业后，行业指数线与快照值更新。
- **降级**：mock 接口失败时主图正常、叠加 chip 隐藏。

---

## 8. 实施顺序（建议）

1. **后端周期切换**：`financial_detail_handler` 加 `period` 参数 + 单季换算 + 派生指标重算。单元测试先行。
2. **后端估值历史接口**：`/financial/valuation-history`。
3. **后端行业快照接口**：`/financial/industry-valuation-snapshot` + akshare provider 方法 + 缓存。
4. **前端 `PeriodSwitcher` + 周期切换接线**：先让现有图表支持月/季/年。
5. **前端 `FinancialOverlayChart`**：双轴 + 叠加层组件，先独立验证。
6. **前端 3 个 hook + 数据合并**：估值历史、价格叠加、行业快照。
7. **前端方案 B**：把摘要/利润表/资产负债表/现金流的图升级为 `FinancialOverlayChart`。
8. **前端方案 A**：新增「估值与市场表现」卡片。
9. **联调 + 降级测试**。

---

## 9. 不在本期范围

- 行业 PE/PB 的**历史曲线**（需新建 `sw_index_valuation` 表 + 回补 job，单独立项）。
- 股息率曲线（数据源缺失）。
- 2018 年之前的估值历史（akshare 源上限）。
- TTM 指标计算（当前已有 `pe_ttm` 字段，无需自算）。
- 对比 Tab / 业绩预告 Tab 的改造（本期聚焦趋势图）。
