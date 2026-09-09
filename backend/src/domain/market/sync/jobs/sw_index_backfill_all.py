"""
SwIndexBackfillAllJob
=====================
申万行业指数日线全量回填（一/二/三级通用）。

数据源：index_hist_sw（swsresearch.com，~1999 至今）。
symbol 存储：一级 sw801010、二级 sw801016、三级 sw850111（带 sw 前缀，market='SW'）。
market 列额外标注级别：'SW' / 'SW2' / 'SW3'（便于 sector-scan 按级别过滤）。

用法：
  # 全部三级一起回填到 30 年
  python -m src.domain.market.sync.jobs.sw_index_backfill_all --years 30 --workers 6

  # 只回填二级
  python -m src.domain.market.sync.jobs.sw_index_backfill_all --level 2 --years 30
"""
import argparse
import logging
import socket
import sys
from pathlib import Path

socket.setdefaulttimeout(60)

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent  # backend/
sys.path.insert(0, str(_BACKEND))

import akshare as ak  # noqa: E402
from src.domain.market.sync.jobs.full_sync import (  # noqa: E402
    _build_service, _ensure_schema, _today, _years_ago,
)
from src.domain.market.sync.sync_service import INDEX_INSERT_SQL, SyncResult  # noqa: E402

log = logging.getLogger("sw_index_backfill_all")

# 各级行业 market 标记 + 清单获取函数
LEVEL_INFO = {
    1: ("SW",  ak.sw_index_first_info),
    2: ("SW2", ak.sw_index_second_info),
    3: ("SW3", ak.sw_index_third_info),
}


def fetch_sector_list(level: int) -> list[tuple[str, str, str | None]]:
    """返回 [(sw_symbol, name, parent_name), ...]。
    parent_name 仅二级/三级有（上级行业），用于前端分组展示。"""
    market_mark, info_fn = LEVEL_INFO[level]
    df = info_fn()
    out = []
    for _, r in df.iterrows():
        code = str(r["行业代码"]).replace(".SI", "")  # 801010 / 801016 / 850111
        name = str(r["行业名称"]).strip()
        parent = str(r.get("上级行业", "")).strip() or None
        out.append((f"sw{code}", name, parent))
    return out


def run(level: int = 0, years: int = 30, workers: int = 6) -> list[SyncResult]:
    """回填指定级别（0=全部三级）的申万行业指数日线。

    Args:
        level: 1/2/3 指定级别，0=全部三级
        years: 回填年数
        workers: 并发数
    """
    _ensure_schema()
    svc = _build_service(workers)
    start, end = _years_ago(years), _today()

    levels = [level] if level else [1, 2, 3]
    results = []
    for lv in levels:
        sectors = fetch_sector_list(lv)
        symbols = [s[0] for s in sectors]
        log.info(f"[L{lv}] {len(symbols)} 个申万{['','一','二','三'][lv]}级行业, {start}~{end}")
        r = svc.backfill_range(
            symbols=symbols, interval="1d", start_date=start, end_date=end,
            insert_sql=INDEX_INSERT_SQL, is_index=True, mode="full",
        )
        # market 列已被 INDEX_INSERT_SQL 写为 'INDEX'，需按级别修正
        _fix_market_level(symbols, LEVEL_INFO[lv][0])
        log.info(f"[L{lv}] 完成: {r.done_symbols}/{r.total_symbols} 成功, {r.total_rows:,} 行")
        results.append(r)
    return results


def _fix_market_level(symbols: list[str], market_mark: str):
    """把指定 symbols 的 market 列精确设为对应级别标记。

    用精确 symbol 列表更新（不带 market='INDEX' 条件），避免 ON CONFLICT
    upsert 覆盖 market 列导致级别标记失效。
    """
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE index_ohlcv SET market = %s WHERE symbol = ANY(%s)",
                (market_mark, symbols),
            )
        conn.commit()
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="申万行业指数（一/二/三级）全量回填")
    parser.add_argument("--level", type=int, default=0, choices=[0, 1, 2, 3],
                        help="级别：1/2/3，0=全部（默认）")
    parser.add_argument("--years", type=int, default=30, help="回填年数")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    (_BACKEND / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(_BACKEND / "logs" / "sw_index_backfill_all.log",
                                encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    results = run(level=args.level, years=args.years, workers=args.workers)
    total_rows = sum(r.total_rows for r in results)
    total_done = sum(r.done_symbols for r in results)
    log.info(f"=== 全部完成: {total_done} 个行业, {total_rows:,} 行 ===")
    for r in results:
        if r.errors:
            for e in r.errors[:5]:
                log.warning(f"    {e}")


if __name__ == "__main__":
    main()
