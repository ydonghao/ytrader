# Market Data 模块设计

**项目**: YTrader 量化交易平台
**模块**: Market Data (市场数据)
**版本**: 1.0
**日期**: 2026-03-29
**状态**: 已评审

---

## 一、模块概述

Market Data 模块是 YTrader 的基础数据层，负责从多个数据源采集行情数据并存储，为策略引擎、投资组合引擎、风控引擎和 AI Lab 提供统一的数据访问接口。

---

## 二、数据源

### 2.1 支持的数据源

| 数据源 | 类型 | 覆盖市场 |
|--------|------|----------|
| AKShare | 免费 | A股、港股、美股、ETF、指数 |
| Tushare | 免费/付费 | A股为主 |
| Yahoo Finance | 免费 | 美股为主 |

> **参考来源**: OpenBB 的 Provider + Fetcher 分离模式；vnpy 的 Gateway 插件模式；TradingAgents-CN 的 AkShare/Tushare/BaoStock 中国数据源集成

### 2.2 数据源策略

**多数据源自动切换**：根据市场类型自动选择对应数据源，当主要数据源失败时自动降级到备用数据源。

| 市场 | 主数据源 | 备用数据源 |
|------|----------|------------|
| A股 | AKShare | Tushare |
| 港股 | AKShare | - |
| 美股 | Yahoo Finance | AKShare |

---

## 三、Provider + Fetcher 分离模式

> **参考来源**: OpenBB 的 Provider/Fetcher 架构

每个数据源实现为 `Provider` + `Fetcher` 的组合：

| 组件 | 职责 |
|------|------|
| `Provider` | 管理凭证、元数据、Provider 级别的配置 |
| `Fetcher` | 负责具体的数据拉取 (extract) 和格式转换 (transform) |

```python
# Provider 负责管理凭证和元数据
class AKShareProvider(Provider):
    name = "akshare"
    credentials = []  # 免费无需凭证
    fetcher_dict = {
        "equity_historical": AKShareEquityHistoricalFetcher,
        "equity_bars": AKShareEquityBarsFetcher,
    }

# Fetcher 负责具体数据获取和格式标准化
class AKShareEquityHistoricalFetcher(Fetcher):
    @staticmethod
    def transform_query(params: dict) -> dict:
        """将通用参数转换为 AKShare 特定格式"""

    @staticmethod
    def extract_data(query, credentials) -> pd.DataFrame:
        """从 AKShare API 拉取原始数据"""

    @staticmethod
    def transform_data(query, raw_data) -> list[EquityHistoricalData]:
        """转换为统一的标准格式"""
```

### 3.1 OBBject 统一结果封装

所有 API 返回值使用 OBBject 封装（参考 OpenBB），保留元数据：

```python
@dataclass
class OBBject:
    results: Any                   # 实际数据
    provider: str                  # 数据来源
    warnings: list[Warning]       # 警告信息
    chart: Chart | None           # 图表对象
    extra: dict                  # 附加数据
```

### 3.2 多级缓存架构

> **参考来源**: Qlib 的 MemCache → ExpressionCache → DatasetCache 三级缓存

| 层级 | 说明 | 性能提升 |
|------|------|---------|
| MemCache | 内存 LRU 缓存 | 毫秒级 |
| ExpressionCache | 预计算表达式缓存 | 10x |
| DatasetCache | 完整数据集缓存 | 50x |

存储性能对比（Qlib benchmark）：

| 方案 | 1 CPU (秒) |
|------|-----------|
| HDF5 | 184.4 |
| Qlib (+E +D) | **7.4** |

### 3.3 二进制列式存储

> **参考来源**: Qlib 的 .bin 文件存储

使用紧凑的二进制列式格式替代 CSV/JSON：

```python
# 存储格式：{instrument}/{field}.{freq}.bin
# 600519.SH/close.day.bin  # 单只股票单字段的二进制文件
# 高效的字节级读取，避免格式解析开销
```



## 四、数据粒度

| 粒度 | 说明 | 存储需求 |
|------|------|----------|
| 日线 | 日K数据 | 保留全部历史 |
| 分钟级 | 1/5/15/60 分钟K线 | 保留最近 3 个月 |

---

## 五、数据采集

### 4.1 采集模式

**拉模式 (Polling)**：定时任务轮询数据源。

### 4.2 采集时段

