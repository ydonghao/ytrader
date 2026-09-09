# 波特五力评分模块 + Financial 页五力 Tab 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `/financial/five-forces/{symbol}` 端点（五轴 0-100 评分 + 每力证据 + 总分）与 Financial 页"五力分析"Tab（雷达图 + 证据卡）。

**Architecture:** 纯函数 `five_forces.py`（零 IO：评分/归一/解读）← handler 串调既有 `ratios()`/`cashflow_analysis()`/`industry_peers()` 内部函数 + 截面仓库拼输入 dict → 前端 useFiveForces + FiveForcesPanel（recharts RadarChart）。前置增量：ratio-analysis 加应付账款周转率/天数。

**Tech Stack:** Python 3.12 / FastAPI / pytest / React + TypeScript + recharts。

**Spec:** `docs/superpowers/specs/2026-08-19-five-forces-design.md`（公式权重与口径唯一权威）

## Global Constraints

- 后端工作目录 `backend/`，测试 `uv run pytest <路径> -q`；既有全量回归 52 失败与本计划无关。前端构建 `cd frontend && pnpm -F web build`。
- 纯函数惯例：dict 进出；不读 DB/HTTP；不抛异常；缺失/分母≤0 → None；分越高=环境对企业越有利。
- 五力权重（spec §2 表，**改数字必须同步改 spec**）：
  - supplier：应付天数趋势 0.4 / 毛利率σ 0.3 / 毛利率vs行业 0.3
  - buyer：应收天数趋势 0.35 / 收现比 0.35 / 行业CR4 0.3
  - barrier：行业ROE中位 0.4 / 行业HHI 0.3 / 资产规模分位 0.3
  - substitute：行业营收同比 0.5 / 研发费率 0.5
  - rivalry：CR4趋势 0.3 / 市占率 0.3 / 毛利率vs行业 0.2 / ROE分位 0.2
- 归一化 `_score(v, p25, p50, p75, invert=False)`：≤p25→25、p50→50、≥p75→75 锚点区间线性，clamp[0,100]；invert 翻转（越小越好）。研发费率用绝对分档 `_absolute_score`（三段线性：2%→25、5%→50、≥7.5%→100）。
- **因子分档阈值**（写进 Task 3 代码 docstring，与 spec 权重表同源）：
  - 毛利率稳定性 σ：<3%→75、3~8%→50、>8%→25 线性
  - 收现比 cash_to_revenue：≥1→75、0.8~1→50、<0.8→25 线性
  - 行业 ROE 中位数：<8%→25、8~15%→50、>15%→75 线性
  - HHI：<1500→25、1500~2500→50、>2500→75 线性
  - 行业营收同比 revenue_yoy：<0→25、0~10%→50、>10%→75 线性
  - 市占率 revenue_share：<2%→25、2~10%→50、>10%→75 线性
  - CR4/毛利率vs行业/ROE分位 走 `_score`（行业分布或 0~1 域）
- 缺失因子剔除后权重重新归一；全缺 → 该力 score None + note。总分=五力等权（None 剔除）。
- handler 串调既有内部函数取数（`ratios`/`cashflow_analysis`/`industry_peers`），**不重复写取数 SQL**；子调用失败对应力降级不整体 error。
- 路由 `/financial/five-forces/{symbol}` 注册回归测试（防遮蔽，b661566 教训）。
- 每任务独立 commit；commit 中文前缀惯例。

---

### Task 1: ratio-analysis 扩充——应付账款周转率/天数

**Files:**
- Modify: `backend/src/domain/market/fundamental/ratio_analysis.py`
- Test: `backend/tests/domain/market/fundamental/test_ratio_analysis.py`

**Interfaces:**
- Consumes: 既有 DETAIL_CANDIDATES/avg_prev/_div/_r4/_days 与 receivable 镜像（ratio_analysis.py:140,362-363,420-421）。
- Produces: `accounts_payable` 候选名进 DETAIL_CANDIDATES + FIXED_FIELDS；RATIO_META 营运组加 `payable_turnover`/`payable_days`；ratio_series 输出该两键。比率总数 25→27。

- [ ] **Step 1: 写失败测试（追加 TestPayable 类）**

镜像既有应收测试（在测试文件找 `receivable` 相关断言复制改造）：

