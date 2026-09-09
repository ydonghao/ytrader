"""Pydantic schemas for macro analyst LLM structured output.

双轨分层结构（与 macro_view 表对齐）：
  第一层·宏观经济状态判断（MacroJudgment × N 维度）
  第二层·资产方向含义（AssetPrediction × N 标的）
"""
from pydantic import BaseModel, Field


# ── 第一层·宏观经济状态判断 ──────────────────────────────────


class MacroJudgment(BaseModel):
    """单个宏观经济维度的判断（可证伪命题）。"""

    dimension: str = Field(
        description=(
            "宏观维度: 'growth'(增长) / 'inflation'(通胀) / 'liquidity'(流动性) / "
            "'leverage'(杠杆/金融稳定) / 'regime'(周期象限) / 'recession_risk'(衰退风险)"
        )
    )
    stance: str = Field(
        description=(
            "该维度未来1个季度的方向判断: 'up'(上升/扩张/收紧-对利率) / "
            "'down'(下降/收缩/宽松-对利率) / 'flat'(持平)"
        )
    )
    confidence: float = Field(
        ge=0.0, le=10.0,
        description="本维度判断置信度 0-10（数据共振/拐点明确则高分）",
    )
    rationale: str = Field(
        description=(
            "判断理由，必须引用具体数据点（如'PMI连续3月回升至50.4'），"
            "不可空泛。需点明依据的理论框架（美林时钟/货币主义/债务周期/金融周期/收益率曲线）。"
        ),
    )


class MacroViewResult(BaseModel):
    """宏观分析师 agent 的完整结构化输出。"""

    objective_reading: str = Field(
        description=(
            "客观解读（第一段，不下结论）：逐指标解释当前值含义、趋势方向、"
            "与历史/阈值对比、指标间关系。禁止结论性判断（不说偏多/偏空、不说利好/利空）。"
        ),
    )
    macro_judgments: list[MacroJudgment] = Field(
        description=(
            "宏观经济状态判断（至少覆盖 growth/inflation/liquidity 三维度，"
            "建议含 regime/recession_risk）。每维度一个可证伪命题。"
        )
    )
    regime_quadrant: str = Field(
        description=(
            "美林时钟当前象限: 'recovery'(复苏) / 'expansion'(扩张) / "
            "'overheating'(过热) / 'stagflation'(滞胀) / 'recession'(衰退)"
        ),
    )
    overall_stance: str = Field(
        description="综合宏观立场的风险偏好: 'bullish'(偏多) / 'bearish'(偏空) / 'neutral'(中性)",
    )
    confidence: float = Field(
        ge=0.0, le=10.0,
        description="整体置信度 0-10",
    )
    summary: str = Field(
        description=(
            "宏观叙事（200-500字）：当前经济处于什么周期位置、核心驱动、"
            "关键风险。须基于输入数据，不编造。"
        ),
    )

    # ── 第二层·资产方向含义 ───────────────────────────────────
    asset_predictions: list["AssetPrediction"] = Field(
        description=(
            "由第一层推断的大类资产方向预测（逐标的）。"
            "输入会给定标的清单（symbol/name/asset_class），需逐个给方向+理由。"
        ),
    )


class AssetPrediction(BaseModel):
    """单个标的的方向预测（可证伪命题）。"""

    symbol: str = Field(description="标的符号（与输入清单一致，如 sh000300 / US.INX / USDCNY / XAU）")
    name: str = Field(default="", description="标的名称（沪深300 / 标普500 / 美元 / 黄金）")
    predicted: str = Field(
        description="未来1季度方向预测: 'up'(上涨/走强) / 'down'(下跌/走弱) / 'flat'(震荡)",
    )
    rationale: str = Field(
        description=(
            "方向预测理由，须关联第一层宏观判断（如'复苏象限+流动性宽松利股→沪深300偏多'）。"
        ),
    )
    asset_class: str = Field(default="index", description="index / fx / commodity")


# 解决前向引用（MacroViewResult.asset_predictions 引用 AssetPrediction）
MacroViewResult.model_rebuild()
