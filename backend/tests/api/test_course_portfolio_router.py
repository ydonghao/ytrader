"""course_portfolio_router 测试: 全链路用假数据源(不触DB)。"""
import sys, os
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import src.api.router.course_portfolio_router as mod
from src.infra.database.portfolio.course_models import (
    CoursePortfolio,
    CoursePortfolioLeg,
)

# 假数据: 3红利/2蓝筹/1创新(足够 稳健5只 2/2/1 配额)
_D = date(2026, 9, 18)
FAKE_VALS = {
    "sh600000": {"trade_date": _D, "pe": 8.0, "pe_ttm": 8.0, "pb": 0.6,
                 "ps": None, "ps_ttm": None, "dv_ratio": 6.0, "dv_ttm": 6.0,
                 "total_mv": 2.0e11},
    "sh601288": {"trade_date": _D, "pe": 6.0, "pe_ttm": 6.0, "pb": 0.55,
                 "ps": None, "ps_ttm": None, "dv_ratio": 7.0, "dv_ttm": 7.0,
                 "total_mv": 1.5e11},
    "sh601398": {"trade_date": _D, "pe": 6.5, "pe_ttm": 6.5, "pb": 0.6,
                 "ps": None, "ps_ttm": None, "dv_ratio": 6.5, "dv_ttm": 6.5,
                 "total_mv": 2.5e11},
    "sh600036": {"trade_date": _D, "pe": 15.0, "pe_ttm": 15.0, "pb": 1.2,
                 "ps": None, "ps_ttm": None, "dv_ratio": 2.0, "dv_ttm": 2.0,
                 "total_mv": 9.0e11},
    "sz000858": {"trade_date": _D, "pe": 12.0, "pe_ttm": 12.0, "pb": 2.0,
                 "ps": None, "ps_ttm": None, "dv_ratio": 2.5, "dv_ttm": 2.5,
                 "total_mv": 5.0e11},
    "sz300750": {"trade_date": _D, "pe": 40.0, "pe_ttm": 40.0, "pb": 5.0,
                 "ps": None, "ps_ttm": None, "dv_ratio": 0.5, "dv_ttm": 0.5,
                 "total_mv": 8.0e11},
}

FAKE_FINS = {
    "sh600000": {"roe_weighted": 11.0}, "sh601288": {"roe_weighted": 10.5},
    "sh601398": {"roe_weighted": 10.8}, "sh600036": {"roe_weighted": 14.0},
    "sz000858": {"roe_weighted": 25.0}, "sz300750": {"roe_weighted": 22.0},
}

FAKE_REVS = {
    "sh600000": [{"report_date": date(2025, 12, 31), "revenue": 1030.0},
                 {"report_date": date(2024, 12, 31), "revenue": 1000.0}],
    "sh601288": [{"report_date": date(2025, 12, 31), "revenue": 1030.0},
                 {"report_date": date(2024, 12, 31), "revenue": 1000.0}],
    "sh601398": [{"report_date": date(2025, 12, 31), "revenue": 1020.0},
                 {"report_date": date(2024, 12, 31), "revenue": 1000.0}],
    "sh600036": [{"report_date": date(2025, 12, 31), "revenue": 1010.0},
                 {"report_date": date(2024, 12, 31), "revenue": 1000.0}],
    "sz000858": [{"report_date": date(2025, 12, 31), "revenue": 1015.0},
                 {"report_date": date(2024, 12, 31), "revenue": 1000.0}],
    "sz300750": [{"report_date": date(2025, 12, 31), "revenue": 1300.0},
                 {"report_date": date(2024, 12, 31), "revenue": 1000.0}],
}

PE_SERIES = {s: [10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0,
                 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0,
                 9.0, 10.0, 11.0, 9.0] for s in FAKE_VALS}
NAMES = {s: f"名称{s}" for s in FAKE_VALS}
CLOSES = {s: 10.0 for s in FAKE_VALS}


