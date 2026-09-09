# YTrader 量化交易平台

**项目**: YTrader 量化交易服务
**版本**: 1.2
**日期**: 2026-03-31
**状态**: 设计阶段

---

## 一、项目概述

### 1.1 核心目标

面向个人用户的**股票市场量化交易平台**，支持：
- **多市场**: A股、港股、美股（股票 + ETF + 指数）
- **交易模式**: 研究/回测 + 模拟交易 + AI Lab 协作
- **架构**: 云端部署，单体架构

### 1.2 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Zustand + Rsbuild |
| 后端 | FastAPI + Redis + TimescaleDB + MongoDB |
| 数据源 | AKShare, Tushare, Yahoo Finance |
| AI | OpenClaw / Claude API + Multi-Provider LLM |
| 记忆 | ChromaDB (向量记忆) |
| 工具协议 | FastMCP (MCP Server) |
| 部署 | 云端服务 |

### 1.3 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     Frontend (Web)                              │
│  React 18 + TypeScript + Zustand + Rsbuild                     │
│  Dashboard | Market | Trading | Strategies | AI Lab            │
│  Portfolio | Risk | Collaboration | Settings                   │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP/WebSocket
┌────────────────────────────▼────────────────────────────────────┐
│                      Backend (单体)                             │
│  FastAPI + Redis + TimescaleDB                                 │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │   Market    │  │  Strategy   │  │ Portfolio   │            │
│  │   Data      │  │   Engine    │  │   Engine    │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │    Risk     │  │     AI      │  │   Team      │            │
│  │   Engine    │  │   Lab       │  │Collaboration│            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、项目结构

```
ytrader/
├── backend/
│   ├── src/
│   │   ├── api/              # API层 (routers, handlers)
│   │   ├── application/      # 应用层 (services, use cases)
│   │   ├── domain/           # 领域层 (entities, events)
│   │   │   ├── market/       # 市场数据
│   │   │   ├── strategy/      # 策略引擎
│   │   │   ├── portfolio/     # 投资组合
│   │   │   ├── risk/          # 风险引擎
│   │   │   └── ailab/         # AI Lab
│   │   ├── infra/            # 基础设施 (database, cache)
│   │   └── pkg/              # 工具包
│   ├── conf/                 # 配置
│   └── tests/                # 测试
│
├── frontend/
│   ├── apps/web/             # 主应用
│   ├── packages/
│   │   ├── arch/             # 架构包 (api, hooks, utils)
│   │   ├── common/           # 通用组件
│   │   └── trading/          # 交易域包
│   └── config/               # 配置
│
└── docs/                    # 文档
```

---

## 三、数据架构

### 3.1 数据流程

```
AKShare / Tushare / Yahoo Finance
         │
         ▼
┌───────────────────┐
│  Data Collector   │
│    Service        │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│    TimescaleDB    │
│    (hypertable)   │
└───────────────────┘
```

### 3.2 数据库表

| 表名 | 类型 | 说明 |
|------|------|------|
| `stock_daily` | hypertable | 股票日线数据 |
| `stock_minute` | hypertable | 分钟线 (1/5/15/60分钟) |
| `stock_tick` | hypertable | 逐笔数据 |
| `etf_daily` | hypertable | ETF 日线数据 |
| `etf_nav` | hypertable | ETF 净值 (IOPV) |
| `index_daily` | hypertable | 指数日线 |
| `fundamental` | regular | 财务数据 |
| `backtest_results` | regular | 回测结果 |
| `signals` | regular | 交易信号 |

### 3.3 支持资产

| 类型 | 市场 | 示例 |
|------|------|------|
| 股票 | A股 (SH/SZ) | 000001.SZ, 600519.SH |
| 股票 | 港股 (HKEX) | 00700.HK |
| 股票 | 美股 | AAPL, TSLA |
| ETF | 多市场 | 510300.SH (沪深300ETF) |
| 指数 | 多市场 | 沪深300, 恒生, 标普500 |

---

## 四、策略引擎

### 4.1 策略类型

| 类型 | 示例 | 信号类型 |
|------|------|---------|
| 技术分析 | MA, RSI, MACD, Bollinger Bands | 趋势跟踪、均值回归 |
| 统计套利 | Pairs trading, Correlation | 均值回归、收敛 |
| 因子策略 | Alpha158 (158因子), Value, Momentum, Quality | 多空 |
| 事件驱动 | Earnings, News, Corporate | 事件驱动 |
| AI 驱动 | RD-Agent 自动因子挖掘、模型优化 | 自动发现 |

