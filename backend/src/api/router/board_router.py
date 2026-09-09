"""自定义看板 API — 多看板 CRUD,布局 JSON 整存整取。"""
from fastapi import APIRouter

from src.api.handler.board_handler import (
    create_board,
    delete_board,
    get_board,
    list_boards,
    update_board,
)

router = APIRouter(prefix="/board", tags=["board"])


@router.get("/boards")
def _list_boards():
    return list_boards()


@router.post("/boards")
def _create_board(body: dict):
    return create_board(body)


@router.get("/boards/{board_id}")
def _get_board(board_id: int):
    return get_board(board_id)


@router.put("/boards/{board_id}")
def _update_board(board_id: int, body: dict):
    return update_board(board_id, body)


@router.delete("/boards/{board_id}")
def _delete_board(board_id: int):
    return delete_board(board_id)
