"""自选股(分组) API handler。

遵循项目约定:
- repository 在函数体内延迟 import + 工厂创建
- 返回 responses.success(data) / responses.fail(msg=...)
"""
from typing import Any

from src.pkg import responses


def _repo():
    from src.infra.database.watchlist.repository import (
        create_watchlist_repository,
    )
    return create_watchlist_repository()


def _group_dict(g, item_count: int = 0) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "sort_index": g.sort_index,
        "item_count": item_count,
    }


def _item_dict(it) -> dict:
    return {
        "id": it.id,
        "group_id": it.group_id,
        "symbol": it.symbol,
        "note": it.note,
        "sort_index": it.sort_index,
    }


# ── 分组 ──

def list_groups() -> Any:
    repo = _repo()
    groups = repo.list_groups()
    counts = repo.count_items_by_group()
    return responses.success(
        [_group_dict(g, counts.get(g.id, 0)) for g in groups]
    )


def create_group(body: dict) -> Any:
    name = (body.get("name") or "").strip()
    if not name:
        return responses.fail(msg="缺少 name")
    repo = _repo()
    if any(g.name == name for g in repo.list_groups()):
        return responses.fail(msg="分组名已存在")
    g = repo.create_group(name=name)
    return responses.success(_group_dict(g, 0))


def update_group(group_id: int, body: dict) -> Any:
    name = (body.get("name") or "").strip()
    if not name:
        return responses.fail(msg="缺少 name")
    repo = _repo()
    if any(g.id != group_id and g.name == name for g in repo.list_groups()):
        return responses.fail(msg="分组名已存在")
    g = repo.rename_group(group_id, name)
    if not g:
        return responses.fail(msg="分组不存在")
    counts = repo.count_items_by_group()
    return responses.success(_group_dict(g, counts.get(g.id, 0)))


def delete_group(group_id: int) -> Any:
    repo = _repo()
    repo.delete_group(group_id)
    return responses.success({"id": group_id, "deleted": True})


def reorder_groups(body: dict) -> Any:
    ids = body.get("ids") or []
    if not isinstance(ids, list):
        return responses.fail(msg="ids 必须为数组")
    repo = _repo()
    repo.reorder_groups([int(i) for i in ids])
    return responses.success({"ids": ids})


# ── 成员 ──

def list_items(group_id: int) -> Any:
    repo = _repo()
    return responses.success([_item_dict(it) for it in repo.list_items(group_id)])


def add_item(group_id: int, body: dict) -> Any:
    symbol = (body.get("symbol") or "").strip()
    if not symbol:
        return responses.fail(msg="缺少 symbol")
    note = (body.get("note") or "").strip() or None
    repo = _repo()
    if repo.get_group(group_id) is None:
        return responses.fail(msg="分组不存在")
    from src.infra.database.watchlist.repository import DuplicateWatchlistItem
    try:
        it = repo.add_item(group_id=group_id, symbol=symbol, note=note)
    except DuplicateWatchlistItem:
        return responses.fail(msg="该股票已在分组内")
    return responses.success(_item_dict(it))


def delete_item(item_id: int) -> Any:
    repo = _repo()
    ok = repo.delete_item(item_id)
    if not ok:
        return responses.fail(msg="成员不存在")
    return responses.success({"id": item_id, "deleted": True})


def update_item(item_id: int, body: dict) -> Any:
    note = body.get("note")
    note = note.strip() if isinstance(note, str) else note
    repo = _repo()
    it = repo.update_item_note(item_id, note if note else None)
    if not it:
        return responses.fail(msg="成员不存在")
    return responses.success(_item_dict(it))


def reorder_items(group_id: int, body: dict) -> Any:
    ids = body.get("ids") or []
    if not isinstance(ids, list):
        return responses.fail(msg="ids 必须为数组")
    repo = _repo()
    repo.reorder_items(group_id, [int(i) for i in ids])
    return responses.success({"ids": ids})


def move_item(body: dict) -> Any:
    item_id = body.get("item_id")
    to_group_id = body.get("to_group_id")
    if item_id is None or to_group_id is None:
        return responses.fail(msg="缺少 item_id 或 to_group_id")
    sort_index = body.get("sort_index")
    repo = _repo()
    from src.infra.database.watchlist.repository import DuplicateWatchlistItem
    try:
        it = repo.move_item(
            int(item_id),
            int(to_group_id),
            int(sort_index) if sort_index is not None else None,
        )
    except DuplicateWatchlistItem:
        return responses.fail(msg="目标分组已存在该股票")
    if not it:
        return responses.fail(msg="成员不存在")
    return responses.success(_item_dict(it))
