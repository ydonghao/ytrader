# backend/tests/domain/market/industry_analysis/test_tables.py
"""表模型可导入注册;列名契约(不触库——SQL 字符串与列常量静态校验)。"""
from src.infra.database.market.industry_analysis import (
    PB_BREAK_COLUMNS, PROSPERITY_COLUMNS, FLOW_COLUMNS,
    IndustryFundFlowTable, IndustryPbBreakTable, IndustryProsperityTable,
)


def test_table_names():
    assert IndustryPbBreakTable.__tablename__ == "industry_pb_break_daily"
    assert IndustryFundFlowTable.__tablename__ == "industry_fund_flow_daily"
    assert IndustryProsperityTable.__tablename__ == "industry_prosperity_daily"


def test_column_contracts():
    assert PB_BREAK_COLUMNS == ("trade_date", "scope", "scope_code",
                                "total_count", "break_count", "break_rate",
                                "median_pb")
    assert FLOW_COLUMNS == ("trade_date", "em_industry_name",
                            "main_net_inflow", "close_change_pct")
    assert PROSPERITY_COLUMNS == ("trade_date", "sw_code", "score",
                                  "score_profit", "score_valuation",
                                  "score_momentum", "score_flow", "inputs")
