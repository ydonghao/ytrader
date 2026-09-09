# WeChat Blog Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily AI blog generation pipeline that selects hot tech topics from collected news, writes WeChat-ready articles in 3 styles, and suggests images.

**Architecture:** 3 LangGraph agents (TopicPicker → BlogWriter → ImageAdvisor) in a linear pipeline, reading from existing `intel_news` + `deep_analysis` data, writing to new `blog_draft` table. Follows the exact same DDD patterns as the News Agent system.

**Tech Stack:** langgraph, langchain-openai, SQLModel, FastAPI, React, APScheduler — all already installed.

---

## File Structure

```
backend/src/
├── domain/market/intel/blog/
│   ├── __init__.py                     # CREATE
│   ├── models.py                       # CREATE — BlogDraft dataclass
│   ├── state.py                        # CREATE — BlogPipelineState TypedDict
│   ├── schemas.py                      # CREATE — Pydantic output schemas
│   ├── repository_interface.py         # CREATE — IBlogRepository ABC
│   └── agents/
│       ├── __init__.py                 # CREATE
│       ├── topic_picker.py             # CREATE — TopicPickerAgent
│       ├── blog_writer.py              # CREATE — BlogWriterAgent
│       ├── image_advisor.py            # CREATE — ImageAdvisorAgent
│       └── graph.py                    # CREATE — Blog pipeline StateGraph + run_blog_generation()
├── infra/database/impl/
│   ├── blog_db.py                      # CREATE — blog_draft table + BlogRepository + seed
│   └── agent_db.py                     # MODIFY — add 3 blog agent configs + 3 prompt templates to seed
├── api/
│   ├── router/blog_router.py           # CREATE — blog CRUD + generate API
│   └── model/blog_api_model.py         # CREATE — request/response models
├── infra/scheduler.py                  # MODIFY — add blog_daily_generate job
└── main.py                             # MODIFY — register blog_router

backend/tests/
└── blog/
    ├── __init__.py                     # CREATE
    ├── conftest.py                     # CREATE — shared fixtures
    ├── test_topic_picker.py            # CREATE
    ├── test_blog_writer.py             # CREATE
    ├── test_image_advisor.py           # CREATE
    └── test_blog_graph.py             # CREATE — E2E pipeline test

frontend/apps/web/src/
├── pages/
│   ├── BlogDraft.tsx                   # CREATE — blog management page
│   └── BlogDraft.css                  # CREATE
├── App.tsx                             # MODIFY — add route
└── components/Layout.tsx              # MODIFY — add nav item
```

---

### Task 1: Domain Layer — Models, State, Schemas, Repository Interface

**Files:**
- Create: `backend/src/domain/market/intel/blog/__init__.py`
- Create: `backend/src/domain/market/intel/blog/models.py`
- Create: `backend/src/domain/market/intel/blog/state.py`
- Create: `backend/src/domain/market/intel/blog/schemas.py`
- Create: `backend/src/domain/market/intel/blog/repository_interface.py`

- [ ] **Step 1: Create `blog/__init__.py`** — empty file.

- [ ] **Step 2: Create `models.py`**

```python
"""Blog domain models."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class BlogDraft:
    """Blog post draft, stored in blog_draft table."""
    title: str
    style: str  # tech_depth / pop_science / hot_commentary
    status: str = "draft"  # draft / approved / published / discarded
    content: str = ""
    image_suggestions: list[dict] = field(default_factory=list)
    source_news_ids: list[int] = field(default_factory=list)
    topic_score: float = 0.0
    topic_reason: str = ""
    metadata: dict = field(default_factory=dict)
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
```

- [ ] **Step 3: Create `state.py`**

```python
"""Blog pipeline LangGraph state."""
import operator
from typing import Annotated, Any, TypedDict


class BlogPipelineState(TypedDict, total=False):
    # Input
    date_range_hours: int
    style: str
    candidate_news: list[dict[str, Any]]

    # TopicPicker output
    selected_topic: dict[str, Any]
    topic_score: float
    topic_reason: str
    source_news_ids: list[int]

    # BlogWriter output
    title: str
    content: str
    metadata: dict[str, Any]

    # ImageAdvisor output
    image_suggestions: list[dict[str, Any]]

    # Meta
    errors: Annotated[list[str], operator.add]
    processing_steps: Annotated[list[str], operator.add]
```

- [ ] **Step 4: Create `schemas.py`**

```python
"""Pydantic schemas for blog agent LLM structured output."""
from pydantic import BaseModel, Field


class TopicPickerResult(BaseModel):
    """TopicPickerAgent output — selected topic with score."""
    topic_title: str = Field(description="博文主题标题（吸引人的标题）")
    topic_summary: str = Field(description="主题摘要，为什么这个话题值得关注")
    score: float = Field(ge=0.0, le=10.0, description="综合评分 0-10")
    reason: str = Field(description="选题理由：为什么适合写博文")
    source_news_ids: list[int] = Field(description="引用的新闻 ID 列表")
    key_angles: list[str] = Field(description="2-3 个可以展开讨论的角度")


class BlogContentResult(BaseModel):
    """BlogWriterAgent output — complete blog post."""
    title: str = Field(description="博文标题，要有吸引力")
    subtitle: str = Field(description="副标题或导语")
    content: str = Field(description="Markdown 格式的博文正文，1500-3000 字")
    word_count: int = Field(description="正文字数")
    reading_time_minutes: int = Field(description="预计阅读时间（分钟）")


class ImageSuggestionResult(BaseModel):
    """ImageAdvisorAgent output — image placement suggestions."""
    suggestions: list[dict[str, str]] = Field(
        description="配图建议列表，每个含 position/description/keywords"
    )
```

- [ ] **Step 5: Create `repository_interface.py`**

