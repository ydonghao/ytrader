"""kline_trend 纯函数测试(买入体检 4.4)。"""
from src.domain.market.fundamental.kline_trend import (
    sma, ols_slope, trend_state,
)


class TestSma:
    def test_basic(self):
        assert sma([1.0, 2.0, 3.0, 4.0], 2) == 3.5  # 末2均值

    def test_insufficient(self):
        assert sma([1.0, 2.0], 3) is None


class TestOlsSlope:
    def test_uptrend_positive(self):
        assert ols_slope([1.0, 2.0, 3.0, 4.0]) > 0

    def test_downtrend_negative(self):
        assert ols_slope([4.0, 3.0, 2.0, 1.0]) < 0

    def test_flat_zero(self):
        assert abs(ols_slope([2.0, 2.0, 2.0])) < 1e-9

    def test_short(self):
        assert ols_slope([1.0]) is None


def _mk_closes(trend: str, n: int = 200) -> list[float]:
    """构造趋势序列:上升=等差上行,下降=等差下行,横盘=围绕均值波动。"""
    base = [float(i) for i in range(1, n + 1)]        # 1,2,...,200 上升
    if trend == "上升":
        return base
    if trend == "下降":
        return base[::-1]
    return [100.0 + (1.0 if i % 2 else -1.0) for i in range(n)]  # 横盘


class TestTrendState:
    def test_uptrend(self):
        r = trend_state(_mk_closes("上升"))
        assert r is not None and r["state"] == "上升"
        assert r["ma20"] > r["ma60"] > r["ma120"]

    def test_downtrend(self):
        r = trend_state(_mk_closes("下降"))
        assert r is not None and r["state"] == "下降"

    def test_sideways(self):
        r = trend_state(_mk_closes("横盘"))
        assert r is not None and r["state"] == "横盘"

    def test_insufficient_data(self):
        assert trend_state([1.0] * 119) is None

    def test_slope_pct_scale(self):
        # 200日从1涨到200,日均涨幅远超阈值 → slope_pct > 0
        r = trend_state(_mk_closes("上升"))
        assert r["slope_pct"] > 0
