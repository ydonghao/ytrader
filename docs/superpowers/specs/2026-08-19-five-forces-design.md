# 波特五力评分模块 + Financial 页五力 Tab 设计

日期：2026-08-19
状态：待评审
前置：`2026-08-18-sw-industry-cross-section-design.md`（行业截面表，两力因子数据源）；
`2026-08-18-ratio-analysis-design.md`（比率端点，三力量化数据源，本设计将扩充应付账款）；
`2026-08-18-cashflow-analysis-design.md`（收现比）。
方法论：波特五力模型（课程 14 集，宁德时代案例）——五种力量组合决定行业盈利能力；
本设计将定性框架落到已验证的量化指标，遵循案例"从财务结构中找证据"的路径。

## 目标

- 新端点 `GET /financial/five-forces/{symbol}`：五轴评分（0-100，**分越高=环境对
  企业越有利**）+ 每力 3-5 项证据（指标值 + 近 5 年趋势 + 解读文案）+ 总分。
- Financial 页新增"五力分析"Tab：recharts 雷达图 + 五张证据卡片 + 总分徽章。
- 三层范式：纯函数 `five_forces.py`（零 IO，评分/归一/解读）→ handler 串调既有
  四个 handler 内部函数与截面仓库（不重复取数）→ 前端 Panel。

## 非目标（YAGNI）

- 不做港股/美股五力——无行业归属时两力行业因子缺失，端点仍返回三力+降级 note，
  不做海外市场行业映射。
- 不做 LLM 定性补充——纯量化，解读文案为模板化规则生成。
- 不做五力历史雷达回溯——当前快照 + 证据趋势（近 5 期），雷达只看最新。
- 不做替代品产品级定性——研发费用率作代理因子（课程案例口径：研发投入对冲替代）。
- 不动既有 ratio/cashflow/industry-peers 端点响应结构（只增量加科目）。

## 数据事实（已核实 2026-08-19）

- **应付账款**：balance detail 科目实测 `应付账款`（茅台 2025=4.007e9）、
  `应付票据及应付账款`（同值）；固定列无，走 DETAIL_CANDIDATES（与应收
  `accounts_receivable` 固定列不同——应付须从 detail 解析）。
- **研发费用**：income 固定列 `rd_expense`（`_INCOME_MAP` 已有"研发费用"），
  研发费率=rd_expense/revenue 可直接算。
- 截面仓库：`get_member`/`fetch_sections`（含 distribution.roe/gross_margin
  的 mean/median、cr4/hhi、revenue_yoy）与 `fetch_peer_details`（roe 现算）
  均已上线；茅台→白酒Ⅱ801125（19 家，2025 年报 CR4=0.7657）。
- 既有端点内部函数可直接复用：`ratios()`（ratio-analysis，含应收周转天数
  `receivable_days`/毛利率/ROE）、`cashflow_analysis()`（收现比
  `cash_to_revenue`）、`industry_peers()`（sections/peers/target 四块）。
- 归一化所需行业分布：截面 `distribution.{gross_margin,net_margin,roe}` 含
  mean/median/std/p25/p75，可做指标→分位映射。
- ratio-analysis 现 25 比率 5 组（资本成本组刚落地）；应收周转天数公式
  365×平均应收/营收（`receivable_days`，unit=day）——应付镜像同式。

## 方案取舍

| 方案 | 结论 |
|---|---|
| A. 三力量化+两力行业因子（本设计） | **采纳**：每力有≥2个可验证数据因子，雷达五轴完整，证据卡"财务证据佐判"对齐课程案例 |
| B. 加现金转换周期/筹码集中度交叉 | 否：现金转换周期=应收+存货-应付天数可由现有因子线性组合（信息增量小）；筹码集中度是股东结构非五力语义，混入会稀释模型 |
| C. 极简版（雷达+一句话） | 否：丢证据卡片，失课程"找证据"精髓 |

## 后端设计

### 1. ratio-analysis 扩充（增量，先于五力）

`DETAIL_CANDIDATES` 加 `accounts_payable: ["应付账款", "*应付账款",
"应付票据及应付账款", "*应付票据及应付账款"]`；RATIO_META 营运组加两行：
`payable_turnover`（营收/平均应付，unit=x）、`payable_days`（365/周转率，
unit=day）——镜像 `receivable_turnover`/`receivable_days` 实现与测试。
（比率数 25→27；改动局限在 ratio_analysis.py + 其测试，端点结构不变。）

### 2. 纯函数模块 `src/domain/market/fundamental/five_forces.py`

零 IO、dict 进出。签名：

```python
def five_forces(data: dict) -> dict:
    """data = {
      ratios:      ratio-analysis 响应 periods（list，最新在前）,
      cashflow:    cashflow-analysis 响应 periods,
      industry:    industry_peers 响应 {industry, sections, peers, target},
    } → {
      forces: [{key, label, score: 0-100|None,
                evidence: [{metric, value, unit, trend: [近5期值],
                            interpretation}]}],
      total_score: 0-100|None,
      note?: str,
    }"""
```

**归一化器**：`_score(value, p25, p50, p75, invert=False)`——用行业分布四分位做
0-100 线性映射（≤p25→25、p50→50、≥p75→75 锚点，区间线性，clamp[0,100]）；
`invert=True` 时翻转（应收天数等"越小越好"指标）。历史趋势类因子用
`_trend_score(series)`（近 3 期斜率→0-100，改善=高分）。

