# 永久投资组合 (Permanent Portfolio) 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 ytrader 平台交付一个完整的多组合管理 + 跨市场净值监控 + 再平衡建议 + 历史回测功能，落地 `/perm-portfolio` 页面与 `/api/v1/perm-portfolio/*` API。

**Architecture:** 领域层纯函数（净值/再平衡计算）→ 基础设施层 SQLModel 仓储（5 张表）→ 数据同步 job（行情 + 汇率 + 每日净值）→ HTTP 层（13 端点）→ React 前端页（组合列表 + 概览/再平衡/持仓三 tab）。回测复用现有 `lt-backtest` 引擎，仅新增一个固定权重策略适配器。标的池从 `config.yaml` 迁移到 DB，新增港股分流与 HKDCNY 汇率支持。

**Tech Stack:**
- 后端：Python 3.13 / FastAPI / SQLModel / SQLAlchemy / psycopg2 / akshare
- 数据库：PostgreSQL（SQLModel `create_all` 自动建表）
- 测试：pytest
- 前端：React + TypeScript / react-router / recharts / CSS BEM
- 调度：cron（工作日 16:30 同步行情，17:00 算净值）

## Global Constraints

下列约束源自 spec 与 `CLAUDE.md`，适用于本计划所有任务：

- **路由前缀**：`/api/v1/perm-portfolio`（避开已被交易持仓归因占用的 `/api/v1/portfolio`）；前端路由 `/perm-portfolio`。
- **建表机制**：只用 SQLModel `metadata.create_all`（`DBConnection(auto_create_tables=True)` 自动调用），**禁止手写 DDL**。
- **建表关键坑**：新表的 `class X(SQLModel, table=True)` 必须在 `backend/main.py` 启动路径被 import 才会进 metadata。仿照现有 `from src.infra.database.agent.entity import ...`（`main.py` L134-136）追加 import。
- **stock_ohlcv 是裸 SQL 表**（无 SQLModel）：用 `session.exec(text("..."), params={...})` 查询；日期比较带时间字符串 `'YYYY-MM-DD 23:59:59'`。
- **响应规范**：统一用 `from src.pkg import responses`，返回 `responses.success(data)` / `responses.fail(msg=...)` / `responses.error(...)`；handler 内 repository 延迟 import + 工厂创建。
- **代码风格**：行宽 79；强制类型注解；`snake_case`；模块顶部 docstring；DDL 字段用 `Field`。
- **DDD 分层**：`domain/market/portfolio/` 纯计算不碰 DB；`infra/database/portfolio/` 表 + 仓储；`api/router` + `api/handler` HTTP 层。
- **再平衡口径**：`max_drift` 与触发判断按**资产类**（equity/bond/gold/cash）聚合，不是按单标的；`portfolio_nav_item.drift` 记录单标的对所在资产类偏离的贡献。
- **YAGNI 边界**：不做实盘下单、分钟级监控、告警推送、税务建模、盘中实时刷新。

---

## File Structure

下列文件全部路径以 `backend/` 为后端根、`frontend/apps/web/src/` 为前端根。

### 新建文件

| 路径 | 职责 |
|---|---|
| `backend/src/domain/market/portfolio/__init__.py` | 包标记 |
| `backend/src/domain/market/portfolio/nav_calculator.py` | 净值/权重/偏离纯函数 + dataclass 输入输出 |
| `backend/src/domain/market/portfolio/rebalance_advisor.py` | 再平衡建议纯函数（产出买卖指令） |
| `backend/src/domain/market/portfolio/permanent_strategy.py` | `FixedWeightStrategy(LongTermStrategy)` 回测适配器 |
| `backend/src/infra/database/portfolio/__init__.py` | 包标记 |
| `backend/src/infra/database/portfolio/models.py` | 5 张 SQLModel 表 |
| `backend/src/infra/database/portfolio/repository.py` | `PortfolioRepository` + `create_portfolio_repository()` 工厂 |
| `backend/src/api/router/perm_portfolio_router.py` | `APIRouter(prefix="/perm-portfolio")` + 13 端点 |
| `backend/src/api/handler/perm_portfolio_handler.py` | handler 函数（调 repository，返回 `responses.*`） |
| `backend/src/domain/market/sync/jobs/portfolio_nav_daily.py` | 每日净值 job（17:00 cron） |
| `backend/scripts/seed_portfolio_instruments.py` | 标的池 seed（A/HK/US 12 标的 + 港股 4 标的） |
| `backend/scripts/seed_preset_portfolios.py` | 3 个预置组合 seed（永久/全天候/黄金蝴蝶） |
| `backend/tests/domain/market/portfolio/__init__.py` | 包标记 |
| `backend/tests/domain/market/portfolio/test_nav_calculator.py` | 净值计算单测 |
| `backend/tests/domain/market/portfolio/test_rebalance_advisor.py` | 再平衡建议单测 |
| `backend/tests/domain/market/portfolio/test_permanent_strategy.py` | 固定权重策略单测 |
| `backend/tests/domain/market/portfolio/test_models.py` | 5 张表实例化冒烟测 |
| `backend/tests/infra/database/portfolio/__init__.py` | 包标记 |
| `backend/tests/infra/database/portfolio/test_repository.py` | 仓储集成测试（sqlite fixture） |
| `backend/tests/domain/market/sync/providers/test_akshare_portfolio.py` | 港股分流 + HKDCNY 单测 |
| `frontend/apps/web/src/pages/PermPortfolio.tsx` | 永久组合主页面（3 tab） |
| `frontend/apps/web/src/pages/PermPortfolio.css` | BEM 样式（暗色主题） |

### 修改文件

| 路径 | 改动 |
|---|---|
| `backend/main.py` L134-136 附近 | 追加 `from src.infra.database.portfolio.models import ...` 让 `create_all` 收表；追加路由 import + `app.include_router(perm_portfolio_router, prefix="/api/v1")` |
| `backend/src/domain/market/sync/providers/akshare_provider.py` L94-103 | `fetch_daily` 加港股分流（5 位纯数字 → `fetch_hk_stock_daily`） |
| `backend/src/domain/market/sync/providers/akshare_provider.py` L208-247 | `fetch_fx_daily` 放开多 pair（`_FX_BOC_SYMBOL` 映射） |
| `backend/src/domain/market/sync/jobs/portfolio_daily.py` L45-69 | 标的源从 `app_config.portfolio_universe.bars` 改为 `portfolio_instrument WHERE enabled=true`；FX 同步从活跃组合涉及币种派生 |
| `backend/src/infra/database/market/fx_rate.py` | `FxRateRepository` 增 `get_rate(pair, date_)` 方法 |
| `frontend/apps/web/src/App.tsx` L39 + L79 附近 | 懒加载 `PermPortfolio` + `<Route path="/perm-portfolio">` |
| `frontend/apps/web/src/components/Layout.tsx` L46-55 | Strategy 组加 `{path: '/perm-portfolio', label: '永久组合', icon: Icon.portfolio}` |

---

## Task 1: nav_calculator 纯函数 + 单测

净值/权重/偏离核心算法。无 DB 依赖，最先做，给后续 job/API 打地基。

**Files:**
- Create: `backend/src/domain/market/portfolio/__init__.py`
- Create: `backend/src/domain/market/portfolio/nav_calculator.py`
- Test: `backend/tests/domain/market/portfolio/__init__.py`
- Test: `backend/tests/domain/market/portfolio/test_nav_calculator.py`

**Interfaces:**
- Consumes: 无（纯函数）。
- Produces: `calc_portfolio_nav(initial_capital, threshold, items_in) -> NavResult`；dataclass `NavItemInput` / `NavItemOutput` / `NavResult`。后续 Task 6（nav job）和 Task 8（rebalance 端点）依赖这些类型。

- [ ] **Step 1: Write the failing test**

Create `backend/tests/domain/market/portfolio/__init__.py` (empty file).

Create `backend/tests/domain/market/portfolio/test_nav_calculator.py`:

```python
"""nav_calculator 单测：净值/权重/偏离核心算法。"""
from datetime import date

from src.domain.market.portfolio.nav_calculator import (
    NavItemInput,
    calc_portfolio_nav,
)


def _item(
    instrument_id: int,
    symbol: str,
    asset_class: str,
    target_weight: float,
    shares: int,
    price: float,
    fx_rate: float = 1.0,
) -> NavItemInput:
    return NavItemInput(
        instrument_id=instrument_id,
        symbol=symbol,
        asset_class=asset_class,
        target_weight=target_weight,
        shares=shares,
        price=price,
        fx_rate=fx_rate,
    )


def test_equal_weight_four_classes_no_drift():
    """4 标的等权重，价格不变 → nav=1.0，各类 drift=0。"""
    # 每类 initial_capital * 0.25 = 25000，股价 10 → shares 2500
    items = [
        _item(1, "sh510300", "equity", 0.25, 2500, 10.0),
        _item(2, "sh511260", "bond", 0.25, 2500, 10.0),
        _item(3, "sh518880", "gold", 0.25, 2500, 10.0),
        _item(4, "sh511990", "cash", 0.25, 2500, 10.0),
    ]
    r = calc_portfolio_nav(100000.0, 0.05, items)
    assert r.total_value_cny == 100000.0
    assert abs(r.nav_cny - 1.0) < 1e-9
    assert abs(r.max_drift) < 1e-9
    assert r.rebalance_suggested is False
    # 各资产类 actual_weight = 0.25
    by_class = {it.asset_class: it.actual_weight for it in r.items}
    for cls in ("equity", "bond", "gold", "cash"):
        assert abs(by_class[cls] - 0.25) < 1e-9


def test_drift_after_price_change_triggers_rebalance():
    """股票大涨 → 股票类超配，max_drift > threshold 触发。"""
    items = [
        _item(1, "sh510300", "equity", 0.25, 2500, 20.0),  # 翻倍
        _item(2, "sh511260", "bond", 0.25, 2500, 10.0),
        _item(3, "sh518880", "gold", 0.25, 2500, 10.0),
        _item(4, "sh511990", "cash", 0.25, 2500, 10.0),
    ]
    # total = 50000 + 25000*3 = 125000
    # equity actual = 50000/125000 = 0.4, drift = +0.15
    r = calc_portfolio_nav(100000.0, 0.05, items)
    assert abs(r.total_value_cny - 125000.0) < 1e-6
    assert abs(r.nav_cny - 1.25) < 1e-9
    assert abs(r.max_drift - 0.15) < 1e-9
    assert r.rebalance_suggested is True
    equity_item = next(it for it in r.items if it.asset_class == "equity")
    assert abs(equity_item.drift - 0.15) < 1e-9


def test_fx_conversion_hkd_usd_to_cny():
    """跨币种折算：HKD/USD 标的按 fx_rate 折人民币。"""
    # 港股 02800，1000 股 × 10 HKD × 0.9 = 9000 CNY
    # 美股 VOO，100 股 × 400 USD × 7.2 = 288000 CNY
    items = [
        _item(1, "02800", "equity", 0.5, 1000, 10.0, fx_rate=0.9),
        _item(2, "VOO", "equity", 0.5, 100, 400.0, fx_rate=7.2),
    ]
    r = calc_portfolio_nav(297000.0, 0.05, items)
    assert abs(r.total_value_cny - 297000.0) < 1e-6
    # 同类聚合 equity actual = 1.0
    assert abs(r.items[0].actual_weight - 1.0) < 1e-9


def test_multi_instrument_same_class_aggregation():
    """同类多标的：target_weight 相加，actual 按市值聚合。"""
    # 股票类两标的各 target 0.125，合计 0.25
    items = [
        _item(1, "sh510300", "equity", 0.125, 1000, 10.0),  # 10000
        _item(2, "VOO", "equity", 0.125, 100, 100.0, fx_rate=1.0),  # 10000
        _item(3, "sh511260", "bond", 0.25, 4000, 10.0),  # 40000
        _item(4, "sh518880", "gold", 0.25, 4000, 10.0),  # 40000
        _item(5, "sh511990", "cash", 0.25, 4000, 10.0),  # 40000
    ]
    # total = 20000 + 120000 = 140000
    # equity actual = 20000/140000 ≈ 0.142857, target 0.25, drift ≈ -0.107
    r = calc_portfolio_nav(140000.0, 0.05, items)
    assert abs(r.total_value_cny - 140000.0) < 1e-6
    equity_items = [it for it in r.items if it.asset_class == "equity"]
    # 单标的 drift = actual - target(单) = 0.0714 - 0.125
    # 但 max_drift 是资产类层面
    assert abs(r.max_drift - abs(0.2 / 1.4 - 0.25)) < 1e-6
    # 两个 equity 单标的 drift 之和 = 资产类 drift
    single_sum = sum(it.drift for it in equity_items)
    assert abs(single_sum - (0.2 / 1.4 - 0.25)) < 1e-6


def test_max_drift_takes_largest_absolute():
    """多类偏离时 max_drift 取绝对值最大那个。"""
    items = [
        _item(1, "sh510300", "equity", 0.25, 2500, 30.0),  # +0.25 类
        _item(2, "sh511260", "bond", 0.25, 2500, 5.0),     # -0.125 类
        _item(3, "sh518880", "gold", 0.25, 2500, 10.0),
        _item(4, "sh511990", "cash", 0.25, 2500, 10.0),
    ]
    # total = 75000+12500+25000+25000 = 137500
    # equity = 75000/137500 ≈ 0.545 drift ≈ +0.295
    # bond = 12500/137500 ≈ 0.091 drift ≈ -0.159
    r = calc_portfolio_nav(100000.0, 0.05, items)
    assert r.max_drift > 0.29
    assert r.max_drift < 0.30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/market/portfolio/test_nav_calculator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.domain.market.portfolio'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/src/domain/market/portfolio/__init__.py` (empty docstring):

```python
"""永久投资组合领域层：净值计算、再平衡建议、回测策略适配器。"""
```

Create `backend/src/domain/market/portfolio/nav_calculator.py`:

```python
"""
组合净值计算引擎（纯函数）
=========================
输入各标的（股数/收盘价/汇率/目标权重），输出组合净值、
各标的实际权重、各资产类偏离、是否触发再平衡。

口径约定（重要）：
  - target_weight 是单标的的目标权重。
  - 再平衡判断按资产类（equity/bond/gold/cash）聚合：
    actual_weight_class = Σ(value_cny of class) / total_value_cny
    target_weight_class = Σ(target_weight of class)
    drift_class = actual_weight_class - target_weight_class
  - max_drift = max(|drift_class|) across all classes。
  - 单标的 item.drift = item.actual_weight - item.target_weight
    （它对所在资产类偏离的贡献，供下钻定位）。
  - rebalance_suggested = max_drift > threshold。
"""
from dataclasses import dataclass, field


@dataclass
class NavItemInput:
    """单标的的净值计算输入。"""
    instrument_id: int
    symbol: str
    asset_class: str          # equity | bond | gold | cash
    target_weight: float      # 单标的的目标权重（0~1）
    shares: int
    price: float              # 原币种收盘价
    fx_rate: float            # 折算 CNY 的汇率（CNY 标的 = 1.0）


@dataclass
class NavItemOutput:
    """单标的的净值计算输出。"""
    instrument_id: int
    symbol: str
    asset_class: str
    target_weight: float
    shares: int
    price: float
    fx_rate: float
    value_cny: float          # = shares * price * fx_rate
    actual_weight: float      # = value_cny / total_value_cny
    drift: float              # = actual_weight - target_weight


@dataclass
class NavResult:
    """组合净值计算结果。"""
    total_value_cny: float
    nav_cny: float            # = total_value_cny / initial_capital
    items: list[NavItemOutput] = field(default_factory=list)
    max_drift: float = 0.0
    rebalance_suggested: bool = False


def calc_portfolio_nav(
    initial_capital: float,
    threshold: float,
    items_in: list[NavItemInput],
) -> NavResult:
    """计算组合净值 / 各标的实际权重 / 资产类最大偏离。

    Args:
        initial_capital:  初始资金（净值归一化基准）。
        threshold:        触发再平衡的偏离阈值（如 0.05）。
        items_in:         各标的的输入列表。

    Returns:
        NavResult。
    """
    # 1. 单标的 value_cny
    valued: list[NavItemOutput] = []
    for it in items_in:
        value_cny = it.shares * it.price * it.fx_rate
        valued.append(
            NavItemOutput(
                instrument_id=it.instrument_id,
                symbol=it.symbol,
                asset_class=it.asset_class,
                target_weight=it.target_weight,
                shares=it.shares,
                price=it.price,
                fx_rate=it.fx_rate,
                value_cny=value_cny,
                actual_weight=0.0,
                drift=0.0,
            )
        )

    # 2. total_value_cny
    total = sum(v.value_cny for v in valued)

    # 3. 单标的 actual_weight
    for v in valued:
        v.actual_weight = (
            v.value_cny / total if total > 0 else 0.0
        )

    # 4. 资产类聚合：target_class / actual_class
    target_by_class: dict[str, float] = {}
    actual_by_class: dict[str, float] = {}
    for v in valued:
        target_by_class[v.asset_class] = (
            target_by_class.get(v.asset_class, 0.0) + v.target_weight
        )
        actual_by_class[v.asset_class] = (
            actual_by_class.get(v.asset_class, 0.0) + v.actual_weight
        )

    # 5. max_drift（资产类层面，绝对值）
    max_drift = 0.0
    for cls, tgt in target_by_class.items():
        act = actual_by_class.get(cls, 0.0)
        d = abs(act - tgt)
        if d > max_drift:
            max_drift = d

    # 6. nav_cny
    nav = total / initial_capital if initial_capital > 0 else 0.0

    # 7. rebalance flag
    suggested = max_drift > threshold

    return NavResult(
        total_value_cny=total,
        nav_cny=nav,
        items=valued,
        max_drift=max_drift,
        rebalance_suggested=suggested,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/market/portfolio/test_nav_calculator.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/src/domain/market/portfolio/__init__.py \
        backend/src/domain/market/portfolio/nav_calculator.py \
        backend/tests/domain/market/portfolio/__init__.py \
        backend/tests/domain/market/portfolio/test_nav_calculator.py
git commit -m "feat(portfolio): add nav_calculator pure function with tests"
```

