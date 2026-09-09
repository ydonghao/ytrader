"""滚动 Walk-Forward 寻优 + 过拟合检测。

核心思想：把历史切成滚动窗口，每个窗口在"训练段(IS)"做参数寻优，
把最优参数拿到"测试段(OOS)"验证。拼接所有 OOS 段得到 walk-forward 曲线，
用 IS vs OOS 的落差衡量过拟合。

复用 LongTermGridOptimizer（训练段寻优）+ PortfolioBacktester（OOS 回测）。
纯计算引擎，不依赖 infra/conf/api。
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from ...sync.sync_provider import OHLCVBar
from . import metrics as M
from .models import LongTermResult
from .optimizer import LongTermGridOptimizer
from .portfolio_backtester import PortfolioBacktester
from .strategies import build_strategy

log = logging.getLogger(__name__)

_EPS = 1e-9


# ── 数据切片工具 ────────────────────────────────────────────────────────────────


def _bar_day(b: OHLCVBar):
    """K 线交易日：trade_time 可能是 datetime 或 date（index_ohlcv 回传 date）。"""
    t = b.trade_time
    if hasattr(t, "date") and not isinstance(t, type(None)):
        try:
            return t.date()
        except AttributeError:
            return t
    return t


def common_dates(bars_by_symbol: dict[str, list[OHLCVBar]]) -> list:
    """各标的交易日的交集（排序）。用于窗口切分的公共时间轴。"""
    sets = []
    for sym, bars in bars_by_symbol.items():
        if not bars:
            continue
        sets.append({_bar_day(b) for b in bars})
    if not sets:
        return []
    common = set.intersection(*sets)
    return sorted(common)


def slice_by_dates(
    bars_by_symbol: dict[str, list[OHLCVBar]],
    start_date,
    end_date,
) -> dict[str, list[OHLCVBar]]:
    """按 [start_date, end_date]（含）切片各标的 bars。"""
    out: dict[str, list[OHLCVBar]] = {}
    for sym, bars in bars_by_symbol.items():
        out[sym] = [
            b for b in bars
            if start_date <= _bar_day(b) <= end_date
        ]
    return out


def slice_benchmark(bars: list[OHLCVBar], start_date, end_date) -> list[OHLCVBar]:
    """切片基准 bars。"""
    return [b for b in bars if start_date <= _bar_day(b) <= end_date]


# ── 数据模型 ────────────────────────────────────────────────────────────────────


@dataclass
class WalkForwardConfig:
    """Walk-forward 配置。"""
    train_days: int = 504        # 训练段交易日（≈2 年）
    test_days: int = 126         # 测试段交易日（≈0.5 年）
    step_days: int = 126         # 滑动步长（= test_days 即不重叠）
    metric: str = "sharpe_ratio"  # 训练段寻优指标
    param_grid: Optional[dict] = None  # None=自动从 ParamSpec 派生
    top_k: int = 5


@dataclass
class WindowResult:
    """单个 walk-forward 窗口的结果。"""
    index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    best_params: dict
    is_sharpe: float
    is_cagr: float
    oos_sharpe: float
    oos_cagr: float
    oos_max_drawdown: float
    oos_total_return_pct: float
    oos_equity: list = field(default_factory=list)  # [{date, equity}]

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "best_params": self.best_params,
            "is_sharpe": round(self.is_sharpe, 3),
            "is_cagr": round(self.is_cagr, 2),
            "oos_sharpe": round(self.oos_sharpe, 3),
            "oos_cagr": round(self.oos_cagr, 2),
            "oos_max_drawdown": round(self.oos_max_drawdown, 2),
            "oos_total_return_pct": round(self.oos_total_return_pct, 2),
        }


@dataclass
class WalkForwardResult:
    """Walk-forward 整体结果。"""
    strategy: str
    n_windows: int
    skipped: int
    windows: list[WindowResult]
    oos_equity_curve: list[dict]   # 拼接的 OOS 曲线 [{date, nav}]
    aggregated: dict               # OOS 聚合指标
    overfitting: dict              # 过拟合度量
    warning: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "n_windows": self.n_windows,
            "skipped": self.skipped,
            "windows": [w.to_dict() for w in self.windows],
            "oos_equity_curve": self.oos_equity_curve,
            "aggregated": self.aggregated,
            "overfitting": self.overfitting,
            "warning": self.warning,
        }


# ── 引擎 ────────────────────────────────────────────────────────────────────────


def _equity_list(result: LongTermResult) -> list[float]:
    """从 LongTermResult 提取权益数值序列。"""
    return [p.get("equity", 0) for p in result.equity_curve]


def _chain_oos_equity(windows: list[WindowResult]) -> list[dict]:
    """拼接各窗口 OOS 权益为连续 walk-forward 曲线（复利衔接）。"""
    curve: list[dict] = []
    running = 1.0  # 累计净值
    for w in windows:
        eq = w.oos_equity
        if not eq:
            continue
        base = eq[0].get("equity", 1.0) or 1.0
        for pt in eq:
            e = pt.get("equity", base)
            running_nav = running * (e / base) if base else running
            curve.append({"date": pt.get("date", ""), "nav": round(running_nav, 5)})
        # 段末净值作为下一段起点倍数
        last = eq[-1].get("equity", base)
        running = running * (last / base) if base else running
    return curve


def run_walk_forward(
    config: WalkForwardConfig,
    strategy_name: str,
    bars_by_symbol: dict[str, list[OHLCVBar]],
    benchmark_bars: Optional[list[OHLCVBar]] = None,
    backtester_kwargs: Optional[dict] = None,
) -> WalkForwardResult:
    """运行 walk-forward 滚动寻优。

    Returns:
        WalkForwardResult（含每窗口 IS/OOS + 拼接曲线 + 过拟合度量）。
    """
    backtester_kwargs = backtester_kwargs or {}
    dates = common_dates(bars_by_symbol)
    train, test, step = config.train_days, config.test_days, config.step_days

    if len(dates) < train + test:
        return WalkForwardResult(
            strategy=strategy_name, n_windows=0, skipped=0, windows=[],
            oos_equity_curve=[], aggregated={}, overfitting={},
            warning=(
                f"数据不足：公共交易日 {len(dates)} < 训练{train}+测试{test}，"
                "无法 walk-forward。请缩小窗口或扩大日期范围。"
            ),
        )

    windows: list[WindowResult] = []
    skipped = 0
    idx = 0
    for i in range(0, len(dates) - train - test + 1, max(step, 1)):
        train_dates = dates[i:i + train]
        test_dates = dates[i + train:i + train + test]
        tr_start, tr_end = train_dates[0], train_dates[-1]
        te_start, te_end = test_dates[0], test_dates[-1]

        # 训练段：网格寻优
        tr_bars = slice_by_dates(bars_by_symbol, tr_start, tr_end)
        tr_bench = (
            slice_benchmark(benchmark_bars, tr_start, tr_end)
            if benchmark_bars else None
        )
        try:
            opt = LongTermGridOptimizer(
                strategy_name=strategy_name,
                param_grid=config.param_grid,
                metric=config.metric,
                top_k=1,
                backtester_kwargs=backtester_kwargs,
            )
            opt_res = opt.optimize(
                bars_by_symbol=tr_bars, benchmark_bars=tr_bench,
            )
            if not opt_res.best:
                skipped += 1
                continue
            best_params = opt_res.best_params
            is_sharpe = opt_res.best.sharpe_ratio
            is_cagr = opt_res.best.cagr
        except Exception as e:  # noqa: BLE001
            log.warning("[walk-forward] 窗口 %d 训练失败: %s", idx, e)
            skipped += 1
            continue

        # 测试段：用 best_params 跑回测
        te_bars = slice_by_dates(bars_by_symbol, te_start, te_end)
        te_bench = (
            slice_benchmark(benchmark_bars, te_start, te_end)
            if benchmark_bars else None
        )
        try:
            strategy = build_strategy(strategy_name, best_params)
            bt = PortfolioBacktester(**backtester_kwargs)
            oos = bt.run(
                strategy=strategy, bars_by_symbol=te_bars,
                benchmark_bars=te_bench or None,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("[walk-forward] 窗口 %d OOS 失败: %s", idx, e)
            skipped += 1
            continue

        windows.append(WindowResult(
            index=idx,
            train_start=str(tr_start), train_end=str(tr_end),
            test_start=str(te_start), test_end=str(te_end),
            best_params=best_params,
            is_sharpe=is_sharpe, is_cagr=is_cagr,
            oos_sharpe=oos.sharpe_ratio,
            oos_cagr=oos.cagr,
            oos_max_drawdown=oos.max_drawdown,
            oos_total_return_pct=oos.total_return_pct,
            oos_equity=oos.equity_curve,
        ))
        idx += 1

    if not windows:
        return WalkForwardResult(
            strategy=strategy_name, n_windows=0, skipped=skipped,
            windows=[], oos_equity_curve=[], aggregated={},
            overfitting={},
            warning="所有窗口均失败，无法生成 walk-forward 结果。",
        )

    oos_curve = _chain_oos_equity(windows)
    aggregated = _aggregate_oos(oos_curve, windows)
    overfitting = _overfitting_metrics(windows)

    return WalkForwardResult(
        strategy=strategy_name,
        n_windows=len(windows),
        skipped=skipped,
        windows=windows,
        oos_equity_curve=oos_curve,
        aggregated=aggregated,
        overfitting=overfitting,
    )


def _aggregate_oos(curve: list[dict], windows: list[WindowResult]) -> dict:
    """对拼接 OOS 曲线算聚合指标。"""
    navs = [p["nav"] for p in curve if "nav" in p]
    if len(navs) < 2:
        return {
            "total_return_pct": round(
                sum(w.oos_total_return_pct for w in windows)
                / max(len(windows), 1), 2
            ),
            "cagr": round(
                statistics.mean([w.oos_cagr for w in windows]), 2
            ),
            "sharpe_ratio": round(
                statistics.mean([w.oos_sharpe for w in windows]), 3
            ),
            "max_drawdown": round(
                max((w.oos_max_drawdown for w in windows), default=0.0), 2
            ),
            "method": "per-window average (curve too short)",
        }
    dd, _ = M.max_drawdown(navs)
    sharpe = M.sharpe_ratio(navs, risk_free_rate=0.0)
    total_ret = (navs[-1] / navs[0] - 1.0) * 100.0 if navs[0] else 0.0
    days = len(navs)
    cagr = M.cagr(navs[0] or 1.0, navs[-1], days)
    return {
        "total_return_pct": round(total_ret, 2),
        "cagr": round(cagr, 2),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown": round(dd, 2),
        "method": "chained OOS curve",
    }


def _overfitting_metrics(windows: list[WindowResult]) -> dict:
    """过拟合度量。"""
    is_sharpes = [w.is_sharpe for w in windows]
    oos_sharpes = [w.oos_sharpe for w in windows]
    med_is = statistics.median(is_sharpes) if is_sharpes else 0.0
    med_oos = statistics.median(oos_sharpes) if oos_sharpes else 0.0
    wfe = med_oos / med_is if abs(med_is) > _EPS else 0.0

    # 参数稳定性：不同最优参数集数 / 窗口数
    distinct = len({tuple(sorted(w.best_params.items())) for w in windows})
    stability = distinct / max(len(windows), 1)

    pos = sum(1 for s in oos_sharpes if s > 0)
    return {
        "walk_forward_efficiency": round(wfe, 3),
        "param_stability": round(stability, 3),
        "oos_positive_ratio": round(pos / max(len(windows), 1), 3),
        "median_is_sharpe": round(med_is, 3),
        "median_oos_sharpe": round(med_oos, 3),
        "distinct_param_sets": distinct,
    }
