#!/usr/bin/env python3
"""历史缺口一次性回补（2026-09-08 盘点结论，免费源可覆盖部分）。

三个独立子命令：

  fx        汇率 5 对 → fx_rate。新浪中行折算价（与 quant_daily 日常写入
            同源同口径：中行折算价/100），回补到源地板。
  index     主指数日线 → index_ohlcv。新浪 stock_zh_index_daily（复用
            index_backfill.run，years=40 覆盖到 1986，实际到源地板）。
  earnings  业绩预告+业绩快报 → stock_earnings_forecast。东财按报告期
            全市场批量（复用 provider.fetch_earnings_batch），2008 起回补。

注意：macro_indicator 里 us_core_pce/us_ism_pmi/us_unemp 的 1970-01-01
  起的行是真实历史数据（美国 70 年代序列，非缺日期哨兵），不要清理。

实测源地板（2026-09-08）：
  USDCNY 1994-03-22 / GBPCNY·JPYCNY 1994-08-30 / HKDCNY 1994-04-15
  / EURCNY 1999-01-04（中行折算价序列起点）
  上证综指 1990-12-19 / 深证成指 1991-04-03 / 深证综指 1995-12-19
  / 沪深300 2002-01-04（sh932000 新浪无日线，报错可忽略，本地已有 2014-10 起）
  股东户数：东财接口地板即 2013-03，本地已到底，不在本脚本范围。
  shareholder_info：遗留 mock 端点种子表（假数据），不补。

用法：
    uv run python scripts/backfill_history_gaps.py fx
    uv run python scripts/backfill_history_gaps.py index
    uv run python scripts/backfill_history_gaps.py earnings
"""
from __future__ import annotations

import argparse
import datetime as dt
import socket
import sys
import time
from pathlib import Path

# akshare 请求挂死兜底（同 index_backfill.py）
socket.setdefaulttimeout(60)

_BACKEND = Path(__file__).parent.parent  # backend/
sys.path.insert(0, str(_BACKEND))

import psycopg2  # noqa: E402
from psycopg2.extras import execute_values  # noqa: E402

from conf import app_config  # noqa: E402
from src.infra.database.sql_engine.dsn import get_dsn  # noqa: E402


def run_fx() -> None:
    """汇率 5 对回补到中行折算价序列起点。"""
    from src.domain.market.sync.providers.akshare_provider import AkshareProvider

    provider = AkshareProvider()
    pairs: list[str] = app_config.quant_universe.fx_pairs
    today = dt.date.today().isoformat()
    total = 0
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            for pair in pairs:
                bars = provider.fetch_fx_ohlc(pair, "1994-01-01", today)
                if not bars:
                    print(f"[fx] {pair} 无数据")
                    continue
                rows = [
                    (b.trade_time.date(), pair, b.close_, b.open_, b.high_,
                     b.low_, "akshare", dt.datetime.now())
                    for b in bars
                ]
                execute_values(
                    cur,
                    """
                    INSERT INTO fx_rate
                        (date, pair, rate, open_, high_, low_, source, created_at)
                    VALUES %s
                    ON CONFLICT (date, pair) DO UPDATE SET
                        rate = EXCLUDED.rate, open_ = EXCLUDED.open_,
                        high_ = EXCLUDED.high_, low_ = EXCLUDED.low_,
                        source = EXCLUDED.source
                    """,
                    rows,
                )
                total += len(rows)
                print(f"[fx] {pair} +{len(rows)} 行 "
                      f"({rows[0][0]} ~ {rows[-1][0]})")
        conn.commit()
    finally:
        conn.close()
    print(f"[fx] 合计 {total} 行")


def run_index() -> None:
    """主指数日线回补 1990s–2006 缺口（years=40 触达新浪全深度）。"""
    from src.domain.market.sync.jobs.index_backfill import run as index_run

    r = index_run(years=40, workers=4)
    print(f"[index] {r.done_symbols}/{r.total_symbols} 成功, "
          f"{r.total_rows:,} 行")
    for e in (r.errors or [])[:20]:
        print(f"    {e}")


def _quarter_ends(start_year: int) -> list[str]:
    """start_year 起至最近一个已过去季末的报告期列表（YYYYMMDD）。"""
    today = dt.date.today()
    ends = []
    for year in range(start_year, today.year + 1):
        for md in ("0331", "0630", "0930", "1231"):
            d = dt.date(year, int(md[:2]), int(md[2:]))
            if d <= today:
                ends.append(d.strftime("%Y%m%d"))
    return ends


def run_earnings(start_year: int = 2008) -> None:
    """业绩预告+快报按报告期回补（东财源，2008 起有数）。"""
    from src.domain.market.sync.providers.akshare_provider import AkshareProvider
    from src.infra.database.market.financial_full import (
        create_earnings_forecast_repository,
    )

    provider = AkshareProvider()
    repo = create_earnings_forecast_repository()
    stats = {"preannounce": 0, "express": 0}
    periods = _quarter_ends(start_year)
    for i, rd in enumerate(periods, 1):
        try:
            batch = provider.fetch_earnings_batch(rd)
        except Exception as e:  # noqa: BLE001
            print(f"[earnings:{rd}] 拉取失败: {e}")
            continue
        n_by_type = {}
        for ftype, rows in batch.items():
            if not rows:
                continue
            try:
                n = repo.bulk_upsert(rows)
                stats[ftype] += n
                n_by_type[ftype] = n
            except Exception as e:  # noqa: BLE001
                print(f"[earnings:{rd}:{ftype}] 写入失败: {e}")
        print(f"[earnings] {i}/{len(periods)} {rd} "
              f"preannounce={n_by_type.get('preannounce', 0)} "
              f"express={n_by_type.get('express', 0)}")
        time.sleep(0.3)  # 对东财礼貌一点
    print(f"[earnings] 合计 preannounce={stats['preannounce']} "
          f"express={stats['express']}")


def run_macro() -> None:
    raise SystemExit(
        "macro 清理已撤销：1970-01-01 起的 us_* 行是真实历史数据"
        "（首月 3 行曾误删，已于 2026-09-08 恢复），此子命令不再提供。"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["fx", "index", "earnings", "macro"],
        help="回补动作（见模块 docstring）",
    )
    parser.add_argument(
        "--start-year", type=int, default=2008,
        help="earnings 起始年份（默认 2008，东财源地板）",
    )
    args = parser.parse_args()

    if args.action == "fx":
        run_fx()
    elif args.action == "index":
        run_index()
    elif args.action == "earnings":
        run_earnings(start_year=args.start_year)
    else:
        run_macro()


if __name__ == "__main__":
    main()
