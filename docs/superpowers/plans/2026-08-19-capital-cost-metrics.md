# 资本成本指标（Capital Cost Metrics）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 ratio-analysis 端点新增第五组"资本成本"（投资资本 / WACC / 经济利润），权益资本成本由行业截面年报期 ROE 中位数驱动，前端补 `yi` 单位渲染。

**Architecture:** 后端复用已上线的 ROIC 积木（`_nopat`/`_invested_capital`/`_avg_invested_capital`，Greenblatt 口径）扩展纯函数（`ratio_series` 加可选参数 `cost_of_equity`，零 IO 惯例保持）；handler 新增 `_resolve_cost_of_equity` 查申万归属→行业截面**最新年报期** ROE 中位数并注入；前端仅补单位格式化分支（新组由 API 下发的 groups 自动渲染）。

**Tech Stack:** Python 3.12 / pytest / React + TypeScript + recharts / 既有 `sw_industry` 仓库。

**Spec:** `docs/superpowers/specs/2026-08-18-capital-cost-metrics-design.md`（口径唯一权威）

## Global Constraints

- 后端工作目录 `backend/`，测试 `uv run pytest <路径> -q`；既有全量回归 52 失败与本计划无关，只看指定子集。前端构建 `pnpm -F web build`（从 `frontend/` 目录）。
- 纯函数惯例：dict 进 dict 出；不读 DB/HTTP；不抛异常；缺失/分母≤0 → None；派生值仅最终赋值处 round（pct 用既有 `_pct`（×100 round4），元单位不 round）。
- **ROIC 及其分母口径不得变**（`_nopat`/`_invested_capital`/`_avg_invested_capital` 行为回归）；新逻辑只允许提取小函数、调用处等价改写。
- 权益成本=个股归属申万行业**最新年报期**（`report_date` 以 12-31 结尾且 `sample_count≥8`，二级优先否则一级）截面 `distribution.roe.median`；债务成本=模块常量 `COST_OF_DEBT = 0.045`。
- 无行业归属（港美股）/无年报截面 → cost_of_equity=None → wacc/economic_profit 全期 None、invested_capital 照常、**不加 note**（避免误导）；有权益成本时 note 格式：`权益成本={行业名}{级别}级({年报期}年报)ROE中位数{med}%；债务成本假设4.5%`。
- 每个任务完成后独立 commit；commit 用项目惯例中文前缀。

---

### Task 1: 纯函数扩展——第五组三个指标

**Files:**
- Modify: `backend/src/domain/market/fundamental/ratio_analysis.py`
- Test: `backend/tests/domain/market/fundamental/test_ratio_analysis.py`

**Interfaces:**
- Consumes: 既有 `_nopat`/`_invested_capital`/`_avg_invested_capital`/`_pct`/`_div`/`yoy` 与 RATIO_META/GROUPS 结构。
- Produces:
  - `COST_OF_DEBT = 0.045`（模块常量）
  - `_effective_tax_rate(ebt, tax) -> float`（0.0~1.0；ebt 非正或 tax None → 0.0；clamp [0,1]）
  - `ratio_series(records: list, cost_of_equity: float | None = None) -> dict`（新关键字参数，默认 None 保持向后兼容）
  - periods 行新增三个 key：`invested_capital`（元或 None）、`wacc`（pct 或 None）、`economic_profit`（元或 None）
  - RATIO_META 追加 3 行、GROUPS 追加第五组 `{key: "capital_cost", label: "资本成本"}`（growth 之后）

- [ ] **Step 1: 写失败测试（追加到测试文件）**

