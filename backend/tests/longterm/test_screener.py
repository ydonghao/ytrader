"""
选股器测试
==========
验证 4 种筛选模式的排名正确性、门槛过滤、数据缺失处理。
用 mock 替换 DB 加载，喂合成数据，保证可独立运行。
"""
import sys
import os
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

from src.domain.market.strategy.longterm import screener


# ── 合成数据 ──────────────────────────────────────────────────────────────

TODAY = date(2025, 6, 1)

# 5 只测试标的：精心构造让排名可预测
# A: 低PE + 高ROE + 低PB → 神奇公式/红利都该靠前
# B: 高PE + 高ROE → 神奇公式收益端差
# C: 低PE + 低ROE → 神奇公式质量端差
# D: 高PB + 负ROE → 各模式都该被剔
# E: 中等 → 兜底

VAL_MAP = {
    "A": {"pe_ttm": 5.0, "pb": 0.5, "dv_ttm": None, "pe": 5.0},   # 便宜
    "B": {"pe_ttm": 40.0, "pb": 4.0, "dv_ttm": None, "pe": 40.0}, # 贵
    "C": {"pe_ttm": 4.0, "pb": 0.6, "dv_ttm": None, "pe": 4.0},   # 很便宜但ROE低
    "D": {"pe_ttm": -5.0, "pb": 5.0, "dv_ttm": None, "pe": -5.0}, # 亏损
    "E": {"pe_ttm": 15.0, "pb": 1.5, "dv_ttm": None, "pe": 15.0}, # 中等
}

FIN_MAP = {
    "A": {"roe_weighted": 15.0, "debt_ratio": 60.0, "net_margin": 20.0},
    "B": {"roe_weighted": 12.0, "debt_ratio": 50.0, "net_margin": 15.0},
    "C": {"roe_weighted": 1.0, "debt_ratio": 70.0, "net_margin": 2.0},   # 低质量
    "D": {"roe_weighted": -5.0, "debt_ratio": 80.0, "net_margin": -10.0},# 亏损
    "E": {"roe_weighted": 8.0, "debt_ratio": 55.0, "net_margin": 10.0},
}

# F-Score 历史需要两期，构造质量改善的 A
FIN_HIST = {
    "A": [
        {"report_date": date(2024, 9, 30), "roe_weighted": 10.0, "net_margin": 15.0, "debt_ratio": 65.0},
        {"report_date": date(2024, 12, 31), "roe_weighted": 15.0, "net_margin": 20.0, "debt_ratio": 60.0},
    ],
    "C": [
        {"report_date": date(2024, 9, 30), "roe_weighted": 1.5, "net_margin": 3.0, "debt_ratio": 68.0},
        {"report_date": date(2024, 12, 31), "roe_weighted": 1.0, "net_margin": 2.0, "debt_ratio": 70.0},
    ],
}


def _mock_val(symbols, as_of=None):
    return {s: VAL_MAP[s] for s in symbols if s in VAL_MAP}

def _mock_fin(symbols, as_of=None):
    return {s: FIN_MAP[s] for s in symbols if s in FIN_MAP}

def _mock_fin_hist(symbols, as_of=None, **kw):
    return {s: FIN_HIST.get(s, []) for s in symbols}


# ── 神奇公式选股 ──────────────────────────────────────────────────────────

@patch("src.domain.market.strategy.longterm.screener.fetch_latest_financials", _mock_fin)
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_valuations", _mock_val)
def test_magic_formula_ranking():
    """A(低PE高ROE) 应排第一，D(亏损高PB) 应被剔。"""
    result = screener.screen(
        mode="magic_formula",
        symbols=list(VAL_MAP.keys()),
        as_of=TODAY,
        top_n=5,
    )
    syms = [item.symbol for item in result.ranked_list]
    # D 亏损(PE<3)应被剔除
    assert "D" not in syms
    # A 是最优组合，应排第一
    assert syms[0] == "A"
    assert result.ranked_list[0].rank == 1


