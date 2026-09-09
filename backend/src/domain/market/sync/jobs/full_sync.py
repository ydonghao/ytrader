"""
FullSyncJob
===========
全量回填编排任务：A/H 股 + ETF 日线（10y）、A/H 股分钟线（2y）、
贵金属/原油/货币日线（3y）。统一走 akshare（支持服务端/客户端日期切片）。

用法：
  # 全量（耗时极长，分钟线可能数天）
  python -m src.domain.market.sync.jobs.full_sync

  # 只跑日线子集（验证）
  python -m src.domain.market.sync.jobs.full_sync --steps a_daily,etf_daily,hk_daily

  # 分批跑分钟线
  python -m src.domain.market.sync.jobs.full_sync --steps a_minute --workers 12

步骤可选：a_daily etf_daily hk_daily a_minute hk_minute commodity fx
"""
import argparse
import logging
import socket
import sys
from datetime import date, timedelta
from pathlib import Path

# 全局 socket 超时：akshare 内部 requests 不设 timeout，碰到慢/空响应会无限等待
# 把整个线程池拖死。设 60s 兜底，让挂死的连接快速失败、worker 跳过继续。
socket.setdefaulttimeout(60)

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent  # backend/
sys.path.insert(0, str(_BACKEND))

import psycopg2  # noqa: E402

from conf import app_config  # noqa: E402
from src.domain.market.sync import ProgressTracker, SyncService  # noqa: E402
from src.domain.market.sync.providers.akshare_provider import AkshareProvider  # noqa: E402
from src.domain.market.sync.sync_service import (  # noqa: E402
    COMMODITY_INSERT_SQL,
    INDEX_INSERT_SQL,
    SyncConfig,
    SyncResult,
)

log = logging.getLogger("full_sync")

ALL_STEPS = [
    "a_daily", "etf_daily", "hk_daily",
    "a_minute", "hk_minute",
    "commodity", "fx", "index",
]


# ── 基础组件 ──────────────────────────────────────────────────────────────
def _get_dsn() -> str:
    from src.domain.market.sync.jobs.daily import _get_dsn as _g
    return _g()


def _build_service(workers: int) -> SyncService:
    provider = AkshareProvider()
    tracker = ProgressTracker()
    config = SyncConfig(max_workers=workers, rate_delay=0.05, db_dsn=_get_dsn())
    return SyncService(provider, tracker, config)


def _build_sina_service(workers: int) -> SyncService:
    """Sina 数据源 service：用于 A 股分钟线（datalen=3000，覆盖 60m~3y/30m~1.5y/15m~9mo/5m~3mo）。
    Sina 有 456 日配额限速，故 workers 保守、rate_delay 较大。"""
    from src.domain.market.sync.providers.sina_provider import SinaProvider
    provider = SinaProvider(rate_delay=0.5)
    tracker = ProgressTracker()
    config = SyncConfig(max_workers=workers, rate_delay=0.5, db_dsn=_get_dsn())
    return SyncService(provider, tracker, config)