```python
import pytest  # 文件顶部已有则跳过

from src.domain.market.fundamental.ratio_analysis import (
    COST_OF_DEBT,
    _effective_tax_rate,
    ratio_series,
)


class TestCapitalCost:
    """资本成本组：投资资本/WACC/经济利润（spec 2026-08-18-capital-cost）。"""

    @staticmethod
    def _rec(date, equity=800.0, short=100.0, long=100.0, ebt=200.0,
             tax=50.0, revenue=1000.0, net_profit=150.0):
        return {
            "report_date": date,
            "fin": {
                "revenue": revenue, "net_profit": net_profit,
                "ebt": ebt, "tax": tax,
                "equity": equity, "short_loan": short, "long_loan": long,
                "total_assets": 2000.0, "total_liabilities": 1200.0,
            },
            "details": [None, None],
        }

    def test_effective_tax_rate(self):
        assert _effective_tax_rate(200.0, 50.0) == pytest.approx(0.25)
        assert _effective_tax_rate(200.0, None) == 0.0       # 税缺失按0
        assert _effective_tax_rate(-100.0, 50.0) == 0.0      # ebt非正
        assert _effective_tax_rate(100.0, 200.0) == 1.0      # clamp上限

    def test_wacc_hand_computed(self):
        """ic=800+100+100=1000；债务权重0.2、权益0.8；税率25%
        → 0.2×4.5%×0.75+0.8×8% = 0.675%+6.4% = 7.075%"""
        recs = [self._rec("2024-12-31"), self._rec("2025-12-31")]
        out = ratio_series(recs, cost_of_equity=0.08)
        latest = out["periods"][0]
        assert latest["values"]["invested_capital"] == pytest.approx(1000.0)
        assert latest["ratios"]["wacc"] == pytest.approx(7.075, abs=1e-3)
        # 首期 invested_capital 也为期末时点值（1000），WACC 不受影响
        first = out["periods"][1]
        assert first["values"]["invested_capital"] == pytest.approx(1000.0)
        assert first["ratios"]["wacc"] == pytest.approx(7.075, abs=1e-3)

    def test_wacc_tax_missing(self):
        rec = self._rec("2025-12-31", tax=None)
        out = ratio_series([rec], cost_of_equity=0.08)
        # 0.2×4.5%+0.8×8% = 7.3%
        assert out["periods"][0]["ratios"]["wacc"] == pytest.approx(7.3, abs=1e-3)

    def test_cost_of_equity_none_degrades(self):
        """无权益成本 → wacc/economic_profit None，invested_capital 照常。"""
        out = ratio_series([self._rec("2025-12-31")])
        p = out["periods"][0]
        assert p["values"]["invested_capital"] == pytest.approx(1000.0)
        assert p["ratios"]["wacc"] is None
        assert p["ratios"]["economic_profit"] is None

    def test_economic_profit_hand_computed(self):
        """两期：ic 同值 1000 → 平均 1000；ROIC 与 WACC 之差×平均IC。
        NOPAT=200×0.75=150 → roic=15%；EP=(0.15-0.07075)×1000=79.25"""
        recs = [self._rec("2024-12-31"), self._rec("2025-12-31")]
        out = ratio_series(recs, cost_of_equity=0.08)
        latest = out["periods"][0]
        assert latest["ratios"]["roic"] == pytest.approx(15.0, abs=1e-3)
        assert latest["ratios"]["economic_profit"] == pytest.approx(
            79.25, abs=1e-2)
        # 首期无平均IC → EP None
        assert out["periods"][1]["ratios"]["economic_profit"] is None

    def test_equity_none_all_none(self):
        rec = self._rec("2025-12-31", equity=None)
        out = ratio_series([rec], cost_of_equity=0.08)
        p = out["periods"][0]
        assert p["values"]["invested_capital"] is None
        assert p["ratios"]["wacc"] is None
        assert p["ratios"]["economic_profit"] is None

    def test_groups_and_meta(self):
        out = ratio_series([self._rec("2025-12-31")], cost_of_equity=0.08)
        keys = [g["key"] for g in out["groups"]]
        assert keys[-1] == "capital_cost"
        metas = [m for g in out["groups"] if g["key"] == "capital_cost"
                 for m in g["ratios"]]
        assert [m["key"] for m in metas] == [
            "invested_capital", "wacc", "economic_profit"]
        units = {m["key"]: m["unit"] for m in metas}
        assert units == {"invested_capital": "yi", "wacc": "pct",
                         "economic_profit": "yi"}

    def test_nopat_behavior_unchanged(self):
        """提取 _effective_tax_rate 后 _nopat 行为回归：200×(1-0.25)=150。"""
        from src.domain.market.fundamental.ratio_analysis import _nopat
        assert _nopat(200.0, 50.0) == pytest.approx(150.0)
        assert _nopat(200.0, None) == pytest.approx(200.0)
        assert _nopat(None, 50.0) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_ratio_analysis.py -q`
