"""
做T回测引擎
============
处理底仓管理、T+1 约束、成本计算、日内净额恢复。

收益逻辑：
  做T本质是日内"低买高卖"产生现金流。我们用 **intraday_cash** 追踪：
    - 买入：cash -= (金额 + 成本)
    - 卖出：cash += (金额 - 成本)
  收盘若 intraday_net != 0（日内净头寸未归零），按收盘价强制反向平仓
  恢复底仓，把该平仓的现金流也计入。

  因此 net_pnl = 当日全部成交（含收盘强制平仓）后的 intraday_cash 净变化。
  这是"与股票涨跌无关、纯靠日内差价赚到的现金"。
"""
import logging
from collections import defaultdict
from datetime import date, datetime
from itertools import groupby

from ...sync.sync_provider import OHLCVBar
from .cost_model import CostBreakdown, TCostModel
from .models import TBacktestResult, TDayResult, TSignal, TStrategyState, TTrade
from .strategies.base import TStrategy

log = logging.getLogger(__name__)


class TBacktester:
    """
    做T回测引擎

    Args:
        cost_model:  成本模型（A股做T成本）
        base_shares: 底仓股数（不变）
        initial_cash: 日内可用现金缓冲（用于买入，每日重置；默认足够买一份）
    """

    def __init__(
        self,
        cost_model: TCostModel,
        base_shares: int = 1000,
        cash_buffer: float = 100_000.0,
    ):
        self.cost_model = cost_model
        self.base_shares = base_shares
        self.cash_buffer = cash_buffer

    def run(
        self,
        strategy: TStrategy,
        bars: list[OHLCVBar],
    ) -> TBacktestResult:
        """
        运行做T回测。

        Args:
            strategy: 做T策略实例
            bars:     分钟线列表（按时间升序）

        Returns:
            TBacktestResult
        """
        if not bars:
            return self._empty_result(strategy, bars)

        bars = sorted(bars, key=lambda b: b.trade_time)
        # 期初参考价：第一根 bar 的开盘价（用于算底仓市值与收益率）
        base_price = bars[0].open_

        daily_results: list[TDayResult] = []
        all_trades: list[TTrade] = []
        price_series: list[dict] = []

        # 按交易日分组
        for day, day_bars in self._group_by_day(bars):
            day_trades, day_result = self._run_day(
                strategy, day, day_bars, price_series
            )
            daily_results.append(day_result)
            all_trades.extend(day_trades)

        return self._summarize(
            strategy, bars, base_price, daily_results, all_trades, price_series
        )

    # ── 单日执行 ──────────────────────────────────────────────────────────
    def _run_day(
        self,
        strategy: TStrategy,
        day: date,
        day_bars: list[OHLCVBar],
        price_series: list[dict],
    ) -> tuple[list[TTrade], TDayResult]:
        """处理单个交易日的所有 bar"""
        if not day_bars:
            return [], TDayResult(day=day)

        day_open = day_bars[0].open_
        prev_close = day_bars[0].open_  # 简化：用当日开盘近似（首日无昨收）
        # 注：精确昨收需要跨日数据；这里取 day_bars[0].open_ 作为基准，
        # 固定价差等策略的基准价由调用方/历史均线决定，影响可控。

        strategy.on_day_start(day_open, prev_close)

        # 日内状态
        state = TStrategyState(
            base_shares=self.base_shares,
            sellable_shares=self.base_shares,  # 开盘时全部底仓可卖
            intraday_net=0,
            cash=self.cash_buffer,
            day_open=day_open,
            prev_close=prev_close,
            qty_today=0,
        )

        trades: list[TTrade] = []
        gross_pnl = 0.0
        cost_break = CostBreakdown()
        # 追踪日内已成交的买卖均价/量，用于估算毛收益
        # （毛收益 = 卖出回款 - 对应买入成本，简化用净额法）

        for bar in day_bars:
            price_series.append({
                "t": bar.trade_time.strftime("%Y-%m-%d %H:%M"),
                "price": round(bar.close_, 3),
            })

            sigs = strategy.on_bar(bar, state)
            if not sigs:
                continue

            for sig in sigs:
                trade = self._try_execute(sig, bar, state)
                if trade:
                    trades.append(trade)
                    self._apply_trade(trade, state)
                    cost_break = self._merge_cost(cost_break, trade)

        # 收盘强制恢复底仓：平掉日内净头寸
        closing_trades = self._force_close_intraday(
            state, day_bars[-1], strategy
        )
        for t in closing_trades:
            trades.append(t)
            cost_break = self._merge_cost(cost_break, t)

        # 计算净收益：日内现金净变化 - 缓冲（缓冲是借入的，需扣除）
        # 注意：收盘已尽量强制净额归零，cash 与缓冲的差额即为做T净赚。
        # 若因 T+1 限制仍有未平的日内净买入（当日新买不可卖），
        # 该持仓按收盘价估值回补（视为"可平但被规则限制"的待平头寸），
        # 避免夸大亏损。
        close_px = day_bars[-1].close_
        if state.intraday_net > 0:
            # 有净买入仓位未能平掉，按收盘价加回现金口径
            net_pnl = state.cash - self.cash_buffer + state.intraday_net * close_px
        else:
            net_pnl = state.cash - self.cash_buffer
        cost_total = cost_break.total
        gross_pnl = net_pnl + cost_total  # 毛收益 = 净收益 + 成本

        day_result = TDayResult(
            day=day,
            trades=trades,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            cost_total=cost_total,
            cost_breakdown=cost_break,
            close_price=day_bars[-1].close_,
        )
        return trades, day_result

    def _try_execute(
        self, sig: TSignal, bar: OHLCVBar, state: TStrategyState
    ) -> TTrade | None:
        """
        校验 T+1 / 资金约束后执行信号，返回 TTrade；不满足返回 None。

        成交价：取 bar.close_（保守用收盘价，避免未来函数）。
        """
        action = sig.action.upper()
        qty = sig.quantity
        if qty <= 0:
            return None

        if action == "SELL":
            # T+1：只能卖可卖底仓
            if qty > state.sellable_shares:
                qty = state.sellable_shares
                if qty <= 0:
                    return None
            is_sell = True
        elif action == "BUY":
            # 资金约束
            est_cost = (
                bar.close_ * qty
                * (1 + self.cost_model.commission_rate)
                + self.cost_model.min_commission
            )
            if est_cost > state.cash:
                # 裁剪到资金可承受
                max_qty = int(
                    state.cash
                    / (bar.close_ * (1 + self.cost_model.commission_rate))
                )
                qty = max(max_qty, 0)
                if qty <= 0:
                    return None
            is_sell = False
        else:
            return None

        cb = self.cost_model.calc(bar.close_, qty, is_sell)
        return TTrade(
            timestamp=bar.trade_time,
            action="SELL" if is_sell else "BUY",
            price=bar.close_,
            quantity=qty,
            commission=cb.commission,
            stamp_duty=cb.stamp_duty,
            transfer_fee=cb.transfer_fee,
            slippage=cb.slippage,
            reason=sig.reason,
        )

    def _apply_trade(self, trade: TTrade, state: TStrategyState) -> None:
        """成交后更新日内状态"""
        amount = trade.amount
        cost = trade.total_cost
        if trade.is_sell:
            state.sellable_shares -= trade.quantity
            state.intraday_net -= trade.quantity
            state.cash += amount - cost
        else:
            # 买入：当日新买部分 T+1 不可卖，所以不增加 sellable_shares
            state.intraday_net += trade.quantity
            state.cash -= amount + cost
        state.qty_today += trade.quantity

    def _force_close_intraday(
        self,
        state: TStrategyState,
        last_bar: OHLCVBar,
        strategy: TStrategy,
    ) -> list[TTrade]:
        """
        收盘强制平掉日内净头寸，尽量恢复底仓数量。

        - intraday_net > 0（日内净买入，底仓被稀释）：卖出多余部分。
          ⚠️ 受 T+1 约束：当日新买的不可卖，只能卖 sellable_shares。
          若可卖不足，多余股票作为持仓留存（真实做T中持有到次日）。
        - intraday_net < 0（日内净卖出，卖超了）：买回补足（受资金约束）。
        - = 0：无需操作。

        注意：net_pnl 的计算基于"日内现金净变化"。若 T+1 导致部分
        净买入无法在收盘卖出，这部分股票按持仓留存，其买入成本已计入
        现金流出，因此现金变化仍正确反映做T的盈亏（留存仓位视为
        "本应卖出但受 T+1 限制无法卖"的待平头寸）。
        """
        out: list[TTrade] = []
        net = state.intraday_net
        if net == 0:
            return out

        if net > 0:
            # 净买入 → 收盘卖出多余部分恢复底仓
            # T+1 约束：只能卖 sellable_shares（当日新买不可卖）
            sell_qty = min(net, state.sellable_shares)
            if sell_qty <= 0:
                return out  # 无可卖底仓，净买入仓位留存到次日
            cb = self.cost_model.calc(last_bar.close_, sell_qty, is_sell=True)
            t = TTrade(
                timestamp=last_bar.trade_time,
                action="SELL",
                price=last_bar.close_,
                quantity=sell_qty,
                commission=cb.commission,
                stamp_duty=cb.stamp_duty,
                transfer_fee=cb.transfer_fee,
                slippage=cb.slippage,
                reason="收盘强制平仓恢复底仓",
            )
            self._apply_trade(t, state)
            out.append(t)
        else:
            # 净卖出 → 收盘买回 |net| 股补足（受资金约束，尽量买）
            need = -net
            est_cost = (
                last_bar.close_ * need
                * (1 + self.cost_model.commission_rate)
                + self.cost_model.min_commission
            )
            if est_cost > state.cash:
                need = int(
                    state.cash
                    / (last_bar.close_ * (1 + self.cost_model.commission_rate))
                )
            if need <= 0:
                return out
            cb = self.cost_model.calc(last_bar.close_, need, is_sell=False)
            t = TTrade(
                timestamp=last_bar.trade_time,
                action="BUY",
                price=last_bar.close_,
                quantity=need,
                commission=cb.commission,
                stamp_duty=cb.stamp_duty,
                transfer_fee=cb.transfer_fee,
                slippage=cb.slippage,
                reason="收盘强制平仓恢复底仓",
            )
            self._apply_trade(t, state)
            out.append(t)
        return out

    # ── 汇总 ──────────────────────────────────────────────────────────────
    def _summarize(
        self,
        strategy: TStrategy,
        bars: list[OHLCVBar],
        base_price: float,
        daily_results: list[TDayResult],
        all_trades: list[TTrade],
        price_series: list[dict],
    ) -> TBacktestResult:
        total_net = sum(d.net_pnl for d in daily_results)
        total_gross = sum(d.gross_pnl for d in daily_results)
        total_cost = sum(d.cost_total for d in daily_results)
        cost_break = CostBreakdown()
        for d in daily_results:
            cost_break = self._merge_cost(cost_break, d.cost_breakdown, is_day=True)

        base_value = self.base_shares * base_price
        total_return_pct = (total_net / base_value * 100) if base_value else 0.0
        cost_reduction = (total_net / self.base_shares) if self.base_shares else 0.0

        # 标注买卖点到价格序列
        trade_points = {}
        for t in all_trades:
            key = t.timestamp.strftime("%Y-%m-%d %H:%M")
            trade_points.setdefault(key, []).append(t.action)

        for pt in price_series:
            acts = trade_points.get(pt["t"], [])
            if acts:
                pt["action"] = "SELL" if "SELL" in acts else "BUY"

        return TBacktestResult(
            algorithm=strategy.name,
            symbol=bars[0].symbol if bars else "",
            interval=bars[0].interval if bars else "",
            start_date=(
                bars[0].trade_time.strftime("%Y-%m-%d") if bars else ""
            ),
            end_date=(
                bars[-1].trade_time.strftime("%Y-%m-%d") if bars else ""
            ),
            base_shares=self.base_shares,
            base_price=base_price,
            total_net_pnl=total_net,
            total_return_pct=total_return_pct,
            cost_reduction=cost_reduction,
            gross_pnl=total_gross,
            total_cost=total_cost,
            cost_breakdown=cost_break,
            total_trades=len(all_trades),
            total_buys=sum(1 for t in all_trades if not t.is_sell),
            total_sells=sum(1 for t in all_trades if t.is_sell),
            total_days=len(daily_results),
            win_days=sum(1 for d in daily_results if d.is_win),
            daily_results=daily_results,
            trades=all_trades,
            price_series=price_series,
        )

    # ── 工具 ──────────────────────────────────────────────────────────────
    @staticmethod
    def _group_by_day(
        bars: list[OHLCVBar],
    ) -> list[tuple[date, list[OHLCVBar]]]:
        """按交易日分组，保持顺序"""
        groups: dict[date, list[OHLCVBar]] = defaultdict(list)
        for b in bars:
            d = b.trade_time.date() if isinstance(b.trade_time, datetime) else b.trade_time
            groups[d].append(b)
        return sorted(groups.items())

    @staticmethod
    def _merge_cost(
        base: CostBreakdown, src, is_day: bool = False
    ) -> CostBreakdown:
        """合并成本明细（src 为 TTrade 或 CostBreakdown）"""
        if isinstance(src, CostBreakdown):
            return CostBreakdown(
                commission=base.commission + src.commission,
                stamp_duty=base.stamp_duty + src.stamp_duty,
                transfer_fee=base.transfer_fee + src.transfer_fee,
                slippage=base.slippage + src.slippage,
            )
        # TTrade
        return CostBreakdown(
            commission=base.commission + src.commission,
            stamp_duty=base.stamp_duty + src.stamp_duty,
            transfer_fee=base.transfer_fee + src.transfer_fee,
            slippage=base.slippage + src.slippage,
        )

    def _empty_result(
        self, strategy: TStrategy, bars: list[OHLCVBar]
    ) -> TBacktestResult:
        return TBacktestResult(
            algorithm=strategy.name,
            symbol="",
            interval="",
            start_date="N/A",
            end_date="N/A",
            base_shares=self.base_shares,
            base_price=0.0,
        )
