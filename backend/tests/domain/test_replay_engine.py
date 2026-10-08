"""engine 纯函数测试 — fill.ts 语义 1:1 移植 + v3 新增,不碰 DB。"""

import pytest

from src.domain.replay.engine import (
    commission, dividend_tax_rate, limit_prices, price_limit_ratio,
    slippage, stamp_tax, try_fill_market,
)


class TestRules:
    def test_limit_ratio_by_board(self):
        assert price_limit_ratio("sh600519") == 0.10
        assert price_limit_ratio("sz300750") == 0.20
        assert price_limit_ratio("sz301001") == 0.20
        assert price_limit_ratio("sh688111") == 0.20
        assert price_limit_ratio("bj830799") == 0.30
        assert price_limit_ratio("sh600519", name="ST某某") == 0.05

    def test_limit_prices_round2(self):
        assert limit_prices(10.0, 0.1) == (11.0, 9.0)
        assert limit_prices(9.99, 0.1) == (10.99, 8.99)

    def test_fees(self):
        assert commission(100000) == 25.0
        assert commission(1000) == 5.0  # 最低 5 元
        assert stamp_tax(100000, "2023-08-28") == 50.0
        assert stamp_tax(100000, "2023-08-27") == 100.0  # 换挡前千1

    def test_slippage_deterministic_bounded(self):
        a = slippage("s1:sh600519:2020-03-13:3:buy")
        b = slippage("s1:sh600519:2020-03-13:3:buy")
        assert a == b
        assert 0 <= a <= 0.0015

    def test_dividend_tax_tiers(self):
        assert dividend_tax_rate("2019-01-01", "2020-06-01") == 0.0   # >1年
        assert dividend_tax_rate("2020-01-01", "2020-06-01") == 0.1   # 1月~1年
        assert dividend_tax_rate("2020-05-10", "2020-06-01") == 0.2   # <1月


class TestTryFillMarket:
    ORDER = {"symbol": "sh600519", "side": "buy", "shares": 100,
             "note": "测试", "order_type": "market"}

    def test_buy_ok_with_slippage(self):
        # 调用方已把滑点并入段价:10.0 * (1+0.001)
        r = try_fill_market(
            cash=1e6, positions=[], order=self.ORDER,
            seg_price=10.0 * 1.001, prev_close=10.0,
            name="贵州茅台", day="2020-03-13")
        assert r["ok"]
        price = r["trade"]["price"]
        assert price == pytest.approx(10.0 * 1.001, abs=0.01)
        expect_fee = max(5.0, round(price * 100 * 0.00025 * 100) / 100)
        assert r["cash"] == pytest.approx(1e6 - price * 100 - expect_fee,
                                          abs=0.01)
        assert r["positions"][0]["shares"] == 100
        assert r["positions"][0]["buy_date"] == "2020-03-13"

    def test_buy_rejects_limit_up(self):
        r = try_fill_market(1e6, [], self.ORDER, seg_price=11.0,
                            prev_close=10.0, name=None, day="2020-03-13")
        assert not r["ok"] and "涨停" in r["error"]

    def test_buy_lot_and_cash(self):
        assert not try_fill_market(1e6, [], {**self.ORDER, "shares": 150},
                                   10.0, 10.0, None, "2020-03-13")["ok"]
        assert not try_fill_market(1000.0, [], self.ORDER, 10.0, 10.0,
                                   None, "2020-03-13")["ok"]

    def test_sell_odd_lot_tax(self):
        pos = [{"symbol": "sh600519", "shares": 150, "cost_price": 9.0,
                "buy_date": "2020-03-12"}]
        order = {"symbol": "sh600519", "side": "sell", "shares": 50,
                 "note": None, "order_type": "market"}
        r = try_fill_market(0.0, pos, order, seg_price=10.0,
                            prev_close=10.0, name=None, day="2020-03-13")
        assert r["ok"]  # 卖出允许零股
        assert r["positions"][0]["shares"] == 100
        # 现金 = 10*50 - 佣金5 - 印花税 500*0.001=0.5(2020-03-13 为换挡前千1)
        assert r["cash"] == pytest.approx(500 - 5 - 0.5, abs=0.01)

    def test_sell_rejects_t1_same_day(self):
        pos = [{"symbol": "sh600519", "shares": 100, "cost_price": 9.0,
                "buy_date": "2020-03-13"}]
        order = {"symbol": "sh600519", "side": "sell", "shares": 100,
                 "note": None, "order_type": "market"}
        r = try_fill_market(0.0, pos, order, 10.0, 10.0, None,
                            "2020-03-13")
        assert not r["ok"] and "T+1" in r["error"]

    def test_sell_rejects_limit_down(self):
        pos = [{"symbol": "sh600519", "shares": 100, "cost_price": 9.0,
                "buy_date": "2020-03-12"}]
        order = {"symbol": "sh600519", "side": "sell", "shares": 100,
                 "note": None, "order_type": "market"}
        r = try_fill_market(0.0, pos, order, seg_price=8.9, prev_close=10.0,
                            name=None, day="2020-03-13")
        assert not r["ok"] and "跌停" in r["error"]


