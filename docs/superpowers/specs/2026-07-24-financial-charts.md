# 财务报表可视化 — 设计文档

> 日期：2026-07-24
> 状态：待评审
> 范围：升级 `/financial` 页的利润表/资产负债表/现金流 Tab，从纯表格改为图表+表格共存

## 1. 背景与目标

现有 `/financial` 页（`apps/web/src/pages/Financial.tsx`）的三大报表 Tab（利润表/资产负债表/现金流量表）只有表格，没有图表。用户需要多图表类型可视化。

**目标**：在每个报表 Tab 的表格上方，加 3 张固定图表（柱状趋势 + 折线趋势 + 饼图构成），图表与表格共存。

## 2. 现状分析

**已有基础（直接复用）：**
- 数据：`incomeData`/`balanceData`/`cashflowData`（`StatementRow[]`）已在组件内通过 `GET /financial/detail/{symbol}?statement_type=...` 拉取
- 图表库：recharts（`BarChart`/`LineChart`/`PieChart`/`ComposedChart` 均已 import）
- 摘要 Tab 已有柱状+折线图表范例可参照
- CSS：`fin-chart-card`/`fin-chart-card__title` 样式已有

**缺口：**
- 利润表/资产负债表/现金流 Tab 只有 `renderStatementTable()`，返回纯 `FinTable`
- 没有饼图（`PieChart`/`Pie`/`Cell` 需 import，但 recharts 支持）

## 3. 设计

### 3.1 每个 Tab 的 3 张图表

#### 利润表 Tab

| 图 | 类型 | 数据 | 说明 |
|---|---|---|---|
| 图1 | 柱状（BarChart） | 营收+净利润，多期 | X轴=报告期，Y轴=亿元，双色柱并排 |
| 图2 | 折线（LineChart） | 毛利率+净利率，多期 | Y轴=%，双线 |
| 图3 | 饼图（PieChart） | 最新期费用构成 | 营业成本/销售费用/管理费用/研发费用/其他 |

#### 资产负债表 Tab

| 图 | 类型 | 数据 | 说明 |
|---|---|---|---|
| 图1 | 柱状（BarChart） | 总资产+总负债，多期 | 双色柱 |
| 图2 | 折线（LineChart） | 资产负债率，多期 | 单线 |
| 图3 | 饼图（PieChart） | 最新期资产构成 | 货币资金/应收账款/存货/固定资产/商誉/其他 |

#### 现金流量表 Tab

| 图 | 类型 | 数据 | 说明 |
|---|---|---|---|
| 图1 | 柱状（BarChart） | 经营/投资/筹资现金流净额，多期 | 三色柱（正值负值不同色） |
| 图2 | 折线（LineChart） | 经营现金流净额，多期 | 单线 |
| 图3 | 饼图（PieChart） | 最新期现金余额构成 | 期末现金/经营净额/投资净额/筹资净额 |

### 3.2 布局结构

每个报表 Tab 的 render 函数改为：

```typescript
function renderIncome() {
  return (
    <div>
      {/* 图表区 */}
      <div className="fin-statement-charts">
        <div className="fin-chart-card">柱状趋势图</div>
        <div className="fin-chart-card">折线趋势图</div>
        <div className="fin-chart-card">饼图构成</div>
      </div>
      {/* 表格（现有逻辑不变） */}
      {renderStatementTable(incomeData, '利润表', [...])}
    </div>
  );
}
```

3 张图表用 `.fin-statement-charts` flex 容器横向排列（柱+折线并排），饼图在下方或右侧。响应式：窄屏纵向堆叠。

### 3.3 数据转换

现有 `trendData`（摘要 Tab 已有）提取了 `revenue`/`netProfit`/`grossMargin`/`netMargin`。报表 Tab 需要类似转换，但提取不同字段：

```typescript
// 利润表趋势数据
const incomeTrend = incomeData.map(r => ({
  label: reportLabel(r.report_date),
  revenue: r.revenue ? r.revenue / 1e8 : null,     // 转亿元
  netProfit: r.net_profit ? r.net_profit / 1e8 : null,
  grossMargin: r.gross_margin,
  netMargin: r.net_margin,
}));
```

饼图数据从 `incomeData[0]`（最新期）提取。

### 3.4 改动范围

| 文件 | 动作 | 说明 |
|---|---|---|
| `apps/web/src/pages/Financial.tsx` | Modify | 3 个 render 函数加图表 + 趋势数据转换 + PieChart import |
| `apps/web/src/pages/Financial.css` | Modify | `.fin-statement-charts` 布局样式 |

**不改后端**：所有数据已在 `incomeData`/`balanceData`/`cashflowData` 中。

### 3.5 复用现有模式

- 图表卡片：复用 `.fin-chart-card` / `.fin-chart-card__title`
- 柱状/折线写法：复用摘要 Tab 的 `ComposedChart`/`LineChart` 模式
- 数字格式化：复用 `fmtYuan`/`fmtPct`/`fmtNum`
- 颜色：复用现有 `#3fb950`(绿)/`#58a6ff`(蓝)/`#d29922`(黄)/`#f85149`(红)

## 4. 不做的事（YAGNI）

- ❌ 不做图表类型切换器（固定 3 张图）
- ❌ 不做用户自选指标（固定指标组合）
- ❌ 不改后端 API（数据已有）
- ❌ 不加新路由（在现有 `/financial` 页内改）
- ❌ 不做图表导出/下载
