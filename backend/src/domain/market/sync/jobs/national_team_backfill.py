"""
NationalTeamBackfillJob — 全市场季报持仓回填(东方财富接口)。

每季度一次拉全市场前十大流通股东(~60000行),过滤国家队后落库。
2015→最新已披露季度,约46季,单季2-3分钟,全量约1.5-2小时。

用法:
  # 全量回填(不限季度)
  python -m src.domain.market.sync.jobs.national_team_backfill --max-quarters 0
  # 每次跑3季(定时任务)
  python -m src.domain.market.sync.jobs.national_team_backfill --max-quarters 3
"""
import argparse
import json
import logging
import socket
import sys
import datetime as dt
from pathlib import Path

socket.setdefaulttimeout(60)

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync.providers.akshare_provider import AkshareProvider  # noqa: E402
from src.domain.market.sync.providers.national_team_config import (  # noqa: E402
    match_holder_category, get_backfill_from,
)
from src.infra.database.market.national_team_holding import (  # noqa: E402
    create_national_team_repository,
)

log = logging.getLogger("national_team_backfill")
_PROGRESS = _BACKEND / "conf" / ".national_team_backfill_quarters.json"


def _quarter_end_dates(from_year: int) -> list[str]:
    """从 from_year 各季度末到当前最近已披露季度的报告期(YYYYMMDD)。"""
    today = dt.date.today()
    out = []
    y, q = from_year, 1
    while True:
        md = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}[q]
        d = dt.date.fromisoformat(f"{y}-{md[:2]}-{md[2:]}")
        if d > today:
            break
        out.append(f"{y}{md}")
        q += 1
        if q > 4:
            q, y = 1, y + 1
    return out


def _load_done() -> set:
    if _PROGRESS.exists():
        try:
            return set(json.loads(_PROGRESS.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def _save_done(done: set) -> None:
    _PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    _PROGRESS.write_text(json.dumps(sorted(done)), encoding="utf-8")


def run_market(max_quarters: int = 0, reset: bool = False) -> dict:
    """按季度循环,全市场回填。
    max_quarters: 本轮最多跑几个季度(0=不限)。
    """
    from_year = int(get_backfill_from()[:4])
    quarters = _quarter_end_dates(from_year)
    # 只回填已过披露截止的季度：一季报4/30、中报8/31、三季报10/31、年报次年4/30。
    # （原实现统一用 120 天缓冲，中报要拖到 10 月底、一季报拖到 7 月底才回填，
    #   错过披露后的时效窗口。）
    today = dt.date.today()

    def _disclosed(q: str) -> bool:
        y, md = int(q[:4]), q[4:]
        yy = y + 1 if md == "1231" else y
        mm, dd = {"0331": (4, 30), "0630": (8, 31),
                  "0930": (10, 31), "1231": (4, 30)}[md]
        return dt.date(yy, mm, dd) <= today

    quarters = [q for q in quarters if _disclosed(q)]
    log.info(f"待回填: {len(quarters)} 个已披露季度 (2015→{quarters[-1] if quarters else '-'})")

    done = set() if reset else _load_done()
    todo = [q for q in quarters if q not in done]
    todo.sort()  # 升序,旧→新

    repo = create_national_team_repository()
    provider = AkshareProvider()
    processed = matched_total = written_total = 0

    for q in todo:
        if max_quarters and processed >= max_quarters:
            log.info(f"达到本轮上限 {max_quarters} 季, 暂停。")
            break
        report_date = dt.date.fromisoformat(f"{q[:4]}-{q[4:6]}-{q[6:8]}")
        try:
            all_holders = provider.fetch_market_holders_by_quarter(q)
            rows = []
            for h in all_holders:
                if not h.get("holder_name"):
                    continue
                cat = match_holder_category(h["holder_name"])
                if not cat:
                    continue
                rows.append({
                    "report_date": report_date,
                    "holder_name": h["holder_name"],
                    "holder_category": cat,
                    "symbol": h["symbol"],
                    "company_name": h.get("company_name", ""),
                    "hold_shares": int(h.get("hold_shares") or 0),
                    "hold_value": float(h.get("hold_value") or 0),
                    "pct_of_float": float(h.get("pct_of_float") or 0),
                    "ranking": int(h.get("ranking") or 0),
                })
            if rows:
                repo.bulk_upsert(rows)
            done.add(q)
            _save_done(done)
            processed += 1
            matched_total += len(rows)
            written_total += len(rows)
            log.info(f"[{q}] 全市场{len(all_holders)}行 → 国家队{len(rows)}条入库 (累计{written_total}条, {processed}/{len(todo)}季)")
        except Exception as e:
            log.warning(f"[{q}] 失败: {e}")
            # 失败不标记done,下轮重试

    remaining = len(todo) - processed
    summary = {"quarters_processed": processed, "rows_written": written_total, "remaining": remaining}
    log.info(f"=== 本轮完成: {summary} ===")
    return summary


def main():
    parser = argparse.ArgumentParser(description="国家队全市场季报持仓回填")
    parser.add_argument("--max-quarters", type=int, default=0,
                        help="本轮最多跑几季(0=不限)")
    parser.add_argument("--reset", action="store_true",
                        help="忽略进度,从头开始")
    args = parser.parse_args()
    (_BACKEND / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(_BACKEND / "logs" / "national_team_backfill.log",
                                encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    run_market(max_quarters=args.max_quarters, reset=args.reset)


if __name__ == "__main__":
    main()