```python
"""Blog repository interface."""
from abc import ABC, abstractmethod
from src.domain.market.intel.blog.models import BlogDraft


class IBlogRepository(ABC):
    @abstractmethod
    def list_drafts(self, status: str | None = None, page: int = 1, size: int = 20) -> tuple[list[BlogDraft], int]: ...

    @abstractmethod
    def get_draft(self, draft_id: int) -> BlogDraft | None: ...

    @abstractmethod
    def create_draft(self, draft: BlogDraft) -> BlogDraft: ...

    @abstractmethod
    def update_draft(self, draft_id: int, updates: dict) -> BlogDraft | None: ...

    @abstractmethod
    def delete_draft(self, draft_id: int) -> bool: ...

    @abstractmethod
    def get_recent_news_for_topic(self, hours: int = 24, limit: int = 30) -> list[dict]: ...
```

- [ ] **Step 6: Verify imports**

Run: `cd backend && uv run python -c "from src.domain.market.intel.blog.models import BlogDraft; from src.domain.market.intel.blog.state import BlogPipelineState; from src.domain.market.intel.blog.schemas import TopicPickerResult; from src.domain.market.intel.blog.repository_interface import IBlogRepository; print('OK')"`

- [ ] **Step 7: Commit**

```bash
git add backend/src/domain/market/intel/blog/
git commit -m "feat(blog): add blog domain models, state, schemas, repository interface"
```

---

### Task 2: DB Table + Repository Implementation + Seed Data

**Files:**
- Create: `backend/src/infra/database/impl/blog_db.py`
- Modify: `backend/src/infra/database/impl/agent_db.py` — add blog agent configs + prompt templates to `seed_agent_data()`

- [ ] **Step 1: Create `blog_db.py`**

```python
"""Blog system SQLModel table, repository, and seed data."""
import json
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import Column, Text, text
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, INTEGER
from sqlmodel import SQLModel, Field, select

from src.domain.market.intel.blog.models import BlogDraft
from src.domain.market.intel.blog.repository_interface import IBlogRepository
from src.infra.database.db_helper import DBConnection, create_db_connection


class BlogDraftTable(SQLModel, table=True):
    __tablename__ = "blog_draft"
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(default="", max_length=500)
    style: str = Field(default="pop_science", max_length=50)
    status: str = Field(default="draft", max_length=20, index=True)
    content: str = Field(default="", sa_column=Column(Text))
    image_suggestions: dict = Field(default=[], sa_column=Column(JSONB))
    source_news_ids: list = Field(default=[], sa_column=Column(ARRAY(INTEGER)))
    topic_score: float = Field(default=0.0)
    topic_reason: str = Field(default="", sa_column=Column(Text))
    metadata: dict = Field(default={}, sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: Optional[datetime] = None


def _row_to_draft(row: BlogDraftTable) -> BlogDraft:
    return BlogDraft(
        id=row.id,
        title=row.title,
        style=row.style,
        status=row.status,
        content=row.content,
        image_suggestions=row.image_suggestions or [],
        source_news_ids=row.source_news_ids or [],
        topic_score=row.topic_score,
        topic_reason=row.topic_reason,
        metadata=row.metadata or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
        published_at=row.published_at,
    )


class BlogRepository(IBlogRepository):
    def __init__(self, db_connection: DBConnection) -> None:
        self._db = db_connection

    def list_drafts(
        self, status: str | None = None, page: int = 1, size: int = 20
    ) -> tuple[list[BlogDraft], int]:
        with self._db.session_scope() as session:
            stmt = select(BlogDraftTable).order_by(BlogDraftTable.created_at.desc())
            if status:
                stmt = stmt.where(BlogDraftTable.status == status)
            total = len(session.exec(stmt).all())
            rows = session.exec(stmt.offset((page - 1) * size).limit(size)).all()
            return [_row_to_draft(r) for r in rows], total

    def get_draft(self, draft_id: int) -> BlogDraft | None:
        with self._db.session_scope() as session:
            row = session.get(BlogDraftTable, draft_id)
            return _row_to_draft(row) if row else None

    def create_draft(self, draft: BlogDraft) -> BlogDraft:
        with self._db.session_scope() as session:
            row = BlogDraftTable(
                title=draft.title,
                style=draft.style,
                status=draft.status,
                content=draft.content,
                image_suggestions=draft.image_suggestions,
                source_news_ids=draft.source_news_ids,
                topic_score=draft.topic_score,
                topic_reason=draft.topic_reason,
                metadata=draft.metadata,
            )
            session.add(row)
            session.flush()
            return _row_to_draft(row)

    def update_draft(self, draft_id: int, updates: dict) -> BlogDraft | None:
        with self._db.session_scope() as session:
            row = session.get(BlogDraftTable, draft_id)
            if not row:
                return None
            for key, val in updates.items():
                if hasattr(row, key) and key != "id":
                    setattr(row, key, val)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            return _row_to_draft(row)

    def delete_draft(self, draft_id: int) -> bool:
        with self._db.session_scope() as session:
            row = session.get(BlogDraftTable, draft_id)
            if not row:
                return False
            session.delete(row)
            return True

    def get_recent_news_for_topic(
        self, hours: int = 24, limit: int = 30
    ) -> list[dict]:
        """Get recent processed news with deep_analysis for topic selection."""
        with self._db.session_scope() as session:
            rows = session.execute(
                text(
                    "SELECT id, title, content, category, tags, sentiment, "
                    "deep_analysis FROM intel_news "
                    "WHERE processed = true AND published_at >= NOW() - INTERVAL :hours "
                    "ORDER BY published_at DESC LIMIT :limit"
                ),
                {"hours": f"{hours} hours", "limit": limit},
            ).fetchall()
            return [
                {
                    "id": r[0],
                    "title": r[1],
                    "content": (r[2] or "")[:500],
                    "category": r[3],
                    "tags": r[4] or [],
                    "sentiment": r[5],
                    "deep_analysis": r[6] if isinstance(r[6], dict) else (json.loads(r[6]) if r[6] else {}),
                }
                for r in rows
            ]


# Singleton + Factory
_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection()
    return _db_connection


def create_blog_repository(
    db_connection: DBConnection | None = None,
) -> BlogRepository:
    return BlogRepository(db_connection or _get_db_connection())
```

- [ ] **Step 2: Add blog agent configs + prompt templates to `agent_db.py` seed data**