import copy

from src.domain.replay.engine import (
    cancel_day_pending, check_pending, freeze_amount, sellable_shares,
    try_place_limit,
)


def _state(cash=1e6, positions=None, pending=None, frozen=0.0):
    return {"cash": cash, "frozen_cash": frozen,
            "positions": positions or [], "pending_orders": pending or []}


class TestPlaceLimit:
    def test_buy_limit_freezes(self):
        st = _state()
        r = try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                                 "shares": 100, "limit_price": 10.0,
                                 "note": "x"}, 10.0, None, "2020-03-13")
        assert r["ok"]
        assert st["frozen_cash"] == freeze_amount(10.0, 100)
        assert len(st["pending_orders"]) == 1
        assert st["pending_orders"][0]["frozen"] == st["frozen_cash"]

    def test_buy_limit_out_of_range(self):
        st = _state()
        r = try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                                 "shares": 100, "limit_price": 12.0,
                                 "note": "x"}, 10.0, None, "2020-03-13")
        assert not r["ok"] and "区间" in r["error"]
        assert st["frozen_cash"] == 0.0

    def test_buy_limit_insufficient(self):
        st = _state(cash=500.0)  # 冻结需 1005(max(1002, 1000+5),佣金5元下限)
        r = try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                                 "shares": 100, "limit_price": 10.0,
                                 "note": "x"}, 10.0, None, "2020-03-13")
        assert not r["ok"] and "资金不足" in r["error"]

    def test_sell_limit_t1_and_frozen_shares(self):
        pos = [{"symbol": "sh600519", "shares": 200, "cost_price": 9.0,
                "buy_date": "2020-03-13"}]
        st = _state(positions=pos)
        # T+1:今日买入
        r = try_place_limit(st, {"symbol": "sh600519", "side": "sell",
                                 "shares": 100, "limit_price": 10.5,
                                 "note": "x"}, 10.0, None, "2020-03-13")
        assert not r["ok"] and "T+1" in r["error"]
        # 昨日买入,挂 100 股后可卖余量=100
        pos[0]["buy_date"] = "2020-03-12"
        assert try_place_limit(_state(positions=copy.deepcopy(pos)),
                               {"symbol": "sh600519", "side": "sell",
                                "shares": 100, "limit_price": 10.5,
                                "note": "x"}, 10.0, None,
                               "2020-03-13")["ok"]
        st2 = _state(positions=copy.deepcopy(pos))
        try_place_limit(st2, {"symbol": "sh600519", "side": "sell",
                              "shares": 100, "limit_price": 10.5,
                              "note": "x"}, 10.0, None, "2020-03-13")
        assert sellable_shares(st2, "sh600519", "2020-03-13") == 100
        r = try_place_limit(st2, {"symbol": "sh600519", "side": "sell",
                                  "shares": 200, "limit_price": 10.5,
                                  "note": "x"}, 10.0, None, "2020-03-13")
        assert not r["ok"] and "持仓不足" in r["error"]


