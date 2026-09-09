"""
长期投资组合回测路由
====================
GET  /api/v1/lt-backtest/algorithms — 7 种经典长期策略元数据（原理卡片）
POST /api/v1/lt-backtest/backtest   — 运行长期组合回测（日线，纯计算不落库）

经典长期投资算法：双动量 / 均线趋势 / 全天候 / 估值定投 / 神奇公式 /
F-Score 价值 / 红利。支持多标的组合、定期调仓、目标权重、A 股成本、
基准对比（alpha/beta）。价值类策略需先同步基本面数据（fundamentals.py）。
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field
import psycopg2
from psycopg2.extras import RealDictCursor

from src.domain.market.strategy.longterm.portfolio_backtester import (
    PortfolioBacktester,
)
from src.domain.market.strategy.longterm.strategies import (
    algorithm_metas,
    build_strategy,
)
from src.domain.market.sync.providers.akshare_provider import AkshareProvider
from src.domain.market.sync.sync_provider import OHLCVBar
from src.infra.database.sql_engine.dsn import get_dsn
from src.pkg import responses

log = logging.getLogger(__name__)

router = APIRouter(prefix="/lt-backtest", tags=["lt-backtest"])


# ── 请求/响应模型 ──────────────────────────────────────────────────────────────


class LTBacktestRequest(BaseModel):
    """长期组合回测请求。"""
    strategy: str = "dual_momentum"      # 7 选 1
    symbols: list[str] = Field(          # 股票池（带前缀 sh/sz）
        default_factory=lambda: ["sh000300"]
    )
    benchmark: str = "sh000300"          # 基准（沪深300 买入持有）
    start_date: str = ""                 # YYYY-MM-DD
    end_date: str = ""                   # YYYY-MM-DD
    initial_capital: float = 1_000_000.0
    commission_rate: float = 0.0003      # 佣金 万3
    slippage: float = 0.0001             # 滑点
    rebalance_freq: Optional[str] = None # 覆盖策略默认频率
    params: dict = Field(default_factory=dict)   # 策略特定参数
    name: Optional[str] = None           # 回测命名（历史列表展示用）
    save: bool = True                    # 是否落库到历史


class LTOptimizeRequest(BaseModel):
    """长期策略参数寻优请求。"""
    strategy: str = "magic_formula"       # 寻优的策略名
    symbols: list[str] = Field(default_factory=lambda: ["sh510300"])
    benchmark: str = "sh000300"
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 1_000_000.0
    commission_rate: float = 0.0003
    slippage: float = 0.0001
    metric: str = "sharpe_ratio"          # sharpe_ratio/cagr/total_return_pct/sortino_ratio/max_drawdown/alpha
    top_k: int = 10                       # 对比表返回前 K 组合
    param_grid: Optional[dict[str, list]] = None  # 空 = 自动从 ParamSpec 派生


# ── 数据获取：日线（DB 优先，akshare 回退）──────────────────────────────────


def _fetch_daily_from_db(
    symbols: list[str], start_date: str, end_date: str
) -> dict[str, list[OHLCVBar]]:
    """从本地 stock_ohlcv 表读日线。返回 {symbol: [OHLCVBar]}。"""
    out: dict[str, list[OHLCVBar]] = {}
    try:
        conn = psycopg2.connect(get_dsn())
    except Exception:
        return out
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 单查询批量取（原来逐 symbol 一条 SQL，N 个标的就是 N 次往返）
            cur.execute(
                """
                SELECT symbol, trade_date, open_, close_, high_, low_, volume, amount, market
                FROM stock_ohlcv
                WHERE symbol = ANY(%s)
                  AND trade_date >= %s
                  AND trade_date <= %s
                ORDER BY symbol, trade_date ASC
                """,
                (
                    symbols,
                    f"{start_date} 00:00:00",
                    f"{end_date} 23:59:59",
                ),
            )
            rows = cur.fetchall()
    except Exception:
        pass
    else:
        bars_by_sym: dict[str, list[OHLCVBar]] = {s: [] for s in symbols}
        for r in rows:
            t = r["trade_date"]
            if hasattr(t, "to_pydatetime"):
                t = t.to_pydatetime()
            bars_by_sym[r["symbol"]].append(
                OHLCVBar(
                    symbol=r["symbol"],
                    trade_time=t,
                    open_=float(r["open_"]),
                    close_=float(r["close_"]),
                    high_=float(r["high_"]),
                    low_=float(r["low_"]),
                    volume=float(r["volume"]),
                    amount=float(r.get("amount") or 0.0),
                    interval="1d",
                    market=r.get("market") or "A",
                    provider="db",
                )
            )
        out.update(bars_by_sym)
    finally:
        conn.close()
    return out


def _fetch_daily_from_akshare(
    symbols: list[str], start_date: str, end_date: str
) -> dict[str, list[OHLCVBar]]:
    """akshare 兜底拉日线。"""
    provider = AkshareProvider()
    out: dict[str, list[OHLCVBar]] = {}
    for sym in symbols:
        bars = provider.fetch_daily_range(
            symbol=sym,
            start_date=start_date or None,
            end_date=end_date or None,
        )
        out[sym] = bars
    return out


def _fetch_valuation_from_db(
    symbols: list[str], start_date: str, end_date: str
) -> dict[str, list[dict]]:
    """从 stock_valuation 表读估值历史（价值策略用）。"""
    out: dict[str, list[dict]] = {}
    try:
        conn = psycopg2.connect(get_dsn())
    except Exception:
        return out
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 单查询批量取（ANY 数组参数，按 symbol 分组）
            cur.execute(
                """
                SELECT symbol, trade_date, pe, pe_ttm, pb, ps, ps_ttm,
                       dv_ratio, dv_ttm, total_mv
                FROM stock_valuation
                WHERE symbol = ANY(%s)
                  AND trade_date >= %s
                  AND trade_date <= %s
                ORDER BY symbol, trade_date ASC
                """,
                (symbols, start_date, end_date),
            )
            rows = cur.fetchall()
    except Exception:
        pass
    else:
        for r in rows:
            out.setdefault(r["symbol"], []).append(
                {
                    "trade_date": r["trade_date"],
                    "pe": r.get("pe"),
                    "pe_ttm": r.get("pe_ttm"),
                    "pb": r.get("pb"),
                    "ps": r.get("ps"),
                    "ps_ttm": r.get("ps_ttm"),
                    "dv_ratio": r.get("dv_ratio"),
                    "dv_ttm": r.get("dv_ttm"),
                    "total_mv": r.get("total_mv"),
                }
            )
    finally:
        conn.close()
    return out


def _fetch_financials_from_db(
    symbols: list[str]
) -> dict[str, list[dict]]:
    """从 stock_financials 表读财务历史（价值策略用）。"""
    out: dict[str, list[dict]] = {}
    try:
        conn = psycopg2.connect(get_dsn())
    except Exception:
        return out
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 单查询批量取（ANY 数组参数，按 symbol 分组）
            cur.execute(
                """
                SELECT symbol, report_date, roe_weighted, roe_diluted,
                       gross_margin, net_margin, debt_ratio
                FROM stock_financials
                WHERE symbol = ANY(%s)
                ORDER BY symbol, report_date ASC
                """,
                (symbols,),
            )
            rows = cur.fetchall()
    except Exception:
        pass
    else:
        for r in rows:
            out.setdefault(r["symbol"], []).append(
                {
                    "report_date": r["report_date"],
                    "roe_weighted": r.get("roe_weighted"),
                    "roe_diluted": r.get("roe_diluted"),
                    "gross_margin": r.get("gross_margin"),
                    "net_margin": r.get("net_margin"),
                    "debt_ratio": r.get("debt_ratio"),
                }
            )
    finally:
        conn.close()
    return out


def _fetch_index_daily(benchmark: str, start_date: str, end_date: str):
    """拉基准指数日线（DB 优先，akshare 回退）。"""
    # 先试 index_ohlcv 表
    try:
        conn = psycopg2.connect(get_dsn())
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT trade_date, open_, close_, high_, low_, volume, amount
                FROM index_ohlcv
                WHERE symbol = %s AND trade_date >= %s AND trade_date <= %s
                ORDER BY trade_date ASC
                """,
                (benchmark, start_date, end_date),
            )
            rows = cur.fetchall()
            conn.close()
            if rows:
                return [
                    OHLCVBar(
                        symbol=benchmark,
                        trade_time=(
                            r["trade_date"].to_pydatetime()
                            if hasattr(r["trade_date"], "to_pydatetime")
                            else r["trade_date"]
                        ),
                        open_=float(r["open_"]),
                        close_=float(r["close_"]),
                        high_=float(r["high_"]),
                        low_=float(r["low_"]),
                        volume=float(r["volume"]),
                        amount=float(r.get("amount") or 0.0),
                        interval="1d",
                        market="INDEX",
                        provider="db",
                    )
                    for r in rows
                ]
    except Exception:
        pass
    # akshare 回退
    try:
        provider = AkshareProvider()
        return provider.fetch_index_daily(
            symbol=benchmark,
            start_date=start_date or None,
            end_date=end_date or None,
        )
    except Exception:
        return []


