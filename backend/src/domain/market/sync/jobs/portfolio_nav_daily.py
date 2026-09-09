"""
Portfolio NAV Daily
===================
每日组合净值物化 job（供 cron 调用, 在 portfolio_daily 之后运行）。

对每个 is_active=true 的组合:
  1. 读取 holdings + 各标的当日收盘价(原币种) + 汇率(→CNY)
  2. 调 nav_calculator 算净值/实际权重/偏离
  3. 写入 portfolio_nav + portfolio_nav_item

trade_date 策略: 取标的池中最新的共同交易日(用最大标的的最新交易日)。
某个标的当日无收盘价时, 取其最近交易日收盘价(与停牌处理一致)。

crontab 示例（工作日 17:00, 行情同步后）:
  0 17 * * 1-5 cd /path/backend && .venv/bin/python -m src.domain.market.sync.jobs.portfolio_nav_daily >> logs/portfolio_nav.log 2>&1
"""
import logging
import sys
import datetime as dt
from pathlib import Path
from typing import Optional

_BACKEND = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.portfolio.nav_calculator import (
    NavItemInput,
    calc_portfolio_nav,
)
from src.infra.database.market.fx_rate import create_fx_rate_repository
from src.infra.database.portfolio.repository import (
    create_portfolio_repository,
)

log = logging.getLogger("portfolio_nav")


def _resolve_trade_date(repo, holdings) -> Optional[dt.date]:
    """确定核算交易日: 取各持仓标的中"最新交易日"的最小值。

    即所有标的都有数据的最近日期。若某标的完全没有数据(新上市/未同步),
    用其他标的的最新日期兜底。
    """
    dates = []
    for h in holdings:
        inst = repo.get_instrument(h.instrument_id)
        if inst:
            d = repo.get_latest_price_date(inst.symbol)
            if d:
                dates.append(d)
    if not dates:
        return None
    return min(dates)  # 最保守: 取共同最新日


def _calc_one_portfolio(portfolio, repo, fx_repo, trade_date) -> None:
    """算单个组合的净值并写入。"""
    holdings = repo.list_holdings(portfolio.id)
    if not holdings:
        log.warning(
            f"[portfolio={portfolio.id}] 无持仓, 跳过"
        )
        return

    items_in: list[NavItemInput] = []
    for h in holdings:
        inst = repo.get_instrument(h.instrument_id)
        if not inst:
            log.warning(
                f"[portfolio={portfolio.id}] "
                f"instrument_id={h.instrument_id} 不存在, 跳过"
            )
            continue

        # 收盘价(原币种): 取 trade_date 或最近交易日
        price = repo.get_close_price(inst.symbol, trade_date)
        if price is None:
            log.warning(
                f"[portfolio={portfolio.id} {inst.symbol}] "
                f"无收盘价(trade_date={trade_date}), 跳过该标的"
            )
            continue

        # 汇率: CNY=1.0, 其余从 fx_rate 取
        if inst.ccy == "CNY":
            fx = 1.0
        else:
            pair = f"{inst.ccy}CNY"
            fx = fx_repo.get_rate(pair, trade_date)
            if fx is None:
                log.warning(
                    f"[portfolio={portfolio.id} {inst.symbol}] "
                    f"汇率 {pair} 缺失(trade_date={trade_date}), "
                    f"跳过该标的"
                )
                continue

        items_in.append(
            NavItemInput(
                instrument_id=inst.id,
                symbol=inst.symbol,
                asset_class=inst.asset_class,
                target_weight=h.target_weight,
                shares=h.shares,
                price=price,
                fx_rate=fx,
            )
        )

    if not items_in:
        log.warning(
            f"[portfolio={portfolio.id}] 无可用行情, 跳过"
        )
        return

    # 上一交易日净值(用于算日收益率)
    prev_nav = repo.get_latest_nav(portfolio.id)
    prev_nav_cny = prev_nav.nav_cny if prev_nav else None

    result = calc_portfolio_nav(
        initial_capital=portfolio.initial_capital,
        threshold=portfolio.rebalance_threshold,
        items_in=items_in,
        prev_nav_cny=prev_nav_cny,
    )

    # 构造明细写入
    items_out = [
        {
            "instrument_id": it.instrument_id,
            "symbol": it.symbol,
            "asset_class": it.asset_class,
            "shares": it.shares,
            "price": it.price,
            "price_cny": it.price_cny,
            "fx_rate": it.fx_rate,
            "value_cny": it.value_cny,
            "target_weight": it.target_weight,
            "actual_weight": it.actual_weight,
            "drift": it.drift,
        }
        for it in result.items
    ]

    repo.save_nav(
        portfolio_id=portfolio.id,
        trade_date=trade_date,
        nav_cny=result.nav_cny,
        prev_nav_cny=result.prev_nav_cny,
        daily_return=result.daily_return,
        total_value_cny=result.total_value_cny,
        max_drift=result.max_drift,
        rebalance_suggested=result.rebalance_suggested,
        items=items_out,
    )

    log.info(
        f"[portfolio={portfolio.id} {portfolio.name}] "
        f"date={trade_date} nav={result.nav_cny:.4f} "
        f"max_drift={result.max_drift:.4f} "
        f"rebalance={'是' if result.rebalance_suggested else '否'}"
    )


def run(target_date: Optional[dt.date] = None) -> None:
    """算所有活跃组合的净值。

    Args:
        target_date: 指定交易日; None 则自动取各标的最新共同交易日。
    """
    repo = create_portfolio_repository()
    fx_repo = create_fx_rate_repository()

    portfolios = repo.list_portfolios(active_only=True)
    if not portfolios:
        log.info("无活跃组合, 跳过")
        return

    for portfolio in portfolios:
        if target_date is not None:
            trade_date = target_date
        else:
            holdings = repo.list_holdings(portfolio.id)
            trade_date = _resolve_trade_date(repo, holdings)
        if trade_date is None:
            log.warning(
                f"[portfolio={portfolio.id}] 无法确定交易日, 跳过"
            )
            continue

        # 跳过已物化的日期(避免重复算; 除非要覆盖, 走 save_nav 自带覆盖)
        existing = repo.get_nav_history(
            portfolio.id,
            start_date=trade_date,
            end_date=trade_date,
        )
        if existing:
            log.info(
                f"[portfolio={portfolio.id}] {trade_date} 已有净值, 覆盖"
            )

        _calc_one_portfolio(portfolio, repo, fx_repo, trade_date)

    log.info("portfolio nav daily complete")


if __name__ == "__main__":
    run()
