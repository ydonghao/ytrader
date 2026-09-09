"""job1 转换逻辑测试（mock 小 DataFrame，不发 HTTP）。"""
import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.domain.market.sync.jobs.sw_industry_member_sync import (
    build_member_rows,
)

FIRST = pd.DataFrame([
    {"行业代码": "801080.SI", "行业名称": "食品饮料"},
    {"行业代码": "801010.SI", "行业名称": "农林牧渔"},
])
SECOND = pd.DataFrame([
    {"行业代码": "801120.SI", "行业名称": "白酒Ⅱ", "上级行业": "食品饮料"},
    {"行业代码": "801125.SI", "行业名称": "啤酒", "上级行业": "食品饮料"},
])
# 白酒 2 只 + 啤酒 1 只；啤酒拉取失败（不在 cons_by_code）
# 计入日期两种类型都要覆盖：akshare 实际返回 datetime.date，兼容历史 str
CONS = {
    "801120": pd.DataFrame([
        {"证券代码": "600519", "证券名称": "贵州茅台",
         "最新权重": 12.3, "计入日期": "2021-12-13"},
        {"证券代码": "000596", "证券名称": "古井贡酒",
         "最新权重": 1.2, "计入日期": date(2021, 12, 13)},
    ]),
}


def test_transform_si_stripped_prefix_mapped():
    rows = build_member_rows(FIRST, SECOND, CONS)
    assert len(rows) == 2  # 啤酒缺成分 → 跳过
    m = next(r for r in rows if r["symbol"] == "sh600519")
    assert m["sw_code_l2"] == "801120"          # .SI 剥离
    assert m["sw_name_l2"] == "白酒Ⅱ"
    assert m["sw_code_l1"] == "801080"          # 上级行业名 → 一级代码
    assert m["sw_name_l1"] == "食品饮料"
    assert m["code"] == "600519"
    assert m["weight"] == 12.3
    assert m["included_date"] == "2021-12-13"  # str 原样保留
    gj = next(r for r in rows if r["symbol"] == "sz000596")
    assert gj["included_date"] == "2021-12-13"  # date 对象 → ISO 字符串


def test_prefix_rules():
    rows = build_member_rows(FIRST, SECOND, {
        "801120": pd.DataFrame([{"证券代码": "300750", "证券名称": "X",
                                 "最新权重": None, "计入日期": None}]),
        "801125": pd.DataFrame([{"证券代码": "830799", "证券名称": "Y",
                                 "最新权重": None, "计入日期": None}]),
    })
    syms = {r["code"]: r["symbol"] for r in rows}
    assert syms["300750"] == "sz300750"
    assert syms["830799"] == "bj830799"
