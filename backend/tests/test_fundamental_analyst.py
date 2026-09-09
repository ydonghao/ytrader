"""Tests for the fundamental analysis agent (P1).

不依赖真实 LLM / 网络 / DB：
  - LLM 客户端 mock 成返回固定 JSON。
  - 数据收集函数 mock 成返回固定 context（或 mock 仓储层）。
  - DB prompt 模板加载 mock 成回落默认值。
"""
import asyncio
import json
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..")
)

import pytest

from src.domain.market.fundamental.agents.fundamental_analyst import (
    collect_financial_series,
    collect_valuation_percentile,
    format_context_for_prompt,
    fundamental_analyst_node,
    parse_report,
)
from src.domain.market.fundamental.agents.schemas import (
    FundamentalReport,
)


AGENT_MOD = (
    "src.domain.market.fundamental.agents.fundamental_analyst"
)


# ── 固定样本 ───────────────────────────────────────────────────

VALID_REPORT = {
    "profitability": {
        "revenue_trend": "growth",
        "profit_trend": "growth",
        "margin_change": "毛利率稳定在 91% 附近",
        "cashflow_profit_match": "OCF/净利润持续大于 1",
        "summary": "盈利质量优秀。",
    },
    "financial_health": {
        "debt_level": "low",
        "interest_bearing_debt": "无有息负债",
        "solvency": "货币资金充裕",
        "summary": "财务健康。",
    },
    "valuation": {
        "pe_percentile": "5年分位 12%",
        "pb_percentile": "5年分位 20%",
        "cheap_or_expensive": "cheap",
        "summary": "估值偏低。",
    },
    "capital_efficiency": {
        "roic_trend": "ROIC 近 8 期均 >20%",
        "roe_trend": "ROE 稳定在 25%+",
        "roa_trend": "ROA 约 18%",
        "summary": "资本回报优秀。",
    },
    "moat": {
        "has_moat": True,
        "evidence": ["ROIC 持续 >20%", "毛利率稳定 91%"],
        "summary": "具备定价权护城河。",
    },
    "risks": [
        {
            "category": "goodwill",
            "description": "商誉占总资产较高",
            "severity": "medium",
        }
    ],
    "overall_score": 82,
    "one_line_conclusion": "高 ROIC + 低估值，基本面优秀。",
}


def _sample_ctx() -> dict:
    """一份含真实注入数据的 context 样本。"""
    return {
        "symbol": "sh600519",
        "series": [
            {
                "report_date": "2023-12-31",
                "revenue": 150000000000.0,
                "net_profit": 70000000000.0,
                "net_profit_parent": 70000000000.0,
                "operating_profit": 95000000000.0,
                "gross_margin": 91.2,
                "net_margin": 46.6,
                "debt_ratio": 25.0,
                "total_assets": 400000000000.0,
                "total_liabilities": 100000000000.0,
                "equity": 300000000000.0,
                "equity_parent": 300000000000.0,
                "short_loan": 0.0,
                "long_loan": 0.0,
                "monetary_funds": 150000000000.0,
                "goodwill": 1000000000.0,
                "ocf": 80000000000.0,
                "free_cash_flow": 70000000000.0,
                "capex": -10000000000.0,
                "roic": 31.6667,
                "roa": 17.5,
                "roe": 23.3333,
            },
        ],
        "valuation": {
            "as_of": "2024-01-15",
            "total_mv": 2000000000000.0,
            "pe_ttm": {
                "current": 25.5,
                "stats": {
                    "percentile": 0.12,
                    "sample_size": 1200,
                    "min": 10.0,
                    "max": 60.0,
                    "p25": 18.0,
                    "p50": 28.0,
                    "p75": 40.0,
                },
            },
            "pb": {
                "current": 8.0,
                "stats": {
                    "percentile": 0.2,
                    "sample_size": 1200,
                    "min": 3.0,
                    "max": 20.0,
                    "p25": 6.0,
                    "p50": 9.0,
                    "p75": 12.0,
                },
            },
        },
        "latest_derived": {
            "roic": 31.6667,
            "roa": 17.5,
            "ev": 1850000000000.0,
            "earnings_yield": 5.13,
            "fcf_yield": 3.78,
            "invested_capital": 300000000000.0,
        },
        "data_available": True,
    }