Expected: FAIL——`ImportError: cannot import name 'COST_OF_DEBT'`（既有测试不应受影响；确认失败仅因新 import）

- [ ] **Step 3: 实现**

`ratio_analysis.py` 改动三处：

**(a) 模块常量 + 提取税率函数**（`_nopat` 附近）：

```python
COST_OF_DEBT = 0.045  # 债务资本成本≈5年期LPR（课程口径"贷款利率"）


def _effective_tax_rate(ebt: Optional[float], tax: Optional[float]) -> float:
    """有效税率 = 所得税/EBIT，clamp [0,1]；ebt 非正或税缺失 → 0.0。"""
    if ebt is None or ebt <= 0 or tax is None:
        return 0.0
    return min(max(tax / ebt, 0.0), 1.0)
```

`_nopat` 改为调用它（行为不变）：

```python
def _nopat(ebit: Optional[float],
           tax: Optional[float]) -> Optional[float]:
    """NOPAT = EBIT×(1-有效税率)；有效税率=所得税/EBIT，clamp 到 [0,1]，
    税缺失按 0（退化为 EBIT，同 derived_metrics 口径）。"""
    if ebit is None:
        return None
    return ebit * (1.0 - _effective_tax_rate(ebit, tax))
```

**(b) GROUPS/RATIO_META 追加**（growth 组之后）：

```python
GROUPS: list[dict] = [
    # ...既有五组保持不动...
    {"key": "capital_cost", "label": "资本成本"},
]
```

RATIO_META 追加（注意 invested_capital/economic_profit 为绝对额单位 yi）：

```python
    {"key": "invested_capital", "label": "投资资本", "group": "capital_cost",
     "unit": "yi",
     "formula": "股东权益+短期借款+长期借款（期末时点，元；格林布拉特口径未扣超额现金）"},
    {"key": "wacc", "label": "加权平均资本成本", "group": "capital_cost",
     "unit": "pct",
     "formula": "债务权重×4.5%×(1-有效税率)+权益权重×权益成本；权重=期末时点占比；"
                "有效税率=所得税/利润总额(clamp[0,1]缺失按0)；"
                "权益成本=所属申万行业最新年报期ROE中位数（handler注入）"},
    {"key": "economic_profit", "label": "经济利润", "group": "capital_cost",
     "unit": "yi",
     "formula": "(ROIC-WACC)×平均投资资本；ROIC分母同源（平均口径）；元"},
```

**(c) `ratio_series` 签名与计算循环**：

```python
def ratio_series(records: list, cost_of_equity: Optional[float] = None) -> dict:
```

循环内（`roic` 计算之后、营运能力之前）追加——注意复用已算出的 `ebt_val` 变量（若实现中 EBIT 取值已是局部变量则复用，否则就地重取同一表达式）：

```python
            # 资本成本（肖星《财务分析与决策》经济利润章）
            _ic = _invested_capital(v)
            _avg_ic = _avg_invested_capital(v, prev)
            _roic = _pct(_div(
                _nopat(v.get("ebt") if v.get("ebt") is not None
                       else v.get("operating_profit"), v.get("tax")),
                _avg_ic,
            ))
            if cost_of_equity is None or _ic is None or _ic <= 0:
                _wacc = None
            else:
                _debt_w = _div(_or_zero(v.get("short_loan"))
                               + _or_zero(v.get("long_loan")), _ic)
                _eq_w = _div(v.get("equity"), _ic)
                _tax_r = _effective_tax_rate(
                    v.get("ebt") if v.get("ebt") is not None
                    else v.get("operating_profit"), v.get("tax"))
                if _debt_w is None or _eq_w is None:
                    _wacc = None
                else:
                    _wacc = _pct(_debt_w * COST_OF_DEBT * (1 - _tax_r)
                                 + _eq_w * cost_of_equity)
            if (_wacc is None or _roic is None or _avg_ic is None):
                _ep = None
            else:
                _ep = (_roic / 100.0 - _wacc / 100.0) * _avg_ic
```