# ── 端点 ────────────────────────────────────────────────────────────────────────


@router.get("/algorithms")
def list_algorithms():
    """7 种经典长期策略的元数据：原理、适用行情、优缺点、参数规格。"""
    return {"code": 0, "msg": "ok", "data": algorithm_metas()}


@router.post("/backtest")
def run_lt_backtest(req: LTBacktestRequest):
    """
    运行长期组合回测。

    流程：拉日线 → （价值策略）拉基本面 → 构建策略 → 组合引擎执行
          → 返回收益指标 + 权益曲线 + 调仓明细。
    """
    # 1. 校验策略名
    try:
        strategy = build_strategy(req.strategy, req.params)
    except ValueError as e:
        return {"code": 1, "msg": str(e), "data": None}

    # 覆盖调仓频率
    if req.rebalance_freq:
        strategy.rebalance_freq = req.rebalance_freq

    # 2. 拉日线：DB 优先，akshare 回退
    sd = req.start_date or "2000-01-01"
    ed = req.end_date or "2099-12-31"
    symbols = req.symbols or [getattr(strategy, "symbol", None)]
    symbols = [s for s in symbols if s]

    bars_by_symbol = _fetch_daily_from_db(symbols, sd, ed)
    source = "本地数据库"
    missing = [s for s in symbols if not bars_by_symbol.get(s)]
    if missing:
        ak_bars = _fetch_daily_from_akshare(missing, sd, ed)
        for s, bs in ak_bars.items():
            if bs:
                bars_by_symbol[s] = bs
        source = "本地数据库+akshare"

    if not any(bars_by_symbol.values()):
        return {
            "code": 1,
            "msg": (
                f"未获取到任何日线数据（{symbols}），"
                "请检查股票代码与日期范围"
            ),
            "data": None,
        }

    # 3. 价值策略：拉基本面
    valuation_by_symbol = None
    financials_by_symbol = None
    if getattr(strategy, "needs_fundamentals", False):
        valuation_by_symbol = _fetch_valuation_from_db(symbols, sd, ed)
        financials_by_symbol = _fetch_financials_from_db(symbols)
        if not any(valuation_by_symbol.values()):
            return {
                "code": 1,
                "msg": (
                    f"策略 {req.strategy} 需要基本面数据，但本地库无估值历史。"
                    "请先运行: python -m src.domain.market.sync.jobs.fundamentals"
                ),
                "data": None,
            }

    # 4. 拉基准
    benchmark_bars = _fetch_index_daily(req.benchmark, sd, ed)

    # 5. 运行引擎
    bt = PortfolioBacktester(
        initial_capital=req.initial_capital,
        commission_rate=req.commission_rate,
        slippage=req.slippage,
    )
    result = bt.run(
        strategy=strategy,
        bars_by_symbol=bars_by_symbol,
        valuation_by_symbol=valuation_by_symbol,
        financials_by_symbol=financials_by_symbol,
        benchmark_bars=benchmark_bars or None,
    )

    log.info(
        "[长期回测] %s symbols=%s %s→%s [%s] rebalances=%d trades=%d ret=%.2f%%",
        req.strategy, symbols, sd, ed, source,
        result.rebalance_count, result.total_trades, result.total_return_pct,
    )

    data = result.to_dict()

    # 落库到历史（默认开启）
    if req.save:
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
                source="lt_backtest",
                strategy=req.strategy,
                name=req.name or "",
                params={
                    **req.model_dump(),
                    "data_source": source,
                },
                benchmark=req.benchmark,
            )
            data["result_id"] = repo.save(record)
        except Exception as e:
            log.warning("[长期回测] 落库失败（不影响结果返回）: %s", e)

    return {"code": 0, "msg": "ok", "data": data}


