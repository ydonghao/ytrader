"""
Settings Router
===============
GET  /settings            → list all app settings
PUT  /settings/feishu_open_id → save the user's Feishu open_id
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.infra.notification.feishu import (
    set_user_open_id,
    _ensure_settings_table,
    _get_user_open_id,
)

router = APIRouter(prefix="/settings", tags=["settings"])
log = logging.getLogger(__name__)


class FeishuOpenIdRequest(BaseModel):
    open_id: str


@router.get("")
def get_settings():
    """Return all app settings (non-secret ones)."""
    _ensure_settings_table()
    open_id = _get_user_open_id()
    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "feishu_user_open_id": open_id or "",
        },
    }


@router.put("/feishu_open_id")
def save_feishu_open_id(body: FeishuOpenIdRequest):
    """Save the user's Feishu open_id for notifications."""
    if not body.open_id or not body.open_id.strip():
        raise HTTPException(status_code=400, detail="open_id cannot be empty")
    ok = set_user_open_id(body.open_id.strip())
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save setting")
    return {"code": 0, "msg": "ok", "data": {"feishu_user_open_id": body.open_id.strip()}}
