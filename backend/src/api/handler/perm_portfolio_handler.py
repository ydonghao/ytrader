"""永久投资组合 API handler。

遵循项目约定:
- repository 在函数体内延迟 import + 工厂创建
- 返回 responses.success(data) / responses.fail(msg=...)
"""
from typing import Any, Optional
from datetime import date

from src.pkg import responses


# ═══════════════════════════════════════════════════════════════
# 标的池
# ═══════════════════════════════════════════════════════════════

def list_instruments(
    market: Optional[str] = None,
    asset_class: Optional[str] = None,
    enabled_only: bool = False,
) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    insts = repo.list_instruments(
        market=market, asset_class=asset_class, enabled_only=enabled_only
    )
    return responses.success(
        [
            {
                "id": i.id,
                "symbol": i.symbol,
                "market": i.market,
                "asset_class": i.asset_class,
                "ccy": i.ccy,
                "name": i.name,
                "provider": i.provider,
                "enabled": i.enabled,
            }
            for i in insts
        ]
    )


def create_instrument(body: dict) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    required = ("symbol", "market", "asset_class", "ccy", "name")
    for k in required:
        if not body.get(k):
            return responses.fail(msg=f"缺少必填字段: {k}")
    inst = repo.upsert_instrument(
        symbol=body["symbol"],
        market=body["market"],
        asset_class=body["asset_class"],
        ccy=body["ccy"],
        name=body["name"],
        provider=body.get("provider", "akshare"),
        enabled=body.get("enabled", True),
    )
    return responses.success(
        {
            "id": inst.id,
            "symbol": inst.symbol,
            "market": inst.market,
            "asset_class": inst.asset_class,
            "ccy": inst.ccy,
            "name": inst.name,
        }
    )


def update_instrument(instrument_id: int, body: dict) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    inst = repo.get_instrument(instrument_id)
    if not inst:
        return responses.fail(msg="标的不存在")
    # 通过 upsert 更新(保留原 symbol)
    updated = repo.upsert_instrument(
        symbol=inst.symbol,
        market=body.get("market", inst.market),
        asset_class=body.get("asset_class", inst.asset_class),
        ccy=body.get("ccy", inst.ccy),
        name=body.get("name", inst.name),
        enabled=body.get("enabled", inst.enabled),
    )
    return responses.success({"id": updated.id, "enabled": updated.enabled})


def delete_instrument(instrument_id: int) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    ok, msg = repo.delete_instrument(instrument_id)
    if not ok:
        return responses.fail(msg=msg)
    return responses.success({"deleted": True})


# ═══════════════════════════════════════════════════════════════
# 组合定义
# ═══════════════════════════════════════════════════════════════

def list_portfolios(active_only: bool = True) -> Any:
    """组合列表 + 最新净值概要。"""
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    portfolios = repo.list_portfolios(active_only=active_only)
    out = []
    for p in portfolios:
        latest = repo.get_latest_nav(p.id)
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "strategy_type": p.strategy_type,
                "base_ccy": p.base_ccy,
                "rebalance_threshold": p.rebalance_threshold,
                "initial_capital": p.initial_capital,
                "is_active": p.is_active,
                "latest_nav": (
                    {
                        "trade_date": str(latest.trade_date),
                        "nav_cny": latest.nav_cny,
                        "daily_return": latest.daily_return,
                        "max_drift": latest.max_drift,
                        "rebalance_suggested": (
                            latest.rebalance_suggested
                        ),
                    }
                    if latest
                    else None
                ),
            }
        )
    return responses.success(out)


