#!/usr/bin/env python
"""
新闻回填脚本
=============
每日爬取A股股票新闻并保存到数据库。

Usage:
    python scripts/news_backfill.py                    # 回填所有股票
    python scripts/news_backfill.py --symbols sh600000  # 仅回填指定股票
    python scripts/news_backfill.py --days-back 30      # 回填30天
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import psycopg2

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.domain.market.news.models import NewsArticle
from src.domain.market.news.news_provider import NewsProvider
from src.domain.market.news.providers.akshare_provider import AkshareNewsProvider
from src.domain.market.news.repository import NewsRepository
from src.domain.market.news.sync_service import NewsSyncService, NewsSyncStats
from src.infra.database.news_repository import NewsRepositoryImpl

from pkg.utils.db_dsn import load_db_dsn


DEFAULT_PROGRESS_FILE = ".news_backfill_progress.json"
DB_CONNECTION_STRING = load_db_dsn(Path(__file__).parent.parent)


def get_stock_list() -> list[dict]:
    """
    从 stock_ohlcv 表获取 A股股票列表。

    Returns:
        [{"symbol": "sh600000", "name": "xxx"}, ...]
    """
    conn = psycopg2.connect(DB_CONNECTION_STRING)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT symbol
            FROM stock_ohlcv
            WHERE symbol LIKE 'sh%' OR symbol LIKE 'sz%'
            ORDER BY symbol
            """
        )
        rows = cursor.fetchall()
        return [{"symbol": row[0]} for row in rows]
    finally:
        cursor.close()
        conn.close()


def backfill_stock_list(
    sync_service: NewsSyncService,
    symbols: Optional[list[str]] = None,
    days_back: int = 7,
    progress_file: str = DEFAULT_PROGRESS_FILE,
) -> dict:
    """
    回填股票列表的新闻。

    Args:
        sync_service: 新闻同步服务。
        symbols: 限定的股票代码列表。None 表示全部。
        days_back: 回溯天数。
        progress_file: 进度文件路径。

    Returns:
        回填统计结果。
    """
    stock_list = get_stock_list()

    if symbols:
        stock_list = [s for s in stock_list if s["symbol"] in symbols]

    total_symbols = len(stock_list)
    total_news = 0
    saved_news = 0
    errors = 0
    completed_symbols = 0

    for i, stock in enumerate(stock_list):
        symbol = stock["symbol"]
        print(f"[{i + 1}/{total_symbols}] Syncing {symbol}...")

        try:
            stats = sync_service.sync_stock_news(symbol, days_back=days_back)
            total_news += stats.total
            saved_news += stats.saved
            if stats.errors > 0:
                errors += 1
        except Exception as e:
            print(f"  Error: {e}")
            errors += 1

        completed_symbols += 1

        if (i + 1) % 10 == 0:
            _save_progress(
                progress_file,
                {
                    "total_symbols": total_symbols,
                    "completed_symbols": completed_symbols,
                    "total_news": total_news,
                    "saved_news": saved_news,
                    "errors": errors,
                    "last_updated": datetime.now().isoformat(),
                },
            )

    result = {
        "total_symbols": total_symbols,
        "completed_symbols": completed_symbols,
        "total_news": total_news,
        "saved_news": saved_news,
        "errors": errors,
        "last_updated": datetime.now().isoformat(),
    }

    _save_progress(progress_file, result)
    return result


def _save_progress(progress_file: str, data: dict) -> None:
    """保存进度到文件"""
    with open(progress_file, "w") as f:
        json.dump(data, f, indent=2)


def main():
    """主入口"""
    parser = argparse.ArgumentParser(description="新闻回填脚本")
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="限定的股票代码列表，如 --symbols sh600000 sh600001",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=7,
        help="回溯天数 (默认: 7)",
    )
    parser.add_argument(
        "--progress-file",
        default=DEFAULT_PROGRESS_FILE,
        help=f"进度文件路径 (默认: {DEFAULT_PROGRESS_FILE})",
    )
    args = parser.parse_args()

    provider = AkshareNewsProvider()
    repository = NewsRepositoryImpl()
    sync_service = NewsSyncService(provider, repository)

    print(f"Starting news backfill...")
    print(f"Days back: {args.days_back}")
    if args.symbols:
        print(f"Symbols: {', '.join(args.symbols)}")
    print()

    result = backfill_stock_list(
        sync_service,
        symbols=args.symbols,
        days_back=args.days_back,
        progress_file=args.progress_file,
    )

    print()
    print("=" * 50)
    print(f"Backfill completed!")
    print(f"  Total symbols: {result['total_symbols']}")
    print(f"  Completed: {result['completed_symbols']}")
    print(f"  Total news fetched: {result['total_news']}")
    print(f"  Saved: {result['saved_news']}")
    print(f"  Errors: {result['errors']}")


if __name__ == "__main__":
    main()
