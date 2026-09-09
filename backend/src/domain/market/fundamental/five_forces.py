"""波特五力评分（纯函数）。

课程 14 集宁德时代案例的量化落地：五种力量组合决定行业盈利能力，
"从财务结构中找证据"。分越高=环境对企业越有利。

归一化三器 + 三档阈值器：
- _score: 行业分布四分位锚点映射（p25→25/p50→50/p75→75 区间线性）
- _trend_score: 近3期斜率（改善→高分），用于趋势类因子
- _absolute_score: 绝对强度分档（研发费率等无行业分布可比的指标）
- _tier: 双阈值三档分映射（t1/t2 + low/mid/high，语义同 _score）

five_forces(data) 主入口：data = {ratios, cashflow, industry}（spec §2），
输出 {forces: [{key, label, score, evidence}], total_score, note?}。
五力权重（spec §2 表，改数字必须同步 spec）：
- supplier: 应付天数趋势0.4 / 毛利率σ0.3 / 毛利率vs行业0.3
- buyer: 应收天数趋势0.35 / 收现比0.35 / 行业CR4 0.3
- barrier: 行业ROE中位0.4 / 行业HHI 0.3 / 营收规模分位0.3
- substitute: 行业营收同比0.5 / 研发费率0.5
- rivalry: CR4趋势0.3 / 市占率0.3 / 毛利率vs行业0.2 / ROE分位0.2
缺失因子剔除后权重重新归一；全缺 → 该力 score None + note。
总分 = 五力等权（None 剔除）。
"""
from statistics import pstdev

FORCES_META = [
    {"key": "supplier", "label": "供应商议价能力"},
    {"key": "buyer", "label": "购买者议价能力"},
    {"key": "barrier", "label": "进入壁垒"},
    {"key": "substitute", "label": "替代品威胁"},
    {"key": "rivalry", "label": "同业竞争格局"},
]


def _score(value, p25, p50, p75, invert=False):
    """四分位锚点 0-100 映射（区间线性；超出锚点按邻近段斜率外延，clamp[0,100]）。"""
    if value is None:
        return None
    if p25 is None or p50 is None or p75 is None or p25 == p75:
        return 50.0  # 分布退化→中性
    anchors = [(p25, 25.0), (p50, 50.0), (p75, 75.0)]
    pts = anchors if not invert else [(a, 100.0 - s) for a, s in anchors]
    segs = [(a, b) for a, b in zip(pts, pts[1:]) if b[0] != a[0]]
    if value <= pts[0][0]:
        (x0, y0), (x1, y1) = segs[0]
    elif value >= pts[-1][0]:
        (x0, y0), (x1, y1) = segs[-1]
    else:
        for (x0, y0), (x1, y1) in segs:
            if x0 <= value <= x1:
                break
    out = y0 + (value - x0) / (x1 - x0) * (y1 - y0)
    return max(0.0, min(100.0, out))


def _trend_score(series):
    """近3期斜率→0-100（series 最新在前；改善=高分）。
    斜率以均值归一（防量级失真）：slope/mean 映射 [-0.1, +0.1]→[0,100]。"""
    vals = [x for x in (series or [])[:3] if x is not None]
    if len(vals) < 2:
        return None
    # 最新在前：斜率 = (最新-最旧)/(期数-1)，除以均值归一
    mean = sum(vals) / len(vals)
    if mean == 0:
        return 50.0
    slope = (vals[0] - vals[-1]) / (len(vals) - 1)
    norm = slope / abs(mean)
    return max(0.0, min(100.0, (norm + 0.1) / 0.2 * 100.0))


def _absolute_score(value):
    """研发费率绝对分档：<2%→0~25、2~5%→25~50、≥5%→50~100 三段线性。
    （0.035→37.5、0.06→70——测试断言按此公式；锚点 2%→25、5%→50、≥7.5%→100）"""
    if value is None:
        return None
    if value < 0.02:
        return max(0.0, value / 0.02 * 25.0)
    if value < 0.05:
        return 25.0 + (value - 0.02) / 0.03 * 25.0
    return min(100.0, 50.0 + (value - 0.05) / 0.025 * 50.0)


