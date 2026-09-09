from src.domain.market.intel.agents.base import (
    render_prompt,
    truncate_content,
)


def test_render_prompt_substitutes_variables():
    template = "Hello {{ name }}, welcome to {{ place }}."
    result = render_prompt(template, name="World", place="YTrader")
    assert result == "Hello World, welcome to YTrader."


def test_render_prompt_handles_missing_gracefully():
    template = "Hello {{ name }}."
    result = render_prompt(template, name="Alice")
    assert result == "Hello Alice."


def test_truncate_content_short():
    assert truncate_content("short text", 100) == "short text"


def test_truncate_content_long():
    text = "a" * 5000
    result = truncate_content(text, 3000)
    assert len(result) == 3003  # 3000 + "..."
    assert result.endswith("...")


def test_agent_node_decorator():
    import asyncio
    from src.domain.market.intel.agents.base import agent_node

    @agent_node
    async def good_node(state):
        return {"processing_steps": ["good: done"]}

    @agent_node
    async def bad_node(state):
        raise ValueError("test error")

    result_good = asyncio.get_event_loop().run_until_complete(
        good_node({"x": 1})
    )
    assert result_good["processing_steps"] == ["good: done"]

    result_bad = asyncio.get_event_loop().run_until_complete(
        bad_node({"x": 1})
    )
    assert len(result_bad["errors"]) == 1
    assert "bad_node" in result_bad["errors"][0]
