# 时光机 v3「拟真考核模式」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 /replay 新增 `exam` 拟真考核模式:盲盒开局(隐藏日期)、8 段盘中推进(合成分时)、服务端权威撮合(市价滑点/限价触发)、强制写理由、揭晓评分入榜、分红送转落账;`free` 模式行为完全不变。

**Architecture:** 纯函数域层(`backend/src/domain/replay/`:synthetic/engine/eras/scoring)+ 撮合后移服务端(handler 内单事务推进+撮合,信息门=响应只含截至当前段的行情)+ 前端 store 双分支(free=现状客户端权威;exam=服务端权威,客户端只渲染)。spec 见 `docs/superpowers/specs/2026-09-29-time-machine-v3-exam-mode-design.md`。

**Tech Stack:** FastAPI + SQLModel + psycopg2(后端既有);zustand v5 + vitest + lightweight-charts(前端既有);无新依赖。

## Global Constraints

- DB symbol 一律小写带市场前缀(sh600519/sz000300),新代码入参先 `.lower()` 归一(spec §4.4)。
- `free` 模式现有行为与端点契约不变;`GET /replay/advance?days=N` 语义保留给 free(spec §2)。
- exam 会话中 `PUT /sessions/{id}/state` 一律拒绝(服务端权威);free 会话照旧。
- UI 脱敏挡君子不挡 F12;as-of 行情/view 响应允许携带真实日期,仅会话**元数据端点**(list/get)脱敏(spec §3.1/§6)。
- 评分 = 超额收益分(80)+换手纪律分(20),其余指标只披露(spec §3.5)。
- 后端测试:本地 PG 集成测试(`python -m pytest tests/... -v`,cwd=backend);域层纯函数测试不碰 DB。
- 前端测试:`npm test`(vitest run,cwd=frontend/apps/web)。
- 提交信息用中文、`feat(replay):`/`test(replay):`/`fix(replay):` 前缀,每任务一提交。
- 前端 selector 遵守 zustand v5 稳定引用约定(v1 坑:返回新数组会无限重渲染,用模块级 NO_* 常量兜底)。

## 文件地图

**后端新建**
- `backend/src/domain/replay/__init__.py` — 空包标记
- `backend/src/domain/replay/synthetic.py` — 日OHLC→8段合成路径(确定性)
- `backend/src/domain/replay/engine.py` — fill.ts 规则移植 + 段级撮合 + 挂单簿 + 分红落账
- `backend/src/domain/replay/eras.py` — 基准指数→牛顶/熊底/震荡三池
- `backend/src/domain/replay/scoring.py` — 揭晓评分

**后端修改**
- `backend/src/infra/database/replay/models.py` — ReplaySession.mode / ReplayTrade.order_type
- `backend/src/infra/database/replay/repository.py` — ensure_replay_columns()
- `backend/main.py` — lifespan 调 ensure_replay_columns
- `backend/src/api/handler/replay_handler.py` — exam 全部分支(create/masking/advance/orders/pool/view/reveal/leaderboard)
- `backend/src/api/router/replay_router.py` — 新端点路由 + advance step 参数

**后端测试**
- `backend/tests/domain/test_replay_synthetic.py` / `test_replay_engine.py` / `test_replay_eras.py` / `test_replay_scoring.py`
- `backend/tests/api/test_replay_exam.py` — exam 集成测试(新文件,不改旧 test_replay_router.py)

**前端修改**(均在 `frontend/apps/web/src/pages/replay/`)
- `types.ts` / `api.ts` — 类型与请求层扩展
- `store.ts` — exam 分支(服务端权威)+ placeOrder 签名扩展
- `BlindMask.tsx`(新) — useDayLabel/useBlind 脱敏
- `IntradayStrip.tsx`(新) — 当日 8 段分时迷你图(纯 SVG)
- `EventCard.tsx`(新) — 今日事件/挂单卡
- `OrderTicket.tsx` — 市价/限价 + 理由必填(exam)
- `PlayControls.tsx` — 段级推进/快进(exam)
- `SessionHome.tsx` — 模式选择 + 拟真榜
- `ReviewView.tsx` — 评分卡
- `ReplayKlineChart.tsx` — labelFor 轴脱敏 prop
- `__tests__/store.test.ts` — exam 分支用例(扩展)

---

### Task 1: 数据模型与迁移(mode / order_type 列)

**Files:**
- Modify: `backend/src/infra/database/replay/models.py`
- Modify: `backend/src/infra/database/replay/repository.py`
- Modify: `backend/main.py`
- Test: `backend/tests/api/test_replay_exam.py`(新建)

**Interfaces:**
- Consumes: 无(首任务)
- Produces: `ReplaySession.mode: str`(default `"free"`);`ReplayTrade.order_type: str`(default `"market"`);`ensure_replay_columns() -> None`(幂等,main 启动调用)

- [ ] **Step 1: 写失败测试(列存在 + 默认值)**

新建 `backend/tests/api/test_replay_exam.py`:

```python
"""时光机 v3 拟真考核模式(exam)集成测试。

依赖本地 Postgres(同 test_replay_router.py)。只跑本文件:
  python -m pytest tests/api/test_replay_exam.py -v
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import create_app

    return TestClient(create_app())


@pytest.fixture
def db_conn():
    from src.infra.database.sql_engine.dsn import get_dsn
    import psycopg2
    conn = psycopg2.connect(get_dsn())
    yield conn
    conn.close()


class TestExamMigration:
    def test_mode_and_order_type_columns_exist(self, client, db_conn):
        with client:  # 触发 lifespan → ensure_replay_columns
            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name, column_default FROM "
                    "information_schema.columns "
                    "WHERE table_name = 'replay_session' "
                    "AND column_name = 'mode'"
                )
                row = cur.fetchone()
                assert row is not None, "replay_session.mode 列不存在"
                assert "'free'" in (row[1] or "")
                cur.execute(
                    "SELECT column_name, column_default FROM "
                    "information_schema.columns "
                    "WHERE table_name = 'replay_trade' "
                    "AND column_name = 'order_type'"
                )
                row = cur.fetchone()
                assert row is not None, "replay_trade.order_type 列不存在"
                assert "'market'" in (row[1] or "")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/api/test_replay_exam.py -v`
Expected: FAIL — mode 列不存在

- [ ] **Step 3: 模型加字段**

`backend/src/infra/database/replay/models.py` 中 `ReplaySession` 的 `benchmark_symbol` 字段行后加:

```python
    mode: str = "free"  # free=自由模式 | exam=拟真考核(v3)
```

`ReplayTrade` 的 `note` 字段行后加:

```python
    order_type: str = "market"  # market=市价 | limit=限价(v3 exam 撮合来源)
```

- [ ] **Step 4: repository 加 ensure_replay_columns**

`backend/src/infra/database/replay/repository.py` 末尾追加(照 macro_indicator.py 先例):

```python
def ensure_replay_columns() -> None:
    """v3: 给已存在的 replay 表补新列(无 Alembic 兜底,幂等)。

    SQLModel.metadata.create_all 不会给已存在的表加新列,故用
    ALTER TABLE ADD COLUMN IF NOT EXISTS,app 启动时调用。
    """
    from sqlalchemy import text

    db = _get_db_connection()
    with db.session_scope() as s:
        s.exec(text(
            "ALTER TABLE replay_session ADD COLUMN IF NOT EXISTS "
            "mode VARCHAR DEFAULT 'free'"
        ))
        s.exec(text(
            "ALTER TABLE replay_trade ADD COLUMN IF NOT EXISTS "
            "order_type VARCHAR DEFAULT 'market'"
        ))
```

- [ ] **Step 5: main.py lifespan 接线**

`backend/main.py` 中 replay models import 块(`from src.infra.database.replay.models import ...`,约 186-191 行)之后追加:

```python
        from src.infra.database.replay.repository import (
            ensure_replay_columns,
        )
        try:
            ensure_replay_columns()
        except Exception as e:  # noqa: BLE001
            print(f"[replay] ensure v3 columns: {e}")
```

- [ ] **Step 6: 运行测试通过**

Run: `cd backend && python -m pytest tests/api/test_replay_exam.py -v`
Expected: PASS(1 passed)

- [ ] **Step 7: 旧套件回归**

Run: `cd backend && python -m pytest tests/api/test_replay_router.py -v`
Expected: PASS(全部)

- [ ] **Step 8: Commit**

```bash
git add backend/src/infra/database/replay/ backend/main.py backend/tests/api/test_replay_exam.py
git commit -m "feat(replay): v3迁移——replay_session.mode/replay_trade.order_type两列+启动幂等补列"
```

---

### Task 2: synthetic.py — 日OHLC 合成 8 段盘中路径

**Files:**
- Create: `backend/src/domain/replay/__init__.py`(空文件)
- Create: `backend/src/domain/replay/synthetic.py`
- Test: `backend/tests/domain/test_replay_synthetic.py`

**Interfaces:**
- Produces:
  - `SEG_COUNT = 8`
  - `segments(symbol: str, day: str, bar: dict, seed: str = "") -> list[dict]`
  - 段 dict:`{"open": float, "high": float, "low": float, "close": float}`(2位舍入)
  - 性质:seg0.open==bar.open;末段 close==bar.close;seg[k+1].open==seg[k].close;min(全段low)==bar.low;max(全段high)==bar.high;全程∈[bar.low,bar.high];同参确定性;坏数据退化为 8 段平坦收盘价。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/domain/test_replay_synthetic.py`:

```python
"""synthetic.segments 纯函数测试 — 不碰 DB。"""

import pytest

from src.domain.replay.synthetic import SEG_COUNT, segments

BAR = {"open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5,
       "volume": 1000, "amount": 10000.0}


class TestSegments:
    def test_shape_and_continuity(self):
        segs = segments("sh600519", "2020-03-13", BAR, seed="42")
        assert len(segs) == SEG_COUNT
        assert segs[0]["open"] == pytest.approx(BAR["open"], abs=0.01)
        assert segs[-1]["close"] == pytest.approx(BAR["close"], abs=0.01)
        for k in range(SEG_COUNT - 1):
            assert segs[k + 1]["open"] == pytest.approx(segs[k]["close"])
        for s in segs:
            assert s["low"] <= s["open"] <= s["high"]
            assert s["low"] <= s["close"] <= s["high"]

    def test_bounded_and_reaches_extremes(self):
        for seed in ("a", "b", "c", "d"):
            segs = segments("sh600519", "2020-03-13", BAR, seed=seed)
            assert min(s["low"] for s in segs) == pytest.approx(BAR["low"], abs=0.01)
            assert max(s["high"] for s in segs) == pytest.approx(BAR["high"], abs=0.01)
            for s in segs:
                assert BAR["low"] - 0.01 <= s["low"]
                assert s["high"] <= BAR["high"] + 0.01

    def test_deterministic(self):
        a = segments("sz000001", "2018-01-02", BAR, seed="7")
        b = segments("sz000001", "2018-01-02", BAR, seed="7")
        c = segments("sz000001", "2018-01-03", BAR, seed="7")
        assert a == b
        assert a != c  # 不同日期路径应不同(连续价格抖动,概率上必然)

    def test_one_price_day_degrades_flat(self):
        bar = {"open": 5.0, "high": 5.0, "low": 5.0, "close": 5.0,
               "volume": 1, "amount": 5.0}
        segs = segments("sh600519", "2020-03-13", bar, seed="1")
        for s in segs:
            assert s == {"open": 5.0, "high": 5.0, "low": 5.0, "close": 5.0}

    @pytest.mark.parametrize("bad", [
        {"open": None, "high": 11, "low": 9, "close": 10},
        {"open": 10, "high": 9, "low": 9.5, "close": 10},   # h < l
        {"open": 12, "high": 11, "low": 9.5, "close": 10},  # open 越界
        {"open": 10, "high": 11, "low": 9.5},               # 缺 close
    ])
    def test_bad_bar_flat_close(self, bad):
        segs = segments("sh600519", "2020-03-13", bad, seed="1")
        c = float(bad.get("close") or 0)
        assert segs == [{"open": c, "high": c, "low": c, "close": c}
                        for _ in range(SEG_COUNT)]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/domain/test_replay_synthetic.py -v`
Expected: FAIL — `ModuleNotFoundError: src.domain.replay`

- [ ] **Step 3: 实现**

`backend/src/domain/replay/synthetic.py`:

```python
"""日 OHLC → 8 段盘中合成路径(v3 拟真考核)。

确定性:random.Random(str) 对字符串 seed 走 sha512 派生,跨进程稳定,
同一 (seed, symbol, day) 永远同一路径,服务端可随时重算无需落库。
"""

from __future__ import annotations

import math
import random

SEG_COUNT = 8


def _round2(v: float) -> float:
    return round(v * 100) / 100


def _flat(c: float) -> list[dict]:
    v = _round2(c)
    return [{"open": v, "high": v, "low": v, "close": v}
            for _ in range(SEG_COUNT)]


def segments(symbol: str, day: str, bar: dict, seed: str = "") -> list[dict]:
    """日 bar → SEG_COUNT 段连续 OHLC。

    性质(见测试):端点对齐 open/close、路径必经 high/low、全程有界、
    段间连续(seg[k+1].open == seg[k].close)。坏数据退化为 8 段平坦收盘价。
    """
    try:
        o = float(bar["open"]); h = float(bar["high"])
        l = float(bar["low"]); c = float(bar["close"])
    except (KeyError, TypeError, ValueError):
        return _flat(0.0)
    if not all(map(math.isfinite, (o, h, l, c))):
        return _flat(c)
    if l > h or o < l or o > h or c < l or c > h:
        return _flat(c)
    if h == l:  # 一字板
        return _flat(c)

    rng = random.Random(f"{seed}:{symbol}:{day}")
    hi_i = rng.randrange(1, SEG_COUNT)
    lo_i = rng.randrange(1, SEG_COUNT)
    while lo_i == hi_i:
        lo_i = rng.randrange(1, SEG_COUNT)

    pts = [o]
    for k in range(1, SEG_COUNT):
        if k == hi_i:
            pts.append(h)
        elif k == lo_i:
            pts.append(l)
        else:
            # 朝收盘价方向抖动插值,clamp 在 [l, h]
            drift = pts[-1] + (c - pts[-1]) * rng.random() * 0.6
            pts.append(min(h, max(l, drift)))
    pts.append(c)

    segs: list[dict] = []
    wick = (h - l) * 0.05
    for k in range(SEG_COUNT):
        so, sc = pts[k], pts[k + 1]
        sh = min(h, max(l, max(so, sc) + wick * rng.random()))
        sl = min(h, max(l, min(so, sc) - wick * rng.random()))
        segs.append({"open": _round2(so), "high": _round2(sh),
                     "low": _round2(sl), "close": _round2(sc)})
    return segs
```

- [ ] **Step 4: 运行测试通过**

Run: `cd backend && python -m pytest tests/domain/test_replay_synthetic.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/replay/ backend/tests/domain/test_replay_synthetic.py
git commit -m "feat(replay): 合成分时synthetic——日OHLC确定性8段路径,必经高低点,坏数据退化"
```

---

### Task 3: engine.py 基础 — fill.ts 规则移植 + 滑点 + 红利税档

**Files:**
- Create: `backend/src/domain/replay/engine.py`
- Test: `backend/tests/domain/test_replay_engine.py`

**Interfaces:**
- Produces:
  - `round2(v) -> float`;`price_limit_ratio(symbol, name=None) -> float`;`limit_prices(prev_close, ratio) -> tuple[float, float]`;`commission(amount) -> float`;`stamp_tax(amount, day) -> float`;`slippage(seed) -> float`(0~0.0015,方向调用方施加:买加卖减);`dividend_tax_rate(buy_date, ex_date) -> float`
  - `try_fill_market(cash, positions, order, seg_price, prev_close, name, day) -> dict`;`order = {"symbol", "side", "shares", "note", "order_type"}`,`seg_price` 为**已含滑点**的段价
  - FillResult:成功 `{"ok": True, "cash", "positions", "trade"}`;失败 `{"ok": False, "error": str}`;trade dict 与 replay_trade 列一致

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/domain/test_replay_engine.py`:

```python
"""engine 纯函数测试 — fill.ts 语义 1:1 移植 + v3 新增,不碰 DB。"""

import pytest

from src.domain.replay.engine import (
    commission, dividend_tax_rate, limit_prices, price_limit_ratio,
    slippage, stamp_tax, try_fill_market,
)


class TestRules:
    def test_limit_ratio_by_board(self):
        assert price_limit_ratio("sh600519") == 0.10
        assert price_limit_ratio("sz300750") == 0.20
        assert price_limit_ratio("sz301001") == 0.20
        assert price_limit_ratio("sh688111") == 0.20
        assert price_limit_ratio("bj830799") == 0.30
        assert price_limit_ratio("sh600519", name="ST某某") == 0.05

    def test_limit_prices_round2(self):
        assert limit_prices(10.0, 0.1) == (11.0, 9.0)
        assert limit_prices(9.99, 0.1) == (10.99, 8.99)

    def test_fees(self):
        assert commission(100000) == 25.0
        assert commission(1000) == 5.0  # 最低 5 元
        assert stamp_tax(100000, "2023-08-28") == 50.0
        assert stamp_tax(100000, "2023-08-27") == 100.0  # 换挡前千1

    def test_slippage_deterministic_bounded(self):
        a = slippage("s1:sh600519:2020-03-13:3:buy")
        b = slippage("s1:sh600519:2020-03-13:3:buy")
        assert a == b
        assert 0 <= a <= 0.0015

    def test_dividend_tax_tiers(self):
        assert dividend_tax_rate("2019-01-01", "2020-06-01") == 0.0   # >1年
        assert dividend_tax_rate("2020-01-01", "2020-06-01") == 0.1   # 1月~1年
        assert dividend_tax_rate("2020-05-01", "2020-06-01") == 0.2   # <1月


class TestTryFillMarket:
    ORDER = {"symbol": "sh600519", "side": "buy", "shares": 100,
             "note": "测试", "order_type": "market"}

    def test_buy_ok_with_slippage(self):
        # 调用方已把滑点并入段价:10.0 * (1+0.001)
        r = try_fill_market(
            cash=1e6, positions=[], order=self.ORDER,
            seg_price=10.0 * 1.001, prev_close=10.0,
            name="贵州茅台", day="2020-03-13")
        assert r["ok"]
        price = r["trade"]["price"]
        assert price == pytest.approx(10.0 * 1.001, abs=0.01)
        expect_fee = max(5.0, round(price * 100 * 0.00025 * 100) / 100)
        assert r["cash"] == pytest.approx(1e6 - price * 100 - expect_fee,
                                          abs=0.01)
        assert r["positions"][0]["shares"] == 100
        assert r["positions"][0]["buy_date"] == "2020-03-13"

    def test_buy_rejects_limit_up(self):
        r = try_fill_market(1e6, [], self.ORDER, seg_price=11.0,
                            prev_close=10.0, name=None, day="2020-03-13")
        assert not r["ok"] and "涨停" in r["error"]

    def test_buy_lot_and_cash(self):
        assert not try_fill_market(1e6, [], {**self.ORDER, "shares": 150},
                                   10.0, 10.0, None, "2020-03-13")["ok"]
        assert not try_fill_market(1000.0, [], self.ORDER, 10.0, 10.0,
                                   None, "2020-03-13")["ok"]

    def test_sell_odd_lot_tax(self):
        pos = [{"symbol": "sh600519", "shares": 150, "cost_price": 9.0,
                "buy_date": "2020-03-12"}]
        order = {"symbol": "sh600519", "side": "sell", "shares": 50,
                 "note": None, "order_type": "market"}
        r = try_fill_market(0.0, pos, order, seg_price=10.0,
                            prev_close=10.0, name=None, day="2020-03-13")
        assert r["ok"]  # 卖出允许零股
        assert r["positions"][0]["shares"] == 100
        # 现金 = 10*50 - 佣金5 - 印花税 500*0.0005=0.25
        assert r["cash"] == pytest.approx(500 - 5 - 0.25, abs=0.01)

    def test_sell_rejects_t1_same_day(self):
        pos = [{"symbol": "sh600519", "shares": 100, "cost_price": 9.0,
                "buy_date": "2020-03-13"}]
        order = {"symbol": "sh600519", "side": "sell", "shares": 100,
                 "note": None, "order_type": "market"}
        r = try_fill_market(0.0, pos, order, 10.0, 10.0, None,
                            "2020-03-13")
        assert not r["ok"] and "T+1" in r["error"]

    def test_sell_rejects_limit_down(self):
        pos = [{"symbol": "sh600519", "shares": 100, "cost_price": 9.0,
                "buy_date": "2020-03-12"}]
        order = {"symbol": "sh600519", "side": "sell", "shares": 100,
                 "note": None, "order_type": "market"}
        r = try_fill_market(0.0, pos, order, seg_price=8.9, prev_close=10.0,
                            name=None, day="2020-03-13")
        assert not r["ok"] and "跌停" in r["error"]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/domain/test_replay_engine.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 实现 engine.py(基础部分)**

新建 `backend/src/domain/replay/engine.py`:

```python
"""v3 拟真考核撮合引擎 — 前端 fill.ts 规则 1:1 移植 + 段级撮合扩展。

本模块只做纯计算,不碰 DB;positions 元素形状同前端 Position:
{symbol, shares, cost_price, buy_date}。
"""

