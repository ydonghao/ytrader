"""
股利折现模型 DDM（纯函数）
=====================
适用于"确定性高、成长性低"的红利型公司（课程 15 集：长江电力 2024 分红 230 亿、
折现率 5.5%、永续增长 2% → 内在价值约 6703 亿，对比当时市值 7338 亿）。

Gordon 恒定增长模型：V = D₀ × (1+g) / (r − g)
安全边际复用 dcf.margin_of_safety（同口径通用算子）。
"""
from __future__ import annotations

from typing import Optional

from src.domain.market.fundamental.dcf import margin_of_safety

# 默认假设（红利股参考值）
DEFAULT_GROWTH_RATE = 0.02      # 永续增长 ≈ 长期通胀
DEFAULT_DISCOUNT_RATE = 0.055   # 红利股折现率参考


def ddm_intrinsic_value(
    d0: float,
    growth_rate: float = DEFAULT_GROWTH_RATE,
    discount_rate: float = DEFAULT_DISCOUNT_RATE,
) -> Optional[float]:
    """Gordon 股利折现内在价值（总，与市值同口径）。

    d0: 当期分红总额（或 TTM 分红）。d0<=0、r<=g 返回 None。
    """
    if d0 is None or d0 <= 0:
        return None
    if discount_rate <= growth_rate:
        return None
    return round(d0 * (1 + growth_rate) / (discount_rate - growth_rate), 2)


# margin_of_safety 直接复用 dcf 模块的通用实现（内在价值与市值同口径）
ddm_margin_of_safety = margin_of_safety
