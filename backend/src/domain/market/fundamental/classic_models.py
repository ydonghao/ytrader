"""股票投资课程——经典量化诊断模型（docs 12/13/19/21 补强）纯函数。

簇 1 的 quality_report 是自研透明加权体系；本模块引入两个学术界广泛验证、
课程检查清单（doc 21）精神相通的**经典多因子模型**：

    Altman Z-Score   破产预测 5 因子（1968 制造业模型）
        Z = 1.2·X1 + 1.4·X2 + 3.3·X3 + 0.6·X4 + 1.0·X5
        >2.99 安全 / 1.81~2.99 灰色 / <1.81 高破产风险
    Beneish M-Score  盈余操纵 8 因子（1999）
        M = -4.84 + ...（8 项指数）；M > -1.78 操纵嫌疑
    Piotroski F-Score 财务质量 9 因子（2000）
        盈利/杠杆/效率三组各 3 项；0~9 分，≥8 强质量

与 fraud_signals（规则红旗）互补：M-Score 是统计模型，对系统性盈余管理更敏感。

数据口径
--------
- 流动资产/负债、留存收益、EBIT、折旧、销管费：部分不在固定列，需从
  ``detail`` JSONB 抽取或由调用方以命名参数供给（缺失则该模型返回 None）。
- 市值：来自 stock_valuation.total_mv（调用方传入 ``market_cap``）。
全部纯函数。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── Altman Z-Score（破产预测）────────────────────────────────────────────────

@dataclass
class AltmanZScore:
    z: float
    x1: Optional[float]   # 营运资本/总资产
    x2: Optional[float]   # 留存收益/总资产
    x3: Optional[float]   # EBIT/总资产
    x4: Optional[float]   # 市值/总负债
    x5: Optional[float]   # 销售额/总资产
    verdict: str          # safe / grey / distress


def altman_z_score(
    fin: dict,
    *,
    market_cap: Optional[float],
    retained_earnings: Optional[float] = None,
    current_assets: Optional[float] = None,
    current_liabilities: Optional[float] = None,
    ebit: Optional[float] = None,
) -> Optional[AltmanZScore]:
    """Altman Z-Score 破产预测（5 因子制造业模型）。

    Args:
        fin: 基本面快照，至少含 total_assets / total_liabilities / revenue。
        market_cap:          股东权益市值（必填，来自估值表 total_mv）。
        retained_earnings:   留存收益（detail 科目；缺失用 equity 粗估并标注）。
        current_assets:      流动资产合计（detail）。
        current_liabilities: 流动负债合计（detail）。
        ebit:                息税前利润（缺省用 operating_profit 近似）。

    Returns:
        AltmanZScore；总资产/总负债/市值/营收任一缺失返回 None。
    留存收益/流动资产缺失时用近似（X2/X1 精度降低，但仍出分）。
    """
    ta = fin.get("total_assets")
    tl = fin.get("total_liabilities")
    rev = fin.get("revenue")
    mc = market_cap
    if not ta or not tl or mc is None or not rev:
        return None

    # X1 营运资本/总资产
    ca = current_assets if current_assets is not None else fin.get("current_assets")
    cl = current_liabilities if current_liabilities is not None else fin.get("current_liabilities")
    if ca is not None and cl is not None:
        x1 = (ca - cl) / ta
    else:
        x1 = None  # 缺流动资产/负债 → 该项置 0（保守）
    # X2 留存收益/总资产（缺省用 equity 近似，高估但可接受）
    re = retained_earnings if retained_earnings is not None else fin.get("retained_earnings")
    x2 = (re / ta) if re is not None else None
    # X3 EBIT/总资产
    eb = ebit if ebit is not None else fin.get("ebit", fin.get("operating_profit"))
    x3 = (eb / ta) if eb is not None else None
    # X4 市值/总负债
    x4 = mc / tl if tl != 0 else None
    # X5 销售额/总资产
    x5 = rev / ta

    z = (1.2 * (x1 or 0.0) + 1.4 * (x2 or 0.0) + 3.3 * (x3 or 0.0)
         + 0.6 * (x4 or 0.0) + 1.0 * x5)
    if z > 2.99:
        verdict = "safe"
    elif z > 1.81:
        verdict = "grey"
    else:
        verdict = "distress"
    return AltmanZScore(z=z, x1=x1, x2=x2, x3=x3, x4=x4, x5=x5, verdict=verdict)


# ── Beneish M-Score（盈余操纵）──────────────────────────────────────────────

@dataclass
class BeneishMScore:
    m: Optional[float]
    partial: bool            # 是否缺 DEPI/SGAI（折旧/销管费）项
    components: dict         # 8 项指数明细
    verdict: str             # manipulator / watch / clean


def beneish_m_score(
    curr: dict,
    prev: dict,
    *,
    sga_curr: Optional[float] = None,
    sga_prev: Optional[float] = None,
    depreciation_curr: Optional[float] = None,
    depreciation_prev: Optional[float] = None,
    net_ppe_curr: Optional[float] = None,
    net_ppe_prev: Optional[float] = None,
) -> Optional[BeneishMScore]:
    """Beneish M-Score 盈余操纵检测（8 因子）。

    需相邻两期财报。8 项指数：
        DSRI  应收周转天数指数（应收/营收 变化）
        GMI   毛利恶化（毛利率 prev/curr）
        AQI   资产质量（非流动资产占比变化）
        SGI   销售增长
        DEPI  折旧率指数（需折旧+净固定资产）
        SGAI  销管费指数（需销管费）
        TATA  应计项目（(净利−OCF)/总资产）
        LVGI  杠杆指数（资产负债率变化）

    Args:
        curr/prev: 两期快照（revenue/accounts_receivable/gross_margin 或 gross_profit/
                   current_assets/total_assets/net_profit/ocf/total_liabilities）。
        sga_curr/prev:               销管费（sell+admin expense，可选）。
        depreciation_curr/prev:      折旧（可选）。
        net_ppe_curr/prev:           净固定资产（可选，算 DEPI）。

    Returns:
        BeneishMScore；核心字段缺失返回 None。缺 DEPI/SGAI 时该两项贡献置 0
        且 partial=True。M > -1.78 操纵嫌疑 / -1.78~-2.22 观察区 / < -2.22 干净。
    """
    def _gm(snap):
        gm = snap.get("gross_margin")
        if gm is not None:
            return gm
        gp = snap.get("gross_profit")
        rev = snap.get("revenue")
        return (gp / rev) if (gp is not None and rev and rev > 0) else None

    rev_c, rev_p = curr.get("revenue"), prev.get("revenue")
    ta_c, ta_p = curr.get("total_assets"), prev.get("total_assets")
    if not rev_c or not rev_p or not ta_c or not ta_p or rev_p <= 0 or ta_p <= 0:
        return None

    # DSRI
    ar_c, ar_p = curr.get("accounts_receivable"), prev.get("accounts_receivable")
    dsri = None
    if ar_c is not None and ar_p is not None and rev_c > 0 and rev_p > 0:
        dsri = (ar_c / rev_c) / (ar_p / rev_p)
    # GMI
    gm_c, gm_p = _gm(curr), _gm(prev)
    gmi = (gm_p / gm_c) if (gm_c and gm_p and gm_c != 0) else None
    # AQI
    ca_c, ca_p = curr.get("current_assets"), prev.get("current_assets")
    aqi = None
    if ca_c is not None and ca_p is not None:
        nca_c = (1 - ca_c / ta_c)
        nca_p = (1 - ca_p / ta_p)
        aqi = (nca_c / nca_p) if nca_p != 0 else None
    # SGI
    sgi = rev_c / rev_p
    # TATA
    np_c, ocf_c = curr.get("net_profit"), curr.get("ocf")
    tata = ((np_c - ocf_c) / ta_c) if (np_c is not None and ocf_c is not None) else None
    # LVGI
    tl_c, tl_p = curr.get("total_liabilities"), prev.get("total_liabilities")
    lvgi = None
    if tl_c is not None and tl_p is not None and ta_c > 0 and ta_p > 0:
        lvgi = (tl_c / ta_c) / (tl_p / ta_p)

    partial = False
    # DEPI（需折旧+净固定资产）
    dep_c = depreciation_curr if depreciation_curr is not None else curr.get("depreciation")
    dep_p = depreciation_prev if depreciation_prev is not None else prev.get("depreciation")
    ppe_c = net_ppe_curr if net_ppe_curr is not None else curr.get("net_ppe", curr.get("fixed_assets"))
    ppe_p = net_ppe_prev if net_ppe_prev is not None else prev.get("net_ppe", prev.get("fixed_assets"))
    depi = None
    if all(v is not None and v > 0 for v in (dep_c, dep_p, ppe_c, ppe_p)):
        rate_c = dep_c / (dep_c + ppe_c)
        rate_p = dep_p / (dep_p + ppe_p)
        depi = rate_p / rate_c if rate_c != 0 else None
    # SGAI（需销管费）
    sg_c = sga_curr if sga_curr is not None else curr.get("sga_expense")
    sg_p = sga_prev if sga_prev is not None else prev.get("sga_expense")
    sgai = None
    if sg_c is not None and sg_p is not None and rev_c > 0 and rev_p > 0:
        sgai = (sg_c / rev_c) / (sg_p / rev_p)

    # 核心四项必须有（DSRI/GMI/SGI/TATA），其余尽量补
    if dsri is None or gmi is None or tata is None:
        return None
    aqi_v = aqi if aqi is not None else 1.0
    lvgi_v = lvgi if lvgi is not None else 1.0
    if depi is None or sgai is None:
        partial = True
    depi_v = depi if depi is not None else 1.0
    sgai_v = sgai if sgai is not None else 1.0

    m = (-4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi_v + 0.892 * sgi
         + 0.115 * depi_v - 0.172 * sgai_v + 4.679 * tata - 0.327 * lvgi_v)
    if m > -1.78:
        verdict = "manipulator"
    elif m > -2.22:
        verdict = "watch"
    else:
        verdict = "clean"
    return BeneishMScore(
        m=m, partial=partial,
        components={"DSRI": dsri, "GMI": gmi, "AQI": aqi, "SGI": sgi,
                    "DEPI": depi, "SGAI": sgai, "TATA": tata, "LVGI": lvgi},
        verdict=verdict,
    )


# ── Piotroski F-Score（财务质量 9 因子）─────────────────────────────────────

@dataclass
class PiotroskiFScore:
    score: int          # 通过因子数（0~9）
    evaluated: int      # 可评估因子数（缺数据的因子不计入）
    partial: bool       # 是否有因子缺数据（评分口径降级）
    components: dict    # {因子名: {"pass": True/False/None, "why": str}}
    verdict: str        # strong(>=8) / good(>=6) / mediocre(>=4) / weak(<4)


def _interest_debt(snap: dict) -> Optional[float]:
    """有息负债 = 短借+长借+应付债券+一年内到期非流动负债（缺失项跳过）。"""
    keys = ("short_loan", "long_loan", "bonds_payable",
            "non_current_liab_due_within_1y")
    parts = [snap.get(k) for k in keys]
    if all(p is None for p in parts):
        return None
    return sum(p for p in parts if p is not None)


def _gm_ratio(snap: dict) -> Optional[float]:
    gm = snap.get("gross_margin")
    if gm is not None:
        # 兼容两种口径：百分比(如 30.0) 或比率(0.3)——只用于两期同口径比较
        return gm
    gp, rev = snap.get("gross_profit"), snap.get("revenue")
    return (gp / rev) if (gp is not None and rev and rev > 0) else None


def piotroski_f_score(curr: dict, prev: dict) -> Optional[PiotroskiFScore]:
    """Piotroski F-Score（2000）标准 9 因子——需**相邻两个年报**快照。

    盈利：ROA>0 / ΔROA>0 / CFO>0 / 应计质量(CFO ROA > 会计 ROA)
    杠杆：有息负债率下降 / 流动比率上升 / 未增发股本
    效率：毛利率上升 / 总资产周转率上升

    Args:
        curr/prev: 两个年报期快照。用到的键：net_profit / total_assets /
            ocf / revenue / gross_margin(或 gross_profit) / short_loan /
            long_loan / bonds_payable / non_current_liab_due_within_1y /
            current_assets / current_liabilities / share_capital。
            有息负债四项全缺时退化用 total_liabilities 口径；股本缺则
            该因子置 None（partial）。

    Returns:
        PiotroskiFScore；两期总资产/净利/营收任一缺失返回 None。
        缺数据的因子 pass=None 不计分（evaluated<9, partial=True），
        避免"数据越少分越高"的偏置。
    """
    ta_c, ta_p = curr.get("total_assets"), prev.get("total_assets")
    np_c, np_p = curr.get("net_profit"), prev.get("net_profit")
    rev_c, rev_p = curr.get("revenue"), prev.get("revenue")
    if not ta_c or not ta_p or np_c is None or np_p is None \
            or not rev_c or not rev_p:
        return None

    def _factor(passed, why):
        return {"pass": passed, "why": why}

    components: dict = {}
    roa_c = np_c / ta_c
    roa_p = np_p / ta_p

    # 1 ROA > 0
    components["roa_positive"] = _factor(
        roa_c > 0, f"ROA {roa_c:.1%}")
    # 2 ΔROA > 0
    components["roa_improving"] = _factor(
        roa_c > roa_p, f"ROA {roa_p:.1%} → {roa_c:.1%}")
    # 3 CFO > 0
    ocf = curr.get("ocf")
    if ocf is None:
        components["cfo_positive"] = _factor(None, "缺 OCF")
    else:
        components["cfo_positive"] = _factor(
            ocf > 0, f"OCF/总资产 {ocf / ta_c:.1%}")
    # 4 应计质量：CFO ROA > 会计 ROA
    if ocf is None:
        components["accrual_quality"] = _factor(None, "缺 OCF")
    else:
        cfo_roa = ocf / ta_c
        components["accrual_quality"] = _factor(
            cfo_roa > roa_c,
            f"CFO ROA {cfo_roa:.1%} vs ROA {roa_c:.1%}")

    # 5 有息负债率下降（全缺退化为资产负债率口径）
    debt_c, debt_p = _interest_debt(curr), _interest_debt(prev)
    lev_note = "有息负债率"
    if debt_c is None and debt_p is None:
        debt_c = curr.get("total_liabilities")
        debt_p = prev.get("total_liabilities")
        lev_note = "资产负债率(有息科目缺失退化)"
    if debt_c is None or debt_p is None:
        components["leverage_decreasing"] = _factor(None, "缺负债科目")
    else:
        lev_c, lev_p = debt_c / ta_c, debt_p / ta_p
        components["leverage_decreasing"] = _factor(
            lev_c < lev_p, f"{lev_note} {lev_p:.1%} → {lev_c:.1%}")

    # 6 流动比率上升
    def _cr(snap):
        ca, cl = snap.get("current_assets"), snap.get("current_liabilities")
        return (ca / cl) if (ca is not None and cl and cl > 0) else None
    cr_c, cr_p = _cr(curr), _cr(prev)
    if cr_c is None or cr_p is None:
        components["current_ratio_improving"] = _factor(None, "缺流动资产/负债")
    else:
        components["current_ratio_improving"] = _factor(
            cr_c > cr_p, f"流动比率 {cr_p:.2f} → {cr_c:.2f}")

    # 7 未增发（股本未增加）
    sh_c, sh_p = curr.get("share_capital"), prev.get("share_capital")
    if sh_c is None or sh_p is None:
        components["no_share_dilution"] = _factor(None, "缺股本科目")
    else:
        components["no_share_dilution"] = _factor(
            sh_c <= sh_p, f"股本 {sh_p:.0f} → {sh_c:.0f}")

    # 8 毛利率上升
    gm_c, gm_p = _gm_ratio(curr), _gm_ratio(prev)
    if gm_c is None or gm_p is None:
        components["gross_margin_improving"] = _factor(None, "缺毛利率")
    else:
        components["gross_margin_improving"] = _factor(
            gm_c > gm_p, f"毛利率 {gm_p:.1%} → {gm_c:.1%}"
            if max(abs(gm_c), abs(gm_p)) <= 1
            else f"毛利率 {gm_p:.1f}% → {gm_c:.1f}%")

    # 9 总资产周转率上升
    at_c, at_p = rev_c / ta_c, rev_p / ta_p
    components["asset_turnover_improving"] = _factor(
        at_c > at_p, f"周转率 {at_p:.2f} → {at_c:.2f}")

    passes = [v["pass"] for v in components.values()]
    score = sum(1 for p in passes if p is True)
    evaluated = sum(1 for p in passes if p is not None)
    partial = any(p is None for p in passes)
    if score >= 8:
        verdict = "strong"
    elif score >= 6:
        verdict = "good"
    elif score >= 4:
        verdict = "mediocre"
    else:
        verdict = "weak"
    return PiotroskiFScore(
        score=score, evaluated=evaluated, partial=partial,
        components=components, verdict=verdict,
    )
