"""组合回测结果 repository 实现。

遵循项目 Repository Pattern：工厂 + session_scope（参考 portfolio/repository.py）。
映射 PortfolioBacktestRecord(domain DTO) ↔ PortfolioBacktestResult(SQLModel)。
列表查询只 select 摘要列，不拉重 JSONB。
"""
import threading
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from src.domain.market.strategy.portfolio_backtest_repository_interface import (
    IPortfolioBacktestRepository,
    PortfolioBacktestRecord,
)
from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn

from .models import PortfolioBacktestResult

# 列表查询用摘要列（不含 equity_curve/rebalances/trades/final_weights）
_SUMMARY_COLS = (
    PortfolioBacktestResult.id,
    PortfolioBacktestResult.name,
    PortfolioBacktestResult.source,
    PortfolioBacktestResult.strategy,
    PortfolioBacktestResult.symbols,
    PortfolioBacktestResult.benchmark,
    PortfolioBacktestResult.start_date,
    PortfolioBacktestResult.end_date,
    PortfolioBacktestResult.status,
    PortfolioBacktestResult.portfolio_id,
    PortfolioBacktestResult.created_at,
    PortfolioBacktestResult.initial_capital,
    PortfolioBacktestResult.final_equity,
    PortfolioBacktestResult.total_return_pct,
    PortfolioBacktestResult.cagr,
    PortfolioBacktestResult.sharpe_ratio,
    PortfolioBacktestResult.sortino_ratio,
    PortfolioBacktestResult.max_drawdown,
    PortfolioBacktestResult.max_dd_duration,
    PortfolioBacktestResult.volatility,
    PortfolioBacktestResult.win_rate,
    PortfolioBacktestResult.rebalance_count,
    PortfolioBacktestResult.total_trades,
    PortfolioBacktestResult.benchmark_return_pct,
    PortfolioBacktestResult.benchmark_cagr,
    PortfolioBacktestResult.alpha,
    PortfolioBacktestResult.beta,
)


def _row_to_full_record(row: PortfolioBacktestResult) -> PortfolioBacktestRecord:
    """SQLModel 行 → 完整 record。"""
    return PortfolioBacktestRecord(
        id=row.id,
        name=row.name,
        source=row.source,
        strategy=row.strategy,
        symbols=row.symbols or [],
        params=row.params or {},
        benchmark=row.benchmark,
        start_date=row.start_date,
        end_date=row.end_date,
        status=row.status,
        portfolio_id=row.portfolio_id,
        error_msg=row.error_msg,
        created_at=row.created_at,
        initial_capital=row.initial_capital,
        final_equity=row.final_equity,
        total_return_pct=row.total_return_pct,
        cagr=row.cagr,
        sharpe_ratio=row.sharpe_ratio,
        sortino_ratio=row.sortino_ratio,
        max_drawdown=row.max_drawdown,
        max_dd_duration=row.max_dd_duration,
        volatility=row.volatility,
        win_rate=row.win_rate,
        rebalance_count=row.rebalance_count,
        total_trades=row.total_trades,
        benchmark_return_pct=row.benchmark_return_pct,
        benchmark_cagr=row.benchmark_cagr,
        alpha=row.alpha,
        beta=row.beta,
        equity_curve=row.equity_curve or [],
        rebalances=row.rebalances or [],
        trades=row.trades or [],
        final_weights=row.final_weights or {},
    )


def _summary_row_to_record(row) -> PortfolioBacktestRecord:
    """摘要行 → record（snapshots 为空，省 JSONB）。"""
    d = row._mapping if hasattr(row, "_mapping") else row
    return PortfolioBacktestRecord(
        id=d["id"],
        name=d["name"],
        source=d["source"],
        strategy=d["strategy"],
        symbols=d["symbols"] or [],
        benchmark=d["benchmark"],
        start_date=d["start_date"],
        end_date=d["end_date"],
        status=d["status"],
        portfolio_id=d["portfolio_id"],
        created_at=d["created_at"],
        initial_capital=d["initial_capital"],
        final_equity=d["final_equity"],
        total_return_pct=d["total_return_pct"],
        cagr=d["cagr"],
        sharpe_ratio=d["sharpe_ratio"],
        sortino_ratio=d["sortino_ratio"],
        max_drawdown=d["max_drawdown"],
        max_dd_duration=d["max_dd_duration"],
        volatility=d["volatility"],
        win_rate=d["win_rate"],
        rebalance_count=d["rebalance_count"],
        total_trades=d["total_trades"],
        benchmark_return_pct=d["benchmark_return_pct"],
        benchmark_cagr=d["benchmark_cagr"],
        alpha=d["alpha"],
        beta=d["beta"],
    )


