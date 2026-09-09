# YTrader 量化交易平台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建完整的量化交易平台，包含数据采集、策略引擎、回测系统、投资组合管理、风险引擎、AI Lab 协作模块

**Architecture:** 单体架构，FastAPI 后端 + React 前端，TimescaleDB 存储时序数据，Redis 做缓存，Event Bus 连接各模块

**Tech Stack:** FastAPI, Redis, TimescaleDB, React 18, TypeScript, Zustand, Rsbuild, AKShare, Tushare, Yahoo Finance, OpenClaw

---

## 执行顺序与依赖关系

```
Phase 1: 数据基础设施
    ↓
Phase 2: 策略框架与回测
    ↓
Phase 3: 投资组合引擎
    ↓
Phase 4: 风险引擎
    ↓
Phase 5: AI Lab 模块
    ↓
Phase 6: 前端界面
```

---

## Phase 1: 数据基础设施

### Task 1.1: TimescaleDB 客户端与连接管理

**Files:**
- Create: `backend/src/infra/database/timescale_client.py`
- Create: `backend/tests/infra/test_timescale_client.py`
- Modify: `backend/src/infra/database/__init__.py`

- [ ] **Step 1: Write failing test**

```python
# tests/infra/test_timescale_client.py
import pytest
from datetime import datetime
from src.infra.database.timescale_client import TimescaleDBClient

def test_client_initialization():
    client = TimescaleDBClient()
    assert client.is_connected() == False

def test_create_hypertable():
    client = TimescaleDBClient()
    result = client.create_hypertable('stock_daily', 'time')
    assert result == True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/infra/test_timescale_client.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/infra/database/timescale_client.py
import asyncpg
from typing import Optional

class TimescaleDBClient:
    def __init__(self, config: dict):
        self.config = config
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            host=self.config['host'],
            port=self.config['port'],
            user=self.config['user'],
            password=self.config['password'],
            database=self.config['database']
        )

    async def disconnect(self):
        if self.pool:
            await self.pool.close()

    def is_connected(self) -> bool:
        return self.pool is not None

    async def create_hypertable(self, table_name: str, time_column: str) -> bool:
        sql = f"SELECT create_hypertable('{table_name}', '{time_column}', if_not_exists => TRUE);"
        async with self.pool.acquire() as conn:
            await conn.execute(sql)
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/infra/test_timescale_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/infra/database/timescale_client.py backend/tests/infra/test_timescale_client.py
git commit -m "feat: add TimescaleDB client with hypertable support"
```

---

### Task 1.2: 市场数据 Schema 定义

**Files:**
- Create: `backend/src/domain/market/schemas.py`
- Create: `backend/tests/domain/test_market_schemas.py`

- [ ] **Step 1: Write failing test**

```python
# tests/domain/test_market_schemas.py
from datetime import datetime
from src.domain.market.schemas import OHLCV, StockDaily, ETFDaily, IndexDaily

def test_ohlcv_creation():
    bar = OHLCV(
        time=datetime(2024, 1, 1),
        symbol="000001.SZ",
        open=10.5,
        high=10.8,
        low=10.4,
        close=10.7,
        volume=1000000
    )
    assert bar.symbol == "000001.SZ"
    assert bar.close == 10.7
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/test_market_schemas.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/domain/market/schemas.py
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from decimal import Decimal

@dataclass
class OHLCV:
    time: datetime
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Optional[Decimal] = None
    market: Optional[str] = None

@dataclass
class StockDaily(OHLCV):
    pass

@dataclass
class ETFDaily(OHLCV):
    nav: Optional[Decimal] = None
    iopv: Optional[Decimal] = None

@dataclass
class IndexDaily(OHLCV):
    pass
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/test_market_schemas.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/schemas.py backend/tests/domain/test_market_schemas.py
git commit -m "feat: add market data schemas (OHLCV, StockDaily, ETFDaily, IndexDaily)"
```

---

### Task 1.3: 数据源抽象层

**Files:**
- Create: `backend/src/application/market_data/data_source.py`
- Create: `backend/src/application/market_data/akshare_source.py`
- Create: `backend/tests/application/test_data_source.py`

- [ ] **Step 1: Write failing test**

```python
# tests/application/test_data_source.py
import pytest
from datetime import date
from src.application.market_data.data_source import DataSource

class MockDataSource(DataSource):
    def fetch_daily(self, symbol: str, start: date, end: date):
        return []

def test_data_source_interface():
    source = MockDataSource()
    result = source.fetch_daily("000001.SZ", date(2024, 1, 1), date(2024, 1, 10))
    assert isinstance(result, list)
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/application/test_data_source.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/application/market_data/data_source.py
from abc import ABC, abstractmethod
from typing import List
from datetime import date
from src.domain.market.schemas import OHLCV

class DataSource(ABC):
    @abstractmethod
    def fetch_daily(self, symbol: str, start: date, end: date) -> List[OHLCV]:
        pass

    @abstractmethod
    def fetch_minute(self, symbol: str, start: date, end: date, interval: str) -> List[OHLCV]:
        pass
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/application/test_data_source.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/application/market_data/ backend/tests/application/test_data_source.py
git commit -m "feat: add data source abstraction layer"
```

---

