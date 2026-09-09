"""MacroMonthlyJob
================
宏观经济数据月度同步（供调度器 / cron 调用）。

同步内容：
  1. akshare 指标（A/B 档）：遍历 config 中 provider=akshare 的 code，
     走 AkshareProvider.fetch_macro_series / fetch_macro_derived。
  2. CSV 种子（C 档）：provider=csv_seed 的 code，从 scripts/seed/macro/
     全量读 CSV 导入（幂等：按 (code, report_date) 主键 upsert）。
  3. 元数据刷新：全量写 macro_indicator_meta（与 macro_sync 同逻辑）。

调用：
  python -m src.domain.market.sync.jobs.macro_monthly
"""
import csv
import logging
import sys
from datetime import datetime
from pathlib import Path

import socket
socket.setdefaulttimeout(60)

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from conf import app_config  # noqa: E402
from src.domain.market.sync.providers.akshare_provider import (  # noqa: E402
    AkshareProvider,
)
from src.infra.database.market.macro_indicator import (  # noqa: E402
    create_macro_indicator_repository,
)
from src.infra.database.sql_engine.engine import (  # noqa: E402
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn  # noqa: E402

log = logging.getLogger("macro_monthly")

_SEED_DIR = _BACKEND / "scripts" / "seed" / "macro"

# code → (csv 文件名, [code 列表], unit, freq, source, source_url)
# 列表长度 = CSV 的 value 列数
_CSV_SEED_MAP = {
    "cn_unemp_1624": (
        "cn_unemp.csv",
        ["cn_unemp_1624", "cn_unemp_2529"],
        "%", "month", "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/"),
    "cn_disp_income_median_yoy": (
        "cn_disp_income.csv",
        ["cn_disp_income_median_yoy"],
        "%", "quarter", "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/"),
    "cn_birth": (
        "cn_birth.csv",
        ["cn_birth"],
        "万人", "year", "国家统计局",
        "https://www.stats.gov.cn/sj/zxdb/"),
    "cn_industrial_profit_yoy": (
        "cn_industrial_profit.csv",
        ["cn_industrial_profit_yoy"],
        "%", "month", "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/"),
    "cn_trade_us_amt": (
        "cn_trade_us.csv",
        ["cn_trade_us_amt"],
        "亿美元", "month", "海关总署",
        "https://www.customs.gov.cn/"),
    "cn_cpi_food": (
        "cn_cpi_classified.csv",
        ["cn_cpi_food", "cn_cpi_consumer"],
        "%", "month", "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/"),
    "cn_sf_govbond": (
        "cn_sf_govbond.csv",
        ["cn_sf_govbond"],
        "亿元", "month", "中国人民银行",
        "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"),
    "cn_loan_household": (
        "cn_loan_split.csv",
        ["cn_loan_household", "cn_loan_enterprise"],
        "亿元", "month", "中国人民银行",
        "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"),
    "cn_fai_yoy": (
        "cn_fai.csv",
        ["cn_fai_yoy", "cn_realestate_inv_yoy"],
        "%", "month", "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/"),
}

# 派生指标 code 列表（走 fetch_macro_derived）
_DERIVED_CODES = ["cn_deposit_demand_ratio", "cn_deposit_term_ratio"]


def _seed_from_csv(
    repo, csv_path: Path, codes: list, unit: str, freq: str,
    source: str, source_url: str, provider: str = "csv_seed",
) -> int:
    """从 CSV 导入历史时序种子。

    CSV 格式：report_date,value 或 report_date,value1,value2,...
    codes 长度须等于 value 列数。返回写入条数。
    文件不存在返回 0。幂等：按 (code, date) 主键 upsert。
    """
    if not csv_path.exists():
        log.warning(f"[csv_seed] 文件不存在: {csv_path}")
        return 0
    n = 0
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            report_date_s = (row.get("report_date") or "").strip()
            if not report_date_s:
                continue
            try:
                report_date = datetime.strptime(
                    report_date_s[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            for i, code in enumerate(codes):
                key = f"value{i + 1}" if len(codes) > 1 else "value"
                raw = row.get(key)
                if raw is None or raw.strip() == "":
                    continue
                try:
                    value = float(raw)
                except (ValueError, TypeError):
                    continue
                repo.upsert(
                    indicator_code=code,
                    report_date=report_date,
                    value=value,
                    freq=freq,
                    unit=unit,
                    source=source,
                    source_url=source_url,
                    provider=provider,
                )
                n += 1
    return n


def _sync_akshare(prov: AkshareProvider, repo) -> dict:
    """同步 akshare 指标（provider=akshare 且在 _MACRO_EXTRACTORS）。

    跳过 csv_seed 指标和派生指标（分别由 _sync_csv_seed /
    _sync_derived 处理）。
    """
    stats: dict[str, int] = {}
    for cfg in app_config.macro_universe.indicators:
        if cfg.provider not in ("akshare", "fred"):
            continue
        if cfg.code in _DERIVED_CODES:
            continue
        try:
            rows = prov.fetch_macro_series(cfg.code)
        except Exception as e:
            log.error(f"[akshare:{cfg.code}] 拉取失败: {e}")
            stats[cfg.code] = -1
            continue
        if not rows:
            log.warning(f"[akshare:{cfg.code}] 无数据")
            stats[cfg.code] = 0
            continue
        for report_date, value, freq, unit in rows:
            repo.upsert(
                indicator_code=cfg.code,
                report_date=report_date,
                value=value,
                freq=cfg.freq or freq,
                unit=cfg.unit or unit,
                source=cfg.source or "akshare",
                source_url=cfg.source_url or "",
                provider="akshare",
            )
        stats[cfg.code] = len(rows)
        log.info(f"[akshare:{cfg.code}] +{len(rows)} 行")
    return stats


def _sync_derived(prov: AkshareProvider, repo) -> dict:
    """同步派生指标（存款占比等）。"""
    stats: dict[str, int] = {}
    for code in _DERIVED_CODES:
        try:
            rows = prov.fetch_macro_derived(code)
        except Exception as e:
            log.error(f"[derived:{code}] 计算失败: {e}")
            stats[code] = -1
            continue
        if not rows:
            stats[code] = 0
            continue
        for report_date, value, freq, unit in rows:
            repo.upsert(
                indicator_code=code,
                report_date=report_date,
                value=value,
                freq=freq,
                unit=unit,
                source="中国人民银行",
                source_url="https://www.pbc.gov.cn/",
                provider="akshare",
            )
        stats[code] = len(rows)
        log.info(f"[derived:{code}] +{len(rows)} 行")
    return stats


def _sync_csv_seed(repo) -> dict:
    """同步 CSV 种子指标。"""
    stats: dict[str, int] = {}
    # 去重：同一 CSV 文件只导入一次（多个 code 映射到同一文件）
    seen_files: set[str] = set()
    for code, (fname, codes, unit, freq, source, source_url) in (
        _CSV_SEED_MAP.items()
    ):
        if fname in seen_files:
            continue
        seen_files.add(fname)
        csv_path = _SEED_DIR / fname
        n = _seed_from_csv(
            repo, csv_path, codes, unit, freq, source, source_url)
        for c in codes:
            stats[c] = n // max(len(codes), 1)
        log.info(f"[csv_seed:{fname}] +{n} 行（codes={codes}）")
    return stats


def _sync_indicator_meta(repo) -> int:
    """刷新指标元数据（与 macro_sync 同逻辑）。"""
    for i, cfg in enumerate(app_config.macro_universe.indicators):
        repo.upsert_meta({
            "code": cfg.code,
            "name": cfg.name,
            "unit": cfg.unit,
            "freq": cfg.freq,
            "category": cfg.category,
            "group": cfg.group,
            "provider": cfg.provider,
            "threshold_high": cfg.threshold_high,
            "threshold_low": cfg.threshold_low,
            "direction": cfg.direction,
            "sort_order": i,
            "description": cfg.description,
            "explanation": cfg.explanation,
            "doc_url": cfg.doc_url,
            "range_low": cfg.range_low,
            "range_high": cfg.range_high,
            "reference_lines": cfg.reference_lines or [],
        })
    log.info(f"[meta] 刷新 {len(app_config.macro_universe.indicators)} 条")
    return len(app_config.macro_universe.indicators)


def run() -> dict:
    """执行月度同步。返回各阶段统计。"""
    prov = AkshareProvider()
    db = create_db_connection(get_dsn())
    repo = create_macro_indicator_repository(db)

    results: dict = {}
    results["akshare"] = _sync_akshare(prov, repo)
    results["derived"] = _sync_derived(prov, repo)
    results["csv_seed"] = _sync_csv_seed(repo)
    results["meta"] = _sync_indicator_meta(repo)

    total_ak = sum(
        v for v in results["akshare"].values() if v > 0)
    total_dv = sum(
        v for v in results["derived"].values() if v > 0)
    total_csv = sum(
        v for v in results["csv_seed"].values() if v > 0)
    log.info(
        f"macro_monthly 完成：akshare +{total_ak}，"
        f"derived +{total_dv}，csv_seed +{total_csv} 行")
    return results


def main():
    (_BACKEND / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(
                _BACKEND / "logs" / "macro_monthly.log",
                encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    run()


if __name__ == "__main__":
    main()
