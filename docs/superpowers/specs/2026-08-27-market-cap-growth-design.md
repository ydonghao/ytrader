# 市值与业绩增长趋势（指数 + 个股）设计

日期：2026-08-27
状态：待评审
参考：用户提供的直播截图——"沪深300市值与业绩增长趋势"：蓝色柱=总营收
（按报告期），红色折线圆点=总市值，双 Y 轴。本设计将该形态落到指数
（中证系宽基）与个股两层，共用同一图表组件。
前置：`2026-08-18-sw-industry-cross-section-design.md`（成分/截面表模式）、
`2026-08-19-five-forces-design.md`（Panel+Tab 三层范式）。

## 目标

- 指数层：`GET /financial/market-cap-growth/index/{code}?years=10`
  → 营收/归母净利润三口径（单季/累计/TTM）柱数据 + 总市值按报告期末对齐
  的折线数据，一次返回。
- 个股层：`GET /financial/market-cap-growth/stock/{symbol}?years=10`
  → 同形状响应（同一纯函数换算口径）。
- 前端：Indices 页新增"市值与业绩增长趋势"区块（9 指数切换，默认沪深300）；
  Financial 页新增"市值业绩"Tab；两处复用 `MarketCapGrowthChart` 组件。
- 顺带激活两张空壳基础设施：`index_valuation_daily`（宽基估值表，现有
  **零写入方**，Indices 页指数 PE 分位徽章依赖它）与
  `index_financial_quarterly` 的 `scope_type='index'` 分支（现只灌 sw）。

## 非目标（YAGNI）

- 不做历史成分股回溯（中证官网只有最新成分）——历史市值/财务聚合用
  **当前成分近似**，`source='computed'` 标注，幸存者偏差接受并在表注释说明。
- 不做市值线月频/日频切换——参考图口径即报告期末对齐（每季一点）；
  月频序列落库是给估值分位等下游用的，本图只取报告期邻近点。
- 不做深交所/国证系指数（创业板指 399006 等）——csindex 无官方成分，
  不引入新浪成分源（质量不稳）；仅中证系 9 宽基。
- 不做申万行业版图（sw scope 已有 index-financial-agg 覆盖，不重复挂图）。
- 不做港/美股个股——stock_valuation 仅 A 股；非 A 股 symbol 返回空 bars
  + 明确 msg，前端 StateView empty。

## 数据事实（已核实 2026-08-27）

- akshare 1.18.50 `index_stock_cons_weight_csindex(symbol)` 连通正常：
  000300 返回 300 行（成分代码/名称/交易所/权重/快照日）。
- `stock_financial_detail`（financial_full.py:78）：`revenue`/`net_profit_parent`
  固定列，**累计口径**；`get_history(symbol,'income',start,end)` 升序。
- `period_transform.transform_to_quarter`（period_transform.py:80）：累计→
  单季差分，按年分组，流量字段做差；输入输出均为 dict 列表。
- `index_financial_quarterly`（index_financial.py:26）：PK(scope_type,
  scope_code, report_date)，`revenue_sum/net_profit_sum`（**亿**），
  scope_type 已支持 'index'，但只灌了 sw（借 national_team_symbol_sector
  近似，本设计换成真成分）。
- `index_valuation_daily`（index_valuation.py:26）：`total_mv`（亿）列 +
  `upsert_index/bulk_upsert_index/get_index_range` 方法齐全，**无任何调用方**
  （grep 证实）；`sync_sw_index_valuation_daily`/backfill 均只写 sw 表。
- `stock_valuation.total_mv`（valuation.py:38）单位**元**；
  `StockValuationRepository.get_as_of(symbol, date)`（valuation.py:104）点时
  查询；`get_range_batch(symbols, start, end, monthly=True)`（valuation.py:145）
  SQL 层 DISTINCT ON 月度降采样，天然适合成分股市值加总。
- 个股报告期末市值先例：`valuation_history` handler
  （financial_detail_handler.py:403）逐报告期 `get_as_of` 取 pe/pb/total_mv。
- 路由遮蔽教训（financial_router.py:1060-1071 注释）：新路径独立命名
  `/market-cap-growth/...`，与既有端点无前缀包含关系。
- 前端：`IndexFinancialChart.tsx` 为孤儿组件（无引用），ComposedChart 双轴
  柱线同构，可改造；Financial.tsx 现有 13 Tab，Panel 模式自包含（prop:
  symbol + 自带 hook）；Indices.tsx 已有 sh000300→000300 代码映射先例。

## 方案取舍

