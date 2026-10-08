"""
DCF（现金流折现）估值 + 安全边际（纯函数）
=============================================
价值投资的绝对估值锚：基于自由现金流折现算「内在价值」，
与当前市值对比得出「安全边际」，回答"这公司值多少钱、现价贵不贵"。

两阶段模型：
  1. 显式预测期（projection_years 年）：每年 FCF 按增长率 g 复利
     FCF_i = latest_fcf × (1+g)^i
  2. 永续终值：TV = FCF_N × (1+terminal_growth) / (wacc - terminal_growth)
  内在价值 = Σ_{i=1..N} FCF_i/(1+wacc)^i + TV/(1+wacc)^N

假设由调用方提供（价值投资者应自行调参）：
  - latest_fcf: 基础自由现金流（最新 TTM，来自 stock_financial_detail.free_cash_flow）
  - growth_rate: 显式预测期年增长率（默认 8%，保守）
  - terminal_growth: 永续增长率（默认 3%，接近长期 GDP）
  - wacc: 加权平均资本成本/折现率（默认 9%）
  - projection_years: 显式预测年数（默认 10）

安全边际 = (内在价值 - 市值) / 市值
  > 0 表示低估（现价低于内在价值），越大越有吸引力。
"""
from __future__ import annotations

import datetime as dt
import random
from typing import Optional


def ttm_fcf(
    rows: list[tuple[dt.date, float]],
) -> Optional[tuple[float, dt.date, str]]:
    """把累计口径的现金流量表行差分成 TTM 自由现金流。

    A 股现金流量表是年初至今累计值（一季报 3 个月 / 中报 6 个月 /
    三季报 9 个月），直接拿最新一期当年度基数会把半年/季度值当
    全年用，内在价值随财报季时点系统性摆动 2~4 倍。这里还原成
    滚动 12 个月：
      最新期为年报（12-31）→ 直接用，本身就是完整 12 个月；
      否则 TTM = 上年年报 + 最新期累计 − 去年同期累计。
    差分缺行时退回最近一个年报（annual_fallback，宁可旧不可短），
    连年报都没有则 None。

    Args:
        rows: [(report_date, free_cash_flow), ...]，任意顺序。

    Returns:
        (ttm 值, 基准报告期, 方法)，
        方法 ∈ {ttm, annual, annual_fallback}；无可用数据返回 None。
    """
    if not rows:
        return None
    by_date = {
        d: v
        for d, v in sorted(rows, key=lambda r: r[0])
        if v is not None
    }
    if not by_date:
        return None
    latest_date = max(by_date)
    latest = by_date[latest_date]

    if latest_date.month == 12:
        return latest, latest_date, "annual"

    prev_annual = dt.date(latest_date.year - 1, 12, 31)
    same_period_prev = latest_date.replace(year=latest_date.year - 1)
    if prev_annual in by_date and same_period_prev in by_date:
        ttm = by_date[prev_annual] + latest - by_date[same_period_prev]
        return ttm, latest_date, "ttm"

    annuals = [d for d in by_date if d.month == 12]
    if annuals:
        d = max(annuals)
        return by_date[d], d, "annual_fallback"
    return None


def dcf_intrinsic_value(
    latest_fcf: float,
    growth_rate: float = 0.08,
    terminal_growth: float = 0.03,
    wacc: float = 0.09,
    projection_years: int = 10,
) -> Optional[float]:
    """
    两阶段 DCF 内在价值（总，与市值同口径）。

    latest_fcf<=0、wacc<=terminal_growth、projection_years<1 返回 None
    （无法计算或无意义）。
    """
    if latest_fcf is None or latest_fcf <= 0:
        return None
    if wacc <= terminal_growth:
        return None
    if projection_years < 1:
        return None

    pv = 0.0
    fcf = latest_fcf
    for i in range(1, projection_years + 1):
        fcf = fcf * (1 + growth_rate)
        pv += fcf / ((1 + wacc) ** i)

    # 永续终值（折现到第 N 年）
    terminal_fcf = fcf * (1 + terminal_growth)
    terminal_value = terminal_fcf / (wacc - terminal_growth)
    pv += terminal_value / ((1 + wacc) ** projection_years)

    return round(pv, 2)


def margin_of_safety(
    intrinsic_value: Optional[float],
    market_value: Optional[float],
) -> Optional[float]:
    """
    安全边际 = (内在价值 - 市值) / 市值。

    >0 低估（有吸引力），<0 高估。输入缺失或市值<=0 返回 None。
    """
    if (
        intrinsic_value is None
        or market_value is None
        or market_value <= 0
    ):
        return None
    return round(
        (intrinsic_value - market_value) / market_value, 4
    )


