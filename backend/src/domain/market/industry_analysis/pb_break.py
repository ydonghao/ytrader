# backend/src/domain/market/industry_analysis/pb_break.py
"""破净率聚合(纯函数):个股PB行 → market/industry 两级破净统计。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.domain.market.industry_analysis.stats import median


@dataclass(frozen=True)
class BreakStat:
    total_count: int
    break_count: int
    break_rate: Optional[float]   # 0-1
    median_pb: Optional[float]


def _stat(pbs: list[Optional[float]]) -> BreakStat:
    valid = [p for p in pbs if p is not None]
    n_break = sum(1 for p in valid if p < 1.0)
    rate = (n_break / len(pbs)) if pbs else None
    return BreakStat(total_count=len(pbs), break_count=n_break,
                     break_rate=rate, median_pb=median(valid))


def aggregate_pb_break(rows) -> dict:
    """rows: [(symbol, pb|None, sw_code_l1|None), ...] 一次遍历两级聚合。

    market 口径含全部行(无行业归属也计入——规格§3.1:市场级无偏差);
    industries 只含有申万归属的行。
    """
    all_pb: list[Optional[float]] = []
    by_ind: dict[str, list[Optional[float]]] = {}
    for _symbol, pb, sw_code in rows:
        all_pb.append(pb)
        if sw_code:
            by_ind.setdefault(sw_code, []).append(pb)
    return {
        "market": _stat(all_pb),
        "industries": {code: _stat(pbs) for code, pbs in by_ind.items()},
    }
