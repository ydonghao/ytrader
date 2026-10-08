"""
APScheduler 定时任务管理器。

任务：
  - 每日 16:05 (Asia/Shanghai) 刷新 market_stats + minute_stats 表
    （A 股收盘后，数据已稳定）
  - 每 5 分钟检查所有 active 价格告警（仅工作日 9:30-15:00）

启动/停止由 main.py lifespan 控制。
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

# ── 全局状态 ─────────────────────────────────────────────────────

_scheduler: AsyncIOScheduler | None = None
_last_run: datetime | None = None
_last_run_ok: bool = False
_last_error: str | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


def _build_refresh_job():
    """返回刷新 stats 的同步 job 函数。"""
    def _run():
        global _last_run, _last_run_ok, _last_error
        _last_run = datetime.now(timezone.utc)
        try:
            # 动态 import 避免循环引用
            from src.api.router.market_router import refresh_market_stats
            refresh_market_stats()
            _last_run_ok = True
            _last_error = None
        except Exception as exc:
            _last_run_ok = False
            _last_error = str(exc)

    return _run


def _import_and_run(module_path: str, func_name: str):
    """动态 import 并执行 job 函数（避免循环引用，供 add_job 使用）。"""
    import importlib
    mod = importlib.import_module(module_path)
    fn = getattr(mod, func_name)
    return fn()


def check_price_alerts():
    """
    检查所有 active alerts，根据最新价格触发符合条件的告警。
    供 APScheduler 定时调用，也可直接调用。
    """
    from collections import defaultdict

    from src.infra.database.alert.repository import create_alert_repository

    try:
        repo = create_alert_repository()
        active_alerts = repo.get_active_alerts()
    except Exception as e:
        log.error("[check_price_alerts] DB connection failed: %s", e)
        return

    if not active_alerts:
        log.debug("[check_price_alerts] no active alerts")
        return

    # 按 symbol 分组
    by_symbol: dict[str, list] = defaultdict(list)
    for alert in active_alerts:
        by_symbol[alert.symbol].append(alert)

    triggered_count = 0
    for symbol, alerts in by_symbol.items():
        # 获取最新收盘价
        current_price = repo.get_latest_price(symbol)
        if current_price is None:
            continue

        for alert in alerts:
            should_trigger = False
            if alert.direction == "above" and current_price >= alert.target_price:
                should_trigger = True
            elif alert.direction == "below" and current_price <= alert.target_price:
                should_trigger = True

            if should_trigger:
                repo.trigger_alert(alert.id)
                triggered_count += 1

                # Send Feishu notification
                try:
                    from src.infra.notification.feishu import send_alert_notification
                    send_alert_notification(
                        symbol=alert.symbol,
                        direction=alert.direction,
                        target_price=alert.target_price,
                        current_price=current_price,
                        message=alert.message,
                    )
                except Exception as notify_err:
                    log.error("[Feishu] notification failed: %s", notify_err)

                log.warning(
                    "[PRICE_ALERT_TRIGGERED] symbol=%s target=%.2f direction=%s current=%.2f",
                    symbol, alert.target_price, alert.direction, current_price,
                )

    if triggered_count:
        log.info("[check_price_alerts] triggered %d alert(s)", triggered_count)
    else:
        log.debug("[check_price_alerts] no alerts triggered")


def check_metric_alerts():
    """检查所有 active 指标告警（PE/PB/股息率/ROE 跨阈值）。

    供 APScheduler 定时调用，也可直接调用。
    指标值每日更新（估值日线 / 季报），故检查频率低于价格告警。
    """
    from src.infra.database.alert.repository import create_alert_repository
    try:
        repo = create_alert_repository()
    except Exception as e:
        log.error("[check_metric_alerts] DB connection failed: %s", e)
        return

    try:
        active = repo.get_active_metric_alerts()
    except Exception as e:
        log.error("[check_metric_alerts] query active failed: %s", e)
        return

    if not active:
        log.debug("[check_metric_alerts] no active metric alerts")
        return

    # 按 symbol 分组，每个 symbol 每种 metric 只查一次
    triggered_count = 0
    for alert in active:
        try:
            cur = repo.get_latest_metric_value(alert.symbol, alert.metric_kind)
        except Exception as e:
            log.warning("[check_metric_alerts] %s %s query failed: %s",
                        alert.symbol, alert.metric_kind, e)
            continue
        if cur is None:
            continue
        hit = False
        if alert.direction == "above" and cur >= alert.threshold:
            hit = True
        elif alert.direction == "below" and cur <= alert.threshold:
            hit = True
        if hit:
            try:
                repo.trigger_metric_alert(alert.id)
                triggered_count += 1
                log.warning(
                    "[METRIC_ALERT_TRIGGERED] %s %s %s %.2f cur=%.2f",
                    alert.symbol, alert.metric_kind, alert.direction,
                    alert.threshold, cur,
                )
            except Exception as e:
                log.error("[check_metric_alerts] trigger %s failed: %s",
                          alert.id, e)

    if triggered_count:
        log.info("[check_metric_alerts] triggered %d alert(s)", triggered_count)
    else:
        log.debug("[check_metric_alerts] no alerts triggered")


def setup_scheduler() -> AsyncIOScheduler:
    """注册所有定时任务并返回调度器实例。"""
    sched = get_scheduler()

    # ═══════════════════════════════════════════════════════
    # 暂时关闭: 每日市场统计刷新
    # sched.add_job(
    #     _build_refresh_job(),
    #     CronTrigger(hour=16, minute=5, timezone="Asia/Shanghai"),
    #     id="daily_stats_refresh",
    #     name="每日市场统计刷新",
    #     replace_existing=True,
    #     misfire_grace_time=3600,
    # )
    # ═══════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════
    # 暂时关闭: 价格告警检查
    # sched.add_job(
    #     check_price_alerts,
    #     CronTrigger(hour="9-14", minute="*/5", timezone="Asia/Shanghai"),
    #     id="alert_price_check",
    #     name="价格告警检查",
    #     replace_existing=True,
    #     misfire_grace_time=300,
    # )
    # # 也添加 15:00 的检查
    # sched.add_job(
    #     check_price_alerts,
    #     CronTrigger(hour=15, minute="0,5", timezone="Asia/Shanghai"),
    #     id="alert_price_check_15",
    #     name="价格告警检查-收盘",
    #     replace_existing=True,
    #     misfire_grace_time=300,
    # )
    # ═══════════════════════════════════════════════════════



    # ── 量化数据每日增量（工作日收盘后，按资产类拆 8 个独立 job）──────────────
    # 重构自单体 quant_daily_sync：原单 job 拉 1 万+ 标的、~20 分钟，任何重启/卡死
    # 都整体中断。现按资产类拆开，时间错开避免并发压力，单点失败互不影响，
    # max_instances=1 防重入。每个走 DB 驱动增量（incremental_from_db）。
    def _run_quant_split(job_id: str):
        from src.domain.market.sync.jobs.quant_daily import run_split
        try:
            run_split(job_id, incremental=True)
        except Exception as e:
            log.error("[QUANT/%s] failed: %s", job_id, e)

    # (job_id, 名称, 触发时间)——工作日错开 16:30~16:55
    _QUANT_SPLIT_SCHEDULE = [
        ("quant_a_daily",          "量化-A股日线增量",        dict(hour=16, minute=30)),
        ("quant_etf_daily",        "量化-ETF日线增量",        dict(hour=16, minute=35)),
        ("quant_hk_daily",         "量化-H股日线增量",        dict(hour=16, minute=40)),
        ("quant_index_daily",      "量化-大盘指数增量",       dict(hour=16, minute=45)),
        ("quant_sw_index_daily",   "量化-申万行业指数增量",   dict(hour=16, minute=46)),
        ("quant_commodity_metal",  "量化-贵金属增量",         dict(hour=16, minute=50)),
        ("quant_commodity_energy", "量化-原油增量",           dict(hour=16, minute=51)),
        ("quant_fx",               "量化-汇率增量",           dict(hour=16, minute=55)),
    ]
    for _job_id, _name, _cron in _QUANT_SPLIT_SCHEDULE:
        sched.add_job(
            lambda jid=_job_id: _run_quant_split(jid),
            CronTrigger(day_of_week="mon-fri", timezone="Asia/Shanghai", **_cron),
            id=_job_id,
            name=_name,
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
            coalesce=True,
        )

    # ── 国家队监控 ETF 每日份额快照（工作日 16:45 收盘后，累积成历史序列
    #    供「异常申赎信号」用；腾讯实时接口，幂等 upsert）─────────────────────
    def _run_nt_etf_shares():
        from src.domain.market.sync.jobs.nt_etf_shares_sync import run as _run
        try:
            _run()
        except Exception as e:
            log.error("[NT_ETF_SHARES] failed: %s", e)

    sched.add_job(
        _run_nt_etf_shares,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=45, timezone="Asia/Shanghai"),
        id="nt_etf_shares_daily",
        name="国家队ETF份额每日快照",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )

    # ── 量化数据周末兜底全量（每周六 03:30，近 14 天窗口幂等补缺口）──────────
    def _run_quant_weekly_catchup():
        from src.domain.market.sync.jobs.quant_daily import weekly_catchup
        try:
            weekly_catchup()
        except Exception as e:
            log.error("[QUANT_CATCHUP] failed: %s", e)

    sched.add_job(
        _run_quant_weekly_catchup,
        CronTrigger(day_of_week="sat", hour=3, minute=30, timezone="Asia/Shanghai"),
        id="quant_weekly_catchup",
        name="量化数据周末兜底全量",
        replace_existing=True,
        misfire_grace_time=7200,
        max_instances=1,
        coalesce=True,
    )

    # ── 基本面数据周同步（每周六 03:00 低峰，估值+财务）─────────────────────
    def _run_fundamentals_weekly():
        from src.domain.market.sync.jobs.fundamentals import run as _run
        try:
            _run(max_workers=6, rate_delay=0.2)
        except Exception as e:
            log.error("[FUNDAMENTALS_WEEKLY] failed: %s", e)
        # 东财快照偶发 TTM 口径脏点（PE 跳升不回落），同步后本地重算修正
        try:
            from src.domain.market.sync.jobs.valuation_guard import run as _guard
            _guard()
        except Exception as e:
            log.error("[VALUATION_GUARD] failed: %s", e)

    sched.add_job(
        _run_fundamentals_weekly,
        CronTrigger(day_of_week="sat", hour=3, minute=0, timezone="Asia/Shanghai"),
        id="fundamentals_weekly",
        name="基本面数据周同步",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # ── 市场情绪日同步（北向资金/两融/中国10Y国债，收盘后）─────────────────────
    def _run_market_sentiment_daily():
        from src.domain.market.sync.jobs.market_sentiment_sync import run as _run
        try:
            stats = _run(days=90)
            log.info("[MARKET_SENTIMENT_DAILY] %s", stats)
        except Exception as e:
            log.error("[MARKET_SENTIMENT_DAILY] failed: %s", e)

    sched.add_job(
        _run_market_sentiment_daily,
        CronTrigger(hour=17, minute=0, timezone="Asia/Shanghai"),
        id="market_sentiment_daily",
        name="市场情绪日同步(北向/两融/国债)",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # ── 股东户数周同步（筹码集中度，定期报告披露后才有新数据）─────────────────
    def _run_shareholder_count_weekly():
        from src.domain.market.sync.jobs.shareholder_count_sync import run as _run
        try:
            stats = _run(workers=6)
            log.info("[SHAREHOLDER_COUNT_WEEKLY] %s", stats)
        except Exception as e:
            log.error("[SHAREHOLDER_COUNT_WEEKLY] failed: %s", e)

    sched.add_job(
        _run_shareholder_count_weekly,
        CronTrigger(day_of_week="sun", hour=3, minute=30, timezone="Asia/Shanghai"),
        id="shareholder_count_weekly",
        name="股东户数周同步(筹码集中度)",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # ── 全球指数每日增量（道指/纳指/标普/恒生/国企 → index_ohlcv）──────────────
    # 全球指数原仅在周六 macro_sync 里同步，后端一旦连续数日停机即长期停更
    # （曾出现停在 7-02、20 天未更新的情况）。独立成每日 job，收盘后幂等补齐。
    def _run_global_indices_daily():
        from src.domain.market.sync.jobs.macro_sync import _sync_global_indices
        from src.domain.market.sync.providers.akshare_provider import AkshareProvider
        try:
            stats = _sync_global_indices(AkshareProvider())
            total = sum(v for v in stats.values() if v > 0)
            log.info("[GLOBAL_INDICES_DAILY] synced %d indices, +%d rows", len(stats), total)
        except Exception as e:
            log.error("[GLOBAL_INDICES_DAILY] failed: %s", e)

    sched.add_job(
        _run_global_indices_daily,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=58, timezone="Asia/Shanghai"),
        id="global_indices_daily",
        name="全球指数每日增量",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )

    # ── 宏观经济数据周同步（每周六 04:00，指标月度+全球指数幂等）─────────────
    def _run_macro_sync():
        from src.domain.market.sync.jobs.macro_sync import run as _run
        try:
            _run()
        except Exception as e:
            log.error("[MACRO_SYNC] failed: %s", e)

    sched.add_job(
        _run_macro_sync,
        CronTrigger(day_of_week="sat", hour=4, minute=0, timezone="Asia/Shanghai"),
        id="macro_sync",
        name="宏观经济数据周同步",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # ── 宏观判断快照（每周五 17:00 收盘后生成）──────────────────────────
    def _run_macro_snapshot():
        from src.domain.market.intel.macro.snapshot import generate_snapshot as _gen
        try:
            _gen()
        except Exception as e:
            log.error("[MACRO_SNAPSHOT] failed: %s", e)

    sched.add_job(
        _run_macro_snapshot,
        CronTrigger(day_of_week="fri", hour=17, minute=0, timezone="Asia/Shanghai"),
        id="macro_snapshot",
        name="宏观判断快照生成",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ── 宏观判断验证（每日 18:00 给到期快照打分）────────────────────────
    def _run_macro_validate():
        from src.domain.market.intel.macro.snapshot import validate_pending as _val
        try:
            _val()
        except Exception as e:
            log.error("[MACRO_VALIDATE] failed: %s", e)

    sched.add_job(
        _run_macro_validate,
        CronTrigger(hour=18, minute=0, timezone="Asia/Shanghai"),
        id="macro_validate",
        name="宏观判断验证打分",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ── 宏观经济数据月度同步（每月 1 日 04:30）──────────────────────────
    def _run_macro_monthly():
        from src.domain.market.sync.jobs.macro_monthly import run as _run
        try:
            _run()
        except Exception as e:
            log.error("[MACRO_MONTHLY] failed: %s", e)

    sched.add_job(
        _run_macro_monthly,
        CronTrigger(day=1, hour=4, minute=30,
                    timezone="Asia/Shanghai"),
        id="macro_monthly",
        name="宏观经济数据月度同步",
        replace_existing=True,
        misfire_grace_time=86400,
        max_instances=1,
        coalesce=True,
    )

    # ── 宏观 Gildata 补数（每月 12/18 日 05:20）────────────────────────
    # akshare 停更/未覆盖的宏观指标（社融分项、失业率分年龄、对美贸易、
    # ISM PMI 等）经 Gildata 聚源补齐。12 日覆盖 CPI/社融/贸易（9-13 日发布），
    # 18 日覆盖工业/固投/地产/失业率/季度收入（15 日前后发布）。
    def _run_macro_gildata():
        from src.domain.market.sync.jobs.macro_gildata import run as _run
        try:
            _run()
        except Exception as e:
            log.error("[MACRO_GILDATA] failed: %s", e)

    sched.add_job(
        _run_macro_gildata,
        CronTrigger(day="12,18", hour=5, minute=20,
                    timezone="Asia/Shanghai"),
        id="macro_gildata",
        name="宏观 Gildata 补数同步",
        replace_existing=True,
        misfire_grace_time=86400,
        max_instances=1,
        coalesce=True,
    )

    # ── 财务三大报表增量（每周六 05:00 起，A 股 → 港股 → 美股，增量）────────
    # 财报按季发布，90 天阈值跳过季内已同步的 symbol。
    # 排在 fundamentals(03:00) / macro(04:00) / macro_monthly(04:30) 之后。
    def _run_financial_full_weekly():
        from src.domain.market.sync.jobs.financial_full_sync import run as _run
        for mkt in ("A", "HK", "US"):
            try:
                _run(
                    markets=mkt,
                    statements="income,balance,cashflow,abstract" if mkt == "A" else "income",
                    earnings=False,       # 业绩由每日 job 单独处理
                    max_workers=6,
                    rate_delay=0.15,
                    # resume 必须 False：ProgressTracker 的 done 集合跨周持久化，
                    # 首轮跑完全部标 DONE 后，后续每周 pending 恒为空，季度新财报
                    # 永远不会被拉取（增量逻辑没机会执行）。增量跳过改由
                    # incremental 的 90 天 DB 新鲜度检查承担（每 symbol 一次
                    # DB 查询，无 API 调用）。
                    resume=False,
                    incremental=True,     # 增量：跳过近 90 天已同步的 symbol
                )
            except Exception as e:
                log.error("[FINANCIAL_FULL_WEEKLY/%s] failed: %s", mkt, e)

    sched.add_job(
        _run_financial_full_weekly,
        CronTrigger(day_of_week="sat", hour=5, minute=0, timezone="Asia/Shanghai"),
        id="financial_full_weekly",
        name="财务三大报表增量同步",
        replace_existing=True,
        misfire_grace_time=14400,   # 4小时容错（A+HK+US 合计）
        max_instances=1,
        coalesce=True,
    )

    # ── 申万行业成分股 + 行业截面（每周六 06:00，先成分后截面）─────────
    # 06:00 的原因：financial_full_weekly（05:00）是三大报表唯一写入方，
    # 先于它跑则截面永远聚合上周快照；04:00 又与 macro_sync 的分钟任务撞车。
    # 顺序：macro 04:00 → financial_full 05:00 → sw_industry 06:00。
    def _run_sw_industry_weekly():
        from src.domain.market.sync.jobs import (
            sw_industry_cross_section_sync,
            sw_industry_member_sync,
        )
        try:
            r1 = sw_industry_member_sync.run()
            log.info(
                "[SW_INDUSTRY_WEEKLY] members=%d industries=%d",
                r1.get("members", 0), r1.get("industries", 0),
            )
        except Exception as e:  # noqa: BLE001
            log.error("[SW_INDUSTRY_WEEKLY] member sync failed: %s", e)
        try:
            r2 = sw_industry_cross_section_sync.run()
            log.info("[SW_INDUSTRY_WEEKLY] sections=%d", r2.get("sections", 0))
        except Exception as e:  # noqa: BLE001
            log.error("[SW_INDUSTRY_WEEKLY] cross-section sync failed: %s", e)

    sched.add_job(
        _run_sw_industry_weekly,
        CronTrigger(day_of_week="sat", hour=6, minute=0,
                    timezone="Asia/Shanghai"),
        id="sw_industry_weekly",
        name="申万行业成分股与截面同步",
        replace_existing=True,
        misfire_grace_time=14400,
        max_instances=1,
        coalesce=True,
    )

    # ── 宽基指数成分/财务聚合/市值回填（每周六 06:30，先成分后下游）──────
    # 06:30 的原因：financial_full_weekly（05:00，三大表）与
    # fundamentals_weekly（03:00，估值）之后；单 job 链式执行保证
    # 成分 → 财务聚合 → 市值回填 的先后依赖（等价于规格的
    # 06:30/07:00/07:30 三连发，依赖顺序更强保证）。
    def _run_index_panorama_weekly():
        from src.domain.market.sync.jobs import (
            index_constituent_sync,
            index_financial_sync,
            index_market_cap_sync,
        )
        try:
            r1 = index_constituent_sync.run()
            log.info("[INDEX_PANORAMA_WEEKLY] constituents=%s", r1)
        except Exception as e:  # noqa: BLE001
            log.error("[INDEX_PANORAMA_WEEKLY] constituent sync failed: %s", e)
            return  # 成分失败，下游跳过
        try:
            r2 = index_financial_sync.sync_index_financial_quarterly()
            log.info("[INDEX_PANORAMA_WEEKLY] financial=%s", r2)
        except Exception as e:  # noqa: BLE001
            log.error("[INDEX_PANORAMA_WEEKLY] financial agg failed: %s", e)
        try:
            r3 = index_market_cap_sync.sync_index_market_cap()
            log.info("[INDEX_PANORAMA_WEEKLY] mv=%s", r3)
        except Exception as e:  # noqa: BLE001
            log.error("[INDEX_PANORAMA_WEEKLY] mv backfill failed: %s", e)

    sched.add_job(
        _run_index_panorama_weekly,
        CronTrigger(day_of_week="sat", hour=6, minute=30,
                    timezone="Asia/Shanghai"),
        id="index_panorama_weekly",
        name="宽基指数成分/财务聚合/市值回填",
        replace_existing=True,
        misfire_grace_time=14400,
        max_instances=1,
        coalesce=True,
    )

    # ── 业绩预告/快报增量（每日 17:00 收盘后）────────────────────────────
    # 财报季（1/4/7/10月）公告密集，每日拉最近 2 个报告期的预告/快报。
    # 幂等 upsert，非财报季拉到的是旧数据（无新行，秒完）。
    def _run_financial_earnings_daily():
        from src.domain.market.sync.jobs.financial_full_sync import run as _run
        try:
            _run(
                markets="A",
                statements="",         # 空=不拉三大表，只拉业绩
                earnings=True,
                max_workers=4,
                rate_delay=0.1,
                resume=False,
                incremental=True,     # 增量：只拉最近 2 个报告期
            )
        except Exception as e:
            log.error("[FINANCIAL_EARNINGS_DAILY] failed: %s", e)

    sched.add_job(
        _run_financial_earnings_daily,
        CronTrigger(hour=17, minute=0, timezone="Asia/Shanghai"),
        id="financial_earnings_daily",
        name="业绩预告/快报每日增量",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )

    # ── 财报季景气雷达(每日 17:30,预告 job 之后)─────────────────────────
    # 预告窗(1/4/7/10月)内:拉窗口内新披露预告 → 入池 → 新闻同步 → 词典扫描
    # → 候选/命中落库;非财报季秒完。幂等:整窗重扫,hit 唯一约束去重。
    def _run_boom_radar_daily():
        from src.domain.market.boom.service import build_default_service
        try:
            from conf import app_config
            if not app_config.boom_radar.enabled:
                return
            svc = build_default_service()
            stats = svc.run_daily()
            if stats.get("candidates"):
                import asyncio
                asyncio.run(svc.llm_deep_read())
        except Exception as e:
            log.error("[BOOM_RADAR_DAILY] failed: %s", e)

    sched.add_job(
        _run_boom_radar_daily,
        CronTrigger(hour=17, minute=30, timezone="Asia/Shanghai"),
        id="boom_radar_daily",
        name="财报季景气雷达每日扫描",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )

    # ── 持仓论点重估（每日 17:35，业绩同步 17:00 / boom 17:30 之后）────
    # active 论点：新财报(formal/express/preannounce)触发重估 +
    # 目标估值带到价检测；幂等（reeval 唯一约束 + band 事件去重）。
    def _run_thesis_reeval_daily():
        from src.domain.market.thesis.service import run_daily
        try:
            summary = run_daily()
            if summary.get("reevaluated") or summary.get(
                "band_alerts"
            ):
                log.info("[THESIS_DAILY] %s", summary)
        except Exception as e:
            log.error("[THESIS_DAILY] failed: %s", e)

    sched.add_job(
        _run_thesis_reeval_daily,
        CronTrigger(hour=17, minute=35, timezone="Asia/Shanghai"),
        id="thesis_reeval_daily",
        name="持仓论点每日重估",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )

    # ── 温度计日快照（每日 17:40，论点重估后）─────────────────────
    def _run_thermometer_daily():
        from src.domain.market.thesis.thermometer_service import (
            sync_thermometer_daily,
        )
        try:
            row = sync_thermometer_daily()
            if row:
                log.info("[THERMOMETER_DAILY] %s", row.get("level"))
        except Exception as e:
            log.error("[THERMOMETER_DAILY] failed: %s", e)

    sched.add_job(
        _run_thermometer_daily,
        CronTrigger(hour=17, minute=40, timezone="Asia/Shanghai"),
        id="thermometer_daily",
        name="全市场温度日快照",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )

    # ── 全市场排雷 Z 扫描（周六 06:00，financial_full_weekly 05:00 后）──
    # 批量 Altman Z（仅 z；M 需两期 detail 成本高不做全市场），
    # 幂等 upsert mine_screening_result。
    def _run_mine_market_scan():
        from src.domain.market.thesis.mine_sweep import scan_market
        try:
            summary = scan_market()
            log.info("[MINE_SCAN] %s", summary)
        except Exception as e:
            log.error("[MINE_SCAN] failed: %s", e)

    sched.add_job(
        _run_mine_market_scan,
        CronTrigger(
            day_of_week="sat", hour=6, minute=0,
            timezone="Asia/Shanghai",
        ),
        id="mine_market_scan",
        name="全市场排雷Z扫描(每周六)",
        replace_existing=True,
        misfire_grace_time=7200,
        max_instances=1,
        coalesce=True,
    )

    # ── 资本事件同步（周六 06:30，回购5s+增减持全量~90s）──────────────
    # akshare stock_repurchase_em + stock_ggcg(全部) → capital_event
    # 幂等 upsert（五元组唯一）。
    def _run_capital_event_sync():
        from src.domain.market.sync.providers.akshare_provider import (
            AkshareProvider,
        )
        from src.infra.database.portfolio.thesis_repository import (
            create_thesis_repository,
        )
        try:
            rows = AkshareProvider().fetch_capital_events()
            n = create_thesis_repository().upsert_capital_events(rows)
            log.info("[CAPITAL_EVENT_SYNC] upsert %s/%s", n, len(rows))
        except Exception as e:
            log.error("[CAPITAL_EVENT_SYNC] failed: %s", e)

    sched.add_job(
        _run_capital_event_sync,
        CronTrigger(
            day_of_week="sat", hour=6, minute=30,
            timezone="Asia/Shanghai",
        ),
        id="capital_event_sync",
        name="资本事件同步(回购+增减持,每周六)",
        replace_existing=True,
        misfire_grace_time=10800,
        max_instances=1,
        coalesce=True,
    )

    # ── 行业分析三件套(破净率16:40/资金流17:05/景气分17:20)────────────────
    def _run_industry_pb_break_daily():
        from src.domain.market.sync.jobs import industry_pb_break_sync
        try:
            from conf import app_config
            if not app_config.industry_analysis.enabled:
                return
            industry_pb_break_sync.run(days=2)
        except Exception as e:  # noqa: BLE001
            log.error("[INDUSTRY_PB_BREAK_DAILY] failed: %s", e)

    def _run_industry_fund_flow_daily():
        from src.domain.market.sync.jobs import industry_fund_flow_sync
        try:
            from conf import app_config
            if not app_config.industry_analysis.enabled:
                return
            industry_fund_flow_sync.run()
        except Exception as e:  # noqa: BLE001
            log.error("[INDUSTRY_FLOW_DAILY] failed: %s", e)

    def _run_industry_prosperity_daily():
        from src.domain.market.sync.jobs import industry_prosperity_sync
        try:
            from conf import app_config
            if not app_config.industry_analysis.enabled:
                return
            industry_prosperity_sync.run()
        except Exception as e:  # noqa: BLE001
            log.error("[INDUSTRY_PROSPERITY_DAILY] failed: %s", e)

    for _jid, _fn, _hm, _name in (
        ("industry_pb_break_daily", _run_industry_pb_break_daily,
         (16, 40), "行业破净率每日聚合"),
        ("industry_fund_flow_daily", _run_industry_fund_flow_daily,
         (17, 5), "行业资金流每日落库"),
        ("industry_prosperity_daily", _run_industry_prosperity_daily,
         (17, 20), "行业景气分每日重算"),
    ):
        sched.add_job(
            _fn,
            CronTrigger(hour=_hm[0], minute=_hm[1],
                        timezone="Asia/Shanghai"),
            id=_jid,
            name=_name,
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
            coalesce=True,
        )

    # ── 国家队持仓回填（每日凌晨2点，每次3个季度，全市场口径）──────────────
    def _run_national_team_backfill():
        import subprocess
        import sys as _sys
        from pathlib import Path as _Path
        try:
            backend_dir = _Path(__file__).parent.parent.parent  # backend/
            log.info("[NATIONAL_TEAM] backfill batch start (max-quarters=3)")
            result = subprocess.run(
                [_sys.executable, "-m",
                 "src.domain.market.sync.jobs.national_team_backfill",
                 "--max-quarters", "3"],
                cwd=str(backend_dir),
                capture_output=True, text=True, timeout=7200,
            )
            if result.returncode != 0:
                log.error("[NATIONAL_TEAM] backfill failed: %s",
                          result.stderr[-500:] if result.stderr else "no stderr")
            else:
                log.info("[NATIONAL_TEAM] backfill batch done")
        except subprocess.TimeoutExpired:
            log.warning("[NATIONAL_TEAM] backfill batch timed out at 7200s")
        except Exception as e:
            log.error("[NATIONAL_TEAM] backfill error: %s", e)

    sched.add_job(
        _run_national_team_backfill,
        CronTrigger(hour=2, minute=0, timezone="Asia/Shanghai"),
        id="national_team_backfill",
        name="国家队持仓回填-每日3季",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )

    # ── 每日申万一级行业估值落盘（P0b，工作日 16:10 收盘后）────────
    sched.add_job(
        lambda: _import_and_run(
            "src.domain.market.sync.jobs.index_valuation_sync",
            "sync_sw_index_valuation_daily",
        ),
        CronTrigger(
            hour=16, minute=10, day_of_week="mon-fri",
            timezone="Asia/Shanghai",
        ),
        id="sync_sw_index_valuation_daily",
        name="申万行业估值落盘-每日",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )

    # ── 日度化 computed sw 估值（数据治理 1.2，16:12）─────────────────
    def _run_sw_computed_daily():
        from src.domain.market.sync.jobs.index_valuation_sync import (
            compute_and_save_sw_computed,
        )
        try:
            compute_and_save_sw_computed()
        except Exception as e:
            log.error("[SW_COMPUTED_DAILY] failed: %s", e)

    sched.add_job(
        _run_sw_computed_daily,
        CronTrigger(hour=16, minute=12, day_of_week="mon-fri",
                    timezone="Asia/Shanghai"),
        id="sw_computed_daily",
        name="sw估值日度化computed",
        replace_existing=True,
        misfire_grace_time=10800,
        max_instances=1,
        coalesce=True,
    )

    # ── 指标告警检查（P1b，工作日 16:15 收盘+估值更新后）────────────
    sched.add_job(
        check_metric_alerts,
        CronTrigger(
            hour=16, minute=15, day_of_week="mon-fri",
            timezone="Asia/Shanghai",
        ),
        id="alert_metric_check",
        name="指标告警检查-每日",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
        coalesce=True,
    )

    # ── 投资周报（周日 20:00，四期P3；存研究笔记 __weekly__）────────
    def _run_weekly_report():
        from src.domain.market.thesis.weekly_report import (
            collect_and_save,
        )
        try:
            collect_and_save()
        except Exception as e:
            log.error("[WEEKLY_REPORT] failed: %s", e)

    sched.add_job(
        _run_weekly_report,
        CronTrigger(day_of_week="sun", hour=20, minute=0,
                    timezone="Asia/Shanghai"),
        id="weekly_report",
        name="投资周报生成",
        replace_existing=True,
        misfire_grace_time=10800,
        max_instances=1,
        coalesce=True,
    )

    # ── 数据健康体检（每日 18:30，所有写入 job 之后）──────────────────
    def _run_data_health_daily():
        from src.domain.market.health.runner import run_daily
        try:
            run_daily()
        except Exception as e:
            log.error("[DATA_HEALTH_DAILY] failed: %s", e)
        # 阶段三自愈(默认干跑,只建议+审计;一周无误报后
        # 设 YTRADER_HEAL_DRYRUN=0 开真回补)
        try:
            from src.domain.market.health.heal import run_heal
            run_heal()
        except Exception as e:
            log.error("[DATA_HEAL] failed: %s", e)

    sched.add_job(
        _run_data_health_daily,
        CronTrigger(hour=18, minute=30, timezone="Asia/Shanghai"),
        id="data_health_daily",
        name="数据健康体检",
        replace_existing=True,
        misfire_grace_time=7200,
        max_instances=1,
        coalesce=True,
    )

    # ── 数据治理阶段二: job 执行留痕(事件监听,不侵入各 job) ──────────
    from apscheduler.events import (
        EVENT_JOB_ERROR,
        EVENT_JOB_EXECUTED,
    )

    def _on_job_event(event):
        from src.infra.database.market.job_run_log import (
            create_job_run_log_repository,
        )
        try:
            status = "error" if event.code == EVENT_JOB_ERROR else "success"
            err = None
            if status == "error" and getattr(event, "exception", None):
                err = f"{type(event.exception).__name__}: {event.exception}"
            create_job_run_log_repository().add(
                job_id=event.job_id, status=status,
                error_summary=err,
                scheduled_at=getattr(event, "scheduled_run_time", None),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("[JOB_RUN_LOG] 写入失败: %s", e)

    sched.add_listener(_on_job_event,
                       EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    return sched


def get_status() -> dict:
    """返回调度器当前状态（供 /system/scheduler API 使用）。"""
    sched = get_scheduler()
    jobs = []
    for job in sched.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
            "trigger": str(job.trigger),
        })

    return {
        "running": sched.running,
        "jobs": jobs,
        "last_run": str(_last_run) if _last_run else None,
        "last_run_ok": _last_run_ok,
        "last_error": _last_error,
    }
