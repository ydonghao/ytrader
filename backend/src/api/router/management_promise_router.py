"""管理层言行追踪路由（2026-10 言行追踪 V1）。"""
from typing import Any, Optional

from fastapi import APIRouter, Body

from src.api.handler.management_promise_handler import (
    add_promise,
    delete_promise,
    import_annual_reports,
    import_forecasts,
    list_promises,
    verify_promise,
)

router = APIRouter(prefix="/management-promises", tags=["management"])


@router.get("/{symbol}")
def get_promises(symbol: str) -> Any:
    """承诺列表 + 信用档案（兑现率）。"""
    return list_promises(symbol)


@router.post("/{symbol}")
def post_promise(symbol: str, payload: dict = Body(...)) -> Any:
    """手动录入一条承诺（指引/资本开支/分红/回购/增持）。"""
    return add_promise({**payload, "symbol": symbol})


@router.post("/{symbol}/import-forecasts")
def post_import_forecasts(symbol: str) -> Any:
    """从业绩预告自动导入承诺并按财报实际值判兑现（幂等）。"""
    return import_forecasts(symbol)


@router.post("/{symbol}/import-annual-reports")
async def post_import_annual_reports(symbol: str,
                                     payload: dict = Body(...)) -> Any:
    """年报 MD&A 承诺抽取（V2）：PDF→MD&A 切片→LLM 抽承诺，人工验证。"""
    return await import_annual_reports(symbol, payload)


@router.post("/{row_id}/verify")
def post_verify(row_id: int, payload: dict = Body(...)) -> Any:
    """人工验证承诺兑现情况。"""
    return verify_promise(row_id, payload)


@router.delete("/{row_id}")
def del_promise(row_id: int) -> Any:
    """删除一条承诺。"""
    return delete_promise(row_id)
