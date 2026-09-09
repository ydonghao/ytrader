"""
策略参数优化器
===============
网格搜索最优参数。
"""
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product
from typing import Callable, Optional

from .backtester import Backtester, BacktestResult
from .base import Strategy

log = logging.getLogger(__name__)


class GridOptimizer:
    """
    网格搜索参数优化器
    
    使用示例:
        optimizer = GridOptimizer(
            strategy_class=SMACrossStrategy,
            param_grid={
                "fast_period": [5, 10, 15],
                "slow_period": [20, 30, 60],
            },
            metric="sharpe_ratio",
        )
        best, all_results = optimizer.optimize(bars)
    """

    def __init__(
        self,
        strategy_class: type[Strategy],
        param_grid: dict[str, list],
        metric: str = "sharpe_ratio",
        n_jobs: int = 4,
        **backtester_kwargs,
    ):
        """
        Args:
            strategy_class: 策略类（非实例）
            param_grid: 参数网格，如 {"period": [5, 10], "threshold": [0.5, 0.6]}
            metric: 优化目标字段名（对应 BacktestResult 的字段）
            n_jobs: 并行数
            **backtester_kwargs: 传给 Backtester 的参数
        """
        self.strategy_class = strategy_class
        self.param_grid = param_grid
        self.metric = metric
        self.n_jobs = n_jobs
        self.backtester_kwargs = backtester_kwargs

    def optimize(
        self,
        bars_by_symbol: dict[str, list],
        start_date: str = "",
        end_date: str = "",
    ) -> tuple[BacktestResult, list[BacktestResult]]:
        """
        运行网格搜索
        
        Returns:
            (最优结果, 所有结果排序列表)
        """
        # 生成参数组合
        keys = list(self.param_grid.keys())
        values = list(self.param_grid.values())
        combos = list(product(*values))
        log.info(f"[GridOptimizer] 共 {len(combos)} 组参数 → {keys}")

        all_results: list[BacktestResult] = []

        if self.n_jobs == 1:
            for combo in combos:
                params = dict(zip(keys, combo))
                result = self._evaluate(params, bars_by_symbol, start_date, end_date)
                all_results.append(result)
        else:
            with ProcessPoolExecutor(max_workers=self.n_jobs) as executor:
                futures = {}
                for combo in combos:
                    params = dict(zip(keys, combo))
                    future = executor.submit(
                        self._evaluate, params, bars_by_symbol, start_date, end_date,
                    )
                    futures[future] = params

                for future in as_completed(futures):
                    try:
                        result = future.result()
                        all_results.append(result)
                    except Exception as e:
                        log.warning(f"[GridOptimizer] 参数组合 {futures[future]} 失败: {e}")

        # 排序
        all_results.sort(
            key=lambda r: getattr(r, self.metric, 0) or 0,
            reverse=True,
        )

        best = all_results[0] if all_results else None
        return best, all_results

    def _evaluate(
        self,
        params: dict,
        bars_by_symbol: dict[str, list],
        start_date: str,
        end_date: str,
    ) -> BacktestResult:
        """评估单组参数"""
        try:
            strategy = self.strategy_class(**params)
            bt = Backtester(**self.backtester_kwargs)
            result = bt.run_multi(strategy, bars_by_symbol, start_date, end_date)
            result.strategy_name = f"{strategy.name}({params})"
            return result
        except Exception as e:
            # 返回一个空结果表示失败
            log.warning(f"[GridOptimizer] 参数 {params} 评估失败: {e}")
            from dataclasses import dataclass
            @dataclass
            class FailedResult:
                strategy_name: str = str(params)
                total_return: float = -9999.0
                sharpe_ratio: float = -9999.0
            return FailedResult()
