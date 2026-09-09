# 永久投资组合功能设计 (P2+P3)

**项目**: ytrader 量化交易平台
**模块**: portfolio（新建）+ market/sync（扩展）+ 前端永久组合页
**版本**: 1.0
**日期**: 2026-08-07
**状态**: 待实现
**前置**: `2026-06-21-etf-portfolio-data-sync-design.md` P1 已完成（标的行情 + USDCNY 汇率已同步）

---

## 一、背景与目标

### 1.1 永久投资组合理论

Harry Browne 提出的永久投资组合（Permanent Portfolio）将资金等分四类资产，对冲四种经济环境：

| 资产类 | 目标权重 | 对冲环境 |
|---|---|---|
| 股票 | 25% | 繁荣 |
| 长期国债 | 25% | 通缩 |
| 黄金 | 25% | 通胀 |
| 现金 | 25% | 衰退 |

核心纪律是**周期性再平衡**——当某类资产实际权重偏离目标超阈值时，卖出超配资产、买入低配资产，让配置回归目标。本功能的本质价值在于把这个"监控→偏离识别→再平衡建议"的闭环做成产品。

### 1.2 本功能交付什么

在已完成的 P1（标的行情同步）基础上，交付一个**完整的多组合管理 + 监控 + 再平衡建议 + 回测**功能，适配 A 股 / H 股 / 美股三市场：

- 用户可在 UI 上**管理标的池**（A/H/US 标的的增删改）
- 用户可在 UI 上**管理多个策略组合**（永久组合 / 全天候 / 黄金蝴蝶 / 自定义），每个组合自由选标的 + 配权重
- 系统每日收盘后**自动算净值**（跨市场折算人民币）+ 实际权重 + 偏离度，物化到时序表
- 偏离超阈值时**给出再平衡建议**（具体买卖指令）
- 用户可对任意组合**做历史回测**（复用现有 `lt-backtest` 引擎）

### 1.3 与现有系统的关系

| 现有能力 | 关系 |
|---|---|
| P1：`stock_ohlcv` 已有 A股6+美股4 标的，`fx_rate` 已有 USDCNY | 本功能扩展：标的池转 DB 管理 + 新增 H 股标的 + HKDCNY 汇率 |
| `/api/v1/portfolio`（交易持仓 Brinson 归因） | **命名冲突，本功能用 `/perm-portfolio` 新前缀避开** |
| `/api/v1/lt-backtest`（长期组合回测引擎） | **复用**：永久组合回测 = 固定权重策略 + 现有引擎 |
| `domain/market/strategy/longterm/`（回测领域模型） | **复用**：`RebalanceSignal.target_weights` 范式、`LongTermResult` 指标 |
| `infra/database/alert/`（告警模块） | 本功能暂不接入（偏离在前端展示即可，YAGNI） |

---

## 二、范围划分

### 2.1 做（本 spec）

| 模块 | 内容 |
|---|---|
| **标的池 DB 管理** | `portfolio_instrument` 表 + API + UI（A/H/US 标的增删改） |
| **多组合 DB 管理** | `portfolio_definition` + `portfolio_holding` 表 + API + UI |
| **每日净值物化** | `portfolio_nav` + `portfolio_nav_item` 表 + 定时 job |
| **再平衡建议** | 偏离检测算法 + 建议输出 API + UI 卡片 |
| **组合回测** | 复用 `lt-backtest`，固定权重策略适配器 |
| **H 股支持** | 标的池预置港股 + provider 分流修正 + HKDCNY 汇率同步 |
| **前端页面** | `/perm-portfolio` 页（组合列表 + 概览/再平衡/持仓三 tab） |

### 2.2 不做（YAGNI 边界）

- **不做实盘下单**：再平衡建议只输出指令文本，不接券商 API 自动执行
- **不做分钟级监控**：永久组合是日级策略，日线足够
- **不做告警推送**：偏离信息在前端页展示，不接 alert 模块推送（飞书/站内）
- **不做税务/手续费建模**：再平衡建议是毛值（回测引擎保留手续费建模，实时建议不建）
- **不做组合净值实时刷新**：每日定时算物化，盘中不刷新（盘中无意义，A/H/US 时区不同步）

