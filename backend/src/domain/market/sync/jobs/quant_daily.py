"""
QuantDailyJob
=============
量化数据每日增量保活（供调度器 / cron 调用）。

设计（重构后）：
  - **拆分**：原单体 run() 拆成 8 个独立函数（a_daily / etf_daily / hk_daily /
    index_daily / sw_index_daily / commodity_metal / commodity_energy / fx），
    调度器为每个注册独立 job，时间错开，单点失败互不影响。
  - **真增量**：工作日走 DB 驱动增量（incremental_from_db=True）—— 按
    MAX(trade_date) 续拉缺口，不再每次重拉全部标的。比旧的 full 滚动窗口快得多，
    且不依赖易损坏的 sync_progress.json。
  - **周末兜底**：weekly_catchup() 以 mode="full" + 近 14 天窗口依次跑 8 个组，
    幂等补节假日/滞后缺口。
  - **一键全跑**：run() 顺序调用 8 个子函数，供手动 `python -m ...` 验证。

分钟线在东财网络修复前跳过（MINUTE_ENABLED=False）。

调用：
  python -m src.domain.market.sync.jobs.quant_daily            # 一键全跑（full 滚动窗口）
  python -m src.domain.market.sync.jobs.quant_daily --incremental   # 一键增量
"""
import logging
import socket
import sys
from datetime import date, timedelta
from pathlib import Path

# 全局 socket 超时兜底，防止 akshare 请求挂死（见 full_sync.py 注释）
socket.setdefaulttimeout(60)

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent  # backend/
sys.path.insert(0, str(_BACKEND))

from conf import app_config  # noqa: E402
from src.domain.market.sync import ProgressTracker, SyncService  # noqa: E402
from src.domain.market.sync.jobs.full_sync import (  # noqa: E402
    _db_a_list, _db_hk_list, _get_dsn, _ensure_schema,
)
from src.domain.market.sync.providers.akshare_provider import AkshareProvider  # noqa: E402
from src.domain.market.sync.sync_service import (  # noqa: E402
    COMMODITY_INSERT_SQL,
    INDEX_INSERT_SQL,
    SyncConfig,
)

log = logging.getLogger("quant_daily")

# 分钟线在东财网络修复前跳过
MINUTE_ENABLED = False

# 工作日增量窗口的兜底起点：DB 无记录的 symbol 用此（近 30 天，覆盖长假缺口）
FALLBACK_DAYS = 30
# 周末兜底全量窗口
CATCHUP_DAYS = 14


def _build_service(workers: int = 6) -> SyncService:
    provider = AkshareProvider()
    tracker = ProgressTracker()
    config = SyncConfig(max_workers=workers, rate_delay=0.05, db_dsn=_get_dsn())
    return SyncService(provider, tracker, config)


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _today() -> str:
    return date.today().isoformat()


# ── 8 个独立同步函数（每个自建 service、各自 try/except、互不影响）──────────────
# 工作日增量用 incremental_from_db=True（DB 驱动）；周末兜底用 mode="full" 滚动窗口。
# 所有 job 内部都先 _ensure_schema()（幂等），保证表/约束就绪。


def _symbols_for(group: str) -> list[str]:
    """取某资产类的标的清单。集中一处，供增量/全量复用。"""
    qu = app_config.quant_universe
    if group == "a":
        return _db_a_list()
    if group == "etf":
        return _build_service().provider.get_etf_list()
    if group == "hk":
        return _db_hk_list() + [e.symbol for e in qu.hk_etf_symbols]
    if group == "index":
        return [i.symbol for i in qu.indices]
    if group == "sw_index":
        return [f"sw{i.symbol}" for i in qu.sw_industries]
    if group == "metal":
        return qu.commodities.get("metals", [])
    if group == "energy":
        return qu.commodities.get("energy", [])
    return []


def sync_a_daily(incremental: bool = True) -> dict:
    """A 股日线增量。"""
    _ensure_schema()
    svc = _build_service()
    syms = _symbols_for("a")
    start = _days_ago(FALLBACK_DAYS) if incremental else _days_ago(7)
    r = svc.backfill_range(
        syms, "1d", start, _today(),
        mode="full", incremental_from_db=incremental,
    )
    return {"a_daily": _result_dict(r)}


