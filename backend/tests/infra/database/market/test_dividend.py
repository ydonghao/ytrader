"""StockDividend 仓储测试 — sqlite in-memory，不依赖真实 PG。

注：bulk_upsert 用 psycopg2 直连 PG（ON CONFLICT 批量），由同步任务
做集成验证；此处覆盖 ORM 路径（upsert / get_history / get_latest_ex_date）。
"""
from contextlib import contextmanager
from datetime import date

from sqlmodel import Session, SQLModel, create_engine

from src.infra.database.market.dividend import (
    StockDividend,
    StockDividendRepository,
)


class _FakeDb:
    """模拟 DBConnection，session_scope 返回 sqlite session。"""

    def __init__(self, engine):
        self._engine = engine

    @contextmanager
    def session_scope(self):
        with Session(self._engine) as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise


def _make_repo():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine, tables=[StockDividend.__table__])
    return StockDividendRepository(_FakeDb(engine))


def test_upsert_insert_then_overwrite():
    repo = _make_repo()
    repo.upsert("sh600000", date(2024, 6, 1), div_per_share=0.30)
    repo.upsert("sh600000", date(2024, 6, 1), div_per_share=0.35)  # 覆盖
    rows = repo.get_history("sh600000")
    assert len(rows) == 1
    assert rows[0].div_per_share == 0.35


def test_get_history_ordered_asc_and_range_filtered():
    repo = _make_repo()
    repo.upsert("sh600000", date(2023, 6, 1), div_per_share=0.20)
    repo.upsert("sh600000", date(2024, 6, 1), div_per_share=0.30)
    repo.upsert("sh600000", date(2024, 12, 1), div_per_share=0.10)
    rows = repo.get_history(
        "sh600000", start=date(2024, 1, 1), end=date(2024, 12, 31)
    )
    assert [r.ex_date for r in rows] == [date(2024, 6, 1), date(2024, 12, 1)]


def test_get_latest_ex_date():
    repo = _make_repo()
    repo.upsert("sh600000", date(2023, 6, 1), div_per_share=0.20)
    repo.upsert("sh600000", date(2024, 6, 1), div_per_share=0.30)
    assert repo.get_latest_ex_date("sh600000") == date(2024, 6, 1)


def test_get_latest_ex_date_none_when_empty():
    repo = _make_repo()
    assert repo.get_latest_ex_date("sh600000") is None


def test_get_history_empty_when_no_symbol():
    repo = _make_repo()
    assert repo.get_history("sh000001") == []