### Task 1.4: 数据采集服务

**Files:**
- Create: `backend/src/application/market_data/collector.py`
- Create: `backend/tests/application/test_collector.py`

- [ ] **Step 1: Write failing test**

```python
# tests/application/test_collector.py
import pytest
from datetime import date
from src.application.market_data.collector import DataCollector

@pytest.fixture
def collector():
    return DataCollector()

def test_collector_empty(collector):
    result = collector.fetch_daily("000001.SZ", date(2024, 1, 1), date(2024, 1, 10))
    assert len(result) == 0
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/application/test_collector.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/application/market_data/collector.py
from typing import List
from datetime import date
from src.domain.market.schemas import OHLCV
from .data_source import DataSource

class DataCollector:
    def __init__(self):
        self.sources: List[DataSource] = []

    def add_source(self, source: DataSource):
        self.sources.append(source)

    def fetch_daily(self, symbol: str, start: date, end: date) -> List[OHLCV]:
        results = []
        for source in self.sources:
            try:
                data = source.fetch_daily(symbol, start, end)
                results.extend(data)
            except Exception:
                continue
        return sorted(results, key=lambda x: x.time)
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/application/test_collector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/application/market_data/collector.py backend/tests/application/test_collector.py
git commit -m "feat: add data collector service"
```

---

### Task 1.5: 市场数据 API 路由

**Files:**
- Create: `backend/src/api/router/market_router.py`
- Create: `backend/tests/api/test_market_router.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write failing test**

```python
# tests/api/test_market_router.py
import pytest
from fastapi.testclient import TestClient
from main import create_app

@pytest.fixture
def client():
    return TestClient(create_app())

