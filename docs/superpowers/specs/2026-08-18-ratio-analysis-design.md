# 比率分析（Ratio Analysis）设计

日期：2026-08-18
状态：已定稿（用户确认：四大类全套 14 比率；不做行业对比）

## 1. 目标

在财务报表功能中实现比率分析：跨报表计算 14 个核心财务比率（盈利/偿债/营运/成长
四组），多期矩阵呈现 + 单比率趋势图，消除绝对金额的规模干扰。

**非目标（YAGNI）**：行业对比（无同行批量取数基础设施，值得单独立项）、单季差分、
杜邦分解（quality.py 已有 dupont_decomposition）、现金流量表比率（净现比/收现比
已存在于 quality.py）、导出、改动存量 Tab。

## 2. 数据事实（已验证）

- 数据源与 common-size 同：`stock_financial_detail` 表，repo.get_history(symbol,
  statement_type) 返回行对象含 `.report_date`（date，升序）与 `.detail`（中文科目
  JSONB），**行上同时有英文固定列**。
- 14 个比率所需字段中，大部分有英文固定列（`revenue`/`operating_cost`/
  `net_profit`/`operating_profit`/`total_assets`/`total_liabilities`/`equity`/
  `inventory`/`accounts_receivable`）；**流动资产合计、流动负债合计、利息费用、
  利润总额无固定列**，需从 detail 中文科目提取（A 股同花顺与港股东财科目名有差异，
  用候选名表 + 优雅降级）。
- **不需要现金流量表**：四组比率均只涉及 income + balance 两表。
- A 股利润表为累计口径（Q3 报表 = 前三季累计），资产负债表为时点值。
- 数值解析复用 `parse_amount`（financial_full.py，兼容 `'547.03亿'` 字符串），
  common_size.py 同款 try-import + 本地兜底。

## 3. 方案取舍

- **A 纯前端计算**：否决——后端纯函数可被 screener/CLI 复用，前端重复拉两表明细
  payload 大、无后端测试保障。
- **B 后端纯函数模块 + API + 前端独立 Tab（采纳）**：与 quality/percentile/dcf/
  common-size 等 fundamental 纯函数模块同范式。
- **C 只做后端 API**：否决，用户诉求是"在财务报表中可见"。

## 4. 后端设计

### 4.1 纯函数模块 `src/domain/market/fundamental/ratio_analysis.py`

```
RATIO_META: list[dict]           # 14 比率元数据（key/label/group/unit/formula）
FIELD_CANDIDATES: dict[str, list[str]]
                                 # 语义字段 -> detail 中文候选名（固定列之外的字段）
def resolve_metric_fields(fin: dict, details: list[dict]) -> dict[str, float | None]
    单期字段归一。每个语义字段：英文固定列非 None 优先，否则按候选名在
    details（income_detail + balance_detail）中匹配，parse_amount 解析。
def ratio_series(records: list[dict]) -> dict
    多期计算。输入升序 records：
    [{report_date, fin: {...两表固定列合并...},
      details: [income_detail | None, balance_detail | None]}]
    输出 {"groups": [...分组元数据], "periods": [...]} 降序（最新在前）。
```

约定（对齐 quality.py / common_size.py）：缺 key 返 None 不抛异常；不读 DB、不发
HTTP；模块顶部中文 docstring 写明方法论（比率分析定义、四大类）与口径。

### 4.2 二十二比率清单与口径（教科书补齐版）

| 组 key | 比率（key） | 公式 | 分母口径 |
|---|---|---|---|
| profitability 盈利能力 | gross_margin 毛利率 | (营业总收入−营业成本)÷营业总收入 | 当期 |
| | net_margin 净利率 | 净利润÷营业总收入 | 当期 |
| | roe ROE（净资产报酬率） | 净利润÷净资产 | 平均 |
| | roa ROA（总资产报酬率） | 净利润÷总资产 | 平均 |
| | roic ROIC（投资资本回报率） | EBIT×(1−有效税率)÷投入资本；有效税率=所得税÷利润总额（缺失按 0） | 平均 |
| solvency 偿债能力 | debt_ratio 资产负债率 | 总负债÷总资产 | 当期 |
| | current_ratio 流动比率 | 流动资产合计÷流动负债合计 | 当期 |
| | quick_ratio 速动比率 | (流动资产合计−存货)÷流动负债合计 | 当期 |
| | interest_cover 利息保障倍数 | EBIT÷利息费用 | 当期 |
| efficiency 营运能力 | inventory_turnover 存货周转率 | 营业成本÷存货 | 平均 |
| | inventory_days 存货周转天数 | 365÷存货周转率 | 派生 |
| | receivable_turnover 应收账款周转率 | 营业总收入÷应收账款 | 平均 |
| | receivable_days 应收账款周转天数 | 365÷应收账款周转率 | 派生 |
| | current_asset_turnover 流动资产周转率 | 营业总收入÷流动资产 | 平均 |
| | current_asset_days 流动资产周转天数 | 365÷流动资产周转率 | 派生 |
| | fixed_asset_turnover 固定资产周转率 | 营业总收入÷固定资产 | 平均 |
| | fixed_asset_days 固定资产周转天数 | 365÷固定资产周转率 | 派生 |
| | asset_turnover 总资产周转率 | 营业总收入÷总资产 | 平均 |
| | asset_days 总资产周转天数 | 365÷总资产周转率 | 派生 |
| growth 成长能力 | revenue_growth 营收增长率 | 营业总收入同比−1 | 跨期 |
| | profit_growth 净利润增长率 | 净利润同比−1 | 跨期 |
| | asset_growth 总资产增长率 | 总资产同比−1 | 跨期 |

