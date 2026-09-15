# 时光机模拟驾驶舱（Time Machine Replay）设计文档

日期：2026-09-14
状态：已获用户确认，待实施

## 1. 背景与目标

ytrader 是价值投资研究平台，已有长线回测、做T实验室、永久组合等"批量计算"型工具。本功能补一块**交互式**能力：用户回到历史某一天，在"未来不可见"的驾驶舱里逐日推进、模拟买卖，训练"只用当时信息做决策"的能力，旅程结束后揭晓全貌复盘。

一句话：**像飞机模拟驾驶舱一样的炒股时光机**——K 线是风挡，指标是仪表，时间控制是油门。

## 2. 关键决策（与用户逐项确认）

| 决策点 | 结论 |
|---|---|
| 核心玩法 | **双模式**：航行（盲盒训练，未来遮蔽）→ 揭晓（完整复盘） |
| 时间粒度 | **日线优先**；分钟级留作后续迭代 |
| 标的范围 | **全 A 自由选**，随时加入股票池 |
| 交易规则 | **拟真**：T+1、涨跌停拒单、整手 100 股、佣金+印花税 |
| 引擎架构 | **前端驱动**（zustand 状态机）+ 后端 as-of 数据切片 + 存档快照 |
| 座舱布局 | **B · 交易终端三栏**（左股票池/持仓，中 K 线+播放控制，右下单台+指标） |
| 选股入口 | 直接搜索 + 当时口径选股器 + 自选股快照导入 + 当日市场榜单 |

## 3. 双模式

一次"旅程（journey）"= 起始日期 + 初始资金（默认 100 万）+ 空股票池。

- **航行模式**：一切数据按当前日期遮蔽。遮蔽由**后端数据截断**实现（只供给 ≤ 当前日的数据），不是前端视觉遮挡——DevTools 也扒不到未来数据（前端仅有 1 天滚动小缓冲，属可接受的自用妥协）。
- **揭晓/复盘模式**：随时手动点"揭晓"，或走到 end_date 自动进入。完整 K 线展开，买卖点以 marker 标注在 K 线图上；收益曲线对比沪深 300；交易清单（含下单时写的理由）；战绩统计：总收益、年化、最大回撤、胜率、超额收益。

## 4. 座舱布局（B · 三栏终端）

- **顶栏**：✈ 当前日期、旅程第 N 个交易日、账户总览（现金/持仓市值/总收益率）
- **左栏**：股票池（[+ 加股] 入口；列表显示各标的当日涨跌幅）+ 持仓列表（股数/成本/浮动盈亏，复用 `PositionTable` 或轻量自绘）
- **中栏**：K 线风挡（复用 `frontend/packages/trading/market-data` 的 `KlineChart`，lightweight-charts 增量喂数据）+ 成交量副图 + 播放控制台：
  - `◀ 回看一天`（只回看不许撤单，历史不可改）
  - `下一天 ▶`
  - 自动播放 1x/2x/4x + ⏸（油门）
- **右栏**：
  - 下单台：当前标的、参考价（当日收盘）、股数输入（整手校验）、买入/卖出按钮、可写一句**下单理由**（复盘时回看）
  - 指标仪表区：MA/MACD/KDJ/RSI（前端用截断 K 线纯函数计算）+ PE/PB 与历史分位（后端 as-of 接口供给）

旅程中"第 T 天"的语义：**站在 T 日收盘后**——能看到 T 日完整 K 线与当日榜单，下单按 T 收盘价成交（视同尾盘竞价），T+1 日起可卖。

## 5. 拟真交易规则（前端引擎）

- 成交价 = 当日收盘价；买入日次日起可卖（T+1）
- 涨跌停：当日收盘涨停则拒买单，跌停则拒卖单（按主板 ±10%、创业板/科创板 ±20%、ST ±5% 判定）
- 买入整手 100 股（卖出允许零股清仓，贴合实盘）；资金不足拒单
- 费率：佣金万 2.5（最低 5 元）+ 卖出印花税 0.05%
- 停牌日（无 bar）：不可成交，持仓估值沿用上日收盘
- 数据缺口日直接跳过；起始日后上市的新股自上市日起可买
- **价格口径：沿用 `stock_ohlcv` 原样（平台统一口径，真实历史成交价）**。已核实库内无复权因子表与复权计算设施（2026-09-14 spike：provider 拉数用 qfq，但落库口径即全站口径）；除权缺口即当年盘面真实所见。MVP 不模拟分红/送转现金流——高股息标的持有期收益会略微低估，在此记录
- 印花税率按日期切换：2023-08-28 起 0.05%，此前 0.1%

