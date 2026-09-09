# backend/tests/api/test_boom_router.py
"""boom_router 契约测试(service 打桩,不触网/库)。"""
import datetime as dt
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.api.router.boom_router import router


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


FAKE_STATS = {"in_season": True, "window_name": "2026Q3预告窗",
              "report_date": "2026-09-30", "pool": 3, "news_synced": 3,
              "hits": 7, "candidates": 3}


def test_radar_list(client):
    with patch("src.api.router.boom_router._radar_data") as fake:
        fake.return_value = {"season": {"in_season": True},
                             "report_dates": ["2026-09-30"],
                             "candidates": [{"symbol": "600519",
                                             "categories": ["supply_tight"],
                                             "hits_preview": []}],
                             "summary": {"pool": 1, "with_hits": 1}}
        r = client.get("/boom/radar")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["candidates"][0]["symbol"] == "600519"


def test_radar_detail_404(client):
    with patch("src.api.router.boom_router.create_boom_repository") as rep:
        rep.return_value.get_candidate.return_value = None
        r = client.get("/boom/radar/600000",
                       params={"report_date": "2026-09-30"})
    assert r.status_code == 404


def test_radar_detail_invalid_date_400(client):
    r = client.get("/boom/radar/600519", params={"report_date": "notadate"})
    assert r.status_code == 400
    assert "report_date" in r.json()["detail"]


