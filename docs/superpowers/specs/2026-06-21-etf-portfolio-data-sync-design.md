# ETF 配置组合数据采集设计 (P1)

**项目**: ytrader 量化交易平台
**模块**: market/sync (行情采集) + portfolio 数据基础
**版本**: 1.0
**日期**: 2026-06-21
**状态**: 待实现

---

## 一、背景与目标

需要把一篮子「永久投资组合 / 全天候」风格的配置标的行情拉入本地库，用于组合净值监控、再平衡告警、回测与前端展示。标的清单（A 股 6 + 美股 6）：

| 市场 | 资产 | 标的 |
|------|------|------|
| A | 宽基指数 | 沪深300ETF `510300` / A500ETF |
| A | 长期国债 | 10年国债ETF `511260` / 30年国债ETF `511090` |
| A | 黄金 | 华安黄金ETF `518880` / 博时黄金ETF `159934` |
| A | 现金 | 华宝添益 `511990` |
| US | 宽基指数 | `VOO` / `SPY` |
| US | 长期国债 | `TLT` |
| US | 黄金 | `GLD` / `IAU` |
| US | 现金 | `SHV` |

### 已确认的决策

1. **用途**：监控 + 回测 + 展示全要 → 分阶段实现
2. **美股数据源**：AKShare（已装 1.18.50，国内可达、免费、免 token）
3. **币种**：美股折算人民币 → 需拉 USDCNY 汇率日线
4. **汇率存储**：独立 `fx_rate` 表
5. **A 股 ETF 数据源**：与美股统一用 AKShare（顺便规避 Tencent 的 `sz1` 校验坑）

### 范围划分

| 阶段 | 内容 | 状态 |
|------|------|------|
| **P1（本 spec）** | 12 标的 + USDCNY 采集入库；回测即时可用 | 本文档 |
| P2 | portfolio 定义表 + 每日组合净值物化 + 人民币折算 | 待定 |
| P3 | 偏离告警（接 alert 模块）+ 再平衡建议 + 前端组合页 | 待定 |

**P1 完成标准**：12 标的日线 + USDCNY 日线稳定入库 `stock_ohlcv` / `fx_rate`；`backtest_router` 无需改动即可对 `VOO`/`sh510300` 等跑回测。

---

## 二、架构决策

### 2.1 为什么扩展 `market/sync` 而非实现 `market/providers`

项目存在两套并行的 provider 体系（历史包袱）：

| 体系 | 位置 | 状态 |
|------|------|------|
| Provider+Fetcher（OpenBB 风格） | `domain/market/providers/` | `NotImplementedError` 占位，从未落地，抽象与 sync 不兼容 |
| SyncProvider | `domain/market/sync/providers/` | Sina/Tencent，**实际在跑**，配套 SyncService/ProgressTracker/daily.py |

**决策**：在 sync 体系新增 `AkshareProvider`。白嫖现有全部基础设施（三模式 backfill、断点续传、cron、并发、批量 upsert），避免建第二条数据通路加重双轨问题。`market/providers/` 不碰。

### 2.2 存储复用 `stock_ohlcv`

`stock_ohlcv` 现有列 `(symbol, trade_date, open_, close_, high_, low_, volume, amount, market, created_at)`，唯一键 `(trade_date, symbol)`，`market` 为字符串列。美股直接 `market='US'` 写入，upsert 已具备。**`backtest_router` 的 `SELECT close_ FROM stock_ohlcv WHERE symbol=?` 零改动**即可回测新标的。

### 2.3 分层规范说明

CLAUDE.md 规定「domain 禁止 psycopg2 / 手写 SQL，走 SQLModel ORM」。现状 `SyncService` 已在 domain 层用 psycopg2（既有技术债）。本设计的取舍：

- `AkshareProvider`（domain 层）：只返回 `OHLCVBar`，**不碰 DB** → 天然合规
- `stock_ohlcv` 写入：沿用 `SyncService` 既有的 psycopg2 批量 upsert（既有行为，不在本 spec 范围内纠正）
- `fx_rate` 写入：**走 SQLModel + repository 守规范**（全新独立小表，无批量性能诉求，给 P2 留干净接口）

---

## 三、组件设计

### 3.1 新增：`AkshareProvider` — `domain/market/sync/providers/akshare_provider.py`

实现 `SyncProvider` 接口（定义见 `sync_provider.py`）。

```python
class AkshareProvider(SyncProvider):
    name = "akshare"
    supports_minute = False   # P1 不实现分钟线（YAGNI，回测用日线）

    def fetch_daily(self, symbol, start_date=None, end_date=None, datalen=1300):
        """按 symbol 分流到 akshare 的 A股ETF / 美股接口"""
        if self._is_us_ticker(symbol):          # ^[A-Z]{1,5}$
            return self._fetch_us(symbol, start_date, end_date)    # → market="US"
        else:                                    # sh510300 / sz159934
            return self._fetch_a_etf(symbol, start_date, end_date) # → market="A"

    def fetch_minute(self, *a, **kw):
        raise NotImplementedError("P1 不支持分钟线")

    def get_stock_list(self, market="A"):
        """从 config 读 portfolio_universe 对应 market 的标的，不做全市场扫描"""
        ...

    def validate_symbol(self, symbol):
        """美股 ticker 正则 / A股 sh|sz+6位 / ETF 纯数字"""
        ...
```

