# backend/tests/domain/market/industry_analysis/test_daily_jobs.py
"""每日 job 的纯转换段(不触网不触库)。"""
import datetime as dt
from types import SimpleNamespace

import pandas as pd

from src.domain.market.sync.jobs.industry_fund_flow_sync import parse_flow_df
from src.domain.market.sync.jobs.industry_pb_break_sync import (
    build_pb_rows,
)

D = dt.date(2026, 9, 18)


def test_build_pb_rows():
    aggregate = SimpleNamespace(
        market=SimpleNamespace(total_count=2, break_count=1, break_rate=0.5,
                               median_pb=1.0),
        industries={"801780": SimpleNamespace(total_count=1, break_count=0,
                                              break_rate=0.0,
                                              median_pb=1.5)},
    )
    rows = build_pb_rows(D, aggregate)
    assert rows == [
        {"trade_date": D, "scope": "market", "scope_code": "ALL",
         "total_count": 2, "break_count": 1, "break_rate": 0.5,
         "median_pb": 1.0},
        {"trade_date": D, "scope": "industry", "scope_code": "801780",
         "total_count": 1, "break_count": 0, "break_rate": 0.0,
         "median_pb": 1.5},
    ]


def test_parse_flow_df_both_dialects():
    # 口径1:列含「行业/净额」(现有 /market/fund-flow 同款)
    df1 = pd.DataFrame([
        {"行业": "银行", "净额": 1.5e9, "涨跌幅": 1.2},
        {"行业": "酿酒行业", "净额": -3e8, "涨跌幅": -0.5},
    ])
    # 口径2:列含「名称/主力净流入-净额」
    df2 = pd.DataFrame([
        {"名称": "银行", "主力净流入-净额": 1.5e9, "涨跌幅": 1.2},
    ])
    r1 = parse_flow_df(df1, D)
    r2 = parse_flow_df(df2, D)
    assert r1[0] == {"trade_date": D, "em_industry_name": "银行",
                     "main_net_inflow": 1.5e9, "close_change_pct": 1.2}
    assert r1[1]["em_industry_name"] == "酿酒行业"
    assert r2[0]["em_industry_name"] == "银行"
    assert r2[0]["main_net_inflow"] == 1.5e9


def test_parse_flow_df_skips_dirty_rows():
    df = pd.DataFrame([
        {"行业": "", "净额": None, "涨跌幅": None},          # 空名
        {"行业": "银行", "净额": "abc", "涨跌幅": 1.0},     # 脏数值
    ])
    rows = parse_flow_df(df, D)
    assert rows == [{"trade_date": D, "em_industry_name": "银行",
                     "main_net_inflow": None, "close_change_pct": 1.0}]


def test_parse_flow_df_nan_rows_never_reach_db():
    # pandas NaN 是 truthy 非 None:行业名 NaN → str "nan" 落库脏名;
    # 净额 NaN → float('nan') 落库 'NaN' 非 NULL,沿 flow20 传播致评分归零
    nan = float("nan")
    df = pd.DataFrame([
        {"行业": nan, "净额": 1e9, "涨跌幅": 1.0},          # 名 NaN → 整行跳过
        {"行业": "银行", "净额": nan, "涨跌幅": nan},       # 值 NaN → None
        {"行业": "银行", "净额": float("inf"), "涨跌幅": 0.5},  # inf → None
    ])
    rows = parse_flow_df(df, D)
    assert [r["em_industry_name"] for r in rows] == ["银行", "银行"]
    assert all(r["main_net_inflow"] is None for r in rows)
    assert rows[0]["close_change_pct"] is None
    assert rows[1]["main_net_inflow"] is None and \
        rows[1]["close_change_pct"] == 0.5
    assert "nan" not in {r["em_industry_name"] for r in rows}


def test_fund_flow_sync_skips_weekend():
    """周末快照按 today 落库会污染日期——run() 应直接跳过。"""
    import datetime as dt
    from src.domain.market.sync.jobs import industry_fund_flow_sync as m

    sunday = dt.date(2026, 9, 27)      # 周日
    out = m.run(trade_date=sunday)
    assert out.get("skipped") == "2026-09-27" and out["rows"] == 0
