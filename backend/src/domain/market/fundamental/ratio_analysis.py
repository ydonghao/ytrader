"""比率分析（Ratio Analysis）纯函数。

跨报表计算 27 个核心财务比率，五组：
  - profitability 盈利能力：毛利率 / 净利率 / ROE / ROA / ROIC
  - solvency     偿债能力：资产负债率 / 流动比率 / 速动比率 / 利息保障倍数
  - efficiency   营运能力：存货 / 应收账款 / 应付账款 / 流动资产 /
                  固定资产 / 总资产周转率及各自周转天数（天数=365/周转率）
  - growth       成长能力：营收 / 净利润 / 总资产同比增长率
  - capital_cost 资本成本：投资资本 / WACC / 经济利润（肖星《财务分析与决策》
                  经济利润章；权益成本由调用方注入，None 时 WACC/经济利润
                  退化 None，投资资本照常）

口径约定（对齐 common_size.py / quality.py）：缺失/分母 ≤ 0 → None 不抛异常；
全部比率按报告期累计、不年化（Q3 报表算出的 ROE 即"前三季 ROE"）；
ROE/ROA/周转率分母 = 期初期末平均余额（首期缺期初 → None）；
同比需去年同期在场且基数 > 0（负基数同比无意义）。

字段解析：英文固定列（stock_financial_detail 列）非 None 优先，否则按中文
候选名在 details（income/balance 两表 detail JSONB）中匹配，parse_amount 解析。
"""
from __future__ import annotations

from typing import Optional

try:
    from src.infra.database.market.financial_full import parse_amount
except Exception:  # pragma: no cover — 脱离后端环境时的最小兜底

    def parse_amount(v) -> Optional[float]:
        if isinstance(v, bool) or v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", "").replace(" ", "")
        if s in ("", "nan", "NaN", "None", "--", "null"):
            return None
        try:
            if s.endswith("亿"):
                return float(s[:-1]) * 1e8
            if s.endswith("万"):
                return float(s[:-1]) * 1e4
            return float(s)
        except ValueError:
            return None


# ── 分组与比率元数据（groups 随 API 下发，前端不重复维护定义）──
GROUPS: list[dict] = [
    {"key": "profitability", "label": "盈利能力"},
    {"key": "solvency", "label": "偿债能力"},
    {"key": "efficiency", "label": "营运能力"},
    {"key": "growth", "label": "成长能力"},
    {"key": "capital_cost", "label": "资本成本"},
]

