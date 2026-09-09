"""
长期组合策略基类
================
所有长期策略继承此类。策略只需关注"在调仓日给出目标权重"，
T+1 / 成本 / 权重执行 / 权益跟踪由引擎处理。

生命周期（按交易日）：
  1. 每个交易日：引擎更新价格/持仓/权益，记录权益曲线
  2. 到调仓日：engine 调 on_rebalance()
       → 策略看全局宇宙 + 历史价格 + 基本面，返回 RebalanceSignal(目标权重)
  3. engine 据目标权重执行买卖（按目标股数对齐），应用 A 股成本

关键区别（vs 短期 TA 策略）：
  - 短期策略看单标的、产买卖整仓信号；长期策略看全局、产目标权重
  - 长期策略可做横截面选股（如动量排名、价值排名）—— 这是 SingleSymbolStrategy
    做不到的，因为后者把多标的 K 线拆开逐个喂给策略
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from ...sync.sync_provider import OHLCVBar
from ..indicators import sma  # 复用现有技术指标
from .models import PortfolioState, RebalanceSignal


@dataclass
class ParamSpec:
    """策略参数规格（供前端动态渲染表单）。"""
    key: str
    label: str
    type: str = "number"        # number | select
    default: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    unit: str = ""
    options: list = field(default_factory=list)
    help: str = ""


class LongTermStrategy(ABC):
    """
    长期组合策略抽象基类。

    子类需实现：
      - on_rebalance(): 调仓日返回目标权重
      - get_param_specs(): 参数规格（前端表单）
    """

    name: str = "BaseLongTerm"
    display_name: str = "基础长期策略"
    one_liner: str = ""
    description: str = ""
    market_fit: str = ""
    pros: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    family: str = ""          # 动量/价值/趋势/资产配置/定投

    # 默认调仓频率，可被实例参数覆盖
    rebalance_freq: str = "monthly"
    # 是否需要基本面数据（价值类策略置 True，引擎据此决定是否拉基本面）
    needs_fundamentals: bool = False

    @abstractmethod
    def on_rebalance(
        self,
        today: date,
        bars_by_symbol: dict[str, list[OHLCVBar]],
        valuation_by_symbol: Optional[dict[str, list[dict]]] = None,
        financials_by_symbol: Optional[dict[str, list[dict]]] = None,
        state: Optional[PortfolioState] = None,
    ) -> RebalanceSignal:
        """
        调仓日决策。

        Args:
            today:                 当前调仓日
            bars_by_symbol:        各标的历史日线 {symbol: [OHLCVBar]}（升序，含今天）
            valuation_by_symbol:   各标的估值历史 {symbol: [dict]}（价值策略用，可选）
            financials_by_symbol:  各标的财务历史 {symbol: [dict]}（价值策略用，可选）
            state:                 当前组合状态

        Returns:
            RebalanceSignal，target_weights {symbol: 0~1}
        """
        ...

    @abstractmethod
    def get_param_specs(self) -> list[ParamSpec]:
        """参数规格（前端表单）。"""
        ...

    def get_params(self) -> dict:
        """返回当前参数值（记录用）。"""
        return {}

    def meta(self) -> dict:
        """策略元数据（前端原理卡片）。"""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "one_liner": self.one_liner,
            "description": self.description,
            "market_fit": self.market_fit,
            "family": self.family,
            "pros": self.pros,
            "risks": self.risks,
            "rebalance_freq": self.rebalance_freq,
            "needs_fundamentals": self.needs_fundamentals,
            "params": [p.__dict__ for p in self.get_param_specs()],
        }

    # ── 通用工具方法（子类复用） ──────────────────────────────────────────
    @staticmethod
    def closes(bars: list[OHLCVBar]) -> list[float]:
        """提取收盘价序列。"""
        return [b.close_ for b in bars]

    @staticmethod
    def returns(bars: list[OHLCVBar], lookback: int) -> Optional[float]:
        """
        过去 lookback 根 bar 的收益率（%）。
        不足 lookback 返回 None。
        """
        if len(bars) < lookback + 1:
            return None
        start = bars[-lookback - 1].close_
        end = bars[-1].close_
        if start <= 0:
            return None
        return (end / start - 1.0) * 100.0

    @staticmethod
    def above_sma(bars: list[OHLCVBar], period: int) -> Optional[bool]:
        """当前价是否在 period 日均线之上（不足周期返回 None）。"""
        closes = [b.close_ for b in bars]
        ma = sma(closes, period)
        if not ma or ma[-1] is None:
            return None
        return closes[-1] > ma[-1]
