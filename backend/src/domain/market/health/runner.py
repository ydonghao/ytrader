"""体检 runner：跑全部规则 → 落库 → 边沿去重推送（阶段二）。"""
import datetime as dt
import logging
from typing import Optional

from .registry import CheckResult, all_checks

log = logging.getLogger(__name__)


def run_checks(query, today=None) -> list:
    """纯执行：全部规则 → CheckResult 列表（不落库，可单测）。"""
    ctx = {"today": today or dt.date.today(), "query": query}
    out = []
    for spec in all_checks():
        try:
            out.append(spec["fn"](ctx))
        except Exception as e:  # noqa: BLE001
            out.append(CheckResult(
                check_id=spec["check_id"], table=spec["table"],
                severity=spec["severity"], status="fail",
                message=f"检查自身异常: {e}",
            ))
    return out


def _pg_query(sql: str) -> list:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from src.infra.database.sql_engine.dsn import get_dsn
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def edge_transitions(results: list, history: dict) -> list:
    """边沿触发去重（纯函数）：history={check_id: 上次 status}。

    ok→warn/fail 推异常；warn/fail→ok 推恢复；持续异常不推。
    info 级不推。
    """
    notify = []
    for r in results:
        if r.severity == "info":
            continue
        prev = history.get(r.check_id)
        if prev == r.status:
            continue
        if (prev in ("warn", "fail")) != (r.status in ("warn", "fail")):
            notify.append(r)
    return notify


def run_daily() -> dict:
    """每日 18:30 体检：落库 + 飞书边沿推送。"""
    from src.infra.database.market.data_health import (
        create_data_health_repository,
    )

    results = run_checks(_pg_query)
    repo = create_data_health_repository()
    history = repo.latest_status_map()
    repo.replace_today(results)
    notify = edge_transitions(results, history)
    for r in notify:
        _notify_feishu(r)
    summary = {
        "total": len(results),
        "fail": sum(1 for r in results if r.status == "fail"),
        "warn": sum(1 for r in results if r.status == "warn"),
        "notified": len(notify),
    }
    log.info("[DATA_HEALTH] %s", summary)
    return summary


def _notify_feishu(r) -> None:
    """用底层卡片直发(send_alert_notification 是价格告警专用签名)。"""
    try:
        from src.infra.notification.feishu import (
            _get_user_open_id,
            _send_message,
        )
        recovered = r.status == "ok"
        emoji = "✅" if recovered else "⚠️"
        color = "green" if recovered else "red"
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": color,
                "title": {
                    "tag": "plain_text",
                    "content": f"{emoji} 数据健康"
                               f"{'恢复' if recovered else '异常'}",
                },
            },
            "elements": [{
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**[{r.check_id}]** {r.table}\n"
                        f"{r.message}\n"
                        f"severity: {r.severity} · status: {r.status}"
                    ),
                },
            }],
        }
        open_id = _get_user_open_id()
        if open_id:
            _send_message(open_id, card)
    except Exception as e:  # noqa: BLE001
        log.warning("[DATA_HEALTH] feishu 通知失败: %s", e)