RATIO_META: list[dict] = [
    {"key": "gross_margin", "label": "毛利率", "group": "profitability",
     "unit": "pct", "formula": "(营业总收入-营业成本)/营业总收入"},
    {"key": "net_margin", "label": "净利率", "group": "profitability",
     "unit": "pct", "formula": "净利润/营业总收入"},
    {"key": "roe", "label": "ROE", "group": "profitability",
     "unit": "pct", "formula": "净利润/平均净资产"},
    {"key": "roa", "label": "ROA", "group": "profitability",
     "unit": "pct", "formula": "净利润/平均总资产"},
    {"key": "roic", "label": "ROIC", "group": "profitability",
     "unit": "pct",
     "formula": "EBIT×(1-有效税率)/平均投入资本；EBIT≈利润总额(缺则营业利润)；"
                "有效税率=所得税/利润总额(缺失按0)；投入资本=股东权益+短期借款+"
                "长期借款(格林布拉特口径，同 derived_metrics)"},
    {"key": "debt_ratio", "label": "资产负债率", "group": "solvency",
     "unit": "pct", "formula": "总负债/总资产"},
    {"key": "current_ratio", "label": "流动比率", "group": "solvency",
     "unit": "x", "formula": "流动资产合计/流动负债合计"},
    {"key": "quick_ratio", "label": "速动比率", "group": "solvency",
     "unit": "x", "formula": "(流动资产合计-存货)/流动负债合计"},
    {"key": "interest_cover", "label": "利息保障倍数", "group": "solvency",
     "unit": "x",
     "formula": "EBIT/利息费用（EBIT≈利润总额，缺则营业利润；利息费用候选："
                "利息费用/利息支出/财务费用）"},
    {"key": "inventory_turnover", "label": "存货周转率",
     "group": "efficiency", "unit": "x",
     "formula": "营业成本/平均存货（累计口径未年化）"},
    {"key": "inventory_days", "label": "存货周转天数", "group": "efficiency",
     "unit": "day", "formula": "365/存货周转率"},
    {"key": "receivable_turnover", "label": "应收账款周转率",
     "group": "efficiency", "unit": "x",
     "formula": "营业总收入/平均应收账款（累计口径未年化）"},
    {"key": "receivable_days", "label": "应收账款周转天数",
     "group": "efficiency", "unit": "day",
     "formula": "365/应收账款周转率"},
    {"key": "payable_turnover", "label": "应付账款周转率",
     "group": "efficiency", "unit": "x",
     "formula": "营业收入/平均应付账款"},
    {"key": "payable_days", "label": "应付账款周转天数",
     "group": "efficiency", "unit": "day",
     "formula": "365/应付账款周转率"},
    {"key": "current_asset_turnover", "label": "流动资产周转率",
     "group": "efficiency", "unit": "x",
     "formula": "营业总收入/平均流动资产（累计口径未年化）"},
    {"key": "current_asset_days", "label": "流动资产周转天数",
     "group": "efficiency", "unit": "day",
     "formula": "365/流动资产周转率"},
    {"key": "fixed_asset_turnover", "label": "固定资产周转率",
     "group": "efficiency", "unit": "x",
     "formula": "营业总收入/平均固定资产（累计口径未年化）"},
    {"key": "fixed_asset_days", "label": "固定资产周转天数",
     "group": "efficiency", "unit": "day",
     "formula": "365/固定资产周转率"},
    {"key": "asset_turnover", "label": "总资产周转率", "group": "efficiency",
     "unit": "x", "formula": "营业总收入/平均总资产（累计口径未年化）"},
    {"key": "asset_days", "label": "总资产周转天数", "group": "efficiency",
     "unit": "day", "formula": "365/总资产周转率"},
    {"key": "revenue_growth", "label": "营收增长率", "group": "growth",
     "unit": "growth", "formula": "营业总收入同比-1"},
    {"key": "profit_growth", "label": "净利润增长率", "group": "growth",
     "unit": "growth", "formula": "净利润同比-1"},
    {"key": "asset_growth", "label": "总资产增长率", "group": "growth",
     "unit": "growth", "formula": "总资产同比-1"},
    {"key": "invested_capital", "label": "投资资本", "group": "capital_cost",
     "unit": "yi",
     "formula": "股东权益+短期借款+长期借款（期末时点，元；格林布拉特口径未扣超额现金）"},
    {"key": "wacc", "label": "加权平均资本成本", "group": "capital_cost",
     "unit": "pct",
     "formula": "债务权重×4.5%×(1-有效税率)+权益权重×权益成本；权重=期末时点占比；"
                "有效税率=所得税/利润总额(clamp[0,1]缺失按0)；"
                "权益成本=所属申万行业最新年报期ROE中位数（handler注入）"},
    {"key": "economic_profit", "label": "经济利润", "group": "capital_cost",
     "unit": "yi",
     "formula": "(ROIC-WACC)×平均投资资本；ROIC分母同源（平均口径）；元"},
]