---

## Task 2: rebalance_advisor 纯函数 + 单测

当 `max_drift > threshold` 时产出具体买卖指令。纯函数，依赖 Task 1 的 `NavItemOutput` 思路但接收更简单的输入（避免硬耦合 DB 表类型）。

**Files:**
- Create: `backend/src/domain/market/portfolio/rebalance_advisor.py`
- Test: `backend/tests/domain/market/portfolio/test_rebalance_advisor.py`

**Interfaces:**
- Consumes: Task 1 的口径约定（资产类聚合）。
- Produces: `suggest_rebalance(holdings, nav_items, total_value_cny, threshold) -> list[RebalanceAction]`；dataclass `RebalanceHolding` / `RebalanceNavItem` / `RebalanceAction`。Task 8 的 `GET /portfolios/{id}/rebalance` 端点依赖此函数。

- [ ] **Step 1: Write the failing test**

Create `backend/tests/domain/market/portfolio/test_rebalance_advisor.py`:

```python
"""rebalance_advisor 单测：再平衡建议算法。"""
from src.domain.market.portfolio.rebalance_advisor import (
    RebalanceAction,
    RebalanceHolding,
    RebalanceNavItem,
    suggest_rebalance,
)


def test_overweight_class_sells():
    """股票类超配 → 产出卖出指令。"""
    # total = 125000, equity 50000 (actual 0.4, target 0.25)
    holdings = [
        RebalanceHolding(
            instrument_id=1, symbol="sh510300",
            asset_class="equity", target_weight=0.25,
            shares=2500,
        ),
        RebalanceHolding(
            instrument_id=2, symbol="sh511260",
            asset_class="bond", target_weight=0.25,
            shares=2500,
        ),
    ]
    nav_items = [
        RebalanceNavItem(
            instrument_id=1, symbol="sh510300",
            asset_class="equity", shares=2500,
            price_cny=20.0, value_cny=50000.0,
        ),
        RebalanceNavItem(
            instrument_id=2, symbol="sh511260",
            asset_class="bond", shares=2500,
            price_cny=10.0, value_cny=25000.0,
        ),
    ]
    actions = suggest_rebalance(
        holdings, nav_items, total_value_cny=125000.0, threshold=0.05,
    )
    # 股票超配：需卖出 (0.4-0.25)*125000 = 18750 → 18750/20 = 937 股
    sells = [a for a in actions if a.action == "SELL"]
    assert len(sells) == 1
    assert sells[0].symbol == "sh510300"
    assert sells[0].shares_delta == 937
    assert "超配" in sells[0].reason


def test_underweight_class_buys():
    """债券类低配 → 产出买入指令。"""
    holdings = [
        RebalanceHolding(
            instrument_id=1, symbol="sh510300",
            asset_class="equity", target_weight=0.25,
            shares=2500,
        ),
        RebalanceHolding(
            instrument_id=2, symbol="sh511260",
            asset_class="bond", target_weight=0.25,
            shares=2500,
        ),
    ]
    nav_items = [
        RebalanceNavItem(
            instrument_id=1, symbol="sh510300",
            asset_class="equity", shares=2500,
            price_cny=10.0, value_cny=25000.0,
        ),
        RebalanceNavItem(
            instrument_id=2, symbol="sh511260",
            asset_class="bond", shares=2500,
            price_cny=5.0, value_cny=12500.0,
        ),
    ]
    # total = 37500, equity 0.667, bond 0.333
    # bond target 0.25, actual 0.333 → 实际比 target 高？不，等权场景下
    # 只有 2 类，target 合计 0.5，actual 合计 1.0，需用 actual_class - target_class
    # 这里 bond actual = 12500/37500 = 0.333, target 0.25 → 超配
    actions = suggest_rebalance(
        holdings, nav_items, total_value_cny=37500.0, threshold=0.05,
    )
    # bond 超配 → 卖 bond；equity actual 0.667 target 0.25 超配也卖
    # 此测重点验证：低配类（若构造）会买。改成低配场景：
    holdings2 = [
        RebalanceHolding(
            instrument_id=1, symbol="sh510300",
            asset_class="equity", target_weight=0.5,
            shares=1000,
        ),
        RebalanceHolding(
            instrument_id=2, symbol="sh511260",
            asset_class="bond", target_weight=0.5,
            shares=1000,
        ),
    ]
    nav_items2 = [
        RebalanceNavItem(
            instrument_id=1, symbol="sh510300",
            asset_class="equity", shares=1000,
            price_cny=10.0, value_cny=10000.0,
        ),
        RebalanceNavItem(
            instrument_id=2, symbol="sh511260",
            asset_class="bond", shares=1000,
            price_cny=20.0, value_cny=20000.0,
        ),
    ]
    # total = 30000, equity 0.333 target 0.5 → 低配，需买
    # 需买入市值 = (0.5-0.333)*30000 = 5000 → 5000/10 = 500 股
    actions2 = suggest_rebalance(
        holdings2, nav_items2, total_value_cny=30000.0, threshold=0.05,
    )
    buys = [a for a in actions2 if a.action == "BUY"]
    assert len(buys) == 1
    assert buys[0].symbol == "sh510300"
    assert buys[0].shares_delta == 500


def test_no_action_when_within_threshold():
    """偏离在阈值内 → 不产出指令。"""
    holdings = [
        RebalanceHolding(
            instrument_id=1, symbol="sh510300",
            asset_class="equity", target_weight=0.5,
            shares=1000,
        ),
        RebalanceHolding(
            instrument_id=2, symbol="sh511260",
            asset_class="bond", target_weight=0.5,
            shares=1000,
        ),
    ]
    nav_items = [
        RebalanceNavItem(
            instrument_id=1, symbol="sh510300",
            asset_class="equity", shares=1000,
            price_cny=10.0, value_cny=10000.0,
        ),
        RebalanceNavItem(
            instrument_id=2, symbol="sh511260",
            asset_class="bond", shares=1000,
            price_cny=10.5, value_cny=10500.0,
        ),
    ]
    # total 20500, equity 0.4878 target 0.5 drift -0.012 < 0.05
    actions = suggest_rebalance(
        holdings, nav_items, total_value_cny=20500.0, threshold=0.05,
    )
    assert actions == []


def test_multi_instrument_class_proportional_split():
    """同类多标的按当前市值比例分摊卖出。"""
    holdings = [
        RebalanceHolding(
            instrument_id=1, symbol="sh510300",
            asset_class="equity", target_weight=0.125,
            shares=1000,
        ),
        RebalanceHolding(
            instrument_id=2, symbol="VOO",
            asset_class="equity", target_weight=0.125,
            shares=100,
        ),
        RebalanceHolding(
            instrument_id=3, symbol="sh511260",
            asset_class="bond", target_weight=0.25,
            shares=4000,
        ),
        RebalanceHolding(
            instrument_id=4, symbol="sh518880",
            asset_class="gold", target_weight=0.25,
            shares=4000,
        ),
        RebalanceHolding(
            instrument_id=5, symbol="sh511990",
            asset_class="cash", target_weight=0.25,
            shares=4000,
        ),
    ]
    # 让 equity 涨：300 10→30, VOO 100→100
    nav_items = [
        RebalanceNavItem(1, "sh510300", "equity", 1000, 30.0, 30000.0),
        RebalanceNavItem(2, "VOO", "equity", 100, 100.0, 10000.0),
        RebalanceNavItem(3, "sh511260", "bond", 4000, 10.0, 40000.0),
        RebalanceNavItem(4, "sh518880", "gold", 4000, 10.0, 40000.0),
        RebalanceNavItem(5, "sh511990", "cash", 4000, 10.0, 40000.0),
    ]
    # total = 160000, equity actual = 40000/160000 = 0.25, target 0.25
    # 实际没偏离！需把 equity 抬更高触发卖出
    nav_items[0] = RebalanceNavItem(
        1, "sh510300", "equity", 1000, 60.0, 60000.0,
    )
    # total = 190000, equity actual = 70000/190000 ≈ 0.368, target 0.25
    # 需卖 (0.368-0.25)*190000 ≈ 22421 → 按市值比例分摊
    # 300 占 60000/70000=0.857 → 卖 22421*0.857/60 ≈ 320 股
    # VOO 占 0.143 → 卖 22421*0.143/100 ≈ 32 股
    actions = suggest_rebalance(
        holdings, nav_items, total_value_cny=190000.0, threshold=0.05,
    )
    sells = [a for a in actions if a.action == "SELL"]
    syms = {a.symbol for a in sells}
    assert "sh510300" in syms
    assert "VOO" in syms
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/market/portfolio/test_rebalance_advisor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.domain.market.portfolio.rebalance_advisor'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/src/domain/market/portfolio/rebalance_advisor.py`:

```python
"""
再平衡建议引擎（纯函数）
=======================
输入当前持仓 + 最新净值明细 + 总市值 + 阈值，输出买卖指令列表。

口径（与 nav_calculator 对齐）：
  - 偏离按资产类聚合判断。
  - 超配类（actual_class > target_class）：按该类内各标的的当前市值比例
    分摊卖出股数。卖出市值 = (actual_class - target_class) * total_value。
  - 低配类（actual_class < target_class）：按该类内各标的的目标权重比例
    分摊买入股数。买入市值 = (target_class - actual_class) * total_value。
  - 偏离在阈值内 → 不产出指令。
"""
from dataclasses import dataclass


@dataclass
class RebalanceHolding:
    """再平衡输入：持仓快照。"""
    instrument_id: int
    symbol: str
    asset_class: str
    target_weight: float        # 单标的的目标权重
    shares: int


@dataclass
class RebalanceNavItem:
    """再平衡输入：最新净值明细。"""
    instrument_id: int
    symbol: str
    asset_class: str
    shares: int
    price_cny: float            # 折人民币的当日价
    value_cny: float            # = shares * price_cny


@dataclass
class RebalanceAction:
    """再平衡输出：单条买卖指令。"""
    instrument_id: int
    symbol: str
    asset_class: str
    action: str                 # "BUY" | "SELL"
    shares_delta: int           # 调仓股数（正数绝对值，方向由 action 决定）
    reason: str


def suggest_rebalance(
    holdings: list[RebalanceHolding],
    nav_items: list[RebalanceNavItem],
    total_value_cny: float,
    threshold: float,
) -> list[RebalanceAction]:
    """产出再平衡买卖指令。

    Args:
        holdings:        当前持仓列表。
        nav_items:       最新净值明细（与 holdings 按 instrument_id 对齐）。
        total_value_cny: 组合当前总市值（人民币）。
        threshold:       触发再平衡的资产类偏离阈值。

    Returns:
        买卖指令列表；偏离在阈值内时返回空列表。
    """
    if total_value_cny <= 0:
        return []

    # 1. 按 instrument_id 对齐 holdings 与 nav_items
    nav_by_inst = {n.instrument_id: n for n in nav_items}

    # 2. 资产类聚合：target_class / actual_class / 当前价
    target_by_class: dict[str, float] = {}
    value_by_class: dict[str, float] = {}
    items_by_class: dict[str, list[dict]] = {}
    for h in holdings:
        n = nav_by_inst.get(h.instrument_id)
        if n is None:
            continue
        target_by_class[h.asset_class] = (
            target_by_class.get(h.asset_class, 0.0) + h.target_weight
        )
        value_by_class[h.asset_class] = (
            value_by_class.get(h.asset_class, 0.0) + n.value_cny
        )
        items_by_class.setdefault(h.asset_class, []).append(
            {"holding": h, "nav": n}
        )

    actions: list[RebalanceAction] = []
    for cls, target_w in target_by_class.items():
        actual_w = value_by_class.get(cls, 0.0) / total_value_cny
        drift = actual_w - target_w
        if abs(drift) <= threshold:
            continue

        members = items_by_class.get(cls, [])
        if not members:
            continue

        if drift > 0:
            # 超配 → 卖出，按当前市值比例分摊
            sell_value = drift * total_value_cny
            class_total_value = value_by_class[cls]
            if class_total_value <= 0:
                continue
            for m in members:
                n = m["nav"]
                proportion = n.value_cny / class_total_value
                shares_delta = int(
                    (sell_value * proportion) / n.price_cny
                ) if n.price_cny > 0 else 0
                if shares_delta <= 0:
                    continue
                actions.append(
                    RebalanceAction(
                        instrument_id=n.instrument_id,
                        symbol=n.symbol,
                        asset_class=cls,
                        action="SELL",
                        shares_delta=shares_delta,
                        reason=(
                            f"{cls} 类超配 "
                            f"(actual {actual_w:.1%} > target "
                            f"{target_w:.1%})，按市值比例卖出"
                        ),
                    )
                )
        else:
            # 低配 → 买入，按目标权重比例分摊
            buy_value = -drift * total_value_cny
            class_target = target_w
            if class_target <= 0:
                continue
            for m in members:
                h = m["holding"]
                n = m["nav"]
                proportion = h.target_weight / class_target
                shares_delta = int(
                    (buy_value * proportion) / n.price_cny
                ) if n.price_cny > 0 else 0
                if shares_delta <= 0:
                    continue
                actions.append(
                    RebalanceAction(
                        instrument_id=n.instrument_id,
                        symbol=n.symbol,
                        asset_class=cls,
                        action="BUY",
                        shares_delta=shares_delta,
                        reason=(
                            f"{cls} 类低配 "
                            f"(actual {actual_w:.1%} < target "
                            f"{target_w:.1%})，按目标权重比例买入"
                        ),
                    )
                )

    return actions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/market/portfolio/test_rebalance_advisor.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/src/domain/market/portfolio/rebalance_advisor.py \
        backend/tests/domain/market/portfolio/test_rebalance_advisor.py
git commit -m "feat(portfolio): add rebalance_advisor pure function with tests"
```

---

## Task 3: 5 张 SQLModel 表 + main.py import 注册

定义 5 张表并确保启动时进 `SQLModel.metadata`（关键坑：必须在 `main.py` import）。

**Files:**
- Create: `backend/src/infra/database/portfolio/__init__.py`
- Create: `backend/src/infra/database/portfolio/models.py`
- Modify: `backend/main.py`（L134-136 附近 import 块追加）
- Test: `backend/tests/domain/market/portfolio/test_models.py`

**Interfaces:**
- Consumes: `SQLModel` / `Field` / `UniqueConstraint`。
- Produces: 5 个 SQLModel 表类 `PortfolioInstrument` / `PortfolioDefinition` / `PortfolioHolding` / `PortfolioNav` / `PortfolioNavItem`。Task 4 仓储、Task 6 job、Task 8 API 全部依赖。

- [ ] **Step 1: Write the failing test**

Create `backend/tests/domain/market/portfolio/test_models.py`:

```python
"""5 张表实例化冒烟测：确保字段默认值/类型正确，可进 SQLModel metadata。"""
from datetime import date, datetime

from sqlmodel import SQLModel

from src.infra.database.portfolio.models import (
    PortfolioDefinition,
    PortfolioHolding,
    PortfolioInstrument,
    PortfolioNav,
    PortfolioNavItem,
)


def test_all_five_tables_registered_in_metadata():
    """5 张表都进 SQLModel.metadata（create_all 能建表的前提）。"""
    names = SQLModel.metadata.tables.keys()
    for t in (
        "portfolio_instrument",
        "portfolio_definition",
        "portfolio_holding",
        "portfolio_nav",
        "portfolio_nav_item",
    ):
        assert t in names, f"{t} 未注册进 metadata"


def test_instrument_defaults():
    inst = PortfolioInstrument(
        symbol="sh510300", market="A", asset_class="equity",
        ccy="CNY", name="沪深300ETF",
    )
    assert inst.provider == "akshare"
    assert inst.enabled is True
    assert isinstance(inst.created_at, datetime)


def test_definition_defaults():
    d = PortfolioDefinition(name="永久投资组合", strategy_type="permanent")
    assert d.base_ccy == "CNY"
    assert d.rebalance_threshold == 0.05
    assert d.initial_capital == 100000.0
    assert d.is_active is True


def test_holding_basic():
    h = PortfolioHolding(
        portfolio_id=1, instrument_id=2,
        target_weight=0.25, shares=1000, cost_price=10.0,
    )
    assert h.target_weight == 0.25
    assert h.shares == 1000


def test_nav_basic():
    n = PortfolioNav(
        portfolio_id=1, trade_date=date(2026, 8, 7),
        nav_cny=1.05, prev_nav_cny=1.04, daily_return=0.0096,
        total_value_cny=105000.0, max_drift=0.03,
        rebalance_suggested=False,
    )
    assert n.nav_cny == 1.05
    assert n.rebalance_suggested is False


def test_nav_item_basic():
    ni = PortfolioNavItem(
        nav_id=1, instrument_id=2, symbol="sh510300",
        asset_class="equity", shares=1000,
        price=10.0, price_cny=10.0, fx_rate=1.0,
        value_cny=10000.0, target_weight=0.25,
        actual_weight=0.27, drift=0.02,
    )
    assert ni.value_cny == 10000.0
    assert ni.drift == 0.02
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/market/portfolio/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.infra.database.portfolio'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/src/infra/database/portfolio/__init__.py`:

```python
"""永久组合基础设施层：SQLModel 表 + 仓储。"""
```

Create `backend/src/infra/database/portfolio/models.py`:

```python
"""
永久组合 SQLModel 表
===================
5 张表：
  - portfolio_instrument:   标的池（A/HK/US）
  - portfolio_definition:   组合定义（永久/全天候/自定义）
  - portfolio_holding:      组合持仓（持仓制，记股数+成本）
  - portfolio_nav:          每日组合净值（时序）
  - portfolio_nav_item:     每日持仓明细快照（每标的的权重/偏离）

建表机制：SQLModel.metadata.create_all（main.py 启动时 import 本模块即可）。
"""
from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class PortfolioInstrument(SQLModel, table=True):
    """标的池：用户可在 UI 增删改的可投资标的。"""

    __tablename__ = "portfolio_instrument"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(unique=True, index=True)  # sh510300/02800/VOO
    market: str              # "A" | "HK" | "US"
    asset_class: str         # "equity" | "bond" | "gold" | "cash"
    ccy: str                 # "CNY" | "HKD" | "USD"
    name: str                # 显示名
    provider: str = "akshare"
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class PortfolioDefinition(SQLModel, table=True):
    """组合定义：永久组合 / 全天候 / 黄金蝴蝶 / 自定义。"""

    __tablename__ = "portfolio_definition"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    strategy_type: str       # permanent|all_weather|golden_butterfly|custom
    base_ccy: str = "CNY"
    rebalance_threshold: float = 0.05
    initial_capital: float = 100000.0
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class PortfolioHolding(SQLModel, table=True):
    """组合持仓：实际持仓股数 + 成本。"""

    __tablename__ = "portfolio_holding"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "instrument_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolio_definition.id", index=True)
    instrument_id: int = Field(foreign_key="portfolio_instrument.id")
    target_weight: float     # 单标的的目标权重（0~1）
    shares: int              # 持仓股数
    cost_price: float        # 成本价（原币种）
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class PortfolioNav(SQLModel, table=True):
    """每日组合净值（归一化）。"""

    __tablename__ = "portfolio_nav"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "trade_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(
        foreign_key="portfolio_definition.id", index=True,
    )
    trade_date: date
    nav_cny: float           # 归一化净值（初始日=1.0）
    prev_nav_cny: Optional[float] = None
    daily_return: Optional[float] = None
    total_value_cny: float
    max_drift: float         # 最大资产类偏离（绝对值）
    rebalance_suggested: bool
    created_at: datetime = Field(default_factory=datetime.now)


class PortfolioNavItem(SQLModel, table=True):
    """每日持仓明细快照：每标的的实际权重/偏离。"""

    __tablename__ = "portfolio_nav_item"

    id: Optional[int] = Field(default=None, primary_key=True)
    nav_id: int = Field(foreign_key="portfolio_nav.id", index=True)
    instrument_id: int
    symbol: str              # 冗余存储（查询友好）
    asset_class: str
    shares: int
    price: float             # 当日收盘价（原币种）
    price_cny: float         # 折算人民币
    fx_rate: float           # 当日折算汇率（CNY 标的=1.0）
    value_cny: float         # = shares * price_cny
    target_weight: float
    actual_weight: float     # = value_cny / total_value_cny
    drift: float             # = actual_weight - target_weight
    created_at: datetime = Field(default_factory=datetime.now)
```

- [ ] **Step 4: Register import in main.py**

Modify `backend/main.py` — find the agent import block (L134-136) and append a portfolio import block right after the `app_logger.info("[Agent] tables migrated and seeded")` try/except (after L151). Insert this new try/except block:

```python
    # Portfolio module: import models so SQLModel.metadata.create_all
    # picks up the 5 new portfolio_* tables on first connection.
    try:
        from src.infra.database.portfolio.models import (  # noqa: F401
            PortfolioDefinition,
            PortfolioHolding,
            PortfolioInstrument,
            PortfolioNav,
            PortfolioNavItem,
        )
        app_logger.info("[Portfolio] models imported for create_all")
    except Exception as e:
        app_logger.warning(
            f"[Portfolio] model import failed: {e}"
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/market/portfolio/test_models.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/src/infra/database/portfolio/__init__.py \
        backend/src/infra/database/portfolio/models.py \
        backend/main.py \
        backend/tests/domain/market/portfolio/test_models.py
git commit -m "feat(portfolio): add 5 SQLModel tables + register in main.py"
```

---

## Task 4: 仓储接口 + 实现 + 工厂 + fx_rate.get_rate + 集成测试

仓储封装 5 张表的 CRUD + `stock_ohlcv` 收盘价查询 + `fx_rate.get_rate`。

**Files:**
- Create: `backend/src/infra/database/portfolio/repository.py`
- Modify: `backend/src/infra/database/market/fx_rate.py`（加 `get_rate` 方法）
- Test: `backend/tests/infra/database/portfolio/__init__.py`
- Test: `backend/tests/infra/database/portfolio/test_repository.py`

**Interfaces:**
- Consumes: Task 3 的 5 张表；`DBConnection`（`session_scope`）；`fx_rate` 表；`stock_ohlcv` 裸表。
- Produces: `PortfolioRepository` 类 + `create_portfolio_repository(db_connection=None)` 工厂；`FxRateRepository.get_rate(pair, date_)`。Task 6（job）、Task 8（API）、Task 7（seed）依赖。

- [ ] **Step 1: Write the failing test**

Create `backend/tests/infra/database/portfolio/__init__.py` (empty).

Create `backend/tests/infra/database/portfolio/test_repository.py`:

```python
"""仓储集成测试：用 sqlite 内存库 + SQLModel create_all，自动回滚。"""
from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.infra.database.portfolio.models import (
    PortfolioDefinition,
    PortfolioHolding,
    PortfolioInstrument,
)
from src.infra.database.portfolio.repository import PortfolioRepository
from src.infra.database.sql_engine.engine import DBConnection


@pytest.fixture()
def repo():
    """sqlite 内存库 + 真实 DBConnection（auto_create_tables 建 5 表）。"""
    db = DBConnection(
        "sqlite:///:memory:",
        auto_create_tables=True,
    )
    yield PortfolioRepository(db)
    db.close()


def test_instrument_upsert_idempotent(repo):
    i1 = repo.upsert_instrument(
        symbol="sh510300", market="A", asset_class="equity",
        ccy="CNY", name="沪深300ETF",
    )
    assert i1.id is not None
    # 同 symbol 再 upsert → 更新而非新增
    i2 = repo.upsert_instrument(
        symbol="sh510300", market="A", asset_class="equity",
        ccy="CNY", name="沪深300ETF(更新)", enabled=False,
    )
    assert i2.id == i1.id
    assert i2.name == "沪深300ETF(更新)"
    assert i2.enabled is False
    all_inst = repo.list_instruments()
    assert len(all_inst) == 1


def test_list_instruments_filter(repo):
    repo.upsert_instrument("sh510300", "A", "equity", "CNY", "300")
    repo.upsert_instrument("02800", "HK", "equity", "HKD", "盈富")
    repo.upsert_instrument("sh511260", "A", "bond", "CNY", "国债")
    a_eq = repo.list_instruments(market="A", asset_class="equity")
    assert len(a_eq) == 1
    assert a_eq[0].symbol == "sh510300"
    hk = repo.list_instruments(market="HK")
    assert len(hk) == 1


def test_instrument_delete(repo):
    inst = repo.upsert_instrument(
        "sh510300", "A", "equity", "CNY", "300",
    )
    assert repo.delete_instrument(inst.id) is True
    assert repo.list_instruments() == []


def test_instrument_delete_blocked_when_referenced(repo):
    inst = repo.upsert_instrument(
        "sh510300", "A", "equity", "CNY", "300",
    )
    p = repo.create_portfolio(
        name="P1", strategy_type="permanent",
    )
    repo.set_holdings(p.id, [
        {"instrument_id": inst.id, "target_weight": 1.0,
         "shares": 100, "cost_price": 10.0},
    ])
    # 被引用 → 删除返回 False（API 据此返 409）
    assert repo.delete_instrument(inst.id) is False


def test_portfolio_crud(repo):
    p = repo.create_portfolio(
        name="永久", strategy_type="permanent",
        rebalance_threshold=0.05, initial_capital=100000.0,
    )
    assert p.id is not None
    fetched = repo.get_portfolio(p.id)
    assert fetched is not None
    assert fetched.name == "永久"
    all_p = repo.list_portfolios()
    assert len(all_p) == 1
    updated = repo.update_portfolio(p.id, name="永久2")
    assert updated.name == "永久2"
    assert repo.delete_portfolio(p.id) is True
    assert repo.list_portfolios() == []


def test_holdings_set_and_list(repo):
    i1 = repo.upsert_instrument("sh510300", "A", "equity", "CNY", "300")
    i2 = repo.upsert_instrument("sh511260", "A", "bond", "CNY", "国债")
    p = repo.create_portfolio(name="P", strategy_type="permanent")
    repo.set_holdings(p.id, [
        {"instrument_id": i1.id, "target_weight": 0.5,
         "shares": 100, "cost_price": 10.0},
        {"instrument_id": i2.id, "target_weight": 0.5,
         "shares": 200, "cost_price": 5.0},
    ])
    holdings = repo.list_holdings(p.id)
    assert len(holdings) == 2
    # 二次 set → 覆盖（同一组合 holdings 总数不变）
    repo.set_holdings(p.id, [
        {"instrument_id": i1.id, "target_weight": 1.0,
         "shares": 300, "cost_price": 10.0},
    ])
    assert len(repo.list_holdings(p.id)) == 1


def test_nav_save_and_query(repo):
    i1 = repo.upsert_instrument("sh510300", "A", "equity", "CNY", "300")
    p = repo.create_portfolio(name="P", strategy_type="permanent")
    repo.set_holdings(p.id, [
        {"instrument_id": i1.id, "target_weight": 1.0,
         "shares": 100, "cost_price": 10.0},
    ])
    nav_id = repo.save_nav(
        portfolio_id=p.id,
        trade_date=date(2026, 8, 7),
        nav_cny=1.0,
        prev_nav_cny=None,
        daily_return=None,
        total_value_cny=100000.0,
        max_drift=0.0,
        rebalance_suggested=False,
        items=[
            {
                "instrument_id": i1.id,
                "symbol": "sh510300",
                "asset_class": "equity",
                "shares": 100,
                "price": 10.0,
                "price_cny": 10.0,
                "fx_rate": 1.0,
                "value_cny": 1000.0,
                "target_weight": 1.0,
                "actual_weight": 1.0,
                "drift": 0.0,
            },
        ],
    )
    assert nav_id is not None
    latest = repo.get_latest_nav(p.id)
    assert latest is not None
    assert latest.nav_cny == 1.0
    items = repo.get_nav_items(nav_id)
    assert len(items) == 1
    assert items[0].symbol == "sh510300"
    hist = repo.get_nav_history(
        p.id, date(2026, 1, 1), date(2026, 12, 31),
    )
    assert len(hist) == 1


def test_apply_rebalance_updates_shares(repo):
    i1 = repo.upsert_instrument("sh510300", "A", "equity", "CNY", "300")
    p = repo.create_portfolio(name="P", strategy_type="permanent")
    repo.set_holdings(p.id, [
        {"instrument_id": i1.id, "target_weight": 1.0,
         "shares": 100, "cost_price": 10.0},
    ])
    repo.apply_share_delta(p.id, [
        {"instrument_id": i1.id, "delta": 50},
    ])
    h = repo.list_holdings(p.id)[0]
    assert h.shares == 150
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/infra/database/portfolio/test_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.infra.database.portfolio.repository'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/src/infra/database/portfolio/repository.py`:

```python
"""
永久组合仓储
============
封装 5 张表的 CRUD + stock_ohlcv 收盘价裸 SQL 查询。

约定：
  - 延迟 import models（避免循环）。
  - 删除被组合引用的标的 → 返回 False（API 据此返 409）。
  - set_holdings 是覆盖式（先删后插），用于组合编辑/apply。
  - apply_share_delta 用增量（BUY +delta / SELL -delta）改 shares。
"""
import threading
from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlmodel import select

from src.infra.database.portfolio.models import (
    PortfolioDefinition,
    PortfolioHolding,
    PortfolioInstrument,
    PortfolioNav,
    PortfolioNavItem,
)
from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class PortfolioRepository:
    """永久组合数据访问。"""

    def __init__(self, db: DBConnection):
        self._db = db

    # ── 标的池 ──────────────────────────────────────────────────
    def list_instruments(
        self,
        market: Optional[str] = None,
        asset_class: Optional[str] = None,
        enabled_only: bool = False,
    ) -> list[PortfolioInstrument]:
        with self._db.session_scope() as s:
            stmt = select(PortfolioInstrument)
            if market:
                stmt = stmt.where(PortfolioInstrument.market == market)
            if asset_class:
                stmt = stmt.where(
                    PortfolioInstrument.asset_class == asset_class
                )
            if enabled_only:
                # SQLAlchemy 需要 == 而非 is（惯例见 agent repository）
                stmt = stmt.where(
                    PortfolioInstrument.enabled == True  # noqa: E712
                )
            return list(s.exec(stmt).all())

    def get_instrument(
        self, instrument_id: int,
    ) -> Optional[PortfolioInstrument]:
        with self._db.session_scope() as s:
            return s.get(PortfolioInstrument, instrument_id)

    def upsert_instrument(
        self,
        symbol: str,
        market: str,
        asset_class: str,
        ccy: str,
        name: str,
        provider: str = "akshare",
        enabled: bool = True,
    ) -> PortfolioInstrument:
        from datetime import datetime
        with self._db.session_scope() as s:
            existing = s.exec(
                select(PortfolioInstrument).where(
                    PortfolioInstrument.symbol == symbol
                )
            ).first()
            now = datetime.now()
            if existing:
                existing.market = market
                existing.asset_class = asset_class
                existing.ccy = ccy
                existing.name = name
                existing.provider = provider
                existing.enabled = enabled
                existing.updated_at = now
                s.add(existing)
                s.flush()
                return existing
            inst = PortfolioInstrument(
                symbol=symbol, market=market, asset_class=asset_class,
                ccy=ccy, name=name, provider=provider, enabled=enabled,
                created_at=now, updated_at=now,
            )
            s.add(inst)
            s.flush()
            return inst

    def delete_instrument(self, instrument_id: int) -> bool:
        """删除标的。被组合引用时返回 False（API 返 409）。"""
        with self._db.session_scope() as s:
            referenced = s.exec(
                select(PortfolioHolding).where(
                    PortfolioHolding.instrument_id == instrument_id
                )
            ).first()
            if referenced:
                return False
            inst = s.get(PortfolioInstrument, instrument_id)
            if inst is None:
                return False
            s.delete(inst)
            return True

    # ── 组合定义 ────────────────────────────────────────────────
    def list_portfolios(
        self, active_only: bool = True,
    ) -> list[PortfolioDefinition]:
        with self._db.session_scope() as s:
            stmt = select(PortfolioDefinition)
            if active_only:
                stmt = stmt.where(
                    PortfolioDefinition.is_active == True  # noqa: E712
                )
            return list(s.exec(stmt).all())

    def get_portfolio(
        self, portfolio_id: int,
    ) -> Optional[PortfolioDefinition]:
        with self._db.session_scope() as s:
            return s.get(PortfolioDefinition, portfolio_id)

    def create_portfolio(
        self,
        name: str,
        strategy_type: str,
        base_ccy: str = "CNY",
        rebalance_threshold: float = 0.05,
        initial_capital: float = 100000.0,
        is_active: bool = True,
    ) -> PortfolioDefinition:
        from datetime import datetime
        with self._db.session_scope() as s:
            p = PortfolioDefinition(
                name=name, strategy_type=strategy_type, base_ccy=base_ccy,
                rebalance_threshold=rebalance_threshold,
                initial_capital=initial_capital, is_active=is_active,
                created_at=datetime.now(), updated_at=datetime.now(),
            )
            s.add(p)
            s.flush()
            return p

    def update_portfolio(
        self,
        portfolio_id: int,
        name: Optional[str] = None,
        rebalance_threshold: Optional[float] = None,
        initial_capital: Optional[float] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[PortfolioDefinition]:
        from datetime import datetime
        with self._db.session_scope() as s:
            p = s.get(PortfolioDefinition, portfolio_id)
            if p is None:
                return None
            if name is not None:
                p.name = name
            if rebalance_threshold is not None:
                p.rebalance_threshold = rebalance_threshold
            if initial_capital is not None:
                p.initial_capital = initial_capital
            if is_active is not None:
                p.is_active = is_active
            p.updated_at = datetime.now()
            s.add(p)
            s.flush()
            return p

    def delete_portfolio(self, portfolio_id: int) -> bool:
        with self._db.session_scope() as s:
            p = s.get(PortfolioDefinition, portfolio_id)
            if p is None:
                return False
            # 级联删 holdings / nav / nav_item（nav_item 通过 nav_id）
            navs = s.exec(
                select(PortfolioNav).where(
                    PortfolioNav.portfolio_id == portfolio_id
                )
            ).all()
            for nav in navs:
                items = s.exec(
                    select(PortfolioNavItem).where(
                        PortfolioNavItem.nav_id == nav.id
                    )
                ).all()
                for it in items:
                    s.delete(it)
                s.delete(nav)
            holdings = s.exec(
                select(PortfolioHolding).where(
                    PortfolioHolding.portfolio_id == portfolio_id
                )
            ).all()
            for h in holdings:
                s.delete(h)
            s.delete(p)
            return True

    # ── 持仓 ────────────────────────────────────────────────────
    def list_holdings(
        self, portfolio_id: int,
    ) -> list[PortfolioHolding]:
        with self._db.session_scope() as s:
            return list(
                s.exec(
                    select(PortfolioHolding).where(
                        PortfolioHolding.portfolio_id == portfolio_id
                    )
                ).all()
            )

    def set_holdings(
        self, portfolio_id: int, holdings: list[dict],
    ) -> None:
        """覆盖式设置持仓（先删后插）。"""
        from datetime import datetime
        with self._db.session_scope() as s:
            old = s.exec(
                select(PortfolioHolding).where(
                    PortfolioHolding.portfolio_id == portfolio_id
                )
            ).all()
            for h in old:
                s.delete(h)
            now = datetime.now()
            for h in holdings:
                s.add(
                    PortfolioHolding(
                        portfolio_id=portfolio_id,
                        instrument_id=h["instrument_id"],
                        target_weight=h["target_weight"],
                        shares=h["shares"],
                        cost_price=h["cost_price"],
                        created_at=now, updated_at=now,
                    )
                )

    def apply_share_delta(
        self, portfolio_id: int, deltas: list[dict],
    ) -> None:
        """应用再平衡：按 instrument_id 增减 shares。

        deltas: [{"instrument_id": int, "delta": int}]，BUY 为正，SELL 为负。
        """
        from datetime import datetime
        with self._db.session_scope() as s:
            for d in deltas:
                h = s.exec(
                    select(PortfolioHolding).where(
                        PortfolioHolding.portfolio_id == portfolio_id,
                        PortfolioHolding.instrument_id == d["instrument_id"],
                    )
                ).first()
                if h is None:
                    continue
                h.shares = max(0, h.shares + d["delta"])
                h.updated_at = datetime.now()
                s.add(h)

    # ── 净值 ────────────────────────────────────────────────────
    def get_latest_nav(
        self, portfolio_id: int,
    ) -> Optional[PortfolioNav]:
        with self._db.session_scope() as s:
            return s.exec(
                select(PortfolioNav)
                .where(PortfolioNav.portfolio_id == portfolio_id)
                .order_by(PortfolioNav.trade_date.desc())
            ).first()

    def get_nav_history(
        self,
        portfolio_id: int,
        start: date,
        end: date,
    ) -> list[PortfolioNav]:
        with self._db.session_scope() as s:
            return list(
                s.exec(
                    select(PortfolioNav)
                    .where(PortfolioNav.portfolio_id == portfolio_id)
                    .where(PortfolioNav.trade_date >= start)
                    .where(PortfolioNav.trade_date <= end)
                    .order_by(PortfolioNav.trade_date.asc())
                ).all()
            )

    def get_nav_items(
        self, nav_id: int,
    ) -> list[PortfolioNavItem]:
        with self._db.session_scope() as s:
            return list(
                s.exec(
                    select(PortfolioNavItem).where(
                        PortfolioNavItem.nav_id == nav_id
                    )
                ).all()
            )

    def save_nav(
        self,
        portfolio_id: int,
        trade_date: date,
        nav_cny: float,
        prev_nav_cny: Optional[float],
        daily_return: Optional[float],
        total_value_cny: float,
        max_drift: float,
        rebalance_suggested: bool,
        items: list[dict],
    ) -> int:
        """保存一条 nav + 其 nav_item 列表。返回 nav.id。

        如该 (portfolio_id, trade_date) 已存在 → 覆盖（含 items）。
        """
        from datetime import datetime
        with self._db.session_scope() as s:
            existing = s.exec(
                select(PortfolioNav).where(
                    PortfolioNav.portfolio_id == portfolio_id,
                    PortfolioNav.trade_date == trade_date,
                )
            ).first()
            if existing:
                # 删旧 items
                old_items = s.exec(
                    select(PortfolioNavItem).where(
                        PortfolioNavItem.nav_id == existing.id
                    )
                ).all()
                for it in old_items:
                    s.delete(it)
                nav = existing
                nav.nav_cny = nav_cny
                nav.prev_nav_cny = prev_nav_cny
                nav.daily_return = daily_return
                nav.total_value_cny = total_value_cny
                nav.max_drift = max_drift
                nav.rebalance_suggested = rebalance_suggested
            else:
                nav = PortfolioNav(
                    portfolio_id=portfolio_id, trade_date=trade_date,
                    nav_cny=nav_cny, prev_nav_cny=prev_nav_cny,
                    daily_return=daily_return,
                    total_value_cny=total_value_cny,
                    max_drift=max_drift,
                    rebalance_suggested=rebalance_suggested,
                    created_at=datetime.now(),
                )
            s.add(nav)
            s.flush()
            now = datetime.now()
            for it in items:
                s.add(
                    PortfolioNavItem(
                        nav_id=nav.id,
                        instrument_id=it["instrument_id"],
                        symbol=it["symbol"],
                        asset_class=it["asset_class"],
                        shares=it["shares"],
                        price=it["price"],
                        price_cny=it["price_cny"],
                        fx_rate=it["fx_rate"],
                        value_cny=it["value_cny"],
                        target_weight=it["target_weight"],
                        actual_weight=it["actual_weight"],
                        drift=it["drift"],
                        created_at=now,
                    )
                )
            return nav.id

    # ── stock_ohlcv 收盘价（裸 SQL，无 SQLModel）─────────────────
    def get_close_on(
        self,
        symbol: str,
        trade_date: date,
    ) -> Optional[float]:
        """查 <= trade_date 的最近一根收盘价（停牌回退到上一交易日）。"""
        with self._db.session_scope() as s:
            row = s.exec(
                text(
                    "SELECT close_ FROM stock_ohlcv "
                    "WHERE symbol = :symbol "
                    "AND trade_date <= :d "
                    "ORDER BY trade_date DESC LIMIT 1"
                ),
                params={
                    "symbol": symbol,
                    "d": f"{trade_date.isoformat()} 23:59:59",
                },
            ).first()
            return float(row[0]) if row else None


# ======== 工厂函数（遵循 intel/blog 单例 + 工厂约定） ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_portfolio_repository(
    db_connection: DBConnection | None = None,
) -> PortfolioRepository:
    """创建永久组合仓储实例。"""
    return PortfolioRepository(db_connection or _get_db_connection())
```

