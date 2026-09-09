# 组合回测增强设计（阶段 1+2：持久化 + 优化策略）

- 日期：2026-08-14
- 状态：已设计，待实现
- 关联：`2026-08-07-permanent-portfolio-design.md`、`2026-06-21-etf-portfolio-data-sync-design.md`
- 范围：在现有组合回测（`/lt-backtest`、`/perm-portfolio` backtest）基础上，新增①回测结果持久化 + 历史对比；②现代组合构建策略（风险平价 / 最小方差 / MVO 最大夏普 / 等权）+ 有效前沿资产配置工具。

---

## 1. 背景与动机

项目现有四套互相独立的回测系统，其中**组合类回测**有两处入口：

- `/lt-backtest`（`lt_backtest_router.py`）—— 7 种经典长期算法，底层 `PortfolioBacktester`（目标权重驱动，bar 迭代，A 股成本，基准 alpha/beta）。
- `/perm-portfolio`（`perm_portfolio_handler.py`）—— 固定权重组合回测（`FixedWeightStrategy` 复用同一 `PortfolioBacktester`）+ 滚动窗口回测。

两处组合回测**结果均不落库**，刷新即丢，无法回看与对比。同时，现有 7 种策略集中在"动量/趋势/定投/价值"，缺少**现代组合构建法**（风险平价、最小方差、均值-方差优化）——这是"资产配置优化"的核心工具。

本 spec 解决这两个缺口。阶段 3（walk-forward）、阶段 4（归因分析）留待后续独立 spec。

### 1.1 现有可复用资产（不重造轮子）

| 资产 | 位置 | 复用方式 |
|---|---|---|
| `PortfolioBacktester` 引擎 | `domain/market/strategy/longterm/portfolio_backtester.py` | 新策略产出 `RebalanceSignal` 即可接入，引擎/成本/基准全白嫖 |
| 策略基类 `LongTermStrategy` | `domain/market/strategy/longterm/base.py` | 新策略继承，实现 `on_rebalance` |
| 策略注册表 | `domain/market/strategy/longterm/strategies/__init__.py` | 注册后自动进 `algorithm_metas()` → 前端原理卡片 |
| `LongTermResult` 结果模型 | `domain/market/strategy/longterm/models.py` | 统一结果结构，`to_dict()` 序列化 |
| 日线/基准数据获取 | `lt_backtest_router.py` `_fetch_daily_from_db` 等 | 新端点复用 |
| 仓储范式 | `infra/database/portfolio/repository.py` + `create_*_repository()` 工厂 | 新仓储照搬 |
| `backtest_results` JSONB 惯例 | `strategy_router.py:30-56` | 结果快照用 JSONB 存 |

---

## 2. 范围边界

**做（阶段 1+2）**：

1. 组合回测结果持久化 —— 新建 `portfolio_backtest_result` 表 + repository，一套覆盖 lt-backtest / perm-portfolio / 新优化策略。
2. 历史列表 / 详情 / 对比 / 删除端点。
3. 4 种新策略：风险平价、最小方差、MVO 最大夏普、等权基线。
4. 有效前沿资产配置工具端点（独立计算，不跑回测）。
5. 前端：回测历史对比视图 + 有效前沿可视化。

**不做（YAGNI）**：

- 不统一 TA/RSI（`/backtest`、`/strategy`）那两套**单标的**回测 —— 用户要的是"组合"回测增强，单标的回测已各自落库。
- 不做实盘下单、walk-forward、归因分析（阶段 3/4）。
- 不引入应用层 use_case 重构现有 handler 编排（保持增量最小；落库以最小侵入接入现有 handler）。

---

## 3. 架构分层

严格遵循 CLAUDE.md DDD 规则（依赖外层→内层）。

