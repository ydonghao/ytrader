"""每日行业/指数估值落盘 job。

- sync_sw_index_valuation_daily(): 调 akshare sw_index_first_info，
  把当天 31 个行业的 PE/PB/PS/股息率落盘到 sw_index_valuation_daily。
  从今天起积累历史（akshare 该接口无历史）。

注册到 scheduler.py，工作日 16:10（收盘后）运行。
"""
import logging
import datetime as dt

from src.domain.market.sync.providers.akshare_provider import AkshareProvider
from src.infra.database.market.index_valuation import (
    create_index_valuation_repository,
)

log = logging.getLogger(__name__)


def sync_sw_index_valuation_daily() -> int:
    """落盘当天申万一级行业估值快照。

    Returns:
        写入条数。
    """
    prov = AkshareProvider()
    data = prov.fetch_sw_index_valuation_snapshot()
    if not data:
        log.warning("[sync_sw_val] snapshot empty, skip")
        return 0

    repo = create_index_valuation_repository()
    today = dt.date.today()
    count = 0
    for item in data:
        try:
            repo.upsert_sw(
                sw_code=item.get("sw_code"),
                trade_date=today,
                pe_ttm=item.get("pe_ttm"),
                pb=item.get("pb"),
                dv_ttm=item.get("dividend_yield"),
                source="akshare",
            )
            count += 1
        except Exception as e:
            log.warning(
                "[sync_sw_val] upsert %s failed: %s", item.get("sw_code"), e
            )
    log.info("[sync_sw_val] saved %d industries for %s", count, today)
    return count