- [ ] **Step 4: Add fx_rate.get_rate method**

Modify `backend/src/infra/database/market/fx_rate.py` — add this method to `FxRateRepository` (after `get_latest_date`, before the factory section):

```python
    def get_rate(
        self, pair: str, date_: dt.date,
    ) -> Optional[float]:
        """查 <= date_ 的最新汇率（缺失日回退到上一有数据日）。

        用于跨市场标的折算 CNY：HKD/USD 标的取当日 HKDCNY/USDCNY。
        无数据返回 None。
        """
        with self._db.session_scope() as s:
            row = s.exec(
                select(FxRate)
                .where(FxRate.pair == pair)
                .where(FxRate.date <= date_)
                .order_by(FxRate.date.desc())
            ).first()
            return row.rate if row else None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/infra/database/portfolio/test_repository.py -v`
Expected: PASS (9 passed).

- [ ] **Step 6: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/src/infra/database/portfolio/repository.py \
        backend/src/infra/database/market/fx_rate.py \
        backend/tests/infra/database/portfolio/__init__.py \
        backend/tests/infra/database/portfolio/test_repository.py
git commit -m "feat(portfolio): add repository + fx_rate.get_rate + integration tests"
```

---

## Task 5: 改造 akshare_provider（港股分流 + HKDCNY 放开）+ 单测

修两个 bug：港股代码被误判进 A 股 ETF；HKDCNY 被硬限拒绝。

**Files:**
- Modify: `backend/src/domain/market/sync/providers/akshare_provider.py` L94-103（`fetch_daily` 加港股分流）
- Modify: `backend/src/domain/market/sync/providers/akshare_provider.py` L208-247（`fetch_fx_daily` 放开多 pair）
- Test: `backend/tests/domain/market/sync/providers/test_akshare_portfolio.py`

**Interfaces:**
- Consumes: `akshare_provider` 现有 `_is_us_ticker` / `_strip_hk_prefix` / `fetch_hk_stock_daily` / `_FX_BOC_SYMBOL`。
- Produces: `fetch_daily("02800")` 正确走港股；`fetch_fx_daily("HKDCNY")` 返回数据。Task 6（job 同步）依赖。

- [ ] **Step 1: Write the failing test**

Create `backend/tests/domain/market/sync/providers/test_akshare_portfolio.py`:

```python
"""akshare_provider 港股分流 + HKDCNY 放开单测（mock akshare）。"""
from unittest.mock import patch, MagicMock

import pandas as pd

from src.domain.market.sync.providers.akshare_provider import (
    AkshareProvider,
)


def test_fetch_daily_routes_5_digit_to_hk():
    """5 位纯数字标的 → fetch_hk_stock_daily，不走 _fetch_a_etf。"""
    provider = AkshareProvider()
    with patch.object(
        provider, "fetch_hk_stock_daily", return_value=[]
    ) as hk_mock, patch.object(
        provider, "_fetch_a_etf", return_value=[]
    ) as a_mock:
        provider.fetch_daily("02800")
    assert hk_mock.called, "港股代码应走 fetch_hk_stock_daily"
    assert not a_mock.called, "港股代码不应走 _fetch_a_etf"


def test_fetch_daily_keeps_us_and_a_routing():
    """美股字母 / A 股 sh 前缀的路由不变。"""
    provider = AkshareProvider()
    with patch.object(
        provider, "_fetch_us", return_value=[]
    ) as us_mock, patch.object(
        provider, "_fetch_a_etf", return_value=[]
    ) as a_mock, patch.object(
        provider, "fetch_hk_stock_daily", return_value=[]
    ) as hk_mock:
        provider.fetch_daily("VOO")
        provider.fetch_daily("sh510300")
    assert us_mock.called
    assert a_mock.called
    assert not hk_mock.called


def test_fetch_fx_daily_supports_hkdcny():
    """HKDCNY 走 currency_boc_sina symbol='港币'，返回 (date, rate)。"""
    provider = AkshareProvider()
    fake_df = pd.DataFrame(
        [
            {"日期": "2026-08-06", "中行折算价": 86.56},
            {"日期": "2026-08-07", "中行折算价": 86.60},
        ]
    )
    with patch(
        "src.domain.market.sync.providers.akshare_provider.ak."
        "currency_boc_sina",
        return_value=fake_df,
    ) as fx_mock:
        rows = provider.fetch_fx_daily(
            "HKDCNY", start_date="2026-08-01", end_date="2026-08-07",
        )
    fx_mock.assert_called_once()
    # 验证传了 symbol=港币 + 日期参数
    kwargs = fx_mock.call_args.kwargs
    assert kwargs["symbol"] == "港币"
    assert kwargs["start_date"] == "20260801"
    assert kwargs["end_date"] == "20260807"
    assert len(rows) == 2
    # rate = 中行折算价/100
    assert abs(rows[0][1] - 0.8656) < 1e-6


def test_fetch_fx_daily_unsupported_pair_returns_empty():
    """不在 _FX_BOC_SYMBOL 的 pair → 返回空。"""
    provider = AkshareProvider()
    rows = provider.fetch_fx_daily("EURUSD")
    assert rows == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_portfolio.py -v`
Expected: FAIL — `test_fetch_daily_routes_5_digit_to_hk` 失败（港股走 `_fetch_a_etf`）；`test_fetch_fx_daily_supports_hkdcny` 失败（返回 `[]`）。

- [ ] **Step 3: Add HK routing to fetch_daily**

Modify `backend/src/domain/market/sync/providers/akshare_provider.py` L94-103. Replace the existing `fetch_daily` method body:

```python
    def fetch_daily(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: int = 1300,
    ) -> list[OHLCVBar]:
        if self._is_us_ticker(symbol):
            return self._fetch_us(symbol, start_date, end_date)  # Task 5
        if self._is_hk_ticker(symbol):
            return self.fetch_hk_stock_daily(symbol, start_date, end_date)
        return self._fetch_a_etf(symbol, start_date, end_date)
```

Then add the `_is_hk_ticker` helper. Find the `_is_valid_symbol` / `_is_us_ticker` block (around L84-91) and append after `_is_us_ticker`:

```python
    @staticmethod
    def _is_hk_ticker(symbol: str) -> bool:
        """港股代码：纯 5 位数字（02800 / 00700）。"""
        return bool(symbol) and symbol.isdigit() and len(symbol) == 5
