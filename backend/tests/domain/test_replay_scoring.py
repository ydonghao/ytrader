"""scoring.score 纯函数测试 — 手算锚定。"""

import pytest

from src.domain.replay.scoring import score


def _nav(values, cash=None, pos=None):
    out = []
    for i, v in enumerate(values):
        p = {"date": f"2020-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}",
             "value": v}
        if cash is not None:
            p["cash"] = cash(v)
        if pos is not None:
            p["pos"] = pos(v)
        out.append(p)
    return out


# 第二根基准 bar 须落在 nav 窗口内(本助手 _nav 日期止于 2020-09-11),
# 否则被窗口过滤,基准年化=0,超额锚定 7.98 不成立
BENCH = [{"trade_date": "2020-01-01", "close": 100.0},
         {"trade_date": "2020-09-11", "close": 102.0}]


class TestScore:
    def test_requires_two_nav_points(self):
        with pytest.raises(ValueError):
            score([{"date": "2020-01-01", "value": 100.0}], BENCH, [],
                  100.0)

    def test_excess_and_turnover_hand_computed(self):
        # 250个交易日:10万→11万(年化≈+10%),基准100→102(年化+2.02%附近)
        nav = _nav([100000 + i * 40 for i in range(251)])  # 终值11万
        # 换手:买卖各一笔 10万/11万,平均NAV≈10.5万 → raw=1.0 → 年化≈1.0x → 满20
        trades = [
            {"symbol": "a", "side": "buy", "price": 10.0, "shares": 10000},
            {"symbol": "a", "side": "sell", "price": 11.0, "shares": 10000},
        ]
        r = score(nav, BENCH, trades, 100000.0)
        # 年化超额 ≈ 10% − 2.02% ≈ 7.98 → 超额分 = min(40+8×7.98, 80) = 80
        assert r["excess_score"] == 80.0
        assert r["turnover_score"] == 20.0
        assert r["total"] == 100.0
        assert r["annual_excess_pct"] == pytest.approx(7.98, abs=0.2)

    def test_negative_excess_floors_at_zero(self):
        nav = _nav([100 - i * 0.04 for i in range(251)])  # 亏钱
        r = score(nav, BENCH, [], 100.0)
        assert r["excess_score"] == 0.0
        assert r["turnover_score"] == 20.0  # 无交易满纪律分

    def test_high_turnover_zero_discipline(self):
        nav = _nav([100 + i * 0.04 for i in range(251)])
        trades = [{"symbol": "a", "side": "buy", "price": 10.0,
                   "shares": 100000}] * 30  # 年化换手 >10x
        r = score(nav, BENCH, trades, 100.0)
        assert r["turnover_score"] == 0.0

    def test_disclosures(self):
        nav = _nav([100, 120, 90], cash=lambda v: v / 2,
                   pos=lambda v: {"a": v / 2})
        trades = [
            {"symbol": "a", "side": "buy", "price": 10.0, "shares": 100},
            {"symbol": "a", "side": "sell", "price": 12.0, "shares": 100},
        ]
        d = score(nav, BENCH, trades, 100.0)["disclosures"]
        assert d["closed_win_rate"] == 1.0
        assert d["closed_trips"] == 1
        assert d["max_drawdown"] == pytest.approx(1 - 90 / 120)
        assert d["avg_cash_ratio"] == pytest.approx(0.5)
        assert d["max_position_weight"] == pytest.approx(0.5)
