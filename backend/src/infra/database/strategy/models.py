"""组合回测结果 SQLModel 表定义。

portfolio_backtest_result: 一次组合回测的完整记录。
指标列冗余存储以支持列表筛选/排序；equity_curve/trades 等以 JSONB 快照存储。

通过 create_all 自动建表（需在 main.py 启动时 import 本模块）。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class PortfolioBacktestResult(SQLModel, table=True):
    """组合回测结果表。"""

    __tablename__ = "portfolio_backtest_result"

    # ── 元数据 ──
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(default="", index=True)
    source: str = Field(default="lt_backtest", index=True)
    strategy: str = Field(default="", index=True)
    symbols: Optional[list] = Field(default=None, sa_column=Column(JSONB))
    params: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    benchmark: str = Field(default="")
    start_date: str = Field(default="")
    end_date: str = Field(default="")
    status: str = Field(default="completed", index=True)
    portfolio_id: Optional[int] = Field(default=None)
    error_msg: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    updated_at: datetime = Field(default_factory=datetime.now)

    # ── 指标（冗余，列表筛选/排序）──
    initial_capital: float = Field(default=0.0)
    final_equity: float = Field(default=0.0)
    total_return_pct: float = Field(default=0.0, index=True)
    cagr: float = Field(default=0.0)
    sharpe_ratio: float = Field(default=0.0, index=True)
    sortino_ratio: float = Field(default=0.0)
    max_drawdown: float = Field(default=0.0)
    max_dd_duration: int = Field(default=0)
    volatility: float = Field(default=0.0)
    win_rate: float = Field(default=0.0)
    rebalance_count: int = Field(default=0)
    total_trades: int = Field(default=0)
    benchmark_return_pct: float = Field(default=0.0)
    benchmark_cagr: float = Field(default=0.0)
    alpha: float = Field(default=0.0)
    beta: float = Field(default=0.0)

    # ── 完整结果快照（JSONB）──
    equity_curve: Optional[list] = Field(default=None, sa_column=Column(JSONB))
    rebalances: Optional[list] = Field(default=None, sa_column=Column(JSONB))
    trades: Optional[list] = Field(default=None, sa_column=Column(JSONB))
    final_weights: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
