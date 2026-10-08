"""论点监控纯函数（课程 3.7 买卖一致性：论点破即卖）。
import datetime as dt

自 portfolio/course_allocation.py 搬迁（2026-09-27），course_allocation
原位 re-export 保持兼容。本模块后续承载 METRIC_REGISTRY / 卖出体检 /
重估 verdict 等持仓论点体系纯函数。
"""
import datetime as dt
from dataclasses import dataclass, field


@dataclass
class ThesisCondition:
    """单条量化入场论点（用于论点破即卖）。"""

    metric: str          # 指标名（与 current_metrics 字典 key 对齐）
    operator: str        # ">=" / ">" / "<=" / "<" / "=="
    threshold: float
    label: str = ""


@dataclass
class ThesisMonitorResult:
    """论点监控结果。"""

    breached: list = field(default_factory=list)
    held: list = field(default_factory=list)
    recommend_sell: bool = False


_OPS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


def evaluate_thesis(conditions: list, current_metrics: dict):
    """任一条件破 → recommend_sell；无法评估（缺值/类型错）视为暂未破。

    用法：买入时固化一组量化论点（如"营收增速维持>=10%"、"ROE>=15%"），
    之后定期用最新指标评估；论点一旦失守，说明当初买入的逻辑已不成立，
    按一致性原则应卖出。
    """
    res = ThesisMonitorResult()
    for c in conditions:
        op = _OPS.get(c.operator)
        v = current_metrics.get(c.metric)
        if op is None or v is None:
            res.held.append(c)
            continue
        try:
            ok = op(v, c.threshold)
        except TypeError:
            res.held.append(c)
            continue
        (res.held if ok else res.breached).append(c)
    res.recommend_sell = len(res.breached) > 0
    return res


# ── 论点指标注册表与派生计算 ──────────────────────────────────────────

METRIC_REGISTRY: dict = {
    "roe":            {"label": "ROE",              "unit": "%"},
    "revenue_yoy":    {"label": "营收同比",          "unit": "%"},
    "net_profit_yoy": {"label": "净利同比",          "unit": "%"},
    "gross_margin":   {"label": "毛利率",            "unit": "%"},
    "ocf_ratio":      {"label": "经营现金流/净利润", "unit": "x"},
    "debt_ratio":     {"label": "资产负债率",        "unit": "%"},
    "pe_ttm":         {"label": "PE(TTM)",           "unit": "x"},
    "pb":             {"label": "PB",                "unit": "x"},
    "dv_ttm":         {"label": "股息率",            "unit": "%"},
}


def _yoy(now, prev):
    if now is None or prev in (None, 0):
        return None
    return (now - prev) / abs(prev) * 100.0


def _annual_factor(report_date) -> float:
    """累计报告期→年化系数：中报×2 / 一季报×4 / 年报×1。"""
    import datetime as _dt

    if isinstance(report_date, str):
        try:
            report_date = _dt.date.fromisoformat(report_date[:10])
        except ValueError:
            return None
    if not isinstance(report_date, _dt.date) or report_date.month < 1:
        return None
    return 12.0 / report_date.month


def compute_metric_values(assembled: dict) -> dict:
    """从装配字典计算 METRIC_REGISTRY 全部指标；缺数据的键输出 None。

    roe：优先 TTM 净利/权益（当期+上年年报−去年同期，无季节失真）；
    缺 TTM 时退化为累计净利按报告期月数年化（中报×2，季节性失真）；
    两者都不可得 → None（诚实缺失优于错误值）。
    """
    np_ = assembled.get("net_profit")
    eq = assembled.get("equity")
    ta = assembled.get("total_assets")
    tl = assembled.get("total_liabilities")
    factor = _annual_factor(assembled.get("report_date"))
    np_ttm = assembled.get("net_profit_ttm")
    if np_ttm and eq:
        roe = np_ttm / eq * 100.0
    elif np_ and eq and factor:
        roe = np_ / eq * 100.0 * factor
    else:
        roe = None
    return {
        "roe": roe,
        "revenue_yoy": _yoy(assembled.get("revenue"),
                            assembled.get("revenue_prev")),
        "net_profit_yoy": _yoy(np_, assembled.get("net_profit_prev")),
        "gross_margin": assembled.get("gross_margin"),
        "ocf_ratio": (assembled.get("ocf") / np_)
        if assembled.get("ocf") and np_ else None,
        "debt_ratio": (tl / ta * 100.0) if tl and ta else None,
        "pe_ttm": assembled.get("pe_ttm"),
        "pb": assembled.get("pb"),
        "dv_ttm": assembled.get("dv_ttm"),
    }