```python
class TestPayable:
    """应付账款周转（镜像应收，营运组；五力供应商议价力因子）。"""

    @staticmethod
    def _rec(date, revenue=1000.0, payable_avg_cur=200.0,
             payable_avg_prev=200.0):
        # 应付走 detail 候选名（balance detail），平均余额=期初期末均值
        return {
            "report_date": date,
            "fin": {"revenue": revenue},
            "details": [None, {
                "应付账款": payable_avg_cur,
            }],
        }

    def test_payable_turnover_and_days(self):
        # 两期应付均 200（期初期末），营收 1000 → 周转率 5x、天数 73 天
        recs = [
            {"report_date": "2024-12-31", "fin": {"revenue": 1000.0},
             "details": [None, {"应付账款": 200.0}]},
            {"report_date": "2025-12-31", "fin": {"revenue": 1000.0},
             "details": [None, {"应付账款": 200.0}]},
        ]
        out = ratio_series(recs)
        latest = out["periods"][0]
        assert latest["ratios"]["payable_turnover"] == pytest.approx(5.0)
        assert latest["ratios"]["payable_days"] == pytest.approx(73.0)

    def test_payable_missing_detail_none(self):
        recs = [{"report_date": "2025-12-31", "fin": {"revenue": 1000.0},
                 "details": [None, {}]}]
        out = ratio_series(recs)
        assert out["periods"][0]["ratios"]["payable_turnover"] is None

    def test_payable_candidates_variant(self):
        """候选名'应付票据及应付账款'兜底（茅台实测科目）。"""
        recs = [
            {"report_date": "2024-12-31", "fin": {"revenue": 1000.0},
             "details": [None, {"应付票据及应付账款": 200.0}]},
            {"report_date": "2025-12-31", "fin": {"revenue": 1000.0},
             "details": [None, {"应付票据及应付账款": 200.0}]},
        ]
        out = ratio_series(recs)
        assert out["periods"][0]["ratios"]["payable_turnover"] == \
            pytest.approx(5.0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_ratio_analysis.py -q`
Expected: FAIL——`payable_turnover` 键不存在（KeyError 或断言 None）

- [ ] **Step 3: 实现**

`ratio_analysis.py` 三处：

(a) DETAIL_CANDIDATES 加（accounts_receivable 行附近）：
```python
    "accounts_payable": ["应付账款", "*应付账款", "应付票据及应付账款",
                         "*应付票据及应付账款"],
```
（应付**只**进 DETAIL_CANDIDATES，不进 FIXED_FIELDS——已核实应收
`accounts_receivable` 在 FIXED_FIELDS 是因它同时是固定列（financial_full
_BALANCE_MAP 有"应收账款"），应付无固定列；resolve_metric_fields 对
DETAIL_CANDIDATES 键做候选名解析，固定列 getattr 得 None 后走候选兜底。）

(b) RATIO_META 营运组（receivable_days 行后）加：
```python
    {"key": "payable_turnover", "label": "应付账款周转率",
     "group": "efficiency", "unit": "x",
     "formula": "营业收入/平均应付账款"},
    {"key": "payable_days", "label": "应付账款周转天数",
     "group": "efficiency", "unit": "day",
     "formula": "365/应付账款周转率"},
```

(c) 周转率先算块（ratio_analysis.py:362-368 receivable_turn 附近）加：
```python
        payable_turn = _div(v.get("revenue"),
                            avg_prev("accounts_payable"))
```
ratios dict（receivable_days 行后）加：
```python
            "payable_turnover": _r4(payable_turn),
            "payable_days": _days(payable_turn),
```

(d) 若有断言比率总数的既有测试（22→25 曾更新），同步 25→27。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_ratio_analysis.py -q`
Expected: 全绿（含新 3 条 + 既有回归；若有 meta 计数断言同步后绿）

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/fundamental/ratio_analysis.py backend/tests/domain/market/fundamental/test_ratio_analysis.py
git commit -m "feat(ratio-analysis): 应付账款周转率/天数——镜像应收(应付票据及应付账款候选实测);营运组25→27;五力供应商议价力因子前置"
```

---

### Task 2: 纯函数 five_forces——归一化器 + 证据结构

**Files:**
- Create: `backend/src/domain/market/fundamental/five_forces.py`
- Test: `backend/tests/domain/market/fundamental/test_five_forces.py`

**Interfaces:**
- Consumes: Task 1 的 payable_days（间接，经 handler 传入）。
- Produces: `five_forces(data: dict) -> dict`（签名见 spec §2）；归一化器 `_score`/`_trend_score`/`_absolute_score`；输出结构 `{forces, total_score, note?}`。