---

## 三、架构决策

### 3.1 为什么标的池转 DB（而非保留 config.yaml）

P1 把标的清单写在 `config.yaml` 的 `portfolio_universe`。本功能要求**用户能在 UI 自由切换标的**，配置文件无法支撑运行时增删改。

| 方案 | 评价 |
|---|---|
| 保留 config + 实时算 | ✗ 不支持 UI 增删改标的 |
| 标的池全转 DB（本方案） | ✓ 用户可 UI 管理；行情同步改读 DB；config 首次 seed 后废弃 |

**迁移路径**：新增一次性 seed 脚本把 config 现有标的 + 港股标的写入 `portfolio_instrument` 表；改造 `portfolio_daily.py` 从 DB 读标的；`portfolio_universe` config 保留但标记 deprecated。

### 3.2 为什么组合定义走 DB（方案 C 多组合）

用户明确要求支持多组合（永久/全天候/自定义）+ UI 管理。

| 方案 | 评价 |
|---|---|
| 配置定义 + 净值物化（方案 B） | ✗ 不支持 UI 增删改组合、不支持多组合 |
| **完整 DB 管理（方案 C，本方案）** | ✓ 支持多组合 + UI CRUD；定义/持仓/净值全在 DB |
| 纯配置实时算（方案 A） | ✗ 无净值历史、偏离告警无法回溯 |

### 3.3 为什么净值物化到表（而非实时算）

净值/偏离度是时间序列查询，要画历史曲线、看偏离趋势。实时 join `stock_ohlcv`+`fx_rate`+`holdings` 算每日净值会慢且无法回溯历史触发。

### 3.4 为什么用独立明细表（而非 JSONB 快照）

`portfolio_nav_item` 独立表存每日每标的的权重/偏离明细，便于结构化查询（如"查所有组合里股票类偏离最大的标的"）。JSONB 快照虽表少，但查询不便。

### 3.5 为什么回测复用 lt-backtest（而非新建）

现有 `PortfolioBacktester`（`domain/market/strategy/longterm/portfolio_backtester.py`）已是成熟的目标权重回测引擎：接受 `LongTermStrategy`（给目标权重）+ `bars_by_symbol`（从 `stock_ohlcv` 读），返回 `LongTermResult`（净值曲线/年化/回撤/夏普/alpha/beta）。永久组合 = **始终返回固定目标权重的策略**，只需写一个 `PermanentPortfolioStrategy(LongTermStrategy)` 适配器，零新建回测代码。

### 3.6 路由前缀 /perm-portfolio（避开冲突）

`/api/v1/portfolio` 已被交易持仓归因页占用。本功能用 `/api/v1/perm-portfolio`，前端路由 `/perm-portfolio`，菜单项"永久组合"。

### 3.7 分层规范遵循

遵循 CLAUDE.md DDD 四层：
- `domain/market/portfolio/`：纯计算（净值/再平衡引擎），不碰 DB
- `infra/database/portfolio/`：SQLModel 表 + repository（接口在 domain，实现在 infra）
- `api/router/` + `api/handler/`：HTTP 层，调 repository 返回 `responses.ok()`
- 新表走 SQLModel `create_all` 自动建表，不用手写 DDL

---

## 四、组件设计

### 4.1 数据模型（5 张新表）

全部 SQLModel + `create_all` 自动建表。文件：`backend/src/infra/database/portfolio/models.py`。

#### 4.1.1 `portfolio_instrument`（标的池）

```python
class PortfolioInstrument(SQLModel, table=True):
    __tablename__ = "portfolio_instrument"
    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(unique=True, index=True)   # sh510300 / 02800 / VOO
    market: str          # "A" | "HK" | "US"
    asset_class: str     # "equity" | "bond" | "gold" | "cash"
    ccy: str             # "CNY" | "HKD" | "USD"
    name: str            # "沪深300ETF"
    provider: str = "akshare"
    enabled: bool = True
    created_at: datetime
    updated_at: datetime
```

预置 seed（首次启动写入）——A/H/US 三市场，每类资产各市场一只：

