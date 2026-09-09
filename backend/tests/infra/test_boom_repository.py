# backend/tests/infra/test_boom_repository.py
"""boom 三表仓储测试(sqlite 内存库)。"""
import datetime as dt
from contextlib import contextmanager

import pytest
from sqlmodel import SQLModel, Session, create_engine

from src.domain.market.boom.keywords import SEED_KEYWORDS
from src.infra.database.market.boom import (
    BoomCandidateTable, BoomKeywordTable, BoomScanHitTable,
    BoomRepository,
)


@pytest.fixture()
def repo(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/boom.db")
    SQLModel.metadata.create_all(
        engine,
        tables=[BoomKeywordTable.__table__, BoomScanHitTable.__table__,
                BoomCandidateTable.__table__],
    )

    @contextmanager
    def scope():
        with Session(engine) as s:
            yield s

    yield BoomRepository(scope)
    engine.dispose()


def test_seed_and_list_keywords(repo):
    n = repo.seed_keywords()
    assert n == len(SEED_KEYWORDS)
    assert repo.seed_keywords() == 0            # 幂等
    kws = repo.list_keywords()
    assert len(kws) == len(SEED_KEYWORDS)
    assert all(isinstance(k.weight, int) for k in kws)


def test_keyword_crud(repo):
    repo.seed_keywords()
    k = repo.create_keyword("supply_tight", "一货难求", 2)
    assert k.id is not None
    repo.update_keyword(k.id, enabled=False)
    assert all(x.keyword != "一货难求" for x in repo.list_keywords(enabled_only=True))
    repo.delete_keyword(k.id)
    assert repo.get_keyword(k.id) is None


def test_upsert_hits_idempotent(repo):
    rows = [{"symbol": "600519", "source_type": "news", "source_ref": "http://a",
             "source_date": dt.date(2026, 9, 7), "keyword": "供不应求",
             "category": "supply_tight", "snippet": "…供不应求…"}]
    assert repo.upsert_hits(rows) == 1
    assert repo.upsert_hits(rows) == 0          # 冲突跳过
    hits = repo.get_hits("600519")
    assert len(hits) == 1 and hits[0].keyword == "供不应求"


def test_upsert_candidates_and_query(repo):
    row = {"symbol": "600519", "report_date": dt.date(2026, 9, 30),
           "forecast_type": "preannounce", "company_name": "贵州茅台",
           "announce_date": dt.date(2026, 10, 12), "change_pct": 60.0,
           "forecast_type_label": "预增", "categories": ["supply_tight"],
           "keyword_count": 2, "news_hit_count": 1}
    repo.upsert_candidates([row])
    row["change_pct"] = 65.0                     # 重新扫 → 更新
    repo.upsert_candidates([row])
    got = repo.get_candidates()
    assert len(got) == 1 and got[0].change_pct == 65.0
    one = repo.get_candidate("600519", dt.date(2026, 9, 30))
    assert one.company_name == "贵州茅台"
    repo.mark_news_synced("600519", dt.date(2026, 9, 30))
    assert repo.get_candidate("600519", dt.date(2026, 9, 30)).news_synced


def test_hits_as_of_lookahead_guard(repo):
    repo.upsert_hits([
        {"symbol": "600519", "source_type": "news", "source_ref": "u1",
         "source_date": dt.date(2026, 10, 11), "keyword": "供不应求",
         "category": "supply_tight", "snippet": ""},
        {"symbol": "600519", "source_type": "news", "source_ref": "u2",
         "source_date": dt.date(2026, 10, 13), "keyword": "高景气",
         "category": "boom_up", "snippet": ""},
    ])
    asof = repo.get_hits_as_of(["600519"], dt.date(2026, 10, 12))
    assert [h.keyword for h in asof] == ["供不应求"]   # 晚于 10-12 的不入


def test_get_report_dates_distinct_desc(repo):
    """报告期下拉:distinct + 降序 + limit 截断。"""
    for rd in (dt.date(2026, 6, 30), dt.date(2026, 9, 30), dt.date(2026, 3, 31)):
        repo.upsert_candidates([
            {"symbol": "600519", "report_date": rd,
             "forecast_type": "preannounce", "categories": [],
             "keyword_count": 0, "news_hit_count": 0},
            {"symbol": "000001", "report_date": rd,
             "forecast_type": "preannounce", "categories": [],
             "keyword_count": 0, "news_hit_count": 0},
        ])
    assert repo.get_report_dates() == [dt.date(2026, 9, 30),
                                       dt.date(2026, 6, 30),
                                       dt.date(2026, 3, 31)]
    assert repo.get_report_dates(limit=2) == [dt.date(2026, 9, 30),
                                              dt.date(2026, 6, 30)]


def test_mark_llm_and_status(repo):
    rd = dt.date(2026, 9, 30)
    repo.upsert_candidates([{"symbol": "600519", "report_date": rd,
                             "forecast_type": "preannounce",
                             "categories": [], "keyword_count": 0,
                             "news_hit_count": 0}])
    repo.mark_llm("600519", rd, score=82, verdict="focus", summary="量价齐升")
    repo.set_status("600519", rd, "added_watchlist")
    c = repo.get_candidate("600519", rd)
    assert c.llm_score == 82 and c.llm_verdict == "focus"
    assert c.status == "added_watchlist"