## 6. 后端设计（纯增量，不改动既有模块）

新增 `src/api/router/replay_router.py` + `src/api/handler/replay_handler.py`（惯例参照 `watchlist_router.py`），表模型放 `src/infra/database/replay/models.py` 并在 `main.py` lifespan 中 import 建表。全部端点挂 `/api/v1/replay`。

### 6.1 会话管理

| 端点 | 说明 |
|---|---|
| `POST /replay/sessions` | 创建旅程：name、start_date、initial_capital、end_date? |
| `GET /replay/sessions` | 旅程列表（含现金/当前日摘要，供继续/删除） |
| `GET /replay/sessions/{id}` | 完整状态（含 state JSONB），继续旅程时恢复 |
| `PUT /replay/sessions/{id}/state` | 防抖自动存档：current_date + state 快照 |
| `POST /replay/sessions/{id}/reveal` | 切换揭晓模式（不可逆） |
| `DELETE /replay/sessions/{id}` | 删除旅程 |

### 6.2 数据切片（全部 as-of 截断，防未来函数的核心）

| 端点 | 说明 |
|---|---|
| `GET /replay/kline/{symbol}?asof=&limit=` | 截断 K 线（`stock_ohlcv` 原样口径），加股/切股时初始化 |
| `GET /replay/advance?session_id=&days=N` | **油门端点**：批量返回池内全部标的 + 基准指数接下来 N 个交易日的 bar（按各标的自身数据对齐，缺日跳过）；同时返回交易日历序列 |
| `GET /replay/valuation/{symbol}?asof=` | PE/PB 及十年分位（`stock_valuation` 截断 SQL 自算，剔负值，样本不足 30 返回 null） |
| `GET /replay/board?asof=&type=` | 当日榜单：gainers（涨幅）/ amount（成交额），纯 `stock_ohlcv` 当日查询，零泄漏 |

**选股器不新建端点**：前端直接调现有 `POST /screener/screen` 并传 `as_of=旅程当前日`。精度说明：财报表无披露日列，as-of 口径 = 报告期 ≤ asof−60 天滞后近似（沿用平台 `FINANCIAL_LAG_DAYS=60` 统一口径），UI 如实标注。new_high 榜单砍入 YAGNI。

股票搜索复用平台既有搜索端点（实施时确认 market_router 中现有能力，不新建）。

### 6.3 表结构（2 张新表）

```sql
replay_session (
  id              SERIAL PRIMARY KEY,
  name            TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'active',   -- active | revealed
  start_date      DATE NOT NULL,
  current_date    DATE NOT NULL,
  end_date        DATE,
  initial_capital DOUBLE PRECISION NOT NULL,
  cash            DOUBLE PRECISION NOT NULL,         -- 冗余快照，列表页展示用
  benchmark_symbol TEXT NOT NULL DEFAULT 'sh000300',
  state           JSONB NOT NULL,   -- { pool:[...], positions:[{symbol,shares,cost_price,buy_date}], nav:[{date,value}], ... }
  created_at      TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now()
);

replay_trade (
  id          SERIAL PRIMARY KEY,
  session_id  INT NOT NULL REFERENCES replay_session(id) ON DELETE CASCADE,
  trade_date  DATE NOT NULL,
  symbol      TEXT NOT NULL,
  side        TEXT NOT NULL,        -- buy | sell
  price       DOUBLE PRECISION NOT NULL,   -- 前复权口径
  shares      INT NOT NULL,
  fee         DOUBLE PRECISION NOT NULL,
  tax         DOUBLE PRECISION NOT NULL DEFAULT 0,
  note        TEXT,                 -- 下单理由，复盘时回看
  created_at  TIMESTAMPTZ DEFAULT now()
);
```

净值曲线不必每日落库：`state.nav` 随快照保存；揭晓后复盘曲线由前端用 K 线数据 + 成交记录重算校验。

## 7. 前端设计

