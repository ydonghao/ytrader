"""时光机模拟驾驶舱 API — 会话存档 + as-of 行情切片。"""

from fastapi import APIRouter, Query

from src.api.handler import replay_handler as h

router = APIRouter(prefix="/replay", tags=["replay"])


@router.post("/sessions")
def _create_session(body: dict):
    return h.create_session(body)


@router.get("/sessions")
def _list_sessions():
    return h.list_sessions()


@router.get("/sessions/{session_id}")
def _get_session(session_id: int):
    return h.get_session(session_id)


@router.put("/sessions/{session_id}/state")
def _save_state(session_id: int, body: dict):
    return h.save_state(session_id, body)


@router.post("/sessions/{session_id}/reveal")
def _reveal(session_id: int):
    return h.reveal(session_id)


@router.delete("/sessions/{session_id}")
def _delete_session(session_id: int):
    return h.delete_session(session_id)


@router.post("/sessions/{session_id}/trades")
def _add_trade(session_id: int, body: dict):
    return h.add_trade(session_id, body)


@router.get("/sessions/{session_id}/trades")
def _list_trades(session_id: int):
    return h.list_trades(session_id)


@router.get("/kline/{symbol}")
def _kline(symbol: str, asof: str = Query(...), limit: int = Query(300)):
    return h.kline(symbol, asof, limit)


@router.get("/advance")
def _advance(session_id: int = Query(...), days: int = Query(1),
             step: str = Query(None)):
    return h.advance(session_id, days, step)


@router.get("/valuation/{symbol}")
def _valuation(symbol: str, asof: str = Query(...)):
    return h.valuation(symbol, asof)


@router.get("/board")
def _board(
    asof: str = Query(...),
    type: str = Query("gainers"),
    limit: int = Query(50),
):
    return h.board(asof, type, limit)


@router.get("/instrument/{symbol}")
def _instrument(symbol: str):
    return h.instrument(symbol)


@router.get("/news")
def _news(
    asof: str = Query(...),
    days: int = Query(3),
    limit: int = Query(20),
):
    return h.news(asof, days, limit)


@router.get("/sessions/{session_id}/view")
def _view(session_id: int):
    return h.view(session_id)


@router.post("/sessions/{session_id}/pool")
def _add_pool(session_id: int, body: dict):
    return h.add_pool(session_id, body)


@router.post("/sessions/{session_id}/orders")
def _orders(session_id: int, body: dict):
    return h.place_order(session_id, body)


@router.get("/leaderboard")
def _leaderboard():
    return h.leaderboard()


@router.get("/training-log")
def _training_log():
    return h.training_log()
