# backend/tests/domain/market/industry_analysis/test_llm_analyst.py
from src.domain.market.industry_analysis.llm_analyst import (
    build_prompt, parse_industry_json,
)

CTX = {"name": "银行", "tier_label": "易分析",
       "approach": "看净息差/不良率", "score": 72.5, "score_profit": 80.0,
       "score_valuation": 65.0, "score_momentum": 50.0, "score_flow": 70.0,
       "pb": 0.6, "pb_pct": 12.0, "rs60": 0.05, "flow20": 2.4e9}


def test_build_prompt_contains_facts():
    p = build_prompt(CTX)
    assert "银行" in p and "72.5" in p and "净息差" in p


def test_parse_ok():
    r = parse_industry_json(
        '```json\n{"summary": "ok", "drivers": ["a", "b"], '
        '"risks": ["c"]}\n```')
    assert r["summary"] == "ok" and r["drivers"] == ["a", "b"]


def test_parse_fallback():
    r = parse_industry_json("不是json")
    assert r["summary"].startswith("不是json")
    assert r["drivers"] == [] and r["risks"] == []
