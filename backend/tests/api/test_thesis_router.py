"""thesis router 端点测试：独立 app 只挂 thesis_router（不 import main）。"""
import sys
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.api.handler import thesis_handler  # noqa: E402
from src.api.router import thesis_router as mod  # noqa: E402
from src.domain.market.thesis import service  # noqa: E402


class _Repo:
    theses = [{
        "id": 1, "symbol": "sh600519", "status": "active",
        "buy_date": "2026-01-10", "buy_price": 1500.0,
        "shares": 100, "thesis_text": "t", "snapshot": None,
        "target_band": None, "decision": None, "decision_note": None,
        "decision_at": None, "last_reviewed_at": None,
        "close_reason": None, "close_price": None, "closed_at": None,
        "created_at": "2026-01-10T00:00:00",
    }]

    def list_theses(self, status=None):
        return self.theses

    def create_thesis(self, data):
        return 1

    def get_thesis(self, tid):
        return self.theses[0]

    def update_thesis(self, tid, **f):
        return True

    def close_thesis(self, tid, reason, price=None):
        return True

    def list_conditions(self, tid):
        return []

    def replace_conditions(self, tid, items):
        return len(items)

    def list_reevals(self, tid, limit=50):
        return []

    def add_event(self, tid, kind, detail=None):
        return 1

    def list_events(self, unread_only=False, limit=100):
        return [{"id": 1, "thesis_id": 1, "kind": "reeval_done",
                 "detail": {"verdict": "pass"}, "read": False,
                 "created_at": "2026-09-27T00:00:00"}]

    def mark_event_read(self, eid):
        return True

    def latest_close(self, symbols):
        return {}

    def list_mines(self, level=None, limit=100):
        return [{"symbol": "sh600519", "risk_level": "high"}]

    def names_for(self, symbols):
        return {"sh600519": "贵州茅台"}

    def list_thermometer(self, symbol="sh000300", days=365):
        return [{"trade_date": "2026-09-26", "erp_pct": 6.0,
                 "level": "deep_cold"}]

    def add_pass_decision(self, data):
        return 11

    def list_pass_decisions(self, limit=200):
        return [{"id": 11, "symbol": "sh600519",
                 "decision_date": "2026-01-10", "price": 1500.0,
                 "reason": "估值太贵", "revisit_when": None,
                 "confidence": 4,
                 "created_at": "2026-01-10T00:00:00"}]

    def delete_pass_decision(self, pid):
        return True


app = FastAPI()
app.include_router(mod.router, prefix="/api/v1")


def _patch(monkeypatch):
    monkeypatch.setattr(
        thesis_handler, "create_thesis_repository",
        lambda *a, **k: _Repo(),
    )
    monkeypatch.setattr(
        service, "capture_snapshot",
        lambda sym, price=None: {"date": "2026-09-27",
                                 "price": 1500.0},
    )


def test_list_and_create(monkeypatch):
    _patch(monkeypatch)
    client = TestClient(app)
    r = client.get("/api/v1/thesis")
    assert r.json()["code"] == 0
    assert r.json()["data"][0]["symbol"] == "sh600519"
    r2 = client.post(
        "/api/v1/thesis",
        json={"symbol": "sh600519", "thesis_text": "x"},
    )
    assert r2.json()["code"] == 0
    assert r2.json()["data"]["id"] == 1


def test_create_rejects_unknown_metric(monkeypatch):
    _patch(monkeypatch)
    client = TestClient(app)
    r = client.post(
        "/api/v1/thesis",
        json={"symbol": "sh600519",
              "conditions": [{"metric_key": "nope", "operator": ">=",
                              "threshold": 1}]},
    )
    assert r.json()["code"] != 0


def test_mines_list_endpoint(monkeypatch):
    _patch(monkeypatch)
    client = TestClient(app)
    r = client.get("/api/v1/thesis/mines?level=high")
    assert r.json()["code"] == 0
    assert r.json()["data"][0]["symbol"] == "sh600519"


def test_events_read(monkeypatch):
    _patch(monkeypatch)
    client = TestClient(app)
    r = client.get("/api/v1/thesis/events/list?unread=true")
    assert r.json()["data"][0]["kind"] == "reeval_done"
    assert r.json()["data"][0]["symbol"] == "sh600519"
    r2 = client.put("/api/v1/thesis/events/1/read")
    assert r2.json()["code"] == 0


