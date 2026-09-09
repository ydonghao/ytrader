"""财务三大报表 + 业绩预告/快报 API handler。

数据源：stock_financial_detail（三大报表全科目，akshare 同花顺/东财）
        stock_earnings_forecast（业绩预告/快报，全市场批量）

遵循 router → handler → repository 分层，统一用 src.pkg.responses 返回。
与 financial_router.py 中的 mock demo 端点（/statement/{symbol} 等）共存：
真实数据端点用 /detail/ 前缀区分。
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Callable, Optional

from src.pkg import responses
from src.domain.market.fundamental.period_transform import (
    filter_year_only,
    transform_to_quarter,
)

logger = logging.getLogger(__name__)

# 行业估值快照缓存：akshare 调用结果 + 时间戳，1 小时有效
_industry_snapshot_cache: dict = {"data": None, "ts": 0.0}
_INDUSTRY_SNAPSHOT_TTL = 3600  # 秒

# akshare 请求专用执行器：future.result(timeout) 实现「本请求快速失败」。
# 不再用 socket.setdefaulttimeout——那是进程级全局突变，会把同进程内
# 后台同步任务（APScheduler 里的 sync jobs）的超时一并改小。
_AK_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="akshare-req")


def _call_with_timeout(fn: Callable, timeout: float) -> Any:
    """后台线程执行 fn 并限时等待；超时/异常返回 None（调用方自行降级）。"""
    try:
        return _AK_EXECUTOR.submit(fn).result(timeout=timeout)
    except Exception:
        return None


def _parse_date(s: Optional[str]) -> Optional[date]:
    """'2020-01-01' / '20200101' → date；空/无效 → None。"""
    if not s:
        return None
    t = str(s).strip().replace("-", "")
    if len(t) == 8 and t.isdigit():
        try:
            return date(int(t[:4]), int(t[4:6]), int(t[6:8]))
        except ValueError:
            pass
    return None


def detail_series(
    symbol: str,
    statement_type: str = "income",
    limit: int = 20,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: str = "quarter",
) -> Any:
    """单只股票某报表的历史时序（固定列 + detail JSONB）。

    Args:
        symbol:         sh600519 / sz000001 / 00700 / AAPL
        statement_type: income / balance / cashflow / abstract
        limit:          返回最近 N 期（默认 20）；与 start/end 二选一
        start_date:     起始报告期 YYYY-MM-DD（含），指定后 limit 失效
        end_date:       截止报告期 YYYY-MM-DD（含）
        period:         month=原始报告期；quarter=单季换算（流量项做差，
                        派生指标重算）；year=只返回年报期（12-31）。
                        默认 quarter。非法值降级为 quarter。
    """
    from src.infra.database.market.financial_full import (
        create_financial_detail_repository,
    )
    repo = create_financial_detail_repository()

    # 解析日期范围
    sd = _parse_date(start_date)
    ed = _parse_date(end_date)

    try:
        rows = repo.get_history(symbol, statement_type, start=sd, end=ed)
    except Exception as e:
        return responses.error(f"查询失败: {e}")

    if not rows:
        return responses.success({"symbol": symbol, "statement_type": statement_type,
                                  "series": [], "latest_date": None})

    # 日期范围模式：返回范围内全部；limit 模式：取最近 limit 期
    if sd or ed:
        recent = rows                       # 指定了日期范围，不截断
    else:
        recent = rows[-limit:] if len(rows) > limit else rows

    # 周期转换：把 SQLModel 行转 dict 后按 period 处理
    dicts = []
    for r in recent:
        d = {
            "report_date": r.report_date,
        }
        # 遍历所有固定列字段（避免硬编码列名遗漏）
        for c in (
            "revenue", "operating_cost", "gross_profit",
            "sell_expense", "admin_expense", "rd_expense",
            "fin_expense", "operating_profit", "net_profit",
            "net_profit_parent", "net_profit_deduct", "basic_eps",
            "monetary_funds", "accounts_receivable", "inventory",
            "fixed_assets", "goodwill", "total_assets",
            "total_liabilities", "equity", "equity_parent",
            "short_loan", "long_loan",
            "ocf", "icf", "fcf", "cash_end",
            "gross_margin", "net_margin", "debt_ratio",
        ):
            d[c] = getattr(r, c, None)
        # detail JSONB 原样保留，仅在 period=month 时输出
        d["detail"] = getattr(r, "detail", None)
        dicts.append(d)

    if period == "year":
        dicts = filter_year_only(dicts)
    elif period != "month":
        # quarter（默认）及任何非法值都走单季换算
        transform_to_quarter(dicts)

    # 转为前端友好的 dict 列表（降序，最新在前）
    series = []
    for d in reversed(dicts):
        item = {
            "report_date": d["report_date"].isoformat()
            if d.get("report_date") else None,
            "revenue": d.get("revenue"),
            "operating_cost": d.get("operating_cost"),
            "gross_profit": d.get("gross_profit"),
            "sell_expense": d.get("sell_expense"),
            "admin_expense": d.get("admin_expense"),
            "rd_expense": d.get("rd_expense"),
            "fin_expense": d.get("fin_expense"),
            "operating_profit": d.get("operating_profit"),
            "net_profit": d.get("net_profit"),
            "net_profit_parent": d.get("net_profit_parent"),
            "net_profit_deduct": d.get("net_profit_deduct"),
            "basic_eps": d.get("basic_eps"),
            "monetary_funds": d.get("monetary_funds"),
            "accounts_receivable": d.get("accounts_receivable"),
            "inventory": d.get("inventory"),
            "fixed_assets": d.get("fixed_assets"),
            "goodwill": d.get("goodwill"),
            "total_assets": d.get("total_assets"),
            "total_liabilities": d.get("total_liabilities"),
            "equity": d.get("equity"),
            "equity_parent": d.get("equity_parent"),
            "short_loan": d.get("short_loan"),
            "long_loan": d.get("long_loan"),
            "ocf": d.get("ocf"),
            "icf": d.get("icf"),
            "fcf": d.get("fcf"),
            "cash_end": d.get("cash_end"),
            "gross_margin": d.get("gross_margin"),
            "net_margin": d.get("net_margin"),
            "debt_ratio": d.get("debt_ratio"),
            # detail JSONB：month 模式或港股（固定列可能为空时）始终返回
            "detail": d.get("detail") if (period == "month" or symbol[:2].isdigit()) else None,
        }
        series.append(item)
    return responses.success({
        "symbol": symbol,
        "statement_type": statement_type,
        "market": rows[-1].market if rows else "A",
        "latest_date": series[0]["report_date"] if series else None,
        "total_periods": len(rows),
        "series": series,
    })


def forecast_list(
    report_date: Optional[str] = None,
    forecast_type: Optional[str] = None,
    limit: int = 50,
) -> Any:
    """业绩预告/快报全市场列表（按报告期）。

    Args:
        report_date:    YYYYMMDD 或 YYYY-MM-DD，为空取最新报告期
        forecast_type:  preannounce(预告) / express(快报)，为空取全部
        limit:          返回条数（默认 50）
    """
    from src.infra.database.market.financial_full import (
        create_earnings_forecast_repository,
    )
    repo = create_earnings_forecast_repository()

    # 解析 report_date
    rd = None
    if report_date:
        s = str(report_date).replace("-", "")
        try:
            rd = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except (ValueError, IndexError):
            return responses.error(f"report_date 格式错误: {report_date}")

    try:
        rows = repo.get_by_report_date(rd, forecast_type, limit)
    except Exception as e:
        return responses.error(f"查询失败: {e}")

    items = []
    for r in rows:
        items.append({
            "symbol": r.symbol,
            "company_name": r.company_name,
            "forecast_type": r.forecast_type,
            "report_date": r.report_date.isoformat() if r.report_date else None,
            "announce_date": r.announce_date.isoformat() if r.announce_date else None,
            "metric": r.metric,
            "forecast_value": r.forecast_value,
            "change_pct": r.change_pct,
            "prev_value": r.prev_value,
            "forecast_type_label": r.forecast_type_label,
            "revenue": r.revenue,
            "net_profit": r.net_profit,
            "roe": r.roe,
            "eps": r.eps,
        })
    return responses.success({
        "report_date": rows[0].report_date.isoformat() if rows and rows[0].report_date else None,
        "count": len(items),
        "items": items,
    })


def stock_profile(symbol: str) -> Any:
    """股票基本信息概要（供财务页面抬头展示）。

    组合多源数据：
      - stock_info：名称、市场、上市日期
      - stock_valuation：最新市值、PE/PB/PS
      - stock_financial_detail：报告期数、最新报告期
      - akshare stock_individual_info_em：行业、经营范围（实时拉取，失败降级）
    """
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn

    profile: dict = {"symbol": symbol}

    try:
        conn = psycopg2.connect(get_dsn())
        with conn.cursor() as cur:
            # 1. 基本信息
            cur.execute(
                "SELECT name, market, list_date FROM stock_info WHERE symbol=%s",
                (symbol,),
            )
            row = cur.fetchone()
            if row:
                profile["name"] = row[0]
                profile["market"] = row[1]
                profile["list_date"] = row[2].isoformat() if row[2] else None

            # 2. 最新估值
            cur.execute(
                """SELECT trade_date, pe, pe_ttm, pb, ps, total_mv
                   FROM stock_valuation
                   WHERE symbol=%s ORDER BY trade_date DESC LIMIT 1""",
                (symbol,),
            )
            row = cur.fetchone()
            if row:
                profile["val_date"] = row[0].isoformat() if row[0] else None
                profile["pe"] = row[1]
                profile["pe_ttm"] = row[2]
                profile["pb"] = row[3]
                profile["ps"] = row[4]
                profile["total_mv"] = row[5]

            # 3. 财务报告期统计
            cur.execute(
                """SELECT count(*), max(report_date), min(report_date)
                   FROM stock_financial_detail WHERE symbol=%s""",
                (symbol,),
            )
            row = cur.fetchone()
            if row and row[0]:
                profile["report_periods"] = row[0]
                profile["latest_report"] = row[1].isoformat() if row[1] else None
                profile["earliest_report"] = row[2].isoformat() if row[2] else None
        conn.close()
    except Exception as e:
        pass  # 降级：返回已有的 profile

    # 4. 尝试实时拉取行业/经营范围（akshare，失败静默降级）
    #    注意：stock_individual_info_em 是 A 股接口，港股/美股 symbol 跳过。
    #    港股 symbol 是纯 5 位数字（如 00700），不走此分支。
    is_a_share = symbol[:2].lower() in ("sh", "sz", "bj")
    if is_a_share:
        import akshare as ak
        # A 股：sh600519/sz000001 → 去 sh/sz 前缀取纯代码
        code = symbol[2:] if symbol[:2].lower() in ("sh", "sz", "bj") else symbol
        df = _call_with_timeout(
            lambda: ak.stock_individual_info_em(symbol=code), timeout=10,
        )
        if df is not None and not df.empty:
            info = dict(zip(df["item"], df["value"]))
            profile["industry"] = info.get("行业")
            profile["business_scope"] = str(info.get("经营范围", ""))[:500]
            profile["listing_date_em"] = info.get("上市时间")
            profile["total_share"] = info.get("总股本")
            profile["float_share"] = info.get("流通股")

    return responses.success(profile)


def dcf_valuation(
    symbol: str,
    growth_rate: float = 0.08,
    terminal_growth: float = 0.03,
    wacc: float = 0.09,
    projection_years: int = 10,
) -> Any:
    """DCF 内在价值 + 安全边际（价值投资绝对估值锚）。

    取 TTM 自由现金流（stock_financial_detail 近几期累计值
    free_cash_flow = ocf-|capex|，差分为滚动 12 个月）
    + 最新市值（stock_valuation.total_mv），用两阶段 DCF 折现。
    假设由调用方提供（投资者应按公司实际调整增速/折现率）。
    """
    import psycopg2

    from src.infra.database.sql_engine.dsn import get_dsn
    from src.domain.market.fundamental.dcf import (
        dcf_intrinsic_value,
        margin_of_safety,
        dcf_monte_carlo,
        ttm_fcf,
    )

    data: dict = {"symbol": symbol}
    try:
        conn = psycopg2.connect(get_dsn())
        with conn.cursor() as cur:
            # 取近 6 期累计口径现金流（一季报 3 月/中报 6 月/三季报 9 月），
            # 由 ttm_fcf 差分成滚动 12 个月，避免把半年值当全年基数
            cur.execute(
                """
                SELECT report_date, free_cash_flow
                FROM stock_financial_detail
                WHERE symbol = %s AND statement_type = 'cashflow'
                  AND free_cash_flow IS NOT NULL
                ORDER BY report_date DESC LIMIT 6
                """,
                (symbol,),
            )
            frows = cur.fetchall()
            cur.execute(
                """
                SELECT trade_date, total_mv
                FROM stock_valuation
                WHERE symbol = %s
                ORDER BY trade_date DESC LIMIT 1
                """,
                (symbol,),
            )
            vrow = cur.fetchone()
        conn.close()

        base = ttm_fcf(frows)
        latest_fcf = base[0] if base else None
        data["fcf_base"] = latest_fcf
        data["report_date"] = base[1].isoformat() if base else None
        data["fcf_method"] = base[2] if base else None
        total_mv = vrow[1] if vrow else None
        data["market_value"] = total_mv
        data["valuation_date"] = (
            vrow[0].isoformat() if vrow and vrow[0] else None
        )

        intrinsic = dcf_intrinsic_value(
            latest_fcf,
            growth_rate,
            terminal_growth,
            wacc,
            projection_years,
        )
        data["intrinsic_value"] = intrinsic
        data["margin_of_safety"] = margin_of_safety(intrinsic, total_mv)
        # 蒙特卡洛：对 g/WACC 正态采样，得内在价值分布（均值/标准差/分位区间）
        try:
            mc = dcf_monte_carlo(
                latest_fcf,
                growth_mean=growth_rate, growth_std=0.03,
                wacc_mean=wacc, wacc_std=0.01,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
            )
            data["monte_carlo"] = mc
        except Exception:
            data["monte_carlo"] = None
    except Exception as e:  # noqa: BLE001
        data["error"] = str(e)[:200]

    data["assumptions"] = {
        "growth_rate": growth_rate,
        "terminal_growth": terminal_growth,
        "wacc": wacc,
        "projection_years": projection_years,
    }
    data["note"] = (
        "内在价值基于TTM自由现金流(ocf-|capex|,年报+最新累计-去年同期)"
        "两阶段折现；fcf_method=annual_fallback表示缺去年同期数据、"
        "退回最近年报口径。fcf_base 为空则无 FCF 数据(结果 None)。"
        "假设应按公司实际调整(增速/折现率)。"
    )
    return responses.success(data)


def valuation_history(
    symbol: str, report_dates: list[str]
) -> Any:
    """按报告期末取个股估值历史（PE/PE_TTM/PB/PS/总市值）。

    对每个 report_date，取 stock_valuation 中 trade_date <= report_date
    的最近一行（报告期末交易日对齐）。

    Args:
        symbol:       sh600519 / sz000001
        report_dates: ['2023-12-31', '2024-03-31', ...]（前端传入）

    Returns:
        success({"symbol", "points": [{report_date, trade_date,
        pe, pe_ttm, pb, ps, total_mv}]})
    """
    from src.infra.database.market.valuation import (
        create_stock_valuation_repository,
    )
    repo = create_stock_valuation_repository()

    if not report_dates:
        return responses.success(
            {"symbol": symbol, "points": []}
        )

    points = []
    for rd_str in report_dates:
        rd = _parse_date(rd_str)
        if rd is None:
            points.append({
                "report_date": rd_str, "trade_date": None,
                "pe": None, "pe_ttm": None, "pb": None,
                "ps": None, "total_mv": None,
            })
            continue
        try:
            row = repo.get_as_of(symbol, rd)
        except Exception as e:
            logger.warning(
                "valuation_history query failed for %s @ %s: %s",
                symbol, rd_str, e,
            )
            row = None
        if row:
            points.append({
                "report_date": rd_str,
                "trade_date": row.trade_date.isoformat()
                if row.trade_date else None,
                "pe": row.pe,
                "pe_ttm": row.pe_ttm,
                "pb": row.pb,
                "ps": row.ps,
                "total_mv": row.total_mv,
            })
        else:
            points.append({
                "report_date": rd_str, "trade_date": None,
                "pe": None, "pe_ttm": None, "pb": None,
                "ps": None, "total_mv": None,
            })
    return responses.success({"symbol": symbol, "points": points})


def _get_industry_snapshot_cached() -> list[dict]:
    """带 1 小时缓存的申万一级行业估值快照。

    akshare 调用失败时返回 []（不抛异常，让上层降级）。
    """
    now = time.time()
    cached = _industry_snapshot_cache
    if (cached["data"] is not None
            and now - cached["ts"] < _INDUSTRY_SNAPSHOT_TTL):
        return cached["data"]
    from src.domain.market.sync.providers.akshare_provider import (
        AkshareProvider,
    )
    data = _call_with_timeout(
        lambda: AkshareProvider().fetch_sw_index_valuation_snapshot(), timeout=15,
    )
    if data is None:
        logger.warning("industry snapshot fetch failed or timed out")
        data = []
    cached["data"] = data
    cached["ts"] = now
    return data


def industry_valuation_snapshot(
    industry: Optional[str] = None,
) -> Any:
    """申万一级行业估值快照（当天，PE/PB/股息率）。

    Args:
        industry: 行业名称（如 '银行'）或 sw_code（如 'sw801780'）。
                  为空返回全部 31 个行业列表。

    Returns:
        industry 非空：success({industry, sw_code, as_of, pe_static,
        pe_ttm, pb, dividend_yield, company_count})；未找到则
        error('行业未找到')。
        industry 为空：success({as_of, industries: [...]}).
        akshare 不可达：success(None)（前端降级隐藏）。
    """
    data = _get_industry_snapshot_cached()
    if not data:
        return responses.success(None)

    if industry is None:
        return responses.success({
            "as_of": time.strftime("%Y-%m-%d"),
            "industries": data,
        })

    # 精确匹配：先 sw_code 再 industry 名称
    match = next(
        (d for d in data if d["sw_code"] == industry), None
    )
    if match is None:
        match = next(
            (d for d in data if d["industry"] == industry), None
        )
    if match is None:
        return responses.not_found(f"行业未找到: {industry}")

    return responses.success({
        "industry": match["industry"],
        "sw_code": match["sw_code"],
        "as_of": time.strftime("%Y-%m-%d"),
        "pe_static": match["pe_static"],
        "pe_ttm": match["pe_ttm"],
        "pb": match["pb"],
        "dividend_yield": match["dividend_yield"],
        "company_count": match["company_count"],
    })


# ════════════════════════════════════════════════════════════════════════════
#  P0a 个股估值历史分位（PE_TTM/PB/PS_TTM/股息率 × 3/5/10 年窗口）
#  数据源：stock_valuation（已有日频估值），实时计算 + 1h 缓存。
# ════════════════════════════════════════════════════════════════════════════

# 分位结果缓存：key → 结果 dict，配套时间戳，1 小时有效
_valpct_cache: dict = {"data": {}, "ts": {}}
_VALPCT_CACHE_TTL = 3600

# 指标 → stock_valuation 表字段名映射
_VALPCT_ATTR_MAP = {
    "pe_ttm": "pe_ttm",
    "pb": "pb",
    "ps_ttm": "ps_ttm",
    "dv_ttm": "dv_ttm",
}
_VALPCT_WINDOW_YEARS = {
    "3y": 3, "5y": 5, "10y": 10, "15y": 15, "20y": 20,
    "all": 200,  # 全部历史：200 年回溯足以覆盖 A 股全部历史
}


def _parse_exclude_ranges(
    exclude: Optional[str],
) -> list[tuple[date, date]]:
    """
    解析 exclude 查询参数为日期区间列表。

    格式："2020-06-01~2021-02-28,2015-06-15~2015-12-31"
    每段 start~end，多段逗号分隔。非法段静默跳过。
    """
    if not exclude:
        return []
    out: list[tuple[date, date]] = []
    for seg in exclude.split(","):
        seg = seg.strip()
        if "~" not in seg:
            continue
        left, right = seg.split("~", 1)
        try:
            s = date.fromisoformat(left.strip())
            e = date.fromisoformat(right.strip())
            out.append((s, e))
        except ValueError:
            continue
    return out


def valuation_percentile(
    symbol: str,
    windows: list[str] | None = None,
    as_of: Optional[str] = None,
    metrics: list[str] | None = None,
    exclude: Optional[str] = None,
) -> Any:
    """个股估值历史分位（PE_TTM/PB/PS_TTM/股息率 × 3/5/10 年窗口）。

    Args:
        symbol:  sh600519 / sz000001
        windows: ["3y","5y","10y","15y","20y","all"]，默认 3y/5y/10y；
                 "all" 为全部历史（上市至今）
        as_of:   "YYYY-MM-DD"，默认最新交易日
        metrics: ["pe_ttm","pb","ps_ttm","dv_ttm"]，默认全部
        exclude: "2020-06-01~2021-02-28,2015-06-15~2015-12-31"，
                 多段逗号分隔；与全局剔除配置合并后用于过滤 series 与窗口样本

    Returns:
        success({symbol, as_of, metrics: {metric: {current, windows, series}}}).
        其中 windows = {w: percentile_stats|None}，series 为月度降采样的
        历史时序（用于画分位图）。
    """
    from src.infra.database.market.valuation import (
        create_stock_valuation_repository,
    )
    from src.domain.market.fundamental.percentile import (
        percentile_stats, downsample_monthly,
    )

    windows = windows or ["3y", "5y", "10y"]
    metrics = metrics or ["pe_ttm", "pb", "ps_ttm", "dv_ttm"]

    repo = create_stock_valuation_repository()

    # 确定 as_of
    if as_of:
        as_of_date = _parse_date(as_of)
        if as_of_date is None:
            return responses.fail(f"invalid as_of: {as_of}")
    else:
        latest = repo.get_latest_date(symbol)
        if latest is None:
            return responses.success(
                {"symbol": symbol, "as_of": None, "metrics": {}}
            )
        as_of_date = latest

    # 用户传入的剔除区间 + 全局配置剔除区间（Task 4 提供，未实现时降级为空）
    user_excludes = _parse_exclude_ranges(exclude)
    try:
        from src.domain.market.fundamental.percentile_batch import (
            _get_global_exclude_ranges,
        )
        global_excludes = _get_global_exclude_ranges()
    except Exception:
        global_excludes = []
    all_excludes = user_excludes + global_excludes

    result_metrics: dict = {}

    for metric in metrics:
        attr = _VALPCT_ATTR_MAP.get(metric)
        if attr is None:
            result_metrics[metric] = None
            continue

        # 缓存 key（按 symbol+metric+as_of+windows+exclude 组合）
        exclude_key = ",".join(
            f"{s.isoformat()}~{e.isoformat()}" for s, e in all_excludes
        )
        cache_key = (
            f"{symbol}:{metric}:{as_of_date.isoformat()}:"
            f"{','.join(windows)}:{exclude_key}"
        )
        now = time.time()
        cached = _valpct_cache["data"].get(cache_key)
        cached_ts = _valpct_cache["ts"].get(cache_key, 0)
        if cached is not None and now - cached_ts < _VALPCT_CACHE_TTL:
            result_metrics[metric] = cached
            continue

        # 拉最长窗口的原始数据（所有窗口共享同一批 rows，按窗口截取）
        max_years = max(
            (_VALPCT_WINDOW_YEARS[w] for w in windows if w in _VALPCT_WINDOW_YEARS),
            default=10,
        )
        range_start = date(
            as_of_date.year - max_years, as_of_date.month, as_of_date.day
        )
        try:
            rows = repo.get_range(symbol, range_start, as_of_date)
        except Exception as e:
            logger.warning(
                "valuation_percentile get_range failed %s: %s", symbol, e
            )
            rows = []

        # 全窗口有效点（用于 series 画图，过滤 None/负值 + 剔除区间）
        all_points = [
            {"date": r.trade_date.isoformat(), "value": getattr(r, attr)}
            for r in rows
            if getattr(r, attr) is not None and getattr(r, attr) > 0
            and not any(rs <= r.trade_date <= re_ for rs, re_ in all_excludes)
        ]
        current = all_points[-1]["value"] if all_points else None

        metric_result: dict = {
            "current": current,
            "windows": {},
            "series": downsample_monthly(all_points),
        }

        for w in windows:
            years = _VALPCT_WINDOW_YEARS.get(w)
            if years is None:
                metric_result["windows"][w] = None
                continue
            w_start = date(
                as_of_date.year - years, as_of_date.month, as_of_date.day
            )
            w_samples = [
                getattr(r, attr) for r in rows
                if r.trade_date >= w_start
                and getattr(r, attr) is not None
                and getattr(r, attr) > 0
                and not any(rs <= r.trade_date <= re_ for rs, re_ in all_excludes)
            ]
            metric_result["windows"][w] = (
                percentile_stats(w_samples, current) if current is not None else None
            )

        result_metrics[metric] = metric_result
        _valpct_cache["data"][cache_key] = metric_result
        _valpct_cache["ts"][cache_key] = now

    return responses.success({
        "symbol": symbol,
        "as_of": as_of_date.isoformat(),
        "metrics": result_metrics,
    })


# ════════════════════════════════════════════════════════════════════════════
#  P0b 指数/行业估值历史分位 + 财务聚合
#  数据源：index_valuation_daily / sw_index_valuation_daily / index_financial_quarterly
# ════════════════════════════════════════════════════════════════════════════

_P0B_WINDOW_YEARS = {"3y": 3, "5y": 5, "10y": 10, "15y": 15, "20y": 20}


def index_valuation_percentile(
    scope: str,          # "index" | "sw"
    code: str,           # 000300 | sw801010
    window: str = "10y",
    metrics: list[str] | None = None,
) -> Any:
    """指数/行业估值历史分位。

    Args:
        scope: "index"（宽基）| "sw"（申万行业）
        code:  指数代码（000300）或申万行业代码（sw801010）
        window: 3y/5y/10y
        metrics: pe_ttm/pb/ps_ttm/dv_ttm，默认 ["pe_ttm","pb"]

    Returns:
        success({scope, code, window, metrics: {metric: {current,
        stats: percentile_stats|None, series:[...]}}}).
    """
    from src.infra.database.market.index_valuation import (
        create_index_valuation_repository,
    )
    from src.domain.market.fundamental.percentile import (
        percentile_stats, downsample_monthly,
    )

    metrics = metrics or ["pe_ttm", "pb"]
    repo = create_index_valuation_repository()
    years = _P0B_WINDOW_YEARS.get(window, 10)

    end = date.today()
    start = date(end.year - years, end.month, end.day)

    if scope == "sw":
        rows = repo.get_sw_range(code, start, end)
    else:
        rows = repo.get_index_range(code, start, end)

    if not rows:
        return responses.success({
            "scope": scope, "code": code, "window": window,
            "metrics": {},
        })

    result: dict = {}
    for metric in metrics:
        samples = [
            getattr(r, metric) for r in rows
            if getattr(r, metric) is not None and getattr(r, metric) > 0
        ]
        current = samples[-1] if samples else None
        stats = percentile_stats(samples, current) if current else None
        series = downsample_monthly([
            {"date": r.trade_date.isoformat(), "value": getattr(r, metric)}
            for r in rows
            if getattr(r, metric) is not None and getattr(r, metric) > 0
        ])
        result[metric] = {"current": current, "stats": stats, "series": series}

    return responses.success({
        "scope": scope, "code": code, "window": window,
        "metrics": result,
    })


def index_financial_agg(scope: str, code: str) -> Any:
    """指数/行业季度财务聚合时序。

    Returns:
        success({scope, code, series: [{report_date, roe, net_margin,
        revenue_sum, net_profit_sum, assets_sum, sample_count}]}).
    """
    from src.infra.database.market.index_financial import (
        create_index_financial_repository,
    )
    repo = create_index_financial_repository()
    rows = repo.get_series(scope, code)
    series = [{
        "report_date": r.report_date.isoformat(),
        "roe": r.roe,
        "net_margin": r.net_margin,
        "gross_margin": r.gross_margin,
        "revenue_sum": r.revenue_sum,
        "net_profit_sum": r.net_profit_sum,
        "assets_sum": r.assets_sum,
        "sample_count": r.sample_count,
    } for r in rows]
    return responses.success({"scope": scope, "code": code, "series": series})


def fundamental_analysis(
    symbol: str, periods: int = 12
) -> Any:
    """个股基本面深度分析（LangGraph agent，同步返回结构化报告）。

    真实三大报表 + 估值分位 + 衍生指标注入 prompt，LLM 产出
    FundamentalReport 结构化报告。数据缺失不崩，对应字段标「无数据」。
    """
    import asyncio
    from src.domain.market.fundamental.agents.fundamental_analyst import (
        fundamental_analyst_node,
    )

    state = {"symbol": symbol, "periods": periods}
    try:
        result = asyncio.run(fundamental_analyst_node(state))
    except Exception as e:
        return responses.fail(msg=f"分析失败: {e}")
    if result.get("errors"):
        return responses.fail(msg="; ".join(result["errors"]))
    # 存库供历史对比 / 评分趋势
    try:
        from src.infra.database.market.fundamental_report import (
            create_fundamental_report_repository,
        )
        create_fundamental_report_repository().insert(symbol, result)
    except Exception:
        pass  # 存库失败不影响即时返回
    return responses.success(result)


def fundamental_history(symbol: str, limit: int = 20) -> Any:
    """某股票的基本面分析历史（评分趋势 / 回看）。"""
    from src.infra.database.market.fundamental_report import (
        create_fundamental_report_repository,
    )

    repo = create_fundamental_report_repository()
    rows = repo.list_history(symbol, limit)
    return responses.success({
        "symbol": symbol,
        "reports": [
            {
                "id": r.id,
                "created_at": (
                    r.created_at.isoformat() if r.created_at else None
                ),
                "overall_score": r.overall_score,
                "data_available": r.data_available,
                "one_line_conclusion": r.one_line_conclusion,
            }
            for r in rows
        ],
    })


def fundamental_report_detail(report_id: int) -> Any:
    """查看某份历史基本面分析报告的完整内容（回看）。"""
    from src.infra.database.market.fundamental_report import (
        create_fundamental_report_repository,
    )

    repo = create_fundamental_report_repository()
    row = repo.get_by_id(report_id)
    if row is None:
        return responses.fail(msg="报告不存在")
    return responses.success({
        "id": row.id,
        "symbol": row.symbol,
        "created_at": (
            row.created_at.isoformat() if row.created_at else None
        ),
        "overall_score": row.overall_score,
        "data_available": row.data_available,
        "report": row.report,
    })


def index_valuation_percentile_batch(
    scope: str = "sw",
    window: str = "10y",
    metric: str = "pe_ttm",
) -> Any:
    """批量返回所有行业/指数的单指标分位（用于排行页）。

    Returns:
        success({scope, window, metric, items: [{code, industry, current,
        percentile, sample_size}]}).
    """
    from src.infra.database.market.index_valuation import (
        create_index_valuation_repository,
    )
    from src.domain.market.fundamental.percentile import percentile_stats

    repo = create_index_valuation_repository()
    years = _P0B_WINDOW_YEARS.get(window, 10)
    end = date.today()
    start = date(end.year - years, end.month, end.day)

    # 取快照拿全部 code 列表（仅 sw 支持 batch）
    snapshot = _get_industry_snapshot_cached()
    if scope != "sw" or not snapshot:
        return responses.success({
            "scope": scope, "window": window, "metric": metric, "items": [],
        })

    items = []
    for item in snapshot:
        sw_code = item.get("sw_code")
        if not sw_code:
            continue
        try:
            rows = repo.get_sw_range(sw_code, start, end)
        except Exception as e:
            logger.warning("[ivp_batch] %s query failed: %s", sw_code, e)
            rows = []
        samples = [
            getattr(r, metric) for r in rows
            if getattr(r, metric) is not None and getattr(r, metric) > 0
        ]
        current = samples[-1] if samples else None
        stats = percentile_stats(samples, current) if current else None
        items.append({
            "code": sw_code,
            "industry": item.get("industry"),
            "current": current,
            "percentile": stats["percentile"] if stats else None,
            "sample_size": stats["sample_size"] if stats else 0,
        })
    # 按分位升序（None 排最后）
    items.sort(key=lambda x: (x["percentile"] is None, x["percentile"]))
    return responses.success({
        "scope": scope, "window": window, "metric": metric, "items": items,
    })


def quality_report(symbol: str) -> Any:
    """财务质量诊断报告（《股票投资课程》08/19 集"先筛掉 80% 垃圾公司"）。

    取最新三大报表合并快照（fetch_financial_snapshot，含 detail 科目扁平化），
    调用 fundamental.quality.compute_quality_report 输出：
      - metrics：收现比/净现比/现金覆盖/应收 vs 现金/费用毛利比/杜邦/负债拆分/
        重轻资产/存货营收比/商誉占比/现金流阶段
      - quality_score：0~100 透明加权综合分
      - red_flags：淘汰红线（cash_coverage<1 / 应收>现金 / 亏损 / 商誉高危）
      - verdict：pass / review / eliminate
    """
    from src.domain.market.strategy.longterm.data_loader import (
        fetch_financial_snapshot,
    )
    from src.domain.market.fundamental.quality import compute_quality_report

    snap = fetch_financial_snapshot([symbol], include_detail=True)
    fin = snap.get(symbol)
    if not fin:
        return responses.error(f"无 {symbol} 财报数据")

    report = compute_quality_report(fin)
    report["symbol"] = symbol
    report["report_date"] = (
        fin["report_date"].isoformat() if fin.get("report_date") else None
    )
    report["note"] = (
        "quality_score 为透明加权综合分(0~100)；red_flags 为淘汰红线；"
        "verdict=eliminate 建议排除。"
        "指标缺失(数据不足)对应字段为 None，不影响其它指标。"
    )
    return responses.success(report)


# 估值带支持的指标 → stock_valuation 列名
_VALUATION_BAND_METRICS = {
    "pe": "pe",
    "pe_ttm": "pe_ttm",
    "pb": "pb",
    "ps": "ps",
    "ps_ttm": "ps_ttm",
}


def valuation_band_report(
    symbol: str,
    metric: str = "pe_ttm",
    years: int = 8,
) -> Any:
    """均值±1σ 估值带四分类（《股票投资课程》21/24/25 集惯用的参数化估值方法）。

    取最近 years 年的 metric（PE/PB/PS）日序列，算均值 μ 与标准差 σ，
    把当前值放入 ±1σ 通道判四态：超跌 / 合理偏低 / 合理偏高 / 虚高。
    """
    from datetime import timedelta

    from src.infra.database.market.valuation import (
        create_stock_valuation_repository,
    )
    from src.domain.market.fundamental.valuation_band import valuation_band

    col = _VALUATION_BAND_METRICS.get(metric)
    if col is None:
        return responses.error(
            f"不支持的 metric '{metric}'，可选: {list(_VALUATION_BAND_METRICS)}"
        )

    try:
        repo = create_stock_valuation_repository()
        end = date.today()
        start = end - timedelta(days=365 * int(years) + 30)
        rows = repo.get_range(symbol, start, end)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")

    series = []
    current = None
    current_date = None
    for r in rows:
        v = getattr(r, col, None)
        if isinstance(v, (int, float)):
            series.append(float(v))
            current = float(v)  # rows 升序，最后一个即最新
            current_date = r.trade_date

    band = valuation_band(series, current) if current is not None else None
    data = {
        "symbol": symbol,
        "metric": metric,
        "years": years,
        "current": current,
        "current_date": (
            current_date.isoformat() if hasattr(current_date, "isoformat") else None
        ),
        "sample_size": len(series),
        "band": band,
        "note": (
            "band.state：超跌(<μ−σ) / 合理偏低 / 合理偏高 / 虚高(>μ+σ)。"
            "与 percentile（经验分位）互补——本方法为参数化(正态假设)。"
        ),
    }
    return responses.success(data)


def bank_report(symbol: str) -> Any:
    """银行业专项指标报告（《股票投资课程》20 集招行案例）。

    通用质量诊断 quality_report 面向工商企业，不覆盖银行监管指标。本端点
    从最新利润表 + 资产负债表的 detail JSONB 抽取银行科目（利息收支/手续费/
    发放贷款/吸收存款/贷款损失准备），调用 fundamental.bank_metrics 输出：

      - loan_deposit：存贷比（<0.80 资金闲置 / >1.10 吸储紧张）
      - nim：净利息收益率（>=2.5% 健康 / <1.8% 承压）
      - provision_coverage：拨备覆盖率（>=300% 头部 / <150% 监管红线）
      - npl：不良贷款率（<1% 一梯队 / >=2% 偏高）
      - revenue_split：净利息 + 手续费 + 其他营收拆分

    注意：``npl_balance``（不良贷款余额）为监管指标，不在三大报表；
    当前无该数据源时 provision_coverage / npl 为 None。
    """
    from src.domain.market.fundamental.bank_metrics import (
        extract_bank_subjects,
        compute_bank_report,
    )

    import psycopg2
    from psycopg2.extras import RealDictCursor
    from src.infra.database.sql_engine.dsn import get_dsn

    try:
        conn = psycopg2.connect(get_dsn())
    except Exception as e:  # noqa: BLE001
        return responses.error(f"数据库连接失败: {e}")

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 取最新利润表 + 资产负债表的 detail JSONB（银行科目跨两表）。
            cur.execute(
                """
                SELECT * FROM (
                    SELECT DISTINCT ON (statement_type)
                        statement_type, report_date, detail
                    FROM stock_financial_detail
                    WHERE symbol = %s AND statement_type IN ('income', 'balance')
                      AND detail IS NOT NULL
                    ORDER BY statement_type, report_date DESC
                ) t
                """,
                (symbol,),
            )
            rows = cur.fetchall()
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    if not rows:
        return responses.error(f"无 {symbol} 银行报表 detail 数据（可能非银行股）")

    # 合并两表 detail，抽取银行科目。
    merged: dict = {}
    report_date = None
    for r in rows:
        d = r.get("detail")
        if isinstance(d, dict):
            merged.update(d)
        rd = r.get("report_date")
        if report_date is None and rd is not None:
            report_date = rd if isinstance(rd, date) else (
                rd.date() if hasattr(rd, "date") else None
            )

    fin = extract_bank_subjects(merged)
    if not fin:
        return responses.error(
            f"{symbol} detail 中未识别到银行科目（利息收入/发放贷款等），可能非银行股"
        )

    report = compute_bank_report(fin)
    report["symbol"] = symbol
    report["report_date"] = report_date.isoformat() if report_date else None
    report["raw_subjects"] = fin
    report["note"] = (
        "银行监管指标（存贷比/NIM/拨备/NPL/营收拆分）。"
        "provision_coverage/npl 依赖不良贷款余额（监管数据，三大表无），"
        "缺数据时为 None。"
    )
    return responses.success(report)


def peg_report(symbol: str, growth: Optional[float] = None) -> Any:
    """PEG 比率（《股票投资课程》15/17 成长股估值核心）。

    PEG = PE / 盈利增速(%)。<1 低估、1~2 合理、>2 偏贵。
    取 stock_valuation 最新 PE_TTM；``growth`` 为预期盈利增速（小数），
    若未提供则尝试用营收历史 CAGR 代理（注：PEG 本应使用前瞻增速）。
    """
    from datetime import timedelta
    from src.infra.database.market.valuation import (
        create_stock_valuation_repository,
    )
    from src.domain.market.fundamental.valuation_extras import peg_ratio

    try:
        repo = create_stock_valuation_repository()
        end = date.today()
        rows = repo.get_range(symbol, end - timedelta(days=30), end)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询估值失败: {e}")

    pe = None
    for r in reversed(rows):
        v = getattr(r, "pe_ttm", None)
        if isinstance(v, (int, float)) and v > 0:
            pe = float(v)
            break
    if pe is None:
        return responses.error(f"无 {symbol} PE_TTM 数据")

    # growth 未提供时，用营收历史 CAGR 代理（取最近 4 期）。
    used_growth = growth
    source = "user_supplied"
    if used_growth is None:
        try:
            from src.domain.market.strategy.longterm.data_loader import (
                fetch_financial_history,
            )
            hist = fetch_financial_history([symbol], lookback_reports=4)
        except Exception:  # noqa: BLE001
            hist = {}
        # fetch_financial_history 无 revenue 字段，无法直接算营收 CAGR；
        # 此处降级：提示用户传入 growth。
        if not hist.get(symbol):
            return responses.error(
                "PEG 需盈利增速：请传 growth 查询参数（如 ?growth=0.20）"
            )

    r = peg_ratio(pe, used_growth)
    if r is None:
        return responses.error("PEG 计算失败（PE 或增速非法）")
    return responses.success({
        "symbol": symbol, "pe_ttm": pe, "growth": used_growth,
        "growth_source": source, "peg": r.peg, "verdict": r.verdict,
        "note": "PEG<1 低估 / 1~2 合理 / >2 偏贵；衰退/零增长股 PEG 不适用(n/a)。",
    })


def moat_report(symbol: str) -> Any:
    """定价权与护城河评分（《股票投资课程》09 商业模式 / 14 战略）。

    从财报历史取毛利率多期序列 + 当前 ROE/负债率，输出：
      - pricing_power：定价权综合分（水平+稳定性+趋势，0~100）
      - moat：护城河综合分（定价权50% + 资本回报30% + 低杠杆20%）
      - trend：毛利率时序趋势（斜率/波动率/是否改善）
    """
    from src.domain.market.fundamental.moat import (
        gross_margin_trend,
        pricing_power_score,
        moat_score,
    )
    from src.domain.market.strategy.longterm.data_loader import (
        fetch_financial_history,
    )

    try:
        hist = fetch_financial_history([symbol], lookback_reports=8)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询财报历史失败: {e}")

    periods = hist.get(symbol) or []
    gm_series = [p["gross_margin"] for p in periods
                 if p.get("gross_margin") is not None]
    if not gm_series:
        return responses.error(f"无 {symbol} 毛利率历史数据")

    trend = gross_margin_trend(gm_series)
    pp = pricing_power_score(gm_series)
    # 当前基本面（取最新一期的 ROE/负债率作 fin）
    latest = periods[-1] if periods else {}
    fin = {
        "net_profit": None,
        "equity": None,
        "debt_ratio": latest.get("debt_ratio"),
    }
    # ROE 已直接可得 → 用作 moat 资本回报 proxy（roic 缺失时）
    roe = latest.get("roe_weighted") or latest.get("roe_diluted")
    m = moat_score(gm_series, fin, roic=roe)

    return responses.success({
        "symbol": symbol,
        "gross_margin_series": gm_series,
        "trend": {
            "current": trend.current, "slope": trend.slope,
            "improving": trend.improving, "volatility": trend.volatility,
            "stable": trend.stable,
        },
        "pricing_power": pp,
        "moat": m,
        "note": (
            "pricing_power: 毛利率水平+稳定性+趋势；"
            "moat: 定价权50%+资本回报30%+低杠杆20%。verdict wide/narrow/none。"
        ),
    })


def fraud_signals_report(symbol: str) -> Any:
    """财务造假/异常红旗检测（《股票投资课程》21 检查清单）。

    取最近两期财报（合并利润表+资产负债表关键字段），检测四类红旗：
      - 营收-应收背离（压货冲业绩）
      - 净利-现金流背离（利润含金量低）
      - 存货异常积压
      - 毛利率突变（会计操纵嫌疑）
    severity: clean / watch / high_risk（>=2 项触发）。
    """
    from src.domain.market.fundamental.fraud_signals import detect_fraud_red_flags

    import psycopg2
    from psycopg2.extras import RealDictCursor
    from src.infra.database.sql_engine.dsn import get_dsn

    try:
        conn = psycopg2.connect(get_dsn())
    except Exception as e:  # noqa: BLE001
        return responses.error(f"数据库连接失败: {e}")

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH periods AS (
                    SELECT DISTINCT report_date FROM stock_financial_detail
                    WHERE symbol = %s AND statement_type = 'income'
                    ORDER BY report_date DESC LIMIT 2
                )
                SELECT report_date, statement_type, revenue, net_profit,
                       gross_profit, gross_margin, accounts_receivable,
                       inventory, ocf
                FROM stock_financial_detail
                WHERE symbol = %s AND report_date IN (SELECT report_date FROM periods)
                ORDER BY report_date
                """,
                (symbol, symbol),
            )
            rows = cur.fetchall()
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    # 按 report_date 合并 income/balance 字段
    by_date: dict = {}
    for r in rows:
        d = r["report_date"]
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        slot = by_date.setdefault(key, {})
        for k in ("revenue", "net_profit", "gross_profit", "gross_margin",
                  "accounts_receivable", "inventory", "ocf"):
            v = r.get(k)
            if v is not None and k not in slot:
                slot[k] = float(v)
    periods = list(by_date.values())
    if len(periods) < 2:
        return responses.error(f"无 {symbol} 足够的财报期数（需至少 2 期）")

    rep = detect_fraud_red_flags(periods)
    return responses.success({
        "symbol": symbol,
        "periods": list(by_date.keys()),
        "red_flags": [f.__dict__ for f in rep.red_flags],
        "triggered_count": rep.triggered_count,
        "severity": rep.severity,
        "note": "severity: clean(0) / watch(1) / high_risk(>=2)。需相邻两期对比。",
    })


