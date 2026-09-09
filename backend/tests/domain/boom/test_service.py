"""BoomRadarService 流水线测试(fake 依赖)。"""
import datetime as dt
from dataclasses import dataclass, field
from types import SimpleNamespace

from src.domain.market.boom.service import (
    BoomRadarService, growth_filter, raw_text, to_prefixed,
)


# ── 纯函数 ──────────────────────────────────────────────
def _fc(sym, ftype="preannounce", label="预增", pct=60.0, raw=None, ann=None):
    return SimpleNamespace(
        symbol=sym, forecast_type=ftype, report_date=dt.date(2026, 9, 30),
        metric="净利润", company_name="X", announce_date=ann or dt.date(2026, 10, 12),
        change_pct=pct, forecast_type_label=label, raw=raw or {},
    )


def test_growth_filter():
    rows = [
        _fc("600001"),                              # 预增60 → 入池
        _fc("600002", pct=30.0),                    # 预增30 → 出
        _fc("600003", label="预亏", pct=100.0),      # 预亏 → 出
        _fc("600004", pct=None),                    # 预增但无幅度 → 出
        _fc("600005", ftype="express", pct=80.0),   # 快报80 → 入池
        _fc("600006", ftype="express", pct=None),   # 快报无幅度 → 出
    ]
    got = [f.symbol for f in growth_filter(rows, min_change_pct=50.0)]
    assert got == ["600001", "600005"]


def test_raw_text_concatenates_strings():
    row = _fc("600001", raw={"预告类型": "预增", "业绩变动原因说明": "产品供不应求", "数值": 1.2})
    assert "产品供不应求" in raw_text(row)


def test_to_prefixed():
    assert to_prefixed("600519") == "sh600519"
    assert to_prefixed("300750") == "sz300750"


# ── 流水线 ──────────────────────────────────────────────
class FakeRepo:
    def __init__(self):
        self.hits, self.candidates, self.news_synced = [], [], []

    def seed_keywords(self): return 0
    def list_keywords(self, enabled_only=True):
        from src.domain.market.boom.keywords import default_keywords, KeywordDef
        return default_keywords()
    def upsert_hits(self, rows): self.hits.extend(rows); return len(rows)
    def upsert_candidates(self, rows): self.candidates.extend(rows); return len(rows)
    def get_candidates(self, report_date=None, limit=1000): return self.candidates
    def get_candidate(self, symbol, report_date): return None
    def get_hits(self, symbol, report_date=None):
        return [h for h in self.hits if h["symbol"] == symbol]
    def mark_news_synced(self, symbol, report_date): self.news_synced.append(symbol)


class FakeForecastRepo:
    def get_by_announce_date_range(self, start, end, forecast_type=None, limit=20000):
        return [_fc("600001", raw={"业绩变动原因说明": "产品供不应求,行业高景气"}),
                _fc("600002", pct=30.0)]


class FakeNewsSync:
    def __init__(self): self.calls = []
    def sync_stock_news(self, symbol, days_back=7):
        self.calls.append(symbol)
        return SimpleNamespace(saved=3, total=3, duplicates=0, errors=0,
                               duration_seconds=0.1)


@dataclass
class FakeArticle:
    title: str
    content: str
    publish_time: dt.datetime
    symbol: str = "sh600001"


class FakeNewsRepo:
    def find_by_symbol(self, symbol, days_back=7, limit=50):
        return [FakeArticle("满产满销", "公司当前满产满销,订单饱满。",
                            dt.datetime(2026, 10, 10, 9, 0))]


def test_run_daily_off_season_fast_noop():
    svc = BoomRadarService(FakeRepo(), FakeForecastRepo(), FakeNewsSync(),
                           FakeNewsRepo(), {"min_change_pct": 50.0})
    stats = svc.run_daily(today=dt.date(2026, 9, 8))     # 9月非财报季
    assert stats["in_season"] is False
    assert stats["candidates"] == 0


def test_run_daily_in_season_pipeline():
    repo = FakeRepo()
    news_sync = FakeNewsSync()
    svc = BoomRadarService(repo, FakeForecastRepo(), news_sync, FakeNewsRepo(),
                           {"min_change_pct": 50.0})
    stats = svc.run_daily(today=dt.date(2026, 10, 15))
    assert stats["in_season"] is True
    assert stats["pool"] == 1                       # 只有 600001 入池
    assert news_sync.calls == ["sh600001"]          # 新闻同步带前缀
    syms = [c["symbol"] for c in repo.candidates]
    assert syms == ["600001"]
    cats = repo.candidates[0]["categories"]
    assert "supply_tight" in cats and "boom_up" in cats   # raw 文本命中
    assert "demand_strong" in cats                          # 新闻正文命中
    kw_types = {h["source_type"] for h in repo.hits}
    assert kw_types == {"forecast", "news"}
    assert repo.news_synced == ["600001"]


