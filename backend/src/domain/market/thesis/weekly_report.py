"""周报生成（价值投资四期 P3 + 2026-10 决策日志补全三段）：
纯函数聚合 + 存研究笔记。新增：错过复盘/管理层承诺动态/决策记分卡。
"""
import datetime as dt


def build_weekly_report(inputs: dict) -> dict:
    """inputs 见测试；输出 {week, sections, markdown}。"""
    temp = inputs.get("temperature") or {}
    now, prev = temp.get("now") or {}, temp.get("prev") or {}
    ree = inputs.get("reevals") or {}
    events = inputs.get("events") or []
    pipe = inputs.get("pipeline") or {}
    health = inputs.get("health") or {}
    cp = inputs.get("closed_perf") or {}

    lines = [
        f"# 投资周报 {inputs.get('week', '')}",
        "",
        "## 市场温度",
        f"- 当前：{now.get('level_label', '—')}"
        f"（ERP {now.get('erp_pct', '—')}%，"
        f"分位 {now.get('erp_percentile', '—')}%）",
        f"- 上周：{prev.get('level_label', '—')}"
        f"（ERP {prev.get('erp_pct', '—')}%）",
        "",
        "## 持仓重估（本周）",
        f"- {ree.get('sell_signal', 0)}/{ree.get('total', 0)} 重估触发"
        "卖出信号"
        f"（{ree.get('review', 0)} 个 review）",
        "",
        "## 本周事件",
    ]
    kind_label = {
        "condition_breached": "论点破位",
        "price_band_reached": "估值带到价",
        "reeval_done": "财报重估",
        "mine_detected": "排雷告警",
    }
    if events:
        for e in events[:10]:
            lines.append(
                f"- {kind_label.get(e.get('kind'), e.get('kind'))}"
                f"：{e.get('symbol', '')}"
            )
    else:
        lines.append("- 无")
    lines += [
        "",
        "## 研究管道",
        f"- 待决策 {pipe.get('checked', 0)} · 持仓 "
        f"{pipe.get('holding', 0)}",
        "",
        "## 数据健康",
        f"- fail {health.get('fail', '—')} / warn "
        f"{health.get('warn', '—')}",
    ]
    if cp.get("count"):
        lines += [
            "",
            "## 卖出后跟踪",
            f"- 已关闭 {cp['count']} 条：关闭后平均 "
            f"{cp.get('avg_pct', '—')}%，卖飞 "
            f"{cp.get('sold_early_count', 0)}/{cp['count']}",
        ]
    # ── 2026-10 决策日志补全/言行追踪接入：错过复盘 + 承诺动态 + 记分卡 ──
    pp = inputs.get("pass_perf") or {}
    if pp.get("count"):
        lines += [
            "",
            "## 错过复盘（放弃决策跟踪）",
            f"- 已评估 {pp['count']} 条放弃：平均 "
            f"{pp.get('avg_since_pct', '—')}% vs 基准 "
            f"{pp.get('avg_bench_pct', '—')}%（超额 "
            f"{pp.get('avg_excess_pct', '—')}%），踏空 "
            f"{pp.get('missed_count', 0)}/{pp['count']}",
        ]
    pm = inputs.get("promises") or {}
    if pm.get("week_new") or pm.get("verified"):
        lines += [
            "",
            "## 管理层承诺动态",
            f"- 本周新增 {pm.get('week_new', 0)} 条承诺"
            f"（年报抽取 {pm.get('week_new_report', 0)}/"
            f"预告导入 {pm.get('week_new_forecast', 0)}/"
            f"手动 {pm.get('week_new_manual', 0)}）",
            f"- 持仓承诺：待验证 {pm.get('pending', 0)} 条；"
            f"累计已验证 {pm.get('verified', 0)} 条，信用 "
            f"{pm.get('credit_pct') if pm.get('credit_pct') is not None else '—'}%",
        ]
    sc = inputs.get("scorecard") or {}
    if sc.get("active") is not None:
        win = (f"，胜率 {sc['closed_win_rate']}%" 
               if sc.get("closed_win_rate") is not None else "")
        lines += [
            "",
            "## 决策记分卡",
            f"- 持仓 {sc.get('active', 0)} · 已关闭 {sc.get('closed', 0)}{win}"
            f" · 放弃 {sc.get('pass', 0)} · 拟真已揭晓 {sc.get('exam', 0)} 局"
            f"（平均分 {sc.get('exam_avg_score') if sc.get('exam_avg_score') is not None else '—'}）",
        ]
    return {
        "week": inputs.get("week"),
        "sections": {
            "temperature": {
                "now_erp": now.get("erp_pct"),
                "now_label": now.get("level_label"),
                "prev_label": prev.get("level_label"),
            },
            "reevals": ree, "events": events,
            "pipeline": pipe, "health": health, "closed_perf": cp,
            "pass_perf": pp, "promises": pm, "scorecard": sc,
        },
        "markdown": "\n".join(lines),
    }


