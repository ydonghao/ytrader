"""股息投影纯函数测试（二期F4）。"""
import datetime as dt

from src.domain.market.fundamental.dividend_projection import (
    dividend_projection,
)


def _div(year, month, day, dps):
    return {"ex_date": dt.date(year, month, day), "div_per_share": dps}


def test_projection_and_growth():
    today = dt.date(2026, 9, 27)
    # 近5个完整年度每年6月分红(最新完整年=2025), 3.0/3.3/3.6/4.0/4.4
    divs = [
        _div(2021, 6, 24, 3.0), _div(2022, 6, 30, 3.3),
        _div(2023, 6, 28, 3.6), _div(2024, 6, 27, 4.0),
        _div(2025, 6, 26, 4.4),
    ]
    out = dividend_projection(divs, shares=1000, today=today)
    # 年度每股: 2022..2026
    assert [y["dps_total"] for y in out["annual"]] == \
        [3.0, 3.3, 3.6, 4.0, 4.4]
    # 最近增速: 4.4/4.0-1 = 10%
    assert abs(out["latest_growth_pct"] - 10.0) < 1e-9
    # 未来12月: 最近年度 4.4 已于2026-06派过 → 下一笔2027-06, 按年增10%外推
    assert out["next_12m_amount"] == 1000 * 4.4 * 1.10
    assert out["monthly"][0]["month"] == "2027-06"


def test_no_dividends():
    out = dividend_projection([], shares=100, today=dt.date(2026, 9, 27))
    assert out["next_12m_amount"] is None


def test_multi_pay_per_year_scheduled_by_history():
    today = dt.date(2026, 9, 27)
    divs = [
        _div(2024, 1, 20, 1.0), _div(2024, 7, 20, 1.1),
        _div(2025, 1, 20, 1.1), _div(2025, 7, 20, 1.3),
    ]
    out = dividend_projection(divs, shares=100, today=today)
    # 最近完整年(2025)合计 2.4/股 vs 2024 2.1 → 增速 2.4/2.1
    months = [m["month"] for m in out["monthly"]]
    assert months == ["2027-01", "2027-07"]
    expected = 100 * 2.4 * (2.4 / 2.1)
    assert abs(out["next_12m_amount"] - expected) < 0.1


def test_incomplete_current_year_no_growth():
    today = dt.date(2026, 9, 27)
    # 2026 只有中报分红(年度不完整) → 不算增速、不外推
    divs = [
        _div(2024, 6, 28, 3.6), _div(2024, 12, 20, 0.0) or None,
        _div(2025, 6, 27, 4.0), _div(2025, 12, 18, 4.0),
        _div(2026, 6, 26, 4.4),
    ]
    divs = [d for d in divs if d]
    out = dividend_projection(divs, shares=100, today=today)
    assert out["latest_growth_pct"] is None