# 默认假设（供 API 层与文档参考）
def dcf_monte_carlo(
    latest_fcf: float,
    growth_mean: float = 0.08,
    growth_std: float = 0.03,
    wacc_mean: float = 0.09,
    wacc_std: float = 0.01,
    terminal_growth: float = 0.03,
    projection_years: int = 10,
    n_sim: int = 5000,
    seed: Optional[int] = 42,
) -> Optional[dict]:
    """
    蒙特卡洛 DCF：对增长率和折现率做正态分布采样，模拟 n_sim 次，
    返回内在价值分布统计（均值/标准差/分位数/直方图）。

    g ~ N(growth_mean, growth_std)
    WACC ~ N(wacc_mean, wacc_std)

    Returns:
        {mean, std, cv, p5, p25, p50, p75, p95, min, max,
         sample_size, histogram} 或 None。
    """
    if latest_fcf is None or latest_fcf <= 0:
        return None

    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(n_sim):
        g = rng.gauss(growth_mean, growth_std)
        wacc = rng.gauss(wacc_mean, wacc_std)
        if wacc <= terminal_growth:
            continue
        g = max(-0.10, min(0.30, g))
        v = dcf_intrinsic_value(
            latest_fcf, g, terminal_growth, wacc, projection_years
        )
        if v is not None and v > 0:
            values.append(v)

    if len(values) < 30:
        return None

    values.sort()
    n = len(values)

    def _pct(p: float) -> float:
        return values[int(p * (n - 1))]

    mean = sum(values) / n
    std = (sum((v - mean) ** 2 for v in values) / n) ** 0.5

    return {
        "mean": round(mean, 2),
        "std": round(std, 2),
        "cv": round(std / mean, 4) if mean > 0 else None,
        "p5": round(_pct(0.05), 2),
        "p25": round(_pct(0.25), 2),
        "p50": round(_pct(0.50), 2),
        "p75": round(_pct(0.75), 2),
        "p95": round(_pct(0.95), 2),
        "min": round(values[0], 2),
        "max": round(values[-1], 2),
        "sample_size": n,
        "histogram": _build_histogram(values, 20),
    }


def _build_histogram(
    values: list[float], bins: int
) -> list[dict]:
    """构建直方图（每个桶的区间 + 计数）。"""
    if not values or bins <= 0:
        return []
    vmin, vmax = values[0], values[-1]
    if vmax == vmin:
        return [{"bin_start": vmin, "bin_end": vmax, "count": len(values)}]
    width = (vmax - vmin) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - vmin) / width), bins - 1)
        counts[idx] += 1
    return [
        {
            "bin_start": round(vmin + i * width, 2),
            "bin_end": round(vmin + (i + 1) * width, 2),
            "count": counts[i],
        }
        for i in range(bins)
    ]


DEFAULT_GROWTH_RATE = 0.08
DEFAULT_TERMINAL_GROWTH = 0.03
DEFAULT_WACC = 0.09
DEFAULT_PROJECTION_YEARS = 10


def dcf_sensitivity_grid(
    latest_fcf: float,
    waccs: list,
    growths: list,
    growth_rate: float = 0.08,
    projection_years: int = 10,
) -> list:
    """WACC×永续增长敏感性网格（行=wacc 升序，列=g 升序）。

    单元格=内在值（总口径）；wacc<=g 的组合无意义 → None。
    """
    out = []
    for w in waccs:
        row = []
        for g in growths:
            try:
                row.append(dcf_intrinsic_value(
                    latest_fcf, growth_rate=growth_rate,
                    terminal_growth=g, wacc=w,
                    projection_years=projection_years,
                ))
            except Exception:
                row.append(None)
        out.append(row)
    return out


def compare_dcf_versions(then: dict, now: dict) -> dict:
    """同一组假设下"保存时 vs 现在"的估值对比（假设版本化）。

    then/now: dcf 输出快照（intrinsic_value/market_value/
    margin_of_safety/fcf_base/report_date）。

    解读：intrinsic_delta 反映基本面变化（判断驱动），
    market_delta 反映价格变化（情绪驱动）——
    intrinsic 不变而市值下跌 = 市场在送安全边际；
    intrinsic 下滑而市值坚挺 = 判断依据已变、原买入理由需重估。
    """
    def _pct(curr, base):
        if curr is None or base in (None, 0):
            return None
        return round((curr / base - 1.0) * 100, 2)

    iv_t = (then or {}).get("intrinsic_value")
    iv_n = (now or {}).get("intrinsic_value")
    mv_t = (then or {}).get("market_value")
    mv_n = (now or {}).get("market_value")
    fcf_t = (then or {}).get("fcf_base")
    fcf_n = (now or {}).get("fcf_base")
    intrinsic_delta_pct = _pct(iv_n, iv_t)
    market_delta_pct = _pct(mv_n, mv_t)
    fcf_delta_pct = _pct(fcf_n, fcf_t)

    driver = None
    if intrinsic_delta_pct is None or market_delta_pct is None:
        driver = "数据不足"
    elif abs(intrinsic_delta_pct) < 10 and abs(market_delta_pct) < 1:
        driver = "无变化：财报与价格都未更新"
    elif abs(intrinsic_delta_pct) < 10:
        # 内在价值基本没动（<10%），价格变动全是情绪
        driver = ("情绪驱动：市值下跌" if market_delta_pct < 0
                  else "情绪驱动：市值上涨")
    elif market_delta_pct < intrinsic_delta_pct - 10:
        driver = "跌出安全边际：基本面改善但价格更便宜"
    elif market_delta_pct > intrinsic_delta_pct + 10:
        driver = "透支：价格涨得比基本面快"
    else:
        driver = "同步：价格与基本面同向同幅"
    return {
        "then": {
            "intrinsic_value": iv_t, "market_value": mv_t,
            "margin_of_safety": (then or {}).get("margin_of_safety"),
            "fcf_base": fcf_t,
            "report_date": (then or {}).get("report_date"),
        },
        "now": {
            "intrinsic_value": iv_n, "market_value": mv_n,
            "margin_of_safety": (now or {}).get("margin_of_safety"),
            "fcf_base": fcf_n,
            "report_date": (now or {}).get("report_date"),
        },
        "intrinsic_delta_pct": intrinsic_delta_pct,
        "market_delta_pct": market_delta_pct,
        "fcf_delta_pct": fcf_delta_pct,
        "driver": driver,
        "note": "intrinsic_delta=基本面变化(判断驱动)；"
                "market_delta=价格变化(情绪驱动)。",
    }