def collect_and_save() -> dict:
    """拉本周数据 → 周报 → 存研究笔记（symbol=__weekly__）。"""
    import datetime as _dt
    from src.infra.database.portfolio.thesis_repository import (
        create_thesis_repository,
    )

    repo = create_thesis_repository()
    today = _dt.date.today()
    week = f"{today.isocalendar().year}-W{today.isocalendar().week:02d}"
    week_ago = _dt.datetime.now() - _dt.timedelta(days=7)

    temp_now, temp_prev = {}, {}
    try:
        from src.domain.market.thesis.thermometer_service import (
            compute_thermometer,
        )
        t = compute_thermometer()
        temp_now = {
            "level_label": t.get("level_label"),
            "erp_pct": t.get("erp_pct"),
            "erp_percentile": t.get("erp_percentile"),
        }
        rows = repo.list_thermometer(days=10)
        if rows:
            prev_row = rows[max(0, len(rows) - 6)]
            temp_prev = {
                "level_label": prev_row.get("level_label"),
                "erp_pct": prev_row.get("erp_pct"),
            }
    except Exception:
        pass

    ree = {"total": 0, "sell_signal": 0, "review": 0}
    events = []
    try:
        sym_map = {t["id"]: t["symbol"]
                   for t in repo.list_theses()}
        for e in repo.list_events(limit=100):
            if e.get("created_at", "") >= week_ago.isoformat():
                events.append({
                    "kind": e.get("kind"),
                    "symbol": sym_map.get(e.get("thesis_id")),
                })
    except Exception:
        pass
    try:
        for t in repo.list_theses():
            for r in repo.list_reevals(t["id"], limit=20):
                if r["created_at"] >= week_ago.isoformat():
                    ree["total"] += 1
                    if r["verdict"] == "sell_signal":
                        ree["sell_signal"] += 1
                    elif r["verdict"] == "review":
                        ree["review"] += 1
    except Exception:
        pass

    pipe = {}
    try:
        from src.api.handler.thesis_handler import pipeline as _pipe
        import json as _json
        body = _pipe()
        pipe = _json.loads(body.body)["data"]["counts"]
    except Exception:
        pass

    health = {}
    try:
        from src.infra.database.market.data_health import (
            create_data_health_repository,
        )
        today_rows = create_data_health_repository().today()
        health = {
            "fail": sum(1 for r in today_rows
                        if r["status"] == "fail"),
            "warn": sum(1 for r in today_rows
                        if r["status"] == "warn"),
        }
    except Exception:
        pass

    cp = {}
    try:
        closed = repo.list_theses(status="closed")
        prices = repo.latest_close(
            [t["symbol"] for t in closed if t.get("close_price")]
        )
        from src.domain.market.fundamental.thesis_monitor import (
            closed_performance,
        )
        cp = closed_performance(closed, prices)["summary"]
    except Exception:
        pass

    # ── 2026-10 决策日志补全/言行追踪：错过复盘 + 持仓承诺 + 记分卡 ──
    pp = {}
    try:
        import json as _json

        from src.api.handler.thesis_handler import list_pass as _lp
        pp = _json.loads(_lp().body)["data"]["summary"]
    except Exception:
        pp = {}

    pm = {}
    try:
        from src.domain.market.fundamental.management_promise import (
            promise_credit_summary,
        )
        from src.infra.database.market.management_promise import (
            create_management_promise_repository,
        )
        prepo = create_management_promise_repository()
        rows = []
        for t in repo.list_theses(status="active"):
            rows.extend(prepo.list(t["symbol"]))
        credit = promise_credit_summary(rows)
        week_new = [r for r in rows
                    if (r.get("created_at") or "") >= week_ago.isoformat()]
        pm = {
            "week_new": len(week_new),
            "week_new_report": sum(
                1 for r in week_new
                if r.get("source") == "annual_report"),
            "week_new_forecast": sum(
                1 for r in week_new if r.get("source") == "forecast"),
            "week_new_manual": sum(
                1 for r in week_new if r.get("source") == "manual"),
            "pending": credit["pending"],
            "verified": credit["verified"],
            "credit_pct": credit["credit_pct"],
        }
    except Exception:
        pm = {}

    sc = {}
    try:
        active = repo.list_theses(status="active")
        closed = repo.list_theses(status="closed")
        pnls = [
            (t["close_price"] / t["buy_price"] - 1)
            for t in closed
            if t.get("close_price") and t.get("buy_price")
        ]
        sc = {
            "active": len(active), "closed": len(closed),
            "closed_win_rate": (
                round(100 * sum(1 for p in pnls if p > 0) / len(pnls), 1)
                if pnls else None),
            "pass": len(repo.list_pass_decisions()),
        }
        from src.infra.database.replay.repository import (
            create_replay_repository,
        )
        exam_rows = [
            s for s in create_replay_repository().list()
            if (s.mode or "free") == "exam" and s.status == "revealed"
        ]
        scores = [
            sc_ for sc_ in (
                ((s.state or {}).get("score") or {}).get("total")
                for s in exam_rows)
            if sc_ is not None
        ]
        sc["exam"] = len(exam_rows)
        sc["exam_avg_score"] = (
            round(sum(scores) / len(scores), 1) if scores else None)
    except Exception:
        sc = {}

    report = build_weekly_report({
        "week": week, "temperature": {
            "now": temp_now, "prev": temp_prev,
        },
        "reevals": ree, "events": events, "pipeline": pipe,
        "health": health, "closed_perf": cp,
        "pass_perf": pp, "promises": pm, "scorecard": sc,
    })
    repo.add_note(
        symbol="__weekly__",
        title=f"投资周报 {week}",
        content=report["markdown"],
    )
    return report