class _FakeLLMClient:
    """记录传入消息、返回固定响应的假 LLM 客户端。"""

    def __init__(self, response: str):
        self.response = response
        self.calls: list[list[dict]] = []

    def chat(
        self,
        messages=None,
        temperature=0.3,
        max_tokens=1024,
        **kwargs,
    ) -> str:
        self.calls.append(messages or [])
        return self.response


# ── 1. prompt 含真实注入数据 ───────────────────────────────────


def test_format_context_injects_real_data():
    """注入的财务数据必须出现在 prompt 文本里（防止 LLM 瞎编）。"""
    text = format_context_for_prompt(_sample_ctx())
    # 股票代码
    assert "sh600519" in text
    # 营收（真实数字，非占位）
    assert "150000000000" in text
    # ROIC / ROE（衍生指标）
    assert "31.6" in text
    assert "23.3" in text
    # 自由现金流
    assert "70000000000" in text
    # 估值分位
    assert "pe_ttm" in text
    assert "25.50" in text          # 当前 PE
    assert "0.12" in text           # 分位
    # 商誉（风险线索相关）
    assert "商誉" in text
    # 营收不应被标成无数据
    assert "营收 无数据" not in text


def test_format_context_missing_data_no_crash():
    """数据缺失时格式化不崩，并明确标注「无数据」。"""
    ctx = {
        "symbol": "sz000999",
        "series": [],
        "valuation": {
            "as_of": None, "total_mv": None,
            "pe_ttm": None, "pb": None,
        },
        "latest_derived": {},
        "data_available": False,
    }
    text = format_context_for_prompt(ctx)
    assert "sz000999" in text
    assert "无数据" in text
    # 三大报表 / 估值 / 衍生 三段都应存在（即使为空）
    assert "三大报表时序" in text
    assert "估值历史分位" in text
    assert "价值投资衍生指标" in text


# ── 2. 结构化解析 ──────────────────────────────────────────────


def test_parse_report_raw_json():
    report = parse_report(json.dumps(VALID_REPORT))
    assert isinstance(report, FundamentalReport)
    assert report.overall_score == 82
    assert report.profitability.revenue_trend == "growth"
    assert report.moat.has_moat is True
    assert len(report.risks) == 1


def test_parse_report_markdown_fenced():
    raw = "```json\n" + json.dumps(VALID_REPORT) + "\n```"
    report = parse_report(raw)
    assert isinstance(report, FundamentalReport)
    assert report.overall_score == 82


def test_parse_report_with_preamble():
    raw = (
        "好的，以下是分析结果：\n"
        + json.dumps(VALID_REPORT)
        + "\n以上为报告。"
    )
    report = parse_report(raw)
    assert isinstance(report, FundamentalReport)
    assert report.one_line_conclusion.startswith("高 ROIC")


def test_parse_report_string_with_braces_does_not_crash():
    """JSON 内含大括号字符的字符串值不应破坏括号匹配。"""
    payload = json.loads(json.dumps(VALID_REPORT))
    payload["profitability"]["summary"] = "见 {附录A} 说明"
    report = parse_report("前缀\n" + json.dumps(payload))
    assert isinstance(report, FundamentalReport)
    assert "{附录A}" in report.profitability.summary


def test_parse_report_invalid_returns_none():
    assert parse_report("") is None
    assert parse_report("抱歉，我无法完成") is None
    assert parse_report("{not valid json}") is None


def test_parse_report_score_out_of_range_rejected():
    payload = json.loads(json.dumps(VALID_REPORT))
    payload["overall_score"] = 150  # 超出 0-100
    assert parse_report(json.dumps(payload)) is None


# ── 3. 数据收集层降级（仓储空 / 异常不崩）──────────────────────


class _FakeFinRepo:
    """永远返回空的三大报表仓储。"""

    def get_history(self, *args, **kwargs):
        return []


class _FakeRaisingFinRepo:
    """get_history 抛异常的仓储（模拟 DB 不可达）。"""

    def get_history(self, *args, **kwargs):
        raise RuntimeError("db down")


def test_collect_series_empty_when_repo_empty(monkeypatch):
    import src.infra.database.market.financial_full as ffm
    monkeypatch.setattr(
        ffm,
        "create_financial_detail_repository",
        lambda *a, **k: _FakeFinRepo(),
    )
    series = collect_financial_series("sh000001", periods=8)
    assert series == []


