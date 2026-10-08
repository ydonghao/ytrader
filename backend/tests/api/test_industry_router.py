# backend/tests/api/test_industry_router.py
"""industry_router 契约测试(service 函数打桩,不触网/库)。

下半段:service 函数不打桩、打 _repo 假仓储——repo 契约回归保护,
照 tests/domain/market/industry_analysis/test_inputs.py 的 fake 模式。
"""
import datetime as dt
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.router import industry_router


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(industry_router.router)
    return TestClient(app)


def test_overview(client):
    with patch.object(industry_router, "_overview_data") as fake:
        fake.return_value = {"trade_date": "2026-09-18", "rows": []}
        r = client.get("/industry/overview")
    assert r.status_code == 200
    assert r.json() == {"code": 0, "msg": "ok",
                        "data": {"trade_date": "2026-09-18", "rows": []}}


def test_pb_break_defaults_and_validation(client):
    with patch.object(industry_router, "_pb_break_data") as fake:
        fake.return_value = {"series": [], "current": None}
        r = client.get("/industry/pb-break")
        r2 = client.get("/industry/pb-break", params={"scope": "bogus"})
    assert r.status_code == 200 and r.json()["code"] == 0
    assert fake.call_args_list[0].kwargs["scope"] == "market"
    assert r2.status_code == 400


def test_flow(client):
    with patch.object(industry_router, "_flow_data") as fake:
        fake.return_value = {"rows": []}
        r = client.get("/industry/flow")
    assert r.status_code == 200 and r.json()["data"] == {"rows": []}


def test_detail_404_on_bad_code(client):
    r = client.get("/industry/999999")
    assert r.status_code == 404


# ── rs_series: RS 线 = 标的/基准双 rebase 商 ────────────────

def test_rs_series_double_rebase():
    d1, d2 = dt.date(2026, 1, 5), dt.date(2026, 1, 6)
    r = industry_router.rs_series([(d1, 10), (d2, 12)],
                                  [(d1, 100), (d2, 110)])
    assert r[0] == {"date": "2026-01-05", "rs": 1.0}
    assert r[1] == {"date": "2026-01-06", "rs": round(1.2 / 1.1, 6)}


def test_rs_series_skips_mismatched_dates():
    d1, d2, d3 = (dt.date(2026, 1, 5), dt.date(2026, 1, 6),
                  dt.date(2026, 1, 7))
    # 标的 d3 基准缺日 → 跳过;基准 d2 标的缺日 → 跳过
    r = industry_router.rs_series(
        [(d1, 10), (d2, 12), (d3, 15)],
        [(d1, 100), (d2, 110), (d3, 121)])
    assert [p["date"] for p in r] == ["2026-01-05", "2026-01-06",
                                      "2026-01-07"]
    assert industry_router.rs_series(
        [(d1, 10), (d3, 15)], [(d1, 100), (d2, 110), (d3, 121)]) == [
        {"date": "2026-01-05", "rs": 1.0},
        {"date": "2026-01-07", "rs": round((15 / 10) / (121 / 100), 6)}]


def test_rs_series_zero_base_returns_empty():
    d1, d2 = dt.date(2026, 1, 5), dt.date(2026, 1, 6)
    assert industry_router.rs_series([(d1, 10), (d2, 12)],
                                     [(d1, 0), (d2, 110)]) == []
    assert industry_router.rs_series([(d1, 10)], [(d2, 110)]) == []


# ── interpret 503/502 分流 ──────────────────────────────────

class _StubRepo:
    def get_prosperity_latest_date(self):
        return dt.date(2026, 9, 1)


def test_interpret_503_when_not_configured(client):
    from src.domain.market.industry_analysis import llm_analyst

    with patch.object(industry_router, "_repo", return_value=_StubRepo()), \
         patch.object(llm_analyst, "interpret",
                      side_effect=llm_analyst.LLMNotConfigured(
                          "LLM provider not configured")):
        r = client.post("/industry/801780/interpret")
    assert r.status_code == 503


def test_interpret_502_on_llm_failure(client):
    from src.domain.market.industry_analysis import llm_analyst

    with patch.object(industry_router, "_repo", return_value=_StubRepo()), \
         patch.object(llm_analyst, "interpret",
                      side_effect=ValueError("boom")):
        r = client.post("/industry/801780/interpret")
    assert r.status_code == 502


# ── service 函数 × 假仓储(不打桩 service,保护 repo 消费契约)──

