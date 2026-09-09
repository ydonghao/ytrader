"""MarketSentimentSyncJob — 北向资金 / 融资融券 / 中国国债收益率 日频同步。

市场级（非 per-symbol）三条资金面/利率数据：
  1. 北向资金净流入 → north_flow_daily
  2. 融资融券余额   → margin_balance_daily
  3. 中国 10Y 国债收益率 → macro_indicator(cn_bond_10y)，供中美利差分析

用法:
  python -m src.domain.market.sync.jobs.market_sentiment_sync
  python -m src.domain.market.sync.jobs.market_sentiment_sync --days 30
"""
import argparse
import logging
import sys
import datetime as dt
from pathlib import Path

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync.providers.akshare_provider import AkshareProvider  # noqa: E402
from src.infra.database.market.market_sentiment import (  # noqa: E402
    create_market_sentiment_repository,
)

log = logging.getLogger("market_sentiment_sync")


def run(days: int = 90) -> dict:
    """同步近 days 天的北向/两融/国债数据。"""
    provider = AkshareProvider()
    repo = create_market_sentiment_repository()
    today = dt.date.today()
    start = today - dt.timedelta(days=days)
    sd, ed = start.strftime("%Y%m%d"), today.strftime("%Y%m%d")
    result: dict = {"date_range": [sd, ed]}

    # 1. 北向资金
    try:
        rows = provider.fetch_north_flow("北向资金")
        n = repo.upsert_north_flow(rows) if rows else 0
        result["north_flow"] = n
    except Exception as e:  # noqa: BLE001
        log.warning(f"北向资金失败: {e}")
        result["north_flow"] = "error"

    # 2. 融资融券
    try:
        rows = provider.fetch_margin_balance(sd, ed)
        n = repo.upsert_margin_balance(rows) if rows else 0
        result["margin_balance"] = n
    except Exception as e:  # noqa: BLE001
        log.warning(f"两融余额失败: {e}")
        result["margin_balance"] = "error"

    # 3. 中国国债收益率 → macro_indicator(cn_bond_10y)
    try:
        rows = provider.fetch_cn_bond_yield(sd, ed, tenor="10年")
        n = _store_bond_yield_to_macro(rows)
        result["cn_bond_10y"] = n
    except Exception as e:  # noqa: BLE001
        log.warning(f"国债收益率失败: {e}")
        result["cn_bond_10y"] = "error"

    result["synced_at"] = dt.datetime.now().isoformat()
    return result


def _store_bond_yield_to_macro(rows: list[dict]) -> int:
    """把中国 10Y 国债收益率写入 macro_indicator(code=cn_bond_10y)。"""
    if not rows:
        return 0
    from src.infra.database.market.macro_indicator import (
        create_macro_indicator_repository,
    )
    repo = create_macro_indicator_repository()
    n = 0
    for r in rows:
        y = r.get("yield")
        if y is None:
            continue
        try:
            repo.upsert(
                indicator_code="cn_bond_10y",
                report_date=r["trade_date"],
                value=y * 100.0,   # macro_indicator 习惯以 % 存（与 CPI 等一致）
                freq="day",
                unit="%",
                source="akshare-bond_china_yield",
                provider="akshare",
            )
            n += 1
        except Exception as e:  # noqa: BLE001
            log.debug(f"国债 {r.get('trade_date')} 写入失败: {e}")
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()
    print(run(days=args.days))
