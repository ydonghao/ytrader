"""LLM config management API router."""
from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException

from src.domain.llm.models import LLMConfig
from src.infra.database.llm.repository import create_llm_repository
from src.infra.llm.manager import LLMManager
from src.api.model.llm_config_model import (
    LLMConfigCreate,
    LLMConfigUpdate,
    LLMConfigResponse,
    LLMTestRequest,
    LLMTestResponse,
)

router = APIRouter(prefix="/llm", tags=["llm"])

# 懒加载：模块导入即建仓库会触发 SQLAlchemy 连库（任何 import 该包的
# 测试/工具都会触库，DB 不可用时应用起不来）；延迟到首个请求。
_repo = None
_manager = None
_LLM_INIT_LOCK = threading.Lock()


def _get_manager():
    global _repo, _manager
    if _manager is None:
        with _LLM_INIT_LOCK:
            if _manager is None:
                _repo = create_llm_repository()
                _manager = LLMManager(_repo)
    return _manager


def _get_repo():
    _get_manager()
    return _repo


def _ok(data):
    """Unified success response helper."""
    return {"code": 0, "msg": "ok", "data": data}


def _to_response(config: LLMConfig) -> LLMConfigResponse:
    return LLMConfigResponse(
        id=config.id,
        name=config.name,
        provider_type=config.provider_type,
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        is_default=config.is_default,
        extra_params=config.extra_params,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.get("/configs")
def list_configs():
    """List all LLM model configs (API keys masked)."""
    configs = _get_repo().list_configs()
    return _ok([_to_response(c) for c in configs])


@router.post("/configs", status_code=201)
def create_config(body: LLMConfigCreate):
    """Create a new LLM model config."""
    config = LLMConfig(
        name=body.name,
        provider_type=body.provider_type,
        base_url=body.base_url,
        api_key=body.api_key,
        model=body.model,
        is_default=body.is_default,
        extra_params=body.extra_params,
    )
    created = _get_repo().create_config(config)
    _get_manager().refresh()
    return _ok(_to_response(created))


@router.put("/configs/{config_id}")
def update_config(config_id: str, body: LLMConfigUpdate):
    """Update an existing LLM model config."""
    updates = body.model_dump(exclude_none=True)
    if "api_key" in updates and not updates["api_key"]:
        del updates["api_key"]
    updated = _get_repo().update_config(config_id, updates)
    if updated is None:
        raise HTTPException(status_code=404, detail="Config not found")
    _get_manager().refresh()
    return _ok(_to_response(updated))


@router.delete("/configs/{config_id}")
def delete_config(config_id: str):
    """Delete an LLM model config."""
    deleted = _get_repo().delete_config(config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Config not found")
    _get_manager().refresh()
    return _ok({"deleted": True})


@router.put("/configs/{config_id}/default")
def set_default(config_id: str):
    """Set a config as the default model."""
    config = _get_repo().get_config(config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Config not found")
    _get_repo().set_default(config_id)
    _get_manager().refresh()
    return _ok({"id": config_id, "is_default": True})


@router.post("/test")
async def test_connection(body: LLMTestRequest):
    """Test LLM connection by sending a simple message."""
    config_id = body.config_id
    if config_id is None:
        default = _get_repo().get_default_config()
        if default is None:
            return _ok(LLMTestResponse(
                success=False,
                message="No default model configured. Please add and set a default model.",
            ))
        config_id = default.id

    result = await _get_manager().test_connection(config_id)
    return _ok(LLMTestResponse(
        success=result.success,
        message=result.message,
        latency_ms=result.latency_ms,
    ))