# ── 第3期: 日志挂钩 + 复盘端点 ────────────────────────────────────────────
def test_journal_hook_and_review(monkeypatch):
    calls = []

    class _Repo2(_Repo):
        def add_journal(self, tid, kind, decision=None, note=None,
                        price=None, confidence=None, catalysts=None):
            calls.append((kind, decision, price, confidence, catalysts))
            return 1

        def list_journal(self, tid, limit=100):
            return [{"id": 1, "thesis_id": tid, "kind": "created",
                     "decision": None, "note": "t", "price": 1500.0,
                     "confidence": 4, "catalysts": "年报",
                     "created_at": "2026-09-27T10:00:00"}]

        def list_journal_all(self, limit=100):
            return [{"id": 1, "thesis_id": 1, "kind": "created",
                     "decision": None, "note": "t", "price": 1500.0,
                     "confidence": 4, "catalysts": "年报",
                     "created_at": "2026-09-27T10:00:00"}]

        def add_review_log(self, note=None):
            return 1

        def latest_review_at(self):
            return None

        def list_theses(self, status=None):
            if status == "closed":
                return []
            return self.theses

    monkeypatch.setattr(
        thesis_handler, "create_thesis_repository",
        lambda *a, **k: _Repo2(),
    )
    monkeypatch.setattr(
        service, "capture_snapshot",
        lambda sym, price=None: {"date": "2026-09-27",
                                 "price": 1500.0},
    )
    client = TestClient(app)
    r = client.post("/api/v1/thesis",
                    json={"symbol": "sh600519", "thesis_text": "x"})
    assert r.json()["code"] == 0
    assert calls[0][0] == "created" and calls[0][2] == 1500.0

    r2 = client.put("/api/v1/thesis/1",
                    json={"decision": "hold", "decision_note": "n"})
    assert r2.json()["code"] == 0
    assert calls[-1][0] == "decision"

    r3 = client.get("/api/v1/thesis/1/journal")
    assert r3.json()["data"][0]["kind"] == "created"

    r4 = client.get("/api/v1/thesis/review")
    d = r4.json()["data"]
    assert d["stale_review"] is True
    assert d["closed_stats"] == []

    r5 = client.post("/api/v1/thesis/review", json={"note": "月度"})
    assert r5.json()["code"] == 0


# ── 第4期: 仓位建议端点 ───────────────────────────────────────────────────
def test_position_size_endpoint(monkeypatch):
    class _Repo3(_Repo):
        def latest_close(self, symbols):
            return {"sh600519": 70.0}

    monkeypatch.setattr(
        thesis_handler, "create_thesis_repository",
        lambda *a, **k: _Repo3(),
    )
    monkeypatch.setattr(
        thesis_handler.service, "_quality_report",
        lambda sym: {"score": 80, "verdict": "pass", "red_flags": []},
    )
    monkeypatch.setattr(
        thesis_handler.service, "_valuation_handlers",
        lambda sym: {"dcf_upside": 100.0 / 70.0 - 1.0},
    )
    client = TestClient(app)
    r = client.get("/api/v1/thesis/position-size/sh600519?capital=1000000")
    d = r.json()["data"]
    assert d["data_missing"] is False
    assert d["tier"] == "strong"          # quality 80, margin 30
    assert d["suggested_pct"] == 20.0
    assert d["ladder"][0]["shares"] is not None