**五力公式**（权重和=1；缺失因子剔除后权重重新归一；全缺→score None+note）：

| force | 因子（weight） | 取值 | 方向 |
|---|---|---|---|
| supplier 供应商议价力 | 应付天数趋势(0.4) + 毛利率σ(0.3) + 毛利率vs行业(0.3) | payable_days 近5期趋势；毛利率近5期σ；毛利率 vs 行业 gross_margin.median | 应付越长/毛利越稳/毛利越高→分高 |
| buyer 购买者议价力 | 应收天数趋势(0.35) + 收现比(0.35) + 行业CR4(0.3) | receivable_days 趋势(invert)；cash_to_revenue 最新；cr4 最新 | 应收短/收现高/行业集中→分高 |
| barrier 进入壁垒 | 行业ROE中位(0.4) + 行业HHI(0.3) + 资产规模分位(0.3) | roe.median 最新；hhi 最新；target 资产/营收分位代理 | 行业盈利厚/集中/体量大→分高 |
| substitute 替代品威胁 | 行业营收同比(0.5) + 研发费率(0.5) | revenue_yoy 最新；个股 rd_expense/revenue | 行业增长/研发高→分高 |

（研发费率无行业分布可比——截面表无研发分布，归一化用绝对强度分档：
≥5%→75、2~5%→50、<2%→25 线性映射，科技/医药行业 5% 为高投入阈值；
代替"vs 行业"的错配口径。）
| rivalry 同业竞争格局 | CR4趋势(0.3) + 市占率(0.3) + 毛利率vs行业(0.2) + ROE分位(0.2) | cr4 近5期趋势；target.revenue_share；毛利率 vs 中位；target.percentile_roe | 集中化/份额大/盈利领先→分高 |

**解读文案**：模板化规则（如 supplier："应付账款周转{X}天，占款能力{强/中/弱}；
毛利率{N}年波动σ={s}%，{稳定/波动}→ 供应商议价能力{弱/中/强}"），按因子值
三档取词。总分 = 五力等权（None 力剔除）。

### 3. Handler `five_forces(symbol)`（financial_detail_handler.py 尾部）

依次内部调用（沿用函数内 import 惯例）：
1. `industry_peers(symbol)` → 无归属时 industry=None + note
2. `ratios(symbol, "year", 12)`（年报期，趋势稳定）→ 取 periods
3. `cashflow_analysis(symbol, "year", 12)` → 取 periods（缺收现比科目时容忍）
4. 截面仓库补 sections（若 industry_peers 降级信息不足时兜底）

拼 data dict → `five_forces(data)` → responses.success。
任一子调用失败 → 对应力因子缺失降级（不整体 error）；全部失败 → error。

### 4. 路由

`@router.get("/five-forces/{symbol}")`——注册回归测试（与既有路径互异，
防遮蔽）。

## 前端设计

- `hooks/useFiveForces.ts`：`GET /financial/five-forces/{symbol}`，类型
  `Force/Evidence/FiveForcesData`。
- `components/FiveForcesPanel.tsx`：
  - 雷达图：recharts `RadarChart`（五轴=五力，0-100 域），chartTheme 常量
    （axisProps/gridProps/tooltipProps），A股语义下"面积大=格局优"。
  - 总分徽章 + 每力一张证据卡（卡片=力名+分数+evidence 列表：指标名/值/
    趋势迷你数值/解读），StateView 守卫。
- `pages/Financial.tsx`：tabs 数组加 `{key:'fiveforces', label:'五力分析'}`。

## 错误处理

- 纯函数层：全 None 因子 → 该力 None；σ 计算 n<2 → None；分位映射输入 None
  → None；零除 `_div` 守卫。
- Handler 层：四子调用各自 try 降级；无归属 → supplier/buyer/rivalry 行业因子
  缺失但个股因子仍可算（部分分）+ note"无行业归属，部分因子缺失"。
- 前端：forces?.length 守卫；score None 的力在雷达图按 0 绘制+卡片标"数据不足"。

## 测试（TDD）

- `tests/domain/market/fundamental/test_five_forces.py`：
  `_score` 锚点/翻转/clamp；`_trend_score` 改善/恶化/平坦；五力各力手算对照
  （构造 ratios/cashflow/industry dict）；缺失因子权重再归一；全缺 None+note；
  解读文案三档取词；总分等权剔除 None。
- `tests/api/test_five_forces.py`：mock 四子调用返回值 → 响应五块结构；
  无归属降级；路由注册回归。
- ratio-analysis 扩充：`test_ratio_analysis.py` 加应付周转/天数手算（镜像应收）。

## 验证

- 新增测试全绿 + 既有 ratio/cashflow/industry 测试不回归。
- 冒烟 sh600519：rivalry 应高分（CR4=0.77+份额0.178+毛利分位1.0）；
  supplier 应付天数趋势合理；端点五力俱全、总分在 0-100。
- `pnpm -F web build` EXIT=0。

## 预估

纯函数 ~300 行 + handler ~150 行 + 路由 ~10 行 + ratio 扩充 ~40 行；
前端 ~250 行；测试 ~350 行。约 1.5 个工作日。
