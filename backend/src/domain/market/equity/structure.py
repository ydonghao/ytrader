"""股票投资课程簇 6——股权 / IPO 结构（docs 03/06/16）纯函数。

回答"这家公司的股权稳不稳、是不是被炒作的妖股、对股东回报够不够"。
工商企业质量模块（quality.py）不覆盖股权结构层面，本模块实现课程 5 项：

    6.1 股本稀释追踪      增发/配股/转股/回购事件流 → 累计稀释率
    6.2 股权结构稳定性    第一大≥25% 或 前三大≥45%；员工持股平台减持预警
    6.3 妖股操纵风险评分  小市值 + 低流通比 + 大涨幅 + 小业绩 → 多因子评分
    6.4 AH 溢价           (A 价 − H 价×汇率) / (H 价×汇率)
    6.5 融资分红比        累计分红 / 累计融资；>1 为优质（茅台案例）

数据可得性
-----------
- 6.1 股本变动事件、6.2 十大股东、6.5 IPO 募资：需 akshare 股本变动/
  十大股东/IPO 数据同步（管道另建）；本模块以事件/比例列表为入参。
- 6.3 妖股评分、6.4 AH 溢价：纯计算，参数由行情/基本面供给。

全部纯函数，无 DB/IO 依赖。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── 6.1 股本稀释追踪 ────────────────────────────────────────────────────────

# 事件类型：issuance 增发 / rights 配股 / conversion 转股(债转股/期权) /
# buyback 回购（减少股本）。shares_delta：增发/配股/转股为正，回购为负。
DILUTIVE_EVENTS = ("issuance", "rights", "conversion", "buyback")


@dataclass
class ShareDilution:
    initial_shares: float
    final_shares: float
    net_new_shares: float            # 增发+配股+转股 − 回购
    dilution_ratio: Optional[float]  # net_new / initial（>0 = 被稀释）
    stake_retention: Optional[float]  # 原股东持股比例 final = initial/final


def share_dilution_track(
    initial_shares: float,
    events: list[dict],
) -> Optional[ShareDilution]:
    """累计股本稀释率（doc 06）。

    Args:
        initial_shares: 期初总股本。
        events: ``[{"type": "issuance"|"rights"|"conversion"|"buyback",
                  "shares_delta": float}]``，正数增股、负数减股。

    Returns:
        ShareDilution；initial<=0 或事件非法返回 None。
    dilution_ratio = net_new_shares / initial_shares（>0 表示原股东被稀释）。
    """
    if initial_shares is None or initial_shares <= 0:
        return None
    net_new = 0.0
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        delta = ev.get("shares_delta")
        if delta is None:
            continue
        try:
            net_new += float(delta)
        except (TypeError, ValueError):
            continue
    final = initial_shares + net_new
    if final <= 0:
        return None
    return ShareDilution(
        initial_shares=initial_shares,
        final_shares=final,
        net_new_shares=net_new,
        dilution_ratio=net_new / initial_shares,
        stake_retention=initial_shares / final,
    )


# ── 6.2 股权结构稳定性 ──────────────────────────────────────────────────────

@dataclass
class OwnershipStability:
    largest_pct: Optional[float]     # 第一大股东持股
    top3_pct: Optional[float]        # 前三大合计
    stable: bool                     # 第一大≥25% 或 前三大≥45%
    notes: list[str] = field(default_factory=list)


def ownership_stability(
    top_shareholders: list[float],
    *,
    largest_threshold: float = 0.25,
    top3_threshold: float = 0.45,
    esop_reducing: bool = False,
) -> Optional[OwnershipStability]:
    """股权结构稳定性判断（doc 06）。

    Args:
        top_shareholders: 按持股降序排列的前 N 大股东比例（小数）。
        largest_threshold: 第一大股东"稳定"门槛，默认 25%。
        top3_threshold:    前三大"稳定"门槛，默认 45%。
        esop_reducing:     员工持股平台是否在减持（额外预警）。

    Returns:
        OwnershipStability；空列表返回 None。
    """
    if not top_shareholders:
        return None
    largest = top_shareholders[0]
    top3 = sum(top_shareholders[:3])
    stable = largest >= largest_threshold or top3 >= top3_threshold
    notes: list[str] = []
    if esop_reducing:
        notes.append("员工持股平台减持，关注后续松动")
    if not stable:
        notes.append("股权分散，无实控人/第一大持股偏低，治理风险偏高")
    return OwnershipStability(
        largest_pct=largest,
        top3_pct=top3,
        stable=stable,
        notes=notes,
    )


# ── 6.3 妖股操纵风险评分 ────────────────────────────────────────────────────

@dataclass
class ManipulationRisk:
    score: int                 # 0~100，越高越像妖股
    verdict: str               # clean / watch / suspicious
    triggered: list[str]


def manipulation_risk_score(
    market_cap_yi: Optional[float],      # 总市值（亿元）
    float_ratio: Optional[float],        # 流通股占总股本比例（0~1）
    price_change_pct: Optional[float],   # 区间涨幅（小数）
    net_profit_yi: Optional[float],      # 净利润（亿元）
) -> ManipulationRisk:
    """妖股操纵风险多因子评分（doc 16）。

    课程画像：小市值（<30 亿）+ 低流通比 + 短期大涨 + 业绩差 → 易被操纵。
    每命中一项加 25 分（满分 100）：

        市值 < 30 亿           +25
        流通比 < 50%           +25
        区间涨幅 ≥ 50%         +25
        净利润 < 1 亿          +25

    Args:
        market_cap_yi:    总市值（亿元）。
        float_ratio:      流通股本占比（小数）。
        price_change_pct: 区间涨幅（小数，如 0.6 = 60%）。
        net_profit_yi:    净利润（亿元）。

    Returns:
        ManipulationRisk（score/verdict/triggered）。输入为 None 的因子不计分。
        score≥75 suspicious / 50~75 watch / <50 clean。
    """
    score = 0
    triggered: list[str] = []
    if market_cap_yi is not None and market_cap_yi < 30:
        score += 25
        triggered.append(f"小市值 {market_cap_yi:.1f} 亿")
    if float_ratio is not None and float_ratio < 0.50:
        score += 25
        triggered.append(f"低流通比 {float_ratio:.1%}")
    if price_change_pct is not None and price_change_pct >= 0.50:
        score += 25
        triggered.append(f"区间大涨 {price_change_pct:.1%}")
    if net_profit_yi is not None and net_profit_yi < 1:
        score += 25
        triggered.append(f"业绩小 净利 {net_profit_yi:.2f} 亿")

    if score >= 75:
        verdict = "suspicious"
    elif score >= 50:
        verdict = "watch"
    else:
        verdict = "clean"
    return ManipulationRisk(score=score, verdict=verdict, triggered=triggered)


# ── 6.4 AH 溢价 ─────────────────────────────────────────────────────────────

@dataclass
class AhPremium:
    a_price: float
    h_price_cny: float        # H 股价折人民币
    premium: float            # (A − H_cny) / H_cny；>0 = A 股溢价
    premium_pct: float


def ah_premium(
    a_price: Optional[float],
    h_price_hkd: Optional[float],
    hkd_cny_fx: Optional[float] = 1.0,
) -> Optional[AhPremium]:
    """AH 股溢价率（doc 16）。

    Args:
        a_price:      A 股价（人民币）。
        h_price_hkd:  H 股价（港币）。
        hkd_cny_fx:   港币兑人民币汇率（默认 1.0，按同币种处理）。

    Returns:
        AhPremium；价格/汇率非法返回 None。
    """
    if (a_price is None or h_price_hkd is None or hkd_cny_fx is None
            or a_price <= 0 or h_price_hkd <= 0 or hkd_cny_fx <= 0):
        return None
    h_cny = h_price_hkd * hkd_cny_fx
    premium = (a_price - h_cny) / h_cny
    return AhPremium(
        a_price=a_price,
        h_price_cny=h_cny,
        premium=premium,
        premium_pct=premium * 100,
    )


# ── 6.5 融资分红比 ──────────────────────────────────────────────────────────

@dataclass
class FinancingDividendRatio:
    cumulative_dividend: float
    cumulative_financing: float
    ratio: float              # 累计分红 / 累计融资
    verdict: str              # generous(>1) / normal(0.3~1) / stingy(<0.3)


def financing_dividend_ratio(
    cumulative_dividend: Optional[float],
    cumulative_financing: Optional[float],
) -> Optional[FinancingDividendRatio]:
    """累计分红 / 累计融资（IPO 后）（doc 03）。

    课程逻辑：融资分红比 > 1 = 公司从市场拿的钱少于回报给股东的钱，优质
    （茅台累计分红 3000 亿 vs 累计融资 23 亿）；< 0.3 偏吝啬/圈钱嫌疑。

    Args:
        cumulative_dividend:  IPO 以来累计现金分红（元）。
        cumulative_financing: IPO 以来累计股权融资（IPO+增发+配股，元）。

    Returns:
        FinancingDividendRatio；融资<=0 返回 None。
    """
    if cumulative_dividend is None or cumulative_financing is None:
        return None
    if cumulative_financing <= 0:
        return None
    ratio = cumulative_dividend / cumulative_financing
    if ratio > 1.0:
        verdict = "generous"
    elif ratio >= 0.3:
        verdict = "normal"
    else:
        verdict = "stingy"
    return FinancingDividendRatio(
        cumulative_dividend=cumulative_dividend,
        cumulative_financing=cumulative_financing,
        ratio=ratio,
        verdict=verdict,
    )
