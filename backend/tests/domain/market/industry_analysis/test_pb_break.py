# backend/tests/domain/market/industry_analysis/test_pb_break.py
from src.domain.market.industry_analysis.pb_break import aggregate_pb_break

ROWS = [
    ("sh600001", 0.8, "801780"),   # 破净
    ("sh600002", 1.2, "801780"),
    ("sz000001", 0.9, "801120"),   # 破净
    ("sz000002", None, "801120"),  # 缺pb:计总数不计破净
    ("sh600003", 5.0, None),       # 无行业归属:只进market
]


def test_market_scope():
    out = aggregate_pb_break(ROWS)
    m = out["market"]
    assert m.total_count == 5
    assert m.break_count == 2
    assert abs(m.break_rate - 0.4) < 1e-9
    assert m.median_pb == 1.05     # [0.8,0.9,1.2,5.0] 中位 =(0.9+1.2)/2


def test_industry_scope_excludes_unmapped():
    out = aggregate_pb_break(ROWS)
    bank = out["industries"]["801780"]
    assert bank.total_count == 2 and bank.break_count == 1
    assert "801120" in out["industries"]
    food = out["industries"]["801120"]
    assert food.total_count == 2 and food.break_count == 1
    # 缺pb行的中位:只剩 [0.9]
    assert food.median_pb == 0.9


def test_empty():
    out = aggregate_pb_break([])
    assert out["market"].total_count == 0
    assert out["industries"] == {}
