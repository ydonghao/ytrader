# backend/src/domain/market/industry_analysis/llm_analyst.py
"""行业 LLM 解读:手动触发,进程内当日缓存(boom llm_analyst 同款范式)。"""
import json
import re

from src.domain.market.intel.agents.base import (
    load_prompt_from_db_or, render_prompt,
)

DEFAULT_INDUSTRY_ANALYST_PROMPT = """你是A股行业分析师。基于以下行业数据写一段景气解读。

行业: {{ name }}(投资难易度: {{ tier_label }})
分析抓手: {{ approach }}
景气分: {{ score }}(盈利{{ score_profit }}/估值{{ score_valuation }}/动量{{ score_momentum }}/资金{{ score_flow }})
估值: PB={{ pb }}(历史分位{{ pb_pct }}%)
动量: 60日相对沪深300超额 {{ rs60 }}
资金: 近20日主力净流入 {{ flow20 }} 元
请输出 JSON(不要输出其他内容):
{"summary": "120字内行业景气判断", "drivers": ["驱动点1", "驱动点2"], "risks": ["风险点1", "风险点2"]}
"""


class LLMNotConfigured(RuntimeError):
    """LLM provider 未配置(router 层转 503,区别于调用失败的 502)。"""


def build_prompt(ctx: dict) -> str:
    return render_prompt(
        load_prompt_from_db_or("industry_analyst",
                               DEFAULT_INDUSTRY_ANALYST_PROMPT),
        **ctx,
    )


def parse_industry_json(text: str) -> dict:
    fallback = {"summary": "", "drivers": [], "risks": []}
    if not text:
        return fallback
    text = re.sub(r"```(?:json)?", "", text)
    lo, hi = text.find("{"), text.rfind("}")
    if lo < 0 or hi <= lo:
        return {**fallback, "summary": text[:300]}
    try:
        obj = json.loads(text[lo:hi + 1])
    except json.JSONDecodeError:
        return {**fallback, "summary": text[:300]}
    return {
        "summary": str(obj.get("summary", ""))[:500],
        "drivers": [str(x)[:80] for x in (obj.get("drivers") or [])][:5],
        "risks": [str(x)[:80] for x in (obj.get("risks") or [])][:5],
    }


_CACHE: dict[tuple[str, str], dict] = {}


def cache_get(code: str, d: str) -> dict | None:
    return _CACHE.get((code, d))


def cache_put(code: str, d: str, result: dict) -> None:
    if len(_CACHE) > 500:          # 进程内缓存护栏
        _CACHE.clear()
    _CACHE[(code, d)] = result


async def interpret(code: str, d: str) -> dict:
    """调用默认 LLM 生成行业解读;失败上抛,由 router 降级 503。"""
    cached = cache_get(code, d)
    if cached is not None:
        return cached
    from src.infra.database.llm.repository import create_llm_repository
    from src.infra.llm.manager import LLMManager

    # LLMManager 需要 config 仓储(llm_config_router 同款构造)
    manager = LLMManager(create_llm_repository())
    provider = manager.get_provider()
    if provider is None:
        raise LLMNotConfigured("LLM provider not configured")
    result = parse_industry_json(
        (await provider.complete(build_prompt(_build_ctx(code, d)),
                                 temperature=0.2, max_tokens=640)).content)
    cache_put(code, d, result)
    return result


def _build_ctx(code: str, d: str) -> dict:
    """从仓储/知识层拼 prompt 上下文(数值直接进文案)。"""
    import datetime as dt

    from src.domain.market.industry_analysis.knowledge import (
        TIER_LABELS, load_knowledge,
    )
    from src.infra.database.market.industry_analysis import (
        create_industry_analysis_repository,
    )
    repo = create_industry_analysis_repository()
    k = load_knowledge()[code]
    as_of = dt.date.fromisoformat(d)
    p = next((r for r in repo.get_prosperity(as_of)
              if r["sw_code"] == code), None)
    inputs = (p or {}).get("inputs") or {}
    return {"name": k.name, "tier_label": TIER_LABELS[k.tier],
            "approach": k.approach, "score": _fmt(p and p.get("score")),
            "score_profit": _fmt(p and p.get("score_profit")),
            "score_valuation": _fmt(p and p.get("score_valuation")),
            "score_momentum": _fmt(p and p.get("score_momentum")),
            "score_flow": _fmt(p and p.get("score_flow")),
            "pb": _fmt(inputs.get("pb")), "pb_pct": _fmt(inputs.get("pb_pct")),
            "rs60": _fmt(inputs.get("rs60")),
            "flow20": _fmt(inputs.get("flow20"))}


def _fmt(v) -> str:
    if v is None:
        return "缺"
    return f"{v:.4g}" if isinstance(v, float) else str(v)
