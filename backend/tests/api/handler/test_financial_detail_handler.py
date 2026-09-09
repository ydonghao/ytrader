"""financial_detail_handler 的 period 参数 + valuation_history 测试。

用真实本地 DB（conftest 的 db_dsn fixture 间接通过 repo 单例）。
若 sh600519 数据缺失，标记 skip。
"""
import json

import pytest

from src.api.handler.financial_detail_handler import (
    detail_series,
    valuation_history,
)


def _body(resp):
    """从 JSONResponse 取 data dict。"""
    return json.loads(resp.body)["data"]


@pytest.fixture(scope="module")
def has_income_data():
    """探测 sh600519 是否有利润表数据。"""
    data = _body(detail_series("sh600519", "income", limit=50,
                               period="month"))
    return bool(data and data.get("series"))


def test_detail_series_period_year_filters_december(has_income_data):
    """period=year 只返回 12 月年报期。"""
    if not has_income_data:
        pytest.skip("sh600519 无利润表数据")
    data = _body(detail_series("sh600519", "income", limit=50,
                               period="year"))
    series = data["series"]
    assert len(series) > 0
    for item in series:
        # report_date 形如 '2023-12-31'
        assert item["report_date"][5:7] == "12"


def test_detail_series_period_quarter_changes_values(has_income_data):
    """period=quarter 的营收应与 period=month 不同（做了单季差分）。"""
    if not has_income_data:
        pytest.skip("sh600519 无利润表数据")
    month_data = _body(detail_series("sh600519", "income", limit=50,
                                     period="month"))
    qtr_data = _body(detail_series("sh600519", "income", limit=50,
                                   period="quarter"))
    # 至少有一期的 revenue 不同（单季 ≠ 累计）
    month_rev = {r["report_date"]: r["revenue"]
                 for r in month_data["series"]}
    diffs = [
        r for r in qtr_data["series"]
        if r["revenue"] is not None
        and month_rev.get(r["report_date"]) is not None
        and abs((r["revenue"] or 0) - (month_rev[r["report_date"]]
               or 0)) > 0.01
    ]
    assert len(diffs) > 0, "quarter 与 month 的 revenue 应有差异"


def test_detail_series_invalid_period_defaults_quarter(has_income_data):
    """非法 period 值降级为 quarter（不报错）。"""
    if not has_income_data:
        pytest.skip("sh600519 无利润表数据")
    data = _body(detail_series("sh600519", "income", limit=10,
                               period="garbage"))
    assert "series" in data


def test_valuation_history_returns_points():
    """valuation_history 返回每个 report_date 对应的估值点。"""
    # 先拿利润表报告期作为输入
    income = _body(detail_series("sh600519", "income", limit=5,
                                 period="year"))
    dates = [r["report_date"] for r in income["series"]
             if r["report_date"]]
    if not dates:
        pytest.skip("sh600519 无年报数据")
    resp = valuation_history("sh600519", dates)
    data = _body(resp)
    assert data["symbol"] == "sh600519"
    assert isinstance(data["points"], list)
    assert len(data["points"]) == len(dates)
    # 每个点结构正确
    for p in data["points"]:
        assert "report_date" in p
        assert "trade_date" in p
        assert "pe" in p
        assert "pb" in p


def test_valuation_history_empty_dates_returns_empty():
    data = _body(valuation_history("sh600519", []))
    assert data["points"] == []


# ── 行业估值快照（申万一级，sw_index_first_info）──────────────────────────
from src.api.handler.financial_detail_handler import (
    industry_valuation_snapshot,
)


def test_industry_valuation_snapshot_list():
    """无 industry 参数返回全部 31 个申万一级行业快照。"""
    data = _body(industry_valuation_snapshot(None))
    # akshare 可能不可达，降级时 industries 为空——只要不报错即可
    if data is None:
        pytest.skip("akshare 行业快照不可达")
    industries = data.get("industries", [])
    if not industries:
        pytest.skip("akshare 行业快照为空（网络）")
    assert len(industries) >= 20   # 申万一级约 31 个
    first = industries[0]
    assert "industry" in first
    assert "sw_code" in first
    assert "pe_ttm" in first
    assert "pb" in first


def test_industry_valuation_snapshot_single_by_name():
    """按行业名称查单个行业快照。"""
    data = _body(industry_valuation_snapshot("银行"))
    if data is None:
        pytest.skip("akshare 行业快照不可达")
    assert data.get("industry") == "银行"
    assert "sw_code" in data


def test_industry_valuation_snapshot_single_by_sw_code():
    """按 sw_code 查单个行业快照（前端主路径）。"""
    data = _body(industry_valuation_snapshot("sw801780"))
    if data is None:
        pytest.skip("akshare 行业快照不可达")
    assert data.get("sw_code") == "sw801780"
    assert data.get("industry") == "银行"


def test_industry_valuation_snapshot_not_found():
    """不存在的行业名返回 error（code != 0）。"""
    resp = industry_valuation_snapshot("不存在的行业XYZ")
    body = json.loads(resp.body)
    assert body["code"] != 0
