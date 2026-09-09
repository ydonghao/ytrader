"""fetch_financial_snapshot + _flatten_detail 测试。

_flatten_detail 为纯函数（无需 DB）；fetch_financial_snapshot 需 DB，无库时 skip。
"""
import pytest

from src.domain.market.strategy.longterm.data_loader import (
    _flatten_detail,
    fetch_financial_snapshot,
)


class TestFlattenDetail:
    def test_basic_with_chinese_units(self):
        d = {
            "应付账款": "50亿",
            "合同负债": "20亿",
            "销售商品、提供劳务收到的现金": "100亿",
        }
        out = _flatten_detail(d)
        assert out["accounts_payable"] == pytest.approx(50e8)
        assert out["contract_liability"] == pytest.approx(20e8)
        assert out["cash_from_sales"] == pytest.approx(100e8)

    def test_numeric_values(self):
        out = _flatten_detail({"应付账款": 30.0, "在建工程": 10.0})
        assert out["accounts_payable"] == 30.0
        assert out["construction_in_progress"] == 10.0

    def test_candidate_key_fallback(self):
        # 预收款项（候选第二个）
        out = _flatten_detail({"预收款项": "5亿"})
        assert out["advance_receipts"] == pytest.approx(5e8)

    def test_missing_keys(self):
        assert _flatten_detail({"不相关的科目": 100}) == {}

    def test_non_dict(self):
        assert _flatten_detail(None) == {}
        assert _flatten_detail("x") == {}
        assert _flatten_detail([]) == {}


def _db_available() -> bool:
    try:
        import psycopg2

        from src.infra.database.sql_engine.dsn import get_dsn

        conn = psycopg2.connect(get_dsn())
        conn.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_available(), reason="无可用 DB")
class TestFetchFinancialSnapshot:
    def test_empty_symbols(self):
        assert fetch_financial_snapshot([]) == {}

    def test_nonexistent_symbol_returns_empty(self):
        out = fetch_financial_snapshot(["NONEXISTENT_SYMBOL_XYZ_999"])
        assert out == {} or "NONEXISTENT_SYMBOL_XYZ_999" not in out

    def test_real_symbol_returns_data(self):
        """真实标的必须返回非空财报——防止 SQL 静默失败(被 try/except 吞成 {})误判为'无数据'。"""
        out = fetch_financial_snapshot(["sh600519"])  # 贵州茅台
        snap = out.get("sh600519")
        assert snap is not None, "茅台应有三表数据；返回空说明查询静默失败(如缺列)"
        assert snap.get("report_date") is not None
        # 至少一个核心利润表/资产负债表字段有值
        assert any(snap.get(k) is not None for k in ("revenue", "net_profit", "total_assets"))
