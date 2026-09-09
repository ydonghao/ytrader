"""Integration tests for LLM config repository."""
import os
import sys

import pytest
from sqlalchemy import text

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "..")
)

from src.domain.llm.models import LLMConfig
from src.infra.database.llm.repository import create_llm_repository

# 本模块创建的行名（含 update 改名变体）。只清理自己的行、不动真实配置；
# agent_config 外键先解除再删——曾因全表 DELETE 触发 FK 报错致行残留，
# 下次运行 configs[0] 断言错位（跨运行 flaky 根因）。
_TEST_ROW_NAMES = ("Test GPT", "Test Claude", "Updated GPT", "Keep Key Test")
# DBSession.exec 不支持参数绑定——静态常量直接内联（无注入面）
_NAMES_SQL = "(" + ", ".join(f"'{n}'" for n in _TEST_ROW_NAMES) + ")"


def _make_config(name="Test GPT", **kw):
    return LLMConfig(
        name=name,
        provider_type=kw.get("provider_type", "openai_chat"),
        base_url=kw.get("base_url", "https://api.openai.com/v1"),
        api_key=kw.get("api_key", "sk-test-key-123"),
        model=kw.get("model", "gpt-4o"),
        is_default=kw.get("is_default", False),
    )


@pytest.fixture(scope="module")
def llm_repo():
    """Create a repository connected to the real DB."""
    repo = create_llm_repository()

    def _wipe():
        # FK 链：llm_config ← agent_config ← agent_tool_binding（无更深引用）
        with repo._db.session_scope() as session:
            session.exec(text(
                "DELETE FROM agent_tool_binding WHERE agent_config_id IN "
                "(SELECT id FROM agent_config WHERE llm_config_id IN "
                f"(SELECT id FROM llm_config WHERE name IN {_NAMES_SQL}))"
            ))
            session.exec(text(
                "DELETE FROM agent_config WHERE llm_config_id IN "
                f"(SELECT id FROM llm_config WHERE name IN {_NAMES_SQL})"
            ))
            session.exec(text(
                f"DELETE FROM llm_config WHERE name IN {_NAMES_SQL}"
            ))
            session.commit()

    _wipe()  # 进场清残留（历史 teardown FK 失败会遗留测试行）
    yield repo
    _wipe()


def test_create_config(llm_repo):
    result = llm_repo.create_config(_make_config(is_default=True))
    assert result.id != ""
    assert result.name == "Test GPT"
    assert result.api_key == "****"


def test_list_configs(llm_repo):
    configs = llm_repo.list_configs()
    assert isinstance(configs, list)
    for c in configs:
        assert c.api_key == "****"


def test_get_default_config(llm_repo):
    llm_repo.create_config(_make_config(is_default=True))
    config = llm_repo.get_default_config()
    assert config is not None
    assert config.is_default is True
    assert config.api_key != "****"


def test_get_decrypted_config(llm_repo):
    c = llm_repo.create_config(_make_config())
    decrypted = llm_repo.get_decrypted_config(c.id)
    assert decrypted is not None
    assert decrypted.api_key == "sk-test-key-123"


def test_update_config(llm_repo):
    c = llm_repo.create_config(_make_config())
    updated = llm_repo.update_config(c.id, {"name": "Updated GPT"})
    assert updated is not None
    assert updated.name == "Updated GPT"


def test_update_config_keep_api_key(llm_repo):
    c = llm_repo.create_config(_make_config())
    llm_repo.update_config(c.id, {"name": "Keep Key Test"})
    decrypted = llm_repo.get_decrypted_config(c.id)
    assert decrypted.api_key == "sk-test-key-123"


def test_set_default(llm_repo):
    prev = llm_repo.get_default_config()  # 保护现场默认配置
    created = llm_repo.create_config(
        _make_config(
            name="Test Claude",
            provider_type="anthropic",
            base_url="https://api.anthropic.com",
            api_key="sk-ant-test",
            model="claude-sonnet-4-20250514",
        )
    )
    llm_repo.set_default(created.id)
    default = llm_repo.get_default_config()
    assert default is not None
    assert default.id == created.id
    if prev is not None and prev.id != created.id:
        llm_repo.set_default(prev.id)


def test_delete_config(llm_repo):
    c = llm_repo.create_config(_make_config())
    result = llm_repo.delete_config(c.id)
    assert result is True