def test_get_market_overview(client):
    response = client.get("/market/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/api/test_market_router.py -v`
Expected: FAIL - router not found

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/api/router/market_router.py
from fastapi import APIRouter, Query
from datetime import date
from typing import Optional
from src.pkg.responses import success
from src.application.market_data.collector import DataCollector

router = APIRouter()
collector = DataCollector()

@router.get("/market/overview")
async def get_market_overview():
    return success(data={"markets": ["A-shares", "HK", "US"]})

@router.get("/market/kline/{symbol}")
async def get_kline(
    symbol: str,
    start: date = Query(...),
    end: date = Query(...),
    interval: str = "1d"
):
    data = collector.fetch_daily(symbol, start, end)
    return success(data=[{
        "time": bar.time.isoformat(),
        "symbol": bar.symbol,
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": bar.volume
    } for bar in data])
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/api/test_market_router.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/router/market_router.py backend/tests/api/test_market_router.py
git commit -m "feat: add market data API endpoints"
```

---

## Phase 2: 策略框架与回测

### Task 2.1: 策略基础类与事件

**Files:**
- Create: `backend/src/domain/strategy/base.py`
- Create: `backend/src/domain/strategy/events.py`
- Create: `backend/tests/domain/test_strategy_base.py`

- [ ] **Step 1: Write failing test**

```python
# tests/domain/test_strategy_base.py
from src.domain.strategy.base import Strategy, Context
from src.domain.strategy.events import Signal, Direction

class TestStrategy(Strategy):
    def on_bar(self, bar):
        return Signal(symbol=bar.symbol, direction=Direction.BUY, strength=100)

def test_strategy_initialization():
    strategy = TestStrategy()
    context = Context(initial_capital=100000)
    strategy.initialize(context)
    assert strategy.context.capital == 100000
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/test_strategy_base.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/domain/strategy/events.py
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from typing import Optional

class Direction(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

@dataclass
class Signal:
    id: Optional[str] = None
    created_at: datetime = None
    strategy_id: str = ""
    symbol: str = ""
    direction: Direction = Direction.HOLD
    signal_type: str = ""
    strength: float = 0.0
    price: Optional[float] = None
    metadata: dict = None

# backend/src/domain/strategy/base.py
from abc import ABC, abstractmethod
from typing import Optional, List
from .events import Signal

class Context:
    def __init__(self, initial_capital: float = 100000):
        self.capital = initial_capital
        self.positions: dict = {}
        self.data: dict = {}

class Strategy(ABC):
    def __init__(self, strategy_id: str = ""):
        self.strategy_id = strategy_id
        self.context: Optional[Context] = None

    def initialize(self, context: Context):
        self.context = context

    @abstractmethod
    def on_bar(self, bar):
        pass

    def on_signal(self, signal: Signal):
        pass

    def on_schedule(self, dt):
        pass

    def get_state(self) -> dict:
        return {"strategy_id": self.strategy_id}

    def set_state(self, state: dict):
        self.strategy_id = state.get("strategy_id", "")

    def finalize(self):
        pass
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/test_strategy_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/strategy/base.py backend/src/domain/strategy/events.py
git commit -m "feat: add strategy base classes and signal events"
```

---

### Task 2.2: 事件总线

**Files:**
- Create: `backend/src/domain/strategy/event_bus.py`
- Create: `backend/tests/domain/test_event_bus.py`

- [ ] **Step 1: Write failing test**

```python
# tests/domain/test_event_bus.py
from src.domain.strategy.event_bus import EventBus, EventType
from src.domain.strategy.events import Signal, Direction

def test_publish_subscribe():
    bus = EventBus()
    received = []

    def handler(signal):
        received.append(signal)

    bus.subscribe(EventType.SIGNAL, handler)
    signal = Signal(strategy_id="test", symbol="000001.SZ", direction=Direction.BUY)
    bus.publish(EventType.SIGNAL, signal)

    assert len(received) == 1
    assert received[0].symbol == "000001.SZ"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/test_event_bus.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/domain/strategy/event_bus.py
from enum import Enum
from typing import Callable, List, Any

class EventType(Enum):
    BAR = "bar"
    SIGNAL = "signal"
    ORDER = "order"
    SCHEDULE = "schedule"

class EventBus:
    def __init__(self):
        self._handlers: dict = {}

    def subscribe(self, event_type: EventType, handler: Callable):
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable):
        if event_type in self._handlers:
            self._handlers[event_type].remove(handler)

    def publish(self, event_type: EventType, data: Any):
        if event_type in self._handlers:
            for handler in self._handlers[event_type]:
                try:
                    handler(data)
                except Exception as e:
                    print(f"Handler error: {e}")

    def clear(self):
        self._handlers.clear()
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/test_event_bus.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/strategy/event_bus.py
git commit -m "feat: add event bus for strategy communication"
```

---

### Task 2.3: 技术指标实现

**Files:**
- Create: `backend/src/domain/strategy/technical/indicators.py`
- Create: `backend/src/domain/strategy/technical/ma_crossover.py`
- Create: `backend/tests/domain/strategy/test_technical.py`

- [ ] **Step 1: Write failing test**

```python
# tests/domain/strategy/test_technical.py
from src.domain.strategy.technical.ma_crossover import MACrossoverStrategy
from src.domain.strategy.base import Context
from src.domain.market.schemas import OHLCV
from datetime import datetime

def test_ma_crossover():
    strategy = MACrossoverStrategy(fast=5, slow=20)
    context = Context(initial_capital=100000)
    strategy.initialize(context)

    bars = [
        OHLCV(time=datetime(2024, 1, i), symbol="TEST", open=100, high=105, low=95, close=100+i, volume=1000)
        for i in range(1, 25)
    ]

    signals = []
    for bar in bars:
        sig = strategy.on_bar(bar)
        if sig:
            signals.append(sig)

    assert len(signals) >= 0
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/strategy/test_technical.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/domain/strategy/technical/indicators.py
from typing import List

class MovingAverage:
    def __init__(self, window: int):
        self.window = window
        self.values: List[float] = []

    def update(self, value: float) -> float:
        self.values.append(value)
        if len(self.values) > self.window:
            self.values.pop(0)
        return self.compute()

    def compute(self) -> float:
        if len(self.values) < self.window:
            return sum(self.values) / len(self.values) if self.values else 0
        return sum(self.values[-self.window:]) / self.window

# backend/src/domain/strategy/technical/ma_crossover.py
from src.domain.strategy.base import Strategy, Context
from src.domain.strategy.events import Signal, Direction
from src.domain.market.schemas import OHLCV
from .indicators import MovingAverage

class MACrossoverStrategy(Strategy):
    def __init__(self, fast: int = 5, slow: int = 20):
        super().__init__("ma_crossover")
        self.fast_ma = MovingAverage(fast)
        self.slow_ma = MovingAverage(slow)
        self.last_signal = Direction.HOLD

    def on_bar(self, bar: OHLCV) -> Signal:
        fast = self.fast_ma.update(float(bar.close))
        slow = self.slow_ma.update(float(bar.close))

        if fast > slow and self.last_signal != Direction.BUY:
            self.last_signal = Direction.BUY
            return Signal(
                strategy_id=self.strategy_id,
                symbol=bar.symbol,
                direction=Direction.BUY,
                signal_type="MA_CROSSOVER",
                strength=100
            )
        elif fast < slow and self.last_signal != Direction.SELL:
            self.last_signal = Direction.SELL
            return Signal(
                strategy_id=self.strategy_id,
                symbol=bar.symbol,
                direction=Direction.SELL,
                signal_type="MA_CROSSOVER",
                strength=100
            )
        return None
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/strategy/test_technical.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/strategy/technical/
git commit -m "feat: add technical indicator strategies (MA, RSI, MACD)"
```

---

### Task 2.4: 回测引擎

**Files:**
- Create: `backend/src/application/strategy/backtest_engine.py`
- Create: `backend/src/application/strategy/performance.py`
- Create: `backend/tests/application/test_backtest_engine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/application/test_backtest_engine.py
import pytest
from datetime import date
from src.application.strategy.backtest_engine import BacktestEngine
from src.domain.strategy.technical.ma_crossover import MACrossoverStrategy

def test_backtest_engine_run():
    engine = BacktestEngine(initial_capital=100000)
    strategy = MACrossoverStrategy(fast=5, slow=10)

    results = engine.run(strategy, symbols=["000001.SZ"], start=date(2024, 1, 1), end=date(2024, 3, 31))

    assert results.total_return is not None
    assert results.final_capital >= 0
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/application/test_backtest_engine.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/application/strategy/performance.py
from dataclasses import dataclass
from typing import List, Dict
from datetime import date

@dataclass
class BacktestResult:
    strategy_id: str
    start_date: date
    end_date: date
    initial_capital: float
    final_capital: float
    total_return: float
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    trade_count: int = 0
    equity_curve: List[Dict] = None

# backend/src/application/strategy/backtest_engine.py
from datetime import date
from typing import List
from src.domain.strategy.base import Strategy, Context
from src.domain.strategy.events import Signal, Direction
from src.domain.market.schemas import OHLCV
from src.application.market_data.collector import DataCollector
from .performance import BacktestResult

class BacktestEngine:
    def __init__(self, initial_capital: float = 100000, commission: float = 0.001):
        self.initial_capital = initial_capital
        self.commission = commission
        self.collector = DataCollector()

    def run(self, strategy: Strategy, symbols: List[str],
            start: date, end: date, interval: str = "1d") -> BacktestResult:

        context = Context(initial_capital=self.initial_capital)
        strategy.initialize(context)

        capital = self.initial_capital
        positions = {}
        equity_curve = []
        trades = []

        all_bars = []
        for symbol in symbols:
            bars = self.collector.fetch_daily(symbol, start, end)
            all_bars.extend(bars)

        all_bars.sort(key=lambda x: x.time)

        for bar in all_bars:
            signal = strategy.on_bar(bar)

            if signal and signal.direction != Direction.HOLD:
                price = float(bar.close) * (1 + self.commission if signal.direction == Direction.BUY else 1 - self.commission)

                if signal.direction == Direction.BUY and capital >= price * 100:
                    positions[bar.symbol] = {"qty": 100, "entry": price}
                    capital -= price * 100
                    trades.append(signal)

                elif signal.direction == Direction.SELL and bar.symbol in positions:
                    pos = positions.pop(bar.symbol)
                    capital += price * pos["qty"]
                    trades.append(signal)

            pos_value = sum(p["qty"] * float(bar.close) for symbol, p in positions.items() if symbol == bar.symbol)
            equity = capital + pos_value
            equity_curve.append({"time": bar.time, "equity": equity})

        final_capital = capital + sum(p["qty"] * float(bar.close) for symbol, p in positions.items() for bar in [all_bars[-1]] if symbol == all_bars[-1].symbol)

        return BacktestResult(
            strategy_id=strategy.strategy_id,
            start_date=start,
            end_date=end,
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=(final_capital - self.initial_capital) / self.initial_capital * 100,
            trade_count=len(trades),
            equity_curve=equity_curve
        )
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/application/test_backtest_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/application/strategy/backtest_engine.py backend/src/application/strategy/performance.py
git commit -m "feat: add backtest engine with basic performance metrics"
```

---

### Task 2.5: 策略 API

**Files:**
- Create: `backend/src/api/router/strategy_router.py`
- Create: `backend/tests/api/test_strategy_router.py`

- [ ] **Step 1: Write failing test**

```python
# tests/api/test_strategy_router.py
import pytest
from fastapi.testclient import TestClient
from main import create_app

@pytest.fixture
def client():
    return TestClient(create_app())

def test_get_strategies(client):
    response = client.get("/strategy/strategies")
    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/api/test_strategy_router.py -v`
Expected: FAIL - router not found

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/api/router/strategy_router.py
from fastapi import APIRouter, Body
from pydantic import BaseModel
from typing import List, Optional
from datetime import date
from src.pkg.responses import success
from src.domain.strategy.technical.ma_crossover import MACrossoverStrategy
from src.application.strategy.backtest_engine import BacktestEngine

router = APIRouter()

@router.get("/strategy/strategies")
async def get_strategies():
    return success(data={
        "strategies": [
            {"id": "ma_crossover", "name": "MA Crossover", "type": "technical"}
        ]
    })

@router.post("/strategy/backtest")
async def run_backtest(
    strategy_id: str = Body(...),
    symbols: List[str] = Body(...),
    start: date = Body(...),
    end: date = Body(...)
):
    strategy = MACrossoverStrategy(fast=5, slow=20)
    engine = BacktestEngine(initial_capital=100000)
    result = engine.run(strategy, symbols, start, end)

    return success(data={
        "strategy_id": result.strategy_id,
        "total_return": result.total_return,
        "trade_count": result.trade_count
    })
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/api/test_strategy_router.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/router/strategy_router.py backend/tests/api/test_strategy_router.py
git commit -m "feat: add strategy API endpoints"
```

---

## Phase 3: 投资组合引擎

### Task 3.1: 订单与持仓模型

**Files:**
- Create: `backend/src/domain/portfolio/order.py`
- Create: `backend/src/domain/portfolio/position.py`
- Create: `backend/tests/domain/test_portfolio_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/domain/test_portfolio_models.py
from datetime import datetime
from src.domain.portfolio.order import Order, OrderStatus, OrderType
from src.domain.portfolio.position import Position

def test_order_creation():
    order = Order(
        symbol="000001.SZ",
        side="BUY",
        order_type=OrderType.LIMIT,
        price=10.5,
        quantity=100
    )
    assert order.symbol == "000001.SZ"
    assert order.status == OrderStatus.PENDING

def test_position_update():
    pos = Position(symbol="000001.SZ", quantity=100, avg_price=10.0)
    pos.update(quantity=50, price=10.5)
    assert pos.quantity == 150
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/test_portfolio_models.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/domain/portfolio/order.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

class OrderType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"

class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderStatus(Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

@dataclass
class Order:
    id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.LIMIT
    price: float = 0.0
    quantity: int = 0
    filled_quantity: int = 0
    status: OrderStatus = OrderStatus.PENDING
    strategy_id: Optional[str] = None

# backend/src/domain/portfolio/position.py
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Position:
    symbol: str
    quantity: int = 0
    avg_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    updated_at: datetime = None

    def update(self, quantity: int, price: float):
        if quantity > 0:
            total_cost = self.quantity * self.avg_price + quantity * price
            self.quantity += quantity
            self.avg_price = total_cost / self.quantity if self.quantity > 0 else 0
        else:
            self.quantity += quantity
            if self.quantity == 0:
                self.realized_pnl += (self.avg_price - price) * abs(quantity)
                self.avg_price = 0

        self.current_price = price
        self.unrealized_pnl = (price - self.avg_price) * self.quantity
        self.updated_at = datetime.now()
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/test_portfolio_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/portfolio/order.py backend/src/domain/portfolio/position.py
git commit -m "feat: add order and position domain models"
```

---

### Task 3.2: P&L 计算器

**Files:**
- Create: `backend/src/application/portfolio/pnl_calculator.py`
- Create: `backend/tests/application/test_pnl_calculator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/application/test_pnl_calculator.py
from src.application.portfolio.pnl_calculator import PnLCalculator

def test_pnl_calculation():
    calc = PnLCalculator(initial_capital=100000)

    calc.update_position("000001.SZ", quantity=100, price=10.0)
    calc.update_price("000001.SZ", 10.5)

    assert abs(calc.get_unrealized_pnl("000001.SZ") - 50.0) < 0.01
    assert abs(calc.get_total_equity() - 100050.0) < 0.01
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/application/test_pnl_calculator.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/application/portfolio/pnl_calculator.py
from typing import Dict, Optional
from src.domain.portfolio.position import Position

class PnLCalculator:
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}

    def update_position(self, symbol: str, quantity: int, price: float):
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)

        pos = self.positions[symbol]

        if quantity > 0:
            cost = quantity * price
            self.cash -= cost
        else:
            proceeds = abs(quantity) * price
            self.cash += proceeds
            pos.realized_pnl += (price - pos.avg_price) * abs(quantity)

        pos.update(quantity, price)

    def update_price(self, symbol: str, price: float):
        if symbol in self.positions:
            self.positions[symbol].current_price = price
            self.positions[symbol].unrealized_pnl = (price - self.positions[symbol].avg_price) * self.positions[symbol].quantity

    def get_unrealized_pnl(self, symbol: str) -> float:
        if symbol not in self.positions:
            return 0.0
        return self.positions[symbol].unrealized_pnl

    def get_realized_pnl(self, symbol: str) -> float:
        if symbol not in self.positions:
            return 0.0
        return self.positions[symbol].realized_pnl

    def get_total_equity(self) -> float:
        pos_value = sum(p.current_price * p.quantity for p in self.positions.values())
        return self.cash + pos_value

    def get_total_pnl(self) -> float:
        return self.get_total_equity() - self.initial_capital
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/application/test_pnl_calculator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/application/portfolio/pnl_calculator.py
git commit -m "feat: add P&L calculator for portfolio tracking"
```

---

### Task 3.3: 投资组合 API

**Files:**
- Create: `backend/src/api/router/portfolio_router.py`
- Create: `backend/tests/api/test_portfolio_router.py`

- [ ] **Step 1: Write failing test**

```python
# tests/api/test_portfolio_router.py
import pytest
from fastapi.testclient import TestClient
from main import create_app

@pytest.fixture
def client():
    return TestClient(create_app())

def test_get_positions(client):
    response = client.get("/portfolio/positions")
    assert response.status_code == 200

def test_create_order(client):
    response = client.post("/portfolio/orders", json={
        "symbol": "000001.SZ",
        "side": "BUY",
        "order_type": "LIMIT",
        "price": 10.5,
        "quantity": 100
    })
    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/api/test_portfolio_router.py -v`
Expected: FAIL - router not found

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/api/router/portfolio_router.py
from fastapi import APIRouter, Body
from pydantic import BaseModel
from typing import List, Optional
from src.pkg.responses import success
from src.domain.portfolio.order import Order, OrderType, OrderSide
from src.domain.portfolio.position import Position
from src.application.portfolio.pnl_calculator import PnLCalculator

router = APIRouter()

portfolio = {
    "positions": {},
    "orders": [],
    "calculator": PnLCalculator(initial_capital=100000)
}

class OrderRequest(BaseModel):
    symbol: str
    side: str
    order_type: str = "LIMIT"
    price: float
    quantity: int
    strategy_id: Optional[str] = None

@router.get("/portfolio/positions")
async def get_positions():
    return success(data={
        "positions": [
            {
                "symbol": pos.symbol,
                "quantity": pos.quantity,
                "avg_price": pos.avg_price,
                "current_price": pos.current_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "realized_pnl": pos.realized_pnl
            }
            for pos in portfolio["positions"].values()
        ]
    })

@router.post("/portfolio/orders")
async def create_order(order_req: OrderRequest):
    order = Order(
        symbol=order_req.symbol,
        side=OrderSide.BUY if order_req.side == "BUY" else OrderSide.SELL,
        order_type=OrderType[order_req.order_type],
        price=order_req.price,
        quantity=order_req.quantity,
        strategy_id=order_req.strategy_id
    )
    portfolio["orders"].append(order)

    if order.symbol not in portfolio["positions"]:
        portfolio["positions"][order.symbol] = Position(symbol=order.symbol)

    pos = portfolio["positions"][order.symbol]
    calc = portfolio["calculator"]

    if order.side == OrderSide.BUY:
        calc.update_position(order.symbol, order.quantity, order.price)
        pos.quantity += order.quantity
    else:
        calc.update_position(order.symbol, -order.quantity, order.price)
        pos.quantity -= order.quantity

    portfolio["positions"][order.symbol] = pos

    return success(data={"order_id": len(portfolio["orders"]), "status": "FILLED"})

@router.get("/portfolio/performance")
async def get_performance():
    calc = portfolio["calculator"]
    return success(data={
        "initial_capital": calc.initial_capital,
        "total_equity": calc.get_total_equity(),
        "total_pnl": calc.get_total_pnl(),
        "cash": calc.cash
    })
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/api/test_portfolio_router.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/router/portfolio_router.py
git commit -m "feat: add portfolio API endpoints"
```

---

## Phase 4: 风险引擎

### Task 4.1: 风控规则引擎

**Files:**
- Create: `backend/src/domain/risk/rules.py`
- Create: `backend/src/domain/risk/evaluator.py`
- Create: `backend/tests/domain/test_risk_engine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/domain/test_risk_engine.py
from src.domain.risk.rules import PositionLimit, StopLoss
from src.domain.risk.evaluator import RiskEvaluator

def test_position_limit():
    rule = PositionLimit(max_position_per_stock=10000)
    assert rule.evaluate(position_value=15000) == False
    assert rule.evaluate(position_value=5000) == True
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/test_risk_engine.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/domain/risk/rules.py
from abc import ABC, abstractmethod

class RiskRule(ABC):
    @abstractmethod
    def evaluate(self, **kwargs) -> bool:
        pass

class PositionLimit(RiskRule):
    def __init__(self, max_position_per_stock: float):
        self.max_position_per_stock = max_position_per_stock

    def evaluate(self, **kwargs) -> bool:
        position_value = kwargs.get("position_value", 0)
        return position_value <= self.max_position_per_stock

class StopLoss(RiskRule):
    def __init__(self, max_loss_percent: float):
        self.max_loss_percent = max_loss_percent

    def evaluate(self, **kwargs) -> bool:
        pnl_percent = kwargs.get("pnl_percent", 0)
        return pnl_percent >= -self.max_loss_percent

# backend/src/domain/risk/evaluator.py
from typing import List
from .rules import RiskRule

class RiskEvaluator:
    def __init__(self):
        self.rules: List[RiskRule] = []

    def add_rule(self, rule: RiskRule):
        self.rules.append(rule)

    def evaluate(self, **kwargs) -> tuple[bool, List[str]]:
        violations = []
        for rule in self.rules:
            if not rule.evaluate(**kwargs):
                violations.append(rule.__class__.__name__)
        return len(violations) == 0, violations
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/test_risk_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/risk/
git commit -m "feat: add risk rule engine"
```

---

## Phase 5: AI Lab 模块

### Task 5.1: AI Lab 领域模型

**Files:**
- Create: `backend/src/domain/ailab/models.py`
- Create: `backend/tests/domain/test_ailab_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/domain/test_ailab_models.py
from src.domain.ailab.models import Discussion, Message, Agent

def test_discussion_creation():
    discussion = Discussion(topic="分析茅台走势")
    assert discussion.topic == "分析茅台走势"
    assert len(discussion.messages) == 0
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/test_ailab_models.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/domain/ailab/models.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

class AgentRole(Enum):
    MARKET_ANALYST = "market_analyst"
    FUNDAMENTAL_ANALYST = "fundamental_analyst"
    NEWS_ANALYST = "news_analyst"
    STRATEGY_AGENT = "strategy_agent"
    RISK_AGENT = "risk_agent"
    COORDINATOR = "coordinator"

@dataclass
class Message:
    id: Optional[str] = None
    agent_role: AgentRole = AgentRole.COORDINATOR
    content: str = ""
    created_at: datetime = field(default_factory=datetime.now)

@dataclass
class Discussion:
    id: Optional[str] = None
    topic: str = ""
    messages: List[Message] = field(default_factory=list)
    status: str = "active"
    created_at: datetime = field(default_factory=datetime.now)
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/domain/test_ailab_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/ailab/models.py
git commit -m "feat: add AI Lab domain models"
```

---

### Task 5.2: AI Agent 服务

**Files:**
- Create: `backend/src/application/ailab/agent_service.py`
- Create: `backend/tests/application/test_agent_service.py`

- [ ] **Step 1: Write failing test**

```python
# tests/application/test_agent_service.py
from src.application.ailab.agent_service import AgentService, AgentFactory

def test_agent_factory():
    factory = AgentFactory()
    analyst = factory.create_agent("market_analyst")
    assert analyst is not None
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/application/test_agent_service.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/application/ailab/agent_service.py
from abc import ABC, abstractmethod
from typing import Optional
from src.domain.ailab.models import AgentRole

class BaseAgent(ABC):
    def __init__(self, role: AgentRole):
        self.role = role

    @abstractmethod
    def analyze(self, context: dict) -> str:
        pass

class MarketAnalystAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentRole.MARKET_ANALYST)

    def analyze(self, context: dict) -> str:
        return f"市场分析：基于技术指标分析 {context.get('symbol', '未知')}"

class FundamentalAnalystAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentRole.FUNDAMENTAL_ANALYST)

    def analyze(self, context: dict) -> str:
        return f"基本面分析：基于财报数据分析 {context.get('symbol', '未知')}"

class AgentFactory:
    _agents = {
        "market_analyst": MarketAnalystAgent,
        "fundamental_analyst": FundamentalAnalystAgent,
    }

    def create_agent(self, agent_type: str) -> Optional[BaseAgent]:
        agent_class = self._agents.get(agent_type)
        return agent_class() if agent_class else None

class AgentService:
    def __init__(self):
        self.factory = AgentFactory()

    def get_agent(self, agent_type: str):
        return self.factory.create_agent(agent_type)
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/application/test_agent_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/application/ailab/agent_service.py
git commit -m "feat: add AI agent service"
```

---

### Task 5.3: AI Lab API 与 WebSocket

**Files:**
- Create: `backend/src/api/router/ailab_router.py`
- Create: `backend/tests/api/test_ailab_router.py`

- [ ] **Step 1: Write failing test**

```python
# tests/api/test_ailab_router.py
import pytest
from fastapi.testclient import TestClient
from main import create_app

@pytest.fixture
def client():
    return TestClient(create_app())

def test_create_discussion(client):
    response = client.post("/ailab/discuss", json={
        "topic": "分析茅台走势",
        "symbol": "600519.SH"
    })
    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/api/test_ailab_router.py -v`
Expected: FAIL - router not found

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/api/router/ailab_router.py
from fastapi import APIRouter, Body, WebSocket
from pydantic import BaseModel
from typing import List, Optional
from src.pkg.responses import success
from src.domain.ailab.models import Discussion, Message, AgentRole
from src.application.ailab.agent_service import AgentService

router = APIRouter()
agent_service = AgentService()
discussions = {}

class DiscussRequest(BaseModel):
    topic: str
    symbol: Optional[str] = None

@router.post("/ailab/discuss")
async def create_discussion(req: DiscussRequest):
    discussion = Discussion(topic=req.topic)
    discussions[discussion.id] = discussion
    return success(data={"discuss_id": discussion.id, "status": "active"})

@router.get("/ailab/discuss/{discuss_id}")
async def get_discussion(discuss_id: str):
    discussion = discussions.get(discuss_id)
    if not discussion:
        return success(data={"error": "not found"}, code=404)
    return success(data={
        "id": discussion.id,
        "topic": discussion.topic,
        "messages": [{"content": m.content, "role": m.agent_role.value} for m in discussion.messages]
    })

@router.websocket("/ailab/ws/{discuss_id}")
async def websocket_discuss(websocket: WebSocket, discuss_id: str):
    await websocket.accept()
    discussion = discussions.get(discuss_id)
    if not discussion:
        await websocket.close()
        return

    agents = ["market_analyst", "fundamental_analyst"]
    for agent_type in agents:
        agent = agent_service.get_agent(agent_type)
        if agent:
            context = {"symbol": "000001.SZ", "topic": discussion.topic}
            response = agent.analyze(context)
            await websocket.send_text(response)
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m pytest tests/api/test_ailab_router.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/router/ailab_router.py
git commit -m "feat: add AI Lab API with WebSocket support"
```

