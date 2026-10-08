# backend/tests/domain/market/industry_analysis/test_stats.py
from src.domain.market.industry_analysis.stats import (
    histogram, median, percentile_rank,
)


def test_percentile_rank_midrank():
    assert percentile_rank(3.0, [1.0, 2.0, 3.0, 4.0, 5.0]) == 50.0
    assert percentile_rank(5.0, [1.0, 2.0, 3.0]) == 100.0
    assert percentile_rank(0.5, [1.0, 2.0]) == 0.0
    # 并列取中位:两个 2.0 在 [1,2,2,3] → (1 + 0.5*2)/4 = 50%
    assert percentile_rank(2.0, [1.0, 2.0, 2.0, 3.0]) == 50.0


def test_percentile_rank_degenerate():
    assert percentile_rank(None, [1.0]) is None
    assert percentile_rank(1.0, []) is None
    assert percentile_rank(1.0, [1.0]) == 50.0   # midrank:单值取中位


def test_median():
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert median([4.0, 1.0, 2.0, 3.0]) == 2.5
    assert median([]) is None


def test_histogram():
    h = histogram([1, 2, 3, 4, 5], bins=4)
    assert len(h["counts"]) == 4
    assert sum(h["counts"]) == 5
    assert h["counts"] == [1, 1, 1, 2]   # 5 落入最后一桶(右端闭合)
    # 过滤越界与 None
    h2 = histogram([1, 2, 3, None, 99], bins=2, lo=0, hi=4)
    assert sum(h2["counts"]) == 3