**symbol 规范化**：`SyncProvider` 约定 `sh510300` 格式，akshare 接口吃纯数字（A股ETF）或字母 ticker（美股）。provider 内部转换：`sh510300 → "510300"` 给 `fund_etf_hist_em`；`VOO` 原样给 `stock_us_daily`。

**计划使用的 akshare 接口**（实现时以 akshare 1.18.50 实际签名为准，需单测 fixture 锁定列名）：

| 用途 | 接口 | 备注 |
|------|------|------|
| A股 ETF 日线 | `ak.fund_etf_hist_em(symbol="510300", period="daily", adjust="qfq", start_date, end_date)` | 返回列：日期/开盘/收盘/最高/最低/成交量/成交额 |
| 美股日线 | `ak.stock_us_daily(symbol="VOO", adjust="qfq")` | 新版可能改名，实现时核实 |
| USDCNY 历史 | `ak.currency_boc_sina(symbol="美元", start_date, end_date)` | 中行牌价；备选 `ak.fx_spot_quote()` |

**防御性编码**：`fetch_daily` 对返回 DataFrame 做列名存在性检查（akshare 列名常有中英文/大小写变动），缺失则记 warning 并跳过该行。

### 3.2 新增：`FxRate` entity — `infra/database/market/fx_rate.py`

```python
class FxRate(SQLModel, table=True):
    __tablename__ = "fx_rate"
    date: date = Field(primary_key=True)
    pair: str = Field(primary_key=True)   # "USDCNY"
    rate: float
    source: str = "akshare"
    created_at: datetime
```

配套 `IFxRateRepository` 接口（domain）+ `FxRateRepository` 实现（infra）+ `create_fx_rate_repository()` 工厂，遵循项目 Repository Pattern 范例（参考 Intel 模块）。SQLModel `create_all` 自动建表。

### 3.3 新增：组合篮子同步入口 — `domain/market/sync/jobs/portfolio_daily.py`

供 cron 调用，与现有 `daily.py` 平行。**注意**：不直接复用 `daily.py` 的 `sync_market()`（它按 market 调 `get_stock_list` 做全市场扫描，不接受 symbols 参数），而是直接构造 `SyncService` 对显式 symbol 列表 backfill。

```python
def run():
    universe = load_portfolio_universe()        # 从 config.yaml
    provider = AkshareProvider()
    tracker = ProgressTracker()
    service = SyncService(provider, tracker, SyncConfig(db_dsn=_get_dsn()))

    # 1. 12 标的 → stock_ohlcv
    for item in universe.bars:                  # bars = 非 FX 标的
        # ⚠️ mode 不能无脑 incremental：incremental 只处理 tracker 已有
        #    last_sync 记录的 symbol，新标的会被跳过。按有无记录判定：
        has = tracker.get_last_sync("akshare", item.symbol, "1d") is not None
        mode = "incremental" if has else "full"   # 首次 full，后续 incremental
        service.backfill(symbols=[item.symbol], interval="1d", mode=mode)

    # 2. USDCNY → fx_rate（同样需处理冷启动：基于 fx_rate 表最大日期判定增量）
    sync_fx(pair="USDCNY")
```

汇率同步 `sync_fx` 为轻量函数（一天一值，不走 SyncService 的并发体系）：查 `fx_rate` 表该 pair 的最大日期作为起点（无记录则全量起拉），调 `AkshareProvider` 的汇率方法 + `FxRateRepository.upsert`。

crontab 示例（写入 spec 供部署参考）：
```
30 16 * * 1-5 cd /path/backend && .venv/bin/python -m src.domain.market.sync.jobs.portfolio_daily >> logs/portfolio_sync.log 2>&1
```

### 3.4 修改：`conf/config.yaml` 新增 `portfolio_universe`

```yaml
portfolio_universe:
  bars:
    - { symbol: "sh510300", market: "A",  ccy: "CNY", name: "沪深300ETF", asset: "equity" }
    - { symbol: "sh511260", market: "A",  ccy: "CNY", name: "10年国债ETF", asset: "bond" }
    - { symbol: "sh511090", market: "A",  ccy: "CNY", name: "30年国债ETF", asset: "bond" }
    - { symbol: "sh518880", market: "A",  ccy: "CNY", name: "华安黄金ETF", asset: "gold" }
    - { symbol: "sz159934", market: "A",  ccy: "CNY", name: "博时黄金ETF", asset: "gold" }
    - { symbol: "sh511990", market: "A",  ccy: "CNY", name: "华宝添益",  asset: "cash" }
    - { symbol: "VOO",      market: "US", ccy: "USD", name: "标普500",   asset: "equity" }
    - { symbol: "TLT",      market: "US", ccy: "USD", name: "20+年国债", asset: "bond" }
    - { symbol: "GLD",      market: "US", ccy: "USD", name: "黄金ETF",   asset: "gold" }
    - { symbol: "SHV",      market: "US", ccy: "USD", name: "短债ETF",   asset: "cash" }
  fx:
    - { pair: "USDCNY" }
```

