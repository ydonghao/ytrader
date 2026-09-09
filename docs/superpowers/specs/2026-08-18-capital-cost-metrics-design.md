# 资本成本指标（Capital Cost Metrics）设计

日期：2026-08-18
状态：待评审
前置：`2026-08-18-ratio-analysis-design.md`（ROIC 已上线，本设计为其延伸）；
`2026-08-18-sw-industry-cross-section-design.md`（行业截面表，权益资本成本数据源）。
方法论：肖星《财务分析与决策》经济利润章节（同课程体系）——企业创造价值的判据
是回报率**超过**资本成本，超额部分×投资资本即经济利润。

## 目标

- ratio-analysis 端点新增第五组 **capital_cost 资本成本**，3 个指标：
  1. `invested_capital` 投资资本 = 股东权益 + 短期借款 + 长期借款（期末时点）
  2. `wacc` 加权平均资本成本 = 有息负债/投资资本 × **4.5%** × (1-有效税率)
     + 股东权益/投资资本 × 权益资本成本
  3. `economic_profit` 经济利润 = (ROIC − WACC) × **平均**投资资本
- 权益资本成本 = 个股归属申万行业**最新年报期**截面 `distribution.roe.median`
  （行业平均盈利水平），由 handler 查出后作参数注入纯函数。
- 前端 RatiosPanel 自动渲染新组（groups 随 API 下发），仅补 `yi` 单位分支。

## 非目标（YAGNI）

- 不改已有 ROIC（1166b6f，平均投入资本口径）与新组内 ROIC 展示——避免重复。
- 不做债务成本动态化（LPR 查表/财务费用反推）——固定常量，meta 注明假设。
- 不做 Beta/CAPM 权益成本——按用户口径"行业平均盈利水平"，只用截面 ROE。
- 不做新端点/新 Tab——扩展 ratio-analysis。
- 不做 WACC 敏感性分析（不同债务成本下的经济利润区间）。

## 数据事实（已核实 2026-08-18）

- ROIC 积木已在 `ratio_analysis.py`：`_nopat`（有效税率=所得税/EBIT，
  clamp [0,1]，缺失按 0）、`_invested_capital`（equity+short_loan+long_loan，
  Greenblatt 口径）、`_avg_invested_capital`；科目候选 `ebt`（利润总额，
  含"四、利润总额"变体）、`tax`（所得税费用，含"减："变体）齐备。
- 固定列：`equity`/`short_loan`/`long_loan`（balance 行）均在
  `stock_financial_detail`，ratio-analysis 已内连接 income+balance。
- **口径陷阱（实测）**：截面表 `distribution.roe` 为报告期累计未年化——
  白酒Ⅱ 2026-03-31（最新充足期）median 仅 **3.24%**（Q1 利润≈全年 1/4），
  直接用会严重低估权益成本；**最新年报期** 2025-12-31 median=**7.94%**
  （2024=15.74%、2023=19.25%，随行业景气变化，动态特征合理）。
  → 权益成本必须取**最新年报期**（report_date 以 12-31 结尾且 sample_count≥8）。
- 行业归属与截面查询走 `sw_industry` 仓库既有方法（get_member /
  fetch_sections），二级优先、sample_count≥8、无归属（港美股）→ None。
- 前端 `RatiosPanel.tsx` 的 `RatioUnit`/`fmtVal`/`fmtDelta`/趋势图 Y 轴
  仅支持 x/pct/growth/day——**无 yi**，需补分支（4 处各 1-2 行）。
- 茅台验算基准（1166b6f 实测 + 本次截面）：ROIC≈34.4%、有息负债≈0 →
  WACC≈权益成本 7.94%、经济利润≈(34.4%−7.94%)×平均投资资本。

## 方案取舍

| 方案 | 结论 |
|---|---|
| A. 扩展 ratio_analysis 加第五组，handler 注入权益成本 | **采纳**：ROIC 已在此模块，四指标是同链路；groups 随 API 下发，前端近零改动 |
| B. 新模块 economic_profit.py + 新端点 + 新 Tab | 否：与 ROIC 割裂、门户碎片化，~300 行前端只为 3 个数 |
| C. 并入五力子项目2 | 否：拖到未来项目，现在拿不到；行业截面参数注入模式与五力无耦合 |

## 后端设计

### 1. 纯函数模块 `ratio_analysis.py` 扩展

模块顶部常量：`COST_OF_DEBT = 0.045`（≈5 年期 LPR，课程口径"贷款利率"）。

`GROUPS` 追加 `{"key": "capital_cost", "label": "资本成本"}`（第五组，growth 之后）；
`RATIO_META` 追加 3 行（formula 为静态口径描述）：

| key | label | unit | formula |
|---|---|---|---|
| invested_capital | 投资资本 | yi | 股东权益+短期借款+长期借款（期末，元） |
| wacc | 加权平均资本成本 | pct | 债务权重×4.5%×(1-有效税率)+权益权重×权益成本；权重=期末时点占比；有效税率=所得税/利润总额 clamp[0,1] 缺失按0；权益成本由 handler 注入（行业年报 ROE 中位数） |
| economic_profit | 经济利润 | yi | (ROIC−WACC)×平均投资资本；ROIC 分母同源（平均口径） |

签名扩展（向后兼容）：

```python
def ratio_series(records: list, cost_of_equity: float | None = None) -> dict:
```

- `cost_of_equity=None` → wacc/economic_profit 全期 None（纯函数零 IO 惯例保持，
  既有调用方不破）。
