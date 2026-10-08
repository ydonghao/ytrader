"""排雷扫描服务（第5期）：持仓三源精查 + 全市场 Z 扫描。

IO 全部经模块级函数（_z/_m/_fraud/_repo/_snapshots），便于 mock。
check_positions 由 run_daily 末尾延迟调用（防 import 环）。
"""
import logging
from datetime import date
from typing import Optional

from src.api.handler.financial_detail_handler import (
    fraud_signals_report,
    m_score_report,
    z_score_report,
)
from src.domain.market.fundamental.classic_models import altman_z_score
from src.domain.market.fundamental.mine_sweep import assess_mine
from src.domain.market.thesis.service import _data, _repo

log = logging.getLogger(__name__)


def _z(symbol: str) -> dict:
    return _data(z_score_report(symbol)) or {}


def _m(symbol: str) -> dict:
    return _data(m_score_report(symbol)) or {}


def _fraud(symbol: str) -> dict:
    return _data(fraud_signals_report(symbol)) or {}


def _snapshots(symbols: list) -> dict:
    from src.domain.market.strategy.longterm.data_loader import (
        fetch_financial_snapshot,
    )
    return fetch_financial_snapshot(symbols, include_detail=False)


def check_positions() -> dict:
    """active 论点三源精查；高危落 mine_detected 事件（按财报期去重）。"""
    repo = _repo()
    theses = repo.list_theses(status="active")
    summary = {"checked": 0, "high": 0, "medium": 0, "events": 0}
    for t in theses:
        sym = t["symbol"]
        try:
            z, m, f = _z(sym), _m(sym), _fraud(sym)
            periods = f.get("periods") or []
            report_date = (
                z.get("report_date")
                or (periods[-1] if periods else None)
                or date.today().isoformat()
            )
            assess = assess_mine(
                z.get("verdict"), m.get("verdict"), f.get("severity"),
            )
            fraud_flags = [
                fl.get("name") or fl.get("reason") or str(fl)
                for fl in (f.get("red_flags") or [])
            ]
            repo.upsert_mine_results([{
                "symbol": sym, "report_date": report_date,
                "z": z.get("z"), "z_verdict": z.get("verdict"),
                "m": m.get("m"), "m_verdict": m.get("verdict"),
                "m_partial": m.get("partial"),
                "fraud_severity": f.get("severity"),
                "fraud_flags": fraud_flags,
                "risk_level": assess["risk_level"],
                "source": "positions",
            }])
            summary["checked"] += 1
            if assess["risk_level"] == "high":
                summary["high"] += 1
                if not repo.has_event_detail(
                    t["id"], "mine_detected", "report_date",
                    report_date,
                ):
                    repo.add_event(
                        t["id"], "mine_detected",
                        {"risk": "high",
                         "report_date": report_date,
                         "reasons": assess["reasons"]},
                    )
                    summary["events"] += 1
            elif assess["risk_level"] == "medium":
                summary["medium"] += 1
        except Exception as e:
            log.error("[MINE_CHECK] %s 失败: %s", sym, e)
    return summary


def scan_market() -> dict:
    """全市场 Altman Z 扫描（周六批量；仅 z，M 成本高不做全市场）。"""
    repo = _repo()
    symbols = repo.all_financial_symbols()
    summary = {"scanned": 0, "distress": 0, "grey": 0}
    if not symbols:
        return summary
    caps = repo.latest_market_caps(symbols)
    snaps = _snapshots(symbols)
    rows = []
    for sym, snap in snaps.items():
        z = altman_z_score(snap, market_cap=caps.get(sym))
        if z is None:
            continue
        rd = snap.get("report_date") or date.today()
        level = ("high" if z.verdict == "distress"
                 else "medium" if z.verdict == "grey" else "clean")
        rows.append({
            "symbol": sym, "report_date": rd,
            "z": round(z.z, 3), "z_verdict": z.verdict,
            "risk_level": level, "source": "market",
        })
        summary["scanned"] += 1
        if z.verdict == "distress":
            summary["distress"] += 1
        elif z.verdict == "grey":
            summary["grey"] += 1
    if rows:
        for i in range(0, len(rows), 500):
            repo.upsert_mine_results(rows[i:i + 500])
    return summary
