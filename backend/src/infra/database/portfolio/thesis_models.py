"""持仓论点体系 SQLModel 表（spec 2026-09-27 §3）。

4 张表：investment_thesis / thesis_condition / thesis_reeval /
thesis_event。main.py lifespan import 建表（无 Alembic 惯例）。
"""
import datetime as dt
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


class InvestmentThesis(SQLModel, table=True):
    """论点 = 持仓登记（持有 = 论点未破）。"""

    __tablename__ = "investment_thesis"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)              # sh600519
    status: str = Field(default="active")        # active|closed
    buy_date: Optional[dt.date] = None
    buy_price: Optional[float] = None
    shares: Optional[int] = None
    thesis_text: str = ""
    snapshot: Any = Field(default=None, sa_column=Column(JSON))
    target_band: Any = Field(default=None, sa_column=Column(JSON))
    entry_ladder: Any = Field(default=None, sa_column=Column(JSON))
    # [{rung_index, drop_pct, price_level, weight_of_position,
    #   amount, shares}]
    decision: Optional[str] = None               # hold|reduce|sell
    decision_note: Optional[str] = None
    decision_at: Optional[datetime] = None
    last_reviewed_at: Optional[datetime] = None
    close_reason: Optional[str] = None           # thesis_broken|valuation_reached|better_alt|manual
    close_price: Optional[float] = None
    closed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ThesisCondition(SQLModel, table=True):
    """假设条件（论点破即卖）。operator ∈ >= > <= <。"""

    __tablename__ = "thesis_condition"

    id: Optional[int] = Field(default=None, primary_key=True)
    thesis_id: int = Field(
        foreign_key="investment_thesis.id", index=True
    )
    metric_key: str
    operator: str
    threshold: float
    label: str = ""
    status: str = "holding"                      # holding|breached|unknown
    breached_at: Optional[datetime] = None


class ThesisReeval(SQLModel, table=True):
    """财报联动重估历史（thesis+report_date+trigger 唯一，幂等）。"""

    __tablename__ = "thesis_reeval"
    __table_args__ = (
        UniqueConstraint(
            "thesis_id", "report_date", "trigger",
            name="uq_thesis_reeval",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    thesis_id: int = Field(
        foreign_key="investment_thesis.id", index=True
    )
    report_date: Optional[dt.date] = None
    trigger: str     # formal|express|preannounce|price_band|manual
    quality_now: Any = Field(default=None, sa_column=Column(JSON))
    quality_delta: Any = Field(default=None, sa_column=Column(JSON))
    valuation_now: Any = Field(default=None, sa_column=Column(JSON))
    conditions_result: Any = Field(default=None, sa_column=Column(JSON))
    verdict: str = "pass"                        # pass|review|sell_signal
    created_at: datetime = Field(default_factory=datetime.now)


class ThesisEvent(SQLModel, table=True):
    """轻事件表（预警中心"持仓论点"分区数据源）。"""

    __tablename__ = "thesis_event"

    id: Optional[int] = Field(default=None, primary_key=True)
    thesis_id: int = Field(
        foreign_key="investment_thesis.id", index=True
    )
    kind: str        # reeval_done|condition_breached|price_band_reached
    detail: Any = Field(default=None, sa_column=Column(JSON))
    read: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.now)


class ThesisJournal(SQLModel, table=True):
    """决策日志：登记/决策变更/关闭/手记，自动挂钩落库。"""

    __tablename__ = "thesis_journal"

    id: Optional[int] = Field(default=None, primary_key=True)
    thesis_id: int = Field(
        foreign_key="investment_thesis.id", index=True
    )
    kind: str           # created|decision|close|note
    decision: Optional[str] = None
    note: Optional[str] = None
    price: Optional[float] = None     # 决策时现价
    confidence: Optional[int] = None  # 信心度 1~5（校准统计原料）
    catalysts: Optional[str] = None   # 预期催化剂（自由文本）
    created_at: datetime = Field(default_factory=datetime.now)


class PassDecision(SQLModel, table=True):
    """放弃决策（研究过但决定不买）——决策经验的另一半。

    与 thesis_journal 分表：放弃发生在论点存在之前，无 thesis_id；
    快照同登记时口径（价格/质量/估值/温度）。
    """

    __tablename__ = "pass_decision"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    decision_date: Optional[dt.date] = None  # 放弃日（可补记历史）
    price: Optional[float] = None            # 放弃时现价
    reason: str = ""                         # 为什么不买
    revisit_when: Optional[str] = None       # 什么情况下重新看
    confidence: Optional[int] = None         # 对"不买"的信心 1~5
    snapshot: Any = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.now)