In `seed_agent_data()`, add 3 new agent configs and 3 new prompt templates to the existing seed lists (before the `session.add(c)` loop for agents, and before the `session.add(t)` for templates):

Agent configs to append to the `configs` list:
```python
            AgentConfigTable(
                name="topic_picker",
                display_name="Topic Picker",
                description="从新闻中选题，评分排序，选出最佳博文话题",
                agent_type="single",
                system_prompt="topic_picker_system",
                extra_params={"temperature": 0.3},
            ),
            AgentConfigTable(
                name="blog_writer",
                display_name="Blog Writer",
                description="按指定风格写微信公众号博文",
                agent_type="single",
                system_prompt="blog_writer_system",
                extra_params={"temperature": 0.7},
            ),
            AgentConfigTable(
                name="image_advisor",
                display_name="Image Advisor",
                description="为博文建议配图位置和关键词",
                agent_type="single",
                system_prompt="image_advisor_system",
                extra_params={"temperature": 0.4},
            ),
```

Prompt templates to append to the `templates` list:
```python
            PromptTemplateTable(
                name="topic_picker_system",
                description="TopicPickerAgent 选题评分提示词",
                template=(
                    "你是一名资深科技媒体选题编辑。你的任务是从一组近期新闻中选出最适合写微信公众号博文的话题。\n\n"
                    "评分维度（总分 10 分）：\n"
                    "- 热度 (30%): 这个话题在社交/科技圈的关注程度\n"
                    "- 时效性 (30%): 是否是今天/本周的突发热点\n"
                    "- 公众关注度 (20%): 普通读者是否关心，而不仅是技术人员\n"
                    "- 博文适配度 (20%): 是否能展开写 1500+ 字的深度内容\n\n"
                    "选题原则：\n"
                    "- 有故事性、有启发性\n"
                    "- 读者会产生共鸣或好奇\n"
                    "- 可以用通俗语言解释\n"
                    "- 优先选择有深度分析结果的新闻\n\n"
                    "请从以下新闻中选出最佳话题：\n\n"
                    "{{ news_list }}\n\n"
                    "输出选中的话题标题、评分、选题理由、引用的新闻 ID、以及 2-3 个可以展开讨论的角度。"
                ),
                variables={"news_list": "str"},
                category="system",
            ),
            PromptTemplateTable(
                name="blog_writer_system",
                description="BlogWriterAgent 博文写作提示词",
                template=(
                    "你是一名微信公众号科技博主，擅长写有深度又有可读性的科技文章。\n\n"
                    "写作风格：{{ style }}\n\n"
                    "请根据以下素材写一篇微信公众号博文：\n\n"
                    "话题：{{ topic_title }}\n"
                    "选题理由：{{ topic_reason }}\n"
                    "讨论角度：{{ key_angles }}\n"
                    "相关新闻摘要：\n{{ news_summaries }}\n\n"
                    "格式要求：\n"
                    "- 标题：吸引眼球但不是标题党（15-30 字）\n"
                    "- 副标题/导语：一句话让读者想继续看下去\n"
                    "- 正文 1500-3000 字，Markdown 格式\n"
                    "- 短段落（每段 3-4 行），适当使用 **加粗**\n"
                    "- 有清晰的小标题分隔各部分\n"
                    "- 结尾有总结或展望\n\n"
                    "{% if style == 'tech_depth' %}"
                    "技术深度型要求：深入分析原理，引用数据，面向技术人员，结构：背景→原理→应用→展望\n"
                    "{% elif style == 'pop_science' %}"
                    "通俗科普型要求：用比喻解释技术，少用术语，有故事线，面向大众，结构：引人入胜的开头→核心概念→实际影响→未来想象\n"
                    "{% elif style == 'hot_commentary' %}"
                    "热点评论型要求：快速梳理事件脉络，多源整合，犀利点评，有数据支撑，结构：事件回顾→多方观点→我的分析→行业影响\n"
                    "{% endif %}"
                ),
                variables={"style": "str", "topic_title": "str", "topic_reason": "str", "key_angles": "str", "news_summaries": "str"},
                category="system",
            ),
            PromptTemplateTable(
                name="image_advisor_system",
                description="ImageAdvisorAgent 配图建议提示词",
                template=(
                    "你是一名微信公众号配图顾问。根据以下博文内容，建议 3-5 个配图位置。\n\n"
                    "博文标题：{{ title }}\n\n"
                    "博文正文：\n{{ content }}\n\n"
                    "对每个配图位置，输出：\n"
                    "- position: 在哪一段之后（如 '第2段后'、'小结部分'）\n"
                    "- description: 配图应该展示什么（详细描述）\n"
                    "- keywords: 3-5 个英文搜索关键词（可用于图库搜索或 AI 生图）\n\n"
                    "配图原则：\n"
                    "- 与内容紧密相关，不是装饰\n"
                    "- 帮助读者理解抽象概念\n"
                    "- 关键词要具体，便于搜索"
                ),
                variables={"title": "str", "content": "str"},
                category="system",
            ),
```

- [ ] **Step 3: Verify**

Run: `cd backend && uv run python -c "from src.infra.database.impl.blog_db import create_blog_repository; print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add backend/src/infra/database/impl/blog_db.py backend/src/infra/database/impl/agent_db.py
git commit -m "feat(blog): add blog_draft table, BlogRepository, blog agent seed data"
```

---

### Task 3: Agent Nodes — TopicPicker, BlogWriter, ImageAdvisor

**Files:**
- Create: `backend/src/domain/market/intel/blog/agents/__init__.py`
- Create: `backend/src/domain/market/intel/blog/agents/topic_picker.py`
- Create: `backend/src/domain/market/intel/blog/agents/blog_writer.py`
- Create: `backend/src/domain/market/intel/blog/agents/image_advisor.py`
- Create: `backend/tests/blog/test_topic_picker.py`
- Create: `backend/tests/blog/test_blog_writer.py`
- Create: `backend/tests/blog/test_image_advisor.py`

- [ ] **Step 1: Create `agents/__init__.py`** — empty file.

- [ ] **Step 2: Create `topic_picker.py`**