def _fake_repo(**over):
    repo = SimpleNamespace(
        get_prosperity_latest_date=lambda: dt.date(2026, 9, 12),
        get_prosperity=lambda d: [
            {"sw_code": "801780", "score": 66.0, "score_profit": 70.0,
             "score_valuation": 60.0, "score_momentum": 65.0,
             "score_flow": 55.0,
             "inputs": {"revenue_yoy": 8.0, "net_profit_yoy": -33.3,
                        "rs60": 0.2, "flow20": 1.5e9}},
        ],
        get_sw_valuation_window=lambda codes, start, end: {
            "801780": [
                {"trade_date": dt.date(2026, 9, 1), "pe_ttm": 5.0,
                 "pb": 0.5},
                {"trade_date": dt.date(2026, 9, 12), "pe_ttm": 6.0,
                 "pb": 0.6},
            ],
        },
        get_concentration=lambda sw_code, level=1: {
            "report_date": dt.date(2026, 6, 30), "sample_count": 42,
            "revenue_yoy": 3.0, "net_profit_sum": 120.0, "cr4": 35.0,
            "cr8": 55.0, "hhi": 450.0, "distribution": None},
        get_stock_valuation_dates=lambda start, end: [
            dt.date(2026, 9, 11), dt.date(2026, 9, 12)],
        get_member_valuations=lambda d: [],
        get_index_closes=lambda symbols, start, end: {},
    )
    for k, v in over.items():
        setattr(repo, k, v)
    return repo


def test_overview_data_with_fake_repo():
    with patch.object(industry_router, "_repo", return_value=_fake_repo()):
        data = industry_router._overview_data(window=8)
    assert data["trade_date"] == "2026-09-12"
    assert len(data["rows"]) == 31                    # 31 个申万一级全行
    assert all(r["tier_label"] for r in data["rows"])  # 真知识 yaml 标签
    bank = next(r for r in data["rows"] if r["sw_code"] == "801780")
    assert bank["name"] == "银行"
    assert bank["score"] == 66.0 and bank["score_flow"] == 55.0
    assert bank["flow20"] == 1.5e9 and bank["rs60"] == 0.2
    assert bank["pb"] == 0.6 and bank["pb_pct"] == 75.0   # [0.5,0.6] midrank
    assert bank["hist_start"] == "2026-09-01"
    # 无快照行业 → 全 None 行,不炸
    food = next(r for r in data["rows"] if r["sw_code"] == "801120")
    assert food["score"] is None and food["pb_pct"] is None
    assert food["hist_start"] is None


def test_detail_data_with_fake_repo_filters_and_truncates():
    # 25 只本行业(市值递减) + 5 只他行业 → sw_code_l1 过滤 + top20 截断
    members = (
        [{"symbol": f"6013{i:02d}", "name": f"行{i}", "sw_code_l1": "801780",
          "sw_name_l1": "银行", "pb": 0.5 + i * 0.01, "pe_ttm": 5.0 + i,
          "total_mv": (25 - i) * 1e10} for i in range(25)] +
        [{"symbol": f"0000{i:02d}", "name": f"外{i}", "sw_code_l1": "801120",
          "sw_name_l1": "食品饮料", "pb": 3.0, "pe_ttm": 25.0,
          "total_mv": 99e10} for i in range(5)])
    repo = _fake_repo(get_member_valuations=lambda d: members)
    with patch.object(industry_router, "_repo", return_value=repo):
        data = industry_router._detail_data("801780")
    assert data["name"] == "银行"
    assert data["prosperity"]["score"] == 66.0
    assert data["valuation_date"] == "2026-09-12"      # v_dates[-1]
    assert data["member_count"] == 25                  # 过滤前全量本行业
    assert len(data["members"]) == 20                  # top20 截断
    assert all(m["sw_code_l1"] == "801780" for m in data["members"])
    mv = [m["total_mv"] for m in data["members"]]
    assert mv == sorted(mv, reverse=True)              # 市值降序
    assert data["concentration"]["cr4"] == 35.0
    assert len(data["pb_histogram"]["counts"]) == 20   # 直方图照常产出


def test_strength_data_with_fake_repo_double_rebase():
    closes = {
        "sw801780": [(dt.date(2026, 1, 5), 10.0),
                     (dt.date(2026, 1, 6), 12.0),
                     (dt.date(2026, 1, 7), 11.0)],
        "sw801120": [(dt.date(2026, 1, 5), 20.0),
                     (dt.date(2026, 1, 6), 22.0),
                     (dt.date(2026, 1, 7), 26.0)],
        "sh000300": [(dt.date(2026, 1, 5), 100.0),
                     (dt.date(2026, 1, 6), 110.0),
                     (dt.date(2026, 1, 7), 99.0)],
    }
    repo = _fake_repo(get_index_closes=lambda symbols, start, end: closes)
    with patch.object(industry_router, "_repo", return_value=repo):
        data = industry_router._strength_data(
            "801780", ["801120", "bogus"])            # 非法 compare 被滤除
    assert set(data["lines"]) == {"801780", "801120"}
    for line in data["lines"].values():
        assert line[0]["rs"] == 1.0                    # 双 rebase 首点 1.0
    assert data["benchmark"][0]["close"] == 1.0
    assert data["names"] == {"801780": "银行", "801120": "食品饮料"}
    b = data["lines"]["801780"]
    assert b[2]["rs"] == round((11 / 10) / (99 / 100), 6)  # 标的/基准 rebase 商
