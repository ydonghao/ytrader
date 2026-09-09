"""
A 股做T成本模型
================
做T赚的就是微小差价，成本直接决定盈亏。本模型涵盖 A 股全部做T成本项：

  - 佣金 commission：双向，费率万 2.5，**最低 5 元**（做T杀手：小单必交 5 元）
  - 印花税 stamp_duty：**仅卖出单边** 0.05%（2023.8.28 起由 0.1% 减半）
  - 过户费 transfer_fee：双向，万 0.1（沪深统一，2022 年起沪市也按万 0.1）
  - 滑点 slippage：买卖双向，成交价偏离的隐性成本

公式（每笔）：
  commission = max(amount * commission_rate, min_commission)
  stamp_duty = amount * stamp_duty_rate            （仅卖出）
  transfer   = amount * transfer_fee_rate          （双向）
  slippage   = amount * slippage                   （双向）
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class CostBreakdown:
    """单笔成交的成本明细（均为元）"""
    commission: float = 0.0      # 佣金（已套用最低5元）
    stamp_duty: float = 0.0      # 印花税（仅卖出）
    transfer_fee: float = 0.0    # 过户费
    slippage: float = 0.0        # 滑点成本

    @property
    def total(self) -> float:
        return (
            self.commission
            + self.stamp_duty
            + self.transfer_fee
            + self.slippage
        )

    def to_dict(self) -> dict:
        return {
            "commission": round(self.commission, 4),
            "stamp_duty": round(self.stamp_duty, 4),
            "transfer_fee": round(self.transfer_fee, 4),
            "slippage": round(self.slippage, 4),
            "total": round(self.total, 4),
        }


@dataclass
class TCostModel:
    """
    A 股做T成本模型

    Attributes:
        commission_rate: 佣金费率（默认 0.00025 = 万2.5）
        min_commission:   单笔最低佣金（默认 5.0 元）—— 做T关键成本
        stamp_duty_rate:  印花税率（默认 0.0005 = 0.05%，仅卖出）
        transfer_fee_rate: 过户费率（默认 0.00001 = 万0.1，双向）
        slippage:         滑点比例（默认 0.0001 = 0.01%）
    """
    commission_rate: float = 0.00025
    min_commission: float = 5.0
    stamp_duty_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage: float = 0.0001

    def calc(self, price: float, quantity: int, is_sell: bool) -> CostBreakdown:
        """
        计算单笔成交的全部成本。

        Args:
            price:    成交价
            quantity: 成交数量（股）
            is_sell:  是否为卖出（卖出才计印花税）

        Returns:
            CostBreakdown
        """
        if quantity <= 0:
            return CostBreakdown()
        amount = price * quantity
        commission = max(amount * self.commission_rate, self.min_commission)
        stamp_duty = amount * self.stamp_duty_rate if is_sell else 0.0
        transfer_fee = amount * self.transfer_fee_rate
        slippage_cost = amount * self.slippage
        return CostBreakdown(
            commission=commission,
            stamp_duty=stamp_duty,
            transfer_fee=transfer_fee,
            slippage=slippage_cost,
        )

    def to_dict(self) -> dict:
        return {
            "commission_rate": self.commission_rate,
            "min_commission": self.min_commission,
            "stamp_duty_rate": self.stamp_duty_rate,
            "transfer_fee_rate": self.transfer_fee_rate,
            "slippage": self.slippage,
        }
