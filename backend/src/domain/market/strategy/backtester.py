"""
回测引擎
=========
支持滑点、手续费、仓位管理、权益曲线计算。
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .base import Strategy
from .signals import Action, Position, Signal, Trade
from ..sync.sync_provider import OHLCVBar

log = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    symbols: list[str]
    start_date: str
    end_date: str
    initial_capital: float
    final_equity: float
    total_return: float = 0.0       # 总收益率（%）
    sharpe_ratio: float = 0.0      # 夏普率（年化）
    max_drawdown: float = 0.0      # 最大回撤（%）
    max_drawdown_duration_days: int = 0  # 最大回撤持续天数
    win_rate: float = 0.0          # 胜率（%）
    profit_factor: float = 0.0     # 盈亏比
    total_trades: int = 0    # 总交易次数
    winning_trades: int = 0
    losing_trades: int = 0
    avg_trade_return: float = 0.0   # 平均每笔收益率（%）
    avg_holding_days: float = 0.0
    equity_curve: list[tuple] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return f"""
=== {self.strategy_name} Backtest Results ===
标的:   {', '.join(self.symbols)}
回测期: {self.start_date} → {self.end_date}
初始资金: {self.initial_capital:,.2f}
最终权益: {self.final_equity:,.2f}
收益率:   {self.total_return:.2f}%
夏普率:   {self.sharpe_ratio:.2f}
最大回撤: {self.max_drawdown:.2f}%
胜率:     {self.win_rate:.1f}%
盈亏比:   {self.profit_factor:.2f}
总交易数: {self.total_trades}
"""


class Backtester:
    """
    回测引擎
    
    使用方法:
        bt = Backtester(initial_capital=1000000, commission_rate=0.0003)
        result = bt.run_multi(strategy, symbols=["sh600000"], start_date="2023-01-01", ...)
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        commission_rate: float = 0.0003,   # 手续费 0.03%
        slippage: float = 0.0001,           # 滑点 0.01%
        position_size: float = 0.95,        # 仓位比例（每次用95%的资金）
        stop_loss: float = 0.05,            # 止损比例（默认-5%）
        take_profit: float = 0.0,          # 止盈（默认无限制）
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.position_size = position_size
        self.stop_loss = stop_loss
        self.take_profit = take_profit

    def run(
        self,
        strategy: Strategy,
        bars: list[OHLCVBar],
    ) -> BacktestResult:
        """
        对单一标的列表运行回测
        
        Args:
            strategy: 策略实例
            bars: OHLCVBar 列表（按时间升序）
            
        Returns:
            BacktestResult
        """
        if not bars:
            return BacktestResult(
                strategy_name=strategy.name,
                symbols=[],
                start_date="N/A", end_date="N/A",
                initial_capital=self.initial_capital,
                final_equity=self.initial_capital,
                total_return=0.0, sharpe_ratio=0.0,
                max_drawdown=0.0, win_rate=0.0, profit_factor=0.0,
                errors=["No data provided"],
            )

        # 生成信号
        signals = strategy.generate_signals(bars)
        log.info(f"[回测] {strategy.name} 生成 {len(signals)} 个信号")

        return self._run_backtest(strategy.name, list(set(b.symbol for b in bars)),
                                  bars, signals)

    def run_multi(
        self,
        strategy: Strategy,
        bars_by_symbol: dict[str, list[OHLCVBar]],
        start_date: str,
        end_date: str,
    ) -> BacktestResult:
        """
        对多个标的运行回测
        
        Args:
            strategy: 策略实例
            bars_by_symbol: {symbol: bars列表}，各列表内按时间升序
            start_date: 回测开始日期
            end_date: 回测结束日期
        """
        all_signals: list[Signal] = []
        all_bars: list[OHLCVBar] = []
        
        for symbol, bars in bars_by_symbol.items():
            if not bars:
                continue
            bars = sorted(bars, key=lambda x: x.trade_time)
            all_bars.extend(bars)
            sigs = strategy.generate_signals(bars)
            all_signals.extend(sigs)

        symbols = list(bars_by_symbol.keys())
        log.info(f"[回测] {strategy.name} 多标的 {symbols} 生成 {len(all_signals)} 个信号")

        return self._run_backtest(strategy.name, symbols, all_bars, all_signals,
                                  start_date, end_date)

    def _run_backtest(
        self,
        strategy_name: str,
        symbols: list[str],
        bars: list[OHLCVBar],
        signals: list[Signal],
        start_date: str = "",
        end_date: str = "",
    ) -> BacktestResult:
        """核心回测逻辑"""
        
        # 按时间排序
        bars = sorted(bars, key=lambda x: x.trade_time)
        signals = sorted(signals, key=lambda x: x.timestamp)
        
        # 建立时间→K线 map（快速查找）
        bar_map: dict[tuple] = {}
        for b in bars:
            bar_map[(b.symbol, b.trade_time)] = b
        
        # 状态
        cash = self.initial_capital
        available_cash = self.initial_capital  # 可用于开仓的资金
        positions: dict[str, Position] = {}   # 多仓支持：symbol -> Position
        equity_curve: list[tuple] = []
        trades: list[Trade] = []
        trade_returns: list[float] = []
        holding_days: list[float] = []
        
        # 按时间顺序处理信号
        for sig in signals:
            key = (sig.symbol, sig.timestamp)
            if key not in bar_map:
                # 时间点没有K线数据 → 找下一个可用的bar
                bar = None
                for b in bars:
                    if b.symbol == sig.symbol and b.trade_time >= sig.timestamp:
                        bar = b
                        break
                if bar is None:
                    continue
            else:
                bar = bar_map[key]

            # 成交价格（含滑点）
            if sig.action == Action.BUY:
                exec_price = sig.price * (1 + self.slippage)
            elif sig.action in (Action.SELL, Action.CLOSE):
                exec_price = sig.price * (1 - self.slippage)
            else:
                exec_price = sig.price

            # ── BUY：开仓 ─────────────────────────────────
            if sig.action == Action.BUY:
                if sig.symbol in positions:
                    continue  # 已有该标的仓位，跳过
                invest = available_cash * self.position_size
                actual_qty = int(invest / (exec_price * (1 + self.commission_rate)))
                if actual_qty <= 0:
                    continue  # 资金不足
                cost = exec_price * actual_qty
                commission = cost * self.commission_rate
                positions[sig.symbol] = Position(
                    symbol=sig.symbol,
                    quantity=actual_qty,
                    avg_price=exec_price,
                )
                cash -= (cost + commission)
                available_cash -= (cost + commission)
                trades.append(Trade(
                    symbol=sig.symbol,
                    action=Action.BUY,
                    price=exec_price,
                    quantity=actual_qty,
                    commission=commission,
                    timestamp=sig.timestamp,
                ))

            # ── SELL/CLOSE：平仓 ───────────────────────────
            elif sig.action in (Action.SELL, Action.CLOSE):
                if sig.symbol not in positions:
                    continue  # 无仓位，跳过
                pos = positions[sig.symbol]
                commission = pos.quantity * exec_price * self.commission_rate
                pnl = (exec_price - pos.avg_price) * pos.quantity - commission
                trade_return = (exec_price - pos.avg_price) / pos.avg_price
                
                trades.append(Trade(
                    symbol=sig.symbol,
                    action=Action.SELL,
                    price=exec_price,
                    quantity=pos.quantity,
                    commission=commission,
                    timestamp=sig.timestamp,
                    pnl=pnl,
                ))
                
                proceeds = pos.quantity * exec_price - commission
                cash += proceeds
                available_cash += proceeds
                trade_returns.append(trade_return * 100)
                del positions[sig.symbol]

            # 更新权益曲线
            pos_value = sum(p.quantity * bar.close_ for p in positions.values())
            equity_curve.append((sig.timestamp, cash + pos_value))

        # 最后时点权益（持仓按最后收盘价计算）
        last_close = bars[-1].close_ if bars else 0
        pos_value = sum(p.quantity * last_close for p in positions.values())
        final_equity = cash + pos_value

        # 计算指标
        total_return = (final_equity - self.initial_capital) / self.initial_capital * 100
        
        # 夏普率（简化版：使用日收益率序列）
        returns_series = []
        for i in range(1, len(equity_curve)):
            ret = (equity_curve[i][1] - equity_curve[i-1][1]) / equity_curve[i-1][1]
            returns_series.append(ret)
        
        if len(returns_series) > 1:
            import statistics
            mean_ret = statistics.mean(returns_series) * 252  # 年化
            std_ret = statistics.stdev(returns_series) * (252 ** 0.5) if len(returns_series) > 1 else 0
            sharpe = (mean_ret - 0.03) / std_ret if std_ret > 0 else 0.0
        else:
            sharpe = 0.0

        # 最大回撤
        peak = self.initial_capital
        max_dd = 0.0
        for _, equity in equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # 胜率
        winning = [r for r in trade_returns if r > 0]
        losing = [r for r in trade_returns if r <= 0]
        win_rate = len(winning) / len(trade_returns) * 100 if trade_returns else 0.0
        avg_return = statistics.mean(trade_returns) if trade_returns else 0.0

        # 盈亏比
        avg_win = statistics.mean(winning) if winning else 0.0
        avg_loss = abs(statistics.mean(losing)) if losing else 1.0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0.0

        return BacktestResult(
            strategy_name=strategy_name,
            symbols=symbols,
            start_date=start_date or (bars[0].trade_time.strftime("%Y-%m-%d") if bars else "N/A"),
            end_date=end_date or (bars[-1].trade_time.strftime("%Y-%m-%d") if bars else "N/A"),
            initial_capital=self.initial_capital,
            final_equity=final_equity,
            total_return=total_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            avg_trade_return=avg_return,
            equity_curve=equity_curve,
            trades=trades,
        )
