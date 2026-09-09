#!/usr/bin/env python
"""
回测 CLI
=========
用法示例:
    python -m src.domain.market.strategy.backtest_cli \\
        --strategy sma_cross --symbols sh600000,sh600519 \\
        --start 2023-01-01 --end 2025-12-31 \\
        --initial-capital 1000000
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# ── 确保项目根在 path ─────────────────────────────────────────
_BACKEND = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.strategy import (
    Backtester, get_strategy, GridOptimizer,
)
from src.domain.market.strategy.backtester import BacktestResult
from src.domain.market.sync.sync_provider import OHLCVBar

log = logging.getLogger("backtest_cli")


# ── K线数据读取（从 TimescaleDB）────────────────────────────────

from src.infra.database.sql_engine.dsn import get_dsn as get_timescale_dsn


def _get_bars_from_db(
    symbols: list[str],
    start_date: str,
    end_date: str,
    interval: str = "1d",
) -> dict[str, list[OHLCVBar]]:
    """从 TimescaleDB 读取K线数据"""
    try:
        import psycopg2
    except ImportError:
        log.error("psycopg2 未安装，无法从数据库读取K线数据")
        return {}

    conn = psycopg2.connect(get_timescale_dsn())
    bars_by_symbol: dict[str, list[OHLCVBar]] = {s: [] for s in symbols}
    
    try:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(symbols))
            cur.execute(
                f"""
                SELECT symbol, trade_date, open_, close_, high_, low_, volume, amount
                FROM stock_ohlcv
                WHERE symbol IN ({placeholders})
                  AND trade_date >= %s
                  AND trade_date <= %s
                ORDER BY symbol, trade_date
                """,
                symbols + [start_date, end_date],
            )
            rows = cur.fetchall()
        
        for row in rows:
            sym, trade_date, open_, close_, high_, low_, volume, amount = row
            if sym in bars_by_symbol:
                bars_by_symbol[sym].append(OHLCVBar(
                    symbol=sym,
                    trade_time=trade_date,
                    open_=float(open_),
                    close_=float(close_),
                    high_=float(high_),
                    low_=float(low_),
                    volume=float(volume) if volume else 0,
                    amount=float(amount) if amount else 0,
                    interval=interval,
                    market="A",
                    provider="backtest",
                ))
    finally:
        conn.close()

    return bars_by_symbol


def _plot_equity_curve(result: BacktestResult, output_path: Path):
    """绘制权益曲线"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        log.warning("matplotlib 未安装，跳过绘图")
        return

    if not result.equity_curve:
        log.warning("无权益曲线数据，跳过绘图")
        return

    times = [x[0] for x in result.equity_curve]
    equities = [x[1] for x in result.equity_curve]

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(times, equities, color="#2196F3", linewidth=1.5, label="权益")
    ax.axhline(result.initial_capital, color="gray", linestyle="--", alpha=0.5, label="初始资金")
    
    # 填充最大回撤区域
    peak = result.initial_capital
    peak_x, peak_y = times[0], equities[0]
    max_dd_x_start = times[0]
    for i, (t, e) in enumerate(zip(times, equities)):
        if e > peak:
            peak = e
            peak_x, peak_y = t, e
            max_dd_x_start = t

    ax.set_title(
        f"{result.strategy_name} | 收益率: {result.total_return:.2f}% | "
        f"夏普: {result.sharpe_ratio:.2f} | 最大回撤: {result.max_drawdown:.2f}%",
        fontsize=12,
    )
    ax.set_xlabel("日期")
    ax.set_ylabel("账户权益")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.xticks(rotation=45)
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    log.info(f"权益曲线已保存 → {output_path}")


# ── CLI ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ytrader 回测工具")
    parser.add_argument("--strategy", required=True, 
                       help="策略名: sma_cross, rsi, macd, bollinger")
    parser.add_argument("--symbols", required=True,
                       help="标的代码，逗号分隔: sh600000,sh600519")
    parser.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--interval", default="1d", help="K线周期: 1d (默认), 5m, 60m…")
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0,
                       help="初始资金 (默认 1,000,000)")
    parser.add_argument("--commission", type=float, default=0.0003,
                       help="手续费率 (默认 0.0003 = 0.03%%)")
    parser.add_argument("--slippage", type=float, default=0.0001,
                       help="滑点 (默认 0.0001 = 0.01%%)")
    parser.add_argument("--no-plot", action="store_true", help="跳过绘图")
    parser.add_argument("--optimize", action="store_true", help="运行网格搜索优化")
    parser.add_argument("--output-dir", default="reports",
                       help="报告输出目录 (默认 reports/)")
    
    # 策略特定参数（传递给策略构造）
    parser.add_argument("--param", action="append", default=[],
                       help="策略参数，如 --param fast_period=5")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # 解析参数
    symbols = [s.strip() for s in args.symbols.split(",")]
    strategy_params = {}
    for p in args.param:
        if "=" in p:
            k, v = p.split("=", 1)
            # 尝试转数字
            try:
                v = int(v)
            except ValueError:
                try:
                    v = float(v)
                except ValueError:
                    pass
            strategy_params[k] = v

    log.info(f"回测配置: 策略={args.strategy}, 标的={symbols}, "
             f"周期={args.start}→{args.end}, 参数={strategy_params}")

    # 读取数据
    log.info("从数据库读取K线数据...")
    bars_by_symbol = _get_bars_from_db(symbols, args.start, args.end, args.interval)
    
    for sym in symbols:
        count = len(bars_by_symbol.get(sym, []))
        log.info(f"  {sym}: {count} 条K线")

    # 检查数据
    total_bars = sum(len(v) for v in bars_by_symbol.values())
    if total_bars == 0:
        log.error("数据库中无K线数据，回测终止")
        sys.exit(1)

    if total_bars < 50:
        log.warning(f"数据量较少({total_bars}条)，回测结果可能不准确")

    # 构造策略
    strategy = get_strategy(args.strategy, **strategy_params)
    log.info(f"策略: {strategy}")

    # 运行回测
    bt = Backtester(
        initial_capital=args.initial_capital,
        commission_rate=args.commission,
        slippage=args.slippage,
    )
    
    result = bt.run_multi(
        strategy=strategy,
        bars_by_symbol=bars_by_symbol,
        start_date=args.start,
        end_date=args.end,
    )

    print(result.summary())

    # 保存权益曲线图
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    symbol_str = "_".join(symbols[:2]) if len(symbols) <= 2 else "_multi"

    if not args.no_plot:
        png_path = output_dir / f"equity_{strategy.name}_{symbol_str}_{date_str}.png"
        _plot_equity_curve(result, png_path)

    # 保存结果JSON
    json_path = output_dir / f"backtest_{strategy.name}_{symbol_str}_{date_str}.json"
    import json
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "strategy": strategy.name,
            "params": strategy.get_params(),
            "symbols": result.symbols,
            "start_date": result.start_date,
            "end_date": result.end_date,
            "total_return": round(result.total_return, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "max_drawdown": round(result.max_drawdown, 4),
            "win_rate": round(result.win_rate, 2),
            "profit_factor": round(result.profit_factor, 4),
            "total_trades": result.total_trades,
        }, f, ensure_ascii=False, indent=2)
    log.info(f"结果JSON → {json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
