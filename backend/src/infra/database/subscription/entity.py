"""
Subscription SQLModel table definition.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Text, Index
from sqlmodel import SQLModel, Field


class Subscription(SQLModel, table=True):
    """RSS subscription to a Bilibili UP host or WeChat public account."""
    __tablename__ = "subscription"
    __table_args__ = (
        Index("idx_subscription_type_active", "source_type", "is_active"),
        Index(
            "idx_subscription_unique",
            "source_type", "source_id",
            unique=True,
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    source_type: str = Field(max_length=30)   # "bilibili_video" | "bilibili_article" | "wechat" | "youtube"
    source_id: str = Field(max_length=200)     # Bilibili UID / WeChat biz ID
    name: str = Field(max_length=200)          # Display name (UP host name / account name)
    category: str = Field(max_length=30)       # "finance" | "hotlist" | "future_tech"
    feed_url: Optional[str] = Field(default=None, sa_column=Column(Text))
    is_active: bool = Field(default=True)
    last_fetched_at: Optional[datetime] = Field(default=None)
    last_error: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.now)