def get_portfolio(portfolio_id: int) -> Any:
    """组合详情: 定义 + 持仓 + 最新净值明细。"""
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    p = repo.get_portfolio(portfolio_id)
    if not p:
        return responses.fail(msg="组合不存在")

    holdings = repo.list_holdings(portfolio_id)
    holdings_out = []
    for h in holdings:
        inst = repo.get_instrument(h.instrument_id)
        holdings_out.append(
            {
                "id": h.id,
                "instrument_id": h.instrument_id,
                "symbol": inst.symbol if inst else None,
                "market": inst.market if inst else None,
                "asset_class": inst.asset_class if inst else None,
                "ccy": inst.ccy if inst else None,
                "name": inst.name if inst else None,
                "target_weight": h.target_weight,
                "shares": h.shares,
                "cost_price": h.cost_price,
            }
        )

    latest = repo.get_latest_nav(portfolio_id)
    latest_items = []
    if latest:
        nav_items = repo.get_nav_items(latest.id)
        latest_items = [
            {
                "symbol": it.symbol,
                "asset_class": it.asset_class,
                "shares": it.shares,
                "price": it.price,
                "price_cny": it.price_cny,
                "value_cny": it.value_cny,
                "target_weight": it.target_weight,
                "actual_weight": it.actual_weight,
                "drift": it.drift,
            }
            for it in nav_items
        ]

    return responses.success(
        {
            "id": p.id,
            "name": p.name,
            "strategy_type": p.strategy_type,
            "base_ccy": p.base_ccy,
            "rebalance_threshold": p.rebalance_threshold,
            "initial_capital": p.initial_capital,
            "is_active": p.is_active,
            "holdings": holdings_out,
            "latest_nav": (
                {
                    "trade_date": str(latest.trade_date),
                    "nav_cny": latest.nav_cny,
                    "daily_return": latest.daily_return,
                    "total_value_cny": latest.total_value_cny,
                    "max_drift": latest.max_drift,
                    "rebalance_suggested": latest.rebalance_suggested,
                    "items": latest_items,
                }
                if latest
                else None
            ),
        }
    )


def create_portfolio(body: dict) -> Any:
    from datetime import date
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    if not body.get("name") or not body.get("strategy_type"):
        return responses.fail(msg="缺少 name 或 strategy_type")
    initial_capital = body.get("initial_capital", 100000.0)
    p = repo.create_portfolio(
        name=body["name"],
        strategy_type=body["strategy_type"],
        base_ccy=body.get("base_ccy", "CNY"),
        rebalance_threshold=body.get("rebalance_threshold", 0.05),
        initial_capital=initial_capital,
        is_active=body.get("is_active", True),
    )
    # 若带 holdings, 一起创建
    holdings = body.get("holdings")
    if holdings:
        # 自动算 shares: 若 holding 没传 shares(或为0), 按
        # initial_capital × target_weight / 最近收盘价 自动计算,
        # cost_price 记为该收盘价。让前端新建弹窗只需选标的+填权重。
        resolved = []
        today = date.today()
        for h in holdings:
            shares = h.get("shares", 0)
            if not shares:
                inst = repo.get_instrument(h["instrument_id"])
                if inst:
                    price = repo.get_close_price(inst.symbol, today)
                    if price and price > 0:
                        shares = int(
                            initial_capital * h["target_weight"] / price
                        )
                        h["cost_price"] = price
                    else:
                        # 无行情数据(新标的未同步), 用占位 100 股
                        shares = 100
                        h["cost_price"] = h.get("cost_price", 0.0)
                else:
                    shares = 100
            h["shares"] = shares
            resolved.append(h)
        repo.set_holdings(p.id, resolved)
    return responses.success({"id": p.id, "name": p.name})


def update_portfolio(portfolio_id: int, body: dict) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    p = repo.update_portfolio(
        portfolio_id,
        name=body.get("name"),
        rebalance_threshold=body.get("rebalance_threshold"),
        initial_capital=body.get("initial_capital"),
        is_active=body.get("is_active"),
    )
    if not p:
        return responses.fail(msg="组合不存在")
    # 若带 holdings, 全量替换
    if body.get("holdings") is not None:
        repo.set_holdings(portfolio_id, body["holdings"])
    return responses.success({"id": p.id})


