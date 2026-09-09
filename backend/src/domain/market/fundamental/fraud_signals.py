"""股票投资课程——财务异常/造假红旗检测（doc 21 检查清单）纯函数。

簇 1 的 quality_report 关注"公司健不健康"；本模块聚焦"数据是否可信"——
识别财报中常见的**粉饰/操纵信号**。课程 doc 21 强调：买入前要做检查清单，
警惕业绩与基本面、现金流与利润的背离。

四类红旗（均需相邻两期对比）：

    营收-应收背离    应收增速 >> 营收增速 → 压货/放宽信用冲业绩
    净利-现金流背离  净利大增但 OCF 不增/下降 → 利润含金量低
    存货异常积压     存货增速 >> 营收增速 → 滞销/隐藏减值
    毛利率突变       毛利率大幅波动 → 会计政策/成本操纵嫌疑

输入为相邻两期财报快照（fetch_financial_snapshot 风格的 dict，含
revenue/accounts_receivable/net_profit/ocf/inventory/gross_margin）。
全部纯函数，无 DB/IO 依赖。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

try:
    from src.domain.market.fundamental.quality import gross_margin
except Exception:  # noqa: BLE001
    gross_margin = None


@dataclass
class RedFlag:
    name: str
    triggered: bool
    detail: str


@dataclass
class FraudReport:
    red_flags: list[RedFlag] = field(default_factory=list)
    triggered_count: int = 0
    severity: str = "clean"   # clean / watch / high_risk


def _growth(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    """环比/同比增长率；prev<=0 或缺失返回 None。"""
    if curr is None or prev is None or prev <= 0:
        return None
    return (curr - prev) / prev


def _gm(snap: dict) -> Optional[float]:
    """从快照取毛利率：优先 gross_margin 字段，否则 gross_profit/revenue。"""
    if snap.get("gross_margin") is not None:
        return snap["gross_margin"]
    if gross_margin is not None:
        return gross_margin(snap)
    gp = snap.get("gross_profit")
    rev = snap.get("revenue")
    if gp is not None and rev and rev > 0:
        return gp / rev
    return None


# ── 单项红旗 ────────────────────────────────────────────────────────────────

def revenue_receivable_divergence(
    curr: dict, prev: dict, *, threshold: float = 0.10
) -> RedFlag:
    """应收增速 − 营收增速；超过阈值(默认 10pp) → 压货红旗（doc 21）。

    课程逻辑：营收增长应伴随合理的应收增长；若应收增速远超营收，
    说明公司在放宽信用政策、向渠道压货冲收入，未来坏账/退货风险大。
    """
    rev_g = _growth(curr.get("revenue"), prev.get("revenue"))
    ar_g = _growth(
        curr.get("accounts_receivable") or curr.get("notes_receivable"),
        prev.get("accounts_receivable") or prev.get("notes_receivable"),
    )
    if rev_g is None or ar_g is None:
        return RedFlag("revenue_receivable_divergence", False, "数据不足")
    gap = ar_g - rev_g
    triggered = gap >= threshold
    return RedFlag(
        "revenue_receivable_divergence", triggered,
        f"应收增速 {ar_g:.1%} vs 营收增速 {rev_g:.1%}，差 {gap:+.1%}",
    )


def profit_cashflow_divergence(
    curr: dict, prev: dict, *, ocf_floor_ratio: float = 0.5
) -> RedFlag:
    """净利增长但 OCF 不增/为负 → 利润含金量低（doc 13/21）。

    课程逻辑：健康的利润应有现金流支撑。若净利大增而经营现金流停滞甚至
    下降（OCF/净利 < 0.5），说明利润停留在账面（应收/存货堆积），质量存疑。
    """
    np_g = _growth(curr.get("net_profit"), prev.get("net_profit"))
    ocf_g = _growth(curr.get("ocf"), prev.get("ocf"))
    np = curr.get("net_profit")
    ocf = curr.get("ocf")
    ocf_np_ratio = (ocf / np) if (np and np > 0 and ocf is not None) else None

    triggered = False
    detail = ""
    if np_g is not None and np_g > 0 and ocf_g is not None and ocf_g < 0:
        triggered = True
        detail = f"净利增 {np_g:.1%} 但 OCF 降 {ocf_g:.1%}"
    elif ocf_np_ratio is not None and ocf_np_ratio < ocf_floor_ratio:
        triggered = True
        detail = f"OCF/净利 = {ocf_np_ratio:.2f} < {ocf_floor_ratio}，含金量低"
    else:
        parts = []
        if np_g is not None:
            parts.append(f"净利增速 {np_g:.1%}")
        if ocf_g is not None:
            parts.append(f"OCF增速 {ocf_g:.1%}")
        if ocf_np_ratio is not None:
            parts.append(f"OCF/净利 {ocf_np_ratio:.2f}")
        detail = "；".join(parts) or "数据不足"
    return RedFlag("profit_cashflow_divergence", triggered, detail)


def inventory_anomaly(
    curr: dict, prev: dict, *, threshold: float = 0.15
) -> RedFlag:
    """存货增速 − 营收增速；超阈值(默认 15pp) → 积压红旗（doc 07/12）。

    课程逻辑：存货增速持续快于营收，可能产品滞销，后续存在跌价减值风险。
    """
    rev_g = _growth(curr.get("revenue"), prev.get("revenue"))
    inv_g = _growth(curr.get("inventory"), prev.get("inventory"))
    if rev_g is None or inv_g is None:
        return RedFlag("inventory_anomaly", False, "数据不足")
    gap = inv_g - rev_g
    triggered = gap >= threshold
    return RedFlag(
        "inventory_anomaly", triggered,
        f"存货增速 {inv_g:.1%} vs 营收增速 {rev_g:.1%}，差 {gap:+.1%}",
    )


def gross_margin_swing(
    curr: dict, prev: dict, *, swing_threshold: float = 0.05
) -> RedFlag:
    """毛利率同比突变 >5pp → 会计政策/成本操纵嫌疑（doc 13/21）。

    课程逻辑：成熟公司毛利率应相对稳定；短期大幅波动（尤其骤升）需警惕
    成本资本化、收入确认时点调整等会计操纵。
    """
    gm_c = _gm(curr)
    gm_p = _gm(prev)
    if gm_c is None or gm_p is None:
        return RedFlag("gross_margin_swing", False, "数据不足")
    delta = gm_c - gm_p
    triggered = abs(delta) >= swing_threshold
    return RedFlag(
        "gross_margin_swing", triggered,
        f"毛利率 {gm_p:.1%} → {gm_c:.1%}，变动 {delta:+.1%}",
    )


# ── 聚合：造假红旗报告 ──────────────────────────────────────────────────────

def detect_fraud_red_flags(periods: list[dict]) -> FraudReport:
    """聚合多期财报，用最近两期检测造假红旗（doc 21）。

    Args:
        periods: 按时间**升序**排列的财报快照列表（至少 2 期）。

    Returns:
        FraudReport（red_flags / triggered_count / severity）。
        severity: 0 项 clean / 1 项 watch / >=2 项 high_risk。
    """
    rep = FraudReport()
    if not periods or len(periods) < 2:
        rep.red_flags.append(RedFlag("insufficient_data", False, "需至少 2 期财报"))
        return rep
    curr, prev = periods[-1], periods[-2]
    rep.red_flags = [
        revenue_receivable_divergence(curr, prev),
        profit_cashflow_divergence(curr, prev),
        inventory_anomaly(curr, prev),
        gross_margin_swing(curr, prev),
    ]
    triggered = [f for f in rep.red_flags if f.triggered]
    rep.triggered_count = len(triggered)
    if rep.triggered_count >= 2:
        rep.severity = "high_risk"
    elif rep.triggered_count == 1:
        rep.severity = "watch"
    else:
        rep.severity = "clean"
    return rep