```
domain/market/strategy/
├── optimization/                              【新】纯计算，仅依赖 numpy/scipy + base/models
│   ├── __init__.py
│   ├── covariance.py                          # 协方差/预期收益估计（纯函数）
│   ├── solvers.py                             # 通用求解（SLSQP 约束、闭式最小方差、ERC 迭代）
│   ├── risk_parity.py                         # RiskParityStrategy(LongTermStrategy)
│   ├── min_variance.py                        # MinVarianceStrategy(LongTermStrategy)
│   ├── mvo.py                                 # MVOStrategy(最大夏普) + efficient_frontier() 工具
│   └── equal_weight.py                        # EqualWeightStrategy(LongTermStrategy)
├── strategies/__init__.py                     # 注册 4 个新策略进 LONGTERM_STRATEGY_REGISTRY
├── portfolio_backtest_repository_interface.py 【新】IPortfolioBacktestRepository(ABC)
└── (base.py / models.py / portfolio_backtester.py 不动)

infra/database/strategy/                       【新】strategy 域持久化子包
├── __init__.py
├── models.py                                  # PortfolioBacktestResult(SQLModel, table=True)
└── repository.py                              # PortfolioBacktestRepository + create_portfolio_backtest_repository()

api/router/lt_backtest_router.py               # 新增 results/history/compare/frontier 端点；backtest 自动落库
api/handler/perm_portfolio_handler.py          # backtest 端点加可选 save 落库

frontend/apps/web/src/pages/
├── LongTermBacktest.tsx                       # 新增"回测历史/对比"视图
└── EfficientFrontier.tsx（或集成进 LongTermBacktest）  # 有效前沿可视化
```

**层依赖校验**：

- `domain/.../optimization/*` —— 仅 import numpy/scipy、`base.py`、`models.py`、`sync_provider.OHLCVBar`。✅ 禁止 import infra/conf/api。
- `domain/.../portfolio_backtest_repository_interface.py` —— 仅 `abc`。✅
- `infra/database/strategy/*` —— import domain 接口 + `conf` + sqlmodel。✅ 禁止 import api。
- `api/router/lt_backtest_router.py` —— import domain/infra。✅

---

## 4. 数据模型

### 4.1 新表 `portfolio_backtest_result`

SQLModel（`infra/database/strategy/models.py`），由 `create_all` 自动建表。指标列冗余存储以支持列表筛选/排序，完整结果以 JSONB 快照存储（不可变历史记录，与现有 `backtest_results` 惯例一致）。

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | int PK 自增 | |
| `name` | str, indexed | 用户命名，默认自动生成（如"风险平价 2020-2025"） |
| `source` | str, indexed | `lt_backtest` / `perm_portfolio` / `optimizer` |
| `strategy` | str, indexed | 策略名（`risk_parity` 等） |
| `symbols` | JSON (TEXT) | 投资宇宙 |
| `params` | JSON | 策略参数 + 回测配置（initial_capital/rebalance_freq/lookback/commission/slippage/benchmark） |
| `benchmark` | str | 基准代码 |
| `start_date` | str | |
| `end_date` | str | |
| `status` | str, indexed | `running` / `completed` / `failed` |
| `initial_capital` | float | |
| `final_equity` | float | |
| `total_return_pct` | float, indexed | 冗余指标，支持列表筛选排序 |
| `cagr` | float | |
| `sharpe_ratio` | float, indexed | |
| `sortino_ratio` | float | |
| `max_drawdown` | float | |
| `max_dd_duration` | int | |
| `volatility` | float | |
| `win_rate` | float | |
| `rebalance_count` | int | |
| `total_trades` | int | |
| `benchmark_return_pct` | float | |
| `benchmark_cagr` | float | |
| `alpha` | float | |
| `beta` | float | |
| `equity_curve` | JSON | `[{date, equity, benchmark}]` 完整权益曲线 |
| `rebalances` | JSON | 调仓事件列表 |
| `trades` | JSON | 交易明细列表 |
| `final_weights` | JSON | 期末目标权重 `{symbol: weight}` |
| `portfolio_id` | int, nullable | 源自 perm-portfolio 时关联 |
| `error_msg` | str, nullable | status=failed 时原因 |
| `created_at` | datetime, indexed | 默认 now |
| `updated_at` | datetime | |

**为什么不建明细表**：回测结果是**不可变快照**（生成后不再逐点更新），与 perm-portfolio 的**实时 NAV 明细**（每日追加、需查询）性质不同。JSONB 快照匹配现有 `backtest_results` 惯例，实现简单、读取一次到位。规模可控（权益曲线约 250 点/年 × 5 年 ≈ 1250 点；交易数十笔）。

### 4.2 仓储接口

`domain/market/strategy/portfolio_backtest_repository_interface.py`：