def test_detail_returns_all_hits(client):
    """下钻返回全量命中,不截断为 preview。"""
    c = SimpleNamespace(symbol="600519", categories=["supply_tight"])
    hits = [SimpleNamespace(keyword=f"kw{i}", category="supply_tight",
                            source_type="news", source_date=dt.date(2026, 10, 2),
                            snippet=f"片段{i}")
            for i in range(7)]
    with patch("src.api.router.boom_router.create_boom_repository") as rep:
        rep.return_value.get_candidate.return_value = c
        rep.return_value.get_hits.return_value = hits
        r = client.get("/boom/radar/600519",
                       params={"report_date": "2026-09-30"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["hits"]) == 7
    assert "hits_preview" not in data


def test_detail_excludes_cross_window_hits(client):
    """跨报告窗的陈旧命中(source_date < report_date+1)不进下钻。"""
    c = SimpleNamespace(symbol="600519", categories=["supply_tight"])
    hits = [
        SimpleNamespace(keyword="旧命中", category="supply_tight",
                        source_type="news", source_date=dt.date(2026, 7, 1),
                        snippet="Q1 窗旧闻"),
        SimpleNamespace(keyword="新命中", category="supply_tight",
                        source_type="news", source_date=dt.date(2026, 10, 5),
                        snippet="Q3 窗新闻"),
    ]
    with patch("src.api.router.boom_router.create_boom_repository") as rep:
        rep.return_value.get_candidate.return_value = c
        rep.return_value.get_hits.return_value = hits
        r = client.get("/boom/radar/600519",
                       params={"report_date": "2026-09-30"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert [h["keyword"] for h in data["hits"]] == ["新命中"]


def test_analyze_invalid_report_date_400(client):
    r = client.post("/boom/analyze/600519", json={"report_date": "notadate"})
    assert r.status_code == 400
    assert "report_date" in r.json()["detail"]


def test_scan_run(client):
    with patch("src.api.router.boom_router.build_default_service") as svc:
        svc.return_value.run_daily.return_value = FAKE_STATS
        r = client.post("/boom/scan/run", json={})
    assert r.status_code == 200
    assert r.json()["data"]["pool"] == 3


def test_watchlist_add(client):
    with patch("src.api.router.boom_router.create_boom_repository") as rep:
        rep.return_value.get_candidate.return_value = object()
        rep.return_value.set_status.return_value = None
        with patch("src.api.router.boom_router._ensure_watchlist_group") as eg:
            eg.return_value = 99
            with patch("src.api.router.boom_router.watchlist_handler") as wh:
                wh.add_item.return_value = {"code": 0, "data": {"id": 1}}
                r = client.post("/boom/radar/600519/watchlist",
                                json={"report_date": "2026-09-30"})
    assert r.status_code == 200
    wh.add_item.assert_called_once_with(99, {"symbol": "sh600519"})


def test_watchlist_add_unwraps_jsonresponse(client):
    """handler 实际返回 JSONResponse,路由须解包后取 data。"""
    with patch("src.api.router.boom_router.create_boom_repository") as rep:
        rep.return_value.get_candidate.return_value = object()
        rep.return_value.set_status.return_value = None
        with patch("src.api.router.boom_router._ensure_watchlist_group") as eg:
            eg.return_value = 99
            with patch("src.api.router.boom_router.watchlist_handler") as wh:
                wh.add_item.return_value = JSONResponse(
                    status_code=200,
                    content={"code": 0, "msg": "ok", "data": {"id": 7}})
                r = client.post("/boom/radar/600519/watchlist",
                                json={"report_date": "2026-09-30"})
    assert r.status_code == 200
    assert r.json()["data"]["item"] == {"id": 7}


def test_watchlist_add_propagates_error(client):
    """handler 业务失败(code≠0)→ 400 并透出 msg。"""
    with patch("src.api.router.boom_router.create_boom_repository") as rep:
        rep.return_value.get_candidate.return_value = object()
        rep.return_value.set_status.return_value = None
        with patch("src.api.router.boom_router._ensure_watchlist_group") as eg:
            eg.return_value = 99
            with patch("src.api.router.boom_router.watchlist_handler") as wh:
                wh.add_item.return_value = JSONResponse(
                    content={"code": 10001, "msg": "已在分组", "data": None})
                r = client.post("/boom/radar/600519/watchlist",
                                json={"report_date": "2026-09-30"})
    assert r.status_code == 400
    assert "已在分组" in r.json()["detail"]


def test_keywords_crud(client):
    with patch("src.api.router.boom_router.create_boom_repository") as rep:
        kw = type("Kw", (), {"id": 1, "category": "supply_tight", "keyword": "一货难求",
                             "weight": 2, "enabled": True})()
        rep.return_value.list_keywords.return_value = [kw]
        r = client.get("/boom/keywords")
        assert r.status_code == 200
        assert r.json()["data"][0]["category_label"] == "供给紧张"

        rep.return_value.create_keyword.return_value = kw
        r = client.post("/boom/keywords",
                        json={"category": "supply_tight", "keyword": "一货难求",
                              "weight": 2})
        assert r.status_code == 200

        rep.return_value.update_keyword.return_value = kw
        r = client.put("/boom/keywords/1", json={"enabled": False})
        assert r.status_code == 200

        rep.return_value.delete_keyword.return_value = True
        r = client.delete("/boom/keywords/1")
        assert r.status_code == 200


def test_keywords_create_validates_category(client):
    with patch("src.api.router.boom_router.create_boom_repository"):
        r = client.post("/boom/keywords",
                        json={"category": "no_such_cat", "keyword": "x"})
    assert r.status_code == 400


def test_keywords_404_branches(client):
    with patch("src.api.router.boom_router.create_boom_repository") as rep:
        rep.return_value.update_keyword.return_value = None
        r = client.put("/boom/keywords/999", json={"enabled": False})
        assert r.status_code == 404

        rep.return_value.delete_keyword.return_value = False
        r = client.delete("/boom/keywords/999")
        assert r.status_code == 404


def test_keywords_update_validates_category(client):
    with patch("src.api.router.boom_router.create_boom_repository") as rep:
        rep.return_value.update_keyword.return_value = object()
        r = client.put("/boom/keywords/1", json={"category": "garbage"})
    assert r.status_code == 400
    rep.return_value.update_keyword.assert_not_called()


def test_analyze_endpoint(client):
    with patch("src.api.router.boom_router.create_boom_repository") as rep:
        cand = type("C", (), {"symbol": "600519", "report_date": dt.date(2026, 9, 30),
                              "llm_score": None, "keyword_count": 2,
                              "company_name": "X", "change_pct": 60.0,
                              "forecast_type_label": "预增",
                              "forecast_type": "preannounce",
                              "categories": ["supply_tight"],
                              "announce_date": dt.date(2026, 10, 12),
                              "keyword_count": 2, "news_hit_count": 1})()
        rep.return_value.get_candidate.return_value = cand
        rep.return_value.get_hits.return_value = []
        with patch("src.api.router.boom_router._run_analyze") as ra:
            ra.return_value = {"boom_score": 88, "verdict": "focus",
                               "summary": "s", "risks": []}
            r = client.post("/boom/analyze/600519",
                            json={"report_date": "2026-09-30"})
    assert r.status_code == 200
    assert r.json()["data"]["boom_score"] == 88


def test_backtest_endpoint(client):
    # 端点函数体内 import,patch 源模块属性即可生效
    with patch("src.domain.market.boom.backtest.run_full_backtest") as rfb:
        rfb.return_value = {"n_events": 10, "n_traded": 8, "avg_excess": 5.0,
                            "by_year": [], "by_category": [], "meta": {}}
        r = client.post("/boom/backtest",
                        json={"start_year": 2024, "end_year": 2025})
    assert r.status_code == 200
    assert r.json()["data"]["n_events"] == 10
    rfb.assert_called_once_with(start_year=2024, end_year=2025,
                                min_change_pct=50.0, hold_months=3,
                                with_text=False, benchmark="sh000300")


def test_backtest_endpoint_validates_span(client):
    r = client.post("/boom/backtest",
                    json={"start_year": 2010, "end_year": 2026})
    assert r.status_code == 400            # 跨度>10年拒绝
