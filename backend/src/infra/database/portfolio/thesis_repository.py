"""持仓论点 repository：4 表 CRUD + 收盘价/新报告检测查询。"""
import datetime as dt
from datetime import datetime
from typing import Optional

from sqlalchemy import bindparam, text
from sqlmodel import select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn

from .thesis_models import (
    CapitalEvent,
    InvestmentThesis,
    MarketThermometerDaily,
    PassDecision,
    ResearchNote,
    ThesisLadderFill,
    MineScreeningResult,
    ThesisCondition,
    ThesisEvent,
    ThesisJournal,
    ThesisReeval,
    ThesisReviewLog,
)


def _thesis_dict(t: InvestmentThesis) -> dict:
    return {
        "id": t.id, "symbol": t.symbol, "status": t.status,
        "buy_date": t.buy_date.isoformat() if t.buy_date else None,
        "buy_price": t.buy_price, "shares": t.shares,
        "thesis_text": t.thesis_text, "snapshot": t.snapshot,
        "target_band": t.target_band, "entry_ladder": t.entry_ladder,
        "decision": t.decision,
        "decision_note": t.decision_note,
        "decision_at": t.decision_at.isoformat()
        if t.decision_at else None,
        "last_reviewed_at": t.last_reviewed_at.isoformat()
        if t.last_reviewed_at else None,
        "close_reason": t.close_reason, "close_price": t.close_price,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        "created_at": t.created_at.isoformat(),
    }


class ThesisRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    # ── 论点 CRUD ─────────────────────────────────────────────
    def create_thesis(self, data: dict) -> int:
        with self._db.session_scope() as s:
            t = InvestmentThesis(**data)
            s.add(t)
            s.flush()
            return t.id

    def list_theses(self, status: Optional[str] = None) -> list:
        with self._db.session_scope() as s:
            q = select(InvestmentThesis).order_by(
                InvestmentThesis.created_at.desc()
            )
            if status:
                q = q.where(InvestmentThesis.status == status)
            return [_thesis_dict(t) for t in s.exec(q).all()]

    def get_thesis(self, thesis_id: int) -> Optional[dict]:
        with self._db.session_scope() as s:
            t = s.get(InvestmentThesis, thesis_id)
            return _thesis_dict(t) if t else None

    def update_thesis(self, thesis_id: int, **fields) -> bool:
        with self._db.session_scope() as s:
            t = s.get(InvestmentThesis, thesis_id)
            if not t:
                return False
            for k, v in fields.items():
                setattr(t, k, v)
            t.updated_at = datetime.now()
            return True

    def close_thesis(self, thesis_id: int, reason: str,
                     price: Optional[float] = None) -> bool:
        return self.update_thesis(
            thesis_id, status="closed", close_reason=reason,
            close_price=price, closed_at=datetime.now(),
        )

    # ── 研究笔记（二期F6） ─────────────────────────────────────
    def list_notes(self, symbol: Optional[str] = None) -> list:
        with self._db.session_scope() as s:
            q = select(ResearchNote).order_by(
                ResearchNote.updated_at.desc()
            ).limit(200)
            if symbol:
                q = q.where(ResearchNote.symbol == symbol)
            return [
                {
                    "id": r.id, "symbol": r.symbol, "title": r.title,
                    "content": r.content,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat(),
                }
                for r in s.exec(q).all()
            ]

    def add_note(self, symbol: str, title: str,
                 content: str = "") -> int:
        with self._db.session_scope() as s:
            n = ResearchNote(
                symbol=symbol, title=title, content=content,
            )
            s.add(n)
            s.flush()
            return n.id

    def update_note(self, note_id: int, title: str,
                    content: str) -> bool:
        with self._db.session_scope() as s:
            n = s.get(ResearchNote, note_id)
            if not n:
                return False
            n.title, n.content = title, content
            n.updated_at = datetime.now()
            return True

    def delete_note(self, note_id: int) -> bool:
        with self._db.session_scope() as s:
            n = s.get(ResearchNote, note_id)
            if not n:
                return False
            s.delete(n)
            return True

    # ── 建仓成交（二期F5） ─────────────────────────────────────
    def add_ladder_fill(self, thesis_id: int, rung_index: int,
                        price: float, shares: int) -> int:
        with self._db.session_scope() as s:
            f = ThesisLadderFill(
                thesis_id=thesis_id, rung_index=rung_index,
                price=price, shares=shares,
            )
            s.add(f)
            s.flush()
            return f.id

    def list_ladder_fills(self, thesis_id: int) -> list:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(ThesisLadderFill)
                .where(ThesisLadderFill.thesis_id == thesis_id)
                .order_by(ThesisLadderFill.filled_at)
            ).all()
            return [
                {
                    "id": r.id, "rung_index": r.rung_index,
                    "price": r.price, "shares": r.shares,
                    "filled_at": r.filled_at.isoformat(),
                }
                for r in rows
            ]

    def delete_ladder_fill(self, fill_id: int) -> bool:
        with self._db.session_scope() as s:
            f = s.get(ThesisLadderFill, fill_id)
            if not f:
                return False
            s.delete(f)
            return True

    def ensure_thesis_ladder_column(self) -> None:
        """investment_thesis.entry_ladder 幂等加列（无 Alembic）。"""
        from sqlalchemy import text as _text
        try:
            with self._db.session_scope() as s:
                s.execute(_text(
                    "ALTER TABLE investment_thesis "
                    "ADD COLUMN IF NOT EXISTS entry_ladder JSON"
                ))
        except Exception:
            pass   # sqlite 测试/列已存在

    # ── 假设条件（整表替换） ───────────────────────────────────
    def replace_conditions(self, thesis_id: int, items: list) -> int:
        with self._db.session_scope() as s:
            olds = s.exec(
                select(ThesisCondition).where(
                    ThesisCondition.thesis_id == thesis_id
                )
            ).all()
            for o in olds:
                s.delete(o)
            for it in items:
                s.add(ThesisCondition(thesis_id=thesis_id, **it))
            return len(items)

    def list_conditions(self, thesis_id: int) -> list:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(ThesisCondition)
                .where(ThesisCondition.thesis_id == thesis_id)
                .order_by(ThesisCondition.id)
            ).all()
            return [
                {
                    "id": r.id, "thesis_id": r.thesis_id,
                    "metric_key": r.metric_key, "operator": r.operator,
                    "threshold": r.threshold, "label": r.label,
                    "status": r.status,
                    "breached_at": r.breached_at.isoformat()
                    if r.breached_at else None,
                }
                for r in rows
            ]

    def update_condition_status(self, cond_id: int, status: str) -> bool:
        with self._db.session_scope() as s:
            c = s.get(ThesisCondition, cond_id)
            if not c:
                return False
            c.status = status
            if status == "breached" and not c.breached_at:
                c.breached_at = datetime.now()
            return True

    # ── 重估历史（幂等） ───────────────────────────────────────
    def add_reeval(self, row: dict) -> Optional[int]:
        with self._db.session_scope() as s:
            exists = s.exec(
                select(ThesisReeval).where(
                    ThesisReeval.thesis_id == row["thesis_id"],
                    ThesisReeval.report_date == row.get("report_date"),
                    ThesisReeval.trigger == row["trigger"],
                )
            ).first()
            if exists:
                return None
            r = ThesisReeval(**row)
            s.add(r)
            s.flush()
            return r.id

    def list_reevals(self, thesis_id: int, limit: int = 50) -> list:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(ThesisReeval)
                .where(ThesisReeval.thesis_id == thesis_id)
                .order_by(ThesisReeval.created_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "id": r.id,
                    "report_date": r.report_date.isoformat()
                    if r.report_date else None,
                    "trigger": r.trigger, "quality_now": r.quality_now,
                    "quality_delta": r.quality_delta,
                    "valuation_now": r.valuation_now,
                    "conditions_result": r.conditions_result,
                    "verdict": r.verdict,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]

    def latest_reeval_report_date(self, thesis_id: int):
        with self._db.session_scope() as s:
            r = s.exec(
                select(ThesisReeval)
                .where(ThesisReeval.thesis_id == thesis_id)
                .order_by(ThesisReeval.report_date.desc())
            ).first()
            return r.report_date if r else None

    # ── 事件 ──────────────────────────────────────────────────
    def add_event(self, thesis_id: int, kind: str,
                  detail: Optional[dict] = None) -> int:
        with self._db.session_scope() as s:
            e = ThesisEvent(
                thesis_id=thesis_id, kind=kind, detail=detail
            )
            s.add(e)
            s.flush()
            return e.id

    def list_events(self, unread_only: bool = False,
                    limit: int = 100) -> list:
        with self._db.session_scope() as s:
            q = select(ThesisEvent).order_by(
                ThesisEvent.created_at.desc()
            ).limit(limit)
            if unread_only:
                q = q.where(ThesisEvent.read == False)  # noqa: E712
            rows = s.exec(q).all()
            return [
                {
                    "id": r.id, "thesis_id": r.thesis_id,
                    "kind": r.kind, "detail": r.detail, "read": r.read,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]

    def mark_event_read(self, event_id: int) -> bool:
        with self._db.session_scope() as s:
            e = s.get(ThesisEvent, event_id)
            if not e:
                return False
            e.read = True
            return True

    def has_event_detail(self, thesis_id: int, kind: str,
                         detail_key: str, detail_value) -> bool:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(ThesisEvent).where(
                    ThesisEvent.thesis_id == thesis_id,
                    ThesisEvent.kind == kind,
                )
            ).all()
            return any(
                (r.detail or {}).get(detail_key) == detail_value
                for r in rows
            )

    # ── 排雷扫描结果（第5期） ──────────────────────────────────
    def upsert_mine_results(self, rows: list) -> int:
        with self._db.session_scope() as s:
            syms = list({r["symbol"] for r in rows})
            existing = {
                (r.symbol, r.report_date): r
                for r in s.exec(
                    select(MineScreeningResult).where(
                        MineScreeningResult.symbol.in_(syms)
                    )
                ).all()
            }
            for row in rows:
                key = (row["symbol"], row.get("report_date"))
                old = existing.get(key)
                if old:
                    for k, v in row.items():
                        setattr(old, k, v)
                    old.scanned_at = datetime.now()
                else:
                    s.add(MineScreeningResult(**row))
            return len(rows)

    def names_for(self, symbols: list) -> dict:
        """批量查股票名称（stock_info；expanding IN 兼容 pg/sqlite）。"""
        if not symbols:
            return {}
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT symbol, name FROM stock_info "
                    "WHERE symbol IN :syms"
                ).bindparams(bindparam("syms", expanding=True)),
                {"syms": list(set(symbols))},
            ).all()
            return {r[0]: r[1] for r in rows if r[1]}

    def list_mines(self, level: str = None, limit: int = 100) -> list:
        with self._db.session_scope() as s:
            q = select(MineScreeningResult).order_by(
                MineScreeningResult.scanned_at.desc()
            ).limit(limit)
            if level:
                q = q.where(MineScreeningResult.risk_level == level)
            rows = [
                {
                    "symbol": r.symbol,
                    "report_date": r.report_date.isoformat()
                    if r.report_date else None,
                    "z": r.z, "z_verdict": r.z_verdict,
                    "m": r.m, "m_verdict": r.m_verdict,
                    "m_partial": r.m_partial,
                    "fraud_severity": r.fraud_severity,
                    "fraud_flags": r.fraud_flags,
                    "risk_level": r.risk_level, "source": r.source,
                    "scanned_at": r.scanned_at.isoformat(),
                }
                for r in s.exec(q).all()
            ]
        names = self.names_for(list({r["symbol"] for r in rows}))
        for r in rows:
            r["name"] = names.get(r["symbol"])
        return rows

    def latest_market_caps(self, symbols: list) -> dict:
        if not symbols:
            return {}
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT DISTINCT ON (symbol) symbol, total_mv "
                    "FROM stock_valuation WHERE symbol = ANY(:syms) "
                    "ORDER BY symbol, trade_date DESC"
                ),
                {"syms": list(symbols)},
            ).all()
            return {r[0]: float(r[1]) for r in rows
                    if r[1] is not None}

    def all_financial_symbols(self) -> list:
        with self._db.session_scope() as s:
            rows = s.execute(
                text("SELECT DISTINCT symbol FROM stock_financial_detail")
            ).all()
            return [r[0] for r in rows]

    def has_band_event(self, thesis_id: int, band_key: str) -> bool:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(ThesisEvent).where(
                    ThesisEvent.thesis_id == thesis_id,
                    ThesisEvent.kind == "price_band_reached",
                )
            ).all()
            return any(
                (r.detail or {}).get("band") == band_key for r in rows
            )

    # ── 决策日志 + 复盘记录（第3期） ───────────────────────────
    def add_journal(self, thesis_id: int, kind: str,
                    decision: Optional[str] = None,
                    note: Optional[str] = None,
                    price: Optional[float] = None,
                    confidence: Optional[int] = None,
                    catalysts: Optional[str] = None) -> int:
        with self._db.session_scope() as s:
            j = ThesisJournal(
                thesis_id=thesis_id, kind=kind, decision=decision,
                note=note, price=price, confidence=confidence,
                catalysts=catalysts,
            )
            s.add(j)
            s.flush()
            return j.id

    def list_journal(self, thesis_id: int,
                     limit: int = 100) -> list:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(ThesisJournal)
                .where(ThesisJournal.thesis_id == thesis_id)
                .order_by(ThesisJournal.created_at.desc())
                .limit(limit)
            ).all()
            return [self._journal_dict(r) for r in rows]

    def list_journal_all(self, limit: int = 100) -> list:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(ThesisJournal)
                .order_by(ThesisJournal.created_at.desc())
                .limit(limit)
            ).all()
            return [self._journal_dict(r) for r in rows]

    @staticmethod
    def _journal_dict(r) -> dict:
        return {
            "id": r.id, "thesis_id": r.thesis_id, "kind": r.kind,
            "decision": r.decision, "note": r.note, "price": r.price,
            "confidence": r.confidence, "catalysts": r.catalysts,
            "created_at": r.created_at.isoformat(),
        }

    def ensure_journal_columns(self) -> None:
        """thesis_journal 幂等加列 confidence/catalysts（无 Alembic）。"""
        from sqlalchemy import text as _text
        try:
            with self._db.session_scope() as s:
                s.execute(_text(
                    "ALTER TABLE thesis_journal "
                    "ADD COLUMN IF NOT EXISTS confidence INTEGER"
                ))
                s.execute(_text(
                    "ALTER TABLE thesis_journal "
                    "ADD COLUMN IF NOT EXISTS catalysts TEXT"
                ))
        except Exception:
            pass   # sqlite 测试/列已存在

    # ── 放弃决策（决策经验的另一半） ──────────────────────────
    def add_pass_decision(self, data: dict) -> int:
        with self._db.session_scope() as s:
            p = PassDecision(**data)
            s.add(p)
            s.flush()
            return p.id

    def list_pass_decisions(self, limit: int = 200) -> list:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(PassDecision)
                .order_by(PassDecision.created_at.desc())
                .limit(limit)
            ).all()
            return [self._pass_dict(r) for r in rows]

    def delete_pass_decision(self, pass_id: int) -> bool:
        with self._db.session_scope() as s:
            p = s.get(PassDecision, pass_id)
            if not p:
                return False
            s.delete(p)
            return True

    @staticmethod
    def _pass_dict(r) -> dict:
        return {
            "id": r.id, "symbol": r.symbol,
            "decision_date": r.decision_date.isoformat()
            if r.decision_date else None,
            "price": r.price, "reason": r.reason,
            "revisit_when": r.revisit_when, "confidence": r.confidence,
            "created_at": r.created_at.isoformat(),
        }

    def add_review_log(self, note: Optional[str] = None) -> int:
        with self._db.session_scope() as s:
            v = ThesisReviewLog(note=note)
            s.add(v)
            s.flush()
            return v.id

    def latest_review_at(self):
        with self._db.session_scope() as s:
            r = s.exec(
                select(ThesisReviewLog)
                .order_by(ThesisReviewLog.created_at.desc())
            ).first()
            return r.created_at if r else None

    # ── 组合风险查询（二期F1） ─────────────────────────────────
    def latest_industry_map(self, symbols: list) -> dict:
        """{symbol: (sw_code_l1, sw_name_l1)}——sw_industry_member 成分。"""
        if not symbols:
            return {}
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT symbol, sw_code_l1, sw_name_l1 "
                    "FROM sw_industry_member WHERE symbol = ANY(:syms)"
                ),
                {"syms": list(symbols)},
            ).all()
            return {r[0]: (r[1], r[2]) for r in rows if r[1]}

    def daily_returns(self, symbols: list,
                      days: int = 260) -> dict:
        """近 N 自然日日收益序列（对齐日期交集对不齐时按各序列算）。"""
        if not symbols:
            return {}
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT symbol, trade_date, close_ FROM stock_ohlcv "
                    "WHERE symbol = ANY(:syms) "
                    "AND trade_date >= CURRENT_DATE - :days "
                    "ORDER BY symbol, trade_date"
                ),
                {"syms": list(symbols), "days": days},
            ).all()
        closes: dict = {}
        for sym, d, c in rows:
            if c is not None:
                closes.setdefault(sym, []).append((str(d), float(c)))
        out = {}
        for sym, series in closes.items():
            vals = [v for _, v in series]
            out[sym] = [
                (vals[i] - vals[i - 1]) / vals[i - 1]
                for i in range(1, len(vals)) if vals[i - 1] > 0
            ]
        return out

    def latest_metrics_map(self, symbols: list) -> dict:
        """{symbol: {pe_ttm, pb, total_mv}}——stock_valuation 最新行。"""
        if not symbols:
            return {}
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT DISTINCT ON (symbol) symbol, pe_ttm, pb, "
                    "total_mv FROM stock_valuation "
                    "WHERE symbol = ANY(:syms) "
                    "ORDER BY symbol, trade_date DESC"
                ),
                {"syms": list(symbols)},
            ).all()
            return {
                r[0]: {"pe_ttm": r[1], "pb": r[2], "total_mv": r[3]}
                for r in rows
            }

    # ── 资本事件（第6期V2） ────────────────────────────────────
    def upsert_capital_events(self, rows: list) -> int:
        """批量幂等 upsert：预载已存五元组键集，跳过冲突/重复行。"""
        n = 0
        with self._db.session_scope() as s:
            seen: set = set()
            for i in range(0, len(rows), 500):
                batch = rows[i:i + 500]
                if not batch:
                    continue
                syms = list({r["symbol"] for r in batch})
                existing = {
                    (r.symbol, r.event_type, r.announce_date,
                     r.holder_name, r.start_date)
                    for r in s.exec(
                        select(CapitalEvent).where(
                            CapitalEvent.symbol.in_(syms)
                        )
                    ).all()
                }
                fresh = []
                for r in batch:
                    key = (r["symbol"], r["event_type"],
                           r.get("announce_date"),
                           r.get("holder_name") or "",
                           r.get("start_date"))
                    if key in existing or key in seen:
                        continue   # 库内已存 或 本轮源数据重复
                    seen.add(key)
                    fresh.append(r)
                for r in fresh:
                    s.add(CapitalEvent(**r))
                n += len(fresh)
        return n

    def list_capital_events(self, symbol: str, months: int = 24,
                            limit: int = 200) -> list:
        from datetime import timedelta
        cutoff = dt.date.today() - timedelta(days=months * 30)
        with self._db.session_scope() as s:
            q = (
                select(CapitalEvent)
                .where(CapitalEvent.symbol == symbol,
                       CapitalEvent.announce_date >= cutoff)
                .order_by(CapitalEvent.announce_date.desc())
                .limit(limit)
            )
            return [
                {
                    "symbol": r.symbol, "event_type": r.event_type,
                    "announce_date": r.announce_date.isoformat()
                    if r.announce_date else None,
                    "holder_name": r.holder_name,
                    "start_date": r.start_date.isoformat()
                    if r.start_date else None,
                    "shares_wan": r.shares_wan, "amount": r.amount,
                    "ratio_pct": r.ratio_pct, "progress": r.progress,
                }
                for r in s.exec(q).all()
            ]

    # ── 温度计日快照 ──────────────────────────────────────────
    def upsert_thermometer_rows(self, rows: list) -> int:
        with self._db.session_scope() as s:
            for i in range(0, len(rows), 500):
                batch = rows[i:i + 500]
                if not batch:
                    continue
                syms = list({r["symbol"] for r in batch})
                existing = {
                    (r.symbol, r.trade_date): r
                    for r in s.exec(
                        select(MarketThermometerDaily).where(
                            MarketThermometerDaily.symbol.in_(syms)
                        )
                    ).all()
                }
                for r in batch:
                    old = existing.get((r["symbol"], r["trade_date"]))
                    if old:
                        for k, v in r.items():
                            if k not in ("symbol", "trade_date"):
                                setattr(old, k, v)
                    else:
                        s.add(MarketThermometerDaily(**r))
            return len(rows)

    def list_thermometer(self, symbol: str = "sh000300",
                         days: int = 365) -> list:
        from datetime import timedelta
        cutoff = dt.date.today() - timedelta(days=days)
        with self._db.session_scope() as s:
            rows = s.exec(
                select(MarketThermometerDaily)
                .where(MarketThermometerDaily.symbol == symbol,
                       MarketThermometerDaily.trade_date >= cutoff)
                .order_by(MarketThermometerDaily.trade_date.asc())
            ).all()
            return [
                {
                    "trade_date": r.trade_date.isoformat(),
                    "ep_pct": r.ep_pct, "erp_pct": r.erp_pct,
                    "level": r.level, "level_label": r.level_label,
                    "position_band": (
                        {"low": r.position_low, "high": r.position_high}
                        if r.position_low is not None else None
                    ),
                    "erp_percentile": r.erp_percentile,
                    "buffett_pct": r.buffett_pct,
                    "buffett_level": r.buffett_level,
                }
                for r in rows
            ]

    # ── 行情/新报告检测（裸 SQL 表，text() 查询） ─────────────
    # 注：ANY(:syms) 为 PG 语法，仅生产库使用；sqlite 测试不覆盖。
    def latest_close(self, symbols: list) -> dict:
        if not symbols:
            return {}
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT symbol, close_ FROM stock_ohlcv "  # 列名 close_
                    "WHERE symbol = ANY(:syms) "
                    "AND (symbol, trade_date) IN ("
                    "  SELECT symbol, MAX(trade_date) FROM stock_ohlcv "
                    "  WHERE symbol = ANY(:syms) GROUP BY symbol)"
                ),
                {"syms": list(symbols)},
            ).all()
            return {r[0]: float(r[1]) for r in rows if r[1] is not None}

    def latest_report_dates(self, symbols: list) -> dict:
        if not symbols:
            return {}
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT symbol, MAX(report_date) "
                    "FROM stock_financial_detail "
                    "WHERE symbol = ANY(:syms) GROUP BY symbol"
                ),
                {"syms": list(symbols)},
            ).all()
            return {r[0]: r[1] for r in rows if r[0]}

    def latest_earnings_dates(self, symbols: list) -> dict:
        """{symbol: (report_date, announce_date, forecast_type)}。"""
        if not symbols:
            return {}
        with self._db.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT DISTINCT ON (symbol) symbol, report_date, "
                    "announce_date, forecast_type "
                    "FROM stock_earnings_forecast "
                    "WHERE symbol = ANY(:syms) "
                    "ORDER BY symbol, announce_date DESC"
                ),
                {"syms": list(symbols)},
            ).all()
            return {r[0]: (r[1], r[2], r[3]) for r in rows if r[0]}


_db_connection: DBConnection | None = None


def create_thesis_repository(
    db_connection: DBConnection | None = None,
) -> ThesisRepository:
    global _db_connection
    if db_connection is None:
        if _db_connection is None:
            _db_connection = create_db_connection(get_dsn())
        db_connection = _db_connection
    return ThesisRepository(db_connection)
