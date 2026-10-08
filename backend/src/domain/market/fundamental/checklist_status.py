"""买入体检清单(课程21集)——状态映射与组装。纯函数,零 IO。

设计决策(spec):
- 四态 ok/watch/risk/missing;手动项 pending/filled;
- 只展示不下结论:本模块任何输出不含总体 verdict/conclusion;
- 所有源数据缺失/畸形 → 该项 missing,不抛异常(逐项降级);
- 2.5 上下游议价 = 自动项 + 可编辑备注(BARGAIN_NOTE_KEY)。

阈值均为课程口径,见各函数 docstring。
"""
from datetime import date
from typing import Any, Optional

# ── 手动项定义(9 项)────────────────────────────────────────────────
MANUAL_ITEMS: list[dict] = [
    # 一、企业基本情况(6)
    {"key": "company_name", "section": "company", "title": "公司全称",
     "input_type": "text",
     "course": "股票系统里都是简称,出于基本礼貌,公司全称要知道。"},
    {"key": "mission_vision", "section": "company", "title": "简介与使命愿景",
     "input_type": "text",
     "course": "使命=我们现在是谁;愿景=未来想干什么。官网可查。"},
    {"key": "core_products", "section": "company", "title": "核心产品",
     "input_type": "text",
     "course": "官网与财报都有,一看就知道的基础信息。"},
    {"key": "pricing_power", "section": "company", "title": "定价权",
     "input_type": "choice", "choices": ["是", "否", "不知道"],
     "course": "产品和服务是否具有定价权;不知道就先填不知道,慢慢研究。"},
    {"key": "market_position", "section": "company", "title": "市场情况",
     "input_type": "text",
     "course": "增量还是存量?市占率升降?海外开拓情况?生意还能做多大?"},
    {"key": "ownership_type", "section": "company", "title": "股权架构",
     "input_type": "choice+text",
     "choices": ["国企", "民企", "家族企业", "合伙人团队", "资本控股"],
     "course": "集中执行力强但易一言堂;分散有代理人风险。无绝对好坏。"},
    # 二、行业分析(3)
    {"key": "industry_cycle", "section": "industry", "title": "行业周期",
     "input_type": "choice", "choices": ["导入期", "成长期", "成熟期", "衰退期"],
     "course": "成长/成熟期对普通投资者最友好;导入期风险大收益大;衰退期烟蒂股多。"},
    {"key": "competitive_pattern", "section": "industry", "title": "竞争格局",
     "input_type": "choice", "choices": ["百舸争流", "一超多强", "巨头垄断"],
     "course": "百舸争流很卷打价格战;风险低可选一超多强/巨头垄断只投最好公司。"},
    {"key": "smile_position", "section": "industry", "title": "微笑曲线位置",
     "input_type": "choice+text",
     "choices": ["左端(研发设计)", "中间(制造组装)", "右端(品牌营销)"],
     "course": "施振荣1992:两端附加值最高,中间制造最低;尽量选两端避中间。"},
]
BARGAIN_NOTE_KEY = "bargaining_power_note"

_SECTIONS_META = [
    {"key": "company", "title": "一、企业基本情况"},
    {"key": "industry", "title": "二、行业分析"},
    {"key": "finance", "title": "三、财务指标"},
    {"key": "price", "title": "四、股价与估值"},
]


def _auto(key: str, section: str, title: str, status: str,
          value: Any = None, detail: Any = None, hint: str = "",
          **extra) -> dict:
    return {"key": key, "type": "auto", "section": section, "title": title,
            "status": status, "value": value, "detail": detail,
            "hint": hint, **extra}


# ── 各自动项状态判定(课程口径)──────────────────────────────────────

def revenue_cagr(annual: list, years: int = 8) -> Optional[float]:
    """年报营收 CAGR(最多取末 years+1 个年报点)。

    <2 点 / 首值<=0 / 跨度<365天 → None。
    跨度按日数判(>=365 即两个年报点),不用 365.25 折算——
    否则恰隔 365 天(非闰年)的两期年报会被误拒;折算值仅作开方指数。
    """
    pts = [(r.get("report_date"), r.get("revenue")) for r in (annual or [])
           if isinstance(r.get("revenue"), (int, float))]
    pts = pts[-(years + 1):]
    if len(pts) < 2:
        return None
    (d0, v0), (d1, v1) = pts[0], pts[-1]
    if not isinstance(d0, date) or not isinstance(d1, date):
        return None
    if v0 <= 0 or v1 <= 0:
        return None
    if (d1 - d0).days < 365:
        return None
    span = (d1 - d0).days / 365.25
    return (v1 / v0) ** (1 / span) - 1


