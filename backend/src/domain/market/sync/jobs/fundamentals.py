"""
FundamentalsJob
===============
基本面数据同步任务（供 cron 调用）。

功能：
  - 拉取 A 股个股估值历史（PE/PB/PS/股息率/总市值）→ stock_valuation
  - 拉取 A 股个股财务指标历史（ROE 等）          → stock_financials
  - 幂等 upsert，增量跳过（库里近 N 天有数据的跳过）
  - 进度持久化（ProgressTracker，支持断点续传）
  - 限流退避（连续空返回时整体 sleep）
  - 剔除 ST/*ST（污染价值/红利排名）
  - 数据源：akshare（stock_value_em / stock_financial_analysis_indicator）

使用（crontab 示例，每周末低峰跑一次）：
  0 3 * * 6 cd /path/to/backend && python -m src.domain.market.sync.jobs.fundamentals >> logs/fundamentals_sync.log 2>&1
"""
import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

_BACKEND = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync.progress import ProgressTracker, SyncStatus
from src.domain.market.sync.providers.akshare_provider import AkshareProvider
from src.infra.database.market.financials import (
    create_stock_financials_repository,
)
from src.infra.database.market.valuation import (
    create_stock_valuation_repository,
)
from src.infra.database.market.dividend import (
    create_stock_dividend_repository,
)
from src.domain.market.fundamental.dividend_yield import (
    ttm_dividend_per_share,
    dividend_yield_ttm,
)

log = logging.getLogger("fundamentals_sync")

# 增量跳过阈值（天）：库里最新数据距今小于此值则跳过。
# 设 7 天：周末/节假日（3天）+ 一周缓冲，避免假期刚过又被重拉全量。
SKIP_RECENT_DAYS = 7
# 限流退避：连续 N 个空返回后整体 sleep
RATE_LIMIT_EMPTY_STREAK = 8
RATE_LIMIT_BACKOFF_SEC = 30

PROVIDER = "akshare"


def _row_date(d) -> date:
    """把 trade_date/report_date 字段统一转 date（可能是 datetime/date/字符串）。"""
    if d is None:
        return date.min
    if hasattr(d, "date"):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        try:
            return datetime.strptime(d[:10], "%Y-%m-%d").date()
        except ValueError:
            return date.min
    return date.min


