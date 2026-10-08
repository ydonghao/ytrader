"""课程组合(自动建组合)SQLModel 表定义。

2 张表:
- CoursePortfolio:    组合计划(风险偏好/资金/现金预留/状态)
- CoursePortfolioLeg: 计划腿(类别/目标权重/估值带快照JSONB/建仓档位JSONB)

通过 SQLModel.metadata.create_all 自动建表;main.py 启动链路经
course_portfolio_router → repository → 本模块完成注册(参考 models.py 说明)。
"""
import datetime as dt
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field, UniqueConstraint


class CoursePortfolio(SQLModel, table=True):
    """课程组合计划(课程23/24: 风险偏好配比 + 分批建仓)。"""

    __tablename__ = "course_portfolio"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    risk_profile: str                     # defensive|balanced|aggressive|radical
    total_capital: float
    cash_reserve_pct: float = 0.10
    target_stock_count: int = 8
    status: str = "planned"               # planned|building|complete
    notes: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class CoursePortfolioLeg(SQLModel, table=True):
    """课程组合计划腿: 一只标的的目标配比 + 估值带 + 分批建仓档位。"""

    __tablename__ = "course_portfolio_leg"

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="course_portfolio.id", index=True)
    symbol: str = Field(index=True)
    name: str = ""
    category: str                         # dividend|bluechip|growth
    target_weight: float
    target_amount: float
    pe_band: Any = Field(default=None, sa_column=Column(JSON))
    # {mean,std,z_score,state,sample_count,current_pe}
    entry_plan: Any = Field(default=None, sa_column=Column(JSON))
    # [{rung_index,drop_pct,price_level,amount,executed,executed_at,fill_price,fill_shares}]
    shares: int = 0
    invested_amount: float = 0.0
    avg_cost: float = 0.0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "symbol", name="uq_course_leg_port_symbol"
        ),
    )
