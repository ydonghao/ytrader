"""course_review 纯函数测试: 买入触发/超配减仓/破位/组合聚合。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.domain.market.portfolio.course_review import (
    LegReviewInput,
    review_leg,
    review_portfolio,
)


def _leg(**kw) -> LegReviewInput:
    base = dict(
        symbol="sh600000", name="浦发银行", category="dividend",
        target_weight=0.125,
        entry_plan=[
            {"rung_index": 0, "drop_pct": 0.0, "price_level": 10.0,
             "amount": 18000.0, "executed": True, "fill_price": 10.0,
             "fill_shares": 1800},
            {"rung_index": 1, "drop_pct": 0.05, "price_level": 9.5,
             "amount": 13800.0, "executed": False},
            {"rung_index": 2, "drop_pct": 0.10, "price_level": 9.0,
             "amount": 13800.0, "executed": False},
            {"rung_index": 3, "drop_pct": 0.15, "price_level": 8.5,
             "amount": 14400.0, "executed": False},
        ],
        shares=1800, invested_amount=18000.0,
        current_price=10.0, dv_ttm=6.0, pe_state="low_fair",
    )
    base.update(kw)
    return LegReviewInput(**base)


def test_buy_rung_triggered():
    adv = review_leg(_leg(current_price=9.4), total_capital=500000.0)
    assert adv.code == "BUY_RUNG"
    assert adv.amount == 13800.0
    assert adv.shares == 1400  # 13800/9.4=1468 → 整手 1400


def test_buy_rung_not_triggered():
    adv = review_leg(_leg(current_price=9.6), total_capital=500000.0)
    assert adv.code == "HOLD"
    assert "下一档" in adv.message


def test_breakdown_below_lowest_rung():
    adv = review_leg(_leg(current_price=8.4), total_capital=500000.0)
    assert adv.code == "BREAKDOWN"


def test_trim_after_complete_when_overweight():
    plan = [
        {"rung_index": 0, "drop_pct": 0.0, "price_level": 10.0,
         "amount": 60000.0, "executed": True, "fill_price": 10.0,
         "fill_shares": 6000},
    ]
    # 目标 12.5% × 50万 = 6.25万;现价涨到 13 → 市值 7.8万 = 15.6% > 12.5%+3%
    adv = review_leg(
        _leg(entry_plan=plan, shares=6000, current_price=13.0,
             target_weight=0.125),
        total_capital=500000.0,
    )
    assert adv.code == "TRIM"


def test_hold_after_complete_normal_weight():
    plan = [
        {"rung_index": 0, "drop_pct": 0.0, "price_level": 10.0,
         "amount": 60000.0, "executed": True, "fill_price": 10.0,
         "fill_shares": 6000},
    ]
    adv = review_leg(
        _leg(entry_plan=plan, shares=6000, current_price=10.2,
             target_weight=0.125),
        total_capital=500000.0,
    )
    assert adv.code == "HOLD"


def test_hold_when_no_price():
    adv = review_leg(_leg(current_price=None), total_capital=500000.0)
    assert adv.code == "HOLD"
    assert "收盘价" in adv.message


def test_review_portfolio_aggregation():
    legs = [
        _leg(symbol="A", category="dividend", target_weight=0.25,
             shares=1800, invested_amount=18000.0, current_price=10.0,
             dv_ttm=6.0),
        _leg(symbol="B", category="bluechip", target_weight=0.20,
             shares=0, invested_amount=0.0, current_price=20.0,
             dv_ttm=2.0, entry_plan=[]),
    ]
    rev = review_portfolio(legs, total_capital=500000.0, cash_reserve_pct=0.10)
    assert rev.progress_invested == 18000.0
    assert rev.cash_remaining == 500000.0 * 0.9 - 18000.0
    assert rev.category_actual["dividend"] == 18000.0
    assert rev.category_actual["bluechip"] == 0.0
    assert rev.dividend_yield_weighted == 6.0  # 仅A有持仓
    assert len(rev.advices) == 2
