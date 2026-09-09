"""Tests for market router API endpoints."""
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock


class TestMarketOverview:
    """Test GET /market/overview endpoint."""

    def test_market_overview_returns_success(self):
        from fastapi.testclient import TestClient
        from src.api.router.market_router import router

        # Create a minimal FastAPI app for testing
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/market/overview")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "markets" in data["data"]


class TestMarketKline:
    """Test GET /market/kline/{symbol} endpoint."""

    def test_kline_symbol_required(self):
        """路径参数 symbol 是必需的，缺失返回 422"""
        from fastapi.testclient import TestClient
        from src.api.router.market_router import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # symbol 是路径参数，缺失返回 404（路径不匹配）
        response = client.get("/market/kline/")
        assert response.status_code == 404

    def test_kline_with_optional_params(self):
        """K线 start/end/interval 均可选"""
        from fastapi.testclient import TestClient
        from src.api.router.market_router import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # 全用默认值也应该能返回（空结果或真实数据）
        response = client.get("/market/kline/sh600000")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "bars" in data["data"]

    def test_kline_with_valid_params(self):
        """K线带日期参数"""
        from fastapi.testclient import TestClient
        from src.api.router.market_router import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        with patch("src.api.router.market_router.fetch_kline") as mock_fetch:
            mock_fetch.return_value = [
                {"trade_date": "2024-01-01", "open_": 10.0, "close_": 10.5,
                 "high_": 10.8, "low_": 9.8, "volume": 1000000.0, "amount": 0.0}
            ]

            response = client.get(
                "/market/kline/sh600000",
                params={"start": "2024-01-01", "end": "2024-01-10", "interval": "1d"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 0
            assert data["data"]["symbol"] == "sh600000"
            assert len(data["data"]["bars"]) == 1


class TestMarketSearch:
    """Test GET /market/search endpoint."""

    def test_search_requires_query(self):
        """search 参数 q 是必需的，缺失返回 422"""
        from fastapi.testclient import TestClient
        from src.api.router.market_router import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/market/search")
        assert response.status_code == 422  # 缺少必需 Query 参数 q

    def test_search_with_query(self):
        """搜索返回结果"""
        from fastapi.testclient import TestClient
        from src.api.router.market_router import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        with patch("src.api.router.market_router.search_symbols") as mock_search:
            mock_search.return_value = [
                {"symbol": "sh600000", "market": "A",
                 "list_date": "1994-01-01", "bars": 0}
            ]

            response = client.get("/market/search", params={"q": "浦发"})

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 0
            assert len(data["data"]) == 1
            assert data["data"][0]["symbol"] == "sh600000"


class TestRangeSql:
    """Test _range_sql helper for range-based pct change."""

    def test_range_sql_with_both_dates(self):
        from src.api.router.market_router import _range_sql
        sql, params = _range_sql("index_ohlcv", "trade_date", "2025-01-01", "2025-06-30")
        assert "%s" in sql
        assert "index_ohlcv" in sql
        assert "trade_date" in sql
        assert "trade_date <= %s" in sql
        assert "trade_date < %s" in sql
        assert "rn = 1" in sql
        # params 按出现顺序：先 end 后 start
        assert params == ["2025-06-30", "2025-01-01"]

    def test_range_sql_with_where_clause(self):
        """where 子句（无论带不带前导 WHERE）拼入 SQL 时不得产生双重 WHERE。"""
        from src.api.router.market_router import _range_sql
        # 调用方传带 "WHERE " 前缀
        sql, _ = _range_sql("index_ohlcv", "trade_date", "2025-01-01", "2025-06-30",
                            where="WHERE market='INDEX'")
        assert "market='INDEX'" in sql
        assert "WHERE WHERE" not in sql  # 防回归：双重 WHERE 关键字
        assert "%s" in sql
        # 调用方传不带前缀（推荐用法）
        sql2, _ = _range_sql("index_ohlcv", "trade_date", "2025-01-01", "2025-06-30",
                             where="market='SW'")
        assert "WHERE market='SW'" in sql2
        assert "WHERE WHERE" not in sql2

    def test_range_sql_end_only(self):
        from src.api.router.market_router import _range_sql
        sql, _ = _range_sql("index_ohlcv", "trade_date", None, "2025-06-30")
        assert "trade_date <= %s" in sql
        assert "ASC" in sql  # prev 取最早一条（start 空 → ASC）

    def test_range_sql_no_dates(self):
        """start/end 都空时，退化为「最新 close + 最早 close」。
        此分支实际不会被调用（list_indices 无参时走 _latest_sql），只确保不报错。"""
        from src.api.router.market_router import _range_sql
        sql, params = _range_sql("index_ohlcv", "trade_date", None, None)
        assert isinstance(sql, str)
        assert "index_ohlcv" in sql
        assert params == []


class TestMarketIndices:
    """Test GET /market/indices endpoint (with optional start/end range)."""

    def _make_client(self):
        from fastapi.testclient import TestClient
        from src.api.router.market_router import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_indices_no_params_returns_today_snapshot(self):
        """无参 → 现状：最新收盘 + 当日涨跌幅。patch get_conn 返回固定行。"""
        client = self._make_client()

        # 模拟 cursor.fetchall 返回：先 INDEX 查询，再 SW 查询
        index_rows = [
            {"symbol": "sh000300", "close_": 4000.0, "prev": 3980.0},
        ]
        sw_rows = [
            {"symbol": "sw801010", "close_": 3000.0, "prev": 2970.0},
        ]

        mock_cursor = MagicMock()
        # 两次 execute → 两次 fetchall，按 INDEX / SW 顺序
        mock_cursor.fetchall.side_effect = [index_rows, sw_rows]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = False

        # 注意：list_indices 内部用 `from conf import app_config`（函数内导入），
        # 故 app_config 不在 market_router 模块命名空间——必须 patch 源头 `conf.app_config`。
        with patch("src.api.router.market_router.get_conn", return_value=mock_conn), \
             patch("conf.app_config") as mock_cfg:
            # mock 量化宇宙配置（indices / sw_industries 名字映射）
            mock_cfg.quant_universe.indices = [
                type("I", (), {"symbol": "sh000300", "name": "沪深300"})()
            ]
            mock_cfg.quant_universe.sw_industries = [
                type("I", (), {"symbol": "801010", "name": "农林牧渔"})()
            ]

            response = client.get("/market/indices")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert len(data["data"]["market_index"]) == 1
        assert data["data"]["market_index"][0]["symbol"] == "sh000300"
        assert data["data"]["market_index"][0]["name"] == "沪深300"
        # change_pct = (4000/3980 - 1) * 100 ≈ 0.50
        assert data["data"]["market_index"][0]["change_pct"] == round((4000.0/3980.0 - 1)*100, 2)
        assert data["data"]["sw_index"][0]["name"] == "农林牧渔"

    def test_indices_with_range_uses_range_sql(self):
        """带 start/end → 调用 _range_sql 路径。验证传入参数。"""
        client = self._make_client()

        index_rows = [{"symbol": "sh000300", "close_": 4000.0, "prev": 3500.0}]
        sw_rows = [{"symbol": "sw801010", "close_": 3000.0, "prev": 2800.0}]

        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [index_rows, sw_rows]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = False

        with patch("src.api.router.market_router.get_conn", return_value=mock_conn), \
             patch("conf.app_config") as mock_cfg:
            mock_cfg.quant_universe.indices = [
                type("I", (), {"symbol": "sh000300", "name": "沪深300"})()
            ]
            mock_cfg.quant_universe.sw_industries = [
                type("I", (), {"symbol": "801010", "name": "农林牧渔"})()
            ]

            response = client.get("/market/indices",
                                  params={"start": "2025-01-01", "end": "2025-06-30"})

        assert response.status_code == 200
        data = response.json()
        # 区间涨跌：sh000300 (4000/3500-1)*100 ≈ 14.29
        assert data["data"]["market_index"][0]["change_pct"] == round((4000.0/3500.0 - 1)*100, 2)
        # execute 被调用时带了 params（参数化）
        # 第一次 execute（INDEX）的第二参数应包含两个日期
        first_call_args = mock_cursor.execute.call_args_list[0]
        assert first_call_args[0][1] == ["2025-06-30", "2025-01-01"]  # [end, start] 顺序

    def test_indices_invalid_date_returns_422(self):
        """非法日期 → FastAPI Pydantic 校验失败 422。"""
        client = self._make_client()
        response = client.get("/market/indices", params={"start": "not-a-date"})
        assert response.status_code == 422

    def test_indices_start_after_end_returns_400(self):
        """start > end → 业务校验 400。"""
        client = self._make_client()
        response = client.get("/market/indices",
                              params={"start": "2025-06-30", "end": "2025-01-01"})
        assert response.status_code == 400