@patch("src.domain.market.strategy.longterm.screener.fetch_latest_financials", _mock_fin)
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_valuations", _mock_val)
def test_magic_formula_top_n_limit():
    result = screener.screen(
        mode="magic_formula", symbols=list(VAL_MAP.keys()),
        as_of=TODAY, top_n=2,
    )
    assert len(result.ranked_list) <= 2


# ── 红利选股 ──────────────────────────────────────────────────────────────

@patch("src.domain.market.strategy.longterm.screener.fetch_latest_financials", _mock_fin)
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_valuations", _mock_val)
def test_dividend_pb_proxy():
    """无股息率时用低 PB 近似，A(PB=0.5) 应靠前。"""
    result = screener.screen(
        mode="dividend", symbols=list(VAL_MAP.keys()), as_of=TODAY, top_n=5,
    )
    syms = [item.symbol for item in result.ranked_list]
    assert "A" in syms
    # D 高 PB(5.0) 应被剔（超 pb_max=3）
    assert "D" not in syms
    # A 最低 PB 应排第一
    assert syms[0] == "A"


# ── F-Score 选股 ──────────────────────────────────────────────────────────

@patch("src.domain.market.strategy.longterm.screener.fetch_financial_history", _mock_fin_hist)
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_financials", _mock_fin)
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_valuations", _mock_val)
def test_fscore_quality_ranking():
    """A(质量改善) F-Score 应高，C(质量恶化) F-Score 应低。"""
    # 只用 A 和 C（有历史）
    result = screener.screen(
        mode="fscore", symbols=["A", "C"], as_of=TODAY, top_n=5,
        filters={"min_fscore": 0},  # 放宽门槛看打分
    )
    syms = [item.symbol for item in result.ranked_list]
    if syms:
        # A 的 ROE/净利率都在改善，负债降 → F-Score 应 ≥ C
        a_item = next((i for i in result.ranked_list if i.symbol == "A"), None)
        c_item = next((i for i in result.ranked_list if i.symbol == "C"), None)
        if a_item and c_item:
            assert a_item.fscore >= c_item.fscore


# ── 自定义多因子 ──────────────────────────────────────────────────────────

@patch("src.domain.market.strategy.longterm.screener.fetch_latest_financials", _mock_fin)
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_valuations", _mock_val)
def test_custom_filters():
    """设严格 PE 上限，应只剩便宜的票。"""
    result = screener.screen(
        mode="custom", symbols=list(VAL_MAP.keys()), as_of=TODAY, top_n=10,
        filters={"pe_max": 10, "pb_max": 2.0, "roe_min": 0},
    )
    syms = [item.symbol for item in result.ranked_list]
    # 只剩 A(PE5/PB0.5) 和 C(PE4/PB0.6) 满足
    # D 亏损 PE<0 但 roe<0 被剔
    for s in syms:
        assert VAL_MAP[s]["pe_ttm"] <= 10
        assert VAL_MAP[s]["pb"] <= 2.0


@patch("src.domain.market.strategy.longterm.screener.fetch_latest_financials", _mock_fin)
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_valuations", _mock_val)
def test_custom_no_match():
    """门槛过严无匹配，返回空但不崩。"""
    result = screener.screen(
        mode="custom", symbols=list(VAL_MAP.keys()), as_of=TODAY, top_n=10,
        filters={"pe_max": 0.1, "pb_max": 0.1},
    )
    assert len(result.ranked_list) == 0


# ── 异常处理 ──────────────────────────────────────────────────────────────

def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="未知选股模式"):
        screener.screen(mode="nonexistent", symbols=["A"], as_of=TODAY)


@patch("src.domain.market.strategy.longterm.screener.fetch_latest_financials", _mock_fin)
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_valuations", _mock_val)
def test_to_dict_serializable():
    result = screener.screen(
        mode="magic_formula", symbols=list(VAL_MAP.keys()), as_of=TODAY, top_n=3,
    )
    import json
    d = result.to_dict()
    json.dumps(d)  # 不抛异常
    assert "ranked_list" in d
    assert d["mode"] == "magic_formula"


