"""自定义看板 API handler。

遵循项目约定:
- repository 在函数体内延迟 import + 工厂创建
- 返回 responses.success(data) / responses.fail(msg=...)
"""
from typing import Any

from src.pkg import responses


def _repo():
    from src.infra.database.board.repository import (
        create_analysis_board_repository,
    )
    return create_analysis_board_repository()


def _board_dict(b, include_layout: bool = False) -> dict:
    d = {
        "id": b.id,
        "name": b.name,
        "sort_index": b.sort_index,
        "updated_at": b.updated_at.isoformat() if b.updated_at else None,
    }
    if include_layout:
        d["layout"] = b.layout
    return d


# 空板初值(与前端 boardTypes.ts EMPTY_LAYOUT 同构)
EMPTY_LAYOUT = {
    "version": 1,
    "timeRange": {"preset": "1y", "start": None, "end": None},
    "maxZ": 0,
    "cards": [],
}


def list_boards() -> Any:
    return responses.success([_board_dict(b) for b in _repo().list_boards()])


def create_board(body: dict) -> Any:
    name = (body.get("name") or "").strip()
    if not name:
        return responses.fail(msg="缺少 name")
    repo = _repo()
    if any(b.name == name for b in repo.list_boards()):
        return responses.fail(msg="看板名已存在")
    b = repo.create_board(name=name, layout=EMPTY_LAYOUT)
    return responses.success(_board_dict(b, include_layout=True))


def get_board(board_id: int) -> Any:
    b = _repo().get_board(board_id)
    if not b:
        return responses.fail(msg="看板不存在")
    return responses.success(_board_dict(b, include_layout=True))


def update_board(board_id: int, body: dict) -> Any:
    repo = _repo()
    name = body.get("name")
    if isinstance(name, str):
        name = name.strip()
        if not name:
            return responses.fail(msg="name 不能为空")
        if any(
            b.id != board_id and b.name == name
            for b in repo.list_boards()
        ):
            return responses.fail(msg="看板名已存在")
    else:
        name = None
    layout = body.get("layout")
    if layout is not None and not isinstance(layout, dict):
        return responses.fail(msg="layout 格式错误")
    b = repo.update_board(board_id, name=name, layout=layout)
    if not b:
        return responses.fail(msg="看板不存在")
    return responses.success(_board_dict(b, include_layout=True))


def delete_board(board_id: int) -> Any:
    ok = _repo().delete_board(board_id)
    if not ok:
        return responses.fail(msg="看板不存在")
    return responses.success({"id": board_id, "deleted": True})
