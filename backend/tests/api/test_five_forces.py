"""five-forces 端点测试（mock 子调用，模式抄 test_industry_peers.py）。"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

RATIOS_RESP = {"code": 0, "data": {"periods": [
    {"report_date": "2025-12-31",
     "ratios": {"payable_days": 140.0, "receivable_days": 30.0,
                "gross_margin": 91.0, "roe": 34.0},
     "values": {"revenue": 1.7e11, "rd_expense": 1.9e8}},
]}}
CASHFLOW_RESP = {"code": 0, "data": {"periods": [
    {"report_date": "2025-12-31", "ratios": {"cash_to_revenue": 1.1}},
]}}
INDUSTRY_RESP = {"code": 0, "data": {
    "industry": {"level": 2, "code": "801125", "name": "白酒Ⅱ",
                 "degraded": False},
    "sections": [{"report_date": "2025-12-31", "cr4": 0.77, "hhi": 2600.0,
                  "revenue_yoy": 0.08,
                  "distribution": {
                      "gross_margin": {"p25": 55.0, "median": 70.0,
                                       "p75": 78.0},
                      "roe": {"p25": 8.0, "median": 15.0, "p75": 22.0}}}],
    "peers": [],
    "target": {"revenue_share": 0.178, "percentile_roe": 1.0,
               "percentile_gross_margin": 1.0},
}}


def _resp(payload):
    class R:  # minimal response-like
        body = json.dumps(payload)
    return R()


def _call(industry=INDUSTRY_RESP, ratios=RATIOS_RESP, cashflow=CASHFLOW_RESP):
    from src.api.handler.financial_detail_handler import five_forces_report
    with patch(
        "src.api.handler.financial_detail_handler.ratios",
        return_value=_resp(ratios),
    ), patch(
        "src.api.handler.financial_detail_handler.cashflow_analysis",
        return_value=_resp(cashflow),
    ), patch(
        "src.api.handler.financial_detail_handler.industry_peers",
        return_value=_resp(industry),
    ):
        return json.loads(five_forces_report("sh600519").body)


def test_full_structure():
    body = _call()
    assert body["code"] == 0
    d = body["data"]
    assert [f["key"] for f in d["forces"]] == [
        "supplier", "buyer", "barrier", "substitute", "rivalry"]
    assert d["total_score"] is not None


def test_no_industry_degrades():
    body = _call(industry={"code": 0, "data": {
        "industry": None, "sections": [], "peers": [], "target": None}})
    assert body["code"] == 0
    assert body["data"]["note"]


def test_both_fail_returns_error():
    """ratios 无可用期 且 行业无归属 → 端点整体 error（code != 0）。"""
    body = _call(
        ratios={"code": 1, "message": "no data"},  # 错误包 → periods []
        cashflow={"code": 0, "data": {"periods": []}},
        industry={"code": 0, "data": {
            "industry": None, "sections": [], "peers": [], "target": None}},
    )
    assert body["code"] != 0


def test_route_registered_once():
    from src.api.router.financial_router import router
    paths = [r.path for r in router.routes]
    assert paths.count("/financial/five-forces/{symbol}") == 1