# detail 中文候选名（A 股同花顺在前、港股东财在后；'*' 前缀为同花顺重述科目）
DETAIL_CANDIDATES: dict[str, list[str]] = {
    "revenue": ["一、营业总收入", "*营业总收入", "营业收入", "营业额", "营业收益"],
    "operating_cost": ["其中：营业成本", "营业成本", "营运支出", "销售成本"],
    "net_profit": ["五、净利润", "*净利润", "除税后溢利"],
    "operating_profit": ["三、营业利润", "*营业利润", "经营溢利"],
    "total_assets": ["*资产合计", "资产合计", "总资产", "资产总额"],
    "total_liabilities": ["*负债合计", "负债合计", "总负债", "负债总额"],
    "equity": ["所有者权益（或股东权益）合计",
               "*所有者权益（或股东权益）合计", "权益总额", "总权益",
               "所有者权益合计"],
    "inventory": ["存货", "库存"],
    "fixed_assets": ["固定资产合计", "*固定资产合计", "其中：固定资产",
                     "物业、厂房及设备", "物业厂房及设备", "固定资产"],
    "accounts_receivable": ["应收账款", "贸易及其他应收款"],
    # 应付无固定列（_BALANCE_MAP 无"应付账款"）→ 只走候选名解析；
    # "应付票据及应付账款"为同花顺合并科目（茅台实测）
    "accounts_payable": ["应付账款", "*应付账款", "应付票据及应付账款",
                         "*应付票据及应付账款"],
    "current_assets": ["*流动资产合计", "流动资产合计", "流动资产总值"],
    "current_liabilities": ["*流动负债合计", "流动负债合计", "流动负债总值"],
    "ebt": ["利润总额", "*利润总额", "四、利润总额", "*四、利润总额",
            "除税前溢利", "税前利润"],
    "tax": ["所得税费用", "*所得税费用", "减：所得税费用", "*减：所得税费用",
            "其中：所得税费用", "所得税", "所得税开支", "税项"],
    "short_loan": ["短期借款", "*短期借款", "短期银行借款"],
    "long_loan": ["长期借款", "*长期借款", "长期银行借款"],
    "interest_expense": ["其中：利息费用", "利息费用", "利息支出", "融资成本",
                         "财务费用"],
}

ALL_FIELDS: list[str] = list(DETAIL_CANDIDATES.keys())

# 有英文固定列的语义字段（stock_financial_detail 列名与语义名一致）。
# ebt/tax 无真实固定列：列入后 handler 按 FIXED_FIELDS 建 fin 时 getattr 得
# None，仍回落 detail 中文候选（生产行为不变）；同时允许调用方以英文键经
# fin 直传（测试/未来入库列），享固定列优先级。
FIXED_FIELDS: frozenset = frozenset({
    "revenue", "operating_cost", "net_profit", "operating_profit",
    "total_assets", "total_liabilities", "equity", "inventory",
    "accounts_receivable", "fixed_assets", "short_loan", "long_loan",
    "ebt", "tax",
})


def _pick_amount(detail: dict, candidates: list[str]) -> Optional[float]:
    """按候选顺序取首个数值非 None 的科目（模式抄 common_size._pick_amount）。"""
    for k in candidates:
        if isinstance(detail, dict) and k in detail:
            v = parse_amount(detail.get(k))
            if v is not None:
                return v
    return None


def resolve_metric_fields(fin: dict, details: list) -> dict:
    """单期字段归一：固定列非 None 优先 → 两表 detail 候选名兜底。

    Returns:
        ``{语义字段: float | None}``，覆盖 ALL_FIELDS 全部键。
    """
    fin = fin if isinstance(fin, dict) else {}
    details = [d for d in (details or []) if isinstance(d, dict)]
    out: dict[str, Optional[float]] = {}
    for field in ALL_FIELDS:
        v = None
        if field in FIXED_FIELDS:
            v = parse_amount(fin.get(field))
        if v is None:
            for d in details:
                v = _pick_amount(d, DETAIL_CANDIDATES[field])
                if v is not None:
                    break
        out[field] = v
    return out


def _div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """安全除：任一为 None 或分母 ≤ 0 → None。不舍入（由调用处终值舍入）。"""
    if num is None or den is None or den <= 0:
        return None
    return num / den


def _r4(x: Optional[float]) -> Optional[float]:
    """终值舍入（每个比率只在最终赋值处舍入一次，避免复合舍入丢精度）。"""
    return None if x is None else round(x, 4)


def _sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b


