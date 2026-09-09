# ETF 配置组合数据采集 (P1) 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 12 个配置组合标的（6 A股ETF + 6 美股）+ USDCNY 汇率的日线拉入本地库，回测即时可用。

**Architecture:** 在 `market/sync` 体系新增 `AkshareProvider`（白嫖现有 SyncService/ProgressTracker），复用 `stock_ohlcv` 表（`market='US'`），新增独立 `fx_rate` 表（SQLModel 守规范）。详见 spec `docs/superpowers/specs/2026-06-21-etf-portfolio-data-sync-design.md`。

**Tech Stack:** Python, akshare 1.18.50, SQLModel, psycopg2 (sync 既有), pytest

---

## 关键事实（实现前必读，已联网验证）

akshare 1.18.50 三个接口的真实返回列（测试 fixture 据此写）：

| 接口 | 列名 | 备注 |
|------|------|------|
| `ak.fund_etf_hist_em(symbol="510300", period="daily", adjust="qfq")` | 日期/开盘/收盘/最高/最低/成交量/成交额/振幅/涨跌幅/涨跌额/换手率 | **中文列**；日期格式 "2012-05-28" |
| `ak.stock_us_daily(symbol="VOO", adjust="qfq")` | date/open/high/low/close/volume | **英文小写**；无 amount（填 0）；date 是 Timestamp |
| `ak.currency_boc_sina(symbol="美元", start_date, end_date)` | 日期/中行汇买价/中行钞买价/中行钞卖价/央行中间价/中行折算价 | 取"中行折算价"，单位是**每百美元人民币**，rate = 中行折算价 / 100 |

现有接口契约：
- `SyncService(provider, tracker, SyncConfig(db_dsn=...))` → `.backfill(symbols=[], interval="1d", mode="full"|"incremental"|"resume")`
- `ProgressTracker().get_last_sync(provider: str, symbol: str, interval: str) -> Optional[str]`
- `create_db_connection()` → `db.session_scope()` contextmanager（`engine.py`）
- 配置：`from conf import app_config`（`AppConfig` 单例，`load_local_config` 读 `conf/config.yaml`）

---

## File Structure

| 文件 | 职责 | 动作 |
|------|------|------|
| `conf/settings.py` | 加 `PortfolioUniverseConfig` 模型 + `AppConfig.portfolio_universe` 字段 | 修改 |
| `conf/config.yaml` | 加 `portfolio_universe` 段（12标的+USDCNY） | 修改 |
| `infra/database/market/__init__.py` | 新建包 | 新建 |
| `infra/database/market/fx_rate.py` | `FxRate` entity + `FxRateRepository` + 工厂 | 新建 |
| `domain/market/sync/providers/akshare_provider.py` | `AkshareProvider(SyncProvider)` | 新建 |
| `domain/market/sync/jobs/portfolio_daily.py` | 组合篮子同步入口 | 新建 |
| `tests/infra/database/market/test_fx_rate.py` | fx_rate upsert 幂等 | 新建 |
| `tests/domain/market/sync/providers/test_akshare_provider.py` | provider 单测 | 新建 |
| `tests/domain/market/sync/jobs/test_portfolio_daily.py` | run() 集成测试 | 新建 |

---

## Task 1: portfolio_universe 配置模型 + config.yaml

**Files:**
- Modify: `conf/settings.py`（在 `AppConfig` 前加 3 个模型 + `AppConfig` 加字段）
- Modify: `conf/config.yaml`（加 `portfolio_universe` 段）
- Test: `tests/conf/test_portfolio_universe_config.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/conf/test_portfolio_universe_config.py
from conf.settings import PortfolioUniverseConfig


def test_portfolio_universe_config_parses():
    raw = {
        "bars": [
            {"symbol": "VOO", "market": "US", "ccy": "USD",
             "name": "标普500", "asset": "equity"},
            {"symbol": "sh510300", "market": "A", "ccy": "CNY",
             "name": "沪深300ETF", "asset": "equity"},
        ],
        "fx": [{"pair": "USDCNY"}],
    }
    cfg = PortfolioUniverseConfig(**raw)
    assert len(cfg.bars) == 2
    assert cfg.bars[0].symbol == "VOO"
    assert cfg.bars[0].market == "US"
    assert cfg.bars[1].ccy == "CNY"
    assert cfg.fx[0].pair == "USDCNY"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python -m pytest tests/conf/test_portfolio_universe_config.py -v`
Expected: FAIL `ImportError: cannot import name 'PortfolioUniverseConfig'`

- [ ] **Step 3: 实现 — 在 `conf/settings.py` 加模型**

在 `class AppConfig(BaseModel):` **之前**插入：

