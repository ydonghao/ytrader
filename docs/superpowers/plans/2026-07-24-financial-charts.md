# 财务报表可视化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `/financial` 页的利润表/资产负债表/现金流 Tab 中，表格上方各加 3 张固定图表（柱状趋势 + 折线趋势 + 饼图构成）。

**Architecture:** 纯前端改动。复用现有 `incomeData`/`balanceData`/`cashflowData`（已在组件内拉取），为每个报表 Tab 新增趋势数据转换 + 3 个 recharts 图表（BarChart/LineChart/PieChart）。不改后端。

**Tech Stack:** React 18 + TypeScript, recharts 2.x（BarChart/LineChart/PieChart/Pie/Cell），CSS（`fin-` 前缀）。

## Global Constraints

- CSS 类名用 `fin-` 前缀（与现有 Financial.css 一致）
- 图表颜色：`#3fb950`(绿)/`#58a6ff`(蓝)/`#d29922`(黄)/`#f85149`(红)/`#bc8cff`(紫)/`#ff7b72`(橙红)
- 图表卡片复用现有 `.fin-chart-card` / `.fin-chart-card__title` 样式
- 数字格式化复用 `fmtYuan`/`fmtPct`/`fmtNum`（已在 helpers 区定义）
- `reportLabel(dateStr)` 已定义（line 119），用于 X 轴标签
- 数据已是升序（`incomeData[0]` 是最新期），趋势图需 `.slice().reverse()` 变升序
- recharts `PieChart`/`Pie`/`Cell` 需要新 import（现有 import 没有）
- 不改后端 API
- TypeScript 严格模式，`eslint src --ext .ts,.tsx`

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `apps/web/src/pages/Financial.tsx` | Modify | import PieChart/Cell + 3 个趋势 useMemo + 3 个 render 函数加图表 |
| `apps/web/src/pages/Financial.css` | Modify | `.fin-statement-charts` 布局样式 + `.fin-pie-*` 样式 |

**组件分解**：所有改动在现有 `Financial` 组件内。3 个报表 render 函数（`renderIncome`/`renderBalance`/`renderCashflow`）各包一个图表区 + 现有表格。

---

### Task 1: import 补全 + 数据转换 + CSS 布局

**Files:**
- Modify: `apps/web/src/pages/Financial.tsx`（import 行 line 14-18 + 新增 3 个 useMemo 趋势数据）
- Modify: `apps/web/src/pages/Financial.css`（新增 `.fin-statement-charts` 布局）

**Interfaces:**
- Produces: `incomeTrend`/`balanceTrend`/`cashflowTrend`（useMemo 数组，供 Task 2/3 使用）+ `PieChart`/`Pie`/`Cell` import（供 Task 3 使用）

- [ ] **Step 1: 补全 recharts import**

在 `Financial.tsx` line 14-18 的 import 块，追加 `PieChart, Pie, Cell`：

```typescript
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, LineChart, Line, ComposedChart,
  PieChart, Pie, Cell,
} from 'recharts';
```

- [ ] **Step 2: 新增 3 个趋势数据 useMemo**

在现有 `trendData`（line 352-360）之后，新增 3 个 useMemo。每个从对应数据提取趋势 + 最新期饼图数据：

