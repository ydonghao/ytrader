"""Request/response models for Skill definition API."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel


class SkillCreate(BaseModel):
    name: str
    display_name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    output_schema: dict[str, Any] = {}
    is_active: bool = True


class SkillUpdate(BaseModel):
    name: str | None = None
    display_name: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] | None = None
    steps: list[dict[str, Any]] | None = None
    output_schema: dict[str, Any] | None = None
    is_active: bool | None = None


class SkillResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    steps: list[dict[str, Any]]
    output_schema: dict[str, Any]
    is_active: bool
    created_at: str | None = None
    updated_at: str | None = None


class SkillExecuteRequest(BaseModel):
    input_params: dict[str, Any] = {}


class SkillExecuteResponse(BaseModel):
    success: bool
    outputs: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    duration_ms: float = 0.0


class SkillValidateResponse(BaseModel):
    valid: bool
    errors: list[str] = []
