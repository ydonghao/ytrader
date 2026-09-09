"""国家队「实时全景」API handler — 新增端点(纯增量,不影响既有 handler)。

端点:
  GET /national-team/live/snapshot   持仓+实时行情+汇总+矩阵+洞察(实时全景页主体)
  GET /national-team/live/entities   6 大主体元数据(团队页)
  GET /national-team/live/kline      个股/ETF 前复权日K(详情弹窗蜡烛图)
  GET /national-team/etf/snapshot    ETF 实时 + 份额变动信号
  GET /national-team/etf/history     ETF 份额历史序列(折线/热力)
  GET /national-team/etf/signals     份额级异常申赎信号(独立于既有成交量信号)
"""
import time
from typing import Any

from src.pkg import responses

# ── 快照级缓存:全景页一次组装要批量取行情,盘口 60s 内复用,避免高频刷新打爆接口 ──
_SNAP_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
_SNAP_TTL = 60  # 秒
_ETF_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}


def _cached(getter, cache, ttl):
    now = time.time()
    if cache["data"] and now - cache["ts"] < ttl:
        return responses.success(cache["data"])
    try:
        data = getter()
        cache["data"] = data
        cache["ts"] = now
        return responses.success(data)
    except Exception as e:
        # 降级:取数失败时若有旧缓存,返回旧值保证展示连续性
        if cache["data"]:
            return responses.success(cache["data"])
        return responses.fail(f"获取实时全景失败: {e}")


def live_snapshot() -> Any:
    """实时全景快照(持仓+行情+汇总+矩阵+洞察)。"""
    from src.domain.market.nt_snapshot import build_snapshot
    return _cached(build_snapshot, _SNAP_CACHE, _SNAP_TTL)


def live_entities() -> Any:
    """6 大国家队主体元数据。"""
    from src.domain.market.sync.providers.national_team_config import get_entity_meta
    from src.domain.market.nt_snapshot import build_snapshot
    # 快照里的 entities 已含「是否有持仓 + 总市值」,优先用;否则降级到纯元数据
    if _SNAP_CACHE["data"] and "national_team_entities" in (_SNAP_CACHE["data"] or {}):
        return responses.success({
            "entities": _SNAP_CACHE["data"]["national_team_entities"],
            "team_summary": _SNAP_CACHE["data"].get("team_summary", []),
        })
    snap = build_snapshot()
    return responses.success({
        "entities": snap["national_team_entities"],
        "team_summary": snap["team_summary"],
    })


def live_kline(symbol: str, days: int = 30) -> Any:
    """个股/ETF 前复权日K(详情弹窗蜡烛图)。symbol=6位代码。"""
    from src.domain.market.nt_snapshot import kline_for
    if not symbol:
        return responses.fail("symbol 不能为空")
    days = max(5, min(days, 250))
    return responses.success({"symbol": symbol, "days": days, "kline": kline_for(symbol, days)})


def etf_snapshot() -> Any:
    """ETF 实时 + 份额变动信号 + 汇金占比。"""
    from src.domain.market.nt_snapshot import build_etf_snapshot
    return _cached(build_etf_snapshot, _ETF_CACHE, _SNAP_TTL)


def etf_history(etf_code: str = None, days: int = 90) -> Any:
    """ETF 份额历史序列(单只或全部)。全部时返回 {dates, cells} 供热力图。"""
    from src.infra.database.market.national_team_etf_shares import (
        create_etf_shares_repository,
    )
    from src.domain.market.sync.providers.national_team_config import get_etf_first_holders
    repo = create_etf_shares_repository()
    if etf_code:
        return responses.success({
            "etf_code": etf_code,
            "history": repo.get_history(etf_code, days),
        })
    # 全部:组装 dates × etf → shares_yi 热力结构
    etfs = get_etf_first_holders()
    dates = repo.get_all_latest_dates(days)
    cells: dict[str, dict[str, float]] = {}
    for e in etfs:
        hist = repo.get_history(e["code"], days)
        cells[e["code"]] = {h["trade_date"]: round(h["shares"] / 1e8, 2) for h in hist}
    return responses.success({"dates": dates, "cells": cells, "coverage": repo.coverage_info()})


def etf_signals() -> Any:
    """份额级异常申赎信号(与既有「成交量护盘信号」互补,口径不同)。"""
    data = _ETF_CACHE["data"]
    if not data or (time.time() - _ETF_CACHE["ts"] > _SNAP_TTL):
        from src.domain.market.nt_snapshot import build_etf_snapshot
        data = build_etf_snapshot()
        _ETF_CACHE["data"] = data
        _ETF_CACHE["ts"] = time.time()
    return responses.success({
        "signals": data.get("signals", []),
        "total_value_yi": data.get("total_value_yi", 0),
        "coverage": data.get("coverage", ""),
    })
