"""position_bridge 桥接测试 — sqlite in-memory, 不依赖真实 PG/网络。

覆盖三层:
1. domain 层 build_positions 的持仓转换口径(纯函数);
2. handler 层 load_bridge_positions 与 PortfolioRepository 的
   sqlite 集成(含默认 active 组合选择);
3. risk/portfolio router 无真实持仓时的降级 + warning(mock 桥接)。
"""
from contextlib import contextmanager

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from src.domain.market.portfolio.position_bridge import (
    HoldingInput,
    build_positions,
)
from src.infra.database.portfolio.models import (
    PortfolioDefinition,
    PortfolioHolding,
    PortfolioInstrument,
)
from src.infra.database.portfolio.repository import PortfolioRepository


# ═══════════════════════════════════════════════════════════════
# sqlite in-memory 基建(参考 test_fx_rate.py 的 _FakeDb 模式)
# ═══════════════════════════════════════════════════════════════

class _FakeDb:
    """模拟 DBConnection, session_scope 返回 sqlite session。

    expire_on_commit=False 与真实 DBConnection 保持一致,
    否则 commit 后 ORM 属性过期触发 DetachedInstanceError。
    """

    def __init__(self, engine):
        self._engine = engine

    @contextmanager
    def session_scope(self):
        with Session(self._engine, expire_on_commit=False) as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise


def _make_repo() -> tuple[PortfolioRepository, object]:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            PortfolioDefinition.__table__,
            PortfolioInstrument.__table__,
            PortfolioHolding.__table__,
        ],
    )
    # stock_ohlcv 是裸 SQL 表, 手动建 + 种子行情
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE stock_ohlcv ("
            "symbol TEXT, trade_date TEXT, close_ REAL)"
        ))
    return PortfolioRepository(_FakeDb(engine)), engine


def _seed_close(engine, symbol: str, close_: float) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO stock_ohlcv "
                "VALUES (:s, :d, :c)"
            ),
            {"s": symbol, "d": "2026-08-12", "c": close_},
        )


def _seed_instrument(repo, symbol: str, name: str) -> int:
    inst = repo.upsert_instrument(
        symbol=symbol,
        market="A",
        asset_class="equity",
        ccy="CNY",
        name=name,
    )
    return inst.id


# ═══════════════════════════════════════════════════════════════
# 1. domain 层: build_positions 纯函数
# ═══════════════════════════════════════════════════════════════

def test_build_positions_uses_fetched_close_price():
    positions = build_positions(
        [
            HoldingInput(
                symbol="sh510300",
                shares=1000,
                cost_price=4.0,
                name="沪深300ETF",
                ccy="CNY",
            )
        ],
        lambda sym: 4.25,
    )
    assert len(positions) == 1
    p = positions[0]
    assert p["symbol"] == "sh510300"
    assert p["quantity"] == 1000
    assert p["avg_price"] == 4.0
    assert p["current_price"] == 4.25
    assert p["market_value"] == 4250.0
    assert p["ccy"] == "CNY"
    assert p["name"] == "沪深300ETF"


def test_build_positions_none_price_falls_back_to_avg_price():
    """取不到行情时 current_price 兜底为 avg_price(cost_price)。"""
    positions = build_positions(
        [HoldingInput(symbol="sh510300", shares=100, cost_price=4.0)],
        lambda sym: None,
    )
    assert len(positions) == 1
    assert positions[0]["current_price"] == 4.0
    assert positions[0]["market_value"] == 400.0


def test_build_positions_fetcher_error_does_not_break():
    def _boom(sym):
        raise RuntimeError("db down")

    positions = build_positions(
        [HoldingInput(symbol="sz159934", shares=200, cost_price=5.5)],
        _boom,
    )
    assert positions[0]["current_price"] == 5.5


def test_build_positions_skips_empty_and_unvaluable():
    holdings = [
        HoldingInput(symbol="sh510300", shares=0, cost_price=4.0),
        HoldingInput(symbol="", shares=100, cost_price=4.0),
        HoldingInput(symbol="sh000001", shares=100, cost_price=0.0),
    ]
    assert build_positions(holdings, lambda s: None) == []


def test_build_positions_defaults_name_and_ccy():
    positions = build_positions(
        [HoldingInput(symbol="hk02800", shares=100, cost_price=28.0)]
    )
    assert positions[0]["name"] == "hk02800"
    assert positions[0]["ccy"] == "CNY"


# ═══════════════════════════════════════════════════════════════
# 2. handler 层: load_bridge_positions + repo(sqlite)
# ═══════════════════════════════════════════════════════════════

def _load_bridge_positions(portfolio_id, repo):
    from src.api.handler.perm_portfolio_handler import (
        load_bridge_positions,
    )
    return load_bridge_positions(portfolio_id, repo=repo)


