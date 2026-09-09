"""
做T策略基类
============
所有做T算法继承此类。算法只需关注"在当前 bar 下是否要买卖"，
T+1 校验、成本计算、日内净额恢复由引擎处理。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from ....sync.sync_provider import OHLCVBar
from ..models import TSignal, TStrategyState


@dataclass
class ParamSpec:
    """算法参数规格（供前端动态渲染表单）"""
    key: str
    label: str
    type: str = "number"        # number | select
    default: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    unit: str = ""
    options: list = field(default_factory=list)   # type=select 时的选项
    help: str = ""              # 说明文字（小白向）


class TStrategy(ABC):
    """
    做T策略抽象基类。

    生命周期（每个交易日）：
      1. engine 调 on_day_start() → 算法重置日内状态
      2. 每个 bar 调 on_bar() → 返回该 bar 想做的交易（TSignal 列表）
      3. engine 校验 T+1/资金 后执行
      4. 收盘 engine 强制平掉日内净头寸恢复底仓
    """

    name: str = "BaseTStrategy"
    display_name: str = "基础做T"
    one_liner: str = ""          # 一句话原理（大白话）
    description: str = ""        # 详细原理
    market_fit: str = ""         # 适用行情
    pros: list[str] = field(default_factory=list)       # 优点
    risks: list[str] = field(default_factory=list)      # 风险
    danger: bool = False         # 是否高风险（马丁等）

    @abstractmethod
    def get_param_specs(self) -> list[ParamSpec]:
        """参数规格（前端表单）"""
        ...

    @abstractmethod
    def on_day_start(self, day_open: float, prev_close: float) -> None:
        """每日开盘初始化算法内部状态"""
        ...

    @abstractmethod
    def on_bar(
        self,
        bar: OHLCVBar,
        state: TStrategyState,
    ) -> list[TSignal]:
        """
        处理一根 bar，返回想做的交易信号列表。

        引擎会校验：
          - 卖出量 ≤ state.sellable_shares（T+1 约束）
          - 买入量 ≤ state.cash 可承受范围
        不满足的信号会被裁剪或丢弃。
        """
        ...

    def get_params(self) -> dict:
        """返回当前参数值（记录用）"""
        return {}

    def meta(self) -> dict:
        """算法元数据（前端原理卡片）"""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "one_liner": self.one_liner,
            "description": self.description,
            "market_fit": self.market_fit,
            "pros": self.pros,
            "risks": self.risks,
            "danger": self.danger,
            "params": [p.__dict__ for p in self.get_param_specs()],
        }
