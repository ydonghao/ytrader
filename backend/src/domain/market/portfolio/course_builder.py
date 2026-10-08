"""自动建组合(课程23/24)——选股分类 + 配额分配 + 建仓档位规划(纯函数)。

课程口径:
- 23讲: 风险偏好 → 红利/蓝筹/创新三类目标配比(RISK_PROFILES);成长×股东回报
        四象限;类内等权;预留 10% 现金。
- 24讲: PE 均值±1σ 判估值四状态;合理偏低/超跌即建底仓 30% + 层层狙击
        (越跌越买);合理偏高等待回调(锚定 μ/μ-0.5σ/μ-1σ/μ-1.5σ);虚高不建仓;
        金额按 100 股整手取整。

全部纯函数: 市场数据(估值快照/财务/年报营收/指数成分/PE序列/收盘价)由调用方注入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.domain.market.fundamental.valuation_band import valuation_band

# ── 常量 ──────────────────────────────────────────────────────────────
CATEGORY_DIVIDEND = "dividend"
CATEGORY_BLUECHIP = "bluechip"
CATEGORY_GROWTH = "growth"
CATEGORIES = (CATEGORY_DIVIDEND, CATEGORY_BLUECHIP, CATEGORY_GROWTH)

PAYOUT_THRESHOLD = 0.30       # 派息率门槛(小数, 课程23)
GROWTH_THRESHOLD = 0.10       # 年报营收增速门槛(小数, 课程23)
DIVIDEND_YIELD_MIN = 3.0      # 红利股股息率门槛(dv_ttm, %)
ROE_MIN = 10.0                # 蓝筹/创新 ROE 门槛(roe_weighted, %)

LADDER_BASE_RATIO = 0.30
LADDER_REST_RATIOS = (0.23, 0.23, 0.24)   # 与底仓合计 1.00
LOW_FAIR_DROPS = (0.05, 0.10, 0.15)       # 第2/3/4档相对现价回落
HIGH_FAIR_ANCHORS = (0.0, 0.5, 1.0, 1.5)  # 相对 μ 的 σ 下移(首档=μ, 进入合理偏低)

LOT_SIZE = 100
PE_MIN_MONTHLY_SAMPLES = 24

STATE_MAP = {
    "超跌": "oversold",
    "合理偏低": "low_fair",
    "合理偏高": "high_fair",
    "虚高": "overvalued",
}
STATE_INSUFFICIENT = "insufficient"


# ── 数据结构 ──────────────────────────────────────────────────────────
@dataclass
class CandidateRow:
    """分类前单标的输入快照(调用方从 stock_valuation/stock_financials/
    stock_financial_detail/index_constituent 组装)。"""

    symbol: str
    dv_ttm: Optional[float] = None       # 股息率(%)
    pe_ttm: Optional[float] = None
    total_mv: Optional[float] = None     # 总市值(元)
    roe_pct: Optional[float] = None      # 最新 roe_weighted(%)
    annual_revenues: list[float] = field(default_factory=list)  # 年报营收, 降序≤2条
    in_csi300: bool = False


@dataclass
class ClassifiedStock:
    """分类结果 + 类内排序键。"""

    symbol: str
    category: str
    revenue_growth: Optional[float]
    payout_ratio: Optional[float]
    dv_ttm: Optional[float]
    total_mv: Optional[float]
    rank_metric: float


@dataclass
class LadderRungPlan:
    """建仓档位(课程24 层层狙击)。"""

    rung_index: int
    drop_pct: float          # 相对生成日现价的回落(0=首档)
    price_level: float
    amount: float
    executed: bool = False
    executed_at: Optional[str] = None
    fill_price: Optional[float] = None
    fill_shares: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "rung_index": self.rung_index,
            "drop_pct": round(self.drop_pct, 4),
            "price_level": round(self.price_level, 3),
            "amount": round(self.amount, 2),
            "executed": self.executed,
            "executed_at": self.executed_at,
            "fill_price": self.fill_price,
            "fill_shares": self.fill_shares,
        }


@dataclass
class PlanLegDraft:
    """计划腿草稿。"""

    symbol: str
    name: str
    category: str
    target_weight: float
    target_amount: float
    pe_band: Optional[dict]
    entry_plan: list[dict]
    current_price: Optional[float] = None


@dataclass
class CoursePlanDraft:
    """组合计划草稿(不落库)。"""

    risk_profile: str
    total_capital: float
    investable_capital: float
    slots: dict[str, int]
    legs: list[PlanLegDraft]
    warnings: list[str]
    candidates: dict[str, list[dict]]   # 换股备选(未入选部分)


# ── 派生指标 ──────────────────────────────────────────────────────────
def derive_revenue_growth(annual_revenues: list[float]) -> Optional[float]:
    """年报营收同比 = 最新/上一年 − 1(小数)。不足两年或基数≤0 → None。"""
    if annual_revenues is None or len(annual_revenues) < 2:
        return None
    cur, prev = annual_revenues[0], annual_revenues[1]
    if cur is None or not prev or prev <= 0:
        return None
    return cur / prev - 1.0


def derive_payout_ratio(
    dv_ttm_pct: Optional[float], pe_ttm: Optional[float]
) -> Optional[float]:
    """派息率(小数) = 股息率 × PE(D/MV × MV/NP = D/NP)。任一缺失 → None。"""
    if dv_ttm_pct is None or pe_ttm is None or pe_ttm <= 0:
        return None
    return (dv_ttm_pct / 100.0) * pe_ttm


# ── 分类(课程23 四象限落地的三类口径) ─────────────────────────────────
def classify_stock(row: CandidateRow) -> Optional[str]:
    """返回类别(优先级 红利 > 创新 > 蓝筹), 不匹配 → None。

    - 红利: 派息率≥30% 且 增速<10% 且 股息率≥3%(成熟红利象限)
    - 创新: 增速≥10% 且 派息率<30% 且 ROE≥10%(成长再投入看ROE)
    - 蓝筹: 沪深300成分 且 ROE≥10%
    """
    growth = derive_revenue_growth(row.annual_revenues)
    payout = derive_payout_ratio(row.dv_ttm, row.pe_ttm)
    if (payout is not None and payout >= PAYOUT_THRESHOLD
            and growth is not None and growth < GROWTH_THRESHOLD
            and row.dv_ttm is not None and row.dv_ttm >= DIVIDEND_YIELD_MIN):
        return CATEGORY_DIVIDEND
    if (growth is not None and growth >= GROWTH_THRESHOLD
            and (payout is None or payout < PAYOUT_THRESHOLD)
            and row.roe_pct is not None and row.roe_pct >= ROE_MIN):
        return CATEGORY_GROWTH
    if row.in_csi300 and row.roe_pct is not None and row.roe_pct >= ROE_MIN:
        return CATEGORY_BLUECHIP
    return None


def classify_candidates(rows: list[CandidateRow]) -> list[ClassifiedStock]:
    """分类整个候选宇宙, 附带类内排序键;未匹配的丢弃。"""
    out: list[ClassifiedStock] = []
    for r in rows:
        cat = classify_stock(r)
        if cat is None:
            continue
        growth = derive_revenue_growth(r.annual_revenues)
        payout = derive_payout_ratio(r.dv_ttm, r.pe_ttm)
        if cat == CATEGORY_DIVIDEND:
            metric = r.dv_ttm or 0.0
        elif cat == CATEGORY_GROWTH:
            metric = growth or 0.0
        else:
            metric = r.total_mv or 0.0
        out.append(ClassifiedStock(
            symbol=r.symbol, category=cat, revenue_growth=growth,
            payout_ratio=payout, dv_ttm=r.dv_ttm, total_mv=r.total_mv,
            rank_metric=metric,
        ))
    return out


def pick_top_n(
    classified: list[ClassifiedStock], category: str, n: int
) -> list[ClassifiedStock]:
    """某类按 rank_metric 降序取前 n。"""
    pool = [c for c in classified if c.category == category]
    pool.sort(key=lambda c: c.rank_metric, reverse=True)
    return pool[: max(n, 0)]


def select_pools(
    classified: list[ClassifiedStock],
    slots: dict[str, int],
    multiplier: int = 3,
) -> dict[str, list[ClassifiedStock]]:
    """每类取 max(slots,1)×multiplier 只备选池(头部将入选)。"""
    pools: dict[str, list[ClassifiedStock]] = {}
    for cat in CATEGORIES:
        n = max(slots.get(cat, 0), 1) * multiplier
        pools[cat] = pick_top_n(classified, cat, n)
    return pools


# ── 配额分配 ──────────────────────────────────────────────────────────
def allocate_slots(stock_count: int, weights: dict[str, float]) -> dict[str, int]:
    """按类别配比把 stock_count 分成各类腿数。

    最大余数法;配比>0 的类别至少 1 腿;配比为 0 的类别不分配;
    min-1 导致超配时从最大腿回收。weights 须非零维度 ≥1。
    """
    active = {k: w for k, w in (weights or {}).items() if w and w > 0}
    if not active or stock_count <= 0:
        return {}
    total_w = sum(active.values())
    quotas = {k: w / total_w for k, w in active.items()}
    base = {k: max(1, int(quotas[k] * stock_count)) for k in active}
    remaining = stock_count - sum(base.values())
    order = sorted(
        active,
        key=lambda k: quotas[k] * stock_count - base.get(k, 0),
        reverse=True,
    )
    i = 0
    while remaining > 0:
        base[order[i % len(order)]] += 1
        remaining -= 1
        i += 1
    while remaining < 0:
        victim = max(base, key=lambda k: base[k])
        if base[victim] <= 1:
            break
        base[victim] -= 1
        remaining += 1
    # 零配比类别显式补 0(调用方 slots.get(cat, 0) 语义一致且对前端更直观)
    return {**{k: 0 for k in (weights or {}) if k not in base}, **base}


# ── 整手取整 ──────────────────────────────────────────────────────────
def round_to_lot_amount(
    amount: float, price: float, lot_size: int = LOT_SIZE
) -> float:
    """金额按价格折算整手(向下取整), 返回实际投入金额;不足一手 → 0。"""
    if price is None or price <= 0 or amount <= 0:
        return 0.0
    lots = int(amount / price // lot_size)
    return lots * lot_size * price


# ── 估值带(课程24 μ±1σ 四态) ─────────────────────────────────────────
def plan_pe_band(
    pe_series: list[float], current_pe: Optional[float]
) -> Optional[dict]:
    """个股 PE 带: μ±1σ 四状态 + 样本量。

    - 样本(月度降采样后) < 24 或 current_pe 缺失 → {state: insufficient};
    - state 映射为英文码: oversold/low_fair/high_fair/overvalued。
    """
    series = [p for p in (pe_series or []) if p and p > 0]
    if current_pe is None or current_pe <= 0 or len(series) < PE_MIN_MONTHLY_SAMPLES:
        return {"state": STATE_INSUFFICIENT, "sample_count": len(series)}
    band = valuation_band(series, current_pe)
    if band is None:
        return {"state": STATE_INSUFFICIENT, "sample_count": len(series),
                "current_pe": current_pe}
    return {
        "mean": band["mean"],
        "std": band["std"],
        "z_score": band["z_score"],
        "state": STATE_MAP.get(band["state"], STATE_INSUFFICIENT),
        "sample_count": len(series),
        "current_pe": current_pe,
    }


# ── 档位规划(课程24 层层狙击) ─────────────────────────────────────────
def plan_ladder(
    band: Optional[dict],
    current_price: float,
    target_amount: float,
    lot_size: int = LOT_SIZE,
) -> list[LadderRungPlan]:
    """按估值状态生成分批建仓档位。

    - low_fair/oversold: 首档30%@现价 + 3档@回落5%/10%/15%;
    - high_fair: 4档锚定 μ/μ-0.5σ/μ-1σ/μ-1.5σ 对应价格
      (盈利不变假设 P_target = P_now × PE_target / PE_now, 等待回调);
    - overvalued/insufficient/None: 不建仓(空档位)。
    金额整手取整, 不足一手丢档。
    """
    if not band or current_price is None or current_price <= 0 or target_amount <= 0:
        return []
    state = band.get("state")
    ratios = (LADDER_BASE_RATIO,) + LADDER_REST_RATIOS
    if state in ("low_fair", "oversold"):
        drops = [0.0] + list(LOW_FAIR_DROPS)
        levels = [current_price * (1 - d) for d in drops]
    elif state == "high_fair":
        mean, std, cur_pe = band.get("mean"), band.get("std"), band.get("current_pe")
        if not mean or std is None or not cur_pe:
            return []
        levels = [current_price * (mean - k * std) / cur_pe
                  for k in HIGH_FAIR_ANCHORS]
        drops = [1 - lv / current_price for lv in levels]
    else:
        return []

    rungs: list[LadderRungPlan] = []
    for i, (lv, r) in enumerate(zip(levels, ratios)):
        amt = round_to_lot_amount(target_amount * r, lv, lot_size)
        if amt <= 0:
            continue
        rungs.append(LadderRungPlan(
            rung_index=i, drop_pct=drops[i], price_level=lv, amount=amt,
        ))
    return rungs


# ── 装配 ──────────────────────────────────────────────────────────────
def assemble_plan(
    *,
    pools: dict[str, list[ClassifiedStock]],
    slots: dict[str, int],
    weights: dict[str, float],
    total_capital: float,
    cash_reserve_pct: float,
    names: dict[str, str],
    prices: dict[str, float],
    pe_series: dict[str, list[float]],
    current_pes: dict[str, Optional[float]],
) -> CoursePlanDraft:
    """由备选池装配组合计划草稿。

    - investable = total_capital × (1 − cash_reserve_pct);
    - 每类取池头部 slots[cat] 只, 类内等权(单腿金额 = 类别权重×investable÷腿数);
    - 候选不足/为空 → warnings 且该类权重留现金;
    - 无收盘价 → 生成观察腿(空档位)并警告。
    """
    investable = total_capital * (1 - cash_reserve_pct)
    warnings: list[str] = []
    legs: list[PlanLegDraft] = []
    candidates: dict[str, list[dict]] = {}

    for cat in CATEGORIES:
        n = slots.get(cat, 0)
        pool = pools.get(cat, [])
        if n == 0:
            candidates[cat] = []
            continue
        if not pool:
            warnings.append(f"类别 {cat} 候选池为空, 对应权重保留为现金")
            candidates[cat] = []
            continue
        if len(pool) < n:
            warnings.append(f"类别 {cat} 候选不足: 需 {n} 只, 仅 {len(pool)} 只")
        per_amount = investable * (weights.get(cat, 0.0)) / n
        for c in pool[:n]:
            price = prices.get(c.symbol)
            band = plan_pe_band(
                pe_series.get(c.symbol, []), current_pes.get(c.symbol)
            )
            rungs = plan_ladder(band, price, per_amount) if price else []
            if price is None:
                warnings.append(f"{c.symbol} 无收盘价, 仅生成观察腿")
            legs.append(PlanLegDraft(
                symbol=c.symbol,
                name=names.get(c.symbol, c.symbol),
                category=cat,
                target_weight=round(weights.get(cat, 0.0) / n, 4),
                target_amount=round(per_amount, 2),
                pe_band=band,
                entry_plan=[r.to_dict() for r in rungs],
                current_price=price,
            ))
        candidates[cat] = [
            {
                "symbol": c.symbol,
                "dv_ttm": c.dv_ttm,
                "total_mv": c.total_mv,
                "revenue_growth": c.revenue_growth,
                "payout_ratio": c.payout_ratio,
            }
            for c in pool[n:]
        ]

    return CoursePlanDraft(
        risk_profile="",
        total_capital=total_capital,
        investable_capital=investable,
        slots=slots,
        legs=legs,
        warnings=warnings,
        candidates=candidates,
    )
