"""一次性历史回填 job：用成分股估值加权自算指数/行业估值历史。

akshare 的 sw_index_first_info 只有当天快照、无历史。
本 job 用当前成分股的 stock_valuation 日线，按总市值加权自算
PE/PB 等的历史日线，回填到 sw_index_valuation_daily / index_valuation_daily，
source='computed'。

口径：用"当前成分股"近似历史成分（标注 source=computed）。
  PE_TTM = Σ(total_mv) / Σ(total_mv / pe_ttm)   （调和加权，避免负值放大）
  PB     = Σ(total_mv) / Σ(total_mv / pb)

成分股来源：national_team_symbol_sector（symbol → 申万行业名）。
注意：该表只覆盖国家队曾持仓的股票，并非全行业成分股，但作为近似可用。
"""
import logging
import datetime as dt
from typing import Optional

from src.infra.database.market.valuation import (
    create_stock_valuation_repository,
)
from src.infra.database.market.index_valuation import (
    create_index_valuation_repository,
)
from src.infra.database.market.national_team_holding import (
    NationalTeamSymbolSector,
)
from src.infra.database.sql_engine.engine import create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn
from sqlmodel import Session, select


def _get_engine():
    """获取 SQLModel engine（供 Session 使用）。"""
    return create_db_connection(get_dsn())._engine

log = logging.getLogger(__name__)


def _to_prefixed_symbol(code: str) -> str:
    """纯 6 位代码 → 带交易所前缀（sh/sz/bj），匹配 stock_valuation.symbol 格式。

    与 national_team_handler.py 的转换逻辑一致。
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


def _load_sw_sector_symbols() -> dict[str, list[str]]:
    """从 national_team_symbol_sector 加载 申万行业名→[symbol]。

    national_team_symbol_sector 存纯 6 位代码（如 '000538'），
    需转成带前缀格式（如 'sz000538'）匹配 stock_valuation。

    Returns:
        {sector_name: [sh600519, sz000001, ...]}
    """
    out: dict[str, list[str]] = {}
    with Session(_get_engine()) as s:
        rows = s.exec(select(NationalTeamSymbolSector)).all()
        for r in rows:
            if r.sector and r.symbol:
                out.setdefault(r.sector, []).append(_to_prefixed_symbol(r.symbol))
    return out


def _pick_as_of(rows: list, trade_date: dt.date):
    """从升序 rows 中取 <= trade_date 的最近一行。"""
    row = None
    for r in rows:
        if r.trade_date <= trade_date:
            row = r
        else:
            break
    return row


def _compute_weighted_pe(rows_by_symbol: dict[str, list], trade_date: dt.date) -> Optional[float]:
    """市值加权 PE_TTM（调和加权）。样本不足返回 None。"""
    mv_sum = 0.0
    pe_weighted_sum = 0.0
    for rows in rows_by_symbol.values():
        row = _pick_as_of(rows, trade_date)
        if row is None or row.pe_ttm is None or row.pe_ttm <= 0:
            continue
        if row.total_mv is None or row.total_mv <= 0:
            continue
        mv_sum += row.total_mv
        pe_weighted_sum += row.total_mv / row.pe_ttm
    if mv_sum <= 0 or pe_weighted_sum <= 0:
        return None
    return mv_sum / pe_weighted_sum


def _compute_weighted_pb(rows_by_symbol: dict[str, list], trade_date: dt.date) -> Optional[float]:
    mv_sum = 0.0
    pb_weighted_sum = 0.0
    for rows in rows_by_symbol.values():
        row = _pick_as_of(rows, trade_date)
        if row is None or row.pb is None or row.pb <= 0:
            continue
        if row.total_mv is None or row.total_mv <= 0:
            continue
        mv_sum += row.total_mv
        pb_weighted_sum += row.total_mv / row.pb
    if mv_sum <= 0 or pb_weighted_sum <= 0:
        return None
    return mv_sum / pb_weighted_sum


def backfill_sw_valuation_by_sector_name(
    sector_name: str,
    sw_code: str,
    years: int = 10,
) -> int:
    """回填单个申万行业的估值历史（成分股加权自算）。

    Args:
        sector_name: 申万行业名称（如 '银行'）
        sw_code:     sw801780
        years:       回填年数

    Returns:
        写入条数。
    """
    sector_map = _load_sw_sector_symbols()
    symbols = sector_map.get(sector_name, [])
    if not symbols:
        log.warning("[backfill_sw] no symbols for sector %s", sector_name)
        return 0

    val_repo = create_stock_valuation_repository()
    idx_repo = create_index_valuation_repository()

    end = dt.date.today()
    start = dt.date(end.year - years, end.month, end.day)

    # 批量拉每个 symbol 的估值区间
    rows_by_symbol: dict[str, list] = {}
    for sym in symbols:
        try:
            rows_by_symbol[sym] = val_repo.get_range(sym, start, end)
        except Exception as e:
            log.debug("[backfill_sw] %s get_range failed: %s", sym, e)

    if not rows_by_symbol:
        return 0

    # 收集所有交易日期，按月采样降频以控制写入量
    all_dates: set[dt.date] = set()
    for rows in rows_by_symbol.values():
        for r in rows:
            all_dates.add(r.trade_date)

    month_last: dict[str, dt.date] = {}
    for d in sorted(all_dates):
        month_last[d.strftime("%Y-%m")] = d
    sample_dates = sorted(month_last.values())

    bulk_rows = []
    for d in sample_dates:
        pe = _compute_weighted_pe(rows_by_symbol, d)
        pb = _compute_weighted_pb(rows_by_symbol, d)
        if pe is None and pb is None:
            continue
        bulk_rows.append({
            "sw_code": sw_code, "trade_date": d,
            "pe_ttm": pe, "pb": pb,
            "source": "computed",
        })

    if bulk_rows:
        idx_repo.bulk_upsert_sw(bulk_rows)
    log.info(
        "[backfill_sw] %s(%s): wrote %d monthly points",
        sector_name, sw_code, len(bulk_rows),
    )
    return len(bulk_rows)


def backfill_all_sw_valuation(years: int = 10) -> dict[str, int]:
    """回填全部申万一级行业的估值历史。

    申万行业名→sw_code 映射从 akshare 当天快照取。
    Returns: {sw_code: wrote_count}
    """
    from src.domain.market.sync.providers.akshare_provider import AkshareProvider
    prov = AkshareProvider()
    snapshot = prov.fetch_sw_index_valuation_snapshot()
    results: dict[str, int] = {}
    for item in snapshot:
        sector = item.get("industry")
        sw_code = item.get("sw_code")
        if not sector or not sw_code:
            continue
        try:
            n = backfill_sw_valuation_by_sector_name(sector, sw_code, years)
            results[sw_code] = n
        except Exception as e:
            log.warning("[backfill_all_sw] %s failed: %s", sw_code, e)
            results[sw_code] = 0
    return results