```

- [ ] **Step 4: Open fetch_fx_daily to multi-pair**

Modify `backend/src/domain/market/sync/providers/akshare_provider.py` `fetch_fx_daily` (L208-247). Replace the method body:

```python
    def fetch_fx_daily(
        self,
        pair: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[tuple]:
        """拉汇率日线（CNY 对，中行折算价/100）。

        支持 USDCNY / HKDCNY / EURCNY 等 _FX_BOC_SYMBOL 内所有 pair。
        返回 [(date, rate), ...]。currency_boc_sina 必须传日期参数，
        否则部分 akshare 版本返回陈旧默认窗口。
        """
        boc_sym = self._FX_BOC_SYMBOL.get(pair)
        if not boc_sym:
            return []
        kwargs = {"symbol": boc_sym}
        if start_date:
            sd = (
                start_date.replace("-", "")
                if isinstance(start_date, str)
                else start_date
            )
            kwargs["start_date"] = sd
        if end_date:
            ed = (
                end_date.replace("-", "")
                if isinstance(end_date, str)
                else end_date
            )
            kwargs["end_date"] = ed
        try:
            df = ak.currency_boc_sina(**kwargs)
        except Exception:
            return []
        if df is None or df.empty:
            return []
        out = []
        for _, r in df.iterrows():
            try:
                d = r["日期"]
                if not isinstance(d, date):
                    d = datetime.strptime(
                        str(d)[:10], "%Y-%m-%d"
                    ).date()
                rate = float(r["中行折算价"]) / 100.0
                out.append((d, rate))
            except (KeyError, ValueError, TypeError):
                continue
        return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_portfolio.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/src/domain/market/sync/providers/akshare_provider.py \
        backend/tests/domain/market/sync/providers/test_akshare_portfolio.py
git commit -m "feat(sync): route HK tickers + open HKDCNY in akshare provider"
```

---

## Task 6: 改造 portfolio_daily.py（DB 读标的）+ 新增 portfolio_nav_daily.py

把数据源从 config 改成 DB；新增每日净值 job。

**Files:**
- Modify: `backend/src/domain/market/sync/jobs/portfolio_daily.py` L45-69
- Create: `backend/src/domain/market/sync/jobs/portfolio_nav_daily.py`

**Interfaces:**
- Consumes: Task 4 `PortfolioRepository.list_instruments` / `list_portfolios` / `list_holdings`；Task 5 港股分流 + HKDCNY；Task 1 `calc_portfolio_nav`；Task 4 `get_close_on` / `FxRateRepository.get_rate`。
- Produces: `portfolio_daily.run()`（行情 + 汇率同步）；`portfolio_nav_daily.run()`（净值物化）。Task 8 API 查的就是 nav job 物化的数据。

- [ ] **Step 1: Refactor portfolio_daily.py to read DB**

Modify `backend/src/domain/market/sync/jobs/portfolio_daily.py`. Replace the full file content:

```python
"""
Portfolio Daily Sync
===================
标的池每日行情 + 汇率同步（供 cron 调用）。

  - 标的源：portfolio_instrument WHERE enabled=true（不再读 config）
  - 行情 → stock_ohlcv（首拉 full / 增量 incremental）
  - 汇率 → fx_rate（从活跃组合涉及币种派生 pair 列表）

crontab 示例（工作日 16:30 收盘后）:
  30 16 * * 1-5 cd /path/backend && .venv/bin/python -m src.domain.market.sync.jobs.portfolio_daily >> logs/portfolio_sync.log 2>&1
"""
import logging
import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync import ProgressTracker, SyncService
from src.domain.market.sync.providers.akshare_provider import AkshareProvider
from src.domain.market.sync.sync_service import SyncConfig, SyncResult
from src.infra.database.market.fx_rate import create_fx_rate_repository
from src.infra.database.portfolio.repository import (
    create_portfolio_repository,
)

PROVIDER_NAME = "akshare"

log = logging.getLogger("portfolio_sync")


def _build_provider() -> AkshareProvider:
    return AkshareProvider()


def _build_tracker() -> ProgressTracker:
    return ProgressTracker()


def _build_service(
    provider: AkshareProvider, tracker: ProgressTracker
) -> SyncService:
    from src.domain.market.sync.jobs.daily import _get_dsn
    return SyncService(provider, tracker, SyncConfig(db_dsn=_get_dsn()))


def _load_universe_bars() -> list:
    """从 DB 读 enabled 标的（迁移自 config.portfolio_universe）。"""
    repo = create_portfolio_repository()
    return repo.list_instruments(enabled_only=True)


def _derive_fx_pairs() -> list[str]:
    """从活跃组合涉及币种派生需同步的 FX pair。

    策略：扫所有活跃组合的 holdings → instrument.ccy → {ccy}CNY。
    兜底含 USDCNY（即使无美股组合也保底同步）。
    """
    repo = create_portfolio_repository()
    ccys: set[str] = {"USD"}  # 保底
    for p in repo.list_portfolios(active_only=True):
        for h in repo.list_holdings(p.id):
            inst = repo.get_instrument(h.instrument_id)
            if inst and inst.ccy != "CNY":
                ccys.add(inst.ccy)
    return sorted(f"{c}CNY" for c in ccys)


def run() -> None:
    provider = _build_provider()
    tracker = _build_tracker()
    service = _build_service(provider, tracker)

    for inst in _load_universe_bars():
        last = tracker.get_last_sync(PROVIDER_NAME, inst.symbol, "1d")
        mode = "incremental" if last is not None else "full"
        result = service.backfill(
            symbols=[inst.symbol], interval="1d", mode=mode
        )
        log.info(
            f"[{inst.symbol}] {mode}: "
            f"done={result.done_symbols} "
            f"failed={result.failed_symbols} "
            f"rows={result.total_rows}"
        )

    for pair in _derive_fx_pairs():
        sync_fx(pair)
    log.info("portfolio sync complete")


def sync_fx(pair: str = "USDCNY") -> None:
    provider = _build_provider()
    repo = create_fx_rate_repository()
    latest = repo.get_latest_date(pair)
    rows = provider.fetch_fx_daily(pair)
    for d, rate in rows:
        if latest and d <= latest:
            continue
        repo.upsert(d, pair, rate)


if __name__ == "__main__":
    run()
```

Note: 布尔过滤用 `== True`（带 `# noqa: E712`），与项目惯例（agent repository L535）一致——SQLAlchemy 需 `==` 才能正确翻译为 SQL，`is True` 会被 Python 直接求值为 False 不生效。

- [ ] **Step 2: Create portfolio_nav_daily.py**

Create `backend/src/domain/market/sync/jobs/portfolio_nav_daily.py`:

```python
"""
Portfolio NAV Daily
===================
每日组合净值物化 job（17:00 cron，行情同步后）。

  - 遍历活跃组合 → 读 holdings
  - 查当日收盘价 + 汇率 → calc_portfolio_nav
  - 写 portfolio_nav + portfolio_nav_item

错误处理：
  - 某标的当日无收盘价（停牌/休市）→ 用最近交易日收盘价（get_close_on 已回退）
  - 某币种汇率缺失 → 跳过该组合当日，记 error，下次补
  - 组合无持仓 → nav_cny=0，记 warning 跳过

crontab（工作日 17:00）:
  0 17 * * 1-5 cd /path/backend && .venv/bin/python -m src.domain.market.sync.jobs.portfolio_nav_daily >> logs/portfolio_nav.log 2>&1
"""
import logging
import sys
from datetime import date
from pathlib import Path

_BACKEND = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.portfolio.nav_calculator import (
    NavItemInput,
    calc_portfolio_nav,
)
from src.infra.database.market.fx_rate import create_fx_rate_repository
from src.infra.database.portfolio.repository import (
    create_portfolio_repository,
)

log = logging.getLogger("portfolio_nav")


def _trade_date() -> date:
    """T 当日（17:00 后跑即当日收盘）。"""
    return date.today()


def _build_items_in(
    portfolio_id: int, trade_date: date,
) -> tuple[list[NavItemInput], float] | None:
    """构造 calc_portfolio_nav 的输入。

    Returns:
        (items_in, None) 或 (None, error_msg)（汇率缺失时）。
    """
    repo = create_portfolio_repository()
    fx_repo = create_fx_rate_repository()
    holdings = repo.list_holdings(portfolio_id)
    if not holdings:
        return [], "no holdings"

    items_in: list[NavItemInput] = []
    for h in holdings:
        inst = repo.get_instrument(h.instrument_id)
        if inst is None:
            log.warning(
                "[nav] portfolio=%s holding=%s instrument missing, skip",
                portfolio_id, h.instrument_id,
            )
            continue
        price = repo.get_close_on(inst.symbol, trade_date)
        if price is None:
            log.warning(
                "[nav] %s no close on %s, skip instrument",
                inst.symbol, trade_date,
            )
            continue
        if inst.ccy == "CNY":
            fx = 1.0
        else:
            pair = f"{inst.ccy}CNY"
            fx = fx_repo.get_rate(pair, trade_date)
            if fx is None:
                return None, f"{pair} fx rate missing on {trade_date}"
        items_in.append(
            NavItemInput(
                instrument_id=inst.id,
                symbol=inst.symbol,
                asset_class=inst.asset_class,
                target_weight=h.target_weight,
                shares=h.shares,
                price=price,
                fx_rate=fx,
            )
        )
    return items_in, None


def _calc_and_save(
    portfolio, trade_date: date,
) -> None:
    repo = create_portfolio_repository()
    built = _build_items_in(portfolio.id, trade_date)
    if built is None:
        log.error("[nav] portfolio=%s build failed", portfolio.id)
        return
    items_in, err = built
    if err == "no holdings":
        log.warning("[nav] portfolio=%s no holdings, skip", portfolio.id)
        return
    if not items_in:
        log.warning(
            "[nav] portfolio=%s all instruments missing price, skip",
            portfolio.id,
        )
        return

    result = calc_portfolio_nav(
        portfolio.initial_capital,
        portfolio.rebalance_threshold,
        items_in,
    )

    # prev nav（前一交易日）
    prev = repo.get_latest_nav(portfolio.id)
    prev_nav = prev.nav_cny if prev else None
    daily_ret = (
        (result.nav_cny / prev_nav - 1.0)
        if prev_nav and prev_nav > 0
        else None
    )

    item_dicts = [
        {
            "instrument_id": v.instrument_id,
            "symbol": v.symbol,
            "asset_class": v.asset_class,
            "shares": v.shares,
            "price": v.price,
            "price_cny": v.price * v.fx_rate,
            "fx_rate": v.fx_rate,
            "value_cny": v.value_cny,
            "target_weight": v.target_weight,
            "actual_weight": v.actual_weight,
            "drift": v.drift,
        }
        for v in result.items
    ]
    repo.save_nav(
        portfolio_id=portfolio.id,
        trade_date=trade_date,
        nav_cny=result.nav_cny,
        prev_nav_cny=prev_nav,
        daily_return=daily_ret,
        total_value_cny=result.total_value_cny,
        max_drift=result.max_drift,
        rebalance_suggested=result.rebalance_suggested,
        items=item_dicts,
    )
    log.info(
        "[nav] portfolio=%s date=%s nav=%.4f drift=%.4f rebalance=%s",
        portfolio.id, trade_date, result.nav_cny,
        result.max_drift, result.rebalance_suggested,
    )


def run() -> None:
    repo = create_portfolio_repository()
    trade_date = _trade_date()
    portfolios = repo.list_portfolios(active_only=True)
    log.info(
        "[nav] start: %d active portfolios, trade_date=%s",
        len(portfolios), trade_date,
    )
    for p in portfolios:
        try:
            _calc_and_save(p, trade_date)
        except Exception as e:
            log.error(
                "[nav] portfolio=%s failed: %s", p.id, e, exc_info=True,
            )
    log.info("[nav] complete")


if __name__ == "__main__":
    run()
```

- [ ] **Step 3: Verify jobs import cleanly (smoke test)**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "from src.domain.market.sync.jobs import portfolio_daily, portfolio_nav_daily; print('imports OK')"`
Expected: prints `imports OK` (no exception).

- [ ] **Step 4: Run full test suite to ensure no regressions**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/market/portfolio tests/infra/database/portfolio tests/domain/market/sync/providers/test_akshare_portfolio.py -v`
Expected: all PASS (no regressions from refactor).

- [ ] **Step 5: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/src/domain/market/sync/jobs/portfolio_daily.py \
        backend/src/domain/market/sync/jobs/portfolio_nav_daily.py
git commit -m "feat(portfolio): daily sync reads DB + add portfolio_nav_daily job"
```

---

## Task 7: seed 脚本（标的池 + 预置组合）

一次性幂等脚本，部署时手动跑。

**Files:**
- Create: `backend/scripts/seed_portfolio_instruments.py`
- Create: `backend/scripts/seed_preset_portfolios.py`

**Interfaces:**
- Consumes: Task 4 `create_portfolio_repository` / `upsert_instrument` / `create_portfolio` / `set_holdings`。
- Produces: 标的池 16 条记录（A 4 + HK 4 + US 4 + 保底）+ 3 个预置组合（永久/全天候/黄金蝴蝶）各含 holdings。Task 11 端到端验证依赖 seed 数据。

- [ ] **Step 1: Create seed_portfolio_instruments.py**

Create `backend/scripts/seed_portfolio_instruments.py`:

```python
"""
标的池 seed（幂等）
==================
首次部署手动跑：把 A/HK/US 三市场各资产类标的 upsert 进
portfolio_instrument 表。

跑法：
  cd backend && .venv/bin/python -m scripts.seed_portfolio_instruments
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from src.infra.database.portfolio.repository import (
    create_portfolio_repository,
)

# (symbol, market, asset_class, ccy, name)
INSTRUMENTS = [
    # A 股
    ("sh510300", "A", "equity", "CNY", "沪深300ETF"),
    ("sh511260", "A", "bond", "CNY", "国泰10年国债ETF"),
    ("sh518880", "A", "gold", "CNY", "华安黄金ETF"),
    ("sh511990", "A", "cash", "CNY", "华宝添益货币"),
    # H 股（5 位纯数字）
    ("02800", "HK", "equity", "HKD", "盈富基金"),
    ("02819", "HK", "bond", "HKD", "恒生国债ETF"),
    ("02840", "HK", "gold", "HKD", "SPDR金ETF"),
    ("02815", "HK", "cash", "HKD", "港元货币基金"),
    # 美股
    ("VOO", "US", "equity", "USD", "标普500ETF"),
    ("TLT", "US", "bond", "USD", "20+年国债ETF"),
    ("GLD", "US", "gold", "USD", "黄金ETF"),
    ("SHV", "US", "cash", "USD", "短债ETF"),
]


def run() -> None:
    repo = create_portfolio_repository()
    for sym, mkt, cls, ccy, name in INSTRUMENTS:
        repo.upsert_instrument(
            symbol=sym, market=mkt, asset_class=cls,
            ccy=ccy, name=name, enabled=True,
        )
        print(f"[seed] upsert instrument {sym} ({name})")
    print(f"[seed] done: {len(INSTRUMENTS)} instruments")


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Create seed_preset_portfolios.py**

Create `backend/scripts/seed_preset_portfolios.py`:

```python
"""
预置组合 seed（幂等）
====================
首次部署手动跑：建 3 个标准组合 + 各自 holdings。

跑法：
  cd backend && .venv/bin/python -m scripts.seed_preset_portfolios

权重口径：
  - 永久组合:    equity/bond/gold/cash 各 25%（单市场各 1 标的）
  - 全天候(简化): equity 30% / bond 55% / gold 15% / cash 0%
  - 黄金蝴蝶:    equity 40% / bond 20% / gold 20% / cash 20%

shares 初始分配：用建仓日收盘价算
  shares = initial_capital * target_weight / price
本 seed 用占位价 1.0（首次 nav job 跑前用户应手动校准 shares
或在 UI 调整；nav job 不依赖 cost_price，只看 shares × 当日价）。
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from src.infra.database.portfolio.repository import (
    create_portfolio_repository,
)

# 组合定义：(name, strategy_type, [(symbol, weight), ...])
PORTFOLIOS = [
    (
        "永久投资组合",
        "permanent",
        [
            ("sh510300", 0.25),
            ("sh511260", 0.25),
            ("sh518880", 0.25),
            ("sh511990", 0.25),
        ],
    ),
    (
        "全天候(简化)",
        "all_weather",
        [
            ("sh510300", 0.30),
            ("sh511260", 0.55),
            ("sh518880", 0.15),
        ],
    ),
    (
        "黄金蝴蝶",
        "golden_butterfly",
        [
            ("sh510300", 0.40),
            ("sh511260", 0.20),
            ("sh518880", 0.20),
            ("sh511990", 0.20),
        ],
    ),
]

INITIAL_CAPITAL = 100000.0
PLACEHOLDER_PRICE = 1.0  # 首次 nav job 前 UI 校准


def run() -> None:
    repo = create_portfolio_repository()

    # 建 symbol → instrument_id 映射
    all_inst = repo.list_instruments()
    sym_to_id = {i.symbol: i.id for i in all_inst}
    if not sym_to_id:
        print(
            "[seed] WARN: portfolio_instrument 表为空，"
            "请先跑 scripts.seed_portfolio_instruments"
        )
        return

    # 已存在的同名组合跳过（幂等）
    existing = {p.name for p in repo.list_portfolios(active_only=False)}

    for name, stype, holdings_spec in PORTFOLIOS:
        if name in existing:
            print(f"[seed] portfolio '{name}' exists, skip")
            continue
        p = repo.create_portfolio(
            name=name,
            strategy_type=stype,
            rebalance_threshold=0.05,
            initial_capital=INITIAL_CAPITAL,
        )
        holdings = []
        for sym, w in holdings_spec:
            inst_id = sym_to_id.get(sym)
            if inst_id is None:
                print(
                    f"[seed] WARN: instrument {sym} not in pool, skip"
                )
                continue
            shares = int(
                INITIAL_CAPITAL * w / PLACEHOLDER_PRICE
            )
            holdings.append(
                {
                    "instrument_id": inst_id,
                    "target_weight": w,
                    "shares": shares,
                    "cost_price": PLACEHOLDER_PRICE,
                }
            )
        repo.set_holdings(p.id, holdings)
        print(
            f"[seed] create portfolio '{name}' (id={p.id}, "
            f"{len(holdings)} holdings)"
        )
    print("[seed] done")


if __name__ == "__main__":
    run()
```

- [ ] **Step 3: Verify scripts parse (smoke test)**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "import ast; ast.parse(open('scripts/seed_portfolio_instruments.py').read()); ast.parse(open('scripts/seed_preset_portfolios.py').read()); print('syntax OK')"`
Expected: prints `syntax OK`.

- [ ] **Step 4: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/scripts/seed_portfolio_instruments.py \
        backend/scripts/seed_preset_portfolios.py
git commit -m "feat(portfolio): add seed scripts for instruments + preset portfolios"
```

---

## Task 8: API router + handler（13 端点）+ main.py 注册

HTTP 层。handler 调 repository，返回 `responses.success/fail`。

**Files:**
- Create: `backend/src/api/handler/perm_portfolio_handler.py`
- Create: `backend/src/api/router/perm_portfolio_router.py`
- Modify: `backend/main.py`（顶部 import + `app.include_router`）

**Interfaces:**
- Consumes: Task 4 仓储全部方法；Task 1 `calc_portfolio_nav`；Task 2 `suggest_rebalance`；Task 4 `FxRateRepository.get_rate` / `get_close_on`。
- Produces: 13 个 HTTP 端点（见 spec §4.8）。Task 10 前端依赖这些端点的返回结构。

- [ ] **Step 1: Write handler**

Create `backend/src/api/handler/perm_portfolio_handler.py`:

```python
"""永久组合 API handler。

遵循 router → handler → repository 分层，统一用 src.pkg.responses 返回。
handler 内 repository 延迟 import + 工厂创建。
"""
from datetime import date, datetime
from typing import Any, Optional

from src.pkg import responses


# ── 标的池 ────────────────────────────────────────────────────
def list_instruments(
    market: Optional[str] = None,
    asset_class: Optional[str] = None,
) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    insts = repo.list_instruments(market=market, asset_class=asset_class)
    return responses.success(
        [_inst_to_dict(i) for i in insts]
    )


def create_instrument(body: dict) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    required = ("symbol", "market", "asset_class", "ccy", "name")
    if not all(body.get(k) for k in required):
        return responses.fail(msg=f"缺少必填字段: {required}")
    repo = create_portfolio_repository()
    inst = repo.upsert_instrument(
        symbol=body["symbol"],
        market=body["market"],
        asset_class=body["asset_class"],
        ccy=body["ccy"],
        name=body["name"],
        enabled=body.get("enabled", True),
    )
    return responses.success(_inst_to_dict(inst))


def update_instrument(instrument_id: int, body: dict) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    inst = repo.get_instrument(instrument_id)
    if inst is None:
        return responses.fail(msg="标的不存在")
    repo.upsert_instrument(
        symbol=inst.symbol,
        market=body.get("market", inst.market),
        asset_class=body.get("asset_class", inst.asset_class),
        ccy=body.get("ccy", inst.ccy),
        name=body.get("name", inst.name),
        enabled=body.get("enabled", inst.enabled),
    )
    return responses.success(_inst_to_dict(repo.get_instrument(instrument_id)))


def delete_instrument(instrument_id: int) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    ok = repo.delete_instrument(instrument_id)
    if not ok:
        return responses.fail(
            msg="标的被组合引用，无法删除（先从组合移除）",
            code=__err_conflict(),
        )
    return responses.success({"deleted": True})


# ── 组合定义 ──────────────────────────────────────────────────
def list_portfolios() -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    out = []
    for p in repo.list_portfolios(active_only=True):
        nav = repo.get_latest_nav(p.id)
        out.append(
            {
                **_portfolio_to_dict(p),
                "latest_nav": (
                    _nav_to_dict(nav) if nav else None
                ),
            }
        )
    return responses.success(out)


def create_portfolio(body: dict) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    if not body.get("name") or not body.get("strategy_type"):
        return responses.fail(msg="name/strategy_type 必填")
    repo = create_portfolio_repository()
    p = repo.create_portfolio(
        name=body["name"],
        strategy_type=body["strategy_type"],
        rebalance_threshold=body.get("rebalance_threshold", 0.05),
        initial_capital=body.get("initial_capital", 100000.0),
    )
    holdings = body.get("holdings", [])
    if holdings:
        repo.set_holdings(p.id, holdings)
    return responses.success(
        {
            **_portfolio_to_dict(p),
            "holdings": [
                _holding_to_dict(h) for h in repo.list_holdings(p.id)
            ],
        }
    )


def get_portfolio(portfolio_id: int) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    p = repo.get_portfolio(portfolio_id)
    if p is None:
        return responses.fail(msg="组合不存在")
    holdings = repo.list_holdings(portfolio_id)
    nav = repo.get_latest_nav(portfolio_id)
    nav_items = repo.get_nav_items(nav.id) if nav else []
    return responses.success(
        {
            **_portfolio_to_dict(p),
            "holdings": [_holding_to_dict(h) for h in holdings],
            "latest_nav": _nav_to_dict(nav) if nav else None,
            "latest_nav_items": [
                _nav_item_to_dict(i) for i in nav_items
            ],
        }
    )


def update_portfolio(portfolio_id: int, body: dict) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    p = repo.update_portfolio(
        portfolio_id,
        name=body.get("name"),
        rebalance_threshold=body.get("rebalance_threshold"),
        initial_capital=body.get("initial_capital"),
        is_active=body.get("is_active"),
    )
    if p is None:
        return responses.fail(msg="组合不存在")
    if "holdings" in body:
        repo.set_holdings(portfolio_id, body["holdings"])
    return responses.success(
        {
            **_portfolio_to_dict(p),
            "holdings": [
                _holding_to_dict(h)
                for h in repo.list_holdings(portfolio_id)
            ],
        }
    )


def delete_portfolio(portfolio_id: int) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    ok = repo.delete_portfolio(portfolio_id)
    if not ok:
        return responses.fail(msg="组合不存在")
    return responses.success({"deleted": True})


# ── 净值 ──────────────────────────────────────────────────────
def get_nav_history(
    portfolio_id: int,
    start: str,
    end: str,
) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    sd = _parse_date(start) or _default_start()
    ed = _parse_date(end) or date.today()
    navs = repo.get_nav_history(portfolio_id, sd, ed)
    out = []
    for n in navs:
        out.append(
            {
                **_nav_to_dict(n),
                "items": [
                    _nav_item_to_dict(i)
                    for i in repo.get_nav_items(n.id)
                ],
            }
        )
    return responses.success(out)


# ── 再平衡 ────────────────────────────────────────────────────
def get_rebalance(portfolio_id: int) -> Any:
    """实时算当前再平衡建议（基于最新 nav 物化的明细）。"""
    from src.domain.market.portfolio.rebalance_advisor import (
        RebalanceHolding,
        RebalanceNavItem,
        suggest_rebalance,
    )
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    p = repo.get_portfolio(portfolio_id)
    if p is None:
        return responses.fail(msg="组合不存在")
    nav = repo.get_latest_nav(portfolio_id)
    if nav is None:
        return responses.success(
            {"actions": [], "reason": "尚无净值数据"}
        )
    nav_items = repo.get_nav_items(nav.id)
    holdings = repo.list_holdings(portfolio_id)
    # 对齐 holdings 与 nav_items
    inst_ids = {h.instrument_id for h in holdings}
    holding_d = {
        h.instrument_id: RebalanceHolding(
            instrument_id=h.instrument_id,
            symbol=_lookup_symbol(nav_items, h.instrument_id),
            asset_class=_lookup_class(nav_items, h.instrument_id),
            target_weight=h.target_weight,
            shares=h.shares,
        )
        for h in holdings
    }
    nav_d = []
    for it in nav_items:
        if it.instrument_id not in inst_ids:
            continue
        nav_d.append(
            RebalanceNavItem(
                instrument_id=it.instrument_id,
                symbol=it.symbol,
                asset_class=it.asset_class,
                shares=it.shares,
                price_cny=it.price_cny,
                value_cny=it.value_cny,
            )
        )
    actions = suggest_rebalance(
        list(holding_d.values()),
        nav_d,
        total_value_cny=nav.total_value_cny,
        threshold=p.rebalance_threshold,
    )
    return responses.success(
        {
            "trade_date": nav.trade_date.isoformat(),
            "max_drift": nav.max_drift,
            "threshold": p.rebalance_threshold,
            "rebalance_suggested": nav.rebalance_suggested,
            "actions": [_action_to_dict(a) for a in actions],
        }
    )


def apply_rebalance(portfolio_id: int, body: dict) -> Any:
    """应用再平衡建议：按 actions 增减 holdings.shares。

    body: {"actions": [{"instrument_id": int, "action": "BUY|SELL",
                        "shares_delta": int}]}
    """
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    actions = body.get("actions", [])
    if not actions:
        return responses.fail(msg="actions 为空")
    repo = create_portfolio_repository()
    deltas = []
    for a in actions:
        delta = int(a["shares_delta"])
        if a["action"] == "SELL":
            delta = -delta
        deltas.append({"instrument_id": a["instrument_id"], "delta": delta})
    repo.apply_share_delta(portfolio_id, deltas)
    return responses.success({"applied": len(deltas)})


# ── 回测（端点薄封装，实现在 Task 9）──────────────────────────
def backtest_portfolio(portfolio_id: int, body: dict) -> Any:
    from src.api.handler.perm_portfolio_handler import _run_backtest
    try:
        result = _run_backtest(portfolio_id, body)
    except ValueError as e:
        return responses.fail(msg=str(e))
    return responses.success(result)


# ── 内部：序列化 ──────────────────────────────────────────────
def _inst_to_dict(i) -> dict:
    return {
        "id": i.id,
        "symbol": i.symbol,
        "market": i.market,
        "asset_class": i.asset_class,
        "ccy": i.ccy,
        "name": i.name,
        "provider": i.provider,
        "enabled": i.enabled,
    }


def _portfolio_to_dict(p) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "strategy_type": p.strategy_type,
        "base_ccy": p.base_ccy,
        "rebalance_threshold": p.rebalance_threshold,
        "initial_capital": p.initial_capital,
        "is_active": p.is_active,
    }