def test_bridge_uses_latest_close_price_from_ohlcv():
    repo, engine = _make_repo()
    p = repo.create_portfolio(name="永久组合", strategy_type="permanent")
    inst_id = _seed_instrument(repo, "sh510300", "沪深300ETF")
    repo.set_holdings(
        p.id,
        [
            {
                "instrument_id": inst_id,
                "target_weight": 0.25,
                "shares": 1000,
                "cost_price": 4.0,
            }
        ],
    )
    _seed_close(engine, "sh510300", 4.25)

    positions = _load_bridge_positions(p.id, repo)
    assert len(positions) == 1
    assert positions[0]["symbol"] == "sh510300"
    assert positions[0]["current_price"] == 4.25
    assert positions[0]["avg_price"] == 4.0
    assert positions[0]["market_value"] == 4250.0


def test_bridge_falls_back_to_cost_price_without_quotes():
    repo, engine = _make_repo()
    p = repo.create_portfolio(name="永久组合", strategy_type="permanent")
    inst_id = _seed_instrument(repo, "sz159934", "黄金ETF")
    repo.set_holdings(
        p.id,
        [
            {
                "instrument_id": inst_id,
                "target_weight": 0.25,
                "shares": 500,
                "cost_price": 5.5,
            }
        ],
    )
    # 不种 stock_ohlcv 行情 → current_price 兜底 cost_price

    positions = _load_bridge_positions(p.id, repo)
    assert positions[0]["current_price"] == 5.5
    assert positions[0]["market_value"] == 2750.0


def test_bridge_default_portfolio_picks_first_active():
    repo, engine = _make_repo()
    active = repo.create_portfolio(
        name="active", strategy_type="permanent"
    )
    inactive = repo.create_portfolio(
        name="inactive", strategy_type="custom", is_active=False
    )
    inst_id = _seed_instrument(repo, "sh510300", "沪深300ETF")
    repo.set_holdings(
        inactive.id,
        [
            {
                "instrument_id": inst_id,
                "target_weight": 1.0,
                "shares": 100,
                "cost_price": 4.0,
            }
        ],
    )
    # 默认(active)组合无持仓 → 返回 []
    assert _load_bridge_positions(None, repo) == []

    # 给 active 组合放持仓后, 不传 id 也能取到
    _seed_close(engine, "sh510300", 4.1)
    repo.set_holdings(
        active.id,
        [
            {
                "instrument_id": inst_id,
                "target_weight": 1.0,
                "shares": 200,
                "cost_price": 4.0,
            }
        ],
    )
    positions = _load_bridge_positions(None, repo)
    assert len(positions) == 1
    assert positions[0]["quantity"] == 200

    # 显式指定 inactive 组合则取它的持仓
    positions = _load_bridge_positions(inactive.id, repo)
    assert positions[0]["quantity"] == 100


def test_bridge_returns_empty_when_no_holdings():
    repo, _ = _make_repo()
    p = repo.create_portfolio(name="空组合", strategy_type="custom")
    assert _load_bridge_positions(p.id, repo) == []


# ═══════════════════════════════════════════════════════════════
# 3. router 层: 无真实持仓时降级 + warning(mock 桥接/repo)
# ═══════════════════════════════════════════════════════════════
# （slim/p3 返工）原 _FakeCursor/_FakeConn 仅服务已删除的
# portfolio_router.get_portfolio_attribution() 模拟归因端点测试，一并移除。
# ═══════════════════════════════════════════════════════════════


def test_risk_router_degrades_with_warning(monkeypatch):
    from src.api.handler import perm_portfolio_handler
    from src.api.router import risk_router

    monkeypatch.setattr(
        perm_portfolio_handler, "load_bridge_positions", lambda pid: []
    )
    monkeypatch.setattr(risk_router, "_get_positions", lambda: [])

    resp = risk_router.risk_portfolio()
    assert resp["code"] == 0
    assert resp["data"]["portfolio_value"] == 0
    assert resp["data"]["warning"] == "无真实持仓,显示演示数据"


def test_risk_router_uses_bridged_positions(monkeypatch):
    from src.api.handler import perm_portfolio_handler
    from src.api.router import risk_router

    bridged = [
        {
            "symbol": "sh510300",
            "name": "沪深300ETF",
            "quantity": 1000,
            "avg_price": 4.0,
            "current_price": 4.25,
            "market_value": 4250.0,
            "ccy": "CNY",
        }
    ]
    seen = {}

    def _fake_bridge(pid):
        seen["pid"] = pid
        return bridged

    monkeypatch.setattr(
        perm_portfolio_handler, "load_bridge_positions", _fake_bridge
    )
    # 隔离 PG: 个股收益用固定序列
    monkeypatch.setattr(
        risk_router,
        "_get_stock_returns",
        lambda sym, days=252: [0.01, -0.02, 0.005] * 30,
    )

    resp = risk_router.risk_portfolio(portfolio_id=7)
    data = resp["data"]
    assert seen["pid"] == 7  # portfolio_id 透传到桥接
    assert "warning" not in data
    assert data["portfolio_value"] == 4250.0
    assert data["position_count"] == 1
    assert data["top_positions"][0]["symbol"] == "sh510300"


# （slim/p3 返工）原 test_attribution_degrades_to_demo_with_warning /
# test_attribution_uses_bridged_positions 测的是已退役的模拟归因端点
# portfolio_router.get_portfolio_attribution()，随 router 一并删除；
# bridge/domain 层与 risk_router 桥接的测试保留。
