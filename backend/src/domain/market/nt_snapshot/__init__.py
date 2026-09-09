"""国家队「实时全景」聚合器(移植自压缩包仪表盘的数据层,改为全动态)。

输入:DB 最新报告期持仓(权威季报)+ 腾讯实时行情(估值/盘口/份额)。
输出:与压缩包 data.json 同构的快照 —— 持仓明细、团队/行业汇总、行业×团队矩阵、
     量化洞察卡,以及 ETF 实时 + 份额变动信号。

与既有 national_team_handler 完全解耦:既有的「历年持仓/每日动向」走 DB/akshare
成交量口径,本模块只服务新增的实时全景视图,互不影响。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from src.domain.market.sync.providers.national_team_config import (
    get_entity_meta,
    get_etf_first_holders,
)
from src.domain.market.sync.providers.db_quote import (
    fetch_stock_quotes,
    fetch_etf_quotes,
    fetch_one_kline,
)

# category → 展示名/色的统一映射(前端也用同一份,经 /live/entities 暴露)
_CATEGORY_TO_TEAM = {
    "huijin": "中央汇金", "zhengjin": "证金公司", "social_security": "社保基金",
    "pension": "养老金", "safe": "外管局", "big_fund": "国家大基金",
}


def _latest_period_rows() -> list[dict]:
    """DB 最新报告期的全部国家队持仓行(含行业),按 symbol 聚合到 holders。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    # 复用既有 top 接口:它取最新报告期并按 symbol 聚合(含 holders + sector)
    return repo.get_top_holdings(period=None, limit=100000, offset=0)


def _industry_of(symbol: str, sector: str) -> str:
    """行业(细分)映射:DB 里 sector 是申万一级;若没有更细的 industry,用 sector 兜底。
    压缩包区分 sector(粗) 与 industry(细),本系统只有申万一级,二者一致。"""
    return sector or "未知"


def _fmt_big(v: float) -> str:
    """亿 → 万亿/亿 展示。"""
    if v >= 10000:
        return f"{v/10000:.2f}万亿"
    return f"{v:.1f}亿"