def efficiency_report(symbol: str) -> Any:
    """经营效率趋势（《股票投资课程》08/13/19）。

    取最近 N 期财报，算三大周转率（应收/存货/总资产）的时序趋势：
      - improving   周转率上升（轻资产化/管理改善）
      - deteriorating 周转率下降（竞争力衰退早期信号）
      - stable      稳定
    """
    from src.domain.market.fundamental.efficiency_trend import (
        compute_turnovers, turnover_trend,
    )

    import psycopg2
    from psycopg2.extras import RealDictCursor
    from src.infra.database.sql_engine.dsn import get_dsn

    try:
        conn = psycopg2.connect(get_dsn())
    except Exception as e:  # noqa: BLE001
        return responses.error(f"数据库连接失败: {e}")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH periods AS (
                    SELECT DISTINCT report_date FROM stock_financial_detail
                    WHERE symbol = %s AND statement_type = 'income'
                    ORDER BY report_date DESC LIMIT 6
                )
                SELECT report_date, statement_type, revenue, operating_cost,
                       accounts_receivable, inventory, total_assets
                FROM stock_financial_detail
                WHERE symbol = %s AND report_date IN (SELECT report_date FROM periods)
                ORDER BY report_date
                """,
                (symbol, symbol),
            )
            rows = cur.fetchall()
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    by_date: dict = {}
    for r in rows:
        d = r["report_date"]
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        slot = by_date.setdefault(key, {})
        for k in ("revenue", "operating_cost", "accounts_receivable",
                  "inventory", "total_assets"):
            v = r.get(k)
            if v is not None and k not in slot:
                slot[k] = float(v)
    periods = list(by_date.values())
    if len(periods) < 2:
        return responses.error(f"无 {symbol} 足够的财报期数（需至少 2 期）")

    trend = turnover_trend(periods)
    per_period = []
    keys = list(by_date.keys())
    for i in range(1, len(periods)):
        per_period.append({"period": keys[i], **compute_turnovers(periods[i], periods[i - 1])})
    return responses.success({
        "symbol": symbol,
        "periods": keys,
        "per_period_turnovers": per_period,
        "trend": {
            "receivable": trend.receivable.__dict__ if trend.receivable else None,
            "inventory": trend.inventory.__dict__ if trend.inventory else None,
            "asset": trend.asset.__dict__ if trend.asset else None,
            "overall": trend.overall,
        },
        "note": "overall: improving(周转率上升=效率改善) / stable / deteriorating(下降=衰退信号)。",
    })


def style_report(symbol: str, growth: Optional[float] = None) -> Any:
    """成长 vs 价值风格分类（《股票投资课程》17）。

    综合 PE + 增速 + ROE 判定 growth/value/balanced + 质量标签
   （quality/fair/weak/trap_risk），附 PEG。
    PE 取 valuation 最新 PE_TTM；ROE 取财报最新；``growth`` 不传则提示。
    """
    from datetime import timedelta
    from src.infra.database.market.valuation import (
        create_stock_valuation_repository,
    )
    from src.domain.market.strategy.growth_value import classify_growth_value

    try:
        repo = create_stock_valuation_repository()
        end = date.today()
        vrows = repo.get_range(symbol, end - timedelta(days=30), end)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询估值失败: {e}")

    pe = None
    for r in reversed(vrows):
        v = getattr(r, "pe_ttm", None)
        if isinstance(v, (int, float)) and v > 0:
            pe = float(v)
            break

    roe = None
    try:
        from src.domain.market.strategy.longterm.data_loader import (
            fetch_financial_history,
        )
        hist = fetch_financial_history([symbol], lookback_reports=1)
        if hist.get(symbol):
            latest = hist[symbol][-1]
            roe = latest.get("roe_weighted") or latest.get("roe_diluted")
    except Exception:  # noqa: BLE001
        pass

    if pe is None:
        return responses.error(f"无 {symbol} PE_TTM 数据")
    if growth is None:
        return responses.error(
            "风格分类需盈利增速：请传 growth 查询参数（如 ?growth=0.20）"
        )

    style = classify_growth_value(growth, pe, roe)
    if style is None:
        return responses.error("分类失败（PE/增速非法）")
    return responses.success({
        "symbol": symbol, "pe_ttm": pe, "roe": roe, "growth": growth,
        "style": style.style, "quality": style.quality,
        "peg": style.peg, "rationale": style.rationale,
        "note": "style: growth/value/balanced(GARP)；quality: quality/fair/weak/trap_risk。",
    })


# ── 经典模型：流动性 / Altman Z / Beneish M ─────────────────────────────────

# detail JSONB 中流动性/破产模型相关科目（多候选兼容）。
_LIQUID_SUBJECT_CANDIDATES = {
    "current_assets": ["流动资产合计"],
    "current_liabilities": ["流动负债合计"],
    "trading_financial_assets": ["交易性金融资产"],
    "retained_earnings": ["未分配利润", "盈余公积和未分配利润"],
    "ebit": ["息税前利润", "利润总额"],
}


def _latest_financial_merged(symbol: str) -> Optional[dict]:
    """取 symbol 最新利润表+资产负债表，合并固定列与 detail 科目为单个 dict。

    返回 {report_date, <固定列>, <detail 扁平化>}；无数据返回 None。
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from src.infra.database.sql_engine.dsn import get_dsn

    try:
        conn = psycopg2.connect(get_dsn())
    except Exception:  # noqa: BLE001
        return None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM (
                    SELECT DISTINCT ON (statement_type)
                        statement_type, report_date, revenue, operating_cost,
                        operating_profit, net_profit, monetary_funds,
                        accounts_receivable, inventory, total_assets,
                        total_liabilities, equity, detail
                    FROM stock_financial_detail
                    WHERE symbol = %s AND statement_type IN ('income', 'balance')
                    ORDER BY statement_type, report_date DESC
                ) t
                """,
                (symbol,),
            )
            rows = cur.fetchall()
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    if not rows:
        return None
    merged: dict = {}
    report_date = None
    detail_merged: dict = {}
    for r in rows:
        if report_date is None and r.get("report_date") is not None:
            rd = r["report_date"]
            report_date = rd if isinstance(rd, date) else (
                rd.date() if hasattr(rd, "date") else None
            )
        for k in ("revenue", "operating_cost", "operating_profit", "net_profit",
                  "monetary_funds", "accounts_receivable", "inventory",
                  "total_assets", "total_liabilities", "equity"):
            v = r.get(k)
            if v is not None and k not in merged:
                merged[k] = float(v)
        d = r.get("detail")
        if isinstance(d, dict):
            detail_merged.update(d)
    merged["report_date"] = report_date
    merged["_detail"] = detail_merged
    return merged


def _extract_detail_amount(detail: dict, candidates: list[str]) -> Optional[float]:
    """从 detail dict 按候选科目名取金额（best-effort）。"""
    try:
        from src.infra.database.market.financial_full import parse_amount
    except Exception:  # noqa: BLE001
        def parse_amount(v):  # type: ignore
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    for k in candidates:
        if k in detail:
            v = parse_amount(detail[k])
            if v is not None:
                return v
    return None


def liquidity_report(symbol: str) -> Any:
    """流动性比率四件套（《股票投资课程》12/19）。

    流动比率/速动比率/现金比率/营运资本，verdict strong/healthy/stretched/risky。
    流动资产/负债合计从 detail 抽取。
    """
    from src.domain.market.fundamental.liquidity import compute_liquidity

    snap = _latest_financial_merged(symbol)
    if not snap:
        return responses.error(f"无 {symbol} 财报数据")
    detail = snap.get("_detail", {})
    ca = _extract_detail_amount(detail, _LIQUID_SUBJECT_CANDIDATES["current_assets"])
    cl = _extract_detail_amount(detail, _LIQUID_SUBJECT_CANDIDATES["current_liabilities"])
    tfa = _extract_detail_amount(detail, _LIQUID_SUBJECT_CANDIDATES["trading_financial_assets"])
    r = compute_liquidity(
        ca, cl,
        inventory=snap.get("inventory"),
        monetary_funds=snap.get("monetary_funds"),
        trading_financial_assets=tfa,
    )
    return responses.success({
        "symbol": symbol,
        "report_date": snap["report_date"].isoformat() if snap.get("report_date") else None,
        "current_ratio": r.current_ratio,
        "quick_ratio": r.quick_ratio,
        "cash_ratio": r.cash_ratio,
        "working_capital": r.working_capital,
        "verdict": r.verdict,
        "note": "current>2或quick>1.5 strong / 1.5~2 healthy / 1~1.5 stretched / <1 risky。",
    })


def z_score_report(symbol: str) -> Any:
    """Altman Z-Score 破产预测（《股票投资课程》21 检查清单补强）。

    Z>2.99 safe / 1.81~2.99 grey / <1.81 distress。
    市值取 stock_valuation.total_mv；留存收益/EBIT/流动资产从 detail。
    """
    from datetime import timedelta
    from src.infra.database.market.valuation import (
        create_stock_valuation_repository,
    )
    from src.domain.market.fundamental.classic_models import altman_z_score

    snap = _latest_financial_merged(symbol)
    if not snap:
        return responses.error(f"无 {symbol} 财报数据")

    market_cap = None
    try:
        repo = create_stock_valuation_repository()
        end = date.today()
        vrows = repo.get_range(symbol, end - timedelta(days=30), end)
        for r in reversed(vrows):
            mv = getattr(r, "total_mv", None)
            if isinstance(mv, (int, float)) and mv > 0:
                market_cap = float(mv)
                break
    except Exception:  # noqa: BLE001
        pass

    detail = snap.get("_detail", {})
    re_ = _extract_detail_amount(detail, _LIQUID_SUBJECT_CANDIDATES["retained_earnings"])
    ebit = _extract_detail_amount(detail, _LIQUID_SUBJECT_CANDIDATES["ebit"])
    ca = _extract_detail_amount(detail, _LIQUID_SUBJECT_CANDIDATES["current_assets"])
    cl = _extract_detail_amount(detail, _LIQUID_SUBJECT_CANDIDATES["current_liabilities"])

    z = altman_z_score(
        snap, market_cap=market_cap, retained_earnings=re_,
        current_assets=ca, current_liabilities=cl, ebit=ebit,
    )
    if z is None:
        return responses.error(
            f"{symbol} 数据不足（需 total_assets/liabilities/revenue + market_cap）"
        )
    return responses.success({
        "symbol": symbol,
        "report_date": snap["report_date"].isoformat() if snap.get("report_date") else None,
        "z": round(z.z, 4), "verdict": z.verdict,
        "factors": {"X1_WC_TA": z.x1, "X2_RE_TA": z.x2, "X3_EBIT_TA": z.x3,
                    "X4_MV_TL": z.x4, "X5_SALES_TA": z.x5},
        "note": "Z>2.99 safe / 1.81~2.99 grey / <1.81 distress（破产风险）。"
                "X1/X2 缺数据时近似或置0，精度降低。",
    })


def m_score_report(symbol: str) -> Any:
    """Beneish M-Score 盈余操纵检测（《股票投资课程》21 检查清单补强）。

    M>-1.78 操纵嫌疑 / -1.78~-2.22 观察 / <-2.22 clean。
    取最近两期对比；折旧/销管费缺时 partial=True。
    """
    from src.domain.market.fundamental.classic_models import beneish_m_score

    import psycopg2
    from psycopg2.extras import RealDictCursor
    from src.infra.database.sql_engine.dsn import get_dsn

    try:
        conn = psycopg2.connect(get_dsn())
    except Exception as e:  # noqa: BLE001
        return responses.error(f"数据库连接失败: {e}")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH periods AS (
                    SELECT DISTINCT report_date FROM stock_financial_detail
                    WHERE symbol = %s AND statement_type = 'income'
                    ORDER BY report_date DESC LIMIT 2
                )
                SELECT report_date, statement_type, revenue, accounts_receivable,
                       gross_profit, gross_margin, current_assets, total_assets,
                       net_profit, ocf, total_liabilities, detail
                FROM stock_financial_detail
                WHERE symbol = %s AND report_date IN (SELECT report_date FROM periods)
                ORDER BY report_date
                """,
                (symbol, symbol),
            )
            rows = cur.fetchall()
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    by_date: dict = {}
    for r in rows:
        d = r["report_date"]
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        slot = by_date.setdefault(key, {"_detail": {}})
        for k in ("revenue", "accounts_receivable", "gross_profit", "gross_margin",
                  "current_assets", "total_assets", "net_profit", "ocf", "total_liabilities"):
            v = r.get(k)
            if v is not None and k not in slot:
                slot[k] = float(v)
        dd = r.get("detail")
        if isinstance(dd, dict):
            slot["_detail"].update(dd)
    periods = list(by_date.values())
    if len(periods) < 2:
        return responses.error(f"无 {symbol} 足够的财报期数（需至少 2 期）")

    curr, prev = periods[-1], periods[-2]
    m = beneish_m_score(curr, prev)
    if m is None:
        return responses.error(f"{symbol} 数据不足，无法算 M-Score")
    return responses.success({
        "symbol": symbol,
        "periods": list(by_date.keys()),
        "m": round(m.m, 4) if m.m is not None else None,
        "verdict": m.verdict,
        "partial": m.partial,
        "components": m.components,
        "note": "M>-1.78 操纵嫌疑 / -1.78~-2.22 观察 / <-2.22 clean。"
                "partial=True 表示缺折旧/销管费(DEPI/SGAI)项，精度降低。",
    })


