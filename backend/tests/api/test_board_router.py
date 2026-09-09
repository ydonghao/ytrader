"""自定义看板 router 集成测试 — TestClient 打本地 PG,自带清理。

依赖本地 Postgres(见 tests/conftest.py 默认 db_dsn)。
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import create_app
    return TestClient(create_app())


def _cleanup(client, prefix="/api/v1/board"):
    """只删本套件创建的 TS_ 前缀看板,避免误删真实数据(conftest 默认真实 DSN)。"""
    r = client.get(f"{prefix}/boards")
    for b in r.json().get("data", []) or []:
        if str(b["name"]).startswith("TS_"):
            client.delete(f"{prefix}/boards/{b['id']}")


LAYOUT = {
    "version": 1,
    "timeRange": {"preset": "1y", "start": None, "end": None},
    "maxZ": 1,
    "cards": [
        {
            "id": "u1", "type": "kline", "title": "贵州茅台",
            "symbol": "sh600519", "config": {},
            "x": 0, "y": 0, "w": 6, "h": 14, "z": 1, "opacity": 1,
        }
    ],
}


class TestBoardRouter:
    PREFIX = "/api/v1/board"

    def test_board_lifecycle(self, client):
        try:
            # 建看板(空布局)
            r = client.post(f"{self.PREFIX}/boards", json={"name": "TS_BOARD"})
            assert r.status_code == 200 and r.json()["code"] == 0, r.text
            bid = r.json()["data"]["id"]
            assert r.json()["data"]["layout"]["cards"] == []

            # 重名拒绝
            r = client.post(f"{self.PREFIX}/boards", json={"name": "TS_BOARD"})
            assert r.json()["code"] != 0

            # 列表轻量(不含 layout)
            r = client.get(f"{self.PREFIX}/boards")
            row = next(x for x in r.json()["data"] if x["id"] == bid)
            assert "layout" not in row

            # 保存布局(全量替换)
            r = client.put(
                f"{self.PREFIX}/boards/{bid}", json={"layout": LAYOUT}
            )
            assert r.json()["code"] == 0
            r = client.get(f"{self.PREFIX}/boards/{bid}")
            assert r.json()["data"]["layout"] == LAYOUT

            # 二次保存替换(旧卡片不残留)
            r = client.put(
                f"{self.PREFIX}/boards/{bid}",
                json={"layout": {"version": 1, "cards": [], "maxZ": 0}},
            )
            assert r.json()["code"] == 0
            r = client.get(f"{self.PREFIX}/boards/{bid}")
            assert r.json()["data"]["layout"]["cards"] == []

            # 重命名 + 重名校验(排除自身)
            r = client.post(
                f"{self.PREFIX}/boards", json={"name": "TS_BOARD2"}
            )
            bid2 = r.json()["data"]["id"]
            r = client.put(
                f"{self.PREFIX}/boards/{bid}", json={"name": "TS_BOARD2"}
            )
            assert r.json()["code"] != 0
            r = client.put(
                f"{self.PREFIX}/boards/{bid}", json={"name": "TS_BOARD_REN"}
            )
            assert (
                r.json()["code"] == 0
                and r.json()["data"]["name"] == "TS_BOARD_REN"
            )

            # 非法 layout 拒绝
            r = client.put(
                f"{self.PREFIX}/boards/{bid}", json={"layout": "oops"}
            )
            assert r.json()["code"] != 0

            # 删除 + 再取失败
            assert (
                client.delete(f"{self.PREFIX}/boards/{bid}").json()["code"]
                == 0
            )
            r = client.get(f"{self.PREFIX}/boards/{bid}")
            assert r.json()["code"] != 0
            client.delete(f"{self.PREFIX}/boards/{bid2}")
        finally:
            _cleanup(client)

    def test_create_requires_name(self, client):
        try:
            r = client.post(f"{self.PREFIX}/boards", json={"name": "  "})
            assert r.json()["code"] != 0
        finally:
            _cleanup(client)

    def test_missing_board_fails(self, client):
        try:
            r = client.put(f"{self.PREFIX}/boards/999999", json={"name": "X"})
            assert r.json()["code"] != 0
            r = client.delete(f"{self.PREFIX}/boards/999999")
            assert r.json()["code"] != 0
            r = client.get(f"{self.PREFIX}/boards/999999")
            assert r.json()["code"] != 0
        finally:
            _cleanup(client)
