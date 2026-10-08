"""v3 拟真考核撮合引擎 — 前端 fill.ts 规则 1:1 移植 + 段级撮合扩展。

本模块只做纯计算,不碰 DB;positions 元素形状同前端 Position:
{symbol, shares, cost_price, buy_date}。
"""

from __future__ import annotations

import random
from datetime import date


def round2(v: float) -> float:
    return round(v * 100) / 100


def price_limit_ratio(symbol: str, name: str | None = None) -> float:
    """涨跌停幅度:ST 5% / 创业·科创 20% / 北交 30% / 主板 10%。"""
    if name and "ST" in name.upper():
        return 0.05
    code = symbol.lower()
    for p in ("sh", "sz", "bj"):
        if code.startswith(p):
            code = code[len(p):]
            break
    if code.startswith(("300", "301", "688", "689")):
        return 0.2
    if code.startswith(("8", "4", "92")):
        return 0.3
    return 0.1


def limit_prices(prev_close: float, ratio: float) -> tuple[float, float]:
    return (round2(prev_close * (1 + ratio)),
            round2(prev_close * (1 - ratio)))


def commission(amount: float) -> float:
    return max(5.0, round2(amount * 0.00025))


def stamp_tax(amount: float, day: str) -> float:
    rate = 0.0005 if day >= "2023-08-28" else 0.001
    return round2(amount * rate)


def slippage(seed: str) -> float:
    """确定性滑点 0~0.15%,方向由调用方施加(买加卖减)。"""
    return random.Random(f"slip:{seed}").random() * 0.0015


def dividend_tax_rate(buy_date: str, ex_date: str) -> float:
    """红利税持有期税档:>1年 0 / 1月~1年 10% / <1月 20%(同论点体系)。"""
    b = date.fromisoformat(buy_date)
    e = date.fromisoformat(ex_date)
    days = (e - b).days
    if days > 365:
        return 0.0
    if days >= 30:
        return 0.1
    return 0.2


def try_fill_market(
    cash: float,
    positions: list[dict],
    order: dict,
    seg_price: float,
    prev_close: float,
    name: str | None,
    day: str,
) -> dict:
    """市价单按段价成交(调用方已把滑点并入 seg_price)。

    规则:整手买入/零股卖出、涨跌停区间校验(段价触及即拒)、
    T+1、资金校验、费税。返回 FillResult。
    """
    shares = order.get("shares")
    if not isinstance(shares, int) or shares <= 0:
        return {"ok": False, "error": "股数须为正整数"}
    side = order["side"]
    if side == "buy" and shares % 100 != 0:
        return {"ok": False, "error": "买入股数须为100的整数倍"}
    ratio = price_limit_ratio(order["symbol"], name)
    up, down = limit_prices(prev_close, ratio)
    price = round2(seg_price)
    amount = round2(price * shares)
    if side == "buy":
        if price >= up:
            return {"ok": False, "error": "涨停，无法买入"}
        fee = commission(amount)
        cost = round2(amount + fee)
        if cost > cash:
            return {"ok": False, "error": "资金不足"}
        positions2 = [dict(p) for p in positions]
        i = next((k for k, p in enumerate(positions2)
                  if p["symbol"] == order["symbol"]), -1)
        if i >= 0:
            p = positions2[i]
            total = p["shares"] + shares
            p["cost_price"] = round2(
                (p["cost_price"] * p["shares"] + price * shares) / total)
            p["shares"] = total
        else:
            positions2.append({
                "symbol": order["symbol"], "shares": shares,
                "cost_price": price, "buy_date": day,
            })
        return {"ok": True, "cash": round2(cash - cost),
                "positions": positions2,
                "trade": _trade(day, order, price, shares, fee, 0.0)}
    # sell
    if price <= down:
        return {"ok": False, "error": "跌停，无法卖出"}
    i = next((k for k, p in enumerate(positions)
              if p["symbol"] == order["symbol"]), -1)
    if i < 0:
        return {"ok": False, "error": "无持仓"}
    p = positions[i]
    if p["shares"] < shares:
        return {"ok": False, "error": "持仓不足"}
    if p["buy_date"] >= day:
        return {"ok": False, "error": "T+1：今日买入明日才可卖出"}
    fee = commission(amount)
    tax = stamp_tax(amount, day)
    positions2 = [dict(q) for q in positions]
    if positions2[i]["shares"] == shares:
        positions2.pop(i)
    else:
        positions2[i]["shares"] -= shares
    return {"ok": True, "cash": round2(cash + amount - fee - tax),
            "positions": positions2,
            "trade": _trade(day, order, price, shares, fee, tax)}


