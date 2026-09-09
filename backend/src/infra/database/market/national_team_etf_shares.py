"""national_team_etf_shares 表:国家队监控 ETF 每日份额快照(份)。

用途:ETF 份额级「异常申赎信号」需要历史份额序列(今日 vs 20 日均变动)。
腾讯实时接口只给「当下」份额,历史只能靠每日归档累积,故落库。

幂等:按 (trade_date, etf_code) upsert。每日定时任务(nt_etf_shares_sync)写入。
冷启动:表空时前端降级显示「数据积累中」,~20 个交易日后信号生效。
"""
import datetime as dt
import threading
from datetime import datetime
from typing import Optional

from sqlmodel import Session, SQLModel, Field, select
from sqlalchemy import func, BigInteger, Column

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class NationalTeamEtfShares(SQLModel, table=True):
    """某交易日某 ETF 的份额/规模快照。"""

    __tablename__ = "national_team_etf_shares"

    id: Optional[int] = Field(default=None, primary_key=True)
    trade_date: dt.date              # 交易日
    etf_code: str                    # 6 位 ETF 代码
    etf_name: str = Field(default="")
    # 基金份额可达数百亿份(如 510300 ≈ 236 亿份),超 int32,必须 BIGINT
    shares: int = Field(default=0, sa_column=Column(BigInteger))
    price: float = Field(default=0.0)
    total_value_yi: float = Field(default=0.0)  # 规模(亿)
    created_at: datetime = Field(default_factory=datetime.now)


class NationalTeamEtfSharesRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    def upsert(self, record: dict) -> None:
        with self._db.session_scope() as s:
            existing = s.exec(
                select(NationalTeamEtfShares).where(
                    NationalTeamEtfShares.trade_date == record["trade_date"],
                    NationalTeamEtfShares.etf_code == record["etf_code"],
                )
            ).first()
            if existing:
                for k, v in record.items():
                    setattr(existing, k, v)
            else:
                s.add(NationalTeamEtfShares(**record))

    def get_history(self, etf_code: str, days: int = 90) -> list[dict]:
        """某 ETF 最近 `days` 个交易日的份额序列(升序)。"""
        with self._db.session_scope() as s:
            rows = s.exec(
                select(NationalTeamEtfShares)
                .where(NationalTeamEtfShares.etf_code == etf_code)
                .order_by(NationalTeamEtfShares.trade_date.desc())
                .limit(days)
            ).all()
            return [
                {
                    "trade_date": r.trade_date.isoformat() if r.trade_date else None,
                    "shares": int(r.shares or 0),
                    "price": float(r.price or 0),
                    "total_value_yi": float(r.total_value_yi or 0),
                }
                for r in reversed(rows)
            ]

    def get_all_latest_dates(self, days: int = 90) -> list[str]:
        """有快照的交易日(升序,去重),供热力图横轴。"""
        with self._db.session_scope() as s:
            rows = s.exec(
                select(NationalTeamEtfShares.trade_date)
                .distinct()
                .order_by(NationalTeamEtfShares.trade_date.desc())
                .limit(days)
            ).all()
            return sorted(r.isoformat() for r in rows if r)

    def coverage_info(self) -> dict:
        with self._db.session_scope() as s:
            n_dates = s.exec(select(func.count(NationalTeamEtfShares.trade_date.distinct()))).one()
            n_codes = s.exec(select(func.count(NationalTeamEtfShares.etf_code.distinct()))).one()
            latest = s.exec(select(func.max(NationalTeamEtfShares.trade_date))).one()
        return {
            "trade_dates": int(n_dates or 0),
            "etf_count": int(n_codes or 0),
            "latest_date": latest.isoformat() if latest else None,
        }


# ======== 工厂 ========
_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_etf_shares_repository(
    db_connection: DBConnection | None = None,
) -> NationalTeamEtfSharesRepository:
    return NationalTeamEtfSharesRepository(db_connection or _get_db_connection())


def ensure_etf_shares_table() -> None:
    """幂等建表 + 把 shares 升级为 BIGINT(份额可达数百亿份,超 int32)。
    与 national_team_holding.ensure_national_team_bigint_columns 同模式。"""
    from sqlalchemy import text
    try:
        db = _get_db_connection()
        eng = db._engine  # noqa: SLF001
        SQLModel.metadata.create_all(eng)
        with db.session_scope() as s:
            s.exec(text(
                "ALTER TABLE national_team_etf_shares "
                "ALTER COLUMN shares TYPE BIGINT"
            ))
    except Exception:
        pass


try:
    ensure_etf_shares_table()
except Exception:
    pass