```typescript
  // 利润表趋势数据（柱状+折线用，升序）
  const incomeTrend = useMemo(() => {
    return incomeData.slice().reverse().map(r => ({
      label: reportLabel(r.report_date),
      revenue: r.revenue ? r.revenue / 1e8 : null,
      netProfit: r.net_profit ? r.net_profit / 1e8 : null,
      grossMargin: r.gross_margin,
      netMargin: r.net_margin,
    }));
  }, [incomeData]);

  // 利润表最新期费用构成（饼图用）
  const incomePie = useMemo(() => {
    if (!incomeData[0]) return [];
    const r = incomeData[0];
    return [
      { name: '营业成本', value: r.operating_cost || 0 },
      { name: '销售费用', value: r.sell_expense || 0 },
      { name: '管理费用', value: r.admin_expense || 0 },
      { name: '研发费用', value: r.rd_expense || 0 },
      { name: '财务费用', value: r.fin_expense || 0 },
    ].filter(d => d.value > 0);
  }, [incomeData]);

  // 资产负债表趋势数据
  const balanceTrend = useMemo(() => {
    return balanceData.slice().reverse().map(r => ({
      label: reportLabel(r.report_date),
      totalAssets: r.total_assets ? r.total_assets / 1e8 : null,
      totalLiab: r.total_liabilities ? r.total_liabilities / 1e8 : null,
      debtRatio: r.debt_ratio,
    }));
  }, [balanceData]);

  // 资产负债表最新期资产构成（饼图用）
  const balancePie = useMemo(() => {
    if (!balanceData[0]) return [];
    const r = balanceData[0];
    return [
      { name: '货币资金', value: r.monetary_funds || 0 },
      { name: '应收账款', value: r.accounts_receivable || 0 },
      { name: '存货', value: r.inventory || 0 },
      { name: '固定资产', value: r.fixed_assets || 0 },
      { name: '商誉', value: r.goodwill || 0 },
    ].filter(d => d.value > 0);
  }, [balanceData]);

  // 现金流量表趋势数据
  const cashflowTrend = useMemo(() => {
    return cashflowData.slice().reverse().map(r => ({
      label: reportLabel(r.report_date),
      ocf: r.ocf ? r.ocf / 1e8 : null,
      icf: r.icf ? r.icf / 1e8 : null,
      fcf: r.fcf ? r.fcf / 1e8 : null,
    }));
  }, [cashflowData]);

  // 现金流量表最新期构成（饼图用，取绝对值避免负值）
  const cashflowPie = useMemo(() => {
    if (!cashflowData[0]) return [];
    const r = cashflowData[0];
    return [
      { name: '期末现金余额', value: r.cash_end || 0 },
      { name: '经营现金流', value: Math.abs(r.ocf || 0) },
      { name: '投资现金流', value: Math.abs(r.icf || 0) },
      { name: '筹资现金流', value: Math.abs(r.fcf || 0) },
    ].filter(d => d.value > 0);
  }, [cashflowData]);
```

- [ ] **Step 3: 新增 CSS 布局**

在 `Financial.css` 末尾追加：

```css
/* ── 报表 Tab 图表区 ── */
.fin-statement-charts {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 24px;
}
.fin-statement-charts .fin-chart-card {
  flex: 1 1 320px;
  min-width: 300px;
}
.fin-statement-charts .fin-chart-card:nth-child(3) {
  flex: 1 1 100%;
}
@media (max-width: 768px) {
  .fin-statement-charts .fin-chart-card {
    flex: 1 1 100%;
  }
}
.fin-pie-center-label {
  font-size: 13px;
  fill: #8b949e;
  text-anchor: middle;
}
```

- [ ] **Step 4: 验证编译**

