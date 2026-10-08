# backend/src/domain/market/industry_analysis/flow_map.py
"""东财行业资金流→申万一级行业近似映射(多对一,人工维护)。

未匹配的东财行业由调用方置缺(评分按剩余权重归一),不强行归属。
"""
from __future__ import annotations

from pathlib import Path

import yaml

_CONF_DIR = Path(__file__).parent.parent.parent.parent.parent / "conf"


def load_flow_map(path: Path | None = None) -> dict[str, str]:
    p = path or (_CONF_DIR / "em_flow_to_sw.yaml")
    raw: dict = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {str(k).strip(): str(v).strip() for k, v in raw.items()}


def summarize_flow(rows: list[dict]) -> list[dict]:
    """近30自然日资金流行 → 每东财行业 day/flow5/flow20 + 申万映射,按 flow20 降序。"""
    if not rows:
        return []
    by_day: dict = {}
    for r in rows:
        by_day.setdefault(r["trade_date"], {})[r["em_industry_name"]] = \
            r.get("main_net_inflow") or 0.0
    days = sorted(by_day, reverse=True)          # 交易日降序,days[0] 即最新
    em2sw = load_flow_map()
    names = sorted({r["em_industry_name"] for r in rows})
    out = []
    for name in names:
        day_v = by_day[days[0]].get(name) if days else None
        flow5 = sum(by_day[d].get(name, 0.0) for d in days[:5])
        flow20 = sum(by_day[d].get(name, 0.0) for d in days[:20])
        out.append({"em_industry_name": name, "sw_code": em2sw.get(name),
                    "day": day_v, "flow5": flow5, "flow20": flow20})
    out.sort(key=lambda r: (r["flow20"] is not None, r["flow20"]),
             reverse=True)
    return out