class PortfolioBacktestRepository(IPortfolioBacktestRepository):
    """组合回测结果数据访问层。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def save(self, record: PortfolioBacktestRecord) -> int:
        with self._db.session_scope() as s:
            row = PortfolioBacktestResult(
                name=record.name,
                source=record.source,
                strategy=record.strategy,
                symbols=record.symbols,
                params=record.params,
                benchmark=record.benchmark,
                start_date=record.start_date,
                end_date=record.end_date,
                status=record.status,
                portfolio_id=record.portfolio_id,
                error_msg=record.error_msg,
                initial_capital=record.initial_capital,
                final_equity=record.final_equity,
                total_return_pct=record.total_return_pct,
                cagr=record.cagr,
                sharpe_ratio=record.sharpe_ratio,
                sortino_ratio=record.sortino_ratio,
                max_drawdown=record.max_drawdown,
                max_dd_duration=record.max_dd_duration,
                volatility=record.volatility,
                win_rate=record.win_rate,
                rebalance_count=record.rebalance_count,
                total_trades=record.total_trades,
                benchmark_return_pct=record.benchmark_return_pct,
                benchmark_cagr=record.benchmark_cagr,
                alpha=record.alpha,
                beta=record.beta,
                equity_curve=record.equity_curve,
                rebalances=record.rebalances,
                trades=record.trades,
                final_weights=record.final_weights,
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.id

    def get(self, result_id: int) -> Optional[PortfolioBacktestRecord]:
        with self._db.session_scope() as s:
            row = s.get(PortfolioBacktestResult, result_id)
            return _row_to_full_record(row) if row else None

    def get_many(self, ids: list[int]) -> list[PortfolioBacktestRecord]:
        if not ids:
            return []
        with self._db.session_scope() as s:
            rows = s.exec(
                select(PortfolioBacktestResult).where(
                    PortfolioBacktestResult.id.in_(ids)
                )
            ).all()
            return [_row_to_full_record(r) for r in rows]

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
        with self._db.session_scope() as s:
            stmt = select(*_SUMMARY_COLS)
            if strategy:
                stmt = stmt.where(
                    PortfolioBacktestResult.strategy == strategy
                )
            if source:
                stmt = stmt.where(
                    PortfolioBacktestResult.source == source
                )
            if start:
                stmt = stmt.where(
                    PortfolioBacktestResult.created_at >= start
                )
            if end:
                stmt = stmt.where(
                    PortfolioBacktestResult.created_at <= end
                )

            # 总数
            from sqlalchemy import func as sa_func
            count_stmt = select(sa_func.count()).select_from(
                PortfolioBacktestResult
            )
            if strategy:
                count_stmt = count_stmt.where(
                    PortfolioBacktestResult.strategy == strategy
                )
            if source:
                count_stmt = count_stmt.where(
                    PortfolioBacktestResult.source == source
                )
            if start:
                count_stmt = count_stmt.where(
                    PortfolioBacktestResult.created_at >= start
                )
            if end:
                count_stmt = count_stmt.where(
                    PortfolioBacktestResult.created_at <= end
                )
            total = s.execute(count_stmt).scalar() or 0

            page = max(page, 1)
            size = max(min(size, 100), 1)
            stmt = stmt.order_by(
                PortfolioBacktestResult.created_at.desc()
            ).offset((page - 1) * size).limit(size)
            rows = s.execute(stmt).all()
            records = [_summary_row_to_record(r) for r in rows]
            return records, total

    def delete(self, result_id: int) -> bool:
        with self._db.session_scope() as s:
            row = s.get(PortfolioBacktestResult, result_id)
            if not row:
                return False
            s.delete(row)
            s.commit()
            return True

    def update_status(
        self, result_id: int, status: str,
        error_msg: Optional[str] = None,
    ) -> None:
        with self._db.session_scope() as s:
            row = s.get(PortfolioBacktestResult, result_id)
            if row:
                row.status = status
                row.error_msg = error_msg
                row.updated_at = datetime.now()
                s.add(row)
                s.commit()


# ── 工厂（单例 + 线程锁，照搬 portfolio/repository.py）──
_db_connection: Optional[DBConnection] = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_portfolio_backtest_repository(
    db_connection: Optional[DBConnection] = None,
) -> PortfolioBacktestRepository:
    """创建组合回测结果仓储实例。"""
    return PortfolioBacktestRepository(
        db_connection or _get_db_connection()
    )
