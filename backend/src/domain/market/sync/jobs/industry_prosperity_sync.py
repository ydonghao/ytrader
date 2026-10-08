# backend/src/domain/market/sync/jobs/industry_prosperity_sync.py
"""景气分每日重算 job(17:20):31 行业全量重算 upsert,inputs 快照随存。"""
import logging

from src.domain.market.industry_analysis.inputs import assemble_inputs
from src.domain.market.industry_analysis.prosperity import compute_prosperity
from src.infra.database.market.industry_analysis import (
    create_industry_analysis_repository,
)

log = logging.getLogger(__name__)


def run(trade_date=None) -> dict:
    repo = create_industry_analysis_repository()
    from conf import app_config
    cfg = app_config.industry_analysis
    as_of = trade_date or _latest_valuation_date(repo)
    if as_of is None:
        return {"rows": 0}
    inputs = assemble_inputs(repo, as_of,
                             pct_window_years=cfg.pct_window_years)
    from src.domain.market.industry_analysis.knowledge import load_knowledge
    know = load_knowledge()
    for code, x in inputs.items():          # 名字从知识层补
        x.name = know[code].name
    scores = compute_prosperity(inputs, weights=cfg.weights)
    rows = []
    for code, s in scores.items():
        rows.append({"trade_date": as_of, "sw_code": code, "score": s.score,
                     "score_profit": s.score_profit,
                     "score_valuation": s.score_valuation,
                     "score_momentum": s.score_momentum,
                     "score_flow": s.score_flow, "inputs": s.inputs})
    n = repo.upsert_prosperity(rows)
    log.info("[INDUSTRY_PROSPERITY] date=%s rows=%d", as_of, n)
    return {"date": str(as_of), "rows": n}


def _latest_valuation_date(repo):
    import datetime as dt
    today = dt.date.today()
    dates = repo.get_stock_valuation_dates(today - dt.timedelta(days=15),
                                           today)
    return dates[-1] if dates else None
