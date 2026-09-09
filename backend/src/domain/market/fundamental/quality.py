"""
财务质量诊断（纯函数）
=====================
基于 stock_financial_detail（三大报表合并单期快照）计算"公司财务健不健康"
的诊断指标，对应《股票投资课程》08/12/13/19/21 集中强调的"先筛掉 80% 垃圾公司"
的初级筛选层。现有系统仅有 ROE/毛利率/净利率/资产负债率/FCF，本模块补齐：

  - 收现比 / 净现比（盈利现金含量）
  - 现金覆盖短期债务、应收款 vs 现金（两条淘汰红线）
  - 费用/毛利比三档评级（课程给出的最精确阈值 30%/70%）
  - 杜邦三因子分解（定位 ROE 驱动来源）
  - 经营性/有息负债拆分、重/轻资产分类、存货/营收比、商誉占比
  - 毛利率商业模式分类、投资/筹资现金流阶段四象限
  - compute_quality_report 聚合：透明加权评分 + 淘汰红线否决 + verdict

输入 fin dict 的 key（由 data_loader.fetch_financial_snapshot 提供）：
  固定列：revenue, operating_cost, gross_profit, sell_expense, admin_expense,
          rd_expense, fin_expense, operating_profit, net_profit,
          monetary_funds, accounts_receivable, inventory, fixed_assets, goodwill,
          total_assets, total_liabilities, equity, short_loan, long_loan,
          ocf, icf, fcf(筹资活动CF！非自由现金流), free_cash_flow
  detail 扁平化（fetch_financial_snapshot 合并）：cash_from_sales,
          trading_financial_assets, accounts_payable, contract_liability,
          advance_receipts, notes_payable, notes_receivable, other_receivables,
          non_current_liab_due_within_1y, construction_in_progress, bonds_payable

口径与 derived_metrics.py / dcf.py 一致：缺失返回 None，不抛异常；
比率类保留 4 位小数；评分/聚合返回 dict。

⚠️ 注意：stock_financial_detail.fcf 列是"筹资活动现金流量净额"，不是自由现金流；
   自由现金流是 free_cash_flow。cash_flow_stage 用 fcf（筹资口径），其余 FCF 用 free_cash_flow。
"""
from __future__ import annotations

from typing import Optional


# ──────────────────────────────────────────────────────────────────────────────
#  内部工具
# ──────────────────────────────────────────────────────────────────────────────

def _num(x) -> Optional[float]:
    """转 float；bool/None/非法返回 None。"""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    return None


def _add(a, b) -> Optional[float]:
    """两者皆数值则相加；仅一个为数值返回该值；均非数值返回 None。"""
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return na + nb
    return na if na is not None else nb


def _sum(*xs) -> Optional[float]:
    """对多个值做宽容求和（None 跳过）；全部缺失返回 None。"""
    acc: Optional[float] = None
    for x in xs:
        acc = _add(acc, x)
    return acc


def _norm(value: float, lo: float, hi: float) -> float:
    """把 value 线性归一到 0–100（[lo,hi]→[0,100]，超出截断）。"""
    if hi <= lo:
        return 0.0
    t = (value - lo) / (hi - lo)
    return max(0.0, min(100.0, t * 100.0))


# ──────────────────────────────────────────────────────────────────────────────
#  盈利现金含量
# ──────────────────────────────────────────────────────────────────────────────

def cash_to_revenue(fin: dict) -> Optional[float]:
    """收现比(倍) = 销售商品、提供劳务收到的现金 / 营业收入。

    >1 先款后货（供应链强势、产品畅销）；长期 <1 回款差、应收高（风险）。
    cash_from_sales 缺失或营收为 0 返回 None。
    """
    cs = _num(fin.get("cash_from_sales"))
    rev = _num(fin.get("revenue"))
    if cs is None or not rev:
        return None
    return round(cs / rev, 4)


def ocf_net_income_ratio(fin: dict) -> Optional[float]:
    """净现比(倍) = 经营活动现金流量净额 / 净利润。

    >1 利润质量高（利润有真金白银支撑）；持续 <1 盈利质量差（应收高/库存积压）。
    净利润 <= 0（亏损）时返回 None（比值无意义，亏损由 red_flag 标记）。
    """
    ocf = _num(fin.get("ocf"))
    net = _num(fin.get("net_profit"))
    if ocf is None or net is None or net <= 0:
        return None
    return round(ocf / net, 4)


