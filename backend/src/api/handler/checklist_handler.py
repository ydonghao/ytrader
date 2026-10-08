"""买入体检聚合 handler(课程21集)。

三层范式:本文件只做"取数 + 逐项降级 + 调 checklist_status 组装";
所有判定逻辑在纯函数 checklist_status.py(可离线测试)。
串调既有 report 函数,json.loads(resp.body).get("data") 解包
(先例:financial_detail_handler.py:2138 five_forces_report)。
"""
import json
from datetime import date, timedelta
from typing import Any

from src.pkg import responses

from src.domain.market.fundamental.checklist_status import build_checklist


def _data(fn, *args, **kwargs):
    """调既有 handler 函数 → 解包 data;任何异常/失败码 → None(逐项降级)。"""
    try:
        body = json.loads(fn(*args, **kwargs).body)
        if body.get("code") == 0:
            return body.get("data")
    except Exception:  # noqa: BLE001
        pass
    return None


def _fetch_closes(symbol: str, limit: int = 200) -> list:
    """近 N 日收盘价(升序)。handler 不反向 import router 层 fetch_kline,
    自写 stock_ohlcv 查询(对齐 stock_profile 内嵌 psycopg2 先例)。"""
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn

    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT close_ FROM stock_ohlcv
                   WHERE symbol = %s ORDER BY trade_date DESC LIMIT %s""",
                (symbol, limit),
            )
            rows = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    return rows[::-1]  # DESC 取最近N根 → 反转成升序


def checklist_report(symbol: str) -> Any:
    """GET /checklist/{symbol} — 四区21项聚合(只展示不下结论)。"""
    from src.api.handler.financial_detail_handler import (
        concentration_report, detail_series, five_forces_report,
        fraud_signals_report, industry_peers, liquidity_report,
        moat_report, stock_profile, valuation_band_report,
        z_score_report, m_score_report,
    )
    from src.domain.market.fundamental.kline_trend import trend_state
    from src.domain.market.fundamental.quality import payout_ratio
    from src.domain.market.strategy.longterm.data_loader import (
        fetch_financial_history,
    )
    from src.infra.database.market.dividend import (
        create_stock_dividend_repository,
    )
    from src.infra.database.market.checklist import (
        create_checklist_repository,
    )

    sources: dict = {}

    profile = _data(stock_profile, symbol) or {}
    sources["profile"] = profile or None

    # 年报序列(营收/净利/EPS),显式按报告期升序防御
    income = _data(detail_series, symbol, "income", 20, None, None, "year") or {}
    annual = sorted(
        (income.get("series") or []),
        key=lambda r: r.get("report_date") or "",
    )
    # detail_series 的 report_date 为 ISO 字符串;revenue_cagr 契约要求
    # date 对象(见 Task 2 测试)→ 逐行转换,畸形值留给纯函数判 missing
    for r in annual:
        if isinstance(r.get("report_date"), str):
            try:
                r["report_date"] = date.fromisoformat(r["report_date"])
            except ValueError:
                pass
    sources["income_annual"] = annual or None

    # ROE 年报序列(取近20期报告滤 12-31;fetch_financial_history 升序)
    hist = fetch_financial_history([symbol], lookback_reports=20) or {}
    roe_annual = [
        r["roe_weighted"] for r in hist.get(symbol, [])
        if str(r.get("report_date", "")).endswith("12-31")
        and isinstance(r.get("roe_weighted"), (int, float))
    ]
    sources["roe_annual"] = roe_annual or None

    # 五力(supplier/buyer 议价 + ROE 行业分位)与行业截面(CR4/HHI 参考)
    ff = _data(five_forces_report, symbol) or {}
    sources["five_forces"] = ff or None
    if ff.get("forces"):
        for f in ff["forces"]:
            for ev in f.get("evidence") or []:
                if ev.get("metric") == "ROE行业分位" and isinstance(
                        ev.get("value"), (int, float)):
                    sources["roe_pctile"] = ev["value"]
    peers = _data(industry_peers, symbol) or {}
    sections = peers.get("sections") or []
    sources["sections_latest"] = next(
        (s for s in reversed(sections) if s.get("cr4") is not None), None)

    sources["liquidity"] = _data(liquidity_report, symbol) or None
    sources["fraud"] = _data(fraud_signals_report, symbol) or None
    sources["z"] = _data(z_score_report, symbol) or None
    sources["m"] = _data(m_score_report, symbol) or None
    sources["band_pe"] = _data(valuation_band_report, symbol, "pe", 8) or None
    sources["band_ps"] = _data(valuation_band_report, symbol, "ps", 8) or None
    sources["concentration"] = _data(concentration_report, symbol) or None
    sources["moat"] = _data(moat_report, symbol) or None

    # 派息率(每股口径等价:Σ近365日每股派息 / 最新年报EPS)
    eps = None
    if annual:
        eps = annual[-1].get("basic_eps")
    div_sum = None
    try:
        dr = create_stock_dividend_repository()
        div_rows = dr.get_history(
            symbol, start=date.today() - timedelta(days=365))
        divs = [r.div_per_share for r in div_rows
                if isinstance(r.div_per_share, (int, float))]
        div_sum = sum(divs) if divs else None
    except Exception:  # noqa: BLE001
        pass
    if isinstance(eps, (int, float)) and isinstance(div_sum, (int, float)):
        sources["payout"] = payout_ratio(eps, div_sum)

    # K线趋势(自写查询 + Task 1 纯函数)
    try:
        closes = _fetch_closes(symbol)
        sources["kline_trend"] = trend_state(closes) if closes else None
    except Exception:  # noqa: BLE001
        sources["kline_trend"] = None

    # 前十大股东(1.6 参考)
    sources["shareholders"] = _shareholders(symbol)

    # 已保存手动项
    try:
        saved = create_checklist_repository().get_all(symbol)
    except Exception:  # noqa: BLE001
        saved = {}

    data = build_checklist(sources, saved)
    data["symbol"] = symbol
    data["note"] = (
        "只展示不下结论;四态 ok/watch/risk/missing 为课程口径状态点,"
        "非买卖建议。手动项须研究清楚再填——糊弄的数据不如不填;"
        "投资后定期复检(>90天页面提示)。"
    )
    return responses.success(data)


def _shareholders(symbol: str) -> list:
    """前十大股东(1.6 股权架构参考),复用 ownership 查询逻辑。"""
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn

    # connect 也须在 try 内:DB 不可达时返回 [],不得打断 GET 聚合响应
    # (对齐 stock_profile 的降级写法;conn 判空防 finally NameError)
    conn = None
    try:
        conn = psycopg2.connect(get_dsn())
        with conn.cursor() as cur:
            cur.execute(
                """SELECT holder_name, shares_pct, holder_type
                   FROM shareholder_info WHERE symbol = %s
                   ORDER BY ranking ASC LIMIT 10""",
                (symbol,),
            )
            return [{"name": r[0], "ratio": r[1], "type": r[2]}
                    for r in cur.fetchall()]
    except Exception:  # noqa: BLE001
        return []
    finally:
        if conn is not None:
            conn.close()


def save_checklist_items(symbol: str, payload: dict) -> Any:
    """PUT /checklist/{symbol}/items — 批量保存手动项(空值=清除)。"""
    from src.infra.database.market.checklist import (
        create_checklist_repository,
    )
    from src.domain.market.fundamental.checklist_status import sanitize_items

    items = sanitize_items((payload or {}).get("items") or [])
    if not items:
        # 客户端载荷问题 → 422/INVALID_PARAM(而非 500;DB 异常分支才走 error)
        return responses.validate_error("无可保存项(item_key 非法或全为空)")
    try:
        n = create_checklist_repository().upsert_items(symbol, items)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"保存失败: {e}")
    return responses.success({"symbol": symbol, "saved": n})
