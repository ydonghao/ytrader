"""类比估值法（可比公司乘数截面）纯函数测试。"""
import pytest

from src.domain.market.fundamental.comps import (
    comps_valuation,
    multiple_stats,
)


def _peer(sym, pe, pb, ps=1.5, dv=1.0, mv=100.0):
    return {
        "symbol": sym, "name": sym,
        "pe_ttm": pe, "pb": pb, "ps_ttm": ps,
        "dv_ttm": dv, "total_mv": mv,
    }


PEERS = [
    _peer("a", 10, 2.0, mv=100),
    _peer("b", 12, 3.0, mv=200),
    _peer("c", 14, 4.0, mv=300),
    _peer("d", 16, 5.0, mv=400),
    _peer("t", 20, 6.0, mv=500),  # 目标股
]


class TestMultipleStats:
    def test_basic(self):
        r = multiple_stats([10, 12, 14, 16])
        assert r["count"] == 4
        assert r["median"] == 13
        assert r["mean"] == 13

    def test_too_few(self):
        assert multiple_stats([10]) is None
        assert multiple_stats([]) is None

    def test_non_numeric_filtered(self):
        r = multiple_stats([10, None, "x", 20, True])
        assert r["count"] == 2


class TestCompsValuation:
    def test_target_missing(self):
        r = comps_valuation(PEERS[:4], "zzz")
        assert r["target_found"] is False
        assert r["multiples"] == {}

    def test_pe_stats(self):
        # 同行 PE = [10,12,14,16] → median=13；目标 20 → 高估
        r = comps_valuation(PEERS, "t")
        pe = r["multiples"]["pe_ttm"]
        assert pe["median"] == 13
        assert pe["own"] == 20
        # implied = 500 × 13/20 = 325
        assert pe["implied_value"] == pytest.approx(325.0)
        assert pe["upside"] == pytest.approx(13 / 20 - 1, abs=1e-4)

    def test_negative_pe_excluded(self):
        peers = [
            _peer("a", 10, 2.0), _peer("b", -5, 3.0),
            _peer("c", 14, 4.0), _peer("d", None, 5.0),
            _peer("t", 12, 3.5),
        ]
        r = comps_valuation(peers, "t")
        pe = r["multiples"]["pe_ttm"]
        # 只有 10/14 两家有效 PE → count=2
        assert pe["count"] == 2
        assert pe["median"] == 12

    def test_own_invalid(self):
        peers = [
            _peer("a", 10, 2.0), _peer("b", 12, 3.0),
            _peer("c", 14, 4.0), _peer("d", 16, 5.0),
            _peer("t", -3, 6.0),  # 目标亏损
        ]
        r = comps_valuation(peers, "t")
        pe = r["multiples"]["pe_ttm"]
        assert pe["own_valid"] is False
        assert pe["own"] is None
        assert pe["implied_value"] is None
        assert pe["upside"] is None

    def test_min_peers_guard(self):
        # 同行仅 3 家（< 默认 4）→ 统计降级为 None
        peers = [
            _peer("a", 10, 2.0), _peer("b", 12, 3.0),
            _peer("c", 14, 4.0), _peer("t", 20, 6.0, mv=500),
        ]
        r = comps_valuation(peers, "t")
        pe = r["multiples"]["pe_ttm"]
        assert pe["median"] is None
        assert pe["upside"] is None
        # rank 仍然可算（3 家均 <= 20）
        assert pe["rank_pct"] == 1.0

    def test_rank_pct(self):
        # PE 同行 [10,12,14,16]，own=14 → 3/4
        r = comps_valuation(PEERS, "t")  # own=20 → 4/4
        assert r["multiples"]["pe_ttm"]["rank_pct"] == 1.0
        peers = PEERS.copy()
        peers[4] = _peer("t", 13, 6.0, mv=500)
        r2 = comps_valuation(peers, "t")
        assert r2["multiples"]["pe_ttm"]["rank_pct"] == pytest.approx(
            0.5
        )

    def test_dv_zero_valid(self):
        peers = [
            _peer("a", 10, 2.0, dv=0), _peer("b", 12, 3.0, dv=2),
            _peer("c", 14, 4.0, dv=4), _peer("d", 16, 5.0, dv=6),
            _peer("t", 13, 3.5, dv=0),
        ]
        r = comps_valuation(peers, "t")
        dv = r["multiples"]["dv_ttm"]
        assert dv["own_valid"] is True
        assert dv["own"] == 0
        assert dv["median"] == 3  # [0,2,4,6] 的中位数