from __future__ import annotations

import random
from datetime import date


def round2(v: float) -> float:
    return round(v * 100) / 100


def price_limit_ratio(symbol: str, name: str | None = None) -> float:
    """涨跌停幅度:ST 5% / 创业·科创 20% / 北交 30% / 主板 10%。"""
    if name and "ST" in name.upper():
        return 0.05
    code = symbol.lower()
    for p in ("sh", "sz", "bj"):
        if code.startswith(p):
            code = code[len(p):]
            break
    if code.startswith(("300", "301", "688", "689")):
        return 0.2
    if code.startswith(("8", "4", "92")):
        return 0.3
    return 0.1


def limit_prices(prev_close: float, ratio: float) -> tuple[float, float]:
    return (round2(prev_close * (1 + ratio)),
            round2(prev_close * (1 - ratio)))


def commission(amount: float) -> float:
    return max(5.0, round2(amount * 0.00025))


def stamp_tax(amount: float, day: str) -> float:
    rate = 0.0005 if day >= "2023-08-28" else 0.001
    return round2(amount * rate)


def slippage(seed: str) -> float:
    """确定性滑点 0~0.15%,方向由调用方施加(买加卖减)。"""
    return random.Random(f"slip:{seed}").random() * 0.0015


def dividend_tax_rate(buy_date: str, ex_date: str) -> float:
    """红利税持有期税档:>1年 0 / 1月~1年 10% / <1月 20%(同论点体系)。"""
    b = date.fromisoformat(buy_date)
    e = date.fromisoformat(ex_date)
    days = (e - b).days
    if days > 365:
        return 0.0
    if days >= 30:
        return 0.1
    return 0.2


def try_fill_market(
    cash: float,
    positions: list[dict],
    order: dict,
    seg_price: float,
    prev_close: float,
    name: str | None,
    day: str,
) -> dict:
    """市价单按段价成交(调用方已把滑点并入 seg_price)。

    规则:整手买入/零股卖出、涨跌停区间校验(段价触及即拒)、
    T+1、资金校验、费税。返回 FillResult。
    """
    shares = order.get("shares")
    if not isinstance(shares, int) or shares <= 0:
        return {"ok": False, "error": "股数须为正整数"}
    side = order["side"]
    if side == "buy" and shares % 100 != 0:
        return {"ok": False, "error": "买入股数须为100的整数倍"}
    ratio = price_limit_ratio(order["symbol"], name)
    up, down = limit_prices(prev_close, ratio)
    price = round2(seg_price)
    amount = round2(price * shares)
    if side == "buy":
        if price >= up:
            return {"ok": False, "error": "涨停，无法买入"}
        fee = commission(amount)
        cost = round2(amount + fee)
        if cost > cash:
            return {"ok": False, "error": "资金不足"}
        positions2 = [dict(p) for p in positions]
        i = next((k for k, p in enumerate(positions2)
                  if p["symbol"] == order["symbol"]), -1)
        if i >= 0:
            p = positions2[i]
            total = p["shares"] + shares
            p["cost_price"] = round2(
                (p["cost_price"] * p["shares"] + price * shares) / total)
            p["shares"] = total
        else:
            positions2.append({
                "symbol": order["symbol"], "shares": shares,
                "cost_price": price, "buy_date": day,
            })
        return {"ok": True, "cash": round2(cash - cost),
                "positions": positions2,
                "trade": _trade(day, order, price, shares, fee, 0.0)}
    # sell
    if price <= down:
        return {"ok": False, "error": "跌停，无法卖出"}
    i = next((k for k, p in enumerate(positions)
              if p["symbol"] == order["symbol"]), -1)
    if i < 0:
        return {"ok": False, "error": "无持仓"}
    p = positions[i]
    if p["shares"] < shares:
        return {"ok": False, "error": "持仓不足"}
    if p["buy_date"] >= day:
        return {"ok": False, "error": "T+1：今日买入明日才可卖出"}
    fee = commission(amount)
    tax = stamp_tax(amount, day)
    positions2 = [dict(q) for q in positions]
    if positions2[i]["shares"] == shares:
        positions2.pop(i)
    else:
        positions2[i]["shares"] -= shares
    return {"ok": True, "cash": round2(cash + amount - fee - tax),
            "positions": positions2,
            "trade": _trade(day, order, price, shares, fee, tax)}


def _trade(day, order, price, shares, fee, tax) -> dict:
    return {"trade_date": day, "symbol": order["symbol"],
            "side": order["side"], "price": price, "shares": shares,
            "fee": fee, "tax": tax, "note": order.get("note"),
            "order_type": order.get("order_type", "market")}
```

- [ ] **Step 4: 运行测试通过**

Run: `cd backend && python -m pytest tests/domain/test_replay_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/replay/engine.py backend/tests/domain/test_replay_engine.py
git commit -m "feat(replay): 撮合引擎基础——fill.ts规则移植+确定性滑点+红利税三档"
```

---

### Task 4: engine.py 挂单簿 — 限价冻结/逐段触发/收盘撤销

**Files:**
- Modify: `backend/src/domain/replay/engine.py`(追加)
- Test: `backend/tests/domain/test_replay_engine.py`(追加)

**Interfaces:**
- Consumes: Task 3 的 `try_fill_market/limit_prices/price_limit_ratio/round2`
- Produces(直接改传入 state dict,handler 持事务;测试用 deepcopy 隔离):
  - `freeze_amount(limit_price: float, shares: int) -> float`
  - `sellable_shares(state: dict, symbol: str, day: str) -> int`
  - `try_place_limit(state: dict, order: dict, prev_close: float, name: str | None, day: str) -> dict` — order 须含 `limit_price`;成功 `{"ok": True, "order": 挂单dict}` 并已入 `state["pending_orders"]`/加冻结
  - `check_pending(state, seg_by_symbol: dict[str, dict], prev_closes: dict[str, float], names: dict[str, str], day: str) -> tuple[list[dict], list[dict]]` — 当前段逐单检查;买单触发 `seg.low <= 限价`(成交价 `min(限价, seg.open)`)、卖单触发 `seg.high >= 限价`(成交价 `max(限价, seg.open)`);触发后走 try_fill_market 全套规则,拒绝即撤;返回 (trades, events)
  - `cancel_day_pending(state) -> list[dict]` — 全撤+解冻,返回事件
  - state 约定键:`cash/frozen_cash/positions/pending_orders`;挂单 dict:`{id, side, symbol, shares, limit_price, note, placed_day, frozen}`

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/domain/test_replay_engine.py` 末尾追加:

```python
import copy

from src.domain.replay.engine import (
    cancel_day_pending, check_pending, freeze_amount, sellable_shares,
    try_place_limit,
)


def _state(cash=1e6, positions=None, pending=None, frozen=0.0):
    return {"cash": cash, "frozen_cash": frozen,
            "positions": positions or [], "pending_orders": pending or []}


class TestPlaceLimit:
    def test_buy_limit_freezes(self):
        st = _state()
        r = try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                                 "shares": 100, "limit_price": 10.0,
                                 "note": "x"}, 10.0, None, "2020-03-13")
        assert r["ok"]
        assert st["frozen_cash"] == freeze_amount(10.0, 100)
        assert len(st["pending_orders"]) == 1
        assert st["pending_orders"][0]["frozen"] == st["frozen_cash"]

    def test_buy_limit_out_of_range(self):
        st = _state()
        r = try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                                 "shares": 100, "limit_price": 12.0,
                                 "note": "x"}, 10.0, None, "2020-03-13")
        assert not r["ok"] and "区间" in r["error"]
        assert st["frozen_cash"] == 0.0

    def test_buy_limit_insufficient(self):
        st = _state(cash=500.0)  # 冻结需 ~1002
        r = try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                                 "shares": 100, "limit_price": 10.0,
                                 "note": "x"}, 10.0, None, "2020-03-13")
        assert not r["ok"] and "资金不足" in r["error"]

    def test_sell_limit_t1_and_frozen_shares(self):
        pos = [{"symbol": "sh600519", "shares": 200, "cost_price": 9.0,
                "buy_date": "2020-03-13"}]
        st = _state(positions=pos)
        # T+1:今日买入
        r = try_place_limit(st, {"symbol": "sh600519", "side": "sell",
                                 "shares": 100, "limit_price": 10.5,
                                 "note": "x"}, 10.0, None, "2020-03-13")
        assert not r["ok"] and "T+1" in r["error"]
        # 昨日买入,挂 100 股后可卖余量=100
        pos[0]["buy_date"] = "2020-03-12"
        assert try_place_limit(_state(positions=copy.deepcopy(pos)),
                               {"symbol": "sh600519", "side": "sell",
                                "shares": 100, "limit_price": 10.5,
                                "note": "x"}, 10.0, None,
                               "2020-03-13")["ok"]
        st2 = _state(positions=copy.deepcopy(pos))
        try_place_limit(st2, {"symbol": "sh600519", "side": "sell",
                              "shares": 100, "limit_price": 10.5,
                              "note": "x"}, 10.0, None, "2020-03-13")
        assert sellable_shares(st2, "sh600519", "2020-03-13") == 100
        r = try_place_limit(st2, {"symbol": "sh600519", "side": "sell",
                                  "shares": 200, "limit_price": 10.5,
                                  "note": "x"}, 10.0, None, "2020-03-13")
        assert not r["ok"] and "持仓不足" in r["error"]


class TestCheckPending:
    def _seg(self, o, h, l, c):
        return {"open": o, "high": h, "low": l, "close": c}

    def test_buy_limit_triggers_on_cross(self):
        st = _state()
        try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                             "shares": 100, "limit_price": 10.0,
                             "note": "x"}, 10.0, None, "2020-03-13")
        trades, events = check_pending(
            st, {"sh600519": self._seg(10.2, 10.4, 9.8, 9.9)},
            {"sh600519": 10.0}, {}, "2020-03-13")
        assert len(trades) == 1
        # 成交价 = min(限价, 段开盘) = 10.0
        assert trades[0]["price"] == 10.0
        assert trades[0]["order_type"] == "limit"
        assert st["pending_orders"] == []
        assert st["frozen_cash"] == 0.0
        assert st["positions"][0]["shares"] == 100
        assert st["cash"] == pytest.approx(1e6 - 10.0 * 100 - 25.0, abs=0.01)

    def test_sell_limit_triggers_better_open(self):
        pos = [{"symbol": "sh600519", "shares": 100, "cost_price": 9.0,
                "buy_date": "2020-03-12"}]
        st = _state(cash=0.0, positions=pos)
        try_place_limit(st, {"symbol": "sh600519", "side": "sell",
                             "shares": 100, "limit_price": 10.5,
                             "note": "x"}, 10.0, None, "2020-03-13")
        # 段开盘 10.8 高于限价 → 成交价取开盘 10.8(更优)
        trades, _ = check_pending(
            st, {"sh600519": self._seg(10.8, 11.0, 10.6, 10.7)},
            {"sh600519": 10.0}, {}, "2020-03-13")
        assert trades[0]["price"] == 10.8
        assert st["positions"] == []

    def test_no_trigger_when_far(self):
        st = _state()
        try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                             "shares": 100, "limit_price": 9.0,
                             "note": "x"}, 10.0, None, "2020-03-13")
        trades, events = check_pending(
            st, {"sh600519": self._seg(10.0, 10.2, 9.9, 10.1)},
            {"sh600519": 10.0}, {}, "2020-03-13")
        assert trades == [] and events == []
        assert len(st["pending_orders"]) == 1

    def test_suspended_symbol_skipped(self):
        st = _state()
        try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                             "shares": 100, "limit_price": 10.0,
                             "note": "x"}, 10.0, None, "2020-03-13")
        trades, _ = check_pending(st, {}, {"sh600519": 10.0}, {},
                                  "2020-03-13")
        assert trades == []
        assert len(st["pending_orders"]) == 1  # 停牌悬着


class TestCancelDayPending:
    def test_cancel_unfreezes(self):
        st = _state()
        try_place_limit(st, {"symbol": "sh600519", "side": "buy",
                             "shares": 100, "limit_price": 10.0,
                             "note": "x"}, 10.0, None, "2020-03-13")
        events = cancel_day_pending(st)
        assert len(events) == 1 and events[0]["type"] == "order_cancelled"
        assert st["pending_orders"] == []
        assert st["frozen_cash"] == 0.0
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/domain/test_replay_engine.py -v`
Expected: FAIL — ImportError(cancel_day_pending 等不存在)

- [ ] **Step 3: 实现(追加到 engine.py 末尾)**

```python
# ── 挂单簿(v3:限价单当日有效) ──

import uuid


def freeze_amount(limit_price: float, shares: int) -> float:
    """限价买单冻结额 = max(金额×1.002, 金额+5)。

    佣金有 5 元下限,金额<2500 时 0.2% 余量盖不住(审查修正:
    原纯 1.002 公式在小额单会让成交把 cash 打到负数,违 spec §6
    "防挂单超额占款"意图)。
    """
    amount = limit_price * shares
    return round2(max(amount * 1.002, amount + 5.0))


def sellable_shares(state: dict, symbol: str, day: str) -> int:
    """可卖股数 = 持股 − 挂单冻结卖股(挂单下单时已校验 T+1)。"""
    pos = next((p for p in state["positions"]
                if p["symbol"] == symbol), None)
    if pos is None:
        return 0
    frozen = sum(o["shares"] for o in state.get("pending_orders", [])
                 if o["symbol"] == symbol and o["side"] == "sell")
    return max(0, pos["shares"] - frozen)


def try_place_limit(state: dict, order: dict, prev_close: float,
                    name: str | None, day: str) -> dict:
    """限价单校验入挂单簿(当日有效,收盘自动撤)。"""
    shares = order.get("shares")
    if not isinstance(shares, int) or shares <= 0:
        return {"ok": False, "error": "股数须为正整数"}
    if order["side"] == "buy" and shares % 100 != 0:
        return {"ok": False, "error": "买入股数须为100的整数倍"}
    limit_price = order.get("limit_price")
    try:
        limit_price = float(limit_price)
    except (TypeError, ValueError):
        return {"ok": False, "error": "limit_price 应为正数"}
    if limit_price <= 0:
        return {"ok": False, "error": "limit_price 应为正数"}
    up, down = limit_prices(
        prev_close, price_limit_ratio(order["symbol"], name))
    if not (down <= limit_price <= up):
        return {"ok": False, "error": f"限价须在当日区间 [{down}, {up}]"}
    frozen = 0.0
    if order["side"] == "buy":
        need = freeze_amount(limit_price, shares)
        if state["cash"] - state.get("frozen_cash", 0.0) < need:
            return {"ok": False, "error": "资金不足（含挂单冻结）"}
        frozen = need
        state["frozen_cash"] = round2(
            state.get("frozen_cash", 0.0) + need)
    else:
        pos = next((p for p in state["positions"]
                    if p["symbol"] == order["symbol"]), None)
        if pos is None:
            return {"ok": False, "error": "无持仓"}
        if pos["buy_date"] >= day:
            return {"ok": False, "error": "T+1：今日买入明日才可卖出"}
        if shares > sellable_shares(state, order["symbol"], day):
            return {"ok": False, "error": "持仓不足（含挂单冻结）"}
    o = {"id": uuid.uuid4().hex[:8], "side": order["side"],
         "symbol": order["symbol"], "shares": shares,
         "limit_price": round2(limit_price), "note": order.get("note"),
         "placed_day": day, "frozen": frozen}
    state.setdefault("pending_orders", []).append(o)
    return {"ok": True, "order": o}


def check_pending(state: dict, seg_by_symbol: dict[str, dict],
                  prev_closes: dict[str, float], names: dict[str, str],
                  day: str) -> tuple[list[dict], list[dict]]:
    """当前段逐单检查触发;触发的单走 try_fill_market 全套规则,拒绝即撤。

    改 state(cash/positions/pending_orders/frozen_cash),返回 (trades, events)。
    """
    trades: list[dict] = []
    events: list[dict] = []
    for o in list(state.get("pending_orders", [])):
        seg = seg_by_symbol.get(o["symbol"])
        if seg is None:  # 停牌,挂单悬着
            continue
        hit = None
        if o["side"] == "buy" and seg["low"] <= o["limit_price"]:
            hit = min(o["limit_price"], seg["open"])
        elif o["side"] == "sell" and seg["high"] >= o["limit_price"]:
            hit = max(o["limit_price"], seg["open"])
        if hit is None:
            continue
        state["pending_orders"].remove(o)
        prev = prev_closes.get(o["symbol"], o["limit_price"])
        # 有效现金 = cash − 其余挂单冻结 + 本单冻结(审查修正:
        # 原公式漏扣其余冻结,多单同段触发会超卖资金到负)
        cash = (state["cash"] - state.get("frozen_cash", 0.0)
                + (o["frozen"] if o["side"] == "buy" else 0.0))
        r = try_fill_market(cash, state["positions"],
                            {**o, "order_type": "limit"}, hit, prev,
                            names.get(o["symbol"]), day)
        if r["ok"]:
            # 回写:r.cash 基于"cash−frozen_cash+own"口径,换算回真实 cash
            state["cash"] = round2(
                r["cash"] + state.get("frozen_cash", 0.0) - o["frozen"]
                if o["side"] == "buy" else r["cash"])
            state["positions"] = r["positions"]
            trades.append(r["trade"])
        else:  # 触发但规则拒绝(如资金被挪用)→ 撤单
            events.append({"type": "order_cancelled", "symbol": o["symbol"],
                           "msg": f"限价单触发但被拒({r['error']})，已撤销"})
        if o["side"] == "buy":
            state["frozen_cash"] = round2(
                state.get("frozen_cash", 0.0) - o["frozen"])
    return trades, events


def cancel_day_pending(state: dict) -> list[dict]:
    """日切:撤销全部挂单并解冻(冻结全部来自挂单,直接归零)。"""
    events = [{"type": "order_cancelled", "symbol": o["symbol"],
               "msg": f"限价单未触发已收盘撤销（{o['side']} "
                      f"{o['shares']}股 @ {o['limit_price']}）"}
              for o in state.get("pending_orders", [])]
    state["pending_orders"] = []
    state["frozen_cash"] = 0.0
    return events
```

- [ ] **Step 4: 运行测试通过**