def _industry_item(profile: Optional[dict]) -> dict:
    if not profile or not profile.get("industry"):
        return _auto("industry", "industry", "所属行业", "missing",
                     hint="申万行业/东财行业归属")
    return _auto("industry", "industry", "所属行业", "ok",
                 value=profile["industry"],
                 hint="基础信息;行业周期与竞争格局见下方手动项")


def _growth_item(income_annual: Optional[list]) -> dict:
    cagr = revenue_cagr(income_annual or [])
    if cagr is None:
        return _auto("growth", "finance", "业绩曲线(成长性)", "missing",
                     hint="年报营收序列不足,无法算 CAGR")
    pct = round(cagr * 100, 2)
    if cagr < 0.03:
        return _auto("growth", "finance", "业绩曲线(成长性)", "watch",
                     value=f"{pct}%",
                     detail="近8年营收CAGR<3%,成长停滞(格力案例口径)",
                     hint="没成长性的公司估值低;要搞清公司性质——烟蒂还是成长")
    return _auto("growth", "finance", "业绩曲线(成长性)", "ok",
                 value=f"{pct}%", detail="近8年营收CAGR",
                 hint="第一眼就看业绩曲线;曲线糟糕基本不考虑")


def _balance_item(liquidity: Optional[dict]) -> dict:
    verdict_map = {"strong": ("ok", "流动性强"), "healthy": ("ok", "流动性健康"),
                   "stretched": ("watch", "流动性紧张"),
                   "risky": ("risk", "流动性风险")}
    v = (liquidity or {}).get("verdict")
    if v not in verdict_map:
        return _auto("balance", "finance", "资产负债表健康", "missing",
                     hint="流动比率/速动比率/现金比率")
    status, label = verdict_map[v]
    return _auto("balance", "finance", "资产负债表健康", status,
                 value=label, detail=f"verdict={v}",
                 hint="重资产公司固定资产高(如比亚迪的工厂);应付账款高=强势甲方")


def _roe_item(roe_annual: Optional[list], pctile: Optional[float]) -> dict:
    roes = [r for r in (roe_annual or [])
            if isinstance(r, (int, float))]
    if not roes:
        return _auto("roe", "finance", "ROE", "missing",
                     hint="尽量选 ROE 高的公司;不同商业模式差异大,宜横向对比")
    latest = roes[-1]
    if latest < 0:
        return _auto("roe", "finance", "ROE", "risk", value=f"{latest:.2f}%",
                     detail="最新年报 ROE 为负(亏损)",
                     hint="ROE 是效率指标,横向对比居多")
    detail_bits = [f"最新年报 ROE {latest:.2f}%"]
    if pctile is not None:
        detail_bits.append(f"行业分位 {pctile * 100:.0f}%")
    if len(roes) >= 3 and roes[-1] < roes[-2] < roes[-3]:
        return _auto("roe", "finance", "ROE", "watch", value=f"{latest:.2f}%",
                     detail=";".join(detail_bits) + ";连续3年下滑",
                     hint="ROE 高=商业模式好一些;连续下滑要留意")
    if latest < 8:
        return _auto("roe", "finance", "ROE", "watch", value=f"{latest:.2f}%",
                     detail=";".join(detail_bits) + ";<8%",
                     hint="同类型公司其他条件相同时,尽量选 ROE 高的")
    return _auto("roe", "finance", "ROE", "ok", value=f"{latest:.2f}%",
                 detail=";".join(detail_bits), hint="心里有数即可")


def _dividend_item(payout: Optional[dict]) -> dict:
    ratio = (payout or {}).get("ratio")
    if ratio is None:
        return _auto("dividend", "finance", "分红", "missing",
                     hint="看分红比例与稳定性;分红是投资的安全垫")
    pct = round(ratio * 100, 1)
    if ratio > 0.7:
        return _auto("dividend", "finance", "分红", "risk", value=f"{pct}%",
                     detail="派息率>70%,警惕掏空家底式分红",
                     hint="分红作为安全垫,主要排除掏空家底的风险")
    label = "慷慨" if ratio > 0.3 else "正常"
    return _auto("dividend", "finance", "分红", "ok", value=f"{pct}%",
                 detail=f"派息率{label}",
                 hint="≤30%正常/30-70%慷慨/>70%警惕掏空")


def _redflag_item(fraud: Optional[dict], z: Optional[dict],
                  m: Optional[dict]) -> dict:
    parts = []
    if fraud and fraud.get("severity"):
        parts.append(("fraud", fraud["severity"]))
    if z and z.get("verdict"):
        parts.append(("z-score", z["verdict"]))
    if m and m.get("verdict"):
        parts.append(("m-score", m["verdict"]))
    if not parts:
        return _auto("redflag", "finance", "财务红旗", "missing",
                     hint="营收-应收背离/净利-现金流背离等")
    bad = any(v in ("high_risk", "distress", "manipulator") for _, v in parts)
    warn = any(v in ("watch", "grey") for _, v in parts)
    detail = "; ".join(f"{k}={v}" for k, v in parts)
    status = "risk" if bad else ("watch" if warn else "ok")
    return _auto("redflag", "finance", "财务红旗", status, detail=detail,
                 hint="fraud红旗/Altman Z/Beneish M 三合一;任一高危即标红")


