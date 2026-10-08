# backend/src/domain/market/sync/jobs/industry_fund_flow_sync.py
"""东财行业资金流每日落库 job(17:05,收盘后快照≈全天)。"""
import datetime as dt
import logging
import math

import akshare as ak

from src.infra.database.market.industry_analysis import (
    create_industry_analysis_repository,
)

log = logging.getLogger(__name__)


def _num(v):
    """NaN/inf → None:pandas NaN 是 truthy 非 None,float('nan') 落库 'NaN'
    非 NULL,会沿 flow20 传播致 score_flow 静默归零。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def parse_flow_df(df, trade_date: dt.date) -> list[dict]:
    """东财行业资金流 df → 落库行;列名容错「行业/名称」与「净额/主力净流入-净额」。

    NaN 行业名(str(NaN)="nan")整行跳过,防脏名落库。
    """
    rows: list[dict] = []
    for _, r in df.iterrows():
        name = str(r.get("行业") or r.get("名称") or "").strip()
        if not name or name.lower() == "nan":
            continue
        net = r.get("净额")
        if net is None:
            net = r.get("主力净流入-净额")
        rows.append({"trade_date": trade_date,
                     "em_industry_name": name,
                     "main_net_inflow": _num(net),
                     "close_change_pct": _num(r.get("涨跌幅"))})
    return rows


def run(trade_date: dt.date | None = None) -> dict:
    repo = create_industry_analysis_repository()
    d = trade_date or dt.date.today()
    # 周末接口返回的是上一交易日快照,按 today 落库会污染日期(2026-09-27
    # 实测: 周日快照被标成周日)。A 股无周末交易,直接跳过。
    if d.weekday() >= 5:
        log.info("[INDUSTRY_FLOW] skip non-trading day %s", d)
        return {"rows": 0, "skipped": str(d)}
    try:
        df = ak.stock_fund_flow_industry(symbol="即时")
    except Exception as e:  # noqa: BLE001
        log.error("[INDUSTRY_FLOW] akshare failed: %s", e)
        return {"rows": 0, "error": str(e)}
    rows = parse_flow_df(df, d)
    n = repo.upsert_fund_flow(rows)
    log.info("[INDUSTRY_FLOW] date=%s rows=%d", d, n)
    return {"rows": n}