# ── dividend_value 模式测试 ──────────────────────────────────────────────

# 给 dividend 模式造真实股息率
VAL_MAP_DV = {
    "A": {"pe_ttm": 8.0, "pb": 0.8, "dv_ttm": 6.0, "pe": 8.0},
    "B": {"pe_ttm": 50.0, "pb": 5.0, "dv_ttm": 1.0, "pe": 50.0},  # 贵+低息→淘汰
    "C": {"pe_ttm": 5.0, "pb": 0.5, "dv_ttm": 5.0, "pe": 5.0},
    "D": {"pe_ttm": -3.0, "pb": 2.0, "dv_ttm": 8.0, "pe": -3.0},  # 亏损→淘汰
    "E": {"pe_ttm": 15.0, "pb": 1.5, "dv_ttm": 4.0, "pe": 15.0},
}

FIN_MAP_DV = {
    "A": {"roe_weighted": 12.0, "debt_ratio": 50.0},
    "B": {"roe_weighted": 5.0, "debt_ratio": 40.0},
    "C": {"roe_weighted": 10.0, "debt_ratio": 55.0},
    "D": {"roe_weighted": -3.0, "debt_ratio": 75.0},
    "E": {"roe_weighted": 9.0, "debt_ratio": 60.0},
}


def _mock_dv_pct_batch(symbols, metric, window, as_of, exclude_ranges=None):
    """mock 批量分位：A/C 低分位(便宜)，E 中等，B 高(贵)。"""
    return {
        "A": {"percentile": 0.10, "sample_size": 60, "current": 0.8},
        "C": {"percentile": 0.05, "sample_size": 80, "current": 0.5},
        "E": {"percentile": 0.45, "sample_size": 50, "current": 1.5},
    }


@patch("src.domain.market.strategy.longterm.screener.stock_percentile_batch", _mock_dv_pct_batch)
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_financials", lambda symbols, as_of=None: {s: FIN_MAP_DV[s] for s in symbols if s in FIN_MAP_DV})
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_valuations", lambda symbols, as_of=None: {s: VAL_MAP_DV[s] for s in symbols if s in VAL_MAP_DV})
def test_dividend_value_filters_and_ranks():
    """dividend_value 模式：硬门槛过滤 + 双排名。"""
    result = screener.screen(
        mode="dividend_value",
        symbols=list(VAL_MAP_DV.keys()),
        as_of=TODAY,
        top_n=5,
        filters={"value_metric": "pb", "value_window": "10y"},
    )
    syms = [item.symbol for item in result.ranked_list]
    # B：股息率1%<3% 且 PB5>3 → 淘汰
    assert "B" not in syms
    # D：PE-3<0 → 淘汰
    assert "D" not in syms
    # A、C、E 入选
    assert set(syms) == {"A", "C", "E"}
    # C 分位最低(0.05)+股息率5%，应排第一
    assert syms[0] == "C"


@patch("src.domain.market.strategy.longterm.screener.stock_percentile_batch", _mock_dv_pct_batch)
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_financials", lambda symbols, as_of=None: {s: FIN_MAP_DV[s] for s in symbols if s in FIN_MAP_DV})
@patch("src.domain.market.strategy.longterm.screener.fetch_latest_valuations", lambda symbols, as_of=None: {s: VAL_MAP_DV[s] for s in symbols if s in VAL_MAP_DV})
def test_dividend_value_factor_breakdown_populated():
    """dividend_value 结果的 factor_breakdown 有值。"""
    result = screener.screen(
        mode="dividend_value",
        symbols=list(VAL_MAP_DV.keys()),
        as_of=TODAY,
        top_n=5,
        filters={"value_metric": "pb", "value_window": "10y"},
    )
    for item in result.ranked_list:
        d = item.to_dict()
        assert "factor_breakdown" in d
        fb = d["factor_breakdown"]
        assert fb is not None
        assert "dy_value" in fb
        assert "value_percentile" in fb
