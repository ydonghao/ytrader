# 买入前检查清单(Buy Checklist)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 课程21集《股票投资前的检查清单》落地为 `/checklist` 买入体检页——四区21项(自动12+手动9,另加2.5议价可编辑备注),只展示不下结论。

**Architecture:** 三层范式对齐五力模块——纯函数(状态判定/组装,零IO可测)→ handler(串调既有 report 函数,`json.loads(resp.body).get("data")` 解包,先例 `financial_detail_handler.py:2138`)→ router → React 独立页。手动项存新表 `stock_checklist_item`。

**Tech Stack:** FastAPI + SQLModel/psycopg2(后端)、React 18 + rsbuild + vitest(前端)、pytest(后端纯函数)。

**Spec:** `docs/superpowers/specs/2026-09-20-buy-checklist-design.md`(含用户三项决策:独立页面/纯手动/只展示不下结论;2.5上下游议价自动+可编辑)。

## Global Constraints

- 状态四态:`ok` / `watch` / `risk` / `missing`;手动项另有 `pending`/`filled`。**无总体结论字段**(不输出 verdict/conclusion/红绿灯)。
- symbol 全程小写带交易所前缀(如 `sh600519`),不做转换,透传。
- 逐项降级:任一数据源异常/缺失 → 该项 `missing`,整页正常返回。
- 后端测试命令(工作目录 `backend/`):`.venv/bin/python -m pytest tests/domain/market/fundamental/test_<name>.py -q`;全量纯函数回归见 Task 9。
- 前端命令(工作目录 `frontend/apps/web/`):`npm run build`(编译验证)、`npx vitest run`(单测)。
- 每个任务结束必须 commit;提交信息用中文、`feat(checklist):`/`test(checklist):` 前缀。
- 既有 388 纯函数测试不得回归。

## 关键既有事实(实现者必读)

| 事实 | 位置 | 用途 |
|---|---|---|
| `responses.success(data)` 返回 **JSONResponse**,串调解包 `json.loads(resp.body).get("data")` | `backend/src/pkg/responses/__init__.py:26`;先例 `financial_detail_handler.py:2138` | Task 4 |
| `stock_profile(symbol)` → data={name, market, industry(akshare实时), business_scope, pe, ps, total_mv, ...} | `financial_detail_handler.py:235` | 2.1/4.1/参考区 |
| `detail_series(symbol, statement_type, limit, start_date, end_date, period)` → data={series:[{report_date, revenue, net_profit, basic_eps, ...}]} | `financial_detail_handler.py:55` | 3.1 业绩/派息EPS |
| `fetch_financial_history([symbol], lookback_reports=N)` → {symbol: [{report_date, roe_weighted,...}]} **升序** | `backend/src/domain/market/strategy/longterm/data_loader.py:322` | 3.3 ROE序列 |
| `five_forces_report(symbol)` → data={forces:[{key,label,score,evidence:[{metric,value,...}]}], total_score, note?} | `financial_detail_handler.py:2125` | 2.5/3.3分位 |
| `industry_peers(symbol)` → data={industry, sections(各期含cr4/hhi), peers, target} | financial_detail_handler(被:2152串调) | 2.3 参考 |
| `liquidity_report(symbol)` → data={ratios, verdict: strong/healthy/stretched/risky} | `financial_detail_handler.py:1592` | 3.2 |
| `moat_report(symbol)` → data={pricing_power_score(0-100), moat_score,...} | `financial_detail_handler.py:1230` | 1.4 参考 |
| `fraud_signals_report(symbol)` → data={red_flags, severity: clean/watch/high_risk} | `financial_detail_handler.py:1288` | 3.5 |
| `z_score_report(symbol)` → data={z, verdict: safe/grey/distress} | `financial_detail_handler.py:1625` | 3.5 |
| `m_score_report(symbol)` → data={m, verdict: manipulator/watch/clean} | `financial_detail_handler.py:1679` | 3.5 |
| `valuation_band_report(symbol, metric, years)` → data={current, sample_size, band:{mean,std,z_score,state}, ...} state∈超跌/合理偏低/合理偏高/虚高 | `financial_detail_handler.py:1024` | 4.2/4.3 |
| `concentration_report(symbol)` → data={holder_counts, verdict: concentrating/dispersing/stable} | `financial_detail_handler.py:1755` | 4.5 |
| `payout_ratio(net_profit, dividend_total)` 纯函数 → {ratio, dividend_total, ...} 或 None | `backend/src/domain/market/fundamental/quality.py:320` | 3.4(每股口径等价) |
| 分红表 `StockDividendRepository.get_history(symbol, start, end)` → 行含 `div_per_share` | `backend/src/infra/database/market/dividend.py:133` | 3.4 |
| 表+Repo 建模范式(psycopg2 直连 + SQLModel) | `backend/src/infra/database/market/shareholder_count.py` | Task 3 |
| main.py lifespan 建表 import 块 / include_router 块 | `backend/main.py:115-170` / `:316-326` | Task 3/5 |
| `fetch_kline` 在 **router 层**,handler 不得反向 import → 自写 stock_ohlcv 小查询(对齐 stock_profile 内嵌 psycopg2 先例) | `backend/src/api/router/market_router.py:64` | Task 4 |
| 前端 API base:`getApiBase()` from `src/lib/api.ts`;响应约定 `json.code === 0 && json.data` | `frontend/apps/web/src/lib/api.ts` | Task 7 |
| StockSearch 现位于 `Financial.tsx:181-240`,样式 `.fin-search*` 在 `Financial.css` | 同左 | Task 6 |
| 路由 lazy 模式 / 菜单"分析"组 | `App.tsx:29-33,71-73` / `components/Layout.tsx:64-67` | Task 7 |
| 可用图标:dashboard/market/trading/strategies/portfolio/analytics/backtest/risk/reports/financial/intel/alerts/settings/... | `components/icons.tsx:19` | Task 7 |

---

### Task 1: K线趋势纯函数 `kline_trend.py`

**Files:**
- Create: `backend/src/domain/market/fundamental/kline_trend.py`
- Test: `backend/tests/domain/market/fundamental/test_kline_trend.py`

**Interfaces:**
- Produces: `trend_state(closes: list[float]) -> Optional[dict]`,返回 `{ma20, ma60, ma120, slope_pct, state}`,`state` ∈ `"上升"/"下降"/"横盘"`;<120 根返回 `None`。Task 4 handler 调用。

- [ ] **Step 1: 写失败测试**

```python
"""kline_trend 纯函数测试(买入体检 4.4)。"""
from src.domain.market.fundamental.kline_trend import (
    sma, ols_slope, trend_state,
)


class TestSma:
    def test_basic(self):
        assert sma([1.0, 2.0, 3.0, 4.0], 2) == 3.5  # 末2均值

    def test_insufficient(self):
        assert sma([1.0, 2.0], 3) is None


class TestOlsSlope:
    def test_uptrend_positive(self):
        assert ols_slope([1.0, 2.0, 3.0, 4.0]) > 0

    def test_downtrend_negative(self):
        assert ols_slope([4.0, 3.0, 2.0, 1.0]) < 0

    def test_flat_zero(self):
        assert abs(ols_slope([2.0, 2.0, 2.0])) < 1e-9

    def test_short(self):
        assert ols_slope([1.0]) is None


def _mk_closes(trend: str, n: int = 200) -> list[float]:
    """构造趋势序列:上升=等差上行,下降=等差下行,横盘=围绕均值波动。"""
    base = [float(i) for i in range(1, n + 1)]        # 1,2,...,200 上升
    if trend == "上升":
        return base
    if trend == "下降":
        return base[::-1]
    return [100.0 + (1.0 if i % 2 else -1.0) for i in range(n)]  # 横盘


class TestTrendState:
    def test_uptrend(self):
        r = trend_state(_mk_closes("上升"))
        assert r is not None and r["state"] == "上升"
        assert r["ma20"] > r["ma60"] > r["ma120"]

    def test_downtrend(self):
        r = trend_state(_mk_closes("下降"))
        assert r is not None and r["state"] == "下降"

    def test_sideways(self):
        r = trend_state(_mk_closes("横盘"))
        assert r is not None and r["state"] == "横盘"

    def test_insufficient_data(self):
        assert trend_state([1.0] * 119) is None

    def test_slope_pct_scale(self):
        # 200日从1涨到200,日均涨幅远超阈值 → slope_pct > 0
        r = trend_state(_mk_closes("上升"))
        assert r["slope_pct"] > 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/market/fundamental/test_kline_trend.py -q`
Expected: FAIL,`ModuleNotFoundError: No module named 'src.domain.market.fundamental.kline_trend'`

- [ ] **Step 3: 写实现**

```python
"""K线趋势判定(买入体检 4.4,课程21集"K线判断")。纯函数,零 IO。

课程口径:K 线用于判断短期走势——上升/下降/横盘三态。
本模块用 MA20/MA60/MA120 排列 + 120 日收盘 OLS 斜率联合判定;
只做"展示型状态",不构成买卖信号(设计决策:只展示不下结论)。
"""
from typing import Optional


def sma(closes: list, period: int) -> Optional[float]:
    """简单移动平均(取末 period 个)。不足返回 None。"""
    if len(closes) < period:
        return None
    vals = [c for c in closes[-period:] if isinstance(c, (int, float))]
    if len(vals) < period:
        return None
    return sum(vals) / period


def ols_slope(values: list) -> Optional[float]:
    """一元线性回归斜率(最小二乘)。少于 2 点返回 None。"""
    n = len(values)
    if n < 2:
        return None
    mx = (n - 1) / 2
    my = sum(values) / n
    num = sum((x - mx) * (y - my) for x, y in zip(range(n), values))
    den = sum((x - mx) ** 2 for x in range(n))
    return num / den if den else None


def trend_state(closes: list) -> Optional[dict]:
    """日频收盘价(升序)→ {ma20, ma60, ma120, slope_pct, state}。

    - <120 根 → None(数据不足)
    - slope_pct = 120日OLS斜率 / 120日均值 × 100(日均变化百分比)
    - 多头排列(ma20>ma60>ma120)且 slope_pct>0.01 → 上升
    - 空头排列(ma20<ma60<ma120)且 slope_pct<-0.01 → 下降
    - 其余 → 横盘
    """
    vals = [c for c in closes if isinstance(c, (int, float)) and not isinstance(c, bool)]
    if len(vals) < 120:
        return None
    ma20, ma60, ma120 = sma(vals, 20), sma(vals, 60), sma(vals, 120)
    win = vals[-120:]
    slope = ols_slope(win)
    if ma20 is None or ma60 is None or ma120 is None or slope is None:
        return None
    mean = sum(win) / len(win)
    if mean <= 0:
        return None
    slope_pct = slope / mean * 100
    if ma20 > ma60 > ma120 and slope_pct > 0.01:
        state = "上升"
    elif ma20 < ma60 < ma120 and slope_pct < -0.01:
        state = "下降"
    else:
        state = "横盘"
    return {
        "ma20": round(ma20, 3),
        "ma60": round(ma60, 3),
        "ma120": round(ma120, 3),
        "slope_pct": round(slope_pct, 4),
        "state": state,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/market/fundamental/test_kline_trend.py -q`