def _tier(v, t1, t2, low, mid, high):
    """三档阈值 0-100 映射（锚点 t1→low、(t1+t2)/2→mid、t2→high；区间线性，
    超出锚点按邻近段斜率外延后 clamp[0,100]，语义同 _score；t1==t2 退化→mid）。

    因子分档阈值（与 spec §2 权重表同源，改动须同步 spec）：
    - 毛利率σ（百分点，越低越好）：3/8 → 75/50/25
    - 收现比 cash_to_revenue：0.8/1.0 → 25/50/75
    - 行业 ROE 中位数（%）：8/15 → 25/50/75
    - 行业 HHI：1500/2500 → 25/50/75
    - 行业营收同比 revenue_yoy：0/0.10 → 25/50/75
    - 市占率 revenue_share：0.02/0.10 → 25/50/75
    """
    if v is None:
        return None
    if t1 is None or t2 is None or t1 == t2:
        return float(mid) if mid is not None else None
    midpt = (t1 + t2) / 2.0
    pts = [(t1, float(low)), (midpt, float(mid)), (t2, float(high))]
    segs = [(a, b) for a, b in zip(pts, pts[1:]) if b[0] != a[0]]
    if v <= pts[0][0]:
        (x0, y0), (x1, y1) = segs[0]
    elif v >= pts[-1][0]:
        (x0, y0), (x1, y1) = segs[-1]
    else:
        for (x0, y0), (x1, y1) in segs:
            if x0 <= v <= x1:
                break
    out = y0 + (v - x0) / (x1 - x0) * (y1 - y0)
    return max(0.0, min(100.0, out))


# ---------------------------------------------------------------------------
# 五力计算（输入结构见 spec §2：ratios/cashflow periods 最新在前 + industry）
# ---------------------------------------------------------------------------


def _ratio_series(periods, key, n=5):
    """从 periods（最新在前）提取 ratios[key] 近 n 期序列（保留 None 占位）。"""
    return [(p.get("ratios") or {}).get(key) for p in (periods or [])[:n]]


def _latest_ratio(periods, key):
    """最新一个非 None 的 ratios[key]（periods 最新在前）。"""
    for p in periods or []:
        v = (p.get("ratios") or {}).get(key)
        if v is not None:
            return v
    return None


def _rd_intensity(periods):
    """最新一期 研发费率 = rd_expense/revenue（revenue≤0 或缺 → None）。"""
    for p in periods or []:
        vals = p.get("values") or {}
        rd, rev = vals.get("rd_expense"), vals.get("revenue")
        if rd is not None and rev is not None and rev > 0:
            return rd / rev
    return None


def _sections(industry):
    return (industry or {}).get("sections") or []


def _adequate_sections(industry):
    """充足期 sections（sample_count≥8），跳过披露中段稀薄期；
    无充足期时退回原始列表（同 _latest_section 兜底语义）；
    sample_count 缺失视为充足（兼容省略该键的数据源/测试夹具）。"""
    secs = _sections(industry)
    adequate = [s for s in secs if (s.get("sample_count") or 8) >= 8]
    return adequate or secs


def _latest_section(industry):
    """最新充足期截面：跳过 sample_count 不足(<8)的披露中段稀薄期
    （与 industry_peers 端点"最新充足期"规则一致）；无充足期时退回
    sections[0]；sample_count 缺失视为充足（兼容省略该键的数据源/
    测试夹具）。空 sections 返回 {}（保持原契约，调用方直接 .get）。"""
    secs = _adequate_sections(industry)
    return secs[0] if secs else {}


def _dist(industry, metric):
    return (_latest_section(industry).get("distribution") or {}).get(
        metric) or {}


def _target(industry):
    return (industry or {}).get("target") or {}


def _first_not_none(series):
    return next((v for v in series if v is not None), None)


def _band(score, high, mid, low):
    """三档取词：≥67→high、34~67→mid、<34→low（score None 不在此调用）。"""
    if score >= 67.0:
        return high
    if score >= 34.0:
        return mid
    return low


