"""买入体检路由(课程21集检查清单)。"""
from typing import Any

from fastapi import APIRouter, Body

from src.api.handler.checklist_handler import (
    checklist_report,
    save_checklist_items,
)

router = APIRouter(prefix="/checklist", tags=["checklist"])


@router.get("/{symbol}")
def get_checklist(symbol: str) -> Any:
    """四区21项聚合(自动12+手动9;只展示不下结论)。"""
    return checklist_report(symbol)


@router.put("/{symbol}/items")
def put_checklist_items(symbol: str, payload: dict = Body(...)) -> Any:
    """批量保存手动项;空值=清除该项(回到待填)。"""
    return save_checklist_items(symbol, payload)
