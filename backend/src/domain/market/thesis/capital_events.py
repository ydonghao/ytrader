"""增减持/回购事件：标准化与行为摘要纯函数（第 6 期 V2）。

原始数据来自 akshare stock_repurchase_em / stock_ggcg_em（实测字段见
spec）。纯函数零 IO：normalize 接收原始行 dict 列表，summarize 接收
标准事件列表。V2 行为摘要不计入资本配置评分，只呈现事实 + 破位级 flag。
"""
import datetime as dt
from typing import Optional


def _prefix(code: str) -> Optional[str]:
    code = (code or "").strip()
    if not code or not code.isdigit() or len(code) != 6:
        return None
    if code.startswith("6"):
        return "sh" + code
    if code[0] in ("0", "2", "3"):
        return "sz" + code
    return "bj" + code


def _as_date(v):
    if v is None or v != v:   # None 或 NaN/NaT（NaT!=NaT 为 True）
        return None
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str) and v:
        try:
            return dt.date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


def _num(v):
    try:
        f = float(v)
        import math
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _clean_str(v) -> Optional[str]:
    """pandas NaN/非字符串 → None。"""
    if isinstance(v, str):
        return v.strip() or None
    return None


def normalize_repurchase(records: list) -> list:
    """stock_repurchase_em 原始行 → 标准行（金额元，股数→万股）。"""
    out = []
    for r in records:
        sym = _prefix(r.get("股票代码") or "")
        if not sym:
            continue
        shares = _num(r.get("已回购股份数量"))
        announce = _as_date(r.get("最新公告日期"))
        if not announce:
            continue   # 无公告日无法幂等去重，跳过
        out.append({
            "symbol": sym,
            "event_type": "buyback",
            "announce_date": announce,
            "holder_name": "",
            "start_date": _as_date(r.get("回购起始时间")),
            "shares_wan": round(shares / 1e4, 4) if shares else None,
            "amount": _num(r.get("已回购金额")),
            "ratio_pct": None,
            "progress": _clean_str(r.get("实施进度")),
        })
    return out


def normalize_ggcg(records: list) -> list:
    """stock_ggcg_em 原始行 → 标准行（数量万股，比例%）。"""
    out = []
    for r in records:
        sym = _prefix(r.get("代码") or "")
        if not sym:
            continue
        direction = _clean_str(
            r.get("持股变动信息-增减")
        ) or ""
        announce = _as_date(r.get("公告日"))
        if not announce:
            continue   # 无公告日无法幂等去重，跳过
        out.append({
            "symbol": sym,
            "event_type": ("hold_increase" if "增" in direction
                           else "hold_decrease" if "减" in direction
                           else None),
            "announce_date": announce,
            "holder_name": _clean_str(r.get("股东名称")) or "",
            "start_date": _as_date(r.get("变动开始日")),
            "shares_wan": _num(r.get("持股变动信息-变动数量")),
            "amount": None,
            "ratio_pct": _num(r.get("持股变动信息-占总股本比例")),
            "progress": None,
        })
    return [r for r in out if r["event_type"]]


def summarize_mgmt_events(events: list, months: int = 24,
                          now=None) -> dict:
    """近 N 月：回购实施金额合计 + 净增减持占股本比 + label/flags。"""
    now = now or dt.date.today()
    window_start = now - dt.timedelta(days=months * 30)
    buyback_amount = 0.0
    net_ratio = 0.0
    for e in events:
        d = _as_date(e.get("announce_date"))
        if not d or d < window_start:
            continue
        if e.get("event_type") == "buyback":
            amt = e.get("amount")
            if amt:
                buyback_amount += amt
        elif e.get("event_type") == "hold_increase":
            r = e.get("ratio_pct")
            if r:
                net_ratio += r
        elif e.get("event_type") == "hold_decrease":
            r = e.get("ratio_pct")
            if r:
                net_ratio -= r

    flags = []
    if net_ratio < -0.05:          # 风险信号优先
        label = "净减持"
    elif buyback_amount > 0:
        label = "回购实施"
    elif net_ratio > 0.05:
        label = "净增持"
    else:
        label = "平静"
    if net_ratio < -1.0:
        flags.append(
            f"近{months}个月净减持超总股本1%"
            f"（{net_ratio:.2f}%）"
        )
    return {
        "months": months,
        "buyback_amount": round(buyback_amount, 2),
        "net_ratio_pct": round(net_ratio, 4),
        "label": label,
        "flags": flags,
        "note": "V2 事实呈现，不计入资本配置评分。",
    }