```python
class PortfolioUniverseBarConfig(BaseModel):
    """配置组合中的行情标的"""
    symbol: str
    market: str        # "A" | "US"
    ccy: str           # "CNY" | "USD"
    name: str
    asset: str         # equity | bond | gold | cash


class PortfolioUniverseFxConfig(BaseModel):
    """配置组合涉及的汇率对"""
    pair: str          # "USDCNY"


class PortfolioUniverseConfig(BaseModel):
    """配置组合标的清单（永久投资组合风格）"""
    bars: list[PortfolioUniverseBarConfig] = []
    fx: list[PortfolioUniverseFxConfig] = []
```

然后在 `class AppConfig(BaseModel):` 内加字段：

```python
    portfolio_universe: PortfolioUniverseConfig = PortfolioUniverseConfig()
```

- [ ] **Step 4: 在 `conf/config.yaml` 加 portfolio_universe 段**

在 yaml 顶层加：

```yaml
portfolio_universe:
  bars:
    - { symbol: "sh510300", market: "A",  ccy: "CNY", name: "沪深300ETF",   asset: "equity" }
    - { symbol: "sh511260", market: "A",  ccy: "CNY", name: "10年国债ETF",   asset: "bond" }
    - { symbol: "sh511090", market: "A",  ccy: "CNY", name: "30年国债ETF",   asset: "bond" }
    - { symbol: "sh518880", market: "A",  ccy: "CNY", name: "华安黄金ETF",   asset: "gold" }
    - { symbol: "sz159934", market: "A",  ccy: "CNY", name: "博时黄金ETF",   asset: "gold" }
    - { symbol: "sh511990", market: "A",  ccy: "CNY", name: "华宝添益",     asset: "cash" }
    - { symbol: "VOO",      market: "US", ccy: "USD", name: "标普500",     asset: "equity" }
    - { symbol: "TLT",      market: "US", ccy: "USD", name: "20+年国债",   asset: "bond" }
    - { symbol: "GLD",      market: "US", ccy: "USD", name: "黄金ETF",     asset: "gold" }
    - { symbol: "SHV",      market: "US", ccy: "USD", name: "短债ETF",     asset: "cash" }
  fx:
    - { pair: "USDCNY" }
```

- [ ] **Step 5: 运行测试验证通过**

Run: `.venv/bin/python -m pytest tests/conf/test_portfolio_universe_config.py -v`
Expected: PASS

- [ ] **Step 6: 验证 app_config 能加载**

Run: `.venv/bin/python -c "from conf import app_config; print(len(app_config.portfolio_universe.bars), [f.pair for f in app_config.portfolio_universe.fx])"`
Expected: `10 ['USDCNY']`

- [ ] **Step 7: Commit**

```bash
git add conf/settings.py conf/config.yaml tests/conf/test_portfolio_universe_config.py
git commit -m "feat(conf): add portfolio_universe config (10 bars + USDCNY)"
```

---

## Task 2: FxRate entity + repository

**Files:**
- Create: `infra/database/market/__init__.py`（空）
- Create: `infra/database/market/fx_rate.py`
- Test: `tests/infra/database/market/test_fx_rate.py`

- [ ] **Step 1: 写失败测试（用 sqlite in-memory，不依赖 PG）**

```python
# tests/infra/database/market/test_fx_rate.py
from contextlib import contextmanager
from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select

from src.infra.database.market.fx_rate import FxRate, FxRateRepository


class _FakeDb:
    """模拟 DBConnection，session_scope 返回 sqlite session"""
    def __init__(self, engine):
        self._engine = engine

    @contextmanager
    def session_scope(self):
        with Session(self._engine) as s:
            yield s


def _make_repo():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine, tables=[FxRate.__table__])
    return FxRateRepository(_FakeDb(engine))


def test_upsert_insert_then_update_idempotent():
    repo = _make_repo()
    repo.upsert(date(2026, 6, 20), "USDCNY", 6.81)
    repo.upsert(date(2026, 6, 20), "USDCNY", 6.82)   # 同日覆盖
    assert repo.get_latest_date("USDCNY") == date(2026, 6, 20)


def test_get_latest_date_none_when_empty():
    repo = _make_repo()
    assert repo.get_latest_date("USDCNY") is None


def test_upsert_multiple_dates_latest_wins():
    repo = _make_repo()
    repo.upsert(date(2026, 6, 19), "USDCNY", 6.80)
    repo.upsert(date(2026, 6, 20), "USDCNY", 6.81)
    assert repo.get_latest_date("USDCNY") == date(2026, 6, 20)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python -m pytest tests/infra/database/market/test_fx_rate.py -v`
Expected: FAIL `ImportError: cannot import name 'FxRate'`