- [ ] **Step 1: 写失败测试（归一化器部分）**

```python
"""五力评分纯函数测试。dict 字面量 + pytest.approx。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.domain.market.fundamental.five_forces import (
    _absolute_score,
    _score,
    _trend_score,
)


class TestScoreNormalizer:

    def test_anchor_points(self):
        """p25/p50/p75 → 25/50/75 锚点。"""
        assert _score(10.0, 10.0, 20.0, 30.0) == pytest.approx(25.0)
        assert _score(20.0, 10.0, 20.0, 30.0) == pytest.approx(50.0)
        assert _score(30.0, 10.0, 20.0, 30.0) == pytest.approx(75.0)

    def test_linear_between_anchors(self):
        """p50~p75 中点 → 62.5。"""
        assert _score(25.0, 10.0, 20.0, 30.0) == pytest.approx(62.5)

    def test_clamp_and_invert(self):
        """超出锚点 clamp；invert 翻转（越小越好）。"""
        assert _score(100.0, 10.0, 20.0, 30.0) == pytest.approx(100.0)
        assert _score(0.0, 10.0, 20.0, 30.0) == pytest.approx(0.0)
        # invert：p25→75、p75→25
        assert _score(10.0, 10.0, 20.0, 30.0, invert=True) == \
            pytest.approx(75.0)

    def test_none_and_degenerate(self):
        assert _score(None, 10.0, 20.0, 30.0) is None
        # p25==p75 退化（分布无离散）→ 中位 50
        assert _score(20.0, 15.0, 15.0, 15.0) == pytest.approx(50.0)


class TestTrendScore:

    def test_improving_series_high(self):
        """近3期持续上升 → 高分（应付天数变长=占款增强）。"""
        s = _trend_score([150.0, 140.0, 130.0])  # 最新在前，递增
        assert s > 60.0

    def test_worsening_series_low(self):
        s = _trend_score([100.0, 120.0, 140.0])  # 递减
        assert s < 40.0

    def test_flat_series_mid(self):
        s = _trend_score([100.0, 100.0, 100.0])
        assert s == pytest.approx(50.0)

    def test_insufficient_points_none(self):
        assert _trend_score([100.0]) is None
        assert _trend_score([]) is None


class TestAbsoluteScore:

    def test_rd_intensity_tiers(self):
        """研发费率绝对分档（三段线性：2%→25、5%→50、≥7.5%→100）。"""
        assert _absolute_score(0.05) == pytest.approx(50.0)
        assert _absolute_score(0.035) == pytest.approx(37.5)
        assert _absolute_score(0.06) == pytest.approx(70.0)
        assert _absolute_score(0.01) == pytest.approx(12.5)
        assert _absolute_score(None) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_five_forces.py -q`
Expected: FAIL——`ModuleNotFoundError`

- [ ] **Step 3: 实现归一化器**

创建 `five_forces.py`（模块 docstring 引课程 14 集；零 IO 惯例）：