# ──────────────────────────────────────────────────────────────────────────────
#  流动性 / 淘汰红线
# ──────────────────────────────────────────────────────────────────────────────

def short_term_debt(fin: dict) -> Optional[float]:
    """短期刚性债务 = 短期借款 + 一年内到期的非流动负债。

    一年内到期科目缺失时退化为仅短期借款（宽容近似）。
    """
    return _add(fin.get("short_loan"), fin.get("non_current_liab_due_within_1y"))


def cash_like(fin: dict) -> Optional[float]:
    """现金类资产 = 货币资金 + 交易性金融资产。交易性金融资产缺失退化为仅货币资金。"""
    return _add(fin.get("monetary_funds"), fin.get("trading_financial_assets"))


def cash_coverage_short_debt(fin: dict) -> Optional[float]:
    """现金覆盖短期债务(倍) = 现金类资产 / 短期刚性债务。

    **<1 即淘汰红线**（账上现金覆盖不了短期债务，现金流压力极大）。
    短期债务为 0 或缺失返回 None。
    """
    cash = cash_like(fin)
    std = short_term_debt(fin)
    if cash is None or std is None or std <= 0:
        return None
    return round(cash / std, 4)


def ar_vs_cash_flag(fin: dict) -> Optional[dict]:
    """应收款 vs 现金 淘汰标记。

    应收款（应收账款 + 应收票据）> 货币资金 → eliminate=True（课程明确淘汰规则）。
    应收款高同时意味着产品大概率无定价权。数据不足返回 None。
    """
    ar = _add(fin.get("accounts_receivable"), fin.get("notes_receivable"))
    cash = _num(fin.get("monetary_funds"))
    if ar is None or cash is None:
        return None
    ratio = round(ar / cash, 4) if cash else None
    return {
        "receivables": ar,
        "cash": cash,
        "ratio": ratio,
        "eliminate": ar > cash,
    }


# ──────────────────────────────────────────────────────────────────────────────
#  费用控制 / 商业模式
# ──────────────────────────────────────────────────────────────────────────────

def expense_to_gross_profit(fin: dict) -> Optional[dict]:
    """费用/毛利比 + 三档评级（课程给出的最精确阈值）。

    费用 = 销售 + 管理 + 研发 + 财务费用；毛利 = 营业收入 − 营业成本。
    毛利优先取 gross_profit，缺失时由 revenue/operating_cost 推算。
    评级：<0.30 strong（强）/ 0.30–0.70 medium（中）/ >0.70 weak（弱，警示）。
    毛利 <= 0 或费用缺失返回 None。
    """
    expense = _sum(
        fin.get("sell_expense"), fin.get("admin_expense"),
        fin.get("rd_expense"), fin.get("fin_expense"),
    )
    gp = _num(fin.get("gross_profit"))
    if gp is None:
        rev = _num(fin.get("revenue"))
        cost = _num(fin.get("operating_cost"))
        if rev and cost is not None:
            gp = rev - cost
    if gp is None or gp <= 0 or expense is None:
        return None
    ratio = round(expense / gp, 4)
    grade = "strong" if ratio < 0.30 else ("medium" if ratio <= 0.70 else "weak")
    return {"expense": expense, "gross_profit": gp, "ratio": ratio, "grade": grade}


def gross_margin_class(fin: dict) -> Optional[dict]:
    """毛利率商业模式分类。

    >60% 定价权型（技术/文化溢价，安全垫厚）/ 30–60% medium / <30% 运营效率型
    （对成本波动敏感，依赖管理效率，新手谨慎）。gross_margin 为百分数（与实体一致）。
    """
    gm = _num(fin.get("gross_margin"))
    if gm is None:
        rev = _num(fin.get("revenue"))
        cost = _num(fin.get("operating_cost"))
        if rev and cost is not None and rev != 0:
            gm = (rev - cost) / rev * 100
    if gm is None:
        return None
    label = "pricing_power" if gm > 60 else ("medium" if gm >= 30 else "efficiency")
    return {"gross_margin": round(gm, 4), "label": label}


# ──────────────────────────────────────────────────────────────────────────────
#  结构分析
# ──────────────────────────────────────────────────────────────────────────────

