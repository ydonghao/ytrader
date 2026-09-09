# backend/tests/domain/boom/test_scanner.py
"""景气词典扫描器纯函数测试。"""
from src.domain.market.boom.keywords import (
    CATEGORIES, CATEGORY_LABELS, SEED_KEYWORDS, default_keywords, KeywordDef,
)
from src.domain.market.boom.scanner import scan_text, summarize


def test_seed_covers_all_categories():
    cats = {k.category for k in SEED_KEYWORDS}
    assert cats == set(CATEGORIES)
    assert all(c in CATEGORY_LABELS for c in cats)


def test_scan_hits_multiple_categories():
    text = "公司产品供不应求,行业处于高景气周期,新品上市后持续放量。"
    hits = scan_text(text, default_keywords())
    cats = {h.category for h in hits}
    assert "supply_tight" in cats      # 供不应求
    assert "boom_up" in cats           # 高景气
    assert any(h.snippet and "供不应求" in h.snippet for h in hits)


def test_scan_negation_context_skipped():
    text = "随着新产能释放,公司产品已不再供不应求。"
    hits = scan_text(text, default_keywords())
    assert all(h.keyword != "供不应求" for h in hits)


def test_scan_dedup_same_keyword():
    text = "产品供不应求,海外市场同样供不应求。"
    hits = scan_text(text, default_keywords())
    assert sum(1 for h in hits if h.keyword == "供不应求") == 1


def test_scan_empty_text_and_no_hit():
    assert scan_text("", default_keywords()) == []
    assert scan_text("今天天气不错", default_keywords()) == []


def test_summarize():
    kws = [KeywordDef("supply_tight", "供不应求", 3), KeywordDef("boom_up", "高景气", 2)]
    hits = scan_text("供不应求叠加高景气", kws)
    s = summarize(hits)
    assert s["categories"] == ["boom_up", "supply_tight"]
    assert s["keyword_count"] == 2
    assert s["score"] == 5
