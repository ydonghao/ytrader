"""季度财务聚合 job：把指数/行业的成分股财报聚合为整体财务指标。

按报告期聚合：
  revenue_sum / net_profit_sum / assets_sum = 成分股加总
  net_margin = Σ净利 / Σ营收
  roe = Σ净利 / Σ净资产（净资产加权）
  sample_count = 有效样本数

数据源：stock_financial_detail（成分股三大报表）。
成分股来源：national_team_symbol_sector（symbol → 申万行业名）。

注意：stock_financial_detail 的 detail JSONB 用带 * 前缀的核心指标 key：
  income 表：'*营业总收入'、'*净利润'
  balance 表：'*资产合计'、'*所有者权益（或股东权益）合计'
"""
import logging
import datetime as dt

import psycopg2

from src.infra.database.market.index_financial import (
    create_index_financial_repository,
)
from src.infra.database.market.national_team_holding import (
    NationalTeamSymbolSector,
)
from src.infra.database.sql_engine.engine import create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn
from sqlmodel import Session, select

log = logging.getLogger(__name__)


def _get_engine():
    """获取 SQLModel engine（供 Session 使用）。"""
    return create_db_connection(get_dsn())._engine


def _to_prefixed_symbol(code: str) -> str:
    """纯 6 位代码 → 带交易所前缀（sh/sz/bj），匹配 stock_financial_detail.symbol。

    national_team_symbol_sector 存纯数字（如 '000538'），需转成 'sz000538'。
    与 index_valuation_backfill 的转换逻辑一致。
    """
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


def _aggregate_sw_sector_financial(
    sector_name: str, sw_code: str,
) -> list[dict]:
    """聚合单个申万行业的季度财务。

    Returns:
        list[dict]，每条含 scope_type/scope_code/report_date/各聚合值。
    """
    # 取成分股（纯数字 → 带前缀）
    symbols: list[str] = []
    with Session(_get_engine()) as s:
        rows = s.exec(
            select(NationalTeamSymbolSector).where(
                NationalTeamSymbolSector.sector == sector_name
            )
        ).all()
        symbols = [_to_prefixed_symbol(r.symbol) for r in rows if r.symbol]

    if not symbols:
        return []

    conn = psycopg2.connect(get_dsn())
    out: list[dict] = []
    try:
        with conn.cursor() as cur:
            # 利润表：按报告期聚合营收/净利
            cur.execute(
                """
                SELECT report_date,
                       SUM(COALESCE((detail->>'*营业总收入')::numeric, 0)) AS rev,
                       SUM(COALESCE((detail->>'*净利润')::numeric, 0)) AS np,
                       COUNT(*) AS cnt
                FROM stock_financial_detail
                WHERE symbol = ANY(%s)
                  AND statement_type = 'income'
                GROUP BY report_date
                ORDER BY report_date
                """,
                (symbols,),
            )
            income_rows = cur.fetchall()

            # 资产负债表：按报告期聚合资产/权益
            cur.execute(
                """
                SELECT report_date,
                       SUM(COALESCE((detail->>'*资产合计')::numeric, 0)) AS assets,
                       SUM(COALESCE((detail->>'*所有者权益（或股东权益）合计')::numeric, 0)) AS equity,
                       COUNT(*) AS cnt
                FROM stock_financial_detail
                WHERE symbol = ANY(%s)
                  AND statement_type = 'balance'
                GROUP BY report_date
                ORDER BY report_date
                """,
                (symbols,),
            )
            balance_map = {
                r[0]: {
                    "assets": float(r[1] or 0),
                    "equity": float(r[2] or 0),
                    "cnt": r[3],
                }
                for r in cur.fetchall()
            }

            for rd, rev, np, cnt in income_rows:
                rev = float(rev or 0)
                np = float(np or 0)
                bal = balance_map.get(rd, {})
                equity = bal.get("equity", 0)
                roe = (np / equity * 100) if equity > 0 else None
                net_margin = (np / rev * 100) if rev > 0 else None
                out.append({
                    "scope_type": "sw",
                    "scope_code": sw_code,
                    "report_date": rd,
                    "roe": roe,
                    "net_margin": net_margin,
                    "revenue_sum": rev / 1e8,        # 转亿
                    "net_profit_sum": np / 1e8,
                    "assets_sum": bal.get("assets", 0) / 1e8,
                    "sample_count": cnt,
                })
    finally:
        conn.close()
    return out


def sync_sw_financial_quarterly() -> dict[str, int]:
    """同步全部申万一级行业的季度财务聚合。

    Returns:
        {sw_code: wrote_count}
    """
    from src.domain.market.sync.providers.akshare_provider import AkshareProvider
    prov = AkshareProvider()
    snapshot = prov.fetch_sw_index_valuation_snapshot()
    repo = create_index_financial_repository()
    results: dict[str, int] = {}
    for item in snapshot:
        sector = item.get("industry")
        sw_code = item.get("sw_code")
        if not sector or not sw_code:
            continue
        try:
            rows = _aggregate_sw_sector_financial(sector, sw_code)
            if rows:
                repo.bulk_upsert(rows)
            results[sw_code] = len(rows)
            log.info("[sync_sw_fin] %s: %d periods", sw_code, len(rows))
        except Exception as e:
            log.warning("[sync_sw_fin] %s failed: %s", sw_code, e)
            results[sw_code] = 0
    return results


def _aggregate_index_financial(index_code: str) -> list[dict]:
    """聚合单个宽基指数成分股的季度财务（**累计口径**，亿）。

    用固定列 revenue/net_profit_parent（sw 聚合走 detail JSONB 是历史
    口径；指数侧统一用固定列，net_profit 取归母口径）。
    """
    conn = psycopg2.connect(get_dsn())
    out: list[dict] = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT f.report_date,
                       SUM(COALESCE(f.revenue, 0)) AS rev,
                       SUM(COALESCE(f.net_profit_parent, 0)) AS np,
                       COUNT(f.revenue) AS cnt
                FROM stock_financial_detail f
                JOIN index_constituent c ON c.stock_symbol = f.symbol
                WHERE c.index_code = %s
                  AND f.statement_type = 'income'
                GROUP BY f.report_date
                ORDER BY f.report_date
                """,
                (index_code,),
            )
            for rd, rev, np_, cnt in cur.fetchall():
                out.append({
                    "scope_type": "index",
                    "scope_code": index_code,
                    "report_date": rd,
                    "revenue_sum": float(rev or 0) / 1e8,
                    "net_profit_sum": float(np_ or 0) / 1e8,
                    "sample_count": cnt,
                })
    finally:
        conn.close()
    return out


def sync_index_financial_quarterly() -> dict[str, int]:
    """同步全部配置宽基指数的季度财务聚合（全量重算幂等）。

    Returns: {index_code: wrote_count}
    """
    from conf import app_config
    items = app_config.quant_universe.index_constituents
    repo = create_index_financial_repository()
    results: dict[str, int] = {}
    for it in items:
        try:
            rows = _aggregate_index_financial(it.code)
            if rows:
                repo.bulk_upsert(rows)
            results[it.code] = len(rows)
            log.info("[sync_idx_fin] %s: %d periods", it.code, len(rows))
        except Exception as e:  # noqa: BLE001
            log.warning("[sync_idx_fin] %s failed: %s", it.code, e)
            results[it.code] = 0
    return results