然后把循环里原 `"roic"` 行改为复用 `_roic`（避免重复计算且保持一致），并在 ratios dict 中追加：

```python
            "invested_capital": _ic,
            "wacc": _wacc,
            "economic_profit": _ep,
```

注意：`invested_capital`/`economic_profit` 放在 **ratios** dict 但 unit=yi（绝对额）——检查既有输出结构：`periods[i]["values"]` 放原始金额、`periods[i]["ratios"]` 放比率。`invested_capital` 是原始金额语义 → 放 `values`；`wacc`/`economic_profit` 是派生 → 放 `ratios`。以既有结构为准（测试断言按此写）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/fundamental/test_ratio_analysis.py -q`
Expected: 全绿（既有 ~40 + 新增 ~8，以实际计数为准）

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/fundamental/ratio_analysis.py backend/tests/domain/market/fundamental/test_ratio_analysis.py
git commit -m "feat(ratio-analysis): 资本成本组——投资资本/WACC/经济利润;WACC债务成本4.5%常量+权益成本参数注入;有效税率提取复用;_nopat行为回归"
```

---

### Task 2: Handler 注入行业权益成本 + API 测试

**Files:**
- Modify: `backend/src/api/handler/financial_detail_handler.py`（`ratios()` 内）
- Test: `backend/tests/api/test_ratios.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `ratio_series(records, cost_of_equity)`；Task 3 的 `create_sw_industry_repository()`（`get_member`/`fetch_sections`）。
- Produces: `ratios()` 响应 `data` 新增可选 `note` 字段（有权益成本时带行业/中位数说明）。

- [ ] **Step 1: 写失败测试（追加到 test_ratios.py）**

```python
class TestCostOfEquityInjection:

    SECTIONS_801125 = [
        {"sw_code": "801125", "report_date": "2026-06-30", "level": 2,
         "sw_name": "白酒Ⅱ", "sample_count": 2, "revenue_sum": 1e11,
         "net_profit_sum": 4e10, "cr4": None, "cr8": None, "hhi": None,
         "revenue_yoy": None, "distribution": None},
        {"sw_code": "801125", "report_date": "2025-12-31", "level": 2,
         "sw_name": "白酒Ⅱ", "sample_count": 19, "revenue_sum": 9e11,
         "net_profit_sum": 3.4e11, "cr4": 0.77, "cr8": 0.9, "hhi": 2600.0,
         "revenue_yoy": 0.06,
         "distribution": {"gross_margin": {"mean": 70.0},
                          "roe": {"mean": 10.1, "median": 7.939},
                          "net_margin": {"mean": 35.0}}},
    ]

    @staticmethod
    def _sw_repo(member=None, sections=None):
        from unittest.mock import MagicMock
        r = MagicMock()
        r.get_member.return_value = member
        r.fetch_sections.return_value = sections or []
        return r

    def test_annual_median_picked_over_thin_latest(self):
        """最新充足期(2026-06-30 n=2 非年报)被跳过，取 2025-12-31 年报 median。"""
        from src.api.handler.financial_detail_handler import (
            _resolve_cost_of_equity,
        )
        from unittest.mock import patch
        member = {"sw_code_l1": "801080", "sw_code_l2": "801125"}
        repo = self._sw_repo(member, self.SECTIONS_801125)
        with patch(
            "src.infra.database.market.sw_industry"
            ".create_sw_industry_repository", return_value=repo,
        ):
            coe, note = _resolve_cost_of_equity("sh600519")
        assert coe == pytest.approx(0.07939)
        assert "白酒Ⅱ" in note and "7.939" in note and "4.5%" in note

    def test_no_member_returns_none(self):
        """港美股无归属 → (None, None)，不抛异常。"""
        from src.api.handler.financial_detail_handler import (
            _resolve_cost_of_equity,
        )
        from unittest.mock import patch
        with patch(
            "src.infra.database.market.sw_industry"
            ".create_sw_industry_repository",
            return_value=self._sw_repo(None, []),
        ):
            assert _resolve_cost_of_equity("hk00700") == (None, None)

    def test_ratios_no_coe_path(self):
        """无权益成本（未 mock sw 仓库 → 无归属路径）→ wacc None、组仍在。"""
        body = _call(
            [_income_row(dt.date(2024, 12, 31)),
             _income_row(dt.date(2025, 12, 31))],
            [_balance_row(dt.date(2024, 12, 31)),
             _balance_row(dt.date(2025, 12, 31))],
        )
        groups = [g["key"] for g in body["data"]["groups"]]
        assert "capital_cost" in groups
        assert body["data"]["periods"][0]["ratios"]["wacc"] is None

    def test_ratios_with_coe_note(self):
        """有权益成本 → wacc 非 None + note 含行业与假设。"""
        from unittest.mock import MagicMock, patch
        from src.api.handler.financial_detail_handler import ratios
        fin_repo = MagicMock()
        fin_repo.get_history.side_effect = (
            lambda sym, st: (
                [_income_row(dt.date(2024, 12, 31)),
                 _income_row(dt.date(2025, 12, 31))]
                if st == "income" else
                [_balance_row(dt.date(2024, 12, 31)),
                 _balance_row(dt.date(2025, 12, 31))]
            )
        )
        sw_repo = self._sw_repo(
            {"sw_code_l1": "801080", "sw_code_l2": "801125"},
            self.SECTIONS_801125,
        )
        with patch(
            "src.infra.database.market.financial_full"
            ".create_financial_detail_repository", return_value=fin_repo,
        ), patch(
            "src.infra.database.market.sw_industry"
            ".create_sw_industry_repository", return_value=sw_repo,
        ):
            body = json.loads(ratios("sh600519", "month", 12).body)
        d = body["data"]
        assert d["periods"][0]["ratios"]["wacc"] is not None
        assert "ROE中位数" in d["note"] and "4.5%" in d["note"]
