# backend/src/domain/market/schemas.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


class MarketType(Enum):
    STOCK = "stock"
    ETF = "etf"
    INDEX = "index"
    FUTURES = "futures"
    OPTIONS = "options"
    CRYPTO = "crypto"


@dataclass
class OHLCV:
    symbol: str
    name: Optional[str] = None
    time: Optional[datetime] = None
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    interval: str = "1d"
    market: Optional[MarketType] = None


@dataclass
class StockDaily(OHLCV):
    turnrate: float = 0.0
    pre_close: float = 0.0


@dataclass
class ETFDaily(OHLCV):
    nav: float = 0.0
    iopv: float = 0.0
    premium: float = 0.0


@dataclass
class IndexDaily(OHLCV):
    amplitude: float = 0.0
    change_pct: float = 0.0
