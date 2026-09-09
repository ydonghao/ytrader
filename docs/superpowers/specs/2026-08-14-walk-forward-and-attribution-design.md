# 组合回测增强阶段 3+4：Walk-Forward + 归因分析

- 日期：2026-08-14
- 状态：已设计，待实现
- 关联：`2026-08-14-portfolio-backtest-enhancement-design.md`（阶段 1+2）
- 范围：在阶段 1+2（持久化 + 优化策略 + 有效前沿）基础上，新增③滚动 walk-forward + 过拟合检测；④回测收益归因分析。

---

## 1. 背景与动机

阶段 1+2 让用户能用现代组合策略跑回测、存历史、对比、看有效前沿。但两个关键问题仍未回答：

1. **"我的策略是不是过拟合了？"** —— 阶段 1+2 的 `LongTermGridOptimizer` 在**全样本**上寻优，最优参数很可能是事后诸葛亮。需要 walk-forward（样本内训练、样本外验证）来检验参数在未见数据上是否稳健。
2. **"收益到底从哪来？"** —— 阶段 1+2 只给组合层面的总收益/夏普，看不到是哪个标的/哪类资产贡献的。现有 `/portfolio/attribution` 是**单日实时持仓**归因，不适用于回测时序结果。

本 spec 解决这两个缺口。

### 1.1 复用资产

| 资产 | 位置 | 复用方式 |
|---|---|---|
| `LongTermGridOptimizer` | `longterm/optimizer.py` | walk-forward 每窗口的训练段调它寻优 |
| `PortfolioBacktester` | `longterm/portfolio_backtester.py` | OOS 段回测 + 归因用其 rebalance 权重 |
| `metrics.py` | `longterm/metrics.py` | 权益曲线指标（已校验） |
| `classify_sector` | `portfolio_router.py` | 归因按行业聚合 |
| `PortfolioBacktestRepository` | `infra/database/strategy/` | walk-forward 结果落库（`source='optimizer'`） |
| `LongTermResult.rebalances` | `longterm/models.py` | 归因的权重路径来源（target_weights 时序） |

---

## 2. 范围边界

**做**：
1. Walk-forward 滚动窗口寻优 + OOS 拼接 + 过拟合度量。
2. 回测结果逐标的收益贡献分解 + 行业聚合 + vs 等权基准的配置/选择效应。
3. 两个新端点 + 前端视图。

**不做（YAGNI）**：
- 不做分钟级 walk-forward（日线策略，日线粒度足够）。
- 不做多因子归因（Fama-French 式，需因子数据，项目无因子库）——只做 Brinson 风格的权重/标的选择分解。
- 不重写既有 `LongTermGridOptimizer`（walk-forward 复用它，不改其行为）。
- 不改 `PortfolioBacktester` 输出（归因用 rebalance target_weights 近似，不注入逐日持仓）。

---

## 3. 阶段 3：Walk-Forward + 过拟合检测

### 3.1 引擎设计（`longterm/walk_forward.py`）

```python
@dataclass
class WalkForwardConfig:
    train_days: int = 504        # 训练段交易日（约 2 年）
    test_days: int = 126         # 测试段交易日（约 0.5 年）
    step_days: int = 126         # 滑动步长（= test_days 即不重叠）
    metric: str = "sharpe_ratio" # 训练段寻优指标
    param_grid: dict | None = None  # None = 从 ParamSpec 自动派生

@dataclass
class WalkForwardResult:
    windows: list[WindowResult]  # 每窗口 IS/OOS 指标 + 最优参数
    oos_equity_curve: list[dict] # 拼接的 OOS 权益曲线（归一化）
    aggregated: dict             # OOS 聚合 cagr/sharpe/max_drawdown
    overfitting: dict            # 过拟合度量
    n_windows: int
```

**算法**：
1. 把所有标的对齐到公共交易日序列 `dates`（复用 `optimization/covariance.py` 的对齐思路）。
2. 滑动：`for i in range(0, len(dates) - train - test + 1, step)`：
   - 训练段 `dates[i:i+train]` → 切片 bars → `LongTermGridOptimizer.optimize()` → `best_params` + IS 指标。
   - 测试段 `dates[i+train:i+train+test]` → 用 `best_params` 跑 `PortfolioBacktester.run()` → OOS 结果。
   - 记录窗口：{train/test 区间, best_params, is_sharpe, oos_sharpe, oos_cagr, oos_max_dd}。