Expected: PASS(11 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/fundamental/kline_trend.py backend/tests/domain/market/fundamental/test_kline_trend.py
git commit -m "feat(checklist): K线趋势纯函数——MA20/60/120排列+120日OLS斜率判升/降/横盘"
```

---

### Task 2: 清单状态映射与组装纯函数 `checklist_status.py`

**Files:**
- Create: `backend/src/domain/market/fundamental/checklist_status.py`
- Test: `backend/tests/domain/market/fundamental/test_checklist_status.py`

**Interfaces:**
- Consumes: Task 1 的 `trend_state`;既有 `quality.payout_ratio`。
- Produces(Task 4/5 依赖,签名精确):
  - `MANUAL_ITEMS: list[dict]`(9 手动项元数据,`{key, section, title, input_type, choices?}`)
  - `BARGAIN_NOTE_KEY = "bargaining_power_note"`
  - `revenue_cagr(annual: list[dict], years: int = 8) -> Optional[float]`
  - `build_checklist(sources: dict, saved: dict) -> dict` — 完整 GET 响应 data
  - `manual_filled(item: dict, row: Optional[dict]) -> bool`
  - `progress(sections: list[dict]) -> dict`
  - `sanitize_items(raw_items: list[dict]) -> list[dict]` — PUT 载荷净化

- [ ] **Step 1: 写失败测试**

```python
"""checklist_status 纯函数测试(买入体检,课程21集)。"""
from datetime import date

from src.domain.market.fundamental.checklist_status import (
    BARGAIN_NOTE_KEY,
    MANUAL_ITEMS,
    build_checklist,
    manual_filled,
    progress,
    revenue_cagr,
    sanitize_items,
)


class TestConstants:
    def test_nine_manual_items(self):
        assert len(MANUAL_ITEMS) == 9

    def test_keys_unique(self):
        keys = [i["key"] for i in MANUAL_ITEMS]
        assert len(keys) == len(set(keys))

    def test_sections(self):
        assert {i["section"] for i in MANUAL_ITEMS} == {"company", "industry"}

    def test_bargain_note_key(self):
        assert BARGAIN_NOTE_KEY == "bargaining_power_note"


class TestRevenueCagr:
    def _annual(self, revs):
        # 2018..年报序列
        return [
            {"report_date": date(2017 + i, 12, 31), "revenue": v}
            for i, v in enumerate(revs)
        ]

    def test_flat_below_3pct(self):
        # 格力口径:1800亿→1800亿,CAGR=0
        assert revenue_cagr(self._annual([1800, 1800, 1800, 1800,
                                          1800, 1800, 1800, 1800])) < 0.03

    def test_growing(self):
        r = revenue_cagr(self._annual([100, 130, 170, 220, 290, 380, 500, 650, 850]))
        assert r > 0.20

    def test_too_few_points(self):
        assert revenue_cagr(self._annual([100])) is None

    def test_nonpositive_base(self):
        assert revenue_cagr(self._annual([0, 100, 200])) is None


class TestBuildChecklist:
    def test_all_sources_missing(self):
        out = build_checklist({}, {})
        secs = {s["key"]: s for s in out["sections"]}
        assert list(secs.keys()) == ["company", "industry", "finance", "price"]
        auto = [it for s in out["sections"] for it in s["items"]
                if it["type"] == "auto"]
        assert len(auto) == 12
        assert all(it["status"] == "missing" for it in auto)
        # 只展示不下结论:响应无 verdict/conclusion 键
        assert "verdict" not in out and "conclusion" not in out

    def test_full_sources(self):
        sources = {
            "profile": {"name": "贵州茅台", "industry": "白酒", "total_mv": 2.1e12},
            "income_annual": [
                {"report_date": date(2017 + i, 12, 31), "revenue": 300 + 60 * i,
                 "net_profit": 100 + 20 * i, "basic_eps": 30.0 + i}
                for i in range(9)
            ],
            "roe_annual": [30.0, 31.0, 32.0, 33.0],
            "roe_pctile": 0.9,
            "five_forces": {"forces": [
                {"key": "supplier", "label": "供应商议价力", "score": 65,
                 "evidence": []},
                {"key": "buyer", "label": "客户议价力", "score": 70, "evidence": []},
            ]},
            "sections_latest": {"cr4": 0.77, "hhi": 0.21},
            "liquidity": {"verdict": "healthy", "ratios": {}},
            "payout": {"ratio": 0.52},
            "fraud": {"severity": "clean", "red_flags": []},
            "z": {"z": 3.1, "verdict": "safe"},
            "m": {"m": -3.0, "verdict": "clean"},
            "band_pe": {"current": 25.0,
                        "band": {"mean": 30.0, "std": 5.0, "z_score": -1.0,
                                 "state": "合理偏低"}},
            "band_ps": {"current": 10.0,
                        "band": {"mean": 12.0, "std": 2.0, "z_score": -1.0,
                                 "state": "合理偏低"}},
            "kline_trend": {"state": "上升", "ma20": 1, "ma60": 1, "ma120": 1,
                            "slope_pct": 0.05},
            "concentration": {"verdict": "concentrating", "holder_counts": [1, 2]},
        }
        out = build_checklist(sources, {})
        by_key = {it["key"]: s for s in out["sections"] for it in s["items"]}
        assert by_key["industry"]["status"] == "ok"
        assert by_key["growth"]["status"] == "ok"       # CAGR>3%
        assert by_key["roe"]["status"] == "ok"
        assert by_key["dividend"]["status"] == "ok"     # 52% 慷慨
        assert by_key["redflag"]["status"] == "ok"
        assert by_key["bargain"]["status"] == "ok"      # 均分>=60
        # 议价项带可编辑备注字段
        assert by_key["bargain"]["editable"] is True
        assert by_key["bargain"]["note_key"] == BARGAIN_NOTE_KEY

    def test_threshold_edges(self):
        # 派息率>70% → risk(掏空家底)
        out = build_checklist({"payout": {"ratio": 0.71},
                               "eps": 1.0, "div_sum": 0.71}, {})
        by = {it["key"]: s for s in out["sections"] for it in s["items"]}
        assert by["dividend"]["status"] == "risk"
        # fraud high_risk → risk
        out = build_checklist({"fraud": {"severity": "high_risk"}}, {})
        by = {it["key"]: s for s in out["sections"] for it in s["items"]}
        assert by["redflag"]["status"] == "risk"
        # z grey → watch
        out = build_checklist({"z": {"z": 2.0, "verdict": "grey"}}, {})
        by = {it["key"]: s for s in out["sections"] for it in s["items"]}
        assert by["redflag"]["status"] == "watch"
        # 估值带虚高 → risk
        out = build_checklist({"band_pe": {"current": 50.0, "band": {
            "mean": 20.0, "std": 5.0, "z_score": 6.0, "state": "虚高"}}}, {})
        by = {it["key"]: s for s in out["sections"] for it in s["items"]}
        assert by["band_pe"]["status"] == "risk"
        # ROE 亏损 → risk
        out = build_checklist({"roe_annual": [5.0, 2.0, -1.0]}, {})
        by = {it["key"]: s for s in out["sections"] for it in s["items"]}
        assert by["roe"]["status"] == "risk"

    def test_manual_items_injected(self):
        saved = {"pricing_power": {"value_choice": "是",
                                   "value_text": None,
                                   "updated_at": "2026-09-01T00:00:00"},
                 "mission_vision": {"value_choice": None,
                                    "value_text": "用技术创新满足向往",
                                    "updated_at": "2026-09-01T00:00:00"}}
        out = build_checklist({}, saved)
        by = {it["key"]: s for s in out["sections"] for it in s["items"]}
        assert by["pricing_power"]["status"] == "filled"
        assert by["pricing_power"]["value_choice"] == "是"
        assert by["mission_vision"]["status"] == "filled"
        assert by["company_name"]["status"] == "pending"
        assert out["manual_progress"] == {"filled": 2, "total": 9}
        assert out["auto_progress"] == {"ok": 0, "watch": 0, "risk": 0,
                                        "missing": 12}


class TestManualFilled:
    def _item(self, t):
        return {"input_type": t}

    def test_choice_filled_by_choice(self):
        assert manual_filled(self._item("choice"),
                             {"value_choice": "成长期", "value_text": ""})

    def test_choice_plus_text_needs_choice(self):
        assert not manual_filled(self._item("choice+text"),
                                 {"value_choice": "", "value_text": "备注"})

    def test_text_filled_by_text(self):
        assert manual_filled(self._item("text"),
                             {"value_choice": None, "value_text": "内容"})

    def test_empty(self):
        assert not manual_filled(self._item("text"), {"value_text": "  "})
        assert not manual_filled(self._item("text"), None)


class TestSanitize:
    def test_filters_unknown_and_blank(self):
        raw = [
            {"item_key": "pricing_power", "value_choice": "是"},
            {"item_key": "hacker_key", "value_choice": "x"},   # 非法键丢弃
            {"item_key": "mission_vision", "value_text": "  "},  # 空白→None=清除
            {"item_key": BARGAIN_NOTE_KEY, "value_text": "强甲方"},
        ]
        out = sanitize_items(raw)
        keys = [r["item_key"] for r in out]
        assert keys == ["pricing_power", "mission_vision",
                        BARGAIN_NOTE_KEY]
        assert out[1]["value_text"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/market/fundamental/test_checklist_status.py -q`
Expected: FAIL,`ModuleNotFoundError: ... checklist_status`

- [ ] **Step 3: 写实现**

```python
"""买入体检清单(课程21集)——状态映射与组装。纯函数,零 IO。

设计决策(spec):
- 四态 ok/watch/risk/missing;手动项 pending/filled;
- 只展示不下结论:本模块任何输出不含总体 verdict/conclusion;
- 所有源数据缺失/畸形 → 该项 missing,不抛异常(逐项降级);
- 2.5 上下游议价 = 自动项 + 可编辑备注(BARGAIN_NOTE_KEY)。

阈值均为课程口径,见各函数 docstring。
"""
from datetime import date
from typing import Any, Optional

# ── 手动项定义(9 项)────────────────────────────────────────────────
MANUAL_ITEMS: list[dict] = [
    # 一、企业基本情况(6)
    {"key": "company_name", "section": "company", "title": "公司全称",
     "input_type": "text",
     "course": "股票系统里都是简称,出于基本礼貌,公司全称要知道。"},
    {"key": "mission_vision", "section": "company", "title": "简介与使命愿景",
     "input_type": "text",
     "course": "使命=我们现在是谁;愿景=未来想干什么。官网可查。"},
    {"key": "core_products", "section": "company", "title": "核心产品",
     "input_type": "text",
     "course": "官网与财报都有,一看就知道的基础信息。"},
    {"key": "pricing_power", "section": "company", "title": "定价权",
     "input_type": "choice", "choices": ["是", "否", "不知道"],
     "course": "产品和服务是否具有定价权;不知道就先填不知道,慢慢研究。"},
    {"key": "market_position", "section": "company", "title": "市场情况",
     "input_type": "text",
     "course": "增量还是存量?市占率升降?海外开拓情况?生意还能做多大?"},
    {"key": "ownership_type", "section": "company", "title": "股权架构",
     "input_type": "choice+text",
     "choices": ["国企", "民企", "家族企业", "合伙人团队", "资本控股"],
     "course": "集中执行力强但易一言堂;分散有代理人风险。无绝对好坏。"},
    # 二、行业分析(3)
    {"key": "industry_cycle", "section": "industry", "title": "行业周期",
     "input_type": "choice", "choices": ["导入期", "成长期", "成熟期", "衰退期"],
     "course": "成长/成熟期对普通投资者最友好;导入期风险大收益大;衰退期烟蒂股多。"},
    {"key": "competitive_pattern", "section": "industry", "title": "竞争格局",
     "input_type": "choice", "choices": ["百舸争流", "一超多强", "巨头垄断"],
     "course": "百舸争流很卷打价格战;风险低可选一超多强/巨头垄断只投最好公司。"},
    {"key": "smile_position", "section": "industry", "title": "微笑曲线位置",
     "input_type": "choice+text",
     "choices": ["左端(研发设计)", "中间(制造组装)", "右端(品牌营销)"],
     "course": "施振荣1992:两端附加值最高,中间制造最低;尽量选两端避中间。"},
]
BARGAIN_NOTE_KEY = "bargaining_power_note"

_SECTIONS_META = [
    {"key": "company", "title": "一、企业基本情况"},
    {"key": "industry", "title": "二、行业分析"},
    {"key": "finance", "title": "三、财务指标"},
    {"key": "price", "title": "四、股价与估值"},
]


def _auto(key: str, section: str, title: str, status: str,
          value: Any = None, detail: Any = None, hint: str = "",
          **extra) -> dict:
    return {"key": key, "type": "auto", "section": section, "title": title,
            "status": status, "value": value, "detail": detail,
            "hint": hint, **extra}


# ── 各自动项状态判定(课程口径)──────────────────────────────────────

def revenue_cagr(annual: list, years: int = 8) -> Optional[float]:
    """年报营收 CAGR(最多取末 years+1 个年报点)。

    <2 点 / 首值<=0 / 跨度<1年 → None。
    """
    pts = [(r.get("report_date"), r.get("revenue")) for r in (annual or [])
           if isinstance(r.get("revenue"), (int, float))]
    pts = pts[-(years + 1):]
    if len(pts) < 2:
        return None
    (d0, v0), (d1, v1) = pts[0], pts[-1]
    if not isinstance(d0, date) or not isinstance(d1, date):
        return None
    if v0 <= 0 or v1 <= 0:
        return None
    span = (d1 - d0).days / 365.25
    if span < 1:
        return None
    return (v1 / v0) ** (1 / span) - 1


def _industry_item(profile: Optional[dict]) -> dict:
    if not profile or not profile.get("industry"):
        return _auto("industry", "industry", "所属行业", "missing",
                     hint="申万行业/东财行业归属")
    return _auto("industry", "industry", "所属行业", "ok",
                 value=profile["industry"],
                 hint="基础信息;行业周期与竞争格局见下方手动项")


def _growth_item(income_annual: Optional[list]) -> dict:
    cagr = revenue_cagr(income_annual or [])
    if cagr is None:
        return _auto("growth", "finance", "业绩曲线(成长性)", "missing",
                     hint="年报营收序列不足,无法算 CAGR")
    pct = round(cagr * 100, 2)
    if cagr < 0.03:
        return _auto("growth", "finance", "业绩曲线(成长性)", "watch",
                     value=f"{pct}%",
                     detail="近8年营收CAGR<3%,成长停滞(格力案例口径)",
                     hint="没成长性的公司估值低;要搞清公司性质——烟蒂还是成长")
    return _auto("growth", "finance", "业绩曲线(成长性)", "ok",
                 value=f"{pct}%", detail="近8年营收CAGR",
                 hint="第一眼就看业绩曲线;曲线糟糕基本不考虑")


def _balance_item(liquidity: Optional[dict]) -> dict:
    verdict_map = {"strong": ("ok", "流动性强"), "healthy": ("ok", "流动性健康"),
                   "stretched": ("watch", "流动性紧张"),
                   "risky": ("risk", "流动性风险")}
    v = (liquidity or {}).get("verdict")
    if v not in verdict_map:
        return _auto("balance", "finance", "资产负债表健康", "missing",
                     hint="流动比率/速动比率/现金比率")
    status, label = verdict_map[v]
    return _auto("balance", "finance", "资产负债表健康", status,
                 value=label, detail=f"verdict={v}",
                 hint="重资产公司固定资产高(如比亚迪的工厂);应付账款高=强势甲方")


def _roe_item(roe_annual: Optional[list], pctile: Optional[float]) -> dict:
    roes = [r for r in (roe_annual or [])
            if isinstance(r, (int, float))]
    if not roes:
        return _auto("roe", "finance", "ROE", "missing",
                     hint="尽量选 ROE 高的公司;不同商业模式差异大,宜横向对比")
    latest = roes[-1]
    if latest < 0:
        return _auto("roe", "finance", "ROE", "risk", value=f"{latest:.2f}%",
                     detail="最新年报 ROE 为负(亏损)",
                     hint="ROE 是效率指标,横向对比居多")
    detail_bits = [f"最新年报 ROE {latest:.2f}%"]
    if pctile is not None:
        detail_bits.append(f"行业分位 {pctile * 100:.0f}%")
    if len(roes) >= 3 and roes[-1] < roes[-2] < roes[-3]:
        return _auto("roe", "finance", "ROE", "watch", value=f"{latest:.2f}%",
                     detail=";".join(detail_bits) + ";连续3年下滑",
                     hint="ROE 高=商业模式好一些;连续下滑要留意")
    if latest < 8:
        return _auto("roe", "finance", "ROE", "watch", value=f"{latest:.2f}%",
                     detail=";".join(detail_bits) + ";<8%",
                     hint="同类型公司其他条件相同时,尽量选 ROE 高的")
    return _auto("roe", "finance", "ROE", "ok", value=f"{latest:.2f}%",
                 detail=";".join(detail_bits), hint="心里有数即可")


def _dividend_item(payout: Optional[dict]) -> dict:
    ratio = (payout or {}).get("ratio")
    if ratio is None:
        return _auto("dividend", "finance", "分红", "missing",
                     hint="看分红比例与稳定性;分红是投资的安全垫")
    pct = round(ratio * 100, 1)
    if ratio > 0.7:
        return _auto("dividend", "finance", "分红", "risk", value=f"{pct}%",
                     detail="派息率>70%,警惕掏空家底式分红",
                     hint="分红作为安全垫,主要排除掏空家底的风险")
    label = "慷慨" if ratio > 0.3 else "正常"
    return _auto("dividend", "finance", "分红", "ok", value=f"{pct}%",
                 detail=f"派息率{label}",
                 hint="≤30%正常/30-70%慷慨/>70%警惕掏空")


def _redflag_item(fraud: Optional[dict], z: Optional[dict],
                  m: Optional[dict]) -> dict:
    parts = []
    if fraud and fraud.get("severity"):
        parts.append(("fraud", fraud["severity"]))
    if z and z.get("verdict"):
        parts.append(("z-score", z["verdict"]))
    if m and m.get("verdict"):
        parts.append(("m-score", m["verdict"]))
    if not parts:
        return _auto("redflag", "finance", "财务红旗", "missing",
                     hint="营收-应收背离/净利-现金流背离等")
    bad = any(v in ("high_risk", "distress", "manipulator") for _, v in parts)
    warn = any(v in ("watch", "grey") for _, v in parts)
    detail = "; ".join(f"{k}={v}" for k, v in parts)
    status = "risk" if bad else ("watch" if warn else "ok")
    return _auto("redflag", "finance", "财务红旗", status, detail=detail,
                 hint="fraud红旗/Altman Z/Beneish M 三合一;任一高危即标红")


def _mcap_item(total_mv: Optional[float]) -> dict:
    if not isinstance(total_mv, (int, float)) or total_mv <= 0:
        return _auto("mcap", "price", "市值规模", "missing",
                     hint="千亿大公司/百亿中型/十亿小型")
    yi = total_mv / 1e8
    if yi >= 1e4:
        label = "万亿级"
    elif yi >= 1e3:
        label = "千亿级"
    elif yi >= 1e2:
        label = "百亿级"
    else:
        label = "十亿级及以下"
    return _auto("mcap", "price", "市值规模", "ok", value=label,
                 detail=f"总市值 {yi:,.0f} 亿元",
                 hint="和同市值公司横向对比,可简单判断市值是否合理(六个吉利)")


def _band_item(band_data: Optional[dict], key: str, title: str,
               metric: str) -> dict:
    band = (band_data or {}).get("band")
    if not band or not band.get("state"):
        return _auto(key, "price", title, "missing",
                     hint=f"{metric} 均值±1σ 估值带(8年窗)")
    state = band["state"]
    status_map = {"超跌": "ok", "合理偏低": "ok",
                  "合理偏高": "watch", "虚高": "risk"}
    status = status_map.get(state, "missing")
    return _auto(
        key, "price", title, status, value=state,
        detail=(f"当前 {band_data.get('current')},"
                f"μ={band.get('mean')},σ={band.get('std')},"
                f"z={band.get('z_score')}(样本{band_data.get('sample_size')})"),
        hint=("PE只适用于利润稳定的大公司;成长型看PS更合适。"
              if metric == "PE" else
              "市销率=市值/总营收,适合利润不稳或高增长公司"))


def _kline_item(trend: Optional[dict]) -> dict:
    if not trend or not trend.get("state"):
        return _auto("kline", "price", "K线趋势", "missing",
                     hint="判断上升/下降/横盘短期走势(参考《技术分析》普林格)")
    state = trend["state"]
    status = "ok" if state == "上升" else "watch"
    return _auto("kline", "price", "K线趋势", status, value=state,
                 detail=(f"MA20={trend.get('ma20')} MA60={trend.get('ma60')} "
                         f"MA120={trend.get('ma120')},"
                         f"120日日均变化 {trend.get('slope_pct')}%"),
                 hint="短期走势参考;到这里股价高低心里基本有数了")


def _concentration_item(conc: Optional[dict]) -> dict:
    v = (conc or {}).get("verdict")
    v_map = {"concentrating": ("ok", "筹码集中(户数连减,主力收集)"),
             "dispersing": ("watch", "筹码分散(户数连增,散户化)"),
             "stable": ("watch", "筹码稳定")}
    if v not in v_map:
        return _auto("chips", "price", "筹码参考(代理)", "missing",
                     hint="获利比例无数据源,以股东户数集中度作代理")
    status, label = v_map[v]
    return _auto("chips", "price", "筹码参考(代理)", status, value=label,
                 detail=f"verdict={v}",
                 hint="代理指标:基本面稳定+估值合理+筹码获利比例低时买入,短期被套概率低")


def _bargain_item(forces: Optional[list]) -> dict:
    by_key = {f.get("key"): f for f in (forces or [])}
    sup = by_key.get("supplier", {}).get("score")
    buy = by_key.get("buyer", {}).get("score")
    scores = [s for s in (sup, buy) if isinstance(s, (int, float))]
    if not scores:
        return _auto("bargain", "industry", "上下游议价能力", "missing",
                     hint="供应商议价力决定成本稳定性;客户议价力决定业绩与应收健康",
                     editable=True, note_key=BARGAIN_NOTE_KEY)
    avg = sum(scores) / len(scores)
    status = "ok" if avg >= 60 else ("watch" if avg >= 40 else "risk")
    detail = (f"供应商 {sup if sup is not None else '无'} / "
              f"客户 {buy if buy is not None else '无'}(0-100,高=对公司有利)")
    return _auto("bargain", "industry", "上下游议价能力", status,
                 value=f"均分 {avg:.0f}", detail=detail,
                 hint="五力自动结论;可在下方补充自己的判断(先自动后可编辑)",
                 editable=True, note_key=BARGAIN_NOTE_KEY)


# ── 组装 ──────────────────────────────────────────────────────────

def manual_filled(item: dict, row: Optional[dict]) -> bool:
    """已填判定:choice 类看 value_choice;text 类看 value_text(trim)。"""
    if not row:
        return False
    if item["input_type"] in ("choice", "choice+text"):
        return bool((row.get("value_choice") or "").strip())
    return bool((row.get("value_text") or "").strip())


def build_checklist(sources: dict, saved: dict) -> dict:
    """组装完整 GET 响应 data(纯函数,任一源缺失→missing)。

    sources 键:profile / income_annual / roe_annual / roe_pctile /
    five_forces(forces 列表) / sections_latest / liquidity / payout /
    fraud / z / m / band_pe / band_ps / kline_trend / concentration
    saved: {item_key: {value_text, value_choice, updated_at}}
    """
    s = sources or {}
    forces = (s.get("five_forces") or {}).get("forces")
    sections = [
        {"key": "company", "title": _SECTIONS_META[0]["title"],
         "items": [_i for _i in (
             _manual_item(mi, saved) for mi in MANUAL_ITEMS
             if mi["section"] == "company")]},
        {"key": "industry", "title": _SECTIONS_META[1]["title"],
         "items": (
             [_industry_item(s.get("profile")),
              _bargain_item(forces)]
             + [_manual_item(mi, saved) for mi in MANUAL_ITEMS
                if mi["section"] == "industry"])},
        {"key": "finance", "title": _SECTIONS_META[2]["title"],
         "items": [_growth_item(s.get("income_annual")),
                   _balance_item(s.get("liquidity")),
                   _roe_item(s.get("roe_annual"), s.get("roe_pctile")),
                   _dividend_item(s.get("payout")),
                   _redflag_item(s.get("fraud"), s.get("z"), s.get("m"))]},
        {"key": "price", "title": _SECTIONS_META[3]["title"],
         "items": [_mcap_item((s.get("profile") or {}).get("total_mv")),
                   _band_item(s.get("band_pe"), "band_pe", "PE 估值带", "PE"),
                   _band_item(s.get("band_ps"), "band_ps", "PS 估值带", "PS"),
                   _kline_item(s.get("kline_trend")),
                   _concentration_item(s.get("concentration"))]},
    ]
    # 2.3 竞争格局的 CR4/HHI 参考塞进行业区参考字段(不做独立项)
    sec_ref = s.get("sections_latest")
    out = {"sections": sections}
    out.update(progress(sections))
    out["references"] = {
        "moat": s.get("moat"),
        "shareholders": s.get("shareholders"),
        "industry_latest": sec_ref,
        "profile": s.get("profile"),
    }
    return out


def _manual_item(mi: dict, saved: dict) -> dict:
    row = saved.get(mi["key"])
    item = {"key": mi["key"], "type": "manual", "section": mi["section"],
            "title": mi["title"], "input_type": mi["input_type"],
            "choices": mi.get("choices"),
            "course": mi.get("course"),
            "value_text": (row or {}).get("value_text"),
            "value_choice": (row or {}).get("value_choice"),
            "updated_at": (row or {}).get("updated_at"),
            "status": "filled" if manual_filled(mi, row) else "pending"}
    return item


def progress(sections: list) -> dict:
    """统计手动/自动进度。"""
    manual_total = manual_filled_n = 0
    auto = {"ok": 0, "watch": 0, "risk": 0, "missing": 0}
    for sec in sections:
        for it in sec["items"]:
            if it["type"] == "manual":
                manual_total += 1
                manual_filled_n += 1 if it["status"] == "filled" else 0
            else:
                auto[it["status"]] = auto.get(it["status"], 0) + 1
    return {"manual_progress": {"filled": manual_filled_n,
                                "total": manual_total},
            "auto_progress": auto}


def sanitize_items(raw_items: list) -> list:
    """PUT 载荷净化:丢弃非法 item_key;空串→None(清除语义)。"""
    valid = {mi["key"] for mi in MANUAL_ITEMS} | {BARGAIN_NOTE_KEY}
    out = []
    for it in raw_items or []:
        k = (it.get("item_key") or "").strip()
        if k not in valid:
            continue
        out.append({
            "item_key": k,
            "value_text": (it.get("value_text") or "").strip() or None,
            "value_choice": (it.get("value_choice") or "").strip() or None,
        })
    return out
```

**注意**:`_manual_item` 在 `build_checklist` 中被引用,定义顺序在后(Python 运行时查找,没问题)。`test_full_sources` 中 `by_key` 通过双层 dict comprehension 以 item key 为主键——同名 section 键会互相覆盖,但 item key 全局唯一,断言安全。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/market/fundamental/test_checklist_status.py -q`
Expected: PASS(17 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/fundamental/checklist_status.py backend/tests/domain/market/fundamental/test_checklist_status.py
git commit -m "feat(checklist): 状态映射与组装纯函数——12自动项四态判定/9手动项注入/PUT净化"
```

---

### Task 3: `stock_checklist_item` 表 + Repo + main.py 建表注册

**Files:**
- Create: `backend/src/infra/database/market/checklist.py`
- Modify: `backend/main.py`(lifespan import 块,在 `market_sentiment` import 之后追加,约 :170 附近)

**Interfaces:**
- Produces(Task 4 依赖):
  - `StockChecklistItem`(SQLModel,表 `stock_checklist_item`,UNIQUE(symbol,item_key))
  - `create_checklist_repository() -> StockChecklistItemRepository`
  - `StockChecklistItemRepository.upsert_items(symbol: str, items: list[dict]) -> int`(items 元素 `{item_key, value_text, value_choice}`)
  - `StockChecklistItemRepository.get_all(symbol: str) -> dict[str, dict]` → `{item_key: {"value_text", "value_choice", "updated_at"(iso str)}}`

说明:本任务无离线 pytest(Repo 需真库,项目惯例 repo 靠 Task 9 实测);验收 = 导入冒烟 + 全量纯函数不回归。

- [ ] **Step 1: 写表 + Repo(对齐 shareholder_count.py 范式)**

```python
"""stock_checklist_item 表:买入体检手动项(每 symbol 每项一行)。

课程21集方法论:定性项研究清楚了再填,糊弄的数据不如不填;
投资后定期复检(加仓减仓前重新过表)→ updated_at 驱动复检提醒。
"""
import datetime as dt
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values
from sqlmodel import SQLModel, Field, UniqueConstraint

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class StockChecklistItem(SQLModel, table=True):
    """买入体检手动项存储(symbol + item_key 唯一)。"""

    __tablename__ = "stock_checklist_item"
    __table_args__ = (UniqueConstraint("symbol", "item_key",
                                       name="uq_checklist_symbol_item"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)                 # 小写带前缀 sh600519
    item_key: str = Field(index=True)               # 如 pricing_power
    value_text: Optional[str] = None                # 多行文本
    value_choice: Optional[str] = None              # 单选值(中文)
    updated_at: datetime = Field(default_factory=datetime.now)


class StockChecklistItemRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    def upsert_items(self, symbol: str, items: list[dict]) -> int:
        """批量插入/更新;value 均为 None 的行 = 清除内容(保留行)。"""
        if not items:
            return 0
        values = [
            (symbol, it["item_key"], it.get("value_text"),
             it.get("value_choice"), datetime.now())
            for it in items
        ]
        sql = """
            INSERT INTO stock_checklist_item
                (symbol, item_key, value_text, value_choice, updated_at)
            VALUES %s
            ON CONFLICT (symbol, item_key) DO UPDATE SET
                value_text = EXCLUDED.value_text,
                value_choice = EXCLUDED.value_choice,
                updated_at = EXCLUDED.updated_at
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def get_all(self, symbol: str) -> dict:
        """{item_key: {value_text, value_choice, updated_at(iso str)}}。"""
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT item_key, value_text, value_choice, updated_at
                       FROM stock_checklist_item WHERE symbol = %s""",
                    (symbol,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        out = {}
        for key, vt, vc, ua in rows:
            out[key] = {
                "value_text": vt,
                "value_choice": vc,
                "updated_at": ua.isoformat() if ua else None,
            }
        return out


def create_checklist_repository() -> StockChecklistItemRepository:
    return StockChecklistItemRepository(create_db_connection())
```

- [ ] **Step 2: main.py lifespan 注册建表**

在 `backend/main.py` lifespan 中 `NorthFlowDaily,` 等 market 模型 import 块之后(约 :170,紧跟 shareholder_count/market_sentiment 注释块结束处)追加:

```python
        # Import checklist model so create_all picks up
        # stock_checklist_item table on first connection.
        from src.infra.database.market.checklist import (  # noqa: F401
            StockChecklistItem,
        )
```

- [ ] **Step 3: 导入冒烟 + 建表验证**

```bash
cd backend && .venv/bin/python -c "
from src.infra.database.market.checklist import (
    StockChecklistItem, create_checklist_repository,
)
from src.main import app  # 或 backend/main.py 的实际装配入口
print('import ok')
"
```
Expected: `import ok`(无 ImportError)。若 main 装配入口路径不同,以 `grep -n "lifespan" backend/main.py` 确认后改用 `import main`。

再验证建表(需 DB 在线,失败则留给 Task 9 实测,不阻塞):

```bash
cd backend && .venv/bin/python -c "
from sqlmodel import SQLModel
from src.infra.database.sql_engine.engine import create_db_connection
from src.infra.database.market.checklist import StockChecklistItem
db = create_db_connection()
with db.session_scope() as s:
    SQLModel.metadata.create_all(s.connection())
print('table ensured')
"
```

- [ ] **Step 4: 全量纯函数回归(确认无破坏)**

Run: `cd backend && .venv/bin/python -m pytest tests/domain -q`
Expected: 与基线一致(388+ 新增 28 项全绿;tests/api、tests/sync 环境性失败属既有,见项目记忆)

- [ ] **Step 5: Commit**

```bash
git add backend/src/infra/database/market/checklist.py backend/main.py
git commit -m "feat(checklist): stock_checklist_item表+Repo(UNIQUE(symbol,item_key) upsert)+main建表注册"
```

---

### Task 4: 聚合 handler `checklist_handler.py`

**Files:**
- Create: `backend/src/api/handler/checklist_handler.py`

**Interfaces:**
- Consumes: Task 2 `build_checklist/sanitize_items/MANUAL_ITEMS/BARGAIN_NOTE_KEY`、Task 3 `create_checklist_repository`、Task 1 `trend_state`、既有 `quality.payout_ratio` 与 12 个 report 函数(见"关键既有事实"表)。
- Produces(Task 5 依赖):
  - `checklist_report(symbol: str) -> Any`(responses.success JSONResponse)
  - `save_checklist_items(symbol: str, payload: dict) -> Any`

本任务 handler 为薄壳(取数+降级,逻辑全在 Task 2 纯函数),测试靠 Task 5 冒烟。

- [ ] **Step 1: 写 handler**

```python
"""买入体检聚合 handler(课程21集)。

三层范式:本文件只做"取数 + 逐项降级 + 调 checklist_status 组装";
所有判定逻辑在纯函数 checklist_status.py(可离线测试)。
串调既有 report 函数,json.loads(resp.body).get("data") 解包
(先例:financial_detail_handler.py:2138 five_forces_report)。
"""
import json
from datetime import date, timedelta
from typing import Any

from src.pkg import responses


def _data(fn, *args, **kwargs):
    """调既有 handler 函数 → 解包 data;任何异常/失败码 → None(逐项降级)。"""
    try:
        body = json.loads(fn(*args, **kwargs).body)
        if body.get("code") == 0:
            return body.get("data")
    except Exception:  # noqa: BLE001
        pass
    return None


def _fetch_closes(symbol: str, limit: int = 200) -> list:
    """近 N 日收盘价(升序)。handler 不反向 import router 层 fetch_kline,
    自写 stock_ohlcv 查询(对齐 stock_profile 内嵌 psycopg2 先例)。"""
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn

    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT close_ FROM stock_ohlcv
                   WHERE symbol = %s ORDER BY time DESC LIMIT %s""",
                (symbol, limit),
            )
            rows = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    return rows[::-1]  # DESC 取最近N根 → 反转成升序
```

**注意**:`stock_ohlcv` 的时间列名需与实际表一致——实现时先执行 `cd backend && .venv/bin/python -c "import psycopg2; from src.infra.database.sql_engine.dsn import get_dsn; c=psycopg2.connect(get_dsn()); cur=c.cursor(); cur.execute(\"select column_name from information_schema.columns where table_name='stock_ohlcv'\"); print([r[0] for r in cur.fetchall()])"` 确认(可能是 `time`/`trade_time`/`ts`),按实际列名替换 `time`。

继续 handler 主体:

```python
def checklist_report(symbol: str) -> Any:
    """GET /checklist/{symbol} — 四区21项聚合(只展示不下结论)。"""
    from src.api.handler.financial_detail_handler import (
        concentration_report, detail_series, five_forces_report,
        fraud_signals_report, industry_peers, liquidity_report,
        moat_report, stock_profile, valuation_band_report,
        z_score_report, m_score_report,
    )
    from src.domain.market.fundamental.kline_trend import trend_state
    from src.domain.market.fundamental.quality import payout_ratio
    from src.domain.market.strategy.longterm.data_loader import (
        fetch_financial_history,
    )
    from src.infra.database.market.dividend import (
        create_stock_dividend_repository,
    )
    from src.infra.database.market.checklist import (
        create_checklist_repository,
    )

    sources: dict = {}

    profile = _data(stock_profile, symbol) or {}
    sources["profile"] = profile or None

    # 年报序列(营收/净利/EPS),显式按报告期升序防御
    income = _data(detail_series, symbol, "income", 20, None, None, "year") or {}
    annual = sorted(
        (income.get("series") or []),
        key=lambda r: r.get("report_date") or "",
    )
    sources["income_annual"] = annual or None

    # ROE 年报序列(取近20期报告滤 12-31;fetch_financial_history 升序)
    hist = fetch_financial_history([symbol], lookback_reports=20) or {}
    roe_annual = [
        r["roe_weighted"] for r in hist.get(symbol, [])
        if str(r.get("report_date", "")).endswith("12-31")
        and isinstance(r.get("roe_weighted"), (int, float))
    ]
    sources["roe_annual"] = roe_annual or None

    # 五力(supplier/buyer 议价 + ROE 行业分位)与行业截面(CR4/HHI 参考)
    ff = _data(five_forces_report, symbol) or {}
    sources["five_forces"] = ff or None
    if ff.get("forces"):
        for f in ff["forces"]:
            for ev in f.get("evidence") or []:
                if ev.get("metric") == "ROE行业分位" and isinstance(
                        ev.get("value"), (int, float)):
                    sources["roe_pctile"] = ev["value"]
    peers = _data(industry_peers, symbol) or {}
    sections = peers.get("sections") or []
    sources["sections_latest"] = next(
        (s for s in reversed(sections) if s.get("cr4") is not None), None)

    sources["liquidity"] = _data(liquidity_report, symbol) or None
    sources["fraud"] = _data(fraud_signals_report, symbol) or None
    sources["z"] = _data(z_score_report, symbol) or None
    sources["m"] = _data(m_score_report, symbol) or None
    sources["band_pe"] = _data(valuation_band_report, symbol, "pe", 8) or None
    sources["band_ps"] = _data(valuation_band_report, symbol, "ps", 8) or None
    sources["concentration"] = _data(concentration_report, symbol) or None
    sources["moat"] = _data(moat_report, symbol) or None

    # 派息率(每股口径等价:Σ近365日每股派息 / 最新年报EPS)
    eps = None
    if annual:
        eps = annual[-1].get("basic_eps")
    div_sum = None
    try:
        dr = create_stock_dividend_repository()
        div_rows = dr.get_history(
            symbol, start=date.today() - timedelta(days=365))
        divs = [r.div_per_share for r in div_rows
                if isinstance(r.div_per_share, (int, float))]
        div_sum = sum(divs) if divs else None
    except Exception:  # noqa: BLE001
        pass
    if isinstance(eps, (int, float)) and isinstance(div_sum, (int, float)):
        sources["payout"] = payout_ratio(eps, div_sum)

    # K线趋势(自写查询 + Task 1 纯函数)
    try:
        closes = _fetch_closes(symbol)
        sources["kline_trend"] = trend_state(closes) if closes else None
    except Exception:  # noqa: BLE001
        sources["kline_trend"] = None

    # 前十大股东(1.6 参考)
    sources["shareholders"] = _shareholders(symbol)

    # 已保存手动项
    try:
        saved = create_checklist_repository().get_all(symbol)
    except Exception:  # noqa: BLE001
        saved = {}

    data = build_checklist(sources, saved)
    data["symbol"] = symbol
    data["note"] = (
        "只展示不下结论;四态 ok/watch/risk/missing 为课程口径状态点,"
        "非买卖建议。手动项须研究清楚再填——糊弄的数据不如不填;"
        "投资后定期复检(>90天页面提示)。"
    )
    return responses.success(data)


def _shareholders(symbol: str) -> list:
    """前十大股东(1.6 股权架构参考),复用 ownership 查询逻辑。"""
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn

    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT holder_name, hold_ratio, holder_type
                   FROM shareholder_info WHERE symbol = %s
                   ORDER BY ranking ASC LIMIT 10""",
                (symbol,),
            )
            return [{"name": r[0], "ratio": r[1], "type": r[2]}
                    for r in cur.fetchall()]
    except Exception:  # noqa: BLE001
        return []
    finally:
        conn.close()


def save_checklist_items(symbol: str, payload: dict) -> Any:
    """PUT /checklist/{symbol}/items — 批量保存手动项(空值=清除)。"""
    from src.infra.database.market.checklist import (
        create_checklist_repository,
    )
    from src.domain.market.fundamental.checklist_status import sanitize_items

    items = sanitize_items((payload or {}).get("items") or [])
    if not items:
        return responses.error("无可保存项(item_key 非法或全为空)")
    try:
        n = create_checklist_repository().upsert_items(symbol, items)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"保存失败: {e}")
    return responses.success({"symbol": symbol, "saved": n})
```

顶部 import 补充(Task 2 的 `build_checklist` 加入文件头 import):

```python
from src.domain.market.fundamental.checklist_status import build_checklist
```

**shareholder_info 列名同样需实测确认**(可能无 `holder_type` 列):先
`cur.execute("select column_name from information_schema.columns where table_name='shareholder_info'")` 查看,按实际列调整 SELECT(参考 `financial_router.py:707` `get_shareholder_info` 的 `SELECT *`,可直接对齐其返回字段名)。

- [ ] **Step 2: 导入冒烟**

```bash
cd backend && .venv/bin/python -c "
from src.api.handler.checklist_handler import (
    checklist_report, save_checklist_items,
)
print('handler import ok')
"
```
Expected: `handler import ok`

- [ ] **Step 3: Commit**

```bash
git add backend/src/api/handler/checklist_handler.py
git commit -m "feat(checklist): 聚合handler——串调12个既有report逐项降级+派息率每股口径+自写OHLCV查询"
```

---

### Task 5: router + main.py 注册 + 实测冒烟

**Files:**
- Create: `backend/src/api/router/checklist_router.py`
- Modify: `backend/main.py`(import 区 + include_router 区 :326 附近)

**Interfaces:**
- Consumes: Task 4 `checklist_report/save_checklist_items`。
- Produces: `GET /api/v1/checklist/{symbol}`、`PUT /api/v1/checklist/{symbol}/items`。

- [ ] **Step 1: 写 router**

```python
"""买入体检路由(课程21集检查清单)。"""
from typing import Any

from fastapi import APIRouter, Body

from src.api.handler.checklist_handler import (
    checklist_report,
    save_checklist_items,
)

router = APIRouter(prefix="/checklist", tags=["checklist"])


@router.get("/{symbol}")
def get_checklist(symbol: str) -> Any:
    """四区21项聚合(自动12+手动9;只展示不下结论)。"""
    return checklist_report(symbol)


@router.put("/{symbol}/items")
def put_checklist_items(symbol: str, payload: dict = Body(...)) -> Any:
    """批量保存手动项;空值=清除该项(回到待填)。"""
    return save_checklist_items(symbol, payload)
```

- [ ] **Step 2: main.py 注册**

在 `backend/main.py` 的 router import 区(与 financial 等同级)加:

```python
from src.api.router.checklist_router import router as checklist_router
```

include_router 区(:326 附近,紧跟其它 include)加:

```python
    app.include_router(checklist_router, prefix="/api/v1")  # /api/v1/checklist
```

- [ ] **Step 3: 启动实测(需 DB 在线)**

```bash
cd backend && .venv/bin/python -m uvicorn main:app --port 8001 &>/tmp/uv8.log & sleep 6
# GET:期望 code=0,四区 sections,自动项 status 合法
curl -s "http://127.0.0.1:8001/api/v1/checklist/sh600519" | python3 -c "
import json,sys; d=json.load(sys.stdin)
assert d['code']==0, d
data=d['data']
assert [s['key'] for s in data['sections']]==['company','industry','finance','price']
auto=[i for s in data['sections'] for i in s['items'] if i['type']=='auto']
assert len(auto)==12, len(auto)
assert 'verdict' not in data and 'conclusion' not in data
print('GET ok:', data['manual_progress'], data['auto_progress'])
"
# PUT:保存两项后 GET 回显
curl -s -X PUT "http://127.0.0.1:8001/api/v1/checklist/sh600519/items" \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"item_key":"pricing_power","value_choice":"是"},{"item_key":"mission_vision","value_text":"用技术创新,满足人们对美好生活的向往"}]}'
curl -s "http://127.0.0.1:8001/api/v1/checklist/sh600519" | python3 -c "
import json,sys; data=json.load(sys.stdin)['data']
by={i['key']:i for s in data['sections'] for i in s['items']}
assert by['pricing_power']['value_choice']=='是'
assert by['pricing_power']['status']=='filled'
assert data['manual_progress']['filled']>=2
print('PUT/回显 ok')
"
# 清除:空值回到 pending
curl -s -X PUT "http://127.0.0.1:8001/api/v1/checklist/sh600519/items" \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"item_key":"mission_vision","value_text":""}]}'
kill %1
```
Expected: `GET ok ...` / `PUT/回显 ok`(茅台自动项多数非 missing;若 akshare 网络不可用 industry 可能 missing,属正常降级)

- [ ] **Step 4: Commit**

```bash
git add backend/src/api/router/checklist_router.py backend/main.py
git commit -m "feat(checklist): /checklist路由注册——GET聚合+PUT批量保存,实测茅台冒烟通过"
```

---

### Task 6: StockSearch 抽取为共享组件

**Files:**
- Create: `frontend/apps/web/src/components/StockSearch.tsx`
- Create: `frontend/apps/web/src/components/StockSearch.css`
- Modify: `frontend/apps/web/src/pages/Financial.tsx`(删 :181-240 本地定义,改 import)
- Modify: `frontend/apps/web/src/pages/Financial.css`(剪切 `.fin-search*` 规则块)

**Interfaces:**
- Produces(Task 7 依赖): `import { StockSearch } from '../components/StockSearch'`,props `{ value: string; onSelect: (sym: string) => void }`。

- [ ] **Step 1: 建组件(原样迁移,仅 API_BASE 改为组件内取)**

`StockSearch.tsx`:

```tsx
/**
 * 股票搜索下拉(原 Financial.tsx 内组件抽出共享,买入体检页复用)。
 * 数据源 /market/search;防抖 200ms;reqId 守卫丢弃过期响应。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { getApiBase } from '../lib/api';
import './StockSearch.css';

export function StockSearch({ value, onSelect }: { value: string; onSelect: (sym: string) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<{ symbol: string; name: string }[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const reqIdRef = useRef(0);

  const search = useCallback(async (q: string) => {
    if (q.trim().length < 1) { setResults([]); setLoading(false); return; }
    const reqId = ++reqIdRef.current;
    setLoading(true);
    try {
      const res = await fetch(`${getApiBase()}/market/search?q=${encodeURIComponent(q)}&limit=10`);
      const json = await res.json();
      if (reqId !== reqIdRef.current) return;
      if (json.code === 0 && json.data) {
        setResults(json.data.map((s: any) => ({ symbol: s.symbol, name: s.name || s.symbol })));
      }
    } catch { /* ignore */ }
    if (reqId === reqIdRef.current) setLoading(false);
  }, []);

  useEffect(() => {
    const q = query;
    const t = setTimeout(() => search(q), 200);
    return () => clearTimeout(t);
  }, [query, search]);

  return (
    <div className="fin-search">
      <input
        className="fin-search__input"
        placeholder="搜索股票代码/名称（如 600519 或 茅台）"
        value={query}
        onChange={e => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 200)}
      />
      {open && results.length > 0 && (
        <div className="fin-search__dropdown">
          {results.map(r => (
            <div
              key={r.symbol}
              className="fin-search__item"
              onClick={() => { onSelect(r.symbol); setQuery(`${r.symbol} ${r.name}`); setOpen(false); }}
            >
              <span className="fin-search__symbol">{r.symbol}</span>
              <span className="fin-search__name">{r.name}</span>
            </div>
          ))}
        </div>
      )}
      {open && !loading && results.length === 0 && query.length >= 1 && (
        <div className="fin-search__dropdown"><div className="fin-search__empty">无匹配结果</div></div>
      )}
    </div>
  );
}
```

`StockSearch.css`:用 `grep -n "fin-search" frontend/apps/web/src/pages/Financial.css` 定位整块(从第一条 `.fin-search` 规则到最后一条 `.fin-search__empty` 规则),**剪切**进本文件(保持规则原样,文件头加注释 `/* 股票搜索下拉样式(自 Financial.css 迁移,买入体检页共用) */`)。

- [ ] **Step 2: Financial.tsx 改引**

删除 `Financial.tsx:181-240` 的整个 `function StockSearch(...)` 定义,文件顶部 import 区加:

```tsx
import { StockSearch } from '../components/StockSearch';
```

(若 Financial.tsx 中 `API_BASE` 仅剩此用途,则一并删除该常量;`grep -n "API_BASE" frontend/apps/web/src/pages/Financial.tsx` 确认其它用途后处理。)

- [ ] **Step 3: 构建验证**

```bash
cd frontend/apps/web && npm run build
```
Expected: 构建成功无 TS 错误。

- [ ] **Step 4: 浏览器冒烟(dev 起前后端,Financial 页搜索仍可用)**

```bash
cd frontend/apps/web && npm run dev &  # 访问 /financial 搜索"茅台"能出下拉
```
Expected: 搜索下拉正常,选中后图表切换正常。

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/components/StockSearch.tsx frontend/apps/web/src/components/StockSearch.css frontend/apps/web/src/pages/Financial.tsx frontend/apps/web/src/pages/Financial.css
git commit -m "refactor(web): StockSearch抽为共享组件——买入体检页复用,样式随迁"
```

