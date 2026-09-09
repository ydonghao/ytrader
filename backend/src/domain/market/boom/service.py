"""财报季景气雷达编排:预告入池 → 新闻同步 → 词典扫描 → 命中/候选落库。"""
import datetime as dt
import logging
from typing import Optional

from src.domain.market.boom.keywords import CATEGORY_LABELS, KeywordDef
from src.domain.market.boom.llm_analyst import analyze_candidate
from src.domain.market.boom.scanner import ScanHit, scan_text, summarize
from src.domain.market.boom.season import (
    announce_window, formal_report_dates, is_formal_window,
)

log = logging.getLogger("boom_radar")

DEFAULT_CONFIG = {"min_change_pct": 50.0, "news_days_back": 7}


def to_prefixed(symbol: str) -> str:
    """纯 6 位 → 带 sh/sz 前缀(news/ohlcv 口径)。"""
    return ("sh" if symbol.startswith(("6", "9", "5")) else "sz") + symbol


def growth_filter(forecasts, min_change_pct: float) -> list:
    """业绩大增过滤:preannounce 需「预增」且幅度达标;express 幅度达标即可。"""
    out = []
    for f in forecasts:
        pct = f.change_pct
        if pct is None or pct < min_change_pct:
            continue
        if f.forecast_type == "preannounce" and f.forecast_type_label != "预增":
            continue
        out.append(f)
    return out


def raw_text(row) -> str:
    """forecast.raw 原始行里的字符串字段拼接为待扫文本。"""
    raw = row.raw if isinstance(row.raw, dict) else {}
    return "。".join(str(v) for v in raw.values() if isinstance(v, str) and v)


def window_start_for_report_date(rd) -> dt.date:
    """报告期对应的披露窗起点:季末+1天(下月1日)。"""
    return rd + dt.timedelta(days=1)


def filter_window_hits(hits, report_date) -> list:
    """只保留当前报告窗内的命中(source_date ≥ 季末+1);无日期者剔除。"""
    ws = window_start_for_report_date(report_date)
    return [h for h in hits
            if getattr(h, "source_date", None) is not None
            and h.source_date >= ws]


