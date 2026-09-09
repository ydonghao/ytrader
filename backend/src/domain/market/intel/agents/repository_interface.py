"""Agent repository interface — domain layer contract."""
from abc import ABC, abstractmethod
from src.domain.market.intel.agents.models import (
    AgentConfig,
    AgentPipeline,
    Celebrity,
    PromptTemplate,
    PromptTemplateHistory,
)


class IAgentRepository(ABC):
    """Agent 系统 CRUD 接口, 覆盖 agent_config/pipeline/template/celebrity 四张表."""

    # ── Agent Config ──
    @abstractmethod
    def list_agent_configs(self) -> list[AgentConfig]: ...

    @abstractmethod
    def get_agent_config(self, config_id: int) -> AgentConfig | None: ...

    @abstractmethod
    def get_agent_config_by_name(self, name: str) -> AgentConfig | None: ...

    @abstractmethod
    def update_agent_config(self, config_id: int, updates: dict) -> AgentConfig | None: ...

    # ── Pipeline ──
    @abstractmethod
    def list_pipelines(self) -> list[AgentPipeline]: ...

    @abstractmethod
    def get_pipeline(self, pipeline_id: int) -> AgentPipeline | None: ...

    @abstractmethod
    def get_active_pipeline(self) -> AgentPipeline | None: ...

    @abstractmethod
    def update_pipeline(self, pipeline_id: int, updates: dict) -> AgentPipeline | None: ...

    # ── Prompt Template ──
    @abstractmethod
    def list_prompt_templates(self) -> list[PromptTemplate]: ...

    @abstractmethod
    def get_prompt_template(self, template_id: int) -> PromptTemplate | None: ...

    @abstractmethod
    def get_prompt_template_by_name(self, name: str) -> PromptTemplate | None: ...

    @abstractmethod
    def update_prompt_template(self, template_id: int, updates: dict) -> PromptTemplate | None: ...

    # ── Prompt Template History ──
    @abstractmethod
    def list_prompt_history(
        self, template_id: int,
    ) -> list[PromptTemplateHistory]: ...

    @abstractmethod
    def get_prompt_history_by_version(
        self, template_id: int, version: int,
    ) -> PromptTemplateHistory | None: ...

    @abstractmethod
    def revert_prompt_template(
        self, template_id: int, version: int,
    ) -> PromptTemplate | None: ...

    # ── Celebrity ──
    @abstractmethod
    def list_celebrities(self, active_only: bool = False) -> list[Celebrity]: ...

    @abstractmethod
    def get_celebrity(self, celebrity_id: int) -> Celebrity | None: ...

    @abstractmethod
    def create_celebrity(self, celebrity: Celebrity) -> Celebrity: ...

    @abstractmethod
    def update_celebrity(self, celebrity_id: int, updates: dict) -> Celebrity | None: ...

    @abstractmethod
    def delete_celebrity(self, celebrity_id: int) -> bool: ...