class FakeRepo:
    """内存版 CoursePortfolioRepository。"""

    def __init__(self):
        self.plans: dict[int, CoursePortfolio] = {}
        self.legs: dict[tuple[int, int], CoursePortfolioLeg] = {}
        self._next_pid = 1
        self._next_lid = 1

    def get_close_price(self, symbol, on_or_before):
        return CLOSES.get(symbol)

    def create_plan(self, portfolio, legs):
        pid = self._next_pid
        self._next_pid += 1
        portfolio.id = pid
        self.plans[pid] = portfolio
        for l in legs:
            l.id = self._next_lid
            self._next_lid += 1
            l.portfolio_id = pid
            self.legs[(pid, l.id)] = l
        return pid

    def list_plans(self):
        return [
            {"id": p.id, "name": p.name, "risk_profile": p.risk_profile,
             "total_capital": p.total_capital,
             "cash_reserve_pct": p.cash_reserve_pct,
             "target_stock_count": p.target_stock_count,
             "status": p.status, "notes": p.notes, "created_at": None}
            for p in self.plans.values()
        ]

    def get_plan(self, pid):
        if pid not in self.plans:
            return None
        legs = [l for (p, _), l in self.legs.items() if p == pid]
        return {"portfolio": self.plans[pid], "legs": legs}

    def delete_plan(self, pid):
        if pid not in self.plans:
            return False
        self.plans.pop(pid)
        for k in [k for k in self.legs if k[0] == pid]:
            self.legs.pop(k)
        return True

    def save_leg_fill(self, leg_id, entry_plan, shares_delta, fill_price,
                      fill_value, status=None):
        for (pid, lid), l in self.legs.items():
            if lid == leg_id:
                l.entry_plan = entry_plan
                l.shares = (l.shares or 0) + shares_delta
                l.invested_amount = (l.invested_amount or 0.0) + fill_value
                l.avg_cost = l.invested_amount / l.shares if l.shares else 0.0
                if status:
                    self.plans[pid].status = status
                return

    def set_plan_status(self, pid, status):
        self.plans[pid].status = status


@pytest.fixture
def client(monkeypatch):
    fake = FakeRepo()
    monkeypatch.setattr(mod, "_course_repo", lambda: fake)
    monkeypatch.setattr(mod, "_csi300_members",
                        lambda: ["sh600036", "sz000858", "sh600000"])
    monkeypatch.setattr(mod, "fetch_universe_symbols",
                        lambda *a, **k: list(FAKE_VALS.keys()))
    monkeypatch.setattr(mod, "fetch_latest_valuations",
                        lambda symbols, as_of=None: FAKE_VALS)
    monkeypatch.setattr(mod, "fetch_latest_financials",
                        lambda symbols, as_of=None, lag_days=45: FAKE_FINS)
    monkeypatch.setattr(mod, "fetch_annual_revenues",
                        lambda symbols, as_of=None: FAKE_REVS)
    monkeypatch.setattr(mod, "fetch_symbol_names",
                        lambda symbols: NAMES)
    monkeypatch.setattr(mod, "_load_pe_series",
                        lambda symbols, as_of=None: {
                            s: list(PE_SERIES[s]) for s in symbols})

    app = FastAPI()
    app.include_router(mod.router, prefix="/api/v1")
    with TestClient(app) as c:
        yield c


def _gen_body():
    return {
        "total_capital": 500000.0,
        "risk_profile": "balanced",
        "stock_count": 5,
    }


def _save_body_from(gen_data, name="测试组合"):
    return {
        "name": name,
        "total_capital": 500000.0,
        "risk_profile": "balanced",
        "stock_count": 5,
        "legs": [
            {"symbol": l["symbol"], "category": l["category"],
             "target_weight": l["target_weight"],
             "target_amount": l["target_amount"]}
            for l in gen_data["legs"]
        ],
    }


def test_generate_rejects_unknown_profile(client):
    body = _gen_body()
    body["risk_profile"] = "nope"
    resp = client.post("/api/v1/course-portfolio/generate", json=body)
    assert resp.status_code == 400


def test_generate_pe_series_window_ends_at_as_of(client, monkeypatch):
    """红线: generate 的 PE 带序列窗口必须截至 as_of, 不得掺未来数据。"""
    captured = {}

    def fake_pe_series(symbols, as_of=None):
        captured["as_of"] = as_of
        return {s: list(PE_SERIES[s]) for s in symbols}

    monkeypatch.setattr(mod, "_load_pe_series", fake_pe_series)
    body = _gen_body()
    body["as_of"] = "2020-08-21"
    resp = client.post("/api/v1/course-portfolio/generate", json=body)
    assert resp.status_code == 200
    assert captured["as_of"] == date(2020, 8, 21)