class BoomRadarService:
    def __init__(self, repo, forecast_repo, news_sync, news_repo, config: dict,
                 survey_provider=None):
        self.repo = repo
        self.forecast_repo = forecast_repo
        self.news_sync = news_sync
        self.news_repo = news_repo
        self.config = {**DEFAULT_CONFIG, **config}
        self.survey_provider = survey_provider

    def run_daily(self, today: Optional[dt.date] = None) -> dict:
        today = today or dt.date.today()
        status = announce_window(today)
        formal = is_formal_window(today)
        if not status.in_season and not formal:
            return {"in_season": False, "next_window_start": status.next_window_start,
                    "pool": 0, "news_synced": 0, "hits": 0, "candidates": 0,
                    "formal_added": 0}

        pool: list = []
        keywords: list[KeywordDef] = []
        hit_rows: list[dict] = []
        cand_rows: list[dict] = []
        news_synced = 0
        since: Optional[dt.datetime] = None

        if status.in_season:
            forecasts = self.forecast_repo.get_by_announce_date_range(
                status.window_start, today
            )
            pool = growth_filter(forecasts, self.config["min_change_pct"])
            # 词典种子幂等播种(首跑/新环境 boom_keyword 表空时补齐)
            self.repo.seed_keywords()
            keywords = [
                KeywordDef(k.category, k.keyword, k.weight)
                for k in self.repo.list_keywords(enabled_only=True)
            ]
            since = dt.datetime.combine(status.window_start, dt.time.min)

        # 正式报表窗(3/4/8/10 月整月,对齐披露季):单季净利大增但无预告
        # 的公司补充入池。一期可多报(4月=一季报+年报尾),逐报告期查询。
        formal_rows: list[dict] = []
        if formal and hasattr(self.forecast_repo, "get_quarter_yoy_growth"):
            for rd in formal_report_dates(today):
                try:
                    growth = self.forecast_repo.get_quarter_yoy_growth(
                        rd, self.config["min_change_pct"]
                    )
                except Exception as e:
                    log.warning("quarter yoy growth query failed (%s): %s", rd, e)
                    growth = []
                existing_syms = {f.symbol for f in pool}
                for g in growth:
                    if g["symbol"] in existing_syms:
                        continue
                    cand_rows.append({
                        "symbol": g["symbol"], "report_date": g["report_date"],
                        "forecast_type": "formal", "company_name": None,
                        "announce_date": None, "change_pct": g["yoy_pct"],
                        "forecast_type_label": "单季大增",
                        "categories": [], "keyword_count": 0, "news_hit_count": 0,
                    })
                    formal_rows.append(g["symbol"])

        for f in pool:
            prefixed = to_prefixed(f.symbol)
            existing = self.repo.get_candidate(f.symbol, f.report_date)
            # 已存在的候选默认视为已同步(缺 news_synced 标记时幂等跳过);
            # 真实行显式 news_synced=False 则重试同步。
            if existing is None or not getattr(existing, "news_synced", True):
                try:
                    self.news_sync.sync_stock_news(
                        prefixed, days_back=self.config["news_days_back"]
                    )
                    news_synced += 1
                    self.repo.mark_news_synced(f.symbol, f.report_date)
                except Exception as e:      # 单股失败不阻塞
                    log.warning("news sync %s failed: %s", f.symbol, e)

            hits: list[ScanHit] = []
            # 文本源1:预告 raw 原因文本
            ftext = raw_text(f)
            if ftext:
                hits += scan_text(ftext, keywords)
            hit_rows += [
                {"symbol": f.symbol, "source_type": "forecast",
                 "source_ref": f"{f.symbol}|{f.forecast_type}|{f.report_date}|{f.metric}",
                 "source_date": f.announce_date, "keyword": h.keyword,
                 "category": h.category, "snippet": h.snippet}
                for h in hits
            ]
            # 文本源2:个股新闻正文/标题
            try:
                articles = self.news_repo.find_by_symbol(
                    prefixed, days_back=self.config["news_days_back"] * 5, limit=50
                )
            except Exception:
                articles = []
            news_hits = 0
            for a in articles:
                if a.publish_time and a.publish_time < since:
                    continue
                text = f"{a.title}。{a.content}"
                a_hits = scan_text(text, keywords)
                news_hits += len(a_hits)
                hits += a_hits        # 新闻命中并入汇总,候选 categories 覆盖双源
                hit_rows += [
                    {"symbol": f.symbol, "source_type": "news",
                     "source_ref": getattr(a, "url", f"{prefixed}|{a.publish_time}"),
                     "source_date": a.publish_time.date() if a.publish_time else None,
                     "keyword": h.keyword, "category": h.category,
                     "snippet": h.snippet}
                    for h in a_hits
                ]
            # 文本源3:调研纪要(二期;provider 未注入则跳过)
            if self.survey_provider is not None:
                try:
                    surveys = self.survey_provider.fetch_survey(f.symbol)
                except Exception:
                    surveys = []
                for sv in surveys:
                    sv_date = sv.get("survey_date")
                    if sv_date is None or sv_date < since.date():
                        continue          # 早于当前窗口的调研纪要跳过
                    sv_hits = scan_text(sv.get("q_a_text", ""), keywords)
                    hit_rows += [
                        {"symbol": f.symbol, "source_type": "survey",
                         "source_ref": f"{f.symbol}|survey|{sv.get('survey_date')}",
                         "source_date": sv.get("survey_date"),
                         "keyword": h.keyword, "category": h.category,
                         "snippet": h.snippet}
                        for h in sv_hits
                    ]
                    news_hits += len(sv_hits)
            s = summarize(hits)
            cand_rows.append({
                "symbol": f.symbol, "report_date": f.report_date,
                "forecast_type": f.forecast_type,
                "company_name": f.company_name,
                "announce_date": f.announce_date, "change_pct": f.change_pct,
                "forecast_type_label": f.forecast_type_label,
                "categories": s["categories"], "keyword_count": s["keyword_count"],
                "news_hit_count": news_hits,
            })

        added = self.repo.upsert_hits(hit_rows) if hit_rows else 0
        self.repo.upsert_candidates(cand_rows) if cand_rows else None
        stats = {"in_season": status.in_season,
                 "next_window_start": status.next_window_start,
                 "pool": len(pool), "news_synced": news_synced, "hits": added,
                 "candidates": len(cand_rows), "formal_added": len(formal_rows)}
        if status.in_season:
            stats["window_name"] = status.window_name
            stats["report_date"] = status.report_date
        return stats


    async def llm_deep_read(self, report_date=None, limit=None) -> dict:
        """对候选池(有命中、未分析)跑 LLM 深读;失败降级不回写。"""
        limit = limit or self.config.get("llm_daily_limit", 30)
        rows = [r for r in self.repo.get_candidates(report_date=report_date)
                if r.keyword_count > 0 and r.llm_score is None]
        rows.sort(key=lambda r: r.keyword_count, reverse=True)
        rows = rows[:limit]
        analyzed = failed = 0
        for c in rows:
            hits = [
                {"keyword": h.keyword,
                 "category_label": CATEGORY_LABELS.get(h.category, h.category),
                 "source_type": h.source_type, "snippet": h.snippet}
                for h in filter_window_hits(
                    self.repo.get_hits(c.symbol, c.report_date), c.report_date)
            ]
            cand = {"symbol": c.symbol, "company_name": c.company_name,
                    "change_pct": c.change_pct,
                    "forecast_type_label": c.forecast_type_label}
            try:
                out = await analyze_candidate(cand, hits)
            except Exception as e:
                log.warning("llm deep read %s failed: %s", c.symbol, e)
                failed += 1
                continue
            if out["verdict"] == "parse_error":
                failed += 1
                continue
            self.repo.mark_llm(c.symbol, c.report_date, out["boom_score"],
                               out["verdict"], out["summary"])
            analyzed += 1
        return {"analyzed": analyzed, "failed": failed,
                "skipped": max(0, limit - len(rows))}


def build_default_service() -> BoomRadarService:
    from conf import app_config
    from src.domain.market.news.sync_service import NewsSyncService
    from src.domain.market.sync.providers.akshare_provider import AkshareProvider
    from src.infra.database.market.boom import create_boom_repository
    from src.infra.database.market.financial_full import (
        create_earnings_forecast_repository,
    )
    from src.infra.database.news_repository import create_news_repository

    cfg = app_config.boom_radar
    news_repo = create_news_repository()
    return BoomRadarService(
        repo=create_boom_repository(),
        forecast_repo=create_earnings_forecast_repository(),
        news_sync=NewsSyncService(AkshareProvider(), news_repo),
        news_repo=news_repo,
        survey_provider=AkshareProvider(),
        config={"min_change_pct": cfg.min_change_pct,
                "news_days_back": cfg.news_days_back,
                "llm_daily_limit": cfg.llm_daily_limit},
    )