# ── 参数寻优 ──────────────────────────────────────────────────────────────────


@router.post("/optimize")
def optimize_strategy(req: LTOptimizeRequest):
    """
    长期策略参数寻优。

    流程：拉数据（同 backtest）→ 网格展开参数组合 → 每组合跑回测
          → 按 metric 排序 → 返回最优组合完整结果 + 对比表。
    """
    from src.domain.market.strategy.longterm.optimizer import (
        SUPPORTED_METRICS,
        LongTermGridOptimizer,
    )

    if req.metric not in SUPPORTED_METRICS:
        return {
            "code": 1,
            "msg": f"不支持的指标 '{req.metric}'，可用: {list(SUPPORTED_METRICS)}",
            "data": None,
        }

    # 校验策略名
    try:
        build_strategy(req.strategy, {})
    except ValueError as e:
        return {"code": 1, "msg": str(e), "data": None}

    # 拉数据（复用 backtest 的数据获取逻辑）
    sd = req.start_date or "2000-01-01"
    ed = req.end_date or "2099-12-31"
    symbols = req.symbols or []

    bars_by_symbol = _fetch_daily_from_db(symbols, sd, ed)
    missing = [s for s in symbols if not bars_by_symbol.get(s)]
    if missing:
        ak_bars = _fetch_daily_from_akshare(missing, sd, ed)
        for s, bs in ak_bars.items():
            if bs:
                bars_by_symbol[s] = bs

    if not any(bars_by_symbol.values()):
        return {"code": 1, "msg": f"未获取到日线数据（{symbols}）", "data": None}

    valuation_by_symbol = None
    financials_by_symbol = None
    # 价值策略需要基本面
    try:
        probe = build_strategy(req.strategy, {})
        if getattr(probe, "needs_fundamentals", False):
            valuation_by_symbol = _fetch_valuation_from_db(symbols, sd, ed)
            financials_by_symbol = _fetch_financials_from_db(symbols)
            if not any(valuation_by_symbol.values()):
                return {
                    "code": 1,
                    "msg": (
                        f"策略 {req.strategy} 需基本面数据，本地库无估值历史。"
                        "请先运行 fundamentals 同步任务"
                    ),
                    "data": None,
                }
    except Exception:
        pass

    benchmark_bars = _fetch_index_daily(req.benchmark, sd, ed) or None

    # 运行寻优
    optimizer = LongTermGridOptimizer(
        strategy_name=req.strategy,
        param_grid=req.param_grid,
        metric=req.metric,
        top_k=req.top_k,
        backtester_kwargs={
            "initial_capital": req.initial_capital,
            "commission_rate": req.commission_rate,
            "slippage": req.slippage,
        },
    )
    result = optimizer.optimize(
        bars_by_symbol=bars_by_symbol,
        valuation_by_symbol=valuation_by_symbol,
        financials_by_symbol=financials_by_symbol,
        benchmark_bars=benchmark_bars,
    )

    log.info(
        "[长期寻优] %s metric=%s 组合数=%d best_params=%s",
        req.strategy, req.metric, result.total_combos, result.best_params,
    )

    return {"code": 0, "msg": "ok", "data": result.to_dict()}


