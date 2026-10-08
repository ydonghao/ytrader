"""管理层与资本配置评估（价值投资闭环第 6 期 V1）。

四维：分红连续性 / 分红率 / ROIC / 筹码集中度，全部来自库内现成数据。
透明加权计分，缺数据维度按剩余权重归一；铁公鸡+低ROIC 硬规则直判
concerning。增减持/回购同步为 follow-up（见 spec）。
"""
from typing import List, Optional

_WEIGHTS = {"dividend": 30, "payout": 20, "roic": 35, "holder": 15}


def _consecutive(years: List[bool]) -> int:
    n = 0
    for paid in reversed(years):
        if paid:
            n += 1
        else:
            break
    return n


def capital_allocation(
    dividend_years: Optional[List[bool]],
    payout_pct: Optional[float],
    roic_pct: Optional[float],
    holder_change_pct: Optional[float],
) -> dict:
    """四维 → {score, verdict, consecutive_dividend_years, iron_rooster,
    payout_zone, roic_zone, holder_change, flags, reasons}。"""
    consecutive = _consecutive(dividend_years) if dividend_years else 0
    iron_rooster = bool(
        dividend_years and len(dividend_years) >= 8
        and not any(dividend_years)
    )

    flags: List[str] = []
    gains: List[str] = []

    # ── 分红连续性 ──
    div_dim = None
    if dividend_years:
        if consecutive >= 5:
            div_dim = 1.0
            gains.append(f"连续 {consecutive} 年分红")
        elif iron_rooster:
            div_dim = 0.0
            flags.append("铁公鸡：长期零分红")
        elif consecutive >= 1:
            div_dim = 0.6
        else:
            div_dim = 0.2

    # ── 分红率 ──
    pay_dim = None
    if payout_pct is not None:
        if 20.0 <= payout_pct <= 70.0:
            pay_dim = 1.0
            gains.append(f"分红率 {payout_pct:.0f}% 合理")
        elif payout_pct > 90.0:
            pay_dim = 0.3
            flags.append("分红率>90%，不可持续")
        elif payout_pct < 10.0:
            pay_dim = 0.3
            if not (roic_pct is not None and roic_pct >= 12.0):
                flags.append("分红率<10% 且 ROIC 不高，回报股东意愿弱")
        else:
            pay_dim = 0.8

    # ── ROIC ──
    roic_dim = None
    if roic_pct is not None:
        if roic_pct >= 12.0:
            roic_dim = 1.0
            gains.append(f"ROIC {roic_pct:.1f}% 优秀")
        elif roic_pct >= 8.0:
            roic_dim = 0.7
        elif roic_pct >= 6.0:
            roic_dim = 0.4
        else:
            roic_dim = 0.0
            flags.append(f"ROIC {roic_pct:.1f}%<6%，再投资毁灭价值")

    # ── 筹码（弱信号） ──
    hold_dim = None
    holder_label = None
    if holder_change_pct is not None:
        if holder_change_pct <= -10.0:
            hold_dim, holder_label = 1.0, "集中"
        elif holder_change_pct >= 30.0:
            hold_dim, holder_label = 0.0, "分散"
        else:
            hold_dim, holder_label = 0.6, "平稳"

    dims = {
        "dividend": div_dim, "payout": pay_dim,
        "roic": roic_dim, "holder": hold_dim,
    }
    avail_w = sum(_WEIGHTS[k] for k, v in dims.items() if v is not None)
    score = None
    if avail_w > 0:
        score = round(
            sum(_WEIGHTS[k] * v for k, v in dims.items()
                if v is not None) / avail_w * 100,
        )

    verdict = "unknown"
    if score is not None:
        if iron_rooster and roic_pct is not None and roic_pct < 6.0:
            verdict = "concerning"     # 硬规则
        elif score >= 70:
            verdict = "shareholder_friendly"
        elif score >= 45:
            verdict = "neutral"
        else:
            verdict = "concerning"

    return {
        "score": score,
        "verdict": verdict,
        "consecutive_dividend_years": consecutive,
        "iron_rooster": iron_rooster,
        "payout_pct": payout_pct,
        "roic_pct": roic_pct,
        "holder_change": {
            "pct": holder_change_pct, "label": holder_label,
        },
        "flags": flags,
        "reasons": gains,
        "weights": _WEIGHTS,
        "note": "V1 四维（分红/分红率/ROIC/筹码）；"
                "增减持与回购待同步链路后并入。",
    }
