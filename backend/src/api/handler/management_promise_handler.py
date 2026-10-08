"""管理层言行追踪 handler：承诺 CRUD + 业绩预告自动导入 + 信用档案。"""
import datetime as dt
from typing import Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from src.domain.market.fundamental.management_promise import (
    FORECAST_METRIC_COLUMNS,
    assess_forecast_promise,
    direction_broken,
    promise_credit_summary,
)
from src.infra.database.sql_engine.dsn import get_dsn
from src.pkg import responses

_CATEGORIES = ("业绩指引", "资本开支", "分红", "回购", "增持", "其他")
_VERIFY_STATUS = ("fulfilled", "beat", "broken", "pending")


def _repo():
    from src.infra.database.market.management_promise import (
        create_management_promise_repository,
    )
    return create_management_promise_repository()


def _bare(symbol: str) -> str:
    """sh600519 → 600519（业绩预告表存裸 6 位码）。"""
    s = symbol.strip().lower()
    return s[2:] if s[:2] in ("sh", "sz", "bj") and len(s) == 8 else s


def list_promises(symbol: str) -> Any:
    """承诺列表 + 信用档案（兑现率）。"""
    sym = symbol.strip().lower()
    rows = _repo().list(sym)
    return responses.success({
        "rows": rows,
        "credit": promise_credit_summary(rows),
    })


def add_promise(payload: dict) -> Any:
    """手动录入一条承诺（业绩会指引/资本开支计划/分红回购等）。"""
    sym = (payload.get("symbol") or "").strip().lower()
    content = (payload.get("content") or "").strip()
    if not sym:
        return responses.error("symbol 必填")
    if not content:
        return responses.error("承诺内容必填")
    category = payload.get("category") or "业绩指引"
    if category not in _CATEGORIES:
        return responses.error(f"category 应为 {'/'.join(_CATEGORIES)}")
    target = payload.get("target_report_date")
    if target:
        try:
            target = dt.date.fromisoformat(target)
        except (TypeError, ValueError):
            return responses.error("target_report_date 应为 YYYY-MM-DD")
    promise_date = None
    if payload.get("promise_date"):
        try:
            promise_date = dt.date.fromisoformat(payload["promise_date"])
        except (TypeError, ValueError):
            return responses.error("promise_date 应为 YYYY-MM-DD")
    row = _repo().add_manual({
        "symbol": sym, "category": category, "content": content,
        "promise_date": promise_date,
        "target_report_date": target,
        "detail": (payload.get("note") or "").strip() or None,
    })
    return responses.success(row)


def verify_promise(row_id: int, payload: dict) -> Any:
    """人工验证承诺兑现情况（manual 承诺的主闭环）。"""
    status = payload.get("status")
    if status not in _VERIFY_STATUS:
        return responses.error(
            f"status 应为 {'/'.join(_VERIFY_STATUS)}")
    row = _repo().verify(
        row_id, status, (payload.get("evidence") or "").strip() or None)
    if not row:
        return responses.error("承诺不存在")
    return responses.success(row)


def delete_promise(row_id: int) -> Any:
    ok = _repo().delete(row_id)
    if not ok:
        return responses.error("承诺不存在")
    return responses.success({"deleted": True})


