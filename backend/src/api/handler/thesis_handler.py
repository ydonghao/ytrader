"""持仓论点 handler：端点编排 + 卖出体检聚合。"""
import datetime as dt
from typing import Any, Optional

from src.domain.market.fundamental.capital_allocation import (
    capital_allocation,
)
from src.domain.market.fundamental.market_thermometer import (
    build_erp_history,
    market_thermometer,
)
from src.domain.market.fundamental.position_sizing import (
    suggest_position_size,
)
from src.domain.market.fundamental.thesis_monitor import (
    METRIC_REGISTRY,
    backtest_conditions,
    build_sell_check,
    check_price_band,
    closed_performance,
    confidence_calibration,
    ladder_progress,
    pass_performance,
    pipeline_stages,
    upside_to_margin,
)
from src.domain.market.thesis import service
from src.infra.database.portfolio.thesis_repository import (
    create_thesis_repository,
)
from src.pkg import responses


def _repo():
    return create_thesis_repository()


def _clean_confidence(v) -> Optional[int]:
    """信心度入参清洗：空→None，非法抛 ValueError。"""
    if v is None or v == "":
        return None
    c = int(v)
    if not 1 <= c <= 5:
        raise ValueError
    return c


def list_theses(status: Optional[str] = None) -> Any:
    repo = _repo()
    theses = repo.list_theses(status=status or None)
    symbols = [t["symbol"] for t in theses]
    prices = repo.latest_close(symbols) if symbols else {}
    cond_map = {t["id"]: repo.list_conditions(t["id"])
                for t in theses}
    reeval_map = {}
    for t in theses:
        rows = repo.list_reevals(t["id"], limit=1)
        reeval_map[t["id"]] = rows[0] if rows else None
    for t in theses:
        t["current_price"] = prices.get(t["symbol"])
        if t["current_price"] and t["buy_price"]:
            t["pnl_pct"] = (
                t["current_price"] / t["buy_price"] - 1.0
            ) * 100.0
        else:
            t["pnl_pct"] = None
        conds = cond_map[t["id"]]
        t["condition_summary"] = {
            "total": len(conds),
            "breached": sum(
                1 for c in conds if c["status"] == "breached"
            ),
            "unknown": sum(
                1 for c in conds if c["status"] == "unknown"
            ),
        }
        t["last_reeval_verdict"] = (
            reeval_map[t["id"]] or {}
        ).get("verdict")
        lr = t.get("last_reviewed_at")
        if lr:
            age = dt.datetime.now() - dt.datetime.fromisoformat(lr)
            t["stale"] = age.days > 90
    return responses.success(theses)


def create_thesis(payload: dict) -> Any:
    symbol = (payload.get("symbol") or "").strip().lower()
    if not symbol:
        return responses.error("symbol 必填")
    for it in payload.get("conditions") or []:
        if it.get("metric_key") not in METRIC_REGISTRY:
            return responses.error(
                "未知指标 {}".format(it.get("metric_key"))
            )
    repo = _repo()
    data = {
        k: payload[k] for k in (
            "buy_date", "buy_price", "shares", "thesis_text",
            "target_band", "entry_ladder",
        ) if k in payload
    }
    try:
        confidence = _clean_confidence(payload.get("confidence"))
    except (TypeError, ValueError):
        return responses.error("confidence 应为 1~5")
    catalysts = (payload.get("catalysts") or "").strip() or None
    data["symbol"] = symbol
    data["snapshot"] = service.capture_snapshot(symbol)
    tid = repo.create_thesis(data)
    conditions = payload.get("conditions") or []
    if conditions:
        repo.replace_conditions(tid, conditions)
    try:
        repo.add_journal(tid, "created", note=payload.get("thesis_text"),
                         price=(data["snapshot"] or {}).get("price"),
                         confidence=confidence, catalysts=catalysts)
    except Exception:
        pass  # 日志失败不阻塞登记
    return responses.success({"id": tid})


def get_thesis(thesis_id: int) -> Any:
    repo = _repo()
    t = repo.get_thesis(thesis_id)
    if not t:
        return responses.error("论点不存在")
    t["conditions"] = repo.list_conditions(thesis_id)
    t["reevals"] = repo.list_reevals(thesis_id)
    t["journal"] = repo.list_journal(thesis_id)
    fills = repo.list_ladder_fills(thesis_id)
    t["ladder_fills"] = fills
    t["ladder_progress"] = ladder_progress(
        t.get("entry_ladder") or [], fills,
    )
    return responses.success(t)