---

### Task 7: Checklist 页面骨架(路由/菜单/选股/自动项渲染)

**Files:**
- Create: `frontend/apps/web/src/pages/Checklist.tsx`
- Create: `frontend/apps/web/src/pages/Checklist.css`
- Modify: `frontend/apps/web/src/App.tsx`(lazy + Route)
- Modify: `frontend/apps/web/src/components/Layout.tsx`(分析组菜单)

**Interfaces:**
- Consumes: Task 6 `StockSearch`;Task 5 GET 端点。
- Produces: 路由 `/checklist`;Task 8 在本骨架上补手动项表单。

- [ ] **Step 1: App.tsx 注册路由**

lazy 声明区(:33 `EarningsRadar` 之后)加:

```tsx
const Checklist = lazy(() => import('./pages/Checklist').then(m => ({default: m.Checklist})));
```

Routes 内(:73 `/earnings-radar` 之后)加:

```tsx
          <Route path="/checklist" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><Checklist /></Suspense>} />
```

- [ ] **Step 2: Layout.tsx 菜单**

"分析"组(:64-67)首项位置插入:

```tsx
      {path: '/checklist', label: '买入体检', icon: Icon.analytics},
```

- [ ] **Step 3: 写页面骨架**

`Checklist.tsx`(本任务先渲染自动项 + 手动项只读占位,Task 8 补表单):

