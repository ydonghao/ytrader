"""数据健康检查框架（数据治理阶段二·方案A）。

规则纯函数化：输入 ctx={today, query(sql)->list[dict]}，输出 CheckResult；
query 由 runner 注入（生产 psycopg2 / 测试注入假实现），规则可单测。
"""
import datetime as dt
from dataclasses import dataclass, field
from typing import Callable, Optional

# severity: critical(功能受损)/warn(异常可观察)/info(口径注记)
_CHECKS: list[dict] = []


def register(check_id: str, table: str, severity: str = "warn"):
    def deco(fn):
        _CHECKS.append({
            "check_id": check_id, "table": table,
            "severity": severity, "fn": fn,
        })
        return fn
    return deco


@dataclass
class CheckResult:
    check_id: str
    table: str
    severity: str
    status: str                     # ok|warn|fail
    metric: dict = field(default_factory=dict)
    message: str = ""


def all_checks() -> list:
    return list(_CHECKS)


# ── 规则实现 ──────────────────────────────────────────────────────────────

def _max_date(ctx, table, col="trade_date") -> Optional[dt.date]:
    rows = ctx["query"](
        f"SELECT MAX({col})::date AS d FROM {table}"
    )
    return rows[0]["d"] if rows else None


def _freshness(ctx, check_id, table, max_calendar_days, severity,
               note="", col="trade_date"):
    """通用新鲜度检查：距最新交易日（自然日近似）。"""
    @register(check_id, table, severity)
    def _check(ctx=ctx):
        d = _max_date(ctx, table, col)
        age = (ctx["today"] - d).days if d else None
        if d is None:
            status = "fail"
        else:
            status = ("ok" if age <= max_calendar_days else
                      "fail" if severity == "critical" else "warn")
        return CheckResult(
            check_id=check_id, table=table, severity=severity,
            status=status,
            metric={"max_date": str(d), "age_days": age,
                    "tolerance_days": max_calendar_days},
            message=note or (
                f"{table} 最新 {d}（距今 {age} 天，容忍 {max_calendar_days}）"
            ),
        )
    return _check


# ── 12 条初始规则（逐表枚举，不临时挑）──────────────────────────────────
# 日频：容忍 4 自然日（≈2 交易日）；周频 9；月频 35
_DAILY = [
    ("stock_ohlcv", "critical"),        # K线：一切回测的底座
    ("index_ohlcv", "warn"),
    ("sw_index_valuation_daily", "warn"),
    ("market_thermometer_daily", "warn"),
    ("industry_pb_break_daily", "warn"),
    ("industry_prosperity_daily", "warn"),
]
for _t, _sev in _DAILY:
    _freshness(None, f"freshness_{_t}", _t, 4, _sev)

_freshness(None, "freshness_stock_valuation", "stock_valuation",
           9, "critical")               # 周频同步但关键
_freshness(None, "freshness_capital_event", "capital_event",
           9, "warn", col="announce_date")
_freshness(None, "freshness_macro_cn_bond", "macro_indicator",
           10, "warn", col="report_date")   # cn_bond_10y 日频但源偶缺
_freshness(None, "freshness_shareholder_count", "stock_shareholder_count",
           100, "info", col="report_date",
           note="报告期口径天然稀疏（季报披露节奏），仅确认写入侧在跑")


@register("structural_north_flow", "north_flow_daily", "info")
def _north_flow_structural(ctx):
    """北向 2026-08-18 起外部停发——口径注记，不告警不回补。"""
    d = _max_date(ctx, "north_flow_daily")
    return CheckResult(
        check_id="structural_north_flow", table="north_flow_daily",
        severity="info", status="ok",
        metric={"max_date": str(d)},
        message="结构性停发注记：外部源自 2026-08-18 起不再披露每日"
                "北向净买额，非 job 故障；upsert SQL bug 已修复，"
                "源恢复写入即自动续上。",
    )


@register("coverage_stock_valuation", "stock_valuation", "warn")
def _valuation_coverage(ctx):
    """近 5 日均行数 vs 90 日基线，骤降 >30% 告 warn。

    财报季 PE 断线是 index_pe 80% 披露门控的设计内行为（白名单注记）。
    """
    rows = ctx["query"](
        "SELECT MAX(trade_date)::date AS d FROM stock_valuation"
    )
    latest = rows[0]["d"] if rows else None
    if latest is None:
        return CheckResult(
            check_id="coverage_stock_valuation",
            table="stock_valuation", severity="warn", status="fail",
            message="stock_valuation 无数据",
        )
    cnt = ctx["query"](
        "SELECT COUNT(*) AS c FROM stock_valuation "
        f"WHERE trade_date > '{latest - dt.timedelta(days=6)}'"
    )[0]["c"]
    base = ctx["query"](
        "SELECT COUNT(*) AS c FROM stock_valuation "
        f"WHERE trade_date > '{latest - dt.timedelta(days=96)}' "
        f"AND trade_date <= '{latest - dt.timedelta(days=6)}'"
    )[0]["c"]
    recent_avg = cnt / 5 if latest else 0
    base_avg = base / 90 if base else 0
    drop = None
    if base_avg > 0:
        drop = round((1 - recent_avg / base_avg) * 100, 1)
    status = "warn" if (drop is not None and drop > 30) else "ok"
    return CheckResult(
        check_id="coverage_stock_valuation", table="stock_valuation",
        severity="warn", status=status,
        metric={"recent_daily_avg": round(recent_avg, 1),
                "baseline_daily_avg": round(base_avg, 1),
                "drop_pct": drop},
        message=(
            f"近5日均 {recent_avg:.0f} 行 vs 90日基线 {base_avg:.0f}"
            + (f"（降 {drop}%）" if drop is not None else "")
            + "；财报季 PE 单日断线属披露门控设计内行为"
        ),
    )


@register("zero_stock_ohlcv_change_pct", "stock_ohlcv", "warn")
def _change_pct_zero(ctx):
    """change_pct 近 10 日全零检测（历史事故的通用化）。"""
    rows = ctx["query"](
        "SELECT MAX(trade_date)::date AS d FROM stock_ohlcv"
    )
    latest = rows[0]["d"] if rows else None
    if latest is None:
        return CheckResult(
            check_id="zero_stock_ohlcv_change_pct", table="stock_ohlcv",
            severity="warn", status="fail", message="无数据",
        )
    stats = ctx["query"](
        "SELECT COUNT(*) AS total, "
        "COUNT(*) FILTER (WHERE change_pct = 0) AS zeros "
        "FROM stock_ohlcv "
        f"WHERE trade_date > '{latest - dt.timedelta(days=14)}'"
    )[0]
    total, zeros = stats["total"], stats["zeros"]
    zero_rate = round(zeros / total * 100, 1) if total else None
    status = "warn" if (zero_rate is not None and zero_rate > 90
                        and total > 1000) else "ok"
    return CheckResult(
        check_id="zero_stock_ohlcv_change_pct", table="stock_ohlcv",
        severity="warn", status=status,
        metric={"zero_rate": zero_rate, "sample": total},
        message=f"change_pct 零值率 {zero_rate}%（近10日）",
    )