# ── 回测历史 / 对比 / 有效前沿 ──────────────────────────────────────────────────


class CompareRequest(BaseModel):
    """多次回测对比请求。"""
    ids: list[int] = Field(default_factory=list)


class EfficientFrontierRequest(BaseModel):
    """有效前沿资产配置工具请求。"""
    symbols: list[str] = Field(default_factory=lambda: ["sh510300", "sh518880"])
    start_date: str = ""
    end_date: str = ""
    lookback: int = 120
    max_weight: float = 0.4
    cash_buffer: float = 0.05
    n_points: int = 25
    risk_free_rate: float = 0.0


class WalkForwardRequest(BaseModel):
    """Walk-forward 滚动寻优请求。"""
    strategy: str = "dual_momentum"
    symbols: list[str] = Field(default_factory=lambda: ["sh510300", "sh511010"])
    benchmark: str = "sh000300"
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 1_000_000.0
    commission_rate: float = 0.0003
    slippage: float = 0.0001
    param_grid: Optional[dict] = None
    train_days: int = 504
    test_days: int = 126
    step_days: int = 126
    metric: str = "sharpe_ratio"
    save: bool = False
    name: Optional[str] = None


def _bt_repo():
    """惰性创建仓储（避免 import 时连 DB）。"""
    from src.infra.database.strategy.repository import (
        create_portfolio_backtest_repository,
    )
    return create_portfolio_backtest_repository()


