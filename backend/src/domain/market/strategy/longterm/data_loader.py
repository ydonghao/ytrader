"""
长期策略 / 选股器共享数据加载
================================
批量从 DB 拉估值/财务/日线快照，供选股器和回测共用。

关键优化：全市场选股（~5000 标的）时，用单条 SQL + DISTINCT ON 一次往返
取所有标的的最新快照，而非逐 symbol 循环（5000 次往返）。

点-in-time 规则（与 value_utils 一致）：
  - 估值：trade_date <= as_of 的最新（日频，无披露滞后）
  - 财务：report_date <= as_of - 60 天 的最新（财报披露滞后）
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from src.infra.database.sql_engine.dsn import get_dsn

log = logging.getLogger(__name__)

# 与 value_utils.FINANCIAL_LAG_DAYS 保持一致
FINANCIAL_LAG_DAYS = 60


def _get_conn():
    return psycopg2.connect(get_dsn())


def _as_date(d) -> Optional[date]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return d


def fetch_latest_valuations(
    symbols: list[str],
    as_of: Optional[date] = None,
) -> dict[str, dict]:
    """
    批量拉所有标的在 as_of（默认今天）的最新估值快照。

    Returns:
        {symbol: {trade_date, pe, pe_ttm, pb, ps, ps_ttm, dv_ratio, dv_ttm, total_mv}}
        无数据的标的不出现在结果里。
    """
    if not symbols:
        return {}
    as_of = as_of or date.today()
    out: dict[str, dict] = {}
    try:
        conn = _get_conn()
    except Exception:
        return out
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # DISTINCT ON (symbol) 取每组 trade_date 最大的行
            cur.execute(
                """
                SELECT DISTINCT ON (symbol)
                    symbol, trade_date, pe, pe_ttm, pb, ps, ps_ttm,
                    dv_ratio, dv_ttm, total_mv
                FROM stock_valuation
                WHERE symbol = ANY(%s) AND trade_date <= %s
                ORDER BY symbol, trade_date DESC
                """,
                (list(symbols), as_of),
            )
            for r in cur.fetchall():
                out[r["symbol"]] = {
                    "trade_date": _as_date(r["trade_date"]),
                    "pe": r.get("pe"),
                    "pe_ttm": r.get("pe_ttm"),
                    "pb": r.get("pb"),
                    "ps": r.get("ps"),
                    "ps_ttm": r.get("ps_ttm"),
                    "dv_ratio": r.get("dv_ratio"),
                    "dv_ttm": r.get("dv_ttm"),
                    "total_mv": r.get("total_mv"),
                }
    except Exception as e:
        log.warning(f"fetch_latest_valuations 失败: {e}")
    finally:
        conn.close()
    return out


def fetch_latest_financials(
    symbols: list[str],
    as_of: Optional[date] = None,
    lag_days: int = FINANCIAL_LAG_DAYS,
) -> dict[str, dict]:
    """
    批量拉所有标的在 as_of 时点已披露的最新财报（预留 lag_days 披露滞后）。

    Returns:
        {symbol: {report_date, roe_weighted, roe_diluted, gross_margin, net_margin, debt_ratio}}
    """
    if not symbols:
        return {}
    as_of = as_of or date.today()
    cutoff = as_of - __import__("datetime").timedelta(days=lag_days)
    out: dict[str, dict] = {}
    try:
        conn = _get_conn()
    except Exception:
        return out
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (symbol)
                    symbol, report_date, roe_weighted, roe_diluted,
                    gross_margin, net_margin, debt_ratio
                FROM stock_financials
                WHERE symbol = ANY(%s) AND report_date <= %s
                ORDER BY symbol, report_date DESC
                """,
                (list(symbols), cutoff),
            )
            for r in cur.fetchall():
                out[r["symbol"]] = {
                    "report_date": _as_date(r["report_date"]),
                    "roe_weighted": r.get("roe_weighted"),
                    "roe_diluted": r.get("roe_diluted"),
                    "gross_margin": r.get("gross_margin"),
                    "net_margin": r.get("net_margin"),
                    "debt_ratio": r.get("debt_ratio"),
                }
    except Exception as e:
        log.warning(f"fetch_latest_financials 失败: {e}")
    finally:
        conn.close()
    return out


