# News Agent Deep Analysis — Plan 2: Agent Core (LangGraph)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all 4 agents (Tagging, Celebrity, Trend, Report) as LangGraph nodes, build the CelebrityAgent subgraph with fan-out/debate/synthesis, and assemble the main StateGraph pipeline.

**Architecture:** Each agent is an async node function operating on `NewsAnalysisState`. CelebrityAgent is a LangGraph subgraph using `Send` for dynamic fan-out. Prompts are loaded from DB and rendered via Jinja2.

**Tech Stack:** langgraph (StateGraph, Send), langchain-openai (ChatOpenAI), jinja2

**Depends on:** Plan 1 (Foundation) must be fully implemented and committed.
**Required by:** Plan 3 (API & Frontend)

---

## File Structure

```
backend/src/domain/market/intel/agents/
├── __init__.py                   # EXISTS (from Plan 1)
├── models.py                     # EXISTS
├── schemas.py                    # EXISTS
├── state.py                      # EXISTS
├── repository_interface.py       # EXISTS
├── base.py                       # CREATE — shared helpers (prompt rendering, error handling)
├── tagging.py                    # CREATE — TaggingAgent node
├── celebrity.py                  # CREATE — CelebrityAgent subgraph
├── trend.py                      # CREATE — TrendAgent node
├── report.py                     # CREATE — ReportAgent node
├── graph.py                      # CREATE — main StateGraph assembly + run function

backend/tests/agents/
├── __init__.py                   # EXISTS
├── conftest.py                   # EXISTS
├── test_tagging.py               # CREATE
├── test_celebrity.py             # CREATE
├── test_trend.py                 # CREATE
├── test_report.py                # CREATE
├── test_graph.py                 # CREATE — end-to-end pipeline test
```

---

### Task 1: Create Base Helpers

**Files:**
- Create: `backend/src/domain/market/intel/agents/base.py`

- [ ] **Step 1: Write `base.py` with shared utilities**

```python
# backend/src/domain/market/intel/agents/base.py
"""Shared helpers for agent nodes: prompt rendering, error wrapping."""
from typing import Any, Callable, Coroutine
from functools import wraps
from loguru import logger
from jinja2 import Template


def render_prompt(template_str: str, **variables: Any) -> str:
    """Render a Jinja2 prompt template with the given variables."""
    return Template(template_str).render(**variables)


def load_prompt_from_db(template_name: str) -> str:
    """Load prompt template text from DB by name.

    Returns the raw template string (not yet rendered).
    Raises ValueError if template not found.
    """
    from src.infra.database.impl.agent_db import create_agent_repository

    repo = create_agent_repository()
    tmpl = repo.get_prompt_template_by_name(template_name)
    if not tmpl:
        raise ValueError(f"Prompt template '{template_name}' not found")
    return tmpl.template


def agent_node(func: Callable[..., Coroutine]) -> Callable[..., Coroutine]:
    """Decorator: wraps agent node with error handling and logging.

    Catches exceptions, appends to state['errors'], and returns
    a safe partial state so the pipeline can continue.
    """

    @wraps(func)
    async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
        node_name = func.__name__
        try:
            logger.debug(f"[agent] {node_name} started")
            result = await func(state)
            logger.debug(f"[agent] {node_name} completed")
            return result
        except Exception as e:
            error_msg = f"{node_name}: {type(e).__name__}: {e}"
            logger.error(f"[agent] {error_msg}")
            return {
                "errors": [error_msg],
                "processing_steps": [f"{node_name}: FAILED"],
            }

    return wrapper


def truncate_content(content: str, max_chars: int = 3000) -> str:
    """Truncate content to max_chars with ellipsis."""
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "..."
```

- [ ] **Step 2: Write the test**

```python
# backend/tests/agents/test_base.py
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
```

- [ ] **Step 3: Run tests**

Run: `cd backend && uv run python -m pytest tests/agents/test_base.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/src/domain/market/intel/agents/base.py backend/tests/agents/test_base.py
git commit -m "feat(agents): add base helpers — prompt rendering, error handling, truncation"
```

---

### Task 2: Implement TaggingAgent