def _holding_to_dict(h) -> dict:
    return {
        "id": h.id,
        "portfolio_id": h.portfolio_id,
        "instrument_id": h.instrument_id,
        "target_weight": h.target_weight,
        "shares": h.shares,
        "cost_price": h.cost_price,
    }


def _nav_to_dict(n) -> dict:
    return {
        "id": n.id,
        "portfolio_id": n.portfolio_id,
        "trade_date": n.trade_date.isoformat(),
        "nav_cny": n.nav_cny,
        "prev_nav_cny": n.prev_nav_cny,
        "daily_return": n.daily_return,
        "total_value_cny": n.total_value_cny,
        "max_drift": n.max_drift,
        "rebalance_suggested": n.rebalance_suggested,
    }


def _nav_item_to_dict(i) -> dict:
    return {
        "id": i.id,
        "instrument_id": i.instrument_id,
        "symbol": i.symbol,
        "asset_class": i.asset_class,
        "shares": i.shares,
        "price": i.price,
        "price_cny": i.price_cny,
        "fx_rate": i.fx_rate,
        "value_cny": i.value_cny,
        "target_weight": i.target_weight,
        "actual_weight": i.actual_weight,
        "drift": i.drift,
    }


def _action_to_dict(a) -> dict:
    return {
        "instrument_id": a.instrument_id,
        "symbol": a.symbol,
        "asset_class": a.asset_class,
        "action": a.action,
        "shares_delta": a.shares_delta,
        "reason": a.reason,
    }


def _lookup_symbol(nav_items, instrument_id: int) -> str:
    for it in nav_items:
        if it.instrument_id == instrument_id:
            return it.symbol
    return ""


def _lookup_class(nav_items, instrument_id: int) -> str:
    for it in nav_items:
        if it.instrument_id == instrument_id:
            return it.asset_class
    return ""


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _default_start() -> date:
    """默认近 1 年。"""
    from datetime import timedelta
    return date.today() - timedelta(days=365)


def __err_conflict():
    """409 Conflict 错误码（用 INVALID_PARAM 兜底，前端按 msg 判断）。"""
    from src.typings.errno.error_no import ErrorNo
    return ErrorNo.INVALID_PARAM
```

- [ ] **Step 2: Write router**

Create `backend/src/api/router/perm_portfolio_router.py`:

```python
"""永久组合 API 路由。

prefix=/perm-portfolio（避开已被交易持仓占用的 /portfolio）。
main.py 注册：app.include_router(perm_portfolio_router, prefix="/api/v1")
最终路径：/api/v1/perm-portfolio/*
"""
from typing import Optional

from fastapi import APIRouter

from src.api.handler.perm_portfolio_handler import (
    apply_rebalance,
    backtest_portfolio,
    create_instrument,
    create_portfolio,
    delete_instrument,
    delete_portfolio,
    get_nav_history,
    get_portfolio,
    get_rebalance,
    list_instruments,
    list_portfolios,
    update_instrument,
    update_portfolio,
)

router = APIRouter(prefix="/perm-portfolio", tags=["perm-portfolio"])


# ── 标的池 ────────────────────────────────────────────────────
@router.get("/instruments")
def _list_instruments(
    market: Optional[str] = None,
    asset_class: Optional[str] = None,
):
    return list_instruments(market=market, asset_class=asset_class)


@router.post("/instruments")
def _create_instrument(body: dict):
    return create_instrument(body)


@router.put("/instruments/{instrument_id}")
def _update_instrument(instrument_id: int, body: dict):
    return update_instrument(instrument_id, body)


@router.delete("/instruments/{instrument_id}")
def _delete_instrument(instrument_id: int):
    return delete_instrument(instrument_id)


# ── 组合 ──────────────────────────────────────────────────────
@router.get("/portfolios")
def _list_portfolios():
    return list_portfolios()


@router.post("/portfolios")
def _create_portfolio(body: dict):
    return create_portfolio(body)


@router.get("/portfolios/{portfolio_id}")
def _get_portfolio(portfolio_id: int):
    return get_portfolio(portfolio_id)


@router.put("/portfolios/{portfolio_id}")
def _update_portfolio(portfolio_id: int, body: dict):
    return update_portfolio(portfolio_id, body)


@router.delete("/portfolios/{portfolio_id}")
def _delete_portfolio(portfolio_id: int):
    return delete_portfolio(portfolio_id)


