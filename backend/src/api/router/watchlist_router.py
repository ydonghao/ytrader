"""自选股(分组) API — 分组管理 + 组内成员管理。"""
from fastapi import APIRouter

from src.api.handler.watchlist_handler import (
    add_item,
    create_group,
    delete_group,
    delete_item,
    list_groups,
    list_items,
    move_item,
    reorder_groups,
    reorder_items,
    update_group,
    update_item,
)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("/groups")
def _list_groups():
    return list_groups()


@router.post("/groups")
def _create_group(body: dict):
    return create_group(body)


# 注意: /groups/order 必须在 /groups/{group_id} 之前声明
@router.put("/groups/order")
def _reorder_groups(body: dict):
    return reorder_groups(body)


@router.put("/groups/{group_id}")
def _update_group(group_id: int, body: dict):
    return update_group(group_id, body)


@router.delete("/groups/{group_id}")
def _delete_group(group_id: int):
    return delete_group(group_id)


@router.get("/groups/{group_id}/items")
def _list_items(group_id: int):
    return list_items(group_id)


@router.post("/groups/{group_id}/items")
def _add_item(group_id: int, body: dict):
    return add_item(group_id, body)


@router.put("/groups/{group_id}/items/order")
def _reorder_items(group_id: int, body: dict):
    return reorder_items(group_id, body)


@router.delete("/items/{item_id}")
def _delete_item(item_id: int):
    return delete_item(item_id)


@router.put("/items/{item_id}")
def _update_item(item_id: int, body: dict):
    return update_item(item_id, body)


@router.post("/items/move")
def _move_item(body: dict):
    return move_item(body)