@router.get("/results")
def list_results(
    strategy: Optional[str] = None,
    source: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    page: int = 1,
    size: int = 20,
):
    """回测历史列表（分页 + 筛选，只返摘要指标）。"""
    try:
        repo = _bt_repo()
        records, total = repo.list_results(
            strategy=strategy, source=source, start=start, end=end,
            page=page, size=size,
        )
        return responses.page_success(
            [r.summary() for r in records], total, size, page
        )
    except Exception as e:
        log.warning("[回测历史] 列表失败: %s", e)
        return responses.fail(msg=f"列表失败: {e}")


@router.get("/results/{result_id}")
def get_result(result_id: int):
    """单次回测详情（含 equity_curve / trades）。"""
    try:
        repo = _bt_repo()
        rec = repo.get(result_id)
        if not rec:
            return responses.fail(msg=f"回测结果 {result_id} 不存在", code=1)
        return responses.success(rec.full())
    except Exception as e:
        log.warning("[回测历史] 详情失败: %s", e)
        return responses.fail(msg=f"详情失败: {e}")


@router.post("/compare")
def compare_results(req: CompareRequest):
    """多次回测对比：叠加权益曲线 + 指标对比表。"""
    if not req.ids or len(req.ids) < 2:
        return responses.fail(msg="至少选 2 条回测进行对比")
    if len(req.ids) > 10:
        return responses.fail(msg="最多对比 10 条回测")
    try:
        repo = _bt_repo()
        records = repo.get_many(req.ids)
        if len(records) < 2:
            return responses.fail(msg="有效回测不足 2 条")
        # 指标对比表：每行一个 run
        metrics_table = [
            {
                "id": r.id,
                "name": r.name,
                "strategy": r.strategy,
                "total_return_pct": round(r.total_return_pct, 2),
                "cagr": round(r.cagr, 2),
                "sharpe_ratio": round(r.sharpe_ratio, 3),
                "sortino_ratio": round(r.sortino_ratio, 3),
                "max_drawdown": round(r.max_drawdown, 2),
                "volatility": round(r.volatility, 2),
                "alpha": round(r.alpha, 4),
                "beta": round(r.beta, 4),
                "benchmark_return_pct": round(r.benchmark_return_pct, 2),
            }
            for r in records
        ]
        # 权益叠加：归一化到起点=1.0，便于跨 run 比较
        equity_overlay = []
        for r in records:
            curve = r.equity_curve or []
            if not curve:
                continue
            base = curve[0].get("equity", 1.0) if isinstance(curve[0], dict) else 1.0
            if not base or base <= 0:
                base = 1.0
            equity_overlay.append({
                "id": r.id,
                "name": r.name,
                "strategy": r.strategy,
                "curve": [
                    {
                        "date": pt.get("date", ""),
                        "nav": round(
                            pt.get("equity", 0) / base, 4
                        ) if isinstance(pt, dict) else None,
                    }
                    for pt in curve if isinstance(pt, dict)
                ],
            })
        return responses.success({
            "metrics_table": metrics_table,
            "equity_overlay": equity_overlay,
        })
    except Exception as e:
        log.warning("[回测对比] 失败: %s", e)
        return responses.fail(msg=f"对比失败: {e}")


