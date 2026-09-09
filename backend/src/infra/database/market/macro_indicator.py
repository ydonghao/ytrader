"""macro_indicator 表：宏观经济指标时序（CPI / PMI / M2 / 社融 / LPR / GDP …）。

与 fx_rate 同为"标量比率类"独立建表：按 (indicator_code, report_date) 主键幂等 upsert。
月度/季度数据更新稀疏，靠 SQLModel.metadata.create_all 自动建表（项目无 Alembic）。

另含 macro_indicator_meta 元数据表：code → 名称/单位/阈值线（如 PMI 荣枯线 50），
供前端展示与状态徽章判断。
"""
import threading
import datetime as dt
from datetime import datetime
from typing import Any, Optional

# 字段名 `date` 会遮蔽 datetime.date，用模块别名 dt.date 引用类型注解。
from sqlalchemy import JSON, Column
from sqlmodel import Session, SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class MacroIndicator(SQLModel, table=True):
    """宏观经济指标时序记录（如 cn_cpi_yoy=0.3 @ 2026-05）。"""

    __tablename__ = "macro_indicator"

    indicator_code: str = Field(primary_key=True)  # cn_cpi_yoy / cn_pmi / cn_m2 ...
    report_date: dt.date = Field(primary_key=True)
    value: float
    freq: str = Field(default="month")             # month / quarter / day / year
    unit: str = Field(default="")                  # "%" / "万亿" / ""
    source: str = Field(default="akshare")         # 数据源名称（akshare / 国家统计局）
    source_url: str = Field(default="")            # 数据源权威页面（供用户溯源）
    provider: str = Field(default="akshare")       # 实际抓取 provider（akshare / fred），便于溯源
    created_at: datetime = Field(default_factory=datetime.now)


class MacroIndicatorMeta(SQLModel, table=True):
    """指标元数据：展示名称、单位、阈值线（如 PMI 荣枯线 50）。

    预测/展示用：threshold_high / threshold_low 决定状态徽章（偏热/偏冷/中性），
    仅 threshold_* 非空时启用，例如 PMI 荣枯线 50、CPI 目标 3%。
    """

    __tablename__ = "macro_indicator_meta"

    code: str = Field(primary_key=True)            # cn_pmi
    name: str                                       # 制造业 PMI
    unit: str = Field(default="")                  # %
    freq: str = Field(default="month")
    category: str = Field(default="cn")            # cn / us / global
    group: str = Field(default="")                 # growth / inflation / employment / monetary（经济维度分组）
    provider: str = Field(default="akshare")       # akshare / fred（sync 数据源分发）
    threshold_high: Optional[float] = Field(default=None)  # PMI 50（≥为扩张）
    threshold_low: Optional[float] = Field(default=None)
    direction: str = Field(default="high_good")    # high_good(高于阈值利好) / low_good / neutral
    sort_order: int = Field(default=0)
    description: str = Field(default="")           # 简短说明（徽章/卡片副标题）
    explanation: str = Field(default="")           # 详细含义解释（tip 弹层，讲指标是什么/怎么读）
    doc_url: str = Field(default="")               # 外链：权威资料/百科（tip 中"了解更多"）
    range_low: Optional[float] = Field(default=None)   # 图示区间下限（如 CPI 0%）
    range_high: Optional[float] = Field(default=None)  # 图示区间上限（如 CPI 5%）
    # reference_lines: [{value, label, severity}] 多条带语义的分界线
    # severity ∈ normal(正常区) / warning(警戒) / danger(严重) / boom(繁荣/利好极端)
    reference_lines: Any = Field(default=None, sa_column=Column(JSON))


