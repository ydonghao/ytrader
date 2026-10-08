"""统一收件箱端点测试：三源合并 + 一源失败降级。"""
import sys
import os
import datetime as dt

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import importlib
mod = importlib.import_module("src.api.router.alerts_router")  # noqa: E402
from src.infra.database.portfolio import thesis_repository  # noqa: E402


class _PriceAlert:
    symbol = "sh600519"
    direction = "above"
    target_price = 1800.0
    triggered_at = dt.datetime(2026, 9, 26, 15, 0)
    created_at = dt.datetime(2026, 9, 1, 9, 0)


class _MetricAlert:
    symbol = "sz000001"
    metric_kind = "pe_ttm"
    direction = "above"
    threshold = 10.0
    triggered_at = dt.datetime(2026, 9, 27, 16, 15)
    created_at = dt.datetime(2026, 9, 1, 9, 0)


class _AlertRepo:
    def list_alerts(self, status=None, limit=200, offset=0):
        return [_PriceAlert()] if status == "triggered" else []

    def list_metric_alerts(self, status=None, limit=200, offset=0):
        return [_MetricAlert()] if status == "triggered" else []


class _ThesisRepo:
    def list_theses(self):
        return [{"id": 1, "symbol": "sh600036"}]

    def list_events(self, unread_only=False, limit=100):
        return [{
            "id": 9, "thesis_id": 1, "kind": "reeval_done",
            "detail": {"verdict": "review"}, "read": False,
            "created_at": "2026-09-27T17:35:00",
        }]


app = FastAPI()
app.include_router(mod.router, prefix="/api/v1")


def test_unified_merged_sorted(monkeypatch):
    monkeypatch.setattr(mod, "create_alert_repository",
                        lambda: _AlertRepo())
    monkeypatch.setattr(
        thesis_repository, "create_thesis_repository",
        lambda: _ThesisRepo())
    client = TestClient(app)
    r = client.get("/api/v1/alerts/unified")
    d = r.json()["data"]
    assert [i["kind"] for i in d] == ["thesis", "metric", "price"]
    assert d[0]["symbol"] == "sh600036" and d[0]["read"] is False
    assert d[2]["message"] == "上穿 1800.0"


def test_unified_degrades_when_thesis_fails(monkeypatch):
    monkeypatch.setattr(mod, "create_alert_repository",
                        lambda: _AlertRepo())

    def _boom():
        raise RuntimeError("x")

    monkeypatch.setattr(
        thesis_repository, "create_thesis_repository", _boom)
    client = TestClient(app)
    r = client.get("/api/v1/alerts/unified")
    kinds = [i["kind"] for i in r.json()["data"]]
    assert "thesis" not in kinds and "price" in kinds
