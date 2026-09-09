# backend/src/domain/market/boom/scanner.py
"""景气文本扫描器(纯函数)。同词去重取首现;否定语境丢弃。"""
from dataclasses import dataclass
from typing import Sequence

from src.domain.market.boom.keywords import KeywordDef

NEGATION_WORDS = ("未", "不再", "难以", "没有", "无法", "不复")
NEGATION_WINDOW = 8   # 命中词往前看 8 个字符
SNIPPET_RADIUS = 30   # 摘录上下文半径


@dataclass(frozen=True)
class ScanHit:
    keyword: str
    category: str
    weight: int
    snippet: str


def _negated(text: str, idx: int) -> bool:
    start = max(0, idx - NEGATION_WINDOW)
    return any(n in text[start:idx] for n in NEGATION_WORDS)


def scan_text(text: str, keywords: Sequence[KeywordDef]) -> list[ScanHit]:
    if not text:
        return []
    hits: list[ScanHit] = []
    seen: set[str] = set()
    for kw in keywords:
        if kw.keyword in seen:
            continue
        idx = text.find(kw.keyword)
        if idx < 0 or _negated(text, idx):
            continue
        seen.add(kw.keyword)
        lo = max(0, idx - SNIPPET_RADIUS)
        hi = min(len(text), idx + len(kw.keyword) + SNIPPET_RADIUS)
        hits.append(ScanHit(kw.keyword, kw.category, kw.weight, text[lo:hi]))
    return hits


def summarize(hits: list[ScanHit]) -> dict:
    return {
        "categories": sorted({h.category for h in hits}),
        "keyword_count": len(hits),
        "score": sum(h.weight for h in hits),
    }