```tsx
/**
 * 买入体检(课程21集《股票投资前的检查清单》)。
 * 四区21项:自动12(状态点 ok/watch/risk/missing)+手动9(纯手动填写)。
 * 设计决策:只展示不下结论——无总体红绿灯/买不买判定。
 * 手动项研究清楚了再填(糊弄的数据不如不填);>90天未更新提示复检。
 */
import { useEffect, useState } from 'react';
import { PageHeader, StateView } from '../components/ui';
import { StockSearch } from '../components/StockSearch';
import { getApiBase } from '../lib/api';
import { daysSince, formatDaysAgo } from './checklistHelpers';
import './Checklist.css';

export interface ChecklistItem {
  key: string;
  type: 'auto' | 'manual';
  section: string;
  title: string;
  status: string;              // auto: ok/watch/risk/missing; manual: filled/pending
  value?: string | null;
  detail?: string | null;
  hint?: string;
  course?: string;             // 手动项课程口径
  input_type?: 'text' | 'choice' | 'choice+text';
  choices?: string[];
  value_text?: string | null;
  value_choice?: string | null;
  updated_at?: string | null;
  editable?: boolean;          // 2.5 议价专属
  note_key?: string;
  note_text?: string | null;
}

export interface ChecklistSection { key: string; title: string; items: ChecklistItem[]; }
export interface ChecklistData {
  symbol: string;
  sections: ChecklistSection[];
  manual_progress: { filled: number; total: number };
  auto_progress: { ok: number; watch: number; risk: number; missing: number };
  note?: string;
}

const STATUS_DOT: Record<string, string> = {
  ok: 'chk-dot chk-dot--ok', watch: 'chk-dot chk-dot--watch',
  risk: 'chk-dot chk-dot--risk', missing: 'chk-dot chk-dot--missing',
  filled: 'chk-dot chk-dot--ok', pending: 'chk-dot chk-dot--pending',
};
const STATUS_TEXT: Record<string, string> = {
  ok: '✓', watch: '⚠', risk: '✗', missing: '—',
  filled: '已填', pending: '待填',
};

function AutoItem({ it }: { it: ChecklistItem }) {
  return (
    <div className="chk-item">
      <span className={STATUS_DOT[it.status]} title={it.status}>{STATUS_TEXT[it.status]}</span>
      <div className="chk-item__body">
        <div className="chk-item__head">
          <span className="chk-item__title">{it.title}</span>
          {it.value && <span className="chk-item__value">{it.value}</span>}
        </div>
        {it.detail && <div className="chk-item__detail">{it.detail}</div>}
        {it.hint && <div className="chk-item__hint">{it.hint}</div>}
      </div>
    </div>
  );
}

function ManualItemReadonly({ it }: { it: ChecklistItem }) {
  return (
    <div className="chk-item chk-item--manual">
      <span className={STATUS_DOT[it.status]}>{STATUS_TEXT[it.status]}</span>
      <div className="chk-item__body">
        <div className="chk-item__head">
          <span className="chk-item__title">{it.title}</span>
          {it.value_choice && <span className="chk-item__value">{it.value_choice}</span>}
          {it.updated_at && (
            <span className={`chk-item__date${(daysSince(it.updated_at) ?? 0) > 90 ? ' chk-item__date--stale' : ''}`}>
              上次填写 {formatDaysAgo(it.updated_at)}
              {(daysSince(it.updated_at) ?? 0) > 90 ? ' · 建议复检' : ''}
            </span>
          )}
        </div>
        {it.value_text && <div className="chk-item__detail">{it.value_text}</div>}
        {it.course && <div className="chk-item__hint">课程口径:{it.course}</div>}
      </div>
    </div>
  );
}

export function Checklist() {
  const [symbol, setSymbol] = useState('sh600519');
  const [data, setData] = useState<ChecklistData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let stale = false;
    setLoading(true); setError(''); setData(null);
    fetch(`${getApiBase()}/checklist/${symbol}`)
      .then(r => r.json())
      .then(json => {
        if (stale) return;
        if (json.code === 0 && json.data) setData(json.data);
        else setError(json.msg || '加载失败');
      })
      .catch(e => { if (!stale) setError(String(e)); })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, [symbol]);

  return (
    <div className="page checklist-page">
      <PageHeader title="买入体检" subtitle="股票投资前的检查清单(课程21集)——只展示不下结论;手动项研究清楚再填" />
      <div className="chk-toolbar">
        <StockSearch value={symbol} onSelect={setSymbol} />
        {data && (
          <div className="chk-progress">
            <span>手动项 {data.manual_progress.filled}/{data.manual_progress.total}</span>
            <span className="chk-dot chk-dot--ok" /> {data.auto_progress.ok}
            <span className="chk-dot chk-dot--watch" /> {data.auto_progress.watch}
            <span className="chk-dot chk-dot--risk" /> {data.auto_progress.risk}
            <span className="chk-dot chk-dot--missing" /> {data.auto_progress.missing}
          </div>
        )}
      </div>
      <StateView loading={loading} error={error} empty={!loading && !error && !data}>
        {data && (
          <div className="chk-sections">
            {data.sections.map(sec => (
              <section key={sec.key} className="chk-section">
                <h3 className="chk-section__title">{sec.title}</h3>
                <div className="chk-section__items">
                  {sec.items.map(it => it.type === 'auto'
                    ? <AutoItem key={it.key} it={it} />
                    : <ManualItemReadonly key={it.key} it={it} />)}
                </div>
              </section>
            ))}
          </div>
        )}
      </StateView>
    </div>
  );
}
```