def concentration_report(symbol: str) -> Any:
    """筹码集中度（《股票投资课程》18/21）。

    读股东户数历史，判筹码集中/分散趋势：户数连续减少=主力收集(利好)，
    增加=散户化(利空)。附人均持股变化。
    """
    from src.infra.database.market.shareholder_count import (
        create_shareholder_count_repository,
    )
    from src.domain.market.equity.concentration import (
        concentration_trend, per_capita_holding,
    )

    try:
        repo = create_shareholder_count_repository()
        rows = repo.get_history(symbol, limit=12)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询股东户数失败: {e}")

    if not rows:
        return responses.error(f"无 {symbol} 股东户数数据（需先同步 shareholder_count）")

    counts = [r.holder_count for r in rows if r.holder_count]
    dates = [r.report_date.isoformat() if r.report_date else None for r in rows]
    trend = concentration_trend(counts)
    # 人均持股（用最新一期 per_capita_holding 列）
    latest_pch = rows[-1].per_capita_holding if rows else None
    pch = per_capita_holding(
        None, counts
    )  # shares 缺，仅算户数维度；人均用表内列
    return responses.success({
        "symbol": symbol,
        "report_dates": dates,
        "holder_counts": counts,
        "latest_per_capita_holding": latest_pch,
        "trend": trend.__dict__ if trend else None,
        "verdict": trend.verdict if trend else None,
        "note": "verdict: concentrating(户数连减=筹码集中,主力收集利好) / "
                "dispersing(户数连增=散户化) / stable。",
    })


