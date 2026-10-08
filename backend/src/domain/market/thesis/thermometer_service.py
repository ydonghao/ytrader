"""温度计服务：实时计算 / 日快照落库 / 历史回填（闭环增强）。

compute_thermometer 自 thesis_handler 原样抽出（懒 import，便于测试
patch 源模块）；backfill 用指数估值×债券历史逐日重建全部历史温度，
运行分位（截至当日的序列内分位）；回填行 buffett 为空（历史全市场
市值求和过重）。
"""
import datetime as dt
import logging
from datetime import date, timedelta
from typing import Optional

log = logging.getLogger(__name__)

_SYMBOL = "sh000300"


def _index_pe_series(symbol: str, years: int = 16):
    """指数 PE 序列（升序，日频）。

    index_valuation_daily 存无前缀代码；computed 权威但稀疏（月频），
    legu 日频深历史（2005 起，更新至约前一月）——合并取并集，
    重叠日 computed 优先。
    """
    from src.infra.database.market.index_valuation import (
        create_index_valuation_repository,
    )
    code = symbol[2:] if symbol[:2] in ("sh", "sz") else symbol
    end = date.today()
    repo = create_index_valuation_repository()
    start = end - timedelta(days=years * 365)
    merged: dict = {}
    for source in ("legu", "computed"):   # computed 后写覆盖 legu
        for r in repo.get_index_range(
            code, start, end, source=source,
        ):
            if r.pe_ttm and r.trade_date:
                merged[r.trade_date.isoformat()] = r.pe_ttm
    return sorted(merged.items())


def _bond_series(limit: int = 4500):
    from src.infra.database.market.macro_indicator import (
        create_macro_indicator_repository,
    )
    repo = create_macro_indicator_repository()
    rows = repo.get_series("cn_bond_10y", limit=limit)
    out = []
    for r in rows:
        v = (r.get("value") if isinstance(r, dict)
             else getattr(r, "value", None))
        d = (r.get("report_date") if isinstance(r, dict)
             else getattr(r, "report_date", None))
        if v is not None and d:
            out.append((d, float(v)))
    return out


def _total_mv_sum_tln() -> Optional[float]:
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT SUM(mv) FROM ("
                "  SELECT DISTINCT ON (symbol) symbol, "
                "  total_mv AS mv FROM stock_valuation "
                "  ORDER BY symbol, trade_date DESC) t"
            )
            row = cur.fetchone()
            return float(row[0]) / 1e12 if row and row[0] else None
    finally:
        conn.close()


def compute_thermometer(symbol: str = _SYMBOL,
                        gdp: float = 140.0) -> dict:
    """全市场温度：ERP 五档 + 逐日对齐分位 + 巴菲特 + 水位。"""
    from src.domain.market.fundamental.market_thermometer import (
        build_erp_series,
        market_thermometer,
    )

    pe_series: list = []
    try:
        pe_series = _index_pe_series(symbol)
    except Exception as e:
        log.warning("thermometer index pe 失败: %s", e)

    bond, bond_series = None, []
    try:
        bs = _bond_series()
        if bs:
            bond_series = bs
            bond = bs[-1][1]
    except Exception as e:
        log.warning("thermometer bond 失败: %s", e)

    total_mv_sum = None
    try:
        total_mv_sum = _total_mv_sum_tln()
    except Exception as e:
        log.warning("thermometer total mv 失败: %s", e)

    erp_hist, approx = build_erp_series(
        pe_series, bond_series, bond
    )
    values = [v for _, v in erp_hist]
    pe_ttm = pe_series[-1][1] if pe_series else None
    out = market_thermometer(
        pe_ttm, bond, total_mv_sum=total_mv_sum, gdp=gdp,
        erp_history=values, erp_history_approx=approx,
    )
    out["symbol"] = symbol
    out["gdp_assumption_tln"] = gdp
    return out


def sync_thermometer_daily(symbol: str = _SYMBOL) -> Optional[dict]:
    """每日快照落库（17:40 job）。"""
    from src.infra.database.portfolio.thesis_repository import (
        create_thesis_repository,
    )
    out = compute_thermometer(symbol)
    if out.get("erp_pct") is None:
        return None
    band = out.get("position_band") or {}
    row = {
        "symbol": symbol,
        "trade_date": date.today(),
        "ep_pct": out.get("ep_pct"), "erp_pct": out.get("erp_pct"),
        "level": out.get("level"), "level_label": out.get("level_label"),
        "position_low": band.get("low"),
        "position_high": band.get("high"),
        "erp_percentile": out.get("erp_percentile"),
        "buffett_pct": out.get("buffett_pct"),
        "buffett_level": out.get("buffett_level"),
        "history_approx": bool(out.get("erp_history_approx")),
    }
    create_thesis_repository().upsert_thermometer_rows([row])
    return row


def backfill_thermometer(symbol: str = _SYMBOL) -> dict:
    """历史回填：逐日 ERP + 档位 + 运行分位，幂等可重跑。"""
    from src.domain.market.fundamental.market_thermometer import (
        build_erp_series,
        erp_to_level,
    )
    from src.infra.database.portfolio.thesis_repository import (
        create_thesis_repository,
    )

    pe_series = _index_pe_series(symbol)
    bond_series = _bond_series()
    current_bond = bond_series[-1][1] if bond_series else None
    series, approx = build_erp_series(
        pe_series, bond_series, current_bond
    )
    rows = []
    running: list = []
    for d_iso, erp in series:
        level, label, band = erp_to_level(erp)
        running.append(erp)
        pct = round(
            sum(1 for v in running if v <= erp) / len(running) * 100.0, 1
        )
        rows.append({
            "symbol": symbol,
            "trade_date": dt.date.fromisoformat(d_iso),
            "ep_pct": None,   # 逐日 ep 可由 pe 反推，留空省算
            "erp_pct": round(erp, 2),
            "level": level, "level_label": label,
            "position_low": band["low"] if band else None,
            "position_high": band["high"] if band else None,
            "erp_percentile": pct,
            "buffett_pct": None, "buffett_level": None,
            "history_approx": approx,
        })
    if rows:
        create_thesis_repository().upsert_thermometer_rows(rows)
    return {"rows": len(rows), "approx": approx,
            "first": rows[0]["trade_date"].isoformat() if rows else None,
            "last": rows[-1]["trade_date"].isoformat() if rows else None}