```python
class IPortfolioBacktestRepository(ABC):
    @abstractmethod
    def save(self, record: PortfolioBacktestRecord) -> int: ...
    @abstractmethod
    def get(self, result_id: int) -> Optional[PortfolioBacktestRecord]: ...
    @abstractmethod
    def list_results(
        self, *, strategy: str = None, source: str = None,
        start: str = None, end: str = None, page: int = 1, size: int = 20,
    ) -> tuple[list[PortfolioBacktestRecord], int]: ...
    @abstractmethod
    def get_many(self, ids: list[int]) -> list[PortfolioBacktestRecord]: ...
    @abstractmethod
    def delete(self, result_id: int) -> bool: ...
    @abstractmethod
    def update_status(self, result_id: int, status: str, error_msg: str = None) -> None: ...
```

`PortfolioBacktestRecord` 是 domain 层的 dataclass（在接口文件或 models.py 定义），承载 `LongTermResult` 指标 + 元数据，与 SQLModel 表模型解耦（表模型在 infra 层）。

### 4.3 仓储实现

`infra/database/strategy/repository.py`：

- `PortfolioBacktestRepository(IPortfolioBacktestRepository)` —— SQLModel session 读写。
- `create_portfolio_backtest_repository()` 工厂（单例，照搬 `portfolio/repository.py` 模式）。
- `save`：record → SQLModel 行，`session.add` + commit，返回 id。
- `list_results`：分页 + 过滤，**只 select 摘要列**（不拉 JSONB），按 `created_at desc`。
- `get` / `get_many`：含完整 JSONB。

---

## 5. API 设计

所有新端点挂在现有 `/lt-backtest`（prefix `/api/v1/lt-backtest`），避免新增第 5 个回测 router 造成碎片化。

### 5.1 端点清单

| 方法 | 路径 | 功能 | 请求 | 响应 data |
|---|---|---|---|---|
| POST | `/lt-backtest/backtest` | （既有，增强）跑回测 + **自动落库** | `LTBacktestRequest`（加 `name?: str`, `save?: bool=true`） | 既有结果 + `result_id` |
| GET | `/lt-backtest/results` | 【新】历史列表（分页+筛选） | query: strategy/source/start/end/page/size | `{records:[摘要], total, page, size}` |
| GET | `/lt-backtest/results/{id}` | 【新】单次详情 | — | 完整结果（含 equity_curve/trades） |
| POST | `/lt-backtest/compare` | 【新】多次回测对比 | `{ids: [int]}` | `{runs:[完整结果], metrics_table:[...], equity_overlay:[...]}` |
| DELETE | `/lt-backtest/results/{id}` | 【新】删除 | — | `{deleted: bool}` |
| POST | `/lt-backtest/efficient-frontier` | 【新】有效前沿资产配置工具 | `{symbols, lookback=120, end_date?, benchmark?}` | `{frontier:[{risk,return,sharpe,weights}], min_variance:{...}, max_sharpe:{...}}` |

### 5.2 统一响应

遵循 `{"code": 0, "msg": "ok", "data": {...}}`。分页用 `page_success` 风格。

### 5.3 落库接入（最小侵入）

`lt_backtest_router.py:run_lt_backtest`：在 `result = bt.run(...)` 之后、return 之前，插入：

```python
if req.save:
    repo = create_portfolio_backtest_repository()
    record = build_record_from_result(
        result, source="lt_backtest", strategy=req.strategy,
        name=req.name, params=req.model_dump(), benchmark=req.benchmark,
    )
    result_id = repo.save(record)
    data = result.to_dict(); data["result_id"] = result_id
    return ok(data)
```

`perm_portfolio_handler.py:backtest_portfolio`：加可选 `save: bool = False`（默认关，避免改动既有 perm 行为），为 True 时同样落库（`source="perm_portfolio"`，带 `portfolio_id`）。

### 5.4 有效前沿端点

`POST /lt-backtest/efficient-frontier` —— 纯计算，不跑回测：

1. 拉各标的日线（复用 `_fetch_daily_from_db`）。
2. 取末尾 `lookback` 根收盘 → 价格矩阵 → 日收益率 → 协方差 + 年化预期收益。
3. `optimization/mvo.efficient_frontier()` 沿前沿采样 N 个目标收益，逐点解最小方差 → 风险/收益/夏普/权重。
4. 标注最小方差点、最大夏普点。
5. 返回供前端散点图绘制。

---

## 6. 优化策略设计

### 6.1 协方差估计（`optimization/covariance.py`，纯函数）

