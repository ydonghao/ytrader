"""argument_note 仓储 sqlite 测试 + 论证库端点测试（LLM/上下文替身）。"""
import sys
import os
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

from src.infra.database.market.argument_note import (  # noqa: E402
    ArgumentNote,
    ArgumentNoteRepository,
)


class _SqliteDb:
    def __init__(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(
            self.engine, tables=[ArgumentNote.__table__])

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
    return ArgumentNoteRepository(_SqliteDb())


def test_draft_single_per_side_and_archive(repo):
    d1 = repo.save_draft("sh600519", "bull", "初稿 v1",
                         generated_by="test-model")
    d2 = repo.save_draft("sh600519", "bull", "初稿 v2（覆盖）",
                         generated_by="test-model")
    assert d2["id"] == d1["id"]          # 同 side 单草稿，覆盖不新增
    assert d2["content"].endswith("v2（覆盖）")
    assert d2["status"] == "draft"
    a = repo.archive(d2["id"], evidence="已逐条核对年报")
    assert a["status"] == "archived" and a["evidence"] == "已逐条核对年报"
    # 归档后再生成 → 新草稿与归档历史并存
    d3 = repo.save_draft("sh600519", "bull", "新一轮初稿")
    rows = repo.list("sh600519")
    assert len(rows) == 2
    assert rows[0]["status"] == "draft"  # draft 优先在前
    assert repo.delete(d3["id"]) is True


def test_manual_add_and_update(repo):
    row = repo.add_manual({"symbol": "sh600519", "side": "bear",
                           "content": "估值透支论"})
    assert row["status"] == "archived" and row["generated_by"] == "manual"
    up = repo.update(row["id"], content="估值透支论（修订）",
                     evidence="PE 分位 95%")
    assert up["content"].endswith("（修订）")


# ── 端点（假仓储 + LLM/上下文替身） ───────────────────────────────────────

from src.api.router import argument_router as _mod  # noqa: E402

app = FastAPI()
app.include_router(_mod.router, prefix="/api/v1")


class _FakeRepo:
    _rows: list = []
    _next_id = 1

    def save_draft(self, symbol, side, content, generated_by=None,
                   context=None):
        for r in self._rows:
            if (r["symbol"] == symbol and r["side"] == side
                    and r["status"] == "draft"):
                r.update(content=content, generated_by=generated_by,
                         context=context, updated_at="2026-10-03T13:00")
                return dict(r)
        row = dict(id=self._next_id, symbol=symbol, side=side,
                   status="draft", content=content, evidence=None,
                   generated_by=generated_by, context=context,
                   created_at="2026-10-03T13:00",
                   updated_at="2026-10-03T13:00")
        _FakeRepo._rows.append(row)
        _FakeRepo._next_id += 1
        return dict(row)

    def add_manual(self, data):
        row = dict(id=self._next_id, status="archived",
                   generated_by="manual", evidence=data.get("evidence"),
                   context=None, created_at="2026-10-03T13:00",
                   updated_at="2026-10-03T13:00", **{
                       k: v for k, v in data.items()
                       if k != "evidence"})
        _FakeRepo._rows.append(row)
        _FakeRepo._next_id += 1
        return dict(row)

    def list(self, symbol):
        return sorted(
            [dict(r) for r in self._rows if r["symbol"] == symbol],
            key=lambda r: (r["status"] != "draft", r["updated_at"]),
            reverse=False)

    def get(self, row_id):
        return next((dict(r) for r in self._rows
                     if r["id"] == row_id), None)

    def update(self, row_id, content=None, evidence=None):
        r = next((x for x in self._rows if x["id"] == row_id), None)
        if not r:
            return None
        if content is not None:
            r["content"] = content
        if evidence is not None:
            r["evidence"] = evidence
        return dict(r)

    def archive(self, row_id, evidence=None):
        r = next((x for x in self._rows if x["id"] == row_id), None)
        if not r:
            return None
        r["status"] = "archived"
        if evidence:
            r["evidence"] = evidence
        return dict(r)

    def delete(self, row_id):
        n = len(self._rows)
        _FakeRepo._rows[:] = [r for r in self._rows
                              if r["id"] != row_id]
        return len(self._rows) < n


@pytest.fixture()
def patched(monkeypatch):
    _FakeRepo._rows = []
    _FakeRepo._next_id = 1
    from src.infra.database.market import argument_note as an
    monkeypatch.setattr(
        an, "create_argument_note_repository",
        lambda *a, **k: _FakeRepo())
    from src.api.handler import argument_handler as h
    monkeypatch.setattr(
        h, "collect_fundamental_context",
        lambda sym, periods=12: {"series": [], "data_available": True})
    monkeypatch.setattr(
        h, "format_context_for_prompt", lambda ctx: "MOCK_CONTEXT")

    async def _fake_llm(prompt):
        assert "MOCK_CONTEXT" in prompt
        assert "sh600519" in prompt
        return f"【AI初稿】基于上下文的论证（{prompt[:8]}…）", "fake-model"

    monkeypatch.setattr(h, "_call_llm", _fake_llm)
    monkeypatch.setattr(h, "_extra_context",
                        lambda sym: "\n附加诊断：MOCK_EXTRA\n")
    return h


def test_generate_draft_and_archive_flow(patched):
    client = TestClient(app)
    r = client.post("/api/v1/arguments/sh600519/generate",
                    json={"side": "bull"})
    assert r.json()["code"] == 0, r.text
    draft = r.json()["data"]
    assert draft["status"] == "draft"
    assert draft["generated_by"] == "fake-model"
    assert draft["content"].startswith("【AI初稿】")
    assert "MOCK_EXTRA" in draft["context"]["extra"]
    # 非法 side
    bad = client.post("/api/v1/arguments/sh600519/generate",
                      json={"side": "long"})
    assert bad.json()["code"] != 0
    # 编辑（核对修订）
    up = client.put(f"/api/v1/arguments/{draft['id']}",
                    json={"content": "修订后的论证",
                          "evidence": "年报第 12 页核对"})
    assert up.json()["data"]["evidence"] == "年报第 12 页核对"
    # 归档
    arc = client.post(f"/api/v1/arguments/{draft['id']}/archive", json={})
    assert arc.json()["data"]["status"] == "archived"
    # 列表
    lst = client.get("/api/v1/arguments/sh600519").json()["data"]
    assert len(lst["rows"]) == 1
    assert lst["drafts"] == {}


def test_manual_argument_and_delete(patched):
    client = TestClient(app)
    r = client.post("/api/v1/arguments/sh600519",
                    json={"side": "bear", "content": "自己写的看空论"})
    assert r.json()["code"] == 0
    row = r.json()["data"]
    assert row["status"] == "archived"
    assert client.delete(
        f"/api/v1/arguments/{row['id']}").json()["code"] == 0
    assert client.get(
        "/api/v1/arguments/sh600519").json()["data"]["rows"] == []


class _NoProviderManager:
    """get_provider 恒 None 的 LLMManager 替身（隔离真库 llm_config）。"""

    def get_provider(self):
        return None


def _patch_no_provider(monkeypatch):
    import src.infra.llm.manager as mgr_mod
    monkeypatch.setattr(mgr_mod, "LLMManager",
                        lambda repo=None: _NoProviderManager())


@pytest.mark.asyncio
async def test_call_llm_legacy_fallback(monkeypatch):
    """provider 缺位时退化到旧 MiniMax 客户端；密钥也没有则报错。"""
    _patch_no_provider(monkeypatch)
    import src.llm.client as legacy

    monkeypatch.setenv("MINIMAX_API_KEY", "sk-test")

    class _FakeLegacyClient:
        def chat(self, messages, temperature=0.3, max_tokens=2000):
            assert messages[0]["content"].startswith("PROMPT")
            return "LEGACY_CONTENT"

    monkeypatch.setattr(legacy, "get_llm_client",
                        lambda: _FakeLegacyClient())
    from src.api.handler import argument_handler as h
    content, model = await h._call_llm("PROMPT_X")
    assert content == "LEGACY_CONTENT"
    assert model == "minimax-legacy"

    # 两路都不可用 → RuntimeError
    monkeypatch.delenv("MINIMAX_API_KEY")
    with pytest.raises(RuntimeError):
        await h._call_llm("PROMPT_X")


@pytest.mark.asyncio
async def test_call_llm_retries_short_content(monkeypatch):
    """推理模型正文偶发过短（全文进思维链）：自动重试到拿足正文。"""
    from types import SimpleNamespace

    calls = {"n": 0}

    class _FlakyProvider:
        async def complete(self, prompt, **kw):
            calls["n"] += 1
            # 第1次正文1字符,第2次(带enable_thinking=false)正常
            content = "#" if calls["n"] == 1 else "X" * 120
            return SimpleNamespace(content=content, model="glm-test")

    import src.infra.llm.manager as mgr_mod
    monkeypatch.setattr(mgr_mod, "LLMManager", lambda repo=None:
                        SimpleNamespace(get_provider=lambda: _FlakyProvider()))
    from src.api.handler import argument_handler as h
    content, model = await h._call_llm("PROMPT_X")
    assert calls["n"] == 2            # 短正文触发重试
    assert len(content) == 120
    assert model == "glm-test"
