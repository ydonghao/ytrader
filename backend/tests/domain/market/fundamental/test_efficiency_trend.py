"""经营效率趋势纯函数测试。"""
import pytest

from src.domain.market.fundamental.efficiency_trend import (
    turnover_ratio,
    receivable_turnover,
    inventory_turnover,
    asset_turnover,
    compute_turnovers,
    turnover_trend,
)


class TestTurnoverRatio:
    def test_basic(self):
        assert turnover_ratio(1000, 200) == pytest.approx(5.0)

    def test_zero_stock(self):
        assert turnover_ratio(1000, 0) is None

    def test_missing(self):
        assert turnover_ratio(None, 100) is None


class TestSpecificTurnovers:
    def test_receivable(self):
        # 营收1000, 期初期末应收各100 → 均值100 → 10 次
        assert receivable_turnover(1000, 100, 100) == pytest.approx(10.0)

    def test_inventory_uses_operating_cost(self):
        # 营业成本600, 存货期初期末各100 → 6 次
        assert inventory_turnover(600, 100, 100) == pytest.approx(6.0)

    def test_asset(self):
        assert asset_turnover(1000, 400, 600) == pytest.approx(2.0)  # 1000/500

    def test_missing_begin(self):
        assert receivable_turnover(1000, None, 100) is None


class TestComputeTurnovers:
    def test_all_three(self):
        curr = {"revenue": 1000, "operating_cost": 600,
                "accounts_receivable": 100, "inventory": 100, "total_assets": 600}
        prev = {"accounts_receivable": 100, "inventory": 100, "total_assets": 400}
        t = compute_turnovers(curr, prev)
        assert t["receivable"] == pytest.approx(10.0)
        assert t["inventory"] == pytest.approx(6.0)
        assert t["asset"] == pytest.approx(2.0)  # 1000/500


class TestTurnoverTrend:
    def test_improving(self):
        # 周转率逐年上升（资产变轻）
        periods = [
            {"revenue": 100, "operating_cost": 60, "total_assets": 200,
             "accounts_receivable": 20, "inventory": 20},
            {"revenue": 150, "operating_cost": 90, "total_assets": 220,
             "accounts_receivable": 22, "inventory": 22},
            {"revenue": 220, "operating_cost": 130, "total_assets": 240,
             "accounts_receivable": 24, "inventory": 24},
        ]
        r = turnover_trend(periods)
        assert r.asset is not None
        assert r.asset.improving is True
        assert r.overall == "improving"

    def test_deteriorating(self):
        # 营收持平但资产膨胀 → 周转率下降
        periods = [
            {"revenue": 100, "total_assets": 100},
            {"revenue": 100, "total_assets": 150},
            {"revenue": 100, "total_assets": 200},
        ]
        r = turnover_trend(periods)
        assert r.asset.improving is False
        assert r.overall == "deteriorating"

    def test_too_few_periods(self):
        r = turnover_trend([{"revenue": 100, "total_assets": 100}])
        assert r.asset is None
        assert r.overall == "stable"
