"""BI 自定义看板 SQLModel 表定义。

analysis_board: 一个看板 = 一份完整布局 JSON(卡片/时间范围/透明度/z 序),
layout 整存整取,不做服务端结构校验(前端 normalizeLayout 兜底)。

通过 SQLModel.metadata.create_all 自动建表。
注意: 本模块必须在 main.py 启动时被 import, 否则主服务进程的
create_all 看不到这张表(参考 watchlist.models 的注册方式)。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel, UniqueConstraint


class AnalysisBoard(SQLModel, table=True):
    """自定义看板。单用户/全局(无 user_id, 同 watchlist)。name 唯一。"""

    __tablename__ = "analysis_board"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    layout: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    sort_index: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    __table_args__ = (
        UniqueConstraint("name", name="uq_analysis_board_name"),
    )