```

（`json`/`pytest` 已在既有 test_ratios.py 顶部导入；`_call`/`_income_row`/`_balance_row` 复用既有。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_ratios.py -q`
Expected: FAIL——`ImportError: cannot import name '_resolve_cost_of_equity'`

- [ ] **Step 3: 实现 handler**

`financial_detail_handler.py` 的 `ratios()` 函数内，在 `result = ratio_series(records)` 一行之前插入权益成本解析，并改调用：

```python
def _resolve_cost_of_equity(symbol: str):
    """行业年报 ROE 中位数 → (小数, 说明note)；无归属/无年报截面 → (None, None)。

    年报期口径：截面 ROE 为报告期累计未年化，季度期会低估
    （实测 Q1 中位数≈全年 1/4），必须取 12-31 年报期且 sample_count≥8。
    二级优先，无年报期截面时降一级。整体 try 包裹——解析失败不阻断主指标。
    """
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
                        f"权益成本={annual['sw_name']}"
                        f"({'一级' if level == 1 else '二级'}"
                        f"{annual['report_date']}年报)ROE中位数{med}%；"
                        f"债务成本假设4.5%"
                    )
    except Exception:  # noqa: BLE001
        return None, None
    return None, None
```

`ratios()` 内修改：

```python
    cost_of_equity, coe_note = _resolve_cost_of_equity(symbol)
    result = ratio_series(records, cost_of_equity)
    data = {
        "symbol": symbol,
        "total_periods": len(records),
        "groups": result["groups"],
        "periods": result["periods"][:limit],
    }
    if coe_note:
        data["note"] = coe_note
```

