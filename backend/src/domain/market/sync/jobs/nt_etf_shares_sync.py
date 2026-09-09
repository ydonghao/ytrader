"""国家队监控 ETF 每日份额快照同步。

每个交易日抓一次 12 只核心宽基 ETF 的「当日份额/规模」(腾讯实时),
落 national_team_etf_shares,累积成历史序列,供「异常申赎信号」用。

定时:每个交易日 16:40(收盘后,份额已更新)。
手动:python -m src.domain.market.sync.jobs.nt_etf_shares_sync
"""
import datetime as dt
import logging
import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

log = logging.getLogger("nt_etf_shares_sync")


def run() -> dict:
    from src.domain.market.sync.providers.national_team_config import get_etf_first_holders
    from src.domain.market.sync.providers.tencent_quote import fetch_etf_quotes
    from src.infra.database.market.national_team_etf_shares import (
        create_etf_shares_repository,
    )

    etfs = get_etf_first_holders()
    if not etfs:
        return {"written": 0, "reason": "no etf config"}
    codes = [e["code"] for e in etfs]
    quotes = fetch_etf_quotes(codes)
    today = dt.date.today()
    repo = create_etf_shares_repository()
    written = 0
    for e in etfs:
        q = quotes.get(e["code"])
        if not q:
            continue
        repo.upsert({
            "trade_date": today,
            "etf_code": e["code"],
            "etf_name": q.get("name") or e["name"],
            "shares": int(q.get("shares") or 0),
            "price": float(q.get("price") or 0),
            "total_value_yi": float(q.get("total_value_yi") or 0),
        })
        written += 1
    log.info("[NT_ETF_SHARES] %s 写入 %d/%d 只 ETF 份额快照", today, written, len(codes))
    return {"written": written, "date": today.isoformat()}


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    print(run())


if __name__ == "__main__":
    main()