def common_size(
    symbol: str,
    statement_type: str = "income",
    period: str = "month",
    limit: int = 12,
) -> Any:
    """同型分析（Common-Size）：三大报表全科目 ÷ 基准值 → 结构百分比时序。

    基准：income=营业总收入；balance=资产合计；cashflow=现金流入总额
    （经营+投资+筹资三项流入小计之和）。科目来自 detail JSONB（原始累计口径）。

    Args:
        symbol:         sh600519 / 00700 / AAPL
        statement_type: income / balance / cashflow
        period:         month=原始报告期累计口径（默认）；year=只看年报期。
                        不提供 quarter——detail 全科目无法正确单季差分。
        limit:          返回最近 N 期（默认 12）
    """
    from src.domain.market.fundamental.common_size import common_size_series
    from src.infra.database.market.financial_full import (
        create_financial_detail_repository,
    )
    repo = create_financial_detail_repository()
    try:
        rows = repo.get_history(symbol, statement_type)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    if not rows:
        return responses.error(f"无 {symbol} {statement_type} 数据")

    dicts = [
        {"report_date": r.report_date, "detail": getattr(r, "detail", None)}
        for r in rows
    ]
    if period == "year":
        dicts = filter_year_only(dicts)
    if len(dicts) > limit:
        dicts = dicts[-limit:]

    result = common_size_series(dicts, statement_type)
    data = {
        "symbol": symbol,
        "statement_type": statement_type,
        "base_name": result["base_name"],
        "total_periods": len(rows),
        "periods": result["periods"],
    }
    if not result["periods"]:
        data["note"] = "各报告期均缺少基准科目，无法计算结构占比"
    return responses.success(data)


