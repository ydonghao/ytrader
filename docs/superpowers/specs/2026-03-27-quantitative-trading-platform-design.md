# 量化交易平台设计规格

**项目**: YTrader 量化交易平台
**版本**: 1.0
**日期**: 2026-03-27
**状态**: 待用户审查

---

## 1. 系统概述

### 1.1 目标

构建面向个人用户的量化交易平台，支持：
- 多市场：A股、港股、美股（股票 + ETF + 指数）
- 交易模式：研究/回测 + 策略共享 + AI Lab 协作
- 架构：云端部署，单体架构，中等规模

### 1.2 核心功能

| 功能 | 说明 |
|------|------|
| 市场数据 | 多市场数据采集、存储、实时行情 |
| 策略引擎 | 技术分析、基本面、事件驱动、统计套利 |
| AI Lab | 多 Agent 协作讨论股票、新闻、趋势 |
| 投资组合 | 持仓管理、订单管理、P&L 计算 |
| 风险引擎 | 仓位限制、止损止盈、规则引擎 |
| 团队协作 | 策略分享、评论 |
| 回测系统 | 历史数据模拟、绩效分析 |

### 1.3 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Zustand + Rsbuild |
| 后端 | FastAPI + Redis + TimescaleDB |
| 数据源 | AKShare, Tushare, Yahoo Finance |
| AI | OpenClaw / Claude API |
| 部署 | 云端服务 |

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     Frontend (Web)                              │
│  React 18 + TypeScript + Zustand + Rsbuild                     │
│  ├── Dashboard (组合概览, P&L, 持仓)                            │
│  ├── Market (行情, 图表, 订单簿)                                │
│  ├── Strategies (策略列表, 回测, 信号分析)                      │
│  ├── AI Lab (多 Agent 讨论空间)                                 │
│  ├── Portfolio (持仓, P&L, 绩效)                               │
│  ├── Risk (风险暴露, 告警)                                      │
│  ├── Collaboration (策略分享, 评论)                             │
│  └── Settings (配置)                                           │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP/WebSocket
┌────────────────────────────▼────────────────────────────────────┐
│                      Backend (单体)                             │
│  FastAPI + Redis + TimescaleDB                                 │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │   Market    │  │  Strategy   │  │ Portfolio  │            │
│  │   Data      │  │   Engine    │  │   Engine   │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │    Risk     │  │     AI      │  │   Team     │            │
│  │   Engine    │  │   Lab       │  │Collaboration│            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└────────────────────────────┬────────────────────────────────────┘
                             │
                  ┌──────────▼──────────┐
                  │    TimescaleDB     │
                  │  (时序数据存储)     │
                  └─────────────────────┘
```

---

## 3. 数据架构

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
| `stock_daily` | hypertable | 股票日线数据 (A股/港股/美股) |
| `stock_minute` | hypertable | 分钟线数据 (1/5/15/60分钟) |
| `stock_tick` | hypertable | 逐笔数据 |
| `etf_daily` | hypertable | ETF 日线数据 |
| `etf_nav` | hypertable | ETF 净值 (IOPV) |
| `index_daily` | hypertable | 指数日线 (沪深300/恒生/标普500) |
| `fundamental` | regular | 财务数据 (财报, 指标) |
| `backtest_results` | regular | 回测结果 |
| `signals` | regular | 交易信号 |

### 3.3 支持资产

- **股票**: A股 (SH/SZ)、港股 (HKEX)、美股 (NYSE/NASDAQ)
- **ETF**: 股票型、债券型、商品型、跨境ETF
- **指数**: 沪深300、上证指数、恒生指数、标普500等

---

## 4. 策略引擎架构

### 4.1 策略注册中心

- 策略动态加载
- 版本管理
- 策略工厂 (Factory) 模式
- IOC 容器管理生命周期

### 4.2 支持策略类型

| 类型 | 示例 | 信号类型 |
|------|------|---------|
| 技术分析 | MA, RSI, MACD, Bollinger Bands | 趋势跟踪、均值回归 |
| 统计套利 | Pairs trading, Correlation, Spread | 均值回归、收敛 |
| 因子策略 | Value, Momentum, Quality, Multi-factor | 多空 |
| 事件驱动 | Earnings, News, Corporate Actions | 事件驱动 |

### 4.3 核心组件

```
策略 → 信号 → 订单 异步消息传递
         │
    ┌────┴────┐
    ▼         ▼         ▼
参数优化器   信号过滤器   风控前置
(Optimizer)  (Filter)  (Pre-Risk)
• 网格搜索   • 多策略聚合 • 仓位检查
• 贝叶斯优化 • 优先级排序 • 限额检查
• 遗传算法   • 冲突解决   • 风险预算
             • 信号去重   • 熔断机制