Run: `cd backend && python -m pytest tests/domain/test_replay_engine.py -v`
Expected: PASS(全部)

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/replay/engine.py backend/tests/domain/test_replay_engine.py
git commit -m "feat(replay): 挂单簿——限价冻结/逐段触发/触发拒绝即撤/收盘全撤解冻"
```

---

### Task 5: engine.py 日切与分红落账

**Files:**
- Modify: `backend/src/domain/replay/engine.py`(追加)
- Test: `backend/tests/domain/test_replay_engine.py`(追加)

**Interfaces:**
- Consumes: Task 3 `dividend_tax_rate/round2`
- Produces(直接改 state):
  - `nav_value(cash, positions, close_by_symbol) -> float`
  - `day_close_nav(state, day: str, close_by_symbol) -> dict` — nav 追加 `{date, value, cash, pos}`(cash/pos 供评分披露;停牌股用调用方给的最近收盘价)
  - `apply_dividends(state, div_rows: list[dict], day: str) -> list[dict]` — div_rows:`[{symbol, div_per_share, stock_div, convert}]`;现金税后入账、送转股数×(1+送+转)/成本÷系数、送转不征税(简化);事件 `{"type": "dividend"|"split", "symbol", "msg"}`;记录 `state["dividends_received"]`

- [ ] **Step 1: 追加失败测试**

```python
from src.domain.replay.engine import (
    apply_dividends, day_close_nav, nav_value,
)


class TestDayCloseNav:
    def test_appends_point_with_disclosures(self):
        st = {"cash": 900.0, "positions": [
            {"symbol": "sh600519", "shares": 100, "cost_price": 9.0,
             "buy_date": "2020-03-12"}], "nav": []}
        closes = {"sh600519": 10.0}
        assert nav_value(st["cash"], st["positions"], closes) == 1900.0
        pt = day_close_nav(st, "2020-03-13", closes)
        assert pt == {"date": "2020-03-13", "value": 1900.0,
                      "cash": 900.0, "pos": {"sh600519": 1000.0}}
        assert st["nav"][-1] is pt


class TestApplyDividends:
    POS = lambda self, buy: [{  # noqa: E731
        "symbol": "sh600519", "shares": 100, "cost_price": 10.0,
        "buy_date": buy}]

    def test_cash_dividend_tax_tiers(self):
        for buy, rate, got in [("2019-01-01", 0.0, 100.0),
                               ("2020-01-01", 0.1, 90.0),
                               ("2020-05-15", 0.2, 80.0)]:  # 17天<1月
            st = {"cash": 0.0, "positions": self.POS(buy),
                  "dividends_received": []}
            ev = apply_dividends(
                st, [{"symbol": "sh600519", "div_per_share": 1.0,
                      "stock_div": 0, "convert": 0}], "2020-06-01")
            assert st["cash"] == got
            assert ev[0]["type"] == "dividend"
            assert st["dividends_received"][0]["tax_rate"] == rate

    def test_split_multiplies_shares(self):
        st = {"cash": 0.0, "positions": self.POS("2019-01-01"),
              "dividends_received": []}
        apply_dividends(
            st, [{"symbol": "sh600519", "div_per_share": 0,
                  "stock_div": 1.0, "convert": 0}],  # 10送10
            "2020-06-01")
        assert st["positions"][0]["shares"] == 200
        assert st["positions"][0]["cost_price"] == 5.0

    def test_no_position_no_effect(self):
        st = {"cash": 0.0, "positions": [], "dividends_received": []}
        assert apply_dividends(
            st, [{"symbol": "sh600519", "div_per_share": 1.0}], 
            "2020-06-01") == []
        assert st["cash"] == 0.0
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/domain/test_replay_engine.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 实现(追加到 engine.py 末尾)**

```python
# ── 日切与分红落账(v3) ──


def nav_value(cash: float, positions: list[dict],
              close_by_symbol: dict[str, float]) -> float:
    return round2(cash + sum(
        p["shares"] * close_by_symbol.get(p["symbol"], p["cost_price"])
        for p in positions))


def day_close_nav(state: dict, day: str,
                  close_by_symbol: dict[str, float]) -> dict:
    """日切记账:nav 追加 {date, value, cash, pos}(后两者供评分披露)。"""
    value = nav_value(state["cash"], state["positions"], close_by_symbol)
    point = {"date": day, "value": value, "cash": state["cash"],
             "pos": {p["symbol"]: round2(p["shares"] * close_by_symbol.get(
                 p["symbol"], p["cost_price"]))
                     for p in state["positions"]}}
    state.setdefault("nav", []).append(point)
    return point


def apply_dividends(state: dict, div_rows: list[dict],
                    day: str) -> list[dict]:
    """除权日落账:现金分红(持有期税后)+送转(股数×(1+送+转)、成本÷系数)。

    送转本身不征税(简化,spec §3.4)。改 state(cash/positions),返回事件。
    """
    events: list[dict] = []
    for row in div_rows:
        sym = row["symbol"]
        div = float(row.get("div_per_share") or 0)
        factor = 1 + float(row.get("stock_div") or 0) \
            + float(row.get("convert") or 0)
        for p in state.get("positions", []):
            if p["symbol"] != sym:
                continue
            if div > 0:
                tax = dividend_tax_rate(p["buy_date"], day)
                got = round2(div * p["shares"] * (1 - tax))
                state["cash"] = round2(state["cash"] + got)
                state.setdefault("dividends_received", []).append(
                    {"day": day, "symbol": sym, "cash_after_tax": got,
                     "tax_rate": tax})
                events.append({
                    "type": "dividend", "symbol": sym,
                    "msg": f"每股派 {div} 元，税后入账 {got} 元"
                           f"（税率 {tax * 100:.0f}%）"})
            if factor > 1:
                p["shares"] = int(round(p["shares"] * factor))
                p["cost_price"] = round2(p["cost_price"] / factor)
                state.setdefault("dividends_received", []).append(
                    {"day": day, "symbol": sym, "shares_after": p["shares"]})
                events.append({
                    "type": "split", "symbol": sym,
                    "msg": f"每10股送转 {(factor - 1) * 10:.1f} 股，"
                           f"股数调整为 {p['shares']}"})
    return events
```

- [ ] **Step 4: 运行测试通过**

Run: `cd backend && python -m pytest tests/domain/test_replay_engine.py -v`
Expected: PASS(全部)

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/replay/engine.py backend/tests/domain/test_replay_engine.py
git commit -m "feat(replay): 日切nav记账(cash/pos披露位)+分红送转落账三税档"
```

---

### Task 6: eras.py — 时代池划分

**Files:**
- Create: `backend/src/domain/replay/eras.py`
- Test: `backend/tests/domain/test_replay_eras.py`

**Interfaces:**
- Produces:
  - `pools(bars: list[tuple]) -> dict[str, list[date]]`,bars=[(trade_date, close)] 升序 → `{"bull_top": [...], "bear_bottom": [...], "range": [...]}`
  - `thin(dates: list[date], gap: int = 60) -> list[date]` — 贪心抽稀(自然日近似交易日间隔)
  - 判定:牛顶=前250日涨幅≥90%分位 且 后120日回撤>20%;熊底=前250日涨幅≤10%分位 且 后120日反弹>15%;候选不足(序列太短)返回全空池,由 handler 回退

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/domain/test_replay_eras.py`:

```python
"""eras.pools 纯函数测试 — 构造序列驱动,不碰 DB。"""

import datetime as dt
import math

from src.domain.replay.eras import pools, thin


def _series(path: list[float], days_each: int = 1,
            start: str = "2005-01-03") -> list[tuple]:
    """path: 分段终点值;每段线性插值 days_each*20 个点。"""
    out = []
    d = dt.date.fromisoformat(start)
    prev = path[0]
    for v in path[1:]:
        n = days_each * 20
        for k in range(1, n + 1):
            out.append((d, prev + (v - prev) * k / n))
            d += dt.timedelta(days=days_each and 1 or 1)
        prev = v
    return out


class TestPools:
    def test_bull_top_after_rally_before_crash(self):
        # 涨250日+ → 崩120日-40%:崩前应入牛顶池
        s = _series([100, 200, 200, 120])  # 涨→横→崩
        ps = pools(s)
        assert ps["bull_top"], "牛顶池不应为空"

    def test_bear_bottom_after_decline_before_rebound(self):
        s = _series([200, 100, 100, 140])  # 跌→横→反弹
        ps = pools(s)
        assert ps["bear_bottom"], "熊底池不应为空"

    def test_short_series_empty(self):
        assert pools([(dt.date(2020, 1, 1), 1.0)]) == {
            "bull_top": [], "bear_bottom": [], "range": []}

    def test_thin_gap(self):
        ds = [dt.date(2020, 1, 1) + dt.timedelta(days=i * 10)
              for i in range(10)]
        out = thin(ds, gap=60)
        assert out[0] == ds[0]
        assert all((b - a).days >= 60 for a, b in zip(out, out[1:]))
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/domain/test_replay_eras.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 实现**

新建 `backend/src/domain/replay/eras.py`:

```python
"""基准指数历史 → 牛顶/熊底/震荡三时代池(v3 盲盒开局)。"""

from __future__ import annotations

from datetime import date

LOOKBACK = 250    # 前250日涨幅分位
FORWARD = 120     # 后120日走势判定
MIN_GAP = 60      # 池内日期最小间隔(自然日近似交易日)
MIN_HISTORY = 300  # 起点前至少300交易日(K线上下文,由 handler 用)


def pools(bars: list[tuple]) -> dict[str, list[date]]:
    """bars = [(trade_date, close)] 升序 → 三池日期列表。"""
    n = len(bars)
    if n <= max(LOOKBACK, MIN_HISTORY) + FORWARD:
        return {"bull_top": [], "bear_bottom": [], "range": []}
    cands: list[tuple] = []  # (date, trail, fwd_dd, fwd_ret)
    for i in range(LOOKBACK, n - FORWARD):
        base = bars[i - LOOKBACK][1]
        cur = bars[i][1]
        if not base or not cur:
            continue
        trail = cur / base - 1
        window = [b[1] for b in bars[i:i + FORWARD + 1]]
        fwd_dd = 1 - min(window) / cur
        fwd_ret = bars[i + FORWARD][1] / cur - 1
        cands.append((bars[i][0], trail, fwd_dd, fwd_ret))
    if not cands:
        return {"bull_top": [], "bear_bottom": [], "range": []}
    trails = sorted(c[1] for c in cands)
    q90 = trails[int(len(trails) * 0.9)]
    q10 = trails[int(len(trails) * 0.1)]
    bull = thin([c[0] for c in cands if c[1] >= q90 and c[2] > 0.20])
    bear = thin([c[0] for c in cands if c[1] <= q10 and c[3] > 0.15])
    used = set(bull) | set(bear)
    rng = thin([c[0] for c in cands if c[0] not in used])
    return {"bull_top": bull, "bear_bottom": bear, "range": rng}


def thin(dates: list[date], gap: int = MIN_GAP) -> list[date]:
    """贪心抽稀:顺序保留,与前一个保留点间隔 <gap 自然日的丢弃。"""
    out: list[date] = []
    for d in dates:
        if not out or (d - out[-1]).days >= gap:
            out.append(d)
    return out
```

- [ ] **Step 4: 运行测试通过**

Run: `cd backend && python -m pytest tests/domain/test_replay_eras.py -v`
Expected: PASS(若构造序列分位判定不满足,调整 `_series` 段长/幅度直到判据成立——判据本身由断言锁定,不许改判据)

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/replay/eras.py backend/tests/domain/test_replay_eras.py
git commit -m "feat(replay): 时代池eras——前250日分位×后120日回撤/反弹三分类+贪心抽稀"
```

---

### Task 7: scoring.py — 揭晓评分

**Files:**
- Create: `backend/src/domain/replay/scoring.py`
- Test: `backend/tests/domain/test_replay_scoring.py`

**Interfaces:**
- Produces:
  - `score(nav: list[dict], benchmark_bars: list[dict], trades: list[dict], initial_capital: float) -> dict`
  - nav 点:`{date, value, cash?, pos?}`;benchmark_bars:`{trade_date, close}`;trades 按 id/时间升序
  - 返回:`{"total", "excess_score", "turnover_score", "annual_excess_pct", "annual_turnover", "disclosures": {"max_drawdown", "benchmark_max_drawdown", "closed_win_rate", "closed_trips", "avg_cash_ratio", "max_position_weight"}}`
  - 公式(spec §3.5):超额分=`clamp(40+8×年化超额百分点, 0, 80)`;换手分=年化换手≤2x 满20,否则 `clamp(20×(10−turn)/8, 0, 20)`;nav<2 点 raise ValueError
  - 年化:`(v1/v0)^(250/days)−1`×100;换手=`Σ(价×股)/2 ÷ 平均NAV`,按 `×250/days` 年化

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/domain/test_replay_scoring.py`:

```python
"""scoring.score 纯函数测试 — 手算锚定。"""

import pytest

from src.domain.replay.scoring import score


def _nav(values, cash=None, pos=None):
    out = []
    for i, v in enumerate(values):
        p = {"date": f"2020-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}",
             "value": v}
        if cash is not None:
            p["cash"] = cash(v)
        if pos is not None:
            p["pos"] = pos(v)
        out.append(p)
    return out


BENCH = [{"trade_date": "2020-01-01", "close": 100.0},
         {"trade_date": "2020-12-31", "close": 102.0}]


class TestScore:
    def test_requires_two_nav_points(self):
        with pytest.raises(ValueError):
            score([{"date": "2020-01-01", "value": 100.0}], BENCH, [],
                  100.0)

    def test_excess_and_turnover_hand_computed(self):
        # 250个交易日:100→110(年化+10%),基准100→102(年化+2.02%附近)
        nav = _nav([100 + i * 0.04 for i in range(251)])  # 终值110
        # 换手:买卖各一笔 10万/11万,平均NAV≈105 → raw≈1.0 → 年化≈1.0x → 满20
        trades = [
            {"symbol": "a", "side": "buy", "price": 10.0, "shares": 10000},
            {"symbol": "a", "side": "sell", "price": 11.0, "shares": 10000},
        ]
        r = score(nav, BENCH, trades, 100.0)
        # 年化超额 ≈ 10% − 2.02% ≈ 7.98 → 超额分 = min(40+8×7.98, 80) = 80
        assert r["excess_score"] == 80.0
        assert r["turnover_score"] == 20.0
        assert r["total"] == 100.0
        assert r["annual_excess_pct"] == pytest.approx(7.98, abs=0.2)

    def test_negative_excess_floors_at_zero(self):
        nav = _nav([100 - i * 0.04 for i in range(251)])  # 亏钱
        r = score(nav, BENCH, [], 100.0)
        assert r["excess_score"] == 0.0
        assert r["turnover_score"] == 20.0  # 无交易满纪律分

    def test_high_turnover_zero_discipline(self):
        nav = _nav([100 + i * 0.04 for i in range(251)])
        trades = [{"symbol": "a", "side": "buy", "price": 10.0,
                   "shares": 100000}] * 30  # 年化换手 >10x
        r = score(nav, BENCH, trades, 100.0)
        assert r["turnover_score"] == 0.0

    def test_disclosures(self):
        nav = _nav([100, 120, 90], cash=lambda v: v / 2,
                   pos=lambda v: {"a": v / 2})
        trades = [
            {"symbol": "a", "side": "buy", "price": 10.0, "shares": 100},
            {"symbol": "a", "side": "sell", "price": 12.0, "shares": 100},
        ]
        d = score(nav, BENCH, trades, 100.0)["disclosures"]
        assert d["closed_win_rate"] == 1.0
        assert d["closed_trips"] == 1
        assert d["max_drawdown"] == pytest.approx(1 - 90 / 120)
        assert d["avg_cash_ratio"] == pytest.approx(0.5)
        assert d["max_position_weight"] == pytest.approx(0.5)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/domain/test_replay_scoring.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 实现**

新建 `backend/src/domain/replay/scoring.py`:

```python
"""揭晓评分(v3):总分 = 超额收益分(80) + 换手纪律分(20),spec §3.5。"""

from __future__ import annotations

TRADING_DAYS = 250


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _annual_pct(v0: float, v1: float, days: int) -> float:
    if v0 <= 0 or days <= 0:
        return 0.0
    return ((v1 / v0) ** (TRADING_DAYS / days) - 1) * 100


def _max_drawdown(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    peak = values[0]
    mdd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak:
            mdd = max(mdd, 1 - v / peak)
    return mdd


def _closed_win_rate(trades: list[dict]) -> tuple[float | None, int]:
    """FIFO 平仓胜率:(win_rate|None, 平仓次数)。trades 须按时间升序。"""
    lots: dict[str, list[list]] = {}
    wins = 0
    trips = 0
    for t in trades:
        q = lots.setdefault(t["symbol"], [])
        if t["side"] == "buy":
            q.append([t["price"], t["shares"]])
            continue
        remain = t["shares"]
        pnl = 0.0
        while remain > 0 and q:
            lot = q[0]
            take = min(lot[1], remain)
            pnl += (t["price"] - lot[0]) * take
            remain -= take
            lot[1] -= take
            if lot[1] == 0:
                q.pop(0)
        if remain == 0:
            trips += 1
            wins += 1 if pnl > 0 else 0
    return (wins / trips if trips else None), trips


def score(nav: list[dict], benchmark_bars: list[dict],
          trades: list[dict], initial_capital: float) -> dict:
    if len(nav) < 2:
        raise ValueError("nav 不足2点，无法评分")
    days = len(nav)
    final = nav[-1]["value"]
    port_ann = _annual_pct(initial_capital, final, days)
    d0, d1 = nav[0]["date"], nav[-1]["date"]
    win = [b for b in benchmark_bars if d0 <= b["trade_date"] <= d1]
    bench_ann = (_annual_pct(win[0]["close"], win[-1]["close"], days)
                 if len(win) >= 2 else 0.0)
    excess_ann = port_ann - bench_ann
    excess_score = _clamp(40 + 8 * excess_ann, 0, 80)

    avg_nav = sum(p["value"] for p in nav) / days
    turnover_raw = (sum(t["price"] * t["shares"] for t in trades) / 2
                    / avg_nav) if avg_nav > 0 else 0.0
    turn_ann = turnover_raw * TRADING_DAYS / days
    turn_score = (20.0 if turn_ann <= 2
                  else _clamp(20 * (10 - turn_ann) / 8, 0, 20))

    nav_values = [p["value"] for p in nav]
    bench_values = [b["close"] for b in win] or [1.0]
    win_rate, trips = _closed_win_rate(trades)
    cash_ratio = None
    weight = None
    pts = [p for p in nav if p.get("cash") is not None]
    if pts:
        cash_ratio = sum(p["cash"] / p["value"] for p in pts) / len(pts)
        weights = [v / p["value"] for p in pts
                   for v in (p.get("pos") or {}).values()]
        weight = max(weights) if weights else None
    return {
        "total": round(excess_score + turn_score, 1),
        "excess_score": round(excess_score, 1),
        "turnover_score": round(turn_score, 1),
        "annual_excess_pct": round(excess_ann, 2),
        "annual_turnover": round(turn_ann, 2),
        "disclosures": {
            "max_drawdown": _max_drawdown(nav_values),
            "benchmark_max_drawdown": _max_drawdown(bench_values),
            "closed_win_rate": win_rate,
            "closed_trips": trips,
            "avg_cash_ratio": cash_ratio,
            "max_position_weight": weight,
        },
    }
```

- [ ] **Step 4: 运行测试通过**

Run: `cd backend && python -m pytest tests/domain/test_replay_scoring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/replay/scoring.py backend/tests/domain/test_replay_scoring.py
git commit -m "feat(replay): 揭晓评分scoring——超额80+换手20,胜率/回撤/现金占比只披露"
```