def _resolve_cost_of_equity(symbol: str):
    """行业年报 ROE 中位数 → (小数, 说明note)；无归属/无年报截面 → (None, None)。

    年报期口径：截面 ROE 为报告期累计未年化，季度期会低估
    （实测 Q1 中位数≈全年 1/4），必须取 12-31 年报期且 sample_count≥8。
    二级优先，无年报期截面时降一级。整体 try 包裹——解析失败不阻断主指标。
    """
    try:
        from src.infra.database.market.sw_industry import (
            create_sw_industry_repository,
        )
        repo = create_sw_industry_repository()
        m = repo.get_member(symbol)
        if not m:
            return None, None
        for level, code in ((2, m["sw_code_l2"]), (1, m["sw_code_l1"])):
            secs = repo.fetch_sections(code, level, limit=40)
            annual = next(
                (s for s in secs
                 if s["report_date"].endswith("12-31")
                 and (s.get("sample_count") or 0) >= 8),
                None,
            )
            if annual:
                roe = ((annual.get("distribution") or {}).get("roe") or {})
                med = roe.get("median")
                if med is not None:
                    return med / 100.0, (
                        f"权益成本={annual['sw_name']}"
                        f"({'一级' if level == 1 else '二级'}"
                        f"{annual['report_date']}年报)ROE中位数{med}%；"
                        f"债务成本假设4.5%"
                    )
    except Exception:  # noqa: BLE001
        return None, None
    return None, None