- [ ] **Step 3: 实现 entity + repository**

```python
# infra/database/market/__init__.py
# （空文件，声明包）
```

```python
# infra/database/market/fx_rate.py
"""fx_rate 表：汇率日线（独立于 stock_ohlcv，语义为标量比率而非 K 线）"""
from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, Session, SQLModel, select

from src.infra.database.sql_engine.engine import create_db_connection


class FxRate(SQLModel, table=True):
    __tablename__ = "fx_rate"
    date: date = Field(primary_key=True)
    pair: str = Field(primary_key=True)       # "USDCNY"
    rate: float
    source: str = "akshare"
    created_at: datetime = Field(default_factory=datetime.now)


class FxRateRepository:
    """汇率数据访问（守 SQLModel ORM 规范）"""

    def __init__(self, db):
        # db 须提供 session_scope() contextmanager（DBConnection 协议）
        self._db = db

    def upsert(self, date_: date, pair: str, rate: float,
               source: str = "akshare") -> None:
        with self._db.session_scope() as s:  # type: Session
            existing = s.exec(
                select(FxRate).where(
                    FxRate.date == date_, FxRate.pair == pair
                )
            ).first()
            if existing:
                existing.rate = rate
                existing.source = source
            else:
                s.add(FxRate(date=date_, pair=pair, rate=rate, source=source))
            s.commit()

    def get_latest_date(self, pair: str) -> Optional[date]:
        with self._db.session_scope() as s:  # type: Session
            row = s.exec(
                select(FxRate).where(FxRate.pair == pair)
                .order_by(FxRate.date.desc())
            ).first()
            return row.date if row else None


def create_fx_rate_repository() -> FxRateRepository:
    return FxRateRepository(create_db_connection())
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python -m pytest tests/infra/database/market/test_fx_rate.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/infra/database/market/__init__.py src/infra/database/market/fx_rate.py tests/infra/database/market/test_fx_rate.py
git commit -m "feat(infra): add fx_rate table + repository (SQLModel, upsert idempotent)"
```

---

## Task 3: AkshareProvider — validate_symbol + symbol 规范化

**Files:**
- Create: `domain/market/sync/providers/akshare_provider.py`
- Test: `tests/domain/market/sync/providers/test_akshare_provider.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/domain/market/sync/providers/test_akshare_provider.py
import pytest

from src.domain.market.sync.providers.akshare_provider import AkshareProvider


@pytest.fixture
def prov():
    return AkshareProvider()


def test_validate_us_ticker_passes(prov):
    assert prov.validate_symbol("VOO") is True
    assert prov.validate_symbol("TLT") is True
    assert prov.validate_symbol("GLD") is True


def test_validate_a_etf_passes(prov):
    assert prov.validate_symbol("sh510300") is True
    assert prov.validate_symbol("sz159934") is True   # sz1 前缀（旧 Tencent 会挡）


def test_validate_rejects_garbage(prov):
    assert prov.validate_symbol("123abc") is False
    assert prov.validate_symbol("") is False
    assert prov.validate_symbol("TOOLONGSYMBOL") is False   # >5 字母


def test_is_us_ticker(prov):
    assert prov._is_us_ticker("VOO") is True
    assert prov._is_us_ticker("sh510300") is False


def test_strip_a_etf_prefix(prov):
    assert prov._strip_exchange_prefix("sh510300") == "510300"
    assert prov._strip_exchange_prefix("sz159934") == "159934"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: 实现 provider 骨架（符号识别 + 规范化，fetch 方法留到 Task 4-6）**

```python
# domain/market/sync/providers/akshare_provider.py
"""AKShare 数据源 Provider（A股ETF + 美股 + 汇率，统一走 akshare）"""
import re
from datetime import datetime
from typing import Optional

from src.domain.market.sync.sync_provider import OHLCVBar, SyncProvider


_US_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
_A_PREFIX_RE = re.compile(r"^(sh|sz)(\d{6})$")


