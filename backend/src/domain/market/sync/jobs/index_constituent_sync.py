"""宽基指数成分股同步 job：csindex 最新成分 → index_constituent 全量重灌。

数据源 akshare index_stock_cons_weight_csindex（中证指数官网，含权重，
只有最新快照——历史成分近似由下游 source='computed' 标注）。
指数清单来自 conf quant_universe.index_constituents。
单指数失败跳过（warning），不阻塞其他指数。
"""
import logging
import time
import datetime as dt

import akshare as ak
import pandas as pd

from src.infra.database.market.index_constituent import (
    create_index_constituent_repository,
)

log = logging.getLogger(__name__)


def _to_prefixed(code: str) -> str:
    """纯 6 位代码 → sh/sz/bj 前缀（与 index_valuation_backfill 同款）。"""
    c = code.strip()
    if c.startswith(("sh", "sz", "bj")):
        return c
    if c.startswith("6"):
        return f"sh{c}"
    if c.startswith(("0", "3")):
        return f"sz{c}"
    if c.startswith(("8", "4")):
        return f"bj{c}"
    return c


def _build_rows(index_code: str, df: pd.DataFrame) -> list[dict]:
    """csindex 成分 DataFrame → member 行（纯转换，权重缺失容忍 None）。"""
    rows: list[dict] = []
    as_of = None
    if not df.empty and "日期" in df.columns:
        v = df.iloc[0]["日期"]
        s = v.isoformat() if hasattr(v, "isoformat") else str(v)
        try:
            as_of = dt.date.fromisoformat(s[:10])
        except ValueError:
            as_of = None
    for _, r in df.iterrows():
        w = r.get("权重")
        rows.append({
            "index_code": index_code,
            "stock_symbol": _to_prefixed(str(r["成分券代码"])),
            "stock_name": r.get("成分券名称"),
            "weight": float(w) if pd.notna(w) else None,
            "as_of_date": as_of,
        })
    return rows


def run(interval: float = 0.5) -> dict[str, int]:
    """同步全部配置指数的成分。Returns {index_code: wrote_count}。"""
    from conf import app_config
    items = app_config.quant_universe.index_constituents
    repo = create_index_constituent_repository()
    results: dict[str, int] = {}
    for it in items:
        try:
            df = ak.index_stock_cons_weight_csindex(symbol=it.code)
            rows = _build_rows(it.code, df)
            wrote = repo.replace_members(it.code, rows)
            results[it.code] = wrote
            log.info("[idx_cons] %s: %d members", it.code, wrote)
        except Exception as e:  # noqa: BLE001
            log.warning("[idx_cons] %s failed: %s", it.code, e)
            results[it.code] = 0
        finally:
            time.sleep(interval)
    return results