---

### Task 8: handler — exam 开局(时代池抽起点 + 元数据脱敏 + 禁外部存档)

**Files:**
- Modify: `backend/src/api/handler/replay_handler.py`
- Test: `backend/tests/api/test_replay_exam.py`(追加)

**Interfaces:**
- Consumes: Task 6 `pools`;Task 1 列
- Produces:
  - `POST /replay/sessions` body 增可选 `mode("exam")/length_days(120|250|500)/era_pref(random|bull_top|bear_bottom|range)`;exam 时 `name` 可缺省(默认"盲盒旅程"),`start_date/end_date` 忽略
  - `_session_dict` 返回增 `mode`;exam+active 时 `start_date/current_date=None`、增 `day_ordinal/length_days`、state 去掉 nav(防真实日期泄露);revealed 后恢复真实日期
  - `_pick_exam_start(benchmark, length_days, era_pref) -> date`(raise ValueError 无数据)
  - `save_state` 对 exam 会话返回失败
  - `_trade_dict` 增 `order_type`

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/api/test_replay_exam.py` 末尾追加:

```python
class TestExamCreate:
    def test_create_masked_and_no_external_state(self, client, db_conn):
        sid = None
        try:
            r = client.post("/api/v1/replay/sessions", json={
                "mode": "exam", "initial_capital": 100000,
                "length_days": 120, "era_pref": "random"})
            assert r.json()["code"] == 0, r.text
            d = r.json()["data"]
            sid = d["id"]
            assert d["mode"] == "exam"
            assert d["start_date"] is None and d["current_date"] is None
            assert d["day_ordinal"] == 1 and d["length_days"] == 120
            assert "nav" not in d["state"]  # 元数据脱敏
            with db_conn.cursor() as cur:  # 库里有真实日期
                cur.execute("SELECT start_date, mode FROM replay_session "
                            "WHERE id = %s", (sid,))
                row = cur.fetchone()
            assert row[0] is not None and row[1] == "exam"
            g = client.get(f"/api/v1/replay/sessions/{sid}")
            assert g.json()["data"]["start_date"] is None
            x = client.put(f"/api/v1/replay/sessions/{sid}/state",
                           json={"current_date": "2020-01-01", "cash": 1,
                                 "state": {}})
            assert x.json()["code"] != 0  # 服务端记账
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_create_validation(self, client):
        base = {"mode": "exam", "initial_capital": 100000}
        assert client.post("/api/v1/replay/sessions",
                           json=base).json()["code"] != 0
        assert client.post("/api/v1/replay/sessions", json={
            **base, "length_days": 99}).json()["code"] != 0
        assert client.post("/api/v1/replay/sessions", json={
            **base, "length_days": 250,
            "era_pref": "hack"}).json()["code"] != 0
        assert client.post("/api/v1/replay/sessions",
                           json={"mode": "hack"}).json()["code"] != 0
    }
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/api/test_replay_exam.py -v`
Expected: FAIL — create 返回 code!=0(现实现要求 start_date)

- [ ] **Step 3: 实现 handler 改造**

`backend/src/api/handler/replay_handler.py`:

(a) 顶部 import 区(`import psycopg2` 之后)追加:

```python
import random as _random

from src.domain.replay.eras import pools as _era_pools
```

(b) 替换整个 `create_session`(free 分支逐字保留原逻辑):

```python
def create_session(body: dict):
    mode = body.get("mode") or "free"
    if mode not in ("free", "exam"):
        return responses.fail("mode 应为 free|exam")
    try:
        capital = float(body.get("initial_capital"))
    except (TypeError, ValueError):
        return responses.fail("initial_capital 应为正数")
    if capital <= 0:
        return responses.fail("initial_capital 应为正数")
    if mode == "exam":
        length_days = body.get("length_days")
        if length_days not in (120, 250, 500):
            return responses.fail("length_days 应为 120|250|500")
        era_pref = body.get("era_pref") or "random"
        if era_pref not in ("random", "bull_top", "bear_bottom", "range"):
            return responses.fail(
                "era_pref 应为 random|bull_top|bear_bottom|range")
        benchmark = body.get("benchmark_symbol") or "sh000300"
        try:
            start = _pick_exam_start(benchmark, length_days, era_pref)
        except ValueError as e:
            return responses.fail(str(e))
        s = ReplaySession(
            name=(body.get("name") or "").strip() or "盲盒旅程",
            start_date=start, current_date=start, end_date=None,
            initial_capital=capital, cash=capital,
            benchmark_symbol=benchmark, mode="exam",
            state={
                "pool": [], "positions": [], "nav": [], "names": {},
                "industries": {}, "seg_idx": 0, "day_ordinal": 1,
                "length_days": length_days, "skipped_days": 0,
                "pending_orders": [], "frozen_cash": 0.0,
                "dividends_received": [], "era_pref": era_pref,
            })
        return responses.success(_session_dict(_repo().create(s)))
    # ↓ free:原逻辑不动
    name = (body.get("name") or "").strip()
    d, err = _parse_day(body.get("start_date"), "start_date")
    if err:
        return err
    if not name:
        return responses.fail("name 必填")
    if d >= date.today():
        return responses.fail("起始日期必须早于今天")
    first = _next_trading_day(d)
    if first is None:
        return responses.fail("起始日期之后没有交易日数据")
    end_d, err = (
        _parse_day(body.get("end_date"), "end_date")
        if body.get("end_date")
        else (None, None)
    )
    if err:
        return err
    if end_d is not None and end_d <= first:
        return responses.fail("end_date 必须晚于起始交易日")
    if end_d is not None and end_d > date.today():
        return responses.fail("end_date 不能晚于今天")
    s = ReplaySession(
        name=name, start_date=first, current_date=first, end_date=end_d,
        initial_capital=capital, cash=capital,
        benchmark_symbol=body.get("benchmark_symbol") or "sh000300",
        state={"pool": [], "positions": [], "nav": []},
    )
    return responses.success(_session_dict(_repo().create(s)))
```

(c) 替换 `_session_dict`:

```python
def _session_dict(s: ReplaySession, with_state: bool = True) -> dict:
    mode = s.mode or "free"
    blind = mode == "exam" and s.status == "active"
    st = s.state or {}
    out = {
        "id": s.id,
        "name": s.name,
        "status": s.status,
        "mode": mode,
        # 拟真+航行中:真实日期脱敏(F12 不设防,spec §6)
        "start_date": None if blind else s.start_date.isoformat(),
        "current_date": None if blind else s.current_date.isoformat(),
        "day_ordinal": st.get("day_ordinal") if blind else None,
        "length_days": st.get("length_days") if blind else None,
        "end_date": s.end_date.isoformat() if s.end_date else None,
        "initial_capital": s.initial_capital,
        "cash": s.cash,
        "benchmark_symbol": s.benchmark_symbol,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }
    if with_state:
        state_out = dict(st or {"pool": [], "positions": [], "nav": []})
        if blind:
            state_out.pop("nav", None)  # nav 含真实日期,盲盒期由 /view 供给
        out["state"] = state_out
    return out
```

(d) `_trade_dict` 的 `"note": t.note,` 行后加:

```python
        "order_type": t.order_type or "market",
```

(e) `save_state` 函数开头(`d, err = _parse_day...` 之前)插入:

```python
    s = _repo().get(session_id)
    if s is not None and (s.mode or "free") == "exam":
        return responses.fail("拟真会话由服务端记账，禁止外部存档")
```

(f) 文件末尾(`news` 函数之后)追加:

```python
# ── v3 拟真考核 ──


def _benchmark_series(symbol: str) -> list[tuple]:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date::date, close_ FROM index_ohlcv "
            "WHERE symbol = %s ORDER BY trade_date",
            (symbol.lower(),),
        )
        return cur.fetchall()


def _pick_exam_start(benchmark: str, length_days: int,
                     era_pref: str) -> date:
    """时代池抽起点:偏好池优先,约束前≥300/后≥length_days 交易日;空则回退。

    无任何数据 raise ValueError。
    """
    series = _benchmark_series(benchmark)
    if not series:
        raise ValueError("基准指数无数据")
    dates = [r[0] for r in series]
    idx = {d: i for i, d in enumerate(dates)}

    def usable(d) -> bool:
        i = idx.get(d)
        return i is not None and i >= 300 and i + length_days < len(dates)

    cands: list = []
    if era_pref != "random":
        cands = [d for d in _era_pools(series).get(era_pref, []) if usable(d)]
    if not cands:
        cands = [d for d in dates if usable(d)]
    if not cands:
        cands = dates[300:] or dates  # 数据不足兜底(测试库短历史)
    return _random.choice(cands)
```

- [ ] **Step 4: 运行测试通过**

Run: `cd backend && python -m pytest tests/api/test_replay_exam.py tests/api/test_replay_router.py -v`
Expected: PASS(exam + 旧套件全绿)

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/handler/replay_handler.py backend/tests/api/test_replay_exam.py
git commit -m "feat(replay): exam开局——时代池随机抽日+元数据脱敏(start/current→null)+禁外部存档"
```

---

### Task 9: handler — 段级推进 + 视图 + 池端点(信息门)

**Files:**
- Modify: `backend/src/api/handler/replay_handler.py`
- Modify: `backend/src/api/router/replay_router.py`
- Test: `backend/tests/api/test_replay_exam.py`(追加)

**Interfaces:**
- Consumes: Task 2 `SEG_COUNT/segments`;Task 4 `check_pending/cancel_day_pending`;Task 5 `day_close_nav/apply_dividends`
- Produces:
  - `GET /replay/advance?session_id=&step=seg|day`(exam);`days=N` 保留 free;free 传 step 或 exam 缺 step → fail
  - `GET /replay/sessions/{id}/view` → ExamView dict(exam 专属)
  - `POST /replay/sessions/{id}/pool` body `{symbols: [..]}` → ExamView + `failed: [..]`
  - ExamView 形状(Task 13 前端 types 一字对应):`{mode, day_ordinal, seg_idx, seg_count, date, travel_complete, segments{sym:[seg]}, partial_bars{sym:ReplayBar}, indices_segments, indices_partial, cash, positions, nav, pending, frozen_cash, events[], pool, names, industries}`;advance 响应额外 `fills[]`
  - 内部助手:`_day_bars/_prev_closes/_dividends_for/_segs_of/_partial_bar/_exam_view/_advance_exam/_trade_model`

- [ ] **Step 1: 追加失败测试**

```python
class TestExamAdvance:
    def _make(self, client, symbol, length_days=120):
        r = client.post("/api/v1/replay/sessions", json={
            "mode": "exam", "initial_capital": 100000,
            "length_days": length_days, "era_pref": "random"})
        assert r.json()["code"] == 0, r.text
        sid = r.json()["data"]["id"]
        p = client.post(f"/api/v1/replay/sessions/{sid}/pool",
                        json={"symbols": [symbol]})
        assert p.json()["code"] == 0, p.text
        assert p.json()["data"]["pool"] == [symbol]
        return sid

    def test_view_and_seg_info_gate(self, client, dyn_symbol):
        sid = None
        try:
            sid = self._make(client, dyn_symbol)
            v = client.get(f"/api/v1/replay/sessions/{sid}/view").json()["data"]
            assert v["seg_idx"] == 0 and v["seg_count"] == 8
            assert len(v["segments"][dyn_symbol]) == 1  # 只到第0段
            r = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "seg"})
            v = r.json()["data"]
            assert v["seg_idx"] == 1
            assert len(v["segments"][dyn_symbol]) == 2  # 信息门:≤当前段
            assert (v["partial_bars"][dyn_symbol]["close"]
                    == v["segments"][dyn_symbol][-1]["close"])
            assert set(v["indices_segments"]) == {
                "sh000001", "sz399001", "sz399006", "sh000300"}
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_roll_at_seg7_and_dividend_path(self, client, dyn_symbol,
                                            db_conn):
        sid = None
        try:
            sid = self._make(client, dyn_symbol)
            for _ in range(7):
                client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "seg"})
            v = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "seg"}).json()["data"]
            assert v["seg_idx"] == 0 and v["day_ordinal"] == 2  # 日切
            with db_conn.cursor() as cur:
                cur.execute("SELECT current_date FROM replay_session "
                            "WHERE id = %s", (sid,))
                assert cur.fetchone()[0].isoformat() == v["date"]
            assert len(v["nav"]) == 1  # 昨日 nav 已记
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_skip_day_and_travel_complete(self, client, dyn_symbol,
                                          db_conn):
        sid = None
        try:
            sid = self._make(client, dyn_symbol)
            # 直接把 length_days 改成 2,快进两日到终点
            with db_conn.cursor() as cur:
                cur.execute(
                    "UPDATE replay_session "
                    "SET state = jsonb_set(state, '{length_days}', '2') "
                    "WHERE id = %s", (sid,))
                db_conn.commit()
            a = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "day"}).json()["data"]
            assert a["day_ordinal"] == 2 and not a["travel_complete"]
            b = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "day"}).json()["data"]
            assert b["travel_complete"] is True
            c = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "day"})
            assert c.json()["code"] != 0  # 终点后拒绝推进
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_step_mode_mismatch(self, client, dyn_symbol, trade_day):
        sid = None
        try:
            sid = self._make(client, dyn_symbol)
            r = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "days": 1})
            assert r.json()["code"] != 0  # exam 缺 step
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")
        r = client.post("/api/v1/replay/sessions", json={
            "name": "TS_step", "start_date": trade_day,
            "initial_capital": 1e6})
        sid = r.json()["data"]["id"]
        try:
            r = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "seg"})
            assert r.json()["code"] != 0  # free 不接受 step
        finally:
            client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_pool_rejects_bad_symbol(self, client):
        r = client.post("/api/v1/replay/sessions", json={
            "mode": "exam", "initial_capital": 100000,
            "length_days": 120, "era_pref": "random"})
        sid = r.json()["data"]["id"]
        try:
            p = client.post(f"/api/v1/replay/sessions/{sid}/pool",
                            json={"symbols": ["sh999999"]})
            assert p.json()["code"] == 0
            assert p.json()["data"]["failed"] == ["sh999999"]
            assert p.json()["data"]["pool"] == []
        finally:
            client.delete(f"/api/v1/replay/sessions/{sid}")
```

`dyn_symbol` fixture 本文件没有——在文件顶部补(与 test_replay_router.py 同实现):

```python
@pytest.fixture(scope="module")
def dyn_symbol():
    from src.infra.database.sql_engine.dsn import get_dsn
    import psycopg2
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol FROM stock_ohlcv "
                "WHERE trade_date::date < '2019-06-01' "
                "GROUP BY symbol ORDER BY COUNT(*) DESC LIMIT 1")
            row = cur.fetchone()
            assert row, "stock_ohlcv 无 2019-06 之前的数据"
            return row[0]
    finally:
        conn.close()


@pytest.fixture(scope="module")
def trade_day():
    from src.infra.database.sql_engine.dsn import get_dsn
    import psycopg2
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(trade_date::date) FROM index_ohlcv "
                "WHERE symbol = 'sh000001' "
                "AND trade_date::date <= '2020-03-13'")
            return cur.fetchone()[0].isoformat()
    finally:
        conn.close()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/api/test_replay_exam.py -v`
Expected: FAIL — /view 404、step 参数被忽略

- [ ] **Step 3: 实现**

`backend/src/api/handler/replay_handler.py`:

(a) 顶部追加 import:

```python
from src.domain.replay import engine as _engine
from src.domain.replay.synthetic import SEG_COUNT, segments as _segments
```

(b) 文件末尾追加(内部助手 + 三个入口):