```python
"""波特五力评分（纯函数）。

课程 14 集宁德时代案例的量化落地：五种力量组合决定行业盈利能力，
"从财务结构中找证据"。分越高=环境对企业越有利。

归一化三器：
- _score: 行业分布四分位锚点映射（p25→25/p50→50/p75→75 区间线性）
- _trend_score: 近3期斜率（改善→高分），用于趋势类因子
- _absolute_score: 绝对强度分档（研发费率等无行业分布可比的指标）
缺失因子剔除后权重重新归一；全缺 → 该力 None。
"""

FORCES_META = [
    {"key": "supplier", "label": "供应商议价能力"},
    {"key": "buyer", "label": "购买者议价能力"},
    {"key": "barrier", "label": "进入壁垒"},
    {"key": "substitute", "label": "替代品威胁"},
    {"key": "rivalry", "label": "同业竞争格局"},
]


def _score(value, p25, p50, p75, invert=False):
    """四分位锚点 0-100 映射（区间线性，clamp）。"""
    if value is None:
        return None
    if p25 is None or p50 is None or p75 is None or p25 == p75:
        return 50.0  # 分布退化→中性
    anchors = [(p25, 25.0), (p50, 50.0), (p75, 75.0)]
    pts = anchors if not invert else [(a, 100.0 - s) for a, s in anchors]
    if value <= pts[0][0]:
        out = pts[0][1]
    elif value >= pts[-1][0]:
        out = pts[-1][1]
    else:
        out = pts[-1][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= value <= x1:
                out = y0 + (value - x0) / (x1 - x0) * (y1 - y0)
                break
    return max(0.0, min(100.0, out))


def _trend_score(series):
    """近3期斜率→0-100（series 最新在前；改善=高分）。
    斜率以均值归一（防量级失真）：slope/mean 映射 [-0.1, +0.1]→[0,100]。"""
    vals = [x for x in (series or [])[:3] if x is not None]
    if len(vals) < 2:
        return None
    # 最新在前：斜率 = (最新-最旧)/(期数-1)，除以均值归一
    mean = sum(vals) / len(vals)
    if mean == 0:
        return 50.0
    slope = (vals[0] - vals[-1]) / (len(vals) - 1)
    norm = slope / abs(mean)
    return max(0.0, min(100.0, (norm + 0.1) / 0.2 * 100.0))


def _absolute_score(value):
    """研发费率绝对分档：<2%→0~25、2~5%→25~50、≥5%→50~100 三段线性。
    （0.035→37.5、0.06→70——测试断言按此公式；锚点 2%→25、5%→50、≥7.5%→100）"""
    if value is None:
        return None
    if value < 0.02:
        return max(0.0, value / 0.02 * 25.0)
    if value < 0.05:
        return 25.0 + (value - 0.02) / 0.03 * 25.0
    return min(100.0, 50.0 + (value - 0.05) / 0.05 * 50.0)
```

（占位：五力计算函数 `five_forces` 在 Task 3 实现——本任务先落地归一化器与 META，保证可独立测试。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_five_forces.py -q`
Expected: 归一化器测试全绿（~10 条）

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/fundamental/five_forces.py backend/tests/domain/market/fundamental/test_five_forces.py
git commit -m "feat(five-forces): 归一化三器——四分位锚点/趋势斜率/绝对分档;FORCES_META五力元数据"
```

---

### Task 3: 纯函数 five_forces——五力计算 + 解读

**Files:**
- Modify: `backend/src/domain/market/fundamental/five_forces.py`（追加 `five_forces` 主函数 + 五力各自计算 + 解读模板）
- Test: `backend/tests/domain/market/fundamental/test_five_forces.py`（追加）

**Interfaces:**
- Consumes: Task 2 的归一化器与 FORCES_META。
- Produces: `five_forces(data)` 完整输出（spec §2 签名），供 Task 4 handler 调用。

- [ ] **Step 1: 写失败测试**

构造完整输入 dict（ratios/cashflow/industry 三块），断言五力 score 手算、证据结构、缺失降级、总分等权：