`Checklist.css`:

```css
/* 买入体检页(课程21集)。状态点四态 + A股红涨绿跌无冲突的中性徽章色。 */
.checklist-page { display: flex; flex-direction: column; gap: 16px; }
.chk-toolbar { display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
.chk-progress { display: flex; align-items: center; gap: 6px; color: var(--text-secondary, #888); font-size: 13px; }
.chk-sections { display: grid; gap: 16px; }
.chk-section { background: var(--bg-card, #1c1f26); border: 1px solid var(--border-color, #2a2e37); border-radius: 10px; padding: 16px; }
.chk-section__title { margin: 0 0 12px; font-size: 15px; }
.chk-section__items { display: grid; gap: 10px; }
.chk-item { display: flex; gap: 10px; align-items: flex-start; padding: 8px 10px; border-radius: 8px; background: rgba(255, 255, 255, 0.02); }
.chk-item__body { flex: 1; min-width: 0; display: grid; gap: 4px; }
.chk-item__head { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.chk-item__title { font-weight: 600; font-size: 13px; }
.chk-item__value { font-size: 13px; color: var(--text-primary, #eee); }
.chk-item__detail { font-size: 12px; color: var(--text-secondary, #999); white-space: pre-wrap; word-break: break-word; }
.chk-item__hint { font-size: 12px; color: var(--text-faint, #777); }
.chk-item__date { font-size: 12px; color: var(--text-faint, #777); }
.chk-item__date--stale { color: #d4a017; }
.chk-dot { display: inline-block; width: 18px; height: 18px; border-radius: 50%; font-size: 11px; line-height: 18px; text-align: center; flex: none; }
.chk-dot--ok { background: rgba(46, 160, 67, 0.25); color: #3fb950; }
.chk-dot--watch { background: rgba(210, 153, 34, 0.25); color: #d29922; }
.chk-dot--risk { background: rgba(248, 81, 73, 0.25); color: #f85149; }
.chk-dot--missing { background: rgba(139, 148, 158, 0.2); color: #8b949e; }
.chk-dot--pending { background: rgba(139, 148, 158, 0.2); color: #8b949e; }
```