def _mcap_item(total_mv: Optional[float]) -> dict:
    if not isinstance(total_mv, (int, float)) or total_mv <= 0:
        return _auto("mcap", "price", "市值规模", "missing",
                     hint="千亿大公司/百亿中型/十亿小型")
    yi = total_mv / 1e8
    if yi >= 1e4:
        label = "万亿级"
    elif yi >= 1e3:
        label = "千亿级"
    elif yi >= 1e2:
        label = "百亿级"
    else:
        label = "十亿级及以下"
    return _auto("mcap", "price", "市值规模", "ok", value=label,
                 detail=f"总市值 {yi:,.0f} 亿元",
                 hint="和同市值公司横向对比,可简单判断市值是否合理(六个吉利)")


def _band_item(band_data: Optional[dict], key: str, title: str,
               metric: str) -> dict:
    band = (band_data or {}).get("band")
    if not band or not band.get("state"):
        return _auto(key, "price", title, "missing",
                     hint=f"{metric} 均值±1σ 估值带(8年窗)")
    state = band["state"]
    status_map = {"超跌": "ok", "合理偏低": "ok",
                  "合理偏高": "watch", "虚高": "risk"}
    status = status_map.get(state, "missing")
    return _auto(
        key, "price", title, status, value=state,
        detail=(f"当前 {band_data.get('current')},"
                f"μ={band.get('mean')},σ={band.get('std')},"
                f"z={band.get('z_score')}(样本{band_data.get('sample_size')})"),
        hint=("PE只适用于利润稳定的大公司;成长型看PS更合适。"
              if metric == "PE" else
              "市销率=市值/总营收,适合利润不稳或高增长公司"))


def _kline_item(trend: Optional[dict]) -> dict:
    if not trend or not trend.get("state"):
        return _auto("kline", "price", "K线趋势", "missing",
                     hint="判断上升/下降/横盘短期走势(参考《技术分析》普林格)")
    state = trend["state"]
    status = "ok" if state == "上升" else "watch"
    return _auto("kline", "price", "K线趋势", status, value=state,
                 detail=(f"MA20={trend.get('ma20')} MA60={trend.get('ma60')} "
                         f"MA120={trend.get('ma120')},"
                         f"120日日均变化 {trend.get('slope_pct')}%"),
                 hint="短期走势参考;到这里股价高低心里基本有数了")


def _concentration_item(conc: Optional[dict]) -> dict:
    v = (conc or {}).get("verdict")
    v_map = {"concentrating": ("ok", "筹码集中(户数连减,主力收集)"),
             "dispersing": ("watch", "筹码分散(户数连增,散户化)"),
             "stable": ("watch", "筹码稳定")}
    if v not in v_map:
        return _auto("chips", "price", "筹码参考(代理)", "missing",
                     hint="获利比例无数据源,以股东户数集中度作代理")
    status, label = v_map[v]
    return _auto("chips", "price", "筹码参考(代理)", status, value=label,
                 detail=f"verdict={v}",
                 hint="代理指标:基本面稳定+估值合理+筹码获利比例低时买入,短期被套概率低")


def _bargain_item(forces: Optional[list]) -> dict:
    by_key = {f.get("key"): f for f in (forces or [])}
    sup = by_key.get("supplier", {}).get("score")
    buy = by_key.get("buyer", {}).get("score")
    scores = [s for s in (sup, buy) if isinstance(s, (int, float))]
    if not scores:
        return _auto("bargain", "industry", "上下游议价能力", "missing",
                     hint="供应商议价力决定成本稳定性;客户议价力决定业绩与应收健康",
                     editable=True, note_key=BARGAIN_NOTE_KEY)
    avg = sum(scores) / len(scores)
    status = "ok" if avg >= 60 else ("watch" if avg >= 40 else "risk")
    detail = (f"供应商 {sup if sup is not None else '无'} / "
              f"客户 {buy if buy is not None else '无'}(0-100,高=对公司有利)")
    return _auto("bargain", "industry", "上下游议价能力", status,
                 value=f"均分 {avg:.0f}", detail=detail,
                 hint="五力自动结论;可在下方补充自己的判断(先自动后可编辑)",
                 editable=True, note_key=BARGAIN_NOTE_KEY)


# ── 组装 ──────────────────────────────────────────────────────────

