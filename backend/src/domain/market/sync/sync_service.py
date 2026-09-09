"""
SyncService
============
可复用的同步核心服务。

设计原则：
  - 数据源无关：通过 SyncProvider 接口支持 Sina/Tencent/Akshare
  - 模式无关：同时支持全量回填（backfill）和增量同步（incremental）
  - 断点续传：通过 ProgressTracker 记录每个 symbol 的最后同步时间
  - 增量逻辑：只拉取 last_sync_time 之后的新数据

使用方式：
  # 1. 初始化（注入数据源）
  service = SyncService(
      provider=sina_provider,   # SyncProvider 实现
      progress_tracker=tracker,
  )

  # 2. 全量回填（一次性）
  service.backfill(
      symbols=["sh600000", "sz000001"],
      interval="1d",
      mode="full",    # 忽略 last_sync_time，全量拉取
  )

  # 3. 增量同步（每日定时调用）
  service.backfill(
      symbols=all_symbols,       # 全量列表
      interval="1d",
      mode="incremental",         # 只拉 last_sync_time 之后的数据
  )
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values

from .progress import ProgressTracker, SyncStatus
from .sync_provider import OHLCVBar, SyncProvider

log = logging.getLogger(__name__)


# ── SQL ────────────────────────────────────────────────────────────────────────
DAILY_INSERT_SQL = """
INSERT INTO stock_ohlcv
    (symbol, trade_date, open_, close_, high_, low_, volume, amount, market, created_at)
VALUES %s
ON CONFLICT (trade_date, symbol) DO UPDATE SET
    open_ = EXCLUDED.open_, close_ = EXCLUDED.close_,
    high_ = EXCLUDED.high_, low_ = EXCLUDED.low_,
    volume = EXCLUDED.volume, amount = EXCLUDED.amount
"""

MINUTE_INSERT_SQL = """
INSERT INTO stock_ohlcv_minute
    (symbol, trade_time, open_, close_, high_, low_, volume, amount, market, interval, created_at)
VALUES %s
ON CONFLICT (trade_time, symbol, interval) DO UPDATE SET
    open_ = EXCLUDED.open_, close_ = EXCLUDED.close_,
    high_ = EXCLUDED.high_, low_ = EXCLUDED.low_,
    volume = EXCLUDED.volume, amount = EXCLUDED.amount
"""

COMMODITY_INSERT_SQL = """
INSERT INTO commodity_ohlcv
    (symbol, trade_date, open_, close_, high_, low_, volume, amount, asset_class, created_at)
VALUES %s
ON CONFLICT (trade_date, symbol) DO UPDATE SET
    open_ = EXCLUDED.open_, close_ = EXCLUDED.close_,
    high_ = EXCLUDED.high_, low_ = EXCLUDED.low_,
    volume = EXCLUDED.volume, amount = EXCLUDED.amount,
    asset_class = EXCLUDED.asset_class
"""

INDEX_INSERT_SQL = """
INSERT INTO index_ohlcv
    (symbol, trade_date, open_, close_, high_, low_, volume, amount, market, created_at)
VALUES %s
ON CONFLICT (trade_date, symbol) DO UPDATE SET
    open_ = EXCLUDED.open_, close_ = EXCLUDED.close_,
    high_ = EXCLUDED.high_, low_ = EXCLUDED.low_,
    volume = EXCLUDED.volume, amount = EXCLUDED.amount
