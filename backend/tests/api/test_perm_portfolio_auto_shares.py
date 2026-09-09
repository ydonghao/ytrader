"""create_portfolio 自动算 shares 集成测试。

验证: 新建组合时 holdings 不传 shares, 后端按
initial_capital × target_weight / 最近收盘价 自动计算。
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import create_app
    return TestClient(create_app())


def _cleanup_portfolio(client, name):
    r = client.get("/api/v1/perm-portfolio/portfolios?active_only=false")
    for p in r.json().get("data", []):
        if p["name"] == name:
            client.delete(f"/api/v1/perm-portfolio/portfolios/{p['id']}")


class TestAutoShares:
    """create_portfolio 自动算 shares 测试。"""

    def test_auto_shares_from_latest_close(self, client):
        """holdings 不传 shares → 按 initial_capital×权重/收盘价 自动算。"""
        pname = "TEST_AUTOSHARES_PORTFOLIO"
        try:
            # 用已有行情数据的标的 sh510300 (有 2456 条历史)
            r = client.get("/api/v1/perm-portfolio/instruments")
            inst = next(
                (i for i in r.json()["data"] if i["symbol"] == "sh510300"),
                None,
            )
            assert inst is not None, "sh510300 不在标的池"

            body = {
                "name": pname,
                "strategy_type": "custom",
                "initial_capital": 100000.0,
                "holdings": [
                    {
                        "instrument_id": inst["id"],
                        "target_weight": 0.5,
                        # 故意不传 shares
                    }
                ],
            }
            r = client.post("/api/v1/perm-portfolio/portfolios", json=body)
            assert r.status_code == 200
            j = r.json()
            assert j["code"] == 0, f"创建失败: {j}"
            pid = j["data"]["id"]

            # 验证 shares 被算出来了
            r2 = client.get(f"/api/v1/perm-portfolio/portfolios/{pid}")
            holdings = r2.json()["data"]["holdings"]
            assert len(holdings) == 1
            h = holdings[0]
            # sh510300 价格约 4-5 元, 100000×0.5/4.7 ≈ 10638 股
            assert h["shares"] > 0
            assert h["cost_price"] > 0  # cost_price 记了收盘价
            print(
                f"  自动算出 shares={h['shares']}, "
                f"cost_price={h['cost_price']}"
            )
        finally:
            _cleanup_portfolio(client, pname)

    def test_explicit_shares_not_overwritten(self, client):
        """holdings 显式传了 shares → 不被覆盖。"""
        pname = "TEST_EXPLICIT_SHARES"
        try:
            r = client.get("/api/v1/perm-portfolio/instruments")
            inst = next(
                (i for i in r.json()["data"] if i["symbol"] == "sh510300"),
                None,
            )
            body = {
                "name": pname,
                "strategy_type": "custom",
                "holdings": [
                    {
                        "instrument_id": inst["id"],
                        "target_weight": 1.0,
                        "shares": 888,
                        "cost_price": 10.0,
                    }
                ],
            }
            r = client.post("/api/v1/perm-portfolio/portfolios", json=body)
            pid = r.json()["data"]["id"]
            r2 = client.get(f"/api/v1/perm-portfolio/portfolios/{pid}")
            h = r2.json()["data"]["holdings"][0]
            assert h["shares"] == 888
            assert h["cost_price"] == 10.0
        finally:
            _cleanup_portfolio(client, pname)