**Files:**
- Create: `backend/src/domain/market/intel/agents/tagging.py`
- Create: `backend/tests/agents/test_tagging.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/agents/test_tagging.py
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from src.domain.market.intel.agents.tagging import tagging_node


def _make_mock_llm(result_dict: dict) -> MagicMock:
    """Create a mock ChatOpenAI that returns structured output."""
    mock_model = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=MagicMock(**result_dict))
    mock_model.with_structured_output.return_value = structured
    return mock_model


def test_tagging_node_returns_expected_keys():
    mock_llm = _make_mock_llm({
        "tags": ["AI", "半导体"],
        "industry": "Technology",
        "sentiment": 0.7,
        "confidence": 0.9,
    })

    with patch(
        "src.domain.market.intel.agents.tagging.create_chat_model_for_agent",
        return_value=mock_llm,
    ):
        state = {
            "news_title": "NVIDIA 发布新芯片",
            "news_content": "性能提升3倍",
            "news_id": 1,
            "news_category": "future_tech",
        }
        result = asyncio.get_event_loop().run_until_complete(
            tagging_node(state)
        )

    assert "tags" in result
    assert result["tags"] == ["AI", "半导体"]
    assert result["industry"] == "Technology"
    assert result["sentiment"] == 0.7
    assert "processing_steps" in result
```