def _db_a_list_filtered() -> list[str]:
    """
    从 stock_info 表读沪深A股，剔除 ST/*ST。
    失败时降级用 get_a_stock_list 并按 bj 前缀过滤北交所。
    """
    try:
        import psycopg2
        from src.infra.database.sql_engine.dsn import get_dsn
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol FROM stock_info
                    WHERE market = 'A'
                      AND name NOT LIKE 'ST%'
                      AND name NOT LIKE '*ST%'
                      AND symbol NOT LIKE 'bj%'
                    ORDER BY symbol
                """)
                rows = cur.fetchall()
                syms = [r[0] for r in rows]
                if syms:
                    return syms
                log.warning("stock_info 查询为空，降级用 get_a_stock_list")
        finally:
            conn.close()
    except Exception as e:
        log.warning(f"读 stock_info 失败({e})，降级用 get_a_stock_list")
    # 降级
    provider = AkshareProvider()
    all_syms = provider.get_a_stock_list()
    return [s for s in all_syms if not s.lower().startswith("bj")]


# 全局缓存：从 stock_info 读 (symbol -> name)，用于 name 判断是否基金
_SYMBOL_NAME_CACHE: dict[str, str] = {}


def _load_symbol_names():
    """懒加载 symbol->name 映射（只查一次 DB）。"""
    global _SYMBOL_NAME_CACHE
    if _SYMBOL_NAME_CACHE:
        return
    try:
        import psycopg2
        from src.infra.database.sql_engine.dsn import get_dsn
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT symbol, name FROM stock_info WHERE market='A'")
                _SYMBOL_NAME_CACHE = {r[0]: r[1] for r in cur.fetchall()}
        finally:
            conn.close()
    except Exception:
        pass


def _is_etf_or_fund(symbol: str) -> bool:
    """
    判断是否为 ETF/基金（无个股估值数据，跳过 stock_value_em）。
    优先用 stock_info 的 name 判断（最可靠），name 含 ETF/LOF/基金 视为基金。
    无 name 信息时回退到代码号段判断。
    """
    _load_symbol_names()
    name = _SYMBOL_NAME_CACHE.get(symbol, "")
    if name:
        n = name.upper()
        if "ETF" in n or "LOF" in n or "基金" in name:
            return True
        return False
    # 无 name 回退：代码号段
    s = symbol.lower()
    if not (s.startswith("sh") or s.startswith("sz")) or len(s) != 8:
        return False
    head3 = s[2:5]
    if s.startswith("sh") and head3[:2] in ("51", "52", "53", "56", "58"):
        return True
    if s.startswith("sz") and head3 in ("159", "150", "184"):
        return True
    return False


def _sync_symbol_valuation(
    provider: AkshareProvider, symbol: str, tracker: ProgressTracker
) -> tuple[str, int, bool]:
    """
    同步单只股票估值。
    返回 (symbol, 写入条数, 是否异常)。

    is_error=True 仅在真异常（限流/网络）时；ETF/无数据票返回 False。
    """
    val_repo = create_stock_valuation_repository()
    try:
        # ETF/基金无个股估值数据，跳过
        if _is_etf_or_fund(symbol):
            return symbol, 0, False
        # 增量跳过：库里有近 N 天数据，直接跳过
        latest = val_repo.get_latest_date(symbol)
        if latest and (date.today() - latest).days < SKIP_RECENT_DAYS:
            return symbol, 0, False
        # 拉 + 转换（fetch_valuation 内部已处理空/异常，返回 list）
        rows = provider.fetch_valuation(symbol)
        if not rows:
            # akshare 真返回空（次新/退市/接口对该票无数据）—— 非限流
            tracker.mark_partial(PROVIDER, symbol, "valuation", 0)
            return symbol, 0, False
        # 客户端 diff：只写 trade_date > latest 的行
        to_write = rows
        if latest:
            to_write = [r for r in rows if _row_date(r.get("trade_date")) > latest]
        if not to_write:
            tracker.mark_done(
                PROVIDER, symbol, "valuation",
                datetime.now().isoformat(), 0,
            )
            return symbol, 0, False
        for r in to_write:
            r["symbol"] = symbol
        n = val_repo.bulk_upsert(to_write)
        tracker.mark_done(
            PROVIDER, symbol, "valuation",
            datetime.now().isoformat(), n,
        )
        return symbol, n, False
    except Exception as e:  # noqa: BLE001
        tracker.mark_failed(PROVIDER, symbol, "valuation", str(e)[:200])
        log.warning(f"[valuation] {symbol} 异常: {e}")
        return symbol, 0, True


def _sync_symbol_financials(
    provider: AkshareProvider, symbol: str, tracker: ProgressTracker
) -> tuple[str, int, bool]:
    """同步单只股票财务指标。同样区分真异常 vs 空数据。"""
    fin_repo = create_stock_financials_repository()
    try:
        # ETF/基金无财务数据，跳过
        if _is_etf_or_fund(symbol):
            return symbol, 0, False
        latest = fin_repo.get_latest_report_date(symbol)
        if latest and (date.today() - latest).days < SKIP_RECENT_DAYS:
            return symbol, 0, False
        rows = provider.fetch_financials(symbol)
        if not rows:
            tracker.mark_partial(PROVIDER, symbol, "financials", 0)
            return symbol, 0, False  # 真空，非异常
        to_write = rows
        if latest:
            to_write = [r for r in rows if _row_date(r.get("report_date")) > latest]
        if not to_write:
            tracker.mark_done(
                PROVIDER, symbol, "financials",
                datetime.now().isoformat(), 0,
            )
            return symbol, 0, False
        for r in to_write:
            r["symbol"] = symbol
        n = fin_repo.bulk_upsert(to_write)
        tracker.mark_done(
            PROVIDER, symbol, "financials",
            datetime.now().isoformat(), n,
        )
        return symbol, n, False
    except Exception as e:  # noqa: BLE001
        tracker.mark_failed(PROVIDER, symbol, "financials", str(e)[:200])
        log.warning(f"[financials] {symbol} 异常: {e}")
        return symbol, 0, True


def _sync_symbol_dividend(
    provider: AkshareProvider, symbol: str, tracker: ProgressTracker
) -> tuple[str, int, bool]:
    """
    同步单只股票分红明细，并回写最新交易日的 TTM 股息率到
    stock_valuation。

    流程：
      1. 拉分红明细 → stock_dividend（幂等覆盖）
      2. 近一年有现金分红：取最新收盘价 → 算 TTM 股息率 →
         update stock_valuation 最新记录的 dv_ratio/dv_ttm
      3. 近一年无分红：跳过（dv 保持 None，红利选股自然走质量/PB）

    返回 (symbol, 写入明细条数, 是否异常)。
    """
    div_repo = create_stock_dividend_repository()
    val_repo = create_stock_valuation_repository()
    try:
        if _is_etf_or_fund(symbol):
            return symbol, 0, False
        rows = provider.fetch_dividend_detail(symbol)
        if not rows:
            tracker.mark_partial(PROVIDER, symbol, "dividend", 0)
            return symbol, 0, False
        n = div_repo.bulk_upsert(
            [{**r, "symbol": symbol} for r in rows]
        )
        tracker.mark_done(
            PROVIDER, symbol, "dividend",
            datetime.now().isoformat(), n,
        )

        # 回填最新交易日 TTM 股息率
        latest_date = val_repo.get_latest_date(symbol)
        if latest_date is None:
            return symbol, n, False  # 无估值数据，无法锚定交易日
        div_rows = div_repo.get_history(symbol, end=latest_date)
        dividends = [
            {"ex_date": d.ex_date, "div_per_share": d.div_per_share}
            for d in div_rows
        ]
        ttm_dps = ttm_dividend_per_share(dividends, latest_date)
        if ttm_dps is None or ttm_dps <= 0:
            return symbol, n, False  # 近一年无现金分红
        # 取最近 ~13 个月收盘价（够算 TTM，避免拉全量 10 年）
        start = latest_date - timedelta(days=400)
        bars = provider.fetch_a_stock_daily(
            symbol, start_date=start.strftime("%Y%m%d")
        )
        price = bars[-1].close_ if bars else None
        dv = dividend_yield_ttm(dividends, price, latest_date)
        if dv is not None:
            val_repo.update_dividend_yield(
                symbol, latest_date, dv_ratio=dv, dv_ttm=dv
            )
        return symbol, n, False
    except Exception as e:  # noqa: BLE001
        tracker.mark_failed(PROVIDER, symbol, "dividend", str(e)[:200])
        log.warning(f"[dividend] {symbol} 异常: {e}")
        return symbol, 0, True


def run(
    symbols: list[str] | None = None,
    max_workers: int = 6,
    rate_delay: float = 0.2,
    valuation: bool = True,
    financials: bool = True,
    dividend: bool = True,
    resume: bool = True,
) -> dict:
    """
    执行基本面同步。

    Args:
        symbols:    股票池（带前缀 sh/sz），为空则拉沪深A股（剔除ST）
        max_workers: 并发数（默认 6，akshare 限流明显，建议 4-8）
        rate_delay: 每个请求后等待秒数
        valuation:  是否同步估值
        financials: 是否同步财务指标
        dividend:   是否同步分红明细（并回写 TTM 股息率）
        resume:     是否断点续传（跳过已完成的 symbol）
    """
    provider = AkshareProvider()
    tracker = ProgressTracker()

    if not symbols:
        log.info("读取沪深A股列表（剔除ST）...")
        symbols = _db_a_list_filtered()
        log.info(f"股票列表: {len(symbols)} 只")
    else:
        # 用户显式指定的不剔 ST
        log.info(f"使用指定股票池: {len(symbols)} 只")

    if not symbols:
        log.warning("股票列表为空，跳过")
        return {"symbols": 0, "valuation_rows": 0, "financials_rows": 0}

    log.info(f"=== FundamentalsSync {datetime.now():%Y-%m-%d %H:%M} ===")
    log.info(
        f"  symbols={len(symbols)}, workers={max_workers}, "
        f"valuation={valuation}, financials={financials}, resume={resume}"
    )

    total_val = 0
    total_fin = 0
    total_div = 0
    done = 0
    skipped = 0
    failed = 0

    def _process_batch(kind: str, interval: str, sync_fn):
        """跑一轮（估值/财务/分红）。"""
        nonlocal total_val, total_fin, total_div, done, skipped, failed
        # resume: 跳过已完成的
        pending = symbols
        if resume:
            pending = tracker.get_pending_symbols(PROVIDER, interval, symbols)
            if len(pending) < len(symbols):
                log.info(f"[{kind}] 断点续传：跳过 {len(symbols)-len(pending)} 已完成，剩 {len(pending)}")

        error_streak = 0  # 连续"异常"计数（限流才计，空数据不计）
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(sync_fn, provider, sym, tracker): sym
                for sym in pending
            }
            for fut in as_completed(futures):
                sym = futures[fut]
                try:
                    _sym, n, is_error = fut.result()
                    if kind == "valuation":
                        total_val += n
                    elif kind == "financials":
                        total_fin += n
                    else:
                        total_div += n
                    if n == 0:
                        skipped += 1
                    else:
                        done += 1
                        error_streak = 0  # 成功写入，重置异常计数
                    if is_error:
                        # 真异常（限流/超时/网络）才计入限流退避
                        error_streak += 1
                        failed += 1
                        if error_streak >= RATE_LIMIT_EMPTY_STREAK:
                            log.warning(
                                f"[{kind}] 连续 {error_streak} 个异常，疑似限流，退避 {RATE_LIMIT_BACKOFF_SEC}s"
                            )
                            time.sleep(RATE_LIMIT_BACKOFF_SEC)
                            error_streak = 0
                    else:
                        error_streak = 0  # 非异常（含空数据），重置
                except Exception as e:  # noqa: BLE001
                    log.warning(f"[{kind}] {sym} 异常: {e}")
                    failed += 1
                if rate_delay:
                    time.sleep(rate_delay / max_workers)
            # 一轮批处理结束：把累积进度一次性落盘
            tracker.flush()

    if valuation:
        log.info("--- 同步估值 ---")
        _process_batch("valuation", "valuation", _sync_symbol_valuation)
    if financials:
        log.info("--- 同步财务 ---")
        _process_batch("financials", "financials", _sync_symbol_financials)
    if dividend:
        log.info("--- 同步分红明细(+回填股息率) ---")
        _process_batch("dividend", "dividend", _sync_symbol_dividend)

    log.info(f"=== FundamentalsSync 完成 ===")
    log.info(f"  估值写入: {total_val:,} 行")
    log.info(f"  财务写入: {total_fin:,} 行")
    log.info(f"  分红写入: {total_div:,} 行")
    log.info(f"  成功: {done}, 跳过/空: {skipped}, 失败: {failed}")

    return {
        "symbols": len(symbols),
        "valuation_rows": total_val,
        "financials_rows": total_fin,
        "dividend_rows": total_div,
    }


def main():
    parser = argparse.ArgumentParser(description="基本面数据同步（估值+财务）")
    parser.add_argument(
        "--symbols", default="",
        help="股票代码（逗号分隔，带前缀 sh/sz），为空则拉沪深A股（剔除ST）",
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument(
        "--only",
        choices=["valuation", "financials", "dividend", "both", "all"],
        default="all",
        help="只同步某类 / both=估值+财务 / all=全部(含分红)",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="忽略进度文件，全量重跑",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(
                Path(__file__).parent.parent.parent.parent.parent
                / "logs" / "fundamentals_sync.log",
                encoding="utf-8",
            ),
            logging.StreamHandler(sys.stdout),
        ],
    )

    logs_dir = Path(__file__).parent.parent.parent.parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    symbols = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols else None
    )
    run(
        symbols=symbols,
        max_workers=args.workers,
        rate_delay=args.delay,
        valuation=args.only in ("valuation", "both", "all"),
        financials=args.only in ("financials", "both", "all"),
        dividend=args.only in ("dividend", "all"),
        resume=not args.no_resume,
    )


if __name__ == "__main__":
    main()