| market | equity | bond | gold | cash |
|---|---|---|---|---|
| A | sh510300 沪深300 | sh511260 10年国债 | sh518880 华安黄金 | sh511990 华宝添益 |
| HK | 02800 盈富基金 | 02819 恒生国债ETF | 02840 SPDR金 | 02815 港元货币基金 |
| US | VOO 标普500 | TLT 20+年国债 | GLD 黄金ETF | SHV 短债ETF |

#### 4.1.2 `portfolio_definition`（组合定义）

```python
class PortfolioDefinition(SQLModel, table=True):
    __tablename__ = "portfolio_definition"
    id: int | None = Field(default=None, primary_key=True)
    name: str                               # "永久投资组合"
    strategy_type: str                      # permanent|all_weather|golden_butterfly|custom
    base_ccy: str = "CNY"                   # 净值核算基准币种
    rebalance_threshold: float = 0.05       # 触发再平衡的偏离阈值（5%）
    initial_capital: float = 100000.0       # 初始资金（净值归一化基准）
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
```

预置 seed（首次启动写入 3 个标准组合）：

| name | strategy_type | 资产类目标权重 |
|---|---|---|
| 永久投资组合 | permanent | equity25% / bond25% / gold25% / cash25% |
| 全天候(简化) | all_weather | equity30% / bond55% / gold15% / cash0% |
| 黄金蝴蝶 | golden_butterfly | equity40% / bond20% / gold20% / cash20% |

#### 4.1.3 `portfolio_holding`（组合持仓）

持仓制：记录实际持仓股数 + 成本，净值 = Σ(股数 × 收盘价_cny)。

```python
class PortfolioHolding(SQLModel, table=True):
    __tablename__ = "portfolio_holding"
    id: int | None = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolio_definition.id", index=True)
    instrument_id: int = Field(foreign_key="portfolio_instrument.id")
    target_weight: float          # 该标的占组合的目标权重（0~1）
    shares: int                   # 持仓股数（持仓制核算基准）
    cost_price: float             # 成本价（原币种）
    created_at: datetime
    updated_at: datetime
    __table_args__ = (UniqueConstraint("portfolio_id", "instrument_id"),)
```

**初始 shares 分配**：组合首次创建时，按 `initial_capital × target_weight` 等比买入各标的，用建仓日的收盘价算 `shares = (initial_capital × target_weight) / price`。用户可在 UI 手动调整 shares。

#### 4.1.4 `portfolio_nav`（每日组合净值）

```python
class PortfolioNav(SQLModel, table=True):
    __tablename__ = "portfolio_nav"
    id: int | None = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolio_definition.id", index=True)
    trade_date: date
    nav_cny: float                # 组合净值（归一化，初始日=1.0）
    prev_nav_cny: float | None
    daily_return: float | None    # (nav - prev_nav) / prev_nav
    total_value_cny: float        # 总市值人民币
    max_drift: float               # 最大资产类偏离度（绝对值）
    rebalance_suggested: bool      # max_drift > threshold?
    created_at: datetime
    __table_args__ = (UniqueConstraint("portfolio_id", "trade_date"),)
```

#### 4.1.5 `portfolio_nav_item`（每日持仓明细快照）

替代 JSONB 快照。每条记录 = 某组合某日某标的的实际权重/偏离。

```python
class PortfolioNavItem(SQLModel, table=True):
    __tablename__ = "portfolio_nav_item"
    id: int | None = Field(default=None, primary_key=True)
    nav_id: int = Field(foreign_key="portfolio_nav.id", index=True)
    instrument_id: int
    symbol: str                    # 冗余存储（查询友好）
    asset_class: str
    shares: int
    price: float                   # 当日收盘价（原币种）
    price_cny: float               # 折算人民币
    fx_rate: float                 # 当日折算汇率（CNY标的=1.0）
    value_cny: float               # = shares × price_cny
    target_weight: float
    actual_weight: float           # = value_cny / total_value_cny
    drift: float                   # = actual_weight - target_weight（按资产类聚合后）
    created_at: datetime
```

### 4.2 领域层：净值计算引擎

文件：`backend/src/domain/market/portfolio/nav_calculator.py`（纯函数，不碰 DB）。

