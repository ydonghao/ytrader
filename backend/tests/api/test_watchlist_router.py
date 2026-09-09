"""自选股 router 集成测试 — TestClient 打本地 PG，自带清理。

依赖本地 Postgres(见 tests/conftest.py 默认 db_dsn)。
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import create_app
    return TestClient(create_app())


def _cleanup(client, prefix="/api/v1/watchlist"):
    r = client.get(f"{prefix}/groups")
    for g in r.json().get("data", []) or []:
        client.delete(f"{prefix}/groups/{g['id']}")


class TestWatchlistRouter:
    PREFIX = "/api/v1/watchlist"

    def test_group_and_item_lifecycle(self, client):
        try:
            # 建分组
            r = client.post(f"{self.PREFIX}/groups", json={"name": "TS_G1"})
            assert r.status_code == 200 and r.json()["code"] == 0, r.text
            gid = r.json()["data"]["id"]

            # 重名拒绝
            r = client.post(f"{self.PREFIX}/groups", json={"name": "TS_G1"})
            assert r.json()["code"] != 0

            # 列分组带 item_count
            r = client.get(f"{self.PREFIX}/groups")
            g = next(x for x in r.json()["data"] if x["id"] == gid)
            assert g["item_count"] == 0

            # 加成员
            r = client.post(
                f"{self.PREFIX}/groups/{gid}/items",
                json={"symbol": "sh600519", "note": "x"},
            )
            assert r.json()["code"] == 0
            iid = r.json()["data"]["id"]

            # 重复加同 symbol 拒绝
            r = client.post(
                f"{self.PREFIX}/groups/{gid}/items",
                json={"symbol": "sh600519"},
            )
            assert r.json()["code"] != 0

            # 改备注
            r = client.put(f"{self.PREFIX}/items/{iid}", json={"note": "y"})
            assert r.json()["code"] == 0 and r.json()["data"]["note"] == "y"

            # 列成员
            r = client.get(f"{self.PREFIX}/groups/{gid}/items")
            assert len(r.json()["data"]) == 1

            # 跨组移动
            r = client.post(f"{self.PREFIX}/groups", json={"name": "TS_G2"})
            gid2 = r.json()["data"]["id"]
            r = client.post(
                f"{self.PREFIX}/items/move",
                json={"item_id": iid, "to_group_id": gid2},
            )
            assert r.json()["code"] == 0 and r.json()["data"]["group_id"] == gid2

            # 删分组级联
            client.delete(f"{self.PREFIX}/groups/{gid2}")
            r = client.get(f"{self.PREFIX}/groups/{gid2}/items")
            assert r.json()["data"] == []
        finally:
            _cleanup(client)