同时建 Task 8 要用的 `checklistHelpers.ts`(本任务的 `daysSince/formatDaysAgo` import 需要它,现在就建并配测试):

```ts
/** 买入体检页纯工具(日期复检提醒等)。 */
export function daysSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.floor((Date.now() - t) / 86400000);
}

export function formatDaysAgo(iso: string | null | undefined): string {
  const d = daysSince(iso);
  if (d === null) return '';
  if (d <= 0) return '今天';
  if (d === 1) return '1 天前';
  if (d < 30) return `${d} 天前`;
  if (d < 365) return `${Math.floor(d / 30)} 个月前`;
  return `${Math.floor(d / 365)} 年前`;
}
```

- [ ] **Step 4: 构建验证**

```bash
cd frontend/apps/web && npm run build
```
Expected: 构建成功。

- [ ] **Step 5: 浏览器冒烟**

`npm run dev` 后访问 `/checklist`:茅台默认加载,四区渲染,自动项状态点显示,菜单"分析→买入体检"可达。

- [ ] **Step 6: Commit**

```bash
git add frontend/apps/web/src/pages/Checklist.tsx frontend/apps/web/src/pages/Checklist.css frontend/apps/web/src/pages/checklistHelpers.ts frontend/apps/web/src/App.tsx frontend/apps/web/src/components/Layout.tsx
git commit -m "feat(checklist): 买入体检页骨架——/checklist路由+菜单+四区渲染+自动项状态点"
```

