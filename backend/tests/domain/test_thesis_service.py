"""thesis service 测试：全部外部 IO monkeypatch，只测编排逻辑。"""
import datetime as dt

import pytest

from src.domain.market.thesis import service


class _Repo:
    def __init__(self):
        self.theses = [{
            "id": 1, "symbol": "sh600519", "status": "active",
            "buy_date": "2026-01-10", "buy_price": 1500.0,
            "shares": 100, "thesis_text": "t",
            "snapshot": {"price": 1500.0, "quality": {
                "score": 80, "verdict": "pass", "red_flags": []}},
            "target_band": {"metric": "price", "low": 2000,
                            "high": 2100},
            "decision": None, "last_reviewed_at": None,
        }]
        self.reevals = []
        self.events = []

    def list_theses(self, status=None):
        return [t for t in self.theses
                if status is None or t["status"] == status]

    def get_thesis(self, tid):
        return next((t for t in self.theses if t["id"] == tid), None)

    def list_conditions(self, tid):
        return [{"id": 11, "thesis_key": 1, "metric_key": "roe",
                 "operator": ">=", "threshold": 15.0, "label": ""}]

    def update_condition_status(self, cid, status):
        return True

    def update_thesis(self, tid, **f):
        self.theses[0].update(f)
        return True

    def add_reeval(self, row):
        key = (row["thesis_id"], row["report_date"], row["trigger"])
        if key in [(r["thesis_id"], r["report_date"], r["trigger"])
                   for r in self.reevals]:
            return None
        self.reevals.append(row)
        return len(self.reevals)

    def add_event(self, tid, kind, detail=None):
        self.events.append({"thesis_id": tid, "kind": kind,
                            "detail": detail})
        return len(self.events)

    def has_band_event(self, tid, band_key):
        return any(
            e["kind"] == "price_band_reached"
            and (e["detail"] or {}).get("band") == band_key
            for e in self.events
        )

    def has_event_detail(self, tid, kind, key, value):
        return any(
            e["kind"] == kind
            and (e["detail"] or {}).get(key) == value
            for e in self.events
        )

    def latest_reeval_report_date(self, tid):
        return None

    def latest_close(self, symbols):
        return {"sh600519": 2050.0}

    def latest_report_dates(self, symbols):
        return {"sh600519": dt.date(2026, 6, 30)}

    def latest_earnings_dates(self, symbols):
        return {}


@pytest.fixture()
def patched(monkeypatch):
    repo = _Repo()
    monkeypatch.setattr(service, "_repo", lambda: repo)
    monkeypatch.setattr(
        service, "_quality_report",
        lambda sym: {"score": 70, "verdict": "pass", "red_flags": []},
    )
    monkeypatch.setattr(
        service, "_valuation_handlers",
        lambda sym: {"dcf_upside": 1900.0 / 1500.0 - 1.0,
                     "ddm_upside": None, "asset_upside": None,
                     "comps_upside": None},
    )
    monkeypatch.setattr(
        service, "_financial_assembly",
        lambda sym: {"net_profit": 100.0, "equity": 500.0,
                     "report_date": "2025-12-31",
                     "roe": None, "pe_ttm": 30.0, "pb": None,
                     "dv_ttm": None},
    )
    return repo


def test_capture_snapshot_tolerates_failures(monkeypatch):
    def _boom(sym):
        raise RuntimeError("x")

    monkeypatch.setattr(service, "_quality_report", _boom)
    monkeypatch.setattr(service, "_valuation_handlers",
                        lambda sym: {})
    snap = service.capture_snapshot("sh600519", price=1500.0)
    assert snap["quality"] is None
    assert snap["price"] == 1500.0


def test_assemble_metrics_covers_registry(patched):
    m = service.assemble_metrics("sh600519")
    assert m["roe"] == 20.0      # 100/500*100
    assert m["pe_ttm"] == 30.0
    assert m["revenue_yoy"] is None


def test_run_daily_triggers_reeval_and_band(patched):
    summary = service.run_daily()
    assert summary["active"] == 1
    assert summary["reevaluated"] == 1
    assert summary["band_alerts"] == 1   # 2050 进入 [2000,2100] 带
    # 幂等：再跑一次不再新增
    summary2 = service.run_daily()
    assert summary2["reevaluated"] == 0
    assert summary2["band_alerts"] == 0


def test_run_daily_verdict_rules(patched):
    service.run_daily()
    verdicts = [r["verdict"] for r in patched.reevals]
    assert verdicts == ["pass"]  # roe=20>=15, 质量 80→70 降 10 不超阈


# ── 第5期: mine_sweep.check_positions ─────────────────────────────────────
def test_check_positions_events_dedup(monkeypatch):
    from src.domain.market.thesis import mine_sweep

    repo = _Repo()
    repo.theses[0]["symbol"] = "sh600519"
    monkeypatch.setattr(mine_sweep, "_repo", lambda: repo)
    monkeypatch.setattr(
        mine_sweep, "_z",
        lambda sym: {"z": 1.5, "verdict": "distress",
                     "report_date": "2026-06-30"},
    )
    monkeypatch.setattr(
        mine_sweep, "_m", lambda sym: {"m": -2.5, "verdict": "clean"},
    )
    monkeypatch.setattr(
        mine_sweep, "_fraud",
        lambda sym: {"severity": "clean", "red_flags": [],
                     "periods": ["2026-03-31", "2026-06-30"]},
    )
    upserts = []
    monkeypatch.setattr(
        repo, "upsert_mine_results",
        lambda rows: upserts.extend(rows) or len(rows),
        raising=False,
    )

    s1 = mine_sweep.check_positions()
    assert s1["checked"] == 1 and s1["high"] == 1 and s1["events"] == 1
    assert upserts[0]["risk_level"] == "high"
    s2 = mine_sweep.check_positions()   # 同财报期不重复告警
    assert s2["events"] == 0

    # 高危转好 → medium 不发事件
    monkeypatch.setattr(
        mine_sweep, "_z",
        lambda sym: {"z": 3.2, "verdict": "safe",
                     "report_date": "2026-06-30"},
    )
    s3 = mine_sweep.check_positions()
    assert s3["high"] == 0 and s3["medium"] == 0  # safe+clean → clean
