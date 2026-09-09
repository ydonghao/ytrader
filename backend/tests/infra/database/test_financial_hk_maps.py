"""港股科目映射回归测试（纯静态，不连库）。

候选名以 2026-08 现场 akshare stock_financial_hk_report_em（00700）
实测 STD_ITEM_NAME 为准——2026-07 入库的港股数据因映射候选名与东财
实际科目名不符，固定列全空（现金流 Tab 港股全"—"事故根因）。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.infra.database.market.financial_full import (  # noqa: E402
    _DETAIL_COLUMNS,
    _HK_BALANCE_MAP,
    _HK_CASHFLOW_MAP,
    _HK_INCOME_MAP,
)


def test_detail_columns_include_capex_and_fcf():
    """bulk_upsert 按 _DETAIL_COLUMNS 组 SQL——漏列会静默丢弃数据
    （2026-08 实测：capex/free_cash_flow 曾被丢弃，HK 试点全 None）。"""
    assert "capex" in _DETAIL_COLUMNS
    assert "free_cash_flow" in _DETAIL_COLUMNS


def test_hk_cashflow_map_hits_live_subjects():
    # 东财港股现金流量表为"业务净额"三行式 + 期末现金 + 购建固定资产
    assert "经营业务现金净额" in _HK_CASHFLOW_MAP["ocf"]
    assert "投资业务现金净额" in _HK_CASHFLOW_MAP["icf"]
    assert "融资业务现金净额" in _HK_CASHFLOW_MAP["fcf"]
    assert "期末现金" in _HK_CASHFLOW_MAP["cash_end"]
    assert "购建固定资产" in _HK_CASHFLOW_MAP["capex"]


def test_hk_income_map_hits_live_subjects():
    assert "营业额" in _HK_INCOME_MAP["revenue"]
    assert "除税后溢利" in _HK_INCOME_MAP["net_profit"]
    assert "股东应占溢利" in _HK_INCOME_MAP["net_profit_parent"]
    assert "每股基本盈利" in _HK_INCOME_MAP["basic_eps"]
    assert "销售及分销费用" in _HK_INCOME_MAP["sell_expense"]


def test_hk_balance_map_hits_live_subjects():
    assert "总资产" in _HK_BALANCE_MAP["total_assets"]
    assert "总负债" in _HK_BALANCE_MAP["total_liabilities"]
    assert "总权益" in _HK_BALANCE_MAP["equity"]
    assert "股东权益" in _HK_BALANCE_MAP["equity_parent"]
    assert "物业厂房及设备" in _HK_BALANCE_MAP["fixed_assets"]
    assert "应收帐款" in _HK_BALANCE_MAP["accounts_receivable"]
    assert "短期贷款" in _HK_BALANCE_MAP["short_loan"]
    assert "长期贷款" in _HK_BALANCE_MAP["long_loan"]


def test_all_candidate_lists_nonempty():
    for m in (_HK_INCOME_MAP, _HK_BALANCE_MAP, _HK_CASHFLOW_MAP):
        for field, candidates in m.items():
            assert candidates, f"{field} 候选名为空"