def dupont_decomposition(fin: dict) -> Optional[dict]:
    """杜邦三因子分解：ROE = 净利率 × 总资产周转率 × 权益乘数。

    揭示 ROE 来源：高利润(产品议价) / 高周转(运营效率) / 高杠杆(财务)。
    同 ROE 下，靠产品议价的公司经营质量优于靠杠杆的公司。
    返回 {net_margin, asset_turnover, equity_multiplier, roe, driver}；
    因子均为小数比率（非百分数）；所需字段缺失或分母为 0 返回 None。

    driver 标签（启发式阈值）：净利率>15% → profit；周转>1.0 → efficiency；
    权益乘数>3.0 → leverage；多命中以 / 拼接；均不命中 → low。
    """
    net = _num(fin.get("net_profit"))
    rev = _num(fin.get("revenue"))
    assets = _num(fin.get("total_assets"))
    equity = _num(fin.get("equity"))
    if not (net and rev and assets and equity):
        return None
    if rev == 0 or assets == 0 or equity == 0:
        return None
    nm = net / rev                 # 净利率
    at = rev / assets              # 总资产周转率
    em = assets / equity           # 权益乘数
    roe = nm * at * em
    drivers = []
    if nm > 0.15:
        drivers.append("profit")
    if at > 1.0:
        drivers.append("efficiency")
    if em > 3.0:
        drivers.append("leverage")
    return {
        "net_margin": round(nm, 4),
        "asset_turnover": round(at, 4),
        "equity_multiplier": round(em, 4),
        "roe": round(roe, 4),
        "driver": "/".join(drivers) if drivers else "low",
    }


def liability_split(fin: dict) -> Optional[dict]:
    """负债拆分：经营性负债 vs 有息负债。

    经营性 = 应付账款 + 合同负债 + 预收账款（产品畅销信号，"不是真负债"）。
    有息 = 短期借款 + 长期借款 + 应付债券 + 一年内到期非流动负债（造血差才靠债务融资）。
    返回各项金额 + 占总负债比；总负债缺失时占比为 None。
    注：本口径比 derived_metrics.interest_bearing_debt（仅短+长借）更完整（含债券+一年内到期）。
    """
    operating = _sum(
        fin.get("accounts_payable"), fin.get("contract_liability"),
        fin.get("advance_receipts"),
    )
    interest = _sum(
        fin.get("short_loan"), fin.get("long_loan"),
        fin.get("bonds_payable"), fin.get("non_current_liab_due_within_1y"),
    )
    total = _num(fin.get("total_liabilities"))

    def _ratio(part: Optional[float]) -> Optional[float]:
        if part is not None and total and total != 0:
            return round(part / total, 4)
        return None

    return {
        "operating_liability": operating,
        "interest_bearing_liability": interest,
        "operating_ratio": _ratio(operating),
        "interest_bearing_ratio": _ratio(interest),
        "total_liabilities": total,
    }


def asset_heaviness(fin: dict) -> Optional[dict]:
    """重/轻资产分类 = (固定资产 + 在建工程) / 总资产。

    label：>0.40 heavy（重资产，工厂型）/ 0.20–0.40 medium / <0.20 light（轻资产）。
    阈值为启发式。在建工程缺失退化为仅固定资产。
    """
    fa = _add(fin.get("fixed_assets"), fin.get("construction_in_progress"))
    assets = _num(fin.get("total_assets"))
    if fa is None or assets is None or assets == 0:
        return None
    ratio = round(fa / assets, 4)
    label = "heavy" if ratio > 0.40 else ("medium" if ratio >= 0.20 else "light")
    return {"fixed_like_assets": fa, "total_assets": assets, "ratio": ratio, "label": label}


def inventory_to_revenue(fin: dict) -> Optional[float]:
    """存货/营收比(倍) = 存货 / 营业收入。时序走高 = 产销失衡/积压风险（趋势由调用方算）。"""
    inv = _num(fin.get("inventory"))
    rev = _num(fin.get("revenue"))
    if inv is None or not rev:
        return None
    return round(inv / rev, 4)


