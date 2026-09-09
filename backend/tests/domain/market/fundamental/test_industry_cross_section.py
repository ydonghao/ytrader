"""行业截面纯函数测试。模式抄 test_ratio_analysis.py：dict 字面量 + pytest.approx。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.domain.market.fundamental.industry_cross_section import (
    cross_section_metrics,
)


def _peer(symbol, revenue, net_profit=1.0, gross_margin=30.0,
          net_margin=10.0, roe=12.0):
    return {"symbol": symbol, "revenue": revenue, "net_profit": net_profit,
            "gross_margin": gross_margin, "net_margin": net_margin, "roe": roe}


# 5 家公司：营收 [50,30,10,5,5]，总营收 100
PEERS5 = [
    _peer("a", 50.0, gross_margin=50.0),
    _peer("b", 30.0, gross_margin=40.0),
    _peer("c", 10.0, gross_margin=30.0),
    _peer("d", 5.0, gross_margin=20.0),
    _peer("e", 5.0, gross_margin=10.0),
]


class TestCrossSectionMetrics:

    def test_concentration_hand_computed(self):
        """CR4=0.95, CR8=1.0, HHI=(.25+.09+.01+.0025+.0025)*10000=3550。"""
        m = cross_section_metrics(PEERS5)
        assert m["sample_count"] == 5
        assert m["revenue_sum"] == pytest.approx(100.0)
        assert m["cr4"] == pytest.approx(0.95)
        assert m["cr8"] == pytest.approx(1.0)
        assert m["hhi"] == pytest.approx(3550.0)

    def test_distribution_hand_computed(self):
        """gross_margin [10,20,30,40,50]：mean=30 median=30 p25=20 p75=40。"""
        d = cross_section_metrics(PEERS5)["distribution"]["gross_margin"]
        assert d["mean"] == pytest.approx(30.0)
        assert d["median"] == pytest.approx(30.0)
        assert d["p25"] == pytest.approx(20.0)
        assert d["p75"] == pytest.approx(40.0)
        assert d["std"] == pytest.approx(15.8114, abs=1e-3)

    def test_none_metric_excluded_but_kept_in_concentration(self):
        """毛利率 None 的股票从分布剔除，但仍计入营收/集中度。"""
        peers = [
            _peer("a", 50.0, gross_margin=None),
            _peer("b", 30.0, gross_margin=40.0),
            _peer("c", 10.0, gross_margin=20.0),
            _peer("d", 5.0, gross_margin=10.0),
        ]
        m = cross_section_metrics(peers)
        assert m["sample_count"] == 4
        d = m["distribution"]["gross_margin"]
        assert d["mean"] == pytest.approx(23.3333, abs=1e-3)  # 3 家
        assert m["cr4"] == pytest.approx(1.0)

    def test_revenue_none_row_dropped(self):
        peers = PEERS5 + [_peer("f", None)]
        assert cross_section_metrics(peers)["sample_count"] == 5

    def test_small_sample_all_none(self):
        """sample_count < 4 → 集中度与分布全 None。"""
        m = cross_section_metrics(PEERS5[:3])
        assert m["sample_count"] == 3
        assert m["cr4"] is None and m["cr8"] is None and m["hhi"] is None
        assert m["distribution"]["gross_margin"] is None

    def test_empty_peers(self):
        m = cross_section_metrics([])
        assert m["sample_count"] == 0
        assert m["revenue_sum"] is None and m["cr4"] is None

    def test_net_profit_sum_skips_none(self):
        peers = [
            _peer("a", 50.0, net_profit=None),
            _peer("b", 30.0, net_profit=3.0),
            _peer("c", 10.0, net_profit=-1.0),
            _peer("d", 5.0, net_profit=None),
        ]
        m = cross_section_metrics(peers)
        assert m["net_profit_sum"] == pytest.approx(2.0)  # 全 None 剔除后求和


import datetime as dt

from src.domain.market.fundamental.industry_cross_section import (
    attach_yoy,
    peer_ranks,
)


class TestAttachYoy:

    def _sections(self):
        return [
            {"report_date": "2023-12-31", "revenue_sum": 80.0},
            {"report_date": "2024-12-31", "revenue_sum": 100.0},
            {"report_date": "2025-12-31", "revenue_sum": 120.0},
        ]

    def test_yoy_chain(self):
        out = attach_yoy(self._sections())
        assert out[0]["revenue_yoy"] is None          # 首期无去年同期
        assert out[1]["revenue_yoy"] == pytest.approx(0.25)
        assert out[2]["revenue_yoy"] == pytest.approx(0.20)

    def test_quarter_matches_same_period_only(self):
        """2025-09-30 的同比期是 2024-09-30，不是相邻年报。"""
        secs = [
            {"report_date": "2024-09-30", "revenue_sum": 50.0},
            {"report_date": "2024-12-31", "revenue_sum": 90.0},
            {"report_date": "2025-09-30", "revenue_sum": 60.0},
        ]
        out = attach_yoy(secs)
        assert out[2]["revenue_yoy"] == pytest.approx(0.20)

    def test_base_le_zero_or_missing(self):
        secs = [
            {"report_date": "2024-12-31", "revenue_sum": 0.0},
            {"report_date": "2025-12-31", "revenue_sum": 10.0},
        ]
        assert attach_yoy(secs)[1]["revenue_yoy"] is None

    def test_date_object_and_none_revenue(self):
        secs = [
            {"report_date": dt.date(2024, 12, 31), "revenue_sum": None},
            {"report_date": dt.date(2025, 12, 31), "revenue_sum": 10.0},
        ]
        assert attach_yoy(secs)[1]["revenue_yoy"] is None


class TestPeerRanks:

    PEERS = [
        {"symbol": "sh600519", "name": "贵州茅台", "revenue": 170.0,
         "gross_margin": 91.6, "roe": 34.0},
        {"symbol": "sz000858", "name": "五粮液", "revenue": 90.0,
         "gross_margin": 75.0, "roe": 22.0},
        {"symbol": "sh603369", "name": "今世缘", "revenue": 100.0,
         "gross_margin": 75.0, "roe": 20.0},
        {"symbol": "sz000568", "name": "泸州老窖", "revenue": 30.0,
         "gross_margin": 88.0, "roe": None},
    ]

    def test_ranks_descending_with_ties(self):
        out = peer_ranks(self.PEERS, "sh600519")["peers"]
        by = {p["symbol"]: p for p in out}
        assert by["sh600519"]["rank_revenue"] == 1
        assert by["sh603369"]["rank_revenue"] == 2
        # 毛利率排序：茅台 91.6 第 1；泸州老窖 88.0 第 2；两家 75.0 并列第 3
        assert by["sz000568"]["rank_gross_margin"] == 2
        assert by["sz000858"]["rank_gross_margin"] == 3
        assert by["sh603369"]["rank_gross_margin"] == 3

    def test_target_percentile_and_share(self):
        out = peer_ranks(self.PEERS, "sh600519")
        t = out["target"]
        # 毛利率 91.6 全行业最高（4 家全有值）→ 1.0
        assert t["percentile_gross_margin"] == pytest.approx(1.0)
        # ROE 有效样本 3 家，茅台 34.0 最高 → 1.0
        assert t["percentile_roe"] == pytest.approx(1.0)
        # 营收份额 170/390（派生值按模块惯例 _r4 保留 4 位 → 0.4359）
        assert t["revenue_share"] == pytest.approx(170.0 / 390.0, abs=1e-4)

    def test_target_absent(self):
        out = peer_ranks(self.PEERS, "hk00700")
        assert out["target"] is None
        assert len(out["peers"]) == 4