| 方案 | 结论 |
|---|---|
| A. 成分表+聚合灌数+市值回填+语义化端点（本设计） | **采纳**：口径换算留在后端可单测；指数/个股响应同形；激活两张空表，Indices 页指数分位徽章顺带复活 |
| B. 不加端点，前端拼 index-financial-agg + index-valuation-percentile | 否：成分/灌数反正要做；percentile 端点挪用做普通时序语义错位；TTM 换算逻辑泄漏到前端且两层两套拼法 |
| C. 三口径预计算落表 | 否：换算纯计算轻量（40 期），落库三份冗余，加口径要改表 |

## 后端设计

### 1. 新表 `index_constituent` + 同步 job

`src/infra/database/market/index_constituent.py`（仿 sw_industry_member：
SQLModel 惰性建表 + Repository bulk_upsert/`get_members(index_code)` +
模块级单例工厂）：

- 列：`index_code`(PK, "000300")、`stock_symbol`(PK, "sh600519")、
  `stock_name`、`weight`(%, float)、`as_of_date`(成分快照日)、
  `synced_at`(server_default now)。
- 纯 6 位代码→sh/sz/bj 前缀转换：复制 index_valuation_backfill.py:40 的
  `_to_prefixed_symbol`（10 行纯映射）为 job 模块私有函数，不为此抽公共层。

配置段 `quant_universe.index_constituents`（config.yaml，紧跟 indices 段）：

```yaml
index_constituents:
  - { code: "000300", symbol: "sh000300", name: "沪深300" }
  - { code: "000016", symbol: "sh000016", name: "上证50" }
  - { code: "000905", symbol: "sh000905", name: "中证500" }
  - { code: "000852", symbol: "sh000852", name: "中证1000" }
  - { code: "932000", symbol: "sh932000", name: "中证2000" }
  - { code: "000903", symbol: "sh000903", name: "中证100" }
  - { code: "000010", symbol: "sh000010", name: "上证180" }
  - { code: "000985", symbol: "sh000985", name: "中证全指" }
  - { code: "000688", symbol: "sh000688", name: "科创50" }
```

job `sync_index_constituents()`（新文件 `sync/jobs/index_constituent_sync.py`）：
逐指数调 `ak.index_stock_cons_weight_csindex(code)`，事务内 DELETE 该指数
全部成分行 + bulk INSERT 新快照（全量重灌，成分进出靠删旧行保证）；
单指数失败 log warning 继续。
调度：每周六 06:30（sw_industry_member_sync 06:00 之后）。

### 2. 指数财务聚合 `sync_index_financial_quarterly()`

扩展 `sync/jobs/index_financial_sync.py`：SQL JOIN
`index_constituent × stock_financial_detail(statement_type='income')`，
按 report_date 聚合 `SUM(revenue)/SUM(net_profit_parent)`（元→亿存表，
与表既有口径一致），sample_count=该期有数据的成分股数，写
`index_financial_quarterly(scope_type='index', scope_code=code)`。
全量重算+upsert（幂等）。调度：每周六 07:00（financial_full_sync 05:00
之后）。
- 口径注意：聚合序列存**累计值**；单季差分在聚合层做，新纳入样本的
  报告期会出现一期跳变（与主流行情终端一致），sample_count 暴露给前端。

### 3. 指数市值月度序列 `sync_index_market_cap()`

新 job（同 index_financial_sync.py 或独立文件）：对每指数取
`get_members()` 成分列表 → `StockValuationRepository.get_range_batch(
symbols, start=今天-10年, end=今天, monthly=True)` → 按月末日期
`SUM(total_mv)` 元→亿 → `IndexValuationRepository.bulk_upsert_index`
（只填 total_mv + close 不动，source='computed'）。全量重算幂等。
调度：每周六 07:30（fundamentals 估值同步之后）。
- 单指数 300~2000 成分，SQL DISTINCT ON 月采样，量级可控。

### 4. 纯函数模块 `src/domain/market/fundamental/market_cap_growth.py`

零 IO、dict 进出、不抛异常（模块惯例）。输入序列
`[{report_date: str, revenue: float|None, net_profit: float|None}]`（累计）：

- `to_quarterly(rows)`：委托/复用 `period_transform.transform_to_quarter`
  差分逻辑（年分组，cur−上期累计；年报期=全年值本身）。
- `to_ttm(rows)`：`TTM_t = FY_{t-1} + YTD_t − YTD_{t-1同期}`；依赖期
  （上年年报、上年同期）任一缺失 → 该期 None，不外推。
- `align_mv(monthly_mv, report_dates)`：对每个报告期末取
  `≤ report_date` 的最近月度点，None 安全。

### 5. Handler + 路由

`financial_detail_handler.py` 尾部新增两个函数（1h 内存缓存，键=
(kind, code, years)，仿 `_valpct_cache`）：

- `market_cap_growth_index(code, years=10)`：读
  `index_financial_quarterly.get_series('index', code)` 累计序列 →
  `to_quarterly/to_ttm` → bars；读 `get_index_range(code, …)` 月度市值 →
  `align_mv` → mv_series；指数名从配置段取。