```python
@dataclass
class NavItemInput:
    instrument_id: int
    symbol: str
    asset_class: str
    target_weight: float
    shares: int
    price: float          # 原币种收盘价
    fx_rate: float         # → CNY

@dataclass
class NavResult:
    total_value_cny: float
    nav_cny: float
    items: list[NavItemOutput]
    max_drift: float
    rebalance_suggested: bool

def calc_portfolio_nav(
    initial_capital: float,
    threshold: float,
    items_in: list[NavItemInput],
) -> NavResult:
    """
    步骤:
    1. 每标的: value_cny = shares × price × fx_rate
    2. total_value_cny = Σ value_cny
    3. 按 asset_class 聚合算各类资产 actual_weight_class
       (注: target_weight 也是按资产类聚合的——多标的同类相加)
    4. drift_class = actual_weight_class - target_weight_class
    5. max_drift = max(|drift_class|) across 4 classes
    6. nav_cny = total_value_cny / initial_capital
    7. rebalance_suggested = max_drift > threshold
    """
```

**权重约定（重要）**：
- `portfolio_holding.target_weight` 是**单标的**的目标权重。
- 永久组合的再平衡判断是**按资产类（equity/bond/gold/cash）聚合**，不是按单标的。
- 当某资产类有多个标的时，各标的的 `target_weight` 之和 = 该资产类的目标权重。例如股票类目标 25%，配两个标的（沪深300 + 标普500），则各 0.125。
- 实际权重同样按资产类聚合：股票类 actual = Σ(该类各标的 value_cny) / total_value_cny。
- 单标的的 `drift` 字段记录它对所在资产类偏离的贡献（单标的 actual - target），用于下钻定位；触发再平衡的 `max_drift` 是**资产类层面**的偏离。

例如：股票类有沪深300 + 标普500两只，实际权重分别 0.15 / 0.20（合计 0.35），目标 0.25，则股票类 drift = +0.10（超配）。单标的 drift 沪深300 = 0.15-0.125=+0.025，标普500 = 0.20-0.125=+0.075。

### 4.3 领域层：再平衡建议引擎

文件：`backend/src/domain/market/portfolio/rebalance_advisor.py`。

```python
@dataclass
class RebalanceAction:
    instrument_id: int
    symbol: str
    asset_class: str
    action: str            # "BUY" | "SELL"
    shares_delta: int      # 调仓股数（正数绝对值，方向由 action 决定）
    reason: str

def suggest_rebalance(
    holdings: list[PortfolioHolding],
    nav_items: list[PortfolioNavItem],
    threshold: float,
) -> list[RebalanceAction]:
    """
    当 max_drift > threshold 时:
    对每个超配资产类: 算需卖出的市值 = (actual - target) × total_value
       按该类内各标的的当前市值比例分摊卖出股数
    对每个低配资产类: 算需买入的市值 = (target - actual) × total_value
       按该类内各标的的目标权重比例分摊买入股数
    返回具体买卖指令列表
    """
```

### 4.4 领域层：回测策略适配器

文件：`backend/src/domain/market/portfolio/permanent_strategy.py`。

```python
from ..strategy.longterm.base import LongTermStrategy
from ..strategy.longterm.models import RebalanceSignal, PortfolioState

class FixedWeightStrategy(LongTermStrategy):
    """始终返回固定目标权重的策略，用于组合回测。"""
    def __init__(self, name: str, target_weights: dict[str, float]):
        self._name = name
        self._target_weights = target_weights   # {symbol: weight}

    def on_rebalance(self, state: PortfolioState) -> RebalanceSignal:
        # 永久组合: 每次调仓都回归原始目标权重
        return RebalanceSignal(
            target_weights=self._target_weights,
            reason=f"{self._name} 固定权重再平衡"
        )
```

回测 API 接到请求后：从 `portfolio_holding` 读 `{symbol: target_weight}` → 构造 `FixedWeightStrategy` → 从 `stock_ohlcv` 读历史 bars → 调 `PortfolioBacktester.run()` → 返回 `LongTermResult.to_dict()`。

### 4.5 基础设施层：repository

