"""synthetic.segments 纯函数测试 — 不碰 DB。"""

import pytest

from src.domain.replay.synthetic import SEG_COUNT, segments

BAR = {"open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5,
       "volume": 1000, "amount": 10000.0}


class TestSegments:
    def test_shape_and_continuity(self):
        segs = segments("sh600519", "2020-03-13", BAR, seed="42")
        assert len(segs) == SEG_COUNT
        assert segs[0]["open"] == pytest.approx(BAR["open"], abs=0.01)
        assert segs[-1]["close"] == pytest.approx(BAR["close"], abs=0.01)
        for k in range(SEG_COUNT - 1):
            assert segs[k + 1]["open"] == pytest.approx(segs[k]["close"])
        for s in segs:
            assert s["low"] <= s["open"] <= s["high"]
            assert s["low"] <= s["close"] <= s["high"]

    def test_bounded_and_reaches_extremes(self):
        for seed in ("a", "b", "c", "d"):
            segs = segments("sh600519", "2020-03-13", BAR, seed=seed)
            assert min(s["low"] for s in segs) == pytest.approx(BAR["low"], abs=0.01)
            assert max(s["high"] for s in segs) == pytest.approx(BAR["high"], abs=0.01)
            for s in segs:
                assert BAR["low"] - 0.01 <= s["low"]
                assert s["high"] <= BAR["high"] + 0.01

    def test_deterministic(self):
        a = segments("sz000001", "2018-01-02", BAR, seed="7")
        b = segments("sz000001", "2018-01-02", BAR, seed="7")
        c = segments("sz000001", "2018-01-03", BAR, seed="7")
        assert a == b
        assert a != c  # 不同日期路径应不同(连续价格抖动,概率上必然)

    def test_one_price_day_degrades_flat(self):
        bar = {"open": 5.0, "high": 5.0, "low": 5.0, "close": 5.0,
               "volume": 1, "amount": 5.0}
        segs = segments("sh600519", "2020-03-13", bar, seed="1")
        for s in segs:
            assert s == {"open": 5.0, "high": 5.0, "low": 5.0, "close": 5.0}

    @pytest.mark.parametrize("bad", [
        {"open": None, "high": 11, "low": 9, "close": 10},
        {"open": 10, "high": 9, "low": 9.5, "close": 10},   # h < l
        {"open": 12, "high": 11, "low": 9.5, "close": 10},  # open 越界
        {"open": 10, "high": 11, "low": 9.5},               # 缺 close
    ])
    def test_bad_bar_flat_close(self, bad):
        segs = segments("sh600519", "2020-03-13", bad, seed="1")
        c = float(bad.get("close") or 0)
        assert segs == [{"open": c, "high": c, "low": c, "close": c}
                        for _ in range(SEG_COUNT)]
