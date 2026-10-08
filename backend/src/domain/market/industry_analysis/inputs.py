# backend/src/domain/market/industry_analysis/inputs.py
"""景气评分输入装配:跨表现读 → IndustryInputs(仓储鸭子类型注入可测)。

数据口径(规格§4 F2):
- 盈利:cross_section 两个最新报告期(净利同比自算,亏损基数→None)
- 估值:sw_index_valuation_daily 窗口内 midrank 分位(窗口=评分 config 恒定)
- 动量:index_ohlcv 61 根首尾收益 − sh000300 同窗(复用 relative_strength)
- 资金:近30自然日东财流映射申万求和(不足1个交易日→None)
"""
from __future__ import annotations

import datetime as dt

from src.domain.market.industry_analysis.flow_map import load_flow_map
from src.domain.market.industry_analysis.knowledge import SW_L1_CODES
from src.domain.market.industry_analysis.prosperity import (
    IndustryInputs, net_profit_yoy,
)
from src.domain.market.industry_analysis.stats import percentile_rank
from src.domain.market.strategy.relative_strength import relative_strength

_BENCH = "sh000300"
_FLOW_LOOKBACK_DAYS = 30       # 自然日,约 20 个交易日
_RS_BARS = 61                 # 60日收益需要61根


def _ret_over(closes: list[tuple[dt.date, float]]) -> float | None:
    if len(closes) < 2:
        return None
    first, last = closes[0][1], closes[-1][1]
    if not first:
        return None
    return last / first - 1.0


def _build_rs60(repo, as_of: dt.date,
                codes: list[str]) -> dict[str, float | None]:
    start = as_of - dt.timedelta(days=_RS_BARS * 2)   # 61根交易日≈122自然日
    symbols = [f"sw{c}" for c in codes] + [_BENCH]
    closes = repo.get_index_closes(symbols, start, as_of)
    bench = _ret_over(closes.get(_BENCH, []))
    out: dict[str, float | None] = {}
    for c in codes:
        tgt = _ret_over(closes.get(f"sw{c}", []))
        if tgt is None or bench is None:
            out[c] = None
            continue
        rs = relative_strength(tgt, bench)
        out[c] = rs.excess if rs else None
    return out


def _pick_year_ago(sec: list[dict]) -> dict:
    """净利同比基期=最新报告期一年前同期(±45天容差取最近);找不到返回 {}。

    仓储返回 ~550 天内全部报告期(季度频),上季≠基期,必须按一年前同期挑。
    """
    if not sec:
        return {}
    cur_d = sec[-1].get("report_date")
    if cur_d is None:
        return {}
    best = None
    for row in sec[:-1]:
        rd = row.get("report_date")
        if rd is None:
            continue
        delta = abs((rd - (cur_d - dt.timedelta(days=365))).days)
        if delta <= 45 and (best is None or delta < best[0]):
            best = (delta, row)
    return best[1] if best else {}


def _build_flow20(repo, as_of: dt.date) -> dict[str, float]:
    rows = repo.get_flow_rows(as_of - dt.timedelta(days=_FLOW_LOOKBACK_DAYS))
    em2sw = load_flow_map()
    sums: dict[str, float] = {}
    for r in rows:
        # 上界:as_of 之后落库的资金流行(17:05 job 逐日写入)不得并入
        # 上周估值日的评分快照,否则逐日覆写漂移
        d = r.get("trade_date")
        if d is not None and d > as_of:
            continue
        code = em2sw.get(r.get("em_industry_name", ""))
        v = r.get("main_net_inflow")
        if code and v is not None:
            sums[code] = sums.get(code, 0.0) + float(v)
    return sums


def assemble_inputs(repo, as_of: dt.date,
                    pct_window_years: int = 8) -> dict[str, IndustryInputs]:
    codes = list(SW_L1_CODES)
    w_start = as_of - dt.timedelta(days=int(pct_window_years * 365.25))

    sections = repo.get_cross_section_latest_two(level=1, as_of=as_of)
    valuations = repo.get_sw_valuation_window(codes, w_start, as_of)
    rs60 = _build_rs60(repo, as_of, codes)
    flow20 = _build_flow20(repo, as_of)

    out: dict[str, IndustryInputs] = {}
    for code in codes:
        sec = sections.get(code) or []
        cur = sec[-1] if sec else {}
        prev = _pick_year_ago(sec)
        series = valuations.get(code) or []
        last_v = series[-1] if series else {}
        pbs = [r["pb"] for r in series]
        pes = [r["pe_ttm"] for r in series]
        out[code] = IndustryInputs(
            sw_code=code,
            name="",
            revenue_yoy=cur.get("revenue_yoy"),
            net_profit_yoy=net_profit_yoy(cur.get("net_profit_sum"),
                                          prev.get("net_profit_sum")),
            pb=last_v.get("pb"),
            pb_pct=percentile_rank(last_v.get("pb"), pbs),
            pe_ttm=last_v.get("pe_ttm"),
            pe_pct=percentile_rank(last_v.get("pe_ttm"), pes),
            rs60=rs60.get(code),
            flow20=flow20.get(code),
        )
    return out