def _trade(day, order, price, shares, fee, tax) -> dict:
    return {"trade_date": day, "symbol": order["symbol"],
            "side": order["side"], "price": price, "shares": shares,
            "fee": fee, "tax": tax, "note": order.get("note"),
            "confidence": order.get("confidence"),
            "order_type": order.get("order_type", "market")}


# ── 挂单簿(v3:限价单当日有效) ──

import uuid


def freeze_amount(limit_price: float, shares: int) -> float:
    """限价买单冻结额 = max(金额×1.002, 金额+5)。

    佣金有 5 元下限,金额<2500 时 0.2% 余量盖不住(审查修正:
    原纯 1.002 公式在小额单会让成交把 cash 打到负数,违 spec §6
    "防挂单超额占款"意图)。
    """
    amount = limit_price * shares
    return round2(max(amount * 1.002, amount + 5.0))


def sellable_shares(state: dict, symbol: str, day: str) -> int:
    """可卖股数 = 持股 − 挂单冻结卖股(挂单下单时已校验 T+1)。"""
    pos = next((p for p in state["positions"]
                if p["symbol"] == symbol), None)
    if pos is None:
        return 0
    frozen = sum(o["shares"] for o in state.get("pending_orders", [])
                 if o["symbol"] == symbol and o["side"] == "sell")
    return max(0, pos["shares"] - frozen)


def try_place_limit(state: dict, order: dict, prev_close: float,
                    name: str | None, day: str) -> dict:
    """限价单校验入挂单簿(当日有效,收盘自动撤)。"""
    shares = order.get("shares")
    if not isinstance(shares, int) or shares <= 0:
        return {"ok": False, "error": "股数须为正整数"}
    if order["side"] == "buy" and shares % 100 != 0:
        return {"ok": False, "error": "买入股数须为100的整数倍"}
    limit_price = order.get("limit_price")
    try:
        limit_price = float(limit_price)
    except (TypeError, ValueError):
        return {"ok": False, "error": "limit_price 应为正数"}
    if limit_price <= 0:
        return {"ok": False, "error": "limit_price 应为正数"}
    up, down = limit_prices(
        prev_close, price_limit_ratio(order["symbol"], name))
    if not (down <= limit_price <= up):
        return {"ok": False, "error": f"限价须在当日区间 [{down}, {up}]"}
    frozen = 0.0
    if order["side"] == "buy":
        need = freeze_amount(limit_price, shares)
        if state["cash"] - state.get("frozen_cash", 0.0) < need:
            return {"ok": False, "error": "资金不足（含挂单冻结）"}
        frozen = need
        state["frozen_cash"] = round2(
            state.get("frozen_cash", 0.0) + need)
    else:
        pos = next((p for p in state["positions"]
                    if p["symbol"] == order["symbol"]), None)
        if pos is None:
            return {"ok": False, "error": "无持仓"}
        if pos["buy_date"] >= day:
            return {"ok": False, "error": "T+1：今日买入明日才可卖出"}
        if shares > sellable_shares(state, order["symbol"], day):
            return {"ok": False, "error": "持仓不足（含挂单冻结）"}
    o = {"id": uuid.uuid4().hex[:8], "side": order["side"],
         "symbol": order["symbol"], "shares": shares,
         "limit_price": round2(limit_price), "note": order.get("note"),
         "confidence": order.get("confidence"),
         "placed_day": day, "frozen": frozen}
    state.setdefault("pending_orders", []).append(o)
    return {"ok": True, "order": o}


