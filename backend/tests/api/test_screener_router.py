"""screener_router 测试：list_modes 含新模式 + exclude-ranges 端点。"""
import os
import sys
import shutil
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


# ── 公共 fixture：最小 FastAPI app，只挂 screener_router ─────────────────────────
@pytest.fixture
def client(tmp_path):
    """构建仅含 screener 路由的 TestClient，并把 _DEFAULT_CONFIG_PATH 重定向到
    临时副本，避免污染真实 config.yaml。"""
    from src.api.router.screener_router import router as screener_router
    from conf.settings import _DEFAULT_CONFIG_PATH
    import conf.settings as settings_mod

    # 复制真实 config.yaml 到临时位置，端点回写时只改副本
    tmp_cfg = tmp_path / "config_test.yaml"
    shutil.copyfile(_DEFAULT_CONFIG_PATH, tmp_cfg)

    original_path = settings_mod._DEFAULT_CONFIG_PATH
    settings_mod._DEFAULT_CONFIG_PATH = str(tmp_cfg)

    app = FastAPI()
    app.include_router(screener_router, prefix="/api/v1")

    with TestClient(app) as c:
        yield c

    # 还原
    settings_mod._DEFAULT_CONFIG_PATH = original_path


@pytest.fixture
def saved_ranges():
    """备份/还原 app_config 内存中的 exclude_ranges。"""
    from conf import app_config
    original = list(app_config.screener.dividend_value.exclude_ranges)
    yield original
    app_config.screener.dividend_value.exclude_ranges = original


def test_list_modes_includes_dividend_value(client):
    resp = client.get("/api/v1/screener/modes")
    assert resp.status_code == 200
    body = resp.json()
    modes = [m["mode"] for m in body["data"]]
    assert "dividend_value" in modes
    dv = next(m for m in body["data"] if m["mode"] == "dividend_value")
    assert "filters_default" in dv
    assert "value_metric" in dv["filters_default"]


def test_exclude_ranges_get_and_put(client, saved_ranges):
    # GET
    resp = client.get("/api/v1/screener/exclude-ranges")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert "ranges" in body["data"]

    # PUT（写一条，再读回）
    resp2 = client.put("/api/v1/screener/exclude-ranges", json={
        "ranges": [["2015-06-15", "2015-12-31"]]
    })
    assert resp2.status_code == 200
    assert resp2.json()["code"] == 0

    # 读回验证
    resp3 = client.get("/api/v1/screener/exclude-ranges")
    ranges = resp3.json()["data"]["ranges"]
    assert ["2015-06-15", "2015-12-31"] in ranges