def update_thesis(thesis_id: int, payload: dict) -> Any:
    allowed = {
        "buy_date", "buy_price", "shares", "thesis_text",
        "target_band", "decision", "decision_note",
    }
    fields = {k: v for k, v in payload.items() if k in allowed}
    if "decision" in fields:
        fields["decision_at"] = dt.datetime.now()
    try:
        confidence = _clean_confidence(payload.get("confidence"))
    except (TypeError, ValueError):
        return responses.error("confidence 应为 1~5")
    repo = _repo()
    ok = repo.update_thesis(thesis_id, **fields)
    if not ok:
        return responses.error("论点不存在")
    if "decision" in fields:
        t = repo.get_thesis(thesis_id) or {}
        try:
            price = repo.latest_close(
                [t.get("symbol")] if t.get("symbol") else []
            ).get(t.get("symbol"))
        except Exception:
            price = None
        try:
            repo.add_journal(thesis_id, "decision",
                             decision=fields["decision"],
                             note=fields.get("decision_note"),
                             price=price, confidence=confidence)
        except Exception:
            pass
    return responses.success({"updated": True})


def close_thesis(thesis_id: int, payload: dict) -> Any:
    reason = payload.get("reason", "manual")
    price = payload.get("price")
    try:
        confidence = _clean_confidence(payload.get("confidence"))
    except (TypeError, ValueError):
        return responses.error("confidence 应为 1~5")
    repo = _repo()
    ok = repo.close_thesis(thesis_id, reason=reason, price=price)
    if not ok:
        return responses.error("论点不存在")
    try:
        repo.add_journal(thesis_id, "close", decision=reason,
                         note=payload.get("note"), price=price,
                         confidence=confidence)
    except Exception:
        pass
    return responses.success({"closed": True})


def replace_conditions(thesis_id: int, payload: dict) -> Any:
    items = payload.get("conditions") or []
    for it in items:
        if it.get("metric_key") not in METRIC_REGISTRY:
            return responses.error(
                "未知指标 {}".format(it.get("metric_key"))
            )
    n = _repo().replace_conditions(thesis_id, items)
    return responses.success({"count": n})


def sell_check(thesis_id: int) -> Any:
    repo = _repo()
    t = repo.get_thesis(thesis_id)
    if not t:
        return responses.error("论点不存在")
    conditions = repo.list_conditions(thesis_id)
    metrics = service.assemble_metrics(t["symbol"])
    price = repo.latest_close([t["symbol"]]).get(t["symbol"])
    band_result = check_price_band(
        t.get("target_band"), price, metrics
    )
    try:
        quality_now = service._quality_report(t["symbol"])
    except Exception:
        quality_now = None
    try:
        valuation_now = service._valuation_handlers(t["symbol"])
    except Exception:
        valuation_now = None
    if valuation_now is not None and price is not None:
        valuation_now["price"] = price
    report = build_sell_check(
        t, conditions, metrics, band_result,
        snapshot=t.get("snapshot"),
        valuation_now=valuation_now,
        quality_now=quality_now,
    )
    return responses.success(report)


def run_reeval(thesis_id: int) -> Any:
    out = service.run_reeval(thesis_id)
    if out is None:
        return responses.error("论点不存在")
    return responses.success(out)


def list_events(unread: bool = False) -> Any:
    repo = _repo()
    events = repo.list_events(unread_only=unread)
    thesis_map = {t["id"]: t for t in repo.list_theses()}
    for e in events:
        t = thesis_map.get(e["thesis_id"])
        e["symbol"] = t["symbol"] if t else None
    names = repo.names_for(list({e["symbol"] for e in events if e["symbol"]}))
    for e in events:
        e["name"] = names.get(e["symbol"])
    return responses.success(events)


def mark_event_read(event_id: int) -> Any:
    ok = _repo().mark_event_read(event_id)
    if not ok:
        return responses.error("事件不存在")
    return responses.success({"read": True})


def get_journal(thesis_id: int) -> Any:
    repo = _repo()
    if not repo.get_thesis(thesis_id):
        return responses.error("论点不存在")
    return responses.success(repo.list_journal(thesis_id))


