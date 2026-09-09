"""永久投资组合 SQLModel 表定义。

5 张表:
- PortfolioInstrument: 标的池(A/HK/US 可选标的)
- PortfolioDefinition: 组合定义(永久/全天候/黄金蝴蝶/自定义)
- PortfolioHolding:    组合持仓(持仓制: shares + cost_price)
- PortfolioNav:        每日组合净值(时间序列)
- PortfolioNavItem:    每日持仓明细快照(各标的实际权重/偏离)

通过 SQLModel.metadata.create_all 自动建表。
注意: 本模块必须在 main.py 启动时被 import, 否则主服务进程
的 create_all 看不到这些表(参考 agent.entity 的注册方式)。
"""
import datetime as dt
from datetime import date, datetime
from typing import Optional

from sqlmodel import SQLModel, Field, UniqueConstraint


class PortfolioInstrument(SQLModel, table=True):
    """标的池: 用户管理的全市场可选标的(A/HK/US)。

    symbol 规范:
      A 股:  sh510300 / sz159934 (带交易所前缀)
      港股:  02800 (纯5位数字)
      美股:  VOO (1~5位字母)
    """

    __tablename__ = "portfolio_instrument"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(unique=True, index=True)
    market: str = Field(index=True)        # "A" | "HK" | "US"
    asset_class: str = Field(index=True)   # equity | bond | gold | cash
    ccy: str                                # "CNY" | "HKD" | "USD"
    name: str
    provider: str = "akshare"
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class PortfolioDefinition(SQLModel, table=True):
    """组合定义: 永久组合/全天候/黄金蝴蝶/自定义。

    strategy_type:
      permanent      永久投资组合(25/25/25/25)
      all_weather    全天候(简化)
      golden_butterfly 黄金蝴蝶
      custom         自定义
    """

    __tablename__ = "portfolio_definition"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    strategy_type: str = Field(index=True)
    base_ccy: str = "CNY"
    rebalance_threshold: float = 0.05   # 触发再平衡的偏离阈值
    initial_capital: float = 100000.0   # 初始资金(净值归一化基准)
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class PortfolioHolding(SQLModel, table=True):
    """组合持仓: 某组合持有的标的 + 目标权重 + 实际股数。

    持仓制核算: 净值 = Σ(shares × price × fx_rate)
    """

    __tablename__ = "portfolio_holding"

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(
        foreign_key="portfolio_definition.id", index=True
    )
    instrument_id: int = Field(
        foreign_key="portfolio_instrument.id", index=True
    )
    target_weight: float    # 单标的目标权重(0~1)
    shares: int             # 持仓股数
    cost_price: float = 0.0  # 成本价(原币种)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "instrument_id", name="uq_holding_port_inst"
        ),
    )


class PortfolioNav(SQLModel, table=True):
    """每日组合净值快照(时间序列)。

    每个组合每个交易日一条记录。
    """

    __tablename__ = "portfolio_nav"

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(
        foreign_key="portfolio_definition.id", index=True
    )
    trade_date: date = Field(index=True)
    nav_cny: float                          # 归一化净值(初始日=1.0)
    prev_nav_cny: Optional[float] = None
    daily_return: Optional[float] = None
    total_value_cny: float                  # 总市值人民币
    max_drift: float                        # 最大资产类偏离(绝对值)
    rebalance_suggested: bool = False
    created_at: datetime = Field(default_factory=datetime.now)

    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "trade_date", name="uq_nav_port_date"
        ),
    )


class PortfolioNavItem(SQLModel, table=True):
    """每日持仓明细快照: 各标的的实际权重/偏离。

    每条 = 某组合某日某标的。nav_id 关联 PortfolioNav。
    """

    __tablename__ = "portfolio_nav_item"

    id: Optional[int] = Field(default=None, primary_key=True)
    nav_id: int = Field(foreign_key="portfolio_nav.id", index=True)
    instrument_id: int
    symbol: str                              # 冗余存储(查询友好)
    asset_class: str
    shares: int
    price: float                             # 当日收盘价(原币种)
    price_cny: float                         # 折算人民币
    fx_rate: float                           # 当日折算汇率
    value_cny: float                         # = shares × price_cny
    target_weight: float
    actual_weight: float                     # = value_cny / total_value_cny
    drift: float                             # 单标的层面偏离
    created_at: datetime = Field(default_factory=datetime.now)