- 单期计算（periods 循环内，`v`=当期字段、`prev`=上期）：
  - `ic = _invested_capital(v)`（期末）；None → 三指标均 None
  - `invested_capital = ic`（元，不 round）
  - 债务权重 = (short+long)/ic、权益权重 = equity/ic（ic>0 守卫，`_div`）
  - 有效税率 = `_nopat` 同款（tax/ebt clamp，缺失 0）——**复用提取的
    `_effective_tax_rate(ebt, tax)` 小函数**（从 `_nopat` 内联逻辑抽出，
    `_nopat` 改调它，行为不变）
  - `wacc = _pct(债务权重×0.045×(1-税率) + 权益权重×cost_of_equity)`
    （cost_of_equity 入参为小数，如 0.0794）
  - `economic_profit = (roic/100 − wacc/100) × _avg_invested_capital(v, prev)`
    （roic 或 avg_ic 为 None → None；结果为元，不 round）

### 2. Handler `ratios()` 扩展（`financial_detail_handler.py`）

在现有 repo 取数后追加权益成本解析（失败不阻断主流程）：

```python
cost_of_equity, coe_note = _resolve_cost_of_equity(symbol)
```

新增私有函数（handler 内）：

```python
def _resolve_cost_of_equity(symbol: str):
    """行业年报 ROE 中位数 → (小数值, 说明)；无归属/无年报截面 → (None, None)。"""
    try:
        from src.infra.database.market.sw_industry import (
            create_sw_industry_repository,
        )
        repo = create_sw_industry_repository()
        m = repo.get_member(symbol)
        if not m:
            return None, None
        for level, code in ((2, m["sw_code_l2"]), (1, m["sw_code_l1"])):
            secs = repo.fetch_sections(code, level, limit=40)
            annual = next(
                (s for s in secs
                 if s["report_date"].endswith("12-31")
                 and (s.get("sample_count") or 0) >= 8),
                None,
            )
            if annual:
                roe = ((annual.get("distribution") or {}).get("roe") or {})
                med = roe.get("median")
                if med is not None:
                    return med / 100.0, (
                        f"权益成本={annual['sw_name']}{level}级"
                        f"({annual['report_date']}年报)ROE中位数{med}%；"
                        f"债务成本假设4.5%"
                    )
    except Exception:  # noqa: BLE001
        return None, None
    return None, None
```

调用处：`result = ratio_series(records, cost_of_equity)`；响应 data 追加
`note: coe_note`（None 时省略字段；无归属时不加 note——港美股 ROIC 照常，
避免误导）。

### 3. 路由

无变化（复用 `/financial/ratio-analysis/{symbol}`）。

## 前端设计

`RatiosPanel.tsx` 补 `yi` 单位（模式抄 CashflowAnalysis spec 的 fmt 约定）：

- `RatioUnit` 类型加 `'yi'`
- `fmtVal`：`if (unit === 'yi') return \`${(v / 1e8).toFixed(2)}亿\``
- `fmtDelta`：yi 分支同 fmtVal 格式（带正负号）
- 趋势图 Y 轴 tickFormatter：yi 时 `(v / 1e8).toFixed(0) + '亿'`
- `useRatios.ts` 的类型注释如有 `RatioUnit` 联合类型同步加 `'yi'`

新组渲染、Δ 列、行点击趋势图均由既有数据驱动逻辑自动生效。

## 错误处理

- 纯函数层：ic None/≤0 → 三指标 None；权益权重+债务权重分母同 ic 守卫；
  roic 或 avg_ic None → 经济利润 None；cost_of_equity None → wacc/EP 全 None。
- Handler 层：权益成本解析整体 try 包裹（截面表未同步/库异常 → None+无 note，
  主指标不受影响）；两表无数据 error 逻辑不变。
- 前端：`periods?.length` 既有守卫覆盖；yi 值可能极大（2e11），fmt 除 1e8 后
  正常显示。

## 测试（TDD）

- `tests/domain/market/fundamental/test_ratio_analysis.py` 追加
  `TestCapitalCost` 类：
  - WACC 手算对照（equity=800、short=100、long=100、ic=1000：债务权重 0.2、
    权益 0.8；税率 25% → 0.2×4.5%×0.75+0.8×8% = 0.675%+6.4% = 7.075%）
  - 税缺失（税率 0）→ 0.2×4.5%+0.8×8% = 7.3%
  - cost_of_equity=None → wacc/economic_profit None、invested_capital 照常
  - 经济利润 = (roic−wacc)×平均 ic 手算（两期 ic 构造）
  - equity None → 三指标 None；ic>0 但 roic None（首期无平均）→ EP None
  - 既有 `_nopat` 行为回归（提取 `_effective_tax_rate` 后不变）
- `tests/api/test_ratios.py` 追加：
  - patch `create_sw_industry_repository` 返回固定 member+sections →
    响应含 capital_cost 组、wacc 非空、note 含"ROE中位数"
  - member None（港美股）→ wacc 全 None、无 note、code=0

## 验证

- `uv run pytest tests/domain/market/fundamental/test_ratio_analysis.py tests/api/test_ratios.py -q` 全绿。
- 冒烟 sh600519：wacc≈7.94%（有息负债≈0）、economic_profit 为正（ROIC 34%≫WACC）、
  note 含"白酒Ⅱ"与"7.94%"。
- 冒烟 hk00700：wacc None、ROIC/invested_capital 照常、无 note。
- `pnpm -F web build` 通过（RatiosPanel yi 分支无类型错）。

## 预估

后端 ~90 行（模块 60 + handler 30）；前端 4 处 ~8 行；测试 ~150 行。
半个工作日内。
