"""Unit tests for LLM domain models."""
from src.domain.llm.models import (
    LLMConfig,
    LLMResponse,
    TokenUsage,
    LLMChunk,
    TestResult,
    MASKED_KEY,
)


def test_llm_config_defaults():
    config = LLMConfig()
    assert config.id == ""
    assert config.is_default is False
    assert config.extra_params == {}


def test_llm_config_with_values():
    config = LLMConfig(
        id="abc",
        name="GPT-4o",
        provider_type="openai_chat",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
        is_default=True,
    )
    assert config.name == "GPT-4o"
    assert config.provider_type == "openai_chat"


def test_llm_response():
    resp = LLMResponse(content="hello", model="gpt-4o")
    assert resp.content == "hello"
    assert resp.usage is None
    assert resp.raw_response is None


def test_llm_response_with_usage():
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    resp = LLMResponse(content="hi", model="gpt-4o", usage=usage)
    assert resp.usage.total_tokens == 15


def test_llm_chunk():
    chunk = LLMChunk(content="hel", model="gpt-4o", finish_reason=None)
    assert chunk.content == "hel"
    assert chunk.finish_reason is None


def test_test_result():
    result = TestResult(success=True, message="OK", latency_ms=150.3)
    assert result.success is True
    assert result.latency_ms == 150.3


def test_masked_key_constant():
    assert MASKED_KEY == "****"