def add_journal_note(thesis_id: int, payload: dict) -> Any:
    repo = _repo()
    if not repo.get_thesis(thesis_id):
        return responses.error("论点不存在")
    note = (payload.get("note") or "").strip()
    if not note:
        return responses.error("note 不能为空")
    jid = repo.add_journal(thesis_id, "note", note=note)
    return responses.success({"id": jid})


def review_summary() -> Any:
    from src.domain.market.fundamental.thesis_monitor import (
        build_review_summary,
    )
    repo = _repo()
    closed = repo.list_theses(status="closed")
    journals = repo.list_journal_all(limit=200)
    symbol_map = {t["id"]: t["symbol"]
                  for t in repo.list_theses()}
    for j in journals:
        j["symbol"] = symbol_map.get(j.get("thesis_id"))
    try:
        last = repo.latest_review_at()
    except Exception:
        last = None
    return responses.success(
        build_review_summary(closed, journals, last)
    )


def mark_reviewed(payload: dict) -> Any:
    _repo().add_review_log(note=payload.get("note"))
    return responses.success({"marked": True})


def position_size(symbol: str, capital: float = 1000000.0) -> Any:
    """仓位建议（第4期）：质量×低估→档位+半凯利+建仓三档。"""
    repo = _repo()
    price = repo.latest_close([symbol]).get(symbol)
    try:
        quality = service._quality_report(symbol)
    except Exception:
        quality = None
    try:
        upside = (service._valuation_handlers(symbol) or {}
                  ).get("dcf_upside")
    except Exception:
        upside = None
    score = quality.get("score") if quality else None
    margin = upside_to_margin(upside)
    return responses.success(suggest_position_size(
        score, margin,
        total_capital=capital, current_price=price,
    ))


def list_mines(level: Optional[str] = None,
               limit: int = 100) -> Any:
    """排雷名单（第5期）。"""
    return responses.success(
        _repo().list_mines(level=level, limit=limit)
    )


def scan_mines(payload: dict) -> Any:
    """手动排雷扫描：scope=positions（三源精查）| market（全市场Z）。"""
    from src.domain.market.thesis import mine_sweep
    scope = (payload or {}).get("scope", "positions")
    if scope == "market":
        return responses.success(mine_sweep.scan_market())
    return responses.success(mine_sweep.check_positions())


def capital_allocation_report(symbol: str) -> Any:
    """管理层与资本配置（第6期V1）：四源聚合 → 四维报告。"""
    from datetime import timedelta
    from src.domain.market.fundamental.derived_metrics import roic
    from src.infra.database.alert.repository import (
        create_alert_repository,
    )
    from src.infra.database.market.dividend import (
        create_stock_dividend_repository,
    )
    from src.infra.database.market.shareholder_count import (
        create_shareholder_count_repository,
    )

    dividend_years, payout_pct = None, None
    try:
        end = dt.date.today()
        rows = create_stock_dividend_repository().get_history(
            symbol, start=end - timedelta(days=10 * 365), end=end,
        )
        years = {}
        for r in rows:
            if r.div_per_share and r.ex_date:
                years.setdefault(r.ex_date.year, False)
                years[r.ex_date.year] = True
        if years:
            all_years = list(range(min(years), dt.date.today().year + 1))
            dividend_years = [years.get(y, False) for y in all_years]
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "capital_allocation dividend 失败: %s", e)

    try:
        alert_repo = create_alert_repository()
        dv = alert_repo.get_latest_metric_value(symbol, "dv_ttm")
        pe = alert_repo.get_latest_metric_value(symbol, "pe_ttm")
        if dv is not None and pe is not None and pe > 0:
            payout_pct = round(dv * pe, 1)   # 两率相除法
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "capital_allocation payout 失败: %s", e)

    roic_pct = None
    try:
        snap = service._financial_assembly(symbol)
        r = roic(snap)
        if r is not None:
            roic_pct = round(r * 100, 2)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "capital_allocation roic 失败: %s", e)

    holder_change_pct = None
    try:
        hrows = create_shareholder_count_repository(
        ).get_history(symbol)
        counts = [
            (h.report_date, h.holder_count) for h in hrows
            if h.holder_count
        ]
        if len(counts) >= 2:
            latest_d, latest_c = counts[-1]
            year_ago = [
                c for d, c in counts
                if (latest_d - d).days >= 300
            ]
            if year_ago:
                base = year_ago[-1]
                holder_change_pct = round(
                    (latest_c - base) / base * 100, 1,
                )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "capital_allocation holder 失败: %s", e)

    mgmt_behavior = None
    try:
        from src.domain.market.thesis.capital_events import (
            summarize_mgmt_events,
        )
        events = _repo().list_capital_events(symbol, months=24)
        mgmt_behavior = summarize_mgmt_events(events, months=24)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "capital_allocation mgmt_behavior 失败: %s", e)

    out = capital_allocation(
        dividend_years, payout_pct, roic_pct, holder_change_pct,
    )
    out["symbol"] = symbol
    out["mgmt_behavior"] = mgmt_behavior
    if mgmt_behavior and mgmt_behavior.get("flags"):
        out["flags"].extend(mgmt_behavior["flags"])
    return responses.success(out)