```python
# ── v3 段级推进(信息门:响应只含截至当前段的行情) ──


def _split_symbols(symbols: list[str]) -> tuple[list[str], list[str]]:
    syms = [s.lower() for s in symbols]
    idx = [s for s in syms if s.startswith(("sh000", "sz399"))]
    stk = [s for s in syms if not s.startswith(("sh000", "sz399"))]
    return stk, idx


def _day_bars(symbols: list[str], day: date) -> dict[str, dict]:
    """池内股票+指数的当日 bar(停牌无行)。"""
    out: dict[str, dict] = {}
    stk, idx = _split_symbols(symbols)
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        for table, keys in (("stock_ohlcv", stk), ("index_ohlcv", idx)):
            if not keys:
                continue
            cur.execute(
                f'SELECT symbol, {_BAR_COLS} FROM "{table}" '
                "WHERE symbol = ANY(%s) AND trade_date::date = %s",
                (keys, day),
            )
            for r in cur.fetchall():
                out[r.pop("symbol")] = _bar(r)
    return out


def _prev_closes(symbols: list[str], day: date) -> dict[str, float]:
    """每符号 < day 的最后收盘价(限价区间/停牌估值)。"""
    out: dict[str, float] = {}
    stk, idx = _split_symbols(symbols)
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        for table, keys in (("stock_ohlcv", stk), ("index_ohlcv", idx)):
            if not keys:
                continue
            cur.execute(
                f'SELECT DISTINCT ON (symbol) symbol, close_ AS close '
                f'FROM "{table}" WHERE symbol = ANY(%s) '
                "AND trade_date::date < %s ORDER BY symbol, trade_date DESC",
                (keys, day),
            )
            for r in cur.fetchall():
                out[r["symbol"]] = float(r["close"])
    return out


def _dividends_for(pool: list[str], day: date) -> list[dict]:
    with _conn() as conn, conn.cursor(
            cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT symbol, div_per_share, stock_div, convert "
            "FROM stock_dividend "
            "WHERE symbol = ANY(%s) AND ex_date = %s",
            ([s.lower() for s in pool], day),
        )
        return [dict(r) for r in cur.fetchall()]


def _segs_of(session_id: int, bars: dict[str, dict],
             day_str: str) -> dict[str, list[dict]]:
    return {sym: _segments(sym, day_str, bar, seed=str(session_id))
            for sym, bar in bars.items()}


def _partial_bar(bar: dict, segs: list[dict]) -> dict:
    n = len(segs)
    return {
        "trade_date": bar["trade_date"],
        "open": segs[0]["open"],
        "high": max(s["high"] for s in segs),
        "low": min(s["low"] for s in segs),
        "close": segs[-1]["close"],
        "volume": int(bar["volume"] * n / SEG_COUNT),
        "amount": round(bar["amount"] * n / SEG_COUNT, 2),
    }


def _trade_model(session_id: int, t: dict) -> ReplayTrade:
    return ReplayTrade(
        session_id=session_id,
        trade_date=date.fromisoformat(t["trade_date"]),
        symbol=t["symbol"], side=t["side"], price=t["price"],
        shares=t["shares"], fee=t["fee"], tax=t["tax"],
        note=t.get("note"), order_type=t.get("order_type", "market"))


def _exam_view(s: ReplaySession, fills=None, events=None) -> dict:
    state = s.state
    day_str = s.current_date.isoformat()
    seed = str(s.id)
    pool = state.get("pool") or []
    bars = _day_bars(pool + list(INDEX_SYMBOLS), s.current_date)
    seg_idx = state.get("seg_idx", 0)
    all_segs = _segs_of(s.id, bars, day_str)
    stock_segs = {sym: all_segs[sym][:seg_idx + 1] for sym in pool
                  if sym in all_segs}
    idx_segs = {sym: all_segs[sym][:seg_idx + 1]
                for sym in INDEX_SYMBOLS if sym in all_segs}
    suspended = [sym for sym in pool if sym not in bars]
    ev = list(events or [])
    ev += [{"type": "suspended", "symbol": sym, "msg": "停牌/无行情"}
           for sym in suspended]
    out = {
        "mode": "exam",
        "day_ordinal": state.get("day_ordinal", 1),
        "seg_idx": seg_idx,
        "seg_count": SEG_COUNT,
        "date": day_str,
        "travel_complete": bool(state.get("travel_complete")),
        "segments": stock_segs,
        "partial_bars": {sym: _partial_bar(bars[sym], stock_segs[sym])
                         for sym in stock_segs},
        "indices_segments": idx_segs,
        "indices_partial": {sym: _partial_bar(bars[sym], idx_segs[sym])
                            for sym in idx_segs},
        "cash": state["cash"],
        "positions": state.get("positions") or [],
        "nav": state.get("nav") or [],
        "pending": state.get("pending_orders") or [],
        "frozen_cash": state.get("frozen_cash", 0.0),
        "events": ev,
        "pool": pool,
        "names": state.get("names") or {},
        "industries": state.get("industries") or {},
    }
    if fills is not None:
        out["fills"] = fills
    return out


def view(session_id: int):
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    if (s.mode or "free") != "exam":
        return responses.fail("仅拟真会话有视图端点")
    return responses.success(_exam_view(s))


def add_pool(session_id: int, body: dict):
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    if (s.mode or "free") != "exam":
        return responses.fail("仅拟真会话使用池端点")
    if s.status != "active":
        return responses.fail("会话已揭晓")
    syms = body.get("symbols")
    if not isinstance(syms, list) or not syms:
        return responses.fail("symbols 应为非空数组")
    state = s.state
    pool = state.setdefault("pool", [])
    failed: list[str] = []
    for raw in syms:
        sym = str(raw).lower()
        if sym in pool:
            continue
        with _conn() as conn, conn.cursor(
                cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT 1 FROM stock_ohlcv WHERE symbol = %s "
                "AND trade_date::date <= %s LIMIT 1",
                (sym, s.current_date),
            )
            if cur.fetchone() is None:
                failed.append(sym)
                continue
            cur.execute(
                "SELECT si.name AS name, m.sw_name_l1 AS industry "
                "FROM (SELECT %s AS s) q "
                "LEFT JOIN stock_info si ON si.symbol = q.s "
                "LEFT JOIN sw_industry_member m ON m.symbol = q.s",
                (sym,),
            )
            row = cur.fetchone()
        pool.append(sym)
        if row and row["name"]:
            state.setdefault("names", {})[sym] = _display_name(row["name"])
        if row and row["industry"]:
            state.setdefault("industries", {})[sym] = row["industry"]
    _repo().save_state(session_id, s.current_date, state["cash"], state)
    out = _exam_view(s)
    out["failed"] = failed
    return responses.success(out)


def _advance_exam(s: ReplaySession, step: str):
    if s.status != "active":
        return responses.fail("会话已揭晓")
    state = s.state
    if state.get("travel_complete"):
        return responses.fail("旅程已走完，请揭晓复盘")
    day = s.current_date
    day_str = day.isoformat()
    seed = str(s.id)
    pool = state.get("pool") or []
    bars = _day_bars(pool + list(INDEX_SYMBOLS), day)
    segs_all = _segs_of(s.id,
                        {sym: b for sym, b in bars.items() if sym in pool},
                        day_str)
    prev_closes = _prev_closes(pool, day)
    names = state.get("names") or {}
    fills: list[dict] = []
    events: list[dict] = []

    segs_left = SEG_COUNT - 1 - state.get("seg_idx", 0)
    walk = segs_left if step == "day" else min(1, segs_left)
    for _k in range(walk):
        state["seg_idx"] = state["seg_idx"] + 1
        seg_now = {sym: segs_all[sym][state["seg_idx"]]
                   for sym in segs_all}
        t, ev = _engine.check_pending(state, seg_now, prev_closes, names,
                                      day_str)
        fills += t
        events += ev

    if (step == "day") or segs_left == 0:  # 日切(尾盘后按段=收摊走人)
        events += _engine.cancel_day_pending(state)
        close_map = {sym: bars[sym]["close"]
                     for sym in pool if sym in bars}
        for sym in pool:  # 停牌用最近收盘价
            if sym not in close_map and sym in prev_closes:
                close_map[sym] = prev_closes[sym]
        _engine.day_close_nav(state, day_str, close_map)
        if step == "day":
            state["skipped_days"] = state.get("skipped_days", 0) + 1
        if state.get("day_ordinal", 1) >= state.get("length_days", 1):
            state["travel_complete"] = True
        else:
            nxt = _next_trading_day(day + timedelta(days=1))
            if nxt is None:
                state["travel_complete"] = True
            else:
                divs = _dividends_for(pool, nxt)
                events += _engine.apply_dividends(state, divs,
                                                  nxt.isoformat())
                day = nxt
                state["seg_idx"] = 0
                state["day_ordinal"] = state.get("day_ordinal", 1) + 1
    for t in fills:
        _repo().add_trade(_trade_model(s.id, t))
    _repo().save_state(s.id, day, state["cash"], state)
    s.current_date = day  # 内存对象同步(_exam_view 用)
    return responses.success(_exam_view(s, fills=fills, events=events))
```

(c) 替换 `advance` 入口(在原 `advance` 函数上方重写):

```python
def advance(session_id: int, days: int = 1, step: str | None = None):
    """油门端点:free=days 日推进(原语义);exam=step=seg|day 段级推进。"""
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    if (s.mode or "free") == "exam":
        if step not in ("seg", "day"):
            return responses.fail("拟真会话请用 step=seg|day 推进")
        return _advance_exam(s, step)
    if step is not None:
        return responses.fail("step 仅拟真会话可用")
    days = max(1, min(days, 60))
    ...  # ↓ 原 free 逻辑从这里开始逐字保留(with _conn 查询块 + bump_current_date)
```

(原 `advance` 中 `s = _repo().get(session_id)` 与开头的会话判空两行删掉——已上移到入口。)

(d) `backend/src/api/router/replay_router.py`:替换 advance 路由并在文件末尾(`_news` 之后)追加新路由:

```python
@router.get("/advance")
def _advance(session_id: int = Query(...), days: int = Query(1),
             step: str = Query(None)):
    return h.advance(session_id, days, step)


@router.get("/sessions/{session_id}/view")
def _view(session_id: int):
    return h.view(session_id)


@router.post("/sessions/{session_id}/pool")
def _add_pool(session_id: int, body: dict):
    return h.add_pool(session_id, body)
```

- [ ] **Step 4: 运行测试通过**

Run: `cd backend && python -m pytest tests/api/test_replay_exam.py tests/api/test_replay_router.py -v`
Expected: PASS(旧 advance 测试用 days 参数仍绿)

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/handler/replay_handler.py backend/src/api/router/replay_router.py backend/tests/api/test_replay_exam.py
git commit -m "feat(replay): 段级推进advance(seg|day)+view/pool端点——信息门只发截至当前段,日切nav+分红落账"
```

---

### Task 10: handler — 下单端点(市价滑点/限价入簿/理由必填)

**Files:**
- Modify: `backend/src/api/handler/replay_handler.py`
- Modify: `backend/src/api/router/replay_router.py`
- Test: `backend/tests/api/test_replay_exam.py`(追加)

**Interfaces:**
- Consumes: Task 3/4 engine 全套;Task 9 `_day_bars/_prev_closes`
- Produces:
  - `POST /replay/sessions/{id}/orders` body `{symbol, side, order_type: market|limit, shares, limit_price?, note}` → `{status: "filled", trade, cash, positions, pending, frozen_cash}` 或 `{status: "pending", order, ...}`;拒绝 `code!=0`
  - 校验:exam+active+未到终点;symbol 在池;note 1~140 字;market 段价=当前段 close×(1±slippage);market sell 额外校验 `sellable_shares`;limit 走 `try_place_limit`

- [ ] **Step 1: 追加失败测试**

```python
class TestExamOrders:
    def _make(self, client, symbol):
        r = client.post("/api/v1/replay/sessions", json={
            "mode": "exam", "initial_capital": 100000,
            "length_days": 250, "era_pref": "random"})
        sid = r.json()["data"]["id"]
        client.post(f"/api/v1/replay/sessions/{sid}/pool",
                    json={"symbols": [symbol]})
        return sid

    def _view(self, client, sid):
        return client.get(
            f"/api/v1/replay/sessions/{sid}/view").json()["data"]

    def test_note_required(self, client, dyn_symbol):
        sid = None
        try:
            sid = self._make(client, dyn_symbol)
            r = client.post(f"/api/v1/replay/sessions/{sid}/orders",
                            json={"symbol": dyn_symbol, "side": "buy",
                                  "order_type": "market", "shares": 100})
            assert r.json()["code"] != 0 and "理由" in r.json()["msg"]
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_market_buy_fills_at_segment_price(self, client, dyn_symbol):
        sid = None
        try:
            sid = self._make(client, dyn_symbol)
            v = self._view(client, sid)
            seg_close = v["segments"][dyn_symbol][0]["close"]
            r = client.post(f"/api/v1/replay/sessions/{sid}/orders",
                            json={"symbol": dyn_symbol, "side": "buy",
                                  "order_type": "market", "shares": 100,
                                  "note": "低吸"})
            assert r.json()["code"] == 0, r.text
            d = r.json()["data"]
            assert d["status"] == "filled"
            # 成交价 = 段价×(1+滑点) ∈ [seg_close, seg_close*1.0015]
            assert seg_close <= d["trade"]["price"] <= seg_close * 1.0015 + 0.01
            assert d["positions"][0]["shares"] == 100
            trades = client.get(
                f"/api/v1/replay/sessions/{sid}/trades").json()["data"]
            assert len(trades) == 1
            assert trades[0]["order_type"] == "market"
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_limit_lifecycle(self, client, dyn_symbol):
        sid = None
        try:
            sid = self._make(client, dyn_symbol)
            v = self._view(client, sid)
            seg_close = v["segments"][dyn_symbol][0]["close"]
            # 激进买价:接近段价上方(区间内)——大概率后续段触发
            limit = round(min(seg_close * 1.05,
                              seg_close * 1.08), 2)
            r = client.post(f"/api/v1/replay/sessions/{sid}/orders",
                            json={"symbol": dyn_symbol, "side": "buy",
                                  "order_type": "limit", "shares": 100,
                                  "limit_price": limit, "note": "挂低点"})
            assert r.json()["code"] == 0, r.text
            d = r.json()["data"]
            assert d["status"] == "pending"
            assert d["frozen_cash"] > 0
            # 快进整日:要么日内成交,要么收盘撤销——终态不变量
            a = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "day"}).json()["data"]
            assert a["pending"] == []
            assert a["frozen_cash"] == 0.0
            assert a["day_ordinal"] == 2
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_limit_out_of_range_rejected(self, client, dyn_symbol):
        sid = None
        try:
            sid = self._make(client, dyn_symbol)
            v = self._view(client, sid)
            seg_close = v["segments"][dyn_symbol][0]["close"]
            r = client.post(f"/api/v1/replay/sessions/{sid}/orders",
                            json={"symbol": dyn_symbol, "side": "buy",
                                  "order_type": "limit", "shares": 100,
                                  "limit_price": seg_close * 2,
                                  "note": "乱挂"})
            assert r.json()["code"] != 0 and "区间" in r.json()["msg"]
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_symbol_must_be_in_pool(self, client, dyn_symbol):
        sid = None
        try:
            sid = self._make(client, dyn_symbol)
            r = client.post(f"/api/v1/replay/sessions/{sid}/orders",
                            json={"symbol": "sh600000", "side": "buy",
                                  "order_type": "market", "shares": 100,
                                  "note": "x"})
            assert r.json()["code"] != 0 and "池" in r.json()["msg"]
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/api/test_replay_exam.py -v`
Expected: FAIL — /orders 404

- [ ] **Step 3: 实现**

(a) `backend/src/api/handler/replay_handler.py` 末尾追加:

```python
def place_order(session_id: int, body: dict):
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    if (s.mode or "free") != "exam":
        return responses.fail("仅拟真会话使用下单端点")
    if s.status != "active":
        return responses.fail("会话已揭晓，不能交易")
    state = s.state
    if state.get("travel_complete"):
        return responses.fail("旅程已走完，请揭晓复盘")
    symbol = str(body.get("symbol") or "").lower()
    if symbol not in (state.get("pool") or []):
        return responses.fail("标的不在池内")
    side = body.get("side")
    if side not in ("buy", "sell"):
        return responses.fail("side 应为 buy|sell")
    order_type = body.get("order_type") or "market"
    if order_type not in ("market", "limit"):
        return responses.fail("order_type 应为 market|limit")
    shares = body.get("shares")
    if not isinstance(shares, int) or shares <= 0:
        return responses.fail("shares 应为正整数")
    note = (body.get("note") or "").strip()
    if not (1 <= len(note) <= 140):
        return responses.fail("下单理由必填（1~140 字）")
    day = s.current_date
    day_str = day.isoformat()
    bars = _day_bars([symbol], day)
    if symbol not in bars:
        return responses.fail("当日停牌，无法交易")
    prev = _prev_closes([symbol], day).get(symbol)
    if prev is None:
        return responses.fail("缺前收盘数据")
    names = state.get("names") or {}
    order = {"symbol": symbol, "side": side, "shares": shares,
             "note": note, "order_type": order_type}
    if order_type == "market":
        if side == "sell" and shares > _engine.sellable_shares(
                state, symbol, day_str):
            return responses.fail("持仓不足（含挂单冻结）")
        segs = _segments(symbol, day_str, bars[symbol], seed=str(s.id))
        seg_price = segs[state.get("seg_idx", 0)]["close"]
        slip = _engine.slippage(
            f"{s.id}:{symbol}:{day_str}:{state.get('seg_idx', 0)}:{side}")
        px = seg_price * (1 + slip if side == "buy" else 1 - slip)
        cash_avail = state["cash"] - state.get("frozen_cash", 0.0)
        r = _engine.try_fill_market(cash_avail, state.get("positions") or [],
                                    order, px, prev, names.get(symbol),
                                    day_str)
        if not r["ok"]:
            return responses.fail(r["error"])
        state["cash"] = r["cash"]
        state["positions"] = r["positions"]
        _repo().add_trade(_trade_model(s.id, r["trade"]))
        _repo().save_state(s.id, day, state["cash"], state)
        return responses.success({
            "status": "filled", "trade": r["trade"],
            "cash": state["cash"], "positions": state["positions"],
            "pending": state.get("pending_orders") or [],
            "frozen_cash": state.get("frozen_cash", 0.0)})
    order["limit_price"] = body.get("limit_price")
    r = _engine.try_place_limit(state, order, prev, names.get(symbol),
                                day_str)
    if not r["ok"]:
        return responses.fail(r["error"])
    _repo().save_state(s.id, day, state["cash"], state)
    return responses.success({
        "status": "pending", "order": r["order"],
        "cash": state["cash"], "positions": state.get("positions") or [],
        "pending": state.get("pending_orders") or [],
        "frozen_cash": state.get("frozen_cash", 0.0)})
```

(b) `backend/src/api/router/replay_router.py` 追加:

```python
@router.post("/sessions/{session_id}/orders")
def _orders(session_id: int, body: dict):
    return h.place_order(session_id, body)
```

- [ ] **Step 4: 运行测试通过**

Run: `cd backend && python -m pytest tests/api/test_replay_exam.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/handler/replay_handler.py backend/src/api/router/replay_router.py backend/tests/api/test_replay_exam.py
git commit -m "feat(replay): 下单端点orders——市价滑点成交/限价入簿冻结/理由必填双端校验"
```

---

### Task 11: handler — 揭晓评分 + 拟真榜

**Files:**
- Modify: `backend/src/api/handler/replay_handler.py`
- Modify: `backend/src/api/router/replay_router.py`
- Test: `backend/tests/api/test_replay_exam.py`(追加)

**Interfaces:**
- Consumes: Task 7 `score`
- Produces:
  - `POST /replay/sessions/{id}/reveal` exam 分支:计算评分存 `state["score"]`,响应 `{id, status, score}`;nav<2 点 fail("评分失败:…");free 响应形状不变(`{id, status}`)
  - `GET /replay/leaderboard` → 前50 `[{id, name, score, excess_score, turnover_score, annual_excess_pct, annual_turnover, days, initial_capital, final}]` 按 score 降序
  - 揭晓后 `_session_dict` 不再脱敏(status != active)

- [ ] **Step 1: 追加失败测试**

```python
class TestExamReveal:
    def test_reveal_scores_and_unmasks(self, client, dyn_symbol, db_conn):
        sid = None
        try:
            r = client.post("/api/v1/replay/sessions", json={
                "mode": "exam", "initial_capital": 100000,
                "length_days": 250, "era_pref": "random"})
            sid = r.json()["data"]["id"]
            client.post(f"/api/v1/replay/sessions/{sid}/pool",
                        json={"symbols": [dyn_symbol]})
            with db_conn.cursor() as cur:
                cur.execute(
                    "UPDATE replay_session "
                    "SET state = jsonb_set(state, '{length_days}', '2') "
                    "WHERE id = %s", (sid,))
                db_conn.commit()
            client.get("/api/v1/replay/advance",
                       params={"session_id": sid, "step": "day"})
            client.get("/api/v1/replay/advance",
                       params={"session_id": sid, "step": "day"})
            r = client.post(f"/api/v1/replay/sessions/{sid}/reveal")
            assert r.json()["code"] == 0, r.text
            d = r.json()["data"]
            assert d["status"] == "revealed"
            sc = d["score"]
            assert 0 <= sc["total"] <= 100
            assert {"excess_score", "turnover_score",
                    "annual_excess_pct", "disclosures"} <= set(sc)
            # 揭晓后元数据不再脱敏
            g = client.get(f"/api/v1/replay/sessions/{sid}").json()["data"]
            assert g["start_date"] is not None
            # 榜上有名
            lb = client.get("/api/v1/replay/leaderboard").json()["data"]
            row = next(x for x in lb if x["id"] == sid)
            assert row["score"] == sc["total"] and row["days"] == 2
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_reveal_without_sailing_fails_gracefully(self, client):
        r = client.post("/api/v1/replay/sessions", json={
            "mode": "exam", "initial_capital": 100000,
            "length_days": 120, "era_pref": "random"})
        sid = r.json()["data"]["id"]
        try:
            x = client.post(f"/api/v1/replay/sessions/{sid}/reveal")
            assert x.json()["code"] != 0  # nav 不足,评分失败但会话仍在
        finally:
            client.delete(f"/api/v1/replay/sessions/{sid}")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/api/test_replay_exam.py -v`
Expected: FAIL — reveal 响应无 score

- [ ] **Step 3: 实现**

(a) handler 顶部追加 import:

```python
from src.domain.replay.scoring import score as _score
```

(b) 替换 `reveal`:

```python
def reveal(session_id: int):
    s = _repo().get(session_id)
    if s is None:
        return responses.fail("会话不存在")
    out = {"id": session_id, "status": "revealed"}
    if (s.mode or "free") == "exam":
        state = s.state
        if not state.get("score"):
            nav = state.get("nav") or []
            if len(nav) < 2:
                return responses.fail("评分失败：还没有走过完整的交易日")
            trades = [_trade_dict(t) for t in _repo().list_trades(session_id)]
            with _conn() as conn, conn.cursor(
                    cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"SELECT {_BAR_COLS} FROM index_ohlcv "
                    "WHERE symbol = %s AND trade_date::date >= %s "
                    "AND trade_date::date <= %s ORDER BY trade_date",
                    (s.benchmark_symbol.lower(), nav[0]["date"],
                     nav[-1]["date"]),
                )
                bench = [_bar(r) for r in cur.fetchall()]
            try:
                state["score"] = _score(nav, bench, trades,
                                        s.initial_capital)
            except ValueError as e:
                return responses.fail(f"评分失败：{e}")
            _repo().save_state(session_id, s.current_date, state["cash"],
                               state)
        out["score"] = state["score"]
    if not _repo().set_status(session_id, "revealed"):
        return responses.fail("会话不存在")
    return responses.success(out)
