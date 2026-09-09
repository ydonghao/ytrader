"""FundamentalAnalystAgent — 个股基本面深度分析（P1）。

范式复用：@agent_node 装饰器 + Jinja2 prompt + 结构化 Pydantic 输出
+ tracing/cancel（同 src/domain/market/intel/macro/agents/macro_analyst.py）。

【数据注入（绝不让 LLM 凭空编造）】
节点先把真实数据拼进 prompt，再调 LLM：
  1. 三大报表时序（最近 N 期）：stock_financial_detail。
     营收/净利、毛利率/净利率、ROE、负债率、OCF、自由现金流。
  2. 估值历史分位：stock_valuation + percentile 模块（PE_TTM/PB）。
  3. 衍生指标：derived_metrics.compute_value_metrics
     （ROIC/EV/EBIT-yield/FCF-yield/ROA，最新期）。
数据缺失时在 prompt 内明确标注「无数据」，禁止 LLM 臆测。

【LLM 客户端】用 src/llm/client.py 的 get_llm_client().chat() 拿
JSON 文本，再用 _parse_report 解析为 FundamentalReport（Pydantic）。
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional

from src.domain.market.intel.agents.base import (
    agent_node,
    load_prompt_from_db_or,
    render_prompt,
)
from src.domain.market.fundamental.agents.schemas import FundamentalReport


# ── 默认 prompt（可通过 DB prompt 模板 'fundamental_analyst_system'
#    / 'fundamental_analyst_user' 覆盖，与 macro 范式一致）─────────────
_DEFAULT_SYSTEM_PROMPT = """你是一位严谨的价值投资基本面分析师。基于下方【注入的真实财务数据】对个股做定性分析。

【三条铁律】
1. 只能用上下文里出现的数据下判断；上下文标注「无数据」的字段，对应分析也写「无数据」，严禁臆测或编造数字。
2. 趋势比绝对值重要，拐点比水平重要。
3. 不下股价方向判断（不说看涨/看跌），只评估基本面质量。

【分析维度】逐项给出：
- 盈利质量：营收/利润趋势、毛净利率变化、经营现金流 vs 净利润匹配度（OCF/净利润是否持续≥1）。
- 财务健康：资产负债率水平与变化、有息负债（短期+长期借款）规模、货币资金对有息负债的覆盖。
- 估值：当前 PE_TTM / PB 的历史分位含义（低分位=便宜），给便宜/合理/昂贵判断；分位无数据则填「无数据」并写 'unknown'。
- 资本回报效率：ROIC / ROE / ROA 的趋势与水平（ROIC 持续>15% 通常意味护城河）。
- 护城河线索：基于财务特征推断（持续高 ROIC + 稳定/上行毛利率 + 现金流佳 = 强信号），列出依据。
- 风险点：负债上升 / 现金流恶化 / 商誉占总资产过高 / 盈利下滑等，逐条列出并定级。
- 综合评分 0-100 + 一句话结论。

【输出格式】只输出一个 JSON 对象，不要任何额外文字、不要 markdown 代码块。结构：
{
  "profitability": {"revenue_trend": "...", "profit_trend": "...",
    "margin_change": "...", "cashflow_profit_match": "...",
    "summary": "..."},
  "financial_health": {"debt_level": "...", "interest_bearing_debt": "...",
    "solvency": "...", "summary": "..."},
  "valuation": {"pe_percentile": "...", "pb_percentile": "...",
    "cheap_or_expensive": "...", "summary": "..."},
  "capital_efficiency": {"roic_trend": "...", "roe_trend": "...",
    "roa_trend": "...", "summary": "..."},
  "moat": {"has_moat": true/false, "evidence": ["...", "..."],
    "summary": "..."},
  "risks": [{"category": "...", "description": "...", "severity": "..."}],
  "overall_score": 0,
  "one_line_conclusion": "..."
}