def thermometer(symbol: str = "sh000300",
               gdp: float = 140.0) -> Any:
    """全市场温度计：ERP 五档+分位+巴菲特+水位（计算在服务层）。"""
    from src.domain.market.thesis.thermometer_service import (
        compute_thermometer,
    )
    return responses.success(compute_thermometer(symbol, gdp))


def thermometer_history(symbol: str = "sh000300",
                        days: int = 365) -> Any:
    """温度历史序列（日快照表）。"""
    return responses.success(
        _repo().list_thermometer(symbol=symbol, days=days)
    )


def capital_events_list(symbol: str, months: int = 24) -> Any:
    """近 N 月资本事件列表（第6期V2）。"""
    return responses.success(
        _repo().list_capital_events(symbol, months=months)
    )


def conditions_backtest(payload: dict) -> Any:
    """条件历史回测（阈值校准，默认16季）。"""
    symbol = (payload.get("symbol") or "").strip().lower()
    conditions = payload.get("conditions") or []
    lookback = int(payload.get("lookback") or 16)
    if not symbol or not conditions:
        return responses.error("symbol 与 conditions 必填")
    for c in conditions:
        if c.get("metric_key") not in METRIC_REGISTRY:
            return responses.error(
                "未知指标 {}".format(c.get("metric_key"))
            )
    periods = service._backtest_periods(symbol, lookback=lookback)
    return responses.success(
        backtest_conditions(conditions, periods)
    )


def portfolio_risk_report() -> Any:
    """组合层风险（二期F1）：集中度/相关性/加权估值。"""
    from src.domain.market.fundamental.portfolio_risk import (
        correlation_matrix as corr_fn,
        industry_concentration,
        portfolio_valuation,
    )

    repo = _repo()
    theses = repo.list_theses(status="active")
    held = [t for t in theses if t.get("shares") and t.get("symbol")]
    if not held:
        return responses.success({
            "positions": 0, "groups": [], "flags": ["无持仓论点"],
            "correlation": {"symbols": [], "matrix": {},
                            "effective_positions": None},
            "valuation": {"pe_ttm": None, "pb": None},
            "note": "权重=个股市值/持仓总市值（不含现金）。",
        })
    symbols = [t["symbol"] for t in held]
    prices = repo.latest_close(symbols)
    metrics = repo.latest_metrics_map(symbols)
    ind_map = repo.latest_industry_map(symbols)

    positions = []
    for t in held:
        px = prices.get(t["symbol"])
        val = (t["shares"] or 0) * px if px else 0.0
        m = metrics.get(t["symbol"]) or {}
        ind = ind_map.get(t["symbol"])
        positions.append({
            "symbol": t["symbol"], "value": val,
            "industry": ind[1] if ind else None,
            "industry_code": ind[0] if ind else None,
            "pe_ttm": m.get("pe_ttm"), "pb": m.get("pb"),
        })
    total_value = sum(p["value"] for p in positions) or 1.0
    for p in positions:
        p["weight_pct"] = round(p["value"] / total_value * 100, 1)

    conc = industry_concentration(positions)
    returns = repo.daily_returns(symbols)
    weights = {t["symbol"]: (t["shares"] or 0) * prices.get(t["symbol"], 0)
               / total_value for t in held}
    corr = corr_fn(returns, weights)
    corr_matrix_serial = [
        {"a": a, "b": b, "rho": v} for (a, b), v in
        corr["matrix"].items()
    ]
    pval = portfolio_valuation(positions)

    return responses.success({
        "positions": len(positions),
        "total_market_value": round(total_value, 0),
        "position_rows": [
            {k: p[k] for k in (
                "symbol", "industry", "weight_pct", "pe_ttm", "pb",
            )} for p in positions
        ],
        "groups": conc["groups"],
        "flags": conc["flags"],
        "correlation": {
            "symbols": corr["symbols"],
            "pairs": corr_matrix_serial,
            "effective_positions": corr["effective_positions"],
        },
        "valuation": pval,
        "note": "权重=个股市值/持仓总市值（不含现金）；相关性取近"
                "260自然日日收益。",
    })