def test_generate_returns_grouped_legs(client):
    resp = client.post("/api/v1/course-portfolio/generate", json=_gen_body())
    assert resp.status_code == 200
    data = resp.json()["data"]
    cats = {l["category"] for l in data["legs"]}
    assert cats == {"dividend", "bluechip", "growth"}
    assert data["slots"] == {"dividend": 2, "bluechip": 2, "growth": 1}
    # 红利类按股息率降序: sh601288(7.0) > sh601398(6.5) > sh600000(6.0)
    div_syms = [l["symbol"] for l in data["legs"] if l["category"] == "dividend"]
    assert set(div_syms) == {"sh601288", "sh601398"}
    # 估值状态按各自 pe_ttm vs μ=10, σ≈0.82 判定:
    # 红利腿(pe 6/6.5)→ oversold → 4档;蓝筹(pe 12/15)/创新(pe 40)→ overvalued → 无档位
    for l in data["legs"]:
        band = l["pe_band"]
        if l["category"] == "dividend":
            assert band["state"] == "oversold"
            assert len(l["entry_plan"]) == 4
        else:
            assert band["state"] == "overvalued"
            assert l["entry_plan"] == []
    assert data["candidates"]["dividend"]  # 有备选
    assert abs(sum(l["target_weight"] for l in data["legs"]) - 1.0) < 1e-6


def test_save_and_get_and_review_and_fill(client):
    # 1. generate
    gen = client.post("/api/v1/course-portfolio/generate",
                      json=_gen_body()).json()["data"]
    # 2. save
    resp = client.post("/api/v1/course-portfolio", json=_save_body_from(gen))
    assert resp.status_code == 200
    pid = resp.json()["data"]["id"]
    # 3. detail
    detail = client.get(f"/api/v1/course-portfolio/{pid}").json()["data"]
    assert len(detail["legs"]) == 5
    assert detail["status"] == "planned"
    # 4. review(现价10 > 最低档8.5, ≤ 最高未执行档10 → 触发首档买入)
    review = client.get(f"/api/v1/course-portfolio/{pid}/review")
    assert review.status_code == 200
    advices = {a["symbol"]: a for a in review.json()["data"]["advices"]}
    assert any(a["code"] == "BUY_RUNG" for a in advices.values())
    # 5. fill 首档
    leg0 = next(l for l in detail["legs"] if l["symbol"] == "sh601288")
    fill = client.post(
        f"/api/v1/course-portfolio/{pid}/legs/{leg0['id']}/fills",
        json={"rung_index": 0})
    assert fill.status_code == 200
    assert fill.json()["data"]["fill_shares"] > 0
    detail2 = client.get(f"/api/v1/course-portfolio/{pid}").json()["data"]
    leg0b = next(l for l in detail2["legs"] if l["symbol"] == "sh601288")
    assert leg0b["shares"] > 0
    assert detail2["status"] == "building"
    # 6. list + delete
    assert any(p["id"] == pid for p in
               client.get("/api/v1/course-portfolio").json()["data"])
    assert client.delete(f"/api/v1/course-portfolio/{pid}").status_code == 200
    assert client.get(f"/api/v1/course-portfolio/{pid}").status_code == 404


def test_fill_rejects_double_execution(client):
    gen = client.post("/api/v1/course-portfolio/generate",
                      json=_gen_body()).json()["data"]
    pid = client.post("/api/v1/course-portfolio",
                      json=_save_body_from(gen, "x")).json()["data"]["id"]
    detail = client.get(f"/api/v1/course-portfolio/{pid}").json()["data"]
    leg0 = detail["legs"][0]
    r1 = client.post(f"/api/v1/course-portfolio/{pid}/legs/{leg0['id']}/fills",
                     json={"rung_index": 0})
    assert r1.status_code == 200
    r2 = client.post(f"/api/v1/course-portfolio/{pid}/legs/{leg0['id']}/fills",
                     json={"rung_index": 0})
    assert r2.status_code == 400