def build_snapshot() -> dict[str, Any]:
    """主入口:组装实时全景快照。"""
    rows = _latest_period_rows()
    entity_meta = get_entity_meta()
    if not rows:
        return _empty_snapshot(entity_meta)

    symbols = list({r["symbol"] for r in rows})
    quotes = fetch_stock_quotes(symbols)
    now = dt.datetime.now()
    hour = now.hour
    market_status = "交易中" if 9 <= hour < 15 else "已收盘"

    # ── 持仓明细(每条 = 某 symbol 的某 holder)+ 实时行情叠加 ──
    holdings_detail: list[dict] = []
    # symbol → 聚合(同压缩包 stock_summary)
    stock_agg: dict[str, dict] = {}
    latest_period = rows[0].get("report_date")
    for r in rows:
        sym = r["symbol"]
        q = quotes.get(sym, {})
        sector = r.get("sector") or "未知"
        industry = _industry_of(sym, sector)
        for h in r.get("holders", []):
            cat = h.get("holder_category", "")
            team = _CATEGORY_TO_TEAM.get(cat, cat)
            shares = int(h.get("hold_shares") or 0)
            price = float(q.get("price") or 0)
            holding_value_yi = round(shares * price / 1e8, 2) if price else 0.0
            rec = {
                "code": sym,
                "name": r.get("company_name") or q.get("name") or sym,
                "industry": industry,
                "sector": sector,
                "entity": h.get("holder_name", ""),
                "team": team,
                "team_type": entity_meta.get(cat, {}).get("type", cat),
                "category": cat,
                "shares": shares,
                "ratio": round(float(h.get("pct_of_float") or 0), 2),  # 占流通股%
                "ranking": int(h.get("ranking") or 0),
                # 实时行情字段(无行情时为 0,前端降级)
                "price": price,
                "change_pct": float(q.get("change_pct") or 0),
                "pe_ttm": float(q.get("pe_ttm") or 0),
                "pb": float(q.get("pb") or 0),
                "mcap_yi": float(q.get("mcap_yi") or 0),
                "float_mcap_yi": float(q.get("float_mcap_yi") or 0),
                "amount_wan": float(q.get("amount_wan") or 0),
                "turnover_pct": float(q.get("turnover_pct") or 0),
                "volume_ratio": float(q.get("volume_ratio") or 0),
                "amplitude": float(q.get("amplitude") or 0),
                "high_52w": float(q.get("high_52w") or 0),
                "low_52w": float(q.get("low_52w") or 0),
                "week_52_position": float(q.get("week_52_position") or 0),
                "chg_5d": float(q.get("chg_5d") or 0),
                "chg_20d": float(q.get("chg_20d") or 0),
                "max_drawdown_20d": float(q.get("max_drawdown_20d") or 0),
                "kline": q.get("kline") or [],
                "holding_value_yi": holding_value_yi,
                "data_source": {
                    "holdings": f"{latest_period} 季报前十大流通股东" if latest_period else "季报",
                    "quote": q.get("_source", "DB"),
                    "holding_value": "季报持股数 × 最新交易日收盘价(估算)",
                },
            }
            holdings_detail.append(rec)

            # symbol 聚合
            agg = stock_agg.setdefault(sym, {
                "code": sym, "name": rec["name"], "industry": industry, "sector": sector,
                "price": price, "change_pct": rec["change_pct"], "pe_ttm": rec["pe_ttm"],
                "pb": rec["pb"], "mcap_yi": rec["mcap_yi"], "float_mcap_yi": rec["float_mcap_yi"],
                "amount_wan": rec["amount_wan"], "turnover_pct": rec["turnover_pct"],
                "volume_ratio": rec["volume_ratio"], "amplitude": rec["amplitude"],
                "high_52w": rec["high_52w"], "low_52w": rec["low_52w"],
                "week_52_position": rec["week_52_position"],
                "chg_5d": rec["chg_5d"], "chg_20d": rec["chg_20d"],
                "max_drawdown_20d": rec["max_drawdown_20d"],
                "total_holding_value": 0.0, "holders": [],
            })
            agg["total_holding_value"] += holding_value_yi
            agg["holders"].append({
                "entity": rec["entity"], "team": team, "category": cat,
                "team_type": rec["team_type"], "shares": shares,
                "ratio": rec["ratio"], "holding_value_yi": holding_value_yi,
            })

    stock_summary = sorted(stock_agg.values(), key=lambda x: x["total_holding_value"], reverse=True)

    # ── 团队汇总 ──
    team_summary = _team_summary(holdings_detail, entity_meta)
    # ── 行业汇总 ──
    sector_summary = _sector_summary(holdings_detail)
    # ── 行业 × 团队 矩阵(值=持仓市值亿)──
    industry_team_matrix = _industry_team_matrix(holdings_detail)
    # ── 总市值 ──
    total_value_yi = round(sum(d["holding_value_yi"] for d in holdings_detail), 2)

    meta = {
        "title": "国家队持仓实时追踪",
        "version": "3.0",
        "update_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "data_period": f"{latest_period}季报 + DB行情(最新交易日)" if latest_period else "DB行情",
        "total_stocks": len(stock_summary),
        "total_holdings": len(holdings_detail),
        "total_value_yi": total_value_yi,
        "total_value_display": _fmt_big(total_value_yi),
        "market_status": market_status,
        "data_integrity_note": "持仓=季报前十大流通股东(权威);行情/估值=stock_ohlcv+stock_valuation(每日同步);市值=持股数×最新收盘价(估算)",
    }

    return {
        "meta": meta,
        "national_team_entities": _entities_payload(entity_meta, team_summary),
        "team_summary": team_summary,
        "sector_summary": sector_summary,
        "stock_summary": stock_summary,
        "holdings_detail": holdings_detail,
        "industry_team_matrix": industry_team_matrix,
        "insights": build_insights(holdings_detail, stock_summary, team_summary, sector_summary, total_value_yi),
    }