def _avg(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return (a + b) / 2.0


def _pct(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x * 100, 4)


def _days(rate: Optional[float]) -> Optional[float]:
    """周转天数 = 365/周转率；率缺失或 ≤ 0 → None；round 1 位。"""
    if rate is None or rate <= 0:
        return None
    return round(365.0 / rate, 1)


def _or_zero(x: Optional[float]) -> float:
    return 0.0 if x is None else x


COST_OF_DEBT = 0.045  # 债务资本成本≈5年期LPR（课程口径"贷款利率"）


def _effective_tax_rate(ebt: Optional[float], tax: Optional[float]) -> float:
    """有效税率 = 所得税/EBIT，clamp [0,1]；ebt 非正或税缺失 → 0.0。"""
    if ebt is None or ebt <= 0 or tax is None:
        return 0.0
    return min(max(tax / ebt, 0.0), 1.0)


def _nopat(ebit: Optional[float],
           tax: Optional[float]) -> Optional[float]:
    """NOPAT = EBIT×(1-有效税率)；有效税率=所得税/EBIT，clamp 到 [0,1]，
    税缺失按 0（退化为 EBIT，同 derived_metrics 口径）。"""
    if ebit is None:
        return None
    return ebit * (1.0 - _effective_tax_rate(ebit, tax))


def _invested_capital(v: dict) -> Optional[float]:
    """投入资本 = 股东权益 + 短期借款 + 长期借款（借款缺失按 0）。

    Greenblatt 口径（未扣超额现金），与 derived_metrics.py 一致；
    权益缺失 → None。
    """
    eq = v.get("equity")
    if eq is None:
        return None
    return eq + _or_zero(v.get("short_loan")) + _or_zero(v.get("long_loan"))


def _avg_invested_capital(v: dict, prev: Optional[dict]) -> Optional[float]:
    """平均投入资本；首期无期初 → None。"""
    cur = _invested_capital(v)
    if cur is None:
        return None
    if prev is None:
        return None
    old = _invested_capital(prev)
    if old is None:
        return None
    return (cur + old) / 2.0


def _date_str(rd) -> Optional[str]:
    """report_date 归一为 ISO 字符串（兼容 date 与 str）。"""
    if rd is None:
        return None
    if hasattr(rd, "isoformat"):
        return rd.isoformat()
    return str(rd)[:10]


def _year_ago(ds: Optional[str]) -> Optional[str]:
    """去年同日字符串（报告期均为季末，无 2/29 边缘）。"""
    if not ds or len(ds) < 4:
        return None
    try:
        return str(int(ds[:4]) - 1) + ds[4:]
    except ValueError:
        return None


def _build_groups() -> list[dict]:
    return [
        {
            "key": g["key"],
            "label": g["label"],
            "ratios": [
                {"key": m["key"], "label": m["label"],
                 "unit": m["unit"], "formula": m["formula"]}
                for m in RATIO_META if m["group"] == g["key"]
            ],
        }
        for g in GROUPS
    ]


def ratio_series(records: list[dict],
                 cost_of_equity: Optional[float] = None) -> dict:
    """多期比率计算（27 比率 × 每期）。

    Args:
        records: 升序 ``[{report_date: date|str, fin: dict,
          details: list[dict|None]}]``（fin=两表固定列合并，
          details=[income_detail, balance_detail]）。
        cost_of_equity: 权益资本成本（小数，如 0.0794；行业年报 ROE 中位数，
          由 handler 注入）。None → wacc/economic_profit 全期 None，
          invested_capital 照常（纯函数零 IO，向后兼容）。
    Returns:
        ``{"groups": [...], "periods": [{"report_date", "values", "ratios"}]}``
        periods 降序（最新在前）。values=resolve_metric_fields 完整结果
        + invested_capital（期末时点投资资本，元）。
    """
    resolved: list[dict] = []
    for r in records or []:
        r = r or {}
        ds = _date_str(r.get("report_date"))
        if ds is None:
            continue
        resolved.append({
            "ds": ds,
            "values": resolve_metric_fields(r.get("fin"), r.get("details")),
        })
    by_ds = {p["ds"]: p["values"] for p in resolved}

    periods: list[dict] = []
    for i, p in enumerate(resolved):
        v = p["values"]
        prev = resolved[i - 1]["values"] if i > 0 else None
        last = by_ds.get(_year_ago(p["ds"]))

        def avg_prev(field: str) -> Optional[float]:
            return _avg(v.get(field), prev.get(field)) if prev else None

        def yoy(field: str) -> Optional[float]:
            if last is None:
                return None
            cur, base = v.get(field), last.get(field)
            if cur is None or base is None or base <= 0:
                return None
            return round((cur / base - 1) * 100, 4)

        # 周转率先算（天数依赖），教科书口径：营业收入/平均余额，未年化
        receivable_turn = _div(v.get("revenue"),
                               avg_prev("accounts_receivable"))
        payable_turn = _div(v.get("revenue"),
                            avg_prev("accounts_payable"))
        inventory_turn = _div(v.get("operating_cost"), avg_prev("inventory"))
        current_asset_turn = _div(v.get("revenue"),
                                  avg_prev("current_assets"))
        fixed_asset_turn = _div(v.get("revenue"), avg_prev("fixed_assets"))
        asset_turn = _div(v.get("revenue"), avg_prev("total_assets"))

        # EBIT≈利润总额（缺则营业利润）；利息保障/ROIC/WACC/有效税率共用
        ebit = (v.get("ebt") if v.get("ebt") is not None
                else v.get("operating_profit"))

        # 资本成本（肖星《财务分析与决策》经济利润章）
        _ic = _invested_capital(v)
        _avg_ic = _avg_invested_capital(v, prev)
        _roic = _pct(_div(_nopat(ebit, v.get("tax")), _avg_ic))
        if cost_of_equity is None or _ic is None or _ic <= 0:
            _wacc: Optional[float] = None
        else:
            _debt_w = _div(_or_zero(v.get("short_loan"))
                           + _or_zero(v.get("long_loan")), _ic)
            _eq_w = _div(v.get("equity"), _ic)
            _tax_r = _effective_tax_rate(ebit, v.get("tax"))
            if _debt_w is None or _eq_w is None:
                _wacc = None
            else:
                _wacc = _pct(_debt_w * COST_OF_DEBT * (1 - _tax_r)
                             + _eq_w * cost_of_equity)
        if _wacc is None or _roic is None or _avg_ic is None:
            _ep: Optional[float] = None
        else:
            _ep = (_roic / 100.0 - _wacc / 100.0) * _avg_ic

        ratios: dict[str, Optional[float]] = {
            # 盈利能力
            "gross_margin": _pct(_div(_sub(v.get("revenue"),
                                           v.get("operating_cost")),
                                      v.get("revenue"))),
            "net_margin": _pct(_div(v.get("net_profit"), v.get("revenue"))),
            "roe": _pct(_div(v.get("net_profit"), avg_prev("equity"))),
            "roa": _pct(_div(v.get("net_profit"),
                             avg_prev("total_assets"))),
            # 偿债能力
            "debt_ratio": _pct(_div(v.get("total_liabilities"),
                                    v.get("total_assets"))),
            "current_ratio": _r4(_div(v.get("current_assets"),
                                      v.get("current_liabilities"))),
            "quick_ratio": _r4(_div(_sub(v.get("current_assets"),
                                         v.get("inventory")),
                                    v.get("current_liabilities"))),
            # EBIT≈利润总额（缺则营业利润）；利息费用候选含财务费用兜底
            "interest_cover": _r4(_div(ebit, v.get("interest_expense"))),
            # ROIC：NOPAT/平均投入资本（格林布拉特口径，同 derived_metrics；
            # 有效税率缺失按 0 退化为 EBIT/IC）——复用资本成本块已算的 _roic
            "roic": _roic,
            # 营运能力（累计口径未年化，分母平均余额；天数=365/周转率）
            "inventory_turnover": _r4(inventory_turn),
            "inventory_days": _days(inventory_turn),
            "receivable_turnover": _r4(receivable_turn),
            "receivable_days": _days(receivable_turn),
            "payable_turnover": _r4(payable_turn),
            "payable_days": _days(payable_turn),
            "current_asset_turnover": _r4(current_asset_turn),
            "current_asset_days": _days(current_asset_turn),
            "fixed_asset_turnover": _r4(fixed_asset_turn),
            "fixed_asset_days": _days(fixed_asset_turn),
            "asset_turnover": _r4(asset_turn),
            "asset_days": _days(asset_turn),
            # 成长能力（同比）
            "revenue_growth": yoy("revenue"),
            "profit_growth": yoy("net_profit"),
            "asset_growth": yoy("total_assets"),
            # 资本成本（wacc/economic_profit 为派生 → ratios；
            # invested_capital 原始金额语义保留在 values（见下行），
            # 但前端只读 ratios —— 故 ratios 同置一份满足前端契约）
            "invested_capital": _ic,
            "wacc": _wacc,
            "economic_profit": _ep,
        }
        periods.append(
            {"report_date": p["ds"],
             "values": {**v, "invested_capital": _ic},
             "ratios": ratios}
        )

    periods.reverse()
    return {"groups": _build_groups(), "periods": periods}
