# backend/tests/domain/market/industry_analysis/test_flow_map.py
"""东财行业→申万映射加载。"""
from src.domain.market.industry_analysis.flow_map import load_flow_map
from src.domain.market.industry_analysis.knowledge import SW_L1_CODES


def test_load_and_values_are_sw_codes():
    m = load_flow_map()
    assert len(m) >= 40
    assert all(v in SW_L1_CODES for v in m.values())


def test_known_entries():
    m = load_flow_map()
    assert m.get("银行") == "801780"
    assert m.get("半导体") == "801080"
    assert m.get("环保") == "801970"
