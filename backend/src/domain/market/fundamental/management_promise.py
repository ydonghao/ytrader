"""管理层言行追踪——承诺兑现评估 + 信用档案纯函数（2026-10 V1）。

V1 的"承诺"首选公司自己发布的**业绩预告**（预告数值 = 管理层对股东的
量化承诺），与财报实际值对比判兑现；手动录入的指引/资本开支/分红等
承诺经人工验证后进入同一信用档案。年报 MD&A 的 LLM 抽取留作 V2。

全部纯函数，无 DB/IO。
"""
from __future__ import annotations

from typing import Optional

# 预告指标名 → stock_financial_detail 固定列（import 时映射）
FORECAST_METRIC_COLUMNS = {
    "净利润": "net_profit",
    "归属于上市公司股东的净利润": "net_profit_parent",
    "扣除非经常性损益后的净利润": "net_profit_deduct",
    "营业收入": "revenue",
    "营业总收入": "revenue",
}

_TOLERANCE = 0.10   # ±10% 内视为兑现（预告本身是区间估算）


def assess_forecast_promise(
    forecast_value: Optional[float],
    actual_value: Optional[float],
    *,
    label: Optional[str] = None,
    tolerance: float = _TOLERANCE,
) -> dict:
    """预告承诺 vs 实际值 → {status, deviation_pct, detail}。

    status: pending（实际值未出）/ fulfilled（|偏差|<=tolerance）/
    beat（实际超预告 >tolerance）/ broken（低于预告 >tolerance）。
    方向性修正：预告类型为预增/扭亏而实际同比转降时，无论数值偏差
    一律 broken——方向都错了谈不上兑现。
    """
    if forecast_value is None:
        return {"status": "pending", "deviation_pct": None,
                "detail": "缺预告数值"}
    if actual_value is None:
        return {"status": "pending", "deviation_pct": None,
                "detail": "实际值未披露"}

    base = abs(forecast_value)
    if base == 0:
        return {"status": "pending", "deviation_pct": None,
                "detail": "预告数值为零，无法评估"}
    dev = (actual_value - forecast_value) / base

    if dev < -tolerance:
        status = "broken"
    elif dev > tolerance:
        status = "beat"
    else:
        status = "fulfilled"
    detail = (f"预告 {forecast_value / 1e8:.2f} 亿 vs 实际 "
              f"{actual_value / 1e8:.2f} 亿，偏差 {dev * 100:+.1f}%")
    return {"status": status,
            "deviation_pct": round(dev * 100, 2),
            "detail": detail, "label": label}


def direction_broken(forecast_value: Optional[float],
                     prev_value: Optional[float],
                     actual_value: Optional[float],
                     label: Optional[str]) -> bool:
    """方向性失约：预告"向好"（预增/扭亏/续盈/略增）但实际同比转降。

    prev_value 为上年同期：预告给的对比基准。预告值>同期 而实际<同期
    → 连方向都错了。
    """
    if not label or None in (forecast_value, prev_value, actual_value):
        return False
    if label not in ("预增", "扭亏", "续盈", "略增"):
        return False
    return forecast_value > prev_value and actual_value < prev_value


def promise_credit_summary(rows: list) -> dict:
    """信用档案：已验证承诺的兑现率（beat 计入兑现）。

    rows: management_promise 行 dict（status 字段）。
    credit_pct = (fulfilled + beat) / 已验证数；长期低于同行 =
    管理层指引不可信，估值应打折。
    """
    closed = [r for r in rows if r.get("status") in
              ("fulfilled", "beat", "broken")]
    n_fulfilled = sum(1 for r in closed if r["status"] == "fulfilled")
    n_beat = sum(1 for r in closed if r["status"] == "beat")
    n_broken = sum(1 for r in closed if r["status"] == "broken")
    return {
        "total": len(rows),
        "pending": sum(1 for r in rows
                       if r.get("status") == "pending"),
        "verified": len(closed),
        "fulfilled": n_fulfilled,
        "beat": n_beat,
        "broken": n_broken,
        "credit_pct": (round((n_fulfilled + n_beat) / len(closed) * 100, 1)
                       if closed else None),
        "note": "信用=（兑现+超预告）/已验证；beat 计入兑现。"
                "业绩预告是公司自己的量化承诺。",
    }