def delete_portfolio(portfolio_id: int) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    if not repo.get_portfolio(portfolio_id):
        return responses.fail(msg="组合不存在")
    repo.delete_portfolio(portfolio_id)
    return responses.success({"deleted": True})


# ═══════════════════════════════════════════════════════════════
# 持仓桥接(风险/归因仪表盘)
# ═══════════════════════════════════════════════════════════════

def load_bridge_positions(
    portfolio_id: Optional[int],
    repo: Optional[Any] = None,
) -> list[dict]:
    """读 perm-portfolio 真实持仓, 转成风险/归因 positions 口径。

    供 risk_router / portfolio_router 调用(P0 止血: 不再依赖
    无人写入的 positions 表空跑假数据)。

    - portfolio_id 为空时, 取 is_active=True 的第一个组合;
    - 无组合 / 无持仓 / 指定组合不存在时返回 [];
    - repo 可注入(测试用), 默认走 create_portfolio_repository()。

    返回的每项: {symbol, name, quantity, avg_price, current_price,
    market_value, ccy}, 详见 domain 层 position_bridge.build_positions。
    """
    from src.domain.market.portfolio.position_bridge import (
        HoldingInput,
        build_positions,
    )
    if repo is None:
        from src.infra.database.portfolio.repository import (
            create_portfolio_repository,
        )
        repo = create_portfolio_repository()

    try:
        pid = portfolio_id
        if pid is None:
            actives = repo.list_portfolios(active_only=True)
            if not actives:
                return []
            pid = actives[0].id

        holdings = repo.list_holdings(pid)
        if not holdings:
            return []

        inputs: list[HoldingInput] = []
        for h in holdings:
            inst = repo.get_instrument(h.instrument_id)
            if inst is None:
                continue
            inputs.append(
                HoldingInput(
                    symbol=inst.symbol,
                    shares=h.shares,
                    cost_price=h.cost_price,
                    name=inst.name,
                    ccy=inst.ccy,
                )
            )

        today = date.today()

        def _fetch_price(symbol: str) -> Optional[float]:
            return repo.get_close_price(symbol, today)

        return build_positions(inputs, _fetch_price)
    except Exception:
        # 桥接失败(如 DB 不可达)不抛出, 让调用方降级到原行为
        return []


# ═══════════════════════════════════════════════════════════════
# 净值历史
# ═══════════════════════════════════════════════════════════════