def ratios(symbol: str, period: str = "month", limit: int = 12) -> Any:
    """比率分析（Ratio Analysis）：27 个核心财务比率多期时序。

    五组：盈利（毛利率/净利率/ROE/ROA/ROIC）、偿债（资产负债率/流动/速动/利息保障）、
    营运（存货/应收/应付/流动资产/固定资产/总资产周转率及周转天数）、
    成长（营收/净利/总资产同比）、
    资本成本（投资资本/WACC/经济利润——WACC 需权益成本，取申万行业年报期
    截面 ROE 中位数注入，无归属/解析失败则 WACC 与经济利润为 None）。

    口径：报告期累计不年化；ROE/ROA/周转率分母=期初期末平均余额；
    同比需去年同期在场。取数：income+balance 两表按 report_date 内连接
    （比率不涉及现金流量表）。先在全量历史上计算（平均余额/同比需要
    前序期），再截最近 limit 期——与 common-size 的"先截再算"相反。

    Args:
        symbol: sh600519 / 00700 / AAPL
        period: month=原始报告期累计口径（默认）；year=只看年报期
        limit:  返回最近 N 期（默认 12）
    """
    from src.domain.market.fundamental.ratio_analysis import (
        FIXED_FIELDS,
        ratio_series,
    )
    from src.infra.database.market.financial_full import (
        create_financial_detail_repository,
    )
    repo = create_financial_detail_repository()
    try:
        income_rows = repo.get_history(symbol, "income")
        balance_rows = repo.get_history(symbol, "balance")
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    if not income_rows or not balance_rows:
        return responses.error(f"无 {symbol} 财务报表数据")

    balance_by_date = {r.report_date: r for r in balance_rows}
    records: list[dict] = []
    for r in income_rows:
        b = balance_by_date.get(r.report_date)
        if b is None:
            continue  # 内连接：两表同报告期才计算
        fin = {}
        for f in sorted(FIXED_FIELDS):
            v = getattr(r, f, None)
            if not isinstance(v, (int, float)):
                # 非数值（真实行不会发生；防御 mock 自动属性遮蔽 balance 值）
                v = getattr(b, f, None)
            fin[f] = v if isinstance(v, (int, float)) else None
        records.append({
            "report_date": r.report_date,
            "fin": fin,
            "details": [getattr(r, "detail", None), getattr(b, "detail", None)],
        })
    if period == "year":
        records = filter_year_only(records)

    cost_of_equity, coe_note = _resolve_cost_of_equity(symbol)
    result = ratio_series(records, cost_of_equity)
    data = {
        "symbol": symbol,
        "total_periods": len(records),
        "groups": result["groups"],
        "periods": result["periods"][:limit],  # 已降序，截最新 N 期
    }
    if coe_note:
        data["note"] = coe_note
    if not data["periods"]:
        data["note"] = "无可用报告期（income 与 balance 报告期无交集）"
    return responses.success(data)


def industry_members(symbol: str) -> Any:
    """个股申万行业归属（波特五力行业分析的数据入口，课程 14 集）。"""
    from src.infra.database.market.sw_industry import (
        create_sw_industry_repository,
    )
    try:
        repo = create_sw_industry_repository()
        m = repo.get_member(symbol)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    if not m:
        return responses.error(f"{symbol} 无申万行业归属（非 A 股成分或未同步）")
    return responses.success({
        "symbol": symbol,
        "sw_l1": {"code": m["sw_code_l1"], "name": m["sw_name_l1"]},
        "sw_l2": {"code": m["sw_code_l2"], "name": m["sw_name_l2"]},
        "weight": m.get("weight"),
        "included_date": m.get("included_date"),
    })


def industry_peers(symbol: str, level: int = 2, limit: int = 13) -> Any:
    """同行截面：行业归属 + 截面时序 + 同行明细 + 目标股相对位置。

    level 默认 2（二级）；同行明细取最新充足期（sample_count≥8，
    跳过披露季中段样本过少的最新期），全窗口均无充足期才降一级，
    两种情况都在 industry.degraded/note 标注。sections 降序截 limit 期
    （实时 JOIN，毫秒级）。
    """
    from src.domain.market.fundamental.industry_cross_section import (
        peer_ranks,
    )
    from src.infra.database.market.sw_industry import (
        create_sw_industry_repository,
    )
    try:
        repo = create_sw_industry_repository()
        m = repo.get_member(symbol)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    if not m:
        return responses.error(f"{symbol} 无申万行业归属（非 A 股成分或未同步）")

    sw_code = m["sw_code_l2"] if level == 2 else m["sw_code_l1"]
    degraded, note = False, None
    try:
        sections = repo.fetch_sections(sw_code, level, limit=200)
        # 最新充足期：跳过披露季中段样本过少的最新期（如中报只披露2家）
        pick = next(
            (s for s in sections if (s.get("sample_count") or 0) >= 8),
            None,
        )
        if pick is None and level == 2:
            level, sw_code = 1, m["sw_code_l1"]
            degraded, note = True, "二级样本不足，已降为一级行业"
            sections = repo.fetch_sections(sw_code, 1, limit=200)
            pick = next(
                (s for s in sections if (s.get("sample_count") or 0) >= 8),
                sections[0] if sections else None,
            )
            if pick is not None and sections[0] is not pick:
                note = (f"二级样本不足，已降为一级行业；"
                        f"同行明细采用 {pick['report_date']} 期")
        elif pick is not None and sections[0] is not pick:
            note = f"最新报告期样本不足，同行明细采用 {pick['report_date']} 期"
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    if not sections or pick is None:
        return responses.error("行业截面数据未同步，请先运行 "
                               "sw_industry_cross_section_sync")

    latest = pick["report_date"]
    try:
        peers = repo.fetch_peer_details(sw_code, level, latest)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")

    ranked = peer_ranks(peers, symbol)
    data = {
        "symbol": symbol,
        "industry": {
            "level": level, "code": sw_code,
            "name": sections[0].get("sw_name"),
            "parent": (
                {"code": m["sw_code_l1"], "name": m["sw_name_l1"]}
                if level == 2 else None
            ),
            "degraded": degraded, "note": note,
        },
        "sections": sections[:limit],
        "peers": ranked["peers"],
        "target": ranked["target"],
    }
    if ranked["target"] is None:
        data["note"] = "目标股有归属但最新期无财务数据"
    return responses.success(data)


def cashflow_analysis(symbol: str, period: str = "month",
                      limit: int = 12) -> Any:
    """现金流分析（Cashflow Analysis）：11 个现金流指标多期时序。

    三组：盈利质量（净现比/收现比/FCF率）、增长趋势（OCF/FCF/净利同比）、
    现金流结构（经营/投资/筹资净额、资本开支、资本开支强度）。

    口径：报告期累计不年化；同比需去年同期在场。取数：income+cashflow
    两表按 report_date 内连接（不涉及 balance）。fcf 列=筹资活动净额
    （非自由现金流）；FCF 用 free_cash_flow 列，缺列时兜底 ocf-|capex|。
    先在全量历史上计算（同比需要前序期），再截最近 limit 期。

    Args:
        symbol: sh600519 / 00700 / AAPL
        period: month=原始报告期累计口径（默认）；year=只看年报期
        limit:  返回最近 N 期（默认 12）
    """
    from src.domain.market.fundamental.cashflow_analysis import (
        FIXED_FIELDS,
        cashflow_series,
    )
    from src.infra.database.market.financial_full import (
        create_financial_detail_repository,
    )
    repo = create_financial_detail_repository()
    try:
        income_rows = repo.get_history(symbol, "income")
        cashflow_rows = repo.get_history(symbol, "cashflow")
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    if not income_rows or not cashflow_rows:
        return responses.error(f"无 {symbol} 财务报表数据")

    cashflow_by_date = {r.report_date: r for r in cashflow_rows}
    records: list[dict] = []
    for r in income_rows:
        c = cashflow_by_date.get(r.report_date)
        if c is None:
            continue  # 内连接：两表同报告期才计算
        fin = {}
        for f in sorted(FIXED_FIELDS):
            v = getattr(r, f, None)
            fin[f] = v if v is not None else getattr(c, f, None)
        records.append({
            "report_date": r.report_date,
            "fin": fin,
            # cashflow detail 在前：cash_from_sales 候选优先查现金流量表
            "details": [getattr(c, "detail", None),
                        getattr(r, "detail", None)],
        })
    if period == "year":
        records = filter_year_only(records)

    result = cashflow_series(records)
    data = {
        "symbol": symbol,
        "total_periods": len(records),
        "groups": result["groups"],
        "periods": result["periods"][:limit],  # 已降序，截最新 N 期
    }
    if not data["periods"]:
        data["note"] = "无可用报告期（income 与 cashflow 报告期无交集）"
    elif all(v is None for v in data["periods"][0]["ratios"].values()):
        # 数据缺口（如港股现金流量表固定列未摄取）：期次在但指标全
        # None → 附解释，避免前端渲染纯"—"墙
        data["note"] = "现金流固定列未摄取（该市场数据待补）"
    return responses.success(data)


