"""macro_view 表：宏观经济判断快照（本板块灵魂）。

双轨分层设计（详见设计文档）：
  第一层·宏观经济状态判断（核心，用宏观数据验证，零传导噪音）
    - 增长 / 通胀 / 流动性 / 杠杆 / 周期象限 / 衰退风险
    - 每维度一个可证伪命题（方向 + 理由）
    - 验证标尺：下季度宏观数据（PMI/CPI/M2/社融… 实际值）
  第二层·资产方向含义（参考，用指数/汇率/商品走势验证，含传导噪音）
    - 股（沪深300/标普/恒生）/ 汇（美元/日元）/ 商品（黄金/原油）
    - 验证标尺：预测期内实际涨跌方向

两轨独立打分、并列展示。status 由 pending → scored（两层均完成验证）。

无 Alembic，靠 SQLModel.metadata.create_all 自动建表（与 fx_rate/macro_indicator 一致）。
"""
import threading
import datetime as dt
from datetime import datetime, date
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel, Session, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


# 用 sqlalchemy.JSON 显式声明 JSONB 字段（Postgres），SQLModel 默认会建 JSON 列。
# 跨 SQLite（测试）也兼容（SQLite 无 JSONB，回落到 TEXT 存 JSON）。


class MacroView(SQLModel, table=True):
    """宏观经济判断快照。每次生成（每周 / 手动）一条。"""

    __tablename__ = "macro_view"

    id: Optional[int] = Field(default=None, primary_key=True)
    author: str = Field(default="ai", index=True)      # 'ai' / 'user'（留痕主体）
    snapshot_date: date = Field(index=True)            # 判断时刻 T
    horizon_days: int = Field(default=63)              # 验证窗口（≈1 季度交易日）

    # ── 第一层·宏观经济状态判断（核心）──────────────────────────
    # macro_judgments: [{dimension, stance(up/down/flat), confidence, rationale}]
    # dimension ∈ growth / inflation / liquidity / leverage / regime / recession_risk
    # regime 取值: recovery / expansion / overheating / stagflation / recession
    macro_judgments: Any = Field(sa_column=Column(JSON, nullable=False, default=list))
    regime_quadrant: str = Field(default="")            # 美林时钟象限（冗余，便于排序/展示）
    overall_stance: str = Field(default="neutral")      # bullish / bearish / neutral（总览）
    confidence: float = Field(default=5.0)              # 0-10
    summary: str = Field(default="")                    # 立场理由叙事（AI）/ 判断理由（人）
    objective_reading: str = Field(default="")          # AI 客观解读（不下结论，逐指标解释）
    # signals: 生成快照时的关键指标读数快照 {code: {value, date, trend}}
    signals: Any = Field(default=None, sa_column=Column(JSON))

    # ── 第二层·资产方向含义（参考）──────────────────────────────
    # asset_predictions: [{symbol, name, predicted(up/down/flat), rationale, asset_class}]
    asset_predictions: Any = Field(default=None, sa_column=Column(JSON))

    # ── 验证（后填）─────────────────────────────────────────────
    # macro_validation: [{dimension, predicted, actual_value, actual_dir, hit, validated_at}]
    macro_validation: Any = Field(default=None, sa_column=Column(JSON))
    # asset_validation: [{symbol, predicted, actual_return, actual_dir, hit, validated_at}]
    asset_validation: Any = Field(default=None, sa_column=Column(JSON))
    macro_accuracy: Optional[float] = Field(default=None)   # 第一层命中率 0-1
    asset_accuracy: Optional[float] = Field(default=None)   # 第二层命中率 0-1
    status: str = Field(default="pending")              # pending / scored / partial
    validated_at: Optional[datetime] = Field(default=None)

    # ── 关联 ────────────────────────────────────────────────────
    llm_run_id: Optional[str] = Field(default=None, index=True)  # FK → tracing.agent_run
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class MacroViewRepository:
    """宏观经济判断快照数据访问。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def create(self, view: dict) -> int:
        """创建一条快照，返回 id。"""
        with self._db.session_scope() as s:
            row = MacroView(**view)
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.id

    def get(self, view_id: int) -> Optional[dict]:
        with self._db.session_scope() as s:
            row = s.get(MacroView, view_id)
            return _row_to_dict(row) if row else None

    def list_views(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """历史快照列表（按 snapshot_date 倒序）。"""
        with self._db.session_scope() as s:
            stmt = select(MacroView).order_by(MacroView.snapshot_date.desc()).limit(limit)
            if status:
                stmt = stmt.where(MacroView.status == status)
            rows = s.exec(stmt).all()
            return [_row_to_dict(r) for r in rows]

    def get_latest(self, status: Optional[str] = None) -> Optional[dict]:
        """最新一条快照。"""
        rows = self.list_views(status=status, limit=1)
        return rows[0] if rows else None

    def list_pending_for_validation(self, as_of: date) -> list[dict]:
        """列出 status=pending/partial 且窗口到期的快照（供验证 job）。

        到期条件：as_of - snapshot_date >= horizon_days，等价于
        snapshot_date <= as_of - horizon_days。直接在 SQL 过滤，避免把全部
        pending 行拉到 Python 再筛。
        """
        with self._db.session_scope() as s:
            # 每行的截止日期 = as_of - horizon_days（horizon_days 每行不同）。
            # 用 SQL 表达：snapshot_date + horizon_days <= as_of。
            stmt = (
                select(MacroView)
                .where(MacroView.status.in_(["pending", "partial"]))
                .where(
                    MacroView.snapshot_date + MacroView.horizon_days
                    <= as_of
                )
                .order_by(MacroView.snapshot_date.asc())
            )
            rows = list(s.exec(stmt).all())
            return [_row_to_dict(r) for r in rows]

    def update_validation(
        self,
        view_id: int,
        macro_validation: list,
        asset_validation: list,
        macro_accuracy: Optional[float],
        asset_accuracy: Optional[float],
        status: str,
    ) -> None:
        """回写验证结果。"""
        with self._db.session_scope() as s:
            row = s.get(MacroView, view_id)
            if not row:
                return
            row.macro_validation = macro_validation
            row.asset_validation = asset_validation
            row.macro_accuracy = macro_accuracy
            row.asset_accuracy = asset_accuracy
            row.status = status
            row.validated_at = datetime.now()
            row.updated_at = datetime.now()


# ═══════════════════════════════════════════════════════════
# 序列化
# ═══════════════════════════════════════════════════════════
def _row_to_dict(r: MacroView) -> dict:
    if r is None:
        return None
    return {
        "id": r.id,
        "author": r.author,
        "snapshot_date": r.snapshot_date.isoformat() if r.snapshot_date else None,
        "horizon_days": r.horizon_days,
        "macro_judgments": r.macro_judgments or [],
        "regime_quadrant": r.regime_quadrant,
        "overall_stance": r.overall_stance,
        "confidence": r.confidence,
        "summary": r.summary,
        "objective_reading": r.objective_reading,
        "signals": r.signals or {},
        "asset_predictions": r.asset_predictions or [],
        "macro_validation": r.macro_validation or [],
        "asset_validation": r.asset_validation or [],
        "macro_accuracy": r.macro_accuracy,
        "asset_accuracy": r.asset_accuracy,
        "status": r.status,
        "validated_at": r.validated_at.isoformat() if r.validated_at else None,
        "llm_run_id": r.llm_run_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


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


def create_macro_view_repository(
    db_connection: DBConnection | None = None,
) -> MacroViewRepository:
    """创建宏观判断快照仓储实例。"""
    return MacroViewRepository(db_connection or _get_db_connection())


def ensure_macro_view_columns() -> None:
    """为已存在的 macro_view 表补 author / objective_reading 列（无 Alembic 兜底）。

    SQLModel.metadata.create_all 不会给已存在的表加新列，故用 ALTER TABLE IF NOT EXISTS。
    幂等：列已存在时跳过。在 app 启动时调用。
    """
    from sqlalchemy import text
    db = _get_db_connection()
    with db.session_scope() as s:
        s.exec(text(
            "ALTER TABLE macro_view ADD COLUMN IF NOT EXISTS author VARCHAR DEFAULT 'ai'"
        ))
        s.exec(text(
            "ALTER TABLE macro_view ADD COLUMN IF NOT EXISTS objective_reading TEXT DEFAULT ''"
        ))
        # 给 author 建索引（若不存在）
        s.exec(text(
            "CREATE INDEX IF NOT EXISTS ix_macro_view_author ON macro_view (author)"
        ))