def reeval_verdict(quality_now, quality_base, conditions_result) -> str:
    """重估三档：条件破/质量淘汰→sell_signal；降分>10或新红旗→review。"""
    if any(c.get("status") == "breached" for c in conditions_result):
        return "sell_signal"
    if quality_now and quality_now.get("verdict") == "eliminate":
        return "sell_signal"
    if quality_now and quality_base:
        drop = (quality_base.get("score") or 0) - (
            quality_now.get("score") or 0
        )
        if drop > 10:
            return "review"
        base_flags = set(quality_base.get("red_flags") or [])
        now_flags = set(quality_now.get("red_flags") or [])
        if now_flags - base_flags:
            return "review"
    return "pass"


def check_price_band(band, price, metrics) -> dict:
    """卖出估值带到价检测：现值进入带内(>=low)即到位；
    跌破下沿不算到价（那是另一侧信号）；reached=None 表示无法评估。"""
    if not band:
        return {"metric": None, "current": None, "low": None,
                "high": None, "reached": None}
    metric = band.get("metric") or "price"
    current = price if metric == "price" else metrics.get(metric)
    low, high = band.get("low"), band.get("high")
    reached = None
    if current is not None and low is not None:
        reached = current >= low
    return {"metric": metric, "current": current, "low": low,
            "high": high, "reached": reached}


def _margin(price, fair):
    """安全边际%（正=低估，负=高估）。兼容每股价×每股公允。"""
    if not price or not fair:
        return None
    return (fair - price) / fair * 100.0


def upside_to_margin(upside):
    """相对上行(内在/市值−1) → 安全边际%：m = up/(1+up)×100。

    估值端点返回的内在值多为公司总值，与每股价格不可直接比；
    比率口径与股数无关。
    """
    if upside is None or upside <= -1:
        return None
    return upside / (1.0 + upside) * 100.0