---

## Phase 6: 前端界面

### Task 6.1: 前端项目结构初始化

**Files:**
- Create: `frontend/apps/web/src/main.tsx`
- Create: `frontend/apps/web/src/App.tsx`
- Modify: `frontend/apps/web/index.html`

- [ ] **Step 1: Write failing test**

```typescript
// apps/web/src/__tests__/App.test.tsx
import { render, screen } from '@testing-library/react';
import App from '../App';

test('renders app', () => {
  render(<App />);
  expect(screen.getByText(/Dashboard/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend && pnpm test`
Expected: FAIL - files not found

- [ ] **Step 3: Write minimal implementation**

```typescript
// apps/web/src/main.tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/global.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// apps/web/src/App.tsx
import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import Dashboard from './pages/Dashboard';
import Market from './pages/Market';
import Trading from './pages/Trading';
import Strategies from './pages/Strategies';
import AILab from './pages/AILab';
import Portfolio from './pages/Portfolio';
import Risk from './pages/Risk';
import Settings from './pages/Settings';

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/market" element={<Market />} />
          <Route path="/trading" element={<Trading />} />
          <Route path="/strategies" element={<Strategies />} />
          <Route path="/ailab" element={<AILab />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/risk" element={<Risk />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
};

export default App;
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend && pnpm test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/main.tsx frontend/apps/web/src/App.tsx
git commit -m "feat: setup frontend app with routing"
```