@router.delete("/results/{result_id}")
def delete_result(result_id: int):
    """删除一次回测。"""
    try:
        repo = _bt_repo()
        ok = repo.delete(result_id)
        if not ok:
            return responses.fail(msg=f"回测结果 {result_id} 不存在")
        return responses.success({"deleted": True, "id": result_id})
    except Exception as e:
        log.warning("[回测历史] 删除失败: %s", e)
        return responses.fail(msg=f"删除失败: {e}")


@router.post("/efficient-frontier")
def efficient_frontier(req: EfficientFrontierRequest):
    """有效前沿资产配置工具（纯计算，不跑回测）。

    拉各标的日线 → 估计协方差/预期收益 → 采样前沿 → 标注最小方差/最大夏普点。
    """
    from src.domain.market.strategy.optimization.mvo import (
        efficient_frontier_compute,
    )

    sd = req.start_date or "2000-01-01"
    ed = req.end_date or "2099-12-31"
    symbols = req.symbols or []
    if len(symbols) < 2:
        return responses.fail(msg="有效前沿至少需要 2 个标的")

    bars_by_symbol = _fetch_daily_from_db(symbols, sd, ed)
    missing = [s for s in symbols if not bars_by_symbol.get(s)]
    if missing:
        ak_bars = _fetch_daily_from_akshare(missing, sd, ed)
        for s, bs in ak_bars.items():
            if bs:
                bars_by_symbol[s] = bs
    if not any(bars_by_symbol.values()):
        return responses.fail(msg=f"未获取到日线数据（{symbols}）")

    try:
        data = efficient_frontier_compute(
            bars_by_symbol,
            lookback=req.lookback,
            max_weight=req.max_weight,
            cash_buffer=req.cash_buffer,
            n_points=req.n_points,
            risk_free_rate=req.risk_free_rate,
        )
        return responses.success(data)
    except Exception as e:
        log.warning("[有效前沿] 计算失败: %s", e)
        return responses.fail(msg=f"有效前沿计算失败: {e}")


# ── Walk-Forward 滚动寻优 ──────────────────────────────────────────────────────


@router.post("/walk-forward")
def run_walk_forward(req: WalkForwardRequest):
    """Walk-forward 滚动寻优 + 过拟合检测。

    滑动窗口：训练段网格寻优选最优参数 → 测试段验证 → 拼接 OOS 曲线
    → 计算 walk-forward 效率 / 参数稳定性等过拟合度量。
    """
    from src.domain.market.strategy.longterm.walk_forward import (
        WalkForwardConfig,
        run_walk_forward as _wf,
    )

    # 校验策略名
    try:
        build_strategy(req.strategy, {})
    except ValueError as e:
        return {"code": 1, "msg": str(e), "data": None}

    sd = req.start_date or "2000-01-01"
    ed = req.end_date or "2099-12-31"
    symbols = req.symbols or []

    bars_by_symbol = _fetch_daily_from_db(symbols, sd, ed)
    missing = [s for s in symbols if not bars_by_symbol.get(s)]
    if missing:
        ak_bars = _fetch_daily_from_akshare(missing, sd, ed)
        for s, bs in ak_bars.items():
            if bs:
                bars_by_symbol[s] = bs
    if not any(bars_by_symbol.values()):
        return {"code": 1, "msg": f"未获取到日线数据（{symbols}）", "data": None}

    benchmark_bars = _fetch_index_daily(req.benchmark, sd, ed) or None

    config = WalkForwardConfig(
        train_days=req.train_days,
        test_days=req.test_days,
        step_days=req.step_days,
        metric=req.metric,
        param_grid=req.param_grid,
    )
    try:
        result = _wf(
            config=config,
            strategy_name=req.strategy,
            bars_by_symbol=bars_by_symbol,
            benchmark_bars=benchmark_bars,
            backtester_kwargs={
                "initial_capital": req.initial_capital,
                "commission_rate": req.commission_rate,
                "slippage": req.slippage,
            },
        )
    except Exception as e:
        log.warning("[walk-forward] 失败: %s", e)
        return responses.fail(msg=f"walk-forward 失败: {e}")

    data = result.to_dict()

    # 可选落库：把 OOS 聚合曲线作为一条回测存入历史
    if req.save and result.oos_equity_curve:
        try:
            from src.domain.market.strategy.longterm.models import LongTermResult
            from src.domain.market.strategy.portfolio_backtest_repository_interface import (  # noqa: E501
                PortfolioBacktestRecord,
            )
            from src.infra.database.strategy.repository import (
                create_portfolio_backtest_repository,
            )
            agg = result.aggregated
            navs = [p["nav"] for p in result.oos_equity_curve]
            synthetic = LongTermResult(
                strategy=f"{req.strategy}_walkforward",
                symbols=symbols,
                start_date=result.windows[0].train_start if result.windows else "",
                end_date=result.windows[-1].test_end if result.windows else "",
                initial_capital=req.initial_capital,
                final_equity=req.initial_capital * (navs[-1] if navs else 1.0),
                total_return_pct=agg.get("total_return_pct", 0.0),
                cagr=agg.get("cagr", 0.0),
                sharpe_ratio=agg.get("sharpe_ratio", 0.0),
                max_drawdown=agg.get("max_drawdown", 0.0),
                equity_curve=result.oos_equity_curve,
            )
            repo = create_portfolio_backtest_repository()
            rec = PortfolioBacktestRecord.from_result(
                synthetic, source="optimizer",
                strategy=f"{req.strategy}_walkforward",
                name=req.name or f"{req.strategy} walk-forward",
                params={
                    "train_days": req.train_days, "test_days": req.test_days,
                    "step_days": req.step_days, "metric": req.metric,
                    "overfitting": result.overfitting,
                },
                benchmark=req.benchmark,
            )
            data["result_id"] = repo.save(rec)
        except Exception as e:
            log.warning("[walk-forward] 落库失败: %s", e)

    log.info(
        "[walk-forward] %s windows=%d skipped=%d wfe=%s",
        req.strategy, result.n_windows, result.skipped,
        result.overfitting.get("walk_forward_efficiency"),
    )
    return responses.success(data)