def build_sell_check(
    thesis, conditions, current_metrics, band_result=None,
    snapshot=None, valuation_now=None, quality_now=None, now=None,
):
    """四区卖出体检纯组装。数据装配由 handler/service 注入。"""
    now = now or dt.datetime.now()
    last = thesis.get("last_reviewed_at")
    if isinstance(last, str):
        last = dt.datetime.fromisoformat(last)
    stale_days = (now - last).days if last else None

    eval_conditions = [
        ThesisCondition(
            metric=c["metric_key"], operator=c["operator"],
            threshold=c["threshold"], label=c.get("label", ""),
        )
        for c in conditions
    ]
    res = evaluate_thesis(eval_conditions, current_metrics)
    cond_by_key = {
        (c["metric_key"], c["operator"], c["threshold"]): c
        for c in conditions
    }
    items = []
    for ec in (res.breached + res.held):
        base = cond_by_key.get(
            (ec.metric, ec.operator, ec.threshold), {}
        )
        current = current_metrics.get(ec.metric)
        status = "breached" if ec in res.breached else (
            "unknown" if current is None else "holding"
        )
        items.append({
            "id": base.get("id"),
            "metric_key": ec.metric,
            "label": base.get("label") or ec.label
            or METRIC_REGISTRY.get(ec.metric, {}).get("label", ec.metric),
            "operator": ec.operator,
            "threshold": ec.threshold,
            "current": current,
            "status": status,
        })

    snap_val = (snapshot or {}).get("valuation") or {}
    margin_then = upside_to_margin(snap_val.get("dcf_upside"))
    margin_now = upside_to_margin(
        (valuation_now or {}).get("dcf_upside")
    )
    margin_consumed = (
        margin_then - margin_now
        if margin_then is not None and margin_now is not None else None
    )
    snap_q = (snapshot or {}).get("quality") or {}
    score_diff = (
        (quality_now or {}).get("score", 0) - snap_q.get("score", 0)
        if quality_now and snap_q else None
    )
    new_flags = list(
        set((quality_now or {}).get("red_flags") or [])
        - set(snap_q.get("red_flags") or [])
    )

    return {
        "sections": {
            "thesis": {
                "title": "论点体检",
                "items": items,
                "recommend_sell": res.recommend_sell,
                "stale": bool(stale_days is not None and stale_days > 90),
            },
            "valuation": {
                "title": "估值到位",
                "band": band_result
                or {"metric": None, "current": None, "low": None,
                    "high": None, "reached": None},
                "margin_then": margin_then,
                "margin_now": margin_now,
                "margin_consumed": margin_consumed,
                "valuation_now": valuation_now,
            },
            "fundamentals": {
                "title": "基本面变化",
                "quality_now": quality_now,
                "quality_then": snap_q or None,
                "score_diff": score_diff,
                "new_red_flags": new_flags,
            },
            "decision": {
                "title": "卖出决策",
                "questions": [
                    "买入逻辑是否已被证伪？",
                    "估值是否到达目标卖出区间？",
                    "是否有明显更优的替代标的？",
                ],
                "decision": thesis.get("decision"),
                "decision_note": thesis.get("decision_note"),
            },
        },
        "recommend_sell": res.recommend_sell,
        "stale_days": stale_days,
    }


def build_review_summary(closed_theses, journal_rows,
                         last_review_at, now=None) -> dict:
    """组合级复盘汇总：按关闭原因统计盈亏 + 最近决策 + 复盘提醒。

    closed_theses: 关闭论点 dict 列表（close_reason/buy_price/close_price）
    journal_rows:  日志 dict 列表（含 symbol，倒序或乱序均可）
    """
    now = now or dt.datetime.now()
    if isinstance(last_review_at, str):
        last_review_at = dt.datetime.fromisoformat(last_review_at)
    stale = True
    if last_review_at:
        stale = (now - last_review_at).days > 30

    groups: dict = {}
    for t in closed_theses:
        reason = t.get("close_reason")
        buy, close = t.get("buy_price"), t.get("close_price")
        if not reason or not buy or not close:
            continue
        g = groups.setdefault(reason, {"reason": reason, "count": 0,
                                       "pnl_sum": 0.0, "win_count": 0})
        pnl = (close / buy - 1.0) * 100.0
        g["count"] += 1
        g["pnl_sum"] += pnl
        if pnl > 0:
            g["win_count"] += 1
    closed_stats = [
        {"reason": g["reason"], "count": g["count"],
         "avg_pnl_pct": round(g["pnl_sum"] / g["count"], 2),
         "win_count": g["win_count"]}
        for g in groups.values()
    ]
    recent = sorted(
        (j for j in journal_rows
         if j.get("kind") in ("decision", "close")),
        key=lambda j: j.get("created_at") or "",
        reverse=True,
    )[:20]
    return {
        "stale_review": stale,
        "last_review_at": last_review_at.isoformat()
        if last_review_at else None,
        "closed_stats": closed_stats,
        "recent_decisions": recent,
    }


_VALUATION_METRICS = {"pe_ttm", "pb", "dv_ttm"}


