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


def compute_and_save_sw_computed(trade_date=None) -> int:
    """日度化 computed（数据治理 1.2）：成分股整体法调和加权。

    依赖 stock_valuation(周同步) + sw_industry_member(周六同步)。
    """
    import datetime as dt
    from src.domain.market.health.sw_unify import (
        compute_sw_valuation_daily,
    )
    from src.infra.database.market.industry_analysis import (
        create_industry_analysis_repository,
    )
    from src.infra.database.market.index_valuation import (
        create_index_valuation_repository,
    )

    trade_date = trade_date or dt.date.today()
    irepo = create_industry_analysis_repository()
    v_dates = irepo.get_stock_valuation_dates(
        trade_date - dt.timedelta(days=45), trade_date,
    )
    if not v_dates:
        log.warning("[sw_computed_daily] 无估值截面, skip")
        return 0
    members = irepo.get_members(v_dates[-1]) if hasattr(
        irepo, "get_members") else []
    if not members:
        # 行业 repo 无直取成员时用 member_valuations 截面
        members = [
            {"sw_code": m["sw_code_l1"], "symbol": m["symbol"]}
            for m in irepo.get_member_valuations(v_dates[-1])
        ]
    vals = irepo.get_member_valuations(v_dates[-1])
    valuations = [
        {
            "symbol": v["symbol"],
            "trade_date": dt.date.fromisoformat(str(v_dates[-1])),
            "pe_ttm": v.get("pe_ttm"), "pb": v.get("pb"),
            "total_mv": v.get("total_mv"),
        }
        for v in vals
    ]
    rows = compute_sw_valuation_daily(members, valuations, trade_date)
    repo = create_index_valuation_repository()
    n = 0
    for r in rows:
        code = r["sw_code"]
        # 表内约定带 sw 前缀(如 sw801010);成员表是无前缀6位
        if not str(code).startswith("sw"):
            code = f"sw{code}"
        try:
            repo.upsert_sw(
                sw_code=code, trade_date=trade_date,
                pe_ttm=r.get("pe_ttm"), pb=r.get("pb"),
                source="computed",
            )
            n += 1
        except Exception as e:  # noqa: BLE001
            log.warning("[sw_computed_daily] %s failed: %s",
                        r.get("sw_code"), e)
    log.info("[sw_computed_daily] %s industries for %s", n, trade_date)
    return n