def check_pending(state: dict, seg_by_symbol: dict[str, dict],
                  prev_closes: dict[str, float], names: dict[str, str],
                  day: str) -> tuple[list[dict], list[dict]]:
    """当前段逐单检查触发;触发的单走 try_fill_market 全套规则,拒绝即撤。

    改 state(cash/positions/pending_orders/frozen_cash),返回 (trades, events)。
    """
    trades: list[dict] = []
    events: list[dict] = []
    for o in list(state.get("pending_orders", [])):
        seg = seg_by_symbol.get(o["symbol"])
        if seg is None:  # 停牌,挂单悬着
            continue
        hit = None
        if o["side"] == "buy" and seg["low"] <= o["limit_price"]:
            hit = min(o["limit_price"], seg["open"])
        elif o["side"] == "sell" and seg["high"] >= o["limit_price"]:
            hit = max(o["limit_price"], seg["open"])
        if hit is None:
            continue
        state["pending_orders"].remove(o)
        prev = prev_closes.get(o["symbol"], o["limit_price"])
        # 有效现金 = cash − 其余挂单冻结 + 本单冻结(审查修正:
        # 原公式漏扣其余冻结,多单同段触发会超卖资金到负)
        cash = (state["cash"] - state.get("frozen_cash", 0.0)
                + (o["frozen"] if o["side"] == "buy" else 0.0))
        r = try_fill_market(cash, state["positions"],
                            {**o, "order_type": "limit"}, hit, prev,
                            names.get(o["symbol"]), day)
        if r["ok"]:
            # r 以"有效现金"为基;回填总现金须加回其余挂单冻结、
            # 扣除本单冻结(此时 frozen_cash 仍含本单,末尾统一释放)
            state["cash"] = round2(
                r["cash"] + state.get("frozen_cash", 0.0)
                - (o["frozen"] if o["side"] == "buy" else 0.0))
            state["positions"] = r["positions"]
            trades.append(r["trade"])
        else:  # 触发但规则拒绝(如资金被挪用)→ 撤单
            events.append({"type": "order_cancelled", "symbol": o["symbol"],
                           "msg": f"限价单触发但被拒({r['error']})，已撤销"})
        if o["side"] == "buy":
            state["frozen_cash"] = round2(
                state.get("frozen_cash", 0.0) - o["frozen"])
    return trades, events


def cancel_day_pending(state: dict) -> list[dict]:
    """日切:撤销全部挂单并解冻(冻结全部来自挂单,直接归零)。"""
    events = [{"type": "order_cancelled", "symbol": o["symbol"],
               "msg": f"限价单未触发已收盘撤销（{o['side']} "
                      f"{o['shares']}股 @ {o['limit_price']}）"}
              for o in state.get("pending_orders", [])]
    state["pending_orders"] = []
    state["frozen_cash"] = 0.0
    return events


# ── 日切与分红落账(v3) ──


def nav_value(cash: float, positions: list[dict],
              close_by_symbol: dict[str, float]) -> float:
    return round2(cash + sum(
        p["shares"] * close_by_symbol.get(p["symbol"], p["cost_price"])
        for p in positions))


def day_close_nav(state: dict, day: str,
                  close_by_symbol: dict[str, float]) -> dict:
    """日切记账:nav 追加 {date, value, cash, pos}(后两者供评分披露)。"""
    value = nav_value(state["cash"], state["positions"], close_by_symbol)
    point = {"date": day, "value": value, "cash": state["cash"],
             "pos": {p["symbol"]: round2(p["shares"] * close_by_symbol.get(
                 p["symbol"], p["cost_price"]))
                     for p in state["positions"]}}
    state.setdefault("nav", []).append(point)
    return point


def apply_dividends(state: dict, div_rows: list[dict],
                    day: str) -> list[dict]:
    """除权日落账:现金分红(持有期税后)+送转(股数×(1+送+转)、成本÷系数)。

    送转本身不征税(简化,spec §3.4)。改 state(cash/positions),返回事件。
    """
    events: list[dict] = []
    for row in div_rows:
        sym = row["symbol"]
        div = float(row.get("div_per_share") or 0)
        factor = 1 + float(row.get("stock_div") or 0) \
            + float(row.get("convert") or 0)
        for p in state.get("positions", []):
            if p["symbol"] != sym:
                continue
            if div > 0:
                tax = dividend_tax_rate(p["buy_date"], day)
                got = round2(div * p["shares"] * (1 - tax))
                state["cash"] = round2(state["cash"] + got)
                state.setdefault("dividends_received", []).append(
                    {"day": day, "symbol": sym, "cash_after_tax": got,
                     "tax_rate": tax})
                events.append({
                    "type": "dividend", "symbol": sym,
                    "msg": f"每股派 {div} 元，税后入账 {got} 元"
                           f"（税率 {tax * 100:.0f}%）"})
            if factor > 1:
                p["shares"] = int(round(p["shares"] * factor))
                p["cost_price"] = round2(p["cost_price"] / factor)
                state.setdefault("dividends_received", []).append(
                    {"day": day, "symbol": sym, "shares_after": p["shares"]})
                events.append({
                    "type": "split", "symbol": sym,
                    "msg": f"每10股送转 {(factor - 1) * 10:.1f} 股，"
                           f"股数调整为 {p['shares']}"})
    return events
