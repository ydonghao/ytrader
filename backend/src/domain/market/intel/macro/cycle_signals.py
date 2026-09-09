"""股票投资课程簇 4——宏观周期（docs 02/31）纯函数。

确定性（规则驱动）宏观信号，与 intel/macro 下 LLM 分析互补：
本模块回答"现在处于周期哪个位置、流动性是否宽松、哪些行业应超配"，
全部为可单测的纯函数，输入为已采集的宏观指标读数（来自 macro_indicator 表）。

口径约定
--------
- 增速类指标统一为小数（0.05 = 5%）；PMI 用绝对值（50 为荣枯线）；
- PPI 以同比符号判定方向（>0 = 上游涨价/扩张，<0 = 通缩）；
- "背离/缺口"返回值为百分点差。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# ── 4.1 三部门指标清单 + 方向（doc 31）────────────────────────────────────────

# 每个部门的关键指标及其"利好方向"。``direction``:
#   "high_good"  偏高=健康（如可支配收入增速、PMI）
#   "low_good"   偏低=健康（如失业率、不良率）
#   "range"      区间内为佳（如 CPI 2~3%），用 (lo, hi) 表达
THREE_SECTOR_INDICATORS = {
    "household": {  # 居民部门
        "unemployment_rate":   {"name": "城镇调查失业率", "direction": "low_good", "threshold": 0.055},
        "disposable_income":   {"name": "居民可支配收入增速", "direction": "high_good"},
        "cpi_yoy":             {"name": "CPI 同比", "direction": "range", "range": (0.01, 0.03)},
        "real_estate_invest":  {"name": "房地产开发投资增速", "direction": "high_good"},
    },
    "enterprise": {  # 企业部门
        "ppi_yoy":             {"name": "PPI 同比", "direction": "high_good"},
        "pmi":                 {"name": "制造业 PMI", "direction": "high_good", "threshold": 50.0},
        "industrial_profit":   {"name": "规上工业企业利润增速", "direction": "high_good"},
        "fai_invest":          {"name": "固定资产投资增速", "direction": "high_good"},
    },
    "government": {  # 政府部门（货币/信用）
        "lpr":                 {"name": "LPR(1Y)", "direction": "low_good"},
        "m2_growth":           {"name": "M2 增速", "direction": "high_good"},
        "social_financing":    {"name": "社融增速", "direction": "high_good"},
        "macro_leverage":      {"name": "宏观杠杆率", "direction": "low_good"},
    },
}


def classify_indicator(spec: dict, value: Optional[float]) -> Optional[str]:
    """按部门指标 spec 的方向/阈值，把读数判为 good/neutral/bad。

    Args:
        spec:  THREE_SECTOR_INDICATORS 中的条目（含 name/direction/可选 threshold/range）。
        value: 当前读数（小数或绝对值）。

    Returns:
        ``"good"`` / ``"neutral"`` / ``"bad"``；value 为 None 返回 None（无数据）。
    """
    if value is None or not math.isfinite(value):
        return None
    direction = spec.get("direction", "neutral")
    if direction == "high_good":
        thr = spec.get("threshold")
        if thr is not None:
            return "good" if value >= thr else ("neutral" if value >= thr * 0.9 else "bad")
        return "good" if value > 0 else "bad"
    if direction == "low_good":
        thr = spec.get("threshold")
        if thr is not None:
            return "good" if value <= thr else ("neutral" if value <= thr * 1.1 else "bad")
        return "good" if value <= 0 else "neutral"
    if direction == "range":
        lo, hi = spec.get("range", (None, None))
        if lo is not None and hi is not None:
            return "good" if lo <= value <= hi else "neutral"
    return "neutral"


def three_sector_checklist(readings: dict) -> dict:
    """三部门景气度体检（doc 31）。

    Args:
        readings: ``{indicator_code: value}``，来自 macro_indicator 最新读数。
                  key 与 THREE_SECTOR_INDICATORS 中的 code 对齐（如 "pmi"/"cpi_yoy"）。

    Returns:
        ``{sector: {indicator: {name, value, status}}} + overall_health(0~1)``。
        overall_health = good 占比（neutral 记 0.5）。
    """
    out: dict = {}
    good_score = 0.0
    total = 0.0
    for sector, specs in THREE_SECTOR_INDICATORS.items():
        s_out: dict = {}
        for code, spec in specs.items():
            v = readings.get(code)
            status = classify_indicator(spec, v)
            s_out[code] = {"name": spec["name"], "value": v, "status": status}
            if status is not None:
                total += 1.0
                good_score += {"good": 1.0, "neutral": 0.5, "bad": 0.0}[status]
        out[sector] = s_out
    out["overall_health"] = (good_score / total) if total > 0 else None
    return out


# ── 4.2 景气度组合信号（PMI × PPI 四象限）────────────────────────────────────

PHASE_DOWNTURN = "downturn"        # 低迷：PMI<50 + PPI 通缩
PHASE_RECOVERY = "recovery"        # 复苏：PMI>=50 + PPI 通缩(回暖)
PHASE_OVERHEAT = "overheat"        # 过热：PMI>=50 + PPI 涨价
PHASE_STAGFLATION = "stagflation"  # 滞胀：PMI<50 + PPI 涨价

_PHASE_LABELS = {
    PHASE_DOWNTURN: "低迷（通缩+收缩）",
    PHASE_RECOVERY: "复苏（扩张+物价仍低）",
    PHASE_OVERHEAT: "过热（扩张+通胀）",
    PHASE_STAGFLATION: "滞胀（收缩+通胀）",
}


def business_cycle_phase(
    pmi: Optional[float],
    ppi_yoy: Optional[float],
    *,
    pmi_pivot: float = 50.0,
) -> Optional[dict]:
    """PMI（荣枯线）× PPI（同比符号）四象限定周期位置（doc 31）。

    Args:
        pmi:     制造业 PMI 绝对值。
        ppi_yoy: PPI 同比（小数，>0 = 上游涨价）。
        pmi_pivot: PMI 荣枯线，默认 50。

    Returns:
        {phase, label, pmi_expanding, ppi_inflationary}；任一输入缺失返回 None。
    """
    if pmi is None or ppi_yoy is None:
        return None
    expanding = pmi >= pmi_pivot
    inflationary = ppi_yoy > 0
    if (not expanding) and (not inflationary):
        phase = PHASE_DOWNTURN
    elif expanding and (not inflationary):
        phase = PHASE_RECOVERY
    elif expanding and inflationary:
        phase = PHASE_OVERHEAT
    else:
        phase = PHASE_STAGFLATION
    return {
        "phase": phase,
        "label": _PHASE_LABELS[phase],
        "pmi_expanding": expanding,
        "ppi_inflationary": inflationary,
    }


# ── 4.3 股市-宏观背离（系统性风险预警）──────────────────────────────────────

@dataclass
class EquityMacroDivergence:
    index_return: float            # 指数区间涨幅（小数）
    profit_growth: float           # 工业企业利润增速（小数）
    divergence: float              # = index_return - profit_growth（百分点差）
    bubble_warning: bool           # 背离过大 → 泡沫/系统性风险


def equity_macro_divergence(
    index_return: Optional[float],
    profit_growth: Optional[float],
    *,
    warning_gap: float = 0.20,
) -> Optional[EquityMacroDivergence]:
    """指数涨幅 − 工业企业利润增速 → 泡沫预警（doc 16/25/31）。

    课程逻辑：长期股市涨幅应与企业盈利匹配；若市值涨幅远超利润增速，
    说明上涨由估值驱动而非盈利，存在系统性回调风险。

    Args:
        index_return:   指数区间涨幅（小数，如 0.30 = 30%）。
        profit_growth:  工业企业利润增速（同口径小数）。
        warning_gap:    触发泡沫预警的背离阈值（百分点差），默认 20%。

    Returns:
        EquityMacroDivergence；输入缺失返回 None。
    """
    if index_return is None or profit_growth is None:
        return None
    div = index_return - profit_growth
    return EquityMacroDivergence(
        index_return=index_return,
        profit_growth=profit_growth,
        divergence=div,
        bubble_warning=div >= warning_gap,
    )


# ── 4.4 行业轮动规则表（doc 31）──────────────────────────────────────────────

# 各周期阶段建议超配/低配的行业（行业名与 config 申万一级行业对齐）。
INDUSTRY_ROTATION = {
    PHASE_RECOVERY: {
        "overweight": ["有色金属", "煤炭", "机械设备", "非银金融"],  # 早周期+券商
        "rationale": "复苏期需求回暖、上游原材料领涨、券商对市场敏感先涨",
    },
    PHASE_OVERHEAT: {
        "overweight": ["有色金属", "煤炭", "钢铁", "化工", "石油石化"],  # 资源品涨价
        "rationale": "过热期大宗商品价格上行，资源/周期股盈利弹性最大",
    },
    PHASE_DOWNTURN: {
        "overweight": ["食品饮料", "医药生物", "公用事业", "家用电器"],  # 防御
        "rationale": "低迷期盈利确定性优先，必需消费/公用事业抗周期",
    },
    PHASE_STAGFLATION: {
        "overweight": ["食品饮料", "医药生物", "农林牧渔", "煤炭"],  # 防御+通胀对冲
        "rationale": "滞胀期防御+抗通胀，农业/煤炭受益于物价上行",
    },
}


def industry_rotation(phase: Optional[str]) -> Optional[dict]:
    """按周期阶段返回行业轮动建议（doc 31）。

    Args:
        phase: business_cycle_phase 返回的 phase 字符串。

    Returns:
        ``{overweight: [...], rationale: str}``；未知/None 返回 None。
    """
    if phase is None:
        return None
    entry = INDUSTRY_ROTATION.get(phase)
    return dict(entry) if entry else None


# ── 4.5 M2 vs GDP 货币超发（doc 02）──────────────────────────────────────────

@dataclass
class MoneySupplyGap:
    nominal_gap: float       # M2 增速 - GDP 增速（名义超额）
    real_gap: Optional[float]  # M2 增速 - (GDP 增速 + CPI)，扣除通胀的真实超额
    verdict: str             # loose / neutral / tight


def money_supply_gap(
    m2_growth: Optional[float],
    gdp_growth: Optional[float],
    cpi: Optional[float] = None,
    *,
    loose_threshold: float = 0.03,
) -> Optional[MoneySupplyGap]:
    """M2 增速 − GDP 增速 → 货币宽松/超发判断（doc 02）。

    课程逻辑：M2 增速持续高于 GDP 增速，说明货币投放快于实体需求，
    形成流动性宽松（利好资产价格）；反之偏紧。

    Args:
        m2_growth:   M2 同比增速（小数）。
        gdp_growth:  GDP 同比增速（小数）。
        cpi:         CPI 同比（小数，可选）；提供时额外算"真实超额"
                     = M2 − (GDP + CPI)。
        loose_threshold: 名义超额>=该值判为宽松，默认 3%。

    Returns:
        MoneySupplyGap；M2/GDP 缺失返回 None。
    """
    if m2_growth is None or gdp_growth is None:
        return None
    nominal = m2_growth - gdp_growth
    real = (m2_growth - gdp_growth - cpi) if cpi is not None else None
    if nominal >= loose_threshold:
        verdict = "loose"
    elif nominal <= -loose_threshold:
        verdict = "tight"
    else:
        verdict = "neutral"
    return MoneySupplyGap(nominal_gap=nominal, real_gap=real, verdict=verdict)