class AkshareProvider(SyncProvider):
    name = "akshare"
    supports_minute = False

    # ── 符号识别 / 规范化 ────────────────────────────────────────────────
    @staticmethod
    def _is_us_ticker(symbol: str) -> bool:
        return bool(_US_TICKER_RE.match(symbol))

    @staticmethod
    def _strip_exchange_prefix(symbol: str) -> str:
        """sh510300 → 510300（akshare fund_etf_hist_em 吃纯数字）"""
        m = _A_PREFIX_RE.match(symbol)
        return m.group(2) if m else symbol

    def validate_symbol(self, symbol: str) -> bool:
        if not symbol:
            return False
        if _US_TICKER_RE.match(symbol):
            return True
        if _A_PREFIX_RE.match(symbol):
            return True
        return False

    # ── fetch 方法（Task 4-6 实现）──────────────────────────────────────
    def fetch_daily(self, symbol, start_date=None, end_date=None, datalen=1300):
        raise NotImplementedError

    def fetch_minute(self, *a, **kw):
        raise NotImplementedError("P1 不支持分钟线")

    def get_stock_list(self, market="A"):
        raise NotImplementedError

    # 汇率（Task 6）
    def fetch_fx_daily(self, pair, start_date=None, end_date=None):
        raise NotImplementedError
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/market/sync/providers/akshare_provider.py tests/domain/market/sync/providers/test_akshare_provider.py
git commit -m "feat(sync): AkshareProvider skeleton — symbol validate + normalize"
```

---

## Task 4: AkshareProvider — fetch_daily A股ETF

**Files:**
- Modify: `domain/market/sync/providers/akshare_provider.py`（实现 `_fetch_a_etf`）
- Test: `tests/domain/market/sync/providers/test_akshare_provider.py`（追加）

- [ ] **Step 1: 追加失败测试（mock akshare，中文列 fixture）**

```python
# 追加到 tests/domain/market/sync/providers/test_akshare_provider.py
import pandas as pd


def _a_etf_df():
    """模拟 ak.fund_etf_hist_em 返回（中文列，真实结构）"""
    return pd.DataFrame({
        "日期": ["2026-06-19", "2026-06-20"],
        "开盘": [1.0, 1.1],
        "收盘": [1.1, 1.2],
        "最高": [1.2, 1.3],
        "最低": [0.9, 1.0],
        "成交量": [100000, 110000],
        "成交额": [110000.0, 132000.0],
        "振幅": [30.0, 27.27],
        "涨跌幅": [10.0, 9.09],
        "涨跌额": [0.1, 0.1],
        "换手率": [1.0, 1.1],
    })