```python
"""TopicPickerAgent — select best blog topic from recent news."""
from typing import Any

from loguru import logger

from src.domain.market.intel.agents.base import agent_node, load_prompt_from_db, render_prompt
from src.domain.market.intel.blog.schemas import TopicPickerResult


@agent_node
async def topic_picker_node(state: dict[str, Any]) -> dict[str, Any]:
    from src.infra.llm.langchain_adapter import create_chat_model_for_agent

    candidate_news = state.get("candidate_news", [])
    if not candidate_news:
        return {"errors": ["topic_picker: no candidate news available"]}

    news_list = "\n".join(
        f"[ID:{n['id']}] {n['title']} (tags: {n.get('tags', [])}, sentiment: {n.get('sentiment', 'N/A')})"
        for n in candidate_news[:30]
    )

    try:
        prompt_template = load_prompt_from_db("topic_picker_system")
    except ValueError:
        prompt_template = "从以下新闻中选最佳博文话题:\n{{ news_list }}"

    system_prompt = render_prompt(prompt_template, news_list=news_list)

    llm = create_chat_model_for_agent("topic_picker")
    structured_llm = llm.with_structured_output(TopicPickerResult, method="json_schema")

    result = await structured_llm.ainvoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请从以上新闻中选出最适合写微信公众号博文的话题。"},
    ])

    return {
        "selected_topic": {
            "title": result.topic_title,
            "summary": result.topic_summary,
            "key_angles": result.key_angles,
        },
        "topic_score": result.score,
        "topic_reason": result.reason,
        "source_news_ids": result.source_news_ids,
        "processing_steps": [f"topic_picker: selected '{result.topic_title}' (score={result.score})"],
    }
```

- [ ] **Step 3: Create `blog_writer.py`**

```python
"""BlogWriterAgent — write WeChat blog post in specified style."""
from typing import Any

from src.domain.market.intel.agents.base import agent_node, load_prompt_from_db, render_prompt
from src.domain.market.intel.blog.schemas import BlogContentResult


@agent_node
async def blog_writer_node(state: dict[str, Any]) -> dict[str, Any]:
    from src.infra.llm.langchain_adapter import create_chat_model_for_agent

    style = state.get("style", "pop_science")
    topic = state.get("selected_topic", {})
    topic_reason = state.get("topic_reason", "")
    source_ids = state.get("source_news_ids", [])
    candidate_news = state.get("candidate_news", [])

    news_summaries = "\n".join(
        f"- {n['title']}: {(n.get('content') or '')[:200]}"
        for n in candidate_news
        if n.get("id") in source_ids
    )

    try:
        prompt_template = load_prompt_from_db("blog_writer_system")
    except ValueError:
        prompt_template = "写一篇{{ style }}风格的博文，话题：{{ topic_title }}"

    system_prompt = render_prompt(
        prompt_template,
        style=style,
        topic_title=topic.get("title", ""),
        topic_reason=topic_reason,
        key_angles=str(topic.get("key_angles", [])),
        news_summaries=news_summaries,
    )

    llm = create_chat_model_for_agent("blog_writer")
    structured_llm = llm.with_structured_output(BlogContentResult, method="json_schema")

    result = await structured_llm.ainvoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"请写一篇关于「{topic.get('title', 'AI科技')}」的微信公众号博文，风格：{style}"},
    ])

    return {
        "title": result.title,
        "content": result.subtitle + "\n\n" + result.content,
        "metadata": {
            "word_count": result.word_count,
            "reading_time_minutes": result.reading_time_minutes,
            "subtitle": result.subtitle,
        },
        "processing_steps": [
            f"blog_writer: wrote '{result.title}' ({result.word_count} words, {style})"
        ],
    }
```

- [ ] **Step 4: Create `image_advisor.py`**

```python
"""ImageAdvisorAgent — suggest image placements for blog post."""
from typing import Any

from src.domain.market.intel.agents.base import agent_node, load_prompt_from_db, render_prompt
from src.domain.market.intel.blog.schemas import ImageSuggestionResult


@agent_node
async def image_advisor_node(state: dict[str, Any]) -> dict[str, Any]:
    from src.infra.llm.langchain_adapter import create_chat_model_for_agent

    title = state.get("title", "")
    content = state.get("content", "")

    if not content:
        return {"image_suggestions": [], "processing_steps": ["image_advisor: skipped (no content)"]}

    try:
        prompt_template = load_prompt_from_db("image_advisor_system")
    except ValueError:
        prompt_template = "为博文建议配图:\n{{ title }}\n{{ content }}"

    system_prompt = render_prompt(prompt_template, title=title, content=content[:4000])

    llm = create_chat_model_for_agent("image_advisor")
    structured_llm = llm.with_structured_output(ImageSuggestionResult, method="json_schema")

    result = await structured_llm.ainvoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请为这篇博文建议 3-5 个配图位置。"},
    ])

    return {
        "image_suggestions": result.suggestions,
        "processing_steps": [f"image_advisor: {len(result.suggestions)} image suggestions"],
    }
```

- [ ] **Step 5: Create test files**

`tests/blog/__init__.py` — empty file.

`tests/blog/test_topic_picker.py`:
```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.domain.market.intel.blog.agents.topic_picker import topic_picker_node


def test_topic_picker_selects_topic():
    mock_llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=MagicMock(
        topic_title="GPT-5 发布：AI 能力再次飞跃",
        topic_summary="OpenAI 最新模型在推理能力上有重大突破",
        score=8.5,
        reason="突发热点，公众关注度高",
        source_news_ids=[1, 3],
        key_angles=["技术原理突破", "对行业的影响"],
    ))
    mock_llm.with_structured_output.return_value = structured

    with patch("src.domain.market.intel.blog.agents.topic_picker.create_chat_model_for_agent", return_value=mock_llm), \
         patch("src.domain.market.intel.blog.agents.topic_picker.load_prompt_from_db", return_value="选话题"):
        state = {"candidate_news": [
            {"id": 1, "title": "GPT-5 released", "tags": ["AI"], "sentiment": 0.8},
            {"id": 2, "title": "New chip", "tags": ["芯片"], "sentiment": 0.5},
            {"id": 3, "title": "AI regulation", "tags": ["政策"], "sentiment": -0.2},
        ]}
        result = asyncio.get_event_loop().run_until_complete(topic_picker_node(state))

    assert "selected_topic" in result
    assert result["topic_score"] == 8.5
    assert result["source_news_ids"] == [1, 3]
```