def _ev(metric, value, score, text_fn=None, unit=None, trend=None):
    """证据结构 {metric, value, unit?, trend?, interpretation}。
    因子缺失（score None）→ interpretation 固定'数据缺失'文案。"""
    e = {
        "metric": metric,
        "value": round(value, 4) if isinstance(value, (int, float))
                 and not isinstance(value, bool) else None,
        "interpretation": (text_fn() if score is not None and text_fn
                           else "数据缺失，该因子已剔除"),
    }
    if unit:
        e["unit"] = unit
    if trend and any(v is not None for v in trend):
        e["trend"] = [round(v, 4) if isinstance(v, (int, float)) else None
                      for v in trend]
    return e


def _weighted(parts):
    """[(score, weight)]：None 因子剔除后权重再归一；全 None → None。"""
    valid = [(s, w) for s, w in parts if s is not None]
    if not valid:
        return None
    tw = sum(w for _, w in valid)
    return round(sum(s * w for s, w in valid) / tw, 2)


def _pct100(pct):
    """0~1 分位 → ×100（clamp）。"""
    if pct is None:
        return None
    return max(0.0, min(100.0, pct * 100.0))


def _gm_vs_industry(ratios, industry):
    """毛利率 vs 行业分布（supplier/rivalry 共用因子，_score）。"""
    gm = _latest_ratio(ratios, "gross_margin")
    dist = _dist(industry, "gross_margin")
    usable = bool(industry) and any(
        dist.get(k) is not None for k in ("p25", "median", "p75"))
    s = (_score(gm, dist.get("p25"), dist.get("median"), dist.get("p75"))
         if usable else None)
    med = dist.get("median")

    def _text():
        med_t = f"{med:.1f}%" if med is not None else "—"
        return (f"毛利率{gm:.1f}% vs 行业中位{med_t}，"
                f"{_band(s, '显著领先行业', '与行业相当', '落后行业')}")

    return s, _ev("毛利率vs行业", gm, s, text_fn=_text, unit="pct")


def _force_supplier(ratios, industry):
    """供应商议价能力（分越高=企业对供应商越强势）。
    应付天数趋势0.4（应付变长=占款强）+ 毛利率σ0.3（近5期总体标准差，
    σ<3→75/3~8→50/>8→25）+ 毛利率vs行业0.3（_score vs gross_margin 分布）。"""
    pay_series = _ratio_series(ratios, "payable_days")
    s_trend = _trend_score(pay_series)
    pay_latest = _first_not_none(pay_series)
    n_pay = len([v for v in pay_series if v is not None])
    gms = [v for v in _ratio_series(ratios, "gross_margin") if v is not None]
    # 总体标准差（pstdev；n<2 → None）
    sigma = pstdev(gms) if len(gms) >= 2 else None
    s_gm = _tier(sigma, 3.0, 8.0, 75.0, 50.0, 25.0)
    s_vs, ev_vs = _gm_vs_industry(ratios, industry)
    evidence = [
        _ev("应付账款周转天数趋势", pay_latest, s_trend, unit="day",
            trend=pay_series,
            text_fn=lambda: f"应付账款周转{pay_latest:.0f}天，近{n_pay}期"
                            f"占款能力{_band(s_trend, '增强', '平稳', '减弱')}"),
        _ev("毛利率稳定性", sigma, s_gm, unit="pct", trend=gms,
            text_fn=lambda: f"毛利率近{len(gms)}期波动σ={sigma:.1f}个百分点，"
                            f"盈利{_band(s_gm, '稳定', '较稳定', '波动大')}"),
        ev_vs,
    ]
    return _weighted([(s_trend, 0.4), (s_gm, 0.3), (s_vs, 0.3)]), evidence