**教科书补齐（2026-08-18 二次迭代）**：按《股票投资课程》比率清单补上流动资产/
固定资产周转率与全部 5 个周转天数（unit=day），教科书其余条目口径核对本已等价
（利息保障倍数 EBIT=利润总额=净利润+所得税；总资产/净资产报酬率=ROA/ROE；
书本"期末简化"注不采用，维持平均余额公式本身）。固定资产取数：固定列
`fixed_assets`，detail 候选含港股"物业、厂房及设备/物业厂房及设备"（腾讯实测
无顿号变体）。周转天数 round 1 位，率 ≤ 0 或缺失 → None。

**ROIC（2026-08-18 三次迭代）**：口径对齐既有 derived_metrics.py（投入资本=
股东权益+短期借款+长期借款，格林布拉特口径未扣超额现金），升级为 NOPAT 版
（EBIT×(1−有效税率)，税率缺失退化 EBIT/IC）；分母平均投入资本。同花顺科目
带章节前缀（四、利润总额/减：所得税费用）已入候选；腾讯主表无借款科目，
IC 仅含权益为口径上限。实测：茅台 34.40%（税率 25.6%）、腾讯 20.03%。

口径约定：

- **累计不年化**：全部比率按报告期累计值直接计算（Q3 报表算出的 ROE 即"前三季
  ROE"，与东财未年化口径一致；年报视图下即全年值）。前端底部注明。
- **平均余额**：roe/roa/各周转率分母 =（期初+期末）÷2；首期缺期初 → 该期这些
  比率 None。ROE 分母用 `equity`（所有者权益合计，含少数股东权益，合并口径）。
- **利息保障倍数**：EBIT ≈ 利润总额（detail `利润总额`/`税前利润` 候选，缺则用
  固定列 operating_profit 营业利润近似）；利息费用候选顺序 `利息费用`/
  `利息支出`/`财务费用`（financial 处为简化兜底）。
- **同比**：需要去年同期在场，`去年值缺失或 ≤ 0` → None（负基数同比无意义）。
- **守卫**：任一分母缺失/≤0 → 该期该比率 None；结果 round(x, 4)。
- detail 候选名（A股同花顺 + 港股东财兼容，实测后按需扩展）：
  - 流动资产合计：`流动资产合计`/`*流动资产合计`
  - 流动负债合计：`流动负债合计`/`*流动负债合计`
  - 利润总额：`利润总额`/`*利润总额`/`税前利润`/`除税前溢利`
  - 利息费用：`其中：利息费用`/`利息费用`/`利息支出`/`财务费用`
  - 港股收入兜底：`营业额`（common_size BASE_CANDIDATES 已验证腾讯可用）

### 4.3 Handler + 路由

`financial_detail_handler.py` 新增 `ratios(symbol, period='month', limit=12)`：

- `repo.get_history(symbol, 'income')` 与 `(symbol, 'balance')` 各取一次，按
  report_date **内连接**合并为 records（income 行的固定列 + balance 行的固定列
  合入 fin；details 收两表 detail）。
- `period == 'year'` → 复用 `filter_year_only`（对合并后的 records 过滤）。
- **先在全量历史上调 `ratio_series`（平均余额与同比需要前序期），再截最近 limit
  期**——与 common-size 的"先截再算"相反，是本功能的关键差异。
- 任一表无数据 → `responses.error`；periods 空 → success + note。

`financial_router.py` 尾部加薄壳：

```
GET /financial/ratio-analysis/{symbol}?period=&limit=
```

