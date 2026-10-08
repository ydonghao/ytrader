"""自愈闭环（阶段三·骨架）：默认干跑，只建议+审计，不动表。

复用各 domain 现有 sync 函数回补，不重写拉取逻辑。
干跑开关：环境变量 YTRADER_HEAL_DRYRUN（默认 1=干跑）。
安全阀：每表每日回补窗口 ≤30 天；单次体检最多触发 5 个 heal。
"""
import datetime as dt
import logging
import os

from .runner import run_checks, _pg_query

log = logging.getLogger(__name__)

DRYRUN = os.environ.get("YTRADER_HEAL_DRYRUN", "1") != "0"

# check_id → heal 动作（复用现有 sync；K线类已有周六兜底不重复建）
HEAL_MAP = {
    "freshness_stock_valuation": {
        "fn": "src.domain.market.sync.jobs.fundamentals:run",
        "desc": "基本面周同步（估值+财务）",
    },
    "freshness_market_thermometer_daily": {
        "fn": "src.domain.market.thesis.thermometer_service:"
              "sync_thermometer_daily",
        "desc": "温度计当日快照",
    },
    "freshness_capital_event": {
        "fn": None,   # 周六 job 全量幂等，缺窗口>30天安全阀会拦
        "desc": "资本事件周六全量（幂等重跑即可补）",
    },
}


def collect_heal_candidates(results: list, max_heals: int = 5) -> list:
    """失败且有 heal 动作的检查 → 候选（纯函数，可单测）。"""
    out = []
    for r in results:
        if r.status in ("fail", "warn"):
            spec = HEAL_MAP.get(r.check_id)
            if spec:
                age = (r.metric or {}).get("age_days") or 0
                if age > 30:      # 安全阀：窗口上限
                    continue
                out.append({
                    "check_id": r.check_id,
                    "age_days": age, "desc": spec["desc"],
                    "fn": spec["fn"],
                })
        if len(out) >= max_heals:
            break
    return out


def run_heal() -> dict:
    """体检后执行：干跑只写审计+建议；实跑才调用 sync。"""
    from src.infra.database.market.data_health import (
        create_data_health_repository,
    )
    results = run_checks(_pg_query)
    candidates = collect_heal_candidates(results)
    executed = []
    for c in candidates:
        if DRYRUN or not c["fn"]:
            executed.append({**c, "mode": "dry", "rows": None})
            continue
        try:
            mod_path, fn_name = c["fn"].rsplit(":", 1)
            import importlib
            fn = getattr(importlib.import_module(mod_path), fn_name)
            out = fn()
            executed.append({
                **c, "mode": "run",
                "rows": (out or {}).get("rows")
                if isinstance(out, dict) else None,
            })
        except Exception as e:  # noqa: BLE001
            executed.append({**c, "mode": "error", "error": str(e)})
    mode = "dry" if DRYRUN else "run"
    log.info("[DATA_HEAL] mode=%s candidates=%d", mode, len(executed))
    # 审计落 data_health_result(以 check_id heal_ 前缀区分)
    from .registry import CheckResult
    repo = create_data_health_repository()
    audits = [
        CheckResult(
            check_id=f"heal_{e['check_id']}", table="heal_run",
            severity="info",
            status="ok" if e["mode"] != "error" else "fail",
            metric=e,
            message=f"自愈{e['mode']}: {e['desc']} (缺口{e['age_days']}天)",
        )
        for e in executed
    ]
    if audits:
        repo.replace_today([*results, *audits])
    return {"mode": mode, "heals": executed}