文件：`backend/src/infra/database/portfolio/`。

```
portfolio/
├── models.py                    # 上述 5 个 SQLModel 表
├── repository_interface.py      # IPortfolioRepository (ABC，在 domain)
└── repository.py                # PortfolioRepository(IPortfolioRepository)
                                 # + create_portfolio_repository() 工厂
```

接口方法（关键）：

```python
class IPortfolioRepository(ABC):
    # 标的池
    @abstractmethod
    def list_instruments(self, market=None, asset_class=None) -> list[PortfolioInstrument]: ...
    @abstractmethod
    def upsert_instrument(self, ...) -> PortfolioInstrument: ...
    @abstractmethod
    def delete_instrument(self, instrument_id: int) -> bool: ...

    # 组合定义
    @abstractmethod
    def list_portfolios(self, active_only=True) -> list[PortfolioDefinition]: ...
    @abstractmethod
    def get_portfolio(self, portfolio_id: int) -> PortfolioDefinition | None: ...
    @abstractmethod
    def create_portfolio(self, ...) -> PortfolioDefinition: ...
    @abstractmethod
    def update_portfolio(self, portfolio_id, ...) -> PortfolioDefinition: ...
    @abstractmethod
    def delete_portfolio(self, portfolio_id: int) -> bool: ...

    # 持仓
    @abstractmethod
    def list_holdings(self, portfolio_id: int) -> list[PortfolioHolding]: ...
    @abstractmethod
    def set_holdings(self, portfolio_id: int, holdings: list[dict]) -> None: ...

    # 净值
    @abstractmethod
    def get_latest_nav(self, portfolio_id: int) -> PortfolioNav | None: ...
    @abstractmethod
    def get_nav_history(self, portfolio_id, start, end) -> list[PortfolioNav]: ...
    @abstractmethod
    def get_nav_items(self, nav_id: int) -> list[PortfolioNavItem]: ...
    @abstractmethod
    def save_nav(self, nav: PortfolioNav, items: list[PortfolioNavItem]) -> None: ...
```

### 4.6 每日净值 job

文件：`backend/src/domain/market/sync/jobs/portfolio_nav_daily.py`。

```python
def run():
    repo = create_portfolio_repository()
    for portfolio in repo.list_portfolios(active_only=True):
        holdings = repo.list_holdings(portfolio.id)
        trade_date = latest trading date (T-1 or T)

        # 查当日收盘价 + 汇率
        items_in = []
        for h in holdings:
            inst = repo.get_instrument(h.instrument_id)
            price = stock_ohlcv_repo.get_close(h.instrument.symbol, trade_date)
            fx = fx_rate_repo.get_rate(inst.ccy + "CNY", trade_date) if inst.ccy != "CNY" else 1.0
            items_in.append(NavItemInput(...))

        result = calc_portfolio_nav(portfolio.initial_capital, portfolio.rebalance_threshold, items_in)
        repo.save_nav(PortfolioNav(...), [PortfolioNavItem(...) for each])
```

cron 调度（行情同步后）：
```
0 17 * * 1-5 cd /path/backend && .venv/bin/python -m src.domain.market.sync.jobs.portfolio_nav_daily >> logs/portfolio_nav.log 2>&1
```

### 4.7 数据同步改造

#### 4.7.1 标的池 seed 脚本

文件：`backend/scripts/seed_portfolio_instruments.py`（一次性，部署时手动跑）。

把 config.yaml `portfolio_universe` 现有 10 标的 + 港股 4 标的 + USDCNY/HKDCNY 汇率配置，upsert 到 `portfolio_instrument`。幂等（重复跑覆盖）。

#### 4.7.2 `portfolio_daily.py` 改造

现状：从 `app_config.portfolio_universe.bars` 读标的。
改造：从 `portfolio_instrument WHERE enabled=true` 读标的。同步逻辑（backfill/incremental/SyncService）不变。

#### 4.7.3 H 股标的同步分流修正

`AkshareProvider.fetch_daily`（主入口，L94）当前只区分美股 vs A 股 ETF 两路，5 位纯数字的港股代码会被误判进 `_fetch_a_etf` 返回空。

