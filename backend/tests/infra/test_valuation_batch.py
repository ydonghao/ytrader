"""StockValuationRepository.get_range_batch 测试。

用 mock 替换 psycopg2 连接，验证 SQL 构造、按 symbol 分组与 exclude_ranges 过滤逻辑
（不连真实库）。实现采用 psycopg2 直查（与 data_loader.py 同款），故这里 mock
valuation 模块内的 psycopg2.connect，而非 ORM session。
"""
import sys
import os
import datetime as dt
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from src.infra.database.market import valuation as valuation_module
from src.infra.database.market.valuation import StockValuation, StockValuationRepository


def _make_row(symbol, d, pb=1.0, pe_ttm=10.0):
    return StockValuation(symbol=symbol, trade_date=d, pb=pb, pe_ttm=pe_ttm)


def _dict_row(symbol, d, pb=1.0, pe_ttm=10.0):
    """模拟 RealDictCursor 返回的一行（dict-like）。"""
    return {
        "symbol": symbol,
        "trade_date": d,
        "pe": None,
        "pe_ttm": pe_ttm,
        "pb": pb,
        "ps": None,
        "ps_ttm": None,
        "dv_ratio": None,
        "dv_ttm": None,
        "total_mv": None,
    }


def _patch_conn(rows):
    """返回一个 patch 对象，使 valuation.psycopg2.connect 返回的 cursor 产出 rows。"""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = list(rows)
    mock_conn.cursor.return_value = mock_cur
    mock_conn.close = MagicMock()
    return patch.object(valuation_module.psycopg2, "connect", return_value=mock_conn)


class TestGetRangeBatch:
    def test_groups_by_symbol(self):
        """多符号返回按 symbol 分组的 dict。"""
        repo = StockValuationRepository.__new__(StockValuationRepository)
        fake_rows = [
            _dict_row("A", dt.date(2024, 1, 31)),
            _dict_row("A", dt.date(2024, 2, 28)),
            _dict_row("B", dt.date(2024, 1, 31)),
        ]
        with _patch_conn(fake_rows):
            result = repo.get_range_batch(
                ["A", "B"], dt.date(2024, 1, 1), dt.date(2024, 3, 1)
            )
        assert set(result.keys()) == {"A", "B"}
        assert len(result["A"]) == 2
        assert len(result["B"]) == 1
        # 验证结果元素类型与字段
        assert all(isinstance(r, StockValuation) for r in result["A"])
        assert result["A"][0].symbol == "A"
        assert result["A"][0].trade_date == dt.date(2024, 1, 31)

    def test_empty_symbols_returns_empty(self):
        repo = StockValuationRepository.__new__(StockValuationRepository)
        result = repo.get_range_batch([], dt.date(2024, 1, 1), dt.date(2024, 3, 1))
        assert result == {}

    def test_exclude_ranges_in_query(self):
        """exclude_ranges 非空时，落在剔除区间内的行应被过滤掉。"""
        repo = StockValuationRepository.__new__(StockValuationRepository)
        # 区间内 + 区间外各一行
        fake_rows = [
            _dict_row("A", dt.date(2021, 3, 15)),  # 在 [2021-01-01, 2021-06-30] 内 → 剔除
            _dict_row("A", dt.date(2023, 5, 1)),   # 区间外 → 保留
        ]
        with _patch_conn(fake_rows):
            result = repo.get_range_batch(
                ["A"], dt.date(2020, 1, 1), dt.date(2024, 1, 1),
                exclude_ranges=[(dt.date(2021, 1, 1), dt.date(2021, 6, 30))],
            )
        assert "A" in result
        assert len(result["A"]) == 1
        assert result["A"][0].trade_date == dt.date(2023, 5, 1)
