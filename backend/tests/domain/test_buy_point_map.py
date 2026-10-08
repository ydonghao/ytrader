"""P1 历史买点地图纯函数测试。"""
import datetime as dt

from src.domain.market.fundamental.buy_point_map import (
    buy_point_map,
    dividend_tax,
)


def _mk(days, start_pe=10.0):
    """构造 days 天: PE 在 10 附近, 价格每年涨 ~10%。"""
    val, px = [], []
    base = dt.date(2020, 1, 1)
    p = 100.0
    for i in range(days):
        d = base + dt.timedelta(days=i)
        pe = 10.0 + (0.5 if i % 7 == 0 else 0)   # 10±5% 带内
        val.append({"trade_date": d, "pe_ttm": pe})
        px.append({"trade_date": d, "close": p})
        p *= 1.0004
    return val, px


def test_buy_point_map_distribution():
    val, px = _mk(1500)
    out = buy_point_map(val, px, metric="pe_ttm",
                        current_value=10.2, band=0.05,
                        horizons=[20, 60])
    assert out["sample_count"] > 100
    h20 = out["by_horizon"]["20"]
    assert h20["n"] > 50
    assert h20["win_rate"] > 90        # 单调上涨序列 → 几乎全胜
    assert h20["avg_pct"] > 0
    assert "p10" in h20 and "p90" in h20


def test_buy_point_map_no_match():
    val, px = _mk(100)
    out = buy_point_map(val, px, metric="pe_ttm",
                        current_value=100.0, band=0.05)
    assert out["sample_count"] == 0
    assert out["by_horizon"]["252"]["n"] == 0


def test_dividend_tax_tiers():
    buy = dt.date(2026, 1, 10)
    assert dividend_tax(buy, dt.date(2026, 2, 1))[
        "rate_pct"] == 20            # <1月
    assert dividend_tax(buy, dt.date(2026, 3, 1))[
        "rate_pct"] == 10            # 1月-1年
    assert dividend_tax(buy, dt.date(2026, 12, 1))[
        "rate_pct"] == 10
    out = dividend_tax(buy, dt.date(2027, 6, 1))
    assert out["rate_pct"] == 0       # ≥1年 免税
    assert out["free_after"] == "2027-01-10"
