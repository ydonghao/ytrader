"""组合回测结果仓储接口（domain 层，仅依赖 abc）。

遵循项目 Repository Pattern（参考 domain/market/intel/repository_interface.py）：
接口在 domain，实现在 infra。application/api 只 import 接口 + 工厂函数。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class PortfolioBacktestRecord:
    """一次组合回测的完整记录（domain 层 DTO，与 SQLModel 表模型解耦）。

    指标字段对应 LongTermResult；snapshots 存完整结果快照（不可变）。
    用 from_result() 从 LongTermResult 构造。
    """

    # ── 元数据 ──
    name: str = ""
    source: str = "lt_backtest"      # lt_backtest | perm_portfolio | optimizer
    strategy: str = ""
    symbols: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    benchmark: str = ""
    start_date: str = ""
    end_date: str = ""
    status: str = "completed"        # running | completed | failed
    portfolio_id: Optional[int] = None
    error_msg: Optional[str] = None
    created_at: Optional[datetime] = None
    id: Optional[int] = None

    # ── 指标（冗余，便于列表筛选/排序）──
    initial_capital: float = 0.0
    final_equity: float = 0.0
    total_return_pct: float = 0.0
    cagr: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_dd_duration: int = 0
    volatility: float = 0.0
    win_rate: float = 0.0
    rebalance_count: int = 0
    total_trades: int = 0
    benchmark_return_pct: float = 0.0
    benchmark_cagr: float = 0.0
    alpha: float = 0.0
    beta: float = 0.0

    # ── 完整结果快照 ──
    equity_curve: list = field(default_factory=list)
    rebalances: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    final_weights: dict = field(default_factory=dict)

    @classmethod
    def from_result(
        cls,
        result: Any,
        *,
        source: str = "lt_backtest",
        strategy: str = "",
        name: str = "",
        params: Optional[dict] = None,
        benchmark: str = "",
        portfolio_id: Optional[int] = None,
    ) -> "PortfolioBacktestRecord":
        """从 LongTermResult 构造记录。

        result 需有 to_dict() 或等效属性（LongTermResult 已满足）。
        """
        if hasattr(result, "to_dict"):
            d = result.to_dict()
        elif isinstance(result, dict):
            d = result
        else:
            d = {}

        # 期末目标权重：从最后一次 rebalance 取，或 trades 推断
        final_weights = {}
        rebalances = d.get("rebalances") or []
        if rebalances and isinstance(rebalances[-1], dict):
            final_weights = rebalances[-1].get("target_weights", {}) or {}

        rec = cls(
            name=name or f"{strategy or d.get('strategy', 'backtest')} "
                 f"{d.get('start_date', '')}→{d.get('end_date', '')}",
            source=source,
            strategy=strategy or d.get("strategy", ""),
            symbols=list(d.get("symbols", [])),
            params=params or {},
            benchmark=benchmark,
            start_date=str(d.get("start_date", "")),
            end_date=str(d.get("end_date", "")),
            status="completed",
            portfolio_id=portfolio_id,
            initial_capital=float(d.get("initial_capital", 0) or 0),
            final_equity=float(d.get("final_equity", 0) or 0),
            total_return_pct=float(d.get("total_return_pct", 0) or 0),
            cagr=float(d.get("cagr", 0) or 0),
            sharpe_ratio=float(d.get("sharpe_ratio", 0) or 0),
            sortino_ratio=float(d.get("sortino_ratio", 0) or 0),
            max_drawdown=float(d.get("max_drawdown", 0) or 0),
            max_dd_duration=int(d.get("max_dd_duration", 0) or 0),
            volatility=float(d.get("volatility", 0) or 0),
            win_rate=float(d.get("win_rate", 0) or 0),
            rebalance_count=int(d.get("rebalance_count", 0) or 0),
            total_trades=int(d.get("total_trades", 0) or 0),
            benchmark_return_pct=float(
                d.get("benchmark_return_pct", 0) or 0
            ),
            benchmark_cagr=float(d.get("benchmark_cagr", 0) or 0),
            alpha=float(d.get("alpha", 0) or 0),
            beta=float(d.get("beta", 0) or 0),
            equity_curve=list(d.get("equity_curve", [])),
            rebalances=rebalances,
            trades=list(d.get("trades", [])),
            final_weights=final_weights,
        )
        return rec

    def summary(self) -> dict:
        """列表用摘要（不含重 JSONB）。"""
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "strategy": self.strategy,
            "symbols": self.symbols,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total_return_pct": round(self.total_return_pct, 2),
            "cagr": round(self.cagr, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "max_drawdown": round(self.max_drawdown, 2),
            "volatility": round(self.volatility, 2),
            "alpha": round(self.alpha, 4),
            "beta": round(self.beta, 4),
            "benchmark_return_pct": round(self.benchmark_return_pct, 2),
            "status": self.status,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }

    def full(self) -> dict:
        """详情用完整字典（含 equity_curve/trades）。"""
        s = self.summary()
        s.update({
            "params": self.params,
            "benchmark": self.benchmark,
            "initial_capital": round(self.initial_capital, 2),
            "final_equity": round(self.final_equity, 2),
            "sortino_ratio": round(self.sortino_ratio, 3),
            "max_dd_duration": self.max_dd_duration,
            "win_rate": round(self.win_rate, 2),
            "rebalance_count": self.rebalance_count,
            "total_trades": self.total_trades,
            "benchmark_cagr": round(self.benchmark_cagr, 2),
            "equity_curve": self.equity_curve,
            "rebalances": self.rebalances,
            "trades": self.trades,
            "final_weights": self.final_weights,
            "portfolio_id": self.portfolio_id,
        })
        return s


class IPortfolioBacktestRepository(ABC):
    """组合回测结果仓储接口。"""

    @abstractmethod
    def save(self, record: PortfolioBacktestRecord) -> int:
        """持久化一条记录，返回 id。"""
        ...

    @abstractmethod
    def get(self, result_id: int) -> Optional[PortfolioBacktestRecord]:
        ...

    @abstractmethod
    def get_many(
        self, ids: list[int]
    ) -> list[PortfolioBacktestRecord]:
        ...

    @abstractmethod
    def list_results(
        self,
        *,
        strategy: Optional[str] = None,
        source: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[PortfolioBacktestRecord], int]:
        """分页列表（带筛选），返回 (records, total)。"""
        ...

    @abstractmethod
    def delete(self, result_id: int) -> bool:
        ...

    @abstractmethod
    def update_status(
        self, result_id: int, status: str,
        error_msg: Optional[str] = None,
    ) -> None:
        ...