【上下文数据】
{{ context }}
"""

_DEFAULT_USER_PROMPT = """请基于上方注入的真实财务数据，对股票 {{ symbol }} 输出基本面深度分析 JSON。
记住：只输出 JSON 对象本身，不要前后说明文字。"""


# ════════════════════════════════════════════════════════════════════════════
#  数据注入（真实数据 → 结构化 context）
# ════════════════════════════════════════════════════════════════════════════

def _g(obj: Any, key: str) -> Optional[float]:
    """宽松取属性：obj 为 None 或无该属性时返回 None。"""
    if obj is None:
        return None
    return getattr(obj, key, None)


def _safe_div_pct(
    num: Optional[float], den: Optional[float]
) -> Optional[float]:
    """num/den*100，除零或非数值返回 None。"""
    if (
        isinstance(num, (int, float))
        and isinstance(den, (int, float))
        and den != 0
    ):
        return round(num / den * 100, 4)
    return None


def _merge_period(
    rd: Any, inc: Any, bal: Any, cas: Any
) -> dict[str, Any]:
    """把某报告期的三大表 ORM 行合并为一个 period dict + 派生指标。"""
    from src.domain.market.fundamental.derived_metrics import roa, roic

    p: dict[str, Any] = {
        "report_date": (
            rd.isoformat() if hasattr(rd, "isoformat") else str(rd)
        ),
        "revenue": _g(inc, "revenue"),
        "net_profit": _g(inc, "net_profit"),
        "net_profit_parent": _g(inc, "net_profit_parent"),
        "operating_profit": _g(inc, "operating_profit"),
        "gross_margin": _g(inc, "gross_margin"),
        "net_margin": _g(inc, "net_margin"),
        "debt_ratio": _g(bal, "debt_ratio"),
        "total_assets": _g(bal, "total_assets"),
        "total_liabilities": _g(bal, "total_liabilities"),
        "equity": _g(bal, "equity"),
        "equity_parent": _g(bal, "equity_parent"),
        "short_loan": _g(bal, "short_loan"),
        "long_loan": _g(bal, "long_loan"),
        "monetary_funds": _g(bal, "monetary_funds"),
        "goodwill": _g(bal, "goodwill"),
        "ocf": _g(cas, "ocf"),
        "free_cash_flow": _g(cas, "free_cash_flow"),
        "capex": _g(cas, "capex"),
    }
    # 派生：ROIC / ROA（无需估值）/ ROE（归母净利/归母权益）
    p["roic"] = roic(p)
    p["roa"] = roa(p)
    p["roe"] = _safe_div_pct(p["net_profit_parent"], p["equity_parent"])
    # 自由现金流兜底：表里为空则用 ocf - |capex|
    if p["free_cash_flow"] is None:
        ocf, capex = p["ocf"], p["capex"]
        if isinstance(ocf, (int, float)) and isinstance(
            capex, (int, float)
        ):
            p["free_cash_flow"] = ocf - abs(capex)
    return p


def collect_financial_series(
    symbol: str, periods: int = 12
) -> list[dict[str, Any]]:
    """拉三大报表，按 report_date 合并成时序 period dict（升序）。

    任何一表查询失败都不中断，只丢该表数据（降级）。
    """
    from src.infra.database.market.financial_full import (
        create_financial_detail_repository,
    )

    repo = create_financial_detail_repository()
    by_type: dict[str, dict] = {}
    for st in ("income", "balance", "cashflow"):
        try:
            rows = repo.get_history(symbol, st, limit=periods + 4)
        except Exception:
            rows = []
        by_type[st] = {r.report_date: r for r in rows}

    # 以利润表报告期为主轴；利润表缺失则退化为
    # 资产负债/现金流并集
    dates = sorted(by_type.get("income", {}).keys())
    if not dates:
        dates = sorted(
            set(by_type.get("balance", {}))
            | set(by_type.get("cashflow", {}))
        )
    dates = dates[-periods:] if len(dates) > periods else dates

    series: list[dict[str, Any]] = []
    for d in dates:
        series.append(
            _merge_period(
                d,
                by_type["income"].get(d),
                by_type["balance"].get(d),
                by_type["cashflow"].get(d),
            )
        )
    return series


def collect_valuation_percentile(
    symbol: str, years: int = 5
) -> dict[str, Any]:
    """PE_TTM / PB 历史分位 + 当前总市值（直接查 valuation repo）。"""
    from src.infra.database.market.valuation import (
        create_stock_valuation_repository,
    )
    from src.domain.market.fundamental.percentile import percentile_stats

    repo = create_stock_valuation_repository()
    try:
        latest = repo.get_latest_date(symbol)
    except Exception:
        latest = None
    if latest is None:
        return {
            "as_of": None, "total_mv": None,
            "pe_ttm": None, "pb": None,
        }

    start = date(latest.year - years, latest.month, latest.day)
    try:
        rows = repo.get_range(symbol, start, latest)
    except Exception:
        rows = []

    out: dict[str, Any] = {
        "as_of": latest.isoformat(), "total_mv": None,
        "pe_ttm": None, "pb": None,
    }
    if rows:
        out["total_mv"] = rows[-1].total_mv
    for metric in ("pe_ttm", "pb"):
        samples = [
            getattr(r, metric) for r in rows
            if getattr(r, metric) is not None
            and getattr(r, metric) > 0
        ]
        current = samples[-1] if samples else None
        out[metric] = {
            "current": current,
            "stats": (
                percentile_stats(samples, current)
                if current is not None else None
            ),
        }
    return out


def collect_fundamental_context(
    symbol: str, periods: int = 12
) -> dict[str, Any]:
    """聚合：三大报表时序 + 估值分位 + 最新期价值衍生指标。"""
    from src.domain.market.fundamental.derived_metrics import (
        compute_value_metrics,
    )

    series = collect_financial_series(symbol, periods=periods)
    valuation = collect_valuation_percentile(symbol, years=5)

    latest_derived: dict[str, Any] = {}
    if series:
        fin = series[-1]
        val = {"total_mv": valuation.get("total_mv")}
        latest_derived = compute_value_metrics(fin, val)

    return {
        "symbol": symbol,
        "series": series,
        "valuation": valuation,
        "latest_derived": latest_derived,
        "data_available": len(series) > 0,
    }


# ════════════════════════════════════════════════════════════════════════════
#  context → prompt 文本（纯函数，数据缺失标「无数据」）
# ════════════════════════════════════════════════════════════════════════════

def _fmt_num(v: Any) -> str:
    """数值友好显示；None → '无数据'。"""
    if v is None:
        return "无数据"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _fmt_period(p: dict[str, Any]) -> str:
    """单期财务数据 → 一行紧凑文本。"""
    return (
        f"- {p.get('report_date')}: "
        f"营收 {_fmt_num(p.get('revenue'))} | "
        f"净利 {_fmt_num(p.get('net_profit'))} | "
        f"归母净利 {_fmt_num(p.get('net_profit_parent'))} | "
        f"毛利率 {_fmt_num(p.get('gross_margin'))}% | "
        f"净利率 {_fmt_num(p.get('net_margin'))}% | "
        f"负债率 {_fmt_num(p.get('debt_ratio'))}% | "
        f"ROE {_fmt_num(p.get('roe'))}% | "
        f"ROIC {_fmt_num(p.get('roic'))}% | "
        f"ROA {_fmt_num(p.get('roa'))}% | "
        f"OCF {_fmt_num(p.get('ocf'))} | "
        f"FCF {_fmt_num(p.get('free_cash_flow'))} | "
        f"短期借款 {_fmt_num(p.get('short_loan'))} | "
        f"长期借款 {_fmt_num(p.get('long_loan'))} | "
        f"货币资金 {_fmt_num(p.get('monetary_funds'))} | "
        f"商誉 {_fmt_num(p.get('goodwill'))}"
    )


def format_context_for_prompt(ctx: dict[str, Any]) -> str:
    """把结构化 context 格式化为 LLM 可读文本（纯函数）。"""
    lines: list[str] = []
    series = ctx.get("series") or []
    valuation = ctx.get("valuation") or {}
    latest = ctx.get("latest_derived") or {}

    lines.append(f"【股票代码】{ctx.get('symbol', '')}")

    # 三大报表时序
    if not series:
        lines.append("【三大报表时序】（无数据）")
    else:
        lines.append(
            f"【三大报表时序】（共 {len(series)} 期，"
            f"最新在前）"
        )
        for p in reversed(series):
            lines.append(_fmt_period(p))

    # 估值历史分位
    lines.append("")
    lines.append("【估值历史分位（5年窗口）】")
    if not valuation or valuation.get("as_of") is None:
        lines.append("（无数据）")
    else:
        lines.append(
            f"基准日 {valuation.get('as_of')} | "
            f"总市值 {_fmt_num(valuation.get('total_mv'))}"
        )
        for m in ("pe_ttm", "pb"):
            mv = valuation.get(m) or {}
            cur = mv.get("current")
            st = mv.get("stats") or {}
            if cur is None:
                lines.append(f"- {m}: 无数据")
            else:
                lines.append(
                    f"- {m}: 当前 {cur:.2f} | "
                    f"分位 {st.get('percentile')} | "
                    f"样本 {st.get('sample_size')} | "
                    f"min {st.get('min')} / p50 {st.get('p50')} "
                    f"/ p75 {st.get('p75')} / max {st.get('max')}"
                )

    # 最新期价值衍生指标
    lines.append("")
    lines.append("【最新期价值投资衍生指标】")
    if not latest:
        lines.append("（无数据）")
    else:
        for k in (
            "roic", "roa", "ev", "earnings_yield",
            "fcf_yield", "invested_capital",
        ):
            lines.append(f"- {k}: {_fmt_num(latest.get(k))}")

    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
#  LLM 输出 → FundamentalReport（鲁棒 JSON 抽取）
# ════════════════════════════════════════════════════════════════════════════

def _extract_first_json(text: str) -> Optional[dict]:
    """从文本中抽取首个完整 JSON 对象（兼容 markdown fence / 前后说明）。"""
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                try:
                    return json.loads(part)
                except Exception:
                    continue
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return None
    return None


def parse_report(raw: str) -> Optional[FundamentalReport]:
    """把 LLM 文本输出解析为 FundamentalReport；失败返回 None。"""
    if not raw:
        return None
    # 1. 整体直接解析
    try:
        return FundamentalReport.model_validate_json(raw)
    except Exception:
        pass
    # 2. 抽取首个 JSON 对象后解析
    obj = _extract_first_json(raw)
    if obj is None:
        return None
    try:
        return FundamentalReport.model_validate(obj)
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════
#  Agent 节点（@agent_node：tracing / cancel / 错误兜底）
# ════════════════════════════════════════════════════════════════════════════

@agent_node
async def fundamental_analyst_node(
    state: dict[str, Any],
) -> dict[str, Any]:
    """生成个股基本面深度分析报告（结构化输出 FundamentalReport）。"""
    from src.llm.client import get_llm_client

    symbol = state.get("symbol", "") or ""
    periods = int(state.get("periods", 12) or 12)

    # ── 数据注入 ──
    ctx = collect_fundamental_context(symbol, periods=periods)
    context_text = format_context_for_prompt(ctx)

    # ── 渲染 prompt（Jinja2）──
    system_prompt = render_prompt(
        load_prompt_from_db_or(
            "fundamental_analyst_system", _DEFAULT_SYSTEM_PROMPT
        ),
        context=context_text,
    )
    user_msg = render_prompt(
        load_prompt_from_db_or(
            "fundamental_analyst_user", _DEFAULT_USER_PROMPT
        ),
        symbol=symbol,
    )

    # ── 调 LLM（src/llm/client.py）→ 结构化报告 ──
    client = get_llm_client()
    raw = client.chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        max_tokens=4096,
    )
    report = parse_report(raw)
    if report is None:
        return {
            "errors": [
                "fundamental_analyst: 无法解析 LLM 输出为"
                "结构化报告（raw 非合法 JSON）",
            ],
            "processing_steps": [
                "fundamental_analyst: JSON parse failed",
            ],
        }

    return {
        "symbol": symbol,
        "data_available": ctx["data_available"],
        "periods_injected": len(ctx["series"]),
        "profitability": report.profitability.model_dump(),
        "financial_health": report.financial_health.model_dump(),
        "valuation": report.valuation.model_dump(),
        "capital_efficiency": report.capital_efficiency.model_dump(),
        "moat": report.moat.model_dump(),
        "risks": [r.model_dump() for r in report.risks],
        "overall_score": report.overall_score,
        "one_line_conclusion": report.one_line_conclusion,
        "processing_steps": [
            f"fundamental_analyst: score={report.overall_score} "
            f"data_available={ctx['data_available']} "
            f"periods={len(ctx['series'])}"
        ],
    }