`tests/blog/test_blog_writer.py`:
```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.domain.market.intel.blog.agents.blog_writer import blog_writer_node


def test_blog_writer_produces_content():
    mock_llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=MagicMock(
        title="AI 的新时代",
        subtitle="当机器开始思考",
        content="# 正文\n\n这是博文内容..." * 50,
        word_count=2000,
        reading_time_minutes=8,
    ))
    mock_llm.with_structured_output.return_value = structured

    with patch("src.domain.market.intel.blog.agents.blog_writer.create_chat_model_for_agent", return_value=mock_llm), \
         patch("src.domain.market.intel.blog.agents.blog_writer.load_prompt_from_db", return_value="写博文"):
        state = {
            "style": "pop_science",
            "selected_topic": {"title": "GPT-5", "key_angles": ["原理", "影响"]},
            "topic_reason": "突发热点",
            "source_news_ids": [1],
            "candidate_news": [{"id": 1, "title": "GPT-5", "content": "New model"}],
        }
        result = asyncio.get_event_loop().run_until_complete(blog_writer_node(state))

    assert "title" in result
    assert "content" in result
    assert len(result["content"]) > 100
```

`tests/blog/test_image_advisor.py`:
```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.domain.market.intel.blog.agents.image_advisor import image_advisor_node


def test_image_advisor_returns_suggestions():
    mock_llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=MagicMock(
        suggestions=[
            {"position": "第1段后", "description": "AI芯片示意图", "keywords": ["AI", "chip"]},
            {"position": "小结部分", "description": "未来展望图", "keywords": ["future", "technology"]},
        ],
    ))
    mock_llm.with_structured_output.return_value = structured

    with patch("src.domain.market.intel.blog.agents.image_advisor.create_chat_model_for_agent", return_value=mock_llm), \
         patch("src.domain.market.intel.blog.agents.image_advisor.load_prompt_from_db", return_value="建议配图"):
        result = asyncio.get_event_loop().run_until_complete(image_advisor_node({
            "title": "AI新突破",
            "content": "正文内容" * 100,
        }))

    assert len(result["image_suggestions"]) == 2
```

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run python -m pytest tests/blog/ -v`

- [ ] **Step 7: Commit**

```bash
git add backend/src/domain/market/intel/blog/agents/ backend/tests/blog/
git commit -m "feat(blog): implement TopicPicker, BlogWriter, ImageAdvisor agents with tests"
```

---

### Task 4: Blog Pipeline Graph

**Files:**
- Create: `backend/src/domain/market/intel/blog/agents/graph.py`
- Create: `backend/tests/blog/test_blog_graph.py`

- [ ] **Step 1: Create `graph.py`**

```python
"""Blog pipeline LangGraph — assembles TopicPicker → BlogWriter → ImageAdvisor."""
from typing import Any

from langgraph.graph import StateGraph, END
from loguru import logger

from src.domain.market.intel.blog.state import BlogPipelineState
from src.domain.market.intel.blog.agents.topic_picker import topic_picker_node
from src.domain.market.intel.blog.agents.blog_writer import blog_writer_node
from src.domain.market.intel.blog.agents.image_advisor import image_advisor_node


async def load_news_node(state: dict[str, Any]) -> dict[str, Any]:
    """Load recent news from DB for topic selection."""
    from src.infra.database.impl.blog_db import create_blog_repository

    repo = create_blog_repository()
    hours = state.get("date_range_hours", 24)
    news = repo.get_recent_news_for_topic(hours=hours, limit=30)
    return {"candidate_news": news}


def build_blog_graph() -> Any:
    """Build the blog generation pipeline."""
    g = StateGraph(BlogPipelineState)

    g.add_node("load_news", load_news_node)
    g.add_node("topic_picker", topic_picker_node)
    g.add_node("blog_writer", blog_writer_node)
    g.add_node("image_advisor", image_advisor_node)

    g.set_entry_point("load_news")
    g.add_edge("load_news", "topic_picker")
    g.add_edge("topic_picker", "blog_writer")
    g.add_edge("blog_writer", "image_advisor")
    g.add_edge("image_advisor", END)

    return g.compile()


async def run_blog_generation(style: str = "pop_science", hours: int = 24) -> dict[str, Any]:
    """Generate a blog post and save to DB."""
    from src.infra.database.impl.blog_db import create_blog_repository
    from src.domain.market.intel.blog.models import BlogDraft

    repo = create_blog_repository()

    graph = build_blog_graph()
    result = await graph.ainvoke({
        "date_range_hours": hours,
        "style": style,
        "candidate_news": [],
    })

    # Save to DB
    draft = BlogDraft(
        title=result.get("title", "Untitled"),
        style=style,
        status="draft",
        content=result.get("content", ""),
        image_suggestions=result.get("image_suggestions", []),
        source_news_ids=result.get("source_news_ids", []),
        topic_score=result.get("topic_score", 0.0),
        topic_reason=result.get("topic_reason", ""),
        metadata=result.get("metadata", {}),
    )
    saved = repo.create_draft(draft)

    logger.info(
        f"[blog] Generated draft #{saved.id}: '{saved.title}' "
        f"(score={draft.topic_score}, style={style})"
    )
    return {
        "id": saved.id,
        "title": saved.title,
        "style": style,
        "topic_score": draft.topic_score,
        "errors": result.get("errors", []),
    }