```

(c) handler 末尾追加:

```python
def leaderboard():
    rows = []
    for s in _repo().list():
        if (s.mode or "free") != "exam" or s.status != "revealed":
            continue
        sc = (s.state or {}).get("score")
        if not sc:
            continue
        nav = (s.state or {}).get("nav") or []
        rows.append({
            "id": s.id, "name": s.name, "score": sc.get("total"),
            "excess_score": sc.get("excess_score"),
            "turnover_score": sc.get("turnover_score"),
            "annual_excess_pct": sc.get("annual_excess_pct"),
            "annual_turnover": sc.get("annual_turnover"),
            "days": len(nav), "initial_capital": s.initial_capital,
            "final": nav[-1]["value"] if nav else None,
        })
    rows.sort(key=lambda r: r["score"] or 0, reverse=True)
    return responses.success(rows[:50])
```

(d) router 追加:

```python
@router.get("/leaderboard")
def _leaderboard():
    return h.leaderboard()
```

- [ ] **Step 4: 运行测试通过**

Run: `cd backend && python -m pytest tests/api/test_replay_exam.py tests/api/test_replay_router.py -v`
Expected: PASS(free reveal 旧测试仍绿)

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/handler/replay_handler.py backend/src/api/router/replay_router.py backend/tests/api/test_replay_exam.py
git commit -m "feat(replay): 揭晓评分入state.score+拟真榜leaderboard前50按总分降序"
```

---

### Task 12: 后端全量回归

**Files:** 无新文件

- [ ] **Step 1: replay 相关全部测试**

Run: `cd backend && python -m pytest tests/api/test_replay_router.py tests/api/test_replay_exam.py tests/domain/test_replay_synthetic.py tests/domain/test_replay_engine.py tests/domain/test_replay_eras.py tests/domain/test_replay_scoring.py -v`
Expected: 全 PASS

- [ ] **Step 2: 后端更大范围冒烟(至少 api + domain 目录)**

Run: `cd backend && python -m pytest tests/api tests/domain -q 2>&1 | tail -5`
Expected: 无新增失败(基线见 `.superpowers/sdd/`;若有与 replay 无关的既有失败,记录并继续——不得修与本计划无关的代码)

- [ ] **Step 3: Commit(如有修复)**

```bash
git add -A backend
git commit -m "test(replay): v3后端全量回归通过"
```

---

### Task 13: 前端类型与请求层(types.ts / api.ts)

**Files:**
- Modify: `frontend/apps/web/src/pages/replay/types.ts`
- Modify: `frontend/apps/web/src/pages/replay/api.ts`

**Interfaces:**
- Consumes: Task 9/10/11 的响应形状(键名一字对应)
- Produces(Task 14-19 全依赖):`SessionMode/SegBar/PendingOrder/ExamEvent/ExamView/OrderResult/LeaderboardRow/ScoreResult` 类型;api 函数 `createExamSession/fetchExamView/advanceExam/addToPool/placeOrder/fetchLeaderboard`

- [ ] **Step 1: types.ts 追加与修改**

(a) 文件头部 `ReplayBar` 之后追加:

```ts
export type SessionMode = 'free' | 'exam';

export interface SegBar {
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface PendingOrder {
  id: string;
  side: 'buy' | 'sell';
  symbol: string;
  shares: number;
  limit_price: number;
  note: string | null;
  placed_day: string;
  frozen: number;
}

export interface ExamEvent {
  type: 'dividend' | 'split' | 'order_cancelled' | 'suspended' | 'info';
  symbol?: string;
  msg: string;
}
```

(b) `SessionMeta` 整体替换为:

```ts
export interface SessionMeta {
  id: number;
  name: string;
  status: 'active' | 'revealed';
  mode: SessionMode;                       // v3: 默认 free
  start_date: string | null;               // v3: exam+active 服务端脱敏为 null
  current_date: string | null;
  day_ordinal?: number | null;             // v3: 仅 exam+active 返回
  length_days?: number | null;
  end_date: string | null;
  initial_capital: number;
  cash: number;
  benchmark_symbol: string;
}
```

(c) `NavPoint` 追加可选字段、`SessionState` 追加 score、`Trade` 追加 order_type:

```ts
export interface NavPoint {
  date: string;
  value: number;
  cash?: number;                 // v3: 日切披露位(评分用)
  pos?: Record<string, number>;
}
```

```ts
export interface ScoreResult {
  total: number;
  excess_score: number;
  turnover_score: number;
  annual_excess_pct: number;
  annual_turnover: number;
  disclosures: {
    max_drawdown: number | null;
    benchmark_max_drawdown: number | null;
    closed_win_rate: number | null;
    closed_trips: number;
    avg_cash_ratio: number | null;
    max_position_weight: number | null;
  };
}
```

`SessionState` 中 `industries?` 行后加 `score?: ScoreResult;`;`Trade` 中 `note?` 行后加 `order_type?: 'market' | 'limit';`。

(d) 文件末尾追加:

```ts
export interface ExamView {
  mode: 'exam';
  day_ordinal: number;
  seg_idx: number;
  seg_count: number;
  date: string;
  travel_complete: boolean;
  segments: Record<string, SegBar[]>;
  partial_bars: Record<string, ReplayBar>;
  indices_segments: Record<string, SegBar[]>;
  indices_partial: Record<string, ReplayBar>;
  cash: number;
  positions: Position[];
  nav: NavPoint[];
  pending: PendingOrder[];
  frozen_cash: number;
  events: ExamEvent[];
  pool: string[];
  names: Record<string, string>;
  industries: Record<string, string>;
  failed?: string[];   // 仅 pool 端点
  fills?: Trade[];     // 仅 advance 响应
}

export interface OrderResult {
  status: 'filled' | 'pending';
  trade?: Trade;
  order?: PendingOrder;
  cash: number;
  positions: Position[];
  pending: PendingOrder[];
  frozen_cash: number;
}

export interface LeaderboardRow {
  id: number;
  name: string;
  score: number;
  excess_score: number;
  turnover_score: number;
  annual_excess_pct: number;
  annual_turnover: number;
  days: number;
  initial_capital: number;
  final: number | null;
}
```

- [ ] **Step 2: api.ts 追加**

`createSession` 导出之后追加:

```ts
export const createExamSession = (body: {
  initial_capital: number; length_days: number; era_pref: string;
  name?: string;
}) => jpost<SessionFull>(`${API}/replay/sessions`, {mode: 'exam', ...body});
export const fetchExamView = (id: number) =>
  jget<ExamView>(`${API}/replay/sessions/${id}/view`);
export const advanceExam = (id: number, step: 'seg' | 'day') =>
  jget<ExamView>(`${API}/replay/advance?session_id=${id}&step=${step}`);
export const addToPool = (id: number, symbols: string[]) =>
  jpost<ExamView>(`${API}/replay/sessions/${id}/pool`, {symbols});
export const placeOrder = (id: number, body: {
  symbol: string; side: 'buy' | 'sell';
  order_type: 'market' | 'limit'; shares: number;
  limit_price?: number; note: string;
}) => jpost<OrderResult>(`${API}/replay/sessions/${id}/orders`, body);
export const fetchLeaderboard = () =>
  jget<LeaderboardRow[]>(`${API}/replay/leaderboard`);
```

同时 `api.ts` 顶部 import type 列表补 `ExamView, LeaderboardRow, OrderResult`。

- [ ] **Step 3: 存量测试不受影响确认**

Run: `cd frontend/apps/web && npm test`
Expected: PASS(types-only 变更,旧用例全绿)

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/pages/replay/types.ts frontend/apps/web/src/pages/replay/api.ts
git commit -m "feat(replay): 前端类型与请求层——ExamView/OrderResult/拟真榜等v3契约"
```

---

### Task 14: store.ts — exam 分支(服务端权威)

**Files:**
- Modify: `frontend/apps/web/src/pages/replay/store.ts`
- Test: `frontend/apps/web/src/pages/replay/__tests__/store.test.ts`(追加)

**Interfaces:**
- Consumes: Task 13 api 函数
- Produces(Task 15-19 依赖):
  - 新状态字段:`mode/segIdx/segCount/dayOrdinal/travelComplete/segments/indicesSegs/pending/frozenCash/examEvents`
  - `advance(step?: 'seg' | 'day')`(free 忽略参数=原日推进;exam 默认 'seg')
  - `placeOrder(side, shares, opts?: {note?/orderType?/limitPrice?})`
  - 模块导出 `mergeExamView(st: ReplayStore, v: ExamView): Partial<ReplayStore>`(纯函数,测试直接用)
  - `saveNow` 对 exam no-op;`openSession/reveal` exam 分支;`addSymbol/addSymbols` 走 `api.addToPool`

- [ ] **Step 1: 追加失败测试**

`__tests__/store.test.ts`:mock 工厂(`vi.mock('../api', ...)`)内追加:

```ts
  fetchExamView: vi.fn(),
  advanceExam: vi.fn(),
  addToPool: vi.fn(),
  placeOrder: vi.fn(),
  fetchLeaderboard: vi.fn().mockResolvedValue({code: 0, msg: 'ok', data: []}),
```

`seedSession` 改为带 `mode: 'free' as const`。文件末尾追加:

```ts
describe('exam 模式(服务端权威)', () => {
  const examSession = {
    ...seedSession, mode: 'exam' as const,
    start_date: null, current_date: null,
    day_ordinal: 1, length_days: 120,
  };
  const seg = (c: number) => ({open: c, high: c, low: c, close: c});
  const view = {
    mode: 'exam' as const, day_ordinal: 1, seg_idx: 0, seg_count: 8,
    date: '2020-03-13', travel_complete: false,
    segments: {'600519': [seg(10)]},
    partial_bars: {'600519': bar('2020-03-13', 10)},
    indices_segments: {}, indices_partial: {},
    cash: 1e5, positions: [], nav: [],
    pending: [], frozen_cash: 0, events: [],
    pool: ['600519'], names: {'600519': 'X'}, industries: {},
  };

  beforeEach(() => {
    vi.mocked(api.fetchExamView).mockResolvedValue(
      {code: 0, msg: 'ok', data: view});
  });

  it('openSession hydrate:历史K线止于昨日+今日partial', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      {code: 0, msg: 'ok', data: examSession});
    // 历史 asof 应为 2020-03-12(防当日收盘泄露)
    await useReplayStore.getState().openSession(7);
    expect(api.fetchKline).toHaveBeenCalledWith('600519', '2020-03-12');
    const s = useReplayStore.getState();
    expect(s.mode).toBe('exam');
    expect(s.dates[s.dates.length - 1]).toBe('2020-03-13');
    expect(s.barsBySymbol['600519'].slice(-1)[0].close).toBe(10);
    expect(s.segIdx).toBe(0);
  });

  it('advance seg:合并fills与段数据', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      {code: 0, msg: 'ok', data: examSession});
    await useReplayStore.getState().openSession(7);
    vi.mocked(api.advanceExam).mockResolvedValue({code: 0, msg: 'ok', data: {
      ...view, seg_idx: 1, segments: {'600519': [seg(10), seg(10.2)]},
      partial_bars: {'600519': bar('2020-03-13', 10.2)},
      fills: [{trade_date: '2020-03-13', symbol: '600519',
               side: 'buy', price: 10.1, shares: 100, fee: 5, tax: 0,
               note: 't', order_type: 'market'}],
      positions: [{symbol: '600519', shares: 100, cost_price: 10.1,
                   buy_date: '2020-03-13'}],
      cash: 98995,
    }});
    await useReplayStore.getState().advance();
    expect(api.advanceExam).toHaveBeenCalledWith(7, 'seg');
    const s = useReplayStore.getState();
    expect(s.segIdx).toBe(1);
    expect(s.trades).toHaveLength(1);
    expect(s.positions[0].shares).toBe(100);
  });

  it('placeOrder 走服务端,不再本地撮合', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      {code: 0, msg: 'ok', data: examSession});
    await useReplayStore.getState().openSession(7);
    useReplayStore.setState({selectedSymbol: '600519'});
    vi.mocked(api.placeOrder).mockResolvedValue({code: 0, msg: 'ok', data: {
      status: 'filled',
      trade: {trade_date: '2020-03-13', symbol: '600519', side: 'buy',
              price: 10.1, shares: 100, fee: 5, tax: 0, note: 'n',
              order_type: 'market'},
      cash: 98995,
      positions: [{symbol: '600519', shares: 100, cost_price: 10.1,
                   buy_date: '2020-03-13'}],
      pending: [], frozen_cash: 0,
    }});
    const ok = await useReplayStore.getState().placeOrder('buy', 100,
      {note: 'n'});
    expect(ok).toBe(true);
    expect(api.placeOrder).toHaveBeenCalled();
    expect(api.addTrade).not.toHaveBeenCalled();
    expect(useReplayStore.getState().cash).toBe(98995);
  });

  it('saveNow 对 exam no-op', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      {code: 0, msg: 'ok', data: examSession});
    await useReplayStore.getState().openSession(7);
    await useReplayStore.getState().saveNow();
    expect(api.saveState).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend/apps/web && npm test`
Expected: FAIL — mode 属性不存在、advance 未调 advanceExam

- [ ] **Step 3: 实现 store.ts 改造**

(a) import 区:现有 import(`create/api/computeNav/tryFill/...`)全部保留——free 分支仍走本地 `tryFill` 撮合(行为不变原则);仅把 `import type {...} from './types';` 一行替换为:

```ts
import type {
  ExamEvent, ExamView, NavPoint, PendingOrder, Position, ReplayBar,
  SegBar, SessionMeta, SessionMode, Trade,
} from './types';
```

(b) `ReplayStore` 接口:字段区(`advancing: boolean;` 之后)追加:

```ts
  // ── v3 拟真考核(服务端权威) ──
  mode: SessionMode;
  segIdx: number;
  segCount: number;
  dayOrdinal: number;
  travelComplete: boolean;
  segments: Record<string, SegBar[]>;
  indicesSegs: Record<string, SegBar[]>;
  pending: PendingOrder[];
  frozenCash: number;
  examEvents: ExamEvent[];
```

方法签名替换:

```ts
  advance: (step?: 'seg' | 'day') => Promise<void>;
  placeOrder: (side: 'buy' | 'sell', shares: number, opts?: {
    note?: string;
    orderType?: 'market' | 'limit';
    limitPrice?: number;
  }) => Promise<boolean>;
```

(c) 模块级(store 创建之前)追加:

```ts
const dayBefore = (iso: string): string => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
};

/** exam advance/view 响应 → store 增量(纯函数,测试直用)。 */
export const mergeExamView = (st: ReplayStore, v: ExamView) => {
  const dates = [...st.dates];
  if (v.date > (dates[dates.length - 1] ?? '')) dates.push(v.date);
  const mergePartial = (
    src: Record<string, ReplayBar[]>, patch: Record<string, ReplayBar>,
  ): Record<string, ReplayBar[]> => {
    const out = {...src};
    for (const [sym, pb] of Object.entries(patch)) {
      const arr = out[sym] ? [...out[sym]] : [];
      if (arr.length && arr[arr.length - 1].trade_date === pb.trade_date) {
        arr[arr.length - 1] = pb;
      } else {
        arr.push(pb);
      }
      out[sym] = arr;
    }
    return out;
  };
  const indexBars = mergePartial(st.indexBars, v.indices_partial);
  return {
    dates,
    cursor: dates.length - 1,
    barsBySymbol: mergePartial(st.barsBySymbol, v.partial_bars),
    indexBars,
    benchmarkBars: st.session
      ? indexBars[st.session.benchmark_symbol] ?? st.benchmarkBars
      : st.benchmarkBars,
    segments: v.segments,
    indicesSegs: v.indices_segments,
    segIdx: v.seg_idx,
    dayOrdinal: v.day_ordinal,
    cash: v.cash,
    positions: v.positions,
    nav: v.nav,
    pending: v.pending,
    frozenCash: v.frozen_cash,
    examEvents: v.events,
    travelComplete: v.travel_complete,
    trades: v.fills ? [...st.trades, ...v.fills] : st.trades,
    error: v.travel_complete ? '已到旅程终点，可揭晓复盘' : null,
    playing: v.travel_complete ? false : st.playing,
  };
};
```

(d) 初始 state(`error: null,` 后)与 `closeSession` 的 reset set 中各追加:

```ts
    mode: 'free',
    segIdx: 0,
    segCount: 8,
    dayOrdinal: 0,
    travelComplete: false,
    segments: {},
    indicesSegs: {},
    pending: [],
    frozenCash: 0,
    examEvents: [],
```

(e) `openSession`:`const sess = sj.data;` 之后插入 exam 分支(之后原 free 逻辑不动,并在其 set 中补 `mode: 'free',`):

```ts
      if (sess.mode === 'exam') {
        const vj = await api.fetchExamView(id);
        if (vj.code !== 0) {
          set({error: vj.msg || '拟真视图加载失败'});
          return;
        }
        const v = vj.data;
        const asof = dayBefore(v.date); // 历史 K 线止于昨日,防当日收盘泄露
        const barsBySymbol: Record<string, ReplayBar[]> = {};
        for (const sym of v.pool) {
          const kj = await api.fetchKline(sym, asof);
          if (kj.code === 0) barsBySymbol[sym] = kj.data.bars;
          const pb = v.partial_bars[sym];
          if (pb) barsBySymbol[sym] = [...(barsBySymbol[sym] ?? []), pb];
        }
        const idxArr = await Promise.all(INDEX_SYMBOLS.map(
          (s) => api.fetchKline(s, asof)));
        const indexBars: Record<string, ReplayBar[]> = {};
        INDEX_SYMBOLS.forEach((s, i) => {
          if (idxArr[i].code !== 0) return;
          indexBars[s] = [...idxArr[i].data.bars];
          const pb = v.indices_partial[s];
          if (pb) indexBars[s] = [...indexBars[s], pb];
        });
        const tj = await api.listTrades(id);
        const dates = (indexBars[sess.benchmark_symbol] ?? [])
          .map((b) => b.trade_date);
        set({
          session: sess, phase: 'sailing', mode: 'exam',
          dates, cursor: Math.max(0, dates.length - 1),
          pool: v.pool, names: v.names, industries: v.industries,
          barsBySymbol, indexBars,
          indicesSegs: v.indices_segments, segments: v.segments,
          benchmarkBars: indexBars[sess.benchmark_symbol] ?? [],
          segIdx: v.seg_idx, segCount: v.seg_count,
          dayOrdinal: v.day_ordinal, travelComplete: v.travel_complete,
          cash: v.cash, positions: v.positions, nav: v.nav,
          pending: v.pending, frozenCash: v.frozen_cash,
          examEvents: v.events,
          trades: tj.code === 0 ? tj.data : [],
          selectedSymbol: v.pool[0] ?? null, error: null,
        });
        return;
      }
