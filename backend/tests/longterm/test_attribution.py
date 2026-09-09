"""回测归因单测：合成已知权重+收益验证贡献分解。"""
import datetime as dt

import pytest

from src.domain.market.sync.sync_provider import OHLCVBar
from src.domain.market.strategy.longterm.attribution import (
    classify_sector,
    compute_attribution,
)


def _bars(sym, prices):
    """从价格序列造 bars（每日一根）。"""
    out = []
    for i, p in enumerate(prices):
        out.append(OHLCVBar(
            symbol=sym, trade_time=dt.datetime(2020, 1, 1) + dt.timedelta(days=i),
            open_=p, close_=p, high_=p, low_=p, volume=1000.0,
        ))
    return out


class TestClassifySector:
    def test_etf_and_tech(self):
        assert "ETF" in classify_sector("sh510300")
        assert "黄金" in classify_sector("sh518880")
        assert "科技创新" in classify_sector("sh688001")
        assert "科技" in classify_sector("sz002001")


class TestComputeAttribution:
    def test_contribution_sums_to_attributed(self):
        """两标的：权重各 0.5，一个涨 50% 一个涨 10% → 贡献 25+5=30。"""
        result = {
            "total_return_pct": 30.0,
            "rebalances": [
                {"date": "2020-01-01", "target_weights": {"a": 0.5, "b": 0.5}},
                {"date": "2020-06-01", "target_weights": {"a": 0.5, "b": 0.5}},
            ],
        }
        bars = {
            "a": _bars("a", [10, 15]),      # +50%
            "b": _bars("b", [10, 11]),      # +10%
        }
        attr = compute_attribution(result, bars)
        # a 贡献 0.5×50=25, b 贡献 0.5×10=5 → 合计 30
        assert attr["total_attributed_pct"] == pytest.approx(30.0, abs=0.1)
        contribs = {s["symbol"]: s["contribution_pct"] for s in attr["by_symbol"]}
        assert contribs["a"] == pytest.approx(25.0, abs=0.1)
        assert contribs["b"] == pytest.approx(5.0, abs=0.1)
        # 残差 ≈ 0（权重恒定，无漂移）
        assert abs(attr["residual_pct"]) < 0.5

    def test_overweight_winner_positive_allocation_effect(self):
        """超配赢家（a 涨50%, b 涨10%）：a 权重 0.8 > 等权 0.5 → 配置效应为正。"""
        result = {
            "total_return_pct": 42.0,
            "rebalances": [
                {"date": "2020-01-01", "target_weights": {"a": 0.8, "b": 0.2}},
            ],
        }
        bars = {"a": _bars("a", [10, 15]), "b": _bars("b", [10, 11])}
        attr = compute_attribution(result, bars)
        vse = attr["vs_equal_weight"]
        # 等权收益 = (50+10)/2 = 30；策略 = 0.8×50+0.2×10 = 42 → 超额 +12
        assert vse["equal_weight_return_pct"] == pytest.approx(30.0, abs=0.1)
        assert vse["strategy_attributed_pct"] == pytest.approx(42.0, abs=0.1)
        assert vse["excess_pct"] == pytest.approx(12.0, abs=0.1)
        assert vse["allocation_effect_pct"] > 0

    def test_sector_aggregation(self):
        result = {
            "total_return_pct": 0.0,
            "rebalances": [
                {"date": "2020-01-01",
                 "target_weights": {"sh510300": 0.5, "sh518880": 0.5}},
            ],
        }
        bars = {
            "sh510300": _bars("sh510300", [10, 12]),
            "sh518880": _bars("sh518880", [10, 11]),
        }
        attr = compute_attribution(result, bars)
        sectors = {s["sector"]: s for s in attr["by_sector"]}
        # ETF 与黄金两个不同行业
        assert len(attr["by_sector"]) == 2
        # 各行业 count=1，权重求和≈1
        total_w = sum(s["avg_weight"] for s in attr["by_sector"])
        assert total_w == pytest.approx(1.0, abs=0.01)

    def test_missing_price_data_handled(self):
        result = {
            "total_return_pct": 25.0,
            "rebalances": [
                {"date": "2020-01-01",
                 "target_weights": {"a": 0.5, "b": 0.5}},
            ],
        }
        bars = {"a": _bars("a", [10, 15])}  # b 无数据
        attr = compute_attribution(result, bars)
        b_entry = [s for s in attr["by_symbol"] if s["symbol"] == "b"]
        assert b_entry and b_entry[0]["period_return_pct"] is None
        assert b_entry[0]["note"] == "无价格数据"

    def test_empty_rebalances(self):
        """无 rebalance（如买入持有）→ 返回空结构不报错。"""
        attr = compute_attribution({"total_return_pct": 10.0}, {})
        assert attr["by_symbol"] == []
        assert attr["total_attributed_pct"] == 0.0

    def test_by_symbol_sorted_by_contribution(self):
        result = {
            "total_return_pct": 0.0,
            "rebalances": [
                {"date": "2020-01-01",
                 "target_weights": {"a": 0.5, "b": 0.5}},
            ],
        }
        bars = {"a": _bars("a", [10, 20]), "b": _bars("b", [10, 5])}
        attr = compute_attribution(result, bars)
        # a 正贡献大，排第一
        assert attr["by_symbol"][0]["symbol"] == "a"
        assert attr["by_symbol"][0]["contribution_pct"] > 0
