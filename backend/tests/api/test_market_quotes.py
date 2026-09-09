"""POST /market/quotes 集成测试(本地 PG)。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import create_app
    return TestClient(create_app())


class TestMarketQuotes:
    def test_known_and_unknown_symbols(self, client):
        r = client.post(
            "/api/v1/market/quotes",
            json={"symbols": ["sh600519", "THIS_DOES_NOT_EXIST_xxx"]},
        )
        assert r.status_code == 200
        j = r.json()
        assert j["code"] == 0
        data = j["data"]
        syms = {d["symbol"] for d in data}
        assert "sh600519" in syms
        assert "THIS_DOES_NOT_EXIST_xxx" not in syms  # 无行情略过
        row = next(d for d in data if d["symbol"] == "sh600519")
        assert isinstance(row["price"], (int, float))
        assert isinstance(row["change_pct"], (int, float))
        # 估值字段允许为 null, 但键必须存在
        for k in ("pe", "pb", "dv_ttm", "total_mv"):
            assert k in row

    def test_empty_symbols_returns_empty(self, client):
        r = client.post("/api/v1/market/quotes", json={"symbols": []})
        assert r.json() == {"code": 0, "msg": "ok", "data": []}