def _force_buyer(ratios, cashflow, industry):
    """购买者议价能力（分越高=企业对下游越强势）。
    应收天数趋势0.35（应收变短=改善，趋势分翻转）+ 收现比0.35
    （≥1→75/0.8~1→50/<0.8→25）+ 行业CR4 0.3（_score 0~1 域锚点0.25/0.5/0.75）。"""
    rec_series = _ratio_series(ratios, "receivable_days")
    s_trend = _trend_score(rec_series)
    s_trend = 100.0 - s_trend if s_trend is not None else None  # invert
    rec_latest = _first_not_none(rec_series)
    n_rec = len([v for v in rec_series if v is not None])
    c2r = _latest_ratio(cashflow, "cash_to_revenue")
    s_c2r = _tier(c2r, 0.8, 1.0, 25.0, 50.0, 75.0)
    cr4 = _latest_section(industry).get("cr4") if industry else None
    s_cr4 = _score(cr4, 0.25, 0.5, 0.75) if cr4 is not None else None
    evidence = [
        _ev("应收账款周转天数趋势", rec_latest, s_trend, unit="day",
            trend=rec_series,
            text_fn=lambda: f"应收账款周转{rec_latest:.0f}天，近{n_rec}期"
                            f"回款{_band(s_trend, '加快', '平稳', '变慢')}"),
        _ev("收现比", c2r, s_c2r, unit="x",
            text_fn=lambda: f"收现比{c2r:.2f}，销售回款质量"
                            f"{_band(s_c2r, '优', '中', '差')}"),
        _ev("行业CR4", cr4, s_cr4,
            text_fn=lambda: f"行业CR4={cr4:.2f}，集中度"
                            f"{_band(s_cr4, '高', '中', '低')}，"
                            f"下游客户相对分散"),
    ]
    return _weighted([(s_trend, 0.35), (s_c2r, 0.35), (s_cr4, 0.3)]), evidence


def _force_barrier(industry):
    """进入壁垒（分越高=壁垒越厚）。
    行业ROE中位0.4（<8%→25/8~15%→50/>15%→75）+ 行业HHI 0.3
    （<1500→25/1500~2500→50/>2500→75）+ 营收规模分位0.3（percentile×100）。"""
    roe_med = _dist(industry, "roe").get("median") if industry else None
    s_roe = _tier(roe_med, 8.0, 15.0, 25.0, 50.0, 75.0)
    hhi = _latest_section(industry).get("hhi") if industry else None
    s_hhi = _tier(hhi, 1500.0, 2500.0, 25.0, 50.0, 75.0)
    pct = _target(industry).get("percentile_revenue")
    s_pct = _pct100(pct)
    evidence = [
        _ev("行业ROE中位数", roe_med, s_roe, unit="pct",
            text_fn=lambda: f"行业ROE中位数{roe_med:.1f}%，行业盈利"
                            f"{_band(s_roe, '丰厚', '中等', '微薄')}"),
        _ev("行业HHI", hhi, s_hhi,
            text_fn=lambda: f"行业HHI={hhi:.0f}，集中度"
                            f"{_band(s_hhi, '高', '中', '低')}"),
        _ev("营收规模分位", pct, s_pct,
            text_fn=lambda: f"营收规模行业分位{pct * 100:.0f}%，规模壁垒"
                            f"{_band(s_pct, '高', '中', '低')}"),
    ]
    return _weighted([(s_roe, 0.4), (s_hhi, 0.3), (s_pct, 0.3)]), evidence


def _force_substitute(ratios, industry):
    """替代品威胁（分越高=威胁越小）。
    行业营收同比0.5（<0→25/0~10%→50/>10%→75）
    + 研发费率0.5（_absolute_score 绝对分档：2%→25/5%→50/≥7.5%→100）。"""
    yoy = _latest_section(industry).get("revenue_yoy") if industry else None
    s_yoy = _tier(yoy, 0.0, 0.10, 25.0, 50.0, 75.0)
    rd = _rd_intensity(ratios)
    s_rd = _absolute_score(rd)
    evidence = [
        # 证据值×100：前端 unit="pct" 约定为"已是百分数单位"
        # （同 gross_margin=91.0）；score 计算仍用原始 0~1 分数
        _ev("行业营收同比", yoy * 100 if yoy is not None else None, s_yoy,
            unit="pct",
            text_fn=lambda: f"行业营收同比{yoy * 100:.1f}%，行业景气"
                            f"{_band(s_yoy, '上行', '平稳', '下行')}"),
        _ev("研发费率", rd * 100 if rd is not None else None, s_rd,
            unit="pct",
            text_fn=lambda: f"研发费率{rd * 100:.2f}%，技术壁垒"
                            f"{_band(s_rd, '高', '中', '低')}"),
    ]
    return _weighted([(s_yoy, 0.5), (s_rd, 0.5)]), evidence


