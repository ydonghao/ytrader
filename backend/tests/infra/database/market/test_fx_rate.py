"""FxRate 仓储测试 — sqlite in-memory，不依赖真实 PG。"""
from contextlib import contextmanager
from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select

from src.infra.database.market.fx_rate import FxRate, FxRateRepository


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
    SQLModel.metadata.create_all(engine, tables=[FxRate.__table__])
    return FxRateRepository(_FakeDb(engine))


def test_upsert_insert_then_update_idempotent():
    repo = _make_repo()
    repo.upsert(date(2026, 6, 20), "USDCNY", 6.81)
    repo.upsert(date(2026, 6, 20), "USDCNY", 6.82)  # 同日覆盖
    assert repo.get_latest_date("USDCNY") == date(2026, 6, 20)


def test_get_latest_date_none_when_empty():
    repo = _make_repo()
    assert repo.get_latest_date("USDCNY") is None


def test_upsert_multiple_dates_latest_wins():
    repo = _make_repo()
    repo.upsert(date(2026, 6, 19), "USDCNY", 6.80)
    repo.upsert(date(2026, 6, 20), "USDCNY", 6.81)
    assert repo.get_latest_date("USDCNY") == date(2026, 6, 20)


def test_upsert_overwrites_rate_value_and_does_not_duplicate():
    """同日 upsert 应覆盖 rate/source，且不产生重复行。"""
    repo = _make_repo()
    repo.upsert(date(2026, 6, 20), "USDCNY", 6.81, source="akshare")
    repo.upsert(date(2026, 6, 20), "USDCNY", 6.99, source="manual")

    engine = repo._db._engine  # noqa: SLF001 — 测试内部断言行数
    with Session(engine) as s:
        rows = list(s.exec(select(FxRate).where(FxRate.pair == "USDCNY")))

    assert len(rows) == 1  # 不重复
    assert rows[0].rate == 6.99
    assert rows[0].source == "manual"
