"""一次性历史回填：宏观指标 30 年数据 → macro_indicator 表。

背景：页面上多个宏观指标历史不足（部分仅到 2020/2016/2008），
本脚本把可补的指标回填到约 1995/1996 年（或数据源极限）：

  - CN 指标：经 GildataProvider.fetch_macro_series(code, lookback_months=360)
    一次拉 30 年，逐条 repo.upsert（按 code+report_date 幂等，
    重叠月份为同源同口径数据，覆盖无害且可修补缺口）。
  - US 指标：经 igo_open_data 插件 fred_query 预拉 CSV
    （data/macro_backfill/*.csv），读入后 upsert。
    us_cpi_yoy 用 CPIAUCSL + units=pc1（官方同比换算）。

源极限不可补（本次不动）：cn_sf*（2015 起）、cn_sf_govbond（2017）、
cn_unemp_1624/2529（2023.12 新口径）、cn_lpr_1y（2013 才发布）、
cn_pmi（2005 才有）、cn_deposit_*（上游停更在 2025-05）。

用法（backend/ 目录下）：
  .venv/bin/python scripts/macro_backfill_30y.py            # 全部
  .venv/bin/python scripts/macro_backfill_30y.py --us       # 仅美国
  .venv/bin/python scripts/macro_backfill_30y.py cn_cpi_yoy cn_m2_yoy
"""
import csv
import sys
from datetime import date
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync.providers.gildata_provider import (  # noqa: E402
    GildataProvider,
)
from src.infra.database.market.macro_indicator import (  # noqa: E402
    create_macro_indicator_repository,
)
from src.infra.database.sql_engine.engine import create_db_connection  # noqa: E402
from src.infra.database.sql_engine.dsn import get_dsn  # noqa: E402

LOOKBACK = 360  # 30 年

# CN：13 个有缺口的指标（含 7 个新注册 + 6 个已注册）
CN_CODES = [
    "cn_cpi_yoy", "cn_ppi_yoy", "cn_m1_yoy", "cn_m2_yoy",
    "cn_retail_yoy", "cn_fai_yoy", "cn_industrial_profit_yoy",
    "cn_cpi_food", "cn_cpi_consumer", "cn_realestate_inv_yoy",
    "cn_trade_us_amt", "cn_loan_household", "cn_loan_enterprise",
    "cn_disp_income_median_yoy",
]

# US：code → (CSV 文件, FRED series, source 名称, source_url, unit)
_DATA_DIR = _BACKEND / "data" / "macro_backfill"
US_CODES = {
    "us_cap_util": (
        "us_cap_util.csv", "CUMFNS",
        "美联储(FED)", "https://fred.stlouisfed.org/series/CUMFNS", "%"),
    "us_nfp": (
        "us_nfp.csv", "PAYEMS",
        "美国劳工统计局(BLS)", "https://fred.stlouisfed.org/series/PAYEMS",
        "千人"),
    "us_cpi_yoy": (
        "us_cpi_yoy.csv", "CPIAUCSL(pc1)",
        "美国劳工统计局(BLS)", "https://fred.stlouisfed.org/series/CPIAUCSL",
        "%"),
}


def _coverage(repo, code: str) -> str:
    import psycopg2
    conn = psycopg2.connect(get_dsn())
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT min(report_date), max(report_date), count(*) "
            "FROM macro_indicator WHERE indicator_code=%s", (code,))
        lo, hi, n = cur.fetchone()
        return f"{lo} ~ {hi} ({n} 行)" if n else "(空)"
    finally:
        conn.close()


def backfill_cn(prov: GildataProvider, repo, codes: list[str]) -> None:
    for code in codes:
        before = _coverage(repo, code)
        try:
            rows = prov.fetch_macro_series(code, lookback_months=LOOKBACK)
        except Exception as e:
            print(f"[CN {code}] 拉取异常: {e}", flush=True)
            continue
        if not rows:
            print(f"[CN {code}] 无数据  before={before}", flush=True)
            continue
        src, src_url = prov.source_info(code)
        for report_date, value, freq, unit in rows:
            repo.upsert(
                indicator_code=code, report_date=report_date,
                value=round(value, 4), freq=freq, unit=unit,
                source=src, source_url=src_url, provider="gildata",
            )
        after = _coverage(repo, code)
        print(f"[CN {code}] +{len(rows)} 行  {before}  →  {after}",
              flush=True)


def backfill_us(repo) -> None:
    for code, (fname, series, src, src_url, unit) in US_CODES.items():
        path = _DATA_DIR / fname
        if not path.is_file():
            print(f"[US {code}] 缺 CSV: {path}（先经 igo fred_query 拉取）",
                  flush=True)
            continue
        before = _coverage(repo, code)
        n = 0
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    d = date.fromisoformat(row["date"])
                    v = float(row["value"])
                except (KeyError, ValueError):
                    continue
                repo.upsert(
                    indicator_code=code, report_date=d, value=round(v, 4),
                    freq="month", unit=unit, source=src, source_url=src_url,
                    provider="fred",
                )
                n += 1
        after = _coverage(repo, code)
        print(f"[US {code}] {series} +{n} 行  {before}  →  {after}",
              flush=True)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    us_only = "--us" in sys.argv

    db = create_db_connection(get_dsn())
    repo = create_macro_indicator_repository(db)

    if not us_only:
        prov = GildataProvider()
        codes = args if args else CN_CODES
        backfill_cn(prov, repo, codes)
    if us_only or not args:
        backfill_us(repo)
    print("完成。", flush=True)


if __name__ == "__main__":
    main()