def backtest_conditions(conditions: list, periods: list) -> dict:
    """条件集合在历史财报期上的逐期回测（阈值校准）。

    periods 升序 [{report_date(iso), <财务字段>}]；自第 2 期起评估
    （第 1 期作 yoy 基期）。估值类条件（pe/pb/dv）无历史序列 → unknown，
    汇总进 valuation_unsupported。
    """
    unsupported = sorted({
        c["metric_key"] for c in conditions
        if c["metric_key"] in _VALUATION_METRICS
    })
    eval_conditions = [
        ThesisCondition(
            metric=c["metric_key"], operator=c["operator"],
            threshold=c["threshold"],
        )
        for c in conditions
    ]
    def _year_ago_idx(rows, i):
        """rows[i] 的去年同一报告期行号；找不到返回 None。"""
        import datetime as _dt

        try:
            d = _dt.date.fromisoformat(str(rows[i]["report_date"])[:10])
        except (ValueError, KeyError, TypeError):
            return None
        target = d.replace(year=d.year - 1)
        for j in range(i):
            try:
                dj = _dt.date.fromisoformat(
                    str(rows[j]["report_date"])[:10]
                )
            except (ValueError, KeyError, TypeError):
                continue
            if dj == target:
                return j
        return None

    def _prev_fy_idx(rows, i):
        """rows[i] 之前最近的一个年报（12月）行号。"""
        for j in range(i - 1, -1, -1):
            rd = str(rows[j].get("report_date"))[:10]
            if len(rd) == 10 and rd[5:7] == "12":
                return j
        return None

    out_periods = []
    stats = {id(c): {"evaluated": 0, "breached": 0,
                     "first": None} for c in eval_conditions}
    for i in range(1, len(periods)):
        cur = periods[i]
        base_j = _year_ago_idx(periods, i)
        base = periods[base_j] if base_j is not None else None
        fy_j = _prev_fy_idx(periods, i)
        assembled = dict(cur)
        assembled["net_profit"] = cur.get("net_profit_parent")
        if base is not None:   # 同期基期（去年同一报告期）
            assembled.setdefault("revenue_prev", base.get("revenue"))
            assembled.setdefault(
                "net_profit_prev", base.get("net_profit_parent"),
            )
        # TTM 净利 = 当期 + 上年年报 − 去年同期（无季节失真的 ROE）
        if base is not None and fy_j is not None:
            cur_np = cur.get("net_profit_parent")
            fy_np = periods[fy_j].get("net_profit_parent")
            ya_np = base.get("net_profit_parent")
            if None not in (cur_np, fy_np, ya_np):
                assembled["net_profit_ttm"] = cur_np + fy_np - ya_np
        metrics = compute_metric_values(assembled)
        result = evaluate_thesis(eval_conditions, metrics)
        entry = {"report_date": cur.get("report_date"), "conditions": []}
        for cond_raw, ec in zip(conditions, eval_conditions):
            current = metrics.get(ec.metric)
            if ec.metric in _VALUATION_METRICS or current is None:
                status = "unknown"
            else:
                status = ("breached" if ec in result.breached
                          else "holding")
            st = stats[id(ec)]
            if status != "unknown":
                st["evaluated"] += 1
                if status == "breached":
                    st["breached"] += 1
                    if st["first"] is None:
                        st["first"] = cur.get("report_date")
            entry["conditions"].append({
                "metric_key": ec.metric, "operator": ec.operator,
                "threshold": ec.threshold, "current": current,
                "status": status,
            })
        out_periods.append(entry)

    summary = []
    for cond_raw, ec in zip(conditions, eval_conditions):
        st = stats[id(ec)]
        summary.append({
            "metric_key": ec.metric, "operator": ec.operator,
            "threshold": ec.threshold,
            "evaluated": st["evaluated"], "breached": st["breached"],
            "breach_rate": (st["breached"] / st["evaluated"]
                            if st["evaluated"] else None),
            "first_breach_report_date": st["first"],
        })
    return {
        "periods": out_periods,
        "summary": summary,
        "valuation_unsupported": unsupported,
        "note": "自第2期起评估(第1期作yoy基期)；估值类条件暂不支持。",
    }