（无 statement_type 参数。**实施修正**：原定路径 `/financial/ratios/{symbol}`
与 router:477 遗留端点同路径，FastAPI 同路径先注册优先导致新路由被遮蔽、
前端拿到旧结构渲染崩溃，改为独立路径 `/ratio-analysis`，遗留端点不动。）响应
data 结构：

```json
{
  "symbol": "sh600519", "total_periods": 12,
  "groups": [{"key": "profitability", "label": "盈利能力",
              "ratios": [{"key": "gross_margin", "label": "毛利率",
                          "unit": "pct", "formula": "(营业总收入-营业成本)/营业总收入"}]}],
  "periods": [{
    "report_date": "2026-06-30",
    "values": {"revenue": 1.2e11, "net_profit": 3.1e10},
    "ratios": {"gross_margin": 91.55, "current_ratio": null}
  }]
}
```

`values` 下发 `resolve_metric_fields` 的完整解析结果（全部语义字段原值，
tooltip/核对用）；groups 元数据由后端统一
下发，前端不重复维护比率定义。

### 4.4 测试

- `tests/domain/market/fundamental/test_ratio_analysis.py`：纯函数测试约 18 个——
  字段解析（固定列优先/detail 候选/字符串金额/全缺失）、单期比率（含除零守卫、
  金融股无营业成本毛利率 None）、平均余额（首期 None、两期平均）、同比（去年缺
  失 None、负基数 None）、利息保障兜底链、港股候选（营业额/除税前溢利）、
  groups 元数据完整性；pytest.approx。
- `tests/api/test_ratios.py`：MagicMock 行 + patch
  `create_financial_detail_repository`（模式抄 test_common_size.py）——两表合并、
  降序、limit 截断、year 过滤、单表无数据报错、periods 空 note。

## 5. 前端设计

### 5.1 Hook `src/hooks/useRatios.ts`

`useRatios(symbol, periodMode: 'month'|'year', limit=12)` → `{data, loading,
error}`；fetch `/financial/ratio-analysis/{symbol}?...`，`json.code === 0` 判定；类型
`RatioMeta {key,label,unit,formula}`、`RatioGroup`、`RatioPeriod {report_date,
values, ratios}`、`RatiosData`。模式对齐 useCommonSize.ts。

### 5.2 组件 `src/components/RatiosPanel.tsx`

- 顶部：周期切换（累计/年报，复用 `fin-period-switcher` pill）+ 说明文案。
- 主表：行按四组分组（组标题行，group label），行=比率 label，列=最近 N 个报告期
  （横滚）+ "Δ较上期"列（升蓝 `#79c0ff`/降灰 `#a1a1a6` 中性配色，与
  CommonSizePanel 一致）。单元格按 unit 格式化：pct→`45.2%`、x→`1.25`、
  growth→`+8.9%`/`−3.2%`；None→`—`。行 hover 提示 formula（title 属性）。
- 行交互：点击比率行 → 下方 recharts LineChart 该比率趋势折线（connectNulls，
  chartTheme 令牌），默认选中 roe。
- 底部口径说明："周转率/ROE 为报告期累计口径未年化；平均余额=(期初+期末)÷2"。
- 数据态：loading/error/空 用 StateView。

### 5.3 Financial.tsx 集成

TabType 加 `'ratios'`，tabs 数组加 `{key: 'ratios', label: '比率分析'}`（置于
同型分析 commonsize 之后、forecast 之前）；`{activeTab === 'ratios' &&
<RatiosPanel symbol={symbol} />}`。不改其他 Tab。

## 6. 错误处理

- income 或 balance 任一无数据 → `error("无 {symbol} financial 数据")`。
- 某期某字段缺失 → 该期相关比率 None（表格 `—`），不扩散到其他比率。
- 全部期 ratios 全 None → periods 照常下发（日期与 values 仍在）。
- detail 为 null 的行 → 该表 detail 按 None 参与候选匹配（固定列仍可用）。
- 港股/美股：候选名表内已含港股东财科目（营业额/除税前溢利），缺项自动降级
  为 None，腾讯/茅台冒烟实测后按需补充候选。

## 7. 验证

- `uv run pytest tests/domain/market/fundamental/test_ratio_analysis.py
  tests/api/test_ratios.py -q` + 全量回归。
- 真库冒烟：茅台 sh600519（A 股，14 比率应基本全有值，毛利率 ≈ 91-92% 交叉
  核对入库列 gross_margin）；腾讯 hk00700（港股候选实测，营业额/除税前溢利）。
- 前端 `pnpm -F web build` 通过。
