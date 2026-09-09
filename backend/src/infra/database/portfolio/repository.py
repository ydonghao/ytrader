"""永久投资组合 repository 实现。

职责:
- 标的池 CRUD (PortfolioInstrument)
- 组合定义 CRUD (PortfolioDefinition)
- 持仓 CRUD (PortfolioHolding)
- 净值读写 (PortfolioNav + PortfolioNavItem)
- stock_ohlcv 收盘价查询 (裸 SQL, 参考 alert/repository.py)

遵循项目 Repository Pattern: 工厂 + session_scope。
"""
import threading
import datetime as dt
from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlmodel import Session, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn

from .models import (
    PortfolioInstrument,
    PortfolioDefinition,
    PortfolioHolding,
    PortfolioNav,
    PortfolioNavItem,
)


class PortfolioRepository:
    """永久投资组合数据访问层。"""

    def __init__(self, db: DBConnection):
        self._db = db

    # ── 标的池 ────────────────────────────────────────────────────

    def list_instruments(
        self,
        market: Optional[str] = None,
        asset_class: Optional[str] = None,
        enabled_only: bool = False,
    ) -> list[PortfolioInstrument]:
        """列出标的池(支持 market/asset_class 过滤)。"""
        with self._db.session_scope() as s:
            stmt = select(PortfolioInstrument)
            if market:
                stmt = stmt.where(PortfolioInstrument.market == market)
            if asset_class:
                stmt = stmt.where(
                    PortfolioInstrument.asset_class == asset_class
                )
            if enabled_only:
                stmt = stmt.where(
                    PortfolioInstrument.enabled == True  # noqa: E712
                )
            stmt = stmt.order_by(
                PortfolioInstrument.market, PortfolioInstrument.asset_class
            )
            return list(s.exec(stmt).all())

    def get_instrument(
        self, instrument_id: int
    ) -> Optional[PortfolioInstrument]:
        with self._db.session_scope() as s:
            return s.get(PortfolioInstrument, instrument_id)

    def get_instrument_by_symbol(
        self, symbol: str
    ) -> Optional[PortfolioInstrument]:
        with self._db.session_scope() as s:
            return s.exec(
                select(PortfolioInstrument).where(
                    PortfolioInstrument.symbol == symbol
                )
            ).first()

    def upsert_instrument(
        self,
        symbol: str,
        market: str,
        asset_class: str,
        ccy: str,
        name: str,
        provider: str = "akshare",
        enabled: bool = True,
    ) -> PortfolioInstrument:
        """插入或更新标的(按 symbol 唯一键)。"""
        with self._db.session_scope() as s:
            existing = s.exec(
                select(PortfolioInstrument).where(
                    PortfolioInstrument.symbol == symbol
                )
            ).first()
            now = datetime.now()
            if existing:
                existing.market = market
                existing.asset_class = asset_class
                existing.ccy = ccy
                existing.name = name
                existing.provider = provider
                existing.enabled = enabled
                existing.updated_at = now
                s.add(existing)
                s.commit()
                s.refresh(existing)
                return existing
            inst = PortfolioInstrument(
                symbol=symbol,
                market=market,
                asset_class=asset_class,
                ccy=ccy,
                name=name,
                provider=provider,
                enabled=enabled,
                created_at=now,
                updated_at=now,
            )
            s.add(inst)
            s.commit()
            s.refresh(inst)
            return inst

    def delete_instrument(self, instrument_id: int) -> tuple[bool, str]:
        """删除标的。被组合引用时拒绝, 返回 (success, message)。"""
        with self._db.session_scope() as s:
            refs = s.exec(
                select(PortfolioHolding).where(
                    PortfolioHolding.instrument_id == instrument_id
                )
            ).all()
            if refs:
                portfolios = {h.portfolio_id for h in refs}
                return (
                    False,
                    f"被 {len(portfolios)} 个组合引用, 无法删除",
                )
            inst = s.get(PortfolioInstrument, instrument_id)
            if inst:
                s.delete(inst)
                s.commit()
                return True, "ok"
            return False, "标的不存在"

    # ── 组合定义 ──────────────────────────────────────────────────

    def list_portfolios(
        self, active_only: bool = True
    ) -> list[PortfolioDefinition]:
        with self._db.session_scope() as s:
            stmt = select(PortfolioDefinition)
            if active_only:
                stmt = stmt.where(
                    PortfolioDefinition.is_active == True  # noqa: E712
                )
            stmt = stmt.order_by(PortfolioDefinition.id)
            return list(s.exec(stmt).all())

    def get_portfolio(
        self, portfolio_id: int
    ) -> Optional[PortfolioDefinition]:
        with self._db.session_scope() as s:
            return s.get(PortfolioDefinition, portfolio_id)

    def create_portfolio(
        self,
        name: str,
        strategy_type: str,
        base_ccy: str = "CNY",
        rebalance_threshold: float = 0.05,
        initial_capital: float = 100000.0,
        is_active: bool = True,
    ) -> PortfolioDefinition:
        with self._db.session_scope() as s:
            now = datetime.now()
            p = PortfolioDefinition(
                name=name,
                strategy_type=strategy_type,
                base_ccy=base_ccy,
                rebalance_threshold=rebalance_threshold,
                initial_capital=initial_capital,
                is_active=is_active,
                created_at=now,
                updated_at=now,
            )
            s.add(p)
            s.commit()
            s.refresh(p)
            return p

    def update_portfolio(
        self,
        portfolio_id: int,
        name: Optional[str] = None,
        rebalance_threshold: Optional[float] = None,
        initial_capital: Optional[float] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[PortfolioDefinition]:
        with self._db.session_scope() as s:
            p = s.get(PortfolioDefinition, portfolio_id)
            if not p:
                return None
            if name is not None:
                p.name = name
            if rebalance_threshold is not None:
                p.rebalance_threshold = rebalance_threshold
            if initial_capital is not None:
                p.initial_capital = initial_capital
            if is_active is not None:
                p.is_active = is_active
            p.updated_at = datetime.now()
            s.add(p)
            s.commit()
            s.refresh(p)
            return p

    def delete_portfolio(self, portfolio_id: int) -> bool:
        """删除组合及其持仓与净值记录(级联)。"""
        with self._db.session_scope() as s:
            # 先删 nav_item → nav → holding → definition
            nav_ids = [
                n.id
                for n in s.exec(
                    select(PortfolioNav).where(
                        PortfolioNav.portfolio_id == portfolio_id
                    )
                ).all()
            ]
            for nav_id in nav_ids:
                s.execute(
                    text(
                        "DELETE FROM portfolio_nav_item WHERE nav_id = :nid"
                    ),
                    {"nid": nav_id},
                )
            s.execute(
                text(
                    "DELETE FROM portfolio_nav WHERE portfolio_id = :pid"
                ),
                {"pid": portfolio_id},
            )
            s.execute(
                text(
                    "DELETE FROM portfolio_holding WHERE portfolio_id = :pid"
                ),
                {"pid": portfolio_id},
            )
            p = s.get(PortfolioDefinition, portfolio_id)
            if p:
                s.delete(p)
            s.commit()
            return True

    # ── 持仓 ──────────────────────────────────────────────────────

    def list_holdings(
        self, portfolio_id: int
    ) -> list[PortfolioHolding]:
        with self._db.session_scope() as s:
            return list(
                s.exec(
                    select(PortfolioHolding)
                    .where(PortfolioHolding.portfolio_id == portfolio_id)
                    .order_by(PortfolioHolding.id)
                ).all()
            )

    def set_holdings(
        self, portfolio_id: int, holdings: list[dict]
    ) -> list[PortfolioHolding]:
        """全量替换某组合的持仓。

        holdings: [{instrument_id, target_weight, shares, cost_price}]
        """
        with self._db.session_scope() as s:
            # 清空旧持仓
            s.execute(
                text(
                    "DELETE FROM portfolio_holding "
                    "WHERE portfolio_id = :pid"
                ),
                {"pid": portfolio_id},
            )
            now = datetime.now()
            result = []
            for h in holdings:
                ph = PortfolioHolding(
                    portfolio_id=portfolio_id,
                    instrument_id=h["instrument_id"],
                    target_weight=h["target_weight"],
                    shares=h["shares"],
                    cost_price=h.get("cost_price", 0.0),
                    created_at=now,
                    updated_at=now,
                )
                s.add(ph)
                result.append(ph)
            s.commit()
            for ph in result:
                s.refresh(ph)
            return result

    def update_holding_shares(
        self, holding_id: int, shares: int, cost_price: Optional[float] = None
    ) -> Optional[PortfolioHolding]:
        """更新单持仓股数(用于应用再平衡建议)。"""
        with self._db.session_scope() as s:
            h = s.get(PortfolioHolding, holding_id)
            if not h:
                return None
            h.shares = shares
            if cost_price is not None:
                h.cost_price = cost_price
            h.updated_at = datetime.now()
            s.add(h)
            s.commit()
            s.refresh(h)
            return h

    # ── 净值 ──────────────────────────────────────────────────────

    def get_latest_nav(
        self, portfolio_id: int
    ) -> Optional[PortfolioNav]:
        with self._db.session_scope() as s:
            return s.exec(
                select(PortfolioNav)
                .where(PortfolioNav.portfolio_id == portfolio_id)
                .order_by(PortfolioNav.trade_date.desc())
            ).first()

    def get_nav_history(
        self,
        portfolio_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[PortfolioNav]:
        with self._db.session_scope() as s:
            stmt = (
                select(PortfolioNav)
                .where(PortfolioNav.portfolio_id == portfolio_id)
            )
            if start_date:
                stmt = stmt.where(PortfolioNav.trade_date >= start_date)
            if end_date:
                stmt = stmt.where(PortfolioNav.trade_date <= end_date)
            stmt = stmt.order_by(PortfolioNav.trade_date.asc())
            return list(s.exec(stmt).all())

    def get_nav_items(self, nav_id: int) -> list[PortfolioNavItem]:
        with self._db.session_scope() as s:
            return list(
                s.exec(
                    select(PortfolioNavItem)
                    .where(PortfolioNavItem.nav_id == nav_id)
                    .order_by(PortfolioNavItem.id)
                ).all()
            )

    def save_nav(
        self,
        portfolio_id: int,
        trade_date: date,
        nav_cny: float,
        prev_nav_cny: Optional[float],
        daily_return: Optional[float],
        total_value_cny: float,
        max_drift: float,
        rebalance_suggested: bool,
        items: list[dict],
    ) -> PortfolioNav:
        """保存一日净值记录 + 明细(覆盖同日记录)。

        items: [{instrument_id, symbol, asset_class, shares, price,
                 price_cny, fx_rate, value_cny, target_weight,
                 actual_weight, drift}]
        """
        with self._db.session_scope() as s:
            # 覆盖同日记录
            existing = s.exec(
                select(PortfolioNav).where(
                    PortfolioNav.portfolio_id == portfolio_id,
                    PortfolioNav.trade_date == trade_date,
                )
            ).first()
            if existing:
                # 删旧明细
                s.execute(
                    text(
                        "DELETE FROM portfolio_nav_item "
                        "WHERE nav_id = :nid"
                    ),
                    {"nid": existing.id},
                )
                nav = existing
                nav.nav_cny = nav_cny
                nav.prev_nav_cny = prev_nav_cny
                nav.daily_return = daily_return
                nav.total_value_cny = total_value_cny
                nav.max_drift = max_drift
                nav.rebalance_suggested = rebalance_suggested
            else:
                nav = PortfolioNav(
                    portfolio_id=portfolio_id,
                    trade_date=trade_date,
                    nav_cny=nav_cny,
                    prev_nav_cny=prev_nav_cny,
                    daily_return=daily_return,
                    total_value_cny=total_value_cny,
                    max_drift=max_drift,
                    rebalance_suggested=rebalance_suggested,
                )
            s.add(nav)
            s.commit()
            s.refresh(nav)

            # 写明细
            now = datetime.now()
            for it in items:
                s.add(
                    PortfolioNavItem(
                        nav_id=nav.id,
                        instrument_id=it["instrument_id"],
                        symbol=it["symbol"],
                        asset_class=it["asset_class"],
                        shares=it["shares"],
                        price=it["price"],
                        price_cny=it["price_cny"],
                        fx_rate=it["fx_rate"],
                        value_cny=it["value_cny"],
                        target_weight=it["target_weight"],
                        actual_weight=it["actual_weight"],
                        drift=it["drift"],
                        created_at=now,
                    )
                )
            s.commit()
            return nav

    # ── stock_ohlcv 收盘价查询(裸 SQL) ────────────────────────────

    def get_close_price(
        self, symbol: str, on_or_before: date
    ) -> Optional[float]:
        """返回标的在 on_or_before 当天或最近交易日的收盘价。

        stock_ohlcv 是裸 SQL 表(无 SQLModel), 参考 alert/repository.py
        的 get_latest_price 写法。
        """
        with self._db.session_scope() as s:
            row = s.execute(
                text(
                    "SELECT close_ FROM stock_ohlcv "
                    "WHERE symbol = :symbol "
                    "AND trade_date <= :d "
                    "ORDER BY trade_date DESC LIMIT 1"
                ),
                {"symbol": symbol, "d": on_or_before},
            ).first()
            return float(row[0]) if row else None

    def get_latest_price_date(self, symbol: str) -> Optional[date]:
        """返回标的最新的交易日(trade_date 列)。"""
        with self._db.session_scope() as s:
            row = s.execute(
                text(
                    "SELECT trade_date FROM stock_ohlcv "
                    "WHERE symbol = :symbol "
                    "ORDER BY trade_date DESC LIMIT 1"
                ),
                {"symbol": symbol},
            ).first()
            # trade_date 可能是 datetime, 取 .date()
            td = row[0] if row else None
            if td is None:
                return None
            if isinstance(td, dt.datetime):
                return td.date()
            return td


# ======== 工厂函数(遵循项目约定: 单例 + 工厂) ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_portfolio_repository(
    db_connection: DBConnection | None = None,
) -> PortfolioRepository:
    """创建永久投资组合仓储实例。"""
    return PortfolioRepository(db_connection or _get_db_connection())
