"""选股器 quality 模式逻辑测试（monkeypatch 加载器，无需 DB）。

复用 test_quality.py 的三类画像（healthy/middling/eliminated）验证：
淘汰红线剔除、quality_score 排名、min_quality_score / drop_review / top_n 过滤、
以及 screen() 端到端 dispatch。
"""
import pytest

from src.domain.market.strategy.longterm import screener
from src.domain.market.strategy.longterm import data_loader as dl
from src.domain.market.strategy.longterm.screener import (
    _screen_quality,
    screen,
    SCREENER_MODES,
)

# 健康公司 → verdict=pass, quality_score≈94
HEALTHY = {
    "revenue": 1000, "operating_cost": 400, "gross_profit": 600,
    "sell_expense": 60, "admin_expense": 30, "rd_expense": 30, "fin_expense": 0,
    "monetary_funds": 500, "trading_financial_assets": 100,
    "short_loan": 50, "non_current_liab_due_within_1y": 50,
    "accounts_receivable": 50, "inventory": 60,
    "net_profit": 150, "ocf": 200, "icf": -100, "fcf": -40,
    "total_assets": 1000, "equity": 600, "total_liabilities": 400,
    "gross_margin": 60.0, "goodwill": 0,
}
# 中等公司 → verdict=review, quality_score≈59.7
MIDDLING = {
    "revenue": 1000, "operating_cost": 700, "gross_profit": 300,
    "sell_expense": 150, "admin_expense": 50, "rd_expense": 30, "fin_expense": 20,
    "monetary_funds": 200, "short_loan": 100,
    "accounts_receivable": 50, "net_profit": 50, "ocf": 40,
    "total_assets": 1000, "equity": 600, "goodwill": 0, "gross_margin": 30.0,
}
# 垃圾公司 → verdict=eliminate（现金覆盖<1 + 应收>现金 + 亏损）
ELIMINATED = {
    "revenue": 100, "operating_cost": 90, "gross_profit": 10,
    "monetary_funds": 20, "short_loan": 100, "non_current_liab_due_within_1y": 50,
    "accounts_receivable": 200, "net_profit": -50, "goodwill": 0,
}


def _patch_loader(monkeypatch, snap):
    monkeypatch.setattr(
        screener, "fetch_financial_snapshot",
        lambda symbols, as_of, include_detail=False: snap,
    )


def test_quality_in_modes():
    assert "quality" in SCREENER_MODES


def test_filters_eliminate_and_ranks(monkeypatch):
    _patch_loader(monkeypatch, {"A": HEALTHY, "B": MIDDLING, "C": ELIMINATED})
    val_map = {"A": {"pe_ttm": 20}, "B": {"pe_ttm": 15}}
    items = _screen_quality(["A", "B", "C"], val_map, {}, None, 10, {})
    syms = [i.symbol for i in items]
    assert "C" not in syms                 # eliminated 被剔除
    assert syms[0] == "A"                  # 94 分 > 59 分
    assert items[0].score == pytest.approx(94.0)
    assert items[0].factor_breakdown["verdict"] == "pass"
    assert items[0].roe == pytest.approx(25.0)   # 杜邦 roe 0.25 → 25%
    assert items[0].pe_ttm == 20


def test_drop_review(monkeypatch):
    _patch_loader(monkeypatch, {"A": HEALTHY, "B": MIDDLING})
    items = _screen_quality(["A", "B"], {}, {}, None, 10, {"drop_review": True})
    assert [i.symbol for i in items] == ["A"]   # B(review) 被剔除


def test_min_quality_score(monkeypatch):
    _patch_loader(monkeypatch, {"A": HEALTHY, "B": MIDDLING})
    items = _screen_quality(["A", "B"], {}, {}, None, 10, {"min_quality_score": 80})
    assert [i.symbol for i in items] == ["A"]


def test_top_n(monkeypatch):
    _patch_loader(monkeypatch, {"A": HEALTHY, "B": MIDDLING})
    items = _screen_quality(["A", "B"], {}, {}, None, 1, {})
    assert len(items) == 1


def test_screen_end_to_end(monkeypatch):
    """screen('quality', ...) 端到端 dispatch（monkeypatch 三个加载器 + universe）。"""
    monkeypatch.setattr(
        screener, "fetch_financial_snapshot",
        lambda symbols, as_of, include_detail=False: {"A": HEALTHY, "B": ELIMINATED},
    )
    monkeypatch.setattr(
        screener, "fetch_latest_valuations",
        lambda symbols, as_of: {"A": {"pe_ttm": 20}},
    )
    monkeypatch.setattr(screener, "fetch_latest_financials", lambda symbols, as_of: {})
    monkeypatch.setattr(dl, "fetch_universe_symbols", lambda exclude_st=True: ["A", "B"])

    res = screen("quality", top_n=5)
    assert res.mode == "quality"
    syms = [i.symbol for i in res.ranked_list]
    assert "B" not in syms
    assert syms == ["A"]
    assert res.ranked_list[0].factor_breakdown["verdict"] == "pass"
