"""假设版本化：compare_dcf_versions 纯函数 + 仓储 + 端点测试。"""
import sys
import os
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from src.domain.market.fundamental.dcf import compare_dcf_versions  # noqa: E402


def test_price_fell_fundamentals_intact():
    """内在价值没动、市值跌 30% → 情绪驱动（市场送安全边际）。"""
    then = {"intrinsic_value": 100.0, "market_value": 90.0,
            "margin_of_safety": 0.11, "fcf_base": 5.0,
            "report_date": "2025-12-31"}
    now = {"intrinsic_value": 101.0, "market_value": 63.0,
           "margin_of_safety": 0.60, "fcf_base": 5.05,
           "report_date": "2026-06-30"}
    out = compare_dcf_versions(then, now)
    assert out["intrinsic_delta_pct"] == 1.0
    assert out["market_delta_pct"] == -30.0
    assert "情绪驱动" in out["driver"] and "下跌" in out["driver"]


def test_fundamentals_deteriorated():
    """FCF 下滑带崩内在价值、价格没跌 → 判断依据已变。"""
    then = {"intrinsic_value": 100.0, "market_value": 70.0,
            "fcf_base": 5.0}
    now = {"intrinsic_value": 60.0, "market_value": 69.0,
           "fcf_base": 3.0}
    out = compare_dcf_versions(then, now)
    assert out["intrinsic_delta_pct"] == -40.0
    assert out["market_delta_pct"] == -1.43
    assert out["driver"].startswith("透支")   # 价格相对基本面太坚挺


def test_margin_gifted_by_market():
    """基本面改善 20% 但价格反跌 → 跌出安全边际。"""
    then = {"intrinsic_value": 100.0, "market_value": 100.0,
            "fcf_base": 5.0}
    now = {"intrinsic_value": 120.0, "market_value": 85.0,
           "fcf_base": 6.0}
    out = compare_dcf_versions(then, now)
    assert out["driver"].startswith("跌出安全边际")


def test_missing_data_tolerated():
    out = compare_dcf_versions({}, {"intrinsic_value": 100.0})
    assert out["intrinsic_delta_pct"] is None
    assert out["market_delta_pct"] is None
    assert out["driver"] == "数据不足"
