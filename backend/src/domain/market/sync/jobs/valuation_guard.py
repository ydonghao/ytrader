"""stock_valuation 东财快照脏点守护（PE 跳变检测与本地重算回写）。

背景：stock_valuation.pe_ttm 来自东财快照（ak.stock_value_em），
2026-08 下旬起东财在财报季批量更新 TTM EPS 时对部分公司写入了
错误口径（TTM 被砍半左右，PE 跳升 1.6~2 倍且不回落，如长虹美菱
2026-08-20 16.3→96.9）。

策略：检测近期相邻交易日 PE 跳升 >50% 且持续未回落的公司，用本地
stock_financials（累计口径 EPS，已交叉验证）重算标准 TTM 回写：
    TTM = 最新年报 + 最新累计期 - 上年同期累计期
安全阀：本地重算值与跳变前水平偏差 >50% 时不写（跳变前可能本来
就错，或本地数据有缺口），输出告警留人工复核。

调度：fundamentals_weekly（周六估值同步）之后链式执行，见 scheduler。
手动：backend/scripts/fix_market_data_quality.py fix-pe-jump。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import psycopg2

from src.pkg.utils.db_dsn import load_db_dsn

log = logging.getLogger(__name__)

# 拉取候选公司近 N 天 pe_ttm 序列（检测在 Python 侧做）
PE_SERIES_SQL = """
SELECT symbol, trade_date, pe_ttm
FROM stock_valuation
WHERE trade_date >= %s AND pe_ttm > 0
ORDER BY symbol, trade_date
"""

# 标准口径 TTM / 最新年报值（eps_basic / revenue_ps 通用，field 为列名）
TTM_SQL = """
WITH latest AS (
    SELECT report_date, {field} AS v FROM stock_financials
    WHERE symbol=%s AND {field} IS NOT NULL
    ORDER BY report_date DESC LIMIT 1
), fy AS (
    SELECT report_date, {field} AS v FROM stock_financials
    WHERE symbol=%s AND {field} IS NOT NULL
      AND date_part('month', report_date) = 12
    ORDER BY report_date DESC LIMIT 1
), prev_same AS (
    SELECT {field} AS v FROM stock_financials
    WHERE symbol=%s AND {field} IS NOT NULL
      AND report_date = (CASE
            WHEN date_part('month', (SELECT report_date FROM latest)) = 12
            THEN make_date(date_part('year', (SELECT report_date FROM latest))::int, 1, 1) - 1
            ELSE make_date(
                date_part('year', (SELECT report_date FROM latest))::int - 1,
                date_part('month', (SELECT report_date FROM latest))::int + 1, 1) - 1
          END)
)
SELECT (SELECT v FROM fy), (SELECT report_date FROM fy),
       (SELECT v FROM latest), (SELECT report_date FROM latest),
       (SELECT v FROM prev_same)
"""

# 回写：每个估值交易日取 <= 该日的最近收盘价（行情可能滞后快照 1 天）
PE_FIX_SQL = """
UPDATE stock_valuation v SET
    pe_ttm = p.px / NULLIF(%(eps_ttm)s, 0),
    pe     = p.px / NULLIF(%(fy_eps)s, 0),
    ps_ttm = p.px / NULLIF(%(rev_ttm)s, 0)
FROM (
    SELECT vd, (SELECT o.close_::float8 FROM stock_ohlcv o
                WHERE o.symbol = %(sym)s AND o.trade_date::date <= vd
                ORDER BY o.trade_date DESC LIMIT 1) AS px
    FROM (SELECT DISTINCT trade_date AS vd FROM stock_valuation
          WHERE symbol = %(sym)s AND trade_date >= %(from_d)s) t
) p
WHERE v.symbol = %(sym)s AND v.trade_date = p.vd AND p.px > 0
"""


def _ttm(cur, sym: str, field: str):
    """返回 (年报值, TTM值)。最新期即年报时 TTM=年报本身；缺上年同期拼不出。"""
    cur.execute(TTM_SQL.format(field=field), (sym, sym, sym))
    fy_v, fy_rd, cur_v, cur_rd, prev_v = cur.fetchone()
    if cur_v is None:
        return None, None
    if fy_rd is not None and cur_rd == fy_rd:
        return fy_v, fy_v
    if fy_v is None or prev_v is None:
        return fy_v, None
    return fy_v, fy_v + cur_v - prev_v


def run(lookback_days: int = 90, dry_run: bool = False) -> dict:
    """检测并修复 PE 跳变。返回统计 {detected, fixed, skipped, rows}。"""
    since = date.today() - timedelta(days=lookback_days)
    dsn = load_db_dsn()
    conn = psycopg2.connect(dsn)
    stats = {"detected": 0, "fixed": 0, "skipped": 0, "rows": 0}
    try:
        with conn.cursor() as cur:
            # 预过滤：至少 2 个年报的公司才有可靠 TTM（次新股 PE 波动大）
            cur.execute(
                "SELECT symbol FROM stock_financials "
                "WHERE date_part('month', report_date) = 12 "
                "  AND date_part('year', report_date) <= %s "
                "GROUP BY symbol HAVING count(*) >= 2",
                (date.today().year - 1,),
            )
            seasoned = {r[0] for r in cur.fetchall()}
            cur.execute(PE_SERIES_SQL, (since,))
            rows = cur.fetchall()

        series: dict[str, list] = {}
        for sym, td, pe in rows:
            series.setdefault(sym, []).append((td, pe))

        jumped = []
        for sym, pts in series.items():
            if sym not in seasoned:
                continue
            for i in range(1, len(pts)):
                prev_pe, cur_pe = pts[i - 1][1], pts[i][1]
                if prev_pe and prev_pe > 0 and cur_pe > prev_pe * 1.5:
                    if pts[-1][1] > prev_pe * 1.4:  # 持续未回落 → 脏数据
                        jumped.append((sym, pts[i][0], prev_pe, cur_pe))
                    break
        stats["detected"] = len(jumped)
        log.info("[valuation_guard] 检测到 PE 跳变且未回落: %d 家", len(jumped))

        for sym, jump_d, before, at_jump in jumped:
            with conn.cursor() as cur:
                fy_eps, eps_ttm = _ttm(cur, sym, "eps_basic")
                fy_rev, rev_ttm = _ttm(cur, sym, "revenue_ps")
                if not eps_ttm or eps_ttm <= 0:
                    stats["skipped"] += 1
                    log.warning("[valuation_guard] %s 无法重算 TTM EPS，跳过", sym)
                    continue
                cur.execute(
                    "SELECT close_::float8 FROM stock_ohlcv "
                    "WHERE symbol=%s AND trade_date::date <= %s "
                    "ORDER BY trade_date DESC LIMIT 1", (sym, jump_d))
                r = cur.fetchone()
                px = r[0] if r else None
                local_pe = px / eps_ttm if px else None
                if local_pe and abs(local_pe - before) / before > 0.5:
                    stats["skipped"] += 1
                    log.warning(
                        "[valuation_guard] %s 本地值 %.1f 与跳变前 %.1f "
                        "偏差>50%%，不回写（人工复核）", sym, local_pe, before)
                    continue
                if dry_run:
                    continue
                cur.execute(PE_FIX_SQL, {
                    "sym": sym, "from_d": jump_d,
                    "eps_ttm": eps_ttm, "fy_eps": fy_eps, "rev_ttm": rev_ttm,
                })
                stats["rows"] += cur.rowcount
                stats["fixed"] += 1
            conn.commit()
        log.info("[valuation_guard] 完成: %s", stats)
        return stats
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