| 时段 | 时间 | 任务 |
|------|------|------|
| 盘前 | 07:00 | A股涨停/跌停板列表 |
| 盘中 | 每 5 分钟 | 分钟级K线合成 |
| 盘后 | 15:05 | 日线数据入库 |
| 夜间 | 21:00-23:00 | 美股数据采集 |

### 4.3 错误处理

| 策略 | 实现 |
|------|------|
| 重试机制 | 失败后重试 3 次，间隔 5 秒 |
| 降级策略 | 主要数据源失败后切换备用 |
| 日志记录 | 每次采集状态写入 `data_collection_log` 表 |

---

## 六、存储架构

### 5.1 数据库

**TimescaleDB** 作为时序数据库，支持 hypertable 高效存储和查询时序数据。

### 5.2 表结构（按市场+类型分表）

| 表名 | 类型 | 说明 |
|------|------|------|
| `stock_daily_{market}` | hypertable | 股票日线 (SH/SZ/HK/US) |
| `stock_minute_{market}` | hypertable | 股票分钟线 |
| `etf_daily_{market}` | hypertable | ETF 日线 |
| `etf_nav_{market}` | hypertable | ETF 净值 (IOPV) |
| `index_daily_{market}` | hypertable | 指数日线 |

### 5.3 统一表结构示例

```sql
-- 股票日线表
CREATE TABLE stock_daily (
    time TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    open NUMERIC(18, 4),
    high NUMERIC(18, 4),
    low NUMERIC(18, 4),
    close NUMERIC(18, 4),
    volume BIGINT,
    amount NUMERIC(18, 4),
    market TEXT,
    PRIMARY KEY (time, symbol)
);
SELECT create_hypertable('stock_daily', 'time');
CREATE INDEX idx_stock_daily_symbol ON stock_daily (symbol);
```

---

## 七、历史数据回填

### 6.1 分层回填策略

| 场景 | 策略 | 数据范围 |
|------|------|----------|
| 首次部署 | 全量回填 | 日线 2 年，分钟级 1 个月 |
| 新增标的 | 增量回填 | 最近 30 天 |
| 策略需要 | 按需回填 | 所需标的 |

### 6.2 回填优先级

1. 日线数据优先
2. 分钟级数据其次
3. 实时行情最后

---

## 八、数据访问层

### 7.1 架构模式

**仓储模式 (Repository)**：通过统一的仓储接口屏蔽底层存储细节，支持后续切换存储引擎而不影响其他模块。

```
其他模块 → MarketDataRepository 接口 → TimescaleDB
```

### 7.2 核心接口

| 接口 | 说明 |
|------|------|
| `get_kline(symbol, timeframe)` | 获取K线数据 |
| `get_tickers()` | 获取实时行情列表 |
| `get_depth(symbol)` | 获取订单簿深度 |
| `get_overview()` | 获取市场概览 |
| `add_symbol(symbol)` | 添加跟踪标的 |

---

## 九、API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/market/kline/{symbol}` | GET | K线数据（日/分钟） |
| `/market/tickers` | GET | 实时行情列表 |
| `/market/depth/{symbol}` | GET | 订单簿深度 |
| `/market/overview` | GET | 市场概览 |
| `/market/symbols` | POST | 添加跟踪标的 |

---

## 十、核心组件

| 组件 | 职责 |
|------|------|
| `Provider` + `Fetcher` | 数据源抽象层（参考 OpenBB，支持多数据源热插拔） |
| `DataCollector` | 定时任务调度，调用 Fetcher 获取数据 |
| `MultiLevelCache` | MemCache → ExpressionCache → DatasetCache 三级缓存 |
| `BinaryStorage` | 二进制列式存储 (.bin 格式) |
| `MarketDataRepository` | 仓储接口，CRUD 操作 + OBBject 封装 |
| `Scheduler` | 固定时段触发（盘前/盘中/盘后） |
| `HistoricalBackfiller` | 历史数据回填服务 |
| `FallbackManager` | 数据源降级切换（主 → 备） |

---

## 十一、依赖关系

```
Market Data 模块
├── 被依赖
│   ├── Strategy Engine (策略引擎)
│   ├── Portfolio Engine (投资组合)
│   ├── Risk Engine (风控引擎)
│   └── AI Lab (AI实验室)
│
└── 无外部依赖（独立模块）
```

---

**文档版本**: 1.1
**最后更新**: 2026-03-31