```python
def price_matrix(bars_by_symbol, lookback, today) -> tuple[list[str], np.ndarray]:
    """取各标的末尾 lookback 根收盘 → (symbols, T×N 价格矩阵)。剔除历史不足的标的。"""

def daily_returns(prices: np.ndarray) -> np.ndarray:
    """价格矩阵 → 日收益率矩阵 (T-1)×N。"""

def covariance(returns: np.ndarray) -> np.ndarray:
    """样本协方差矩阵；奇异时用 Ledoit-Wolf 风格收缩到对角 → 确保正定可逆。"""

def expected_returns(returns: np.ndarray, annualize=True) -> np.ndarray:
    """均值历史收益率，年化。"""
```

数值守护：协方差奇异/非正定时，收缩 fallback（对角占优），避免求解器报错。

### 6.2 求解器（`optimization/solvers.py`）

```python
def solve_min_variance(cov, max_weight=0.4, cash_buffer=0.05) -> np.ndarray:
    """min  wᵀΣw  s.t. Σw = 1-cash_buffer, 0 ≤ wᵢ ≤ max_weight。SLSQP。"""

def solve_max_sharpe(mu, cov, rf=0.0, max_weight=0.4, cash_buffer=0.05) -> np.ndarray:
    """max  (wᵀμ - rf) / √(wᵀΣw)。SLSQP，等价 min -Sharpe。"""

def solve_risk_parity(cov, max_weight=0.4, cash_buffer=0.05) -> np.ndarray:
    """等风险贡献 ERC：各资产边际风险贡献相等。迭代法或 SLSQP min Σ(RCᵢ - RCⱼ)²。"""
```

scipy `optimize.minimize(method="SLSQP")` 处理约束（做多 w≥0、单标的上限、Σw=1-cash_buffer）。闭式最小方差（无约束 `w = Σ⁻¹1/(1ᵀΣ⁻¹1)`）作为无 scipy 时的退化路径，但默认走 SLSQP（约束更真实）。

### 6.3 四个策略类（各自文件，继承 `LongTermStrategy`）

每个实现 `on_rebalance(today, bars_by_symbol, ...) -> RebalanceSignal`：

1. `price_matrix` 取 lookback 窗口 → `covariance` →（MVO 额外 `expected_returns`）。
2. 调对应 `solve_*` → 权重向量。
3. 映射回 `{symbol: weight}`（与 price_matrix 返回的 symbols 对齐）。
4. 守护：可用标的 < 2 或求解失败 → 降级等权 + `reason` 标注。
5. 返回 `RebalanceSignal(target_weights, reason)`。

策略参数（`get_param_specs`）：

- 通用：`lookback`（默认 120）、`max_weight`（默认 0.4）、`cash_buffer`（默认 0.05）、`rebalance_freq`（默认 quarterly）。
- MVO：额外 `risk_free_rate`（默认 0.0）。

`meta()` 提供原理卡片（family="资产配置"），注册后自动出现在 `/lt-backtest/algorithms`。

### 6.4 注册

`strategies/__init__.py`：

```python
LONGTERM_STRATEGY_REGISTRY["risk_parity"] = RiskParityStrategy
LONGTERM_STRATEGY_REGISTRY["min_variance"] = MinVarianceStrategy
LONGTERM_STRATEGY_REGISTRY["mvo"] = MVOStrategy
LONGTERM_STRATEGY_REGISTRY["equal_weight"] = EqualWeightStrategy
```

（用 try/except 容错，与价值类策略一致，scipy 缺失时跳过优化类。）

---

## 7. 前端设计

### 7.1 回测历史 / 对比视图（`LongTermBacktest.tsx` 增强）

- 顶部加 Tab：「策略实验室」（既有）↔「回测历史」（新）。
- 「回测历史」：
  - 列表：调 `GET /lt-backtest/results`，表格列（name/strategy/source/区间/total_return/cagr/sharpe/max_drawdown/created_at）+ 筛选（strategy/source）+ 分页。
  - 详情：行点击 → 调 `GET /lt-backtest/results/{id}` → 复用既有结果展示（权益曲线 AreaChart + 指标卡 + 交易表）。
  - 对比：多选行 →「对比」按钮 → 调 `POST /lt-backtest/compare` → 叠加权益曲线（多色 LineChart）+ 指标对比表（每行一个 run，每列一个指标）。
  - 删除：行内删除（确认）→ `DELETE`。
- 跑完一次回测（既有「策略实验室」）后，提示「已保存到历史，result_id=N」，并提供跳转。

### 7.2 有效前沿可视化

