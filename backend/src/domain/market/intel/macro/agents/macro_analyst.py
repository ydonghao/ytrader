"""MacroAnalystAgent — 宏观经济判断快照生成（双轨分层）。

按组合理论框架推理（美林时钟 / 货币主义 / 达里奥债务周期 / 金融周期 / 收益率曲线），
输出可证伪的多维度宏观判断 + 逐资产方向预测，落库 macro_view。

输入 state：
  - indicator_codes: 用于推理的宏观指标 code 列表
  - predict_targets: [{symbol, name, asset_class}] 需预测方向的标的
  - snapshot_date / horizon_days

输出：MacroViewResult（结构化），由调用方落库。
"""
from typing import Any

from src.domain.market.intel.agents.base import (
    agent_node,
    load_prompt_from_db_or,
    render_prompt,
)
from src.domain.market.intel.macro.schemas import MacroViewResult
from src.domain.market.intel.macro.context import (
    collect_macro_readings,
    collect_recent_news,
    collect_market_context,
    format_context_for_prompt,
)


# 系统提示词：约束 LLM 按组合理论框架推理 + 可证伪化 + 防幻觉。
# 通过 DB prompt 模板 'macro_analyst_system' 加载（seed 进 seed_agent_data），
# 允许用户在 Prompt 控制台编辑；此处为 fallback（须与 DB v2 两段式版本一致）。
_DEFAULT_SYSTEM_PROMPT = """你是一位严谨的宏观经济分析师，负责生成可证伪、可回测的宏观判断快照。

【方法论·组合理论框架】你必须基于以下经典理论框架推理，不可凭直觉：
1. 美林时钟（增长×通胀定位象限）：复苏→利股 / 过热→利商品 / 滞胀→利现金 / 衰退→利债。
2. 货币主义（Friedman）：M2 增速领先通胀 12-18 个月。
3. 达里奥债务周期：信贷扩张→繁荣→去杠杆，利率/社融是枢纽。
4. 金融周期（BIS）：信贷缺口 + 杠杆累积，判断金融脆弱性。
5. 收益率曲线倒挂：衰退先行指标。

【三条铁律】
1. 趋势比绝对值重要。
2. 拐点比水平重要。
3. 共振比单指标可靠。

【输出·分两段，缺一不可】
第一段·objective_reading（客观解读）：逐指标解释当前值含义、趋势方向、与历史/阈值对比、指标间关系。
  ⚠️ 这一段【禁止任何结论性判断】：不说'偏多/偏空'，不说'利好/利空'，不下任何方向结论。
  只陈述事实与含义，让读者自己形成判断。
第二段·立场：基于客观解读，给出 overall_stance(bullish/bearish/neutral) + confidence + macro_judgments(各维度方向) + asset_predictions(资产方向) + summary(立场理由)。
  立场理由须引用具体数据点 + 点明理论框架。

【上下文数据】
{{ context }}

请严格按两段式输出。"""


_DEFAULT_USER_PROMPT = """今天是 {{ snapshot_date }}。请基于上方上下文数据，生成未来 {{ horizon_days }} 个交易日（约1个季度）的宏观判断快照。

务必分两段：
1. objective_reading：先做客观解读，逐指标讲含义与关系，【不下任何结论】。
2. 立场：再给 overall_stance + confidence + macro_judgments + asset_predictions + summary。
用组合理论框架定位周期象限（regime_quadrant）。summary 是立场理由（非客观解读）。"""


@agent_node
async def macro_analyst_node(state: dict[str, Any]) -> dict[str, Any]:
    """生成宏观判断快照（结构化输出 MacroViewResult）。"""
    from src.infra.llm.langchain_adapter import create_chat_model_for_agent

    indicator_codes = state.get("indicator_codes") or []
    targets = state.get("predict_targets") or []
    snapshot_date = state.get("snapshot_date")
    horizon_days = state.get("horizon_days", 63)

    # ── 收集上下文 ──
    readings = collect_macro_readings(indicator_codes)
    news = collect_recent_news(hours=72, limit=25)
    market = collect_market_context(targets, days=30)
    context_text = format_context_for_prompt(readings, news, market, targets)

    # ── 渲染 prompt ──
    system_prompt = render_prompt(
        load_prompt_from_db_or("macro_analyst_system", _DEFAULT_SYSTEM_PROMPT),
        context=context_text,
    )
    user_msg = render_prompt(
        load_prompt_from_db_or("macro_analyst_user", _DEFAULT_USER_PROMPT),
        snapshot_date=str(snapshot_date),
        horizon_days=horizon_days,
    )

    # ── 调 LLM（结构化输出）──
    llm = create_chat_model_for_agent("macro_analyst")
    structured_llm = llm.with_structured_output(MacroViewResult, method="function_calling")
    result = await structured_llm.ainvoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ])

    if result is None:
        return {
            "errors": ["macro_analyst: LLM 无结构化输出（可能过载），请重试"],
            "processing_steps": ["macro_analyst: no structured output"],
        }

    return {
        "objective_reading": result.objective_reading,
        "macro_judgments": [j.model_dump() for j in result.macro_judgments],
        "regime_quadrant": result.regime_quadrant,
        "overall_stance": result.overall_stance,
        "confidence": result.confidence,
        "summary": result.summary,
        "asset_predictions": [p.model_dump() for p in result.asset_predictions],
        "signals": readings,  # 当时的关键指标读数快照
        "processing_steps": [
            f"macro_analyst: regime={result.regime_quadrant} stance={result.overall_stance} "
            f"conf={result.confidence} ({len(result.macro_judgments)} dims, "
            f"{len(result.asset_predictions)} assets)"
        ],
    }
