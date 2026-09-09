"""
news_backfill.py 测试
=====================
"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure src is in path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from src.domain.market.news.sync_service import NewsSyncStats


class TestNewsBackfill:
    """NewsBackfill 测试"""

    @pytest.fixture
    def mock_sync_service(self):
        """Mock sync service"""
        service = MagicMock()
        service.sync_stock_news.return_value = NewsSyncStats(
            total=10,
            saved=5,
            duplicates=5,
            errors=0,
            duration_seconds=0.5,
        )
        return service

    @pytest.fixture
    def sample_stock_list(self):
        """示例股票列表"""
        return [
            {"symbol": "sh600000", "name": "浦发银行"},
            {"symbol": "sh600001", "name": "邯郸钢铁"},
            {"symbol": "sh600002", "name": "齐鲁石化"},
        ]

    def test_backfill_stock_list(self, mock_sync_service, sample_stock_list):
        """backfill_stock_list 正确执行"""
        with patch("news_backfill.get_stock_list", return_value=sample_stock_list):
            from news_backfill import backfill_stock_list

            result = backfill_stock_list(
                mock_sync_service,
                symbols=None,
                days_back=7,
            )

        assert result["total_symbols"] == 3
        assert result["total_news"] == 30
        assert result["saved_news"] == 15
        assert result["errors"] == 0

    def test_backfill_with_symbols_filter(
        self, mock_sync_service, sample_stock_list
    ):
        """backfill_stock_list 支持 symbols 过滤"""
        with patch("news_backfill.get_stock_list", return_value=sample_stock_list):
            from news_backfill import backfill_stock_list

            result = backfill_stock_list(
                mock_sync_service,
                symbols=["sh600000", "sh600001"],
                days_back=7,
            )

        assert result["total_symbols"] == 2
        assert mock_sync_service.sync_stock_news.call_count == 2

    def test_backfill_saves_progress(
        self, mock_sync_service, sample_stock_list
    ):
        """backfill_stock_list 保存进度"""
        with patch("news_backfill.get_stock_list", return_value=sample_stock_list):
            from news_backfill import backfill_stock_list

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                progress_file = f.name

            try:
                result = backfill_stock_list(
                    mock_sync_service,
                    symbols=None,
                    days_back=7,
                    progress_file=progress_file,
                )

                with open(progress_file) as f:
                    progress = json.load(f)

                assert progress["total_symbols"] == 3
                assert progress["completed_symbols"] == 3
                assert "last_updated" in progress
            finally:
                os.unlink(progress_file)

    def test_backfill_handles_errors(
        self, mock_sync_service, sample_stock_list
    ):
        """backfill_stock_list 处理错误"""
        mock_sync_service.sync_stock_news.side_effect = [
            NewsSyncStats(total=10, saved=5, duplicates=5, errors=0),
            Exception("Network error"),
            NewsSyncStats(total=10, saved=10, duplicates=0, errors=0),
        ]

        with patch("news_backfill.get_stock_list", return_value=sample_stock_list):
            from news_backfill import backfill_stock_list

            result = backfill_stock_list(
                mock_sync_service,
                symbols=None,
                days_back=7,
            )

        assert result["total_symbols"] == 3
        assert result["errors"] >= 1


class TestGetStockList:
    """get_stock_list 测试"""

    def test_get_stock_list_from_db(self):
        """从数据库获取股票列表"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchall.return_value = [
            ("sh600000", "浦发银行"),
            ("sh600001", "邯郸钢铁"),
        ]

        with patch("psycopg2.connect", return_value=mock_conn):
            from news_backfill import get_stock_list

            result = get_stock_list()

        assert len(result) == 2
        assert result[0]["symbol"] == "sh600000"
