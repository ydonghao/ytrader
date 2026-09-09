"""
纯选股器（Screener）
====================
输出"今天的标的清单"，不回测。与回测策略用同一套筛选规则（一致性），
但只算一次快照，不迭代调仓。

4 种模式：
  - magic_formula: 低 PE + 高 ROE 双排名（与 MagicFormulaStrategy 同逻辑）
  - dividend:      低 PB（高股息近似）+ 质量过滤（与 DividendStrategy 同逻辑）
  - fscore:        F-Score 质量打分 + 低 PB（与 FScoreValueStrategy 同逻辑）
  - custom:        用户自定义多因子门槛（pe_max/pb_max/roe_min/dy_min/debt_max）

复用 value_utils 的 rank_cross_section / top_n_by_score。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .data_loader import (
    FINANCIAL_LAG_DAYS,
    fetch_financial_history,
    fetch_financial_snapshot,
    fetch_latest_financial_detail,
    fetch_latest_financials,
    fetch_latest_valuations,
)
from .strategies.value_utils import (
    rank_cross_section,
    top_n_by_score,
)
from src.domain.market.fundamental.derived_metrics import (
    compute_value_metrics,
)
from src.domain.market.fundamental.quality import (
    compute_quality_report,
)
from src.domain.market.fundamental.percentile_batch import (
    stock_percentile_batch,
    _get_global_exclude_ranges,
)

log = logging.getLogger(__name__)

SCREENER_MODES = ("magic_formula", "dividend", "fscore", "custom", "dividend_value", "quality")


@dataclass
class ScreenItem:
    """单只入选标的的快照。"""
    symbol: str
    rank: int                       # 排名（1 = 最优）
    score: float                    # 综合得分（0~2，越高越好）
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    dv_ttm: Optional[float] = None  # 股息率（%）
    roe: Optional[float] = None     # ROE（%）
    roic: Optional[float] = None    # ROIC（%，magic_formula）
    ebit_yield: Optional[float] = None  # EBIT/EV 收益率（%）
    debt_ratio: Optional[float] = None
    fscore: Optional[int] = None    # F-Score（仅 fscore 模式）
    reason: str = ""                # 入选原因
    factor_breakdown: Optional[dict] = None  # dividend_value 模式的因子拆解

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "symbol": self.symbol,
            "score": round(self.score, 4),
            "pe_ttm": round(self.pe_ttm, 2) if self.pe_ttm else None,
            "pb": round(self.pb, 3) if self.pb else None,
            "dv_ttm": round(self.dv_ttm, 2) if self.dv_ttm else None,
            "roe": round(self.roe, 2) if self.roe else None,
            "roic": round(self.roic, 2) if self.roic else None,
            "ebit_yield": round(self.ebit_yield, 2) if self.ebit_yield else None,
            "debt_ratio": round(self.debt_ratio, 2) if self.debt_ratio else None,
            "fscore": self.fscore,
            "reason": self.reason,
            "factor_breakdown": self.factor_breakdown,
        }


@dataclass
class ScreenResult:
    """选股结果。"""
    mode: str
    as_of: str
    universe_size: int               # 参与筛选的总标的数
    filters: dict                    # 实际使用的筛选条件
    ranked_list: list[ScreenItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "as_of": self.as_of,
            "universe_size": self.universe_size,
            "filters": self.filters,
            "count": len(self.ranked_list),
            "ranked_list": [item.to_dict() for item in self.ranked_list],
        }


def screen(
    mode: str,
    symbols: Optional[list[str]] = None,
    as_of: Optional[date] = None,
    top_n: int = 20,
    filters: Optional[dict] = None,
) -> ScreenResult:
    """
    运行选股。

    Args:
        mode:    magic_formula / dividend / fscore / custom
        symbols: 标的池（空 = 全沪深A股剔ST）
        as_of:   截止日（空 = 今天）
        top_n:   返回前 N 只
        filters: custom 模式的门槛（pe_max/pb_max/roe_min/dy_min/debt_max）

    Returns:
        ScreenResult
    """
    from .data_loader import fetch_universe_symbols

    mode = mode.lower()
    if mode not in SCREENER_MODES:
        raise ValueError(f"未知选股模式 '{mode}'，可用: {SCREENER_MODES}")

    as_of = as_of or date.today()

    # 标的池
    if not symbols:
        symbols = fetch_universe_symbols(exclude_st=True)
    if not symbols:
        return ScreenResult(mode=mode, as_of=as_of.isoformat(),
                            universe_size=0, filters=filters or {})

    # 批量拉快照
    val_map = fetch_latest_valuations(symbols, as_of)
    fin_map = fetch_latest_financials(symbols, as_of)

    dispatch = {
        "magic_formula": _screen_magic_formula,
        "dividend": _screen_dividend,
        "fscore": _screen_fscore,
        "custom": _screen_custom,
        "dividend_value": _screen_dividend_value,
        "quality": _screen_quality,
    }
    items = dispatch[mode](
        symbols=symbols, val_map=val_map, fin_map=fin_map,
        as_of=as_of, top_n=top_n, filters=filters or {},
    )

    result = ScreenResult(
        mode=mode,
        as_of=as_of.isoformat(),
        universe_size=len(symbols),
        filters=filters or {},
    )
    result.ranked_list = items
    return result


# ── 模式1：神奇公式选股（低 PE + 高 ROE 双排名）─────────────────────────────

def _screen_magic_formula(
    symbols, val_map, fin_map, as_of, top_n, filters,
) -> list[ScreenItem]:
    min_roe = filters.get("roe_min", 2.0)
    max_pe = filters.get("pe_max", 50.0)
    min_pe = filters.get("pe_min", 3.0)

    # 取最新三大报表，算真实 ROIC / EBIT 收益率（EV-based）
    detail_map = fetch_latest_financial_detail(symbols, as_of)

    quality_map: dict[str, float] = {}   # ROIC（缺明细降级 ROE）
    value_map: dict[str, float] = {}     # EBIT/EV（缺明细降级 1/PE）
    snap: dict[str, dict] = {}
    used_real = 0

    for sym in symbols:
        val = val_map.get(sym)
        fin = fin_map.get(sym)
        if not val or not fin:
            continue
        pe = val.get("pe_ttm") or val.get("pe")
        roe = fin.get("roe_weighted") or fin.get("roe_diluted")
        if pe is None or roe is None:
            continue
        if pe <= min_pe or pe > max_pe:
            continue
        if roe < min_roe:
            continue

        detail = detail_map.get(sym)
        if detail:
            m = compute_value_metrics(detail, val)
            roic = m.get("roic")
            ey = m.get("earnings_yield")
            if roic is not None and ey is not None:
                quality_map[sym] = roic
                value_map[sym] = ey
                snap[sym] = {
                    "pe_ttm": pe, "pb": val.get("pb"),
                    "roic": roic, "ebit_yield": ey, "ev": m.get("ev"),
                    "roe": roe, "debt_ratio": fin.get("debt_ratio"),
                }
                used_real += 1
                continue
        # 降级：ROE + 1/PE
        quality_map[sym] = roe
        value_map[sym] = 1.0 / pe
        snap[sym] = {"pe_ttm": pe, "pb": val.get("pb"),
                     "roe": roe, "debt_ratio": fin.get("debt_ratio")}

    reason = (
        "双排名(ROIC+EBIT/EV)" if used_real
        else "双排名(ROE+1/PE,缺明细降级)"
    )
    return _finalize(snap, quality_map, value_map, top_n,
                     roe_rank_desc=True, ey_rank_desc=True,
                     reason=reason)


# ── 模式2：红利选股（低 PB + 质量过滤）──────────────────────────────────────

def _screen_dividend(
    symbols, val_map, fin_map, as_of, top_n, filters,
) -> list[ScreenItem]:
    min_dy = filters.get("dy_min", 3.0)
    min_roe = filters.get("roe_min", 2.0)
    max_debt = filters.get("debt_max", 95.0)
    max_pb = filters.get("pb_max", 3.0)

    dy_map: dict[str, float] = {}
    snap: dict[str, dict] = {}
    use_pb_proxy = True

    for sym in symbols:
        val = val_map.get(sym)
        if not val:
            continue
        dy = val.get("dv_ttm") or val.get("dv_ratio")
        pb = val.get("pb")
        # 质量过滤
        fin = fin_map.get(sym)
        roe = fin.get("roe_weighted") if fin else None
        debt = fin.get("debt_ratio") if fin else None
        if roe is not None and roe < min_roe:
            continue
        if debt is not None and debt > max_debt:
            continue
        # 股息率优先，无则用 PB 倒数
        if dy is not None and dy >= min_dy:
            dy_map[sym] = dy
        elif use_pb_proxy and dy is None and pb and 0 < pb < max_pb:
            dy_map[sym] = 1.0 / pb
        else:
            continue
        snap[sym] = {"pe_ttm": val.get("pe_ttm"), "pb": pb, "dv_ttm": dy,
                     "roe": roe, "debt_ratio": debt}

    return _finalize(snap, dy_map, None, top_n,
                     roe_rank_desc=True, ey_rank_desc=None,
                     reason="高股息率(或低PB)")


# ── 模式3：F-Score 选股（质量打分 + 低 PB）───────────────────────────────────

def _screen_fscore(
    symbols, val_map, fin_map, as_of, top_n, filters,
) -> list[ScreenItem]:
    max_pb = filters.get("pb_max", 3.0)
    min_fscore = filters.get("min_fscore", 3)

    # F-Score 需要两期财报对比
    fin_hist = fetch_financial_history(symbols, as_of, lookback_reports=4)

    score_map: dict[str, float] = {}
    pb_map: dict[str, float] = {}
    snap: dict[str, dict] = {}

    for sym in symbols:
        val = val_map.get(sym)
        if not val:
            continue
        pb = val.get("pb")
        if pb is None or pb <= 0 or pb > max_pb:
            continue
        rows = fin_hist.get(sym, [])
        fscore = _fscore(rows)
        if fscore is None or fscore < min_fscore:
            continue
        score_map[sym] = float(fscore)
        pb_map[sym] = pb
        cur_fin = rows[-1] if rows else {}
        snap[sym] = {"pe_ttm": val.get("pe_ttm"), "pb": pb,
                     "roe": cur_fin.get("roe_weighted"),
                     "debt_ratio": cur_fin.get("debt_ratio"),
                     "fscore": fscore}

    return _finalize(snap, score_map, pb_map, top_n,
                     roe_rank_desc=True, ey_rank_desc=False,  # pb 低更好
                     reason=f"F-Score≥{min_fscore}+低PB")


def _fscore(rows: list[dict]) -> Optional[int]:
    """
    简化 F-Score（0~5），需最近两期。
    与 FScoreValueStrategy._fscore 同逻辑（一致性）。
    """
    if len(rows) < 2:
        return None
    cur, prev = rows[-1], rows[-2]
    score = 0
    roe_cur = cur.get("roe_weighted") or cur.get("roe_diluted")
    roe_prev = prev.get("roe_weighted") or prev.get("roe_diluted")
    nm_cur = cur.get("net_margin")
    nm_prev = prev.get("net_margin")
    dr_cur = cur.get("debt_ratio")
    dr_prev = prev.get("debt_ratio")

    if roe_cur is not None and roe_cur > 0:
        score += 1
    if roe_cur is not None and roe_prev is not None and roe_cur > roe_prev:
        score += 1
    if nm_cur is not None and nm_cur > 0:
        score += 1
    if nm_cur is not None and nm_prev is not None and nm_cur > nm_prev:
        score += 1
    if dr_cur is not None and dr_prev is not None and dr_cur < dr_prev:
        score += 1
    return score


# ── 模式4：自定义多因子筛选 ────────────────────────────────────────────────

def _screen_custom(
    symbols, val_map, fin_map, as_of, top_n, filters,
) -> list[ScreenItem]:
    pe_max = filters.get("pe_max", 999)
    pb_max = filters.get("pb_max", 999)
    roe_min = filters.get("roe_min", -999)
    dy_min = filters.get("dy_min", -999)
    debt_max = filters.get("debt_max", 999)

    roe_map: dict[str, float] = {}
    snap: dict[str, dict] = {}

    for sym in symbols:
        val = val_map.get(sym)
        if not val:
            continue
        pe = val.get("pe_ttm") or val.get("pe")
        pb = val.get("pb")
        dy = val.get("dv_ttm") or val.get("dv_ratio")
        if pe is not None and pe > pe_max:
            continue
        if pb is not None and pb > pb_max:
            continue
        if dy is not None and dy < dy_min:
            continue
        fin = fin_map.get(sym)
        roe = fin.get("roe_weighted") if fin else None
        debt = fin.get("debt_ratio") if fin else None
        if roe is not None and roe < roe_min:
            continue
        if debt is not None and debt > debt_max:
            continue
        # 综合得分：用 ROE 排序（也可加权）
        roe_map[sym] = roe if roe is not None else 0
        snap[sym] = {"pe_ttm": pe, "pb": pb, "dv_ttm": dy,
                     "roe": roe, "debt_ratio": debt}

    return _finalize(snap, roe_map, None, top_n,
                     roe_rank_desc=True, ey_rank_desc=None,
                     reason="自定义多因子门槛")


# ── 模式5：红利低估值选股（高股息 + 低估分位 双因子）─────────────────────────

def _screen_dividend_value(
    symbols, val_map, fin_map, as_of, top_n, filters,
) -> list[ScreenItem]:
    """
    红利低估值双因子选股。

    红利因子 = 股息率 dv_ttm（必须有真实值，不兜底）
    低估因子 = 当前估值在历史中的分位（0~1，越低越便宜）
      - metric: pb / pe_ttm / pb_pe（双分位等权平均）
      - window: 10y / 20y
    排名 = 股息率排名(降序) + 低估分位排名(升序)
    """
    # 读配置
    from conf import app_config
    dv_cfg = app_config.screener.dividend_value
    fd = dv_cfg.filters_default

    metric = filters.get("value_metric", fd.value_metric)
    window = filters.get("value_window", fd.value_window)
    min_dy = filters.get("dy_min", fd.dy_min)
    min_roe = filters.get("roe_min", fd.roe_min)
    max_debt = filters.get("debt_max", fd.debt_max)
    max_pb = filters.get("pb_max", fd.pb_max)
    pe_min = filters.get("pe_min", fd.pe_min)
    pe_max = filters.get("pe_max", fd.pe_max)

    exclude_ranges = _get_global_exclude_ranges()

    # 第一遍：硬门槛
    candidates: list[str] = []
    snap: dict[str, dict] = {}
    dy_map_raw: dict[str, float] = {}
    for sym in symbols:
        val = val_map.get(sym)
        if not val:
            continue
        dy = val.get("dv_ttm")
        pb = val.get("pb")
        pe = val.get("pe_ttm") or val.get("pe")
        # 红利门槛：必须有真实股息率
        if dy is None or dy < min_dy:
            continue
        # 估值安全阀
        if pb is not None and pb > max_pb:
            continue
        if pe is not None and (pe <= pe_min or pe > pe_max):
            continue
        # 质量门槛
        fin = fin_map.get(sym)
        roe = fin.get("roe_weighted") if fin else None
        debt = fin.get("debt_ratio") if fin else None
        if roe is not None and roe < min_roe:
            continue
        if debt is not None and debt > max_debt:
            continue
        candidates.append(sym)
        dy_map_raw[sym] = dy
        snap[sym] = {"pe_ttm": pe, "pb": pb, "dv_ttm": dy,
                     "roe": roe, "debt_ratio": debt}

    if not candidates:
        return []

    # 第二遍：批量算分位（只对候选池）
    try:
        pct_map = stock_percentile_batch(
            candidates, metric, window, as_of, exclude_ranges,
        )
        batch_failed = False
    except Exception as e:
        log.warning("[screener] dividend_value 批量分位失败,降级为仅股息率: %s", e)
        pct_map = {}
        batch_failed = True

    # 低估分位 map（越低越好）；剔除 None
    value_map: dict[str, float] = {}
    pct_detail: dict[str, dict] = {}
    for sym, info in pct_map.items():
        pct = info.get("percentile")
        if pct is None:
            continue
        value_map[sym] = pct
        pct_detail[sym] = info

    # 股息率 map（只保留有分位的）
    dy_map = {sym: dy_map_raw[sym] for sym in value_map if sym in dy_map_raw}

    # 降级：分位计算失败 → 仅按股息率排名
    if batch_failed or not value_map:
        if not dy_map_raw:
            return []
        dy_rank_only = rank_cross_section(dy_map_raw, descending=True)
        selected = top_n_by_score(dy_rank_only, top_n)
        metric_label = {"pb": "PB", "pe_ttm": "PE", "pb_pe": "PB+PE"}.get(metric, metric)
        reason = f"高股息(分位计算失败,仅按股息率)" if batch_failed else f"高股息(无有效{metric_label}分位样本)"
        items: list[ScreenItem] = []
        for rank, sym in enumerate(selected, 1):
            s = snap.get(sym, {})
            items.append(ScreenItem(
                symbol=sym, rank=rank, score=dy_rank_only.get(sym, 0),
                pe_ttm=s.get("pe_ttm"), pb=s.get("pb"), dv_ttm=s.get("dv_ttm"),
                roe=s.get("roe"), debt_ratio=s.get("debt_ratio"),
                reason=reason,
                factor_breakdown={
                    "dy_value": dy_map_raw.get(sym),
                    "dy_rank": _rank_of(sym, dy_rank_only),
                    "value_metric": metric, "value_window": window,
                    "value_percentile": None, "value_percentile_pe": None,
                    "value_rank": None,
                    "exclude_applied": [[r[0].isoformat(), r[1].isoformat()] for r in exclude_ranges],
                },
            ))
        return items

    # 双排名：股息率降序 + 分位升序，相加取 top_n
    dy_rank = rank_cross_section(dy_map, descending=True)       # 高股息 → 高分位
    val_rank = rank_cross_section(value_map, descending=False)  # 低分位 → 高分位
    combined = {sym: dy_rank.get(sym, 0) + val_rank.get(sym, 0) for sym in value_map}
    # 同分时优先选低估分位更低的（更便宜）标的
    selected = _top_n_with_value_tiebreak(combined, value_map, top_n)

    metric_label = {"pb": "PB", "pe_ttm": "PE", "pb_pe": "PB+PE"}.get(metric, metric)
    items: list[ScreenItem] = []
    for rank, sym in enumerate(selected, 1):
        s = snap.get(sym, {})
        items.append(ScreenItem(
            symbol=sym,
            rank=rank,
            score=combined[sym],
            pe_ttm=s.get("pe_ttm"),
            pb=s.get("pb"),
            dv_ttm=s.get("dv_ttm"),
            roe=s.get("roe"),
            debt_ratio=s.get("debt_ratio"),
            reason=f"高股息+低{metric_label}分位({window})",
            factor_breakdown={
                "dy_value": dy_map.get(sym),
                "dy_rank": _rank_of(sym, dy_rank),
                "value_metric": metric,
                "value_window": window,
                "value_percentile": value_map.get(sym),
                "value_percentile_pe": pct_detail.get(sym, {}).get("pe_percentile"),
                "value_rank": _rank_of(sym, val_rank),
                "exclude_applied": [[r[0].isoformat(), r[1].isoformat()] for r in exclude_ranges],
            },
        ))
    return items


def _rank_of(sym: str, rank_map: dict[str, float]) -> Optional[int]:
    """从 rank_cross_section 的分位结果反取名次（1=最优）。
    rank_map 值是 0~1 分位，名次 = 按分位降序的位置。"""
    if sym not in rank_map:
        return None
    ordered = sorted(rank_map.items(), key=lambda x: -x[1])
    for i, (s, _) in enumerate(ordered, 1):
        if s == sym:
            return i
    return None


def _top_n_with_value_tiebreak(
    combined: dict[str, float],
    value_map: dict[str, float],
    n: int,
) -> list[str]:
    """取 top_n：综合分降序，同分时优先选低估分位更低（更便宜）的标的。"""
    ranked = sorted(
        combined.items(),
        key=lambda x: (-x[1], value_map.get(x[0], 1.0)),
    )
    return [s for s, _ in ranked[:n]]


# ── 公共：排名 + 取 top_n + 组装 ScreenItem ──────────────────────────────────

def _finalize(
    snap: dict[str, dict],
    primary_map: dict[str, float],
    secondary_map: Optional[dict[str, float]],
    top_n: int,
    roe_rank_desc: bool,
    ey_rank_desc: Optional[bool],
    reason: str,
) -> list[ScreenItem]:
    """双排名相加 → 取 top_n → 组装 ScreenItem。"""
    if not primary_map:
        return []

    primary_rank = rank_cross_section(primary_map, descending=roe_rank_desc)
    secondary_rank = (
        rank_cross_section(secondary_map, descending=ey_rank_desc)
        if secondary_map and ey_rank_desc is not None else {}
    )
    combined: dict[str, float] = {}
    for sym in primary_rank:
        combined[sym] = primary_rank[sym] + secondary_rank.get(sym, 0)

    selected = top_n_by_score(combined, top_n)
    items: list[ScreenItem] = []
    for rank, sym in enumerate(selected, 1):
        s = snap.get(sym, {})
        items.append(ScreenItem(
            symbol=sym,
            rank=rank,
            score=combined[sym],
            pe_ttm=s.get("pe_ttm"),
            pb=s.get("pb"),
            dv_ttm=s.get("dv_ttm"),
            roe=s.get("roe"),
            roic=s.get("roic"),
            ebit_yield=s.get("ebit_yield"),
            debt_ratio=s.get("debt_ratio"),
            fscore=s.get("fscore"),
            reason=reason,
        ))
    return items


# ── 模式6：财务质量诊断选股（compute_quality_report 评分 + 淘汰红线）─────────

def _screen_quality(
    symbols, val_map, fin_map, as_of, top_n, filters,
) -> list[ScreenItem]:
    """
    财务质量诊断选股（《股票投资课程》08/19 集"先筛掉 80% 垃圾公司"）。

    用 fetch_financial_snapshot 取最新三大表快照，逐标的算 quality.compute_quality_report：
      - 剔除 verdict == "eliminate"（淘汰红线触发）
      - 按 quality_score(0~100) 降序排名
      - factor_breakdown 输出完整诊断报告
    可选过滤：min_quality_score（默认 0）、drop_review（True 时连 review 一并剔除）。
    """
    min_score = filters.get("min_quality_score", 0)
    drop_review = filters.get("drop_review", False)

    snap_map = fetch_financial_snapshot(symbols, as_of, include_detail=False)

    candidates: list[tuple[str, dict, float]] = []
    for sym in symbols:
        fin = snap_map.get(sym)
        if not fin:
            continue
        report = compute_quality_report(fin)
        verdict = report.get("verdict")
        if verdict == "eliminate":
            continue
        if drop_review and verdict != "pass":
            continue
        score = report.get("quality_score")
        if score is None or score < min_score:
            continue
        candidates.append((sym, report, float(score)))

    candidates.sort(key=lambda x: x[2], reverse=True)
    selected = candidates[: max(0, int(top_n))]

    items: list[ScreenItem] = []
    for rank, (sym, report, score) in enumerate(selected, 1):
        metrics = report.get("metrics", {})
        dupont = metrics.get("dupont") or {}
        dupont_roe = dupont.get("roe")
        val = val_map.get(sym) or {}
        fin_legacy = fin_map.get(sym) or {}
        items.append(ScreenItem(
            symbol=sym,
            rank=rank,
            score=score,
            pe_ttm=val.get("pe_ttm") or val.get("pe"),
            pb=val.get("pb"),
            dv_ttm=val.get("dv_ttm") or val.get("dv_ratio"),
            roe=round(dupont_roe * 100, 2) if dupont_roe is not None else None,
            debt_ratio=fin_legacy.get("debt_ratio"),
            reason=f"财务质量诊断 {report.get('verdict')}（{score:.1f}分）",
            factor_breakdown=report,
        ))
    return items
