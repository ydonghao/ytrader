"""批量个股估值历史分位服务（选股器专用）。

与单股分位(percentile.py)的区别：一次 SQL 拉全市场月降采样历史，
在 Python 层按 symbol 分组算分位，避免 5000 次单查。

支持：
  - metric: "pb" | "pe_ttm" | "pb_pe"(双分位等权平均)
  - window: "10y" | "20y"(以及 percentile.py 的 _VALPCT_WINDOW_YEARS 子集)
  - exclude_ranges: 剔除区间列表(全局炒作区间下推)
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from src.domain.market.fundamental.percentile import calc_percentile, SAMPLE_MIN
from src.infra.database.market.valuation import create_stock_valuation_repository

_WINDOW_YEARS = {"3y": 3, "5y": 5, "10y": 10, "15y": 15, "20y": 20}

# metric → StockValuation 字段名
_METRIC_ATTR = {
    "pb": "pb",
    "pe_ttm": "pe_ttm",
}


def stock_percentile_batch(
    symbols: list[str],
    metric: str,            # "pb" | "pe_ttm" | "pb_pe"
    window: str,            # "10y" | "20y" | ...
    as_of: dt.date,
    exclude_ranges: Optional[list[tuple[dt.date, dt.date]]] = None,
) -> dict[str, dict]:
    """
    批量算多只股票当前估值在历史中的分位。

    Returns:
        {symbol: {percentile, sample_size, current, pb_percentile?, pe_percentile?}}
        样本不足(<30)/负值/无数据的股票不出现。
        metric="pb_pe" 时额外返回 pb_percentile / pe_percentile 子项。
    """
    if not symbols:
        return {}
    years = _WINDOW_YEARS.get(window, 10)
    range_start = dt.date(as_of.year - years, as_of.month, as_of.day)

    repo = create_stock_valuation_repository()
    rows_map = repo.get_range_batch(
        symbols, range_start, as_of,
        exclude_ranges=exclude_ranges, monthly=True,
    )

    out: dict[str, dict] = {}
    for sym, rows in rows_map.items():
        # 取该 symbol 在 as_of 当天(或之前最近)的值作为 current
        current_row = None
        for r in reversed(rows):
            if r.trade_date <= as_of:
                current_row = r
                break
        if current_row is None:
            continue

        result: dict = {"sample_size": 0, "current": None}

        if metric == "pb_pe":
            pb_pct = _calc_one(rows, "pb", current_row.pb)
            pe_pct = _calc_one(rows, "pe_ttm", current_row.pe_ttm)
            # 复合：两边都有才算，否则降级(只用有的那个)
            if pb_pct is not None and pe_pct is not None:
                result["percentile"] = (pb_pct["percentile"] + pe_pct["percentile"]) / 2
                result["pb_percentile"] = pb_pct["percentile"]
                result["pe_percentile"] = pe_pct["percentile"]
                result["sample_size"] = min(pb_pct["sample_size"], pe_pct["sample_size"])
                result["current"] = current_row.pb  # 复合模式 current 取 PB 做代表
            elif pb_pct is not None:
                # PE 样本不足，降级为纯 PB
                result["percentile"] = pb_pct["percentile"]
                result["pb_percentile"] = pb_pct["percentile"]
                result["pe_percentile"] = None
                result["sample_size"] = pb_pct["sample_size"]
                result["current"] = current_row.pb
            else:
                continue
        else:
            attr = _METRIC_ATTR.get(metric)
            if attr is None:
                continue
            one = _calc_one(rows, attr, getattr(current_row, attr))
            if one is None:
                continue
            result["percentile"] = one["percentile"]
            result["sample_size"] = one["sample_size"]
            result["current"] = one["current"]

        out[sym] = result
    return out


def _calc_one(
    rows: list,
    attr: str,
    current_val: Optional[float],
) -> Optional[dict]:
    """算单个指标的分位。返回 {percentile, sample_size, current} 或 None。"""
    if current_val is None or current_val <= 0:
        return None
    samples = [
        getattr(r, attr) for r in rows
        if getattr(r, attr) is not None and getattr(r, attr) > 0
    ]
    if len(samples) < SAMPLE_MIN:
        return None
    pct = calc_percentile(samples, current_val)
    if pct is None:
        return None
    return {"percentile": pct, "sample_size": len(samples), "current": current_val}


def _get_global_exclude_ranges() -> list[tuple[dt.date, dt.date]]:
    """从 sidecar JSON 读全局剔除区间（UI 编辑写入），回退到 config.yaml。"""
    import json
    import os
    from conf.settings import _DEFAULT_CONFIG_PATH

    # 1. 先读 sidecar（UI PUT 写入的最新值）
    sidecar_path = os.path.join(os.path.dirname(_DEFAULT_CONFIG_PATH), ".screener_exclude_ranges.json")
    raw: list = []
    try:
        if os.path.exists(sidecar_path):
            with open(sidecar_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("exclude_ranges", [])
        else:
            # 2. 回退到 config.yaml
            from conf import app_config
            raw = app_config.screener.dividend_value.exclude_ranges
    except Exception:
        try:
            from conf import app_config
            raw = app_config.screener.dividend_value.exclude_ranges
        except Exception:
            raw = []

    out: list[tuple[dt.date, dt.date]] = []
    for pair in raw:
        try:
            if len(pair) != 2:
                continue
            out.append((dt.date.fromisoformat(pair[0]), dt.date.fromisoformat(pair[1])))
        except (ValueError, TypeError):
            continue
    return out