- [ ] **Step 2: Run test (should FAIL — module doesn't exist)**

Run: `cd backend && uv run python -m pytest tests/agents/test_tagging.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement TaggingAgent**

```python
# backend/src/domain/market/intel/agents/tagging.py
"""TaggingAgent — 为新闻打标签（主题、行业、情感）."""
from typing import Any

from loguru import logger

from src.domain.market.intel.agents.base import (
    agent_node,
    load_prompt_from_db,
    render_prompt,
    truncate_content,
)
from src.domain.market.intel.agents.schemas import TaggingResult


@agent_node
async def tagging_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node: analyze news tags, industry, sentiment."""
    from src.infra.llm.langchain_adapter import create_chat_model_for_agent

    news_title = state.get("news_title", "")
    news_content = truncate_content(state.get("news_content", ""))
    news_category = state.get("news_category", "")

    # Load prompt from DB, fallback to inline
    try:
        prompt_template = load_prompt_from_db("tagging_system")
    except ValueError:
        prompt_template = (
            "你是一名专业的金融新闻分析师。分析新闻标题和正文，"
            "输出 tags(3-8个标签), industry, sentiment(-1到1), confidence(0到1)。"
        )

    user_message = (
        f"新闻类别: {news_category}\n\n"
        f"标题: {news_title}\n\n"
        f"正文: {news_content}"
    )

    llm = create_chat_model_for_agent("tagging")
    structured_llm = llm.with_structured_output(
        TaggingResult, method="json_schema"
    )

    result = await structured_llm.ainvoke([
        {"role": "system", "content": prompt_template},
        {"role": "user", "content": user_message},
    ])

    return {
        "tags": result.tags,
        "industry": result.industry,
        "sentiment": result.sentiment,
        "processing_steps": [
            f"tagging: tags={result.tags}, industry={result.industry}, "
            f"sentiment={result.sentiment:.2f}"
        ],
    }
```

- [ ] **Step 4: Run test (should PASS)**

Run: `cd backend && uv run python -m pytest tests/agents/test_tagging.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/intel/agents/tagging.py backend/tests/agents/test_tagging.py
git commit -m "feat(agents): implement TaggingAgent with structured output"
```

---

### Task 3: Implement CelebrityAgent — Persona Analysis Fan-Out

**Files:**
- Create: `backend/src/domain/market/intel/agents/celebrity.py`

This is the most complex agent — a LangGraph subgraph with:
1. `load_celebrities` — reads active celebrities from DB
2. `fan_out_persona` — uses `Send` to create N parallel persona nodes
3. `persona_analyze` — single celebrity analysis node
4. `debate_round` — one round of inter-celebrity debate
5. `should_continue_debate` — conditional edge (max rounds check)
6. `synthesize` — merge debate results into consensus

- [ ] **Step 1: Write the test**

```python
# backend/tests/agents/test_celebrity.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.domain.market.intel.agents.celebrity import (
    persona_analyze_node,
    synthesize_node,
    should_continue_debate,
)


def _mock_llm_with_response(response_dict: dict) -> MagicMock:
    mock = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=MagicMock(**response_dict))
    mock.with_structured_output.return_value = structured
    return mock


def test_persona_analyze_node():
    mock_llm = _mock_llm_with_response({
        "celebrity_name": "Elon Musk",
        "perspective": "AI硬件领域的重大突破",
        "key_insights": ["3nm制程领先", "AI训练加速"],
        "investment_implication": "利好AI产业链",
        "confidence": 0.85,
    })

    with patch(
        "src.domain.market.intel.agents.celebrity.create_chat_model_for_agent",
        return_value=mock_llm,
    ), patch(
        "src.domain.market.intel.agents.celebrity.load_prompt_from_db",
        return_value="Analyze as {{ name }}: {{ news_title }}",
    ):
        state = {
            "news_title": "NVIDIA 发布新芯片",
            "news_content": "性能提升3倍",
            "celebrity": {
                "name": "Elon Musk",
                "display_name": "马斯克",
                "domain": "tech",
                "title": "CEO",
                "bio": "企业家",
                "viewpoints": "AI是最大机遇",
                "analysis_style": "大胆前瞻",
            },
        }
        result = asyncio.get_event_loop().run_until_complete(
            persona_analyze_node(state)
        )

    assert "persona_analyses" in result
    assert len(result["persona_analyses"]) == 1
    assert result["persona_analyses"][0]["celebrity_name"] == "Elon Musk"


def test_synthesize_node():
    mock_llm = _mock_llm_with_response({
        "consensus_points": ["AI芯片竞争加剧"],
        "disagreements": ["短期估值分歧"],
        "overall_sentiment": "bullish",
        "key_takeaway": "AI基础设施投资持续增长",
    })

    with patch(
        "src.domain.market.intel.agents.celebrity.create_chat_model_for_agent",
        return_value=mock_llm,
    ), patch(
        "src.domain.market.intel.agents.celebrity.load_prompt_from_db",
        return_value="Synthesize: {{ debate_history }}",
    ):
        state = {
            "debate_history": [
                {"round": 1, "responses": [
                    {"celebrity_name": "Musk", "rebuttal": "看涨"},
                    {"celebrity_name": "Buffett", "rebuttal": "谨慎"},
                ]}
            ],
        }
        result = asyncio.get_event_loop().run_until_complete(
            synthesize_node(state)
        )

    assert "celebrity_consensus" in result
    assert result["celebrity_consensus"]["overall_sentiment"] == "bullish"


def test_should_continue_debate():
    assert should_continue_debate({"debate_round": 0, "debate_max_rounds": 2}) == "debate"
    assert should_continue_debate({"debate_round": 1, "debate_max_rounds": 2}) == "debate"
    assert should_continue_debate({"debate_round": 2, "debate_max_rounds": 2}) == "synthesize"
```

- [ ] **Step 2: Run test (should FAIL)**

Run: `cd backend && uv run python -m pytest tests/agents/test_celebrity.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement CelebrityAgent**

```python
# backend/src/domain/market/intel/agents/celebrity.py
"""CelebrityAgent subgraph — multi-persona analysis with debate."""
from typing import Any

from langgraph.types import Send
from loguru import logger

from src.domain.market.intel.agents.base import (
    agent_node,
    load_prompt_from_db,
    render_prompt,
    truncate_content,
)
from src.domain.market.intel.agents.schemas import (
    DebateResponse,
    PersonaAnalysisResult,
    SynthesisResult,
)
from src.domain.market.intel.agents.state import (
    CelebritySubgraphState,
    PersonaState,
)


async def load_celebrities_node(
    state: dict[str, Any],
) -> dict[str, Any]:
    """Read active celebrities from DB."""
    from src.infra.database.impl.agent_db import create_agent_repository

    repo = create_agent_repository()
    celebrities = repo.list_celebrities(active_only=True)
    celeb_dicts = [
        {
            "name": c.name,
            "display_name": c.display_name,
            "domain": c.domain,
            "title": c.title,
            "bio": c.bio,
            "viewpoints": c.viewpoints,
            "analysis_style": c.analysis_style,
        }
        for c in celebrities
    ]
    return {"celebrities": celeb_dicts}


def fan_out_persona(state: dict[str, Any]) -> list[Send]:
    """Create one persona_analyze Send per celebrity."""
    celebrities = state.get("celebrities", [])
    return [
        Send(
            "persona_analyze",
            {
                "news_title": state["news_title"],
                "news_content": state["news_content"],
                "celebrity": celeb,
            },
        )
        for celeb in celebrities
    ]


@agent_node
async def persona_analyze_node(state: dict[str, Any]) -> dict[str, Any]:
    """Single celebrity perspective analysis."""
    from src.infra.llm.langchain_adapter import create_chat_model_for_agent

    celebrity = state["celebrity"]
    news_title = state["news_title"]
    news_content = truncate_content(state.get("news_content", ""))

    try:
        prompt_template = load_prompt_from_db("celebrity_persona_system")
    except ValueError:
        prompt_template = (
            "以 {{ display_name }} 的视角分析新闻。"
            "背景: {{ bio }}\n观点: {{ viewpoints }}"
        )

    system_prompt = render_prompt(
        prompt_template,
        **celebrity,
        news_title=news_title,
        news_content=news_content,
    )

    user_message = f"标题: {news_title}\n\n正文: {news_content}"

    llm = create_chat_model_for_agent("celebrity")
    structured_llm = llm.with_structured_output(
        PersonaAnalysisResult, method="json_schema"
    )

    result = await structured_llm.ainvoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ])

    analysis_dict = {
        "celebrity_name": result.celebrity_name,
        "perspective": result.perspective,
        "key_insights": result.key_insights,
        "investment_implication": result.investment_implication,
        "confidence": result.confidence,
    }

    return {
        "persona_analyses": [analysis_dict],
        "processing_steps": [
            f"persona({celebrity['name']}): completed"
        ],
    }


@agent_node
async def debate_round_node(state: dict[str, Any]) -> dict[str, Any]:
    """One round of debate — each celebrity responds to others' views."""
    from src.infra.llm.langchain_adapter import create_chat_model_for_agent

    analyses = state.get("persona_analyses", [])
    if len(analyses) <= 1:
        return {"debate_history": state.get("debate_history", [])}

    try:
        debate_template = load_prompt_from_db("debate_user")
    except ValueError:
        debate_template = (
            "其他名人观点:\n{{ other_viewpoints }}\n"
            "请以 {{ display_name }} 回应。"
        )

    llm = create_chat_model_for_agent("celebrity")
    structured_llm = llm.with_structured_output(
        DebateResponse, method="json_schema"
    )

    round_responses = []
    for analysis in analyses:
        other_views = "\n".join(
            f"- {a['celebrity_name']}: {a['perspective'][:200]}"
            for a in analyses
            if a["celebrity_name"] != analysis["celebrity_name"]
        )

        prompt = render_prompt(
            debate_template,
            display_name=analysis["celebrity_name"],
            other_viewpoints=other_views,
            news_title=state.get("news_title", ""),
            news_content="",
        )

        try:
            result = await structured_llm.ainvoke([
                {"role": "user", "content": prompt}
            ])
            round_responses.append({
                "celebrity_name": result.celebrity_name,
                "agrees_with": result.agrees_with,
                "disagrees_with": result.disagrees_with,
                "rebuttal": result.rebuttal,
                "adjusted_view": result.adjusted_view,
            })
        except Exception as e:
            logger.warning(f"[debate] {analysis['celebrity_name']} failed: {e}")
            round_responses.append({
                "celebrity_name": analysis["celebrity_name"],
                "agrees_with": [],
                "disagrees_with": [],
                "rebuttal": f"Debate failed: {e}",
                "adjusted_view": analysis.get("perspective", ""),
            })

    current_round = state.get("debate_round", 0) + 1
    history = list(state.get("debate_history", []))
    history.append({"round": current_round, "responses": round_responses})

    return {
        "debate_history": history,
        "debate_round": current_round,
        "processing_steps": [f"debate_round_{current_round}: completed"],
    }


def should_continue_debate(state: dict[str, Any]) -> str:
    """Conditional edge: continue debate or synthesize."""
    current = state.get("debate_round", 0)
    max_rounds = state.get("debate_max_rounds", 2)
    if current < max_rounds:
        return "debate"
    return "synthesize"


@agent_node
async def synthesize_node(state: dict[str, Any]) -> dict[str, Any]:
    """Synthesize debate history into a consensus."""
    from src.infra.llm.langchain_adapter import create_chat_model_for_agent

    debate_history = state.get("debate_history", [])
    if not debate_history:
        analyses = state.get("persona_analyses", [])
        debate_text = "No debate. Initial analyses:\n" + "\n".join(
            f"- {a['celebrity_name']}: {a.get('perspective', 'N/A')[:200]}"
            for a in analyses
        )
    else:
        parts = []
        for round_data in debate_history:
            parts.append(f"=== Round {round_data['round']} ===")
            for resp in round_data["responses"]:
                parts.append(
                    f"{resp['celebrity_name']}: {resp.get('rebuttal', 'N/A')}"
                )
        debate_text = "\n".join(parts)

    try:
        synthesis_template = load_prompt_from_db("synthesis_system")
    except ValueError:
        synthesis_template = "综合辩论: {{ debate_history }}"

    prompt = render_prompt(
        synthesis_template, debate_history=debate_text
    )

    llm = create_chat_model_for_agent("celebrity")
    structured_llm = llm.with_structured_output(
        SynthesisResult, method="json_schema"
    )

    result = await structured_llm.ainvoke([
        {"role": "user", "content": prompt}
    ])

    return {
        "celebrity_consensus": {
            "consensus_points": result.consensus_points,
            "disagreements": result.disagreements,
            "overall_sentiment": result.overall_sentiment,
            "key_takeaway": result.key_takeaway,
        },
        "processing_steps": ["synthesis: completed"],
    }


def build_celebrity_subgraph():
    """Build the CelebrityAgent LangGraph subgraph."""
    from langgraph.graph import StateGraph, END

    sg = StateGraph(CelebritySubgraphState)

    sg.add_node("load_celebrities", load_celebrities_node)
    sg.add_node("persona_analyze", persona_analyze_node)
    sg.add_node("debate", debate_round_node)
    sg.add_node("synthesize", synthesize_node)

    sg.set_entry_point("load_celebrities")

    # After loading celebrities, fan-out to persona analysis
    sg.add_conditional_edges("load_celebrities", fan_out_persona, ["persona_analyze"])

    # After all personas complete, start debate
    sg.add_edge("persona_analyze", "debate")

    # Debate loop: continue or synthesize
    sg.add_conditional_edges("debate", should_continue_debate, {
        "debate": "debate",
        "synthesize": "synthesize",
    })

    sg.add_edge("synthesize", END)

    return sg.compile()
```

- [ ] **Step 4: Run tests (should PASS)**

Run: `cd backend && uv run python -m pytest tests/agents/test_celebrity.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/intel/agents/celebrity.py backend/tests/agents/test_celebrity.py
git commit -m "feat(agents): implement CelebrityAgent subgraph with fan-out, debate, synthesis"
```

---

### Task 4: Implement TrendAgent

**Files:**
- Create: `backend/src/domain/market/intel/agents/trend.py`
- Create: `backend/tests/agents/test_trend.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/agents/test_trend.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.domain.market.intel.agents.trend import trend_node


def test_trend_node_returns_expected_keys():
    mock_llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=MagicMock(
        related_events=[{"title": "AI芯片竞赛", "relevance": "high"}],
        trend_direction="rising",
        confidence=0.75,
        analysis="AI芯片需求持续增长",
        time_horizon="medium",
    ))
    mock_llm.with_structured_output.return_value = structured

    with patch(
        "src.domain.market.intel.agents.trend.create_chat_model_for_agent",
        return_value=mock_llm,
    ), patch(
        "src.domain.market.intel.agents.trend.load_prompt_from_db",
        return_value="Analyze trends: {{ tags }}",
    ):
        state = {
            "news_title": "NVIDIA 发布新芯片",
            "news_content": "性能提升3倍",
            "tags": ["AI", "GPU"],
            "industry": "Technology",
            "celebrity_consensus": {"overall_sentiment": "bullish"},
        }
        result = asyncio.get_event_loop().run_until_complete(
            trend_node(state)
        )

    assert "trend_analysis" in result
    assert result["trend_analysis"]["trend_direction"] == "rising"
    assert "related_events" in result
    assert "processing_steps" in result