（备选标的 SPY/IAU/511090/A500 暂不入默认清单，需要时加配置即可。）

---

## 四、数据流

```
conf/config.yaml (portfolio_universe)
        │
        ▼
portfolio_daily.run()
   ├─ AkshareProvider.fetch_daily(VOO)      → ak.stock_us_daily
   │      └→ SyncService.backfill(首次 full / 增量 incremental)
   │             └→ INSERT stock_ohlcv (market='US') ON CONFLICT upsert
   ├─ AkshareProvider.fetch_daily(sh510300) → ak.fund_etf_hist_em
   │      └→ ... stock_ohlcv (market='A')
   └─ fetch_fx("USDCNY") → ak.currency_boc_sina
          └→ FxRateRepository.upsert → fx_rate

回测(零改动): backtest_router SELECT close_ FROM stock_ohlcv WHERE symbol='VOO'
```

---

## 五、错误处理

| 场景 | 处理 |
|------|------|
| akshare 网络失败/限流 | 复用 `SyncService._sync_one` 的 try/except → `tracker.mark_failed` → 断点续传 |
| akshare 返回空（停牌/退市/休市） | `mark_partial`，不报错 |
| symbol 格式不识别 | provider 抛 `ValueError`，被 `_sync_one` 捕获记 failed |
| akshare API 变动（列名/函数） | `fetch_daily` 防御性列名检查 + 单测 fixture 锁定 |
| 重复跑 | `(trade_date,symbol)` / `(date,pair)` ON CONFLICT upsert → 幂等 |
| 美股非交易日 / A股节假日 | 返回空自然跳过；汇率同理 |

---

## 六、测试策略

镜像 `src/` 结构，`tests/domain/market/sync/...`：

1. **AkshareProvider 单测**（mock akshare 返回）：
   - 美股/ETF 分流正确（`VOO`→US，`sh510300`→A）
   - OHLCVBar 字段映射、时间升序
   - 列名大小写/中英文兼容（防御性检查）
   - `validate_symbol`：`VOO`/`sh510300`/`sz159934` 过，非法值不过
2. **FxRate repository**：upsert 幂等（同日重复写入覆盖不报错）
3. **portfolio_daily 集成**：mock akshare 跑一遍 `run()`，断言 stock_ohlcv + fx_rate 行数符合预期、断点续传跳过已完成 symbol

类名 `Test{Resource}`，方法 `test_{action}_{expected}`，遵循项目测试规范。

---

## 七、P2/P3 展望（占位，各自单独 spec）

- **P2**：`portfolio` 定义表（标的+权重+目标币种）+ 每日 `portfolio_nav` 物化（折算人民币，join `stock_ohlcv` + `fx_rate`）
- **P3**：偏离阈值告警（接入现有 `infra/database/alert`）+ 再平衡建议 + 前端组合页（`/portfolio` 路由已存在）

---

## 八、待实现时核实项

1. akshare 1.18.50 的 `stock_us_daily` / `fund_etf_hist_em` / `currency_boc_sina` 确切签名与返回列名（用 context7 或本地 `ak.__doc__` 核实，单测 fixture 锁定）
2. `fx_rate` 表走 SQLModel `create_all` 自动建表，确认与既有 hypertable 建表流程不冲突
3. 确认 `portfolio_daily` 是否纳入 `scheduler.py`（当前 scheduler 无任何行情同步任务，行情同步靠外部 cron；P1 沿用 cron 模式，不进 scheduler）

---

## 九、部署

crontab（工作日 16:30 收盘后增量同步）:

```
30 16 * * 1-5 cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m src.domain.market.sync.jobs.portfolio_daily >> logs/portfolio_sync.log 2>&1
```

首次部署需手动跑一次全量（`portfolio_daily.run()` 内部对无 `last_sync` 的标的自动走 `full`，无需额外参数）。

回测新标的无需改动：`POST /api/v1/backtest/run` 的 `symbol` 传 `VOO` 或 `sh510300` 即可，`backtest_router` 已从 `stock_ohlcv` 读。

### 已验证（P1 实现）

- akshare 1.18.50 三个接口列名已联网核实并锁定单测 fixture（A股ETF 中文列 / 美股英文列 / 汇率中行折算价÷100）
- `fx_rate` 表经 SQLModel `create_all` 已建（DB 内已存在）
- backtest `SELECT trade_date, close_ FROM stock_ohlcv WHERE symbol='VOO'` 兼容（表/列结构不变，零改动回测）
- 已知限制：akshare eastmoney 接口偶发 `ConnectionError`，provider 静默返回 `[]`；`SyncService` 会 `mark_partial`，下次 incremental 补回