- `market_cap_growth_stock(symbol, years=10)`：`get_history(income)` 累计
  列（revenue/net_profit_parent）→ 同纯函数三口径；mv 用
  `get_as_of(symbol, report_date).total_mv` 元→亿（valuation_history 同构）。

响应（两端点同形）：

```json
{ "code": 0, "data": {
    "kind": "index|stock", "code": "000300|sh600519", "name": "沪深300|贵州茅台",
    "as_of": "2026-08-27",
    "bars": {
      "quarter":     [{"report_date","revenue","net_profit"}],
      "cumulative":  [...], "ttm": [...] },
    "mv_series": [{"report_date", "total_mv"}],
    "sample_count": [{"report_date","count"}]   // 指数版；个股版省略
} }
```

营收/净利/市值统一**亿元**（保留 2 位）。路由（financial_router.py）：

- `GET /market-cap-growth/index/{code}`（router 840 index-financial-agg 邻近）
- `GET /market-cap-growth/stock/{symbol}`

## 前端设计

- `hooks/useMarketCapGrowth.ts`：`useMarketCapGrowth(kind, code, years=10)`
  → `{data, loading, error}`；`GET /financial/market-cap-growth/{kind}/{code}`；
  `json.code===0` 判定（useValuationPercentile 同款）。
- `components/MarketCapGrowthChart.tsx`（改造孤儿 IndexFinancialChart）：
  - recharts `ComposedChart`：x=report_date；左轴 `Bar`（业绩指标，
    `CHART_COLORS[0]` 蓝）；右轴 `Line`+dot（总市值，`CHART_COLORS[2]` 橙，
    避开 up/down 涨跌语义色）；axisProps/gridProps/tooltipProps 全走
    chartTheme。
  - chip 切换组：指标（营收/归母净利润）×口径（单季/累计/TTM）——纯前端
    切换（三口径一次返回），默认营收+单季。
  - props：`{title, data, loading, error}`；StateView 守卫；mv 缺失期
    `connectNulls={false}` 断线。
- `components/MarketCapGrowthPanel.tsx`：自包含（prop: symbol），内用
  hook + Chart（RatiosPanel 模式）。
- `pages/Financial.tsx`：TabType 加 `'marketcapgrowth'`，tabs 数组加
  `{key, label:'市值业绩'}`（估值分位之后），内容分支挂 Panel。
- `pages/Indices.tsx`：`indices__chart-panel` 区块下新增
  「市值与业绩增长趋势」section：9 指数 segmented 选择（配置写死 9 项
  code→name，默认 000300）+ Chart；指数加载失败/无数据时 StateView empty。

## 错误处理

- job 层：单指数成分拉取/聚合失败 → warning + 继续，不阻塞其他指数。
- handler 层：bars 与 mv 双源独立，任一为空仍返回另一侧（前端柱或线空态）；
  全空 → data 里 bars/mv_series 空数组 + 前端 StateView empty（非 error）。
- 纯函数层：None 传播（缺科目/缺期 → 该期 None，recharts 自动跳过）。
- 前端：非 A 股 symbol、未配置指数 → 空态提示文案区分"暂无数据"与
  "不支持该范围"。

## 测试（TDD）

- `tests/domain/market/fundamental/test_market_cap_growth.py`：
  `to_quarterly` 完整年序列手算差分/年报期不差/缺中间期；`to_ttm` 跨年
  （FY+YTD−同期）/缺年报期→None/缺同期→None；`align_mv` 月度点拾取/
  早于首月→None。
- `tests/api/test_market_cap_growth.py`：mock 两个 repo 返回 → 响应形状
  （bars 三口径/mv_series/sample_count）；缓存命中；路由注册回归
  （防遮蔽，同 five-forces 惯例）。
- 既有 `test_period_transform.py` 不回归（若委托则顺带覆盖）。

## 验证

- 新增测试全绿（注意跑子集——全量回归有既有失败，见项目记忆）。
- 冒烟：`uv run python -m src.domain.market.sync.jobs.index_constituent_sync`
  手动灌 000300 → 两个聚合 job → `curl /financial/market-cap-growth/index/000300`
  返回 300 成分近 10 年季度序列；`/stock/sh600519` 同验。
- `pnpm -F web build` EXIT=0；浏览器目检：指数页区块 + 个股 Tab 双轴图
  与参考图同构（蓝柱营收/橙线市值/chip 切换）。

## 预估

表+repo ~120 行；3 个 job ~260 行；纯函数 ~140 行；handler+路由 ~160 行；
前端 Chart+Panel+hook ~300 行 + 两页面挂载 ~60 行；测试 ~300 行。
约 1.5~2 个工作日。