- 路由 `/replay` → `src/pages/replay/ReplayPage.tsx`，子组件集中 `src/pages/replay/`；`App.tsx` 加 Route（lazy），Layout 导航加入口"时光机"
- **引擎**：`src/pages/replay/engine/` 纯函数模块（无 React 依赖，可单测）：
  - `fill.ts`：成交判定（收盘价成交、T+1、涨跌停、整手、费用）
  - `indicators.ts`：MA/EMA/MACD/KDJ/RSI（实施时先查前端包内是否已有可复用实现）
  - `nav.ts`：净值/收益率/回撤计算
- **状态**：zustand `replayStore`——日期指针、股票池、K 线缓存、现金/持仓/成交清单、净值序列、播放状态（速度/暂停）
- **推进时序**：点"下一天"/播放 tick → `advance` 拉取下 N 日 bar → 引擎推进日期并结算（下单在当日已即时成交，推进只做估值刷新与新 bar 追加）→ K 线/仪表/持仓浮盈增量更新 → 防抖 `PUT state`
- **选股弹层**（左栏 [+ 加股]）：四个页签 = 搜索 / 当时口径选股器 / 自选股导入（开舱时快照，UI 标注"轻微未来泄漏"）/ 当日榜单
- **复盘模式**：同页面切换状态——K 线全量展开、买卖点 marker、收益曲线 vs 沪深300、交易清单+理由、战绩卡片
- A 股配色惯例：红涨绿跌，与全站令牌体系一致（chartTheme 常量）

## 8. 错误与边界

| 场景 | 处理 |
|---|---|
| asof 晚于今天 | 后端 400 拒绝 |
| 池内标的停牌 | advance 返回该日无此标的 bar；前端估值沿用上日收盘，不可交易 |
| 旅程期内退市 | MVP：标记不可交易、估值沿用最后价，揭晓时提示（不强制平仓） |
| `stock_ohlcv` 缺某日 | advance 跳过该日，交易日历以指数日线为准 |
| 复权因子缺失 | 实施验证点；兜底退回未复权并在 UI 标注 |
| 并发/多端 | 单用户工具，last-write-wins，不做锁 |

## 9. 测试策略

- **后端 pytest**：
  - as-of 截断的披露日边界（构造 announcement_date 横跨 asof 的财报，断言 2020-03-15 看不到 4 月披露的年报）
  - advance 对齐逻辑（停牌标的、缺口日、池内多标的）
  - 会话 CRUD + state 快照往返
- **前端引擎单测**：成交价/T+1/涨跌停/整手/费率的纯函数用例；indicators 对照已知序列
- **手动验收**：完整走一趟旅程（开舱 → 选股器选股 → 买卖 → 自动播放 → 揭晓复盘）
- 注意：backend 全量 pytest 有 52 项既有失败 + 6 收集错误（与本次无关），只跑新增测试文件子集

## 10. 复用与新增清单

**复用**：`KlineChart`（lightweight-charts）、`PositionTable`/`OrderTable`、watchlist API、财务质量/估值 screener 模块（as-of 化改造）、`stock_ohlcv`/`index_ohlcv`、沪深300基准、chartTheme 配色令牌。

**新增**：replay_router + handler + models（2 表）、`/replay` 页面族、引擎纯函数模块、选股弹层、复盘视图。

## 11. YAGNI 边界（明确不做，留后续迭代）

分钟级回放；分红/送转现金流模拟；多人排行/评分系统；撤单与历史改写；分钟级做T（已有做T实验室承担）。

## 12. 实施前验证点（spike 结果，2026-09-14 已核实）

1. ~~复权因子来源~~ → **库内无复权因子表/设施**，按 `stock_ohlcv` 原样口径实现（见 §5）
2. ~~前端指标/搜索组件~~ → 指标有 `pages/Board/indicators.ts`（ema/macd/rsiWilder/boll，与后端对齐）可复用，无 KDJ 需自写；搜索用现有 `GET /market/search` 端点
3. ~~KlineChart 增量封装~~ → 该组件自取数、无 data 入口，**不可复用**；新建受控 `ReplayKlineChart`（lightweight-charts v5，`setData` 初始化 + `series.update` 增量推进 + `createSeriesMarkers` 标注买卖点），不动共享包
