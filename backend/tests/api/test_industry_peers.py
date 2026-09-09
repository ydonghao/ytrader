"""行业截面端点测试（mock repo，模式抄 test_ratios.py）。"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

MEMBER = {
    "symbol": "sh600519", "code": "600519", "name": "贵州茅台",
    "sw_code_l1": "801080", "sw_name_l1": "食品饮料",
    "sw_code_l2": "801120", "sw_name_l2": "白酒Ⅱ",
    "weight": 12.3, "included_date": "2021-12-13",
}

SECTIONS = [
    {"sw_code": "801120", "report_date": "2025-12-31", "level": 2,
     "sw_name": "白酒Ⅱ", "sample_count": 112, "revenue_sum": 9.5e12,
     "net_profit_sum": 3.2e12, "cr4": 0.52, "cr8": 0.71, "hhi": 980.2,
     "revenue_yoy": 0.08,
     "distribution": {"gross_margin": {"mean": 60.0, "median": 70.0,
                                       "std": 15.0, "p25": 55.0, "p75": 78.0}}},
    {"sw_code": "801120", "report_date": "2024-12-31", "level": 2,
     "sw_name": "白酒Ⅱ", "sample_count": 110, "revenue_sum": 8.8e12,
     "net_profit_sum": 3.0e12, "cr4": 0.50, "cr8": 0.70, "hhi": 950.0,
     "revenue_yoy": None, "distribution": None},
]

PEERS = [
    {"symbol": "sh600519", "name": "贵州茅台", "revenue": 1.7e11,
     "net_profit": 8.5e10, "gross_margin": 91.6, "net_margin": 50.0,
     "roe": 34.0},
    {"symbol": "sz000858", "name": "五粮液", "revenue": 9.0e10,
     "net_profit": 3.2e10, "gross_margin": 75.0, "net_margin": 35.0,
     "roe": 22.0},
]


def _repo(**kw):
    r = MagicMock()
    r.get_member.return_value = kw.get("member", MEMBER)
    if "sections_side_effect" in kw:
        # 二级/一级两次 fetch_sections 各返回不同列表（降级场景）
        r.fetch_sections.side_effect = kw["sections_side_effect"]
    else:
        r.fetch_sections.return_value = kw.get("sections", SECTIONS)
    r.fetch_peer_details.return_value = kw.get("peers", PEERS)
    return r


def _call_members(repo):
    from src.api.handler.financial_detail_handler import industry_members
    with patch(
        "src.infra.database.market.sw_industry"
        ".create_sw_industry_repository",
        return_value=repo,
    ):
        return json.loads(industry_members("sh600519").body)


def _call_peers(repo, level=2, limit=13):
    from src.api.handler.financial_detail_handler import industry_peers
    with patch(
        "src.infra.database.market.sw_industry"
        ".create_sw_industry_repository",
        return_value=repo,
    ):
        return json.loads(industry_peers("sh600519", level, limit).body)


def test_industry_members_ok():
    body = _call_members(_repo())
    assert body["code"] == 0
    d = body["data"]
    assert d["sw_l2"] == {"code": "801120", "name": "白酒Ⅱ"}
    assert d["sw_l1"]["code"] == "801080"


def test_industry_members_no_attribution_error():
    body = _call_members(_repo(member=None))
    assert body["code"] != 0


def test_industry_peers_full_shape():
    body = _call_peers(_repo())
    assert body["code"] == 0
    d = body["data"]
    assert d["industry"]["level"] == 2
    assert d["industry"]["code"] == "801120"
    assert d["industry"]["degraded"] is False
    assert [s["report_date"] for s in d["sections"]] == [
        "2025-12-31", "2024-12-31",
    ]
    assert d["peers"][0]["rank_revenue"] == 1
    assert d["target"]["percentile_gross_margin"] == 1.0


def test_industry_peers_empty_sections_error():
    body = _call_peers(_repo(sections=[]))
    assert body["code"] != 0


def test_industry_peers_degrades_to_level1():
    """全窗口二级样本均 <8 → 降一级，degraded=true。"""
    thin = [
        dict(SECTIONS[0], sample_count=5),
        dict(SECTIONS[1], sample_count=4),
    ]
    repo = _repo(sections=thin)
    body = _call_peers(repo)
    assert body["code"] == 0
    d = body["data"]
    assert d["industry"]["degraded"] is True
    assert d["industry"]["level"] == 1
    assert d["industry"]["code"] == "801080"
    assert "降" in d["industry"]["note"]
    # 降级后用一级 code + level=1 重新取截面与明细
    assert repo.fetch_sections.call_count == 2


def test_industry_peers_skips_thin_latest_period():
    """披露季中段：最新期样本过少 → 用最新充足期取明细，不降级。"""
    sections = [
        dict(SECTIONS[0], report_date="2026-06-30", sample_count=2),
        dict(SECTIONS[1], report_date="2025-12-31", sample_count=112),
    ]
    repo = _repo(sections=sections)
    body = _call_peers(repo)
    assert body["code"] == 0
    d = body["data"]
    assert d["industry"]["degraded"] is False
    assert d["industry"]["level"] == 2
    # 同行明细取最新充足期（2025-12-31），且只查了一次截面
    repo.fetch_peer_details.assert_called_once_with("801120", 2, "2025-12-31")
    assert "2025-12-31" in d["industry"]["note"]
    assert repo.fetch_sections.call_count == 1


def test_degrade_pick_skips_thin_l1_periods():
    """降级到一级后，一级最新期也样本过少 → 明细改用一级最新充足期。

    复现银行股线上问题：L1 2026-06-30 sample_count=1（披露季中段），
    旧行为无条件取 sections[0] 得 1 家"同行截面"；新行为沿用 ≥8
    充足期规则跳到 2025-12-31（sample_count=90）。
    """
    thin_l2 = [
        {"report_date": "2026-06-30", "sample_count": 2, "sw_code": "801125",
         "level": 2, "sw_name": "白酒Ⅱ"},
    ]
    l1_sections = [
        {"report_date": "2026-06-30", "sample_count": 1, "sw_code": "801080",
         "level": 1, "sw_name": "食品饮料"},
        {"report_date": "2025-12-31", "sample_count": 90, "sw_code": "801080",
         "level": 1, "sw_name": "食品饮料"},
    ]
    repo = _repo(sections_side_effect=[thin_l2, l1_sections])
    body = _call_peers(repo)
    assert body["code"] == 0
    d = body["data"]
    assert d["industry"]["level"] == 1
    assert d["industry"]["degraded"] is True
    repo.fetch_peer_details.assert_called_once_with("801080", 1, "2025-12-31")
    note = d["industry"]["note"]
    assert "降为一级行业" in note
    assert "2025-12-31" in note


def test_industry_peers_target_absent_note():
    """目标股有归属但最新期无财务 → target None + note。"""
    peers = [p for p in PEERS if p["symbol"] != "sh600519"]
    body = _call_peers(_repo(peers=peers))
    assert body["code"] == 0
    assert body["data"]["target"] is None
    assert "note" in body["data"]


def test_routes_registered_once():
    """路径存在且各注册一次——router 遮蔽教训（b661566）。"""
    from src.api.router.financial_router import router
    paths = [r.path for r in router.routes]
    assert paths.count("/financial/industry-members/{symbol}") == 1
    assert paths.count("/financial/industry-peers/{symbol}") == 1