```

### 4.4 事件调度

- 定时任务：盘前 (09:15)、盘中、盘后 (15:00)、美股收盘
- 外部事件：数据更新、信号生成
- Cron 表达式灵活调度

### 4.5 状态管理

- 策略内部状态持久化
- 计数器、缓存
- 断点恢复

### 4.6 回测引擎

- 历史数据模拟
- 交易成本与滑点模型
- 多资产支持
- Walk-forward 验证

### 4.7 结果分析器

- 收益曲线
- Sharpe/Sortino/Calmar 比率
- 最大回撤
- Alpha vs Benchmark

---

## 5. 投资组合引擎架构

### 5.1 核心模块

| 模块 | 功能 |
|------|------|
| 资金管理 | 账户余额、保证金、可用资金 |
| 持仓快照 | 历史持仓记录、回溯分析 |
| 多账户支持 | 券商账户分组 |

### 5.2 风控引擎

| 功能 | 说明 |
|------|------|
| 仓位限制 | 单股限额、行业限额、总仓位 |
| 止损止盈 | 移动止损、追踪止损、时间止损 |
| 规则引擎 | 自定义规则、触发告警、自动平仓 |

### 5.3 订单匹配引擎

| 订单类型 | 说明 |
|---------|------|
| 限价单 | 完全成交、冰山订单 |
| 市价单 | 部分成交、滑点模拟 |
| 条件单 | 止损单、止盈单 |

### 5.4 盈亏计算器

- 未实现盈亏
- 已实现盈亏
- 交易日志

### 5.5 绩效分析器

- 收益率
- Sharpe/Sortino 比率
- 最大回撤
- Alpha vs Benchmark

---

## 6. AI Lab 模块

### 6.1 模块定位

多 Agent 协作空间，模拟投资研究团队的工作方式，让不同专业视角的 Agent 讨论股票、新闻、趋势等，形成综合判断。

### 6.2 Agent 角色

| Agent | 职责 |
|-------|------|
| 市场分析师 Agent | 分析价格走势、技术指标、市场情绪 |
| 基本面 Agent | 分析财报、估值、行业发展 |
| 新闻 Agent | 追踪新闻事件、公告、社交媒体情绪 |
| 策略 Agent | 讨论策略逻辑、信号、回测结果 |
| 风控 Agent | 评估风险暴露、提出风控建议 |
| 协调员 Agent | 主持讨论、总结观点、形成交易建议 |

### 6.3 协作机制

**讨论模式：**
- 用户发起议题（如"分析茅台近期走势"）
- 协调员 Agent 邀请相关 Agent 加入讨论
- 各 Agent 依次发表观点，可互相评论
- 支持 WebSocket 流式输出，实时看到讨论进展

**投票共识：**
- 重要决策时，各 Agent 对观点投票
- 多数赞同形成结论
- 保留分歧意见供参考

**人类参与：**
- 用户可以随时插话、提问
- 用户可以指定讨论方向
- 最终决策保留人类确认

---

## 7. 前端设计

### 7.1 页面结构

| 页面 | 描述 |
|------|------|
| Dashboard | 组合概览、P&L、活跃持仓、最新信号 |
| Market | 行情报价、图表、市场扫描器 |
| Trading | 模拟交易 - 下单、开仓订单、订单历史 |
| Strategies | 策略列表、回测运行器、信号分析 |
| AI Lab | 多 Agent 讨论空间 |
| Portfolio | 持仓、P&L历史、绩效图表 |
| Risk | 风险暴露、告警、风险限额 |
| Collaboration | 策略分享、评论 |
| Settings | API配置、数据源、偏好设置 |

### 7.2 设计风格

- **主题**: 深色交易终端风格 (Bloomberg Terminal)
- **背景**: `#0a0e14` (减少眼疲劳)
- **涨跌色**: 绿色/红色
- **字体**: 等宽字体显示数据
- **实时更新**: WebSocket

---

## 8. API 设计

### 8.1 市场数据 API

| 端点 | 说明 |
|------|------|
| `GET /market/overview` | 市场概览 |
| `GET /market/kline/{symbol}` | K线数据 |
| `GET /market/tickers` | 实时行情 |
| `GET /market/depth/{symbol}` | 订单簿深度 |

### 8.2 策略 API

| 端点 | 说明 |
|------|------|
| `GET /strategy/strategies` | 策略列表 |
| `POST /strategy/backtest` | 运行回测 |
| `GET /strategy/backtest/{id}` | 回测结果 |

### 8.3 投资组合 API

| 端点 | 说明 |
|------|------|
| `GET /portfolio/positions` | 当前持仓 |
| `GET /portfolio/orders` | 订单列表 |
| `POST /portfolio/orders` | 创建订单 |
| `GET /portfolio/performance` | 绩效数据 |

### 8.4 AI Lab API

| 端点 | 说明 |
|------|------|
| `POST /ailab/discuss` | 发起讨论 |
| `GET /ailab/discuss/{id}` | 获取讨论状态 |
| `WebSocket /ailab/ws/{discuss_id}` | 实时讨论流 |

### 8.5 团队协作 API

| 端点 | 说明 |
|------|------|
| `GET /team/strategies` | 团队策略列表 |
| `POST /team/strategies` | 分享策略 |
| `POST /team/strategies/{id}/comment` | 评论策略 |

---

## 9. 项目结构

```
ytrader/
├── backend/
│   ├── src/
│   │   ├── api/              # API层 (routers, handlers, models)
│   │   ├── application/       # 应用层 (use cases, services)
│   │   ├── domain/            # 领域层 (entities, events)
│   │   │   ├── strategy/      # 策略领域
│   │   │   ├── portfolio/     # 组合领域
│   │   │   └── ailab/         # AI Lab 领域
│   │   ├── infra/             # 基础设施层 (database, cache, storage)
│   │   └── pkg/               # 工具包 (responses, exceptions, logging)
│   ├── conf/                  # 配置文件
│   └── tests/                 # 测试
│
├── frontend/
│   ├── apps/
│   │   └── web/               # 主应用
│   ├── packages/
│   │   ├── arch/              # 架构包 (api, hooks, i18n, utils)
│   │   ├── common/            # 通用组件 (Button, Card, Table...)
│   │   └── trading/           # 交易域包
│   │       ├── market-data/   # 行情数据
│   │       ├── strategy/      # 策略
│   │       ├── portfolio/     # 组合
│   │       └── ailab/        # AI Lab
│   └── config/                # 配置
│
└── docs/
    └── specs/                 # 设计规格文档
```

---

**文档状态**: 已完成，等待用户审查