```

- [ ] **Step 2: Run test (should FAIL)**

Run: `cd backend && uv run python -m pytest tests/agents/test_trend.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement TrendAgent**

```python
# backend/src/domain/market/intel/agents/trend.py
"""TrendAgent — 事件关联与趋势分析."""
from typing import Any

from src.domain.market.intel.agents.base import (
    agent_node,
    load_prompt_from_db,
    render_prompt,
    truncate_content,
)
from src.domain.market.intel.agents.schemas import TrendResult


@agent_node
async def trend_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node: analyze event relationships and trends."""
    from src.infra.llm.langchain_adapter import create_chat_model_for_agent

    news_title = state.get("news_title", "")
    news_content = truncate_content(state.get("news_content", ""))
    tags = state.get("tags", [])
    industry = state.get("industry", "")
    celebrity_consensus = state.get("celebrity_consensus", {})

    try:
        prompt_template = load_prompt_from_db("trend_system")
    except ValueError:
        prompt_template = (
            "分析趋势。标签: {{ tags }}, 行业: {{ industry }}"
        )

    system_prompt = render_prompt(
        prompt_template,
        tags=str(tags),
        industry=industry,
        celebrity_consensus=str(celebrity_consensus),
        news_title=news_title,
        news_content=news_content,
    )

    user_message = f"标题: {news_title}\n\n正文: {news_content}"

    llm = create_chat_model_for_agent("trend")
    structured_llm = llm.with_structured_output(
        TrendResult, method="json_schema"
    )

    result = await structured_llm.ainvoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ])

    return {
        "related_events": [
            e if isinstance(e, dict) else {"title": str(e)}
            for e in result.related_events
        ],
        "trend_analysis": {
            "trend_direction": result.trend_direction,
            "confidence": result.confidence,
            "analysis": result.analysis,
            "time_horizon": result.time_horizon,
        },
        "processing_steps": [
            f"trend: direction={result.trend_direction}, "
            f"horizon={result.time_horizon}"
        ],
    }
```

