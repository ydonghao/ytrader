"""持仓论点业务服务：快照抓取 / 指标装配 / 财报联动重估 / 到价检测。

纯编排层——所有数据访问通过模块级函数（_repo/_quality_report/
_valuation_handlers/_financial_assembly），便于测试 monkeypatch。
"""
import datetime as dt
import json
import logging
from datetime import date
from typing import Any, Optional

from src.api.handler.financial_detail_handler import (
    asset_value_report,
    comps_valuation,
    dcf_valuation,
    ddm_valuation,
    quality_report,
)
from src.domain.market.fundamental.thesis_monitor import (
    ThesisCondition,
    check_price_band,
    compute_metric_values,
    evaluate_thesis,
    reeval_verdict,
)
from src.domain.market.strategy.longterm.data_loader import (
    fetch_financial_history,
    fetch_financial_snapshot,
)
from src.infra.database.alert.repository import create_alert_repository
from src.infra.database.portfolio.thesis_repository import (
    create_thesis_repository,
)

log = logging.getLogger(__name__)


def _data(resp: Any) -> Optional[dict]:
    """JSONResponse → data dict（checklist_handler 同款降级模式）。"""
    try:
        body = json.loads(resp.body)
        return body.get("data") if body.get("code") == 0 else None
    except Exception:
        return None


def _repo():
    return create_thesis_repository()


def _quality_report(symbol: str) -> Optional[dict]:
    d = _data(quality_report(symbol)) or {}
    if not d:
        return None
    return {
        "score": d.get("quality_score"),
        "verdict": d.get("verdict"),
        "red_flags": d.get("red_flags") or [],
    }


def _valuation_handlers(symbol: str) -> dict:
    """五法相对上行摘要（内在/市值−1，比率与股数无关）；失败置 None。

    估值端点的内在值多为公司总值，不能与每股价格直接比较——
    统一用比率口径，margin 由 upside_to_margin 换算。
    """

    def _ratio(d, iv_key="intrinsic_value", mv_key="market_value"):
        iv, mv = d.get(iv_key), d.get(mv_key)
        if iv and mv and mv > 0:
            return iv / mv - 1.0
        return None

    out: dict = {}
    for key, fn, ivk in (
        ("dcf_upside", dcf_valuation, "intrinsic_value"),
        ("ddm_upside", ddm_valuation, "intrinsic_value"),
        ("asset_upside", asset_value_report, "implied_value"),
    ):
        try:
            d = _data(fn(symbol)) or {}
            out[key] = _ratio(d, ivk)
        except Exception:
            out[key] = None
    try:
        d = _data(comps_valuation(symbol)) or {}
        out["comps_upside"] = (
            (d.get("multiples") or {}).get("pe_ttm") or {}
        ).get("upside")
    except Exception:
        out["comps_upside"] = None
    return out


def _financial_assembly(symbol: str) -> dict:
    """财务装配字典（compute_metric_values 的输入）。"""
    out: dict = {}
    try:
        snap = fetch_financial_snapshot([symbol], include_detail=True)
        if symbol in snap:
            out.update(snap[symbol])
    except Exception as e:
        log.warning("_financial_assembly snapshot 失败 %s: %s",
                    symbol, e)
    try:
        # 历史基期自 stock_financial_detail（stock_financials 无
        # 利润表列），与条件回测同源
        rows = _backtest_periods(symbol, lookback=12)
        if rows:
            cur = rows[-1]
            out["report_date"] = cur.get("report_date")
            out.setdefault("revenue", cur.get("revenue"))
            out.setdefault("net_profit", cur.get("net_profit_parent"))
            import datetime as _dt

            try:
                d = _dt.date.fromisoformat(
                    str(cur.get("report_date"))[:10]
                )
                year_ago_np = None
                for r in rows[:-1]:
                    if str(r.get("report_date"))[:10] == d.replace(
                        year=d.year - 1
                    ).isoformat():
                        out.setdefault(
                            "revenue_prev", r.get("revenue"),
                        )
                        out.setdefault(
                            "net_profit_prev",
                            r.get("net_profit_parent"),
                        )
                        year_ago_np = r.get("net_profit_parent")
                        break
                ann_year = d.year - 1 if d.month != 12 else d.year - 1
                for r in rows[:-1]:
                    rd = str(r.get("report_date"))[:10]
                    if rd[:4] == str(ann_year) and rd[5:7] == "12":
                        fy_np = r.get("net_profit_parent")
                        cur_np = cur.get("net_profit_parent")
                        if None not in (fy_np, year_ago_np, cur_np):
                            out["net_profit_ttm"] = (
                                cur_np + fy_np - year_ago_np
                            )
                        break
            except (ValueError, TypeError):
                pass
    except Exception as e:
        log.warning("_financial_assembly history 失败 %s: %s",
                    symbol, e)
    try:
        alert_repo = create_alert_repository()
        for mk in ("pe_ttm", "pb", "dv_ttm"):
            if out.get(mk) is None:
                v = alert_repo.get_latest_metric_value(symbol, mk)
                if v is not None:
                    out[mk] = v
    except Exception as e:
        log.warning("_financial_assembly valuation 失败 %s: %s",
                    symbol, e)
    return out