def sync_etf_daily(incremental: bool = True) -> dict:
    """A 股 ETF 日线增量。"""
    _ensure_schema()
    svc = _build_service()
    syms = _symbols_for("etf")
    start = _days_ago(FALLBACK_DAYS) if incremental else _days_ago(7)
    r = svc.backfill_range(
        syms, "1d", start, _today(),
        mode="full", incremental_from_db=incremental,
    )
    return {"etf_daily": _result_dict(r)}


def sync_hk_daily(incremental: bool = True) -> dict:
    """H 股 + H 股 ETF 日线增量。"""
    _ensure_schema()
    svc = _build_service()
    syms = _symbols_for("hk")
    start = _days_ago(FALLBACK_DAYS) if incremental else _days_ago(7)
    r = svc.backfill_range(
        syms, "1d", start, _today(),
        mode="full", incremental_from_db=incremental,
    )
    return {"hk_daily": _result_dict(r)}


def sync_index_daily(incremental: bool = True) -> dict:
    """大盘指数日线增量（新浪源，存 index_ohlcv）。"""
    _ensure_schema()
    svc = _build_service()
    syms = _symbols_for("index")
    if not syms:
        return {"index_daily": {"rows": 0}}
    start = _days_ago(FALLBACK_DAYS) if incremental else _days_ago(7)
    r = svc.backfill_range(
        syms, "1d", start, _today(),
        insert_sql=INDEX_INSERT_SQL, is_index=True,
        mode="full", incremental_from_db=incremental,
    )
    return {"index_daily": _result_dict(r)}


def sync_sw_index_daily(incremental: bool = True) -> dict:
    """申万一级行业指数增量（swsresearch.com，存 sw801010）。"""
    _ensure_schema()
    svc = _build_service()
    syms = _symbols_for("sw_index")
    if not syms:
        return {"sw_index_daily": {"rows": 0}}
    start = _days_ago(FALLBACK_DAYS) if incremental else _days_ago(7)
    r = svc.backfill_range(
        syms, "1d", start, _today(),
        insert_sql=INDEX_INSERT_SQL, is_index=True,
        mode="full", incremental_from_db=incremental,
    )
    return {"sw_index_daily": _result_dict(r)}


def sync_commodity_metal(incremental: bool = True) -> dict:
    """贵金属日线增量（commodity_ohlcv, asset_class=metal）。"""
    _ensure_schema()
    svc = _build_service()
    syms = _symbols_for("metal")
    if not syms:
        return {"commodity_metal": {"rows": 0}}
    start = _days_ago(FALLBACK_DAYS) if incremental else _days_ago(10)
    r = svc.backfill_range(
        syms, "1d", start, _today(),
        insert_sql=COMMODITY_INSERT_SQL, asset_class="metal",
        mode="full", incremental_from_db=incremental,
    )
    return {"commodity_metal": _result_dict(r)}


def sync_commodity_energy(incremental: bool = True) -> dict:
    """原油日线增量（commodity_ohlcv, asset_class=energy）。"""
    _ensure_schema()
    svc = _build_service()
    syms = _symbols_for("energy")
    if not syms:
        return {"commodity_energy": {"rows": 0}}
    start = _days_ago(FALLBACK_DAYS) if incremental else _days_ago(10)
    r = svc.backfill_range(
        syms, "1d", start, _today(),
        insert_sql=COMMODITY_INSERT_SQL, asset_class="energy",
        mode="full", incremental_from_db=incremental,
    )
    return {"commodity_energy": _result_dict(r)}


def sync_fx(incremental: bool = True) -> dict:
    """货币对日线（走 FxRateRepository，量小无需线程池）。

    增量：按 repo.get_latest_date(pair) 续拉；全量：近 FALLBACK_DAYS 天。
    """
    from src.infra.database.market.fx_rate import create_fx_rate_repository

    svc = _build_service()
    qu = app_config.quant_universe
    repo = create_fx_rate_repository()
    fallback_start = _days_ago(FALLBACK_DAYS)
    full_start = _days_ago(10)
    fx_rows = 0
    for pair in qu.fx_pairs:
        try:
            if incremental:
                latest = repo.get_latest_date(pair)
                # 闭区间重拉最后一天，覆盖上次同步的滞后修正（upsert 幂等兜底）；
                # 与 _load_symbol_max_dates 的 DB 增量起点保持一致。
                start = latest.isoformat() if latest else fallback_start
            else:
                start = full_start
            bars = svc.provider.fetch_fx_ohlc(pair, start, _today())
            for b in bars:
                repo.upsert(b.trade_time.date(), pair, b.close_, b.open_, b.high_, b.low_)
            fx_rows += len(bars)
        except Exception as e:
            log.error(f"[fx] {pair} 失败: {e}")
    log.info(f"[fx] +{fx_rows} rows, {len(qu.fx_pairs)} pairs")
    return {"fx": {"rows": fx_rows, "pairs": len(qu.fx_pairs)}}