def test_run_daily_idempotent_skip_news_sync():
    repo = FakeRepo()
    news_sync = FakeNewsSync()
    existing = {"symbol": "600001", "report_date": dt.date(2026, 9, 30),
                "forecast_type": "preannounce", "company_name": "X",
                "announce_date": dt.date(2026, 10, 12), "change_pct": 60.0,
                "forecast_type_label": "预增", "categories": [],
                "keyword_count": 0, "news_hit_count": 0}
    repo.candidates.append(existing)
    repo.get_candidate = lambda s, r: SimpleNamespace(**existing)
    svc = BoomRadarService(repo, FakeForecastRepo(), news_sync, FakeNewsRepo(),
                           {"min_change_pct": 50.0})
    svc.run_daily(today=dt.date(2026, 10, 15))
    assert news_sync.calls == []                    # 已同步过 → 跳过


# ── LLM 深读 ────────────────────────────────────────────
class FakeRepoWithLLM(FakeRepo):
    def __init__(self):
        super().__init__()
        self.llm_calls = []
        _c = {"symbol": "600001", "report_date": dt.date(2026, 9, 30),
              "forecast_type": "preannounce", "company_name": "X",
              "announce_date": dt.date(2026, 10, 12), "change_pct": 60.0,
              "forecast_type_label": "预增", "categories": ["supply_tight"],
              "keyword_count": 3, "news_hit_count": 1, "llm_score": None,
              "llm_verdict": None, "llm_summary": None}
        self.candidates = [_c]
        self._c = _c

    def get_candidates(self, report_date=None, limit=1000):
        return [type("C", (), self._c)()]

    def mark_llm(self, symbol, report_date, score, verdict, summary):
        self.llm_calls.append((symbol, score, verdict))


def test_llm_deep_read_writes_back(monkeypatch):
    import asyncio
    repo = FakeRepoWithLLM()
    svc = BoomRadarService(repo, FakeForecastRepo(), FakeNewsSync(),
                           FakeNewsRepo(), {"min_change_pct": 50.0})
    async def fake_analyze(candidate, hits):
        return {"boom_score": 82, "verdict": "focus", "summary": "量价齐升",
                "risks": []}
    monkeypatch.setattr("src.domain.market.boom.service.analyze_candidate",
                        fake_analyze)
    stats = asyncio.run(svc.llm_deep_read())
    assert stats["analyzed"] == 1
    assert repo.llm_calls == [("600001", 82, "focus")]


# ── 调研纪要文本源(Task 11)────────────────────────────
def test_survey_source_scanned(monkeypatch):
    repo = FakeRepo()

    class SurveyProvider:
        def fetch_survey(self, symbol, months_back=6):
            return [{"survey_date": dt.date(2026, 10, 10), "org_types": "基金",
                     "q_a_text": "公司表示当前产品供不应求,新产能Q4释放。"}]

    svc = BoomRadarService(repo, FakeForecastRepo(), FakeNewsSync(), FakeNewsRepo(),
                           {"min_change_pct": 50.0}, survey_provider=SurveyProvider())
    stats = svc.run_daily(today=dt.date(2026, 10, 15))
    survey_hits = [h for h in repo.hits if h["source_type"] == "survey"]
    assert survey_hits and survey_hits[0]["keyword"] == "供不应求"


def test_survey_provider_failure_degrades(monkeypatch):
    repo = FakeRepo()

    class BadProvider:
        def fetch_survey(self, symbol, months_back=6):
            raise RuntimeError("boom")

    svc = BoomRadarService(repo, FakeForecastRepo(), FakeNewsSync(), FakeNewsRepo(),
                           {"min_change_pct": 50.0}, survey_provider=BadProvider())
    stats = svc.run_daily(today=dt.date(2026, 10, 15))
    assert stats["in_season"] is True          # 不因调研源崩溃


# ── 正式报表窗候选补充(Task 12)────────────────────────
class FakeForecastRepoFormal(FakeForecastRepo):
    def __init__(self):
        super().__init__()
        self.formal_calls = []

    def get_quarter_yoy_growth(self, report_date, min_pct):
        self.formal_calls.append((report_date, min_pct))
        return [{"symbol": "000333", "report_date": dt.date(2026, 9, 30),
                 "q_np": 1.2e9, "q_np_prev": 5e8, "yoy_pct": 140.0}]


def test_formal_window_adds_candidates():
    repo = FakeRepo()
    fr = FakeForecastRepoFormal()
    svc = BoomRadarService(repo, fr, FakeNewsSync(), FakeNewsRepo(),
                           {"min_change_pct": 50.0})
    stats = svc.run_daily(today=dt.date(2026, 10, 25))   # 10月下旬正式窗
    assert fr.formal_calls                            # 触发了正式报表查询
    assert fr.formal_calls[0][0] == dt.date(2026, 9, 30)   # 10月 → Q3 报告期
    formal = [c for c in repo.candidates if c["forecast_type"] == "formal"]
    assert formal and formal[0]["symbol"] == "000333"
    assert formal[0]["forecast_type_label"] == "单季大增"