# ── 回测收益归因 ───────────────────────────────────────────────────────────────


class AttributionRequest(BaseModel):
    """回测收益归因请求（直接传结果，不依赖已落库）。"""
    result: dict = Field(default_factory=dict)
    symbols: list[str] = Field(default_factory=list)
    start_date: str = ""
    end_date: str = ""


@router.post("/attribution")
def attribution_direct(req: AttributionRequest):
    """对传入的回测结果做收益归因（逐标的贡献 + 行业聚合 + 配置/选择效应）。

    result: 回测结果字典（含 rebalances/equity_curve）；symbols/日期用于拉价格。
    """
    from src.domain.market.strategy.longterm.attribution import (
        compute_attribution,
    )

    result_dict = req.result or {}
    syms = req.symbols or result_dict.get("symbols", [])
    sd = req.start_date or result_dict.get("start_date", "2000-01-01")
    ed = req.end_date or result_dict.get("end_date", "2099-12-31")
    if not syms:
        return responses.fail(msg="缺少 symbols，无法归因")

    bars_by_symbol = _fetch_daily_from_db(syms, sd, ed)
    try:
        data = compute_attribution(result_dict, bars_by_symbol)
        return responses.success(data)
    except Exception as e:
        log.warning("[归因] 失败: %s", e)
        return responses.fail(msg=f"归因失败: {e}")


@router.post("/results/{result_id}/attribution")
def attribution_by_id(result_id: int):
    """对已持久化的回测结果做收益归因。"""
    try:
        repo = _bt_repo()
        rec = repo.get(result_id)
        if not rec:
            return responses.fail(msg=f"回测结果 {result_id} 不存在")
        from src.domain.market.strategy.longterm.attribution import (
            compute_attribution,
        )
        syms = rec.symbols or []
        sd = rec.start_date or "2000-01-01"
        ed = rec.end_date or "2099-12-31"
        bars_by_symbol = _fetch_daily_from_db(syms, sd, ed) if syms else {}
        result_dict = rec.full()
        data = compute_attribution(result_dict, bars_by_symbol)
        return responses.success(data)
    except Exception as e:
        log.warning("[归因] 失败: %s", e)
        return responses.fail(msg=f"归因失败: {e}")
