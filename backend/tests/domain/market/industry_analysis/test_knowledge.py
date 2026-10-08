# backend/tests/domain/market/industry_analysis/test_knowledge.py
"""知识层 yaml 加载与校验。"""
from pathlib import Path

import pytest

from src.domain.market.industry_analysis.knowledge import (
    SW_L1_CODES, TIER_LABELS, IndustryKnowledge, load_knowledge,
)

CONF = Path(__file__).parent.parent.parent.parent.parent / "conf" / "industry_knowledge.yaml"


def test_load_all_31():
    know = load_knowledge(CONF)
    assert set(know.keys()) == set(SW_L1_CODES)
    food = know["801120"]
    assert isinstance(food, IndustryKnowledge)
    assert food.name == "食品饮料"
    assert food.tier in (1, 2, 3)
    assert food.retail_suitable in ("high", "medium", "low")
    assert food.approach and food.upstream and food.downstream


def test_default_path_loads():
    know = load_knowledge()          # 不传路径 → conf/industry_knowledge.yaml
    assert len(know) == 31


def test_missing_code_raises(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text('"801120":\n  name: 食品饮料\n  tier: 1\n'
                 '  retail_suitable: high\n  approach: x\n'
                 '  upstream: [a]\n  downstream: [b]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="缺少申万一级行业"):
        load_knowledge(p)


def test_bad_enum_raises(tmp_path):
    p = tmp_path / "k.yaml"
    body = "".join(
        f'"{c}":\n  name: n{c}\n  tier: 1\n  retail_suitable: high\n'
        f"  approach: x\n  upstream: [a]\n  downstream: [b]\n"
        for c in SW_L1_CODES
    )
    p.write_text(body.replace("tier: 1", "tier: 9", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="tier"):
        load_knowledge(p)


def test_tier_labels():
    assert TIER_LABELS[1] == "易分析"