def test_fetch_daily_a_etf_maps_chinese_columns(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod

    captured = {}

    def fake(symbol, period="daily", adjust="qfq", **kw):
        captured["symbol"] = symbol
        return _a_etf_df()

    monkeypatch.setattr(mod.ak, "fund_etf_hist_em", fake)
    prov = mod.AkshareProvider()
    bars = prov.fetch_daily("sh510300")

    # akshare 收到的是去前缀的纯数字
    assert captured["symbol"] == "510300"
    assert len(bars) == 2
    b0 = bars[0]
    assert isinstance(b0, mod.OHLCVBar)
    assert b0.symbol == "sh510300"
    assert b0.market == "A"
    assert b0.open_ == 1.0 and b0.close_ == 1.1
    assert b0.high_ == 1.2 and b0.low_ == 0.9
    assert b0.volume == 100000 and b0.amount == 110000.0
    assert b0.trade_time == datetime(2026, 6, 19)
    assert bars[1].trade_time == datetime(2026, 6, 20)


def test_fetch_daily_a_etf_empty_returns_empty(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(
        mod.ak, "fund_etf_hist_em",
        lambda *a, **k: pd.DataFrame(),
    )
    assert mod.AkshareProvider().fetch_daily("sh510300") == []
```

（文件顶部已有 `from datetime import datetime`，若无则补。）

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py::test_fetch_daily_a_etf_maps_chinese_columns -v`
Expected: FAIL `NotImplementedError` 或 `AttributeError: module 'akshare'`

- [ ] **Step 3: 实现 _fetch_a_etf**

修改 `akshare_provider.py`：文件顶部加 `import akshare as ak` 和 `import pandas as pd`；把 `fetch_daily` 改为分流 + 实现 `_fetch_a_etf`：

```python
import akshare as ak
import pandas as pd
# ... 其余 import 不变 ...

    # 替换 fetch_daily 占位：
    def fetch_daily(self, symbol, start_date=None, end_date=None, datalen=1300):
        if self._is_us_ticker(symbol):
            return self._fetch_us(symbol, start_date, end_date)   # Task 5
        return self._fetch_a_etf(symbol, start_date, end_date)

    def _fetch_a_etf(self, symbol, start_date=None, end_date=None):
        code = self._strip_exchange_prefix(symbol)
        try:
            df = ak.fund_etf_hist_em(
                symbol=code, period="daily", adjust="qfq",
                start_date=start_date, end_date=end_date,
            )
        except Exception:
            return []
        if df is None or df.empty:
            return []
        return self._df_to_a_bars(df, symbol)

    @staticmethod
    def _df_to_a_bars(df: pd.DataFrame, symbol: str) -> list:
        bars = []
        for _, r in df.iterrows():
            try:
                t = r["日期"]
                if isinstance(t, str):
                    t = datetime.strptime(t, "%Y-%m-%d")
                bars.append(OHLCVBar(
                    symbol=symbol,
                    trade_time=t,
                    open_=float(r["开盘"]),
                    close_=float(r["收盘"]),
                    high_=float(r["最高"]),
                    low_=float(r["最低"]),
                    volume=float(r["成交量"]),
                    amount=float(r["成交额"]),
                    interval="1d",
                    market="A",
                    provider="akshare",
                ))
            except (KeyError, ValueError, TypeError):
                continue
        return bars
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py -v`
Expected: 全部 PASS（含 Task 3 的 5 个 + Task 4 的 2 个；`_fetch_us` 未实现不影响 A 股分支）

- [ ] **Step 5: Commit**

```bash
git add src/domain/market/sync/providers/akshare_provider.py tests/domain/market/sync/providers/test_akshare_provider.py
git commit -m "feat(sync): AkshareProvider A股ETF fetch_daily (中文列映射)"
```

---

## Task 5: AkshareProvider — fetch_daily 美股

**Files:**
- Modify: `domain/market/sync/providers/akshare_provider.py`（实现 `_fetch_us`）
- Test: `tests/domain/market/sync/providers/test_akshare_provider.py`（追加）

- [ ] **Step 1: 追加失败测试（英文列 fixture，无 amount）**

```python
def _us_df():
    """模拟 ak.stock_us_daily 返回（英文小写列，Timestamp 日期）"""
    return pd.DataFrame({
        "date": pd.to_datetime(["2026-06-19", "2026-06-20"]),
        "open": [100.0, 101.0],
        "high": [102.0, 103.0],
        "low": [99.0, 100.0],
        "close": [101.0, 102.0],
        "volume": [50000.0, 51000.0],
    })


def test_fetch_daily_us_maps_english_columns(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod

    captured = {}
    def fake(symbol, adjust="qfq", **kw):
        captured["symbol"] = symbol
        return _us_df()

    monkeypatch.setattr(mod.ak, "stock_us_daily", fake)
    bars = mod.AkshareProvider().fetch_daily("VOO")

    assert captured["symbol"] == "VOO"
    assert len(bars) == 2
    b = bars[0]
    assert b.symbol == "VOO"
    assert b.market == "US"
    assert b.open_ == 100.0 and b.close_ == 101.0
    assert b.amount == 0.0                 # 美股接口无 amount
    assert b.volume == 50000.0
    assert b.trade_time == datetime(2026, 6, 19)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py::test_fetch_daily_us_maps_english_columns -v`
Expected: FAIL（`_fetch_us` 还是 NotImplementedError，或 `AttributeError: 'AkshareProvider' has no attribute '_fetch_us'`）

- [ ] **Step 3: 实现 _fetch_us**

在 `AkshareProvider` 内加：

```python
    def _fetch_us(self, symbol, start_date=None, end_date=None):
        try:
            df = ak.stock_us_daily(symbol=symbol, adjust="qfq")
        except Exception:
            return []
        if df is None or df.empty:
            return []
        bars = []
        for _, r in df.iterrows():
            try:
                t = r["date"]
                if hasattr(t, "to_pydatetime"):
                    t = t.to_pydatetime()
                elif isinstance(t, str):
                    t = datetime.strptime(t[:10], "%Y-%m-%d")
                bars.append(OHLCVBar(
                    symbol=symbol,
                    trade_time=t,
                    open_=float(r["open"]),
                    close_=float(r["close"]),
                    high_=float(r["high"]),
                    low_=float(r["low"]),
                    volume=float(r["volume"]),
                    amount=0.0,            # akshare 美股接口无成交额
                    interval="1d",
                    market="US",
                    provider="akshare",
                ))
            except (KeyError, ValueError, TypeError):
                continue
        return bars
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/market/sync/providers/akshare_provider.py tests/domain/market/sync/providers/test_akshare_provider.py
git commit -m "feat(sync): AkshareProvider 美股 fetch_daily (英文列映射, amount=0)"
```

---

## Task 6: AkshareProvider — fetch_fx_daily 汇率

**Files:**
- Modify: `domain/market/sync/providers/akshare_provider.py`（实现 `fetch_fx_daily`）
- Test: `tests/domain/market/sync/providers/test_akshare_provider.py`（追加）

- [ ] **Step 1: 追加失败测试（中行折算价 / 100 = rate）**

```python
def _fx_df():
    """模拟 ak.currency_boc_sina 返回（中行折算价 = 每百美元人民币）"""
    return pd.DataFrame({
        "日期": [date(2026, 6, 19), date(2026, 6, 20)],
        "中行汇买价": [676.47, 676.47],
        "中行钞买价": [676.47, 676.47],
        "中行钞卖价/汇卖价": [679.32, 679.32],
        "央行中间价": [None, None],
        "中行折算价": [681.3, 681.3],
    })


def test_fetch_fx_daily_returns_rate_divided_by_100(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(
        mod.ak, "currency_boc_sina",
        lambda *a, **k: _fx_df(),
    )
    rows = mod.AkshareProvider().fetch_fx_daily("USDCNY")

    assert len(rows) == 2
    assert rows[0] == (date(2026, 6, 19), 6.813)     # 681.3 / 100
    assert rows[1] == (date(2026, 6, 20), 6.813)
```

（文件顶部已有 `from datetime import date`，若无则补 `date`。）

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py::test_fetch_fx_daily_returns_rate_divided_by_100 -v`
Expected: FAIL `NotImplementedError`

- [ ] **Step 3: 实现 fetch_fx_daily**

替换 `fetch_fx_daily` 占位：

```python
    def fetch_fx_daily(self, pair: str, start_date=None, end_date=None):
        """拉汇率日线。返回 [(date, rate), ...]，rate = 中行折算价/100。
        目前仅支持 USDCNY（akshare currency_boc_sina symbol='美元'）。"""
        if pair != "USDCNY":
            return []
        # currency_boc_sina 的日期参数格式 YYYYMMDD
        sd = start_date.replace("-", "") if isinstance(start_date, str) else start_date
        ed = end_date.replace("-", "") if isinstance(end_date, str) else end_date
        try:
            df = ak.currency_boc_sina(symbol="美元", start_date=sd, end_date=ed)
        except Exception:
            return []
        if df is None or df.empty:
            return []
        out = []
        for _, r in df.iterrows():
            try:
                d = r["日期"]
                if not isinstance(d, date):
                    d = datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
                rate = float(r["中行折算价"]) / 100.0
                out.append((d, rate))
            except (KeyError, ValueError, TypeError):
                continue
        return out
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/market/sync/providers/akshare_provider.py tests/domain/market/sync/providers/test_akshare_provider.py
git commit -m "feat(sync): AkshareProvider fetch_fx_daily (USDCNY, 中行折算价/100)"
```

---

## Task 7: AkshareProvider — get_stock_list

**Files:**
- Modify: `domain/market/sync/providers/akshare_provider.py`（实现 `get_stock_list`）
- Test: `tests/domain/market/sync/providers/test_akshare_provider.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
def test_get_stock_list_reads_config_bars(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod

    class _FakeCfg:
        class portfolio_universe:
            bars = [
                type("B", (), {"symbol": "sh510300", "market": "A"})(),
                type("B", (), {"symbol": "VOO", "market": "US"})(),
                type("B", (), {"symbol": "TLT", "market": "US"})(),
            ]

    monkeypatch.setattr(mod, "app_config", _FakeCfg())
    prov = mod.AkshareProvider()
    assert prov.get_stock_list(market="A") == ["sh510300"]
    assert set(prov.get_stock_list(market="US")) == {"VOO", "TLT"}
    assert set(prov.get_stock_list()) == {"sh510300", "VOO", "TLT"}
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py::test_get_stock_list_reads_config_bars -v`
Expected: FAIL（`get_stock_list` 抛 NotImplementedError，或 `app_config` 未导入）

- [ ] **Step 3: 实现 get_stock_list**

`akshare_provider.py` 顶部加 import：
```python
from conf import app_config
```
替换 `get_stock_list` 占位：

```python
    def get_stock_list(self, market: str = "A") -> list:
        """从 app_config.portfolio_universe 读标的，按 market 过滤。
        market=None/"" 返回全部（组合篮子是固定清单，不做全市场扫描）。"""
        bars = app_config.portfolio_universe.bars
        if not market:
            return [b.symbol for b in bars]
        return [b.symbol for b in bars if b.market == market]
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/market/sync/providers/akshare_provider.py tests/domain/market/sync/providers/test_akshare_provider.py
git commit -m "feat(sync): AkshareProvider get_stock_list from app_config"
```

---

## Task 8: portfolio_daily job — run()

**Files:**
- Create: `domain/market/sync/jobs/portfolio_daily.py`
- Test: `tests/domain/market/sync/jobs/test_portfolio_daily.py`

- [ ] **Step 1: 写失败测试（mock SyncService + FxRateRepository，验证调用与 mode 判定）**

```python
# tests/domain/market/sync/jobs/test_portfolio_daily.py
from datetime import date

import src.domain.market.sync.jobs.portfolio_daily as mod


class _FakeTracker:
    def __init__(self, last_sync_map):
        self._m = last_sync_map

    def get_last_sync(self, provider, symbol, interval):
        return self._m.get(symbol)


class _FakeService:
    def __init__(self):
        self.calls = []   # [(symbols, mode)]

    def backfill(self, symbols, interval="1d", mode="full", db_dsn=""):
        self.calls.append((symbols, mode))
        from src.domain.market.sync.sync_service import SyncResult
        return SyncResult(provider="akshare", interval=interval, mode=mode,
                          total_symbols=1, done_symbols=1)


class _FakeFxRepo:
    def __init__(self, latest):
        self._latest = latest
        self.upserts = []

    def get_latest_date(self, pair):
        return self._latest

    def upsert(self, d, pair, rate, source="akshare"):
        self.upserts.append((d, pair, rate))


def test_run_uses_full_for_new_symbol_incremental_for_existing(monkeypatch):
    bars = [
        type("B", (), {"symbol": "VOO", "market": "US"})(),
        type("B", (), {"symbol": "sh510300", "market": "A"})(),
    ]
    monkeypatch.setattr(mod, "_load_universe_bars", lambda: bars)
    fake_service = _FakeService()
    monkeypatch.setattr(mod, "_build_service",
                        lambda prov, tracker: fake_service)
    # VOO 有历史 → incremental；sh510300 无 → full
    monkeypatch.setattr(mod, "_build_tracker",
                        lambda: _FakeTracker({"VOO": "2026-06-19"}))
    # 汇率走空，避免干扰
    monkeypatch.setattr(mod, "sync_fx", lambda *a, **k: None)

    mod.run()

    calls = {sym: mode for (syms, mode) in fake_service.calls for sym in syms}
    assert calls["VOO"] == "incremental"
    assert calls["sh510300"] == "full"


def test_sync_fx_pulls_from_latest_date(monkeypatch):
    fx_repo = _FakeFxRepo(latest=date(2026, 6, 19))
    monkeypatch.setattr(mod, "create_fx_rate_repository",
                        lambda: fx_repo)

    provider = type("P", (), {
        "fetch_fx_daily": lambda self, pair, start_date=None, end_date=None:
            [(date(2026, 6, 20), 6.81)],
    })()
    monkeypatch.setattr(mod, "_build_provider", lambda: provider)

    mod.sync_fx("USDCNY")

    assert fx_repo.upserts == [(date(2026, 6, 20), "USDCNY", 6.81)]
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/jobs/test_portfolio_daily.py -v`
Expected: FAIL `ImportError: cannot import name 'portfolio_daily'`

- [ ] **Step 3: 实现 portfolio_daily.run()**

```python
# domain/market/sync/jobs/portfolio_daily.py
"""
Portfolio Daily Sync
===================
配置组合篮子每日同步（供 cron 调用）。

  - 12 标的 → stock_ohlcv（首拉 full / 增量 incremental）
  - USDCNY → fx_rate（基于表内最大日期增量）

crontab 示例（工作日 16:30 收盘后）:
  30 16 * * 1-5 cd /path/backend && .venv/bin/python -m src.domain.market.sync.jobs.portfolio_daily >> logs/portfolio_sync.log 2>&1
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from conf import app_config
from src.domain.market.sync import ProgressTracker, SyncService
from src.domain.market.sync.providers.akshare_provider import AkshareProvider
from src.domain.market.sync.sync_service import SyncConfig
from src.infra.database.market.fx_rate import create_fx_rate_repository

PROVIDER_NAME = "akshare"


def _build_provider():
    return AkshareProvider()


def _build_tracker():
    return ProgressTracker()


def _build_service(provider, tracker):
    import os
    from src.domain.market.sync.jobs.daily import _get_dsn
    return SyncService(provider, tracker, SyncConfig(db_dsn=_get_dsn()))


def _load_universe_bars():
    return app_config.portfolio_universe.bars


def run() -> None:
    provider = _build_provider()
    tracker = _build_tracker()
    service = _build_service(provider, tracker)

    for item in _load_universe_bars():
        has = tracker.get_last_sync(PROVIDER_NAME, item.symbol, "1d") is not None
        mode = "incremental" if has else "full"
        service.backfill(symbols=[item.symbol], interval="1d", mode=mode)

    sync_fx("USDCNY")


def sync_fx(pair: str = "USDCNY") -> None:
    provider = _build_provider()
    repo = create_fx_rate_repository()
    latest = repo.get_latest_date(pair)
    rows = provider.fetch_fx_daily(pair)   # 全量；增量判定可在 provider 内做
    for d, rate in rows:
        if latest and d <= latest:
            continue
        repo.upsert(d, pair, rate)


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/jobs/test_portfolio_daily.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/market/sync/jobs/portfolio_daily.py tests/domain/market/sync/jobs/test_portfolio_daily.py
git commit -m "feat(sync): portfolio_daily job — 12 bars + USDCNY sync (full/incremental auto)"
```

---

## Task 9: 端到端验证 + 部署文档

**Files:**
- Modify: `docs/superpowers/specs/2026-06-21-etf-portfolio-data-sync-design.md`（在末尾加「部署」小节，或新增 `docs/deploy/portfolio-sync.md`）— 这里加到 spec 末尾

- [ ] **Step 1: 跑全量测试**

Run: `cd backend && .venv/bin/python -m pytest tests/conf/test_portfolio_universe_config.py tests/infra/database/market/test_fx_rate.py tests/domain/market/sync/providers/test_akshare_provider.py tests/domain/market/sync/jobs/test_portfolio_daily.py -v`
Expected: 全部 PASS

- [ ] **Step 2: 联网端到端验证（拉 1 个 A 股 + 1 个美股 + 汇率，确认真实入库）**

```bash
cd backend && .venv/bin/python - <<'PY'
from src.domain.market.sync.providers.akshare_provider import AkshareProvider
p = AkshareProvider()
print("A股ETF sh510300 条数:", len(p.fetch_daily("sh510300")))
print("美股 VOO 条数:", len(p.fetch_daily("VOO")))
print("USDCNY 汇率:", p.fetch_fx_daily("USDCNY")[-3:])
PY
```
Expected: 三个都有非空返回，不抛异常。

- [ ] **Step 3: 验证回测可读新标的（无需改 backtest_router）**

```bash
cd backend && .venv/bin/python - <<'PY'
import psycopg2
from src.infra.database.sql_engine.dsn import get_dsn
conn = psycopg2.connect(get_dsn())
with conn.cursor() as cur:
    cur.execute("SELECT symbol, COUNT(*) FROM stock_ohlcv WHERE symbol IN ('VOO','sh510300') GROUP BY symbol")
    print(cur.fetchall())
conn.close()
PY
```
（此步依赖 Step 2 的端到端跑过 `portfolio_daily.run()`；若只跑了 provider 验证，可手动 insert 一条或跳过，记录原因。）

- [ ] **Step 4: 在 spec 末尾加部署小节**

在 `docs/superpowers/specs/2026-06-21-etf-portfolio-data-sync-design.md` 末尾追加：

```markdown

---

## 九、部署

crontab（工作日 16:30 收盘后增量同步）:
```
30 16 * * 1-5 cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m src.domain.market.sync.jobs.portfolio_daily >> logs/portfolio_sync.log 2>&1
```

首次部署需手动跑一次全量（`portfolio_daily.run()` 内部对无 last_sync 的标的自动走 full，无需额外参数）。

回测新标的无需改动：`POST /api/v1/backtest/run` 的 `symbol` 传 `VOO` 或 `sh510300` 即可，`backtest_router` 已从 `stock_ohlcv` 读。
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-06-21-etf-portfolio-data-sync-design.md
git commit -m "docs: add P1 deployment section (crontab + backtest usage)"
```

---

## Self-Review

**1. Spec coverage:**
- §2.1 扩展 sync / 放弃 market/providers → Task 3-8 全在 sync 体系 ✓
- §2.2 复用 stock_ohlcv → Task 8 backfill 写入；Task 9 验证读取 ✓
- §2.3 fx_rate 走 SQLModel → Task 2 ✓
- §3.1 AkshareProvider 四方法 + symbol 规范化 → Task 3/4/5/6/7 ✓
- §3.2 FxRate entity + repository + 工厂 → Task 2 ✓
- §3.3 portfolio_daily（首拉 full/增量 incremental）→ Task 8 ✓（修正了 spec 的冷启动 bug）
- §3.4 config portfolio_universe → Task 1 ✓
- §4 数据流 → Task 8 run() ✓
- §5 错误处理（空返回/格式异常）→ fetch 方法 except + 列名防御 ✓
- §6 测试 → 每 Task TDD ✓

**2. Placeholder scan:** 无 TBD/TODO；每步含实际代码 ✓

**3. Type consistency:**
- `OHLCVBar` 字段（symbol/trade_time/open_/close_/high_/low_/volume/amount/interval/market/provider）跨 Task 一致 ✓
- `FxRateRepository.upsert(date_, pair, rate, source)` / `get_latest_date(pair)` 跨 Task 2/8 一致 ✓
- `AkshareProvider.fetch_fx_daily(pair)` 返回 `[(date, rate)]`，Task 6 与 Task 8 `sync_fx` 消费一致 ✓
- `PortfolioUniverseBarConfig` 字段（symbol/market/ccy/name/asset）跨 Task 1/7/8 一致 ✓

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-21-etf-portfolio-data-sync.md`.