def _force_rivalry(ratios, industry):
    """同业竞争格局（分越高=格局越有利）。
    CR4趋势0.3（近5期集中化=高分）+ 市占率0.3（<2%→25/2~10%→50/>10%→75）
    + 毛利率vs行业0.2（_score）+ ROE分位0.2（percentile×100）。"""
    # 趋势窗口同走充足期过滤（992a223 同规则），防稀薄期 cr4 污染
    cr4_series = [s.get("cr4") for s in _adequate_sections(industry)[:5]]
    s_trend = _trend_score(cr4_series)
    cr4_latest = _first_not_none(cr4_series)
    n_cr4 = len([v for v in cr4_series if v is not None])
    share = _target(industry).get("revenue_share")
    s_share = _tier(share, 0.02, 0.10, 25.0, 50.0, 75.0)
    s_vs, ev_vs = _gm_vs_industry(ratios, industry)
    pct_roe = _target(industry).get("percentile_roe")
    s_proe = _pct100(pct_roe)
    evidence = [
        _ev("CR4趋势", cr4_latest, s_trend, trend=cr4_series,
            text_fn=lambda: f"CR4={cr4_latest:.2f}，近{n_cr4}期格局"
                            f"{_band(s_trend, '集中化', '稳定', '分散化')}"),
        _ev("市占率", share * 100 if share is not None else None, s_share,
            unit="pct",  # 值×100，同 gross_margin 百分数单位约定
            text_fn=lambda: f"市占率{share * 100:.1f}%，行业地位"
                            f"{_band(s_share, '龙头', '中游', '尾部')}"),
        ev_vs,
        _ev("ROE行业分位", pct_roe, s_proe,
            text_fn=lambda: f"ROE行业分位{pct_roe * 100:.0f}%，盈利能力"
                            f"{_band(s_proe, '领先', '居中', '落后')}"),
    ]
    return _weighted(
        [(s_trend, 0.3), (s_share, 0.3), (s_vs, 0.2), (s_proe, 0.2)],
    ), evidence


def five_forces(data):
    """波特五力评分主入口（spec §2）。

    data = {
      ratios:   ratio-analysis 响应 periods（list，最新在前）,
      cashflow: cashflow-analysis 响应 periods,
      industry: industry_peers 响应 {industry, sections, peers, target} | None,
    } → {
      forces: [{key, label, score: 0-100|None,
                evidence: [{metric, value, unit?, trend?, interpretation}]}],
      total_score: 0-100|None,   # 五力等权（None 剔除）
      note?: str,                # 无行业归属/有力 None 时标注
    }
    """
    data = data or {}
    ratios = data.get("ratios") or []
    cashflow = data.get("cashflow") or []
    industry = data.get("industry")

    calcs = {
        "supplier": lambda: _force_supplier(ratios, industry),
        "buyer": lambda: _force_buyer(ratios, cashflow, industry),
        "barrier": lambda: _force_barrier(industry),
        "substitute": lambda: _force_substitute(ratios, industry),
        "rivalry": lambda: _force_rivalry(ratios, industry),
    }
    forces, notes = [], []
    if industry is None:
        notes.append("无行业归属，行业类因子缺失")
    for meta in FORCES_META:
        score, evidence = calcs[meta["key"]]()
        forces.append({"key": meta["key"], "label": meta["label"],
                       "score": score, "evidence": evidence})
        if score is None:
            notes.append(f"{meta['label']}数据不足")
    scored = [f["score"] for f in forces if f["score"] is not None]
    out = {"forces": forces,
           "total_score": round(sum(scored) / len(scored), 2) if scored
                          else None}
    if not scored:
        notes.append("五力均无法评分")
    if notes:
        out["note"] = "；".join(notes)
    return out
