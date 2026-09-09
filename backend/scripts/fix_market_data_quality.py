#!/usr/bin/env python3
"""修复行情/估值数据质量问题（一次性工具）。

三个独立动作（可组合，见 --help）：

1. fix-change-pct  stock_ohlcv.change_pct 全表为 0（写入路径从不写该列）。
    按 symbol LAG(close_) 重算当日涨跌幅（百分数，如 3.5 = +3.5%），
    与 report_router.py 现网口径一致。未复权价：除权日会把除权跳空
    计入涨跌幅（与行情软件未复权日 K 口径相同）。
    分批 UPDATE（默认 500 symbol/批），可断点重跑（幂等）。

2. fix-pe-jump     stock_valuation.pe_ttm 偶发上游（东财快照）脏点：
    相邻交易日 PE 跳升 >50% 且此后未回落（如长虹美菱 2026-08-20
    16.3→96.9）。用本地 stock_financials 累计口径 EPS 重算标准 TTM：
        TTM = 最新年报 + 最新累计期 - 上年同期累计期
    回写跳变日之后的 pe_ttm / pe / ps_ttm。pe(静) = px/最新年报EPS，
    ps_ttm = px/revenue_ps TTM。校验：重算值应接近跳变前水平。

3. add-comments    给三张表的易踩坑列加 COMMENT（口径说明）。

用法：
    uv run python scripts/fix_market_data_quality.py --dry-run          # 全部预演
    uv run python scripts/fix_market_data_quality.py fix-change-pct     # 只跑1
    uv run python scripts/fix_market_data_quality.py fix-pe-jump add-comments
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import psycopg2

BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND / "src"))

from pkg.utils.db_dsn import load_db_dsn  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            BACKEND / "logs/fix_market_data.log", encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("fix_market_data")

# ── 1. change_pct 回填 ────────────────────────────────────────────────────
# 每批 symbol 一次窗口函数 UPDATE；IS DISTINCT FROM 保证幂等（重跑只更新差异行）
CHANGE_PCT_SQL = """
UPDATE stock_ohlcv o SET change_pct = x.c, amplitude = x.a
FROM (
    SELECT symbol, trade_date,
        round(((close_ / NULLIF(LAG(close_) OVER w, 0) - 1) * 100)::numeric, 4)::real AS c,
        round(((high_ - low_) / NULLIF(LAG(close_) OVER w, 0) * 100)::numeric, 4)::real AS a
    FROM stock_ohlcv
    WHERE symbol = ANY(%s)
    WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
) x
WHERE o.symbol = x.symbol AND o.trade_date = x.trade_date
  AND (o.change_pct IS DISTINCT FROM x.c OR o.amplitude IS DISTINCT FROM x.a)
"""

# ── 2. pe_ttm 跳变检测与修复 ──────────────────────────────────────────────
# 检测在 Python 侧做（窗口+聚合混用 SQL 难写清），SQL 只拉序列：
# 近 N 天内相邻交易日 pe_ttm 跳升>50%，且最新值仍 > 跳变前×1.4（未回落）
# 修复回写：按每股口径重算。每个估值交易日取 <= 该日的最近收盘
# （个别 symbol 行情可能滞后估值快照 1 天，价格差可忽略）
# ── 3. 注释 ───────────────────────────────────────────────────────────────
COMMENTS = [
    ("column", "stock_ohlcv.change_pct",
     "当日涨跌幅%，未复权口径（除权日含除权跳空），由 LAG(close_) 重算；"
     "写入路径不产出该列，依赖 scripts/fix_market_data_quality.py 维护"),
    ("column", "stock_ohlcv.amplitude",
     "当日振幅% = (high-low)/昨收，未复权口径，同 change_pct 维护方式"),
    ("column", "stock_dividend.stock_div",
     "送股比例，每10股口径（5 = 10送5）；div_per_share 为每股口径，两者不同"),
    ("column", "stock_dividend.convert",
     "转增比例，每10股口径（4 = 10转4）；复权因子需除以10"),
    ("column", "stock_financials.eps_basic",
     "基本每股收益，报告期累计口径（Q2=上半年累计），已用 eps/nav_ps 与新浪"
     "加权ROE交叉验证一致率92.3%，无系统性单季混杂"),
]


def fix_change_pct(conn, dry_run: bool, batch: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol FROM stock_ohlcv WHERE market='A' "
            "GROUP BY symbol HAVING count(*) FILTER (WHERE change_pct = 0) > 0 "
            "ORDER BY symbol"
        )
        symbols = [r[0] for r in cur.fetchall()]
    log.info(f"[change_pct] 待重算 symbol 数: {len(symbols)}")
    total = 0
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        if dry_run:
            log.info(f"[change_pct] dry-run 跳过批次 {i//batch+1}"
                     f"（{chunk[0]}..{chunk[-1]}, {len(chunk)} 只）")
            continue
        with conn.cursor() as cur:
            cur.execute(CHANGE_PCT_SQL, (chunk,))
            total += cur.rowcount
        conn.commit()
        log.info(f"[change_pct] 批次 {i//batch+1}: 累计更新 {total:,} 行")
    if not dry_run:
        log.info(f"[change_pct] 完成，共更新 {total:,} 行")



def fix_pe_jump(conn, dry_run: bool, lookback_days: int = 90) -> None:
    """薄壳：检测+修复逻辑在 jobs/valuation_guard.py（scheduler 每周链式跑），
    此处仅提供手动入口，避免双维护。"""
    from domain.market.sync.jobs.valuation_guard import run as guard_run
    guard_run(lookback_days=lookback_days, dry_run=dry_run)


def add_comments(conn, dry_run: bool) -> None:
    for kind, obj, comment in COMMENTS:
        sql = f"COMMENT ON {kind.upper()} {obj} IS %s"
        log.info(f"[comments] {obj}: {comment[:50]}...")
        if not dry_run:
            with conn.cursor() as cur:
                cur.execute(sql, (comment,))
            conn.commit()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("actions", nargs="*",
                    choices=["fix-change-pct", "fix-pe-jump", "add-comments"],
                    help="要执行的动作（可多选，空=仅显示帮助）")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写库")
    ap.add_argument("--batch", type=int, default=500,
                    help="change_pct 重算的每批 symbol 数")
    args = ap.parse_args()
    if not args.actions:
        ap.print_help()
        return

    dsn = load_db_dsn(BACKEND)
    conn = psycopg2.connect(dsn)
    try:
        if "fix-change-pct" in args.actions:
            fix_change_pct(conn, args.dry_run, args.batch)
        if "fix-pe-jump" in args.actions:
            fix_pe_jump(conn, args.dry_run)
        if "add-comments" in args.actions:
            add_comments(conn, args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