# ── 第7期: 温度计端点（monkeypatch 数据源） ───────────────────────────────
def test_thermometer_endpoint(monkeypatch):
    class _Row:
        pe_ttm = 12.5
        trade_date = __import__("datetime").date(2026, 9, 26)

    import src.api.handler.thesis_handler as th

    class _IdxRepo:
        def get_index_range(self, *a, **k):
            return [_Row()]

    class _MacroRepo:
        def get_series(self, code, limit=1):
            return [{"report_date": "2026-09-25", "value": 2.0}]

    import src.infra.database.market.index_valuation as iv
    import src.infra.database.market.macro_indicator as mi
    monkeypatch.setattr(
        iv, "create_index_valuation_repository", lambda: _IdxRepo())
    monkeypatch.setattr(
        mi, "create_macro_indicator_repository", lambda: _MacroRepo())

    import psycopg2
    monkeypatch.setattr(
        psycopg2, "connect",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no db")))

    # 延迟 import 使 patch 生效
    import importlib
    importlib.reload(th)
    client = TestClient(app)
    r = client.get("/api/v1/thesis/thermometer")
    d = r.json()["data"]
    assert d["ep_pct"] == 8.0 and d["erp_pct"] == 6.0
    assert d["level"] == "deep_cold"
    assert d["position_band"]["low"] == 80
    assert d["buffett_pct"] is None   # 无 DB 连接 → 降级


# ── 第6期: 资本配置端点（mock 四源） ──────────────────────────────────────
def test_capital_allocation_endpoint(monkeypatch):
    import src.api.handler.thesis_handler as th
    import importlib

    class _Div:
        def __init__(self, year, paid):
            from datetime import date as _d
            self.ex_date = _d(year, 6, 30)
            self.div_per_share = 1.0 if paid else None

    class _DivRepo:
        def get_history(self, symbol, start=None, end=None):
            import datetime as dt2
            y0 = dt2.date.today().year - 5
            return [_Div(y, True) for y in range(y0, y0 + 6)]

    class _AlertRepo:
        def get_latest_metric_value(self, symbol, kind):
            return {"dv_ttm": 3.0, "pe_ttm": 10.0}[kind]

    class _HolderRepo:
        def get_history(self, symbol):
            class _H:
                def __init__(self, d, c):
                    self.report_date, self.holder_count = d, c
            import datetime as dt2
            return [
                _H(dt2.date.today() - dt2.timedelta(days=380), 100000),
                _H(dt2.date.today(), 80000),
            ]

    import src.infra.database.market.dividend as dv_mod
    import src.infra.database.market.shareholder_count as sc_mod
    monkeypatch.setattr(
        dv_mod, "create_stock_dividend_repository", lambda: _DivRepo())
    monkeypatch.setattr(
        sc_mod, "create_shareholder_count_repository",
        lambda: _HolderRepo())
    from src.infra.database.alert import repository as alert_mod
    monkeypatch.setattr(
        alert_mod, "create_alert_repository", lambda: _AlertRepo())
    monkeypatch.setattr(
        th.service, "_financial_assembly",
        lambda sym: {"ebit": 100.0, "total_assets": 500.0,
                     "total_liabilities": 200.0},
    )

    importlib.reload(th)
    client = TestClient(app)
    r = client.get("/api/v1/thesis/capital-allocation/sh600519")
    d = r.json()["data"]
    assert d["consecutive_dividend_years"] >= 5
    assert d["payout_pct"] == 30.0          # 3.0×10
    assert d["holder_change"]["label"] == "集中"   # -20%
    assert d["score"] >= 70


# ── 第6期V2: 资本事件端点 ─────────────────────────────────────────────────
def test_capital_events_endpoint(monkeypatch):
    _patch(monkeypatch)

    class _Repo4(_Repo):
        def list_capital_events(self, symbol, months=24, limit=200):
            return [{"symbol": symbol, "event_type": "buyback",
                     "announce_date": "2026-09-20",
                     "holder_name": "", "shares_wan": 100.0,
                     "amount": 1.5e8, "ratio_pct": None,
                     "progress": "完成实施"}]

    monkeypatch.setattr(
        thesis_handler, "create_thesis_repository",
        lambda *a, **k: _Repo4(),
    )
    client = TestClient(app)
    r = client.get("/api/v1/thesis/capital-events/sh600519")
    d = r.json()["data"]
    assert d[0]["event_type"] == "buyback"


# ── 增强: 条件历史回测端点 ─────────────────────────────────────────────────
def test_conditions_backtest_endpoint(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(
        thesis_handler.service, "_backtest_periods",
        lambda sym, lookback=16: [
            {"report_date": "2024-06-30", "revenue": 1000.0,
             "net_profit_parent": 100.0, "ocf": 90.0,
             "total_assets": 900.0, "total_liabilities": 450.0,
             "equity": 450.0, "gross_margin": 30.0},
            {"report_date": "2025-06-30", "revenue": 1200.0,
             "net_profit_parent": 100.0, "ocf": 90.0,
             "total_assets": 900.0, "total_liabilities": 450.0,
             "equity": 450.0, "gross_margin": 30.0},
        ],
    )
    client = TestClient(app)
    r = client.post("/api/v1/thesis/conditions-backtest", json={
        "symbol": "sh600519",
        "conditions": [{"metric_key": "revenue_yoy", "operator": ">=",
                        "threshold": 10.0}],
    })
    d = r.json()["data"]
    assert d["summary"][0]["evaluated"] == 1
    assert d["summary"][0]["breached"] == 0   # +20% 不破


# ── 决策日志补全: 信心度/催化剂 + 放弃决策 + 校准 ─────────────────────────
def test_create_with_confidence_and_catalysts(monkeypatch):
    calls = []

    class _RepoC(_Repo):
        def add_journal(self, tid, kind, decision=None, note=None,
                        price=None, confidence=None, catalysts=None):
            calls.append((kind, confidence, catalysts))
            return 1

    monkeypatch.setattr(
        thesis_handler, "create_thesis_repository",
        lambda *a, **k: _RepoC(),
    )
    monkeypatch.setattr(
        service, "capture_snapshot",
        lambda sym, price=None: {"date": "2026-10-03", "price": 100.0},
    )
    client = TestClient(app)
    r = client.post(
        "/api/v1/thesis",
        json={"symbol": "sh600519", "thesis_text": "x",
              "confidence": 4, "catalysts": "年报分红落地"},
    )
    assert r.json()["code"] == 0
    assert calls[0] == ("created", 4, "年报分红落地")

    # 非法信心度被拒
    r2 = client.post(
        "/api/v1/thesis",
        json={"symbol": "sh600519", "confidence": 9},
    )
    assert r2.json()["code"] != 0


def test_decision_with_confidence(monkeypatch):
    calls = []

    class _RepoD(_Repo):
        def update_thesis(self, tid, **f):
            return True

        def add_journal(self, tid, kind, decision=None, note=None,
                        price=None, confidence=None, catalysts=None):
            calls.append((kind, decision, confidence))
            return 1

    monkeypatch.setattr(
        thesis_handler, "create_thesis_repository",
        lambda *a, **k: _RepoD(),
    )
    client = TestClient(app)
    r = client.put("/api/v1/thesis/1",
                   json={"decision": "hold", "confidence": 3})
    assert r.json()["code"] == 0
    assert calls[-1] == ("decision", "hold", 3)


def test_pass_endpoints(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(
        thesis_handler, "_index_close_series",
        lambda symbol, start_iso=None, limit=5000: [
            {"trade_date": "2026-01-10", "close": 4000.0},
            {"trade_date": "2026-10-02", "close": 4400.0},
        ],
    )
    client = TestClient(app)
    # 必填校验
    assert client.post("/api/v1/thesis/pass",
                       json={"symbol": "sh600519"}).json()["code"] != 0
    # 补记历史放弃日 + 信心度
    r = client.post("/api/v1/thesis/pass", json={
        "symbol": "sh600519", "reason": "估值太贵",
        "decision_date": "2026-01-10", "price": 1500.0,
        "confidence": 4, "revisit_when": "PE 回到 25 以下",
    })
    assert r.json()["code"] == 0, r.text
    # 错过复盘: 个股 1500→1650(+10%) vs 基准 +10% → 超额 0 → 回避正确
    monkeypatch.setattr(
        thesis_handler, "create_thesis_repository",
        lambda *a, **k: type("R", (_Repo,), {
            "latest_close": staticmethod(
                lambda symbols: {"sh600519": 1650.0}),
        })(),
    )
    r2 = client.get("/api/v1/thesis/pass")
    d = r2.json()["data"]
    row = d["rows"][0]
    assert row["since_pct"] == 10.0
    assert row["bench_pct"] == 10.0
    assert row["excess_pct"] == 0.0
    assert row["verdict"] == "回避正确"
    assert d["summary"]["count"] == 1
    r3 = client.delete("/api/v1/thesis/pass/11")
    assert r3.json()["code"] == 0


def test_calibration_endpoint(monkeypatch):
    class _RepoE(_Repo):
        def list_theses(self, status=None):
            if status != "closed":
                return []
            return [
                {"id": 1, "buy_price": 100.0, "close_price": 150.0},
                {"id": 2, "buy_price": 100.0, "close_price": 90.0},
                {"id": 3, "buy_price": 100.0, "close_price": 130.0},
            ]

        def list_journal_all(self, limit=100):
            return [
                {"id": 1, "thesis_id": 1, "kind": "created",
                 "confidence": 5, "created_at": "2026-01-01"},
                {"id": 2, "thesis_id": 2, "kind": "created",
                 "confidence": 5, "created_at": "2026-01-02"},
                {"id": 3, "thesis_id": 3, "kind": "created",
                 "confidence": 3, "created_at": "2026-01-03"},
                {"id": 4, "thesis_id": 3, "kind": "decision",
                 "confidence": 2, "created_at": "2026-02-01"},
            ]

    monkeypatch.setattr(
        thesis_handler, "create_thesis_repository",
        lambda *a, **k: _RepoE(),
    )
    client = TestClient(app)
    d = client.get("/api/v1/thesis/calibration").json()["data"]
    by_conf = {g["confidence"]: g for g in d["groups"]}
    assert by_conf[5]["count"] == 2 and by_conf[5]["win_count"] == 1
    assert by_conf[3]["count"] == 1 and by_conf[3]["win_count"] == 1
    # decision 条目的信心度不参与(只认 created)
    assert d["no_confidence_count"] == 0
