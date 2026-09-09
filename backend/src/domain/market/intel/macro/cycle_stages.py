"""股票投资课程——库存周期与信用周期（doc 31）纯函数。

簇 4 的 business_cycle_phase 用 PMI×PPI 定宏观周期位置；本模块进一步细化到
中短周期的**库存周期**（基钦周期，~40 个月）与**信用周期**——课程 doc 31
强调这两个是行业轮动/择时的实战抓手。

    库存周期 4 阶段（需求方向 × 库存方向）
        主动去库  需求↓ + 库存↓  衰退（企业主动收缩）
        被动去库  需求↑ + 库存↓  复苏（需求回暖、库存被动消耗）
        主动补库  需求↑ + 库存↑  繁荣（企业主动补库满足需求）
        被动补库  需求↓ + 库存↑  衰退前兆（需求转弱、库存惯性累积）
    信用周期
        M1-M2 剪刀差  M1>M2 资金活化（企业活跃）；M1<M2 资金定期化/空转
        宽信用/紧信用 社融增速方向 + M2 配合

输入为增速指标（小数）。全部纯函数，与 cycle_signals 互补。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── 库存周期 4 阶段 ──────────────────────────────────────────────────────────

STAGE_ACTIVE_DESTOCK = "active_destock"    # 主动去库（衰退）
STAGE_PASSIVE_DESTOCK = "passive_destock"  # 被动去库（复苏）
STAGE_ACTIVE_RESTOCK = "active_restock"    # 主动补库（繁荣）
STAGE_PASSIVE_RESTOCK = "passive_restock"  # 被动补库（衰退前兆）

_STAGE_LABELS = {
    STAGE_ACTIVE_DESTOCK: "主动去库存（衰退：需求弱、企业主动降库）",
    STAGE_PASSIVE_DESTOCK: "被动去库存（复苏：需求回暖、库存被动消耗）",
    STAGE_ACTIVE_RESTOCK: "主动补库存（繁荣：需求旺、企业主动补库）",
    STAGE_PASSIVE_RESTOCK: "被动补库存（衰退前兆：需求转弱、库存惯性累积）",
}

# 各阶段建议超配的行业（与簇4 INDUSTRY_ROTATION 互补，更中观）
STAGE_INDUSTRY_HINTS = {
    STAGE_PASSIVE_DESTOCK: ["有色金属", "煤炭", "机械设备", "电子"],   # 复苏早周期
    STAGE_ACTIVE_RESTOCK: ["有色金属", "钢铁", "化工", "煤炭"],         # 繁荣资源品
    STAGE_PASSIVE_RESTOCK: ["食品饮料", "医药生物", "公用事业"],        # 防御
    STAGE_ACTIVE_DESTOCK: ["医药生物", "食品饮料", "公用事业", "债券"], # 衰退防御+避险
}


@dataclass
class InventoryCycle:
    stage: str
    label: str
    demand_up: bool
    inventory_up: bool
    industry_hints: list[str]


def inventory_cycle(
    demand_growth: Optional[float],
    inventory_growth: Optional[float],
) -> Optional[InventoryCycle]:
    """库存周期 4 阶段定位（doc 31）。

    Args:
        demand_growth:     需求代理增速（营收/工业增加值/PMI 新订单，小数）。
        inventory_growth:  产成品存货增速（小数）。

    Returns:
        InventoryCycle；任一输入缺失返回 None。
    """
    if demand_growth is None or inventory_growth is None:
        return None
    d_up = demand_growth > 0
    inv_up = inventory_growth > 0
    if d_up and not inv_up:
        stage = STAGE_PASSIVE_DESTOCK
    elif d_up and inv_up:
        stage = STAGE_ACTIVE_RESTOCK
    elif (not d_up) and inv_up:
        stage = STAGE_PASSIVE_RESTOCK
    else:
        stage = STAGE_ACTIVE_DESTOCK
    return InventoryCycle(
        stage=stage,
        label=_STAGE_LABELS[stage],
        demand_up=d_up,
        inventory_up=inv_up,
        industry_hints=STAGE_INDUSTRY_HINTS.get(stage, []),
    )


# ── 信用周期 ────────────────────────────────────────────────────────────────

@dataclass
class M1M2Scissors:
    scissors: float        # M1 增速 − M2 增速
    verdict: str           # activating(资金活化) / neutral / termifying(定期化)


def m1_m2_scissors(
    m1_growth: Optional[float], m2_growth: Optional[float]
) -> Optional[M1M2Scissors]:
    """M1−M2 增速剪刀差（doc 31）。

    课程逻辑：M1（现金+企业活期）反映企业资金活化度与经营活动活跃度；
    M1 增速 > M2 = 资金从定期转向活期、企业扩张意愿强（利好股市）；
    M1 < M2 = 资金空转/定期化、实体需求弱。

    Args:
        m1_growth: M1 同比增速（小数）。
        m2_growth: M2 同比增速（小数）。

    Returns:
        M1M2Scissors；输入缺失返回 None。
    """
    if m1_growth is None or m2_growth is None:
        return None
    diff = m1_growth - m2_growth
    if diff > 0.02:        # M1 显著高于 M2
        verdict = "activating"
    elif diff < -0.02:
        verdict = "termifying"
    else:
        verdict = "neutral"
    return M1M2Scissors(scissors=diff, verdict=verdict)


@dataclass
class CreditCycle:
    phase: str             # easing(宽信用) / tightening(紧信用) / stable
    social_financing_growth: Optional[float]
    m2_growth: Optional[float]
    rationale: str


def credit_cycle(
    social_financing_growth: Optional[float],
    m2_growth: Optional[float],
    *,
    easing_threshold: float = 0.03,
) -> Optional[CreditCycle]:
    """信用周期：社融增速方向 + M2 配合（doc 31）。

    课程逻辑：社融是企业融资的主力，社融增速上行 = 信用扩张（宽信用，利好
    周期/成长）；下行 = 信用收缩。M2 同向配合时信号更确定。

    Args:
        social_financing_growth: 社融存量/增量增速（小数）。
        m2_growth:               M2 增速（小数）。
        easing_threshold:        判定宽/紧的增速门槛，默认 3%。

    Returns:
        CreditCycle；社融缺失返回 None。
    """
    if social_financing_growth is None:
        return None
    sf_up = social_financing_growth >= easing_threshold
    sf_down = social_financing_growth <= -easing_threshold  # 注：增速本身正负含义
    # 社融增速本身通常为正（存量在增）；这里用"增速水平"配合方向。
    # 简化：社融增速 >= 阈值 且 M2 同向走高 → 宽信用；反之紧信用。
    high_sf = social_financing_growth >= easing_threshold
    m2_support = (m2_growth is not None and m2_growth >= easing_threshold)

    if high_sf and m2_support:
        phase = "easing"
        rationale = f"社融增速 {social_financing_growth:.1%} 高位 + M2 {m2_growth:.1%} 配合，信用扩张"
    elif not high_sf and (m2_growth is None or m2_growth < easing_threshold):
        phase = "tightening"
        rationale = f"社融增速 {social_financing_growth:.1%} 偏低，信用收缩"
    else:
        phase = "stable"
        rationale = f"社融增速 {social_financing_growth:.1%}，信号中性"
    # 抑制未用变量告警
    _ = (sf_up, sf_down)
    return CreditCycle(
        phase=phase,
        social_financing_growth=social_financing_growth,
        m2_growth=m2_growth,
        rationale=rationale,
    )