---

### Task 8: 手动项表单 + 防抖保存 + 议价备注 + vitest

**Files:**
- Modify: `frontend/apps/web/src/pages/Checklist.tsx`(ManualItemReadonly → ManualItem 可编辑)
- Modify: `frontend/apps/web/src/pages/Checklist.css`(表单样式)
- Test: `frontend/apps/web/src/pages/__tests__/checklistHelpers.test.ts`

**Interfaces:**
- Consumes: Task 5 PUT 端点;Task 7 骨架。
- Produces: 完整交互页(防抖 800ms 保存、复检提醒、2.5 议价备注)。

- [ ] **Step 1: 写 helpers 失败测试(vitest,先于表单实现)**

`__tests__/checklistHelpers.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { daysSince, formatDaysAgo } from '../checklistHelpers';

describe('daysSince', () => {
  it('今天为 0', () => {
    expect(daysSince(new Date().toISOString())).toBe(0);
  });
  it('25小时前为 1 天', () => {
    expect(daysSince(new Date(Date.now() - 25 * 3600_000).toISOString())).toBe(1);
  });
  it('空值返回 null', () => {
    expect(daysSince(null)).toBeNull();
    expect(daysSince('')).toBeNull();
    expect(daysSince('not-a-date')).toBeNull();
  });
});

describe('formatDaysAgo', () => {
  it('今天', () => {
    expect(formatDaysAgo(new Date().toISOString())).toBe('今天');
  });
  it('1 天前', () => {
    expect(formatDaysAgo(new Date(Date.now() - 30 * 3600_000).toISOString())).toBe('1 天前');
  });
  it('45天→1 个月前', () => {
    expect(formatDaysAgo(new Date(Date.now() - 45 * 86400_000).toISOString())).toBe('1 个月前');
  });
  it('空值→空串', () => {
    expect(formatDaysAgo(null)).toBe('');
  });
});
```

Run: `cd frontend/apps/web && npx vitest run src/pages/__tests__/checklistHelpers.test.ts`
Expected: 若 Task 7 已建 helpers 则直接 PASS(10 passed);若未建则 FAIL——补建后重跑至 PASS。

- [ ] **Step 2: ManualItem 可编辑组件(替换 ManualItemReadonly)**

在 `Checklist.tsx` 中新增(保留只读组件可删):

