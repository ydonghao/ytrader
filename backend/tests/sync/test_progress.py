"""
Tests for ProgressTracker — TDD 风格的断点续传测试
"""
import json
import tempfile
import threading
from pathlib import Path

import pytest

from src.domain.market.sync.progress import (
    ProgressTracker,
    SyncStatus,
    SymbolSyncState,
    ProviderSyncProgress,
)


class TestSyncStatus:
    """SyncStatus 枚举测试"""

    def test_pending_value(self):
        assert SyncStatus.PENDING.value == "pending"

    def test_running_value(self):
        assert SyncStatus.RUNNING.value == "running"

    def test_done_value(self):
        assert SyncStatus.DONE.value == "done"

    def test_failed_value(self):
        assert SyncStatus.FAILED.value == "failed"

    def test_partial_value(self):
        assert SyncStatus.PARTIAL.value == "partial"


class TestSymbolSyncState:
    """SymbolSyncState 数据类测试"""

    def test_default_values(self):
        state = SymbolSyncState(symbol="sh600000", interval="1d", status="pending")
        assert state.symbol == "sh600000"
        assert state.interval == "1d"
        assert state.status == "pending"
        assert state.last_sync_time is None
        assert state.last_error is None
        assert state.rows_synced == 0

    def test_with_full_data(self):
        state = SymbolSyncState(
            symbol="sz000001",
            interval="60m",
            status="done",
            last_sync_time="2026-04-03T20:00:00",
            last_error=None,
            rows_synced=3000,
        )
        assert state.rows_synced == 3000
        assert state.last_sync_time == "2026-04-03T20:00:00"


class TestProgressTrackerInit:
    """ProgressTracker 初始化测试"""

    def test_init_with_default_path(self):
        tracker = ProgressTracker()
        assert tracker._path.name == "sync_progress.json"

    def test_init_with_custom_path(self, tmp_path):
        tracker = ProgressTracker(db_path=tmp_path / "custom.json")
        assert tracker._path == tmp_path / "custom.json"

    def test_load_empty_file(self, tmp_path):
        """不存在的文件初始化为空字典"""
        tracker = ProgressTracker(db_path=tmp_path / "new.json")
        assert tracker._data == {}


class TestProgressTrackerSymbolOperations:
    """Symbol 级操作的 TDD 测试"""

    def test_update_symbol_creates_entry(self, tmp_path):
        """RED: 更新 symbol 后能查询到最后同步时间"""
        tracker = ProgressTracker(db_path=tmp_path / "t.json")
        tracker.update_symbol(
            provider="sina",
            symbol="sh600000",
            interval="1d",
            status=SyncStatus.DONE,
            last_sync_time="2026-04-03T00:00:00",
            rows_synced=1300,
        )
        last = tracker.get_last_sync("sina", "sh600000", "1d")
        assert last == "2026-04-03T00:00:00"

    def test_get_last_sync_returns_none_for_unknown(self, tmp_path):
        """未知 symbol 返回 None"""
        tracker = ProgressTracker(db_path=tmp_path / "t.json")
        result = tracker.get_last_sync("sina", "sh600999", "1d")
        assert result is None

    def test_get_pending_symbols_filters_done(self, tmp_path):
        """已完成（status=DONE）的 symbol 不会出现在待补列表"""
        tracker = ProgressTracker(db_path=tmp_path / "t.json")
        all_syms = ["sh600000", "sh600001", "sh600002"]

        # 标记第一个为 DONE
        tracker.update_symbol(
            "sina", "sh600000", "1d", SyncStatus.DONE,
            last_sync_time="2026-04-03T00:00:00", rows_synced=1300,
        )

        pending = tracker.get_pending_symbols("sina", "1d", all_syms)
        assert "sh600000" not in pending
        assert "sh600001" in pending
        assert "sh600002" in pending

    def test_get_pending_symbols_empty_when_all_done(self, tmp_path):
        """全部已完成时返回空列表"""
        tracker = ProgressTracker(db_path=tmp_path / "t.json")
        all_syms = ["sh600000", "sh600001"]
        for sym in all_syms:
            tracker.update_symbol(
                "sina", sym, "1d", SyncStatus.DONE,
                last_sync_time="2026-04-03T00:00:00", rows_synced=100,
            )
        pending = tracker.get_pending_symbols("sina", "1d", all_syms)
        assert pending == []

    def test_mark_done_sets_status_and_rows(self, tmp_path):
        """mark_done 正确设置状态"""
        tracker = ProgressTracker(db_path=tmp_path / "t.json")
        tracker.mark_done("sina", "sh600000", "1d", "2026-04-03T00:00:00", 1300)
        last = tracker.get_last_sync("sina", "sh600000", "1d")
        assert last == "2026-04-03T00:00:00"
        stats = tracker.get_stats("sina", "1d")
        assert stats["done"] == 1
        assert stats["rows"] == 1300

    def test_mark_failed_preserves_previous_rows(self, tmp_path):
        """mark_failed 累加已写入行数"""
        tracker = ProgressTracker(db_path=tmp_path / "t.json")
        tracker.update_symbol(
            "sina", "sh600000", "1d", SyncStatus.DONE,
            last_sync_time="2026-04-02T00:00:00", rows_synced=1000,
        )
        # 再次更新（失败场景），rows 累加
        tracker.update_symbol(
            "sina", "sh600000", "1d", SyncStatus.FAILED,
            rows_synced=0, last_error="Connection timeout",
        )
        stats = tracker.get_stats("sina", "1d")
        assert stats["rows"] == 1000  # 失败不追加新行

    def test_mark_partial_with_rows(self, tmp_path):
        """mark_partial 正确记录行数"""
        tracker = ProgressTracker(db_path=tmp_path / "t.json")
        tracker.mark_partial("sina", "sh600000", "1d", 500)
        last = tracker.get_last_sync("sina", "sh600000", "1d")
        assert last is None  # partial 不更新 last_sync_time
        stats = tracker.get_stats("sina", "1d")
        assert stats["rows"] == 500


