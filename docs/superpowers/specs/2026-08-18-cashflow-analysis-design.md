# 现金流分析（Cashflow Analysis）设计

日期：2026-08-18
状态：待评审
前置：`2026-08-18-ratio-analysis-design.md`（本设计直接镜像其已验证模式）

## 目标

- 新增"现金流分析"Tab：三组 11 个现金流指标的多期矩阵（行=指标、列=报告期，
  最新期在前）+ Δ较上期列 + 行点击趋势图——完全复刻 RatiosPanel 交互。
- 三组指标（仅内连接 income + cashflow 双表，不涉及 balance）：
  - 盈利质量 profit_quality：净现比 / 收现比 / FCF率
  - 增长趋势 growth：OCF同比 / FCF同比 / 净利润同比（交叉验证背离）
  - 现金流结构 structure：经营净额 / 投资净额 / 筹资净额 / 资本开支 / 资本开支强度
- A股 / 港股 / 美股统一支持，缺科目优雅降级（None → 前端显示"—"）。

## 非目标（YAGNI）

- 不做诊断图表（净利润 vs OCF 对比柱图、四象限阶段图）——已否决；
  quality.py 的单期 `cash_flow_stage` 保持不动。
- 不做偿债覆盖组（现金流利息保障 / 现金流量比率）——需三表连接，本次不做。
- 不改现有"现金流量表"Tab（保留原始 4 科目折线图 + 饼图）。
- 不改 quality.py / screener / fraud_signals（净现比公式存在一行重复，可接受）。
- 不做单季度化（period_transform 单季差分）——跟随比率分析的累计口径。
- 不抽象通用"指标矩阵引擎"——两个实例不足以证明抽象层合理。

## 数据事实（已核实）

- `stock_financial_detail` 表 `statement_type='cashflow'` 固定列：
  `ocf` / `icf` / `fcf`（**陷阱：是筹资活动净额，不是自由现金流**，quality.py
  有两处警告）/ `capex` / `free_cash_flow`（摄取时 `compute_derived` 已算好
  = `ocf - abs(capex)`，惰性加列）/ `cash_end`。
- income 固定列：`net_profit` / `revenue`——净现比、FCF率分母来源。
- 销售商品收到的现金无固定列：从 cashflow `detail` JSONB 候选名解析
  （A股同花顺 `销售商品、提供劳务收到的现金`；港股普遍缺该科目 → None 降级）。
- capex 同花顺宽表存正值、部分源存负值 → 一律 `abs()` 防御（与
  `compute_derived` 的 `free_cash_flow = ocf - abs(capex)` 口径一致）。

## 方案取舍

| 方案 | 结论 |
|---|---|
| A. 新纯函数模块 `cashflow_analysis.py` 镜像 `ratio_analysis.py` | **采纳**：common-size / ratio-analysis 两次验证过的模式，纯增量零回归 |
| B. 扩展 ratio_analysis 加第五组 | 否：矩阵 25 行过长；端点需改三表连接；刚上线功能承回归风险 |
| C. 抽象通用矩阵引擎 | 否：YAGNI；需重构刚上线的 ratio_analysis；第三个实例出现时再抽象 |

## 后端设计

### 1. 纯函数模块 `src/domain/market/fundamental/cashflow_analysis.py`

结构镜像 `ratio_analysis.py`：

- `GROUPS`：`profit_quality 盈利质量` / `growth 增长趋势` / `structure 现金流结构`
- `CASHFLOW_META`：11 条 `{key, label, group, unit, formula}`，groups 随 API
  下发、前端不重复维护定义：

  | key | label | unit | formula |
  |---|---|---|---|
  | ocf_to_profit | 净现比 | x | 经营现金流净额/净利润（净利≤0→None，对齐 quality.py） |
  | cash_to_revenue | 收现比 | x | 销售商品收到的现金/营业总收入 |
  | fcf_margin | FCF率 | pct | 自由现金流/营业总收入 |
  | ocf_yoy | 经营现金流同比 | growth | OCF 同比-1（基数>0） |
  | fcf_yoy | 自由现金流同比 | growth | FCF 同比-1（基数>0） |
  | net_profit_yoy | 净利润同比 | growth | 净利润同比-1（基数>0） |
  | ocf | 经营净额 | yi | 固定列 ocf（元） |
  | icf | 投资净额 | yi | 固定列 icf（元） |
  | financing | 筹资净额 | yi | 固定列 fcf（=筹资活动净额，陷阱列） |
  | capex | 资本开支 | yi | 固定列 capex（元，abs） |
  | capex_to_ocf | 资本开支强度 | pct | abs(capex)/OCF（OCF≤0→None） |

- `DETAIL_CANDIDATES`：仅 `cash_from_sales: ["销售商品、提供劳务收到的现金",
  "*销售商品、提供劳务收到的现金"]`（income 的 revenue/net_profit 走固定列）。
