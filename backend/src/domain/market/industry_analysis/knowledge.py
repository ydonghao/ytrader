# backend/src/domain/market/industry_analysis/knowledge.py
"""申万一级行业知识层:conf/industry_knowledge.yaml 静态加载(用户笔记三层分级)。

启动/首次调用即校验:31 码齐全、枚举合法,坏配置报错而不是静默降级。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CONF_DIR = Path(__file__).parent.parent.parent.parent.parent / "conf"

# 申万2021一级31个(纯6位,不带.SI)——与 sw_industry_member.sw_code_l1 同口径
SW_L1_CODES: tuple[str, ...] = (
    "801010", "801020", "801030", "801040", "801050", "801080", "801110",
    "801120", "801130", "801140", "801150", "801160", "801170", "801180",
    "801200", "801210", "801230", "801710", "801720", "801730", "801740",
    "801750", "801760", "801770", "801780", "801790", "801880", "801890",
    "801960", "801970", "801980",
)

TIER_LABELS = {1: "易分析", 2: "需专业分析", 3: "消息驱动"}
SUITABILITY = ("high", "medium", "low")


@dataclass(frozen=True)
class IndustryKnowledge:
    sw_code: str
    name: str
    tier: int                  # 投资难易度三层(用户笔记)
    retail_suitable: str       # 散户适宜度 high/medium/low
    approach: str              # 一句话分析抓手
    upstream: tuple[str, ...]
    downstream: tuple[str, ...]
    note: str = ""


def _to_knowledge(sw_code: str, raw: dict[str, Any]) -> IndustryKnowledge:
    tier = raw.get("tier")
    if tier not in TIER_LABELS:
        raise ValueError(f"{sw_code} tier 非法: {tier}(须 1/2/3)")
    suit = raw.get("retail_suitable")
    if suit not in SUITABILITY:
        raise ValueError(f"{sw_code} retail_suitable 非法: {suit}")
    return IndustryKnowledge(
        sw_code=sw_code,
        name=str(raw.get("name", "")).strip(),
        tier=int(tier),
        retail_suitable=suit,
        approach=str(raw.get("approach", "")).strip(),
        upstream=tuple(raw.get("upstream") or ()),
        downstream=tuple(raw.get("downstream") or ()),
        note=str(raw.get("note", "") or ""),
    )


def load_knowledge(path: Path | None = None) -> dict[str, IndustryKnowledge]:
    """加载并校验知识 yaml;缺码/坏枚举即抛 ValueError。"""
    p = path or (_CONF_DIR / "industry_knowledge.yaml")
    raw: dict = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    missing = set(SW_L1_CODES) - set(raw.keys())
    if missing:
        raise ValueError(f"industry_knowledge.yaml 缺少申万一级行业: {sorted(missing)}")
    return {code: _to_knowledge(code, raw[code]) for code in SW_L1_CODES}
