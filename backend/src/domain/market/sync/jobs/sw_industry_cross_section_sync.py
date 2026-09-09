"""行业截面同步 job：成分股 × 财务明细 → sw_industry_cross_section。

取数（raw psycopg2）：sw_industry_member ⋈ stock_financial_detail
  income（报告期窗口内、revenue 非空）LEFT JOIN balance（同期，取 equity）。
报告期窗口：>= 2016-01-01 且（12-31 年报 或 最近 28 个月≈8 季度）。
统计（纯函数）：每 (level, sw_code, report_date) 分组调
  cross_section_metrics；每组按期升序 attach_yoy。
口径：ROE=净利/权益×100（全口径未年化）；一级成分=名下二级并集。
全量重算 upsert——财务回填后重跑即自动修正（幂等）。
"""
import logging

import psycopg2

from src.domain.market.fundamental.industry_cross_section import (
    attach_yoy,
    cross_section_metrics,
)
from src.infra.database.market.sw_industry import (
    create_sw_industry_repository,
)
from src.infra.database.sql_engine.dsn import get_dsn

log = logging.getLogger(__name__)

_DETAIL_SQL = """
    SELECT m.sw_code_l1, m.sw_name_l1, m.sw_code_l2, m.sw_name_l2,
           i.report_date, i.symbol,
           i.revenue, i.net_profit, i.gross_margin, i.net_margin,
           b.equity
    FROM sw_industry_member m
    JOIN stock_financial_detail i
      ON i.symbol = m.symbol
     AND i.statement_type = 'income'
     AND i.report_date >= DATE '2016-01-01'
     AND (EXTRACT(MONTH FROM i.report_date) = 12
          OR i.report_date >= CURRENT_DATE - INTERVAL '28 months')
    LEFT JOIN stock_financial_detail b
      ON b.symbol = i.symbol
     AND b.statement_type = 'balance'
     AND b.report_date = i.report_date
    WHERE i.revenue IS NOT NULL
"""


def _derive_roe(row: dict) -> float | None:
    np_, eq = row.get("net_profit"), row.get("equity")
    if np_ is None or eq is None or eq <= 0:
        return None
    return np_ / eq * 100


def build_sections(details: list) -> list:
    """明细行 → 截面行（level2 + level1 两套组）。

    Returns: [{sw_code, report_date, level, sw_name, sample_count,
               revenue_sum, net_profit_sum, cr4, cr8, hhi,
               revenue_yoy, distribution}]
    """
    peers_by_key: dict = {}  # (level, sw_code) -> {report_date -> [peer]}
    names: dict = {}
    for row in details:
        if row.get("revenue") is None:
            continue
        peer = dict(row)
        peer["roe"] = _derive_roe(row)
        for level, code_col, name_col in (
            (2, "sw_code_l2", "sw_name_l2"),
            (1, "sw_code_l1", "sw_name_l1"),
        ):
            code = row[code_col]
            names[(level, code)] = row[name_col]
            peers_by_key.setdefault((level, code), {}).setdefault(
                row["report_date"], []
            ).append(peer)

    out: list[dict] = []
    for (level, code), by_date in peers_by_key.items():
        dates = sorted(by_date)
        secs = []
        for d in dates:
            m = cross_section_metrics(by_date[d])
            secs.append({
                "sw_code": code, "report_date": d, "level": level,
                "sw_name": names[(level, code)], **m,
            })
        attach_yoy(secs)
        out.extend(secs)
    return out


def run() -> dict:
    """全量重算截面。Returns {sections, industries}。"""
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(_DETAIL_SQL)
            cols = [c.name for c in cur.description]
            details = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()
    log.info("[sw_xs] 明细行 %d", len(details))

    rows = build_sections(details)
    wrote = create_sw_industry_repository().upsert_sections(rows)
    industries = len({(r["level"], r["sw_code"]) for r in rows})
    log.info("[sw_xs] 截面 %d 行 / %d 个(级别,行业)", wrote, industries)
    return {"sections": wrote, "industries": industries}