```

(f) `advance`:在 `set({advancing: true});` 与 `try {` 之后、原 `const r = await api.fetchAdvance(...)` 之前插入:

```ts
        if (s.mode === 'exam') {
          const r = await api.advanceExam(s.session.id, step ?? 'seg');
          if (r.code !== 0) {
            set({error: r.msg || '推进失败', playing: false});
            return;
          }
          set(mergeExamView(get(), r.data));
          return;
        }
```

(g) `placeOrder` 整体替换:

```ts
    placeOrder: async (side, shares, opts) => {
      const s = get();
      const symbol = s.selectedSymbol;
      if (!s.session || !symbol) return false;
      if (s.cursor < s.dates.length - 1) {
        set({error: '回看状态不能交易'});
        return false;
      }
      if (s.mode === 'exam') {
        if (s.travelComplete) {
          set({error: '旅程已走完，请揭晓复盘'});
          return false;
        }
        const r = await api.placeOrder(s.session.id, {
          symbol, side, order_type: opts?.orderType ?? 'market', shares,
          ...(opts?.orderType === 'limit' && opts?.limitPrice != null
            ? {limit_price: opts.limitPrice} : {}),
          note: (opts?.note ?? '').trim(),
        });
        if (r.code !== 0) {
          set({error: r.msg || '下单失败'});
          return false;
        }
        const d = r.data;
        set({
          cash: d.cash, positions: d.positions, pending: d.pending,
          frozenCash: d.frozen_cash, error: null,
          ...(d.status === 'filled' && d.trade
            ? {trades: [...get().trades, d.trade]} : {}),
        });
        return true;
      }
      // ↓ free:原逻辑(note 取 opts?.note)
      const date = s.dates[s.cursor];
      const bars = s.barsBySymbol[symbol] ?? [];
      const i = bars.findIndex((b) => b.trade_date === date);
      if (i < 0) {
        set({error: '当日停牌，无法成交'});
        return false;
      }
      const prevClose = i > 0 ? bars[i - 1].close : bars[i].open;
      const r = tryFill(
        {cash: s.cash, positions: s.positions},
        {symbol, side, shares, note: opts?.note},
        {date, close: bars[i].close, prevClose, name: s.names[symbol]},
      );
      if (!r.ok) {
        set({error: r.error});
        return false;
      }
      set({cash: r.cash, positions: r.positions,
           trades: [...s.trades, r.trade], error: null});
      await api.addTrade(s.session.id, r.trade);
      await get().saveNow();
      return true;
    },
```

(h) `addSymbol` 开头(`const s = get();` 后)插入:

```ts
      if (s.mode === 'exam') {
        const r = await api.addToPool(s.session.id, [symbol]);
        if (r.code !== 0) {
          set({error: r.msg || '入池失败'});
          return;
        }
        set(mergeExamView(get(), r.data));
        return;
      }
```

`addSymbols` 不改(exam 下逐只走 addSymbol 即可,批量优化非目标)。

(i) `saveNow` 开头插入:

```ts
      if (s.mode === 'exam') return; // 服务端权威,不外部存档
```

(j) `reveal`:`if (s.session.status !== 'revealed') {...}` 块之后插入:

```ts
      if (s.mode === 'exam') {
        // 揭晓后服务端不再脱敏,重取真实日期
        const sj2 = await api.getSession(s.session.id);
        if (sj2.code === 0) set({session: sj2.data});
      }
```

并把 `reveal` 内 `const asof = st.session!.end_date ?? new Date()...` 改为:

```ts
      const st = get();
      const asof = st.session!.end_date
        ?? st.session!.current_date
        ?? new Date().toISOString().slice(0, 10);
```

- [ ] **Step 4: 运行测试通过**

Run: `cd frontend/apps/web && npm test`
Expected: PASS(新旧用例全绿)

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/replay/store.ts frontend/apps/web/src/pages/replay/__tests__/store.test.ts
git commit -m "feat(replay): store exam分支——服务端权威hydrate/段级advance/下单与入池走服务端/saveNow豁免"
```

---

### Task 15: BlindMask 脱敏 + 图表/组件接入

**Files:**
- Create: `frontend/apps/web/src/pages/replay/BlindMask.tsx`
- Modify: `frontend/apps/web/src/pages/replay/ReplayKlineChart.tsx`
- Modify: `frontend/apps/web/src/pages/replay/TopBar.tsx`
- Modify: `frontend/apps/web/src/pages/replay/EraBar.tsx`
- Test: `frontend/apps/web/src/pages/replay/__tests__/blindmask.test.ts`(新建)

**Interfaces:**
- Produces:
  - `dayLabelOf(blind: boolean, dates: string[], d: string): string`(纯函数)
  - `useBlind(): boolean`、`useDayLabel(): (d: string) => string`(hooks)
  - `ReplayKlineChartProps` 增 `labelFor?: (d: string) => string`(applyOptions 动态改轴,不重建图表)

- [ ] **Step 1: 写失败测试**

新建 `__tests__/blindmask.test.ts`:

```ts
import {describe, expect, it} from 'vitest';
import {dayLabelOf} from '../BlindMask';

describe('dayLabelOf', () => {
  const dates = ['2020-03-13', '2020-03-16', '2020-03-17'];
  it('盲盒中渲染为第N天', () => {
    expect(dayLabelOf(true, dates, '2020-03-13')).toBe('第1天');
    expect(dayLabelOf(true, dates, '2020-03-17')).toBe('第3天');
  });
  it('非盲盒原样返回;未知日期原样返回', () => {
    expect(dayLabelOf(false, dates, '2020-03-13')).toBe('2020-03-13');
    expect(dayLabelOf(true, dates, '2020-03-20')).toBe('2020-03-20');
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend/apps/web && npm test`
Expected: FAIL — Cannot find module '../BlindMask'

- [ ] **Step 3: 实现**

新建 `BlindMask.tsx`:

```tsx
import {useCallback} from 'react';
import {useReplayStore} from './store';

/** exam+active 期间真实日期 → 「第N天」;其余场景原样。 */
export const dayLabelOf = (
  blind: boolean, dates: string[], d: string,
): string => {
  if (!blind) return d;
  const i = dates.indexOf(d);
  return i < 0 ? d : `第${i + 1}天`;
};

export const useBlind = (): boolean => {
  const session = useReplayStore((s) => s.session);
  return !!session && session.mode === 'exam' && session.status === 'active';
};

export const useDayLabel = (): ((d: string) => string) => {
  const blind = useBlind();
  const dates = useReplayStore((s) => s.dates);
  return useCallback(
    (d: string) => dayLabelOf(blind, dates, d), [blind, dates]);
};
```

`ReplayKlineChart.tsx`:props 接口加字段;模块顶部 `toTime` 之后加:

```ts
const labelFromTs = (t: unknown, f: (d: string) => string) =>
  f(new Date((t as number) * 1000).toISOString().slice(0, 10));
```

组件参数解构加 `labelFor`;`useEffect([height])` 的**后面**追加新 effect(不在建图 effect 里做,避免 labelFor 变化重建图表):

```tsx
  useEffect(() => {
    chartRef.current?.applyOptions(labelFor ? {
      localization: {
        timeFormatter: (t: unknown) => labelFromTs(t, labelFor),
      },
    } : {});
  }, [labelFor]);
```

`TopBar.tsx`:import `useDayLabel`;`const dayLabel = useDayLabel();`;`日期<b>{vd}</b>` 改 `日期<b>{dayLabel(vd)}</b>`。

`EraBar.tsx`:import `useBlind, useDayLabel`;组件内:

```tsx
  const blind = useBlind();
  const dayLabel = useDayLabel();
```

chip 渲染 `{e.date} {e.title}` 改 `{dayLabel(e.date)} {e.title}`;新闻行 ` — {n.source} {mmdd(n.published_at)}` 改 ` — {n.source}{blind ? '' : ` ${mmdd(n.published_at)}`}`。

- [ ] **Step 4: 运行测试通过 + Cockpit 接线**

`Cockpit.tsx`(本步一并改):import `useDayLabel` 与(若 Task 16 尚未做,先只接 labelFor):

```tsx
  const dayLabel = useDayLabel();
```

`<ReplayKlineChart bars={vis} height={460} />` 改 `<ReplayKlineChart bars={vis} height={460} labelFor={dayLabel} />`。

Run: `cd frontend/apps/web && npm test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/replay/
git commit -m "feat(replay): 盲盒脱敏BlindMask——useDayLabel贯穿TopBar/EraBar/K线轴(applyOptions动态改不重建)"
```

---

### Task 16: IntradayStrip + EventCard(分时条与事件卡)

**Files:**
- Create: `frontend/apps/web/src/pages/replay/IntradayStrip.tsx`
- Create: `frontend/apps/web/src/pages/replay/EventCard.tsx`
- Modify: `frontend/apps/web/src/pages/replay/Cockpit.tsx`
- Test: `frontend/apps/web/src/pages/replay/__tests__/intraday.test.ts`(新建)

**Interfaces:**
- Produces:
  - `computeScale(segs: SegBar[], prevClose: number | null) -> {lo: number; hi: number}`(纯函数)
  - `<IntradayStrip segs segCount prevClose height? />`、`<EventCard />`(读 store)
  - Cockpit:exam 时图表上方渲染分时条、右列 OrderTicket 下渲染事件卡

- [ ] **Step 1: 写失败测试**

新建 `__tests__/intraday.test.ts`:

```ts
import {describe, expect, it} from 'vitest';
import {computeScale} from '../IntradayStrip';

describe('computeScale', () => {
  const seg = (c: number) => ({open: c, high: c + 1, low: c - 1, close: c});
  it('范围覆盖段高低与昨收,含边距', () => {
    const {lo, hi} = computeScale([seg(10), seg(11)], 10.5);
    expect(lo).toBeLessThan(9);
    expect(hi).toBeGreaterThan(12);
  });
  it('一字段也能出有限刻度', () => {
    const {lo, hi} = computeScale([{open: 5, high: 5, low: 5, close: 5}], 5);
    expect(lo).toBeLessThan(5);
    expect(hi).toBeGreaterThan(5);
    expect(Number.isFinite(lo) && Number.isFinite(hi)).toBe(true);
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend/apps/web && npm test`
Expected: FAIL — module 不存在

- [ ] **Step 3: 实现**

新建 `IntradayStrip.tsx`(颜色复用 chartTheme,A股红涨绿跌):

```tsx
import {colorDown, colorUp} from '../../lib/chartTheme';
import type {SegBar} from './types';

export const computeScale = (
  segs: SegBar[], prevClose: number | null,
): {lo: number; hi: number} => {
  const lows = segs.map((s) => s.low);
  const highs = segs.map((s) => s.high);
  if (prevClose != null) {
    lows.push(prevClose);
    highs.push(prevClose);
  }
  let lo = Math.min(...lows);
  let hi = Math.max(...highs);
  const pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.01 || 1;
  lo -= pad;
  hi += pad;
  return {lo, hi};
};

export const IntradayStrip: React.FC<{
  segs: SegBar[];
  segCount: number;
  prevClose: number | null;
  height?: number;
}> = ({segs, segCount, prevClose, height = 64}) => {
  if (segs.length === 0) return null;
  const W = 100;
  const {lo, hi} = computeScale(segs, prevClose);
  const x = (i: number) => (i / (segCount - 1)) * W;
  const y = (v: number) => ((hi - v) / (hi - lo)) * 100;
  const pts = segs.map((s, i) => `${x(i)},${y(s.close)}`).join(' ');
  const cur = segs[segs.length - 1];
  const up = cur.close >= (prevClose ?? cur.close);
  const color = up ? colorUp : colorDown;
  return (
    <svg viewBox={`0 0 ${W} 100`} preserveAspectRatio="none"
      style={{width: '100%', height}} role="img" aria-label="当日分时">
      {prevClose != null && (
        <line x1={0} x2={W} y1={y(prevClose)} y2={y(prevClose)}
          stroke="#6e6e73" strokeDasharray="3 3" strokeWidth={0.5} />
      )}
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.2} />
      <circle cx={x(segs.length - 1)} cy={y(cur.close)} r={1.6}
        fill={color} />
      {Array.from({length: segCount}, (_, i) =>
        i < segs.length ? null : (
          <line key={i} x1={x(i)} x2={x(i)} y1={46} y2={54}
            stroke="#6e6e73" strokeWidth={0.3} />
        ))}
    </svg>
  );
};
```

新建 `EventCard.tsx`:

```tsx
import {useReplayStore} from './store';

const ICON: Record<string, string> = {
  dividend: '💰', split: '🎁', order_cancelled: '↩️',
  suspended: '⏸', info: 'ℹ️',
};

export const EventCard: React.FC = () => {
  const events = useReplayStore((s) => s.examEvents);
  const pending = useReplayStore((s) => s.pending);
  if (events.length === 0 && pending.length === 0) return null;
  return (
    <div className="replay-panel">
      <h4>今日事件 · 挂单</h4>
      {events.map((e, i) => (
        <div key={i} className="replay-hint"
          style={{textAlign: 'left', marginBottom: 2}}>
          {ICON[e.type] ?? '·'} {e.symbol ? `${e.symbol} ` : ''}{e.msg}
        </div>
      ))}
      {pending.map((o) => (
        <div key={o.id} className="replay-hint"
          style={{textAlign: 'left', marginBottom: 2}}>
          📌 限价{o.side === 'buy' ? '买' : '卖'} {o.shares}股 @{' '}
          {o.limit_price}
        </div>
      ))}
    </div>
  );
};
```

`Cockpit.tsx`:import 三件(`IntradayStrip/EventCard` + store 已有);组件内加 selector 与昨收计算:

```tsx
  const mode = useReplayStore((s) => s.mode);
  const segments = useReplayStore((s) => s.segments);
  const segCount = useReplayStore((s) => s.segCount);
  const prevClose = useMemo(() => {
    const hist = bars.filter((b) => !vd || b.trade_date < vd);
    return hist.length ? hist[hist.length - 1].close : null;
  }, [bars, vd]);
```

图表面板 `{symbol ? <ReplayKlineChart .../> : ...}` 上方插入:

```tsx
            {mode === 'exam' && symbol && (
              <IntradayStrip segs={segments[symbol] ?? []}
                segCount={segCount} prevClose={prevClose} />
            )}
```

右列 `<OrderTicket />` 之后加 `<EventCard />`。

- [ ] **Step 4: 运行测试通过**

Run: `cd frontend/apps/web && npm test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/replay/
git commit -m "feat(replay): 当日8段分时条IntradayStrip+今日事件/挂单卡EventCard接入驾驶舱"
```

---

### Task 17: OrderTicket — 市价/限价 + 理由必填(exam)

**Files:**
- Modify: `frontend/apps/web/src/pages/replay/OrderTicket.tsx`(整体替换)
- Test: `frontend/apps/web/src/pages/replay/__tests__/order-ticket.test.ts`(新建,只测纯函数)

**Interfaces:**
- Consumes: Task 14 `placeOrder(side, shares, opts)`;store `segments/segIdx`
- Produces: `validateExamOrder(note, orderType, limitPrice) -> string | null`(导出纯函数)

- [ ] **Step 1: 写失败测试**

新建 `__tests__/order-ticket.test.ts`:

```ts
import {describe, expect, it} from 'vitest';
import {validateExamOrder} from '../OrderTicket';

describe('validateExamOrder', () => {
  it('理由必填且≤140字', () => {
    expect(validateExamOrder('', 'market', null)).toContain('理由');
    expect(validateExamOrder('  ', 'market', null)).toContain('理由');
    expect(validateExamOrder('a'.repeat(141), 'market', null))
      .toContain('理由');
    expect(validateExamOrder('低吸', 'market', null)).toBeNull();
  });
  it('限价必须为正数', () => {
    expect(validateExamOrder('挂单', 'limit', null)).toContain('限价');
    expect(validateExamOrder('挂单', 'limit', 0)).toContain('限价');
    expect(validateExamOrder('挂单', 'limit', 10.5)).toBeNull();
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend/apps/web && npm test`
Expected: FAIL — module 导出不存在

- [ ] **Step 3: 实现(整体替换 OrderTicket.tsx)**

```tsx
import {useMemo, useState} from 'react';
import {useDayLabel, useReplayStore, viewDate} from './store';
import type {ReplayBar} from './types';

// selector 必须返回稳定引用:zustand v5 直接透传 useSyncExternalStore,
// 每次返回新数组会被 React 判定为快照持续变化,触发无限重渲染
const NO_BARS: ReplayBar[] = [];

/** exam 下单前端校验(后端仍硬校验)。 */
export const validateExamOrder = (
  note: string,
  orderType: 'market' | 'limit',
  limitPrice: number | null,
): string | null => {
  const n = note.trim();
  if (n.length < 1 || n.length > 140) return '下单理由必填（1~140 字）';
  if (orderType === 'limit' && (limitPrice == null || !(limitPrice > 0))) {
    return '限价应为正数';
  }
  return null;
};

export const OrderTicket: React.FC = () => {
  const symbol = useReplayStore((s) => s.selectedSymbol);
  const names = useReplayStore((s) => s.names);
  const industries = useReplayStore((s) => s.industries);
  const cash = useReplayStore((s) => s.cash);
  const frozenCash = useReplayStore((s) => s.frozenCash);
  const positions = useReplayStore((s) => s.positions);
  const pending = useReplayStore((s) => s.pending);
  const mode = useReplayStore((s) => s.mode);
  const segments = useReplayStore((s) => s.segments);
  const bars = useReplayStore((s) =>
    (s.selectedSymbol ? s.barsBySymbol[s.selectedSymbol] : undefined) ??
    NO_BARS);
  const vd = useReplayStore(viewDate);
  const dayLabel = useDayLabel();
  const atLatest = useReplayStore((s) => s.cursor === s.dates.length - 1);
  const placeOrder = useReplayStore((s) => s.placeOrder);
  const [shares, setShares] = useState(100);
  const [note, setNote] = useState('');
  const [orderType, setOrderType] = useState<'market' | 'limit'>('market');
  const [limitPrice, setLimitPrice] = useState('');
  const [busy, setBusy] = useState(false);

  const vis = useMemo(
    () => bars.filter((b) => !vd || b.trade_date <= vd),
    [bars, vd],
  );
  const lastVis = vis[vis.length - 1];
  const today = lastVis && lastVis.trade_date === vd ? lastVis : null;
  const exam = mode === 'exam';
  const segs = exam && symbol ? segments[symbol] : undefined;
  const curPrice = segs && segs.length ? segs[segs.length - 1].close
    : today ? today.close : null;
  const frozenSell = pending
    .filter((o) => o.symbol === symbol && o.side === 'sell')
    .reduce((a, o) => a + o.shares, 0);
  const pos = positions.find((p) => p.symbol === symbol);
  const sellable = pos && vd && pos.buy_date < vd
    ? pos.shares - frozenSell : 0;
  const maxBuy = curPrice
    ? Math.floor((exam ? cash - frozenCash : cash) / (curPrice * 100)) * 100
    : 0;

  const submit = async (side: 'buy' | 'sell') => {
    if (exam) {
      const err = validateExamOrder(
        note, orderType,
        orderType === 'limit' ? Number(limitPrice) : null);
      if (err) return; // 按钮已 disable,双保险
    }
    setBusy(true);
    const ok = await placeOrder(side, shares, exam
      ? {
        note,
        orderType,
        ...(orderType === 'limit'
          ? {limitPrice: Number(limitPrice)} : {}),
      }
      : {note: note || undefined});
    if (ok) setNote('');
    setBusy(false);
  };

  const invalid = exam
    ? validateExamOrder(
      note, orderType, orderType === 'limit' ? Number(limitPrice) : null)
    : null;

  if (!symbol) {
    return (
      <div className="replay-panel">
        <h4>下单台</h4>
        <div className="replay-hint">先在左侧选一只股票。</div>
      </div>
    );
  }
  return (
    <div className="replay-panel">
      <h4>下单台 · {names[symbol] ?? ''} {symbol}
        {industries[symbol] && (
          <span className="replay-ind-tag">{industries[symbol]}</span>
        )}
      </h4>
      <div className="replay-hint" style={{marginBottom: 8}}>
        {exam
          ? `${dayLabel(vd)} 现价 ¥${curPrice?.toFixed(2) ?? '—'}`
          : today
            ? `${vd} 收盘价 ¥${today.close.toFixed(2)}（尾盘价成交）`
            : `${vd} 停牌/无数据`}
      </div>
      {exam && (
        <div style={{display: 'flex', gap: 8, marginBottom: 8}}>
          {(['market', 'limit'] as const).map((t) => (
            <button key={t}
              className={`replay-btn${orderType === t ? ' primary' : ''}`}
              style={{flex: 1}}
              onClick={() => {
                setOrderType(t);
                if (t === 'limit' && !limitPrice && curPrice != null) {
                  setLimitPrice(curPrice.toFixed(2));
                }
              }}>
              {t === 'market' ? '市价' : '限价'}
            </button>
          ))}
        </div>
      )}
      {exam && orderType === 'limit' && (
        <input className="replay-input" type="number" min={0.01} step={0.01}
          value={limitPrice}
          onChange={(e) => setLimitPrice(e.target.value)}
          placeholder="限价（当日涨跌停区间内）" />
      )}
      <input className="replay-input" type="number" min={100} step={100}
        value={shares} onChange={(e) => setShares(Number(e.target.value))}
        placeholder="股数（100 的整数倍）" />
      <input className="replay-input" value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder={exam ? '下单理由（必填，≤140字，复盘回看）'
          : '下单理由（复盘时回看，可空）'} />
      <div className="replay-hint" style={{marginBottom: 8}}>
        可买 {Math.max(0, maxBuy)} 股 · 可卖 {Math.max(0, sellable)} 股
        {exam ? '（T+1，含挂单冻结）' : '（T+1）'}
      </div>
      <div style={{display: 'flex', gap: 8}}>
        <button className="replay-btn buy" style={{flex: 1}}
          disabled={busy || !atLatest || !curPrice || !!invalid}
          onClick={() => void submit('buy')}>
          买入
        </button>
        <button className="replay-btn sell" style={{flex: 1}}
          disabled={busy || !atLatest || !curPrice || !!invalid
            || sellable <= 0}
          onClick={() => void submit('sell')}>
          卖出
        </button>
      </div>
      {invalid && (
        <div className="replay-hint" style={{marginTop: 6, color: '#e0413e'}}>
          {invalid}
        </div>
      )}
      {!atLatest && (
        <div className="replay-hint" style={{marginTop: 6}}>
          回看中，回到最新一天才能交易。
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 4: 运行测试通过**

Run: `cd frontend/apps/web && npm test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/replay/OrderTicket.tsx frontend/apps/web/src/pages/replay/__tests__/order-ticket.test.ts
git commit -m "feat(replay): 下单台升级——exam市价/限价切换+现价成交口径+理由必填双端校验"
```

---

### Task 18: PlayControls 段级推进 + SessionHome 模式选择与拟真榜

**Files:**
- Modify: `frontend/apps/web/src/pages/replay/PlayControls.tsx`(整体替换)
- Modify: `frontend/apps/web/src/pages/replay/SessionHome.tsx`(整体替换)

**Interfaces:**
- Consumes: Task 14 `advance(step)`;api `createExamSession/fetchLeaderboard`
- Produces:exam 播放控件(下一时段/快进到明日);首页 free/exam 双表单 + 拟真榜面板

- [ ] **Step 1: 替换 PlayControls.tsx**

```tsx
import {useEffect} from 'react';
import {useReplayStore} from './store';

export const PlayControls: React.FC = () => {
  const playing = useReplayStore((s) => s.playing);
  const speed = useReplayStore((s) => s.speed);
  const cursor = useReplayStore((s) => s.cursor);
  const datesLen = useReplayStore((s) => s.dates.length);
  const mode = useReplayStore((s) => s.mode);
  const segIdx = useReplayStore((s) => s.segIdx);
  const segCount = useReplayStore((s) => s.segCount);
  const travelComplete = useReplayStore((s) => s.travelComplete);
  const {advance, stepBack, play, pause, setSpeed} =
    useReplayStore.getState();

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {
      void useReplayStore.getState().advance();
    }, 1000 / speed);
    return () => clearInterval(t);
  }, [playing, speed]);

  const atReview = cursor < datesLen - 1;
  const exam = mode === 'exam';
  return (
    <div className="replay-panel replay-controls">
      <button className="replay-btn" disabled={cursor <= 0}
        onClick={stepBack} title="回看一天（只看不许交易）">
        ◀
      </button>
      <button className="replay-btn primary"
        disabled={travelComplete}
        onClick={() => void advance(exam ? 'seg' : undefined)}>
        {exam ? `下一时段 ▶ (${segIdx + 1}/${segCount})` : '下一天 ▶'}
      </button>
      {exam && (
        <button className="replay-btn" disabled={travelComplete}
          title="快进:走完今日剩余时段(挂单照常检查),跳到明日开盘"
          onClick={() => void advance('day')}>
          快进到明日 ⏭
        </button>
      )}
      <button className="replay-btn"
        disabled={travelComplete}
        onClick={() => (playing ? pause() : play())}>
        {playing ? '⏸ 暂停' : '▶ 自动'}
      </button>
      {([1, 2, 4] as const).map((v) => (
        <button key={v}
          className={`replay-btn${speed === v ? ' primary' : ''}`}
          onClick={() => setSpeed(v)}>
          {v}x
        </button>
      ))}
      {atReview && <span className="replay-hint">回看中（不可交易）</span>}
    </div>
  );
};
```

- [ ] **Step 2: 替换 SessionHome.tsx**

```tsx
import {useCallback, useEffect, useState} from 'react';
import {StateView} from '../../components/ui';
import * as api from './api';
import {useReplayStore} from './store';
import type {LeaderboardRow, SessionMeta} from './types';