def ladder_progress(ladder: list, fills: list) -> dict:
    """三档建仓执行进度（二期F5）。

    ladder: [{rung_index, price_level, weight_of_position, amount, shares}]
    fills:  [{rung_index, price, shares}]
    """
    fill_by_rung: dict = {}
    for f in fills:
        fill_by_rung.setdefault(f["rung_index"], []).append(f)
    rungs_out = []
    invested = 0.0
    total_shares = 0
    for rung in ladder or []:
        fl = fill_by_rung.get(rung.get("rung_index")) or []
        cost = sum(f["price"] * f["shares"] for f in fl)
        sh = sum(f["shares"] for f in fl)
        invested += cost
        total_shares += sh
        rungs_out.append({
            "rung_index": rung.get("rung_index"),
            "drop_pct": rung.get("drop_pct"),
            "price_level": rung.get("price_level"),
            "weight_of_position": rung.get("weight_of_position"),
            "shares": rung.get("shares"),
            "filled": bool(fl),
            "fill_price": fl[-1]["price"] if fl else None,
            "fill_shares": sh or None,
            "fill_cost": round(cost, 2) or None,
        })
    planned = sum(
        r.get("amount") or 0 for r in ladder or []
    )
    return {
        "rungs": rungs_out,
        "rungs_done": sum(1 for r in rungs_out if r["filled"]),
        "rungs_total": len(rungs_out),
        "invested": round(invested, 2),
        "planned_total": planned,
        "invested_pct": round(invested / planned * 100, 2)
        if planned else None,
        "avg_fill_price": round(invested / total_shares, 4)
        if total_shares else None,
    }


def closed_performance(closed_theses: list, prices: dict) -> dict:
    """关闭论点的后续表现（三期G2）——卖出决策的硬反馈。

    since_close_pct>0 = 关闭后上涨 = 卖飞；<0 = 关闭后下跌 = 卖对。
    """
    rows = []
    for t in closed_theses:
        cp, cur = t.get("close_price"), prices.get(t.get("symbol"))
        if not cp or not cur:
            continue
        pct = (cur / cp - 1) * 100
        rows.append({
            "id": t.get("id"), "symbol": t.get("symbol"),
            "closed_at": t.get("closed_at"),
            "close_price": cp, "current_price": cur,
            "since_close_pct": round(pct, 2),
            "verdict": "卖飞" if pct > 0 else "卖对",
        })
    pcts = [r["since_close_pct"] for r in rows]
    summary = {
        "count": len(rows),
        "avg_pct": round(sum(pcts) / len(pcts), 2) if pcts else None,
        "sold_early_count": sum(1 for p in pcts if p > 0),
    }
    return {"rows": rows, "summary": summary}


def pass_performance(pass_rows: list, prices: dict,
                     bench_rows: list) -> dict:
    """放弃决策的后续表现——"没买之后怎样"，closed_performance 的镜像。

    pass_rows: pass_decision 记录（symbol/decision_date/price）；
    prices: {symbol: 现价}；bench_rows: 基准收盘序列
    [{trade_date, close}] 升序。excess_pct = 个股涨跌幅 − 同窗口基准涨跌幅，
    verdict 按 excess 判：>0 踏空（不买跑输基准），<=0 回避正确。
    """
    def _bench_pct(from_iso):
        """放弃日起基准涨跌幅（起点取首个 >= 放弃日的收盘）。"""
        if not bench_rows or not from_iso:
            return None
        first = next((b["close"] for b in bench_rows
                      if b["trade_date"] >= from_iso), None)
        if not first or bench_rows[-1]["close"] is None:
            return None
        return (bench_rows[-1]["close"] / first - 1) * 100

    rows = []
    for p in pass_rows:
        px, cur = p.get("price"), prices.get(p.get("symbol"))
        row = dict(p)
        row["current_price"] = cur
        row["since_pct"] = (round((cur / px - 1) * 100, 2)
                            if px and cur else None)
        row["bench_pct"] = round(b, 2) if (
            b := _bench_pct(p.get("decision_date"))) is not None else None
        if row["since_pct"] is None or row["bench_pct"] is None:
            row["excess_pct"] = None
            row["verdict"] = None
        else:
            row["excess_pct"] = round(row["since_pct"] - row["bench_pct"], 2)
            row["verdict"] = ("踏空" if row["excess_pct"] > 0
                              else "回避正确")
        rows.append(row)
    scored = [r for r in rows if r["excess_pct"] is not None]
    summary = {
        "count": len(scored),
        "avg_since_pct": (round(sum(r["since_pct"] for r in scored)
                                / len(scored), 2) if scored else None),
        "avg_bench_pct": (round(sum(r["bench_pct"] for r in scored)
                                / len(scored), 2) if scored else None),
        "avg_excess_pct": (round(sum(r["excess_pct"] for r in scored)
                                 / len(scored), 2) if scored else None),
        "missed_count": sum(1 for r in scored if r["excess_pct"] > 0),
    }
    return {"rows": rows, "summary": summary}


