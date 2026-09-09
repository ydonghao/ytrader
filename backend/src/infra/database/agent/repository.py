"""Agent system repository implementation, migration, and seed data."""
import json
import threading
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import text
from sqlmodel import select

from src.domain.market.intel.agents.models import (
    AgentConfig,
    AgentPipeline,
    AgentTool,
    Celebrity,
    PromptTemplate,
    PromptTemplateHistory,
)
from src.domain.market.intel.agents.repository_interface import IAgentRepository
from src.infra.database.agent.entity import (
    AgentConfigTable,
    AgentPipelineTable,
    AgentToolTable,
    AgentToolBindingTable,
    PromptTemplateTable,
    PromptTemplateHistoryTable,
    CelebrityTable,
)
from src.infra.database.sql_engine.engine import DBConnection, create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn


# ═══════════════════════════════════════════
# Row -> Domain Model Helpers
# ═══════════════════════════════════════════

def _row_to_agent_config(row: AgentConfigTable) -> AgentConfig:
    return AgentConfig(
        id=row.id,
        name=row.name,
        display_name=row.display_name,
        description=row.description,
        agent_type=row.agent_type,
        system_prompt=row.system_prompt,
        output_schema=row.output_schema or {},
        llm_config_id=row.llm_config_id,
        extra_params=row.extra_params or {},
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_pipeline(row: AgentPipelineTable) -> AgentPipeline:
    return AgentPipeline(
        id=row.id,
        name=row.name,
        display_name=row.display_name,
        description=row.description,
        graph_config=row.graph_config or {},
        debate_max_rounds=row.debate_max_rounds,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_template(row: PromptTemplateTable) -> PromptTemplate:
    return PromptTemplate(
        id=row.id,
        name=row.name,
        description=row.description,
        template=row.template,
        variables=row.variables or {},
        category=row.category,
        version=row.version,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_history(row: PromptTemplateHistoryTable) -> PromptTemplateHistory:
    return PromptTemplateHistory(
        id=row.id,
        template_id=row.template_id,
        name=row.name,
        version=row.version,
        template=row.template,
        variables=row.variables or {},
        description=row.description,
        created_at=row.created_at,
    )


def _row_to_celebrity(row: CelebrityTable) -> Celebrity:
    return Celebrity(
        id=row.id,
        name=row.name,
        display_name=row.display_name,
        domain=row.domain,
        title=row.title,
        bio=row.bio,
        viewpoints=row.viewpoints,
        analysis_style=row.analysis_style,
        avatar_url=row.avatar_url,
        is_active=row.is_active,
        sort_order=row.sort_order,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_agent_tool(row: AgentToolTable) -> AgentTool:
    return AgentTool(
        id=row.id,
        name=row.name,
        display_name=row.display_name,
        description=row.description,
        source=row.source,
        ref_key=row.ref_key,
        args_schema=row.args_schema or {},
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ═══════════════════════════════════════════
# Repository Implementation
# ═══════════════════════════════════════════

class AgentRepository(IAgentRepository):
    def __init__(self, db_connection: DBConnection) -> None:
        self._db = db_connection

    # -- Agent Config --

    def list_agent_configs(self) -> list[AgentConfig]:
        with self._db.session_scope() as session:
            rows = session.exec(
                select(AgentConfigTable).order_by(AgentConfigTable.id)
            ).all()
            return [_row_to_agent_config(r) for r in rows]

    def get_agent_config(self, config_id: int) -> AgentConfig | None:
        with self._db.session_scope() as session:
            row = session.get(AgentConfigTable, config_id)
            return _row_to_agent_config(row) if row else None

    def get_agent_config_by_name(self, name: str) -> AgentConfig | None:
        with self._db.session_scope() as session:
            row = session.exec(
                select(AgentConfigTable).where(AgentConfigTable.name == name)
            ).first()
            return _row_to_agent_config(row) if row else None

    def update_agent_config(
        self, config_id: int, updates: dict
    ) -> AgentConfig | None:
        with self._db.session_scope() as session:
            row = session.get(AgentConfigTable, config_id)
            if not row:
                return None
            for key, val in updates.items():
                if hasattr(row, key) and key != "id":
                    setattr(row, key, val)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            return _row_to_agent_config(row)

    # -- Pipeline --

    def list_pipelines(self) -> list[AgentPipeline]:
        with self._db.session_scope() as session:
            rows = session.exec(
                select(AgentPipelineTable).order_by(AgentPipelineTable.id)
            ).all()
            return [_row_to_pipeline(r) for r in rows]

    def get_pipeline(self, pipeline_id: int) -> AgentPipeline | None:
        with self._db.session_scope() as session:
            row = session.get(AgentPipelineTable, pipeline_id)
            return _row_to_pipeline(row) if row else None

    def get_active_pipeline(self) -> AgentPipeline | None:
        with self._db.session_scope() as session:
            row = session.exec(
                select(AgentPipelineTable).where(
                    AgentPipelineTable.is_active == True  # noqa: E712
                )
            ).first()
            return _row_to_pipeline(row) if row else None

    def update_pipeline(
        self, pipeline_id: int, updates: dict
    ) -> AgentPipeline | None:
        with self._db.session_scope() as session:
            row = session.get(AgentPipelineTable, pipeline_id)
            if not row:
                return None
            for key, val in updates.items():
                if hasattr(row, key) and key != "id":
                    setattr(row, key, val)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            return _row_to_pipeline(row)

    # -- Prompt Template --

    def list_prompt_templates(self) -> list[PromptTemplate]:
        with self._db.session_scope() as session:
            rows = session.exec(
                select(PromptTemplateTable).order_by(PromptTemplateTable.id)
            ).all()
            return [_row_to_template(r) for r in rows]

    def get_prompt_template(self, template_id: int) -> PromptTemplate | None:
        with self._db.session_scope() as session:
            row = session.get(PromptTemplateTable, template_id)
            return _row_to_template(row) if row else None

    def get_prompt_template_by_name(self, name: str) -> PromptTemplate | None:
        with self._db.session_scope() as session:
            row = session.exec(
                select(PromptTemplateTable).where(
                    PromptTemplateTable.name == name
                )
            ).first()
            return _row_to_template(row) if row else None

    def update_prompt_template(
        self, template_id: int, updates: dict
    ) -> PromptTemplate | None:
        with self._db.session_scope() as session:
            row = session.get(PromptTemplateTable, template_id)
            if not row:
                return None
            # Archive current version to history before any template change
            if "template" in updates and updates["template"] != row.template:
                session.add(PromptTemplateHistoryTable(
                    template_id=row.id,
                    name=row.name,
                    version=row.version,
                    template=row.template,
                    variables=row.variables or {},
                    description=row.description,
                ))
                row.version += 1
            for key, val in updates.items():
                if hasattr(row, key) and key != "id":
                    setattr(row, key, val)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            return _row_to_template(row)

    # -- Prompt Template History --

    def list_prompt_history(
        self, template_id: int,
    ) -> list[PromptTemplateHistory]:
        with self._db.session_scope() as session:
            rows = session.exec(
                select(PromptTemplateHistoryTable)
                .where(PromptTemplateHistoryTable.template_id == template_id)
                .order_by(PromptTemplateHistoryTable.version.desc())
            ).all()
            return [_row_to_history(r) for r in rows]

    def get_prompt_history_by_version(
        self, template_id: int, version: int,
    ) -> PromptTemplateHistory | None:
        with self._db.session_scope() as session:
            row = session.exec(
                select(PromptTemplateHistoryTable).where(
                    PromptTemplateHistoryTable.template_id == template_id,
                    PromptTemplateHistoryTable.version == version,
                )
            ).first()
            return _row_to_history(row) if row else None

    def revert_prompt_template(
        self, template_id: int, version: int,
    ) -> PromptTemplate | None:
        """Revert a template to a historical version.

        Archives the current content (so the revert itself is auditable),
        then copies the historical snapshot's template/variables/description
        back onto the live row and bumps version.
        """
        snap = self.get_prompt_history_by_version(template_id, version)
        if not snap:
            return None
        with self._db.session_scope() as session:
            row = session.get(PromptTemplateTable, template_id)
            if not row:
                return None
            # Archive current state first
            session.add(PromptTemplateHistoryTable(
                template_id=row.id,
                name=row.name,
                version=row.version,
                template=row.template,
                variables=row.variables or {},
                description=row.description,
            ))
            row.version += 1
            row.template = snap.template
            row.variables = snap.variables
            row.description = snap.description
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            return _row_to_template(row)

    # -- Celebrity --

    def list_celebrities(self, active_only: bool = False) -> list[Celebrity]:
        with self._db.session_scope() as session:
            stmt = select(CelebrityTable).order_by(CelebrityTable.sort_order)
            if active_only:
                stmt = stmt.where(
                    CelebrityTable.is_active == True  # noqa: E712
                )
            rows = session.exec(stmt).all()
            return [_row_to_celebrity(r) for r in rows]

    def get_celebrity(self, celebrity_id: int) -> Celebrity | None:
        with self._db.session_scope() as session:
            row = session.get(CelebrityTable, celebrity_id)
            return _row_to_celebrity(row) if row else None

    def create_celebrity(self, celebrity: Celebrity) -> Celebrity:
        with self._db.session_scope() as session:
            row = CelebrityTable(
                name=celebrity.name,
                display_name=celebrity.display_name,
                domain=celebrity.domain,
                title=celebrity.title,
                bio=celebrity.bio,
                viewpoints=celebrity.viewpoints,
                analysis_style=celebrity.analysis_style,
                avatar_url=celebrity.avatar_url,
                is_active=celebrity.is_active,
                sort_order=celebrity.sort_order,
            )
            session.add(row)
            session.flush()
            return _row_to_celebrity(row)

    def update_celebrity(
        self, celebrity_id: int, updates: dict
    ) -> Celebrity | None:
        with self._db.session_scope() as session:
            row = session.get(CelebrityTable, celebrity_id)
            if not row:
                return None
            for key, val in updates.items():
                if hasattr(row, key) and key != "id":
                    setattr(row, key, val)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            return _row_to_celebrity(row)

    def delete_celebrity(self, celebrity_id: int) -> bool:
        with self._db.session_scope() as session:
            row = session.get(CelebrityTable, celebrity_id)
            if not row:
                return False
            session.delete(row)
            return True

    def get_news_by_id(self, news_id: int) -> dict | None:
        """Get a single news item by ID from intel_news."""
        with self._db.session_scope() as session:
            row = session.execute(
                text(
                    "SELECT id, title, content, category "
                    "FROM intel_news WHERE id = :id"
                ),
                {"id": news_id},
            ).first()
            if not row:
                return None
            return {
                "id": row[0],
                "title": row[1],
                "content": row[2],
                "category": row[3],
            }

    # -- Agent Tool (registry of builtin / mcp / skill tools) --

    def list_agent_tools(
        self, source: str | None = None,
    ) -> list[AgentTool]:
        with self._db.session_scope() as session:
            stmt = select(AgentToolTable).order_by(AgentToolTable.id)
            if source:
                stmt = stmt.where(AgentToolTable.source == source)
            rows = session.exec(stmt).all()
            return [_row_to_agent_tool(r) for r in rows]

    def get_agent_tool(self, tool_id: int) -> AgentTool | None:
        with self._db.session_scope() as session:
            row = session.get(AgentToolTable, tool_id)
            return _row_to_agent_tool(row) if row else None

    def get_agent_tool_by_ref(self, ref_key: str) -> AgentTool | None:
        with self._db.session_scope() as session:
            row = session.exec(
                select(AgentToolTable).where(AgentToolTable.ref_key == ref_key)
            ).first()
            return _row_to_agent_tool(row) if row else None

    def create_agent_tool(self, data: dict) -> AgentTool:
        with self._db.session_scope() as session:
            row = AgentToolTable(
                name=data["name"],
                display_name=data.get("display_name", ""),
                description=data.get("description", ""),
                source=data["source"],
                ref_key=data["ref_key"],
                args_schema=data.get("args_schema", {}),
                is_active=data.get("is_active", True),
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return _row_to_agent_tool(row)

    def update_agent_tool(
        self, tool_id: int, updates: dict,
    ) -> AgentTool | None:
        with self._db.session_scope() as session:
            row = session.get(AgentToolTable, tool_id)
            if not row:
                return None
            for key, val in updates.items():
                if hasattr(row, key) and key != "id":
                    setattr(row, key, val)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            return _row_to_agent_tool(row)

    def upsert_agent_tool_by_ref(self, data: dict) -> AgentTool:
        """Insert or update a tool keyed by ref_key (used by MCP re-sync).

        On conflict the name/display_name/description/args_schema/is_active
        are refreshed so a re-synced server reflects its current tool set.
        """
        with self._db.session_scope() as session:
            row = session.exec(
                select(AgentToolTable).where(AgentToolTable.ref_key == data["ref_key"])
            ).first()
            if row is None:
                row = AgentToolTable(
                    name=data["name"],
                    display_name=data.get("display_name", ""),
                    description=data.get("description", ""),
                    source=data["source"],
                    ref_key=data["ref_key"],
                    args_schema=data.get("args_schema", {}),
                    is_active=data.get("is_active", True),
                )
            else:
                row.name = data["name"]
                row.display_name = data.get("display_name", row.display_name)
                row.description = data.get("description", row.description)
                row.args_schema = data.get("args_schema", row.args_schema)
                row.is_active = data.get("is_active", row.is_active)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            session.refresh(row)
            return _row_to_agent_tool(row)

    def delete_agent_tool(self, tool_id: int) -> bool:
        with self._db.session_scope() as session:
            row = session.get(AgentToolTable, tool_id)
            if not row:
                return False
            # cascade-delete bindings referencing this tool
            bindings = session.exec(
                select(AgentToolBindingTable).where(
                    AgentToolBindingTable.agent_tool_id == tool_id
                )
            ).all()
            for b in bindings:
                session.delete(b)
            session.delete(row)
            return True

    # -- Agent Tool Binding (which agent uses which tools) --

    def list_bindings(self, agent_config_id: int) -> list[dict]:
        """Return [{agent_tool_id, is_enabled, tool: AgentTool}] for an agent."""
        with self._db.session_scope() as session:
            rows = session.exec(
                select(AgentToolBindingTable).where(
                    AgentToolBindingTable.agent_config_id == agent_config_id
                )
            ).all()
            # 单次批量预取所有绑定工具，避免 N+1（原先每行一次 session.get）。
            tool_ids = {b.agent_tool_id for b in rows}
            tools_by_id: dict[int, AgentToolTable] = {}
            if tool_ids:
                for t in session.exec(
                    select(AgentToolTable).where(
                        AgentToolTable.id.in_(tool_ids)
                    )
                ).all():
                    tools_by_id[t.id] = t
            return [
                {
                    "agent_tool_id": b.agent_tool_id,
                    "is_enabled": b.is_enabled,
                    "tool": _row_to_agent_tool(t) if (t := tools_by_id.get(b.agent_tool_id)) else None,
                }
                for b in rows
            ]

    def list_enabled_tool_refs(self, agent_config_id: int) -> list[str]:
        """ref_keys of enabled tools bound to an agent (for resolve_tools)."""
        with self._db.session_scope() as session:
            rows = session.exec(
                select(AgentToolBindingTable)
                .where(
                    AgentToolBindingTable.agent_config_id == agent_config_id,
                    AgentToolBindingTable.is_enabled == True,  # noqa: E712
                )
            ).all()
            # 单次批量预取，避免 N+1。
            tool_ids = {b.agent_tool_id for b in rows}
            tools_by_id: dict[int, AgentToolTable] = {}
            if tool_ids:
                for t in session.exec(
                    select(AgentToolTable).where(
                        AgentToolTable.id.in_(tool_ids)
                    )
                ).all():
                    tools_by_id[t.id] = t
            return [
                t.ref_key
                for b in rows
                if (t := tools_by_id.get(b.agent_tool_id)) and t.is_active
            ]

    def set_bindings(
        self, agent_config_id: int, agent_tool_ids: list[int],
    ) -> list[dict]:
        """Rewrite an agent's bindings to exactly `agent_tool_ids`.

        Deletes bindings not in the new set, inserts missing ones, leaves
        overlaps untouched (preserving their is_enabled). New bindings
        default to enabled.
        """
        with self._db.session_scope() as session:
            existing = session.exec(
                select(AgentToolBindingTable).where(
                    AgentToolBindingTable.agent_config_id == agent_config_id
                )
            ).all()
            keep_ids = set(agent_tool_ids)
            for b in existing:
                if b.agent_tool_id not in keep_ids:
                    session.delete(b)
            have_ids = {b.agent_tool_id for b in existing}
            for tid in agent_tool_ids:
                if tid not in have_ids:
                    session.add(AgentToolBindingTable(
                        agent_config_id=agent_config_id,
                        agent_tool_id=tid,
                        is_enabled=True,
                    ))
            session.flush()
        return self.list_bindings(agent_config_id)


# ═══════════════════════════════════════════
# Singleton + Factory
# ═══════════════════════════════════════════

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_agent_repository(
    db_connection: DBConnection | None = None,
) -> AgentRepository:
    return AgentRepository(db_connection or _get_db_connection())


# ═══════════════════════════════════════════
# Seed Data
# ═══════════════════════════════════════════

def seed_agent_data() -> None:
    """Insert default agent configs, pipeline, prompt templates, celebrities."""
    db = _get_db_connection()
    with db.session_scope() as session:
        # Only seed if empty
        existing = session.exec(
            select(AgentConfigTable)
        ).first()
        if existing:
            return

        logger.info("[agent_db] Seeding default agent data...")

        # -- Agent Configs --
        configs = [
            AgentConfigTable(
                name="tagging",
                display_name="Tagging Agent",
                description="为新闻打标签：主题、行业、情感分析",
                agent_type="single",
                system_prompt="tagging_system",
                extra_params={"temperature": 0.2},
            ),
            AgentConfigTable(
                name="celebrity",
                display_name="Celebrity Agent",
                description="多名人视角分析 + 辩论 + 综合",
                agent_type="persona",
                system_prompt="celebrity_persona_system",
                extra_params={"temperature": 0.7},
            ),
            AgentConfigTable(
                name="trend",
                display_name="Trend Agent",
                description="事件关联与趋势分析",
                agent_type="single",
                system_prompt="trend_system",
                extra_params={"temperature": 0.3},
            ),
            AgentConfigTable(
                name="report",
                display_name="Report Agent",
                description="综合报告生成",
                agent_type="synthesis",
                system_prompt="report_system",
                extra_params={"temperature": 0.4},
            ),
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
        ]
        for c in configs:
            session.add(c)

        # -- Pipeline --
        pipeline = AgentPipelineTable(
            name="default",
            display_name="Default News Analysis Pipeline",
            description="Tagging -> Celebrity Debate -> Trend -> Report",
            graph_config={
                "nodes": [
                    {
                        "id": "tagging",
                        "agent_config_name": "tagging",
                    },
                    {
                        "id": "celebrity",
                        "agent_config_name": "celebrity",
                        "subgraph": True,
                    },
                    {
                        "id": "trend",
                        "agent_config_name": "trend",
                    },
                    {
                        "id": "report",
                        "agent_config_name": "report",
                    },
                ],
                "edges": [
                    {"from": "START", "to": "tagging"},
                    {"from": "tagging", "to": "celebrity"},
                    {"from": "celebrity", "to": "trend"},
                    {"from": "trend", "to": "report"},
                    {"from": "report", "to": "END"},
                ],
            },
            debate_max_rounds=2,
        )
        session.add(pipeline)

        # -- Prompt Templates --
        templates = [
            PromptTemplateTable(
                name="tagging_system",
                description="TaggingAgent 系统提示词",
                template=(
                    "你是一名专业的金融新闻分析师。你的任务是为新闻文章打标签。\n"
                    "分析新闻的标题和正文，输出以下结构化信息：\n"
                    "- tags: 3-8 个主题标签"
                    "（中文+英文混合，如 \"AI\", \"半导体\", \"美联储\"）\n"
                    "- industry: 主要行业分类"
                    "（Technology/Finance/Healthcare/Energy/"
                    "Consumer/Industrial/RealEstate/Telecom/Utilities/Other）\n"
                    "- sentiment: 情感分数 -1.0 到 1.0\n"
                    "- confidence: 分析置信度 0.0 到 1.0\n\n"
                    "注意：\n"
                    "- 标签应具体而非笼统\n"
                    "- 情感分数反映对市场的潜在影响方向\n"
                    "- 如果新闻内容不足以判断，confidence 应较低"
                ),
                variables={
                    "news_title": "str",
                    "news_content": "str",
                },
                category="system",
            ),
            PromptTemplateTable(
                name="celebrity_persona_system",
                description="名人视角分析系统提示词",
                template=(
                    "你现在要以 {{ display_name }} ({{ name }}) "
                    "的视角来分析一条新闻。\n\n"
                    "你的背景：\n"
                    "头衔: {{ title }}\n"
                    "简介: {{ bio }}\n"
                    "核心观点: {{ viewpoints }}\n"
                    "分析风格: {{ analysis_style }}\n\n"
                    "请从你的专业视角出发，对这条新闻进行分析：\n"
                    "- perspective: 你的观点（100-300字）\n"
                    "- key_insights: 3-5个关键洞察\n"
                    "- investment_implication: 投资含义\n"
                    "- confidence: 置信度\n\n"
                    "保持你独特的分析风格和思维模式。"
                ),
                variables={
                    "display_name": "str",
                    "name": "str",
                    "title": "str",
                    "bio": "str",
                    "viewpoints": "str",
                    "analysis_style": "str",
                    "news_title": "str",
                    "news_content": "str",
                },
                category="system",
            ),
            PromptTemplateTable(
                name="debate_user",
                description="辩论轮次用户提示词",
                template=(
                    "以下是其他名人对同一新闻的观点：\n\n"
                    "{{ other_viewpoints }}\n\n"
                    "请以 {{ display_name }} 的身份回应：\n"
                    "1. 你同意哪些观点？为什么？\n"
                    "2. 你不同意哪些观点？给出你的理由。\n"
                    "3. 补充或修正你之前的分析。"
                ),
                variables={
                    "display_name": "str",
                    "other_viewpoints": "str",
                    "news_title": "str",
                    "news_content": "str",
                },
                category="debate",
            ),
            PromptTemplateTable(
                name="synthesis_system",
                description="名人观点综合提示词",
                template=(
                    "你是一名中立的金融分析主持人。"
                    "以下是多名投资界名人对同一新闻的辩论记录：\n\n"
                    "{{ debate_history }}\n\n"
                    "请综合以上讨论，输出：\n"
                    "- consensus_points: 所有人都同意的要点\n"
                    "- disagreements: 主要分歧点\n"
                    "- overall_sentiment: 综合情感 "
                    "(bullish/bearish/neutral)\n"
                    "- key_takeaway: 一句话总结共识"
                ),
                variables={"debate_history": "str"},
                category="system",
            ),
            PromptTemplateTable(
                name="trend_system",
                description="TrendAgent 系统提示词",
                template=(
                    "你是一名专业的趋势分析师。"
                    "基于以下新闻内容及其分析结果，"
                    "进行事件关联和趋势分析。\n\n"
                    "新闻标签: {{ tags }}\n"
                    "行业: {{ industry }}\n"
                    "名人共识: {{ celebrity_consensus }}\n\n"
                    "请输出：\n"
                    "- related_events: 关联的近期事件"
                    "（推断可能相关的宏观/行业事件）\n"
                    "- trend_direction: 趋势方向 "
                    "(rising/declining/stable/volatile)\n"
                    "- confidence: 置信度\n"
                    "- analysis: 趋势分析正文（200-400字）\n"
                    "- time_horizon: 影响时间跨度 "
                    "(short/medium/long)\n\n"
                    "注意基于已知信息进行推理，"
                    "对不确定的部分标注低置信度。"
                ),
                variables={
                    "tags": "list",
                    "industry": "str",
                    "celebrity_consensus": "dict",
                    "news_title": "str",
                    "news_content": "str",
                },
                category="system",
            ),
            PromptTemplateTable(
                name="report_system",
                description="ReportAgent 系统提示词",
                template=(
                    "你是一名高级投资研究报告撰写人。"
                    "请基于以下所有分析结果，撰写一份综合报告。\n\n"
                    "新闻: {{ news_title }}\n\n"
                    "标签与情感: {{ tags }}, sentiment={{ sentiment }}\n"
                    "名人观点综合: {{ celebrity_consensus }}\n"
                    "趋势分析: {{ trend_analysis }}\n\n"
                    "请输出结构化报告：\n"
                    "- executive_summary: 执行摘要（100-200字）\n"
                    "- key_findings: 5-8个关键发现\n"
                    "- celebrity_consensus_summary: "
                    "名人观点共识摘要\n"
                    "- trend_outlook: 趋势展望\n"
                    "- risk_factors: 3-5个风险因素\n"
                    "- investment_recommendation: 投资建议\n"
                    "- confidence_level: 整体置信度 "
                    "(high/medium/low)\n\n"
                    "报告应客观、专业，突出不确定性。"
                ),
                variables={
                    "news_title": "str",
                    "tags": "list",
                    "sentiment": "float",
                    "celebrity_consensus": "dict",
                    "trend_analysis": "dict",
                },
                category="system",
            ),
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
                description="ImageAdvisorAgent 配图建议提示词（type 路由版）",
                template=(
                    "你是一名微信公众号配图顾问。根据以下博文内容，建议 3-5 个配图位置，"
                    "并为每个位置选择最合适的配图类型。\n\n"
                    "博文标题：{{ title }}\n\n"
                    "博文正文：\n{{ content }}\n\n"
                    "对每个配图位置，输出：\n"
                    "- position: 在哪一段之后（如 '第2段后'、'小结部分'）\n"
                    "- description: 配图应该展示什么（详细描述）\n"
                    "- type: 配图类型，四选一：\n"
                    "    * chart   — 数据图表（当正文涉及数据对比、排名、趋势时选这个，需填 chart_spec）\n"
                    "    * concept — AI 概念图（抽象概念需要可视化时选这个）\n"
                    "    * photo   — 真实相关图片（人物、产品、场景、实体物件时选这个）\n"
                    "    * cover   — 标准化封面（通常只有第 1 张选这个）\n"
                    "- keywords: 3-5 个关键词\n"
                    "    * type=photo 时用英文（如 'OpenAI logo'、'stock market trading floor'）\n"
                    "    * type=concept 时用英文生图提示词，写具体画面而非抽象词，"
                    "例如 'futuristic data center glowing blue servers' 而非 'AI technology'。\n"
                    "    * 用逗号分隔\n"
                    "- chart_spec: 仅当 type=chart 时必填，结构：\n"
                    "    {chart_type: 'bar'|'line'|'pie'|'doughnut', title: '...', "
                    "labels: [...], datasets: [{label: '...', data: [...]}]}\n\n"
                    "配图原则：\n"
                    "- 与内容紧密相关，不是装饰\n"
                    "- 有数据对比就优先 chart（比文字更有说服力）\n"
                    "- 有具体实体（公司/产品/人物）就选 photo\n"
                    "- abstract 概念才选 concept\n"
                    "- keywords 要具体，便于搜索或生图"
                ),
                variables={"title": "str", "content": "str"},
                category="system",
            ),
        ]
        for t in templates:
            session.add(t)

        # -- Celebrities --
        celebrities = [
            CelebrityTable(
                name="Elon Musk",
                display_name="马斯克",
                domain="tech",
                title="Tesla / SpaceX / xAI CEO",
                bio=(
                    "科技企业家，以大胆创新和跨界思维著称。"
                    "涉足电动车、航天、AI、脑机接口等领域。"
                ),
                viewpoints=(
                    "1. AI 是人类面临的最大机遇和风险\n"
                    "2. 电动车和可持续能源是必然趋势\n"
                    "3. 人口崩溃比人口过剩是更大的威胁\n"
                    "4. 多行星物种是人类长期生存的关键"
                ),
                analysis_style=(
                    "大胆前瞻，关注颠覆性创新和技术拐点，"
                    "偏好高风险高回报逻辑"
                ),
                sort_order=1,
            ),
            CelebrityTable(
                name="Warren Buffett",
                display_name="巴菲特",
                domain="finance",
                title="Berkshire Hathaway CEO",
                bio=(
                    "价值投资之父，被誉为\"奥马哈先知\"。"
                    "长期坚持基本面投资，强调安全边际和护城河。"
                ),
                viewpoints=(
                    "1. 别人贪婪时恐惧，别人恐惧时贪婪\n"
                    "2. 只投资你能理解的公司（能力圈原则）\n"
                    "3. 优秀公司的合理价格好于平庸公司的便宜价格\n"
                    "4. 长期持有，忽略短期波动"
                ),
                analysis_style=(
                    "注重基本面和安全边际，偏好稳健价值股，"
                    "回避热点炒作"
                ),
                sort_order=2,
            ),
            CelebrityTable(
                name="Ray Dalio",
                display_name="达利欧",
                domain="finance",
                title="Bridgewater Associates Founder",
                bio=(
                    "全球最大对冲基金创始人，宏观投资大师。"
                    "提倡\"原则\"思维和经济机器模型。"
                ),
                viewpoints=(
                    "1. 理解经济机器的运行规律\n"
                    "2. 长期债务周期决定了大趋势\n"
                    "3. 分散化是最重要的投资原则\n"
                    "4. 痛苦+反思=进步"
                ),
                analysis_style=(
                    "宏观视角，关注经济周期、货币政策"
                    "和地缘政治的交互影响"
                ),
                sort_order=3,
            ),
            CelebrityTable(
                name="Cathie Wood",
                display_name="木头姐",
                domain="tech",
                title="ARK Invest CEO",
                bio=(
                    "颠覆性创新投资的代表人物，管理ARK系列主动ETF，"
                    "重仓AI、基因编辑、区块链等前沿领域。"
                ),
                viewpoints=(
                    "1. 创新平台（AI/基因/区块链/机器人）正在融合加速\n"
                    "2. 传统价值投资低估了颠覆性创新的价值\n"
                    "3. 5年投资视野，关注指数级增长机会\n"
                    "4. 比特币和区块链将重塑金融体系"
                ),
                analysis_style=(
                    "高成长偏好，重视技术融合的乘数效应，"
                    "5年远期估值"
                ),
                sort_order=4,
            ),
        ]
        for c in celebrities:
            session.add(c)

        logger.info("[agent_db] Default agent data seeded")


# ═══════════════════════════════════════════
# Blog Prompt Migration (idempotent upsert)
# ═══════════════════════════════════════════

# Prompt templates referenced by the blog pipeline but not in the
# original seed_agent_data(). Each entry mirrors the fallback string
# hard-coded in the corresponding agent/processor, so DB becomes the
# single source of truth. content/variables mirror the code fallbacks.
_BLOG_PROMPT_SEEDS: list[dict] = [
    {
        "name": "blog_agent_system",
        "description": "Blog Agent 对话编排系统提示词（选热点→取素材→起草→改写）",
        "category": "system",
        "variables": {},
        "template": (
            "你是公众号写作助手。通过调用工具帮用户完成「选热点题材 → 取素材 → 起草 → 按指令修改」的全流程。\n"
            "规则：\n"
            "1. 能用工具就用工具（如用户问热点就调 discover_trends；要写就调 write_draft），"
            "不要凭空编造热点或正文。\n"
            "2. 工具返回后，用简短中文向用户说明结果（如列出找到的热点），并问下一步要做什么。\n"
            "3. 修改草稿时，根据用户的具体指令调 revise_draft（如「标题更口语化」「第三段加数据」）。\n"
            "4. 一次只推进一步，等用户确认或给明确指令再继续。\n"
            "5. 不要自动连续调用多个工具（除非用户一次提了多个明确需求）。"
        ),
    },
    {
        "name": "trend_spotter_system",
        "description": "TrendSpotter 跨平台热点聚合提示词",
        "category": "system",
        "variables": {"hotlist_data": "str", "platform_names": "str"},
        "template": (
            "你是一名热点趋势分析师。"
            "以下是各平台最近的热榜数据：\n\n"
            "{{ hotlist_data }}\n\n"
            "平台名称映射：{{ platform_names }}\n\n"
            "你的任务：\n"
            "1. 将语义相似（讨论同一事件/话题）的标题"
            "归为同一个热点\n"
            "2. 计算每个热点的综合评分（0-10）：\n"
            "   - 跨平台出现数量越多，分越高"
            "（出现在 ≥3 个平台 = 7分起）\n"
            "   - 排名越靠前（1-5名），额外加分\n"
            "   - 多平台同时出现 = 重大热点\n"
            "3. 判断排名趋势：rising（快速上升）、"
            "stable（稳定前排）、new（新上榜）\n"
            "4. 按 score 降序排列\n\n"
            "注意：\n"
            "- 只聚合真正相关的话题，不要牵强\n"
            "- 如果某个话题只在单个平台出现但排名极靠前，"
            "也可以纳入\n"
            "- source_urls 从输入数据中提取对应的 url"
        ),
    },
    {
        "name": "deep_analysis_system",
        "description": "DeepAnalysis 文章深度解读提示词",
        "category": "system",
        "variables": {"theme": "str", "topic_hint": "str", "corpus": "str"},
        "template": (
            "深度解读以下文章，为主题「{{ theme }}」"
            "（选题：{{ topic_hint }}）提炼关键要点(5-8)、"
            "关键实体、建议写作角度。只基于文章事实，"
            "不要编造。\n\n{{ corpus }}"
        ),
    },
    {
        "name": "editor_in_chief_system",
        "description": "EditorInChief 质量评审提示词",
        "category": "system",
        "variables": {
            "theme": "str", "title": "str",
            "content": "str", "evidence": "str", "rubric": "str",
        },
        "template": (
            "你是「{{ theme }}」公众号主编。"
            "评审以下博文草稿。\n"
            "评分维度(0-10)：信息密度/可读性/"
            "事实可溯性/专题契合度/标题吸引力/综合。\n"
            "事实可溯性最重要：检查草稿论点是否"
            "在下列来源依据中有支撑，"
            "列出无支撑的论点（unsupported_claims）。\n"
            "评审标准：{{ rubric }}\n\n"
            "标题：{{ title }}\n正文：{{ content }}\n\n"
            "来源依据：\n{{ evidence }}"
        ),
    },
    {
        "name": "blog_writer_ai_tech",
        "description": "BlogWriter — AI技术专题写作提示词",
        "category": "system",
        "variables": {
            "style": "str", "topic_title": "str",
            "suggested_angle": "str", "key_points": "str", "evidence": "str",
        },
        "template": (
            "你是一名擅长以「AI 视角」解读技术前沿的公众号作者。\n"
            "请写一篇面向技术开发者与研究者的深度技术博文，"
            "分析原理、引用数据、面向技术人员，"
            "结构：背景→原理→应用→展望。\n\n"
            "主题：{{ topic_title }}\n"
            "建议角度：{{ suggested_angle }}\n"
            "关键要点：{{ key_points }}\n"
            "依据素材：{{ evidence }}\n"
            "风格：{{ style }}。只基于依据素材的事实，不要编造。"
        ),
    },
    {
        "name": "blog_writer_ai_app",
        "description": "BlogWriter — AI应用专题写作提示词",
        "category": "system",
        "variables": {
            "style": "str", "topic_title": "str",
            "suggested_angle": "str", "key_points": "str", "evidence": "str",
        },
        "template": (
            "你是一名擅长以「AI 视角」解读社会热点的公众号作者。\n"
            "请用 AI / 大模型 / 技术的视角解读下面的热点话题"
            "（如 AI 如何预测/分析/影响/重塑该话题），"
            "让大众看得懂、觉得有趣。用比喻解释技术，"
            "少用术语，有故事线，面向大众，"
            "结构：引人入胜的开头→核心概念→实际影响→未来想象。\n\n"
            "主题：{{ topic_title }}\n"
            "建议角度：{{ suggested_angle }}\n"
            "关键要点：{{ key_points }}\n"
            "依据素材：{{ evidence }}\n"
            "风格：{{ style }}。只基于依据素材的事实，不要编造。"
        ),
    },
    {
        "name": "blog_writer_stock",
        "description": "BlogWriter — 炒股专题写作提示词",
        "category": "system",
        "variables": {
            "style": "str", "topic_title": "str",
            "suggested_angle": "str", "key_points": "str", "evidence": "str",
        },
        "template": (
            "你是一名专业的股市分析公众号作者。\n"
            "请写一篇面向股民与投资者的博文，"
            "专业准确、逻辑严密、含风险提示、"
            "合规（不构成投资建议）。\n\n"
            "主题：{{ topic_title }}\n"
            "建议角度：{{ suggested_angle }}\n"
            "关键要点：{{ key_points }}\n"
            "依据素材：{{ evidence }}\n"
            "风格：{{ style }}。只基于依据素材的事实，不要编造。"
        ),
    },
    # Original seed prompts that may be absent if seed_agent_data
    # returned early on a partially-populated DB.
    {
        "name": "blog_writer_system",
        "description": "BlogWriterAgent 博文写作提示词 (默认)",
        "category": "system",
        "variables": {
            "style": "str", "topic_title": "str",
            "topic_reason": "str", "key_angles": "str",
            "news_summaries": "str",
        },
        "template": (
            "你是一名微信公众号科技博主，"
            "擅长写有深度又有可读性的科技文章。\n\n"
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
            "- 短段落（每段 3-4 行），"
            "适当使用 **加粗**\n"
            "- 有清晰的小标题分隔各部分\n"
            "- 结尾有总结或展望\n\n"
            "{% if style == 'tech_depth' %}"
            "技术深度型要求：深入分析原理，引用数据，"
            "面向技术人员，结构：背景→原理→应用→展望\n"
            "{% elif style == 'pop_science' %}"
            "通俗科普型要求：用比喻解释技术，少用术语，"
            "有故事线，面向大众，"
            "结构：引人入胜的开头→核心概念→实际影响→未来想象\n"
            "{% elif style == 'hot_commentary' %}"
            "热点评论型要求：快速梳理事件脉络，"
            "多源整合，犀利点评，有数据支撑，"
            "结构：事件回顾→多方观点→我的分析→行业影响\n"
            "{% endif %}"
        ),
    },
    {
        "name": "image_advisor_system",
        "description": "ImageAdvisorAgent 配图建议提示词（type 路由版）",
        "category": "system",
        "variables": {"title": "str", "content": "str"},
        "template": (
            "你是一名微信公众号配图顾问。"
            "根据以下博文内容，建议 3-5 个配图位置，"
            "并为每个位置选择最合适的配图类型。\n\n"
            "博文标题：{{ title }}\n\n"
            "博文正文：\n{{ content }}\n\n"
            "对每个配图位置，输出：\n"
            "- position: 在哪一段之后"
            "（如 '第2段后'、'小结部分'）\n"
            "- description: 配图应该展示什么（详细描述）\n"
            "- type: 配图类型，四选一：\n"
            "    * chart   — 数据图表（涉及数据对比/排名/趋势时选，需填 chart_spec）\n"
            "    * concept — AI 概念图（抽象概念可视化）\n"
            "    * photo   — 真实相关图片（人物/产品/场景/实体）\n"
            "    * cover   — 标准化封面（通常仅第 1 张）\n"
            "- keywords: 3-5 个关键词\n"
            "    * type=photo 用英文（如 'OpenAI logo'）\n"
            "    * type=concept 用英文生图提示词，写具体画面而非抽象词"
            "（如 'futuristic data center glowing blue servers'）\n"
            "- chart_spec: 仅 type=chart 时必填："
            "{chart_type, title, labels[], datasets[{label,data}]}\n\n"
            "配图原则：\n"
            "- 与内容紧密相关，不是装饰\n"
            "- 有数据对比优先 chart\n"
            "- 有具体实体选 photo，abstract 概念才选 concept\n"
            "- keywords 要具体，便于搜索或生图"
        ),
    },
    # ── User prompts (category="user") ──
    # Mirror the inline user-message strings in each agent node so they are
    # editable from the Prompt console. Names follow the "<node>_user"
    # convention. Idempotent: only inserted when absent (existing edits kept).
    {
        "name": "trend_spotter_user",
        "description": "TrendSpotter 用户提示词（分析指令）",
        "category": "user",
        "variables": {},
        "template": (
            "请分析以上各平台热榜数据，识别跨平台共振的热点话题。\n"
            "将语义相似的标题归为同一个热点，按综合评分降序排列。\n"
            "至少输出 6 个，最多 12 个趋势话题（热点多时尽量多输出）。"
        ),
    },
    {
        "name": "deep_analysis_user",
        "description": "DeepAnalysis 用户提示词（解读指令）",
        "category": "user",
        "variables": {},
        "template": "请深度解读以上文章并结构化输出。",
    },
    {
        "name": "blog_writer_user",
        "description": "BlogWriter 用户提示词（写作指令）",
        "category": "user",
        "variables": {
            "topic_title": "str",
            "style": "str",
            "revision_feedback": "str",
        },
        "template": (
            "请写一篇关于「{{ topic_title or 'AI科技' }}」的微信公众号博文，"
            "风格：{{ style }}"
            "{% if revision_feedback %}"
            "\n\n【主编修改意见，请据此重写】\n{{ revision_feedback }}"
            "{% endif %}"
        ),
    },
    {
        "name": "editor_in_chief_user",
        "description": "EditorInChief 用户提示词（评审指令）",
        "category": "user",
        "variables": {},
        "template": "请评审以上博文草稿。",
    },
]

# Agent configs referenced by create_chat_model_for_agent but not in
# the original seed. extra_params mirror existing blog agents.
_BLOG_AGENT_SEEDS: list[dict] = [
    {
        "name": "deep_analysis",
        "display_name": "Deep Analysis",
        "description": "深度解读检索到的文章,提炼 Material",
        "agent_type": "single",
        "system_prompt": "deep_analysis_system",
        "extra_params": {"temperature": 0.3},
    },
    {
        "name": "editor_in_chief",
        "display_name": "Editor in Chief",
        "description": "博文质量评审 + 事实核查,决定 approve/revise",
        "agent_type": "single",
        "system_prompt": "editor_in_chief_system",
        "extra_params": {"temperature": 0.3},
    },
    {
        "name": "blog_writer",
        "display_name": "Blog Writer",
        "description": "按指定风格写微信公众号博文",
        "agent_type": "single",
        "system_prompt": "blog_writer_system",
        "extra_params": {"temperature": 0.7},
    },
    {
        "name": "image_advisor",
        "display_name": "Image Advisor",
        "description": "为博文建议配图位置和关键词",
        "agent_type": "single",
        "system_prompt": "image_advisor_system",
        "extra_params": {"temperature": 0.4},
    },
]


def _upsert_prompt_template(session, seed: dict) -> None:
    """Insert a prompt template only if its name is absent.

    Existing rows (including user edits) are never touched, so this is
    safe to run repeatedly on upgrade.
    """
    existing = session.exec(
        select(PromptTemplateTable).where(
            PromptTemplateTable.name == seed["name"]
        )
    ).first()
    if existing:
        return
    session.add(PromptTemplateTable(
        name=seed["name"],
        description=seed["description"],
        template=seed["template"],
        variables=seed["variables"],
        category=seed["category"],
    ))


def _upsert_agent_config(session, seed: dict) -> None:
    """Insert an agent config only if its name is absent."""
    existing = session.exec(
        select(AgentConfigTable).where(
            AgentConfigTable.name == seed["name"]
        )
    ).first()
    if existing:
        return
    session.add(AgentConfigTable(
        name=seed["name"],
        display_name=seed["display_name"],
        description=seed["description"],
        agent_type=seed["agent_type"],
        system_prompt=seed["system_prompt"],
        extra_params=seed["extra_params"],
    ))


def migrate_blog_prompts() -> None:
    """Idempotently backfill blog prompt templates + agent configs.

    Inserts the 4 prompt templates + 3 blog_writer variants + 3 agent
    configs that the blog pipeline references but the original seed
    omitted. Runs at app startup after seed_agent_data. Safe to call
    repeatedly: existing rows are left untouched.
    """
    db = _get_db_connection()
    with db.session_scope() as session:
        added = 0
        for seed in _BLOG_PROMPT_SEEDS:
            before = session.exec(
                select(PromptTemplateTable).where(
                    PromptTemplateTable.name == seed["name"]
                )
            ).first()
            if before is None:
                _upsert_prompt_template(session, seed)
                added += 1
        for seed in _BLOG_AGENT_SEEDS:
            before = session.exec(
                select(AgentConfigTable).where(
                    AgentConfigTable.name == seed["name"]
                )
            ).first()
            if before is None:
                _upsert_agent_config(session, seed)
                added += 1
        if added:
            logger.info(
                f"[agent_db] Migrated blog prompts: {added} rows added"
            )


# ═══════════════════════════════════════════
# Macro Analyst — prompt + agent config seeds
# ═══════════════════════════════════════════

_MACRO_PROMPT_SEEDS: list[dict] = [
    {
        "name": "macro_analyst_system",
        "description": "宏观分析师系统提示词（组合理论框架推理 + 可证伪化 + 防幻觉）",
        "category": "system",
        "variables": {"context": "str"},
        "template": (
            "你是一位严谨的宏观经济分析师，负责生成可证伪、可回测的宏观判断快照。\n\n"
            "【方法论·组合理论框架】你必须基于以下经典理论框架推理，不可凭直觉：\n"
            "1. 美林时钟（增长×通胀定位象限）：复苏→利股 / 过热→利商品 / 滞胀→利现金 / 衰退→利债。\n"
            "2. 货币主义（Friedman）：M2 增速领先通胀 12-18 个月。\n"
            "3. 达里奥债务周期：信贷扩张→繁荣→去杠杆，利率/社融是枢纽。\n"
            "4. 金融周期（BIS）：信贷缺口 + 杠杆累积，判断金融脆弱性。\n"
            "5. 收益率曲线倒挂：衰退先行指标。\n\n"
            "【三条铁律】\n"
            "1. 趋势比绝对值重要。\n2. 拐点比水平重要。\n3. 共振比单指标可靠。\n\n"
            "【输出·分两段，缺一不可】\n"
            "第一段·objective_reading（客观解读）：逐指标解释当前值含义、趋势方向、与历史/阈值对比、指标间关系。\n"
            "  ⚠️ 这一段【禁止任何结论性判断】：不说'偏多/偏空'，不说'利好/利空'，不下任何方向结论。\n"
            "  只陈述事实与含义，让读者自己形成判断。\n"
            "第二段·立场：基于客观解读，给出 overall_stance(bullish/bearish/neutral) + confidence + "
            "macro_judgments(各维度方向) + asset_predictions(资产方向) + summary(立场理由)。\n"
            "  立场理由须引用具体数据点 + 点明理论框架。\n\n"
            "【上下文数据】\n{{ context }}\n\n"
            "请严格按两段式输出。"
        ),
    },
    {
        "name": "macro_analyst_user",
        "description": "宏观分析师用户提示词（生成指令）",
        "category": "user",
        "variables": {"snapshot_date": "str", "horizon_days": "int"},
        "template": (
            "今天是 {{ snapshot_date }}。请基于上方上下文数据，生成未来 {{ horizon_days }} 个交易日（约1个季度）的宏观判断快照。\n\n"
            "务必分两段：\n"
            "1. objective_reading：先做客观解读，逐指标讲含义与关系，【不下任何结论】。\n"
            "2. 立场：再给 overall_stance + confidence + macro_judgments + asset_predictions + summary。\n"
            "用组合理论框架定位周期象限（regime_quadrant）。summary 是立场理由（非客观解读）。"
        ),
    },
]

_MACRO_AGENT_SEEDS: list[dict] = [
    {
        "name": "macro_analyst",
        "display_name": "Macro Analyst",
        "description": "宏观经济判断快照生成（双轨分层：宏观状态 + 资产方向）",
        "agent_type": "single",
        "system_prompt": "macro_analyst_system",
        "extra_params": {"temperature": 0.3},
    },
]


def migrate_macro_prompts() -> None:
    """Idempotently backfill macro analyst prompt templates + agent config.

    Runs at app startup alongside migrate_blog_prompts. Safe to call
    repeatedly: existing rows (incl. user edits) are never touched.
    """
    # Defensive import: AgentConfigTable.llm_config_id FK targets llm_config.id;
    # ensure the LLM entity is registered in SQLModel.metadata so mapper
    # configuration / create_all can resolve the FK regardless of import order.
    from src.infra.database.llm.entity import LLMConfigTable  # noqa: F401

    db = _get_db_connection()
    with db.session_scope() as session:
        added = 0
        for seed in _MACRO_PROMPT_SEEDS:
            before = session.exec(
                select(PromptTemplateTable).where(
                    PromptTemplateTable.name == seed["name"]
                )
            ).first()
            if before is None:
                _upsert_prompt_template(session, seed)
                added += 1
        for seed in _MACRO_AGENT_SEEDS:
            before = session.exec(
                select(AgentConfigTable).where(
                    AgentConfigTable.name == seed["name"]
                )
            ).first()
            if before is None:
                _upsert_agent_config(session, seed)
                added += 1
        if added:
            logger.info(
                f"[agent_db] Migrated macro prompts: {added} rows added"
            )


def migrate_macro_prompts_v2() -> None:
    """强制把 macro_analyst prompt 升级为两段式版本。

    与 migrate_macro_prompts（仅不存在时插入）不同，此函数用 update_prompt_template
    更新已存在的行（旧版本自动归档到 prompt_template_history）。
    幂等：通过 template 内容前缀判断是否已是 v2，已升级则跳过。
    """
    from src.infra.database.llm.entity import LLMConfigTable  # noqa: F401
    db = _get_db_connection()
    v2_marker = "【输出·分两段，缺一不可】"
    with db.session_scope() as session:
        updated = 0
        for seed in _MACRO_PROMPT_SEEDS:
            existing = session.exec(
                select(PromptTemplateTable).where(
                    PromptTemplateTable.name == seed["name"]
                )
            ).first()
            if not existing:
                # 全新部署：直接插入（走 seed 路径）
                _upsert_prompt_template(session, seed)
                updated += 1
                continue
            if v2_marker in (existing.template or ""):
                continue  # 已是 v2（system prompt 含此标记）
            if existing.template == seed["template"]:
                continue  # 内容已与目标一致（user prompt 无统一标记，按内容判等保证幂等）
            # 升级：update_prompt_template 归档旧版 + 写新版
            _update_prompt_template_inplace(session, existing, seed)
            updated += 1
        if updated:
            logger.info(f"[agent_db] Migrated macro prompts to v2: {updated} rows")


def _update_prompt_template_inplace(session, row, seed: dict) -> None:
    """就地更新 prompt template 行：归档旧版到 history，提升 version，写新内容。

    （简化版 update_prompt_template，避免循环 import；复用 prompt_template_history 表。）
    """
    from src.infra.database.agent.entity import PromptTemplateHistoryTable
    # 归档旧版
    session.add(PromptTemplateHistoryTable(
        template_id=row.id,
        name=row.name,
        template=row.template,
        variables=row.variables,
        version=row.version,
    ))
    # 写新版
    row.template = seed["template"]
    row.variables = seed["variables"]
    row.description = seed["description"]
    row.version = (row.version or 1) + 1


# ═══════════════════════════════════════════
# Agent Tool Registry — seed + migration
# ═══════════════════════════════════════════

# The 4 built-in blog-agent tools. ref_key = the Python function name, which
# tool_registry._BUILTIN_TOOLS maps to the actual @tool-decorated callable.
# Seeds are idempotent: existing rows (incl. user edits) are never touched.
_AGENT_TOOL_SEEDS: list[dict] = [
    {
        "name": "discover_trends",
        "display_name": "发现热点",
        "description": "发现最近的跨平台热点话题（theme 过滤、count 限量）",
        "source": "builtin",
        "ref_key": "discover_trends",
        "args_schema": {},
        "is_active": True,
    },
    {
        "name": "fetch_articles",
        "display_name": "检索素材",
        "description": "按主题关键词检索深度全文素材",
        "source": "builtin",
        "ref_key": "fetch_articles",
        "args_schema": {},
        "is_active": True,
    },
    {
        "name": "write_draft",
        "display_name": "起草博文",
        "description": "根据选题起草一篇公众号博文（深度分析→写作，HITL 审批）",
        "source": "builtin",
        "ref_key": "write_draft",
        "args_schema": {},
        "is_active": True,
    },
    {
        "name": "revise_draft",
        "display_name": "修改草稿",
        "description": "按用户修改指令重写一篇已存在的草稿",
        "source": "builtin",
        "ref_key": "revise_draft",
        "args_schema": {},
        "is_active": True,
    },
]


def _upsert_agent_tool(session, seed: dict) -> None:
    """Insert an agent_tool only if its ref_key is absent."""
    existing = session.exec(
        select(AgentToolTable).where(AgentToolTable.ref_key == seed["ref_key"])
    ).first()
    if existing:
        return
    session.add(AgentToolTable(
        name=seed["name"],
        display_name=seed.get("display_name", ""),
        description=seed["description"],
        source=seed["source"],
        ref_key=seed["ref_key"],
        args_schema=seed.get("args_schema", {}),
        is_active=seed.get("is_active", True),
    ))


def migrate_agent_tools() -> None:
    """Idempotently seed agent_tool registry + bind builtins to blog_writer.

    Inserts the 4 built-in blog-agent tools into agent_tool and creates an
    enabled agent_tool_binding row for each against the blog_writer agent
    config (so the agent works out of the box with the same 4 tools it had
    when they were hard-coded). Runs at startup after migrate_blog_prompts.
    Existing tools / bindings are never touched.
    """
    db = _get_db_connection()
    with db.session_scope() as session:
        added = 0
        # 1. seed the 4 built-in tools
        tool_ids: list[int] = []
        for seed in _AGENT_TOOL_SEEDS:
            row = session.exec(
                select(AgentToolTable).where(
                    AgentToolTable.ref_key == seed["ref_key"]
                )
            ).first()
            if row is None:
                _upsert_agent_tool(session, seed)
                session.flush()
                row = session.exec(
                    select(AgentToolTable).where(
                        AgentToolTable.ref_key == seed["ref_key"]
                    )
                ).first()
                added += 1
            if row:
                tool_ids.append(row.id)

        # 2. bind all 4 to blog_writer (if blog_writer config exists & not bound)
        blog_cfg = session.exec(
            select(AgentConfigTable).where(AgentConfigTable.name == "blog_writer")
        ).first()
        if blog_cfg and tool_ids:
            for tid in tool_ids:
                already = session.exec(
                    select(AgentToolBindingTable).where(
                        AgentToolBindingTable.agent_config_id == blog_cfg.id,
                        AgentToolBindingTable.agent_tool_id == tid,
                    )
                ).first()
                if already is None:
                    session.add(AgentToolBindingTable(
                        agent_config_id=blog_cfg.id,
                        agent_tool_id=tid,
                        is_enabled=True,
                    ))
                    added += 1
        if added:
            logger.info(f"[agent_db] Migrated agent tools: {added} rows added")