- 「策略实验室」内加「有效前沿」入口（选 symbols + lookback）→ 调 `POST /lt-backtest/efficient-frontier`。
- recharts ScatterChart：x=年化波动率，y=年化收益，前沿曲线 + 标注最小方差点/最大夏普点；点击点展示该点权重饼图。

### 7.3 新策略自动可用

风险平价/最小方差/MVO/等权 注册后，`GET /lt-backtest/algorithms` 自动返回其原理卡片 → 既有算法选择器自动列出，无需额外前端改动（仅通用参数表单需支持新 ParamSpec）。

### 7.4 类型与 API client

- `frontend/apps/web/src/lib/` 或 `@ytrader/trading-strategy` 包内新增结果/对比/前沿的 TS 类型。
- API 调用遵循 `getApiBase()` + `json.code === 0` 约定。

---

## 8. 测试策略（TDD）

遵循 CLAUDE.md：测试目录镜像 `src/`，类名 `Test{Resource}`，方法 `test_{action}_{expected}`，DB 测试用 cursor fixture。

### 8.1 纯函数（domain/optimization，优先 TDD）

- `test_covariance_*`：合成已知相关性数据 → 验证协方差正定、奇异输入收缩 fallback 不报错。
- `test_solve_min_variance_*`：合成对角协方差 → 验证权重和=1-cash_buffer、各权重 ≤ max_weight、方差 ≤ 等权方差。
- `test_solve_max_sharpe_*`：合成已知切线组合数据 → 验证夏普最大、约束满足。
- `test_solve_risk_parity_*`：合成数据 → 验证各资产风险贡献近似相等。
- `test_efficient_frontier_*`：前沿点单调（风险随收益递增）、最小方差点方差最小。

### 8.2 策略集成

- `test_risk_parity_on_rebalance_*`：喂合成 `bars_by_symbol` → 返回 `RebalanceSignal`，权重和 ≤ 1、剔除缺数据标的。
- 历史不足降级：lookback 内标的 < 2 → 等权降级 + reason。

### 8.3 repository

- `test_save_get_*`：存取往返，JSONB 完整还原。
- `test_list_results_filter_*`：按 strategy/source/日期筛选 + 分页正确，列表不含重 JSONB。
- `test_delete_*`。

### 8.4 router 集成

- `test_backtest_persists_*`：POST /backtest → 返回 result_id → GET /results 能查到。
- `test_compare_*`：存 2 条 → POST /compare → 返回叠加曲线 + 指标表。
- `test_efficient_frontier_endpoint_*`：返回前沿点结构正确。

---

## 9. 依赖

- 新增 Python 依赖：`scipy`（加入 `backend/pyproject.toml` `[project.dependencies]`）。理由：约束优化（做多、权重上限、现金缓冲）需要 QP 能力的求解器；纯 numpy 实现约束 MVO 前沿笨拙且脆弱。项目已是重量级量化栈（numpy/pandas/akshare/sqlmodel…），加 scipy 合理。
- 前端无新依赖（recharts 已在）。

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 协方差数值不稳定（奇异/非正定） | 收缩/伪逆 fallback；策略层 try/except 降级等权 |
| scipy 未装时策略 import 失败 | try/except 注册（同价值类策略），降级为等权 + 前端标注不可用 |
| 历史 lookback 数据不足 | 策略守护：< lookback 剔除标的；可用标的 < 2 降级 |
| 落库 JSONB 体积 | 权益曲线/交易规模可控（千点级）；列表查询只 select 摘要列 |
| 改动既有 handler 引入回归 | 落库接入用 `if req.save` 开关包裹，默认行为可回退；既有端点契约只增不减 |

---

## 11. 实现顺序（供 writing-plans 细化）

1. **持久化层**：接口 → SQLModel 表模型 → repository 实现 + 工厂 → 单测。
2. **落库接入**：lt-backtest backtest 自动落库 + perm-portfolio 可选落库。
3. **结果管理端点**：results 列表/详情/对比/删除 → 单测/集成测。
4. **优化纯函数**：covariance → solvers → 单测（TDD）。
5. **4 个策略类**：注册 → `algorithm_metas` 验证 → on_rebalance 单测。
6. **有效前沿端点**：`efficient_frontier()` 工具 + router 端点 → 单测。
7. **前端**：回测历史/对比视图 → 有效前沿可视化 → 新策略参数表单适配。
8. **联调 + 端到端验证**。

每步可独立验证、独立提交。