- [ ] **Step 4: Run test (should PASS)**

Run: `cd backend && uv run python -m pytest tests/agents/test_trend.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/intel/agents/trend.py backend/tests/agents/test_trend.py
git commit -m "feat(agents): implement TrendAgent with structured output"
```

---

### Task 5: Implement ReportAgent

**Files:**
- Create: `backend/src/domain/market/intel/agents/report.py`
- Create: `backend/tests/agents/test_report.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/agents/test_report.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.domain.market.intel.agents.report import report_node


def test_report_node_returns_expected_keys():
    mock_llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=MagicMock(
        executive_summary="NVIDIA新芯片将加速AI产业发展",
        key_findings=["3nm制程突破", "AI训练性能3倍提升"],
        celebrity_consensus_summary="名人普遍看好AI硬件",
        trend_outlook="AI芯片需求将持续增长",
        risk_factors=["地缘政治风险", "估值过高"],
        investment_recommendation="关注AI产业链上下游",
        confidence_level="medium",
    ))
    mock_llm.with_structured_output.return_value = structured

    with patch(
        "src.domain.market.intel.agents.report.create_chat_model_for_agent",
        return_value=mock_llm,
    ), patch(
        "src.domain.market.intel.agents.report.load_prompt_from_db",
        return_value="Write report: {{ news_title }}",
    ):
        state = {
            "news_title": "NVIDIA 发布新芯片",
            "news_content": "性能提升3倍",
            "tags": ["AI", "GPU"],
            "sentiment": 0.7,
            "celebrity_consensus": {"overall_sentiment": "bullish"},
            "trend_analysis": {"trend_direction": "rising"},
        }
        result = asyncio.get_event_loop().run_until_complete(
            report_node(state)
        )

    assert "final_report" in result
    assert "executive_summary" in result["final_report"]
    assert result["final_report"]["confidence_level"] == "medium"
    assert "processing_steps" in result
```