修正：在 `fetch_daily` 加一段分流——5 位纯数字 → `fetch_hk_stock_daily`。约 3 行改动：

```python
def fetch_daily(self, symbol, ...):
    if self._is_us_ticker(symbol):      # ^[A-Z]{1,5}$
        return self._fetch_us(symbol, ...)
    elif self._is_hk_ticker(symbol):    # ^\d{5}$  ← 新增
        return self.fetch_hk_stock_daily(symbol, ...)
    else:                                # sh510300 / sz159934
        return self._fetch_a_etf(symbol, ...)
```

`fetch_hk_stock_daily`（L443，已存在）走 `ak.stock_hk_daily(symbol="02800", adjust="qfq")`，实测可用。

#### 4.7.4 HKDCNY 汇率同步放开

`AkshareProvider.fetch_fx_daily`（L208）当前硬限制 `if pair != "USDCNY": raise`。放开：`_FX_BOC_SYMBOL` 映射表已含 `HKDCNY: 港币`，实测 `ak.currency_boc_sina(symbol="港币", start_date, end_date)` 可用。注意必须传 `start_date/end_date`（不传返回陈旧默认窗口）。`portfolio_daily.py` 遍历活跃组合涉及的币种同步对应汇率。

### 4.8 API 层

路由：`backend/src/api/router/perm_portfolio_router.py`（`APIRouter(prefix="/perm-portfolio")`）。
处理器：`backend/src/api/handler/perm_portfolio_handler.py`。
注册：`main.py` `app.include_router(perm_portfolio_router, prefix="/api/v1")`。

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/instruments` | 标的池列表（支持 market/asset_class 过滤） |
| POST | `/instruments` | 新增标的（校验 symbol 格式） |
| PUT | `/instruments/{id}` | 编辑标的（改名/启停） |
| DELETE | `/instruments/{id}` | 删除（被组合引用时拒绝，返回 409） |
| GET | `/portfolios` | 组合列表（含最新净值概要） |
| POST | `/portfolios` | 新建组合（含 holdings） |
| GET | `/portfolios/{id}` | 组合详情（定义 + 持仓 + 最新净值） |
| PUT | `/portfolios/{id}` | 编辑组合（调权重/换标的/调 shares） |
| DELETE | `/portfolios/{id}` | 删除组合 |
| GET | `/portfolios/{id}/nav` | 净值历史（支持 start/end/date_range） |
| GET | `/portfolios/{id}/rebalance` | 当前再平衡建议（实时算） |
| POST | `/portfolios/{id}/backtest` | 回测（body: start_date, end_date） |
| POST | `/portfolios/{id}/rebalance/apply` | 应用再平衡（更新 holdings.shares） |

### 4.9 前端

#### 4.9.1 路由与导航

- 路由：`/perm-portfolio`（`App.tsx` 懒加载 `pages/PermPortfolio.tsx`）
- 导航：`Layout.tsx` Strategy 组新增 `{path: '/perm-portfolio', label: '永久组合'}`

#### 4.9.2 页面结构

```
永久组合 (/perm-portfolio)
├── 左栏: 组合列表
│   ├─ 永久投资组合 / 全天候 / 黄金蝴蝶 + "新建组合"按钮
│   └─ 每项: 名称 + 最新净值 + 今日涨跌% + 偏离指示器(红/绿)
│
└── 右栏: 选中组合详情（3 tab）
    ├── Tab 概览
    │   ├─ 净值曲线 (recharts LineChart, 区间 1M/3M/6M/1Y/ALL)
    │   ├─ 配置对比饼图（目标 vs 实际，两个 PieChart 并排）
    │   ├─ 各资产类偏离条形图（BarChart, drift 正负, 红色超阈值）
    │   └─ 关键指标卡: 累计收益/年化/最大回撤/夏普（从最新 nav 算或回测取）
    │
    ├── Tab 再平衡
    │   ├─ 偏离度历史趋势（max_drift 时间曲线 + threshold 横线）
    │   ├─ 再平衡建议卡（当前: 卖X股300ETF / 买Y股黄金ETF）
    │   └─ "应用建议"按钮 → 确认弹窗 → 调 rebalance/apply
    │
    └── Tab 持仓管理
        ├─ 持仓表（标的/目标权重/实际权重/股数/成本/市值/偏离）
        ├─ "回测此组合"按钮 → 弹窗选区间 → 显示回测结果
        └─ 编辑模式: 调权重/换标的（下拉选标的池）/改 shares

