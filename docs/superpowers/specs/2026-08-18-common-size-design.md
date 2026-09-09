# 同型分析（Common-Size Analysis）设计

日期：2026-08-18
状态：已定稿（自主模式：用户未响应澄清问题，按推荐选项与仓库既有范式决策）

## 1. 目标

在财务报表功能中实现同型分析：将三大报表的全部科目（detail JSONB 明细）除以基准值
转为结构百分比，跨报告期对比结构变化，消除规模差异。

- 利润表：科目 ÷ 营业总收入（累计口径，即原始报告期值）
- 资产负债表：科目 ÷ 资产合计
- 现金流量表：科目 ÷ 现金流入总额（经营+投资+筹资三项流入小计之和）

**非目标（YAGNI）**：跨公司对比、单季差分口径（detail 科目无法正确差分）、导出、
存量 FinTable/三表现有 Tab 的任何改动。

## 2. 数据事实（已验证）

- 表 `stock_financial_detail`（akshare 同花顺/东财同步），主键
  `(symbol, report_date, statement_type)`；**所有报告期均存 detail JSONB**
  （茅台实测：income 46 科目 / balance 75 / cashflow 71，值为 float 或 "亿/万" 字符串）。
- 科目名带层级前缀：`一、`=章、`其中：`=子项、`*`=重述强调（与不带 `*` 的同名科目同值）。
  detail dict 的 key 顺序即报表科目顺序。
- 基准科目候选：
  - income：`*营业总收入` / `一、营业总收入`
  - balance：`*资产合计` / `资产合计`
  - cashflow：无总额科目，用 `经营活动现金流入小计` + `投资活动现金流入小计` +
    `筹资活动现金流入小计` 求和；三项任缺则该期无基准。
- 数值解析复用 `src/infra/database/market/financial_full.py::parse_amount`（兼容
  `'547.03亿'` 字符串与 nan/空）。

## 3. 方案取舍

- **A 纯前端计算**：拿 `/financial/detail?period=month` 的 detail 前端算占比。否决：
  detail 仅 month 模式返回、payload 大、无后端测试保障、层级/候选逻辑难复用。
- **B 后端纯函数模块 + API + 前端独立 Tab（采纳）**：与 quality/percentile/dcf 等
  18 个 fundamental 纯函数模块同范式，可单测、可复用。
- **C 只做后端 API**：否决，用户诉求是"在财务报表中实现"（可见）。

## 4. 后端设计

### 4.1 纯函数模块 `src/domain/market/fundamental/common_size.py`

```
BASE_CANDIDATES: dict[statement_type, list[str]]        # 基准科目候选（income/balance）
CASHFLOW_INFLOW_KEYS: list[str]                         # 现金流入三项小计

def _level(name) -> int:
    科目名前缀推断层级：'一、二、三…' → 0（章）；
    '其中：' → 2（子项）；'*' 开头 → 1（重述，通常为合计项）；其余 → 1。

def common_size_rows(detail: dict, statement_type: str) -> Optional[list[dict]]:
    单期计算。返回 [{name, level, raw, pct}]，按 detail 原始顺序；基准行 pct=100.0。
    - raw = parse_amount(v)，None 的科目保留行、raw/pct=None（保留结构完整性）。
    - pct = round(raw / base * 100, 2)。
    - 无基准（候选缺失或基准值 ≤ 0）返回 None。
    - 现金流量表：无总额科目，基准 = `经营活动现金流入小计` + `投资活动现金流入小计` +
    `筹资活动现金流入小计` 求和。**同花顺对无该类流入的公司填 None（如茅台无筹资
    流入），缺失项按 0 计入**；三项全缺/全 0 则该期无基准（实施中修正：最初规则
    "任缺则无基准"导致茅台现金流量表全部跳过）。

def common_size_series(rows: list[SQLModel|dict], statement_type: str) -> dict:
    多期聚合。输入 repo.get_history 的原始行（升序），输出：
    {base_name, periods: [{report_date, base_value, items: [...同上]}]}
    降序（最新在前），跳过无基准期。
```

约定（对齐 quality.py）：缺 key 返 None 不抛异常；不读 DB、不发 HTTP；模块顶部中文
docstring 写明方法论（同型分析/垂直分析定义）与输入输出 key 清单。

### 4.2 Handler + 路由

