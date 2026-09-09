"""FinancialFullSyncJob
======================
akshare 全量财务数据同步（供 cron / 手动调用）。

同步内容：
  1. 业绩预告 + 业绩快报（全市场批量）→ stock_earnings_forecast
  2. A 股三大报表 + 财务摘要（按 symbol）→ stock_financial_detail
  3. 港股三大报表（按 symbol）         → stock_financial_detail
  4. 美股三大报表（按 symbol）         → stock_financial_detail

特点：
  - 复用 fundamentals.py 的成熟模式：ThreadPoolExecutor 并发、ProgressTracker
    断点续传、限流退避（连续空/异常计数后 sleep）。
  - 业绩预告/快报是「全市场批量」接口（按报告期 date 一次拉数千行），不走
    per-symbol 循环，单独处理。
  - 增量跳过：库里已有该 symbol 某报表最新报告期的，可按 --skip-recent 跳过。

调用示例：
  # 样本验证（3 只 A 股 + 业绩批量）
  python -m src.domain.market.sync.jobs.financial_full_sync \\
      --symbols sh600519,sz000001,sz000002 --statements income,balance,cashflow

  # 全量 A 股（后台）
  python -m src.domain.market.sync.jobs.financial_full_sync --market A

  # 全量港美股
  python -m src.domain.market.sync.jobs.financial_full_sync --market HK,US
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

from src.domain.market.sync.progress import ProgressTracker, SyncStatus  # noqa: E402
from src.domain.market.sync.providers.akshare_provider import AkshareProvider  # noqa: E402
from src.infra.database.market.financial_full import (  # noqa: E402
    create_financial_detail_repository,
    create_earnings_forecast_repository,
)

log = logging.getLogger("financial_full_sync")

PROVIDER = "akshare"

# 限流退避
RATE_LIMIT_EMPTY_STREAK = 8
RATE_LIMIT_BACKOFF_SEC = 30
# 增量跳过阈值（天）：库中最新报告期距今小于此值则跳过该 symbol。
# 设 90 天（一个季度）：财报按季发布，季内同一 symbol 最多被周增量重拉 1 次。
# 设太小（如 30 天）会导致一个季度内被重拉 3 次（幂等但浪费网络请求）。
SKIP_RECENT_DAYS = 90


# ── 股票清单 ──────────────────────────────────────────────────────────────

def _a_stock_list() -> list[str]:
    """沪深 A 股（剔除 ST/北交所），复用 fundamentals 的 DB 读取逻辑。"""
    from src.domain.market.sync.jobs.fundamentals import _db_a_list_filtered
    syms = _db_a_list_filtered()
    if syms:
        return syms
    # 降级
    provider = AkshareProvider()
    return [s for s in provider.get_a_stock_list() if not s.lower().startswith("bj")]


def _filter_etf(symbols: list[str]) -> list[str]:
    """剔除 ETF/基金（无财务三大表，且同花顺接口对 ETF 会卡住不返回）。

    复用 fundamentals._is_etf_or_fund 的 name 判断 + 代码号段兜底。
    """
    from src.domain.market.sync.jobs.fundamentals import _is_etf_or_fund
    return [s for s in symbols if not _is_etf_or_fund(s)]


def _hk_stock_list() -> list[str]:
    """港股全市场（纯 5 位代码）。"""
    provider = AkshareProvider()
    return provider.get_hk_stock_list()


def _us_stock_list() -> list[str]:
    """美股主流标的清单。

    akshare 无现成的「美股主流代码」列表（stock_us_spot_em 本环境不可达），
    用一份精选的「中概 + 大盘科技 + 主要 ETF」清单（约 60 只）。
    用户需要更多可后续扩充或换数据源。
    """
    return [
        # 大盘科技
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "NFLX",
        "AVGO", "ORCL", "CRM", "AMD", "INTC", "QCOM", "ADBE", "CSCO",
        # 金融
        "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "BRK.A",
        # 消费/医疗/工业
        "WMT", "COST", "HD", "MCD", "NKE", "KO", "PEP", "PG", "JNJ",
        "UNH", "PFE", "MRK", "ABT", "LLY", "DIS", "BA", "CAT",
        # 能源
        "XOM", "CVX",
        # 中概
        "BABA", "PDD", "JD", "BIDU", "NIO", "XPEV", "LI", "TME",
        "BILI", "NTES", "WB", "DIDI",
        # 主要 ETF
        "SPY", "QQQ", "VOO", "IWM", "EEM",
    ]


# ── 业绩预告/快报（全市场批量）────────────────────────────────────────────

def _sync_earnings(provider: AkshareProvider, report_dates: list[str]) -> dict:
    """同步业绩预告 + 业绩快报（按报告期批量拉全市场）→ stock_earnings_forecast。

    report_dates: ['20251231', '20250930', ...]（YYYYMMDD）
    """
    repo = create_earnings_forecast_repository()
    stats = {"preannounce": 0, "express": 0}
    for rd_str in report_dates:
        try:
            batch = provider.fetch_earnings_batch(rd_str)
        except Exception as e:
            log.error(f"[earnings:{rd_str}] 拉取失败: {e}")
            continue
        for ftype, rows in batch.items():
            if not rows:
                continue
            try:
                n = repo.bulk_upsert(rows)
                stats[ftype] += n
                log.info(f"[earnings:{rd_str}:{ftype}] +{n} 行")
            except Exception as e:
                log.error(f"[earnings:{rd_str}:{ftype}] 写入失败: {e}")
    return stats


# ── 三大报表（按 symbol）──────────────────────────────────────────────────

# statement_type → provider 方法名
_STATEMENT_METHODS = {
    "income":   "fetch_income_statement",
    "balance":  "fetch_balance_sheet",
    "cashflow": "fetch_cash_flow",
    "abstract": "fetch_financial_abstract",
}


def _sync_symbol_statements(
    provider: AkshareProvider,
    symbol: str,
    statement_types: list[str],
    market: str,
    tracker: ProgressTracker,
    incremental: bool = False,
    skip_recent_days: int = SKIP_RECENT_DAYS,
) -> tuple[str, int, bool]:
    """同步单只股票的指定报表 → stock_financial_detail。

    market='A' 时用 A 股三大表/摘要方法；'HK' 用港股；'US' 用美股。
    incremental=True 时，库中该 symbol 最新报告期距今 < skip_recent_days 天则跳过
    （财报按季发布，30 天阈值避免重复拉取未更新的数据）。
    返回 (symbol, 写入总行数, 是否异常)。
    """
    if not statement_types:
        return symbol, 0, False
    repo = create_financial_detail_repository()
    total = 0
    is_error = False

    # 增量跳过：只查第一个 statement_type 的最新报告期（各表报告期基本同步）
    if incremental:
        first_st = statement_types[0] if market == "A" else "income"
        latest = repo.get_latest_report_date(symbol, first_st)
        if latest and (date.today() - latest).days < skip_recent_days:
            return symbol, 0, False

    for st_type in statement_types:
        interval = f"finfull_{st_type}"
        # 选 fetch 方法
        if market == "HK":
            # 港股一次拉三大表（fetch_hk_financial 内部循环 3 表）
            if st_type != "income":
                continue  # 港股只需调一次，跳过 balance/cashflow（已在 income 轮处理）
            fn = provider.fetch_hk_financial
        elif market == "US":
            if st_type != "income":
                continue
            fn = provider.fetch_us_financial
        else:
            method_name = _STATEMENT_METHODS.get(st_type)
            if not method_name:
                continue
            fn = getattr(provider, method_name)

        try:
            rows = fn(symbol)
        except Exception as e:
            tracker.mark_failed(PROVIDER, symbol, interval, str(e)[:200])
            log.warning(f"[{st_type}] {symbol} 异常: {e}")
            is_error = True
            continue
        if not rows:
            tracker.mark_partial(PROVIDER, symbol, interval, 0)
            continue
        try:
            n = repo.bulk_upsert(rows)
            total += n
            tracker.mark_done(PROVIDER, symbol, interval,
                              datetime.now().isoformat(), n)
        except Exception as e:
            tracker.mark_failed(PROVIDER, symbol, interval, str(e)[:200])
            log.warning(f"[{st_type}] {symbol} 写入失败: {e}")
            is_error = True
    return symbol, total, is_error


def _sync_market(
    symbols: list[str],
    statement_types: list[str],
    market: str,
    max_workers: int,
    rate_delay: float,
    resume: bool,
    incremental: bool = False,
) -> dict:
    """同步一个市场（A/HK/US）的全部 symbol 三大表。"""
    tracker = ProgressTracker()
    provider = AkshareProvider()
    total_rows = 0
    done = 0
    skipped = 0
    failed = 0

    # 港美股用 income 作 interval key（一次拉三表）
    interval_key = "finfull_income" if market in ("HK", "US") else "finfull_statements"
    pending = symbols
    if resume:
        done_set = set()
        for st in statement_types:
            done_set |= set(
                tracker.get_pending_symbols(
                    PROVIDER, f"finfull_{st}", symbols
                ) and set() or set()
            )
        # 简化：按首个 statement_type 的进度判断
        first_interval = f"finfull_{statement_types[0]}"
        pending = tracker.get_pending_symbols(PROVIDER, first_interval, symbols)
        if len(pending) < len(symbols):
            log.info(f"[{market}] 断点续传：跳过 {len(symbols)-len(pending)}，剩 {len(pending)}")

    log.info(f"=== [{market}] {len(pending)} symbols, workers={max_workers} ===")

    error_streak = 0
    # 分批提交（chunk），避免一次性提交数千 future；
    # 每批完成后 flush 进度 + 打印累计进度（后台进程 stdout 全缓冲，需显式 flush）
    CHUNK = 60
    processed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for chunk_start in range(0, len(pending), CHUNK):
            chunk = pending[chunk_start:chunk_start + CHUNK]
            futures = {
                pool.submit(
                    _sync_symbol_statements,
                    provider, sym, statement_types, market, tracker,
                    incremental,
                ): sym
                for sym in chunk
            }
            for fut in as_completed(futures):
                sym = futures[fut]
                try:
                    _sym, n, is_error = fut.result()
                    total_rows += n
                    if n == 0:
                        skipped += 1
                    else:
                        done += 1
                        error_streak = 0
                    if is_error:
                        error_streak += 1
                        failed += 1
                        if error_streak >= RATE_LIMIT_EMPTY_STREAK:
                            log.warning(
                                f"[{market}] 连续 {error_streak} 异常，疑似限流，退避 {RATE_LIMIT_BACKOFF_SEC}s"
                            )
                            time.sleep(RATE_LIMIT_BACKOFF_SEC)
                            error_streak = 0
                    else:
                        error_streak = 0
                except Exception as e:
                    log.warning(f"[{market}] {sym} 异常: {e}")
                    failed += 1
            processed += len(chunk)
            tracker.flush()
            # 每批打印进度（后台进程需看进度是否在推进）
            log.info(
                f"[{market}] 进度 {processed}/{len(pending)} "
                f"({processed*100//len(pending)}%) | 累计 {total_rows:,} 行, "
                f"成功 {done}, 跳过 {skipped}, 失败 {failed}"
            )

    log.info(f"[{market}] 完成: 写入 {total_rows:,} 行, 成功 {done}, 跳过 {skipped}, 失败 {failed}")
    return {"symbols": len(pending), "rows": total_rows,
            "done": done, "skipped": skipped, "failed": failed}


# ── 报告期生成 ─────────────────────────────────────────────────────────────

def _recent_report_dates(quarters: int = 8) -> list[str]:
    """生成最近 N 个季末报告期（YYYYMMDD），用于业绩预告/快报。

    如 2026-07 时，quarters=8 → [20250630, 20250331, 20241231, ...]
    季末月份为 3/6/9/12。从当前月份回退到最近的已过季末，然后每次再退 3 个月。
    """
    today = date.today()
    y, m = today.year, today.month
    # 回退到最近的已过季末：3/6/9/12
    # 若当前是 7 月，最近的已过季末是 6 月
    q_last_day = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
                  7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
    # 找 <= 当前月的最近季末月
    quarter_ends = [3, 6, 9, 12]
    recent = max(q for q in quarter_ends if q <= m)
    m = recent
    out = []
    for _ in range(quarters):
        last_day = q_last_day[m]
        out.append(f"{y}{m:02d}{last_day:02d}")
        m -= 3
        if m <= 0:
            m += 12
            y -= 1
    return out


# ── 主入口 ─────────────────────────────────────────────────────────────────

def run(
    markets: str = "A",
    symbols: list[str] | None = None,
    statements: str = "income,balance,cashflow,abstract",
    earnings: bool = True,
    max_workers: int = 6,
    rate_delay: float = 0.2,
    resume: bool = True,
    incremental: bool = False,
) -> dict:
    """执行财务数据同步（全量 or 增量）。

    Args:
        markets:    市场组合，逗号分隔（A / HK / US）
        symbols:    指定股票池（仅单市场时有效）；为空则拉全市场清单
        statements: 报表类型，逗号分隔（income/balance/cashflow/abstract）
        earnings:   是否同步业绩预告/快报（仅 A 股市场有意义）
        max_workers: 并发数
        rate_delay: 每请求后等待秒数
        resume:     断点续传
        incremental: 增量模式——三大表只拉最新报告期距今 >30 天的 symbol；
                     业绩预告/快报只拉最近 2 个报告期。全量设 False。
    """
    market_list = [m.strip().upper() for m in markets.split(",") if m.strip()]
    st_types = [s.strip() for s in statements.split(",") if s.strip()]
    log.info(f"=== FinancialFullSync {datetime.now():%Y-%m-%d %H:%M} "
             f"({'增量' if incremental else '全量'}) ===")
    log.info(f"  markets={market_list}, statements={st_types}, workers={max_workers}")

    results: dict = {}
    provider = AkshareProvider()

    # ── 业绩预告/快报（仅 A 股）──
    # 增量模式只拉最近 2 个报告期（幂等 upsert）；全量拉 8 个
    if earnings and "A" in market_list:
        n_quarters = 2 if incremental else 8
        rds = _recent_report_dates(n_quarters)
        log.info(f"--- 同步业绩预告/快报（{len(rds)} 个报告期）---")
        results["earnings"] = _sync_earnings(provider, rds)

    # ── 三大报表（按市场）──
    if not st_types:
        log.info("statements 为空，跳过三大报表同步")
    for market in market_list:
        if market == "A":
            sym_list = symbols or _a_stock_list()
            # 剔除 ETF/基金（无财务三大表，且同花顺接口对 ETF 会卡住）
            if not symbols:
                before = len(sym_list)
                sym_list = _filter_etf(sym_list)
                log.info(f"[A] 剔除 ETF/基金：{before} → {len(sym_list)}")
            st = st_types
        elif market == "HK":
            sym_list = symbols or _hk_stock_list()
            st = ["income"]  # 港股 fetch_hk_financial 一次拉三表
        elif market == "US":
            sym_list = symbols or _us_stock_list()
            st = ["income"]
        else:
            continue
        if not sym_list:
            log.warning(f"[{market}] 股票列表为空，跳过")
            continue
        results[market] = _sync_market(
            sym_list, st, market, max_workers, rate_delay, resume, incremental,
        )

    log.info(f"=== FinancialFullSync 完成 ===")
    for k, v in results.items():
        if isinstance(v, dict):
            log.info(f"  {k}: {v}")
    return results


def main():
    parser = argparse.ArgumentParser(description="akshare 全量财务数据同步")
    parser.add_argument(
        "--markets", default="A",
        help="市场组合，逗号分隔（A / HK / US），默认 A",
    )
    parser.add_argument(
        "--symbols", default="",
        help="股票代码（逗号分隔），为空则拉全市场清单",
    )
    parser.add_argument(
        "--statements", default="income,balance,cashflow,abstract",
        help="报表类型，逗号分隔",
    )
    parser.add_argument("--no-earnings", action="store_true", help="不同步业绩预告/快报")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--no-resume", action="store_true", help="全量重跑")
    parser.add_argument(
        "--incremental", action="store_true",
        help="增量模式：只拉最新报告期距今>30天的 symbol，业绩只拉最近2期",
    )
    args = parser.parse_args()

    (_BACKEND / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(
                _BACKEND / "logs" / "financial_full_sync.log", encoding="utf-8",
            ),
            logging.StreamHandler(sys.stdout),
        ],
    )

    symbols = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols else None
    )
    run(
        markets=args.markets,
        symbols=symbols,
        statements=args.statements,
        earnings=not args.no_earnings,
        max_workers=args.workers,
        rate_delay=args.delay,
        resume=not args.no_resume,
        incremental=args.incremental,
    )


if __name__ == "__main__":
    main()