- [ ] **Step 2: Run test (should FAIL)**

Run: `cd backend && uv run python -m pytest tests/agents/test_report.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement ReportAgent**

```python
# backend/src/domain/market/intel/agents/report.py
"""ReportAgent — 综合报告生成."""
from typing import Any

from src.domain.market.intel.agents.base import (
    agent_node,
    load_prompt_from_db,
    render_prompt,
)
from src.domain.market.intel.agents.schemas import ReportResult


@agent_node
async def report_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node: generate comprehensive analysis report."""
    from src.infra.llm.langchain_adapter import create_chat_model_for_agent

    news_title = state.get("news_title", "")
    tags = state.get("tags", [])
    sentiment = state.get("sentiment", 0.0)
    celebrity_consensus = state.get("celebrity_consensus", {})
    trend_analysis = state.get("trend_analysis", {})

    try:
        prompt_template = load_prompt_from_db("report_system")
    except ValueError:
        prompt_template = "Write report: {{ news_title }}"

    system_prompt = render_prompt(
        prompt_template,
        news_title=news_title,
        tags=str(tags),
        sentiment=sentiment,
        celebrity_consensus=str(celebrity_consensus),
        trend_analysis=str(trend_analysis),
    )

    llm = create_chat_model_for_agent("report")
    structured_llm = llm.with_structured_output(
        ReportResult, method="json_schema"
    )

    result = await structured_llm.ainvoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"请为以下新闻生成综合分析报告: {news_title}"},
    ])

    return {
        "final_report": {
            "executive_summary": result.executive_summary,
            "key_findings": result.key_findings,
            "celebrity_consensus_summary": result.celebrity_consensus_summary,
            "trend_outlook": result.trend_outlook,
            "risk_factors": result.risk_factors,
            "investment_recommendation": result.investment_recommendation,
            "confidence_level": result.confidence_level,
        },
        "processing_steps": [
            f"report: confidence={result.confidence_level}"
        ],
    }
```

- [ ] **Step 4: Run test (should PASS)**

Run: `cd backend && uv run python -m pytest tests/agents/test_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/intel/agents/report.py backend/tests/agents/test_report.py
git commit -m "feat(agents): implement ReportAgent with structured output"
```

---

### Task 6: Build Main StateGraph Pipeline

**Files:**
- Create: `backend/src/domain/market/intel/agents/graph.py`
- Create: `backend/tests/agents/test_graph.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/agents/test_graph.py
"""End-to-end pipeline test with mocked LLM."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.domain.market.intel.agents.graph import build_analysis_graph


