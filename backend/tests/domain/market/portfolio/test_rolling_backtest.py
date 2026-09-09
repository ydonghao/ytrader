"""滚动窗口累计收益单测。"""
from datetime import date

import pytest

from src.domain.market.portfolio.rolling_backtest import (
    calc_rolling_returns,
    _add_months,
    _month_iter,
)


class TestRollingBacktest:
    """滚动窗口累计收益计算测试。"""

    def test_add_months(self):
        assert _add_months(date(2020, 1, 15), 12) == date(2021, 1, 15)
        assert _add_months(date(2020, 1, 15), 1) == date(2020, 2, 15)
        assert _add_months(date(2020, 11, 15), 3) == date(2021, 2, 15)

    def test_month_iter(self):
        months = list(_month_iter(date(2020, 1, 1), date(2020, 3, 1)))
        assert len(months) == 3
        assert months[0] == date(2020, 1, 1)
        assert months[-1] == date(2020, 3, 1)

    def test_single_symbol_rising(self):
        """单标的持续上涨, 每个窗口收益都为正。"""
        # 构造 sh510300 从 2020-01 每月初涨 1%
        prices = {}
        p = 10.0
        import datetime as dt
        for i in range(24):  # 2年
            m = date(2020, 1, 1) + dt.timedelta(days=i * 30)
            prices[m] = round(p, 4)
            p *= 1.01

        results = calc_rolling_returns(
            prices_by_symbol={"sh510300": prices},
            target_weights={"sh510300": 1.0},
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 1),
            window_months=3,
        )
        assert len(results) >= 10  # 12 个月能滚 ~12 个 3 月窗口
        # 持续上涨, 每个窗口收益应 > 0
        for r in results:
            assert r.return_pct > 0

    def test_multi_symbol_weighted(self):
        """两标的加权: 一涨一跌。"""
        import datetime as dt
        prices_a = {date(2020, 1, 1): 10.0, date(2020, 7, 1): 12.0}  # +20%
        prices_b = {date(2020, 1, 1): 10.0, date(2020, 7, 1): 8.0}   # -20%

        results = calc_rolling_returns(
            prices_by_symbol={"A": prices_a, "B": prices_b},
            target_weights={"A": 0.5, "B": 0.5},
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 1),
            window_months=6,
        )
        assert len(results) == 1
        # 加权: 0.5×20% + 0.5×(-20%) = 0
        assert results[0].return_pct == pytest.approx(0, abs=0.1)

    def test_missing_data_skipped(self):
        """某窗口完全无数据 → 该窗口被跳过。"""
        results = calc_rolling_returns(
            prices_by_symbol={},  # 空价格
            target_weights={"X": 1.0},
            start_date=date(2020, 1, 1),
            end_date=date(2020, 6, 1),
            window_months=3,
        )
        assert results == []

    def test_window_format(self):
        """结果格式: start/end 为 YYYY-MM。"""
        prices = {date(2020, 1, 15): 10.0, date(2021, 1, 15): 11.0}
        results = calc_rolling_returns(
            prices_by_symbol={"X": prices},
            target_weights={"X": 1.0},
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 1),
            window_months=12,
        )
        if results:
            assert "-" in results[0].start
            assert len(results[0].start) == 7  # YYYY-MM