```

- [ ] **Step 2: Create E2E test**

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.domain.market.intel.blog.agents.graph import build_blog_graph


def _mock_llm(responses):
    mock = MagicMock()
    call_count = [0]
    def with_structured(schema, **kw):
        idx = call_count[0] % len(responses)
        call_count[0] += 1
        s = MagicMock()
        s.ainvoke = AsyncMock(return_value=MagicMock(**responses[idx]))
        return s
    mock.with_structured_output = with_structured
    return mock


def test_blog_pipeline_produces_draft():
    responses = [
        # topic_picker
        {"topic_title": "AI breakthrough", "topic_summary": "Summary", "score": 8.0, "reason": "Hot topic", "source_news_ids": [1], "key_angles": ["tech", "impact"]},
        # blog_writer
        {"title": "AI的新突破", "subtitle": "当机器开始思考", "content": "正文内容" * 100, "word_count": 2000, "reading_time_minutes": 8},
        # image_advisor
        {"suggestions": [{"position": "第1段后", "description": "图1", "keywords": ["AI"]}]},
    ]
    mock_llm = _mock_llm(responses)

    with patch("src.domain.market.intel.blog.agents.topic_picker.create_chat_model_for_agent", return_value=mock_llm), \
         patch("src.domain.market.intel.blog.agents.blog_writer.create_chat_model_for_agent", return_value=mock_llm), \
         patch("src.domain.market.intel.blog.agents.image_advisor.create_chat_model_for_agent", return_value=mock_llm), \
         patch("src.domain.market.intel.blog.agents.topic_picker.load_prompt_from_db", return_value="t"), \
         patch("src.domain.market.intel.blog.agents.blog_writer.load_prompt_from_db", return_value="t"), \
         patch("src.domain.market.intel.blog.agents.image_advisor.load_prompt_from_db", return_value="t"):
        graph = build_blog_graph()
        result = asyncio.get_event_loop().run_until_complete(
            graph.ainvoke({"date_range_hours": 24, "style": "pop_science", "candidate_news": [{"id": 1, "title": "AI news", "tags": [], "sentiment": 0.5, "content": "text"}]})
        )

    assert "title" in result
    assert result["title"] == "AI的新突破"
    assert "content" in result
    assert len(result["image_suggestions"]) == 1
```

- [ ] **Step 3: Run all blog tests**

Run: `cd backend && uv run python -m pytest tests/blog/ -v`

- [ ] **Step 4: Commit**

```bash
git add backend/src/domain/market/intel/blog/agents/graph.py backend/tests/blog/test_blog_graph.py
git commit -m "feat(blog): add blog pipeline StateGraph and E2E test"
```

---

### Task 5: API Router + Scheduler + main.py Registration

**Files:**
- Create: `backend/src/api/model/blog_api_model.py`
- Create: `backend/src/api/router/blog_router.py`
- Modify: `backend/src/infra/scheduler.py` — add blog generation job
- Modify: `backend/main.py` — register blog_router

- [ ] **Step 1: Create `blog_api_model.py`**

```python
"""Blog API request/response models."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class BlogGenerateRequest(BaseModel):
    style: str = Field(default="pop_science", description="tech_depth / pop_science / hot_commentary")
    date_range_hours: int = Field(default=24, ge=1, le=168)


class BlogDraftUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None


class BlogDraftResponse(BaseModel):
    id: int
    title: str
    style: str
    status: str
    content: str
    image_suggestions: list[dict]
    source_news_ids: list[int]
    topic_score: float
    topic_reason: str
    metadata: dict
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None
```

- [ ] **Step 2: Create `blog_router.py`**

```python
"""Blog draft CRUD + generation API."""
from fastapi import APIRouter, HTTPException
from loguru import logger

from src.api.model.blog_api_model import (
    BlogGenerateRequest,
    BlogDraftUpdateRequest,
    BlogDraftResponse,
)
from src.infra.database.impl.blog_db import create_blog_repository


router = APIRouter(prefix="/blog", tags=["blog"])
_repo = create_blog_repository()


def _ok(data) -> dict:
    return {"code": 0, "msg": "ok", "data": data}


def _draft_to_dict(d) -> dict:
    return {
        "id": d.id,
        "title": d.title,
        "style": d.style,
        "status": d.status,
        "content": d.content,
        "image_suggestions": d.image_suggestions,
        "source_news_ids": d.source_news_ids,
        "topic_score": d.topic_score,
        "topic_reason": d.topic_reason,
        "metadata": d.metadata,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        "published_at": d.published_at.isoformat() if d.published_at else None,
    }


@router.get("/drafts")
def list_drafts(status: str | None = None, page: int = 1, size: int = 20):
    drafts, total = _repo.list_drafts(status=status, page=page, size=size)
    return _ok({
        "records": [_draft_to_dict(d) for d in drafts],
        "total": total,
        "page": page,
        "size": size,
    })


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: int):
    d = _repo.get_draft(draft_id)
    if not d:
        raise HTTPException(404, "Draft not found")
    return _ok(_draft_to_dict(d))


@router.post("/generate")
async def generate_blog(req: BlogGenerateRequest):
    from src.domain.market.intel.blog.agents.graph import run_blog_generation
    try:
        result = await run_blog_generation(style=req.style, hours=req.date_range_hours)
        return _ok(result)
    except Exception as e:
        logger.error(f"[blog] Generation failed: {e}")
        raise HTTPException(500, f"Generation failed: {e}")


@router.put("/drafts/{draft_id}")
def update_draft(draft_id: int, req: BlogDraftUpdateRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    d = _repo.update_draft(draft_id, updates)
    if not d:
        raise HTTPException(404, "Draft not found")
    return _ok({"id": d.id, "updated": True})


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: int):
    ok = _repo.delete_draft(draft_id)
    if not ok:
        raise HTTPException(404, "Draft not found")
    return _ok({"deleted": True})


@router.patch("/drafts/{draft_id}/status")
def update_status(draft_id: int, status: str):
    from datetime import datetime, timezone
    updates: dict = {"status": status}
    if status == "published":
        updates["published_at"] = datetime.now(timezone.utc)
    d = _repo.update_draft(draft_id, updates)
    if not d:
        raise HTTPException(404, "Draft not found")
    return _ok(_draft_to_dict(d))
```

- [ ] **Step 3: Add scheduler job in `scheduler.py`**

In `setup_scheduler()`, after the existing `intel_agent_analysis` job, add:

```python
    # Blog generation — daily at 8:07
    def _run_blog_generation():
        import asyncio
        from src.domain.market.intel.blog.agents.graph import run_blog_generation
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run_blog_generation(style="pop_science"))
        except Exception as e:
            logging.getLogger(__name__).error(f"Blog generation failed: {e}")
        finally:
            loop.close()

    sched.add_job(
        _run_blog_generation,
        CronTrigger(hour=8, minute=7, timezone="Asia/Shanghai"),
        id="blog_daily_generate",
        name="每日博文生成",
        replace_existing=True,
        misfire_grace_time=600,
    )
```

- [ ] **Step 4: Register router in `main.py`**

Add import:
```python
from src.api.router.blog_router import router as blog_router
```

Add registration:
```python
    app.include_router(blog_router, prefix="/api/v1")
```

- [ ] **Step 5: Verify**

Run: `cd backend && uv run python -c "from src.api.router.blog_router import router; print('OK')"`

- [ ] **Step 6: Commit**

```bash
git add backend/src/api/model/blog_api_model.py backend/src/api/router/blog_router.py backend/src/infra/scheduler.py backend/main.py
git commit -m "feat(blog): add blog API router, scheduler job, main.py registration"
```

---

### Task 6: Frontend — BlogDraft Page

**Files:**
- Create: `frontend/apps/web/src/pages/BlogDraft.tsx`
- Create: `frontend/apps/web/src/pages/BlogDraft.css`
- Modify: `frontend/apps/web/src/App.tsx` — add import + route
- Modify: `frontend/apps/web/src/components/Layout.tsx` — add nav item

- [ ] **Step 1: Create `BlogDraft.tsx`**

