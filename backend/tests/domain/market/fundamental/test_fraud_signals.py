"""财务造假红旗检测纯函数测试。"""
import pytest

from src.domain.market.fundamental.fraud_signals import (
    revenue_receivable_divergence,
    profit_cashflow_divergence,
    inventory_anomaly,
    gross_margin_swing,
    detect_fraud_red_flags,
)


class TestRevenueReceivableDivergence:
    def test_triggered_channel_stuffing(self):
        # 营收+10%, 应收+30% → 差 20% >= 10%
        curr = {"revenue": 110, "accounts_receivable": 130}
        prev = {"revenue": 100, "accounts_receivable": 100}
        r = revenue_receivable_divergence(curr, prev)
        assert r.triggered is True

    def test_healthy_aligned(self):
        curr = {"revenue": 110, "accounts_receivable": 108}
        prev = {"revenue": 100, "accounts_receivable": 100}
        r = revenue_receivable_divergence(curr, prev)
        assert r.triggered is False

    def test_insufficient_data(self):
        r = revenue_receivable_divergence({"revenue": 100}, {"revenue": 100})
        assert r.triggered is False


class TestProfitCashflowDivergence:
    def test_profit_up_ocf_down(self):
        curr = {"net_profit": 120, "ocf": 80}
        prev = {"net_profit": 100, "ocf": 100}
        r = profit_cashflow_divergence(curr, prev)
        assert r.triggered is True

    def test_low_ocf_ratio(self):
        # 净利 100, OCF 30 → ratio 0.3 < 0.5
        curr = {"net_profit": 100, "ocf": 30}
        prev = {"net_profit": 90, "ocf": 28}
        r = profit_cashflow_divergence(curr, prev)
        assert r.triggered is True

    def test_healthy(self):
        curr = {"net_profit": 120, "ocf": 130}
        prev = {"net_profit": 100, "ocf": 110}
        r = profit_cashflow_divergence(curr, prev)
        assert r.triggered is False


class TestInventoryAnomaly:
    def test_stockpiling(self):
        curr = {"revenue": 110, "inventory": 140}
        prev = {"revenue": 100, "inventory": 100}
        # 存货+40%, 营收+10% → 差 30% >=15%
        r = inventory_anomaly(curr, prev)
        assert r.triggered is True

    def test_normal(self):
        curr = {"revenue": 110, "inventory": 112}
        prev = {"revenue": 100, "inventory": 100}
        r = inventory_anomaly(curr, prev)
        assert r.triggered is False


class TestGrossMarginSwing:
    def test_big_swing_triggered(self):
        curr = {"gross_margin": 0.50}
        prev = {"gross_margin": 0.40}
        r = gross_margin_swing(curr, prev)
        assert r.triggered is True  # +10pp > 5pp

    def test_stable(self):
        curr = {"gross_margin": 0.41}
        prev = {"gross_margin": 0.40}
        r = gross_margin_swing(curr, prev)
        assert r.triggered is False

    def test_from_profit_ratio(self):
        # 无 gross_margin 字段，用 gross_profit/revenue
        curr = {"gross_profit": 50, "revenue": 100}
        prev = {"gross_profit": 30, "revenue": 100}
        r = gross_margin_swing(curr, prev)
        assert r.triggered is True


class TestDetectFraudRedFlags:
    def test_clean_company(self):
        periods = [
            {"revenue": 100, "accounts_receivable": 100, "net_profit": 20,
             "ocf": 25, "inventory": 50, "gross_margin": 0.40},
            {"revenue": 110, "accounts_receivable": 105, "net_profit": 24,
             "ocf": 30, "inventory": 52, "gross_margin": 0.41},
        ]
        rep = detect_fraud_red_flags(periods)
        assert rep.severity == "clean"
        assert rep.triggered_count == 0

    def test_high_risk_company(self):
        # 多项红旗同时触发
        periods = [
            {"revenue": 100, "accounts_receivable": 100, "net_profit": 20,
             "ocf": 25, "inventory": 50, "gross_margin": 0.40},
            {"revenue": 110, "accounts_receivable": 140, "net_profit": 30,
             "ocf": 15, "inventory": 80, "gross_margin": 0.50},
        ]
        rep = detect_fraud_red_flags(periods)
        assert rep.severity == "high_risk"
        assert rep.triggered_count >= 2

    def test_single_flag_watch(self):
        periods = [
            {"revenue": 100, "accounts_receivable": 100, "net_profit": 20,
             "ocf": 25, "inventory": 50, "gross_margin": 0.40},
            {"revenue": 110, "accounts_receivable": 140, "net_profit": 24,
             "ocf": 30, "inventory": 52, "gross_margin": 0.41},
        ]
        # 仅应收背离触发
        rep = detect_fraud_red_flags(periods)
        assert rep.severity == "watch"
        assert rep.triggered_count == 1

    def test_insufficient_periods(self):
        rep = detect_fraud_red_flags([{"revenue": 100}])
        assert rep.severity == "clean"
        assert any(f.name == "insufficient_data" for f in rep.red_flags)