class TestCheckPending:
    def _seg(self, o, h, l, c):
        return {"open": o, "high": h, "low": l, "close": c}

    def test_buy_limit_triggers_on_cross(self):
        st = _state()
        try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                             "shares": 100, "limit_price": 10.0,
                             "note": "x"}, 10.0, None, "2020-03-13")
        trades, events = check_pending(
            st, {"sh600519": self._seg(10.2, 10.4, 9.8, 9.9)},
            {"sh600519": 10.0}, {}, "2020-03-13")
        assert len(trades) == 1
        # 成交价 = min(限价, 段开盘) = 10.0
        assert trades[0]["price"] == 10.0
        assert trades[0]["order_type"] == "limit"
        assert st["pending_orders"] == []
        assert st["frozen_cash"] == 0.0
        assert st["positions"][0]["shares"] == 100
        # 现金 = 1e6 − 成交额1000 − 佣金5(commission 最低5元,见 test_fees);
        # 冻结1005随成交释放:有效现金 1e6−1005+1005=1e6,成交扣 1005 → 998995
        assert st["cash"] == pytest.approx(1e6 - 10.0 * 100 - 5.0, abs=0.01)

    def test_sell_limit_triggers_better_open(self):
        pos = [{"symbol": "sh600519", "shares": 100, "cost_price": 9.0,
                "buy_date": "2020-03-12"}]
        st = _state(cash=0.0, positions=pos)
        try_place_limit(st, {"symbol": "sh600519", "side": "sell",
                             "shares": 100, "limit_price": 10.5,
                             "note": "x"}, 10.0, None, "2020-03-13")
        # 段开盘 10.8 高于限价 → 成交价取开盘 10.8(更优)
        trades, _ = check_pending(
            st, {"sh600519": self._seg(10.8, 11.0, 10.6, 10.7)},
            {"sh600519": 10.0}, {}, "2020-03-13")
        assert trades[0]["price"] == 10.8
        assert st["positions"] == []

    def test_no_trigger_when_far(self):
        st = _state()
        try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                             "shares": 100, "limit_price": 9.0,
                             "note": "x"}, 10.0, None, "2020-03-13")
        trades, events = check_pending(
            st, {"sh600519": self._seg(10.0, 10.2, 9.9, 10.1)},
            {"sh600519": 10.0}, {}, "2020-03-13")
        assert trades == [] and events == []
        assert len(st["pending_orders"]) == 1

    def test_suspended_symbol_skipped(self):
        st = _state()
        try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                             "shares": 100, "limit_price": 10.0,
                             "note": "x"}, 10.0, None, "2020-03-13")
        trades, _ = check_pending(st, {}, {"sh600519": 10.0}, {},
                                  "2020-03-13")
        assert trades == []
        assert len(st["pending_orders"]) == 1  # 停牌悬着

    def test_trigger_rejected_cancels_and_unfreezes(self):
        # 挂单后把现金挪走(仅剩本单冻结),触发时 try_fill 拒绝 → 撤单解冻。
        # 审查给的段 open=9.8 会以更优价成交(成本 985 ≤ 1000,成交而非拒绝),
        # 改取 open=限价 10.0:成本 1005 > 有效现金 1000 → 必拒
        st = _state(cash=1005.0)
        try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                             "shares": 100, "limit_price": 10.0,
                             "note": "x"}, 10.0, None, "2020-03-13")
        assert st["frozen_cash"] == 1005.0
        st["cash"] = 1000.0  # 挪走 5 元,成交需 1005 → 必拒
        trades, events = check_pending(
            st, {"sh600519": self._seg(10.0, 10.1, 9.9, 10.05)},
            {"sh600519": 10.0}, {}, "2020-03-13")
        assert trades == []
        assert len(events) == 1
        assert events[0]["type"] == "order_cancelled"
        assert "被拒" in events[0]["msg"]
        assert st["pending_orders"] == []
        assert st["frozen_cash"] == 0.0
        assert st["cash"] == 1000.0  # 拒绝不扣款

    def test_buy_limit_triggers_better_open(self):
        st = _state()
        try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                             "shares": 100, "limit_price": 10.0,
                             "note": "x"}, 10.0, None, "2020-03-13")
        # 段开盘 9.8 低于限价 → 成交价取开盘 9.8(更优)
        trades, _ = check_pending(
            st, {"sh600519": self._seg(9.8, 10.1, 9.7, 9.9)},
            {"sh600519": 10.0}, {}, "2020-03-13")
        assert trades[0]["price"] == 9.8

    def test_buy_fill_with_other_frozen_exact_writeback(self):
        # 两笔挂单冻结各1005,一笔触发成交:回写必须精确(其余冻结不混入现金)
        st = _state(cash=1e6)
        try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                             "shares": 100, "limit_price": 10.0,
                             "note": "a"}, 10.0, None, "2020-03-13")
        try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                             "shares": 100, "limit_price": 9.0,
                             "note": "b"}, 10.0, None, "2020-03-13")
        assert st["frozen_cash"] == 1005.0 + 905.0
        # 触发第一笔(限价10,段低9.8),成交价10 → cost 1005
        trades, _ = check_pending(
            st, {"sh600519": self._seg(10.0, 10.1, 9.8, 9.9)},
            {"sh600519": 10.0}, {}, "2020-03-13")
        assert len(trades) == 1
        assert st["cash"] == 1e6 - 1005.0          # 精确回写
        assert st["frozen_cash"] == 905.0          # 其余冻结保留