```tsx
import React, {useState, useEffect, useCallback} from 'react';
import {getApiBase} from '../lib/api';
import './BlogDraft.css';

interface Draft {
  id: number;
  title: string;
  style: string;
  status: string;
  content: string;
  image_suggestions: {position: string; description: string; keywords: string[]}[];
  source_news_ids: number[];
  topic_score: number;
  topic_reason: string;
  metadata: {word_count?: number; reading_time_minutes?: number};
  created_at: string;
}

const STYLES = [
  {value: 'pop_science', label: '通俗科普'},
  {value: 'tech_depth', label: '技术深度'},
  {value: 'hot_commentary', label: '热点评论'},
];

const STATUS_LABELS: Record<string, {label: string; color: string}> = {
  draft: {label: '草稿', color: 'var(--color-text-secondary)'},
  approved: {label: '已审核', color: 'var(--color-accent)'},
  published: {label: '已发布', color: 'var(--color-success)'},
  discarded: {label: '已丢弃', color: 'var(--color-text-secondary)'},
};

export const BlogDraft: React.FC = () => {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selected, setSelected] = useState<Draft | null>(null);
  const [generating, setGenerating] = useState(false);
  const [style, setStyle] = useState('pop_science');
  const apiBase = getApiBase();

  const fetchDrafts = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/blog/drafts`);
      const json = await res.json();
      if (json.code === 0) setDrafts(json.data.records);
    } catch {}
  }, [apiBase]);

  useEffect(() => { fetchDrafts(); }, [fetchDrafts]);

  const generate = async () => {
    setGenerating(true);
    try {
      await fetch(`${apiBase}/blog/generate`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({style}),
      });
      fetchDrafts();
    } finally { setGenerating(false); }
  };

  const updateStatus = async (id: number, status: string) => {
    await fetch(`${apiBase}/blog/drafts/${id}/status?status=${status}`, {method: 'PATCH'});
    fetchDrafts();
    if (selected?.id === id) setSelected({...selected, status});
  };

  const deleteDraft = async (id: number) => {
    await fetch(`${apiBase}/blog/drafts/${id}`, {method: 'DELETE'});
    if (selected?.id === id) setSelected(null);
    fetchDrafts();
  };

  const copyMarkdown = () => {
    if (selected?.content) navigator.clipboard.writeText(selected.content);
  };

  return (
    <div className="blog-draft">
      <div className="blog-draft__header">
        <h2>Blog Drafts</h2>
        <div className="blog-draft__gen-bar">
          <select value={style} onChange={(e) => setStyle(e.target.value)}>
            {STYLES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          <button className="blog-draft__gen-btn" onClick={generate} disabled={generating}>
            {generating ? 'Generating...' : 'Generate Today\'s Blog'}
          </button>
        </div>
      </div>

      <div className="blog-draft__body">
        <div className="blog-draft__list">
          {drafts.map((d) => (
            <div
              key={d.id}
              className={`blog-draft__item ${selected?.id === d.id ? 'blog-draft__item--active' : ''}`}
              onClick={() => setSelected(d)}
            >
              <div className="blog-draft__item-title">{d.title || 'Untitled'}</div>
              <div className="blog-draft__item-meta">
                <span className="blog-draft__item-style">
                  {STYLES.find((s) => s.value === d.style)?.label || d.style}
                </span>
                <span className="blog-draft__item-score">{d.topic_score.toFixed(1)}</span>
                <span style={{color: STATUS_LABELS[d.status]?.color}}>
                  {STATUS_LABELS[d.status]?.label || d.status}
                </span>
              </div>
            </div>
          ))}
          {drafts.length === 0 && <div className="blog-draft__empty">No drafts yet. Generate one!</div>}
        </div>

        <div className="blog-draft__preview">
          {selected ? (
            <>
              <div className="blog-draft__preview-header">
                <h3>{selected.title}</h3>
                <div className="blog-draft__preview-actions">
                  <button onClick={copyMarkdown}>Copy Markdown</button>
                  {selected.status === 'draft' && (
                    <button onClick={() => updateStatus(selected.id, 'approved')}>Approve</button>
                  )}
                  {selected.status === 'approved' && (
                    <button onClick={() => updateStatus(selected.id, 'published')}>Mark Published</button>
                  )}
                  <button className="blog-draft__delete-btn" onClick={() => deleteDraft(selected.id)}>Delete</button>
                </div>
              </div>
              {selected.topic_reason && (
                <div className="blog-draft__reason">
                  <strong>Topic Reason:</strong> {selected.topic_reason}
                </div>
              )}
              <div className="blog-draft__content">
                {selected.content.split('\n').map((line, i) => (
                  <p key={i}>{line || '\u00A0'}</p>
                ))}
              </div>
              {selected.image_suggestions?.length > 0 && (
                <div className="blog-draft__images">
                  <h4>Image Suggestions</h4>
                  {selected.image_suggestions.map((img, i) => (
                    <div key={i} className="blog-draft__img-item">
                      <span className="blog-draft__img-pos">{img.position}</span>
                      <span className="blog-draft__img-desc">{img.description}</span>
                      <span className="blog-draft__img-kw">{img.keywords?.join(', ')}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="blog-draft__empty">Select a draft to preview</div>
          )}
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 2: Create `BlogDraft.css`**

```css
.blog-draft { height: calc(100vh - 96px); display: flex; flex-direction: column; }
.blog-draft__header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-shrink: 0; }
.blog-draft__header h2 { font-size: 1.25rem; font-weight: 600; margin: 0; }
.blog-draft__gen-bar { display: flex; gap: 8px; }
.blog-draft__gen-bar select { padding: 6px 10px; background: var(--color-surface); color: var(--color-text); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: 0.8125rem; }
.blog-draft__gen-btn { padding: 8px 16px; background: var(--color-accent); color: #fff; border: none; border-radius: var(--radius-md); font-size: 0.8125rem; font-weight: 500; cursor: pointer; }
.blog-draft__gen-btn:disabled { opacity: 0.5; }
.blog-draft__body { display: flex; gap: 16px; flex: 1; min-height: 0; }
.blog-draft__list { width: 300px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; }
.blog-draft__item { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: 12px; cursor: pointer; }
.blog-draft__item:hover { background: var(--color-surface-hover); }
.blog-draft__item--active { border-color: var(--color-accent); }
.blog-draft__item-title { font-size: 0.875rem; font-weight: 600; margin-bottom: 6px; color: var(--color-text); }
.blog-draft__item-meta { display: flex; gap: 8px; font-size: 0.6875rem; color: var(--color-text-secondary); }
.blog-draft__item-style { background: var(--color-surface-hover); padding: 2px 6px; border-radius: var(--radius-sm); }
.blog-draft__item-score { font-family: var(--font-mono); color: var(--color-accent); }
.blog-draft__empty { color: var(--color-text-secondary); font-size: 0.8125rem; padding: 40px; text-align: center; }
.blog-draft__preview { flex: 1; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: 20px; overflow-y: auto; display: flex; flex-direction: column; }
.blog-draft__preview-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; flex-shrink: 0; }
.blog-draft__preview-header h3 { font-size: 1rem; font-weight: 600; margin: 0; }
.blog-draft__preview-actions { display: flex; gap: 6px; flex-shrink: 0; }
.blog-draft__preview-actions button { padding: 5px 12px; border-radius: var(--radius-md); font-size: 0.75rem; cursor: pointer; border: 1px solid var(--color-border); background: none; color: var(--color-text-secondary); }
.blog-draft__delete-btn { color: var(--color-danger) !important; border-color: var(--color-danger) !important; }
.blog-draft__reason { font-size: 0.8125rem; color: var(--color-text-secondary); background: var(--color-background); padding: 10px; border-radius: var(--radius-md); margin-bottom: 12px; flex-shrink: 0; }
.blog-draft__content { flex: 1; overflow-y: auto; font-size: 0.875rem; line-height: 1.7; }
.blog-draft__content p { margin: 0 0 8px; }
.blog-draft__images { margin-top: 16px; border-top: 1px solid var(--color-border); padding-top: 12px; flex-shrink: 0; }
.blog-draft__images h4 { font-size: 0.875rem; font-weight: 600; margin: 0 0 8px; }
.blog-draft__img-item { display: flex; gap: 10px; padding: 6px 0; font-size: 0.75rem; align-items: baseline; }
.blog-draft__img-pos { color: var(--color-accent); font-weight: 600; min-width: 80px; }
.blog-draft__img-desc { flex: 1; color: var(--color-text-secondary); }
.blog-draft__img-kw { color: var(--color-text-secondary); font-family: var(--font-mono); font-size: 0.6875rem; }
```

- [ ] **Step 3: Modify `App.tsx`** — add import and route:

```tsx
import {BlogDraft} from './pages/BlogDraft';
// In <Routes>:
<Route path="/blog" element={<BlogDraft />} />
```

- [ ] **Step 4: Modify `Layout.tsx`** — in the Research group items, add before Intel:

```tsx
  {path: '/blog', label: 'Blog', icon: Icon.reports},
```

- [ ] **Step 5: Verify in browser** at `http://localhost:12000/blog`

- [ ] **Step 6: Commit**

```bash
git add frontend/apps/web/src/pages/BlogDraft.tsx frontend/apps/web/src/pages/BlogDraft.css frontend/apps/web/src/App.tsx frontend/apps/web/src/components/Layout.tsx
git commit -m "feat(blog): add BlogDraft frontend page with list/preview/generate"
```

---

### Task 7: Smoke Test — Restart Backend, Verify End-to-End

- [ ] **Step 1: Restart backend**

```bash
lsof -ti :12100 | xargs kill; cd backend && uv run python main.py &
```

Wait for `[Agent] tables migrated and seeded` in logs.

- [ ] **Step 2: Verify blog API endpoints**

```bash
curl -s http://localhost:12000/api/v1/blog/drafts | python3 -m json.tool
```

Expected: `{"code": 0, "data": {"records": [], "total": 0, ...}}`

- [ ] **Step 3: Verify blog agent configs seeded**

```bash
curl -s http://localhost:12100/api/v1/agent/configs | python3 -c "import sys,json; data=json.load(sys.stdin)['data']; blog=[a for a in data if a['name'] in ('topic_picker','blog_writer','image_advisor')]; print(len(blog), 'blog agents')"
```

Expected: `3 blog agents`

- [ ] **Step 4: Verify frontend page loads**

Navigate to `http://localhost:12000/blog` — should show empty list with Generate button.

- [ ] **Step 5: Final commit if any fixes needed**