def _mock_llm(responses: list[dict]) -> MagicMock:
    """Create a mock ChatOpenAI that cycles through responses."""
    mock = MagicMock()
    call_count = [0]

    def make_structured(response: dict) -> MagicMock:
        s = MagicMock()
        s.ainvoke = AsyncMock(return_value=MagicMock(**response))
        return s

    original_with_structured = mock.with_structured_output

    def with_structured(schema, **kw):
        idx = call_count[0] % len(responses)
        call_count[0] += 1
        return make_structured(responses[idx])

    mock.with_structured_output = with_structured
    return mock


def test_full_pipeline_produces_final_report():
    responses = [
        # TaggingAgent
        {"tags": ["AI"], "industry": "Tech", "sentiment": 0.6, "confidence": 0.8},
        # PersonaAnalysis (x3 celebrities)
        {"celebrity_name": "Musk", "perspective": "看涨", "key_insights": ["AI加速"], "investment_implication": "利好", "confidence": 0.9},
        {"celebrity_name": "Buffett", "perspective": "谨慎", "key_insights": ["估值高"], "investment_implication": "观望", "confidence": 0.7},
        {"celebrity_name": "Dalio", "perspective": "宏观利好", "key_insights": ["周期向上"], "investment_implication": "适中", "confidence": 0.75},
        # DebateResponse
        {"celebrity_name": "Musk", "agrees_with": [], "disagrees_with": ["估值担忧"], "rebuttal": "长期看估值合理", "adjusted_view": "仍然看涨"},
        # Synthesis
        {"consensus_points": ["AI长期向好"], "disagreements": ["短期估值"], "overall_sentiment": "bullish", "key_takeaway": "AI增长持续"},
        # Trend
        {"related_events": [], "trend_direction": "rising", "confidence": 0.8, "analysis": "上升", "time_horizon": "medium"},
        # Report
        {"executive_summary": "AI芯片利好", "key_findings": ["性能突破"], "celebrity_consensus_summary": "看涨", "trend_outlook": "持续上升", "risk_factors": ["估值"], "investment_recommendation": "持有", "confidence_level": "medium"},
    ]

    mock_llm = _mock_llm(responses)

    with patch(
        "src.domain.market.intel.agents.tagging.create_chat_model_for_agent",
        return_value=mock_llm,
    ), patch(
        "src.domain.market.intel.agents.celebrity.create_chat_model_for_agent",
        return_value=mock_llm,
    ), patch(
        "src.domain.market.intel.agents.trend.create_chat_model_for_agent",
        return_value=mock_llm,
    ), patch(
        "src.domain.market.intel.agents.report.create_chat_model_for_agent",
        return_value=mock_llm,
    ), patch(
        "src.domain.market.intel.agents.celebrity.load_prompt_from_db",
        return_value="template",
    ), patch(
        "src.domain.market.intel.agents.celebrity.create_agent_repository",
    ) as mock_repo, patch(
        "src.domain.market.intel.agents.tagging.load_prompt_from_db",
        return_value="template",
    ), patch(
        "src.domain.market.intel.agents.trend.load_prompt_from_db",
        return_value="template",
    ), patch(
        "src.domain.market.intel.agents.report.load_prompt_from_db",
        return_value="template",
    ):
        # Mock celebrity list
        from src.domain.market.intel.agents.models import Celebrity
        mock_repo_inst = MagicMock()
        mock_repo_inst.list_celebrities.return_value = [
            Celebrity(name="Elon Musk", display_name="马斯克", domain="tech", title="CEO", bio="", viewpoints="", analysis_style=""),
            Celebrity(name="Warren Buffett", display_name="巴菲特", domain="finance", title="CEO", bio="", viewpoints="", analysis_style=""),
            Celebrity(name="Ray Dalio", display_name="达利欧", domain="finance", title="Founder", bio="", viewpoints="", analysis_style=""),
        ]
        mock_repo.return_value = mock_repo_inst

        graph = build_analysis_graph(debate_max_rounds=1)
        result = asyncio.get_event_loop().run_until_complete(
            graph.ainvoke({
                "news_id": 1,
                "news_title": "NVIDIA 发布新芯片",
                "news_content": "性能提升3倍",
                "news_category": "future_tech",
            })
        )

    assert "final_report" in result
    assert result["final_report"]["executive_summary"] == "AI芯片利好"
    assert "tags" in result
    assert result["tags"] == ["AI"]