class ThesisReviewLog(SQLModel, table=True):
    """复盘记录：每次"标记已复盘"一行。"""

    __tablename__ = "thesis_review_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class MineScreeningResult(SQLModel, table=True):
    """排雷扫描结果（第5期）：三源聚合落库，幂等 upsert。"""

    __tablename__ = "mine_screening_result"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "report_date", name="uq_mine_symbol_report",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    report_date: Optional[dt.date] = None
    z: Optional[float] = None
    z_verdict: Optional[str] = None      # safe|grey|distress
    m: Optional[float] = None
    m_verdict: Optional[str] = None      # manipulator|watch|clean
    m_partial: Optional[bool] = None
    fraud_severity: Optional[str] = None  # clean|watch|high_risk
    fraud_flags: Any = Field(default=None, sa_column=Column(JSON))
    risk_level: str = "clean"            # high|medium|clean
    source: str = "positions"            # positions|market
    scanned_at: datetime = Field(default_factory=datetime.now)


class CapitalEvent(SQLModel, table=True):
    """资本事件（第6期V2）：回购+增减持合一，幂等 upsert。"""

    __tablename__ = "capital_event"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "event_type", "announce_date", "holder_name",
            "start_date", name="uq_capital_event",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    event_type: str = Field(index=True)
    # buyback|hold_increase|hold_decrease
    announce_date: Optional[dt.date] = Field(default=None, index=True)
    holder_name: str = ""
    start_date: Optional[dt.date] = None
    shares_wan: Optional[float] = None
    amount: Optional[float] = None              # 元（回购）
    ratio_pct: Optional[float] = None           # 占总股本%
    progress: Optional[str] = None              # 回购实施进度
    raw: Any = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.now)


class MarketThermometerDaily(SQLModel, table=True):
    """全市场温度日快照（回填行 buffett 为空）。"""

    __tablename__ = "market_thermometer_daily"
    __table_args__ = (
        UniqueConstraint("symbol", "trade_date",
                         name="uq_thermometer_symbol_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    trade_date: dt.date = Field(index=True)
    ep_pct: Optional[float] = None
    erp_pct: Optional[float] = None
    level: Optional[str] = None
    level_label: Optional[str] = None
    position_low: Optional[int] = None
    position_high: Optional[int] = None
    erp_percentile: Optional[float] = None
    buffett_pct: Optional[float] = None
    buffett_level: Optional[str] = None
    history_approx: bool = False
    created_at: datetime = Field(default_factory=datetime.now)


class ThesisLadderFill(SQLModel, table=True):
    """三档建仓成交记录（二期F5）。"""

    __tablename__ = "thesis_ladder_fill"

    id: Optional[int] = Field(default=None, primary_key=True)
    thesis_id: int = Field(
        foreign_key="investment_thesis.id", index=True
    )
    rung_index: int
    price: float
    shares: int
    filled_at: datetime = Field(default_factory=datetime.now)


class ResearchNote(SQLModel, table=True):
    """研究笔记（二期F6）：年报/调研/思考，按标的沉淀能力圈。"""

    __tablename__ = "research_note"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    title: str
    content: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