```bash
cd frontend/apps/web && node_modules/.bin/rsbuild build 2>&1 | tail -5
```
预期：无 error。`PieChart`/`Pie`/`Cell` 是 recharts 标准导出，不会有 import 错误。

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/pages/Financial.tsx apps/web/src/pages/Financial.css
git commit -m "feat(financial): add imports, trend data, and layout CSS for statement charts"
```

---

### Task 2: 利润表 Tab 图表（柱状+折线+饼图）

**Files:**
- Modify: `apps/web/src/pages/Financial.tsx`（`renderIncome` 函数 line 458-475）

**Interfaces:**
- Consumes: `incomeTrend`/`incomePie`（Task 1 产出）
- Produces: `renderIncome` 返回图表区 + 表格

- [ ] **Step 1: 重写 renderIncome 函数**

将现有 `renderIncome`（line 458-475）替换为以下版本（保留原有 `renderStatementTable` 调用，在其上方加图表区）：

```typescript
  function renderIncome() {
    return (
      <div>
        {/* 图表区 */}
        <div className="fin-statement-charts">
          {/* 图1：营收+净利润柱状趋势 */}
          <div className="fin-chart-card">
            <h3 className="fin-chart-card__title">营收与净利润趋势</h3>
            {incomeTrend.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={incomeTrend} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" />
                  <XAxis dataKey="label" tick={{ fill: '#8b949e', fontSize: 11 }} interval="preserveStartEnd" />
                  <YAxis tick={{ fill: '#8b949e', fontSize: 11 }} tickFormatter={v => `${v}亿`} />
                  <Tooltip contentStyle={{ background: '#111822', border: '1px solid #1e2a3a', borderRadius: 6 }} formatter={(v: number, n: string) => [`${v?.toFixed(2)}亿`, n]} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="revenue" name="营业收入" fill="#3fb950" opacity={0.7} radius={[3, 3, 0, 0]} />
                  <Bar dataKey="netProfit" name="净利润" fill="#58a6ff" opacity={0.7} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="fin-empty">暂无数据</div>}
          </div>

          {/* 图2：毛利率+净利率折线趋势 */}
          <div className="fin-chart-card">
            <h3 className="fin-chart-card__title">利润率趋势（%）</h3>
            {incomeTrend.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={incomeTrend} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" />
                  <XAxis dataKey="label" tick={{ fill: '#8b949e', fontSize: 11 }} interval="preserveStartEnd" />
                  <YAxis tick={{ fill: '#8b949e', fontSize: 11 }} tickFormatter={v => `${v}%`} />
                  <Tooltip contentStyle={{ background: '#111822', border: '1px solid #1e2a3a', borderRadius: 6 }} formatter={(v: number, n: string) => [`${v?.toFixed(2)}%`, n]} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line type="monotone" dataKey="grossMargin" name="毛利率" stroke="#3fb950" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="netMargin" name="净利率" stroke="#d29922" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            ) : <div className="fin-empty">暂无数据</div>}
          </div>

          {/* 图3：最新期费用构成饼图 */}
          <div className="fin-chart-card">
            <h3 className="fin-chart-card__title">费用构成（最新期）</h3>
            {incomePie.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <PieChart>
                  <Pie data={incomePie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label={({ name, percent }) => `${name} ${(percent! * 100).toFixed(0)}%`}>
                    {incomePie.map((_, i) => (
                      <Cell key={i} fill={['#3fb950', '#58a6ff', '#d29922', '#f85149', '#bc8cff'][i % 5]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ background: '#111822', border: '1px solid #1e2a3a', borderRadius: 6 }} formatter={(v: number) => fmtYuan(v)} />
                </PieChart>
              </ResponsiveContainer>
            ) : <div className="fin-empty">暂无数据</div>}
          </div>
        </div>

        {/* 表格 */}
        {renderStatementTable(incomeData, '利润表', [
          ['营业总收入', r => r.revenue],
          ['营业成本', r => r.operating_cost],
          ['毛利润', r => r.gross_profit],
          ['销售费用', r => r.sell_expense],
          ['管理费用', r => r.admin_expense],
          ['研发费用', r => r.rd_expense],
          ['财务费用', r => r.fin_expense],
          ['营业利润', r => r.operating_profit],
          ['净利润', r => r.net_profit],
          ['归母净利润', r => r.net_profit_parent],
          ['扣非净利润', r => r.net_profit_deduct],
          ['基本每股收益(元)', r => r.basic_eps],
          ['毛利率(%)', r => r.gross_margin],
          ['净利率(%)', r => r.net_margin],
        ])}
      </div>
    );
  }
```

- [ ] **Step 2: 验证编译**

```bash
cd frontend/apps/web && node_modules/.bin/rsbuild build 2>&1 | tail -5
```
预期：无 error。

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/pages/Financial.tsx
git commit -m "feat(financial): add bar/line/pie charts to income statement tab"
```

---

### Task 3: 资产负债表 Tab 图表（柱状+折线+饼图）

**Files:**
- Modify: `apps/web/src/pages/Financial.tsx`（`renderBalance` 函数 line 477-492）

**Interfaces:**
- Consumes: `balanceTrend`/`balancePie`（Task 1 产出）

- [ ] **Step 1: 重写 renderBalance 函数**

将现有 `renderBalance`（line 477-492）替换为：

```typescript
  function renderBalance() {
    return (
      <div>
        {/* 图表区 */}
        <div className="fin-statement-charts">
          {/* 图1：总资产+总负债柱状趋势 */}
          <div className="fin-chart-card">
            <h3 className="fin-chart-card__title">总资产与总负债趋势</h3>
            {balanceTrend.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={balanceTrend} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" />
                  <XAxis dataKey="label" tick={{ fill: '#8b949e', fontSize: 11 }} interval="preserveStartEnd" />
                  <YAxis tick={{ fill: '#8b949e', fontSize: 11 }} tickFormatter={v => `${v}亿`} />
                  <Tooltip contentStyle={{ background: '#111822', border: '1px solid #1e2a3a', borderRadius: 6 }} formatter={(v: number, n: string) => [`${v?.toFixed(2)}亿`, n]} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="totalAssets" name="总资产" fill="#3fb950" opacity={0.7} radius={[3, 3, 0, 0]} />
                  <Bar dataKey="totalLiab" name="总负债" fill="#f85149" opacity={0.7} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="fin-empty">暂无数据</div>}
          </div>

          {/* 图2：资产负债率折线趋势 */}
          <div className="fin-chart-card">
            <h3 className="fin-chart-card__title">资产负债率趋势（%）</h3>
            {balanceTrend.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={balanceTrend} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" />
                  <XAxis dataKey="label" tick={{ fill: '#8b949e', fontSize: 11 }} interval="preserveStartEnd" />
                  <YAxis tick={{ fill: '#8b949e', fontSize: 11 }} tickFormatter={v => `${v}%`} />
                  <Tooltip contentStyle={{ background: '#111822', border: '1px solid #1e2a3a', borderRadius: 6 }} formatter={(v: number) => [`${v?.toFixed(2)}%`, '资产负债率']} />
                  <Line type="monotone" dataKey="debtRatio" name="资产负债率" stroke="#58a6ff" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            ) : <div className="fin-empty">暂无数据</div>}
          </div>

          {/* 图3：最新期资产构成饼图 */}
          <div className="fin-chart-card">
            <h3 className="fin-chart-card__title">资产构成（最新期）</h3>
            {balancePie.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <PieChart>
                  <Pie data={balancePie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label={({ name, percent }) => `${name} ${(percent! * 100).toFixed(0)}%`}>
                    {balancePie.map((_, i) => (
                      <Cell key={i} fill={['#3fb950', '#58a6ff', '#d29922', '#f85149', '#bc8cff'][i % 5]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ background: '#111822', border: '1px solid #1e2a3a', borderRadius: 6 }} formatter={(v: number) => fmtYuan(v)} />
                </PieChart>
              </ResponsiveContainer>
            ) : <div className="fin-empty">暂无数据</div>}
          </div>
        </div>

        {/* 表格 */}
        {renderStatementTable(balanceData, '资产负债表', [
          ['货币资金', r => r.monetary_funds],
          ['应收账款', r => r.accounts_receivable],
          ['存货', r => r.inventory],
          ['固定资产合计', r => r.fixed_assets],
          ['商誉', r => r.goodwill],
          ['短期借款', r => r.short_loan],
          ['长期借款', r => r.long_loan],
          ['资产合计', r => r.total_assets],
          ['负债合计', r => r.total_liabilities],
          ['所有者权益', r => r.equity],
          ['归母权益', r => r.equity_parent],
          ['资产负债率(%)', r => r.debt_ratio],
        ])}
      </div>
    );
  }
```

- [ ] **Step 2: 验证编译**

```bash
cd frontend/apps/web && node_modules/.bin/rsbuild build 2>&1 | tail -5
```
预期：无 error。

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/pages/Financial.tsx
git commit -m "feat(financial): add bar/line/pie charts to balance sheet tab"
```

---

### Task 4: 现金流量表 Tab 图表（柱状+折线+饼图）

**Files:**
- Modify: `apps/web/src/pages/Financial.tsx`（`renderCashflow` 函数 line 494-501）

**Interfaces:**
- Consumes: `cashflowTrend`/`cashflowPie`（Task 1 产出）

- [ ] **Step 1: 重写 renderCashflow 函数**

将现有 `renderCashflow`（line 494-501）替换为：

```typescript
  function renderCashflow() {
    return (
      <div>
        {/* 图表区 */}
        <div className="fin-statement-charts">
          {/* 图1：经营/投资/筹资现金流柱状趋势 */}
          <div className="fin-chart-card">
            <h3 className="fin-chart-card__title">现金流趋势（经营/投资/筹资）</h3>
            {cashflowTrend.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={cashflowTrend} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" />
                  <XAxis dataKey="label" tick={{ fill: '#8b949e', fontSize: 11 }} interval="preserveStartEnd" />
                  <YAxis tick={{ fill: '#8b949e', fontSize: 11 }} tickFormatter={v => `${v}亿`} />
                  <Tooltip contentStyle={{ background: '#111822', border: '1px solid #1e2a3a', borderRadius: 6 }} formatter={(v: number, n: string) => [`${v?.toFixed(2)}亿`, n]} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="ocf" name="经营现金流" fill="#3fb950" opacity={0.7} radius={[3, 3, 0, 0]} />
                  <Bar dataKey="icf" name="投资现金流" fill="#58a6ff" opacity={0.7} radius={[3, 3, 0, 0]} />
                  <Bar dataKey="fcf" name="筹资现金流" fill="#d29922" opacity={0.7} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="fin-empty">暂无数据</div>}
          </div>

          {/* 图2：经营现金流净额折线趋势 */}
          <div className="fin-chart-card">
            <h3 className="fin-chart-card__title">经营现金流净额趋势</h3>
            {cashflowTrend.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={cashflowTrend} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3a" />
                  <XAxis dataKey="label" tick={{ fill: '#8b949e', fontSize: 11 }} interval="preserveStartEnd" />
                  <YAxis tick={{ fill: '#8b949e', fontSize: 11 }} tickFormatter={v => `${v}亿`} />
                  <Tooltip contentStyle={{ background: '#111822', border: '1px solid #1e2a3a', borderRadius: 6 }} formatter={(v: number) => [`${v?.toFixed(2)}亿`, '经营现金流']} />
                  <Line type="monotone" dataKey="ocf" name="经营现金流净额" stroke="#3fb950" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            ) : <div className="fin-empty">暂无数据</div>}
          </div>

          {/* 图3：最新期现金构成饼图 */}
          <div className="fin-chart-card">
            <h3 className="fin-chart-card__title">现金构成（最新期）</h3>
            {cashflowPie.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <PieChart>
                  <Pie data={cashflowPie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label={({ name, percent }) => `${name} ${(percent! * 100).toFixed(0)}%`}>
                    {cashflowPie.map((_, i) => (
                      <Cell key={i} fill={['#3fb950', '#58a6ff', '#d29922', '#f85149'][i % 4]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ background: '#111822', border: '1px solid #1e2a3a', borderRadius: 6 }} formatter={(v: number) => fmtYuan(v)} />
                </PieChart>
              </ResponsiveContainer>
            ) : <div className="fin-empty">暂无数据</div>}
          </div>
        </div>

        {/* 表格 */}
        {renderStatementTable(cashflowData, '现金流量表', [
          ['经营活动现金流净额', r => r.ocf],
          ['投资活动现金流净额', r => r.icf],
          ['筹资活动现金流净额', r => r.fcf],
          ['期末现金余额', r => r.cash_end],
        ])}
      </div>
    );
  }
```

- [ ] **Step 2: 验证编译**

```bash
cd frontend/apps/web && node_modules/.bin/rsbuild build 2>&1 | tail -5
```
预期：无 error。

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/pages/Financial.tsx
git commit -m "feat(financial): add bar/line/pie charts to cash flow statement tab"
```

---

### Task 5: 端到端验证

**Files:** 无

- [ ] **Step 1: 验证前端构建 + 运行**

```bash
cd frontend/apps/web && node_modules/.bin/rsbuild build 2>&1 | tail -3
curl -s http://localhost:12000/financial -o /dev/null -w "HTTP %{http_code}"
```
预期：build 无 error，HTTP 200。

- [ ] **Step 2: 验证数据链路**

```bash
# 选一只有完整财务数据的股票验证
curl -s "http://localhost:12100/api/v1/financial/detail/sh600519?statement_type=income&limit=5" | python3 -c "
import sys, json
d = json.load(sys.stdin)
s = d['data']['series']
print(f'sh600519 利润表: {len(s)} 期')
if s:
    r = s[0]
    print(f'  最新: revenue={r.get(\"revenue\")}, net_profit={r.get(\"net_profit\")}, gross_margin={r.get(\"gross_margin\")}')
"
```
预期：返回数据，有 revenue/net_profit/gross_margin 字段。

- [ ] **Step 3: 浏览器验证清单**

在 `http://localhost:12000/financial` 搜索一只股票（如 sh600519），验证：
1. 利润表 Tab：上方有 3 张图（柱状营收净利润 + 折线利润率 + 饼图费用构成），下方有表格
2. 资产负债表 Tab：上方有 3 张图（柱状资产负债 + 折线负债率 + 饼图资产构成），下方有表格
3. 现金流量表 Tab：上方有 3 张图（柱状三流 + 折线经营现金流 + 饼图现金构成），下方有表格
4. 饼图 label 显示科目名+百分比
5. 摘要 Tab 原有图表不受影响

- [ ] **Step 4: Commit（如有微调）**

```bash
git status
# 若有改动：git add -A && git commit -m "fix(financial): e2e adjustments"
```

---

## Self-Review 记录

**Spec 覆盖性**：
- ✅ 利润表 3 张图（柱状营收+净利润 / 折线毛利率+净利率 / 饼图费用构成）→ Task 2
- ✅ 资产负债表 3 张图（柱状资产+负债 / 折线负债率 / 饼图资产构成）→ Task 3
- ✅ 现金流量表 3 张图（柱状三流 / 折线经营现金流 / 饼图现金构成）→ Task 4
- ✅ 图表+表格共存 → 每个 render 函数保留 `renderStatementTable` 调用
- ✅ 不改后端 → 全部用现有 `incomeData`/`balanceData`/`cashflowData`

**Placeholder 扫描**：无 TBD/TODO，所有代码块完整。

**类型一致性**：
- `incomeTrend`/`balanceTrend`/`cashflowTrend` 在 Task 1 定义，Task 2/3/4 使用，字段名一致
- `incomePie`/`balancePie`/`cashflowPie` 在 Task 1 定义，格式 `[{name, value}]`，Task 2/3/4 的 `PieChart` 使用一致
- `StatementRow` 字段名（revenue/net_profit/ocf/icf/fcf 等）与现有定义一致

**已知风险**：
1. 饼图 `label` 用了 TypeScript 非空断言 `percent!`——recharts 的 label 回调类型确实允许这样，但 SWC 编译可能不检查。若 TS 报错，改 `(percent ?? 0)`。
2. 现金流饼图用 `Math.abs()` 处理负值（投资/筹资现金流可能为负）——这是有意设计，饼图需要正值。
3. 部分股票可能财务数据不全（某字段为 null）——`filter(d => d.value > 0)` 过滤掉无效饼图切片。