def goodwill_ratio(fin: dict) -> Optional[dict]:
    """商誉占比预警：商誉/总资产、商誉/权益。

    任一 > 0.20 → alert=True（收购溢价高，减值/利益输送风险）。
    商誉为 None（无商誉）返回 {goodwill:None, alert:False}；总资产/权益缺失对应占比为 None。
    """
    gw = _num(fin.get("goodwill"))
    assets = _num(fin.get("total_assets"))
    equity = _num(fin.get("equity"))
    out = {"goodwill": gw, "to_assets": None, "to_equity": None, "alert": False}
    if gw is None or gw == 0:
        return out
    if assets and assets != 0:
        out["to_assets"] = round(gw / assets, 4)
    if equity and equity != 0:
        out["to_equity"] = round(gw / equity, 4)
    out["alert"] = any(v is not None and v > 0.20 for v in (out["to_assets"], out["to_equity"]))
    return out


def payout_ratio(net_profit: float, dividend_total: float) -> Optional[dict]:
    """分红比例(派息率) = 年度分红总额 / 净利润（课程 21/26 集）。

    阈值：≤30% normal（正常）/ 30–70% generous（慷慨高分红）/ >70% high；
    **>100% draining=True（掏空家底式分红，业绩下滑时不可持续红旗）**。
    net_profit<=0（亏损）或 dividend_total<=0（不分红）返回 None。

    注：net_profit 取自 fin['net_profit']，dividend_total 来自 stock_dividend 年度合计；
    本函数为纯算子，分红数据的取数由调用方负责（未接入 compute_quality_report，留作 API 扩展）。
    """
    net = _num(net_profit)
    div = _num(dividend_total)
    if net is None or net <= 0 or div is None or div <= 0:
        return None
    ratio = round(div / net, 4)
    grade = "normal" if ratio <= 0.30 else ("generous" if ratio <= 0.70 else "high")
    return {
        "dividend_total": div,
        "net_profit": net,
        "ratio": ratio,
        "grade": grade,
        "draining": ratio > 1.0,
    }


def cash_flow_stage(fin: dict, revenue_growth: Optional[float] = None) -> Optional[dict]:
    """投资/筹资现金流阶段四象限。

    投资 CF(icf)：<0 扩张 / >0 收缩。
    筹资 CF(**fcf 列**，即筹资活动现金流净额)：<0 还债/分红 / >0 借钱。
    组合 stage：
      self_funded_expansion      自我造血扩张（icf<0 & 筹资<0，最理想）
      borrowing_to_expand        借钱扩张（icf<0 & 筹资>0，关注增长是否支撑）
      contracting_and_repaying   收缩还债（icf>0 & 筹资<0）
      borrowing_but_contracting  收缩仍借钱（icf>0 & 筹资>0，风险）
      expanding/contracting      筹资 CF 缺失时的退化标签
    revenue_growth(可选小数) 透传，供调用方结合增长解读。icf 缺失返回 None。
    """
    icf = _num(fin.get("icf"))
    fin_cf = _num(fin.get("fcf"))  # ⚠️ fcf 列 = 筹资活动现金流净额
    if icf is None:
        return None
    expanding = icf < 0
    out = {
        "investing_cf": icf,
        "financing_cf": fin_cf,
        "revenue_growth": _num(revenue_growth),
        "expanding": expanding,
        "borrowing": None,
        "stage": None,
    }
    if fin_cf is not None:
        out["borrowing"] = fin_cf > 0
    if out["borrowing"] is True and expanding:
        out["stage"] = "borrowing_to_expand"
    elif out["borrowing"] is False and expanding:
        out["stage"] = "self_funded_expansion"
    elif out["borrowing"] is True and not expanding:
        out["stage"] = "borrowing_but_contracting"
    elif out["borrowing"] is False and not expanding:
        out["stage"] = "contracting_and_repaying"
    else:
        out["stage"] = "expanding" if expanding else "contracting"
    return out


# ──────────────────────────────────────────────────────────────────────────────
#  聚合诊断
# ──────────────────────────────────────────────────────────────────────────────

# 评分组件权重（操作化设计，课程未给确切权重；已加权平均到可用组件）
_COMPONENT_WEIGHTS = {
    "cash_safety": 0.25,      # 现金覆盖短期债务
    "earnings_quality": 0.20, # 净现比
    "expense_control": 0.20,  # 费用/毛利比档位
    "gross_margin": 0.15,     # 毛利率档位
    "roe": 0.20,              # 杜邦 ROE
}

