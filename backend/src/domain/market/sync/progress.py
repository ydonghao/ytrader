"""
ProgressTracker
================
进度跟踪器：记录每个 (provider, symbol, interval) 的最后同步时间。
支持断点续传和增量同步。
"""
import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class SyncStatus(Enum):
    """同步状态"""
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    PARTIAL = "partial"   # 部分成功


@dataclass
class SymbolSyncState:
    """单个 symbol 的同步状态"""
    symbol: str
    interval: str           # "1d", "5m", "60m"
    status: str             # SyncStatus.value
    last_sync_time: Optional[str] = None   # ISO格式最后成功时间
    last_error: Optional[str] = None
    rows_synced: int = 0
    updated_at: str = ""


@dataclass
class ProviderSyncProgress:
    """单个数据源的完整进度"""
    provider: str           # "sina" | "tencent"
    interval: str            # "1d"
    market: str              # "A" | "HK"
    status: str
    total_symbols: int = 0
    done_symbols: int = 0
    total_rows: int = 0
    last_run: Optional[str] = None   # ISO时间
    next_run: Optional[str] = None
    symbols: dict[str, SymbolSyncState] = None  # symbol -> state


class ProgressTracker:
    """
    线程安全的进度跟踪器

    数据存储在 JSON 文件，支持：
    - 按 symbol 查询最后同步时间
    - 更新 symbol 的同步状态
    - 增量同步：只取 last_sync_time 之后的新数据
    - 断点续传：重启后可从上次中断处继续

    落盘策略（内存累积 + 批量延迟写）：
      update_symbol() 只改内存并标记 dirty，不再每次都全量写盘——
      sync_progress.json 现已 50MB+，每次 mark_* 都序列化+落盘会严重
      拖慢并发同步（锁内长 IO）。改为每 FLUSH_EVERY 次写或显式 flush()
      时才落盘一次，写盘次数从 O(symbol数) 降到 O(symbol数/50)。
      进程正常退出时 __del__ 兜底 flush；调用方（SyncService /
      fundamentals）在批处理结束后也显式 flush。
    """

    LOCK = threading.Lock()

    # 每 N 次内存写触发一次落盘。崩溃最多丢最后 N 次状态（仅影响断点续传
    # 的续跑点；DB 增量路径不依赖本文件做判断，无数据正确性影响）。
    FLUSH_EVERY = 50

    def __init__(self, db_path: Optional[Path] = None):
        self._path = db_path or self._default_path()
        self._data: dict = self._load()
        self._pending_writes: int = 0

    def _default_path(self) -> Path:
        from pathlib import Path
        return Path(__file__).parent.parent.parent.parent / "data" / "sync_progress.json"

    # ── 基础存取 ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                return {}
        return {}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2))

    # ── Symbol 级操作 ─────────────────────────────────────────────────────

    def get_last_sync(self, provider: str, symbol: str, interval: str) -> Optional[str]:
        """返回某 symbol 的最后成功同步时间（ISO字符串）"""
        key = self._make_key(provider, interval)
        return self._data.get(key, {}).get("symbols", {}).get(symbol, {}).get("last_sync_time")

    def update_symbol(
        self,
        provider: str,
        symbol: str,
        interval: str,
        status: SyncStatus,
        last_sync_time: Optional[str] = None,
        last_error: Optional[str] = None,
        rows_synced: int = 0,
    ):
        """更新单个 symbol 的同步状态（内存更新，延迟批量落盘）"""
        key = self._make_key(provider, interval)
        with self.LOCK:
            if key not in self._data:
                self._data[key] = {"symbols": {}, "meta": {}}
            sym_dict = self._data[key]["symbols"]
            prev = sym_dict.get(symbol, {})
            sym_dict[symbol] = {
                "symbol": symbol,
                "interval": interval,
                "status": status.value,
                "last_sync_time": last_sync_time or prev.get("last_sync_time"),
                "last_error": last_error,
                "rows_synced": (prev.get("rows_synced", 0) + rows_synced),
                "updated_at": datetime.now().isoformat(),
            }
            self._pending_writes += 1
            if self._pending_writes >= self.FLUSH_EVERY:
                self._save_locked()

    def flush(self) -> None:
        """显式把内存中的改动落盘。批处理结束时应调用一次以防丢失。"""
        with self.LOCK:
            if self._pending_writes > 0:
                self._save_locked()

    def _save_locked(self) -> None:
        """在已持锁的前提下落盘并清零计数（调用方须持 self.LOCK）。"""
        self._save()
        self._pending_writes = 0

    def __del__(self):
        # 进程退出时兜底落盘。__del__ 不保证一定调用，故调用方仍需显式 flush()。
        try:
            self.flush()
        except Exception:
            pass

    def get_pending_symbols(
        self,
        provider: str,
        interval: str,
        all_symbols: list[str],
    ) -> list[str]:
        """返回还未完成同步的 symbol 列表（用于断点续传）"""
        key = self._make_key(provider, interval)
        done = set(
            s for s, state in self._data.get(key, {}).get("symbols", {}).items()
            if state.get("status") == SyncStatus.DONE.value
        )
        return [s for s in all_symbols if s not in done]

    def mark_done(self, provider: str, symbol: str, interval: str, last_sync_time: str, rows: int):
        self.update_symbol(provider, symbol, interval, SyncStatus.DONE, last_sync_time, rows_synced=rows)

    def mark_failed(self, provider: str, symbol: str, interval: str, error: str):
        self.update_symbol(provider, symbol, interval, SyncStatus.FAILED, last_error=error)

    def mark_partial(self, provider: str, symbol: str, interval: str, rows: int):
        """部分成功（有数据但可能不完整）"""
        self.update_symbol(provider, symbol, interval, SyncStatus.PARTIAL, rows_synced=rows)

    # ── 汇总统计 ─────────────────────────────────────────────────────────

    def get_stats(self, provider: str, interval: str) -> dict:
        """获取某 provider + interval 的汇总统计"""
        key = self._make_key(provider, interval)
        syms = self._data.get(key, {}).get("symbols", {})
        done = sum(1 for s in syms.values() if s.get("status") == SyncStatus.DONE.value)
        total = len(syms)
        rows = sum(s.get("rows_synced", 0) for s in syms.values())
        return {"total": total, "done": done, "rows": rows}

    # ── 工具 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _make_key(provider: str, interval: str) -> str:
        return f"{provider}:{interval}"

    def __repr__(self):
        return f"<ProgressTracker {len(self._data)} providers>"
