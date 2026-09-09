# RD-Agent 因子挖掘与模型优化系统

**项目**: YTrader 量化交易平台
**模块**: RD-Agent (Research & Development Agent)
**版本**: 1.0
**日期**: 2026-03-31
**状态**: 草稿

---

## 一、模块概述

RD-Agent 是 LLM 驱动的自主因子挖掘与模型优化系统，模拟量化研究员的研发流程，通过自动化的探索-评估-优化循环，持续发现新的 alpha 因子和优化交易模型。

核心价值：
- **自动化因子发现**：从原始数据中自动探索有效因子
- **模型超参数调优**：自动优化模型配置
- **持续迭代**：基于回测结果反馈持续改进

---

## 二、两大场景

### 2.1 Quant Factor Mining（因子挖掘）

从数据中自动发现有效信号，输出新的 alpha 因子表达式。

### 2.2 Quant Model Optimization（模型优化）

自动调整模型超参数和结构，提升预测性能。

---

## 三、核心循环架构

```
┌─────────────────────────────────────────────────────────┐
│                    RD-Agent Loop                         │
│                                                          │
│  ┌─────────┐    ┌──────────┐    ┌──────────┐          │
│  │ Explore  │ →  │  Train & │ →  │ Feedback │          │
│  │ (探索)   │    │  Evaluate│    │ (反馈)   │          │
│  │          │    │  (训练   │    │          │          │
│  │ 因子/    │    │   评估)  │    │ 分析结果 │          │
│  │ 模型空间 │    │          │    │ 指导优化 │          │
│  └─────────┘    └──────────┘    └────┬─────┘          │
│       ↑                               │                 │
│       └───────────────────────────────┘                 │
└─────────────────────────────────────────────────────────┘
```

---

## 四、因子挖掘 (Factor Mining)

### 4.1 因子空间

```python
class FactorSpace:
    """因子表达式空间定义"""

    OPERATORS = [
        "+", "-", "*", "/", "**",  # 算术
        "log", "log1p", "sqrt",   # 数学
        "abs", "sign",             # 一元
        "rank", "decay",           # 排名/衰减
        "ts_delta", "ts_sum",      # 时序
        "ts_max", "ts_min",        # 时序极值
        "ts_mean", "ts_std",       # 时序统计
        "corr", "cov",             # 相关性
        "regression",              # 回归
    ]

    BASE_FEATURES = [
        "open", "high", "low", "close", "volume",  # OHLCV
        "vwap", "turnover",                       # 价量
        "returns", "log_returns",                  # 收益
        "high_low_ratio", "close_open_ratio",      # 价比
    ]

    def generate_expression(self, depth: int = 3) -> str:
        """生成随机因子表达式"""
        if depth == 0:
            return random.choice(self.BASE_FEATURES)
        op = random.choice(self.OPERATORS)
        if op in ["+", "-", "*", "/", "**"]:
            left = self.generate_expression(depth - 1)
            right = self.generate_expression(depth - 1)
            return f"({left} {op} {right})"
        else:  # 单目运算符
            child = self.generate_expression(depth - 1)
            return f"{op}({child})"
```

### 4.2 因子评估

```python
class FactorEvaluator:
    """因子有效性评估"""

    def evaluate(self, factor_expr: str, dataset) -> dict:
        # 计算因子值
        factor_values = self.compute_factor(factor_expr, dataset)

        # 计算 IC (Information Coefficient)
        ic = self.calculate_ic(factor_values, dataset.returns)

        # 计算 IR (Information Ratio)
        ir = self.calculate_ir(factor_values, dataset.returns)

        # 计算因子衰减
        decay = self.calculate_decay(factor_values, dataset.returns)

        return {
            "expression": factor_expr,
            "ic": ic,
            "ir": ir,
            "decay": decay,
            "turnover": self.calculate_turnover(factor_values),
            "score": self.composite_score(ic, ir, decay)
        }

    def composite_score(self, ic: float, ir: float, decay: float) -> float:
        """综合评分：IC * IR * 衰减系数"""
        ic_weight = 0.4
        ir_weight = 0.4
        decay_weight = 0.2
        return ic * ic_weight + ir * ir_weight + decay * decay_weight
```

### 4.3 探索策略

```python
class FactorExplorer:
    """因子探索策略"""

    def __init__(self, llm_guided: bool = True):
        self.llm_guided = llm_guided

    async def suggest_mutations(
        self,
        top_factors: list[dict],
        market_context: str
    ) -> list[str]:
        """基于 LLM 引导的因子变异"""
        if not self.llm_guided:
            return self.random_mutations(top_factors)

        prompt = f"""给定以下表现最好的因子和市场环境，
        提出3-5个因子变异方向：

        Top Factors:
        {top_factors}

        Market Context:
        {market_context}

        变异方向应该：
        1. 保留有效部分
        2. 针对当前市场弱点进行改进
        3. 探索新的特征组合
        """
        response = await llm.complete(prompt)
        return parse_mutations(response)
```

---

## 五、模型优化 (Model Optimization)

### 5.1 支持的模型

与 Qlib Model Zoo 集成：