# 淘汰红线阈值
_CASH_COVERAGE_KILL = 1.0
_SCORE_KILL = 30.0
_SCORE_REVIEW = 60.0


def _component_scores(fin: dict) -> dict:
    """计算各评分组件的 0–100 归一分（仅含可算组件）。"""
    scores: dict[str, Optional[float]] = {}

    cov = cash_coverage_short_debt(fin)
    scores["cash_safety"] = _norm(cov, 0.5, 2.0) if cov is not None else None

    oni = ocf_net_income_ratio(fin)
    scores["earnings_quality"] = _norm(oni, 0.0, 1.2) if oni is not None else None

    eg = expense_to_gross_profit(fin)
    if eg is not None:
        scores["expense_control"] = {"strong": 100.0, "medium": 60.0, "weak": 20.0}[eg["grade"]]
    else:
        scores["expense_control"] = None

    gm = gross_margin_class(fin)
    if gm is not None:
        scores["gross_margin"] = {"pricing_power": 100.0, "medium": 60.0, "efficiency": 30.0}[gm["label"]]
    else:
        scores["gross_margin"] = None

    dp = dupont_decomposition(fin)
    if dp is not None:
        scores["roe"] = _norm(dp["roe"], 0.0, 0.20)
    else:
        scores["roe"] = None

    return scores


def compute_quality_report(fin: dict) -> dict:
    """一次性产出财务质量诊断报告。

    返回：
      metrics: 各单项指标（见上文函数）
      components: 各评分组件 0–100 归一分 + 权重
      quality_score: 0–100 透明加权综合分（仅按可算组件权重重一化）
      red_flags: 淘汰红线列表（cash_coverage<1 / ar>cash / 亏损 / 商誉高危）
      verdict: pass(≥60 且无红线) / review(30–60 或有非否决性红旗) / eliminate(红线触发 或 <30)
    """
    metrics = {
        "cash_to_revenue": cash_to_revenue(fin),
        "ocf_net_income_ratio": ocf_net_income_ratio(fin),
        "cash_coverage_short_debt": cash_coverage_short_debt(fin),
        "ar_vs_cash": ar_vs_cash_flag(fin),
        "expense_to_gross_profit": expense_to_gross_profit(fin),
        "gross_margin_class": gross_margin_class(fin),
        "dupont": dupont_decomposition(fin),
        "liability_split": liability_split(fin),
        "asset_heaviness": asset_heaviness(fin),
        "inventory_to_revenue": inventory_to_revenue(fin),
        "goodwill_ratio": goodwill_ratio(fin),
        "cash_flow_stage": cash_flow_stage(fin),
    }

    # ── 淘汰红线 ──
    red_flags: list[str] = []
    cov = metrics["cash_coverage_short_debt"]
    if cov is not None and cov < _CASH_COVERAGE_KILL:
        red_flags.append("cash_coverage_below_1")
    arf = metrics["ar_vs_cash"]
    if arf is not None and arf.get("eliminate"):
        red_flags.append("receivables_exceed_cash")
    if _num(fin.get("net_profit")) is not None and fin.get("net_profit") <= 0:
        red_flags.append("net_loss")
    gw = metrics["goodwill_ratio"]
    if gw is not None and gw.get("alert"):
        red_flags.append("goodwill_high")

    # ── 综合评分 ──
    comp = _component_scores(fin)
    weight_sum = 0.0
    weighted = 0.0
    components_out = {}
    for k, w in _COMPONENT_WEIGHTS.items():
        s = comp[k]
        components_out[k] = {"score": s, "weight": w}
        if s is not None:
            weight_sum += w
            weighted += s * w
    quality_score = round(weighted / weight_sum, 2) if weight_sum > 0 else None

    # ── 判定 ──
    hard_kill = bool(red_flags) and any(
        f in {"cash_coverage_below_1", "receivables_exceed_cash", "net_loss"}
        for f in red_flags
    )
    if hard_kill or (quality_score is not None and quality_score < _SCORE_KILL):
        verdict = "eliminate"
    elif quality_score is not None and quality_score >= _SCORE_REVIEW and not red_flags:
        verdict = "pass"
    else:
        verdict = "review"

    return {
        "metrics": metrics,
        "components": components_out,
        "quality_score": quality_score,
        "red_flags": red_flags,
        "verdict": verdict,
    }