（原 `if not data["periods"]: data["note"] = ...` 分支保留，注意二者可能同时存在时 periods 空态 note 优先——实现时调整顺序：先算 coe_note，最后无 periods 时覆盖为原有文案。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/api/test_ratios.py -q`
Expected: 全绿

- [ ] **Step 5: 冒烟（真库）**

```bash
cd backend && uv run python -c "
from src.api.handler.financial_detail_handler import ratios
import json
d = json.loads(ratios('sh600519', 'year', 3).body)['data']
p = d['periods'][0]
print(p['report_date'], 'roic=', p['ratios']['roic'], 'wacc=', p['ratios']['wacc'],
      'ep=', p['ratios']['economic_profit'])
print('note:', d.get('note'))
"
```
Expected: wacc≈7.9%（白酒Ⅱ 2025 年报 median 7.939%）、ep 为正（roic≈34%≫wacc）、note 含"白酒Ⅱ"与"7.939"

- [ ] **Step 6: Commit**

```bash
git add backend/src/api/handler/financial_detail_handler.py backend/tests/api/test_ratios.py
git commit -m "feat(ratio-analysis): 权益成本行业注入——handler查申万归属→年报期截面ROE中位数(规避季度未年化低估);港美股降级None不加note;note注明行业与假设"
```

---

### Task 3: 前端 yi 单位 + 构建验证

**Files:**
- Modify: `frontend/apps/web/src/hooks/useRatios.ts`（RatioUnit 联合类型）
- Modify: `frontend/apps/web/src/components/RatiosPanel.tsx`（4 处分支）

**Interfaces:**
- Consumes: Task 1 下发的 capital_cost 组（unit=yi）。
- Produces: RatiosPanel 正确渲染 yi 单位值（金额/Δ/趋势图 Y 轴/Tooltip）。

- [ ] **Step 1: 改类型**

`useRatios.ts:12`：

```ts
export type RatioUnit = 'pct' | 'x' | 'growth' | 'day' | 'yi';
```

- [ ] **Step 2: 改 RatiosPanel 四处分支**

`fmtVal`（~line 29-35）末尾 `return v.toFixed(2);` 之前插入：

```ts
  if (unit === 'yi') return `${(v / 1e8).toFixed(2)}亿`;
```

`fmtDelta`（~line 37-42）`if (unit === 'day') ...` 之后、默认 `return ...pp` 之前插入：

```ts
  if (unit === 'yi') return `${d > 0 ? '+' : ''}${(d / 1e8).toFixed(2)}亿`;
```

趋势图标题（~line 180）：

```tsx
{selMeta.unit === 'x' ? '' : selMeta.unit === 'day' ? '（天）' : selMeta.unit === 'yi' ? '（亿）' : '（%）'}
```

Y 轴 tickFormatter（~line 192-196）：

```tsx
tickFormatter={(v: number) =>
  selMeta.unit === 'x' || selMeta.unit === 'day'
    ? String(v)
    : selMeta.unit === 'yi'
      ? `${(v / 1e8).toFixed(0)}亿`
      : `${v}%`
}
```

- [ ] **Step 3: 构建验证**

Run: `cd frontend && pnpm -F web build`
Expected: EXIT=0（无 TS 类型错）

- [ ] **Step 4: 页面冒烟（可选，有 dev server 时）**

打开财务页 → 比率分析 Tab → 确认第五组"资本成本"三行出现且金额以"亿"显示、WACC 以%显示。

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/hooks/useRatios.ts frontend/apps/web/src/components/RatiosPanel.tsx
git commit -m "feat(ratios-panel): yi单位分支——资本成本组(投资资本/经济利润)金额显示为亿;类型/fmtVal/fmtDelta/Y轴四处"
```

---

## 收尾

- 三任务串行：Task 1（纯函数）→ Task 2（handler）→ Task 3（前端）。每任务独立 commit + 评审。
- 最终验证：`tests/.../test_ratio_analysis.py + tests/api/test_ratios.py` 全绿 + 茅台/腾讯冒烟 + `pnpm -F web build` EXIT=0。