def get_nav_history(
    portfolio_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    sd = date.fromisoformat(start_date) if start_date else None
    ed = date.fromisoformat(end_date) if end_date else None
    navs = repo.get_nav_history(portfolio_id, sd, ed)
    return responses.success(
        [
            {
                "trade_date": str(n.trade_date),
                "nav_cny": n.nav_cny,
                "daily_return": n.daily_return,
                "total_value_cny": n.total_value_cny,
                "max_drift": n.max_drift,
                "rebalance_suggested": n.rebalance_suggested,
            }
            for n in navs
        ]
    )


# ═══════════════════════════════════════════════════════════════
# 再平衡建议
# ═══════════════════════════════════════════════════════════════

def get_rebalance_suggestion(portfolio_id: int) -> Any:
    """基于最新净值明细, 实时算再平衡建议。"""
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    from src.domain.market.portfolio.nav_calculator import (
        NavItemOutput,
        AssetClassBreakdown,
    )
    from src.domain.market.portfolio.rebalance_advisor import (
        suggest_rebalance,
    )
    repo = create_portfolio_repository()
    p = repo.get_portfolio(portfolio_id)
    if not p:
        return responses.fail(msg="组合不存在")

    latest = repo.get_latest_nav(portfolio_id)
    if not latest:
        return responses.fail(msg="尚无净值数据, 请先运行净值同步")

    nav_items = repo.get_nav_items(latest.id)

    # 把 nav_item 还原成 NavItemOutput 供 advisor 用
    items_out = [
        NavItemOutput(
            instrument_id=it.instrument_id,
            symbol=it.symbol,
            asset_class=it.asset_class,
            shares=it.shares,
            price=it.price,
            fx_rate=it.fx_rate,
            price_cny=it.price_cny,
            value_cny=it.value_cny,
            target_weight=it.target_weight,
            actual_weight=it.actual_weight,
            drift=it.drift,
        )
        for it in nav_items
    ]

    # 重建 breakdowns(按资产类聚合)
    breakdowns = []
    from src.domain.market.portfolio.nav_calculator import ASSET_CLASSES
    for ac in ASSET_CLASSES:
        ac_items = [it for it in items_out if it.asset_class == ac]
        if not ac_items:
            continue
        tgt = sum(it.target_weight for it in ac_items)
        act = sum(it.actual_weight for it in ac_items)
        breakdowns.append(
            AssetClassBreakdown(
                asset_class=ac,
                target_weight=tgt,
                actual_weight=act,
                drift=act - tgt,
            )
        )

    actions = suggest_rebalance(
        items_out,
        breakdowns,
        latest.total_value_cny,
        p.rebalance_threshold,
    )

    return responses.success(
        {
            "portfolio_id": portfolio_id,
            "trade_date": str(latest.trade_date),
            "total_value_cny": latest.total_value_cny,
            "max_drift": latest.max_drift,
            "threshold": p.rebalance_threshold,
            "rebalance_suggested": latest.rebalance_suggested,
            "breakdowns": [
                {
                    "asset_class": b.asset_class,
                    "target_weight": b.target_weight,
                    "actual_weight": b.actual_weight,
                    "drift": b.drift,
                }
                for b in breakdowns
            ],
            "actions": [
                {
                    "instrument_id": a.instrument_id,
                    "symbol": a.symbol,
                    "asset_class": a.asset_class,
                    "action": a.action,
                    "shares_delta": a.shares_delta,
                    "value_cny": a.value_cny,
                    "reason": a.reason,
                }
                for a in actions
            ],
        }
    )


def apply_rebalance(portfolio_id: int) -> Any:
    """应用再平衡建议: 更新 holdings.shares。"""
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    # 复用 get_rebalance_suggestion 的逻辑
    suggestion = get_rebalance_suggestion(portfolio_id)
    # success 返回的是 JSONResponse, 这里直接重新算
    p = repo.get_portfolio(portfolio_id)
    if not p:
        return responses.fail(msg="组合不存在")
    latest = repo.get_latest_nav(portfolio_id)
    if not latest:
        return responses.fail(msg="尚无净值数据")

    # 调用建议逻辑
    from src.domain.market.portfolio.nav_calculator import (
        NavItemOutput,
        AssetClassBreakdown,
        ASSET_CLASSES,
    )
    from src.domain.market.portfolio.rebalance_advisor import (
        suggest_rebalance,
    )
    nav_items = repo.get_nav_items(latest.id)
    items_out = [
        NavItemOutput(
            instrument_id=it.instrument_id,
            symbol=it.symbol,
            asset_class=it.asset_class,
            shares=it.shares,
            price=it.price,
            fx_rate=it.fx_rate,
            price_cny=it.price_cny,
            value_cny=it.value_cny,
            target_weight=it.target_weight,
            actual_weight=it.actual_weight,
            drift=it.drift,
        )
        for it in nav_items
    ]
    breakdowns = []
    for ac in ASSET_CLASSES:
        ac_items = [it for it in items_out if it.asset_class == ac]
        if not ac_items:
            continue
        tgt = sum(it.target_weight for it in ac_items)
        act = sum(it.actual_weight for it in ac_items)
        breakdowns.append(
            AssetClassBreakdown(ac, tgt, act, act - tgt)
        )
    actions = suggest_rebalance(
        items_out, breakdowns, latest.total_value_cny,
        p.rebalance_threshold,
    )

    # 应用到 holdings
    holdings = repo.list_holdings(portfolio_id)
    holding_by_inst = {h.instrument_id: h for h in holdings}
    applied = 0
    for a in actions:
        h = holding_by_inst.get(a.instrument_id)
        if not h:
            continue
        new_shares = (
            h.shares + a.shares_delta
            if a.action == "BUY"
            else h.shares - a.shares_delta
        )
        new_shares = max(0, new_shares)
        repo.update_holding_shares(h.id, new_shares)
        applied += 1

    return responses.success(
        {"applied_actions": applied, "total_actions": len(actions)}
    )


# ═══════════════════════════════════════════════════════════════
# 回测
# ═══════════════════════════════════════════════════════════════

def backtest_portfolio(portfolio_id: int, body: dict) -> Any:
    """对组合做历史回测(复用 lt-backtest 引擎)。

    body: {start_date?, end_date?, initial_capital?}
        initial_capital 可覆盖组合定义里的默认资金, 让用户自由试算。
    """
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    repo = create_portfolio_repository()
    p = repo.get_portfolio(portfolio_id)
    if not p:
        return responses.fail(msg="组合不存在")

    holdings = repo.list_holdings(portfolio_id)
    if not holdings:
        return responses.fail(msg="组合无持仓")

    # 构造 target_weights {symbol: weight}
    target_weights = {}
    for h in holdings:
        inst = repo.get_instrument(h.instrument_id)
        if inst:
            target_weights[inst.symbol] = h.target_weight

    sd = body.get("start_date", "2015-01-01")
    ed = body.get("end_date", "2099-12-31")
    # 初始资金: body 覆盖 > 组合定义默认值
    initial_capital = body.get("initial_capital")
    if initial_capital is None or float(initial_capital) <= 0:
        initial_capital = p.initial_capital
    else:
        initial_capital = float(initial_capital)

    # 从 stock_ohlcv 加载 bars(复用 lt_backtest_router 的逻辑)
    try:
        from src.api.router.lt_backtest_router import _fetch_daily_from_db
        bars_by_symbol = _fetch_daily_from_db(
            list(target_weights.keys()), sd, ed
        )
    except ImportError:
        return responses.fail(msg="回测引擎不可用")

    missing = [
        s for s in target_weights if not bars_by_symbol.get(s)
    ]
    if missing:
        # 尝试 akshare 兜底
        try:
            from src.api.router.lt_backtest_router import (
                _fetch_daily_from_akshare,
            )
            ak_bars = _fetch_daily_from_akshare(missing, sd, ed)
            for s, bs in ak_bars.items():
                if bs:
                    bars_by_symbol[s] = bs
        except Exception:
            pass

    available = {
        s: b for s, b in bars_by_symbol.items() if b
    }
    if not available:
        return responses.fail(
            msg=f"无可用行情数据(symbols={list(target_weights)})"
        )

    # 构造固定权重策略
    from src.domain.market.portfolio.permanent_strategy import (
        FixedWeightStrategy,
    )
    from src.domain.market.strategy.longterm.portfolio_backtester import (
        PortfolioBacktester,
    )
    strategy = FixedWeightStrategy(p.name, target_weights)
    backtester = PortfolioBacktester(
        initial_capital=initial_capital
    )
    result = backtester.run(strategy=strategy, bars_by_symbol=available)
    data = result.to_dict()

    # 可选落库到回测历史（默认关闭，保持 perm-portfolio 既有行为）
    if body.get("save"):
        try:
            from src.domain.market.strategy.portfolio_backtest_repository_interface import (  # noqa: E501
                PortfolioBacktestRecord,
            )
            from src.infra.database.strategy.repository import (
                create_portfolio_backtest_repository,
            )
            repo = create_portfolio_backtest_repository()
            record = PortfolioBacktestRecord.from_result(
                result,
                source="perm_portfolio",
                strategy="fixed_weight",
                name=body.get("name") or f"{p.name} 回测",
                params={
                    "start_date": sd, "end_date": ed,
                    "initial_capital": initial_capital,
                    "target_weights": target_weights,
                },
                benchmark="",
                portfolio_id=portfolio_id,
            )
            data["result_id"] = repo.save(record)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "[perm-portfolio backtest] 落库失败: %s", e
            )

    return responses.success(data)


