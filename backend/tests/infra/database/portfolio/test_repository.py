"""portfolio repository 集成测试。

使用真实本地 DB(项目约定), 每个测试用独立符号/组合名避免冲突,
并在 teardown 显式清理创建的数据。
"""
import pytest
from datetime import date

from src.infra.database.portfolio.repository import (
    create_portfolio_repository,
)


@pytest.fixture
def repo():
    return create_portfolio_repository()


def _cleanup_instrument(repo, symbol):
    inst = repo.get_instrument_by_symbol(symbol)
    if inst:
        repo.delete_instrument(inst.id)


def _cleanup_portfolio(repo, name):
    for p in repo.list_portfolios(active_only=False):
        if p.name == name:
            repo.delete_portfolio(p.id)


class TestPortfolioRepository:
    """组合 repository 集成测试。"""

    def test_instrument_upsert_and_list(self, repo):
        """新增标的 + 查询 + 重复 upsert 覆盖。"""
        sym = "TEST_VOO_REP"
        try:
            inst = repo.upsert_instrument(
                symbol=sym,
                market="US",
                asset_class="equity",
                ccy="USD",
                name="Test VOO",
            )
            assert inst.id is not None
            assert inst.symbol == sym

            # 重复 upsert 覆盖(改名)
            inst2 = repo.upsert_instrument(
                symbol=sym,
                market="US",
                asset_class="equity",
                ccy="USD",
                name="Test VOO Updated",
            )
            assert inst2.id == inst.id
            assert inst2.name == "Test VOO Updated"

            # 查询过滤
            listed = repo.list_instruments(market="US")
            syms = [i.symbol for i in listed]
            assert sym in syms

            # 按符号查
            by_sym = repo.get_instrument_by_symbol(sym)
            assert by_sym is not None
            assert by_sym.asset_class == "equity"
        finally:
            _cleanup_instrument(repo, sym)

    def test_portfolio_crud_with_holdings(self, repo):
        """组合创建 + 持仓设置 + 查询 + 删除。"""
        pname = "TEST_PORTFOLIO_REP"
        sym = "TEST_HOLD_E"
        try:
            inst = repo.upsert_instrument(
                symbol=sym,
                market="A",
                asset_class="equity",
                ccy="CNY",
                name="Test Equity",
            )
            p = repo.create_portfolio(
                name=pname, strategy_type="permanent"
            )
            assert p.id is not None
            assert p.strategy_type == "permanent"

            # 设持仓
            holdings = repo.set_holdings(
                p.id,
                [
                    {
                        "instrument_id": inst.id,
                        "target_weight": 0.25,
                        "shares": 1000,
                        "cost_price": 10.0,
                    }
                ],
            )
            assert len(holdings) == 1
            assert holdings[0].shares == 1000

            # 查持仓(对象属性在 session 外可读)
            got = repo.list_holdings(p.id)
            assert len(got) == 1
            assert got[0].target_weight == 0.25

            # 更新持仓股数
            repo.update_holding_shares(holdings[0].id, 1500)
            got2 = repo.list_holdings(p.id)
            assert got2[0].shares == 1500

            # 删除组合(级联持仓)
            ok = repo.delete_portfolio(p.id)
            assert ok
            assert repo.get_portfolio(p.id) is None
            assert repo.list_holdings(p.id) == []
        finally:
            _cleanup_portfolio(repo, pname)
            _cleanup_instrument(repo, sym)

    def test_save_and_query_nav(self, repo):
        """净值保存 + 明细查询 + 覆盖同日记录。"""
        pname = "TEST_NAV_REP"
        sym = "TEST_NAV_E"
        try:
            inst = repo.upsert_instrument(
                symbol=sym,
                market="A",
                asset_class="equity",
                ccy="CNY",
                name="Test",
            )
            p = repo.create_portfolio(
                name=pname, strategy_type="permanent"
            )
            repo.set_holdings(
                p.id,
                [
                    {
                        "instrument_id": inst.id,
                        "target_weight": 0.5,
                        "shares": 100,
                        "cost_price": 10.0,
                    }
                ],
            )

            d = date(2026, 1, 1)
            nav = repo.save_nav(
                portfolio_id=p.id,
                trade_date=d,
                nav_cny=1.0,
                prev_nav_cny=None,
                daily_return=None,
                total_value_cny=100000.0,
                max_drift=0.0,
                rebalance_suggested=False,
                items=[
                    {
                        "instrument_id": inst.id,
                        "symbol": sym,
                        "asset_class": "equity",
                        "shares": 100,
                        "price": 10.0,
                        "price_cny": 10.0,
                        "fx_rate": 1.0,
                        "value_cny": 1000.0,
                        "target_weight": 0.5,
                        "actual_weight": 0.01,
                        "drift": -0.49,
                    }
                ],
            )
            assert nav.id is not None

            hist = repo.get_nav_history(p.id)
            assert len(hist) == 1
            assert hist[0].nav_cny == 1.0

            items = repo.get_nav_items(nav.id)
            assert len(items) == 1
            assert items[0].symbol == sym

            # 覆盖同日记录
            nav2 = repo.save_nav(
                portfolio_id=p.id,
                trade_date=d,
                nav_cny=1.05,
                prev_nav_cny=1.0,
                daily_return=0.05,
                total_value_cny=105000.0,
                max_drift=0.0,
                rebalance_suggested=False,
                items=[
                    {
                        "instrument_id": inst.id,
                        "symbol": sym,
                        "asset_class": "equity",
                        "shares": 100,
                        "price": 10.5,
                        "price_cny": 10.5,
                        "fx_rate": 1.0,
                        "value_cny": 1050.0,
                        "target_weight": 0.5,
                        "actual_weight": 0.01,
                        "drift": -0.49,
                    }
                ],
            )
            hist2 = repo.get_nav_history(p.id)
            assert len(hist2) == 1  # 仍是1条(覆盖)
            assert hist2[0].nav_cny == 1.05
        finally:
            _cleanup_portfolio(repo, pname)
            _cleanup_instrument(repo, sym)

    def test_delete_instrument_with_reference_blocked(self, repo):
        """被组合引用的标的不能删除。"""
        pname = "TEST_REF_PORT"
        sym = "TEST_REF_E"
        try:
            inst = repo.upsert_instrument(
                symbol=sym,
                market="A",
                asset_class="equity",
                ccy="CNY",
                name="Test Ref",
            )
            p = repo.create_portfolio(
                name=pname, strategy_type="custom"
            )
            repo.set_holdings(
                p.id,
                [
                    {
                        "instrument_id": inst.id,
                        "target_weight": 1.0,
                        "shares": 100,
                    }
                ],
            )

            ok, msg = repo.delete_instrument(inst.id)
            assert not ok
            assert "引用" in msg

            # 先删组合, 再删标的就成功
            repo.delete_portfolio(p.id)
            ok2, _ = repo.delete_instrument(inst.id)
            assert ok2
        finally:
            _cleanup_portfolio(repo, pname)
            _cleanup_instrument(repo, sym)
