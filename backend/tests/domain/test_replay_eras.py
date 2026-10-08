"""eras.pools 纯函数测试 — 构造序列驱动,不碰 DB。"""

import datetime as dt

from src.domain.replay.eras import pools, thin


def _series(path: list[float], lens: list[int] | None = None,
            start: str = "2005-01-03") -> list[tuple]:
    """path: 分段终点值;lens: 每段点数(默认每段20),段内线性插值、逐日一bar。"""
    out = []
    d = dt.date.fromisoformat(start)
    prev = path[0]
    for j, v in enumerate(path[1:]):
        n = lens[j] if lens is not None else 20
        for k in range(1, n + 1):
            out.append((d, prev + (v - prev) * k / n))
            d += dt.timedelta(days=1)
        prev = v
    return out


# 段长: 前250平(垫满回看窗基准) + 100主升/主跌 + 40顶/底横盘 + 120崩/反弹 + 120尾
LENS = [250, 100, 40, 120, 120]


class TestPools:
    def test_bull_top_after_rally_before_crash(self):
        # 涨100%后横盘,随后120日崩40%:崩前顶段应入牛顶池
        s = _series([100, 100, 200, 200, 120, 120], lens=LENS)  # 平→涨→横→崩→平尾
        ps = pools(s)
        assert ps["bull_top"], "牛顶池不应为空"

    def test_bear_bottom_after_decline_before_rebound(self):
        # 跌50%后横盘,随后120日反弹40%:反弹前底段应入熊底池
        s = _series([200, 200, 100, 100, 140, 140], lens=LENS)  # 平→跌→横→反弹→平尾
        ps = pools(s)
        assert ps["bear_bottom"], "熊底池不应为空"

    def test_short_series_empty(self):
        assert pools([(dt.date(2020, 1, 1), 1.0)]) == {
            "bull_top": [], "bear_bottom": [], "range": []}

    def test_thin_gap(self):
        ds = [dt.date(2020, 1, 1) + dt.timedelta(days=i * 10)
              for i in range(10)]
        out = thin(ds, gap=60)
        assert out[0] == ds[0]
        assert all((b - a).days >= 60 for a, b in zip(out, out[1:]))