"""


@dataclass
class SyncConfig:
    """同步配置"""
    max_workers: int = 8
    batch_size: int = 500
    rate_delay: float = 0.1      # 每次请求后等待秒数（防限速）
    request_timeout: int = 15
    db_dsn: str = ""


class SyncService:
    """
    同步核心服务

    Attributes:
        provider:         数据源（SyncProvider 实现）
        progress_tracker: 进度跟踪器
        config:          同步配置
    """

    def __init__(
        self,
        provider: SyncProvider,
        progress_tracker: ProgressTracker,
        config: Optional[SyncConfig] = None,
    ):
        self.provider = provider
        self.tracker = progress_tracker
        self.config = config or SyncConfig()

    # ── 主入口 ──────────────────────────────────────────────────────────────

    def backfill(
        self,
        symbols: list[str],
        interval: str = "1d",
        mode: str = "full",     # "full" | "incremental"
        db_dsn: str = "",
    ) -> "SyncResult":
        """
        执行回填或增量同步

        Args:
            symbols:   股票代码列表
            interval:  K线周期 "1d" | "5m" | "15m" | "60m"
            mode:      "full" (忽略last_sync，全量) | "incremental" (只拉新数据)
            db_dsn:   数据库连接

        Returns:
            SyncResult: 同步结果汇总
        """
        db_dsn = db_dsn or self.config.db_dsn
        if not db_dsn:
            raise ValueError("db_dsn must be provided")

        interval = interval or "1d"
        is_daily = interval == "1d"
        insert_sql = DAILY_INSERT_SQL if is_daily else MINUTE_INSERT_SQL

        # 过滤待处理 symbol
        if mode == "incremental":
            # incremental 模式：只同步已有记录的symbol
            pending = [
                s for s in symbols
                if self.tracker.get_last_sync(self.provider.name, s, interval) is not None
            ] if symbols else []
        elif mode == "resume":
            # resume 模式：跳过已完成的symbol（断点续传）
            pending = self.tracker.get_pending_symbols(
                self.provider.name, interval, symbols
            )
        else:
            # full 模式：忽略tracker状态，全量同步
            pending = list(symbols) if symbols else []

        if not pending:
            log.info(f"[{self.provider.name}/{interval}] 无待处理symbol，跳过")
            return SyncResult(provider=self.provider.name, interval=interval)

        log.info(
            f"[{self.provider.name}/{interval}] "
            f"{mode} 模式, {len(pending)} 只股票, max_workers={self.config.max_workers}"
        )

        t0 = time.time()
        total_rows = 0
        done = 0
        failed = 0
        errors = []

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
            futures = {
                pool.submit(
                    self._sync_one,
                    db_dsn, sym, interval, insert_sql, is_daily,
                ): sym
                for sym in pending
            }
            for future in as_completed(futures):
                sym = futures[future]
                try:
                    result = future.result()
                    if result.rows > 0:
                        total_rows += result.rows
                        done += 1
                        last_time = result.last_bar_time or ""
                        self.tracker.mark_done(
                            self.provider.name, sym, interval, last_time, result.rows
                        )
                        log.info(
                            f"  [{done}/{len(pending)}] {sym} +{result.rows} rows "
                            f"total={total_rows:,}"
                        )
                    else:
                        # 有请求但无数据（停牌等）
                        self.tracker.mark_partial(self.provider.name, sym, interval, 0)
                except Exception as e:
                    failed += 1
                    errors.append(f"{sym}: {e}")
                    self.tracker.mark_failed(self.provider.name, sym, interval, str(e))
                    log.warning(f"  {sym} failed: {e}")

                time.sleep(self.config.rate_delay)
        # 批处理结束：把累积的进度一次性落盘（update_symbol 仅内存写）
        self.tracker.flush()
        elapsed = time.time() - t0
        log.info(
            f"[{self.provider.name}/{interval}] 完成: "
            f"{done} 成功, {failed} 失败, {total_rows:,} 行, {elapsed:.0f}s"
        )

        return SyncResult(
            provider=self.provider.name,
            interval=interval,
            mode=mode,
            total_symbols=len(pending),
            done_symbols=done,
            failed_symbols=failed,
            total_rows=total_rows,
            elapsed_seconds=elapsed,
            errors=errors,
        )

    # ── 日期范围回填（akshare 长历史 / 分段切片）─────────────────────────
    def backfill_range(
        self,
        symbols: list[str],
        interval: str = "1d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        insert_sql: Optional[str] = None,
        asset_class: Optional[str] = None,
        is_index: bool = False,
        mode: str = "full",
        db_dsn: str = "",
        incremental_from_db: bool = False,
    ) -> "SyncResult":
        """按日期范围回填。复用线程池 + ProgressTracker + execute_values。

        Args:
            symbols:     标的列表
            interval:    "1d" | "5m" | "15m" | "30m" | "60m"
            start_date:  ISO 起始日 "2026-06-25"（分钟线内部补时分段）
            end_date:    ISO 结束日
            insert_sql:  目标表 upsert SQL（默认按 interval/资产类选表）
            asset_class: commodity_ohlcv 的 metal/energy（写商品表时必填）
            is_index:    写 index_ohlcv 表并走 fetch_index_daily（指数专属）
            mode:        "full" | "incremental" | "resume"
            db_dsn:      数据库连接
            incremental_from_db: DB 驱动增量（推荐工作日用）。忽略易损坏的
                sync_progress.json，改为一次性 GROUP BY 查目标表每个 symbol 的
                MAX(trade_date) 作为该 symbol 的 start_date（覆盖其缺口）。
                DB 无记录的 symbol 退回 start_date。需配合 mode="full"（让 pending
                不过滤），每个 symbol 的 start_date 在提交时按表内最新日重算。
        """
        db_dsn = db_dsn or self.config.db_dsn
        if not db_dsn:
            raise ValueError("db_dsn must be provided")

        interval = interval or "1d"
        is_daily = interval == "1d"
        if insert_sql is None:
            if is_index:
                insert_sql = INDEX_INSERT_SQL
            elif asset_class:
                insert_sql = COMMODITY_INSERT_SQL
            else:
                insert_sql = DAILY_INSERT_SQL if is_daily else MINUTE_INSERT_SQL
        is_commodity = (not is_index) and (
            insert_sql == COMMODITY_INSERT_SQL or asset_class is not None
        )

        # 过滤待处理 symbol
        if mode == "incremental":
            pending = [
                s for s in symbols
                if self.tracker.get_last_sync(self.provider.name, s, interval) is not None
            ] if symbols else []
        elif mode == "resume":
            pending = self.tracker.get_pending_symbols(
                self.provider.name, interval, symbols
            )
        else:
            pending = list(symbols) if symbols else []

        if not pending:
            log.info(f"[{self.provider.name}/{interval}] 无待处理symbol，跳过")
            return SyncResult(provider=self.provider.name, interval=interval)

        # DB 驱动增量：一次性取目标表 {symbol: max_date}，逐 symbol 重算 start_date。
        # 比依赖 sync_progress.json 可靠（JSON 易被并发写坏），且只用一条 GROUP BY。
        sym_start: dict[str, Optional[str]] = {}
        if incremental_from_db:
            target_table, date_col = self._resolve_target_table(
                insert_sql, is_daily, is_commodity, is_index
            )
            sym_start = self._load_symbol_max_dates(db_dsn, target_table, date_col, pending)
            hit = sum(1 for v in sym_start.values() if v)
            log.info(
                f"[{self.provider.name}/{interval}] DB 增量: {hit}/{len(pending)} "
                f"symbol 有历史，按 MAX({date_col}) 续拉"
            )

        log.info(
            f"[{self.provider.name}/{interval}] range {mode} 模式, "
            f"{len(pending)} 只, {start_date}~{end_date}, "
            f"workers={self.config.max_workers}"
        )

        t0 = time.time()
        total_rows = 0
        done = 0
        failed = 0
        errors = []

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
            futures = {
                pool.submit(
                    self._sync_one_range,
                    db_dsn, sym, interval,
                    sym_start.get(sym) or start_date,
                    end_date,
                    insert_sql, is_commodity, is_index, asset_class,
                ): sym
                for sym in pending
            }
            for future in as_completed(futures):
                sym = futures[future]
                try:
                    result = future.result()
                    if result.rows > 0:
                        total_rows += result.rows
                        done += 1
                        last_time = result.last_bar_time or ""
                        self.tracker.mark_done(
                            self.provider.name, sym, interval, last_time, result.rows
                        )
                        log.info(
                            f"  [{done}/{len(pending)}] {sym} +{result.rows} rows "
                            f"total={total_rows:,}"
                        )
                    else:
                        self.tracker.mark_partial(self.provider.name, sym, interval, 0)
                except Exception as e:
                    failed += 1
                    errors.append(f"{sym}: {e}")
                    self.tracker.mark_failed(self.provider.name, sym, interval, str(e))
                    log.warning(f"  {sym} failed: {e}")
                time.sleep(self.config.rate_delay)

        # 批处理结束：把累积的进度一次性落盘（update_symbol 仅内存写）
        self.tracker.flush()
        elapsed = time.time() - t0
        log.info(
            f"[{self.provider.name}/{interval}] range 完成: "
            f"{done} 成功, {failed} 失败, {total_rows:,} 行, {elapsed:.0f}s"
        )
        return SyncResult(
            provider=self.provider.name,
            interval=interval,
            mode=mode,
            total_symbols=len(pending),
            done_symbols=done,
            failed_symbols=failed,
            total_rows=total_rows,
            elapsed_seconds=elapsed,
            errors=errors,
        )

    # ── DB 驱动增量辅助 ──────────────────────────────────────────────────────
    @staticmethod
    def _resolve_target_table(
        insert_sql: str, is_daily: bool, is_commodity: bool, is_index: bool,
    ) -> tuple[str, str]:
        """根据 insert_sql / 资产类推断目标表名与日期列名（供 DB 增量查询）。

        Returns:
            (table, date_col)：stock_ohlcv→trade_date、stock_ohlcv_minute→trade_time、
            commodity_ohlcv/index_ohlcv→trade_date。
        """
        if is_index:
            return "index_ohlcv", "trade_date"
        if is_commodity:
            return "commodity_ohlcv", "trade_date"
        if is_daily:
            return "stock_ohlcv", "trade_date"
        return "stock_ohlcv_minute", "trade_time"

    @staticmethod
    def _load_symbol_max_dates(
        db_dsn: str, table: str, date_col: str, symbols: list[str],
    ) -> dict[str, Optional[str]]:
        """一次性 GROUP BY 取 {symbol: MAX(date)::text}。

        单条 SQL 取回全部 symbol 的最新日期（比逐 symbol 查快上万倍）。
        表名/列名为内部常量（非用户输入），无注入风险。
        """
        if not symbols:
            return {}
        out: dict[str, Optional[str]] = {s: None for s in symbols}
        try:
            conn = psycopg2.connect(db_dsn)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f'SELECT symbol, MAX({date_col})::text '
                        f'FROM {table} WHERE symbol = ANY(%s) '
                        f'GROUP BY symbol',
                        (list(symbols),),
                    )
                    for sym, max_d in cur.fetchall():
                        if max_d:
                            # 续拉起点 = 最新日本身（闭区间）。重拉最后一天可覆盖
                            # 上次同步时的盘中/滞后修正，由 upsert 幂等兜底。
                            # 若改成 +1 天，则 MAX(date) 当天的错误数据永不修正。
                            out[sym] = str(max_d)[:10]
            finally:
                conn.close()
        except Exception as e:
            log.warning(f"[DB增量] 取 {table} MAX({date_col}) 失败，退回 start_date: {e}")
        return out

    def _sync_one_range(
        self, db_dsn: str, symbol: str, interval: str,
        start_date: Optional[str], end_date: Optional[str],
        insert_sql: str, is_commodity: bool, is_index: bool,
        asset_class: Optional[str],
    ):
        """按日期范围同步单个标的（每个 worker 自己的连接）。"""
        conn = psycopg2.connect(db_dsn)
        try:
            if is_commodity:
                bars = self.provider.fetch_commodity_daily(symbol, start_date, end_date)
            elif is_index:
                # 申万一级行业指数（sw801010）走 fetch_sw_index_daily，其余大盘指数走 fetch_index_daily
                if isinstance(symbol, str) and symbol.lower().startswith("sw"):
                    bars = self.provider.fetch_sw_index_daily(symbol, start_date, end_date)
                else:
                    bars = self.provider.fetch_index_daily(symbol, start_date, end_date)
            elif interval == "1d":
                bars = self.provider.fetch_daily_range(symbol, start_date, end_date)
            else:
                bars = self.provider.fetch_minute_range(symbol, interval, start_date, end_date)

            if not bars:
                return _SyncResultSingle(symbol=symbol, rows=0)

            rows = self._bars_to_range_rows(bars, interval, is_commodity, is_index, asset_class)
            if not rows:
                return _SyncResultSingle(symbol=symbol, rows=0)

            with conn.cursor() as cur:
                execute_values(cur, insert_sql, rows, page_size=self.config.batch_size)
            conn.commit()

            # 用 max 而非 bars[-1]：provider 返回顺序不保证升序（多个 akshare
            # 接口未排序），bars[-1] 可能取到中间 bar，导致增量起点错位漏数据。
            last_bar_time = max(b.trade_time for b in bars).isoformat() if bars else None
            return _SyncResultSingle(symbol=symbol, rows=len(rows), last_bar_time=last_bar_time)
        finally:
            conn.close()

    @staticmethod
    def _bars_to_range_rows(
        bars: list[OHLCVBar], interval: str, is_commodity: bool,
        is_index: bool, asset_class: Optional[str],
    ) -> list:
        """OHLCVBar → 目标表行元组（stock_ohlcv / stock_ohlcv_minute / commodity_ohlcv / index_ohlcv）。"""
        rows = []
        now = datetime.now()
        for b in bars:
            if is_commodity:
                rows.append((
                    b.symbol, b.trade_time,
                    b.open_, b.close_, b.high_, b.low_,
                    b.volume, b.amount, asset_class or b.market, now,
                ))
            elif is_index:
                rows.append((
                    b.symbol, b.trade_time,
                    b.open_, b.close_, b.high_, b.low_,
                    b.volume, b.amount, b.market, now,
                ))
            elif interval == "1d":
                rows.append((
                    b.symbol, b.trade_time,
                    b.open_, b.close_, b.high_, b.low_,
                    b.volume, b.amount, b.market, now,
                ))
            else:
                rows.append((
                    b.symbol, b.trade_time,
                    b.open_, b.close_, b.high_, b.low_,
                    b.volume, b.amount, b.market, interval, now,
                ))
        return rows

    def _sync_one(
        self, db_dsn: str, symbol: str, interval: str, insert_sql: str, is_daily: bool,
    ):
        """同步单个股票（每个worker用自己的连接）"""
        conn = psycopg2.connect(db_dsn)
        try:
            # 1. 拉取数据
            if is_daily:
                bars = self.provider.fetch_daily(symbol, datalen=3000)
            else:
                bars = self.provider.fetch_minute(symbol, interval=interval, datalen=3000)

            if not bars:
                return _SyncResultSingle(symbol=symbol, rows=0)

            # 2. 转换格式
            rows = self._bars_to_db_rows(bars, is_daily)
            if not rows:
                return _SyncResultSingle(symbol=symbol, rows=0)

            # 3. 写入DB
            with conn.cursor() as cur:
                execute_values(cur, insert_sql, rows, page_size=self.config.batch_size)
            conn.commit()

            # 同 _sync_one_range：bars 不保证升序，取 max 以免增量起点错位。
            last_bar_time = max(b.trade_time for b in bars).isoformat() if bars else None
            return _SyncResultSingle(symbol=symbol, rows=len(rows), last_bar_time=last_bar_time)
        finally:
            conn.close()

    def _bars_to_db_rows(self, bars: list[OHLCVBar], is_daily: bool) -> list:
        """将 OHLCVBar 列表转换为 DB 行元组"""
        rows = []
        for b in bars:
            if is_daily:
                rows.append((
                    b.symbol,
                    b.trade_time,
                    b.open_, b.close_, b.high_, b.low_,
                    b.volume, b.amount, b.market,
                    datetime.now(),
                ))
            else:
                rows.append((
                    b.symbol,
                    b.trade_time,
                    b.open_, b.close_, b.high_, b.low_,
                    b.volume, b.amount, b.market, b.interval,
                    datetime.now(),
                ))
        return rows


@dataclass
class _SyncResultSingle:
    symbol: str
    rows: int
    last_bar_time: Optional[str] = None


@dataclass
class SyncResult:
    """同步结果"""
    provider: str
    interval: str
    mode: str = "full"
    total_symbols: int = 0
    done_symbols: int = 0
    failed_symbols: int = 0
    total_rows: int = 0
    elapsed_seconds: float = 0.0
    errors: list = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    @property
    def success(self) -> bool:
        return self.failed_symbols == 0