def import_forecasts(symbol: str) -> Any:
    """从业绩预告自动导入承诺并对比实际值（V1 言行追踪主数据源）。

    预告数值=管理层量化承诺；按报告期取财报实际值（累计口径）评估
    兑现（±10% 容差；预增而实际转降直接 broken）。幂等 upsert。
    """
    sym = symbol.strip().lower()
    bare = _bare(sym)
    try:
        conn = psycopg2.connect(get_dsn())
    except Exception as e:  # noqa: BLE001
        return responses.error(f"数据库连接失败: {e}")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT metric, report_date, announce_date,
                       forecast_value, prev_value,
                       forecast_type_label, raw
                FROM stock_earnings_forecast
                WHERE symbol = %s AND forecast_type = 'preannounce'
                ORDER BY report_date DESC LIMIT 24
                """,
                (bare,),
            )
            forecasts = [dict(r) for r in cur.fetchall()]
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询失败: {e}")
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    forecasts = [f for f in forecasts
                 if f["metric"] in FORECAST_METRIC_COLUMNS]
    if not forecasts:
        return responses.error(
            f"{symbol} 无业绩预告记录（预告仅强制披露于亏损/扭亏/±50% "
            f"变动等情形，蓝筹常无预告，可手动录入指引）")

    # 实际值：按报告期批量取 income 累计口径固定列
    dates = sorted({f["report_date"] for f in forecasts})
    actuals: dict = {}
    try:
        with psycopg2.connect(get_dsn()) as conn, \
                conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT report_date, revenue, net_profit,
                       net_profit_parent, net_profit_deduct
                FROM stock_financial_detail
                WHERE symbol = %s AND statement_type = 'income'
                  AND report_date = ANY(%s)
                """,
                (sym, dates),
            )
            for r in cur.fetchall():
                actuals[r["report_date"]] = r
    except Exception:  # noqa: BLE001
        actuals = {}

    repo = _repo()
    counts = {"inserted": 0, "updated": 0, "pending": 0}
    for f in forecasts:
        col = FORECAST_METRIC_COLUMNS[f["metric"]]
        actual = (actuals.get(f["report_date"]) or {}).get(col)
        actual = float(actual) if actual is not None else None
        assess = assess_forecast_promise(
            float(f["forecast_value"]) if f["forecast_value"] is not None
            else None,
            actual,
            label=f["forecast_type_label"],
        )
        if direction_broken(
                f["forecast_value"], f["prev_value"], actual,
                f["forecast_type_label"]):
            assess["status"] = "broken"
            assess["detail"] += "；且预告向好而实际同比转降"
        row = {
            "symbol": sym,
            "category": "业绩指引",
            "content": (f"{f['metric']}预告·{f['forecast_type_label']}"
                        if f.get("forecast_type_label")
                        else f"{f['metric']}预告"),
            "promise_date": f["announce_date"],
            "target_report_date": f["report_date"],
            "metric": f["metric"],
            "forecast_value": f["forecast_value"],
            "actual_value": actual,
            "status": assess["status"],
            "deviation_pct": assess["deviation_pct"],
            "detail": assess["detail"],
            "raw": {"业绩变动原因": (f.get("raw") or {}).get(
                "业绩变动原因")},
        }
        counts[repo.upsert_forecast(row)] += 1
        if assess["status"] == "pending":
            counts["pending"] += 1
    return responses.success({
        "symbol": sym, "scanned": len(forecasts), **counts,
        "note": "±10% 容差判兑现；预告向好而实际转降直接 broken。",
    })


async def import_annual_reports(symbol: str, payload: dict) -> Any:
    """年报 MD&A 承诺抽取（言行追踪 V2，LLM 已配 GLM）。

    下载近年年报 PDF → 切"管理层讨论与分析" → LLM 抽取管理层明确
    承诺/指引/计划 → 入库待人工验证（source=annual_report，内容去重）。
    耗时约 1~3 分钟（含 PDF 下载与逐份 LLM 抽取）。
    """
    import datetime as dt

    from src.domain.market.fundamental.annual_mda import extract_promises

    years = int((payload or {}).get("years") or 2)
    years = max(1, min(years, 3))
    sym = symbol.strip().lower()
    try:
        result = await extract_promises(sym, years=years)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"年报抽取失败: {e}")

    repo = _repo()
    counts = {"inserted": 0, "duplicated": 0}
    for p in result.get("promises") or []:
        try:
            promise_date = dt.date.fromisoformat(p["announce_date"])
        except (KeyError, TypeError, ValueError):
            promise_date = None
        row = {
            "symbol": sym,
            "category": p.get("category") or "其他",
            "content": p["content"],
            "promise_date": promise_date,
            "detail": f"{p.get('year')} 年报 MD&A 抽取"
                      + (f"；目标期间：{p['period']}" if p.get("period")
                         else ""),
        }
        counts[repo.add_annual_report(row)] += 1
    return responses.success({
        "symbol": sym,
        "reports": [
            {"title": r["title"], "year": r["year"],
             "announce_date": r["announce_date"],
             "promises": len(r.get("promises") or []),
             "skipped": r.get("skipped"), "model": r.get("model")}
            for r in result.get("reports") or []
        ],
        "extracted": len(result.get("promises") or []),
        **counts,
        "note": "LLM 只抽取原文明确表述，兑现与否由人工验证判定。",
    })