def compare_report(symbols: list) -> Any:
    """候选对比工作台（二期F2）：≤4 只，并行聚合现成维度。"""
    from concurrent.futures import ThreadPoolExecutor

    from src.api.handler.financial_detail_handler import moat_report

    symbols = [sym.strip().lower() for sym in symbols
               if sym and sym.strip()][:4]
    if not symbols:
        return responses.error("symbols 必填（≤4）")

    def _one(sym: str) -> dict:
        row = {"symbol": sym}
        try:
            q = service._quality_report(sym) or {}
            row["quality_score"] = q.get("score")
            row["quality_verdict"] = q.get("verdict")
        except Exception:
            row["quality_score"] = None
        try:
            row.update(service._valuation_handlers(sym) or {})
        except Exception:
            pass
        try:
            m = service.assemble_metrics(sym)
            for k in ("roe", "revenue_yoy", "pe_ttm", "pb", "dv_ttm"):
                row[k] = m.get(k)
        except Exception:
            pass
        try:
            moat = service._data(moat_report(sym)) or {}
            row["moat_score"] = (moat.get("moat") or {}).get("score")
            row["moat_verdict"] = (
                moat.get("moat") or {}
            ).get("verdict")
        except Exception:
            row["moat_score"] = None
        try:
            # 资本配置四维分（分红/分红率/ROIC/筹码）
            row["capital_score"] = _capital_score_light(sym)
        except Exception:
            row["capital_score"] = None
        return row

    with ThreadPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(_one, symbols))
    return responses.success({"rows": rows})


def _capital_score_light(symbol: str) -> Any:
    """资本配置轻量版（对比页用）：四源并行取数+纯函数。"""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta

    from src.domain.market.fundamental.capital_allocation import (
        capital_allocation,
    )
    from src.domain.market.fundamental.derived_metrics import roic
    from src.infra.database.alert.repository import (
        create_alert_repository,
    )
    from src.infra.database.market.dividend import (
        create_stock_dividend_repository,
    )
    from src.infra.database.market.shareholder_count import (
        create_shareholder_count_repository,
    )

    def _div():
        end = dt.date.today()
        rows = create_stock_dividend_repository().get_history(
            symbol, start=end - timedelta(days=10 * 365), end=end,
        )
        years = {}
        for r in rows:
            if r.div_per_share and r.ex_date:
                years.setdefault(r.ex_date.year, False)
                years[r.ex_date.year] = True
        if not years:
            return None
        all_y = list(range(min(years), dt.date.today().year + 1))
        return [years.get(y, False) for y in all_y]

    def _payout():
        repo = create_alert_repository()
        dv = repo.get_latest_metric_value(symbol, "dv_ttm")
        pe = repo.get_latest_metric_value(symbol, "pe_ttm")
        return round(dv * pe, 1) if dv is not None and pe else None

    def _roic():
        r = roic(service._financial_assembly(symbol))
        return round(r * 100, 2) if r is not None else None

    def _holder():
        rows = create_shareholder_count_repository().get_history(
            symbol
        )
        counts = [
            (h.report_date, h.holder_count) for h in rows
            if h.holder_count
        ]
        if len(counts) < 2:
            return None
        latest_d, latest_c = counts[-1]
        year_ago = [
            c for d, c in counts if (latest_d - d).days >= 300
        ]
        if not year_ago:
            return None
        base = year_ago[-1]
        return round((latest_c - base) / base * 100, 1)

    with ThreadPoolExecutor(max_workers=4) as ex:
        div_f = ex.submit(_div)
        pay_f = ex.submit(_payout)
        roic_f = ex.submit(_roic)
        hold_f = ex.submit(_holder)
    out = capital_allocation(
        div_f.result(), pay_f.result(), roic_f.result(), hold_f.result(),
    )
    return out.get("score")


