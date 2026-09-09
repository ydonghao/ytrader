"""宽基指数市值回填 job：成分股 stock_valuation 月末加总 → index_valuation_daily。

口径：用当前成分近似历史成分（csindex 无历史成分，幸存者偏差，
source='computed'）；月末采样（与 index_valuation_backfill 一致）。
全量重算近 N 年月度序列（删旧重写幂等）。

覆盖率门控：stock_valuation 对成分股的历史覆盖不均（早期只有部分
股票有估值数据），直接加总会把"数据覆盖度"画成"市值爬升"——
某月末有值成分股占比 < 80% 的点不入库（MIN_COVER_RATIO）。

整体法市盈率：同 pass 用 index_financial_quarterly 累计净利和
（披露率门控 + to_ttm）与月末市值和相除，pe_ttm 随 mv 同行写入
（source='computed'）；TTM 断档/净利≤0 的月度点 pe 为 NULL。
"""
import logging
import datetime as dt

from src.infra.database.market.index_constituent import (
    create_index_constituent_repository,
)
from src.infra.database.market.index_valuation import (
    create_index_valuation_repository,
)
from src.infra.database.market.valuation import (
    create_stock_valuation_repository,
)

log = logging.getLogger(__name__)

# 覆盖率门控：月末有 total_mv 的成分股数 / 成分股总数 低于该比例的点丢弃
MIN_COVER_RATIO = 0.8


def _monthly_mv_sum(rows_by_symbol: dict) -> list[dict]:
    """{symbol: [StockValuation…]} → 按月末日期加总 total_mv（纯函数，元）。

    Returns: [{date: date, total_mv: float, count: int}]，升序；
    total_mv None 不计入加总也不计入 count。
    """
    acc: dict = {}
    cnt: dict = {}
    for rows in rows_by_symbol.values():
        for r in rows:
            d, mv = r.trade_date, r.total_mv
            if d is None or mv is None:
                continue
            acc[d] = acc.get(d, 0.0) + float(mv)
            cnt[d] = cnt.get(d, 0) + 1
    return [
        {"date": d, "total_mv": acc[d], "count": cnt[d]}
        for d in sorted(acc.keys())
    ]


def _filter_covered(
    monthly: list[dict], n_symbols: int, min_ratio: float = MIN_COVER_RATIO,
) -> list[dict]:
    """丢弃覆盖率不足的月度点（纯函数；n_symbols<=0 时全部丢弃）。"""
    if n_symbols <= 0:
        return []
    return [p for p in monthly if p.get("count", 0) / n_symbols >= min_ratio]


def sync_index_market_cap(years: int = 10) -> dict[str, int]:
    """回填全部配置宽基指数的月度总市值 + 整体法 PE 序列（亿）。

    Returns: {index_code: mv点数}（pe 点数见日志）
    """
    from conf import app_config
    from src.domain.market.fundamental.index_pe import compute_index_pe
    from src.infra.database.market.index_financial import (
        create_index_financial_repository,
    )
    items = app_config.quant_universe.index_constituents
    cons_repo = create_index_constituent_repository()
    val_repo = create_stock_valuation_repository()
    idx_repo = create_index_valuation_repository()
    fin_repo = create_index_financial_repository()

    from dateutil.relativedelta import relativedelta

    end = dt.date.today()
    # 闰日安全：date(y-years, 2, 29) 在平年会 ValueError，用 relativedelta。
    start = end - relativedelta(years=years)

    results: dict[str, int] = {}
    for it in items:
        try:
            symbols = cons_repo.get_members(it.code)
            if not symbols:
                log.warning("[idx_mv] %s no constituents, skip", it.code)
                results[it.code] = 0
                continue
            rows_by_symbol = val_repo.get_range_batch(
                symbols, start, end, monthly=True,
            )
            monthly = _filter_covered(
                _monthly_mv_sum(rows_by_symbol), len(symbols),
            )
            # 整体法 PE：累计净利和多取一年做 TTM 年报基准
            fin_rows = fin_repo.get_series(
                "index", it.code, start=start - relativedelta(years=1),
            )
            pe_series = compute_index_pe(
                [{"date": p["date"], "total_mv": p["total_mv"] / 1e8}
                 for p in monthly],
                [{"report_date": r.report_date,
                  "net_profit": r.net_profit_sum,
                  "sample_count": r.sample_count} for r in fin_rows],
            )
            pe_by_date = {
                str(p["date"])[:10]: p["pe"] for p in pe_series
            }
            # 删旧重写：清掉上一轮可能写入的低覆盖点，再写达标点
            idx_repo.delete_index_mv(it.code)
            bulk = [
                {"symbol": it.code, "trade_date": p["date"],
                 "total_mv": round(p["total_mv"] / 1e8, 4),
                 "pe_ttm": (round(v, 2)
                            if (v := pe_by_date.get(str(p["date"])[:10]))
                            is not None else None),
                 "source": "computed"}
                for p in monthly
            ]
            if bulk:
                idx_repo.bulk_upsert_index_mv(bulk)
            results[it.code] = len(bulk)
            pe_n = sum(1 for r in bulk if r["pe_ttm"] is not None)
            span = (f"{monthly[0]['date']}~{monthly[-1]['date']}"
                    if monthly else "none")
            log.info("[idx_mv] %s: %d monthly points, pe %d (%s)",
                     it.code, len(bulk), pe_n, span)
        except Exception as e:  # noqa: BLE001
            log.warning("[idx_mv] %s failed: %s", it.code, e)
            results[it.code] = 0
    return results