```python
from src.domain.market.fundamental.five_forces import five_forces


def _ratio_period(rd, payable=140.0, receivable=30.0, gm=91.0,
                  roe=34.0, rd_expense=1.9e8, revenue=1.7e11):
    return {"report_date": rd,
            "ratios": {"payable_days": payable, "receivable_days": receivable,
                       "gross_margin": gm, "roe": roe},
            "values": {"revenue": revenue, "rd_expense": rd_expense}}


def _industry(cr4_latest=0.77, hhi=2600.0, roe_med=15.0, gm_med=70.0,
              rev_yoy=0.08, share=0.178, pct_roe=1.0,
              cr4_series=None):
    return {
        "industry": {"level": 2, "code": "801125", "name": "白酒Ⅱ",
                     "degraded": False},
        "sections": [
            {"report_date": "2025-12-31", "cr4": cr4_latest, "hhi": hhi,
             "revenue_yoy": rev_yoy,
             "distribution": {
                 "gross_margin": {"p25": 55.0, "median": gm_med, "p75": 78.0},
                 "roe": {"p25": 8.0, "median": roe_med, "p75": 22.0},
             }},
        ] + (cr4_series or []),
        "peers": [],
        "target": {"revenue_share": share, "percentile_roe": pct_roe,
                   "percentile_gross_margin": 1.0},
    }


class TestFiveForces:

    def test_rivalry_high_for_leader(self):
        """龙头（高CR4+份额+毛利/ROE领先）→ rivalry 高分。"""
        data = {
            "ratios": [_ratio_period("2025-12-31")],
            "cashflow": [{"report_date": "2025-12-31",
                          "ratios": {"cash_to_revenue": 1.1}}],
            "industry": _industry(cr4_series=[
                {"report_date": "2024-12-31", "cr4": 0.72},
                {"report_date": "2023-12-31", "cr4": 0.68}]),
        }
        out = five_forces(data)
        rivalry = next(f for f in out["forces"] if f["key"] == "rivalry")
        assert rivalry["score"] > 70.0
        assert rivalry["label"] == "同业竞争格局"
        assert len(rivalry["evidence"]) >= 3

    def test_forces_structure_and_total(self):
        data = {
            "ratios": [_ratio_period("2025-12-31")],
            "cashflow": [{"report_date": "2025-12-31",
                          "ratios": {"cash_to_revenue": 1.1}}],
            "industry": _industry(),
        }
        out = five_forces(data)
        assert [f["key"] for f in out["forces"]] == [
            "supplier", "buyer", "barrier", "substitute", "rivalry"]
        scored = [f["score"] for f in out["forces"]
                  if f["score"] is not None]
        assert out["total_score"] == pytest.approx(
            sum(scored) / len(scored), abs=1e-2)
        # 每项证据有 metric/value/interpretation
        ev = out["forces"][0]["evidence"][0]
        assert {"metric", "value", "interpretation"} <= set(ev)

    def test_missing_factor_renormalize(self):
        """cashflow 缺失 → buyer 的收现比因子剔除，权重再归一（不None）。"""
        data = {
            "ratios": [_ratio_period("2025-12-31")],
            "cashflow": [],
            "industry": _industry(),
        }
        out = five_forces(data)
        buyer = next(f for f in out["forces"] if f["key"] == "buyer")
        assert buyer["score"] is not None  # 应收+CR4仍可算

    def test_no_industry_partial(self):
        """无行业归属 → 行业因子缺，个股因子仍算，rivalry/barrier None+note。"""
        data = {"ratios": [_ratio_period("2025-12-31")],
                "cashflow": [], "industry": None}
        out = five_forces(data)
        barrier = next(f for f in out["forces"] if f["key"] == "barrier")
        assert barrier["score"] is None
        assert out["note"]

    def test_interpretation_text_present(self):
        data = {"ratios": [_ratio_period("2025-12-31")],
                "cashflow": [], "industry": _industry()}
        out = five_forces(data)
        for f in out["forces"]:
            for ev in f["evidence"]:
                assert isinstance(ev["interpretation"], str)
                assert len(ev["interpretation"]) > 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_five_forces.py -q`
Expected: FAIL——`ImportError: cannot import name 'five_forces'`

- [ ] **Step 3: 实现五力计算**

在 `five_forces.py` 追加（按 spec §2 权重表；每力一个 `_force_xxx(data)` 返回 `(score, evidence)`；证据含 metric/value/unit/trend/interpretation；`_weighted(parts)` 做缺失剔除再归一；解读 `_interp_xxx` 三档模板）。实现要点：
- supplier：payable_days 近5期（_trend_score）+ 毛利率近5期 σ（σ<3%→75、3~8%→50、>8%→25 线性）+ 毛利率 vs 行业（_score vs gross_margin分布）
- buyer：receivable_days 趋势（_trend_score invert——应收变短=改善）+ cash_to_revenue（_absolute 类：≥1→75、0.8~1→50、<0.8→25）+ CR4（_score 0~1 域）
- barrier：行业 roe.median（_score 绝对：<8%→25、8~15%→50、>15%→75）+ hhi（<1500→25、1500~2500→50、>2500→75）+ target 资产/营收分位
- substitute：revenue_yoy（_score：<0→25、0~10%→50、>10%→75）+ 研发费率（_absolute_score）
- rivalry：cr4 趋势（_trend_score）+ revenue_share（_score：<2%→25、2~10%→50、>10%→75）+ 毛利率vs行业（_score）+ percentile_roe（直接×100）
- 总分等权剔除 None；无 industry → barrier/rivalry 行业因子缺，note 标注

（每个因子的分档阈值写进 spec 附录注释或代码 docstring，保持权重表与 spec 一致。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_five_forces.py -q`
Expected: 全绿（归一化 ~10 + 五力 ~5）

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/fundamental/five_forces.py backend/tests/domain/market/fundamental/test_five_forces.py
git commit -m "feat(five-forces): 五力计算+解读模板——三力量化(应付/应收/CR4趋势)+两力行业因子;缺失因子权重再归一;总分等权剔除None"
```

---

### Task 4: Handler + 路由 + API 测试