def _team_summary(detail: list[dict], entity_meta: dict) -> list[dict]:
    by_team: dict[str, dict] = {}
    for d in detail:
        t = d["team"]
        cat = d["category"]
        o = by_team.setdefault(t, {
            "team": t, "team_type": entity_meta.get(cat, {}).get("type", cat),
            "category": cat, "color": entity_meta.get(cat, {}).get("color", "#999"),
            "stock_count": 0, "total_holding_value": 0.0, "stocks": set(),
        })
        o["total_holding_value"] += d["holding_value_yi"]
        o["stocks"].add(d["code"])
    out = []
    for t, o in by_team.items():
        out.append({
            "team": t, "team_type": o["team_type"], "category": o["category"],
            "color": o["color"], "stock_count": len(o["stocks"]),
            "total_holding_value": round(o["total_holding_value"], 2),
            "total_holding_value_display": _fmt_big(o["total_holding_value"]),
        })
    return sorted(out, key=lambda x: x["total_holding_value"], reverse=True)


def _sector_summary(detail: list[dict]) -> list[dict]:
    by_sec: dict[str, dict] = {}
    for d in detail:
        o = by_sec.setdefault(d["sector"], {"sector": d["sector"], "total_value": 0.0, "count": set()})
        o["total_value"] += d["holding_value_yi"]
        o["count"].add(d["code"])
    return sorted([{
        "sector": s, "total_value": round(o["total_value"], 2), "count": len(o["count"]),
    } for s, o in by_sec.items()], key=lambda x: x["total_value"], reverse=True)


def _industry_team_matrix(detail: list[dict]) -> dict[str, float]:
    """key="{industry}|{team}" → 持仓市值(亿)。前端画团队×行业热力图。"""
    m: dict[str, float] = {}
    for d in detail:
        k = f"{d['industry']}|{d['team']}"
        m[k] = round(m.get(k, 0) + d["holding_value_yi"], 2)
    return m


def _entities_payload(entity_meta: dict, team_summary: list[dict]) -> dict:
    """6 大主体元数据(含 entities 全称 + 是否有持仓)。"""
    has = {t["category"]: t for t in team_summary}
    out = {}
    for cat, m in entity_meta.items():
        out[m["display"]] = {
            "category": cat,
            "color": m["color"],
            "type": m["type"],
            "desc": m["desc"],
            "has_holdings": cat in has,
            "total_holding_value": has.get(cat, {}).get("total_holding_value", 0),
        }
    return out


def _empty_snapshot(entity_meta: dict) -> dict[str, Any]:
    now = dt.datetime.now()
    return {
        "meta": {
            "title": "国家队持仓实时追踪", "version": "3.0",
            "update_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "data_period": "暂无持仓数据", "total_stocks": 0, "total_holdings": 0,
            "total_value_yi": 0, "total_value_display": "0", "market_status": "—",
            "data_integrity_note": "季报持仓回填进行中",
        },
        "national_team_entities": _entities_payload(entity_meta, []),
        "team_summary": [], "sector_summary": [], "stock_summary": [],
        "holdings_detail": [], "industry_team_matrix": {},
        "insights": [],
    }