# ── 调度映射：job_id → (函数, 是否增量) ──────────────────────────────────────
# 调度器按 job_id 取此表调用，单 job 失败不影响其它。
SPLIT_JOBS: dict[str, callable] = {
    "quant_a_daily": sync_a_daily,
    "quant_etf_daily": sync_etf_daily,
    "quant_hk_daily": sync_hk_daily,
    "quant_index_daily": sync_index_daily,
    "quant_sw_index_daily": sync_sw_index_daily,
    "quant_commodity_metal": sync_commodity_metal,
    "quant_commodity_energy": sync_commodity_energy,
    "quant_fx": sync_fx,
}


def run_split(job_id: str, incremental: bool = True) -> dict:
    """调度器入口：跑单个拆分 job。失败抛出由调度器 wrapper 兜底记日志。"""
    fn = SPLIT_JOBS.get(job_id)
    if not fn:
        raise ValueError(f"未知 quant job_id: {job_id}")
    return fn(incremental=incremental)


def weekly_catchup() -> dict:
    """周末兜底全量：近 14 天窗口依次跑 8 个组，幂等补缺口。"""
    results: dict = {}
    for job_id, fn in SPLIT_JOBS.items():
        try:
            results.update(fn(incremental=False))
        except Exception as e:
            log.error(f"[catchup] {job_id} 失败: {e}")
            results[job_id] = {"error": str(e)}
    total = sum(r.get("rows", 0) if isinstance(r, dict) else 0 for r in results.values())
    log.info(f"weekly_catchup 完成：合计 +{total} 行")
    return results


def run(incremental: bool = False) -> dict:
    """一键全跑（手动验证用）。incremental=False 走 full 滚动窗口。"""
    _ensure_schema()
    results: dict = {}
    for job_id, fn in SPLIT_JOBS.items():
        try:
            results.update(fn(incremental=incremental))
        except Exception as e:
            log.error(f"[{job_id}] 失败: {e}")
            results[job_id] = {"error": str(e)}

    # 分钟线（东财修复后启用）
    if MINUTE_ENABLED:
        svc = _build_service()
        a = _db_a_list()
        hk = _db_hk_list() + [e.symbol for e in app_config.quant_universe.hk_etf_symbols]
        m_start = _days_ago(int(365 * app_config.quant_universe.minute_years))
        for iv in app_config.quant_universe.minute_intervals:
            results[f"a_minute_{iv}"] = _result_dict(
                svc.backfill_range(a, iv, m_start, _today(), mode="full")
            )
            results[f"hk_minute_{iv}"] = _result_dict(
                svc.backfill_range(hk, iv, m_start, _today(), mode="full")
            )
    else:
        log.info("分钟线跳过（东财网络未修复，MINUTE_ENABLED=False）")

    total = sum(
        r.get("rows", 0) if isinstance(r, dict) else getattr(r, "total_rows", 0)
        for r in results.values()
    )
    log.info(f"quant_daily 完成：合计 +{total} 行")
    return results


def _result_dict(r) -> dict:
    """SyncResult → 轻量 dict（供日志/汇总，避免序列化整个对象）。"""
    if hasattr(r, "total_rows"):
        return {
            "rows": r.total_rows,
            "done": r.done_symbols,
            "failed": r.failed_symbols,
            "errors": r.errors[:5] if r.errors else [],
        }
    return r if isinstance(r, dict) else {"rows": 0}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="量化数据每日同步")
    parser.add_argument(
        "--incremental", action="store_true",
        help="增量模式（DB 驱动，工作日用）；默认 full 滚动窗口",
    )
    args = parser.parse_args()

    (_BACKEND / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(_BACKEND / "logs" / "quant_daily.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    run(incremental=args.incremental)


if __name__ == "__main__":
    main()