class TestCancelDayPending:
    def test_cancel_unfreezes(self):
        st = _state()
        try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                             "shares": 100, "limit_price": 10.0,
                             "note": "x"}, 10.0, None, "2020-03-13")
        events = cancel_day_pending(st)
        assert len(events) == 1 and events[0]["type"] == "order_cancelled"
        assert st["pending_orders"] == []
        assert st["frozen_cash"] == 0.0


from src.domain.replay.engine import (
    apply_dividends, day_close_nav, nav_value,
)


class TestDayCloseNav:
    def test_appends_point_with_disclosures(self):
        st = {"cash": 900.0, "positions": [
            {"symbol": "sh600519", "shares": 100, "cost_price": 9.0,
             "buy_date": "2020-03-12"}], "nav": []}
        closes = {"sh600519": 10.0}
        assert nav_value(st["cash"], st["positions"], closes) == 1900.0
        pt = day_close_nav(st, "2020-03-13", closes)
        assert pt == {"date": "2020-03-13", "value": 1900.0,
                      "cash": 900.0, "pos": {"sh600519": 1000.0}}
        assert st["nav"][-1] is pt


class TestApplyDividends:
    POS = lambda self, buy: [{  # noqa: E731
        "symbol": "sh600519", "shares": 100, "cost_price": 10.0,
        "buy_date": buy}]

    def test_cash_dividend_tax_tiers(self):
        for buy, rate, got in [("2019-01-01", 0.0, 100.0),
                               ("2020-01-01", 0.1, 90.0),
                               ("2020-05-15", 0.2, 80.0)]:  # 17天<1月
            st = {"cash": 0.0, "positions": self.POS(buy),
                  "dividends_received": []}
            ev = apply_dividends(
                st, [{"symbol": "sh600519", "div_per_share": 1.0,
                      "stock_div": 0, "convert": 0}], "2020-06-01")
            assert st["cash"] == got
            assert ev[0]["type"] == "dividend"
            assert st["dividends_received"][0]["tax_rate"] == rate

    def test_split_multiplies_shares(self):
        st = {"cash": 0.0, "positions": self.POS("2019-01-01"),
              "dividends_received": []}
        apply_dividends(
            st, [{"symbol": "sh600519", "div_per_share": 0,
                  "stock_div": 1.0, "convert": 0}],  # 10送10
            "2020-06-01")
        assert st["positions"][0]["shares"] == 200
        assert st["positions"][0]["cost_price"] == 5.0

    def test_no_position_no_effect(self):
        st = {"cash": 0.0, "positions": [], "dividends_received": []}
        assert apply_dividends(
            st, [{"symbol": "sh600519", "div_per_share": 1.0}],
            "2020-06-01") == []
        assert st["cash"] == 0.0


# ── 决策日志补全: 成交携带信心度 ─────────────────────────────────────────
class TestTradeConfidence:
    def test_market_fill_carries_confidence(self):
        order = {"symbol": "sh600519", "side": "buy", "shares": 100,
                 "note": "低吸", "confidence": 4}
        r = try_fill_market(1e6, [], order, seg_price=10.0,
                            prev_close=10.0, name="贵州茅台",
                            day="2019-06-03")
        assert r["ok"]
        assert r["trade"]["confidence"] == 4
        # 未填信心度时为 None(旧行为兼容)
        r2 = try_fill_market(1e6, [], {**order, "confidence": None},
                             10.0, 10.0, None, "2019-06-03")
        assert r2["trade"]["confidence"] is None