@router.get("/portfolios/{portfolio_id}/nav")
def _get_nav(
    portfolio_id: int,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    return get_nav_history(portfolio_id, start or "", end or "")


@router.get("/portfolios/{portfolio_id}/rebalance")
def _get_rebalance(portfolio_id: int):
    return get_rebalance(portfolio_id)


@router.post("/portfolios/{portfolio_id}/backtest")
def _backtest(portfolio_id: int, body: dict):
    return backtest_portfolio(portfolio_id, body)


@router.post("/portfolios/{portfolio_id}/rebalance/apply")
def _apply_rebalance(portfolio_id: int, body: dict):
    return apply_rebalance(portfolio_id, body)
```

- [ ] **Step 3: Add _run_backtest placeholder in handler (Task 9 will fill)**

The handler references `_run_backtest` which Task 9 implements. For now, add a stub so import doesn't break. Append to `backend/src/api/handler/perm_portfolio_handler.py`:

```python


def _run_backtest(portfolio_id: int, body: dict) -> dict:
    """回测实现（Task 9 填充）。"""
    raise NotImplementedError("backtest not yet implemented")
```

(Note: Task 9 replaces this stub with the real implementation. This keeps Task 8 self-contained and import-safe.)

- [ ] **Step 4: Register router in main.py**

Modify `backend/main.py`. Find the router import block near the top (where `lt_backtest_router`, `macro_router` etc. are imported). Add:

```python
from src.api.router.perm_portfolio_router import router as perm_portfolio_router
```

Find the `app.include_router(...)` block (L279-308) and add after the `lt_backtest_router` line:

```python
    app.include_router(perm_portfolio_router, prefix="/api/v1")  # /api/v1/perm-portfolio
```

- [ ] **Step 5: Smoke test the router imports**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "from src.api.router.perm_portfolio_router import router; print('routes:', len(router.routes))"`
Expected: prints `routes: 13`.

- [ ] **Step 6: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/src/api/handler/perm_portfolio_handler.py \
        backend/src/api/router/perm_portfolio_router.py \
        backend/main.py
git commit -m "feat(portfolio): add 13-endpoint perm-portfolio API + register in main.py"
```

---

## Task 9: 回测集成（FixedWeightStrategy + backtest 端点）

复用 `PortfolioBacktester`，新增固定权重策略适配器，填充 Task 8 的 `_run_backtest`。

**Files:**
- Create: `backend/src/domain/market/portfolio/permanent_strategy.py`
- Modify: `backend/src/api/handler/perm_portfolio_handler.py`（替换 `_run_backtest` stub）
- Test: `backend/tests/domain/market/portfolio/test_permanent_strategy.py`

**Interfaces:**
- Consumes: `LongTermStrategy`（base.py）/ `RebalanceSignal` / `PortfolioBacktester`；Task 4 仓储 `list_holdings` / `get_instrument`；`lt_backtest_router._fetch_daily_from_db` 的 bar 加载模式。
- Produces: `FixedWeightStrategy`；`_run_backtest(portfolio_id, body)` 返回 `LongTermResult.to_dict()`。Task 10 前端持仓 tab 的"回测此组合"按钮依赖。

- [ ] **Step 1: Write the failing test**

Create `backend/tests/domain/market/portfolio/test_permanent_strategy.py`:

```python
"""FixedWeightStrategy 单测：始终返回固定目标权重。"""
from datetime import date

from src.domain.market.portfolio.permanent_strategy import (
    FixedWeightStrategy,
)
from src.domain.market.sync.sync_provider import OHLCVBar


def _bar(sym: str, d: str, close: float) -> OHLCVBar:
    from datetime import datetime
    return OHLCVBar(
        symbol=sym, trade_time=datetime.strptime(d, "%Y-%m-%d"),
        open_=close, close_=close, high_=close, low_=close,
        volume=0.0, amount=0.0, interval="1d", market="A",
        provider="test",
    )


def test_returns_fixed_target_weights():
    strat = FixedWeightStrategy(
        name="永久", target_weights={"sh510300": 0.25, "sh511260": 0.75},
    )
    bars = {
        "sh510300": [_bar("sh510300", "2026-08-07", 10.0)],
        "sh511260": [_bar("sh511260", "2026-08-07", 10.0)],
    }
    sig = strat.on_rebalance(
        today=date(2026, 8, 7), bars_by_symbol=bars,
    )
    assert sig.target_weights == {"sh510300": 0.25, "sh511260": 0.75}
    assert "永久" in sig.reason


def test_get_param_specs_returns_empty():
    strat = FixedWeightStrategy(name="x", target_weights={})
    assert strat.get_param_specs() == []


def test_rebalance_freq_monthly():
    strat = FixedWeightStrategy(name="x", target_weights={})
    assert strat.rebalance_freq == "monthly"


def test_backtester_runs_with_fixed_weight():
    """集成：PortfolioBacktester + FixedWeightStrategy 出结果。"""
    from src.domain.market.strategy.longterm.portfolio_backtester import (
        PortfolioBacktester,
    )

    strat = FixedWeightStrategy(
        name="永久", target_weights={"sh510300": 1.0},
    )
    bars = {
        "sh510300": [
            _bar("sh510300", f"2026-08-{d:02d}", 10.0 + d * 0.1)
            for d in range(1, 31)
        ],
    }
    bt = PortfolioBacktester(initial_capital=100000.0)
    result = bt.run(strategy=strat, bars_by_symbol=bars)
    assert result.strategy == "永久"
    assert len(result.equity_curve) > 0
    # 总收益非零（价格涨了）
    assert result.total_return_pct != 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/market/portfolio/test_permanent_strategy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.domain.market.portfolio.permanent_strategy'`.

- [ ] **Step 3: Write FixedWeightStrategy**

Create `backend/src/domain/market/portfolio/permanent_strategy.py`:

```python
"""
固定权重回测策略适配器
=====================
永久组合 / 全天候等"始终回归固定目标权重"的策略适配器，
复用现有 PortfolioBacktester，零新建回测代码。

用法：
  strat = FixedWeightStrategy(
      name="永久", target_weights={"sh510300": 0.25, ...},
  )
  bt = PortfolioBacktester()
  result = bt.run(strategy=strat, bars_by_symbol={...})
"""
from datetime import date
from typing import Optional

from ..strategy.longterm.base import LongTermStrategy, ParamSpec
from ..strategy.longterm.models import (
    PortfolioState,
    RebalanceSignal,
)
from ...sync.sync_provider import OHLCVBar


class FixedWeightStrategy(LongTermStrategy):
    """始终返回固定目标权重的长期策略。

    每次 on_rebalance 都回归构造时传入的 target_weights，
    不看历史价格/基本面——适合永久组合这类"恒定配置"策略的回测。
    """

    def __init__(self, name: str, target_weights: dict[str, float]):
        self.name = name
        self.display_name = name
        self._target_weights = dict(target_weights)
        # 默认月频调仓（永久组合的典型节奏）
        self.rebalance_freq = "monthly"

    def on_rebalance(
        self,
        today: date,
        bars_by_symbol: dict[str, list[OHLCVBar]],
        valuation_by_symbol: Optional[dict[str, list[dict]]] = None,
        financials_by_symbol: Optional[dict[str, list[dict]]] = None,
        state: Optional[PortfolioState] = None,
    ) -> RebalanceSignal:
        return RebalanceSignal(
            target_weights=self._target_weights,
            reason=f"{self.name} 固定权重再平衡",
        )

    def get_param_specs(self) -> list[ParamSpec]:
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/market/portfolio/test_permanent_strategy.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Fill _run_backtest in handler**

Replace the `_run_backtest` stub at the end of `backend/src/api/handler/perm_portfolio_handler.py`:

```python
def _run_backtest(portfolio_id: int, body: dict) -> dict:
    """组合历史回测：FixedWeightStrategy + PortfolioBacktester。

    body: {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD",
           "initial_capital"?: float, "benchmark"?: str}
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor

    from src.domain.market.portfolio.permanent_strategy import (
        FixedWeightStrategy,
    )
    from src.domain.market.strategy.longterm.portfolio_backtester import (
        PortfolioBacktester,
    )
    from src.domain.market.sync.sync_provider import OHLCVBar
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    from src.infra.database.sql_engine.dsn import get_dsn

    repo = create_portfolio_repository()
    p = repo.get_portfolio(portfolio_id)
    if p is None:
        raise ValueError("组合不存在")
    holdings = repo.list_holdings(portfolio_id)
    if not holdings:
        raise ValueError("组合无持仓，无法回测")

    # 1. {symbol: target_weight}
    symbol_to_weight: dict[str, float] = {}
    for h in holdings:
        inst = repo.get_instrument(h.instrument_id)
        if inst:
            symbol_to_weight[inst.symbol] = h.target_weight
    if not symbol_to_weight:
        raise ValueError("持仓标的均不在标的池")

    # 2. 拉 bars（复用 lt_backtest_router 的裸 SQL 模式）
    sd = body.get("start_date") or "2000-01-01"
    ed = body.get("end_date") or "2099-12-31"
    bars_by_symbol: dict[str, list[OHLCVBar]] = {}
    try:
        conn = psycopg2.connect(get_dsn())
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for sym in symbol_to_weight:
                cur.execute(
                    """
                    SELECT trade_date, open_, close_, high_, low_,
                           volume, amount, market
                    FROM stock_ohlcv
                    WHERE symbol = %s
                      AND trade_date >= %s
                      AND trade_date <= %s
                    ORDER BY trade_date ASC
                    """,
                    (sym, f"{sd} 00:00:00", f"{ed} 23:59:59"),
                )
                rows = cur.fetchall()
                bars = []
                for r in rows:
                    t = r["trade_date"]
                    if hasattr(t, "to_pydatetime"):
                        t = t.to_pydatetime()
                    bars.append(
                        OHLCVBar(
                            symbol=sym, trade_time=t,
                            open_=float(r["open_"]),
                            close_=float(r["close_"]),
                            high_=float(r["high_"]),
                            low_=float(r["low_"]),
                            volume=float(r["volume"]),
                            amount=float(r.get("amount") or 0.0),
                            interval="1d",
                            market=r.get("market") or "A",
                            provider="db",
                        )
                    )
                bars_by_symbol[sym] = bars
        conn.close()
    except Exception as e:
        raise ValueError(f"读取 stock_ohlcv 失败: {e}")

    missing = [s for s in symbol_to_weight if not bars_by_symbol.get(s)]
    if missing:
        raise ValueError(
            f"以下标的在 stock_ohlcv 无数据: {missing}"
        )
    if not any(bars_by_symbol.values()):
        raise ValueError("回测日期范围内无任何日线数据")

    # 3. 跑回测
    strat = FixedWeightStrategy(
        name=p.name, target_weights=symbol_to_weight,
    )
    initial = body.get("initial_capital", p.initial_capital)
    bt = PortfolioBacktester(initial_capital=initial)
    result = bt.run(strategy=strat, bars_by_symbol=bars_by_symbol)
    return result.to_dict()
```

- [ ] **Step 6: Run all portfolio tests to verify no regressions**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/market/portfolio tests/infra/database/portfolio -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add backend/src/domain/market/portfolio/permanent_strategy.py \
        backend/src/api/handler/perm_portfolio_handler.py \
        backend/tests/domain/market/portfolio/test_permanent_strategy.py
git commit -m "feat(portfolio): add FixedWeightStrategy + wire backtest endpoint"
```

---

## Task 10: 前端 PermPortfolio.tsx 页面 + 路由 + 导航

React 页面：组合列表 + 概览/再平衡/持仓三 tab，recharts 图表。

**Files:**
- Create: `frontend/apps/web/src/pages/PermPortfolio.tsx`
- Create: `frontend/apps/web/src/pages/PermPortfolio.css`
- Modify: `frontend/apps/web/src/App.tsx`（L39 + L79 附近）
- Modify: `frontend/apps/web/src/components/Layout.tsx`（L46-55 Strategy 组）

**Interfaces:**
- Consumes: Task 8 的 13 个端点（`getApiBase()` + `fetch`）；recharts（已装）。
- Produces: `/perm-portfolio` 页面。Task 11 端到端验证依赖。

- [ ] **Step 1: Add route + lazy import in App.tsx**

Modify `frontend/apps/web/src/App.tsx`. Find the lazy import block (around L36-39) and add after the `NationalTeam` line:

```tsx
const PermPortfolio = lazy(() => import('./pages/PermPortfolio').then(m => ({default: m.PermPortfolio})));
```

Find the `<Route path="/national-team" ...>` line (around L79) and add after it:

```tsx
          <Route path="/perm-portfolio" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><PermPortfolio /></Suspense>} />
```

- [ ] **Step 2: Add nav item in Layout.tsx**

Modify `frontend/apps/web/src/components/Layout.tsx`. Find the Strategy nav group (L46-55) and add a new item after the `/portfolio` line:

```tsx
      {path: '/perm-portfolio', label: '永久组合', icon: Icon.portfolio},
```

The Strategy group should now read:

```tsx
  {
    title: 'Strategy',
    items: [
      {path: '/strategies', label: 'Strategies', icon: Icon.strategies},
      {path: '/portfolio', label: 'Portfolio', icon: Icon.portfolio},
      {path: '/perm-portfolio', label: '永久组合', icon: Icon.portfolio},
      {path: '/backtest', label: 'Backtest', icon: Icon.backtest},
      {path: '/t-trading', label: '做T实验室', icon: Icon.flask},
      {path: '/lt-backtest', label: '长期投资', icon: Icon.backtest},
    ],
  },
```

- [ ] **Step 3: Write PermPortfolio.css**

Create `frontend/apps/web/src/pages/PermPortfolio.css`:

```css
/* 永久组合页 — 暗色主题，BEM */
.pp-page {
  padding: 24px;
  color: var(--color-text, #e0e0e0);
  background: var(--color-bg, #0f1419);
  min-height: calc(100vh - 60px);
}

.pp-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 20px;
}

/* 左栏：组合列表 */
.pp-portfolio-list {
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
  padding: 12px;
}

.pp-portfolio-list__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-size: 14px;
  color: var(--color-text-secondary, #8b949e);
}

.pp-portfolio-card {
  padding: 12px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 8px;
  border: 1px solid transparent;
  transition: background 0.15s;
}

.pp-portfolio-card:hover {
  background: rgba(255, 255, 255, 0.04);
}

.pp-portfolio-card--active {
  background: rgba(78, 204, 163, 0.08);
  border-color: var(--color-accent, #4ecca3);
}

.pp-portfolio-card__name {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 4px;
}

.pp-portfolio-card__nav-value {
  font-size: 13px;
  color: var(--color-text-secondary, #8b949e);
}

.pp-portfolio-card__drift {
  font-size: 12px;
  margin-top: 4px;
}

.pp-portfolio-card__drift--warning {
  color: #e54d4d;
}

.pp-portfolio-card__drift--ok {
  color: #2eb872;
}

/* 右栏：详情 */
.pp-detail {
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
  padding: 16px;
}

.pp-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.pp-tabs__item {
  padding: 8px 16px;
  cursor: pointer;
  font-size: 14px;
  color: var(--color-text-secondary, #8b949e);
  border-bottom: 2px solid transparent;
}

.pp-tabs__item--active {
  color: var(--color-accent, #4ecca3);
  border-bottom-color: var(--color-accent, #4ecca3);
}

.pp-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.pp-metric-card {
  background: rgba(255, 255, 255, 0.04);
  padding: 12px;
  border-radius: 6px;
}

.pp-metric-card__label {
  font-size: 12px;
  color: var(--color-text-secondary, #8b949e);
  margin-bottom: 4px;
}

.pp-metric-card__value {
  font-size: 20px;
  font-weight: 600;
}

.pp-chart {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 16px;
}

.pp-chart__title {
  font-size: 13px;
  margin-bottom: 8px;
  color: var(--color-text-secondary, #8b949e);
}

.pp-rebalance-card {
  background: rgba(229, 77, 77, 0.06);
  border: 1px solid rgba(229, 77, 77, 0.3);
  padding: 12px;
  border-radius: 6px;
  margin-bottom: 12px;
}

.pp-rebalance-card--ok {
  background: rgba(46, 184, 114, 0.06);
  border-color: rgba(46, 184, 114, 0.3);
}

.pp-action-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  font-size: 13px;
}

.pp-action-row__action--BUY {
  color: #e54d4d;
}

.pp-action-row__action--SELL {
  color: #2eb872;
}

.pp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.pp-table th,
.pp-table td {
  padding: 8px;
  text-align: right;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.pp-table th {
  color: var(--color-text-secondary, #8b949e);
  font-weight: 500;
  text-align: right;
}

.pp-table th:first-child,
.pp-table td:first-child {
  text-align: left;
}

.pp-btn {
  padding: 6px 14px;
  border-radius: 4px;
  border: 1px solid var(--color-accent, #4ecca3);
  background: transparent;
  color: var(--color-accent, #4ecca3);
  cursor: pointer;
  font-size: 13px;
}

.pp-btn:hover {
  background: rgba(78, 204, 163, 0.1);
}

.pp-empty {
  text-align: center;
  padding: 40px;
  color: var(--color-text-secondary, #8b949e);
  font-size: 14px;
}
```

- [ ] **Step 4: Write PermPortfolio.tsx**

Create `frontend/apps/web/src/pages/PermPortfolio.tsx`:

```tsx
/**
 * PermPortfolio — 永久投资组合管理页
 *
 * 三 tab：
 *   1. 概览：净值曲线 + 配置对比饼图 + 资产类偏离条形图 + 关键指标
 *   2. 再平衡：偏离趋势 + 当前建议 + 应用按钮
 *   3. 持仓：持仓表 + 回测入口
 *
 * 顶部：标的池管理弹窗（CRUD）
 */
import React, {useEffect, useState, useMemo} from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, BarChart, Bar,
  ReferenceLine,
} from 'recharts';
import {getApiBase} from '../lib/api';
import './PermPortfolio.css';

const API_BASE = getApiBase();

const ASSET_COLORS: Record<string, string> = {
  equity: '#4ecca3', bond: '#5b9bd5', gold: '#e5a04d', cash: '#8b949e',
};
const ASSET_LABEL: Record<string, string> = {
  equity: '股票', bond: '债券', gold: '黄金', cash: '现金',
};

interface PortfolioSummary {
  id: number;
  name: string;
  strategy_type: string;
  rebalance_threshold: number;
  initial_capital: number;
  latest_nav: NavRecord | null;
}
interface NavRecord {
  id: number;
  trade_date: string;
  nav_cny: number;
  prev_nav_cny: number | null;
  daily_return: number | null;
  total_value_cny: number;
  max_drift: number;
  rebalance_suggested: boolean;
}
interface NavItemRecord {
  instrument_id: number;
  symbol: string;
  asset_class: string;
  shares: number;
  price: number;
  price_cny: number;
  value_cny: number;
  target_weight: number;
  actual_weight: number;
  drift: number;
}
interface RebalanceAction {
  instrument_id: number;
  symbol: string;
  asset_class: string;
  action: 'BUY' | 'SELL';
  shares_delta: number;
  reason: string;
}

type Tab = 'overview' | 'rebalance' | 'holdings';

async function apiGet(path: string): Promise<any> {
  const r = await fetch(`${API_BASE}/perm-portfolio${path}`);
  return r.json();
}
async function apiPost(path: string, body: any): Promise<any> {
  const r = await fetch(`${API_BASE}/perm-portfolio${path}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  return r.json();
}

export const PermPortfolio: React.FC = () => {
  const [portfolios, setPortfolios] = useState<PortfolioSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [tab, setTab] = useState<Tab>('overview');
  const [detail, setDetail] = useState<any>(null);
  const [navHistory, setNavHistory] = useState<any[]>([]);
  const [rebalance, setRebalance] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [range, setRange] = useState('3M');

  useEffect(() => {
    apiGet('/portfolios').then(j => {
      if (j.code === 0) {
        setPortfolios(j.data);
        if (j.data.length > 0 && selectedId === null) {
          setSelectedId(j.data[0].id);
        }
      }
    });
  }, []);

  useEffect(() => {
    if (selectedId === null) return;
    setLoading(true);
    Promise.all([
      apiGet(`/portfolios/${selectedId}`),
      apiGet(
        `/portfolios/${selectedId}/nav?start=${rangeStart(range)}` +
        `&end=${todayStr()}`,
      ),
      apiGet(`/portfolios/${selectedId}/rebalance`),
    ]).then(([d, h, rb]) => {
      if (d.code === 0) setDetail(d.data);
      if (h.code === 0) setNavHistory(h.data);
      if (rb.code === 0) setRebalance(rb.data);
      setLoading(false);
    });
  }, [selectedId, range]);

  const equityCurve = useMemo(
    () => navHistory.map(n => ({date: n.trade_date, nav: n.nav_cny})),
    [navHistory],
  );
  const latestItems: NavItemRecord[] = useMemo(
    () => (detail?.latest_nav_items || []),
    [detail],
  );
  const targetPie = useMemo(() => aggregateByClass(latestItems, 'target_weight'), [latestItems]);
  const actualPie = useMemo(() => aggregateByClass(latestItems, 'actual_weight'), [latestItems]);
  const driftBars = useMemo(() => aggregateDrift(latestItems), [latestItems]);

  return (
    <div className="pp-page">
      <div className="pp-layout">
        {/* 左栏：组合列表 */}
        <div className="pp-portfolio-list">
          <div className="pp-portfolio-list__header">
            <span>组合列表</span>
            <button className="pp-btn" onClick={() => alert('新建组合（TODO UI）')}>+ 新建</button>
          </div>
          {portfolios.map(p => {
            const nav = p.latest_nav;
            const drift = nav?.max_drift ?? 0;
            const over = drift > p.rebalance_threshold;
            return (
              <div
                key={p.id}
                className={`pp-portfolio-card${selectedId === p.id ? ' pp-portfolio-card--active' : ''}`}
                onClick={() => {setSelectedId(p.id); setTab('overview');}}
              >
                <div className="pp-portfolio-card__name">{p.name}</div>
                <div className="pp-portfolio-card__nav-value">
                  净值 {nav ? nav.nav_cny.toFixed(4) : '—'}
                  {nav?.daily_return != null && (
                    <span style={{marginLeft: 8, color: nav.daily_return >= 0 ? '#e54d4d' : '#2eb872'}}>
                      {nav.daily_return >= 0 ? '+' : ''}{(nav.daily_return * 100).toFixed(2)}%
                    </span>
                  )}
                </div>
                <div className={`pp-portfolio-card__drift${over ? ' pp-portfolio-card__drift--warning' : ' pp-portfolio-card__drift--ok'}`}>
                  偏离 {drift !== undefined ? (drift * 100).toFixed(2) + '%' : '—'}
                </div>
              </div>
            );
          })}
        </div>

        {/* 右栏：详情 */}
        <div className="pp-detail">
          {!detail || loading ? (
            <div className="pp-empty">加载中…</div>
          ) : (
            <>
              <div className="pp-tabs">
                {(['overview', 'rebalance', 'holdings'] as Tab[]).map(t => (
                  <div
                    key={t}
                    className={`pp-tabs__item${tab === t ? ' pp-tabs__item--active' : ''}`}
                    onClick={() => setTab(t)}
                  >
                    {tabLabel(t)}
                  </div>
                ))}
              </div>

              {tab === 'overview' && (
                <OverviewTab
                  equityCurve={equityCurve}
                  targetPie={targetPie}
                  actualPie={actualPie}
                  driftBars={driftBars}
                  threshold={detail.rebalance_threshold}
                  range={range}
                  onRangeChange={setRange}
                  latestNav={detail.latest_nav}
                />
              )}

              {tab === 'rebalance' && (
                <RebalanceTab
                  navHistory={navHistory}
                  threshold={detail.rebalance_threshold}
                  rebalance={rebalance}
                  onApply={() => {
                    if (!rebalance || !rebalance.actions?.length) return;
                    if (!confirm(`确认应用 ${rebalance.actions.length} 条再平衡指令？`)) return;
                    apiPost(`/portfolios/${selectedId}/rebalance/apply`, {actions: rebalance.actions})
                      .then(() => alert('已应用，次日 nav job 生效'));
                  }}
                />
              )}

              {tab === 'holdings' && (
                <HoldingsTab items={latestItems} portfolioId={selectedId!} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

/* ── 概览 Tab ── */
const OverviewTab: React.FC<any> = ({
  equityCurve, targetPie, actualPie, driftBars, threshold, range,
  onRangeChange, latestNav,
}) => (
  <>
    <div className="pp-metrics">
      <MetricCard label="最新净值" value={latestNav ? latestNav.nav_cny.toFixed(4) : '—'} />
      <MetricCard label="今日涨跌" value={latestNav?.daily_return != null ? (latestNav.daily_return * 100).toFixed(2) + '%' : '—'} />
      <MetricCard label="最大偏离" value={latestNav ? (latestNav.max_drift * 100).toFixed(2) + '%' : '—'} />
      <MetricCard label="总市值" value={latestNav ? '¥' + Math.round(latestNav.total_value_cny).toLocaleString() : '—'} />
    </div>

    <div className="pp-chart">
      <div className="pp-chart__title">
        净值曲线
        {['1M', '3M', '6M', '1Y', 'ALL'].map(r => (
          <button key={r} className="pp-btn" style={{marginLeft: 8, padding: '2px 8px', fontSize: 12, opacity: range === r ? 1 : 0.5}} onClick={() => onRangeChange(r)}>{r}</button>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={equityCurve}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
          <XAxis dataKey="date" stroke="#8b949e" fontSize={11} />
          <YAxis stroke="#8b949e" fontSize={11} domain={['auto', 'auto']} />
          <Tooltip contentStyle={{background: '#1a1f26', border: '1px solid #333'}} />
          <Line type="monotone" dataKey="nav" stroke="#4ecca3" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>

    <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16}}>
      <div className="pp-chart">
        <div className="pp-chart__title">目标配置</div>
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie data={targetPie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={70} label>
              {targetPie.map((e: any, i: number) => <Cell key={i} fill={ASSET_COLORS[e.key] || '#888'} />)}
            </Pie>
            <Tooltip contentStyle={{background: '#1a1f26', border: '1px solid #333'}} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="pp-chart">
        <div className="pp-chart__title">实际配置</div>
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie data={actualPie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={70} label>
              {actualPie.map((e: any, i: number) => <Cell key={i} fill={ASSET_COLORS[e.key] || '#888'} />)}
            </Pie>
            <Tooltip contentStyle={{background: '#1a1f26', border: '1px solid #333'}} />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>

    <div className="pp-chart">
      <div className="pp-chart__title">资产类偏离（红线 = 触发阈值 ±{Math.round(threshold * 100)}%）</div>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={driftBars}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
          <XAxis dataKey="name" stroke="#8b949e" fontSize={11} />
          <YAxis stroke="#8b949e" fontSize={11} tickFormatter={(v: number) => (v * 100).toFixed(0) + '%'} />
          <Tooltip contentStyle={{background: '#1a1f26', border: '1px solid #333'}} formatter={(v: number) => (v * 100).toFixed(2) + '%'} />
          <ReferenceLine y={threshold} stroke="#e54d4d" strokeDasharray="4 4" />
          <ReferenceLine y={-threshold} stroke="#e54d4d" strokeDasharray="4 4" />
          <Bar dataKey="drift">
            {driftBars.map((e: any, i: number) => (
              <Cell key={i} fill={Math.abs(e.drift) > threshold ? '#e54d4d' : '#4ecca3'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  </>
);

/* ── 再平衡 Tab ── */
const RebalanceTab: React.FC<any> = ({navHistory, threshold, rebalance, onApply}) => {
  const driftCurve = navHistory.map(n => ({date: n.trade_date, drift: n.max_drift}));
  const actions: RebalanceAction[] = rebalance?.actions || [];
  return (
    <>
      <div className="pp-chart">
        <div className="pp-chart__title">偏离度历史（红线 = 阈值 {Math.round(threshold * 100)}%）</div>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={driftCurve}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis dataKey="date" stroke="#8b949e" fontSize={11} />
            <YAxis stroke="#8b949e" fontSize={11} tickFormatter={(v: number) => (v * 100).toFixed(0) + '%'} />
            <Tooltip contentStyle={{background: '#1a1f26', border: '1px solid #333'}} formatter={(v: number) => (v * 100).toFixed(2) + '%'} />
            <ReferenceLine y={threshold} stroke="#e54d4d" strokeDasharray="4 4" />
            <Line type="monotone" dataKey="drift" stroke="#e5a04d" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className={`pp-rebalance-card${actions.length === 0 ? ' pp-rebalance-card--ok' : ''}`}>
        <div style={{fontWeight: 600, marginBottom: 8}}>
          {actions.length === 0
            ? `✓ 配置在阈值内（trade_date ${rebalance?.trade_date || '—'}）`
            : `⚠ 建议再平衡（max_drift ${(rebalance?.max_drift * 100 || 0).toFixed(2)}% > 阈值 ${Math.round(threshold * 100)}%）`}
        </div>
        {actions.map((a, i) => (
          <div key={i} className="pp-action-row">
            <span>
              <span className={`pp-action-row__action--${a.action}`}>{a.action}</span>
              {' '}{a.shares_delta} 股 {a.symbol}（{ASSET_LABEL[a.asset_class] || a.asset_class}）
            </span>
            <span style={{color: '#8b949e', fontSize: 12}}>{a.reason}</span>
          </div>
        ))}
        {actions.length > 0 && (
          <button className="pp-btn" style={{marginTop: 12}} onClick={onApply}>应用建议</button>
        )}
      </div>
    </>
  );
};

/* ── 持仓 Tab ── */
const HoldingsTab: React.FC<{items: NavItemRecord[]; portfolioId: number}> = ({items, portfolioId}) => {
  const [btResult, setBtResult] = useState<any>(null);
  const [btLoading, setBtLoading] = useState(false);
  const runBacktest = () => {
    setBtLoading(true);
    const sd = new Date(); sd.setFullYear(sd.getFullYear() - 1);
    apiPost(`/portfolios/${portfolioId}/backtest`, {
      start_date: sd.toISOString().slice(0, 10),
      end_date: new Date().toISOString().slice(0, 10),
    }).then(j => {setBtResult(j.data); setBtLoading(false);});
  };
  return (
    <>
      <table className="pp-table">
        <thead>
          <tr>
            <th>标的</th><th>资产类</th><th>目标权重</th><th>实际权重</th>
            <th>股数</th><th>原币价</th><th>人民币市值</th><th>偏离</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={i}>
              <td>{it.symbol}</td>
              <td>{ASSET_LABEL[it.asset_class] || it.asset_class}</td>
              <td>{(it.target_weight * 100).toFixed(1)}%</td>
              <td>{(it.actual_weight * 100).toFixed(1)}%</td>
              <td>{it.shares}</td>
              <td>{it.price.toFixed(3)}</td>
              <td>¥{Math.round(it.value_cny).toLocaleString()}</td>
              <td style={{color: Math.abs(it.drift) > 0.05 ? '#e54d4d' : '#8b949e'}}>
                {(it.drift * 100).toFixed(2)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{marginTop: 16}}>
        <button className="pp-btn" onClick={runBacktest} disabled={btLoading}>
          {btLoading ? '回测中…' : '回测此组合（近 1 年）'}
        </button>
      </div>
      {btResult && (
        <div className="pp-metrics" style={{marginTop: 16}}>
          <MetricCard label="总收益" value={(btResult.total_return_pct || 0).toFixed(2) + '%'} />
          <MetricCard label="年化" value={(btResult.cagr || 0).toFixed(2) + '%'} />
          <MetricCard label="最大回撤" value={(btResult.max_drawdown || 0).toFixed(2) + '%'} />
          <MetricCard label="夏普" value={(btResult.sharpe_ratio || 0).toFixed(3)} />
        </div>
      )}
    </>
  );
};

/* ── 小工具 ── */
const MetricCard: React.FC<{label: string; value: string}> = ({label, value}) => (
  <div className="pp-metric-card">
    <div className="pp-metric-card__label">{label}</div>
    <div className="pp-metric-card__value">{value}</div>
  </div>
);

function aggregateByClass(items: NavItemRecord[], key: 'target_weight' | 'actual_weight') {
  const m: Record<string, number> = {};
  for (const it of items) {
    m[it.asset_class] = (m[it.asset_class] || 0) + it[key];
  }
  return Object.entries(m).map(([k, v]) => ({
    key: k, name: ASSET_LABEL[k] || k, value: Math.round(v * 1000) / 1000,
  }));
}
function aggregateDrift(items: NavItemRecord[]) {
  const m: Record<string, number> = {};
  for (const it of items) {
    m[it.asset_class] = (m[it.asset_class] || 0) + it.drift;
  }
  return Object.entries(m).map(([k, v]) => ({
    key: k, name: ASSET_LABEL[k] || k, drift: v,
  }));
}
function tabLabel(t: Tab): string {
  return {overview: '概览', rebalance: '再平衡', holdings: '持仓'}[t];
}
function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}
function rangeStart(r: string): string {
  const d = new Date();
  if (r === '1M') d.setMonth(d.getMonth() - 1);
  else if (r === '3M') d.setMonth(d.getMonth() - 3);
  else if (r === '6M') d.setMonth(d.getMonth() - 6);
  else if (r === '1Y') d.setFullYear(d.getFullYear() - 1);
  else return '2000-01-01';  // ALL
  return d.toISOString().slice(0, 10);
}
```

- [ ] **Step 5: Verify frontend builds (typecheck)**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend && npx tsc --noEmit -p apps/web 2>&1 | head -30`
Expected: no errors referencing `PermPortfolio` (other pre-existing errors may show — only ensure PermPortfolio/App/Layout are clean).

- [ ] **Step 6: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add frontend/apps/web/src/pages/PermPortfolio.tsx \
        frontend/apps/web/src/pages/PermPortfolio.css \
        frontend/apps/web/src/App.tsx \
        frontend/apps/web/src/components/Layout.tsx
git commit -m "feat(portfolio): add PermPortfolio frontend page + route + nav"
```

---

## Task 11: 端到端验证

跑通完整链路：建表 → seed → 同步 → 算净值 → API → 前端。

**Files:**
- 无新文件。验证 Task 1-10 的集成。

**Interfaces:**
- Consumes: Task 1-10 全部产出。
- Produces: 验证报告（口头确认，不写文件）。

- [ ] **Step 1: Verify tables created on startup**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "
from sqlmodel import SQLModel
from src.infra.database.portfolio.models import *
names = SQLModel.metadata.tables.keys()
for t in ('portfolio_instrument','portfolio_definition','portfolio_holding','portfolio_nav','portfolio_nav_item'):
    assert t in names, f'{t} missing'
print('all 5 tables in metadata')
"`
Expected: prints `all 5 tables in metadata`.

- [ ] **Step 2: Run full test suite**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/market/portfolio tests/infra/database/portfolio tests/domain/market/sync/providers/test_akshare_portfolio.py -v`
Expected: all PASS (count: 5 nav + 4 rebalance + 6 models + 8 repo + 4 akshare + 4 strategy = 31 passed).

- [ ] **Step 3: Seed data (against dev DB)**

Run:
```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
.venv/bin/python -m scripts.seed_portfolio_instruments
.venv/bin/python -m scripts.seed_preset_portfolios
```
Expected: prints `[seed] done: 12 instruments` and `[seed] create portfolio '永久投资组合'` × 3 (or "exists, skip" if rerun).

- [ ] **Step 4: Verify API endpoints respond**

Start the server (or hit a running one). Smoke-test the list endpoints:

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "
import requests
base = 'http://localhost:8000/api/v1/perm-portfolio'
for path in ['/instruments', '/portfolios']:
    r = requests.get(base + path)
    j = r.json()
    print(path, 'code=', j.get('code'), 'count=', len(j.get('data') or []))
"`
Expected: both print `code= 0` with non-zero counts (12 instruments, 3 portfolios).

If no server running, document the manual curl:
```bash
curl -s http://localhost:8000/api/v1/perm-portfolio/portfolios | python -m json.tool
```

- [ ] **Step 5: Verify portfolio_daily reads DB (dry run imports)**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "
from src.domain.market.sync.jobs import portfolio_daily
insts = portfolio_daily._load_universe_bars()
pairs = portfolio_daily._derive_fx_pairs()
print('instruments from DB:', len(insts))
print('fx pairs:', pairs)
"`
Expected: prints instrument count = 12 (or however many enabled) and fx pairs including `USDCNY` + `HKDCNY` (if HK portfolios seeded).

- [ ] **Step 6: Run nav job manually for one portfolio**

Run:
```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
.venv/bin/python -m src.domain.market.sync.jobs.portfolio_nav_daily
```
Expected: logs `[nav] complete` after processing 3 portfolios. Some may warn about missing price/fx if行情未同步 — that's acceptable for first run; subsequent `portfolio_daily` runs fill data.

- [ ] **Step 7: Verify nav data written via API**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "
import requests
r = requests.get('http://localhost:8000/api/v1/perm-portfolio/portfolios/1')
j = r.json()
p = j.get('data') or {}
print('portfolio:', p.get('name'))
print('latest_nav:', p.get('latest_nav') is not None)
print('nav_items:', len(p.get('latest_nav_items') or []))
"`
Expected: `latest_nav: True` and `nav_items` ≥ 1 (assuming job ran successfully in Step 6).

- [ ] **Step 8: Verify rebalance + nav history endpoints**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "
import requests
base = 'http://localhost:8000/api/v1/perm-portfolio'
rb = requests.get(base + '/portfolios/1/rebalance').json()
print('rebalance:', rb.get('code'), 'actions:', len((rb.get('data') or {}).get('actions') or []))
nav = requests.get(base + '/portfolios/1/nav?start=2026-01-01&end=2026-12-31').json()
print('nav history:', nav.get('code'), 'records:', len(nav.get('data') or []))
"`
Expected: `rebalance: 0` and `nav history: 0` with `records` ≥ 1.

- [ ] **Step 9: Verify frontend page loads**

Open browser at `http://localhost:5173/perm-portfolio` (or whatever the dev server URL is). Confirm:
- 左栏显示 3 个预置组合卡片
- 点击组合 → 右栏加载概览 tab
- 净值曲线 / 饼图 / 偏离条形图渲染（若有 nav 数据）
- 切换到再平衡 tab → 显示建议或"配置在阈值内"
- 切换到持仓 tab → 显示持仓表

- [ ] **Step 10: Final commit (any e2e fixups)**

If any fixups were needed during verification:
```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add -A
git commit -m "test(portfolio): e2e verification fixups"
```

If no fixups needed, no commit — Task 11 is verification only.

---

## Self-Review

### 1. Spec coverage

逐条核对 spec 各章节对应的 task：

- **§2.1 标的池 DB 管理** → Task 3 (表) + Task 4 (repo) + Task 8 (API CRUD) + Task 10 (UI 标的池管理按钮——已在 PermPortfolio 顶部留了 `+ 新建` 按钮，CRUD 弹窗实现为 alert placeholder; spec §4.9.2 列出"标的池管理弹窗"。**GAP**: 弹窗的完整 CRUD UI 未给出代码，仅留按钮)。
- **§2.1 多组合 DB 管理** → Task 3 + 4 + 8 (portfolio CRUD 5 端点) + Task 7 (seed 3 组合) + Task 10 (列表/详情)。
- **§2.1 每日净值物化** → Task 6 (portfolio_nav_daily job) + Task 1 (calc) + Task 3 (nav 表)。
- **§2.1 再平衡建议** → Task 2 (advisor) + Task 8 (`/rebalance` + `/rebalance/apply` 端点) + Task 10 (再平衡 tab)。
- **§2.1 组合回测** → Task 9 (FixedWeightStrategy + `_run_backtest`) + Task 8 (`/backtest` 端点) + Task 10 (持仓 tab 回测按钮)。
- **§2.1 H 股支持** → Task 5 (akshare 港股分流 + HKDCNY) + Task 7 (seed 港股 4 标的)。
- **§2.1 前端页面** → Task 10 (PermPortfolio.tsx 三 tab)。
- **§4.1 5 张表** → Task 3 全部覆盖（字段与 spec 一致）。
- **§4.2 nav_calculator** → Task 1（口径与 spec §4.2 权重约定完全一致）。
- **§4.3 rebalance_advisor** → Task 2（按资产类聚合、超配按市值比例卖、低配按目标权重买，与 spec 一致）。
- **§4.4 FixedWeightStrategy** → Task 9。
- **§4.5 repository** → Task 4 接口覆盖 spec 列出的全部方法（list_instruments/upsert/delete/list_portfolios/get/create/update/delete/list_holdings/set_holdings/get_latest_nav/get_nav_history/get_nav_items/save_nav）。
- **§4.6 nav job** → Task 6 实现与 spec 伪代码一致。
- **§4.7.1 seed** → Task 7。
- **§4.7.2 portfolio_daily 改造** → Task 6。
- **§4.7.3 港股分流** → Task 5。
- **§4.7.4 HKDCNY** → Task 5。
- **§4.8 API 13 端点** → Task 8 全部覆盖。
- **§4.9 前端** → Task 10（路由 + 导航 + 三 tab + recharts 图表）。
- **§7 测试策略** → Task 1/2/9 单测 + Task 4 集成测 + Task 5 provider 单测。覆盖率与 spec §7 的 6 项对应。
- **§8 部署** → Task 7 seed 脚本 + Task 11 验证步骤含建表/seed/sync/nav 全流程。

**GAP（已知，记录给执行者决策）**：
1. spec §4.9.2 的"标的池管理弹窗"完整 CRUD UI：Task 10 仅留了 `+ 新建` 按钮和 alert placeholder。前端标的池 CRUD 可作为后续增强（API 已就绪，UI 缺表单）。这不阻塞核心功能（组合/再平衡/回测全通）。
2. Task 7 seed 用占位价 1.0 分配 shares，spec §4.1.3 要求"用建仓日收盘价算 shares"。首次 nav job 跑前 shares 不准（但 nav 算法用当日价 × shares，只要 shares 与 initial_capital 量级匹配，首次 nav 会归一化到合理值）。执行者可在 seed 后用 UI 校准 shares。
3. Task 8 `delete_instrument` 在被引用时返回 `responses.fail(code=INVALID_PARAM)`，spec §六 要求 "返回 409 Conflict"。项目 `responses` 模块无 409 专用码，用 INVALID_PARAM 兜底（前端按 msg 文案判断）。如需严格 409 可扩展 `responses`。

### 2. Placeholder scan

搜索红旗模式：
- `TBD` / `TODO` / `implement later` / `fill in details`：Task 10 有 `alert('新建组合（TODO UI）')` —— 这是 UI 待办提示，非计划占位符（按钮已存在，弹窗 UI 是已知 gap，记录在 self-review）。
- Task 8 Step 3 有 `_run_backtest` stub 抛 `NotImplementedError` —— 这是**有意的中间态**，Task 9 Step 5 明确替换它，不是占位符。
- 所有代码步骤都有完整代码，无 "类似 Task N" / "add appropriate error handling" 等。

### 3. Type consistency

- `NavItemInput` / `NavItemOutput` / `NavResult`（Task 1）→ Task 6 nav job 使用 `NavItemInput` ✓
- `RebalanceHolding` / `RebalanceNavItem` / `RebalanceAction`（Task 2）→ Task 8 `get_rebalance` 使用 ✓
- `PortfolioRepository` 方法名（Task 4）：`list_instruments` / `upsert_instrument` / `delete_instrument` / `list_portfolios` / `get_portfolio` / `create_portfolio` / `update_portfolio` / `delete_portfolio` / `list_holdings` / `set_holdings` / `get_latest_nav` / `get_nav_history` / `get_nav_items` / `save_nav` / `get_close_on` / `apply_share_delta` → Task 6/7/8 全部调用一致 ✓
- `FixedWeightStrategy.__init__(name, target_weights)`（Task 9）→ Task 8 `_run_backtest` 调用 `FixedWeightStrategy(name=p.name, target_weights=symbol_to_weight)` ✓
- `create_portfolio_repository()` / `create_fx_rate_repository()` 工厂签名 → 全 task 一致 ✓
- `responses.success(data)` / `responses.fail(msg=...)`（Task 8）→ 与 macro_handler 一致 ✓
- 表字段名（Task 3）→ Task 4 repository 操作的字段名、Task 8 序列化 dict 的 key 全部对齐 ✓
- `fetch_daily` / `fetch_fx_daily` 签名（Task 5 改造）→ 保持原签名，Task 6 job 调用一致 ✓

无类型/签名不一致问题。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-07-permanent-portfolio.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - 每个任务派发一个独立的子 agent，任务之间进行两阶段审核，快速迭代。适合本计划（11 个任务、依赖链清晰）。

**2. Inline Execution** - 在当前会话用 executing-plans skill 批量执行，带检查点审核。适合你想紧密跟进度的情况。

**选哪种？**
