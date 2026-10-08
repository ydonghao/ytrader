"""capital_events 纯函数测试：normalize + summarize。"""
import datetime as dt

from src.domain.market.thesis.capital_events import (
    normalize_ggcg,
    normalize_repurchase,
    summarize_mgmt_events,
)


def test_normalize_repurchase():
    rows = normalize_repurchase([{
        "股票代码": "600380", "股票简称": "健康元",
        "已回购金额": 299999708.87, "已回购股份数量": 29252223.0,
        "实施进度": "完成实施", "最新公告日期": dt.date(2026, 9, 20),
        "回购起始时间": dt.date(2026, 8, 1),
    }])
    assert rows[0] == {
        "symbol": "sh600380", "event_type": "buyback",
        "announce_date": dt.date(2026, 9, 20),
        "holder_name": "", "start_date": dt.date(2026, 8, 1),
        "shares_wan": 2925.2223,           # 股→万股
        "amount": 299999708.87, "ratio_pct": None,
        "progress": "完成实施",
    }


def test_normalize_repurchase_tolerates_missing():
    # 无公告日的行跳过（无法幂等去重）
    rows = normalize_repurchase([{"股票代码": "000001"}])
    assert rows == []


def test_normalize_nan_fields_cleaned():
    rows = normalize_repurchase([{
        "股票代码": "600380", "最新公告日期": dt.date(2026, 9, 20),
        "实施进度": float("nan"),       # pandas NaN 字符串字段
        "已回购股份数量": float("nan"),
    }])
    r = rows[0]
    assert r["progress"] is None and r["shares_wan"] is None


def test_normalize_ggcg():
    rows = normalize_ggcg([{
        "代码": "688603", "股东名称": "上海青骐",
        "持股变动信息-增减": "减持",
        "持股变动信息-变动数量": 31.179,          # 万股
        "持股变动信息-占总股本比例": 0.2499,
        "变动开始日": dt.date(2026, 9, 22),
        "变动截止日": dt.date(2026, 9, 24),
        "公告日": dt.date(2026, 9, 25),
    }])
    r = rows[0]
    assert r["symbol"] == "sh688603"
    assert r["event_type"] == "hold_decrease"
    assert r["holder_name"] == "上海青骐"
    assert r["shares_wan"] == 31.179
    assert r["ratio_pct"] == 0.2499
    assert r["announce_date"] == dt.date(2026, 9, 25)
    assert r["start_date"] == dt.date(2026, 9, 22)
    assert r["amount"] is None


def test_summarize_directions_and_flag():
    now = dt.date(2026, 9, 27)
    events = [
        {"event_type": "hold_increase", "announce_date": "2026-06-01",
         "ratio_pct": 0.3, "amount": None},
        {"event_type": "hold_decrease", "announce_date": "2026-07-01",
         "ratio_pct": 1.5, "amount": None},
        {"event_type": "buyback", "announce_date": "2026-08-01",
         "ratio_pct": None, "amount": 5e8},
        # 超出24个月窗口，不计入
        {"event_type": "hold_increase", "announce_date": "2024-06-01",
         "ratio_pct": 2.0, "amount": None},
    ]
    s = summarize_mgmt_events(events, months=24, now=now)
    assert s["buyback_amount"] == 5e8
    assert round(s["net_ratio_pct"], 2) == round(0.3 - 1.5, 2)
    assert s["label"] == "净减持"
    assert any("净减持" in f for f in s["flags"])   # -1.2% > 1%


def test_summarize_quiet():
    s = summarize_mgmt_events([], months=24,
                              now=dt.date(2026, 9, 27))
    assert s["label"] == "平静" and s["flags"] == []