const fmtMoney = (v: number) =>
  v.toLocaleString('zh-CN', {maximumFractionDigits: 0});

const LENGTHS = [
  {v: 120, label: '半年(120日)'},
  {v: 250, label: '一年(250日)'},
  {v: 500, label: '两年(500日)'},
];
const ERAS = [
  {v: 'random', label: '完全随机'},
  {v: 'bull_top', label: '牛顶区'},
  {v: 'bear_bottom', label: '熊底区'},
  {v: 'range', label: '震荡区'},
];

export const SessionHome: React.FC = () => {
  const openSession = useReplayStore((s) => s.openSession);
  const [list, setList] = useState<SessionMeta[] | null>(null);
  const [board, setBoard] = useState<LeaderboardRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'free' | 'exam'>('free');
  // free 表单
  const [name, setName] = useState('');
  const [startDate, setStartDate] = useState('2020-01-02');
  const [endDate, setEndDate] = useState('');
  const [capital, setCapital] = useState(1000000);
  // exam 表单
  const [exCapital, setExCapital] = useState(100000);
  const [exLength, setExLength] = useState(250);
  const [exEra, setExEra] = useState('random');
  const [exName, setExName] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const r = await api.listSessions();
    if (r.code === 0) setList(r.data);
    else setError(r.msg || '加载失败');
    const b = await api.fetchLeaderboard();
    if (b.code === 0) setBoard(b.data);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const createFree = async () => {
    if (!name.trim()) {
      setError('给旅程起个名字');
      return;
    }
    const r = await api.createSession({
      name: name.trim(),
      start_date: startDate,
      initial_capital: capital,
      ...(endDate ? {end_date: endDate} : {}),
    });
    if (r.code !== 0) {
      setError(r.msg || '创建失败');
      return;
    }
    setError(null);
    await openSession(r.data.id);
  };

  const createExam = async () => {
    setBusy(true);
    try {
      const r = await api.createExamSession({
        initial_capital: exCapital,
        length_days: exLength,
        era_pref: exEra,
        ...(exName.trim() ? {name: exName.trim()} : {}),
      });
      if (r.code !== 0) {
        setError(r.msg || '开局失败');
        return;
      }
      setError(null);
      await openSession(r.data.id);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    if (!window.confirm('删除这段旅程？不可恢复。')) return;
    await api.deleteSession(id);
    await refresh();
  };

  const dateCell = (s: SessionMeta) =>
    s.mode === 'exam' && s.status === 'active'
      ? `盲盒 第${s.day_ordinal}/${s.length_days}天`
      : `${s.start_date ?? '—'} ~ ${s.current_date ?? '—'}`;

  return (
    <div className="replay-page">
      <h3 style={{marginTop: 0}}>✈ 时光机 · 选择或开启一段旅程</h3>
      <div className="replay-panel" style={{marginBottom: 10}}>
        <h4>
          开启新旅程
          <span style={{display: 'inline-flex', gap: 6, marginLeft: 12}}>
            {(['free', 'exam'] as const).map((t) => (
              <button key={t}
                className={`replay-btn${tab === t ? ' primary' : ''}`}
                style={{padding: '1px 10px', fontSize: 12}}
                onClick={() => setTab(t)}>
                {t === 'free' ? '自由模式' : '🎯 拟真考核'}
              </button>
            ))}
          </span>
        </h4>
        {tab === 'free' ? (
          <>
            <div style={{display: 'flex', gap: 8, flexWrap: 'wrap'}}>
              <input className="replay-input" style={{width: 180}}
                placeholder="旅程名称" value={name}
                onChange={(e) => setName(e.target.value)} />
              <input className="replay-input" style={{width: 150}}
                type="date" value={startDate}
                onChange={(e) => setStartDate(e.target.value)} />
              <input className="replay-input" style={{width: 150}}
                type="date" value={endDate} placeholder="终点(可选)"
                onChange={(e) => setEndDate(e.target.value)} />
              <input className="replay-input" style={{width: 130}}
                type="number" step={100000} value={capital}
                onChange={(e) => setCapital(Number(e.target.value))} />
              <button className="replay-btn primary"
                onClick={() => void createFree()}>
                起飞 ▶
              </button>
            </div>
            <div className="replay-hint">
              起始日非交易日会自动顺延到下一交易日；终点仅限定复盘数据范围,留空则一路开到数据尽头。
            </div>
          </>
        ) : (
          <>
            <div style={{display: 'flex', gap: 8, flexWrap: 'wrap'}}>
              <input className="replay-input" style={{width: 130}}
                type="number" step={10000} value={exCapital}
                title="初始资金"
                onChange={(e) => setExCapital(Number(e.target.value))} />
              <select className="replay-input" style={{width: 130}}
                value={exLength}
                onChange={(e) => setExLength(Number(e.target.value))}>
                {LENGTHS.map((o) => (
                  <option key={o.v} value={o.v}>{o.label}</option>
                ))}
              </select>
              <select className="replay-input" style={{width: 110}}
                value={exEra}
                onChange={(e) => setExEra(e.target.value)}>
                {ERAS.map((o) => (
                  <option key={o.v} value={o.v}>{o.label}</option>
                ))}
              </select>
              <input className="replay-input" style={{width: 140}}
                placeholder="旅程名(可空)" value={exName}
                onChange={(e) => setExName(e.target.value)} />
              <button className="replay-btn primary" disabled={busy}
                onClick={() => void createExam()}>
                {busy ? '抽签中…' : '盲盒起飞 🎲'}
              </button>
            </div>
            <div className="replay-hint">
              随机抽一个你不知道的年代:全程隐藏日期(第N天)、一天8个时段逐段看盘、
              下单必须写理由、限价单收盘自动撤、分红送转自动落账;
              揭晓后评分入榜,一局定档不可重开。
            </div>
          </>
        )}
        {error && <div className="replay-error">{error}</div>}
      </div>
      <div className="replay-panel">
        <h4>历史旅程</h4>
        {list === null ? (
          <StateView state="loading" />
        ) : list.length === 0 ? (
          <StateView state="empty" />
        ) : (
          <table className="replay-table">
            <thead>
              <tr>
                <th>名称</th><th>模式</th><th>区间</th>
                <th>初始资金</th><th>现金</th><th>状态</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {list.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td>{s.mode === 'exam' ? '🎯 拟真' : '自由'}</td>
                  <td>{dateCell(s)}</td>
                  <td>{fmtMoney(s.initial_capital)}</td>
                  <td>{fmtMoney(s.cash)}</td>
                  <td>{s.status === 'revealed' ? '已揭晓' : '航行中'}</td>
                  <td>
                    <button className="replay-btn"
                      onClick={() => void openSession(s.id)}>
                      {s.status === 'revealed' ? '查看复盘' : '继续'}
                    </button>{' '}
                    <button className="replay-btn"
                      onClick={() => void remove(s.id)}>
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="replay-panel" style={{marginTop: 10}}>
        <h4>🏆 拟真榜(总分 = 超额收益 80 + 换手纪律 20)</h4>
        {board === null ? (
          <StateView state="loading" />
        ) : board.length === 0 ? (
          <div className="replay-hint">还没有已揭晓的拟真旅程——开一局试试。</div>
        ) : (
          <table className="replay-table">
            <thead>
              <tr>
                <th>#</th><th>名称</th><th>总分</th><th>超额分</th>
                <th>纪律分</th><th>年化超额</th><th>天数</th><th>期末</th>
              </tr>
            </thead>
            <tbody>
              {board.map((r, i) => (
                <tr key={r.id}>
                  <td>{i + 1}</td>
                  <td>{r.name}</td>
                  <td><b>{r.score.toFixed(1)}</b></td>
                  <td>{r.excess_score.toFixed(1)}</td>
                  <td>{r.turnover_score.toFixed(1)}</td>
                  <td>{r.annual_excess_pct >= 0 ? '+' : ''}
                    {r.annual_excess_pct}%</td>
                  <td>{r.days}</td>
                  <td>{r.final == null ? '—'
                    : fmtMoney(r.final)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
```

- [ ] **Step 3: 运行测试**

Run: `cd frontend/apps/web && npm test`
Expected: PASS(store 测试不渲染组件;无组件渲染测试)

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/pages/replay/PlayControls.tsx frontend/apps/web/src/pages/replay/SessionHome.tsx
git commit -m "feat(replay): 播放控件段级化+首页free/exam双表单+拟真榜面板"
```

---

### Task 19: ReviewView — 评分卡

**Files:**
- Modify: `frontend/apps/web/src/pages/replay/ReviewView.tsx`

**Interfaces:**
- Consumes: `session.state.score`(Task 13 ScoreResult)
- Produces:揭晓页顶部评分卡(总分大字+两分项+披露行,空值全部安全渲染)

- [ ] **Step 1: 修改**

(a) `const closeSession = ...` 之后加 selector:

```tsx
  const score = session?.state?.score ?? null;
```

(b) `{stats && (...)}` 区块**之后**插入:

```tsx
      {score && (
        <div className="replay-panel" style={{marginBottom: 10}}>
          <h4>🎯 拟真考核评分
            <span style={{fontSize: 12, color: '#86868b', marginLeft: 8}}>
              总分 = 超额收益分(80) + 换手纪律分(20)
            </span>
          </h4>
          <div style={{display: 'flex', gap: 24, alignItems: 'baseline',
            flexWrap: 'wrap'}}>
            <b style={{fontSize: 34}}>{score.total.toFixed(1)}</b>
            <span>超额分 {score.excess_score.toFixed(1)}
              （年化超额 {score.annual_excess_pct >= 0 ? '+' : ''}
              {score.annual_excess_pct}%）</span>
            <span>纪律分 {score.turnover_score.toFixed(1)}
              （年化换手 {score.annual_turnover}x）</span>
          </div>
          <div className="replay-hint" style={{marginTop: 6}}>
            只披露不打分：平仓胜率{' '}
            {score.disclosures.closed_win_rate == null
              ? '—'
              : `${(score.disclosures.closed_win_rate * 100).toFixed(0)}%`
                + `(${score.disclosures.closed_trips}次)`}
            {' '}· 最大回撤{' '}
            {score.disclosures.max_drawdown == null ? '—'
              : `-${(score.disclosures.max_drawdown * 100).toFixed(1)}%`}
            （基准{' '}
            {score.disclosures.benchmark_max_drawdown == null ? '—'
              : `-${(score.disclosures.benchmark_max_drawdown * 100)
                .toFixed(1)}%`}）
            {' '}· 平均现金占比{' '}
            {score.disclosures.avg_cash_ratio == null ? '—'
              : `${(score.disclosures.avg_cash_ratio * 100).toFixed(0)}%`}
            {' '}· 最大单票仓位{' '}
            {score.disclosures.max_position_weight == null ? '—'
              : `${(score.disclosures.max_position_weight * 100)
                .toFixed(0)}%`}
          </div>
        </div>
      )}
```

- [ ] **Step 2: 运行测试**

Run: `cd frontend/apps/web && npm test`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/web/src/pages/replay/ReviewView.tsx
git commit -m "feat(replay): 复盘页评分卡——总分/两分项/披露行空值安全渲染"
```

---

### Task 20: 全量验证与手动验收

**Files:** 无新文件

- [ ] **Step 1: 后端 replay 全量**

Run: `cd backend && python -m pytest tests/api/test_replay_router.py tests/api/test_replay_exam.py tests/domain/test_replay_synthetic.py tests/domain/test_replay_engine.py tests/domain/test_replay_eras.py tests/domain/test_replay_scoring.py -v`
Expected: 全 PASS

- [ ] **Step 2: 前端全量 + lint**

Run: `cd frontend/apps/web && npm test && npm run lint`
Expected: vitest 全 PASS;eslint 无新增错误

- [ ] **Step 3: 前端构建**

Run: `cd frontend/apps/web && npm run build`
Expected: 构建成功(仓内 tsconfig 既知问题致 `tsc --noEmit` 形同虚设,v1 记录——以 build+vitest+lint 为类型门)

- [ ] **Step 4: 手动验收(起服务过一遍,对照 spec §8)**

Run: `./dev-start.sh`(后端 12100 + 前端 dev server;若前端报 "Unexpected token 'E'" 见备忘=后端没起)

清单(逐条在浏览器确认):

1. exam 开局:三种长度 × 任意时代偏好可开局;响应与 UI 全程无真实日期(SessionHome 列表、TopBar、K线轴、EraBar、新闻);
2. 盯盘日:逐段推进,IntradayStrip 渐进生长,K线当日 bar 只到当前段,下单前看不到收盘价;
3. 市价单即时成交(价格≈现价+滑点);限价单:挂单→EventCard 可见→(a)后续段触发成交 或 (b)快进到明日自动撤销解冻,两路径都走到;
4. 无理由提交:按钮 disable + 后端拒绝(msg 含"理由");
5. 分红除权日:事件卡出现,现金到账=税后口径,送转后股数/成本变化,NAV 无跳空(随机起点未必踩中分红日——可用 free 模式同股除权日人工核对口径,或接受集成测试覆盖);
6. 揭晓:评分卡出现,手算一条会话的总分与公式一致;拟真榜出现该局且排序正确;揭晓后真实日期全部可见;
7. free 回归:旧旅程开仓/推进/下单/揭晓全流程与改造前一致。

- [ ] **Step 5: 最终 Commit**

```bash
git add -A
git commit -m "test(replay): v3拟真考核全量验证通过——后端6套件+前端vitest/lint/build+手动验收清单"
```

---

## 计划自审记录(执行者无需操作,写作时已核对)

1. **Spec 覆盖**:§3.1 盲盒开局→T8;§3.2 盘中循环/快进/停牌→T9/T16/T18;§3.3 订单规则→T3/T4/T10/T17;§3.4 分红落账→T5/T9;§3.5 评分/榜单→T7/T11/T19;§4.2 撮合后移→T9/T10/T14;§4.4 端点→T8/T9/T10/T11;§4.5 迁移→T1;§4.6 前端→T13-T19;§6 边界→各任务测试;§7 测试→各任务+T20;§8 验收→T20 Step 4。
2. **已知偏差(均已在任务内声明)**:spec §4.4 未列 `/pool` 与 `/view` 端点,实施需要(服务端权威下客户端无法 PUT state 加池),属 spec 精神内增补;`_advance_exam` 在 seg7 再按一次"下一时段"才日切(尾盘可交易),快进按钮总是日切——与 spec §3.2 盯盘语义一致。
3. **类型一致性**:ExamView 键名在 T9(后端 dict)与 T13(types.ts)一字对应;`mergeExamView`(T14)消费 ExamView;`placeOrder` 三处签名(store/OrderTicket/api)一致;`order_type` 在 T1/T3/T9/T10/T13 贯通。