def manual_filled(item: dict, row: Optional[dict]) -> bool:
    """已填判定:choice 类看 value_choice;text 类看 value_text(trim)。"""
    if not row:
        return False
    if item["input_type"] in ("choice", "choice+text"):
        return bool((row.get("value_choice") or "").strip())
    return bool((row.get("value_text") or "").strip())


def build_checklist(sources: dict, saved: dict) -> dict:
    """组装完整 GET 响应 data(纯函数,任一源缺失→missing)。

    sources 键:profile / income_annual / roe_annual / roe_pctile /
    five_forces(forces 列表) / sections_latest / liquidity / payout /
    fraud / z / m / band_pe / band_ps / kline_trend / concentration
    saved: {item_key: {value_text, value_choice, updated_at}}
    """
    s = sources or {}
    forces = (s.get("five_forces") or {}).get("forces")
    bargain = _bargain_item(forces)
    note_row = saved.get(BARGAIN_NOTE_KEY)
    bargain["note_text"] = (note_row or {}).get("value_text")
    bargain["note_updated_at"] = (note_row or {}).get("updated_at")
    sections = [
        {"key": "company", "title": _SECTIONS_META[0]["title"],
         "items": [_i for _i in (
             _manual_item(mi, saved) for mi in MANUAL_ITEMS
             if mi["section"] == "company")]},
        {"key": "industry", "title": _SECTIONS_META[1]["title"],
         "items": (
             [_industry_item(s.get("profile")),
              bargain]
             + [_manual_item(mi, saved) for mi in MANUAL_ITEMS
                if mi["section"] == "industry"])},
        {"key": "finance", "title": _SECTIONS_META[2]["title"],
         "items": [_growth_item(s.get("income_annual")),
                   _balance_item(s.get("liquidity")),
                   _roe_item(s.get("roe_annual"), s.get("roe_pctile")),
                   _dividend_item(s.get("payout")),
                   _redflag_item(s.get("fraud"), s.get("z"), s.get("m"))]},
        {"key": "price", "title": _SECTIONS_META[3]["title"],
         "items": [_mcap_item((s.get("profile") or {}).get("total_mv")),
                   _band_item(s.get("band_pe"), "band_pe", "PE 估值带", "PE"),
                   _band_item(s.get("band_ps"), "band_ps", "PS 估值带", "PS"),
                   _kline_item(s.get("kline_trend")),
                   _concentration_item(s.get("concentration"))]},
    ]
    # 2.3 竞争格局的 CR4/HHI 参考塞进行业区参考字段(不做独立项)
    sec_ref = s.get("sections_latest")
    out = {"sections": sections}
    out.update(progress(sections))
    out["references"] = {
        "moat": s.get("moat"),
        "shareholders": s.get("shareholders"),
        "industry_latest": sec_ref,
        "profile": s.get("profile"),
    }
    return out


def _manual_item(mi: dict, saved: dict) -> dict:
    row = saved.get(mi["key"])
    item = {"key": mi["key"], "type": "manual", "section": mi["section"],
            "title": mi["title"], "input_type": mi["input_type"],
            "choices": mi.get("choices"),
            "course": mi.get("course"),
            "value_text": (row or {}).get("value_text"),
            "value_choice": (row or {}).get("value_choice"),
            "updated_at": (row or {}).get("updated_at"),
            "status": "filled" if manual_filled(mi, row) else "pending"}
    return item


def progress(sections: list) -> dict:
    """统计手动/自动进度。"""
    manual_total = manual_filled_n = 0
    auto = {"ok": 0, "watch": 0, "risk": 0, "missing": 0}
    for sec in sections:
        for it in sec["items"]:
            if it["type"] == "manual":
                manual_total += 1
                manual_filled_n += 1 if it["status"] == "filled" else 0
            else:
                auto[it["status"]] = auto.get(it["status"], 0) + 1
    return {"manual_progress": {"filled": manual_filled_n,
                                "total": manual_total},
            "auto_progress": auto}


def sanitize_items(raw_items: list) -> list:
    """PUT 载荷净化:丢弃非法 item_key;空串→None(清除语义)。

    value 可能是数字等非字符串(前端未强转)→ 先 str() 再 strip 防护;
    元素本身非 dict(畸形载荷)→ 跳过,不抛 AttributeError。
    """
    valid = {mi["key"] for mi in MANUAL_ITEMS} | {BARGAIN_NOTE_KEY}
    out = []
    for it in raw_items or []:
        if not isinstance(it, dict):
            continue
        k = str(it.get("item_key") or "").strip()
        if k not in valid:
            continue
        out.append({
            "item_key": k,
            "value_text": str(it.get("value_text") or "").strip() or None,
            "value_choice": str(it.get("value_choice") or "").strip() or None,
        })
    return out
