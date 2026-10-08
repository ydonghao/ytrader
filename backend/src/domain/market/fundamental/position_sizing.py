"""仓位与安全边际建议（价值投资闭环第 4 期）。

透明优先：全部中间量（胜率/赔率/凯利/档位/截断来源）都透出，
模型假设见各公式注释。档位区间为主建议、半凯利为参考、
单票上限为硬约束——价值投资不假装能精确估计胜率，p 压在 0.75。
"""
from typing import Optional

_TIERS = {
    "strong": {"low": 15.0, "high": 20.0},
    "medium": {"low": 8.0, "high": 12.0},
    "weak": {"low": 0.0, "high": 5.0},
}


def _clamp(lo, hi, v):
    return max(lo, min(hi, v))


def suggest_position_size(
    quality_score: Optional[float],
    safety_margin_pct: Optional[float],
    *,
    downside_pct: float = 25.0,
    kelly_fraction: float = 0.5,
    single_cap_pct: float = 20.0,
    total_capital: Optional[float] = None,
    current_price: Optional[float] = None,
) -> dict:
    """质量×低估 → 仓位建议（档位区间+半凯利+单票上限）+ 三档建仓。

    quality_score:  财务质量分 0~100（compute_quality_report）
    safety_margin_pct: 安全边际%（(公允−价)/公允×100，正=低估）
    """
    if quality_score is None or safety_margin_pct is None:
        return {
            "data_missing": True, "tier": None, "band": None,
            "p": None, "upside_pct": None, "downside_pct": None,
            "kelly_full_pct": None, "kelly_half_pct": None,
            "suggested_pct": None, "capped_by": None,
            "single_cap_pct": single_cap_pct, "ladder": [],
        }

    margin = min(max(safety_margin_pct, 0.0), 95.0)
    p = _clamp(
        0.40, 0.75,
        0.45 + quality_score / 100.0 * 0.15
        + min(margin, 40.0) / 40.0 * 0.10,
    )
    upside_pct = (
        margin / (100.0 - margin) * 100.0 if margin > 0 else 0.0
    )

    kelly_full = 0.0
    if upside_pct > 0 and margin > 0:
        d = downside_pct / 100.0
        u = upside_pct / 100.0
        kelly_full = max(0.0, p / d - (1.0 - p) / u) * 100.0
    kelly_half = kelly_full * kelly_fraction

    if quality_score >= 75 and margin >= 30:
        tier = "strong"
    elif quality_score >= 60 and margin >= 15:
        tier = "medium"
    else:
        tier = "weak"
    band = dict(_TIERS[tier])

    capped_by = None
    if kelly_half <= 0:
        suggested = 0.0
        capped_by = "kelly_zero"
    else:
        suggested = _clamp(band["low"], band["high"], kelly_half)
        if (suggested >= single_cap_pct
                and kelly_half > single_cap_pct):
            suggested = single_cap_pct
            capped_by = "single_cap"
        else:
            capped_by = (
                "band_high" if suggested == band["high"]
                else "band_low" if suggested == band["low"]
                else "kelly"
            )

    ladder = []
    if suggested > 0:
        weights = [0.4, 0.3, 0.3]
        drops = [0, -8, -16]
        position_capital = (
            total_capital * suggested / 100.0
            if total_capital else None
        )
        for i, (w, drop) in enumerate(zip(weights, drops)):
            rung = {
                "rung_index": i + 1,
                "drop_pct": drop,
                "weight_of_position": w,
                "price_level": (
                    round(current_price * (1 + drop / 100.0), 3)
                    if current_price else None
                ),
                "amount": (
                    round(position_capital * w, 2)
                    if position_capital else None
                ),
            }
            if rung["amount"] and rung["price_level"]:
                lots = rung["amount"] / rung["price_level"] / 100.0
                # 金额不足一手时至少一手（可执行优先，允许小幅超配）
                rung["shares"] = max(1, round(lots)) * 100
            else:
                rung["shares"] = None
            ladder.append(rung)

    return {
        "data_missing": False,
        "tier": tier,
        "band": band,
        "p": round(p, 4),
        "upside_pct": round(upside_pct, 2),
        "downside_pct": downside_pct,
        "kelly_full_pct": round(kelly_full, 2),
        "kelly_half_pct": round(kelly_half, 2),
        "suggested_pct": suggested,
        "capped_by": capped_by,
        "single_cap_pct": single_cap_pct,
        "ladder": ladder,
    }