class MacroIndicatorRepository:
    """宏观指标数据访问（守 SQLModel ORM 规范）。"""

    def __init__(self, db: DBConnection):
        self._db = db

    # ── 指标时序 ──────────────────────────────────────────────
    def upsert(
        self,
        indicator_code: str,
        report_date: dt.date,
        value: float,
        freq: str = "month",
        unit: str = "",
        source: str = "akshare",
        source_url: str = "",
        provider: str = "akshare",
    ) -> None:
        """插入或更新（按 code+date 主键）一条指标记录。"""
        with self._db.session_scope() as s:
            existing = s.exec(
                select(MacroIndicator).where(
                    MacroIndicator.indicator_code == indicator_code,
                    MacroIndicator.report_date == report_date,
                )
            ).first()
            if existing:
                existing.value = value
                existing.freq = freq
                existing.unit = unit
                existing.source = source
                existing.source_url = source_url
                existing.provider = provider
            else:
                s.add(
                    MacroIndicator(
                        indicator_code=indicator_code, report_date=report_date,
                        value=value, freq=freq, unit=unit,
                        source=source, source_url=source_url, provider=provider,
                    )
                )

    def bulk_upsert(self, rows: list[dict]) -> int:
        """批量 upsert。rows: [{indicator_code, report_date, value, freq, unit, source, source_url, provider}]。
        返回写入条数。"""
        n = 0
        for r in rows:
            self.upsert(
                indicator_code=r["indicator_code"],
                report_date=r["report_date"],
                value=r["value"],
                freq=r.get("freq", "month"),
                unit=r.get("unit", ""),
                source=r.get("source", "akshare"),
                source_url=r.get("source_url", ""),
                provider=r.get("provider", "akshare"),
            )
            n += 1
        return n

    def get_latest_date(self, indicator_code: str) -> Optional[dt.date]:
        """返回指定指标最新记录的日期；无数据为 None。"""
        with self._db.session_scope() as s:
            row = s.exec(
                select(MacroIndicator)
                .where(MacroIndicator.indicator_code == indicator_code)
                .order_by(MacroIndicator.report_date.desc())
            ).first()
            return row.report_date if row else None

    def get_latest_values(self, codes: Optional[list[str]] = None) -> list[dict]:
        """返回每个指标的最新一条记录（子查询取 max(report_date)）。
        codes 为空时返回全部。"""
        with self._db.session_scope() as s:
            from sqlalchemy import func
            # 子查询：每个 code 的 max(report_date)；codes 过滤须同时作用于
            # 子查询与外查询，否则 JOIN 会带出未过滤的 code。
            sub_stmt = (
                select(
                    MacroIndicator.indicator_code,
                    func.max(MacroIndicator.report_date).label("max_date"),
                )
                .group_by(MacroIndicator.indicator_code)
            )
            if codes:
                sub_stmt = sub_stmt.where(MacroIndicator.indicator_code.in_(codes))
            sub = sub_stmt.subquery()
            rows = s.exec(
                select(MacroIndicator)
                .join(
                    sub,
                    (MacroIndicator.indicator_code == sub.c.indicator_code)
                    & (MacroIndicator.report_date == sub.c.max_date),
                )
            ).all()
            return [
                {
                    "indicator_code": r.indicator_code,
                    "report_date": r.report_date.isoformat() if r.report_date else None,
                    "value": r.value,
                    "freq": r.freq,
                    "unit": r.unit,
                    "source": r.source,
                    "source_url": r.source_url,
                    "provider": r.provider,
                }
                for r in rows
            ]

    def get_series(
        self,
        indicator_code: str,
        start_date: Optional[dt.date] = None,
        end_date: Optional[dt.date] = None,
        limit: int = 500,
    ) -> list[dict]:
        """返回单指标历史时序（升序，画图用）。"""
        with self._db.session_scope() as s:
            stmt = (
                select(MacroIndicator)
                .where(MacroIndicator.indicator_code == indicator_code)
                .order_by(MacroIndicator.report_date.desc())
                .limit(limit)
            )
            if start_date:
                stmt = stmt.where(MacroIndicator.report_date >= start_date)
            if end_date:
                stmt = stmt.where(MacroIndicator.report_date <= end_date)
            rows = list(s.exec(stmt).all())
            rows.reverse()  # 升序返回
            return [
                {
                    "report_date": r.report_date.isoformat() if r.report_date else None,
                    "value": r.value,
                }
                for r in rows
            ]

    # ── 元数据 ────────────────────────────────────────────────
    def upsert_meta(self, meta: dict) -> None:
        """插入或更新一条指标元数据。"""
        with self._db.session_scope() as s:
            existing = s.exec(
                select(MacroIndicatorMeta).where(
                    MacroIndicatorMeta.code == meta["code"]
                )
            ).first()
            if existing:
                for k, v in meta.items():
                    setattr(existing, k, v)
            else:
                s.add(MacroIndicatorMeta(**meta))

    def list_meta(
        self, category: Optional[str] = None, group: Optional[str] = None
    ) -> list[dict]:
        """列出指标元数据（按 sort_order 升序）。
        category 过滤 cn/us/global；group 过滤 growth/inflation/employment/monetary。"""
        with self._db.session_scope() as s:
            stmt = select(MacroIndicatorMeta)
            if category:
                stmt = stmt.where(MacroIndicatorMeta.category == category)
            if group:
                stmt = stmt.where(MacroIndicatorMeta.group == group)
            stmt = stmt.order_by(MacroIndicatorMeta.sort_order)
            rows = s.exec(stmt).all()
            return [
                {
                    "code": r.code,
                    "name": r.name,
                    "unit": r.unit,
                    "freq": r.freq,
                    "category": r.category,
                    "group": r.group,
                    "provider": r.provider,
                    "threshold_high": r.threshold_high,
                    "threshold_low": r.threshold_low,
                    "direction": r.direction,
                    "sort_order": r.sort_order,
                    "description": r.description,
                    "explanation": r.explanation,
                    "doc_url": r.doc_url,
                    "range_low": r.range_low,
                    "range_high": r.range_high,
                    "reference_lines": r.reference_lines or [],
                }
                for r in rows
            ]


