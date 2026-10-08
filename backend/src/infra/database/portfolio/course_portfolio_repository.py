"""课程组合 repository: 计划/腿 CRUD + 档位成交回写 + 收盘价查询。

遵循项目 Repository Pattern(参考 portfolio/repository.py):
- 工厂 create_course_portfolio_repository();
- stock_ohlcv 收盘价为裸 SQL 表, 用 text() 查询(同 perm repo)。
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlmodel import select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn

from .course_models import CoursePortfolio, CoursePortfolioLeg


class CoursePortfolioRepository:
    """课程组合计划数据访问。"""

    def __init__(self, db: DBConnection):
        self._db = db

    # ── 计划 CRUD ────────────────────────────────────────────────
    def create_plan(
        self, portfolio: CoursePortfolio, legs: list[CoursePortfolioLeg]
    ) -> int:
        """落库计划+腿, 返回 portfolio.id。"""
        with self._db.session_scope() as s:
            s.add(portfolio)
            s.flush()
            for leg in legs:
                leg.portfolio_id = portfolio.id
                s.add(leg)
            s.flush()
            return portfolio.id

    def list_plans(self) -> list[dict]:
        """全部计划(不含腿), 按 created_at 降序。"""
        with self._db.session_scope() as s:
            rows = list(
                s.exec(
                    select(CoursePortfolio)
                    .order_by(CoursePortfolio.created_at.desc())
                ).all()
            )
            for r in rows:
                s.expunge(r)
            return [
                {
                    "id": p.id,
                    "name": p.name,
                    "risk_profile": p.risk_profile,
                    "total_capital": p.total_capital,
                    "cash_reserve_pct": p.cash_reserve_pct,
                    "target_stock_count": p.target_stock_count,
                    "status": p.status,
                    "notes": p.notes,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in rows
            ]

    def get_plan(self, portfolio_id: int) -> Optional[dict]:
        """计划 + legs(ORM对象);不存在返回 None。"""
        with self._db.session_scope() as s:
            p = s.get(CoursePortfolio, portfolio_id)
            if p is None:
                return None
            legs = list(
                s.exec(
                    select(CoursePortfolioLeg)
                    .where(CoursePortfolioLeg.portfolio_id == portfolio_id)
                    .order_by(CoursePortfolioLeg.category, CoursePortfolioLeg.symbol)
                ).all()
            )
            for l in legs:
                s.expunge(l)
            s.expunge(p)
            return {"portfolio": p, "legs": legs}

    def delete_plan(self, portfolio_id: int) -> bool:
        """删除计划及全部腿。存在并删除返回 True。"""
        with self._db.session_scope() as s:
            p = s.get(CoursePortfolio, portfolio_id)
            if p is None:
                return False
            for l in list(
                s.exec(
                    select(CoursePortfolioLeg).where(
                        CoursePortfolioLeg.portfolio_id == portfolio_id
                    )
                ).all()
            ):
                s.delete(l)
            s.delete(p)
            return True

    # ── 腿与成交回写 ─────────────────────────────────────────────
    def save_leg_fill(
        self,
        leg_id: int,
        entry_plan: list[dict],
        shares_delta: int,
        fill_price: float,
        fill_value: float,
        status: Optional[str] = None,
    ) -> None:
        """回写某腿档位执行: entry_plan JSONB / shares / invested / avg_cost。

        status 非空时同步更新所属计划状态(不改 complete)。
        """
        with self._db.session_scope() as s:
            l = s.get(CoursePortfolioLeg, leg_id)
            if l is None:
                return
            new_shares = (l.shares or 0) + shares_delta
            new_invested = (l.invested_amount or 0.0) + fill_value
            l.entry_plan = entry_plan
            l.shares = new_shares
            l.invested_amount = new_invested
            l.avg_cost = (new_invested / new_shares) if new_shares > 0 else 0.0
            l.updated_at = datetime.now()
            if status:
                p = s.get(CoursePortfolio, l.portfolio_id)
                if p and p.status != "complete":
                    p.status = status
                    p.updated_at = datetime.now()

    def set_plan_status(self, portfolio_id: int, status: str) -> None:
        with self._db.session_scope() as s:
            p = s.get(CoursePortfolio, portfolio_id)
            if p:
                p.status = status
                p.updated_at = datetime.now()

    # ── stock_ohlcv 收盘价(裸 SQL, 同 perm repo) ─────────────────
    def get_close_price(self, symbol: str, on_or_before: date) -> Optional[float]:
        """on_or_before 当天或最近交易日的收盘价;无数据返回 None。"""
        with self._db.session_scope() as s:
            row = s.execute(
                text(
                    "SELECT close_ FROM stock_ohlcv "
                    "WHERE symbol = :symbol AND trade_date <= :d "
                    "ORDER BY trade_date DESC LIMIT 1"
                ),
                {"symbol": symbol, "d": on_or_before},
            ).first()
            return float(row[0]) if row else None

    def get_close_prices_batch(
        self, symbols: list[str], on_or_before: date
    ) -> dict[str, float]:
        """批量收盘价: 每只取 on_or_before 当天或最近交易日。

        stock_ohlcv 是 TimescaleDB 超表, 单只查询也要跨数百个时间分块
        枚举索引(~200ms); N 只逐查的规划开销是 N+1 放大。合并为一条
        DISTINCT ON 后分块规划只摊销一次。
        """
        if not symbols:
            return {}
        out: dict[str, float] = {}
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT DISTINCT ON (symbol) symbol, close_ FROM stock_ohlcv "
                    "WHERE symbol = ANY(:syms) AND trade_date <= :d "
                    "ORDER BY symbol, trade_date DESC"
                ),
                {"syms": list(dict.fromkeys(symbols)), "d": on_or_before},
            ).fetchall()
            for sym, close in rows:
                if close is not None:
                    out[sym] = float(close)
        return out


def create_course_portfolio_repository() -> CoursePortfolioRepository:
    return CoursePortfolioRepository(create_db_connection(get_dsn()))