`financial_detail_handler.py` 新增 `common_size(symbol, statement_type='income',
period='month', limit=12)`：

- `repo.get_history(symbol, statement_type)` 取原始行（累计口径）。
- `period == 'year'` → 复用 `filter_year_only`；其余值一律按原始累计口径处理
  （不提供 quarter：detail 无法正确单季差分，docstring 说明）。
- limit 截最近 N 期后调 `common_size_series`；无数据/无基准返回 `responses.error`
  或空 periods 的 success（与 detail_series 风格一致）。

`financial_router.py` 尾部加薄壳：

```
GET /financial/common-size/{symbol}?statement_type=&period=&limit=
```

响应 data 结构：

```json
{
  "symbol": "sh600519", "statement_type": "income",
  "base_name": "*营业总收入", "total_periods": 87,
  "periods": [{
    "report_date": "2026-03-31", "base_value": 54703000000.0,
    "items": [{"name": "一、营业总收入", "level": 0, "raw": 5.4703e10, "pct": 100.0},
              {"name": "其中：营业成本", "level": 2, "raw": null, "pct": null}]
  }]
}
```

### 4.3 测试

- `tests/domain/market/fundamental/test_common_size.py`：纯函数三件套
  （basic / missing / zero），覆盖三表基准解析、`*` 重述、None 科目行保留、
  cashflow 流入加总、层级推断；pytest.approx。
- `tests/api/test_common_size.py`：MagicMock repo + patch
  `create_financial_detail_repository`（模式抄 test_valuation_percentile_exclude.py），
  断言响应结构、limit 截断、year 过滤、无基准报错。

## 5. 前端设计

### 5.1 Hook `src/hooks/useCommonSize.ts`

`useCommonSize(symbol, statementType, period)` → `{data, loading, error}`；
fetch `/financial/common-size/{symbol}?...`，`json.code === 0` 判定；
类型 `CommonSizeItem {name, level, raw, pct}`、`CommonSizePeriod`、`CommonSizeData`。
模式对齐 useValuationPercentile.ts。

### 5.2 组件 `src/components/CommonSizePanel.tsx`

- 顶部：三表子切换（利润表/资产负债表/现金流量表，pill 按钮）+ 周期切换
  （累计/年报，复用 PeriodSwitcher 或本地小切换）+ 基准说明文案
  （"基准：营业总收入 = 547.03 亿"）。
- 主表：行=科目（按报表顺序，level 缩进 0/1/2 → padding-left 递增；基准行高亮
  pct=100%），列=最近 12 个报告期（横滚），值 = pct（保留 1 位小数）；负值/None
  显示 `—`。列头最新期左侧附"环比 ±pp"着色列（较上一期 pct 差，红涨绿跌遵循
  A股配色 → 但结构占比无涨跌语义，用中性蓝/灰着色 ±）。
- 行交互：点击科目行 → 下方 SelectableChart 画该科目 pct 趋势折线（recharts，
  chartTheme 令牌），默认选中各表第一个非基准科目。
- 数据态：loading/error/空 用现有 StateView。

### 5.3 Financial.tsx 集成

TabType 加 `'commonsize'`，tabs 数组加 `{ key: 'commonsize', label: '同型分析' }`
（置于 cashflow 之后、forecast 之前）；renderCommonSizeTab 渲染 `<CommonSizePanel
symbol={symbol} />`。不改其他 Tab。

## 6. 错误处理

- symbol 无该表数据 → `error("无 {symbol} {statement_type} 数据")`（前端 StateView 展示）。
- 某期基准缺失/为 0 → 该期跳过（不出现在 periods）。
- 所有期都无基准 → periods: [] + note 字段说明。
- detail 为 null 的行 → 跳过。
- 港股/美股：科目名走同一 detail（东财科目），基准候选表按需在模块内扩展候选名
  （本版不专门适配，无基准期自动跳过即天然降级）。

## 7. 验证

- `uv run pytest tests/domain/market/fundamental/test_common_size.py tests/api/test_common_size.py -q`
- 前端 `pnpm -F web build`（或既有 lint/build 命令）通过。
- 手工：`curl /financial/common-size/sh600519?statement_type=income` 对比茅台
  2026-03-31 营业成本占比 ≈ 已知毛利率合理性（毛利率 ≈ 91-92%，营业成本占比 ≈ 8-9%）。