**Files:**
- Modify: `backend/src/api/handler/financial_detail_handler.py`（尾部追加）
- Modify: `backend/src/api/router/financial_router.py`
- Test: `backend/tests/api/test_five_forces.py`

**Interfaces:**
- Consumes: Task 3 的 `five_forces(data)`；既有 `ratios`/`cashflow_analysis`/`industry_peers` 内部函数。
- Produces: `five_forces_endpoint(symbol)` handler（注意命名避开纯函数 `five_forces`——handler 命名 `five_forces_report`）+ 路由 `/financial/five-forces/{symbol}`。

- [ ] **Step 1: 写失败测试**

mock 四子调用（patch `ratios`/`cashflow_analysis`/`industry_peers` 于 handler 模块命名空间）→ 断言五块结构、降级、路由注册：

```python
"""five-forces 端点测试（mock 子调用，模式抄 test_industry_peers.py）。"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

RATIOS_RESP = {"code": 0, "data": {"periods": [
    {"report_date": "2025-12-31",
     "ratios": {"payable_days": 140.0, "receivable_days": 30.0,
                "gross_margin": 91.0, "roe": 34.0},
     "values": {"revenue": 1.7e11, "rd_expense": 1.9e8}},
]}}
CASHFLOW_RESP = {"code": 0, "data": {"periods": [
    {"report_date": "2025-12-31", "ratios": {"cash_to_revenue": 1.1}},
]}}
INDUSTRY_RESP = {"code": 0, "data": {
    "industry": {"level": 2, "code": "801125", "name": "白酒Ⅱ",
                 "degraded": False},
    "sections": [{"report_date": "2025-12-31", "cr4": 0.77, "hhi": 2600.0,
                  "revenue_yoy": 0.08,
                  "distribution": {
                      "gross_margin": {"p25": 55.0, "median": 70.0,
                                       "p75": 78.0},
                      "roe": {"p25": 8.0, "median": 15.0, "p75": 22.0}}}],
    "peers": [],
    "target": {"revenue_share": 0.178, "percentile_roe": 1.0,
               "percentile_gross_margin": 1.0},
}}


def _call(industry=INDUSTRY_RESP):
    from src.api.handler.financial_detail_handler import five_forces_report
    with patch(
        "src.api.handler.financial_detail_handler.ratios",
        return_value=_resp(RATIOS_RESP),
    ), patch(
        "src.api.handler.financial_detail_handler.cashflow_analysis",
        return_value=_resp(CASHFLOW_RESP),
    ), patch(
        "src.api.handler.financial_detail_handler.industry_peers",
        return_value=_resp(industry),
    ):
        return json.loads(five_forces_report("sh600519").body)


def _resp(payload):
    class R:  # minimal response-like
        body = json.dumps(payload)
    return R()


def test_full_structure():
    body = _call()
    assert body["code"] == 0
    d = body["data"]
    assert [f["key"] for f in d["forces"]] == [
        "supplier", "buyer", "barrier", "substitute", "rivalry"]
    assert d["total_score"] is not None


def test_no_industry_degrades():
    body = _call(industry={"code": 0, "data": {
        "industry": None, "sections": [], "peers": [], "target": None}})
    assert body["code"] == 0
    assert body["data"]["note"]


def test_route_registered_once():
    from src.api.router.financial_router import router
    paths = [r.path for r in router.routes]
    assert paths.count("/financial/five-forces/{symbol}") == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_five_forces.py -q`
Expected: FAIL——ImportError

- [ ] **Step 3: 实现 handler + 路由**

`financial_detail_handler.py` 尾部：

```python
def five_forces_report(symbol: str) -> Any:
    """波特五力评分（课程 14 集）：三力量化+两力行业因子。

    串调既有 ratios/cashflow_analysis/industry_peers 内部函数取数
    （不重复 SQL），拼 dict 给纯函数 five_forces。子调用失败对应力
    降级不整体 error。
    """
    from src.domain.market.fundamental.five_forces import five_forces

    def _periods(resp):
        try:
            return json.loads(resp.body).get("data", {}).get("periods", [])
        except Exception:  # noqa: BLE001
            return []

    try:
        ratios_resp = ratios(symbol, "year", 12)
        ratio_periods = _periods(ratios_resp)
    except Exception:  # noqa: BLE001
        ratio_periods = []
    try:
        cashflow_periods = _periods(cashflow_analysis(symbol, "year", 12))
    except Exception:  # noqa: BLE001
        cashflow_periods = []
    try:
        ind_body = json.loads(industry_peers(symbol).body).get("data", {})
        industry = ind_body if ind_body.get("industry") else None
    except Exception:  # noqa: BLE001
        industry = None

    if not ratio_periods and industry is None:
        return responses.error(f"{symbol} 无可用财务与行业数据")

    result = five_forces({
        "ratios": ratio_periods,
        "cashflow": cashflow_periods,
        "industry": industry,
    })
    data = {"symbol": symbol, **result}
    return responses.success(data)
```