def test_collect_series_degrades_on_repo_error(monkeypatch):
    """仓储异常时 collect 不抛，返回空时序。"""
    # collect_financial_series 内部 import 该工厂，patch 模块属性
    import src.infra.database.market.financial_full as ffm
    monkeypatch.setattr(
        ffm,
        "create_financial_detail_repository",
        lambda *a, **k: _FakeRaisingFinRepo(),
    )
    assert collect_financial_series("sh000001", periods=8) == []


class _FakeValRepoNoData:
    def get_latest_date(self, symbol):
        return None


def test_collect_valuation_percentile_no_data(monkeypatch):
    import src.infra.database.market.valuation as valm
    monkeypatch.setattr(
        valm,
        "create_stock_valuation_repository",
        lambda *a, **k: _FakeValRepoNoData(),
    )
    out = collect_valuation_percentile("sh000001", years=5)
    assert out["as_of"] is None
    assert out["pe_ttm"] is None
    assert out["pb"] is None


# ── 4. Agent 节点（mock LLM + mock 数据/DB prompt）──────────────


@pytest.fixture
def stub_deps(monkeypatch):
    """桩掉 DB prompt 加载 + 数据收集，返回可定制的桩。"""
    captured = {}

    def fake_load_prompt(name, fallback):
        return fallback

    def fake_collect(symbol, periods=12):
        ctx = _sample_ctx()
        captured["ctx"] = ctx
        return ctx

    monkeypatch.setattr(
        AGENT_MOD + ".load_prompt_from_db_or", fake_load_prompt
    )
    monkeypatch.setattr(
        AGENT_MOD + ".collect_fundamental_context", fake_collect
    )
    return captured


def _patch_llm(monkeypatch, response: str) -> _FakeLLMClient:
    fake = _FakeLLMClient(response)
    import src.llm.client as llm_mod
    monkeypatch.setattr(
        llm_mod, "get_llm_client", lambda: fake
    )
    return fake


def test_node_success_with_mock_llm(stub_deps, monkeypatch):
    """端到端：mock LLM 返回固定 JSON → 结构化解析正确 +
    prompt 含真实注入数据。"""
    fake = _patch_llm(monkeypatch, json.dumps(VALID_REPORT))

    result = asyncio.run(
        fundamental_analyst_node({"symbol": "sh600519"})
    )

    assert "errors" not in result
    assert result["symbol"] == "sh600519"
    assert result["overall_score"] == 82
    assert result["data_available"] is True
    assert result["periods_injected"] == 1
    assert result["profitability"]["revenue_trend"] == "growth"
    assert result["moat"]["has_moat"] is True
    assert len(result["risks"]) == 1
    assert result["risks"][0]["category"] == "goodwill"

    # 关键：prompt 里确实包含了真实注入数据
    assert len(fake.calls) == 1
    system_content = fake.calls[0][0]["content"]
    assert "150000000000" in system_content   # 营收
    assert "31.6" in system_content           # ROIC
    assert "sh600519" in system_content


def test_node_handles_missing_data(monkeypatch):
    """数据全缺时节点不崩，返回结构化报告 + data_available=False，
    且 prompt 内标注「无数据」。"""
    monkeypatch.setattr(
        AGENT_MOD + ".load_prompt_from_db_or",
        lambda name, fallback: fallback,
    )

    empty_ctx = {
        "symbol": "sz000999",
        "series": [],
        "valuation": {
            "as_of": None, "total_mv": None,
            "pe_ttm": None, "pb": None,
        },
        "latest_derived": {},
        "data_available": False,
    }
    monkeypatch.setattr(
        AGENT_MOD + ".collect_fundamental_context",
        lambda *a, **k: empty_ctx,
    )
    fake = _patch_llm(monkeypatch, json.dumps(VALID_REPORT))

    result = asyncio.run(
        fundamental_analyst_node({"symbol": "sz000999"})
    )

    assert "errors" not in result
    assert result["data_available"] is False
    assert result["periods_injected"] == 0
    # prompt 内对缺失数据有明确标注
    system_content = fake.calls[0][0]["content"]
    assert "无数据" in system_content
    assert "sz000999" in system_content


def test_node_returns_error_on_unparseable(stub_deps, monkeypatch):
    """LLM 输出非合法 JSON 时，节点返回 errors 而非抛异常。"""
    _patch_llm(monkeypatch, "抱歉，我无法生成分析。")

    result = asyncio.run(
        fundamental_analyst_node({"symbol": "sh600519"})
    )

    assert "errors" in result
    assert result["processing_steps"]
    assert "FAILED" not in result["processing_steps"][0]