### 4.2 核心组件

```
策略 → 信号 → 订单 异步消息传递
         │
    ┌────┴────┐
    ▼         ▼         ▼
参数优化器   信号过滤器   风控前置
• 网格搜索  • 多策略聚合 • 仓位检查
• 贝叶斯    • 优先级排序 • 限额检查
• 遗传算法  • 冲突解决   • 熔断机制
```

### 4.3 Model Zoo (模型库)

支持 20+ 预置模型，通过统一接口注册和调用：

| 模型 | 类型 | 来源 |
|------|------|------|
| LGBModel, XGBoostModel, CatBoostModel | GBDT | Qlib/vnpy.alpha |
| LSTMModel, GRUModel | 循环网络 | Qlib |
| TransformerModel, TFTModel | Attention | Qlib |
| MLPModel | 神经网络 | vnpy.alpha |
| DoubleEnsemble | 集成 | Qlib |

### 4.4 qrun 工作流

YAML 配置的自动化研究流程（参考 Qlib）：

```yaml
task:
  model:
    class: LGBModel
    kwargs: {loss: mse, learning_rate: 0.05}
  dataset:
    class: Alpha158Dataset
    segments:
      train: [2008-01-01, 2014-12-31]
      valid: [2015-01-01, 2016-12-31]
      test: [2017-01-01, 2020-08-01]
  record:
    - SignalRecord
    - SigAnaRecord
    - PortAnaRecord
```

### 4.3 事件调度

| 时段 | 任务 |
|------|------|
| 盘前 (07:00-09:00) | 涨停板/跌停板列表、前日收盘确认 |
| 盘中 (09:30-15:00) | 实时分笔、分钟K线合成 |
| 盘后 (15:00-19:00) | 日线数据入库 |
| 夜间 (21:00-23:00) | 美股数据采集 |

### 4.4 回测配置

```python
@dataclass
class BacktestConfig:
    start_date: date
    end_date: date
    initial_capital: float = 1000000.0
    commission_rate: float = 0.0003  # 万三
    slippage: float = 0.0001          # 万一
    benchmark: str = "000300.SH"      # 沪深300
    max_position_size: float = 0.2    # 单股最大20%
    max_total_position: float = 0.9   # 总仓位上限90%
```

### 4.5 回测指标

| 类别 | 指标 |
|------|------|
| 收益 | 总收益率、年化收益率、Alpha vs Benchmark |
| 风险 | 最大回撤、波动率、VaR 95% |
| 调整收益 | Sharpe Ratio、Sortino Ratio、Calmar Ratio |
| 交易统计 | 胜率、平均盈利/亏损、盈亏比 |

---

## 五、投资组合引擎

### 5.1 核心模块

| 模块 | 功能 |
|------|------|
| 资金管理 | 账户余额、可用资金、冻结资金 |
| 持仓管理 | 历史持仓、回溯分析 |
| 多账户 | 券商账户分组 |

### 5.2 订单类型

| 类型 | 说明 |
|------|------|
| 限价单 | 指定价格成交 |
| 市价单 | 以市价立即成交 |
| 冰山单 | 大单拆分小单 |
| 止损单 | 触发后下单 |
| 止盈单 | 触发后下单 |

### 5.3 绩效指标

```
日频: 日收益率、最大回撤
月频: 月度收益率、Sharpe Ratio
年度: 年化收益、Alpha vs Benchmark
```

---

## 六、风控引擎

### 6.1 仓位风控

| 规则 | 参数 | 动作 |
|------|------|------|
| 单股仓位 | max = 20% | 拒绝开仓 |
| 总仓位 | max = 90% | 拒绝开仓 |
| 行业仓位 | max = 30% | 拒绝开仓 |

### 6.2 止损规则

| 类型 | 参数 | 动作 |
|------|------|------|
| 固定止损 | 7% | 市价平仓 |
| 移动止损 | trailing 5% | 市价平仓 |
| 时间止损 | 持有 > 20天 | 信号复查 |
| 回撤止损 | 总回撤 > 15% | 全量清仓 |

