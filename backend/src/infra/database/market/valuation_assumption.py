"""估值假设版本表 + 仓储（2026-10 假设版本化）。

此前 DCF 假设只活在前端 useState/URL 参数里，"当时的判断依据"随
浏览器关闭即散失；本表把每家公司每组假设按版本沉淀，并在保存时快照
当时输出（内在价值/市值/安全边际/基础FCF），供日后按原假设重跑对比——
区分"基本面变了"（判断驱动）还是"只有价格变了"（情绪驱动）。
"""
import datetime as dt
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class ValuationAssumption(SQLModel, table=True):
    """一组估值假设的一个版本（symbol+method 内版本自增）。"""

    __tablename__ = "valuation_assumption"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    method: str = "dcf"      # dcf | ddm | ...
    version: int = 1
    assumptions: dict = Field(default_factory=dict,
                              sa_column=Column(JSON))
    # {growth_rate, terminal_growth, wacc, projection_years, ...}
    output: Optional[dict] = Field(
        default=None, sa_column=Column(JSON))
    # 保存时输出快照 {intrinsic_value, market_value,
    #  margin_of_safety, fcf_base, report_date}
    note: Optional[str] = None   # 为什么用这组假设
    created_at: datetime = Field(default_factory=datetime.now)


class ValuationAssumptionRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    def add(self, symbol: str, method: str, assumptions: dict,
            output: Optional[dict] = None,
            note: Optional[str] = None) -> dict:
        """追加一个版本（symbol+method 内 version = max+1）。"""
        with self._db.session_scope() as s:
            last = s.exec(
                select(ValuationAssumption)
                .where(ValuationAssumption.symbol == symbol,
                       ValuationAssumption.method == method)
                .order_by(ValuationAssumption.version.desc())
            ).first()
            row = ValuationAssumption(
                symbol=symbol, method=method,
                version=(last.version + 1) if last else 1,
                assumptions=assumptions, output=output, note=note,
            )
            s.add(row)
            s.flush()
            return self._dict(row)

    def list(self, symbol: str,
             method: Optional[str] = None) -> list:
        with self._db.session_scope() as s:
            q = (
                select(ValuationAssumption)
                .where(ValuationAssumption.symbol == symbol)
                .order_by(ValuationAssumption.method,
                          ValuationAssumption.version.desc())
            )
            if method:
                q = q.where(ValuationAssumption.method == method)
            return [self._dict(r) for r in s.exec(q).all()]

    def get(self, row_id: int) -> Optional[dict]:
        with self._db.session_scope() as s:
            r = s.get(ValuationAssumption, row_id)
            return self._dict(r) if r else None

    def delete(self, row_id: int) -> bool:
        with self._db.session_scope() as s:
            r = s.get(ValuationAssumption, row_id)
            if not r:
                return False
            s.delete(r)
            return True

    @staticmethod
    def _dict(r: ValuationAssumption) -> dict:
        return {
            "id": r.id, "symbol": r.symbol, "method": r.method,
            "version": r.version, "assumptions": r.assumptions,
            "output": r.output, "note": r.note,
            "created_at": r.created_at.isoformat(),
        }


_db_connection: DBConnection | None = None


def create_valuation_assumption_repository(
    db_connection: DBConnection | None = None,
) -> ValuationAssumptionRepository:
    global _db_connection
    if db_connection is None:
        if _db_connection is None:
            _db_connection = create_db_connection(get_dsn())
        db_connection = _db_connection
    return ValuationAssumptionRepository(db_connection)
