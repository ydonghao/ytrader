"""valuation_assumption 仓储 CRUD 测试（sqlite 内存）+ 假设版本端点测试。"""
import sys
import os
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

from src.infra.database.market.valuation_assumption import (  # noqa: E402
    ValuationAssumption,
    ValuationAssumptionRepository,
)


class _SqliteDb:
    def __init__(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(
            self.engine, tables=[ValuationAssumption.__table__])

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
    return ValuationAssumptionRepository(_SqliteDb())


def test_version_increments_per_symbol_method(repo):
    r1 = repo.add("sh600519", "dcf",
                  {"growth_rate": 0.08, "wacc": 0.09},
                  output={"intrinsic_value": 100.0}, note="初版")
    r2 = repo.add("sh600519", "dcf", {"growth_rate": 0.10})
    r3 = repo.add("sh600519", "ddm", {"g": 0.05})
    assert (r1["version"], r2["version"], r3["version"]) == (1, 2, 1)
    rows = repo.list("sh600519")
    assert len(rows) == 3
    dcf_rows = repo.list("sh600519", method="dcf")
    assert [r["version"] for r in dcf_rows] == [2, 1]   # 版本倒序
    assert dcf_rows[1]["output"] == {"intrinsic_value": 100.0}
    assert repo.delete(r3["id"]) is True
    assert repo.get(r3["id"]) is None
    assert repo.delete(999) is False


# ── 端点（monkeypatch 假仓储 + 假 DCF 输出） ─────────────────────────────

from src.api.router import financial_router as _mod  # noqa: E402

app = FastAPI()
app.include_router(_mod.router, prefix="/api/v1")


class _FakeRepo:
    _rows: list = []
    _next_id = 1

    def add(self, symbol, method, assumptions, output=None, note=None):
        vers = [r["version"] for r in self._rows
                if r["symbol"] == symbol and r["method"] == method]
        row = {"id": self._next_id, "symbol": symbol, "method": method,
               "version": (max(vers) + 1) if vers else 1,
               "assumptions": assumptions, "output": output,
               "note": note, "created_at": "2026-10-03T12:00:00"}
        self._rows.append(row)
        self._next_id += 1
        return dict(row)

    def list(self, symbol, method=None):
        return [dict(r) for r in self._rows
                if r["symbol"] == symbol
                and (method is None or r["method"] == method)]

    def get(self, row_id):
        return next((dict(r) for r in self._rows if r["id"] == row_id),
                    None)

    def delete(self, row_id):
        n = len(self._rows)
        # 原地改类列表：_assumption_repo() 每次返回新实例，
        # 重绑 self._rows 会变实例属性、对后续实例不可见
        _FakeRepo._rows[:] = [r for r in self._rows
                              if r["id"] != row_id]
        return len(_FakeRepo._rows) < n


@pytest.fixture()
def patched(monkeypatch):
    _FakeRepo._rows = []
    _FakeRepo._next_id = 1
    from src.api.handler import financial_detail_handler as h
    from src.infra.database.market import valuation_assumption as va
    monkeypatch.setattr(
        h, "_assumption_repo", lambda: _FakeRepo())
    monkeypatch.setattr(
        va, "create_valuation_assumption_repository",
        lambda *a, **k: _FakeRepo())
    calls = {}
    dcf_calls = {"n": 0}

    def _fake_dcf(symbol, growth_rate=0.08, terminal_growth=0.03,
                  wacc=0.09, projection_years=10):
        calls["params"] = {k: v for k, v in (
            ("growth_rate", growth_rate),
            ("terminal_growth", terminal_growth),
            ("wacc", wacc),
            ("projection_years", projection_years)) if v is not None}
        dcf_calls["n"] += 1
        # 第 1 次=保存时快照(mv=120)；之后=重跑(市值跌 30% → 情绪驱动)
        mv = 120.0 if dcf_calls["n"] == 1 else 84.0
        return {"code": 0, "data": {
            "intrinsic_value": 200.0, "market_value": mv,
            "margin_of_safety": (200.0 - mv) / 200.0, "fcf_base": 6.0,
            "report_date": "2026-06-30", "fcf_method": "ttm"}}

    monkeypatch.setattr(h, "dcf_valuation", _fake_dcf)
    return calls


def test_assumption_endpoints_flow(patched):
    client = TestClient(app)
    # 保存：服务端即时算输出快照
    r = client.post("/api/v1/financial/valuation-assumptions/sh600519",
                    json={"assumptions": {"growth_rate": 0.08,
                                          "wacc": 0.09,
                                          "projection_years": 10},
                          "note": "白酒稳态"})
    assert r.json()["code"] == 0, r.text
    row = r.json()["data"]
    assert row["version"] == 1
    assert row["output"]["intrinsic_value"] == 200.0
    assert patched["params"]["projection_years"] == 10
    # 假设不合法
    bad = client.post(
        "/api/v1/financial/valuation-assumptions/sh600519",
        json={"assumptions": {"foo": 1}})
    assert bad.json()["code"] != 0
    # 列表
    lst = client.get("/api/v1/financial/valuation-assumptions/sh600519")
    assert len(lst.json()["data"]) == 1
    lst_dcf = client.get(
        "/api/v1/financial/valuation-assumptions/sh600519?method=dcf")
    assert len(lst_dcf.json()["data"]) == 1
    # 重跑对比（存档 mv=120，重跑 mv=84 → 内在价值不变、市值 -30% → 情绪驱动）
    rr = client.post(
        f"/api/v1/financial/valuation-assumptions/{row['id']}/rerun")
    assert rr.json()["code"] == 0, rr.text
    cmp = rr.json()["data"]
    assert cmp["intrinsic_delta_pct"] == 0.0
    assert cmp["market_delta_pct"] == -30.0
    assert cmp["driver"] == "情绪驱动：市值下跌"
    assert cmp["assumption"]["version"] == 1
    # 删除
    d = client.delete(
        f"/api/v1/financial/valuation-assumptions/{row['id']}")
    assert d.json()["code"] == 0
    gone = client.get("/api/v1/financial/valuation-assumptions/sh600519")
    assert gone.json()["data"] == []