class TestProgressTrackerStats:
    """汇总统计测试"""

    def test_get_stats_empty(self, tmp_path):
        tracker = ProgressTracker(db_path=tmp_path / "t.json")
        stats = tracker.get_stats("sina", "1d")
        assert stats["total"] == 0
        assert stats["done"] == 0
        assert stats["rows"] == 0

    def test_get_stats_aggregates_rows(self, tmp_path):
        tracker = ProgressTracker(db_path=tmp_path / "t.json")
        tracker.update_symbol("sina", "sh600000", "1d", SyncStatus.DONE,
                             last_sync_time="2026-04-03", rows_synced=1300)
        tracker.update_symbol("sina", "sh600001", "1d", SyncStatus.DONE,
                             last_sync_time="2026-04-03", rows_synced=1200)
        stats = tracker.get_stats("sina", "1d")
        assert stats["done"] == 2
        assert stats["rows"] == 2500

    def test_get_stats_filters_non_done(self, tmp_path):
        tracker = ProgressTracker(db_path=tmp_path / "t.json")
        tracker.update_symbol("sina", "sh600000", "1d", SyncStatus.DONE,
                             last_sync_time="2026-04-03", rows_synced=1300)
        tracker.update_symbol("sina", "sh600001", "1d", SyncStatus.PENDING,
                             rows_synced=0)
        stats = tracker.get_stats("sina", "1d")
        assert stats["total"] == 2
        assert stats["done"] == 1  # 只统计 DONE


class TestProgressTrackerPersistence:
    """持久化测试"""

    def test_persists_to_disk(self, tmp_path):
        """重启后数据不丢失"""
        path = tmp_path / "persist.json"
        t1 = ProgressTracker(db_path=path)
        t1.update_symbol("sina", "sh600000", "1d", SyncStatus.DONE,
                         last_sync_time="2026-04-03", rows_synced=999)
        # 重新创建实例（模拟重启）
        t2 = ProgressTracker(db_path=path)
        last = t2.get_last_sync("sina", "sh600000", "1d")
        assert last == "2026-04-03"

    def test_concurrent_updates_are_safe(self, tmp_path):
        """并发更新不丢数据（线程安全）"""
        tracker = ProgressTracker(db_path=tmp_path / "concurrent.json")
        errors = []

        def worker(i):
            try:
                for j in range(10):
                    tracker.update_symbol(
                        "sina", f"sh60000{i}", "1d", SyncStatus.RUNNING,
                        rows_synced=j,
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        stats = tracker.get_stats("sina", "1d")
        assert stats["total"] == 5