def five_forces_report(symbol: str) -> Any:
    """波特五力评分（课程 14 集）：三力量化+两力行业因子。

    串调既有 ratios/cashflow_analysis/industry_peers 内部函数取数
    （不重复 SQL），拼 dict 给纯函数 five_forces。子调用失败对应力
    降级不整体 error。
    """
    import json

    from src.domain.market.fundamental.five_forces import five_forces

    def _periods(resp):
        try:
            return json.loads(resp.body).get("data", {}).get("periods", [])
        except Exception:  # noqa: BLE001
            return []

    try:
        ratios_resp = ratios(symbol, "year", 12)
        ratio_periods = _periods(ratios_resp)
    except Exception:  # noqa: BLE001
        ratio_periods = []
    try:
        cashflow_periods = _periods(cashflow_analysis(symbol, "year", 12))
    except Exception:  # noqa: BLE001
        cashflow_periods = []
    try:
        ind_body = json.loads(industry_peers(symbol).body).get("data", {})
        industry = ind_body if ind_body.get("industry") else None
    except Exception:  # noqa: BLE001
        industry = None

    if not ratio_periods and industry is None:
        return responses.error(f"{symbol} 无可用财务与行业数据")

    result = five_forces({
        "ratios": ratio_periods,
        "cashflow": cashflow_periods,
        "industry": industry,
    })
    data = {"symbol": symbol, **result}
    return responses.success(data)


# ════════════════════════════════════════════════════════════════════════════
#  市值与业绩增长趋势（指数/个股）：营收/归母净利三口径 + 报告期末总市值
#  指数源 index_financial_quarterly + index_valuation_daily；
#  个股源 stock_financial_detail + stock_valuation。单位统一亿元。
# ════════════════════════════════════════════════════════════════════════════

_mcg_cache: dict = {"data": {}, "ts": {}}
_MCG_CACHE_TTL = 3600  # 秒（成分/财务周更，1h 缓存无害）
# 披露率门控：期样本数低于序列满覆盖的该比例 → 该期柱隐藏（负柱假象）
_MCG_DISCLOSE_MIN_RATIO = 0.8


def _mcg_round(v) -> Optional[float]:
    return round(v, 2) if isinstance(v, (int, float)) else None


def _mcg_index_names() -> dict:
    """配置段宽基指数 code → name。"""
    from conf import app_config
    return {
        it.code: it.name
        for it in app_config.quant_universe.index_constituents
    }


def _mcg_fmt_rows(rows: list) -> list:
    out = []
    for r in rows:
        rd = r.get("report_date")
        rd = rd.isoformat() if hasattr(rd, "isoformat") else str(rd)[:10]
        out.append({
            "report_date": rd,
            "revenue": _mcg_round(r.get("revenue")),
            "net_profit": _mcg_round(r.get("net_profit")),
        })
    return out


def _mcg_bars(cum: list) -> dict:
    """累计序列（revenue/net_profit，亿）→ 三口径 bars。"""
    from src.domain.market.fundamental.market_cap_growth import (
        to_quarterly,
        to_ttm,
    )
    return {
        "quarter": _mcg_fmt_rows(to_quarterly(cum)),
        "cumulative": _mcg_fmt_rows(cum),
        "ttm": _mcg_fmt_rows(to_ttm(cum)),
    }


def _mcg_cached(key: str, compute):
    """1h 结果缓存（仿 _valpct_cache）。"""
    now = time.time()
    if (key in _mcg_cache["data"]
            and now - _mcg_cache["ts"].get(key, 0) < _MCG_CACHE_TTL):
        return _mcg_cache["data"][key]
    result = compute()
    _mcg_cache["data"][key] = result
    _mcg_cache["ts"][key] = now
    return result


def market_cap_growth_index(code: str, years: int = 10) -> Any:
    """指数市值与业绩增长趋势（营收/归母净利 单季/累计/TTM + 总市值）。"""
    names = _mcg_index_names()
    if code not in names:
        # 参数/不存在类走 fail（HTTP 200 + code=1，同 "invalid as_of" 惯例）
        return responses.fail(
            f"未配置的指数: {code}（见 quant_universe.index_constituents）"
        )

    def _compute() -> Any:
        from dateutil.relativedelta import relativedelta
        from src.domain.market.fundamental.market_cap_growth import align_mv
        from src.infra.database.market.index_financial import (
            create_index_financial_repository,
        )
        from src.infra.database.market.index_valuation import (
            create_index_valuation_repository,
        )
        end = date.today()
        # relativedelta 而非 date(y-years, m, d)：2-29 运行日会 ValueError。
        start = end - relativedelta(years=years)
        # 多取一年做差分基准：窗口首期非Q1时（如years截到Q3），
        # transform_to_quarter 对无上期的首期原样透出累计值，会把
        # 9个月累计当成单季柱画出来。
        base_start = end - relativedelta(years=years + 1)
        fin_rows = create_index_financial_repository().get_series(
            "index", code, start=base_start,
        )
        # 披露率门控：财报披露季最新期常只有部分公司出报告（如中报截止
        # 8/31，8月底或仅 34/300 家入库）——"当期 N 家累计 − 上期全量累计"
        # 会差分出巨额负柱。以序列内最大样本数为满覆盖，不足 80% 的期
        # 置 None（三口径全空，柱不画）；市值线不受财报披露影响照常返回。
        max_cnt = max((r.sample_count or 0 for r in fin_rows), default=0)
        start_iso = start.isoformat()
        cum = []
        for r in fin_rows:
            partial = (max_cnt > 0
                       and (r.sample_count or 0)
                       < _MCG_DISCLOSE_MIN_RATIO * max_cnt)
            cum.append({
                "report_date": r.report_date,
                "revenue": None if partial else r.revenue_sum,
                "net_profit": None if partial else r.net_profit_sum,
            })
        mv_rows = create_index_valuation_repository().get_index_range(
            code, start, end,
        )
        monthly = [
            {"date": r.trade_date, "total_mv": r.total_mv} for r in mv_rows
        ]

        def _win(rows: list) -> list:
            return [r for r in rows
                    if str(r["report_date"])[:10] >= start_iso]

        # note 计数只算窗口内被隐藏的期（基准年旧期不展示,不计入）
        hidden = sum(
            1 for r, c in zip(fin_rows, cum)
            if c["revenue"] is None and str(r.report_date)[:10] >= start_iso
        )

        payload = {
            "kind": "index",
            "code": code,
            "name": names.get(code),
            "as_of": end.isoformat(),
            "bars": {k: _win(v) for k, v in _mcg_bars(cum).items()},
            # align_mv 原样透传（表存 4 位），规格要求亿元 2 位 → 此处 round。
            "mv_series": _win([
                {**p, "total_mv": _mcg_round(p.get("total_mv"))}
                for p in align_mv(monthly, [r["report_date"] for r in cum])
            ]),
            "sample_count": _win([
                {"report_date": r.report_date.isoformat(),
                 "count": r.sample_count} for r in fin_rows
            ]),
        }
        if hidden:
            payload["note"] = (
                f"{hidden}个报告期披露率不足"
                f"{int(_MCG_DISCLOSE_MIN_RATIO * 100)}%（财报披露期，"
                f"该期柱已隐藏，样本数见 sample_count）"
            )
        return responses.success(payload)

    return _mcg_cached(f"index:{code}:{years}", _compute)


def market_cap_growth_stock(symbol: str, years: int = 10) -> Any:
    """个股市值与业绩增长趋势（口径同指数版，单位统一亿元）。"""
    if not symbol.startswith(("sh", "sz", "bj")):
        return responses.success({
            "kind": "stock", "code": symbol, "name": None, "as_of": None,
            "bars": {"quarter": [], "cumulative": [], "ttm": []},
            "mv_series": [],
            "note": "仅支持A股个股（stock_valuation 只有A股市值）",
        })

    def _compute() -> Any:
        from dateutil.relativedelta import relativedelta
        from src.infra.database.market.financial_full import (
            create_financial_detail_repository,
        )
        from src.infra.database.market.valuation import (
            create_stock_valuation_repository,
        )
        end = date.today()
        start = end - relativedelta(years=years)
        # 同指数版：多取一年差分基准，避免窗口首期累计值被当单季。
        base_start = end - relativedelta(years=years + 1)
        fin_rows = create_financial_detail_repository().get_history(
            symbol, "income", base_start, None,
        )
        cum = [{
            "report_date": r.report_date,
            "revenue": r.revenue / 1e8 if r.revenue is not None else None,
            "net_profit": (r.net_profit_parent / 1e8
                           if r.net_profit_parent is not None else None),
        } for r in fin_rows]
        val_repo = create_stock_valuation_repository()
        # 单区间查询 + 双指针拾取：替代逐报告期 get_as_of 的 N+1 查询
        # （44 次 × ~60ms ≈ 数秒 → 一次 ~270ms；口径同 get_as_of：
        #   每个报告期取 trade_date <= report_date 的最近一行）。
        try:
            val_rows = val_repo.get_range(symbol, start, end)
        except Exception as e:
            logger.warning("mcg mv query failed %s: %s", symbol, e)
            val_rows = []
        mv_series = []
        cur, i = None, 0
        for r in fin_rows:                      # fin_rows 升序
            while (i < len(val_rows)
                   and val_rows[i].trade_date <= r.report_date):
                cur = val_rows[i]
                i += 1
            mv_series.append({
                "report_date": r.report_date.isoformat(),
                "total_mv": _mcg_round(cur.total_mv / 1e8)
                if cur is not None and cur.total_mv is not None else None,
            })
        start_iso = start.isoformat()

        def _win(rows: list) -> list:
            return [r for r in rows
                    if str(r["report_date"])[:10] >= start_iso]

        return responses.success({
            "kind": "stock",
            "code": symbol,
            "name": None,
            "as_of": end.isoformat(),
            "bars": {k: _win(v) for k, v in _mcg_bars(cum).items()},
            "mv_series": _win(mv_series),
        })

    return _mcg_cached(f"stock:{symbol}:{years}", _compute)


def index_pe_trend(code: str, years: int = 8) -> Any:
    """指数整体法市盈率趋势（月末 PE 序列 + 窗口均值/±σ 参考线统计）。"""
    names = _mcg_index_names()
    if code not in names:
        return responses.fail(
            f"未配置的指数: {code}（见 quant_universe.index_constituents）"
        )

    def _compute() -> Any:
        from dateutil.relativedelta import relativedelta
        from src.domain.market.fundamental.index_pe import mean_std
        from src.infra.database.market.index_valuation import (
            create_index_valuation_repository,
        )
        end = date.today()
        # years<=0 = 全部历史（同估值分位 "all" 惯例：极早起点回溯全表）
        start = (date(1990, 1, 1) if years <= 0
                 else end - relativedelta(years=years))
        # 只取本功能自算的整体法序列（source='computed'）；表内另有遗留
        # legu 日频外部口径孤儿数据，混入会扭曲序列与均值/±σ统计。
        rows = create_index_valuation_repository().get_index_range(
            code, start, end, source="computed",
        )
        series = [
            {"date": r.trade_date.isoformat(), "pe": _mcg_round(r.pe_ttm)}
            for r in rows
        ]
        ms = mean_std([r.pe_ttm for r in rows])
        stats = None
        if ms:
            stats = {
                "mean": _mcg_round(ms["mean"]),
                "std": _mcg_round(ms["std"]),
                "high": _mcg_round(ms["mean"] + ms["std"]),
                "low": _mcg_round(ms["mean"] - ms["std"]),
                "sample_size": ms["sample_size"],
            }
        current = None
        for p in reversed(series):
            if p["pe"] is not None:
                current = p
                break
        payload = {
            "kind": "index_pe",
            "code": code,
            "name": names.get(code),
            "as_of": end.isoformat(),
            "series": series,
            "stats": stats,
            "current": current,
        }
        null_n = sum(1 for p in series if p["pe"] is None)
        if null_n:
            payload["note"] = (
                f"{null_n}个月度点无TTM净利（披露断档或净利≤0），已断线"
            )
        return responses.success(payload)

    return _mcg_cached(f"ipe:{code}:{years}", _compute)


# ════════════════════════════════════════════════════════════════════════════
#  五法估值（《股票投资课程》15 集）：绝对估值 DCF/DDM/净资产 + 相对估值
#  类比同行/乘数历史。DCF（/dcf/）与乘数历史（/valuation-percentile/）
#  已有端点，以下补充 DDM / 净资产分析 / 类比同行三个 handler。
# ════════════════════════════════════════════════════════════════════════════