def confidence_calibration(closed_theses: list, journal_rows: list) -> dict:
    """信心度校准：按登记时信心分组的已关闭论点胜率/盈亏。

    journal_rows 需含 thesis_id/kind/confidence；置信度取该论点最早的
    created 日志条目。信心与胜率长期无梯度 = 系统性过度自信的信号。
    """
    conf_of: dict = {}
    for j in sorted(journal_rows,
                    key=lambda x: x.get("created_at") or ""):
        if (j.get("kind") == "created"
                and j.get("confidence") is not None
                and j.get("thesis_id") is not None
                and j.get("thesis_id") not in conf_of):
            conf_of[j["thesis_id"]] = j["confidence"]
    groups: dict = {}
    no_conf = 0
    for t in closed_theses:
        buy, close = t.get("buy_price"), t.get("close_price")
        if not buy or not close:
            continue
        conf = conf_of.get(t.get("id"))
        if conf is None:
            no_conf += 1
            continue
        pnl = (close / buy - 1.0) * 100.0
        g = groups.setdefault(conf, {"confidence": conf, "count": 0,
                                     "win_count": 0, "pnl_sum": 0.0})
        g["count"] += 1
        g["pnl_sum"] += pnl
        if pnl > 0:
            g["win_count"] += 1
    out = []
    for conf in sorted(groups):
        g = groups[conf]
        out.append({
            "confidence": conf, "count": g["count"],
            "win_count": g["win_count"],
            "win_rate": round(g["win_count"] / g["count"], 3),
            "avg_pnl_pct": round(g["pnl_sum"] / g["count"], 2),
        })
    return {"groups": out, "no_confidence_count": no_conf}


_STAGE_ORDER = ["holding", "closed", "checked", "noted", "watching"]
_STAGE_LABEL = {
    "holding": "持仓中", "closed": "已关闭", "checked": "已体检待决策",
    "noted": "研究中", "watching": "观察",
}


def pipeline_stages(watch, checked, noted, active, closed) -> dict:
    """标的研究阶段（三期G5）：由现有数据推导，零新表。

    优先级：持仓 > 已关闭 > 已体检(未登记=漏斗滞留点) > 已笔记 > 观察。
    """
    rows = []
    all_syms = (watch | checked | noted | active | closed)
    for sym in all_syms:
        if sym in active:
            stage = "holding"
        elif sym in closed:
            stage = "closed"
        elif sym in checked:
            stage = "checked"
        elif sym in noted:
            stage = "noted"
        else:
            stage = "watching"
        rows.append({"symbol": sym, "stage": stage,
                     "stage_label": _STAGE_LABEL[stage]})
    counts = {st: 0 for st in _STAGE_ORDER}
    for r in rows:
        counts[r["stage"]] += 1
    rows.sort(key=lambda r: (_STAGE_ORDER.index(r["stage"]), r["symbol"]))
    return {
        "rows": rows, "counts": counts,
        "note": "已体检待决策 = 体检过但未登记论点的滞留层，"
                "定期清空这层防研究烂尾。",
    }