### 6.3 熔断机制

| 条件 | 动作 |
|------|------|
| 日内回撤 > 5% | 禁止开多 |
| 日内回撤 > 10% | 禁止所有开仓 |
| 连续亏损 > 3次 | 策略暂停 |

---

## 七、AI Lab 模块

> **参考来源**: TradingAgents (多 Agent 辩论架构) + Qlib RD-Agent (自动化因子挖掘)

### 7.1 Agent 层级架构

多 Agent 协作模拟真实交易公司，分 4 层：

**Layer 1 - 分析师团队（并行）**
| Agent | 职责 | 数据源 |
|-------|------|--------|
| MarketAnalyst | 技术分析 (MA, MACD, RSI, Bollinger, ATR, VWAP) | K线数据 |
| SocialMediaAnalyst | 社交媒体情绪 | 社区/论坛舆情 |
| NewsAnalyst | 新闻事件、宏观指标 | 舆情聚合 |
| FundamentalsAnalyst | 财报、估值、现金流 | 财务数据 |
| ChinaMarketAnalyst | A股特殊规则 (涨跌停、T+1、融资融券) | A股特有数据 |

**Layer 2 - 研究员辩论（多空）**
| Agent | 职责 |
|-------|------|
| BullResearcher | 看多倡导者，强调增长/竞争优势 |
| BearResearcher | 空方倡导者，揭示风险/利空因素 |

**Layer 3 - 交易员**
| Agent | 职责 |
|-------|------|
| Trader | 合成报告，做出 BUY/HOLD/SELL 决策 |

**Layer 4 - 风控团队（三方辩论）**
| Agent | 职责 |
|-------|------|
| AggressiveDebater | 激进方，主张承担风险获取收益 |
| ConservativeDebater | 保守方，主张降低风险 |
| NeutralDebater | 中立方，平衡双方观点 |

### 7.2 RD-Agent (因子挖掘引擎)

LLM 驱动的自动化因子/模型优化循环（参考 Qlib RD-Agent）：

```
探索因子空间 → 训练评估 → 反馈优化 → 循环迭代
```

- **Quant Factor Mining**: 自动发现新 alpha 因子
- **Quant Model Optimization**: 自动调优超参数

### 7.3 协作机制

- **讨论模式**: 用户发起 → Analyst Team → Bull/Bear Debate → Trader → Risk Debate → 流式输出
- **LangGraph 状态机**: AgentState 管理辩论状态和轮次
- **ChromaDB 向量记忆**: 每次决策后存储相似情境，供后续参考
- **人类参与**: 用户可随时通过 WebSocket 插话、修改或推翻决策
- **投票共识**: 重要决策时多 Agent 投票，多数赞同形成结论

---

## 八、舆情情报模块 (News Intelligence)

> **参考来源**: TrendRadar (多源聚合 + 趋势评分 + MCP 集成)

### 8.1 概述

舆情情报模块从 11+ 中文平台聚合热点新闻和社交媒体内容，通过关键词过滤和加权评分算法筛选与持仓/关注标的相关的舆情。

### 8.2 数据源

| 平台 | 来源 |
|------|------|
| 今日头条、百度热搜、华尔街见闻、澎湃、B站、财联社、凤凰、微博、知乎、抖音 | newsnow API |

### 8.3 关键词过滤

| 类型 | 语法 | 说明 |
|------|------|------|
| 普通词 | `AI` | 标题包含即匹配 |
| 必要词 | `+发布` | 同一行所有必要词同时出现 |
| 排除词 | `!广告` | 标题包含则过滤 |

### 8.4 加权趋势评分

| 因子 | 权重 |
|------|------|
| 排名分 (Rank) | 60% |
| 频率分 (跨平台出现次数) | 30% |
| 热度分 (平台热度值) | 10% |

### 8.5 三种推送模式

| 模式 | 说明 |
|------|------|
| `daily` | 当日所有匹配新闻汇总 |
| `current` | 当前排名匹配（显示排名变化） |
| `incremental` | 仅新出现的新闻（零重复） |

---

## 九、前端页面