def rolling_backtest_portfolio(portfolio_id: int, body: dict) -> Any:
    """滚动窗口累计收益回测(按月滚动)。

    body: {start_date?, end_date?, window_months?}
    从 start_date 开始, 每月作为窗口起点, 算 window_months 个月的
    组合累计收益率, 返回折线图数据。

    优化: 一次性加载全部行情, 内存按月切片算, 避免逐窗口跑交易引擎。
    """
    from datetime import date
    from src.infra.database.portfolio.repository import (
        create_portfolio_repository,
    )
    from src.domain.market.portfolio.rolling_backtest import (
        calc_rolling_returns,
    )
    repo = create_portfolio_repository()
    p = repo.get_portfolio(portfolio_id)
    if not p:
        return responses.fail(msg="组合不存在")

    holdings = repo.list_holdings(portfolio_id)
    if not holdings:
        return responses.fail(msg="组合无持仓")

    # 构造 target_weights + 收集 symbols
    target_weights: dict[str, float] = {}
    symbols_to_inst: dict[str, int] = {}
    for h in holdings:
        inst = repo.get_instrument(h.instrument_id)
        if inst:
            target_weights[inst.symbol] = h.target_weight
            symbols_to_inst[inst.symbol] = inst.id

    sd_str = body.get("start_date", "2016-01-01")
    ed_str = body.get("end_date", "2099-12-31")
    window_months = int(body.get("window_months", 12))
    try:
        start_date = date.fromisoformat(sd_str[:10])
        end_date = date.fromisoformat(ed_str[:10])
    except (ValueError, TypeError):
        return responses.fail(msg="日期格式无效, 需 YYYY-MM-DD")

    # 一次性加载全部标的的全部历史收盘价
    # 用裸 SQL 一次性查, 比 nav_repo 逐个查快得多
    from sqlalchemy import text
    from src.infra.database.sql_engine.engine import create_db_connection
    from src.infra.database.sql_engine.dsn import get_dsn
    db = create_db_connection(get_dsn())
    prices_by_symbol: dict[str, dict] = {}
    with db.session_scope() as s:
        rows = s.execute(
            text(
                "SELECT symbol, trade_date, close_ FROM stock_ohlcv "
                "WHERE symbol = ANY(:syms) "
                "AND trade_date >= :sd AND trade_date <= :ed "
                "ORDER BY symbol, trade_date"
            ),
            {
                "syms": list(target_weights.keys()),
                "sd": f"{sd_str} 00:00:00",
                "ed": f"{ed_str} 23:59:59",
            },
        ).all()
        for row in rows:
            sym = row[0]
            td = row[1]
            if hasattr(td, "date"):
                td = td.date()
            prices_by_symbol.setdefault(sym, {})[td] = float(row[2])

    if not any(prices_by_symbol.values()):
        return responses.fail(msg="无可用行情数据")

    results = calc_rolling_returns(
        prices_by_symbol=prices_by_symbol,
        target_weights=target_weights,
        start_date=start_date,
        end_date=end_date,
        window_months=window_months,
    )

    return responses.success({
        "portfolio_id": portfolio_id,
        "window_months": window_months,
        "start_date": sd_str[:10],
        "end_date": ed_str[:10],
        "windows": [
            {"start": r.start, "end": r.end, "return_pct": r.return_pct}
            for r in results
        ],
        "count": len(results),
    })