3. 拼接 OOS 权益曲线：每段 OOS 的 equity 序列首尾相接（每段以 1.0 重定位再拼接）。
4. 聚合 OOS 指标：对拼接曲线算 cagr/sharpe/max_drawdown。
5. 过拟合度量：
   - `walk_forward_efficiency = median(oos_sharpe) / max(median(is_sharpe), ε)`：>0.5 尚可，>0.7 好，<0.3 偏过拟合。
   - `param_stability = distinct(best_params) / n_windows`：越低越稳定（1.0=每窗口参数都变=过拟合风险高）。
   - `oos_positive_ratio`：OOS 夏普为正的窗口占比。

### 3.2 端点

`POST /lt-backtest/walk-forward`，请求体 = `LTBacktestRequest` 扩展 + walk-forward 配置：

```json
{
  "strategy": "dual_momentum",
  "symbols": ["sh510300","sh511010"],
  "benchmark": "sh510300",
  "start_date": "...", "end_date": "...",
  "initial_capital": 1000000,
  "param_grid": null,
  "train_days": 504, "test_days": 126, "step_days": 126,
  "metric": "sharpe_ratio",
  "save": true, "name": "DM walk-forward"
}
```

返回 walk-forward 结果。`save=true` 时把聚合 OOS 曲线作为一条回测落库（`source='optimizer'`, `strategy='{name}_walkforward'`），供历史对比。

### 3.3 数值守护
- 窗口数 < 2 → 返回提示（数据不足以 walk-forward）。
- 训练段网格寻优失败/某窗口无有效组合 → 跳过该窗口，`skipped` 计数。
- OOS 段数据不足 → 跳过。

---

## 4. 阶段 4：回测收益归因分析

### 4.1 模块设计（`longterm/attribution.py`）

```python
@dataclass
class BacktestAttribution:
    total_return_pct: float
    by_symbol: list[SymbolContribution]   # 逐标的贡献
    by_sector: list[SectorContribution]   # 行业聚合
    vs_equal_weight: dict                  # 配置/选择效应
```

**算法（逐标的贡献分解）**：
1. 输入：`LongTermResult`（含 rebalances 时序 target_weights）+ bars_by_symbol（各标的价格历史）。
2. 构建权重路径：rebalances 按 date 排序，相邻 rebalance 间用前一个 target_weights（分段常数近似）。
3. 逐标的、逐段计算贡献：`contribution(symbol) = avg_weight(symbol) × period_return(symbol)`。
   - `avg_weight`：该标的在各 rebalance 段的平均目标权重。
   - `period_return`：该标的在整段的收益率（首末收盘价）。
4. `total_attributed = Σ contribution`，与 `total_return_pct` 对比给残差（权重漂移/再平衡/成本导致）。
5. 行业聚合：复用 `classify_sector`，按 sector 汇总贡献 + 权重。
6. vs 等权基准：
   - 等权基准收益 = mean(各标的 period_return)。
   - `allocation_effect`：策略相对等权的**权重配置**带来的超额（用策略权重 vs 等权 × 各标的收益）。
   - `selection_effect`：残差（策略选的标的相对等权组合的超额）。

### 4.2 端点

`POST /lt-backtest/results/{id}/attribution` —— 取已持久化的回测结果做归因（需重新拉各标的价格历史算 period_return）。

也支持 `POST /lt-backtest/attribution` 直接传一个回测结果 + symbols（用于刚跑完未落库的结果）。

返回：逐标的贡献表 + 行业聚合 + 配置/选择效应 + top 贡献/拖累。

### 4.3 近似说明
归因基于 **rebalance target_weights（分段常数）**，不重建逐日漂移持仓。对季度再平衡，分段常数是合理近似；文档与 UI 明确标注"基于调仓目标权重的归因"。

---

## 5. 前端

- **Walk-forward**：`EfficientFrontier.tsx` 同级新增 `WalkForward.tsx`（或并入实验室 Tab 的扩展）。配置 train/test/step + 参数网格 → 展示：每窗口 IS/OOS 指标表、拼接 OOS 权益曲线、过拟合度量卡（WFE/参数稳定性/正收益窗口比）。
- **归因**：回测详情面板（`BacktestHistory.tsx` 的 detail）内加"收益归因"区——逐标的贡献条形图 + 行业饼图 + 配置/选择效应。

均复用 recharts + 既有暗色样式。

---

## 6. 测试（TDD）

- `test_walk_forward.py`：合成数据验证窗口切分正确、OOS 拼接连续、过拟合度量计算、窗口不足守护。
- `test_attribution.py`：合成已知权重+收益 → 验证贡献求和≈总收益、行业聚合、配置/选择效应符号正确。
- 端点集成：walk-forward 端点返回结构；归因端点对已存结果返回贡献表。

---

## 7. 实现顺序

1. walk_forward.py 引擎 + 单测（纯函数，TDD）。
2. walk-forward 端点 + 持久化。
3. attribution.py + 单测。
4. 归因端点。
5. 前端两视图。
6. 端到端验证 + 全量测试 + 提交。