def dividend_calendar() -> Any:
    """持仓股息现金流（二期F4）：未来12月排期+年增速+增长史。"""
    from datetime import timedelta
    from src.domain.market.fundamental.dividend_projection import (
        dividend_projection,
    )
    from src.infra.database.market.dividend import (
        create_stock_dividend_repository,
    )

    repo = _repo()
    theses = repo.list_theses(status="active")
    held = [t for t in theses if t.get("shares") and t.get("symbol")]
    if not held:
        return responses.success({"rows": [], "total_next_12m": None})
    div_repo = create_stock_dividend_repository()
    end = dt.date.today()
    start = end - timedelta(days=6 * 365)
    from src.domain.market.fundamental.buy_point_map import (
        dividend_tax,
    )
    rows = []
    total = 0.0
    for t in held:
        try:
            hist = div_repo.get_history(t["symbol"], start, end)
            events = [
                {"ex_date": r.ex_date, "div_per_share": r.div_per_share}
                for r in hist if r.div_per_share
            ]
            proj = dividend_projection(
                events, t["shares"], today=end,
            )
            total += proj.get("next_12m_amount") or 0
            # P2: 每笔排期按论点买入日算差别化税率
            buy_d = t.get("buy_date")
            monthly = proj.get("monthly") or []
            for m in monthly:
                try:
                    ex_dt = dt.date.fromisoformat(m["month"] + "-15")
                except ValueError:
                    ex_dt = None
                tax = dividend_tax(
                    dt.date.fromisoformat(buy_d) if buy_d else None,
                    ex_dt,
                )
                m["tax_rate_pct"] = tax["rate_pct"]
                m["free_after"] = tax["free_after"]
            rows.append({
                "symbol": t["symbol"], "shares": t["shares"],
                "latest_annual_dps": proj.get("latest_annual_dps"),
                "growth_pct": proj.get("latest_growth_pct"),
                "next_12m": proj.get("next_12m_amount"),
                "monthly": monthly,
                "annual": proj.get("annual"),
            })
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "dividend_calendar %s 失败: %s", t["symbol"], e)
    rows.sort(key=lambda r: -(r.get("next_12m") or 0))
    return responses.success({
        "rows": rows,
        "total_next_12m": round(total, 2),
        "note": "按历史除息月分布外推,实际以公告为准。",
    })


def add_ladder_fill(thesis_id: int, payload: dict) -> Any:
    """标记一档成交（二期F5）。"""
    repo = _repo()
    if not repo.get_thesis(thesis_id):
        return responses.error("论点不存在")
    try:
        fid = repo.add_ladder_fill(
            thesis_id, rung_index=int(payload["rung_index"]),
            price=float(payload["price"]),
            shares=int(payload["shares"]),
        )
    except (KeyError, TypeError, ValueError):
        return responses.error(
            "需 rung_index/price/shares"
        )
    fills = repo.list_ladder_fills(thesis_id)
    t = repo.get_thesis(thesis_id) or {}
    return responses.success({
        "id": fid,
        "ladder_progress": ladder_progress(
            t.get("entry_ladder") or [], fills,
        ),
    })


def delete_ladder_fill(thesis_id: int, fill_id: int) -> Any:
    repo = _repo()
    ok = repo.delete_ladder_fill(fill_id)
    if not ok:
        return responses.error("成交记录不存在")
    fills = repo.list_ladder_fills(thesis_id)
    t = repo.get_thesis(thesis_id) or {}
    return responses.success({
        "deleted": True,
        "ladder_progress": ladder_progress(
            t.get("entry_ladder") or [], fills,
        ),
    })


def list_notes(symbol: Optional[str] = None) -> Any:
    return responses.success(_repo().list_notes(symbol=symbol))


def add_note(payload: dict) -> Any:
    symbol = (payload.get("symbol") or "").strip().lower()
    title = (payload.get("title") or "").strip()
    if not symbol or not title:
        return responses.error("symbol 与 title 必填")
    nid = _repo().add_note(
        symbol, title, (payload.get("content") or "").strip(),
    )
    return responses.success({"id": nid})


