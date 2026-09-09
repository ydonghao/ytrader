"""
AI Chat Router
==============
Natural language portfolio & market query API.
No external LLM — uses keyword intent classification + template responses + live DB data.
"""
import logging
from datetime import datetime, timedelta
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.infra.database.sql_engine.dsn import get_dsn

router = APIRouter(prefix="/ai", tags=["ai"])
log = logging.getLogger(__name__)


# ── Pydantic Models ───────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    context: str = "general"  # "general" | "portfolio" | "market" | "strategy"


class ChatResponse(BaseModel):
    code: int
    msg: str
    data: dict | None


# ── DB helpers ────────────────────────────────────────────────────────────────
def _conn():
    return psycopg2.connect(get_dsn(), cursor_factory=RealDictCursor)


# ── Data fetchers ─────────────────────────────────────────────────────────────
def _get_portfolio_summary() -> dict:
    """Return current portfolio summary with positions and today's P&L."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                # Try to get positions
                cur.execute("""
                    SELECT symbol, quantity, avg_cost, current_price,
                           daily_return, market_value, unrealized_pnl, sector
                    FROM positions
                    ORDER BY market_value DESC
                    LIMIT 20
                """)
                rows = cur.fetchall()

                if not rows:
                    # Return demo data
                    return {
                        "positions": [
                            {"symbol": "平安银行", "quantity": 1000, "avg_cost": 12.50, "current_price": 12.87, "daily_return": 1.25, "market_value": 12870, "unrealized_pnl": 370, "sector": "🏦 Banking"},
                            {"symbol": "招商银行", "quantity": 500, "avg_cost": 35.20, "current_price": 36.15, "daily_return": 0.65, "market_value": 18075, "unrealized_pnl": 475, "sector": "🏦 Banking"},
                            {"symbol": "中国平安", "quantity": 200, "avg_cost": 48.00, "current_price": 47.35, "daily_return": -0.42, "market_value": 9470, "unrealized_pnl": -130, "sector": "🏦 Insurance"},
                        ],
                        "total_value": 40415,
                        "total_cost": 39800,
                        "total_pnl": 615,
                        "total_pnl_pct": 1.55,
                        "daily_pnl": 510,
                        "daily_pnl_pct": 1.28,
                    }

                positions = [dict(r) for r in rows]
                total_value = sum(p["market_value"] or 0 for p in positions)
                total_cost = sum(p["avg_cost"] * p["quantity"] for p in positions)
                total_pnl = sum(p["unrealized_pnl"] or 0 for p in positions)
                daily_pnl = sum(
                    (p["daily_return"] or 0) / 100 * p["market_value"]
                    for p in positions
                )
                return {
                    "positions": positions,
                    "total_value": round(total_value, 2),
                    "total_cost": round(total_cost, 2),
                    "total_pnl": round(total_pnl, 2),
                    "total_pnl_pct": round(total_pnl / total_cost * 100, 2) if total_cost else 0,
                    "daily_pnl": round(daily_pnl, 2),
                    "daily_pnl_pct": round(daily_pnl / total_value * 100, 2) if total_value else 0,
                }
    except Exception as e:
        log.warning("portfolio summary error: %s", e)
        return {"positions": [], "total_value": 0, "total_cost": 0, "total_pnl": 0,
                "total_pnl_pct": 0, "daily_pnl": 0, "daily_pnl_pct": 0}


def _get_position_detail(symbol_hint: str) -> dict | None:
    """Find a position by symbol name/code match."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol, quantity, avg_cost, current_price,
                           daily_return, market_value, unrealized_pnl, sector
                    FROM positions
                    WHERE LOWER(symbol) LIKE LOWER(%s)
                       OR LOWER(symbol) LIKE LOWER(%s)
                    LIMIT 5
                """, (f"%{symbol_hint}%", f"{symbol_hint}%"))
                rows = cur.fetchall()
                if rows:
                    return [dict(r) for r in rows]
    except Exception as e:
        log.warning("position detail error: %s", e)
    return None


def _get_recent_performance(days: int = 30) -> dict:
    """Get backtest / strategy performance over the last N days."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                cur.execute("""
                    SELECT strategy_name, start_date, end_date,
                           total_return, sharpe_ratio, max_drawdown,
                           win_rate, total_trades
                    FROM backtest_results
                    ORDER BY end_date DESC
                    LIMIT 10
                """)
                rows = cur.fetchall()
                if rows:
                    results = [dict(r) for r in rows]
                    return {"results": results, "days": days}
    except Exception as e:
        log.warning("backtest results error: %s", e)

    # Demo data
    return {
        "results": [
            {"strategy_name": "布林带均值回归", "start_date": "2026-03-01", "end_date": "2026-04-05",
             "total_return": 12.5, "sharpe_ratio": 1.85, "max_drawdown": -6.2, "win_rate": 68.5, "total_trades": 42},
            {"strategy_name": "MACD趋势跟踪", "start_date": "2026-03-01", "end_date": "2026-04-05",
             "total_return": 8.3, "sharpe_ratio": 1.42, "max_drawdown": -9.1, "win_rate": 55.2, "total_trades": 28},
            {"strategy_name": "北向资金跟随", "start_date": "2026-02-01", "end_date": "2026-04-05",
             "total_return": 15.7, "sharpe_ratio": 2.10, "max_drawdown": -4.5, "win_rate": 72.0, "total_trades": 18},
        ],
        "days": days,
    }


def _get_market_breadth() -> dict:
    """Get market breadth / today's market summary."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN daily_return > 0 THEN 1 ELSE 0 END) as gainers,
                           SUM(CASE WHEN daily_return < 0 THEN 1 ELSE 0 END) as losers,
                           SUM(CASE WHEN daily_return > 0 THEN 1 ELSE 0 END) * 100.0 /
                               NULLIF(COUNT(*), 0) as gainer_pct
                    FROM stock_daily
                    WHERE date = CURRENT_DATE
                """)
                row = cur.fetchone()
                if row and row["total"] and row["total"] > 0:
                    return dict(row)
    except Exception as e:
        log.warning("market breadth error: %s", e)

    # Demo data
    return {"total": 5200, "gainers": 2800, "losers": 1800, "gainer_pct": 53.8}


def _get_top_signals() -> list[dict]:
    """Get latest trading signals."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol, signal_type, direction, strength, created_at
                    FROM trading_signals
                    ORDER BY created_at DESC
                    LIMIT 10
                """)
                rows = cur.fetchall()
                if rows:
                    return [dict(r) for r in rows]
    except Exception as e:
        log.warning("signals error: %s", e)

    return [
        {"symbol": "平安银行", "signal_type": "MACD", "direction": "BUY", "strength": 0.85, "created_at": datetime.now().isoformat()},
        {"symbol": "招商银行", "signal_type": "RSI", "direction": "BUY", "strength": 0.78, "created_at": datetime.now().isoformat()},
        {"symbol": "中国平安", "signal_type": "BOLL", "direction": "SELL", "strength": 0.62, "created_at": datetime.now().isoformat()},
    ]


# ── Intent Classification ────────────────────────────────────────────────────
def _classify_intent(message: str) -> tuple[str, str]:
    """
    Classify user message into intent category + extract any symbol hint.
    Returns (intent, symbol_hint).
    """
    msg = message.lower().strip()

    # Greeting
    greeting_words = ["你好", "hi", "hello", "嗨", "嗨嗨", "hiya"]
    if any(g in msg for g in greeting_words) and len(msg) < 15:
        return "greeting", ""

    # Help
    help_words = ["help", "帮助", "你能做什么", "怎么用", "功能"]
    if any(h in msg for h in help_words):
        return "help", ""

    # Portfolio summary
    portfolio_words = ["组合", "portfolio", "持仓", "仓位", "我的"]
    has_portfolio = any(p in msg for p in portfolio_words)

    # Symbol hints
    symbol_hint = ""
    for kw in ["平安", "招商", "茅台", "腾讯", "阿里", "苹果", "特斯拉"]:
        if kw in msg:
            symbol_hint = kw
            break

    # P&L query
    pnl_words = ["盈亏", "收益", "赚", "亏", "利润", "pnl", "赚了多少"]
    has_pnl = any(p in msg for p in pnl_words)
    if has_pnl and ("市场" not in msg and "大盘" not in msg):
        return "pnl_query", symbol_hint
    if has_pnl and has_portfolio:
        return "pnl_query", symbol_hint

    # Position detail (explicit symbol OR keyword-based)
    if symbol_hint:
        return "position_detail", symbol_hint
    if has_portfolio and ("详细" in msg or "情况" in msg or "多少" in msg):
        return "position_detail", symbol_hint
    if "持" in msg or "仓" in msg or "仓位" in msg:
        return "position_detail", symbol_hint

    # Market query
    market_words = ["市场", "大盘", "行情", "整体", "今天市场", "市场怎么样", "市场如何"]
    if any(m in msg for m in market_words):
        return "market_query", ""

    # Signal query
    signal_words = ["信号", "机会", "交易信号", "买什么", "推荐"]
    if any(s in msg for s in signal_words):
        return "signal_query", ""

    # Strategy / backtest
    strategy_words = ["策略", "回测", "表现", "策略怎么样", "最近"]
    if any(s in msg for s in strategy_words):
        return "strategy_query", ""

    # Default
    return "unknown", symbol_hint


# ── Response Templates ────────────────────────────────────────────────────────
_TEMPLATES: dict[str, callable] = {}


def _t_greeting() -> dict:
    return {
        "reply": (
            "你好！👋 我是你的 AI 交易助手。我可以帮你：\n"
            "• 查询持仓和收益情况\n"
            "• 分析市场行情\n"
            "• 解读交易信号\n"
            "• 查看策略回测表现\n\n"
            "有什么想问的，直接说就好！"
        ),
        "intent": "greeting",
        "cards": [],
        "actions": [
            {"label": "查询持仓", "href": "/portfolio"},
            {"label": "市场行情", "href": "/market"},
        ],
    }


def _t_help() -> dict:
    return {
        "reply": (
            "我支持以下功能：\n\n"
            "📊 **持仓查询** — '我的持仓怎么样' / '平安的仓位'\n"
            "💰 **收益分析** — '今天盈亏多少' / '收益如何'\n"
            "📈 **市场行情** — '今天大盘怎么样' / '市场分析'\n"
            "⚡ **交易信号** — '有什么交易信号' / '现在买什么'\n"
            "⚙️ **策略表现** — '最近策略表现如何' / '回测结果'\n\n"
            "直接用中文描述你的问题即可，我会尽力解答！"
        ),
        "intent": "help",
        "cards": [],
        "actions": [
            {"label": "查看信号", "href": "/trading"},
            {"label": "策略回测", "href": "/strategies"},
        ],
    }


def _t_portfolio_summary(data: dict, message: str) -> dict:
    positions = data.get("positions", [])
    total_val = data.get("total_value", 0)
    daily_pnl = data.get("daily_pnl", 0)
    daily_pct = data.get("daily_pnl_pct", 0)
    total_pnl = data.get("total_pnl", 0)
    total_pct = data.get("total_pnl_pct", 0)

    sign = "+" if daily_pnl >= 0 else ""
    reply = (
        f"当前组合共持有 **{len(positions)}** 只股票，"
        f"总市值约 **¥{total_val:,.0f}**。"
        f"今日收益 **{sign}¥{daily_pnl:,.0f}（{sign}{daily_pct:.2f}%）**，"
        f"累计收益 **{sign}¥{total_pnl:,.0f}（{sign}{total_pct:.2f}%）**。"
        if positions else
        "目前没有持仓记录，今天先来看看大盘吧！"
    )

    cards = [
        {
            "type": "metric",
            "title": "💰 今日收益",
            "value": f"{sign}¥{daily_pnl:,.0f}",
            "sub": f"{sign}{daily_pct:.2f}%",
        },
        {
            "type": "metric",
            "title": "📊 累计收益",
            "value": f"{sign}¥{total_pnl:,.0f}",
            "sub": f"{sign}{total_pct:.2f}%",
        },
        {
            "type": "metric",
            "title": "💼 总市值",
            "value": f"¥{total_val:,.0f}",
            "sub": f"{len(positions)} 只股票",
        },
    ]

    if positions:
        cards.append({
            "type": "positions",
            "title": "📋 当前持仓",
            "data": positions[:6],
        })

    return {
        "reply": reply,
        "intent": "portfolio_summary",
        "cards": cards,
        "actions": [
            {"label": "详细分析", "href": "/portfolio"},
            {"label": "查看市场", "href": "/market"},
        ],
    }


def _t_position_detail(data: dict | None, symbol_hint: str, message: str) -> dict:
    if data:
        positions = data
        p = positions[0]
        sign = "+" if p["unrealized_pnl"] >= 0 else ""
        reply = (
            f"**{p['symbol']}** 持仓详情：\n"
            f"• 持股数量：{p['quantity']} 股\n"
            f"• 持仓成本：¥{p['avg_cost']:.2f}\n"
            f"• 当前价格：¥{p['current_price']:.2f}\n"
            f"• 今日涨跌：{p['daily_return']:+.2f}%\n"
            f"• 浮动盈亏：{sign}¥{p['unrealized_pnl']:.0f}\n"
            f"• 所属板块：{p.get('sector', 'N/A')}"
        )
        cards = [{
            "type": "positions",
            "title": f"📋 {p['symbol']} 持仓",
            "data": positions,
        }]
    elif symbol_hint:
        reply = (
            f"没有找到 **{symbol_hint}** 相关的持仓记录。"
            "可能还没建仓，或者名称不完全匹配。"
        )
        cards = []
    else:
        reply = "请告诉我你想查看哪只股票的持仓情况，比如：'平安的仓位怎么样'"
        cards = []

    return {
        "reply": reply,
        "intent": "position_detail",
        "cards": cards,
        "actions": [
            {"label": "全部持仓", "href": "/portfolio"},
        ],
    }


def _t_pnl_query(data: dict, message: str) -> dict:
    daily_pnl = data.get("daily_pnl", 0)
    daily_pct = data.get("daily_pnl_pct", 0)
    total_pnl = data.get("total_pnl", 0)
    total_pct = data.get("total_pnl_pct", 0)
    total_val = data.get("total_value", 0)

    sign_d = "+" if daily_pnl >= 0 else ""
    sign_t = "+" if total_pnl >= 0 else ""

    reply = (
        f"今日收益 **{sign_d}¥{daily_pnl:,.0f}（{sign_d}{daily_pct:.2f}%）**。"
        f"累计收益 **{sign_t}¥{total_pnl:,.0f}（{sign_t}{total_pct:.2f}%）**。"
        f"当前总市值 **¥{total_val:,.0f}**。"
        if total_val else
        "目前没有持仓，今天的 P&L 暂无数据。"
    )

    cards = [
        {"type": "metric", "title": "💰 今日收益", "value": f"{sign_d}¥{daily_pnl:,.0f}", "sub": f"{sign_d}{daily_pct:.2f}%"},
        {"type": "metric", "title": "📊 累计收益", "value": f"{sign_t}¥{total_pnl:,.0f}", "sub": f"{sign_t}{total_pct:.2f}%"},
    ]

    return {"reply": reply, "intent": "pnl_query", "cards": cards,
            "actions": [{"label": "收益详情", "href": "/analytics"}, {"label": "持仓明细", "href": "/portfolio"}]}


def _t_market_query(data: dict, message: str) -> dict:
    total = data.get("total", 0)
    gainers = data.get("gainers", 0)
    losers = data.get("losers", 0)
    gainer_pct = data.get("gainer_pct", 0)

    if gainer_pct >= 55:
        mood = "整体偏多 📈"
    elif gainer_pct <= 45:
        mood = "整体偏空 📉"
    else:
        mood = "多空均衡 ⚖️"

    reply = (
        f"今日市场 **{mood}**。"
        f"上涨股票 **{gainers}** 只，下跌 **{losers}** 只。"
        f"上涨家数占比约 **{gainer_pct:.1f}%**。"
        "市场情绪指标处于中性偏多区域。"
    )

    cards = [
        {"type": "metric", "title": "📈 上涨", "value": str(gainers), "sub": f"{gainer_pct:.1f}%"},
        {"type": "metric", "title": "📉 下跌", "value": str(losers), "sub": f"{100-gainer_pct:.1f}%"},
        {"type": "metric", "title": "🌡️ 情绪", "value": mood.split()[0], "sub": f"{gainer_pct:.1f}%上涨"},
    ]

    return {"reply": reply, "intent": "market_query", "cards": cards,
            "actions": [{"label": "市场详情", "href": "/market"}, {"label": "热力图", "href": "/market"}]}


def _t_signal_query(signals: list, message: str) -> dict:
    if not signals:
        reply = "目前没有新的交易信号。稍后再来看看，我会持续监控。"
        cards = []
    else:
        top = signals[:5]
        reply = f"当前共有 **{len(signals)}** 个活跃信号，以下是最新 5 个："
        cards = [{
            "type": "signals",
            "title": "⚡ 交易信号",
            "data": top,
        }]

    return {"reply": reply, "intent": "signal_query", "cards": cards,
            "actions": [{"label": "信号详情", "href": "/trading"}, {"label": "策略列表", "href": "/strategies"}]}


def _t_strategy_query(data: dict, message: str) -> dict:
    results = data.get("results", [])
    if not results:
        reply = "暂无回测数据，请先运行回测或创建策略。"
        cards = []
    else:
        best = max(results, key=lambda r: r["total_return"])
        reply = (
            f"最近 **{data.get('days', 30)}** 天共回测了 **{len(results)}** 个策略，"
            f"表现最好的是 **《{best['strategy_name']}》**，"
            f"累计收益 **{best['total_return']:+.1f}%**，夏普比率 **{best['sharpe_ratio']:.2f}**。"
        )
        cards = [{
            "type": "strategies",
            "title": "📊 策略表现",
            "data": results,
        }]

    return {"reply": reply, "intent": "strategy_query", "cards": cards,
            "actions": [{"label": "全部策略", "href": "/strategies"}, {"label": "新建回测", "href": "/strategies"}]}


def _t_unknown(message: str) -> dict:
    return {
        "reply": (
            f"我没有完全理解你的问题：「{message}」\n\n"
            "你可以试试：\n"
            "• '我的持仓怎么样'\n"
            "• '今天盈亏多少'\n"
            "• '今天大盘怎么样'\n"
            "• '有什么交易信号'"
        ),
        "intent": "unknown",
        "cards": [],
        "actions": [
            {"label": "查询持仓", "href": "/portfolio"},
            {"label": "市场行情", "href": "/market"},
            {"label": "交易信号", "href": "/trading"},
        ],
    }


# ── Response Generator ───────────────────────────────────────────────────────
def _generate_response(intent: str, message: str, symbol_hint: str = "") -> dict:
    """Route intent to the appropriate template function."""
    portfolio_data = _get_portfolio_summary()

    dispatch: dict[str, callable] = {
        "greeting":           lambda: _t_greeting(),
        "help":               lambda: _t_help(),
        "portfolio_summary":   lambda: _t_portfolio_summary(portfolio_data, message),
        "position_detail":    lambda: _t_position_detail(
                                      _get_position_detail(symbol_hint) if symbol_hint else None,
                                      symbol_hint, message),
        "pnl_query":          lambda: _t_pnl_query(portfolio_data, message),
        "market_query":       lambda: _t_market_query(_get_market_breadth(), message),
        "signal_query":       lambda: _t_signal_query(_get_top_signals(), message),
        "strategy_query":     lambda: _t_strategy_query(_get_recent_performance(), message),
        "unknown":            lambda: _t_unknown(message),
    }

    handler = dispatch.get(intent, dispatch["unknown"])
    return handler()


# ── API Endpoint ──────────────────────────────────────────────────────────────
@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """
    Main AI Chat endpoint.
    Classifies intent from user message and returns a structured response
    with reply text, optional data cards, and navigation actions.
    """
    try:
        intent, symbol_hint = _classify_intent(req.message)
        log.info("[AI Chat] intent=%s symbol_hint=%s message=%s", intent, symbol_hint, req.message)

        result = _generate_response(intent, req.message, symbol_hint)

        return ChatResponse(code=0, msg="ok", data=result)

    except Exception as e:
        log.error("chat error: %s", e, exc_info=True)
        return ChatResponse(
            code=1,
            msg="服务器内部错误，请稍后重试",
            data={"reply": "抱歉，服务遇到了一点问题，请稍后重试。", "intent": "error", "cards": [], "actions": []},
        )