def _ensure_schema() -> None:
    """幂等执行 quant_schema.sql（建表 / OHLC 列 / hypertable）。"""
    sql_path = _BACKEND / "scripts" / "quant_schema.sql"
    if not sql_path.exists():
        log.warning("quant_schema.sql 不存在，跳过 schema 初始化")
        return
    sql = sql_path.read_text(encoding="utf-8")
    with psycopg2.connect(_get_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    log.info("schema 就绪")


def _dedup_ohlcv() -> None:
    """防御性去重。**仅当唯一约束缺失时**才扫表去重（保 created_at 最新一条）；
    有 pkey 时 pkey 已保证无重复，直接跳过，避免在压缩 hypertable 上做昂贵全表扫描。
    防重复的真正保障是：① 唯一约束（_ensure_schema 建）② INSERT ON CONFLICT DO UPDATE。"""
    dsn = _get_dsn()
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            # contype: 'p'=主键, 'u'=唯一约束；两者都保证无重复
            cur.execute("""
                SELECT con.contype FROM pg_constraint con
                WHERE con.conrelid = 'stock_ohlcv'::regclass AND con.contype IN ('u','p')
                LIMIT 1
            """)
            has_daily_uq = cur.fetchone() is not None
            cur.execute("""
                SELECT con.contype FROM pg_constraint con
                WHERE con.conrelid = 'stock_ohlcv_minute'::regclass AND con.contype IN ('u','p')
                LIMIT 1
            """)
            has_min_uq = cur.fetchone() is not None
            if has_daily_uq and has_min_uq:
                log.info("去重检查：两表唯一约束均在，pkey 已保证无重复，跳过全表扫描")
                return
            # 仅对缺约束的表去重（建约束前可能有历史重复）
            if not has_daily_uq:
                cur.execute("""
                    DELETE FROM stock_ohlcv a USING stock_ohlcv b
                    WHERE a.trade_date=b.trade_date AND a.symbol=b.symbol
                      AND a.ctid<b.ctid
                      AND (a.created_at IS NULL OR b.created_at IS NULL
                           OR a.created_at<b.created_at)
                """)
                log.info(f"日线去重：删 {cur.rowcount} 行残留重复")
            if not has_min_uq:
                cur.execute("""
                    DELETE FROM stock_ohlcv_minute a USING stock_ohlcv_minute b
                    WHERE a.trade_time=b.trade_time AND a.symbol=b.symbol
                      AND a."interval"=b."interval" AND a.ctid<b.ctid
                      AND (a.created_at IS NULL OR b.created_at IS NULL
                           OR a.created_at<b.created_at)
                """)
                log.info(f"分钟线去重：删 {cur.rowcount} 行残留重复")
        conn.commit()


# ── 标的清单（优先 DB，快且稳；spot 爬取慢且不稳）─────────────────────────
def _db_a_list() -> list[str]:
    """A 股清单从 stock_info 表读（已含 sh/sz/bj，~5500 只）。"""
    with psycopg2.connect(_get_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol FROM stock_info WHERE market='A' ORDER BY symbol")
            return [r[0] for r in cur.fetchall()]


def _db_hk_list() -> list[str]:
    """H 股清单从 stock_ohlcv 表读已存在的 distinct symbol（~3200 只）。"""
    with psycopg2.connect(_get_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT symbol FROM stock_ohlcv WHERE market='HK' ORDER BY symbol"
            )
            return [r[0] for r in cur.fetchall()]


# ── 日期窗口 ──────────────────────────────────────────────────────────────
def _years_ago(years: int) -> str:
    return (date.today() - timedelta(days=365 * years)).isoformat()


def _today() -> str:
    return date.today().isoformat()


# ── 各步骤 ────────────────────────────────────────────────────────────────
def step_a_daily(service: SyncService) -> SyncResult:
    symbols = _db_a_list()
    log.info(f"[a_daily] A 股 {len(symbols)} 只（来自 stock_info）")
    return service.backfill_range(
        symbols=symbols, interval="1d",
        start_date=_years_ago(app_config.quant_universe.daily_years),
        end_date=_today(), mode="resume",
    )


def step_etf_daily(service: SyncService) -> SyncResult:
    symbols = service.provider.get_etf_list()
    log.info(f"[etf_daily] A 股 ETF {len(symbols)} 只（fund_etf_category_sina）")
    return service.backfill_range(
        symbols=symbols, interval="1d",
        start_date=_years_ago(app_config.quant_universe.daily_years),
        end_date=_today(), mode="resume",
    )


def step_hk_daily(service: SyncService) -> SyncResult:
    stocks = _db_hk_list()
    etfs = [e.symbol for e in app_config.quant_universe.hk_etf_symbols]
    symbols = stocks + etfs
    log.info(f"[hk_daily] H 股 {len(stocks)}（来自 stock_ohlcv）+ ETF {len(etfs)}")
    return service.backfill_range(
        symbols=symbols, interval="1d",
        start_date=_years_ago(app_config.quant_universe.daily_years),
        end_date=_today(), mode="resume",
    )


def step_a_minute(service: SyncService) -> list[SyncResult]:
    """A 股分钟线，走 Sina（datalen=3000，覆盖 60m~3y/30m~1.5y/15m~9mo/5m~3mo）。
    东财免费仅 ~1 月，Sina 历史更长，故分钟线用 Sina。start/end 仅记录，Sina 按 datalen 取。"""
    sina = _build_sina_service(workers=min(service.config.max_workers, 4))
    symbols = _db_a_list()
    start = _years_ago(app_config.quant_universe.minute_years)
    end = _today()
    results = []
    for iv in app_config.quant_universe.minute_intervals:
        log.info(f"[a_minute/{iv}] A 股 {len(symbols)} 只 (Sina datalen=3000), 窗口标称 {start}~{end}")
        results.append(sina.backfill_range(
            symbols=symbols, interval=iv,
            start_date=start, end_date=end, mode="full",
        ))
    return results


def step_hk_minute(service: SyncService) -> list[SyncResult]:
    """H 股分钟线：Sina getKLineData 不支持港股（实测返回空），东财免费仅 ~1 月且 flapping。
    无免费 2y 路径，跳过。需要时可用 tushare pro（HK 分钟需 2000+ 积分）。"""
    log.warning(
        "[hk_minute] 跳过：Sina 不支持港股分钟线，东财免费仅 ~1 月且 flapping。"
        "H 股 2y 分钟线需 tushare pro（付费档）。"
    )
    return [SyncResult(provider="sina", interval="1d")]


def step_commodity(service: SyncService) -> SyncResult:
    qu = app_config.quant_universe
    start = _years_ago(qu.commodity_years)
    end = _today()
    metals = qu.commodities.get("metals", [])
    energy = qu.commodities.get("energy", [])
    log.info(f"[commodity] metals={metals} energy={energy}, {start}~{end}")

    # metals 与 energy 分别写（asset_class 不同）
    r1 = service.backfill_range(
        symbols=metals, interval="1d", start_date=start, end_date=end,
        insert_sql=COMMODITY_INSERT_SQL, asset_class="metal", mode="resume",
    ) if metals else SyncResult(provider="akshare", interval="1d")
    r2 = service.backfill_range(
        symbols=energy, interval="1d", start_date=start, end_date=end,
        insert_sql=COMMODITY_INSERT_SQL, asset_class="energy", mode="resume",
    ) if energy else SyncResult(provider="akshare", interval="1d")
    return SyncResult(
        provider="akshare", interval="1d",
        total_symbols=r1.total_symbols + r2.total_symbols,
        done_symbols=r1.done_symbols + r2.done_symbols,
        failed_symbols=r1.failed_symbols + r2.failed_symbols,
        total_rows=r1.total_rows + r2.total_rows,
        errors=r1.errors + r2.errors,
    )


def step_fx(service: SyncService) -> SyncResult:
    """货币 OHLC → fx_rate（走 FxRateRepository，量小无需线程池）。"""
    from src.infra.database.market.fx_rate import create_fx_rate_repository

    qu = app_config.quant_universe
    start = _years_ago(qu.commodity_years)
    end = _today()
    repo = create_fx_rate_repository()
    total_rows = 0
    done = 0
    errors: list[str] = []
    for pair in qu.fx_pairs:
        try:
            bars = service.provider.fetch_fx_ohlc(pair, start, end)
            if not bars:
                log.warning(f"[fx] {pair} 无数据")
                continue
            for b in bars:
                repo.upsert(
                    date_=b.trade_time.date(), pair=pair, rate=b.close_,
                    open_=b.open_, high_=b.high_, low_=b.low_,
                )
            total_rows += len(bars)
            done += 1
            log.info(f"[fx] {pair} +{len(bars)} rows")
        except Exception as e:
            errors.append(f"{pair}: {e}")
            log.warning(f"[fx] {pair} failed: {e}")
    return SyncResult(
        provider="akshare", interval="1d", total_symbols=len(qu.fx_pairs),
        done_symbols=done, total_rows=total_rows, errors=errors,
    )


def step_index(service: SyncService) -> SyncResult:
    """大盘指数 + 申万一级行业指数 → index_ohlcv（is_index=True，自动查 INDEX_INSERT_SQL）。
    大盘走 fetch_index_daily（Sina），行业走 fetch_sw_index_daily（swsresearch.com）。"""
    qu = app_config.quant_universe
    start = _years_ago(qu.daily_years)
    end = _today()
    market_idx = [i.symbol for i in qu.indices]
    sw_idx = [f"sw{i.symbol}" for i in qu.sw_industries]  # 加 sw 前缀，触发 fetch_sw_index_daily
    log.info(f"[index] 大盘 {len(market_idx)} + 行业 {len(sw_idx)}, {start}~{end}")

    r1 = service.backfill_range(
        symbols=market_idx, interval="1d", start_date=start, end_date=end,
        is_index=True, mode="resume",
    ) if market_idx else SyncResult(provider="akshare", interval="1d")
    r2 = service.backfill_range(
        symbols=sw_idx, interval="1d", start_date=start, end_date=end,
        is_index=True, mode="resume",
    ) if sw_idx else SyncResult(provider="akshare", interval="1d")
    return SyncResult(
        provider="akshare", interval="1d",
        total_symbols=r1.total_symbols + r2.total_symbols,
        done_symbols=r1.done_symbols + r2.done_symbols,
        failed_symbols=r1.failed_symbols + r2.failed_symbols,
        total_rows=r1.total_rows + r2.total_rows,
        errors=r1.errors + r2.errors,
    )


# ── 编排 ──────────────────────────────────────────────────────────────────
_STEP_FUNCS = {
    "a_daily": step_a_daily,
    "etf_daily": step_etf_daily,
    "hk_daily": step_hk_daily,
    "a_minute": step_a_minute,
    "hk_minute": step_hk_minute,
    "commodity": step_commodity,
    "fx": step_fx,
    "index": step_index,
}


def run(steps: list[str] = None, workers: int = 8) -> dict:
    steps = steps or ALL_STEPS
    _ensure_schema()
    _dedup_ohlcv()                       # 重同步前清残留重复，保证 upsert 语义干净
    service = _build_service(workers)

    results: dict = {}
    for step in steps:
        if step not in _STEP_FUNCS:
            log.warning(f"未知步骤: {step}，跳过")
            continue
        log.info(f"===== 开始 {step} =====")
        try:
            r = _STEP_FUNCS[step](service)
            results[step] = r
        except Exception as e:
            log.error(f"[{step}] 失败: {e}", exc_info=True)
            results[step] = SyncResult(provider="akshare", interval="1d", errors=[str(e)])
        log.info(f"===== 完成 {step} =====")
    return results


def main():
    parser = argparse.ArgumentParser(description="全量回填编排")
    parser.add_argument(
        "--steps", default=",".join(ALL_STEPS),
        help=f"步骤，逗号分隔。可选: {','.join(ALL_STEPS)}",
    )
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    (_BACKEND / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(
                _BACKEND / "logs" / "full_sync.log", encoding="utf-8",
            ),
            logging.StreamHandler(sys.stdout),
        ],
    )

    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    run(steps=steps, workers=args.workers)


if __name__ == "__main__":
    main()