def update_note(note_id: int, payload: dict) -> Any:
    title = (payload.get("title") or "").strip()
    if not title:
        return responses.error("title 必填")
    ok = _repo().update_note(
        note_id, title, (payload.get("content") or "").strip(),
    )
    if not ok:
        return responses.error("笔记不存在")
    return responses.success({"updated": True})


def delete_note(note_id: int) -> Any:
    ok = _repo().delete_note(note_id)
    if not ok:
        return responses.error("笔记不存在")
    return responses.success({"deleted": True})


def closed_perf() -> Any:
    """关闭论点的后续表现（三期G2）。"""
    repo = _repo()
    closed = repo.list_theses(status="closed")
    prices = repo.latest_close(
        [t["symbol"] for t in closed if t.get("close_price")]
    )
    return responses.success(closed_performance(closed, prices))


def list_pass() -> Any:
    """放弃决策列表 + 错过复盘（个股涨跌 vs 同窗口沪深300）。"""
    repo = _repo()
    rows = repo.list_pass_decisions()
    symbols = [r["symbol"] for r in rows if r.get("price")]
    prices = repo.latest_close(symbols) if symbols else {}
    bench_rows = []
    try:
        dated = [r["decision_date"] for r in rows
                 if r.get("price") and r.get("decision_date")]
        if dated:
            bench_rows = _index_close_series(
                "sh000300", min(dated))
    except Exception:
        bench_rows = []
    out = pass_performance(rows, prices, bench_rows)
    names = repo.names_for(list({r["symbol"] for r in rows}))
    for r in out["rows"]:
        r["name"] = names.get(r["symbol"])
    return responses.success(out)


def add_pass(payload: dict) -> Any:
    """记一笔放弃决策（服务端抓快照；可补记历史日期）。"""
    symbol = (payload.get("symbol") or "").strip().lower()
    reason = (payload.get("reason") or "").strip()
    if not symbol:
        return responses.error("symbol 必填")
    if not reason:
        return responses.error("放弃理由必填（为什么研究后不买）")
    try:
        confidence = _clean_confidence(payload.get("confidence"))
    except (TypeError, ValueError):
        return responses.error("confidence 应为 1~5")
    decision_date = None
    if payload.get("decision_date"):
        try:
            decision_date = dt.date.fromisoformat(
                payload["decision_date"])
        except (TypeError, ValueError):
            return responses.error("decision_date 格式应为 YYYY-MM-DD")
    price = payload.get("price")
    repo = _repo()
    if price is None:
        try:
            price = repo.latest_close([symbol]).get(symbol)
        except Exception:
            price = None
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        return responses.error("price 应为数字")
    snapshot = service.capture_snapshot(symbol, price=price)
    pid = repo.add_pass_decision({
        "symbol": symbol, "decision_date": decision_date,
        "price": price, "reason": reason,
        "revisit_when": (payload.get("revisit_when") or "").strip()
        or None,
        "confidence": confidence, "snapshot": snapshot,
    })
    return responses.success({"id": pid})


def delete_pass(pass_id: int) -> Any:
    ok = _repo().delete_pass_decision(pass_id)
    if not ok:
        return responses.error("放弃记录不存在")
    return responses.success({"deleted": True})


def calibration() -> Any:
    """信心度校准：已关闭论点按登记时信心分组的胜率/盈亏。"""
    repo = _repo()
    closed = repo.list_theses(status="closed")
    journals = repo.list_journal_all(limit=1000)
    return responses.success(
        confidence_calibration(closed, journals)
    )


def pipeline() -> Any:
    """研究管道（三期G5）：阶段由现有数据推导，零新表。"""
    repo = _repo()
    import datetime as _dt
    from src.infra.database.market.checklist import (
        create_checklist_repository,
    )
    cutoff = _dt.datetime.now() - _dt.timedelta(days=90)
    try:
        checked = {
            r["symbol"] for r in repo_rows_checked(cutoff)
        }
    except Exception:
        checked = set()
    noted = set()
    try:
        noted = {n["symbol"] for n in repo.list_notes()}
    except Exception:
        pass
    active = {t["symbol"] for t in repo.list_theses(status="active")}
    closed = {t["symbol"] for t in repo.list_theses(status="closed")}
    watch = set()
    try:
        watch = repo_watchlist_symbols()
    except Exception:
        pass
    return responses.success(pipeline_stages(
        watch, checked, noted, active, closed,
    ))


