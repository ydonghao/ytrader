"""Pydantic schemas for fundamental analyst LLM structured output.

个股基本面深度分析结构化报告，由 LLM 基于注入的真实三大报表 +
估值分位 + 衍生指标数据生成。所有字段必须基于上下文数据，缺失
时填 '无数据'，禁止臆测。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ProfitabilityQuality(BaseModel):
    """盈利质量：营收/利润趋势 + 毛净利率变化 + 现金流 vs 利润匹配。"""

    revenue_trend: str = Field(
        description=(
            "营收趋势: 'growth'(增长) / 'decline'(下滑) / "
            "'volatile'(波动) / 'stagnant'(停滞)"
        )
    )
    profit_trend: str = Field(
        description=(
            "净利润趋势: 'growth'(增长) / 'decline'(下滑) / "
            "'volatile'(波动) / 'loss'(亏损)"
        )
    )
    margin_change: str = Field(
        description=(
            "毛利率/净利率变化描述，须引用注入数据（如"
            "'毛利率从 45% 降至 40%'）。无数据填 '无数据'。"
        )
    )
    cashflow_profit_match: str = Field(
        description=(
            "经营现金流 vs 净利润匹配度（如"
            "'OCF/净利润持续 >1，盈利含金量高'）。"
        )
    )
    summary: str = Field(
        description="盈利质量一段话总结（80-200字）。"
    )


class FinancialHealth(BaseModel):
    """财务健康：负债率 + 有息负债 + 偿债能力。"""

    debt_level: str = Field(
        description="负债水平: 'high'(高) / 'medium'(中等) / 'low'(低)"
    )
    interest_bearing_debt: str = Field(
        description=(
            "有息负债（短期+长期借款）规模与变化描述，须引用数据。"
            "无数据填 '无数据'。"
        )
    )
    solvency: str = Field(
        description=(
            "偿债能力评估（货币资金对有息负债的覆盖等）。"
            "无数据填 '无数据'。"
        )
    )
    summary: str = Field(
        description="财务健康一段话总结（80-200字）。"
    )


class ValuationAssessment(BaseModel):
    """估值：当前 PE/PB 分位 + 便宜/昂贵判断。"""

    pe_percentile: str = Field(
        description=(
            "当前 PE_TTM 历史分位描述（如'5年分位 12%，处历史低位'）。"
            "无数据填 '无数据'。"
        )
    )
    pb_percentile: str = Field(
        description=(
            "当前 PB 历史分位描述。无数据填 '无数据'。"
        )
    )
    cheap_or_expensive: str = Field(
        description=(
            "估值判断: 'cheap'(便宜) / 'fair'(合理) / "
            "'expensive'(昂贵) / 'unknown'(无法判断)"
        )
    )
    summary: str = Field(description="估值一段话总结（80-200字）。")


class CapitalEfficiency(BaseModel):
    """资本回报效率：ROIC/ROE/ROA 趋势。"""

    roic_trend: str = Field(
        description=(
            "ROIC 趋势描述，须引用数据。无数据填 '无数据'。"
        )
    )
    roe_trend: str = Field(
        description=(
            "ROE 趋势描述，须引用数据。无数据填 '无数据'。"
        )
    )
    roa_trend: str = Field(
        description="ROA 趋势描述。无数据填 '无数据'。"
    )
    summary: str = Field(
        description="资本回报效率一段话总结（80-200字）。"
    )


class MoatAssessment(BaseModel):
    """护城河线索：基于财务特征推断（如持续高 ROIC + 稳定毛利率）。"""

    has_moat: bool = Field(
        description=(
            "是否具备护城河线索（持续高 ROIC + 稳定/上行毛利率为强信号）。"
        )
    )
    evidence: list[str] = Field(
        description=(
            "支撑判断的财务特征列表（如'近 8 期 ROIC>15%'、"
            "'毛利率稳定在 50%+'）。无依据时为空列表。"
        )
    )
    summary: str = Field(
        description="护城河一段话总结（80-200字）。"
    )


class RiskItem(BaseModel):
    """单个风险点。"""

    category: str = Field(
        description=(
            "风险类别: 'leverage'(负债上升) / 'cashflow'(现金流恶化) "
            "/ 'goodwill'(商誉占比高) / 'profitability'(盈利下滑) "
            "/ 'valuation'(估值过高) / 'other'"
        )
    )
    description: str = Field(description="风险描述，须引用数据。")
    severity: str = Field(
        description="'high' / 'medium' / 'low'"
    )


class FundamentalReport(BaseModel):
    """个股基本面深度分析报告（LLM 结构化输出）。"""

    profitability: ProfitabilityQuality
    financial_health: FinancialHealth
    valuation: ValuationAssessment
    capital_efficiency: CapitalEfficiency
    moat: MoatAssessment
    risks: list[RiskItem] = Field(
        default_factory=list, description="风险点列表，可为空。"
    )
    overall_score: int = Field(
        ge=0,
        le=100,
        description="综合基本面评分 0-100（越高越好）。",
    )
    one_line_conclusion: str = Field(
        description=(
            "一句话结论（20-60字），须基于数据，"
            "不下股价方向判断。"
        )
    )