# ── 终审修复:3/8 月正式窗(非预告季)可达 ───────────────
def test_formal_window_march_off_season():
    """3月下旬非预告季,正式报表窗仍应产出候选(年报窗)。"""
    repo = FakeRepo()
    fr = FakeForecastRepoFormal()
    fr.get_by_announce_date_range = lambda s, e, **kw: []   # 非预告季无预告
    svc = BoomRadarService(repo, fr, FakeNewsSync(), FakeNewsRepo(),
                           {"min_change_pct": 50.0})
    stats = svc.run_daily(today=dt.date(2026, 3, 25))
    assert stats["in_season"] is False
    assert fr.formal_calls == [(dt.date(2025, 12, 31), 50.0)]  # 3月 → 上年报
    formal = [c for c in repo.candidates if c["forecast_type"] == "formal"]
    assert formal and formal[0]["symbol"] == "000333"
    assert stats["candidates"] == 1


def test_formal_window_august_off_season():
    repo = FakeRepo()
    fr = FakeForecastRepoFormal()
    fr.get_by_announce_date_range = lambda s, e, **kw: []
    svc = BoomRadarService(repo, fr, FakeNewsSync(), FakeNewsRepo(),
                           {"min_change_pct": 50.0})
    stats = svc.run_daily(today=dt.date(2026, 8, 25))
    assert stats["in_season"] is False
    assert fr.formal_calls[0][0] == dt.date(2026, 6, 30)      # 8月 → 中报


# ── 终审修复:命中按报告窗过滤 ─────────────────────────
def test_survey_stale_date_skipped():
    """调研纪要日期早于当前窗口起点 → 跳过不入命中。"""
    repo = FakeRepo()

    class StaleProvider:
        def fetch_survey(self, symbol, months_back=6):
            return [{"survey_date": dt.date(2026, 7, 1),   # 早于 10 月窗
                     "org_types": "基金", "q_a_text": "产品供不应求"}]

    svc = BoomRadarService(repo, FakeForecastRepo(), FakeNewsSync(),
                           FakeNewsRepo(), {"min_change_pct": 50.0},
                           survey_provider=StaleProvider())
    svc.run_daily(today=dt.date(2026, 10, 15))
    assert [h for h in repo.hits if h["source_type"] == "survey"] == []


def test_llm_deep_read_filters_cross_window_hits(monkeypatch):
    """LLM 深读只取当前报告窗内(source_date ≥ report_date+1)的命中。"""
    import asyncio
    from types import SimpleNamespace as NS
    repo = FakeRepoWithLLM()
    repo.get_hits = lambda s, r: [
        NS(keyword="旧命中", category="supply_tight", source_type="news",
           source_date=dt.date(2026, 7, 15), snippet="Q1 窗旧闻"),
        NS(keyword="新命中", category="supply_tight", source_type="news",
           source_date=dt.date(2026, 10, 5), snippet="Q3 窗新闻"),
    ]
    svc = BoomRadarService(repo, FakeForecastRepo(), FakeNewsSync(),
                           FakeNewsRepo(), {"min_change_pct": 50.0})
    seen = {}

    async def fake_analyze(candidate, hits):
        seen["hits"] = hits
        return {"boom_score": 70, "verdict": "watch", "summary": "s",
                "risks": []}

    monkeypatch.setattr("src.domain.market.boom.service.analyze_candidate",
                        fake_analyze)
    asyncio.run(svc.llm_deep_read())
    assert [h["keyword"] for h in seen["hits"]] == ["新命中"]


def test_llm_deep_read_degrades_on_error(monkeypatch):
    import asyncio
    repo = FakeRepoWithLLM()
    svc = BoomRadarService(repo, FakeForecastRepo(), FakeNewsSync(),
                           FakeNewsRepo(), {"min_change_pct": 50.0})
    async def boom(candidate, hits):
        raise RuntimeError("llm down")
    monkeypatch.setattr("src.domain.market.boom.service.analyze_candidate", boom)
    stats = asyncio.run(svc.llm_deep_read())
    assert stats["analyzed"] == 0 and stats["failed"] == 1
    assert repo.llm_calls == []                 # 失败不回写


def test_run_daily_seeds_keywords():
    """run_daily 必须播种词典种子(首跑表空时的接线保证)。"""
    class SeedingRepo(FakeRepo):
        def __init__(self):
            super().__init__()
            self.seeded = 0

        def seed_keywords(self):
            self.seeded += 1
            return 0

    repo = SeedingRepo()
    svc = BoomRadarService(repo, FakeForecastRepo(), FakeNewsSync(),
                           FakeNewsRepo(), {"min_change_pct": 50.0})
    svc.run_daily(today=dt.date(2026, 10, 15))
    assert repo.seeded == 1