def repo_rows_checked(cutoff):
    """近90天有体检更新的标的（读 stock_checklist_item）。"""
    from src.infra.database.market.checklist import (
        create_checklist_repository,
    )
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT symbol FROM stock_checklist_item "
                "WHERE updated_at >= %s", (cutoff,),
            )
            return [{"symbol": r[0]} for r in cur.fetchall()]
    finally:
        conn.close()


def repo_watchlist_symbols():
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT symbol FROM watchlist_item"
            )
            return {r[0] for r in cur.fetchall()}
    finally:
        conn.close()


def thermometer_backtest() -> Any:
    """水位策略回测（三期G3）。"""
    from src.domain.market.fundamental.market_thermometer import (
        allocation_backtest,
    )
    repo = _repo()
    thermo = repo.list_thermometer(symbol="sh000300", days=8000)
    idx = _index_close_series("sh000300", thermo[0]["trade_date"]
                              if thermo else None)
    return responses.success(allocation_backtest(thermo, idx))


def _index_close_series(symbol, start_iso=None, limit=5000):
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn
    sql = f"SELECT trade_date::text AS d, close_ FROM index_ohlcv " \
          f"WHERE symbol=%s"
    params = [symbol]
    if start_iso:
        sql += " AND trade_date >= %s"
        params.append(start_iso)
    sql += " ORDER BY trade_date"
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [{"trade_date": d, "close": c}
                    for d, c in cur.fetchall()]
    finally:
        conn.close()


def stress_test() -> Any:
    """组合压力测试（三期G4）：历史极端窗口实算。"""
    from src.domain.market.fundamental.portfolio_risk import (
        stress_test as stress_fn,
    )
    repo = _repo()
    theses = repo.list_theses(status="active")
    held = [t for t in theses if t.get("shares") and t.get("symbol")]
    if not held:
        return responses.success({"scenarios": [],
                                  "note": "无持仓论点"})
    symbols = [t["symbol"] for t in held]
    prices = repo.latest_close(symbols)
    total = sum((t["shares"] or 0) * prices.get(t["symbol"], 0)
                for t in held) or 1.0
    positions = [
        {"symbol": t["symbol"],
         "weight": (t["shares"] or 0) * prices.get(t["symbol"], 0)
         / total}
        for t in held
    ]
    scenarios = _crash_scenarios()
    history = _stock_history_map(symbols, scenarios)
    out = stress_fn(positions, scenarios, history)
    out["positions"] = positions
    return responses.success(out)


def _crash_scenarios():
    """历史极端窗（指数跌幅由 index_ohlcv 实算）。"""
    import datetime as _dt
    windows = [
        ("2018贸易战", "2018-01-24", "2018-12-28"),
        ("2020疫情冲击", "2020-01-06", "2020-03-23"),
        ("2021-2024长熊", "2021-02-10", "2024-01-19"),
        ("2024流动性冲击", "2023-12-29", "2024-02-05"),
    ]
    out = []
    for name, s, e in windows:
        rows = _index_close_series("sh000300", s)
        rows = [r for r in rows if s <= r["trade_date"] <= e]
        if len(rows) >= 2:
            first = rows[0]["close"]      # 窗口起点价(非窗口最低)
            last = rows[-1]["close"]
            out.append({
                "name": name, "start": s, "end": e,
                "index_drop_pct": round((last / first - 1) * 100, 1),
            })
    return out


def _stock_history_map(symbols, scenarios):
    """各持仓在各场景窗内的自身跌幅。"""
    out = {}
    for sc in scenarios:
        rows = {}
        for sym in symbols:
            import psycopg2
            from src.infra.database.sql_engine.dsn import get_dsn
            conn = psycopg2.connect(get_dsn())
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT close_ FROM stock_ohlcv "
                        "WHERE symbol=%s AND trade_date BETWEEN %s AND %s "
                        "ORDER BY trade_date", (sym, sc["start"], sc["end"]))
                    cs = [r[0] for r in cur.fetchall()]
            finally:
                conn.close()
            if len(cs) >= 2:
                rows[sym] = round((cs[-1] / cs[0] - 1) * 100, 1)
        out[sc["name"]] = rows
    return out