# ======== 工厂函数（遵循 intel/blog 单例 + 工厂约定） ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_macro_indicator_repository(
    db_connection: DBConnection | None = None,
) -> MacroIndicatorRepository:
    """创建宏观指标仓储实例。"""
    return MacroIndicatorRepository(db_connection or _get_db_connection())


def ensure_macro_indicator_columns() -> None:
    """为已存在的 macro_indicator / macro_indicator_meta 表补新列（无 Alembic 兜底）。

    SQLModel.metadata.create_all 不会给已存在的表加新列，故用 ALTER TABLE IF NOT EXISTS。
    幂等：列已存在时跳过。在 app 启动时调用。
    新增列：
      - macro_indicator.source_url         （数据源权威页面，供用户溯源）
      - macro_indicator_meta.explanation   （详细含义解释，tip 弹层）
      - macro_indicator_meta.doc_url       （外链：权威资料/百科）
      - macro_indicator_meta.group         （经济维度分组：growth/inflation/employment/monetary）
      - macro_indicator_meta.provider      （sync 数据源分发：akshare/fred）
      - macro_indicator.provider           （该行实际抓取 provider，便于溯源）
    """
    from sqlalchemy import text
    db = _get_db_connection()
    with db.session_scope() as s:
        s.exec(text(
            "ALTER TABLE macro_indicator ADD COLUMN IF NOT EXISTS source_url VARCHAR DEFAULT ''"
        ))
        s.exec(text(
            "ALTER TABLE macro_indicator_meta ADD COLUMN IF NOT EXISTS explanation TEXT DEFAULT ''"
        ))
        s.exec(text(
            "ALTER TABLE macro_indicator_meta ADD COLUMN IF NOT EXISTS doc_url VARCHAR DEFAULT ''"
        ))
        s.exec(text(
            "ALTER TABLE macro_indicator_meta ADD COLUMN IF NOT EXISTS range_low FLOAT"
        ))
        s.exec(text(
            "ALTER TABLE macro_indicator_meta ADD COLUMN IF NOT EXISTS range_high FLOAT"
        ))
        s.exec(text(
            "ALTER TABLE macro_indicator_meta ADD COLUMN IF NOT EXISTS reference_lines JSONB"
        ))
        s.exec(text(
            'ALTER TABLE macro_indicator_meta ADD COLUMN IF NOT EXISTS "group" VARCHAR DEFAULT \'\''
        ))
        s.exec(text(
            "ALTER TABLE macro_indicator_meta ADD COLUMN IF NOT EXISTS provider VARCHAR DEFAULT 'akshare'"
        ))
        s.exec(text(
            "ALTER TABLE macro_indicator ADD COLUMN IF NOT EXISTS provider VARCHAR DEFAULT 'akshare'"
        ))