def _annual_shares(symbol: str) -> tuple:
    """用最新年报「归母净利 / 基本EPS」反推股本（加权口径，近似）。

    Returns:
        (shares, report_date)；任一环节数据缺失 → (None, None)。
    """
    import psycopg2

    from src.infra.database.sql_engine.dsn import get_dsn

    try:
        conn = psycopg2.connect(get_dsn())
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT net_profit_parent, basic_eps, report_date
                FROM stock_financial_detail
                WHERE symbol = %s AND statement_type = 'income'
                  AND EXTRACT(MONTH FROM report_date) = 12
                  AND net_profit_parent > 0 AND basic_eps > 0
                ORDER BY report_date DESC LIMIT 1
                """,
                (symbol,),
            )
            row = cur.fetchone()
        conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("_annual_shares query failed: %s", e)
        return None, None
    if not row:
        return None, None
    shares = row[0] / row[1]
    return shares, row[2].isoformat()


def ddm_valuation(
    symbol: str,
    growth_rate: float = 0.02,
    discount_rate: float = 0.055,
) -> Any:
    """股利折现模型 DDM（Gordon 恒定增长）内在价值 + 安全边际。

    《股票投资课程》15 集：适用于确定性高、成长性低的红利型公司
    （课程案例：长江电力 2024 分红 230 亿、r=5.5%、g=2% → 约 6703 亿）。

    D₀（TTM 分红总额）两级来源：
      1. dps_ttm（stock_dividend 明细按除权除息日聚合）× 股本
         （股本 = 最新年报归母净利/基本EPS，加权口径近似）
      2. 兜底：total_mv × dv_ttm/100（stock_valuation 落地股息率）
    """
    from src.domain.market.fundamental.ddm import (
        DEFAULT_DISCOUNT_RATE,
        DEFAULT_GROWTH_RATE,
        ddm_intrinsic_value,
    )
    from src.domain.market.fundamental.dcf import margin_of_safety
    from src.domain.market.fundamental.dividend_yield import (
        ttm_dividend_per_share,
    )
    from src.infra.database.market.dividend import (
        create_stock_dividend_repository,
    )

    growth_rate = growth_rate if growth_rate is not None \
        else DEFAULT_GROWTH_RATE
    discount_rate = discount_rate if discount_rate is not None \
        else DEFAULT_DISCOUNT_RATE

    data: dict = {"symbol": symbol}
    try:
        # TTM 每股派息（按除权除息日）
        try:
            repo = create_stock_dividend_repository()
            hist = repo.get_history(symbol)
            dividends = [
                {"ex_date": r.ex_date, "div_per_share": r.div_per_share}
                for r in hist
            ]
        except Exception as e:  # noqa: BLE001
            dividends = []
            logger.warning("ddm dividend history failed: %s", e)
        dps_ttm = ttm_dividend_per_share(dividends, date.today())

        shares, shares_report = _annual_shares(symbol)

        import psycopg2

        from src.infra.database.sql_engine.dsn import get_dsn

        conn = psycopg2.connect(get_dsn())
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date, total_mv, dv_ttm
                FROM stock_valuation
                WHERE symbol = %s
                ORDER BY trade_date DESC LIMIT 1
                """,
                (symbol,),
            )
            vrow = cur.fetchone()
        conn.close()

        total_mv = vrow[1] if vrow else None
        dv_ttm = vrow[2] if vrow else None
        data["market_value"] = total_mv
        data["valuation_date"] = (
            vrow[0].isoformat() if vrow and vrow[0] else None
        )
        data["dps_ttm"] = dps_ttm
        data["dv_ttm"] = dv_ttm

        # D₀ 总额：明细×股本 优先，落地股息率兜底
        d0, d0_method = None, None
        if dps_ttm and shares:
            d0 = dps_ttm * shares
            d0_method = "dps_ttm × 股本（年报净利/EPS 反推）"
        elif total_mv and dv_ttm:
            d0 = total_mv * dv_ttm / 100.0
            d0_method = "total_mv × dv_ttm（落地股息率）"
        data["d0"] = d0
        data["d0_method"] = d0_method

        if shares:
            data["shares"] = round(shares)
            data["shares_report_date"] = shares_report
            price = total_mv / shares if total_mv else None
            data["price"] = round(price, 2) if price else None

        intrinsic = ddm_intrinsic_value(d0, growth_rate, discount_rate)
        data["intrinsic_value"] = intrinsic
        if intrinsic and shares:
            data["intrinsic_per_share"] = round(intrinsic / shares, 2)
        data["margin_of_safety"] = margin_of_safety(intrinsic, total_mv)
    except Exception as e:  # noqa: BLE001
        data["error"] = str(e)[:200]

    data["assumptions"] = {
        "growth_rate": growth_rate,
        "discount_rate": discount_rate,
    }
    data["note"] = (
        "Gordon 模型 V = D₀×(1+g)/(r−g)，适用于分红稳定、成长性低的"
        "红利型公司；不分红或分红波动大的公司不适用（D₀ 为空）。"
        "默认 g=2%（≈长期通胀）、r=5.5%（红利股参考折现率），"
        "投资者应按公司分红可持续性自行调整。"
    )
    return responses.success(data)


def asset_value_report(symbol: str, years: int = 8) -> Any:
    """净资产分析法（《股票投资课程》15 集）。

    账面净资产是底线价值（品牌/商誉/商业信用等不在账上，大型公司
    价值无法只用净资产衡量）；对上市公司，本方法的落点是市净率：
    取最近 years 年 PB 日序列，画趋势 + 均值±1σ 参考线（课程茅台
    案例：8 年 PB 均值 4.33、标准差 2.41），并把当前 PB 放进通道
    判四态。隐含市值 = 归母净资产 × 历史 PB 中枢（μ）。
    """
    from datetime import timedelta

    from src.domain.market.fundamental.valuation_band import valuation_band
    from src.domain.market.fundamental.dcf import margin_of_safety
    from src.infra.database.market.valuation import (
        create_stock_valuation_repository,
    )

    import psycopg2

    from src.infra.database.sql_engine.dsn import get_dsn

    data: dict = {"symbol": symbol, "years": years}
    try:
        conn = psycopg2.connect(get_dsn())
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT equity_parent, report_date
                FROM stock_financial_detail
                WHERE symbol = %s AND statement_type = 'balance'
                  AND equity_parent IS NOT NULL
                ORDER BY report_date DESC LIMIT 1
                """,
                (symbol,),
            )
            brow = cur.fetchone()
        conn.close()
        equity_parent = brow[0] if brow else None
        data["equity_parent"] = equity_parent
        data["equity_report_date"] = (
            brow[1].isoformat() if brow and brow[1] else None
        )

        shares, shares_report = _annual_shares(symbol)
        if shares:
            data["shares"] = round(shares)
            data["shares_report_date"] = shares_report
            if equity_parent:
                data["bps"] = round(equity_parent / shares, 2)

        repo = create_stock_valuation_repository()
        end = date.today()
        start = end - timedelta(days=365 * int(years) + 30)
        rows = repo.get_range(symbol, start, end)

        series = []
        current = None
        current_date = None
        for r in rows:
            v = getattr(r, "pb", None)
            if isinstance(v, (int, float)):
                series.append(float(v))
                current = float(v)  # rows 升序，最后一个即最新
                current_date = r.trade_date

        data["current_pb"] = current
        data["current_pb_date"] = (
            current_date.isoformat()
            if hasattr(current_date, "isoformat") else None
        )
        data["sample_size"] = len(series)
        band = valuation_band(series, current) if current is not None else None
        data["band"] = band

        # 最新市值（rows 里最后一行的 total_mv）
        total_mv = None
        for r in reversed(rows):
            if getattr(r, "total_mv", None):
                total_mv = r.total_mv
                break
        data["market_value"] = total_mv
        if total_mv and shares:
            data["price"] = round(total_mv / shares, 2)
        data["below_book"] = (
            current is not None and current < 1
        )  # 破净：市值低于账面净资产

        # 隐含市值 = 净资产 × 历史 PB 中枢
        implied = None
        if equity_parent and band and band.get("mean"):
            implied = equity_parent * band["mean"]
            data["implied_value"] = round(implied, 2)
            data["implied_basis"] = (
                f"归母净资产 × 历史PB中枢 μ={band['mean']:.2f}"
            )
        data["margin_of_safety"] = margin_of_safety(implied, total_mv)

        # PB 趋势序列（月度降采样：每月最后一个交易日，画图用）
        monthly: dict = {}
        for r in rows:
            v = getattr(r, "pb", None)
            if isinstance(v, (int, float)) and r.trade_date:
                monthly[str(r.trade_date)[:7]] = (
                    r.trade_date.isoformat(), round(float(v), 4)
                )
        data["pb_series"] = [
            {"date": d, "pb": v} for d, v in monthly.values()
        ]
    except Exception as e:  # noqa: BLE001
        data["error"] = str(e)[:200]

    data["note"] = (
        "净资产是底线价值（重置/清算视角）；品牌、用户口碑、商业信用"
        "等不在账面上，故隐含市值仅作保守锚。PB<1 为破净。课程口径："
        "8 年 PB 均值±1σ 作高估/低估参考线，头部公司可适当拉长窗口。"
    )
    return responses.success(data)


def comps_valuation(symbol: str, level: int = 2) -> Any:
    """类比估值法（跟同类型公司比，《股票投资课程》15 集）。

    同申万二级行业（无归属降一级）可比公司最新 PE/PB/PS/股息率截面：
    中位数/均值/四分位 + 目标股排名，同行中位乘数反推隐含市值与
    上行/下行空间。课程局限：只能判断相对高低，参考同行整体高估或
    低估时结论失效，须与绝对估值交叉验证。
    """
    from src.domain.market.fundamental.comps import comps_valuation as _cv
    from src.infra.database.market.sw_industry import (
        create_sw_industry_repository,
    )

    import psycopg2

    from src.infra.database.sql_engine.dsn import get_dsn

    try:
        repo = create_sw_industry_repository()
        m = repo.get_member(symbol)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    if not m:
        return responses.error(
            f"{symbol} 无申万行业归属（非 A 股成分或未同步）"
        )

    sw_code = m["sw_code_l2"] if level == 2 and m.get("sw_code_l2") \
        else m["sw_code_l1"]
    sw_name = m["sw_name_l2"] if sw_code == m.get("sw_code_l2") \
        else m["sw_name_l1"]
    used_level = 2 if sw_code == m.get("sw_code_l2") else 1

    try:
        conn = psycopg2.connect(get_dsn())
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT mem.symbol, mem.name,
                       v.pe_ttm, v.pb, v.ps_ttm, v.dv_ttm, v.total_mv
                FROM sw_industry_member mem
                JOIN LATERAL (
                    SELECT sv.trade_date, sv.pe_ttm, sv.pb, sv.ps_ttm,
                           sv.dv_ttm, sv.total_mv
                    FROM stock_valuation sv
                    WHERE sv.symbol = mem.symbol
                    ORDER BY sv.trade_date DESC
                    LIMIT 1
                ) v ON true
                WHERE mem.{sw_col} = %s
                """.format(sw_col="sw_code_l2" if used_level == 2
                           else "sw_code_l1"),
                (sw_code,),
            )
            raw = cur.fetchall()
        conn.close()
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")

    peers = [
        {
            "symbol": r[0], "name": r[1],
            "pe_ttm": r[2], "pb": r[3], "ps_ttm": r[4],
            "dv_ttm": r[5], "total_mv": r[6],
        }
        for r in raw
    ]

    result = _cv(peers, symbol)
    if not result["target_found"]:
        return responses.error(
            f"目标股 {symbol} 不在行业 {sw_name} 成员中（数据不一致）"
        )

    data = {
        "symbol": symbol,
        "industry": {
            "level": used_level, "code": sw_code, "name": sw_name,
            "member_count": result["sample_count"],
        },
        "multiples": result["multiples"],
        # 亏损/缺失 PE 的排最后，其余按 PE 升序（课程"对标龙头看估值"视角）
        "peers": sorted(
            peers,
            key=lambda p: (
                1, 0,
            ) if not p.get("pe_ttm") or p["pe_ttm"] <= 0 else (
                0, p["pe_ttm"],
            ),
        ),
    }
    data["note"] = (
        "同行中位乘数反推隐含市值：implied = 自身市值 × 同行中位/自身。"
        "PE/PS/PB 剔除 ≤0 样本；样本 <4 家不做统计。类比法只判断相对"
        "高低，须与 DCF/DDM/净资产等绝对估值交叉验证。"
    )
    return responses.success(data)