def _backtest_periods(symbol: str, lookback: int = 16) -> list:
    """按 report_date 合并三表固定列（升序），供条件历史回测。"""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from src.infra.database.sql_engine.dsn import get_dsn
    sql = """
        SELECT report_date,
               MAX(revenue) AS revenue,
               MAX(net_profit_parent) AS net_profit_parent,
               MAX(ocf) AS ocf,
               MAX(total_assets) AS total_assets,
               MAX(total_liabilities) AS total_liabilities,
               MAX(equity) AS equity,
               MAX(gross_margin) AS gross_margin
        FROM stock_financial_detail
        WHERE symbol = %s
        GROUP BY report_date
        ORDER BY report_date DESC
        LIMIT %s
    """
    out: list = []
    try:
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (symbol, lookback))
                for r in cur.fetchall():
                    out.append({
                        "report_date": r["report_date"].isoformat(),
                        **{k: float(r[k]) if r.get(k) is not None
                           else None
                           for k in (
                               "revenue", "net_profit_parent", "ocf",
                               "total_assets", "total_liabilities",
                               "equity", "gross_margin",
                           )},
                    })
        finally:
            conn.close()
    except Exception as e:
        log.warning("_backtest_periods 失败 %s: %s", symbol, e)
    return list(reversed(out))   # 升序


def capture_snapshot(symbol: str,
                     price: Optional[float] = None) -> dict:
    """登记时快照（spec §3.5）：任一来源失败置 None。"""
    if price is None:
        try:
            price = _repo().latest_close([symbol]).get(symbol)
        except Exception as e:
            log.warning("capture_snapshot price 失败 %s: %s",
                        symbol, e)
    try:
        quality = _quality_report(symbol)
    except Exception as e:
        log.warning("capture_snapshot quality 失败 %s: %s", symbol, e)
        quality = None
    try:
        valuation = _valuation_handlers(symbol)
    except Exception as e:
        log.warning("capture_snapshot valuation 失败 %s: %s",
                    symbol, e)
        valuation = {}
    try:
        from src.domain.market.thesis.thermometer_service import (
            compute_thermometer,
        )
        t = compute_thermometer()
        thermo = {k: t.get(k) for k in (
            "level", "level_label", "erp_pct", "erp_percentile",
        )}
    except Exception as e:
        log.warning("capture_snapshot thermometer 失败: %s", e)
        thermo = None
    return {
        "date": date.today().isoformat(),
        "price": price,
        "quality": quality,
        "valuation": valuation,
        "thermometer": thermo,
    }


def assemble_metrics(symbol: str) -> dict:
    """METRIC_REGISTRY 全键现值（缺=None）。"""
    return compute_metric_values(_financial_assembly(symbol))


def get_band_key(band: Optional[dict]) -> Optional[str]:
    if not band:
        return None
    return "{}:{}:{}".format(
        band.get("metric", "price"), band.get("low"), band.get("high"),
    )


