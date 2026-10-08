"""thesis_repository CRUD 测试（sqlite 内存）。"""
import datetime as dt
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy import text as _text
from sqlmodel import Session, SQLModel

from src.infra.database.portfolio.thesis_models import (
    InvestmentThesis,
    PassDecision,
    ThesisCondition,
    ThesisEvent,
    ThesisJournal,
    ThesisReeval,
)
from src.infra.database.portfolio.thesis_repository import (
    ThesisRepository,
)


class _SqliteDb:
    """仅提供 session_scope 的 DBConnection 替身。"""

    def __init__(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(
            self.engine,
            tables=[
                InvestmentThesis.__table__,
                ThesisCondition.__table__,
                ThesisReeval.__table__,
                ThesisEvent.__table__,
                ThesisJournal.__table__,
                PassDecision.__table__,
            ],
        )

    @contextmanager
    def session_scope(self):
        session = Session(self.engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


@pytest.fixture()
def repo():
    return ThesisRepository(_SqliteDb())


def test_thesis_crud_and_close(repo):
    tid = repo.create_thesis({
        "symbol": "sh600519", "thesis_text": "高端白酒护城河",
        "buy_date": dt.date(2026, 1, 10), "buy_price": 1500.0,
        "shares": 100,
        "snapshot": {"price": 1500.0},
        "target_band": {"metric": "pe_ttm", "low": 25, "high": 35},
    })
    assert tid > 0
    theses = repo.list_theses(status="active")
    assert len(theses) == 1 and theses[0]["symbol"] == "sh600519"
    repo.update_thesis(tid, decision="hold", decision_note="持有")
    assert repo.get_thesis(tid)["decision"] == "hold"
    repo.close_thesis(tid, reason="valuation_reached", price=2100.0)
    assert repo.get_thesis(tid)["status"] == "closed"
    assert repo.list_theses(status="active") == []
    assert len(repo.list_theses(status="closed")) == 1


def test_conditions_replace(repo):
    tid = repo.create_thesis({"symbol": "sz000001"})
    repo.replace_conditions(tid, [
        {"metric_key": "roe", "operator": ">=", "threshold": 15,
         "label": "ROE>=15"},
    ])
    assert len(repo.list_conditions(tid)) == 1
    repo.replace_conditions(tid, [
        {"metric_key": "roe", "operator": ">=", "threshold": 12,
         "label": "ROE>=12"},
        {"metric_key": "debt_ratio", "operator": "<=", "threshold": 60,
         "label": "负债率<=60"},
    ])
    conds = repo.list_conditions(tid)
    assert len(conds) == 2 and conds[0]["threshold"] == 12


def test_reeval_unique_and_latest(repo):
    tid = repo.create_thesis({"symbol": "sh600519"})
    repo.add_reeval({
        "thesis_id": tid, "report_date": dt.date(2026, 6, 30),
        "trigger": "formal", "quality_now": {"score": 80},
        "verdict": "pass",
    })
    dup = repo.add_reeval({
        "thesis_id": tid, "report_date": dt.date(2026, 6, 30),
        "trigger": "formal", "quality_now": {"score": 80},
        "verdict": "pass",
    })
    assert dup is None  # 幂等：同 thesis+report_date+trigger 不重复
    assert len(repo.list_reevals(tid)) == 1
    assert repo.latest_reeval_report_date(tid) == dt.date(2026, 6, 30)


def test_events_read_and_band_dedup(repo):
    tid = repo.create_thesis({"symbol": "sh600519"})
    repo.add_event(tid, "price_band_reached",
                   {"band": "pe_ttm:25:35", "alerted": True})
    assert repo.has_band_event(tid, "pe_ttm:25:35") is True
    assert repo.has_band_event(tid, "pe_ttm:30:40") is False
    evs = repo.list_events(unread_only=True)
    assert len(evs) == 1 and evs[0]["read"] is False
    repo.mark_event_read(evs[0]["id"])
    assert repo.list_events(unread_only=True) == []


# ── 第3期：决策日志 + 复盘记录 ────────────────────────────────────────────
def test_journal_and_review_log(repo):
    from src.infra.database.portfolio.thesis_models import (
        ThesisJournal,
        ThesisReviewLog,
    )
    import sqlalchemy as sa
    engine = repo._db.engine
    ThesisJournal.metadata.create_all(
        engine, tables=[ThesisJournal.__table__])
    ThesisReviewLog.metadata.create_all(
        engine, tables=[ThesisReviewLog.__table__])

    tid = repo.create_thesis({"symbol": "sh600519"})
    jid = repo.add_journal(tid, "created", decision=None,
                           note="初始登记", price=1500.0)
    assert jid > 0
    repo.add_journal(tid, "decision", decision="hold",
                     note="逻辑未变", price=1600.0)
    rows = repo.list_journal(tid)   # 倒序：最新在前
    assert [r["kind"] for r in rows] == ["decision", "created"]
    assert rows[0]["price"] == 1600.0

    all_rows = repo.list_journal_all(limit=10)
    assert len(all_rows) == 2

    repo.add_review_log(note="月度复盘")
    repo.add_review_log(note=None)
    latest = repo.latest_review_at()
    assert latest is not None


# ── 第5期: 排雷结果 ────────────────────────────────────────────────────────
def test_mine_upsert_and_list(repo):
    import datetime as dtdt
    from src.infra.database.portfolio.thesis_models import (
        MineScreeningResult,
    )
    repo._db.engine  # ensure engine
    SQLModel.metadata.create_all(
        repo._db.engine, tables=[MineScreeningResult.__table__])
    # stock_info 名称源（sqlite 手工建同名表）
    with Session(repo._db.engine) as s:
        s.exec(_text(
            "CREATE TABLE stock_info (symbol TEXT PRIMARY KEY, name TEXT)"
        ))
        s.exec(_text(
            "INSERT INTO stock_info VALUES ('sh600519', '贵州茅台')"
        ))
        s.commit()
    rd = dt.date(2026, 6, 30)
    rows = [
        {"symbol": "sh600519", "report_date": rd, "z": 1.5,
         "z_verdict": "distress", "risk_level": "high",
         "source": "positions"},
        {"symbol": "sz000001", "report_date": rd, "z": 2.5,
         "z_verdict": "grey", "risk_level": "medium",
         "source": "market"},
    ]
    assert repo.upsert_mine_results(rows) == 2
    # 幂等 upsert：同 symbol+report_date 更新不新增
    rows[0]["z"] = 1.2
    repo.upsert_mine_results(rows)
    mines = repo.list_mines()
    assert len(mines) == 2
    sh = next(m for m in mines if m["symbol"] == "sh600519")
    assert sh["z"] == 1.2 and sh["risk_level"] == "high"
    only_high = repo.list_mines(level="high")
    assert [m["symbol"] for m in only_high] == ["sh600519"]

    # names_for 名称映射 + list_mines 名称回填
    assert repo.names_for(["sh600519", "sz不存在"]) == {"sh600519": "贵州茅台"}
    assert repo.names_for([]) == {}
    mines = repo.list_mines()
    sh = next(m for m in mines if m["symbol"] == "sh600519")
    assert sh["name"] == "贵州茅台"
    sz = next(m for m in mines if m["symbol"] == "sz000001")
    assert sz["name"] is None

    tid = repo.create_thesis({"symbol": "sh600519"})
    repo.add_event(tid, "mine_detected",
                   {"risk": "high", "report_date": rd.isoformat()})
    assert repo.has_event_detail(
        tid, "mine_detected", "report_date", rd.isoformat()) is True
    assert repo.has_event_detail(
        tid, "mine_detected", "report_date", "2020-01-01") is False


# ── 第6期V2: 资本事件 ──────────────────────────────────────────────────────
def test_capital_events_upsert_and_list(repo):
    from src.infra.database.portfolio.thesis_models import (
        CapitalEvent,
    )
    SQLModel.metadata.create_all(
        repo._db.engine, tables=[CapitalEvent.__table__])
    rows = [
        {"symbol": "sh600519", "event_type": "buyback",
         "announce_date": dt.date(2026, 9, 20), "holder_name": "",
         "start_date": dt.date(2026, 8, 1),
         "shares_wan": 100.0, "amount": 1.5e8, "ratio_pct": None,
         "progress": "完成实施"},
    ]
    n1 = repo.upsert_capital_events(rows)
    n2 = repo.upsert_capital_events(rows)   # 幂等：冲突跳过
    assert n1 >= 1
    evs = repo.list_capital_events("sh600519", months=24)
    assert len(evs) == 1 and evs[0]["event_type"] == "buyback"
    assert evs[0]["announce_date"] == "2026-09-20"


# ── 增强: 温度计日快照 ────────────────────────────────────────────────────
def test_thermometer_upsert_and_list(repo):
    from src.infra.database.portfolio.thesis_models import (
        MarketThermometerDaily,
    )
    SQLModel.metadata.create_all(
        repo._db.engine, tables=[MarketThermometerDaily.__table__])
    rows = [
        {"symbol": "sh000300", "trade_date": dt.date(2026, 9, 26),
         "ep_pct": 8.0, "erp_pct": 6.0, "level": "deep_cold",
         "level_label": "极冷", "position_low": 80,
         "position_high": 90},
    ]
    assert repo.upsert_thermometer_rows(rows) == 1
    rows[0]["erp_pct"] = 6.1
    repo.upsert_thermometer_rows(rows)     # 幂等更新
    out = repo.list_thermometer(days=365)
    assert len(out) == 1 and out[0]["erp_pct"] == 6.1
    assert out[0]["position_band"] == {"low": 80, "high": 90}


# ── 决策日志补全: journal 新列 + pass_decision CRUD ──────────────────────
def test_journal_confidence_catalysts_roundtrip(repo):
    tid = repo.create_thesis({"symbol": "sh600519",
                              "thesis_text": "t"})
    jid = repo.add_journal(tid, "created", note="买入逻辑",
                           price=1500.0, confidence=4,
                           catalysts="年报")
    rows = repo.list_journal(tid)
    assert rows[0]["id"] == jid
    assert rows[0]["confidence"] == 4
    assert rows[0]["catalysts"] == "年报"


def test_pass_decision_crud(repo):
    pid = repo.add_pass_decision({
        "symbol": "sh600519", "decision_date": dt.date(2026, 1, 10),
        "price": 1500.0, "reason": "估值太贵",
        "revisit_when": "PE<25", "confidence": 4,
        "snapshot": {"price": 1500.0},
    })
    rows = repo.list_pass_decisions()
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == pid and r["symbol"] == "sh600519"
    assert r["decision_date"] == "2026-01-10"
    assert r["reason"] == "估值太贵" and r["confidence"] == 4
    assert repo.delete_pass_decision(pid) is True
    assert repo.list_pass_decisions() == []
    assert repo.delete_pass_decision(pid) is False