（注意 handler 内需 `import json`——检查文件顶部是否已导入，无则函数内导入。）
路由：`_industry_peers` 块后加 `/five-forces/{symbol}` → `five_forces_report(symbol)`；
router 顶部 handler 导入块加 `five_forces_report,`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/api/test_five_forces.py -q`
Expected: 3 条绿

- [ ] **Step 5: 冒烟（真库）**

```bash
cd backend && uv run python -c "
from src.api.handler.financial_detail_handler import five_forces_report
import json
d = json.loads(five_forces_report('sh600519').body)['data']
for f in d['forces']: print(f['label'], f['score'])
print('total', d['total_score'])
"
```
Expected: rivalry 高分（龙头）、五力数值 0-100、total 合理

- [ ] **Step 6: Commit**

```bash
git add backend/src/api/handler/financial_detail_handler.py backend/src/api/router/financial_router.py backend/tests/api/test_five_forces.py
git commit -m "feat(five-forces): 五力端点——handler串调ratios/cashflow/industry_peers零重复取数;子调用失败降级;路由注册回归"
```

---

### Task 5: 前端五力 Tab

**Files:**
- Create: `frontend/apps/web/src/hooks/useFiveForces.ts`
- Create: `frontend/apps/web/src/components/FiveForcesPanel.tsx`
- Modify: `frontend/apps/web/src/pages/Financial.tsx`

**Interfaces:**
- Consumes: Task 4 端点。
- Produces: Financial 页"五力分析"Tab（雷达图 + 证据卡 + 总分）。

- [ ] **Step 1: useFiveForces.ts**（克隆 useRatios 模式）

```ts
// GET /financial/five-forces/{symbol}
export interface ForceEvidence {
  metric: string; value: number | null; unit?: string;
  trend?: (number | null)[]; interpretation: string;
}
export interface Force {
  key: string; label: string; score: number | null;
  evidence: ForceEvidence[];
}
export interface FiveForcesData {
  symbol: string; forces: Force[];
  total_score: number | null; note?: string;
}
export function useFiveForces(symbol: string | null) { /* cancelled-flag fetch, code===0 判定 */ }
```

- [ ] **Step 2: FiveForcesPanel.tsx**

- 雷达图：`RadarChart`（recharts）五轴=五力 label，dataKey=score（None→0），
  domain [0,100]，chartTheme 常量（axisProps/gridProps/tooltipProps/CHART_COLORS）。
- 总分徽章 + 五张证据卡（力名+分数+evidence 列表：metric/value(+unit)/
  trend 数值序列/interpretation）。
- StateView loading/error/empty + `data?.forces?.length` 纵深防御。
- score None 的力卡片标"数据不足"，雷达按 0 绘制。

- [ ] **Step 3: Financial.tsx 挂 Tab**

tabs 数组（ratios 后）加 `{key:'fiveforces', label:'五力分析'}`，内容区
`{tab === 'fiveforces' && <FiveForcesPanel symbol={symbol} />}`。

- [ ] **Step 4: 构建验证**

Run: `cd frontend && pnpm -F web build` → EXIT=0

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/hooks/useFiveForces.ts frontend/apps/web/src/components/FiveForcesPanel.tsx frontend/apps/web/src/pages/Financial.tsx
git commit -m "feat(five-forces): 前端五力Tab——雷达图(recharts)+五张证据卡+总分徽章;StateView纵深防御"
```

---

## 收尾

- 5 任务串行：Task 1（应付前置）→ 2（归一化）→ 3（五力计算）→ 4（端点）→ 5（前端）。
- 最终验证：全部新增测试绿 + ratio/cashflow/industry 既有测试不回归 + 茅台冒烟（rivalry 高分）+ `pnpm -F web build` EXIT=0。
- spec 权重表与代码 docstring 同步；改权重须先改 spec。