- `FIXED_FIELDS = {revenue, net_profit, ocf, icf, fcf, capex, free_cash_flow,
  cash_end}`。
- `resolve_cashflow_fields(fin, details)`：固定列非 None 优先 → detail 候选名
  兜底（`parse_amount`），返回全字段 dict（None 不抛异常）。
- `cashflow_series(records)`：records 升序 `[{report_date, fin, details}]`；
  输出 `{"groups", "periods"}` periods 降序。口径约定同 ratio_analysis：
  报告期累计不年化；同比需去年同期在场且基数>0；`_div` 守卫（缺失/分母≤0
  → None）；派生比率只在最终赋值处 round 一次；绝对额不 round（前端格式化）。
  - `free_cash_flow` 列为 None 时兜底 `ocf - abs(capex)`（防旧库缺惰性列）。

### 2. Handler `financial_detail_handler.py` 新增 `cashflow_analysis()`

镜像 `ratios()`（line 1837）：

```python
def cashflow_analysis(symbol: str, period: str = "month", limit: int = 12) -> Any:
```

- `repo.get_history(symbol, "income")` + `get_history(symbol, "cashflow")`，
  按 `report_date` 内连接（跳过无交集期，note 提示）。
- 固定列合并进 `fin` dict（income 行优先、cashflow 行补），details=
  `[income_detail, cashflow_detail]`。
- `period="year"` → `filter_year_only`；**先算后截** `periods[:limit]`
  （同比需要全历史前序期）。
- 返回 `{symbol, total_periods, groups, periods, note?}`。

### 3. 路由 `financial_router.py`

`@router.get("/cashflow-analysis/{symbol}")` —— 已核实与现有 31 条路径零冲突
（router:477 遮蔽教训）。必须加路由注册回归测试（路径存在且仅一次、
与 legacy `/ratios/{symbol}` 及 `/ratio-analysis/{symbol}` 互异）。

## 前端设计

### 4. `hooks/useCashflowAnalysis.ts`

克隆 `useRatios.ts`（89 行）：`useEffect` + cancelled-flag fetch
`GET /financial/cashflow-analysis/{symbol}?period=&limit=`，`json.code === 0`
判定；类型 `CashflowUnit = 'x' | 'pct' | 'growth' | 'yi'`，
`CashflowData/Group/Period/Meta` 同构。

### 5. `components/CashflowAnalysisPanel.tsx`

克隆 `RatiosPanel.tsx`（215 行）：

- `fin-period-switcher`（累计/年报两档）；口径脚注：
  "口径：报告期累计未年化；FCF=经营现金流净额-资本开支"。
- 分组矩阵表（`fin-table`，组头行蓝底）+ Δ较上期列（中性色升蓝/降灰，
  现金流指标无 A股涨跌语义）+ 行点击展开趋势 LineChart（`connectNulls`、
  `title=formula`）。
- `fmtVal`/`fmtDelta` 增加 `yi` 分支：`${(v / 1e8).toFixed(2)}亿`
  （API 传原始元，显示层转亿，与 detail 端点惯例一致）；趋势图 Y 轴
  tickFormatter 同步转亿。
- `StateView` loading/error/empty 守卫 + `data.periods?.length` 纵深防御。

### 6. `pages/Financial.tsx`

tabs 数组 ratios 之后插入 `{key: 'cashflowanalysis', label: '现金流分析'}`，
内容区挂 `<CashflowAnalysisPanel symbol={symbol} />`。

## 错误处理

- 纯函数层：全除法 `_div` 守卫；净利≤0 → 净现比 None；收现比科目缺失
  （港股常见）→ None；OCF≤0 → 资本开支强度 None。
- Handler 层：查询异常 → `responses.error`；任一表无数据 → error；
  内连接无交集 → success + note，前端显示空态。
- 前端层：`periods?.length` 守卫防形状不符崩溃（b661566 教训）。

## 测试（TDD）

- `tests/domain/market/fundamental/test_cashflow_analysis.py`（模式抄
  `test_ratio_analysis.py`）：固定列优先/候选名兜底/全缺失；净现比净利≤0；
  收现比缺科目；free_cash_flow 兜底公式；YoY 基数≤0 与首期；periods 降序；
  round 只在终值；capex 负值防御；fcf 陷阱列用作筹资净额。
- `tests/api/test_cashflow_analysis.py`（模式抄 `test_ratios.py`）：
  MagicMock 行 + `patch create_financial_detail_repository`；内连接跳过错期；
  year 过滤；先算后截；响应 code/data 结构；路由注册回归测试。

## 预估

后端 ~250 行模块 + ~50 行 handler + ~10 行路由；前端 ~85 行 hook +
~220 行 Panel + 3 行 Tab；测试 ~280 行。合计约一个工作日内完成。
