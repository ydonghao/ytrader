# backend/tests/domain/boom/test_llm_analyst.py
"""LLM 景气分析师:prompt 组装 + JSON 容错解析。"""
import pytest

from src.domain.market.boom import llm_analyst
from src.domain.market.boom.llm_analyst import build_prompt, parse_boom_json


def test_build_prompt_contains_facts(monkeypatch):
    # 无 DB prompt 模板时用内置默认,测试不依赖 DB
    monkeypatch.setattr(
        llm_analyst, "load_prompt_from_db_or",
        lambda name, fallback: fallback,
    )
    prompt = build_prompt(
        {"symbol": "600519", "company_name": "贵州茅台",
         "change_pct": 60.0, "forecast_type_label": "预增"},
        [{"keyword": "供不应求", "category_label": "供给紧张",
          "source_type": "业绩预告", "snippet": "产品供不应求"}],
    )
    assert "600519" in prompt and "60.0" in prompt and "供不应求" in prompt


def test_parse_plain_json():
    out = parse_boom_json('{"boom_score": 82, "verdict": "focus", '
                          '"summary": "量价齐升", "risks": ["估值高"]}')
    assert out["boom_score"] == 82
    assert out["verdict"] == "focus"


def test_parse_fenced_json():
    text = '好的,分析如下:\n```json\n{"boom_score": 65, "verdict": "watch", "summary": "s", "risks": []}\n```'
    out = parse_boom_json(text)
    assert out["boom_score"] == 65


def test_parse_garbage_fallback():
    out = parse_boom_json("模型抽风了,没有 JSON")
    assert out["verdict"] == "parse_error"
    assert out["boom_score"] is None


def test_parse_clamps_score():
    out = parse_boom_json('{"boom_score": 150, "verdict": "focus", "summary": "", "risks": []}')
    assert out["boom_score"] == 100


def test_parse_validates_verdict():
    out = parse_boom_json('{"boom_score": 50, "verdict": "强烈买入", "summary": "", "risks": []}')
    assert out["verdict"] == "watch"          # 非法枚举 → watch
