# backend/src/domain/market/boom/llm_analyst.py
"""LLM 景气深读:规则命中后的第二道筛(仅候选池,token 可控)。"""
import json
import re
from typing import Any

from src.domain.market.intel.agents.base import (
    load_prompt_from_db_or, render_prompt,
)

VALID_VERDICTS = ("focus", "watch", "exclude")

DEFAULT_BOOM_ANALYST_PROMPT = """你是A股基本面分析师。以下股票在业绩预告/快报中出现大幅预增,且公告/新闻文本命中了景气关键词。请判断其景气信号的成色。

股票: {{ symbol }} {{ company_name }}
预告: {{ forecast_type_label }},变动幅度 {{ change_pct }}%
命中关键词(附摘录):
{% for h in hits %}- [{{ h.category_label }}] {{ h.keyword }}({{ h.source_type }}): {{ h.snippet }}
{% endfor %}
请输出 JSON(不要输出其他内容):
{"boom_score": 0-100整数, "verdict": "focus|watch|exclude", "summary": "80字内景气判断", "risks": ["风险点1", "风险点2"]}
判定标准:多条独立来源互相印证、涉及量价(供给紧张+价格上行)→ focus;单条且语境一般 → watch;否定语境/蹭概念/周期见顶 → exclude。"""


def build_prompt(candidate: dict, hits: list[dict]) -> str:
    return render_prompt(
        load_prompt_from_db_or("boom_analyst", DEFAULT_BOOM_ANALYST_PROMPT),
        symbol=candidate.get("symbol", ""),
        company_name=candidate.get("company_name") or "",
        forecast_type_label=candidate.get("forecast_type_label") or "预增",
        change_pct=candidate.get("change_pct") or 0,
        hits=hits or [],
    )


def parse_boom_json(text: str) -> dict:
    fallback = {"boom_score": None, "verdict": "parse_error",
                "summary": "", "risks": []}
    if not text:
        return fallback
    text = re.sub(r"```(?:json)?", "", text)
    lo, hi = text.find("{"), text.rfind("}")
    if lo < 0 or hi <= lo:
        return {**fallback, "summary": text[:200]}
    try:
        obj = json.loads(text[lo:hi + 1])
    except json.JSONDecodeError:
        return {**fallback, "summary": text[:200]}
    score = obj.get("boom_score")
    score = max(0, min(100, int(score))) if isinstance(score, (int, float)) else None
    verdict = obj.get("verdict")
    verdict = verdict if verdict in VALID_VERDICTS else "watch"
    return {
        "boom_score": score,
        "verdict": verdict,
        "summary": str(obj.get("summary", ""))[:300],
        "risks": [str(r)[:60] for r in (obj.get("risks") or [])][:5],
    }


async def analyze_candidate(candidate: dict, hits: list[dict]) -> dict:
    """调用默认 LLM 分析单个候选;失败上抛,由调用方降级。"""
    from src.infra.llm.manager import LLMManager

    manager = LLMManager()
    provider = manager.get_provider()
    if provider is None:
        raise RuntimeError("LLM provider not configured")
    prompt = build_prompt(candidate, hits)
    result = await provider.complete(prompt, temperature=0.2, max_tokens=512)
    return parse_boom_json(result.content)
