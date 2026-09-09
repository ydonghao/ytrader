"""
长期策略参数寻优器（LongTermGridOptimizer）
============================================
网格搜索：对策略的参数空间做笛卡尔积展开，每个组合跑一次组合回测，
按指定指标（夏普/年化/回撤等）排序，返回最优组合 + 对比表。

与老 optimizer.py（服务 Backtester）平级，专门服务 PortfolioBacktester。

关键设计：
  - 数据预加载一次，每个参数组合复用（不重复拉数据）
  - n_jobs=1（纯 Python 引擎，GIL 下多线程无收益，且数据拷贝开销大）
  - param_grid 为空时从 ParamSpec 自动派生（每参数取 3-5 个点）
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from typing import Optional

from ...sync.sync_provider import OHLCVBar
from .base import LongTermStrategy, ParamSpec
from .models import LongTermResult
from .portfolio_backtester import PortfolioBacktester
from .strategies import build_strategy

log = logging.getLogger(__name__)

# 支持的寻优指标（必须是 LongTermResult 的字段）
SUPPORTED_METRICS = (
    "sharpe_ratio", "cagr", "total_return_pct",
    "sortino_ratio", "max_drawdown", "alpha",
)


@dataclass
class OptimizeCombo:
    """单个参数组合的寻优结果摘要。"""
    params: dict
    sharpe_ratio: float
    cagr: float
    total_return_pct: float
    max_drawdown: float
    sortino_ratio: float
    alpha: float

    def to_dict(self) -> dict:
        return {
            "params": self.params,
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "cagr": round(self.cagr, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "sortino_ratio": round(self.sortino_ratio, 3),
            "alpha": round(self.alpha, 4),
        }


@dataclass
class OptimizeResult:
    """寻优整体结果。"""
    strategy: str
    metric: str
    total_combos: int
    best_params: dict
    best: Optional[LongTermResult]            # 最优组合的完整回测结果
    comparison: list[OptimizeCombo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "metric": self.metric,
            "total_combos": self.total_combos,
            "best_params": self.best_params,
            "best": self.best.to_dict() if self.best else None,
            "comparison": [c.to_dict() for c in self.comparison],
        }


class LongTermGridOptimizer:
    """
    长期策略网格寻优器。

    Args:
        strategy_name:    策略名（dual_momentum/magic_formula/...）
        param_grid:       参数网格 {param: [val1, val2, ...}；为空时自动从 ParamSpec 派生
        metric:           排序指标（sharpe_ratio/cagr/total_return_pct/...）
        top_k:            返回对比表前 K 个组合
        backtester_kwargs: 传给 PortfolioBacktester 的参数（initial_capital 等）
    """

    def __init__(
        self,
        strategy_name: str,
        param_grid: Optional[dict[str, list]] = None,
        metric: str = "sharpe_ratio",
        top_k: int = 10,
        backtester_kwargs: Optional[dict] = None,
    ):
        if metric not in SUPPORTED_METRICS:
            raise ValueError(
                f"不支持的指标 '{metric}'，可用: {SUPPORTED_METRICS}"
            )
        self.strategy_name = strategy_name
        self.param_grid = param_grid or self._derive_grid(strategy_name)
        self.metric = metric
        self.top_k = top_k
        self.backtester_kwargs = backtester_kwargs or {}

    def optimize(
        self,
        bars_by_symbol: dict[str, list[OHLCVBar]],
        valuation_by_symbol: Optional[dict[str, list[dict]]] = None,
        financials_by_symbol: Optional[dict[str, list[dict]]] = None,
        benchmark_bars: Optional[list[OHLCVBar]] = None,
    ) -> OptimizeResult:
        """
        运行寻优。数据预加载一次，每个组合复用。

        Returns:
            OptimizeResult（含最优组合完整结果 + 对比表）
        """
        combos = self._expand_grid()
        if not combos:
            # 单组合（无参数可调）
            combos = [{}]

        log.info(
            "[寻优] %s metric=%s 组合数=%d",
            self.strategy_name, self.metric, len(combos),
        )

        bt = PortfolioBacktester(**self.backtester_kwargs)
        results: list[tuple[dict, LongTermResult]] = []

        for i, params in enumerate(combos):
            try:
                strategy = build_strategy(self.strategy_name, params)
                result = bt.run(
                    strategy=strategy,
                    bars_by_symbol=bars_by_symbol,
                    valuation_by_symbol=valuation_by_symbol,
                    financials_by_symbol=financials_by_symbol,
                    benchmark_bars=benchmark_bars,
                )
                results.append((params, result))
            except Exception as e:  # noqa: BLE001
                log.warning(f"[寻优] 组合 {params} 失败: {e}")
                continue

        if not results:
            return OptimizeResult(
                strategy=self.strategy_name, metric=self.metric,
                total_combos=0, best_params={}, best=None,
            )

        # 按 metric 排序（max_drawdown 越小越好，其他越大越好）
        reverse = self.metric != "max_drawdown"
        results.sort(
            key=lambda x: getattr(x[1], self.metric),
            reverse=reverse,
        )

        # 对比表（top_k）
        comparison: list[OptimizeCombo] = []
        for params, r in results[: self.top_k]:
            comparison.append(OptimizeCombo(
                params=params,
                sharpe_ratio=r.sharpe_ratio,
                cagr=r.cagr,
                total_return_pct=r.total_return_pct,
                max_drawdown=r.max_drawdown,
                sortino_ratio=r.sortino_ratio,
                alpha=r.alpha,
            ))

        best_params, best_result = results[0]
        log.info(
            "[寻优] 完成 最优 %s = %s (params=%s)",
            self.metric,
            getattr(best_result, self.metric),
            best_params,
        )

        return OptimizeResult(
            strategy=self.strategy_name,
            metric=self.metric,
            total_combos=len(results),
            best_params=best_params,
            best=best_result,
            comparison=comparison,
        )

    # ── 网格展开 ──────────────────────────────────────────────────────────
    def _expand_grid(self) -> list[dict]:
        """笛卡尔积展开参数网格。"""
        if not self.param_grid:
            return [{}]
        keys = list(self.param_grid.keys())
        value_lists = [self.param_grid[k] for k in keys]
        out: list[dict] = []
        for combo in itertools.product(*value_lists):
            out.append(dict(zip(keys, combo)))
        return out

    @staticmethod
    def _derive_grid(strategy_name: str) -> dict[str, list]:
        """
        从策略的 ParamSpec 自动派生参数网格。
        number 类型：取 min / 中间值 / max 三点（或按 step 取 3-5 个点）
        select 类型：用全部 options
        """
        try:
            strategy = build_strategy(strategy_name, {})
        except ValueError:
            return {}
        specs: list[ParamSpec] = strategy.get_param_specs()
        grid: dict[str, list] = {}
        for spec in specs:
            if spec.type == "select" and spec.options:
                grid[spec.key] = list(spec.options)
            elif spec.type == "number" and spec.min is not None and spec.max is not None:
                # 按 step 取 3-5 个点，限制总量
                vals = _frange(spec.min, spec.max, spec.step or 1.0, max_points=4)
                if vals:
                    grid[spec.key] = vals
        return grid


def _frange(lo: float, hi: float, step: float, max_points: int = 4) -> list:
    """生成 [lo, lo+step, ..., hi] 序列，限制点数。"""
    if lo >= hi or step <= 0:
        return [lo]
    out: list = []
    cur = lo
    while cur <= hi + 1e-9 and len(out) < max_points:
        # 整数参数保持整数
        out.append(int(cur) if step >= 1 and float(lo).is_integer() else round(cur, 4))
        cur += step
    return out if out else [lo]