```tsx
/** 手动项表单:text→textarea;choice→单选组;choice+text→单选+备注。
 *  防抖 800ms 自动保存;失焦立即保存;保存后回填 updated_at(乐观)。 */
function ManualItem({ it, symbol, onSaved }: {
  it: ChecklistItem;
  symbol: string;
  onSaved: (key: string) => void;
}) {
  const [text, setText] = useState(it.value_text ?? '');
  const [choice, setChoice] = useState(it.value_choice ?? '');
  const dirtyRef = useRef(false);

  // 防抖保存(800ms 静默后触发;对齐 Financial 页 compare 防抖先例)
  useEffect(() => {
    if (!dirtyRef.current) return;
    const t = setTimeout(() => {
      dirtyRef.current = false;
      fetch(`${getApiBase()}/checklist/${symbol}/items`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: [{ item_key: it.key, value_text: text, value_choice: choice }],
        }),
      })
        .then(r => r.json())
        .then(json => { if (json.code === 0) onSaved(it.key); })
        .catch(() => { /* 静默:下次编辑再存 */ });
    }, 800);
    return () => clearTimeout(t);
  }, [text, choice, it.key, symbol, onSaved]);

  const edit = (setter: (v: string) => void) => (v: string) => {
    dirtyRef.current = true;
    setter(v);
  };

  return (
    <div className="chk-item chk-item--manual">
      <span className={choice || text ? 'chk-dot chk-dot--ok' : 'chk-dot chk-dot--pending'}>
        {choice || text.trim() ? '已填' : '待填'}
      </span>
      <div className="chk-item__body">
        <div className="chk-item__head">
          <span className="chk-item__title">{it.title}</span>
          {it.updated_at && (
            <span className={`chk-item__date${(daysSince(it.updated_at) ?? 0) > 90 ? ' chk-item__date--stale' : ''}`}>
              上次填写 {formatDaysAgo(it.updated_at)}
              {(daysSince(it.updated_at) ?? 0) > 90 ? ' · 建议复检' : ''}
            </span>
          )}
        </div>
        {it.choices && (
          <div className="chk-choices">
            {it.choices.map(c => (
              <label key={c} className={`chk-choice${choice === c ? ' chk-choice--on' : ''}`}>
                <input
                  type="radio"
                  name={`${symbol}-${it.key}`}
                  checked={choice === c}
                  onChange={() => edit(setChoice)(c)}
                />
                {c}
              </label>
            ))}
          </div>
        )}
        {(it.input_type === 'text' || it.input_type === 'choice+text') && (
          <textarea
            className="chk-textarea"
            rows={it.input_type === 'text' ? 3 : 1}
            placeholder={it.input_type === 'choice+text' ? '备注(可选)' : '研究清楚了再填'}
            value={text}
            onChange={e => edit(setText)(e.target.value)}
          />
        )}
        {it.course && <div className="chk-item__hint">课程口径:{it.course}</div>}
      </div>
    </div>
  );
}
```

渲染处替换:`ManualItemReadonly` → `ManualItem`,并传入 `symbol` 与 `onSaved`:

```tsx
{sec.items.map(it => it.type === 'auto'
  ? <AutoItem key={it.key} it={it} />
  : <ManualItem key={it.key} it={it} symbol={symbol} onSaved={markSaved} />)}
```

`Checklist` 组件内加乐观回填(保存成功后更新该项 updated_at 为现在):

```tsx
  const markSaved = useCallback((key: string) => {
    setData(prev => prev && {
      ...prev,
      sections: prev.sections.map(s => ({ ...s, items: s.items.map(i =>
        i.key === key ? { ...i, updated_at: new Date().toISOString() } : i) })),
    });
  }, []);
```

议价备注(2.5 自动项下方的可编辑 textarea):`AutoItem` 接收 `symbol/onSaved`,当 `it.editable && it.note_key` 时渲染备注框(同 ManualItem 的防抖逻辑,复用同一组件不合适——直接在 AutoItem 里加一个轻量备注 textarea,保存到 `it.note_key`):

```tsx
function AutoItem({ it, symbol, onSaved }: { it: ChecklistItem; symbol: string; onSaved: (k: string) => void }) {
  const [note, setNote] = useState(it.note_text ?? '');
  const dirtyRef = useRef(false);
  useEffect(() => {
    if (!dirtyRef.current || !it.note_key) return;
    const t = setTimeout(() => {
      dirtyRef.current = false;
      fetch(`${getApiBase()}/checklist/${symbol}/items`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: [{ item_key: it.note_key!, value_text: note }] }),
      }).then(r => r.json()).then(j => { if (j.code === 0 && onSaved) onSaved(it.key); }).catch(() => {});
    }, 800);
    return () => clearTimeout(t);
  }, [note, it.note_key, it.key, symbol, onSaved]);
  // ……原 AutoItem 渲染,末尾追加:
  // {it.editable && it.note_key && (
  //   <textarea className="chk-textarea" rows={2}
  //     placeholder="补充自己的判断(可选,自动结论保留在上方)"
  //     value={note} onChange={e => { dirtyRef.current = true; setNote(e.target.value); }} />
  // )}
}
```

(实现时把上面注释展开进 JSX;`useRef` 补进文件 import。议价项的 `note_text` 需后端给:见 Step 4。)

- [ ] **Step 3: CSS 追加表单样式**

`Checklist.css` 追加:

```css
.chk-choices { display: flex; gap: 8px; flex-wrap: wrap; }
.chk-choice { display: inline-flex; gap: 4px; align-items: center; padding: 3px 10px; border: 1px solid var(--border-color, #2a2e37); border-radius: 999px; font-size: 12px; cursor: pointer; }
.chk-choice--on { border-color: #3fb950; color: #3fb950; }
.chk-textarea { width: 100%; background: rgba(255, 255, 255, 0.04); border: 1px solid var(--border-color, #2a2e37); border-radius: 6px; color: inherit; font-size: 12px; padding: 6px 8px; resize: vertical; box-sizing: border-box; }
```

- [ ] **Step 4: 后端给议价项补 note_text(小改)**

`checklist_status.py` 的 `_bargain_item` 已输出 `editable/note_key`;`build_checklist` 中议价 item 注入已存备注——在 `build_checklist` 行业区组装处,给 bargain 项附加 `note_text`:

```python
    bargain = _bargain_item(forces)
    note_row = saved.get(BARGAIN_NOTE_KEY)
    bargain["note_text"] = (note_row or {}).get("value_text")
    bargain["note_updated_at"] = (note_row or {}).get("updated_at")
```

并把行业区 items 里的 `_bargain_item(forces)` 替换为 `bargain` 变量;测试补一条断言(Task 2 测试文件追加):

```python
    def test_bargain_note_injected(self):
        saved = {BARGAIN_NOTE_KEY: {"value_text": "强甲方",
                                    "value_choice": None,
                                    "updated_at": "2026-09-01T00:00:00"}}
        out = build_checklist({}, saved)
        by = {it["key"]: s for s in out["sections"] for it in s["items"]}
        assert by["bargain"]["note_text"] == "强甲方"
```

Run: `cd backend && .venv/bin/python -m pytest tests/domain/market/fundamental/test_checklist_status.py -q`
Expected: PASS(18 passed)

- [ ] **Step 5: 构建 + 单测 + 冒烟**

```bash
cd frontend/apps/web && npm run build && npx vitest run src/pages/__tests__/checklistHelpers.test.ts
```
Expected: 构建成功;10 passed。

浏览器冒烟:`/checklist` 页选股→填定价权"是"→停1秒→刷新页面回显"已填";议价备注填写后刷新回显。

- [ ] **Step 6: Commit**

```bash
git add frontend/apps/web/src/pages/Checklist.tsx frontend/apps/web/src/pages/Checklist.css frontend/apps/web/src/pages/__tests__/checklistHelpers.test.ts backend/src/domain/market/fundamental/checklist_status.py backend/tests/domain/market/fundamental/test_checklist_status.py
git commit -m "feat(checklist): 手动项表单+800ms防抖保存+复检提醒+议价可编辑备注"
```

---

### Task 9: 全量回归 + 收尾

**Files:**
- 无新文件;跑齐所有验证。

- [ ] **Step 1: 后端纯函数全量回归**

```bash
cd backend && .venv/bin/python -m pytest tests/domain/market/fundamental tests/domain/market/portfolio tests/domain/market/intel tests/domain/market/equity tests/domain/market/derivatives tests/domain/market/strategy/test_ipo_cb.py tests/domain/market/strategy/test_growth_value.py tests/domain/market/equity/test_concentration.py -q
```
Expected: 全绿(基线 388 + 新增 29 = 417 passed 左右)。

- [ ] **Step 2: 后端装配完整性**

```bash
cd backend && .venv/bin/python -c "
from main import app
routes = [r.path for r in app.routes]
assert '/api/v1/checklist/{symbol}' in routes
assert '/api/v1/checklist/{symbol}/items' in routes
print('routes ok')
"
```
Expected: `routes ok`。

- [ ] **Step 3: 前端构建 + 全部单测**

```bash
cd frontend/apps/web && npm run build && npx vitest run
```
Expected: 构建成功;vitest 全绿(replay 既有 + checklist 新增)。

- [ ] **Step 4: 端到端冒烟(真服务)**

```bash
cd backend && .venv/bin/python -m uvicorn main:app --port 8001 &>/tmp/uv9.log & sleep 6
curl -s "http://127.0.0.1:8001/api/v1/checklist/sh600519" | python3 -m json.tool | head -40
kill %1
```
浏览器:`/checklist` 完整走一遍——选股/自动项/填手动项/刷新回显/议价备注/复检提醒文案。

- [ ] **Step 5: 最终 Commit**

```bash
git add -A
git commit -m "test(checklist): 全量回归通过——后端417纯函数绿/前端build+vitest绿/端到端冒烟通过"
```

---

## Self-Review 记录

1. **Spec 覆盖**:四区21项(自动12/手动9)→ Task 2/4/7/8;独立页面+菜单 → Task 7;纯手动 → Task 8(无 AI);只展示不下结论 → Task 2(`build_checklist` 测试断言无 verdict);2.5 自动+可编辑 → Task 2 `_bargain_item` + Task 8 Step 4;表/Repo → Task 3;2 端点 → Task 5;防抖保存/复检提醒 → Task 8;missing 降级 → Task 2/4;课程 hint → Task 2 常量。缺口:无。
2. **占位符扫描**:Task 4 两处"实测确认列名"(stock_ohlcv 时间列、shareholder_info 列)已给出确认命令与对齐来源(financial_router.py:707),属环境事实而非计划缺失。无 TBD/TODO。
3. **类型一致性**:`trend_state`→`kline_trend` 键(Task 1 dict ↔ Task 4 sources["kline_trend"]);`build_checklist(sources, saved)` 两任务签名一致;`sanitize_items` 返回 `{item_key, value_text, value_choice}` ↔ Task 3 `upsert_items` 入参;前端 `ChecklistItem.note_text` ↔ Task 8 Step 4 后端注入键;`chk-*` 类名 CSS/TSX 一致。