def _run_one(thesis: dict, repo, trigger: str,
             report_date: Optional[date]) -> bool:
    """单论点重估；返回是否落了新重估记录。"""
    conditions = repo.list_conditions(thesis["id"])
    metrics = assemble_metrics(thesis["symbol"])
    eval_conditions = [
        ThesisCondition(
            metric=c["metric_key"], operator=c["operator"],
            threshold=c["threshold"],
        )
        for c in conditions
    ]
    result = evaluate_thesis(eval_conditions, metrics)
    cond_result = []
    for c, ec in zip(conditions, eval_conditions):
        current = metrics.get(c["metric_key"])
        if ec in result.breached:
            status = "breached"
        elif current is None:
            status = "unknown"
        else:
            status = "holding"
        cond_result.append({
            "condition_id": c["id"], "metric_key": c["metric_key"],
            "operator": c["operator"], "threshold": c["threshold"],
            "current": current, "status": status,
        })
        repo.update_condition_status(c["id"], status)

    quality_now = _quality_report(thesis["symbol"])
    snap_q = (thesis.get("snapshot") or {}).get("quality")
    verdict = reeval_verdict(quality_now, snap_q, cond_result)

    new_id = repo.add_reeval({
        "thesis_id": thesis["id"],
        "report_date": report_date,
        "trigger": trigger,
        "quality_now": quality_now,
        "quality_delta": {
            "score_diff": (
                quality_now["score"] - snap_q["score"]
                if quality_now and snap_q
                and quality_now.get("score") is not None
                and snap_q.get("score") is not None else None
            ),
        },
        "valuation_now": _valuation_handlers(thesis["symbol"]),
        "conditions_result": cond_result,
        "verdict": verdict,
    })
    if new_id is None:
        return False
    repo.add_event(
        thesis["id"], "reeval_done",
        {"verdict": verdict,
         "report_date": report_date.isoformat()
         if report_date else None},
    )
    if verdict == "sell_signal":
        breached = [c for c in cond_result
                    if c["status"] == "breached"]
        repo.add_event(
            thesis["id"], "condition_breached",
            {"verdict": verdict,
             "breached": [b["metric_key"] for b in breached]},
        )
    repo.update_thesis(thesis["id"], last_reviewed_at=dt.datetime.now())
    return True


def _check_band(thesis: dict, repo) -> bool:
    band = thesis.get("target_band")
    band_key = get_band_key(band)
    if not band or not band_key:
        return False
    if repo.has_band_event(thesis["id"], band_key):
        return False
    price = repo.latest_close([thesis["symbol"]]).get(
        thesis["symbol"]
    )
    band_result = check_price_band(band, price, {})
    if band_result.get("metric") not in (None, "price"):
        band_result = check_price_band(
            band, None, assemble_metrics(thesis["symbol"])
        )
    if band_result.get("reached") is not True:
        return False
    repo.add_event(
        thesis["id"], "price_band_reached",
        {"band": band_key, "current": band_result.get("current"),
         "alerted": True},
    )
    return True


def run_daily(today: Optional[date] = None) -> dict:
    """每日 17:35：新财报重估 + 估值带到价检测。幂等。"""
    today = today or date.today()
    repo = _repo()
    theses = repo.list_theses(status="active")
    summary = {"active": len(theses), "reevaluated": 0,
               "band_alerts": 0}
    if not theses:
        return summary
    symbols = [t["symbol"] for t in theses]
    report_dates = repo.latest_report_dates(symbols)
    earnings = repo.latest_earnings_dates(symbols)
    for t in theses:
        sym = t["symbol"]
        trigger, report_date = None, None
        last_r = repo.latest_reeval_report_date(t["id"])
        formal = report_dates.get(sym)
        if formal and (last_r is None or formal > last_r):
            trigger, report_date = "formal", formal
        else:
            ann = earnings.get(sym)
            if ann and ann[1] and (
                last_r is None or ann[0] > last_r
            ):
                trigger, report_date = (ann[2] or "express"), ann[0]
        try:
            if trigger and _run_one(t, repo, trigger, report_date):
                summary["reevaluated"] += 1
            if _check_band(t, repo):
                summary["band_alerts"] += 1
        except Exception as e:
            log.error("[THESIS_DAILY] %s 失败: %s", sym, e)
    # 排雷精查（第5期）：延迟 import 防环
    try:
        from src.domain.market.thesis.mine_sweep import check_positions
        summary["mine"] = check_positions()
    except Exception as e:
        log.error("[THESIS_DAILY] mine_sweep 失败: %s", e)
    return summary


def run_reeval(thesis_id: int, trigger: str = "manual",
               report_date: Optional[date] = None) -> Optional[dict]:
    """手动重估（API 调用）。"""
    repo = _repo()
    thesis = repo.get_thesis(thesis_id)
    if not thesis:
        return None
    did = _run_one(thesis, repo, trigger, report_date)
    reevals = repo.list_reevals(thesis_id, limit=1)
    return {"created": did, "latest": reevals[0] if reevals else None}