顶部: "标的池管理"按钮 → 弹窗（标的池 CRUD 表格 + "新增标的"表单）
```

#### 4.9.3 视觉规范

- 暗色主题，CSS 变量 + rgba（参考 `NationalTeam.tsx` / `Indices.tsx`）
- recharts：LineChart / PieChart / BarChart
- CSS BEM：`pp-portfolio-card__nav-value`、`pp-drift-bar--warning`

---

## 五、数据流

```
                          ┌─────────────────────────────┐
                          │ portfolio_instrument (标的池) │
                          │   A/HK/US 三市场可选标的      │
                          └─────────────┬───────────────┘
                                        │ enabled=true
                                        ▼
  portfolio_daily.run() (改造后从 DB 读标的)
   ├─ AkshareProvider.fetch_daily(VOO)      → stock_ohlcv (US)
   ├─ AkshareProvider.fetch_daily(sh510300) → stock_ohlcv (A)
   ├─ AkshareProvider.fetch_daily(02800)    → stock_ohlcv (HK)  ← 新增分流
   └─ fetch_fx_daily(USDCNY/HKDCNY)         → fx_rate           ← 放开多 pair

                        ┌──────────────────────────────────┐
                        │ portfolio_definition + holding   │
                        │   (用户 UI 管理的组合+持仓)       │
                        └─────────────┬────────────────────┘
                                      │
  portfolio_nav_daily.run() (每日 17:00)
   ├─ 读 holdings + stock_ohlcv 收盘价 + fx_rate 汇率
   ├─ calc_portfolio_nav() 算净值/权重/偏离
   └─ 写 portfolio_nav + portfolio_nav_item
                                      │
                                      ▼
  API (/api/v1/perm-portfolio/*)
   ├─ GET /portfolios/{id}/nav      → 前端净值曲线/偏离图
   ├─ GET /portfolios/{id}/rebalance→ 再平衡建议
   ├─ POST /portfolios/{id}/backtest→ FixedWeightStrategy + PortfolioBacktester
   └─ POST /portfolios/{id}/rebalance/apply → 更新 holding.shares
```

---

## 六、错误处理

| 场景 | 处理 |
|---|---|
| 某标的当日无收盘价（停牌/休市/新上市） | nav job 跳过该标的，用最近交易日收盘价；记 warning |
| 某币种汇率缺失 | nav job 跳过该组合当日，记 error，下次补 |
| 删除被组合引用的标的 | API 返回 409 Conflict，提示"被 N 个组合引用" |
| 组合无持仓 | nav_cny=0，前端显示空状态 |
| 回测日期范围内某标的无数据 | backtester 跳过该标的，记 warning |
| akshare 港股接口失败 | provider 返回空，SyncService mark_partial，下次补 |
| 汇率接口返回陈旧数据（未传日期） | fetch_fx_daily 强制传 start_date/end_date |
| shares=0 的标的 | 纳入计算（贡献 0 值），保留 target_weight 供再平衡参考 |
| 多组合并发算净值 | job 串行处理各组合，无并发问题 |

---

## 七、测试策略

镜像 `src/` 结构，`tests/domain/market/portfolio/` + `tests/infra/database/portfolio/`。

1. **nav_calculator 单测**（纯函数，核心）：
   - 4 标的等权重 → nav=1.0，各 actual_weight=0.25，drift=0
   - 涨跌后实际权重偏离正确
   - 跨币种折算（HKD/USD → CNY）正确
   - 资产类聚合（多标的同类相加）正确
   - max_drift 取绝对值最大
   - threshold 触发判断正确
2. **rebalance_advisor 单测**：
   - 超配类 → 卖出指令股数正确
   - 低配类 → 买入指令股数正确
   - 多标的同类按比例分摊
3. **FixedWeightStrategy 单测**：
   - on_rebalance 返回固定目标权重
4. **repository 集成测试**（DB fixture，自动 rollback）：
   - instrument upsert/delete 幂等
   - portfolio + holding CRUD
   - 引用约束（删被引用标的报错）
   - nav + nav_item 保存与查询
5. **H 股分流单测**（mock akshare）：
   - `fetch_daily("02800")` 走 `fetch_hk_stock_daily`，不走 `_fetch_a_etf`
6. **HKDCNY 汇率单测**（mock akshare）：
   - `fetch_fx_daily("HKDCNY")` 返回正确数据，强制传日期参数

类名 `Test{Resource}`，方法 `test_{action}_{expected}`，遵循项目测试规范。

---

## 八、部署

### 8.1 首次部署

```bash
# 1. 建表（SQLModel create_all 自动）
cd backend && .venv/bin/python -c "from src.infra.database.portfolio.models import *; from src.infra.database.sql_engine.engine import DBConnection; DBConnection().create_all()"

# 2. seed 标的池 + 预置组合
.venv/bin/python -m scripts.seed_portfolio_instruments
.venv/bin/python -m scripts.seed_preset_portfolios

# 3. 首次回填标的行情（含港股）+ 汇率
.venv/bin/python -m src.domain.market.sync.jobs.portfolio_daily

# 4. 首次算净值
.venv/bin/python -m src.domain.market.sync.jobs.portfolio_nav_daily
```

### 8.2 crontab（工作日）

```
# 16:30 同步标的行情 + 汇率（已有，改造读 DB）
30 16 * * 1-5 cd /path/backend && .venv/bin/python -m src.domain.market.sync.jobs.portfolio_daily >> logs/portfolio_sync.log 2>&1

# 17:00 算组合净值（新增，行情同步后）
0 17 * * 1-5 cd /path/backend && .venv/bin/python -m src.domain.market.sync.jobs.portfolio_nav_daily >> logs/portfolio_nav.log 2>&1
```

---

## 九、待实现时核实项

1. `PortfolioInstrument` 的 `symbol` 唯一约束：港股纯数字 vs A 股 sh/sz 前缀 vs 美股字母，确认无跨市场碰撞（现状无碰撞）
2. `portfolio_nav_item` 查询性能：单组合单日 ~4-12 条 item，1 年 ~250 交易日 × 12 = 3000 条/组合/年，无索引压力，但 `nav_id` 加 index
3. 回测 `bars_by_symbol` 从 `stock_ohlcv` 读的实现：确认 `longterm` 模块有现成的 bar 加载器（`lt_backtest_router` 已用），复用之
4. 港股标的 `02815`（港元货币基金）数据连续性：实测 632 行，确认无大段断层再正式入默认池
5. 全天候/黄金蝴蝶的精确目标权重：本 spec 用的是简化版，实现时可参照原版 Ray Dalio / Tyler 包口径微调
6. 前端"应用再平衡"后的净值衔接：apply 会改 holding.shares，次日 nav job 会基于新 shares 算净值，确认净值曲线在 apply 日有跳变但不中断

---

## 十、与 P1 spec 的衔接

本 spec 是 `2026-06-21-etf-portfolio-data-sync-design.md` 的 P2+P3 合并实现，但范围比原 P2/P3 展望更大：

| 原 spec 展望 | 本 spec 实际范围 |
|---|---|
| P2: portfolio 定义表 + 每日净值物化 | ✓ 含，但扩展为多组合 DB 管理（不止单组合） |
| P3: 偏离告警 + 再平衡建议 + 前端组合页 | ✓ 含再平衡建议 + 前端页；告警改为前端展示（不接 alert 推送） |
| （原未提）H 股支持 | ✓ 新增：标的池 + 港股分流 + HKDCNY |
| （原未提）组合回测 | ✓ 新增：复用 lt-backtest |
| （原未提）标的池 UI 管理 | ✓ 新增：用户可 UI 增删改标的 |

P1 的数据同步基础设施（AkshareProvider/SyncService/fx_rate）完全复用，本 spec 不改动 P1 的同步机制本身，只改数据源（config → DB）。