def fetch_latest_financial_detail(
    symbols: list[str],
    as_of: Optional[date] = None,
    lag_days: int = FINANCIAL_LAG_DAYS,
) -> dict[str, dict]:
    """
    批量取每个标的最新三大报表合并快照（income+balance+cashflow），
    供衍生指标（ROIC/EBIT/EV/FCF Yield/ROA）计算。

    point-in-time：report_date <= as_of - lag_days（财报披露滞后）。
    每个 symbol 取每个 statement_type 的最新一期，Python 层合并三行。

    Returns:
        {symbol: {report_date, operating_profit, net_profit, total_assets,
                  total_liabilities, equity, short_loan, long_loan,
                  monetary_funds, ocf, capex, free_cash_flow}}
        无数据的标的不出现。
    """
    if not symbols:
        return {}
    as_of = as_of or date.today()
    cutoff = as_of - __import__("datetime").timedelta(days=lag_days)
    out: dict[str, dict] = {}
    try:
        conn = _get_conn()
    except Exception:
        return out
    fields = (
        "operating_profit", "net_profit", "total_assets",
        "total_liabilities", "equity", "short_loan", "long_loan",
        "monetary_funds", "ocf", "capex", "free_cash_flow",
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM (
                    SELECT DISTINCT ON (symbol, statement_type)
                        symbol, statement_type, report_date,
                        operating_profit, net_profit, total_assets,
                        total_liabilities, equity, short_loan, long_loan,
                        monetary_funds, ocf, capex, free_cash_flow
                    FROM stock_financial_detail
                    WHERE symbol = ANY(%s) AND report_date <= %s
                    ORDER BY symbol, statement_type, report_date DESC
                ) t
                """,
                (list(symbols), cutoff),
            )
            for r in cur.fetchall():
                sym = r["symbol"]
                d = out.setdefault(
                    sym, {"report_date": _as_date(r["report_date"])}
                )
                for k in fields:
                    v = r.get(k)
                    if v is not None:
                        d[k] = v
    except Exception as e:
        log.warning(f"fetch_latest_financial_detail 失败: {e}")
    finally:
        conn.close()
    return out


# ── 财务质量诊断快照（供 fundamental/quality.compute_quality_report）──────────
# 覆盖 quality.py 所需的固定列。注意：不含 capex/free_cash_flow——部分库未建这两列
# （ensure_stock_financial_detail_columns 才补），且 quality.py 不消费它们（用 ocf/icf/fcf）。
_SNAPSHOT_FIELDS = (
    "revenue", "operating_cost", "gross_profit",
    "sell_expense", "admin_expense", "rd_expense", "fin_expense",
    "operating_profit", "net_profit",
    "monetary_funds", "accounts_receivable", "inventory",
    "fixed_assets", "goodwill", "total_assets", "total_liabilities",
    "equity", "short_loan", "long_loan",
    "ocf", "icf", "fcf",
    "gross_margin", "net_margin", "debt_ratio",
)

# detail JSONB 科目 → 规范英文键（多候选中文科目名兼容 akshare 列名差异）。
# 这些科目不在固定列里，需从 detail JSONB 抽取，供 cash_to_revenue / 完整版
# liability_split / asset_heaviness / ar_vs_cash / cash_coverage 使用。
_DETAIL_SUBJECT_MAP = {
    "accounts_payable": ["应付账款"],
    "notes_payable": ["应付票据", "应付票据及应付账款"],
    "notes_receivable": ["应收票据", "应收票据及应收账款"],
    "other_receivables": ["其他应收款", "其他应收款净额"],
    "non_current_liab_due_within_1y": ["一年内到期的非流动负债"],
    "construction_in_progress": ["在建工程", "在建工程合计"],
    "trading_financial_assets": ["交易性金融资产"],
    "contract_liability": ["合同负债"],
    "advance_receipts": ["预收账款", "预收款项"],
    "bonds_payable": ["应付债券"],
    "cash_from_sales": ["销售商品、提供劳务收到的现金"],
}


def _flatten_detail(detail) -> dict:
    """从单条报表的 detail JSONB 抽取所需科目为规范英文键（best-effort，缺失跳过）。"""
    out: dict = {}
    if not isinstance(detail, dict):
        return out
    try:
        from src.infra.database.market.financial_full import parse_amount
    except Exception:  # noqa: BLE001
        return out
    for eng, candidates in _DETAIL_SUBJECT_MAP.items():
        for k in candidates:
            if k in detail:
                v = parse_amount(detail[k])
                if v is not None:
                    out[eng] = v
                break
    return out


def fetch_financial_snapshot(
    symbols: list[str],
    as_of: Optional[date] = None,
    lag_days: int = FINANCIAL_LAG_DAYS,
    include_detail: bool = True,
) -> dict[str, dict]:
    """
    批量取每个标的最新三大报表合并快照（供财务质量诊断 quality.compute_quality_report）。

    比 fetch_latest_financial_detail 拉更全的固定列，并（可选）把一组 detail JSONB
    科目扁平化为规范英文键。point-in-time：report_date <= as_of - lag_days。

    Args:
        symbols:        标的列表
        as_of:          截止日（空=今天）
        lag_days:       财报披露滞后天数
        include_detail: 是否抽取 detail JSONB 科目（单标的分析 True；全市场选股可 False
                        提速，此时仅固定列、仍覆盖多数指标）

    Returns:
        {symbol: {report_date, <固定列>, <detail扁平化键>...}}；无数据标的不出现。
    """
    if not symbols:
        return {}
    as_of = as_of or date.today()
    cutoff = as_of - timedelta(days=lag_days)
    out: dict[str, dict] = {}
    try:
        conn = _get_conn()
    except Exception:
        return out
    detail_col = ", detail" if include_detail else ""
    fields = ", ".join(_SNAPSHOT_FIELDS)
    sql = f"""
        SELECT * FROM (
            SELECT DISTINCT ON (symbol, statement_type)
                symbol, statement_type, report_date, {fields}{detail_col}
            FROM stock_financial_detail
            WHERE symbol = ANY(%s) AND report_date <= %s
            ORDER BY symbol, statement_type, report_date DESC
        ) t
    """
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (list(symbols), cutoff))
            for r in cur.fetchall():
                sym = r["symbol"]
                d = out.setdefault(sym, {"report_date": _as_date(r["report_date"])})
                for k in _SNAPSHOT_FIELDS:
                    v = r.get(k)
                    if v is not None:
                        d[k] = v
                if include_detail and r.get("detail") is not None:
                    d.update(_flatten_detail(r.get("detail")))
    except Exception as e:
        log.warning(f"fetch_financial_snapshot 失败: {e}")
    finally:
        conn.close()
    return out


def fetch_financial_history(
    symbols: list[str],
    as_of: Optional[date] = None,
    lag_days: int = FINANCIAL_LAG_DAYS,
    lookback_reports: int = 4,
) -> dict[str, list[dict]]:
    """
    批量拉所有标的最近 N 期财报历史（F-Score 需要两期对比）。

    Returns:
        {symbol: [{report_date, roe_weighted, ...}, ...]} 按 report_date 升序
    """
    if not symbols:
        return {}
    as_of = as_of or date.today()
    cutoff = as_of - __import__("datetime").timedelta(days=lag_days)
    out: dict[str, list[dict]] = {s: [] for s in symbols}
    try:
        conn = _get_conn()
    except Exception:
        return out
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 用 window function 取每个 symbol 最近 N 期
            cur.execute(
                """
                SELECT * FROM (
                    SELECT symbol, report_date, roe_weighted, roe_diluted,
                           gross_margin, net_margin, debt_ratio,
                           ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY report_date DESC) AS rn
                    FROM stock_financials
                    WHERE symbol = ANY(%s) AND report_date <= %s
                ) t WHERE rn <= %s ORDER BY symbol, report_date ASC
                """,
                (list(symbols), cutoff, lookback_reports),
            )
            for r in cur.fetchall():
                sym = r["symbol"]
                out.setdefault(sym, []).append({
                    "report_date": _as_date(r["report_date"]),
                    "roe_weighted": r.get("roe_weighted"),
                    "roe_diluted": r.get("roe_diluted"),
                    "gross_margin": r.get("gross_margin"),
                    "net_margin": r.get("net_margin"),
                    "debt_ratio": r.get("debt_ratio"),
                })
    except Exception as e:
        log.warning(f"fetch_financial_history 失败: {e}")
    finally:
        conn.close()
    return out


def fetch_universe_symbols(market: str = "A", exclude_st: bool = True) -> list[str]:
    """
    从 stock_info 拉取标的池（默认沪深A股，可剔 ST）。
    失败返回空列表。
    """
    try:
        conn = _get_conn()
    except Exception:
        return []
    try:
        with conn.cursor() as cur:
            sql = "SELECT symbol FROM stock_info WHERE market = %s"
            params: list = [market]
            if exclude_st:
                # 注意：psycopg2 的 % 是占位符，字面量 % 必须写成 %%
                sql += " AND name NOT LIKE 'ST%%' AND name NOT LIKE '*ST%%'"
            sql += " AND symbol NOT LIKE 'bj%%' ORDER BY symbol"
            cur.execute(sql, params)
            return [r[0] for r in cur.fetchall()]
    except Exception as e:
        log.warning(f"fetch_universe_symbols 失败: {e}")
        return []
    finally:
        conn.close()