| 页面 | 描述 |
|------|------|
| Dashboard | 组合概览、P&L、活跃持仓、最新信号 |
| Market | 行情报价、K线图、订单簿、市场扫描器 |
| News/Trending | 舆情聚合、热点主题、关键词过滤、趋势评分 |
| Trading | 模拟交易、下单、订单历史 |
| Strategies | 策略列表、回测运行器、信号分析 |
| AI Lab | 多 Agent 讨论空间（实时流式输出 + 人类参与） |
| Portfolio | 持仓、P&L历史、绩效图表 |
| Risk | 风险暴露、告警、风险限额 |
| Settings | API配置、数据源、LLM Provider、偏好设置 |

### 设计风格
- **主题**: 深色交易终端 (Bloomberg Terminal)
- **背景**: `#0a0e14`
- **涨跌色**: 绿色/红色
- **字体**: 等宽字体显示数据
- **实时**: WebSocket

---

## 九、API 规格

### 9.1 市场数据

| 端点 | 说明 |
|------|------|
| `GET /market/overview` | 市场概览 |
| `GET /market/kline/{symbol}` | K线数据 |
| `GET /market/tickers` | 实时行情 |
| `GET /market/depth/{symbol}` | 订单簿深度 |

### 9.2 策略

| 端点 | 说明 |
|------|------|
| `GET /strategy/strategies` | 策略列表 |
| `POST /strategy/backtest` | 运行回测 |
| `GET /strategy/backtest/{id}` | 回测结果 |

### 9.3 投资组合

| 端点 | 说明 |
|------|------|
| `GET /portfolio/positions` | 当前持仓 |
| `GET /portfolio/orders` | 订单列表 |
| `POST /portfolio/orders` | 创建订单 |
| `GET /portfolio/performance` | 绩效数据 |

### 9.4 AI Lab

| 端点 | 说明 |
|------|------|
| `POST /ailab/discuss` | 发起讨论 |
| `GET /ailab/discuss/{id}` | 获取讨论状态 |
| `WebSocket /ailab/ws/{discuss_id}` | 实时讨论流 |
| `POST /ailab/intervene` | 用户干预（插话/修改决策） |
| `GET /ailab/memory` | 查看历史决策记忆 |
| `POST /rdagent/factor/mine` | 启动因子挖掘任务 |
| `POST /rdagent/model/optimize` | 启动模型优化任务 |

### 9.5 舆情情报

| 端点 | 说明 |
|------|------|
| `GET /news/latest` | 最新聚合新闻 |
| `GET /news/trending` | 趋势主题列表 |
| `GET /news/search` | 关键词搜索新闻 |
| `GET /news/sentiment/{topic_id}` | 主题情感分析 |
| `WebSocket /news/ws` | 实时增量推送 |

### 9.6 LLM Provider

| 端点 | 说明 |
|------|------|
| `GET /llm/providers` | 列出所有 Provider |
| `POST /llm/providers` | 添加 Provider |
| `POST /llm/providers/{id}/test` | 测试连接 |
| `GET /llm/usage` | Token 用量统计 |

### 9.7 MCP Server

| 端点 | 说明 |
|------|------|
| `GET /mcp/tools` | 列出所有可用工具 |
| `POST /mcp/tools/call` | 调用指定工具 |

---

## 十、开发阶段

| 阶段 | 内容 | 周期 |
|------|------|------|
| Phase 1 | 数据基础设施 (采集、存储、API) | 2周 |
| Phase 2 | 策略框架与回测 | 2周 |
| Phase 3 | 投资组合引擎 | 2周 |
| Phase 4 | 风险引擎 | 1周 |
| Phase 5 | AI Lab 模块 | 2周 |
| Phase 6 | 前端界面 | 2周 |

---

## 十一、数据库 Schema

### stock_daily

```sql
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
```

### signals

```sql
CREATE TABLE signals (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    strength NUMERIC(5, 2),
    price NUMERIC(18, 4),
    metadata JSONB,
    backtest_id TEXT
);
```

### backtest_results

```sql
CREATE TABLE backtest_results (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    strategy_id TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_capital NUMERIC(18, 4),
    final_capital NUMERIC(18, 4),
    total_return NUMERIC(10, 4),
    sharpe_ratio NUMERIC(8, 4),
    max_drawdown NUMERIC(10, 4),
    win_rate NUMERIC(5, 4),
    metrics JSONB,
    equity_curve JSONB
);
```

---

**文档版本**: 1.1
**最后更新**: 2026-03-29