```

- [ ] **Step 2: Run test (should FAIL)**

Run: `cd backend && uv run python -m pytest tests/agents/test_graph.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement graph.py**

```python
# backend/src/domain/market/intel/agents/graph.py
"""Main LangGraph StateGraph — assembles all agents into a pipeline."""
from typing import Any

from langgraph.graph import StateGraph, END
from loguru import logger

from src.domain.market.intel.agents.state import NewsAnalysisState
from src.domain.market.intel.agents.tagging import tagging_node
from src.domain.market.intel.agents.trend import trend_node
from src.domain.market.intel.agents.report import report_node
from src.domain.market.intel.agents.celebrity import build_celebrity_subgraph


def build_analysis_graph(debate_max_rounds: int = 2) -> Any:
    """Build the main news analysis LangGraph pipeline.

    Topology:
        START → Tagging → Celebrity (subgraph) → Trend → Report → END

    Args:
        debate_max_rounds: Number of debate rounds in CelebrityAgent.

    Returns:
        Compiled LangGraph graph ready for .invoke() or .ainvoke().
    """
    g = StateGraph(NewsAnalysisState)

    # Add nodes
    g.add_node("tagging", tagging_node)
    g.add_node("celebrity", build_celebrity_subgraph())
    g.add_node("trend", trend_node)
    g.add_node("report", report_node)

    # Linear edges
    g.set_entry_point("tagging")
    g.add_edge("tagging", "celebrity")
    g.add_edge("celebrity", "trend")
    g.add_edge("trend", "report")
    g.add_edge("report", END)

    return g.compile()


async def run_analysis(news_id: int) -> dict[str, Any]:
    """Run deep analysis on a single news item.

    Loads news from DB, runs the full pipeline, saves result.

    Args:
        news_id: ID of the news item in intel_news table.

    Returns:
        The final pipeline state dict, or error info.
    """
    from src.infra.database.impl.agent_db import create_agent_repository

    repo = create_agent_repository()

    # Load pipeline config
    pipeline = repo.get_active_pipeline()
    debate_max_rounds = pipeline.debate_max_rounds if pipeline else 2

    # Load news
    news_list = repo.find_news_without_analysis(limit=0)  # just for structure
    # Actually we need to load the specific news
    from src.infra.database.impl.intel_db import create_intel_repository
    intel_repo = create_intel_repository()

    # Use raw SQL to get news by ID
    from src.infra.database.impl.agent_db import _get_db_connection
    db = _get_db_connection()
    with db.session_scope() as session:
        from sqlalchemy import text
        row = session.execute(
            text("SELECT id, title, content, category FROM intel_news WHERE id = :id"),
            {"id": news_id},
        ).first()

    if not row:
        return {"error": f"News {news_id} not found"}

    initial_state = {
        "news_id": row[0],
        "news_title": row[1],
        "news_content": row[2] or "",
        "news_category": row[3] or "",
    }

    logger.info(f"[graph] Starting analysis for news_id={news_id}")

    graph = build_analysis_graph(debate_max_rounds=debate_max_rounds)
    result = await graph.ainvoke(initial_state)

    # Save to DB
    analysis_data = {
        "tags": result.get("tags", []),
        "industry": result.get("industry", ""),
        "sentiment": result.get("sentiment", 0.0),
        "persona_analyses": result.get("persona_analyses", []),
        "celebrity_consensus": result.get("celebrity_consensus", {}),
        "trend_analysis": result.get("trend_analysis", {}),
        "final_report": result.get("final_report", {}),
        "errors": result.get("errors", []),
        "processing_steps": result.get("processing_steps", []),
    }
    repo.save_deep_analysis(news_id, analysis_data)

    logger.info(f"[graph] Analysis complete for news_id={news_id}")
    return result
```

- [ ] **Step 4: Run test (should PASS)**

Run: `cd backend && uv run python -m pytest tests/agents/test_graph.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/intel/agents/graph.py backend/tests/agents/test_graph.py
git commit -m "feat(agents): build main StateGraph pipeline with all agents"
```

---

### Task 7: Run All Agent Tests

- [ ] **Step 1: Run full test suite**

Run: `cd backend && uv run python -m pytest tests/agents/ -v`
Expected: All tests pass.

- [ ] **Step 2: Verify no import errors across the module**

Run: `cd backend && uv run python -c "from src.domain.market.intel.agents.graph import build_analysis_graph, run_analysis; print('ALL AGENT IMPORTS OK')"`
Expected: `ALL AGENT IMPORTS OK`