# ── 量化洞察卡(移植压缩包 generate_insights 的 10 类规则,全动态重算)──
def build_insights(
    detail: list[dict], stock: list[dict], team: list[dict],
    sector: list[dict], total_value: float,
) -> list[dict]:
    if not detail:
        return []
    out: list[dict] = []

    # 1. 团队集中度(单一团队 >60% 提示)
    if team and total_value > 0:
        top = team[0]
        pct = top["total_holding_value"] / total_value * 100
        if pct > 60:
            out.append({
                "type": "concentration", "level": "warn" if pct < 85 else "alert",
                "title": "持仓高度集中",
                "detail": f"{top['team']}占总持仓 {pct:.1f}%({top['total_holding_value_display']}),集中度偏高",
            })

    # 2. 行业集中度
    if sector and total_value > 0:
        top = sector[0]
        pct = top["total_value"] / total_value * 100
        if pct > 50:
            out.append({
                "type": "sector_concentration", "level": "warn" if pct < 80 else "alert",
                "title": "行业高度集中",
                "detail": f"{top['sector']}占 {pct:.1f}%({top['total_value']:.0f}亿),行业集中度偏高",
            })

    # 3. 估值筛(PE<10 的低估值蓝筹数)
    low_pe = [s for s in stock if 0 < s["pe_ttm"] < 10]
    if low_pe:
        out.append({
            "type": "valuation", "level": "info",
            "title": f"{len(low_pe)} 只持仓 PE<10(低估值)",
            "detail": "、".join(s["name"] for s in low_pe[:5]) + (f" 等{len(low_pe)}只" if len(low_pe) > 5 else ""),
        })

    # 4. 52 周高位风险(>80 分位)
    high_pos = [s for s in stock if s["week_52_position"] > 80]
    if high_pos:
        out.append({
            "type": "technical", "level": "warn",
            "title": f"{len(high_pos)} 只处于 52 周高位(>80%)",
            "detail": "、".join(s["name"] for s in high_pos[:5]),
        })

    # 5. 52 周低位机会(<20 分位)
    low_pos = [s for s in stock if 0 < s["week_52_position"] < 20]
    if low_pos:
        out.append({
            "type": "opportunity", "level": "opportunity",
            "title": f"{len(low_pos)} 只处于 52 周低位(<20%)",
            "detail": "、".join(s["name"] for s in low_pos[:5]),
        })

    # 6. 当日涨跌广度
    ups = [s for s in stock if s["change_pct"] > 0]
    downs = [s for s in stock if s["change_pct"] < 0]
    if ups or downs:
        biggest_up = max(stock, key=lambda x: x["change_pct"]) if ups else None
        biggest_down = min(stock, key=lambda x: x["change_pct"]) if downs else None
        detail_str = f"上涨 {len(ups)} / 下跌 {len(downs)}"
        if biggest_up:
            detail_str += f";涨幅最大 {biggest_up['name']} +{biggest_up['change_pct']:.2f}%"
        if biggest_down:
            detail_str += f";跌幅最大 {biggest_down['name']} {biggest_down['change_pct']:.2f}%"
        out.append({"type": "daily_market", "level": "info", "title": "今日盘面", "detail": detail_str})

    return out