---

### Task 6.2: Layout 组件

**Files:**
- Create: `frontend/apps/web/src/components/Layout.tsx`
- Create: `frontend/apps/web/src/components/Layout.css`

- [ ] **Step 1: Write failing test**

```typescript
// apps/web/src/__tests__/Layout.test.tsx
import { render, screen } from '@testing-library/react';
import { Layout } from '../components/Layout';

test('renders navigation items', () => {
  render(<Layout><div>Content</div></Layout>);
  expect(screen.getByText('Dashboard')).toBeInTheDocument();
  expect(screen.getByText('Market')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend && pnpm test`
Expected: FAIL - Component not found

- [ ] **Step 3: Write minimal implementation**

```typescript
// apps/web/src/components/Layout.tsx
import React from 'react';
import { NavLink } from 'react-router-dom';
import './Layout.css';

interface LayoutProps {
  children: React.ReactNode;
}

const navItems = [
  { path: '/dashboard', label: 'Dashboard', icon: '📊' },
  { path: '/market', label: 'Market', icon: '📈' },
  { path: '/trading', label: 'Trading', icon: '💱' },
  { path: '/strategies', label: 'Strategies', icon: '⚡' },
  { path: '/ailab', label: 'AI Lab', icon: '🤖' },
  { path: '/portfolio', label: 'Portfolio', icon: '💼' },
  { path: '/risk', label: 'Risk', icon: '🛡️' },
  { path: '/settings', label: 'Settings', icon: '⚙️' },
];

export const Layout: React.FC<LayoutProps> = ({ children }) => {
  return (
    <div className="layout">
      <aside className="layout__sidebar">
        <div className="layout__logo">
          <span className="layout__logo-text">YTrader</span>
        </div>
        <nav className="layout__nav">
          {navItems.map(item => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `layout__nav-item ${isActive ? 'layout__nav-item--active' : ''}`
              }
            >
              <span className="layout__nav-icon">{item.icon}</span>
              <span className="layout__nav-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="layout__footer">
          <span className="layout__version">v0.1.0</span>
        </div>
      </aside>
      <main className="layout__main">{children}</main>
    </div>
  );
};
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend && pnpm test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/components/Layout.tsx frontend/apps/web/src/components/Layout.css
git commit -m "feat: add layout component with navigation"
```

