"""簇 8 杠杆与衍生品纯函数测试。"""
import pytest

from src.domain.market.derivatives.leverage import (
    futures_margin_leverage,
    leveraged_return,
    index_futures_contract_value,
    index_futures_margin,
    futures_basis_signal,
    days_to_delivery,
    margin_financing_capacity,
    beta_hedge_contracts,
)


class TestFuturesMarginLeverage:
    def test_14pct_margin_is_7x(self):
        # 14% 保证金 ≈ 7.14 倍杠杆（doc 27）
        r = futures_margin_leverage(contract_value=1_000_000, margin_rate=0.14)
        assert r.leverage == pytest.approx(1 / 0.14)
        assert r.margin_required == pytest.approx(140_000)

    def test_invalid(self):
        assert futures_margin_leverage(1_000_000, 0) is None
        assert futures_margin_leverage(1_000_000, 1.5) is None
        assert futures_margin_leverage(0, 0.14) is None


class TestLeveragedReturn:
    def test_amplified(self):
        # 5% 涨幅 × 7 倍 = 35%
        assert leveraged_return(0.05, 7) == pytest.approx(0.35)

    def test_loss_amplified(self):
        assert leveraged_return(-0.05, 7) == pytest.approx(-0.35)

    def test_invalid(self):
        assert leveraged_return(0.05, 0) is None


class TestIndexFuturesContractValue:
    def test_if_multiplier(self):
        # IF 3800 点 × 300 = 1,140,000
        assert index_futures_contract_value(3800, code="IF") == 1_140_000

    def test_explicit_multiplier(self):
        assert index_futures_contract_value(5000, multiplier=200) == 1_000_000

    def test_invalid_code(self):
        assert index_futures_contract_value(3800, code="XX") is None

    def test_margin(self):
        # 1,140,000 × 0.12 = 136,800
        assert index_futures_margin(3800, 0.12, code="IF") == 136_800


class TestFuturesBasis:
    def test_contango(self):
        # 期货 3900, 现货 3800 → 升水 100, pct≈2.63% >= 2% → 卖压
        r = futures_basis_signal(3900, 3800)
        assert r.basis == 100
        assert r.contango is True
        assert r.delivery_sell_pressure is True

    def test_normal_backwardation(self):
        # 贴水
        r = futures_basis_signal(3780, 3800)
        assert r.contango is False
        assert r.delivery_sell_pressure is False

    def test_custom_threshold(self):
        # 升水 1% < 自定义 3% 阈值 → 无卖压
        r = futures_basis_signal(3838, 3800, delivery_warning_pct=0.03)
        assert r.delivery_sell_pressure is False

    def test_invalid(self):
        assert futures_basis_signal(3900, 0) is None


class TestDaysToDelivery:
    def test_basic(self):
        from datetime import date
        d = days_to_delivery(date.today().toisoformat() if hasattr(date.today(), 'toisoformat') else None)
        # 不测具体值，只测健壮性；用字符串
        n = days_to_delivery("2099-01-01")
        assert n is not None and n > 0

    def test_past_returns_none(self):
        n = days_to_delivery("2000-01-01")
        assert n is None

    def test_invalid(self):
        assert days_to_delivery("not-a-date") is None


class TestMarginFinancing:
    def test_capacity(self):
        # 自有100万，维持担保130% → 可融≈76.9万，杠杆≈1.77
        r = margin_financing_capacity(own_capital=1_000_000)
        assert r.max_financing == pytest.approx(1_000_000 / 1.3)
        assert r.leverage == pytest.approx((1_000_000 + 1_000_000 / 1.3) / 1_000_000)
        assert r.annual_cost == pytest.approx((1_000_000 / 1.3) * 0.07)

    def test_custom_collateral(self):
        r = margin_financing_capacity(1_000_000, collateral=2_000_000)
        assert r.max_financing == pytest.approx(2_000_000 / 1.3)

    def test_invalid(self):
        assert margin_financing_capacity(0) is None
        assert margin_financing_capacity(None) is None


class TestBetaHedge:
    def test_basic(self):
        # 组合1000万, β=1.2, 合约价值=1,140,000 → 对冲名义1200万, 合约≈10.53
        r = beta_hedge_contracts(10_000_000, 1.2, 1_140_000)
        assert r.hedge_contracts == pytest.approx(12_000_000 / 1_140_000)
        assert r.hedge_contracts_rounded == int(r.hedge_contracts)

    def test_low_beta_fewer_contracts(self):
        r = beta_hedge_contracts(10_000_000, 0.5, 1_140_000)
        assert r.hedge_contracts < 5

    def test_invalid(self):
        assert beta_hedge_contracts(10_000_000, 1.2, 0) is None