# ── ETF 实时 + 份额变动信号 ──
def build_etf_snapshot() -> dict[str, Any]:
    etfs = get_etf_first_holders()
    if not etfs:
        return {"etfs": [], "signals": [], "total_value_yi": 0, "history_dates": []}
    codes = [e["code"] for e in etfs]
    quotes = fetch_etf_quotes(codes)

    from src.infra.database.market.national_team_etf_shares import (
        create_etf_shares_repository,
    )
    repo = create_etf_shares_repository()
    history_dates = repo.get_all_latest_dates(90)
    hist_by_code = {c: repo.get_history(c, 90) for c in codes}

    out_etfs: list[dict] = []
    signals: list[dict] = []
    total_value = 0.0
    for e in etfs:
        q = quotes.get(e["code"], {})
        hist = hist_by_code.get(e["code"], [])
        price = float(q.get("price") or 0)
        shares_yi = float(q.get("shares_yi") or 0)
        total_value_yi = float(q.get("total_value_yi") or 0)
        total_value += total_value_yi

        # 份额变动信号:今日 vs 上一交易日 + 20 日均绝对变动 → 倍数
        prev_shares_yi = hist[-2]["shares"] / 1e8 if len(hist) >= 2 else None
        change_yi = round(shares_yi - prev_shares_yi, 2) if prev_shares_yi is not None else None
        change_pct = round((shares_yi - prev_shares_yi) / prev_shares_yi * 100, 2) \
            if prev_shares_yi else None
        # 20 日均绝对变动
        if len(hist) >= 3:
            diffs = [
                abs(hist[i]["shares"] - hist[i - 1]["shares"]) / 1e8
                for i in range(max(1, len(hist) - 20), len(hist))
                if hist[i]["shares"] and hist[i - 1]["shares"]
            ]
            avg_20d = round(sum(diffs) / len(diffs), 2) if diffs else 0.0
        else:
            avg_20d = None
        change_multiple = round(abs(change_yi) / avg_20d, 1) \
            if (change_yi is not None and avg_20d) else None
        turnover_ratio = round(float(q.get("amount_wan") or 0) / total_value_yi / 100 * 100, 2) \
            if total_value_yi else 0  # 成交额/规模 %

        first_holder_value_yi = round(total_value_yi * e["first_holder_share_pct"] / 100, 2) \
            if total_value_yi else 0

        out_etfs.append({
            "code": e["code"], "name": q.get("name") or e["name"],
            "index": e["index"], "category": e["category"], "note": e["note"],
            "first_holder_entity": e["first_holder_entity"],
            "first_holder_share_pct": e["first_holder_share_pct"],
            "first_holder_value_yi": first_holder_value_yi,
            "first_holder_data_source": e["data_source"],
            "price": price, "change_pct": float(q.get("change_pct") or 0),
            "amount_wan": float(q.get("amount_wan") or 0),
            "shares_yi": shares_yi, "total_value_yi": total_value_yi,
            "turnover_pct": float(q.get("turnover_pct") or 0),
            "volume_ratio": float(q.get("volume_ratio") or 0),
            "high_52w": float(q.get("high_52w") or 0),
            "low_52w": float(q.get("low_52w") or 0),
            "turnover_ratio_pct": turnover_ratio,
            "prev_shares_yi": prev_shares_yi,
            "shares_change_yi": change_yi,
            "shares_change_pct": change_pct,
            "avg_20d_change_yi": avg_20d,
            "change_multiple": change_multiple,
            "history_count": len(hist),
            "data_source": q.get("_source", "腾讯财经实时"),
        })

        # 信号:倍数 ≥3 或换手率 ≥3%
        if change_multiple is not None and change_multiple >= 3:
            direction = "申购" if (change_yi or 0) > 0 else "赎回"
            signals.append({
                "level": "alert",
                "title": f"{e['name']} 今日{change_multiple}倍量{direction}",
                "detail": f"份额{('+' if (change_yi or 0)>=0 else '')}{change_yi}亿份 "
                          f"(vs 20日均{avg_20d}亿),疑似国家队动作",
            })
        if turnover_ratio >= 3:
            signals.append({
                "level": "warn",
                "title": f"{e['name']} 换手活跃({turnover_ratio:.1f}%)",
                "detail": f"成交额占规模 {turnover_ratio:.1f}%,资金活跃度偏高",
            })

    out_etfs.sort(key=lambda x: x["total_value_yi"], reverse=True)
    return {
        "etfs": out_etfs, "signals": signals,
        "total_value_yi": round(total_value, 1),
        "history_dates": history_dates,
        "coverage": _etf_coverage_note(len(history_dates)),
    }


def _etf_coverage_note(n_dates: int) -> str:
    if n_dates == 0:
        return "数据积累中:尚无历史份额,异常申赎信号需累积约20个交易日后生效"
    if n_dates < 20:
        return f"数据积累中:已有 {n_dates} 个交易日,信号精度随历史增长而提升"
    return f"已覆盖 {n_dates} 个交易日"


def kline_for(symbol: str, days: int = 30) -> list[dict]:
    """个股/ETF 前复权日 K(详情弹窗蜡烛图)。"""
    return fetch_one_kline(symbol, days=days)
