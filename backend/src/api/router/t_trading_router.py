"""
做T算法实验室路由
==================
GET  /api/v1/t-trading/algorithms — 4 种做T算法元数据（原理卡片）
POST /api/v1/t-trading/backtest   — 运行做T回测（分钟线，纯计算不落库）

做T = A 股 T+1 制度下，靠底仓日内高抛低吸降低持仓成本。
本路由返回：算法原理、收益、成本拆解、交易明细，专为金融小白设计。
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field
import psycopg2
from psycopg2.extras import RealDictCursor

from src.domain.market.strategy.t_trading.cost_model import TCostModel
from src.domain.market.strategy.t_trading.t_backtester import TBacktester
from src.domain.market.strategy.t_trading.strategies import (
    algorithm_metas,
    build_strategy,
)
from src.domain.market.sync.providers.akshare_provider import AkshareProvider
from src.domain.market.sync.sync_provider import OHLCVBar
from src.infra.database.sql_engine.dsn import get_dsn

log = logging.getLogger(__name__)

router = APIRouter(prefix="/t-trading", tags=["t-trading"])


# ── 请求/响应模型 ──────────────────────────────────────────────────────────────


class CostOverride(BaseModel):
    """成本模型覆盖（默认填 A 股真实值，前端可调）"""
    commission_rate: float = 0.00025    # 佣金 万2.5
    min_commission: float = 5.0         # 最低 5 元
    stamp_duty_rate: float = 0.0005     # 印花税 0.05%（仅卖出）
    transfer_fee_rate: float = 0.00001  # 过户费 万0.1
    slippage: float = 0.0001            # 滑点 0.01%


class TBacktestRequest(BaseModel):
    """做T回测请求"""
    algorithm: str = "grid"             # grid|fixed_band|ma_deviation|martingale
    symbol: str = "sh600000"            # A 股代码（需 sh/sz 前缀）
    start_date: str = ""                # YYYY-MM-DD
    end_date: str = ""                  # YYYY-MM-DD
    interval: str = "5m"                # 5m|15m|30m|60m
    base_shares: int = 1000             # 底仓股数
    cash_buffer: float = 100_000.0      # 日内可用现金缓冲
    params: dict = Field(default_factory=dict)   # 算法特定参数
    cost: Optional[CostOverride] = None  # 成本模型覆盖


# ── 端点 ────────────────────────────────────────────────────────────────────────


def _fetch_minute_from_db(
    symbol: str, interval: str, start_date: str, end_date: str
) -> list[OHLCVBar]:
    """
    从本地 TimescaleDB stock_ohlcv_minute 表读分钟线（首选，"本地验证"路径）。

    本地库已由 sync_service 同步了海量分钟数据（sh600000 等覆盖 2024-2026），
    走本地既快又稳定；akshare 东财接口在本环境 flapping 不可靠。
    """
    try:
        conn = psycopg2.connect(get_dsn())
    except Exception:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT trade_time, open_, close_, high_, low_, volume, amount, market
                FROM stock_ohlcv_minute
                WHERE symbol = %s
                  AND interval = %s
                  AND trade_time >= %s
                  AND trade_time <= %s
                ORDER BY trade_time ASC
                """,
                (symbol, interval, f"{start_date} 00:00:00", f"{end_date} 23:59:59"),
            )
            rows = cur.fetchall()
    except Exception:
        return []
    finally:
        conn.close()

    bars: list[OHLCVBar] = []
    for r in rows:
        t = r["trade_time"]
        if hasattr(t, "to_pydatetime"):
            t = t.to_pydatetime()
        bars.append(
            OHLCVBar(
                symbol=symbol,
                trade_time=t,
                open_=float(r["open_"]),
                close_=float(r["close_"]),
                high_=float(r["high_"]),
                low_=float(r["low_"]),
                volume=float(r["volume"]),
                amount=float(r.get("amount") or 0.0),
                interval=interval,
                market=r.get("market") or "A",
                provider="db",
            )
        )
    return bars


@router.get("/algorithms")
def list_algorithms():
    """4 种做T算法的元数据：原理、适用行情、优缺点、参数规格"""
    return {"code": 0, "msg": "ok", "data": algorithm_metas()}


@router.post("/backtest")
def run_t_backtest(req: TBacktestRequest):
    """
    运行做T回测。

    流程：拉分钟线 → 构建策略 → 引擎执行（T+1/成本/收盘恢复底仓）→ 返回结果。
    """
    # 1. 校验算法名
    algo = req.algorithm.lower()

    # 2. 构建成本模型
    if req.cost:
        cm = TCostModel(
            commission_rate=req.cost.commission_rate,
            min_commission=req.cost.min_commission,
            stamp_duty_rate=req.cost.stamp_duty_rate,
            transfer_fee_rate=req.cost.transfer_fee_rate,
            slippage=req.cost.slippage,
        )
    else:
        cm = TCostModel()

    # 3. 拉分钟线：优先本地 DB（快且稳），本地无数据再回退 akshare 实时
    sd = req.start_date or "2000-01-01"
    ed = req.end_date or "2099-12-31"
    bars = _fetch_minute_from_db(req.symbol, req.interval, sd, ed)
    source = "本地数据库"
    if not bars:
        provider = AkshareProvider()
        bars = provider.fetch_a_stock_minute(
            symbol=req.symbol,
            interval=req.interval,
            start_date=req.start_date or None,
            end_date=req.end_date or None,
        )
        source = "akshare"
    if not bars:
        return {
            "code": 1,
            "msg": (
                f"未获取到 {req.symbol} 的 {req.interval} 分钟线数据"
                f"（本地库与 akshare 均无），请检查股票代码与日期范围"
            ),
            "data": None,
        }

    # 4. 构建策略 + 运行
    try:
        strategy = build_strategy(algo, req.params)
    except ValueError as e:
        return {"code": 1, "msg": str(e), "data": None}

    bt = TBacktester(cm, base_shares=req.base_shares, cash_buffer=req.cash_buffer)
    result = bt.run(strategy, bars)

    log.info(
        "[做T回测] %s %s %s→%s [%s] bars=%d trades=%d net=%.2f cost=%.2f",
        algo, req.symbol, sd, ed, source,
        len(bars), result.total_trades, result.total_net_pnl, result.total_cost,
    )

    return {"code": 0, "msg": "ok", "data": result.to_dict()}
