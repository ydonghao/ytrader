"""股票投资课程簇 3——组合与仓位（docs 22/23/24/26）纯函数。

回答"买什么、配多少、何时买、何时卖"。本模块是课程视角的组合层建议，
与 portfolio/ 下既有永久组合（equity/bond/gold/cash 四类）NAV 计算互补：
这里聚焦"权益内部的红利/蓝筹/成长配比、组合基本面聚合、估值驱动的总仓位、
FIRE 覆盖率、买卖一致性监控"。

全部为纯函数，无 DB/IO 依赖，便于单测。

口径约定
--------
- 权重 ``w`` 统一为 0~1（市值占比）；
- 增速/派息率/收益率统一为小数（0.10 = 10%）；
- 3.5 分批建仓规划器由 ``strategy/position_sizing.plan_laddering`` 实现
  （基于安全边际的越跌越买），本模块不重复。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ── 3.1 组合层基本面聚合（虚拟集团公司）──────────────────────────────────────

@dataclass
class HoldingFundamental:
    """单只持仓的基本面输入。"""

    symbol: str
    weight: float                 # 该标的在组合中的市值权重 (0~1)
    revenue: Optional[float] = None       # 营业收入
    net_profit: Optional[float] = None    # 净利润
    equity: Optional[float] = None        # 净资产(股东权益)
    dividend: Optional[float] = None      # 年度现金分红(总额)
    revenue_growth: Optional[float] = None  # 营收增速(小数)


@dataclass
class PortfolioAggregate:
    """组合层（虚拟集团公司）聚合基本面。"""

    revenue: Optional[float] = None
    net_profit: Optional[float] = None
    equity: Optional[float] = None
    dividend: Optional[float] = None
    revenue_growth: Optional[float] = None  # 加权营收增速
    roe: Optional[float] = None             # = net_profit / equity
    payout_ratio: Optional[float] = None    # = dividend / net_profit
    dividend_yield_proxy: Optional[float] = None  # = dividend / equity (净资产口径股息)


def portfolio_aggregate_fundamentals(
    holdings: list[HoldingFundamental],
) -> PortfolioAggregate:
    """把组合视为"虚拟集团公司"，按持仓市值权重聚合各公司基本面。

    课程 doc 22 思路：组合 = 一个由你持股比例构成的虚拟公司，其营收/净利/
    净资产/分红 = 各成份股指标的市值加权和。由此可算出"组合层 ROE"、
    "组合层派息率"，判断整体组合质量而非单只股票。

    聚合口径：``Σ(weight_i × metric_i)``（等价于按市值占比加权）。
    ROE 由聚合后的 net_profit / equity 反推，而非各成份 ROE 的加权平均——
    这样大权重低 ROE 成份会被真实体现。

    缺失某指标的成份股对该项贡献为 0（不参与）；某项全组合无数据则返回 None。
    """
    if not holdings:
        return PortfolioAggregate()

    def _weighted(getter) -> Optional[float]:
        total = 0.0
        has = False
        for h in holdings:
            v = getter(h)
            if v is not None and math.isfinite(v):
                total += h.weight * v
                has = True
        return total if has else None

    rev = _weighted(lambda h: h.revenue)
    np = _weighted(lambda h: h.net_profit)
    eq = _weighted(lambda h: h.equity)
    div = _weighted(lambda h: h.dividend)
    growth = _weighted(lambda h: h.revenue_growth)

    roe = (np / eq) if (np is not None and eq and eq != 0) else None
    payout = (div / np) if (div is not None and np and np > 0) else None
    div_yield = (div / eq) if (div is not None and eq and eq > 0) else None

    return PortfolioAggregate(
        revenue=rev,
        net_profit=np,
        equity=eq,
        dividend=div,
        revenue_growth=growth,
        roe=roe,
        payout_ratio=payout,
        dividend_yield_proxy=div_yield,
    )


# ── 3.2 成长 × 股东回报四象限 ────────────────────────────────────────────────

# 默认分界：成长 10%（呼应 expected_return 模块的隐含增速门槛 >10%），
# 派息 30%（簇 1 派息率"正常/慷慨"分界）。
GROWTH_DIVIDEND_DEFAULTS = {"growth_threshold": 0.10, "payout_threshold": 0.30}

# 象限编号约定（横轴成长，纵轴派息）：
#   高成长+高派息 = "现金奶牛成长"（最理想）
#   低成长+高派息 = "成熟红利"（可持有，赚股息）
#   高成长+低派息 = "成长再投入"（需 ROE 高才合理）
#   低成长+低派息 = "价值陷阱"（Q3，课程建议回避）
QUADRANT_STAR = "star"
QUADRANT_CASH_COW = "cash_cow"
QUADRANT_REINVEST = "reinvest"
QUADRANT_VALUE_TRAP = "value_trap"


def growth_dividend_quadrant(
    revenue_growth: Optional[float],
    payout_ratio: Optional[float],
    *,
    growth_threshold: float = 0.10,
    payout_threshold: float = 0.30,
) -> Optional[dict]:
    """成长（横轴）× 派息（纵轴）四象限分类（doc 23）。

    Args:
        revenue_growth:  营收增速（小数，可空）。
        payout_ratio:    派息率（小数，可空）。
        growth_threshold: 成长分界，默认 10%。
        payout_threshold: 派息分界，默认 30%。

    Returns:
        {quadrant, label, growth_high, payout_high, avoid}；任一输入缺失返回 None。
        ``avoid=True`` 即 Q3 价值陷阱，课程建议回避。
    """
    if revenue_growth is None or payout_ratio is None:
        return None
    gh = revenue_growth >= growth_threshold
    ph = payout_ratio >= payout_threshold

    if gh and ph:
        q, label = QUADRANT_CASH_COW, "现金奶牛成长"
    elif (not gh) and ph:
        q, label = QUADRANT_STAR, "成熟红利"
    elif gh and (not ph):
        q, label = QUADRANT_REINVEST, "成长再投入(看ROE)"
    else:
        q, label = QUADRANT_VALUE_TRAP, "价值陷阱"
    return {
        "quadrant": q,
        "label": label,
        "growth_high": gh,
        "payout_high": ph,
        "avoid": q == QUADRANT_VALUE_TRAP,
    }


# ── 3.3 风险偏好三档/四档配比 ────────────────────────────────────────────────

# 红利 : 蓝筹 : 成长 的目标权重（doc 23）。
# 防御型 7:3:0 / 稳健 5:4:1 / 积极 3:5:2 / 激进 0:3:7。
RISK_PROFILES = {
    "defensive":  {"dividend": 0.7, "bluechip": 0.3, "growth": 0.0},
    "balanced":   {"dividend": 0.5, "bluechip": 0.4, "growth": 0.1},
    "aggressive": {"dividend": 0.3, "bluechip": 0.5, "growth": 0.2},
    "radical":    {"dividend": 0.0, "bluechip": 0.3, "growth": 0.7},
}


def risk_profile_weights(profile: str) -> Optional[dict]:
    """按风险偏好返回 红利/蓝筹/成长 目标权重（doc 23）。

    profile 取值：``defensive`` / ``balanced`` / ``aggressive`` / ``radical``。
    未知 profile 返回 None。权重之和恒为 1.0。
    """
    return RISK_PROFILES.get(profile)


# ── 3.4 沪深 300 PE 驱动总仓位 ───────────────────────────────────────────────

@dataclass
class IndexPePositionBand:
    """指数 PE 估值带 → 建议总仓位。"""

    z_score: Optional[float]
    band: str          # oversold / low_fair / high_fair / overvalued
    target_position: float  # 0~1
    mean: float
    std: float


def index_pe_position_band(
    pe_series: list[float],
    current_pe: float,
    *,
    std_floor: float = 1e-9,
) -> Optional[IndexPePositionBand]:
    """沪深 300（或任一宽基）PE 时序均值±1σ → 总仓位建议（doc 22/24/25）。

    课程规则：PE < μ−σ 满仓 / ≈μ 约 70% / > μ+σ 降到 <50%。
    本函数量化为 4 档（与 valuation_band 四态对齐）：

        z = (current - mean) / std
        z <= -1   → oversold    满仓 1.00
        -1 < z<=0 → low_fair    偏低 0.80
        0 < z < 1 → high_fair   偏高 0.60
        z >= 1    → overvalued  虚高 0.40

    Args:
        pe_series:  历史 PE_TTM 序列（建议 5~8 年）。
        current_pe: 当前 PE。
        std_floor:  σ 兜底，避免除零。

    Returns:
        IndexPePositionBand；序列为空或 current 非法返回 None。
    """
    if not pe_series or current_pe is None or current_pe <= 0:
        return None
    vals = [p for p in pe_series if p is not None and p > 0]
    n = len(vals)
    if n < 2:
        return None
    mean = sum(vals) / n
    var = sum((p - mean) ** 2 for p in vals) / (n - 1)
    std = math.sqrt(var) if var > 0 else std_floor
    std = max(std, std_floor)
    z = (current_pe - mean) / std

    if z <= -1.0:
        band, pos = "oversold", 1.00
    elif z <= 0.0:
        band, pos = "low_fair", 0.80
    elif z < 1.0:
        band, pos = "high_fair", 0.60
    else:
        band, pos = "overvalued", 0.40

    return IndexPePositionBand(
        z_score=z, band=band, target_position=pos, mean=mean, std=std
    )


# ── 3.6 FIRE 覆盖率 ──────────────────────────────────────────────────────────

@dataclass
class FireCoverage:
    """FIRE（财务自由）股息覆盖率。"""

    coverage_ratio: float       # annual_dividend / annual_expense
    achieved: bool              # >= 1.0
    months_covered: Optional[float]  # 覆盖的月数（股息按年计 / 月支出）


def fire_coverage(
    annual_dividend_income: float,
    annual_living_expense: float,
) -> Optional[FireCoverage]:
    """组合年分红 / 年生活开支（doc 22）。>=1.0 视为 FIRE 达成。

    Args:
        annual_dividend_income: 组合年度现金分红总额。
        annual_living_expense:  年度生活开支。

    Returns:
        FireCoverage；支出<=0 返回 None。
    """
    if annual_living_expense is None or annual_living_expense <= 0:
        return None
    ratio = (annual_dividend_income or 0.0) / annual_living_expense
    months = (annual_dividend_income or 0.0) / (annual_living_expense / 12.0)
    return FireCoverage(
        coverage_ratio=ratio,
        achieved=ratio >= 1.0,
        months_covered=months,
    )


# ── 3.7 买卖一致性——入场论点监控（卖出触发）──────────────────────────────────

@dataclass
class ThesisCondition:
    """单条量化入场论点（用于论点破即卖）。"""

    metric: str          # 指标名（与 current_metrics 字典 key 对齐）
    operator: str        # ">=" / ">" / "<=" / "<" / "=="
    threshold: float
    label: str = ""


@dataclass
class ThesisMonitorResult:
    """论点监控结果。"""

    breached: list[ThesisCondition] = field(default_factory=list)
    held: list[ThesisCondition] = field(default_factory=list)
    recommend_sell: bool = False


def evaluate_thesis(
    conditions: list[ThesisCondition],
    current_metrics: dict,
) -> ThesisMonitorResult:
    """买卖一致性原则（doc 26）：入场时记录的量化论点，任一破即建议卖出。

    用法：买入时固化一组量化论点（如"营收增速维持>=10%"、"ROE>=15%"、
    "资产负债率<=60%"），之后定期用最新指标评估；论点一旦失守，
    说明当初买入的逻辑已不成立，按一致性原则应卖出。

    Args:
        conditions:      入场论点条件列表。
        current_metrics: 当前指标字典 {metric_name: value}。

    Returns:
        ThesisMonitorResult：``breached`` 为已破条件，``recommend_sell``
        当且仅当存在任一 breached。
    """
    _OPS = {
        ">=": lambda a, b: a >= b,
        ">": lambda a, b: a > b,
        "<=": lambda a, b: a <= b,
        "<": lambda a, b: a < b,
        "==": lambda a, b: a == b,
    }
    res = ThesisMonitorResult()
    for c in conditions:
        op = _OPS.get(c.operator)
        v = current_metrics.get(c.metric)
        if op is None or v is None:
            res.held.append(c)  # 无法评估视为暂未触发（保守不卖）
            continue
        try:
            ok = op(v, c.threshold)
        except TypeError:
            res.held.append(c)
            continue
        if ok:
            res.held.append(c)
        else:
            res.breached.append(c)
    res.recommend_sell = len(res.breached) > 0
    return res
