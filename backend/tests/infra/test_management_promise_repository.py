"""management_promise 仓储 sqlite 测试 + 端点测试（假仓储/假 psycopg2）。"""
import datetime as dt
import sys
import os
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

from src.infra.database.market.management_promise import (  # noqa: E402
    ManagementPromise,
    ManagementPromiseRepository,
)


class _SqliteDb:
    def __init__(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(
            self.engine, tables=[ManagementPromise.__table__])

    @contextmanager
    def session_scope(self):
        session = Session(self.engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


@pytest.fixture()
def repo():
    return ManagementPromiseRepository(_SqliteDb())


def test_forecast_upsert_idempotent(repo):
    row = {
        "symbol": "sz000002", "category": "业绩指引",
        "content": "净利润预告·预增", "promise_date": dt.date(2025, 1, 20),
        "target_report_date": dt.date(2024, 12, 31),
        "metric": "净利润", "forecast_value": 100.0,
        "actual_value": 105.0, "status": "fulfilled",
        "deviation_pct": 5.0, "detail": "x",
    }
    assert repo.upsert_forecast(row) == "inserted"
    row["actual_value"] = None
    row["status"] = "pending"
    assert repo.upsert_forecast(row) == "updated"   # 同键不重复插入
    rows = repo.list("sz000002")
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"


def test_manual_add_verify_delete(repo):
    row = repo.add_manual({
        "symbol": "sh600519", "category": "分红",
        "content": "承诺分红率不低于 75%",
        "promise_date": dt.date(2025, 3, 28),
    })
    assert row["status"] == "pending" and row["source"] == "manual"
    v = repo.verify(row["id"], "fulfilled", "2025 年报分红率 75.8%")
    assert v["status"] == "fulfilled" and v["verified_at"]
    assert repo.delete(row["id"]) is True
    assert repo.get(row["id"]) is None


# ── 端点（假仓储 + 假 psycopg2） ──────────────────────────────────────────

from src.api.router import management_promise_router as _mod  # noqa: E402

app = FastAPI()
app.include_router(_mod.router, prefix="/api/v1")


class _FakeRepo:
    _rows: list = []
    _next_id = 1

    @staticmethod
    def _iso(v):
        # 对齐真仓储 _dict：date → isoformat 字符串（否则 JSONResponse
        # 序列化失败）
        return v.isoformat() if isinstance(v, dt.date) else v

    def upsert_forecast(self, row):
        # 入参统一先过 _iso，与存量口径一致（否则 date vs 字符串
        # 永不相等，幂等判定失效）
        row = {k: self._iso(v) for k, v in row.items()}
        for r in self._rows:
            if (r["symbol"] == row["symbol"]
                    and r["source"] == "forecast"
                    and r["metric"] == row["metric"]
                    and r["target_report_date"]
                    == row["target_report_date"]):
                r.update(row)
                return "updated"
        row = dict(row, id=self._next_id, source="forecast",
                   evidence=None, verified_at=None,
                   created_at="2026-10-03T12:00:00")
        _FakeRepo._rows.append(row)
        _FakeRepo._next_id += 1
        return "inserted"

    def add_manual(self, data):
        data = {k: self._iso(v) for k, v in data.items()}
        row = dict(data, id=self._next_id, source="manual",
                   metric=None, forecast_value=None, actual_value=None,
                   status="pending", deviation_pct=None,
                   evidence=None, verified_at=None,
                   created_at="2026-10-03T12:00:00")
        _FakeRepo._rows.append(row)
        _FakeRepo._next_id += 1
        return dict(row)

    def list(self, symbol):
        return [dict(r) for r in self._rows if r["symbol"] == symbol]

    def get(self, row_id):
        return next((dict(r) for r in self._rows if r["id"] == row_id),
                    None)

    def verify(self, row_id, status, evidence):
        r = next((x for x in self._rows if x["id"] == row_id), None)
        if not r:
            return None
        r["status"] = status
        r["evidence"] = evidence
        r["verified_at"] = "2026-10-03T12:30:00"
        return dict(r)

    def delete(self, row_id):
        n = len(self._rows)
        _FakeRepo._rows[:] = [r for r in self._rows
                              if r["id"] != row_id]
        return len(self._rows) < n

    def add_annual_report(self, data):
        data = {k: (v.isoformat() if isinstance(v, dt.date) else v)
                for k, v in data.items()}   # 对齐真仓储 _dict 口径
        dup = next((r for r in self._rows
                    if r["symbol"] == data["symbol"]
                    and r.get("source") == "annual_report"
                    and r["content"] == data["content"]), None)
        if dup:
            return "duplicated"
        row = dict(id=self._next_id, source="annual_report",
                   status="pending", metric=None,
                   forecast_value=None, actual_value=None,
                   deviation_pct=None, evidence=None,
                   verified_at=None, target_report_date=None,
                   created_at="2026-10-03T14:00", **data)
        _FakeRepo._rows.append(row)
        _FakeRepo._next_id += 1
        return "inserted"


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self._rows)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakePsycopg2:
    def __init__(self, conns):
        self._conns = list(conns)
        self._i = 0

    def connect(self, dsn=None):
        # 循环取用：一次 import 消耗 2 个连接（预告/实际），
        # 重复 import（幂等测试）也能按同序拿到
        conn = self._conns[self._i % len(self._conns)]
        self._i += 1
        return conn


@pytest.fixture()
def patched(monkeypatch):
    _FakeRepo._rows = []
    _FakeRepo._next_id = 1
    from src.infra.database.market import management_promise as mp
    monkeypatch.setattr(
        mp, "create_management_promise_repository",
        lambda *a, **k: _FakeRepo())

    def _with_db(forecast_rows, actual_rows):
        monkeypatch.setattr(
            "src.api.handler.management_promise_handler.psycopg2",
            _FakePsycopg2([_FakeConn(forecast_rows),
                           _FakeConn(actual_rows)]))

    return _with_db


def test_manual_promise_lifecycle(patched):
    client = TestClient(app)
    r = client.post("/api/v1/management-promises/sh600519",
                    json={"category": "分红",
                          "content": "承诺分红率不低于 75%"})
    assert r.json()["code"] == 0, r.text
    pid = r.json()["data"]["id"]
    # 缺内容被拒
    bad = client.post("/api/v1/management-promises/sh600519",
                      json={"category": "分红", "content": " "})
    assert bad.json()["code"] != 0
    # 列表 + 信用
    lst = client.get("/api/v1/management-promises/sh600519").json()
    assert lst["data"]["credit"]["pending"] == 1
    # 人工验证
    v = client.post(f"/api/v1/management-promises/{pid}/verify",
                    json={"status": "fulfilled",
                          "evidence": "2025 年报分红率 75.8%"})
    assert v.json()["data"]["status"] == "fulfilled"
    assert client.get(
        "/api/v1/management-promises/sh600519"
    ).json()["data"]["credit"]["credit_pct"] == 100.0
    # 删除
    assert client.delete(
        f"/api/v1/management-promises/{pid}").json()["code"] == 0


def test_import_forecasts_assess_and_idempotent(patched):
    patched(
        forecast_rows=[
            {"metric": "净利润", "report_date": dt.date(2024, 12, 31),
             "announce_date": dt.date(2025, 1, 20),
             "forecast_value": 100.0, "prev_value": 80.0,
             "forecast_type_label": "预增",
             "raw": {"业绩变动原因": "主业增长"}},
            {"metric": "营业收入", "report_date": dt.date(2023, 12, 31),
             "announce_date": dt.date(2024, 1, 15),
             "forecast_value": 50.0, "prev_value": 45.0,
             "forecast_type_label": "略增", "raw": {}},
        ],
        actual_rows=[
            # 净利润实际 105（+5% → fulfilled）
            {"report_date": dt.date(2024, 12, 31),
             "revenue": None, "net_profit": 105.0,
             "net_profit_parent": None, "net_profit_deduct": None},
            # 营收实际未披露 → pending
        ],
    )
    client = TestClient(app)
    r = client.post("/api/v1/management-promises/sz000002/import-forecasts")
    j = r.json()
    assert j["code"] == 0, r.text
    assert j["data"]["scanned"] == 2
    rows = client.get(
        "/api/v1/management-promises/sz000002").json()["data"]["rows"]
    by_metric = {x["metric"]: x for x in rows}
    assert by_metric["净利润"]["status"] == "fulfilled"
    assert by_metric["净利润"]["deviation_pct"] == 5.0
    assert by_metric["营业收入"]["status"] == "pending"
    # 幂等：再导一次 updated 而非重复插入
    r2 = client.post(
        "/api/v1/management-promises/sz000002/import-forecasts")
    assert r2.json()["data"]["inserted"] == 0
    assert r2.json()["data"]["updated"] == 2
    assert len(client.get(
        "/api/v1/management-promises/sz000002").json()["data"]["rows"]) == 2


def test_import_direction_broken(patched):
    patched(
        forecast_rows=[
            # 预增：预告 100 > 上年 80，实际 75（同比转降）
            {"metric": "净利润", "report_date": dt.date(2024, 12, 31),
             "announce_date": dt.date(2025, 1, 20),
             "forecast_value": 100.0, "prev_value": 80.0,
             "forecast_type_label": "预增", "raw": {}},
        ],
        actual_rows=[
            {"report_date": dt.date(2024, 12, 31),
             "revenue": None, "net_profit": 75.0,
             "net_profit_parent": None, "net_profit_deduct": None},
        ],
    )
    client = TestClient(app)
    assert client.post(
        "/api/v1/management-promises/sz000002/import-forecasts"
    ).json()["code"] == 0
    row = client.get(
        "/api/v1/management-promises/sz000002").json()["data"]["rows"][0]
    assert row["status"] == "broken"
    assert "转降" in row["detail"]


def test_import_no_forecasts(patched):
    patched(forecast_rows=[], actual_rows=[])
    client = TestClient(app)
    r = client.post(
        "/api/v1/management-promises/sh600519/import-forecasts")
    assert r.json()["code"] != 0
    assert "预告" in r.json()["msg"]


def test_add_annual_report_dedupe(repo):
    row = {"symbol": "sh600519", "category": "分红",
           "content": "未来三年分红率不低于75%",
           "promise_date": dt.date(2025, 4, 3),
           "detail": "2024 年报 MD&A 抽取"}
    assert repo.add_annual_report(row) == "inserted"
    assert repo.add_annual_report(dict(row)) == "duplicated"
    rows = repo.list("sh600519")
    assert len(rows) == 1
    assert rows[0]["source"] == "annual_report"
    assert rows[0]["status"] == "pending"    # V2:LLM只抽取,人工验证


@pytest.mark.asyncio
async def test_import_annual_reports_endpoint(monkeypatch):
    _FakeRepo._rows = []
    _FakeRepo._next_id = 1
    from src.infra.database.market import management_promise as mp
    monkeypatch.setattr(
        mp, "create_management_promise_repository",
        lambda *a, **k: _FakeRepo())

    async def _fake_extract(symbol, years=2):
        return {
            "symbol": symbol,
            "reports": [{"title": "茅台2024年年度报告",
                         "year": "2024",
                         "announce_date": "2025-04-03",
                         "promises": [
                             {"content": "2025年营业总收入增长9%左右",
                              "category": "业绩指引", "period": "2025年度",
                              "announce_date": "2025-04-03",
                              "year": "2024"}],
                         "skipped": None, "model": "glm-5.3"}],
            "promises": [
                {"content": "2025年营业总收入增长9%左右",
                 "category": "业绩指引", "period": "2025年度",
                 "announce_date": "2025-04-03", "year": "2024"}],
        }

    # handler 函数内 import,patch 源模块即可
    from src.domain.market.fundamental import annual_mda
    monkeypatch.setattr(annual_mda, "extract_promises", _fake_extract)

    client = TestClient(app)
    r = client.post(
        "/api/v1/management-promises/sh600519/import-annual-reports",
        json={"years": 1})
    j = r.json()
    assert j["code"] == 0, r.text
    assert j["data"]["extracted"] == 1
    assert j["data"]["inserted"] == 1
    rows = client.get(
        "/api/v1/management-promises/sh600519"
    ).json()["data"]["rows"]
    assert rows[0]["source"] == "annual_report"
    assert "目标期间：2025年度" in rows[0]["detail"]
    # 再导一次 → 全部去重
    r2 = client.post(
        "/api/v1/management-promises/sh600519/import-annual-reports",
        json={"years": 1})
    assert r2.json()["data"]["duplicated"] == 1
