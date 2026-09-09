"""MacroGildataJob
=================
宏观经济数据 Gildata 补数同步（供调度器 / cron 调用）。

同步内容：
  1. Gildata（聚源）宏观指标 → macro_indicator 表（增量 upsert，幂等）。
     覆盖 akshare 已停更 / 从未覆盖的指标：社融总量与结构分项、
     新增贷款住户/企事业分项、失业率分年龄段（新口径）、
     居民可支配收入中位数同比、出生人口、对美进出口、CPI 分类、
     房地产开发投资增速、工业增加值当月同比、美国 ISM 制造业 PMI。
  2. 长历史指标（*_long）从标准指标复制缺口月份（同源同口径）。

口径约定：
  - 月度指标日期归一为月初（YYYY-MM-01），与既有 akshare/种子数据一致；
    季度保留季末日，年度归一为 YYYY-01-01。
  - 与 akshare 双源指标（社融分项/工业增加值/us_ism_pmi）只写
    比现有最新月份更新的行，避免覆盖 akshare 已有口径（发布日 vs 月初）。
  - 活期/定期存款占比（cn_deposit_*_ratio）Gildata 无月度分项数据，
    不在本任务覆盖范围（上游停更，暂保留历史）。

调用：
  python -m src.domain.market.sync.jobs.macro_gildata
"""
import logging
import sys
from datetime import date
from pathlib import Path

# 全局 socket 超时兜底，防止网关请求挂死
import socket
socket.setdefaulttimeout(120)

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent  # backend/
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync.providers.gildata_provider import (  # noqa: E402
    GildataProvider,
)
from src.infra.database.market.macro_indicator import (  # noqa: E402
    create_macro_indicator_repository,
)
from src.infra.database.sql_engine.engine import (  # noqa: E402
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn  # noqa: E402

log = logging.getLogger("macro_gildata")

# 长历史指标 ← 标准指标（复制缺口月份）
_LONG_FROM_STD = {
    "cn_cpi_yoy_long": "cn_cpi_yoy",
    "cn_ppi_yoy_long": "cn_ppi_yoy",
    "cn_pmi_long": "cn_pmi",
    "cn_m2_yoy_long": "cn_m2_yoy",
}


def _sync_gildata(prov: GildataProvider, repo) -> dict:
    """同步 Gildata 宏观指标 → macro_indicator（增量 upsert）。

    只写比现有最新月份更新的行：akshare 双源指标避免口径覆盖，
    纯 Gildata 指标等价于幂等增量（窗口内有修订也能追上）。
    """
    stats: dict[str, int] = {}
    for code in GildataProvider._MACRO_QUERIES:
        try:
            rows = prov.fetch_macro_series(code)
        except Exception as e:
            log.error(f"[gildata:{code}] 拉取失败: {e}")
            stats[code] = -1
            continue
        if not rows:
            log.warning(f"[gildata:{code}] 无数据")
            stats[code] = 0
            continue
        latest = repo.get_latest_date(code)
        latest_ym = (latest.year, latest.month) if latest else None
        src, src_url = prov.source_info(code)
        n = 0
        for report_date, value, freq, unit in rows:
            if latest_ym and (report_date.year, report_date.month) \
                    <= latest_ym:
                continue
            repo.upsert(
                indicator_code=code,
                report_date=report_date,
                value=round(value, 4),
                freq=freq,
                unit=unit,
                source=src,
                source_url=src_url,
                provider="gildata",
            )
            n += 1
        stats[code] = n
        log.info(f"[gildata:{code}] +{n} 行（最新 {rows[-1][0]}）")
    return stats


def _sync_long_history(repo) -> dict:
    """长历史指标（*_long）从标准指标复制缺口月份（含单位/来源）。"""
    import psycopg2

    stats: dict[str, int] = {}
    conn = psycopg2.connect(get_dsn())
    try:
        cur = conn.cursor()
        for long_code, std_code in _LONG_FROM_STD.items():
            max_d = repo.get_latest_date(long_code)
            cur.execute(
                "SELECT report_date, value, freq, unit, source, source_url "
                "FROM macro_indicator WHERE indicator_code=%s "
                "AND report_date > %s ORDER BY report_date",
                (std_code, max_d or date(1900, 1, 1)))
            rows = cur.fetchall()
            for d, v, freq, unit, src, src_url in rows:
                repo.upsert(
                    indicator_code=long_code,
                    report_date=d,
                    value=v,
                    freq=freq,
                    unit=unit,
                    source=src,
                    source_url=src_url or "",
                    provider="akshare",
                )
            stats[long_code] = len(rows)
            log.info(f"[long:{long_code}] +{len(rows)} 行（自 {std_code}）")
    finally:
        conn.close()
    return stats


def run() -> dict:
    prov = GildataProvider()
    db = create_db_connection(get_dsn())
    repo = create_macro_indicator_repository(db)

    results: dict = {}
    results["gildata"] = _sync_gildata(prov, repo)
    results["long_history"] = _sync_long_history(repo)

    total = sum(v for v in results["gildata"].values() if v > 0)
    total_long = sum(v for v in results["long_history"].values() if v > 0)
    log.info(f"macro_gildata 完成：gildata +{total}，长历史 +{total_long} 行")
    return results


def main():
    (_BACKEND / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(
                _BACKEND / "logs" / "macro_gildata.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    run()


if __name__ == "__main__":
    main()