| 模型 | 类型 | 适用场景 |
|------|------|---------|
| `LGBModel` | GBDT | 表格数据、因子预测 |
| `XGBoostModel` | GBDT | 同上，偏好不同正则化 |
| `CatBoostModel` | GBDT | 类别特征处理 |
| `MLPModel` | 神经网络 | 非线性关系 |
| `LSTMModel` | 循环网络 | 时序依赖 |
| `GRUModel` | 循环网络 | 时序依赖（轻量） |
| `TransformerModel` | Attention | 复杂时序模式 |
| `TFTModel` | Attention | 可解释时序预测 |

### 5.2 超参数空间

```python
class HyperparamSpace:
    """超参数搜索空间"""

    SPACES = {
        "LGBModel": {
            "num_leaves": [31, 63, 127, 255],
            "learning_rate": [0.01, 0.05, 0.1, 0.2],
            "min_child_samples": [10, 20, 50, 100],
            "subsample": [0.6, 0.8, 1.0],
            "colsample_bytree": [0.6, 0.8, 1.0],
        },
        "MLPModel": {
            "hidden_dims": [[64], [128], [64, 32], [128, 64], [128, 64, 32]],
            "activation": ["relu", "tanh"],
            "dropout": [0.1, 0.3, 0.5],
            "learning_rate": [0.001, 0.0001],
        }
    }
```

### 5.3 优化策略

```python
class ModelOptimizer:
    """模型优化器"""

    def optimize(
        self,
        model_class: str,
        dataset,
        strategy: str = "bayesian"
    ) -> dict:
        if strategy == "bayesian":
            return self._bayesian_optimize(model_class, dataset)
        elif strategy == "genetic":
            return self._genetic_optimize(model_class, dataset)
        elif strategy == "grid":
            return self._grid_search(model_class, dataset)

    def _bayesian_optimize(
        self,
        model_class: str,
        dataset
    ) -> dict:
        """贝叶斯优化：高效探索超参数空间"""
        space = HyperparamSpace.SPACES[model_class]
        best_score = -inf
        best_params = None

        # Warm start: 先评估随机采样点
        initial_points = sample_random(space, n=5)
        for params in initial_points:
            score = self._evaluate(model_class, params, dataset)
            if score > best_score:
                best_score = score
                best_params = params

        # 贝叶斯优化迭代
        for _ in range(20):
            # 获取最优采集函数的新点
            candidate = suggest_next_candidate(space, evaluated_points)
            score = self._evaluate(model_class, candidate, dataset)

            if score > best_score:
                best_score = score
                best_params = candidate

        return {"best_params": best_params, "best_score": best_score}
```

---

## 六、与 Qlib 集成

### 6.1 Alpha158 因子库

使用 Qlib 的 Alpha158 因子集作为基础特征：

```python
from qlib.contrib.data.handler import Alpha158

class QlibAlpha158Dataset:
    def __init__(self, market: str = "csi300"):
        self.handler = Alpha158(
            instruments=market,
            start_time="2008-01-01",
            end_time="2024-12-31",
            fit_start_time="2008-01-01",
            fit_end_time="2010-12-31"
        )

    def get_feature_config(self) -> dict:
        """Alpha158 因子配置"""
        return {
            "kbar": {},  # K线基础
            "price": {
                "windows": [0, 1, 2, 3, 4, 5, 10, 20, 30, 60],
                "feature": ["OPEN", "HIGH", "LOW", "VWAP"]
            },
            "rolling": {
                "windows": [5, 10, 20, 30, 60],
                "feature": ["MEAN", "STD", "SUM"]
            }
        }
```

### 6.2 qrun 工作流

通过 YAML 配置自动化研究流程：

```yaml
# workflow_rd_agent.yaml
qlib_init:
    provider_uri: "~/.qlib/qlib_data/cn_data"
    region: cn

market: csi300

task:
    model:
        class: LGBModel
        module_path: qlib.contrib.model.gbdt
        kwargs:
            loss: mse
            learning_rate: 0.05
            num_leaves: 127

    dataset:
        class: DatasetH
        module_path: qlib.data.dataset
        kwargs:
            handler:
                class: Alpha158
                module_path: qlib.contrib.data.handler
            segments:
                train: [2008-01-01, 2014-12-31]
                valid: [2015-01-01, 2016-12-31]
                test: [2017-01-01, 2020-08-01]

    rd_agent:
        enabled: true
        scenario: "factor_mining"  # factor_mining | model_optimization
        exploration_depth: 3
        top_k: 10
        min_ic_threshold: 0.02
```

---

## 七、API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `POST /rdagent/factor/mine` | POST | 启动因子挖掘任务 |
| `GET /rdagent/factor/top` | GET | 获取 top 因子列表 |
| `POST /rdagent/model/optimize` | POST | 启动模型优化任务 |
| `GET /rdagent/model/best` | GET | 获取最佳模型配置 |
| `GET /rdagent/experiment/{id}` | GET | 获取实验详情 |
| `POST /rdagent/workflow/run` | POST | 运行完整 qrun 工作流 |

---

## 八、核心组件

| 组件 | 职责 |
|------|------|
| `FactorSpace` | 因子表达式空间定义和生成 |
| `FactorEvaluator` | 因子 IC/IR/衰减评估 |
| `FactorExplorer` | LLM 引导的因子变异探索 |
| `ModelOptimizer` | 贝叶斯/遗传/网格超参搜索 |
| `QlibIntegrator` | Qlib Alpha158 和 Model Zoo 集成 |
| `WorkflowRunner` | qrun YAML 工作流执行 |

---

**文档版本**: 1.0
**最后更新**: 2026-03-31
