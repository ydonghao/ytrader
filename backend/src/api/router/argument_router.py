"""AI 陪练论证库路由（2026-10 六层第⑥件）。"""
from typing import Any

from fastapi import APIRouter, Body

from src.api.handler.argument_handler import (
    add_manual_argument,
    archive_argument,
    delete_argument,
    generate_argument,
    list_arguments,
    update_argument,
)

router = APIRouter(prefix="/arguments", tags=["arguments"])


@router.get("/{symbol}")
def get_arguments(symbol: str) -> Any:
    """论证列表（draft 优先 + archived 历史）。"""
    return list_arguments(symbol)


@router.post("/{symbol}")
def post_argument(symbol: str, payload: dict = Body(...)) -> Any:
    """手动归档一条自己写的论证。"""
    return add_manual_argument({**payload, "symbol": symbol})


@router.post("/{symbol}/generate")
async def post_generate(symbol: str, payload: dict = Body(...)) -> Any:
    """用库内真实数据生成 bull/bear 初稿（覆盖旧草稿）。"""
    return await generate_argument(symbol, payload)


@router.put("/{row_id}")
def put_argument(row_id: int, payload: dict = Body(...)) -> Any:
    """编辑论证内容/核实依据。"""
    return update_argument(row_id, payload)


@router.post("/{row_id}/archive")
def post_archive(row_id: int, payload: dict = Body(...)) -> Any:
    """验证归档——进入该公司正式论证库。"""
    return archive_argument(row_id, payload)


@router.delete("/{row_id}")
def del_argument(row_id: int) -> Any:
    """删除一条论证。"""
    return delete_argument(row_id)
