# backend/src/domain/market/sync/jobs/industry_pb_break_sync.py
"""破净率每日增量 job(16:40):最近 N 个估值交易日逐日聚合 upsert,幂等可补。"""
import datetime as dt
import logging
from types import SimpleNamespace

from src.domain.market.industry_analysis.pb_break import aggregate_pb_break
from src.infra.database.market.industry_analysis import (
    create_industry_analysis_repository,
)

log = logging.getLogger(__name__)

_SQL = """
    SELECT v.symbol, v.pb, m.sw_code_l1
    FROM stock_valuation v
    LEFT JOIN sw_industry_member m ON m.symbol = v.symbol
    WHERE v.trade_date = %s
"""


def build_pb_rows(trade_date: dt.date, aggregate) -> list[dict]:
    """聚合结果 → upsert 行(market 行 scope_code='ALL')。"""
    rows = [{"trade_date": trade_date, "scope": "market",
             "scope_code": "ALL",
             "total_count": aggregate.market.total_count,
             "break_count": aggregate.market.break_count,
             "break_rate": aggregate.market.break_rate,
             "median_pb": aggregate.market.median_pb}]
    for code, st in aggregate.industries.items():
        rows.append({"trade_date": trade_date, "scope": "industry",
                     "scope_code": code, "total_count": st.total_count,
                     "break_count": st.break_count,
                     "break_rate": st.break_rate,
                     "median_pb": st.median_pb})
    return rows


def aggregate_one_day(repo, conn, trade_date: dt.date) -> int:
    with conn.cursor() as cur:
        cur.execute(_SQL, (trade_date,))
        raw = cur.fetchall()
    agg = aggregate_pb_break(
        (r[0], float(r[1]) if r[1] is not None else None, r[2])
        for r in raw)
    # aggregate_pb_break 返回 dict;build_pb_rows 按属性访问,包一层同构视图
    aggregate = SimpleNamespace(market=agg["market"],
                                industries=agg["industries"])
    return repo.upsert_pb_break(build_pb_rows(trade_date, aggregate))


def run(days: int = 2) -> dict:
    """对最近 days 个 stock_valuation 交易日重算(补昨日缺口+幂等今日)。"""
    import psycopg2

    from src.infra.database.sql_engine.dsn import get_dsn
    repo = create_industry_analysis_repository()
    today = dt.date.today()
    dates = repo.get_stock_valuation_dates(today - dt.timedelta(days=days * 3),
                                           today)[-days:]
    total = 0
    conn = psycopg2.connect(get_dsn())
    try:
        for d in dates:
            total += aggregate_one_day(repo, conn, d)
    finally:
        conn.close()
    log.info("[INDUSTRY_PB_BREAK] dates=%s rows=%d", dates, total)
    return {"dates": [str(d) for d in dates], "rows": total}
