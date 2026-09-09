"""股票投资课程——成长 vs 价值风格分类（doc 17）纯函数。

簇 2 有估值、簇 1 有质量、第二批有 PEG，但缺一个**综合判定"这是成长股还是
价值股"**的分类器。课程 doc 17 把投资方法分为成长派（赚业绩增长的钱）与
价值派（赚估值修复的钱），两者的选股标准与持有逻辑完全不同。

    classify_growth_value    综合增速 + 估值 + ROE 判定风格 + 质量标签
    style_from_peg           由 PEG 进一步细化（GARP 合理价格成长）

输入增速/ROE 为小数。全部纯函数，可组合第二批 valuation_extras.peg_ratio。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:
    from src.domain.market.fundamental.valuation_extras import peg_ratio
except Exception:  # noqa: BLE001
    peg_ratio = None


STYLE_GROWTH = "growth"
STYLE_VALUE = "value"
STYLE_BALANCED = "balanced"   # GARP：合理价格的适度成长


@dataclass
class GrowthValueStyle:
    style: str               # growth / value / balanced
    quality: str             # quality / fair / weak / trap_risk
    peg: Optional[float]
    rationale: str


def classify_growth_value(
    earnings_growth: Optional[float],
    pe: Optional[float],
    roe: Optional[float] = None,
) -> Optional[GrowthValueStyle]:
    """综合增速 + 估值 + ROE 判定成长/价值风格（doc 17）。

    分类规则：
        增速 >= 15%         growth（成长型）
            └ ROE >= 15%    quality growth（高质量成长）
            └ 否则          low-quality growth（靠外延/杠杆的增长）
        增速 <= 5%          value（价值型）
            └ PE <= 15 且 ROE >= 10%   deep value（低估且可持续）
            └ 否则          trap_risk（低估值或因基本面恶化，价值陷阱）
        5% < 增速 < 15%     balanced（GARP，合理价格适度成长）

    Args:
        earnings_growth: 盈利增速（小数）。
        pe:              市盈率。
        roe:             ROE（小数，可选）。

    Returns:
        GrowthValueStyle；增速/PE 缺失返回 None。
    """
    if earnings_growth is None or pe is None:
        return None

    peg_val = None
    if peg_ratio is not None:
        pr = peg_ratio(pe, earnings_growth)
        if pr is not None:
            peg_val = pr.peg

    if earnings_growth >= 0.15:
        style = STYLE_GROWTH
        if roe is not None and roe >= 0.15:
            quality, rat = "quality", f"高质量成长：增速 {earnings_growth:.0%}、ROE {roe:.0%}"
        elif roe is not None and roe < 0.08:
            quality, rat = "weak", f"低质量成长：增速 {earnings_growth:.0%} 但 ROE 仅 {roe:.0%}（增长或靠杠杆/外延）"
        else:
            quality, rat = "fair", f"成长型：增速 {earnings_growth:.0%}、ROE {roe:.0%}" if roe else f"成长型：增速 {earnings_growth:.0%}"
    elif earnings_growth <= 0.05:
        style = STYLE_VALUE
        if pe <= 15 and (roe is None or roe >= 0.10):
            quality, rat = "quality", f"深度价值：PE {pe:.0f}、ROE {roe:.0%}" if roe else f"深度价值：PE {pe:.0f}"
        elif roe is not None and roe < 0.08:
            quality, rat = "trap_risk", f"价值陷阱风险：低增速 {earnings_growth:.0%}、ROE {roe:.0%} 偏低"
        else:
            quality, rat = "fair", f"价值型：PE {pe:.0f}、增速 {earnings_growth:.0%}"
    else:
        style = STYLE_BALANCED
        quality, rat = "fair", f"GARP 合理价格成长：增速 {earnings_growth:.0%}、PE {pe:.0f}"

    # PEG 进一步标注
    if peg_val is not None and peg_val < 1.0:
        rat += f"；PEG {peg_val:.2f}<1 估值偏低"
    elif peg_val is not None and peg_val > 2.0:
        rat += f"；PEG {peg_val:.2f}>2 估值偏高"

    return GrowthValueStyle(style=style, quality=quality, peg=peg_val, rationale=rat)