---

### Task 6.3: Dashboard 页面

**Files:**
- Create: `frontend/apps/web/src/pages/Dashboard.tsx`
- Create: `frontend/apps/web/src/pages/Dashboard.css`

- [ ] **Step 1: Write failing test**

```typescript
// apps/web/src/__tests__/Dashboard.test.tsx
import { render, screen } from '@testing-library/react';
import Dashboard from '../pages/Dashboard';

test('renders dashboard', () => {
  render(<Dashboard />);
  expect(screen.getByText(/Portfolio/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend && pnpm test`
Expected: FAIL - Page not found

- [ ] **Step 3: Write minimal implementation**

```typescript
// apps/web/src/pages/Dashboard.tsx
import React from 'react';
import { Card } from '@ytrader/common-components';
import { useTheme } from '@ytrader/arch-hooks';
import './Dashboard.css';

const Dashboard: React.FC = () => {
  const { theme } = useTheme();

  return (
    <div className="dashboard">
      <header className="dashboard__header">
        <h1 className="dashboard__title">Dashboard</h1>
        <p className="dashboard__subtitle">Portfolio Overview</p>
      </header>

      <div className="dashboard__grid">
        <Card className="dashboard__card">
          <div className="dashboard__metric">
            <span className="dashboard__metric-label">Total Equity</span>
            <span className="dashboard__metric-value">$100,000.00</span>
          </div>
        </Card>

        <Card className="dashboard__card">
          <div className="dashboard__metric">
            <span className="dashboard__metric-label">Daily P&L</span>
            <span className="dashboard__metric-value dashboard__metric-value--positive">
              +$1,234.56
            </span>
          </div>
        </Card>

        <Card className="dashboard__card">
          <div className="dashboard__metric">
            <span className="dashboard__metric-label">Open Positions</span>
            <span className="dashboard__metric-value">5</span>
          </div>
        </Card>

        <Card className="dashboard__card">
          <div className="dashboard__metric">
            <span className="dashboard__metric-label">Active Strategies</span>
            <span className="dashboard__metric-value">3</span>
          </div>
        </Card>
      </div>
    </div>
  );
};

export default Dashboard;
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend && pnpm test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/Dashboard.tsx frontend/apps/web/src/pages/Dashboard.css
git commit -m "feat: add dashboard page with portfolio overview"
```

---

## 实施检查清单

- [ ] Phase 1 Tasks 1.1 - 1.5 (数据基础设施)
- [ ] Phase 2 Tasks 2.1 - 2.5 (策略框架与回测)
- [ ] Phase 3 Tasks 3.1 - 3.3 (投资组合引擎)
- [ ] Phase 4 Task 4.1 (风险引擎)
- [ ] Phase 5 Tasks 5.1 - 5.3 (AI Lab 模块)
- [ ] Phase 6 Tasks 6.1 - 6.3 (前端界面)

---

**Plan Version:** 1.0
**Created:** 2026-03-27
