# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ytrader — 量化交易平台。后端 Python FastAPI + DDD 分层，前端 React/TypeScript Rush monorepo。端口: 后端 `:12100`，前端 dev `:12000`。

## Commands

### Backend
```bash
cd backend
make install          # uv sync
make install-dev      # uv sync --extra dev
make run              # python main.py → 0.0.0.0:12100
make test             # python -m pytest tests/
make test-cov         # pytest with coverage
make format           # black + isort (line-length 79, skip-string-normalization: false)
make lint             # flake8 (max-line-length 79, ignore E203/W503)
```
Run single test: `.venv/bin/python -m pytest tests/path/test_file.py::test_name -v`

### Frontend
```bash
cd frontend
pnpm install          # install all monorepo packages
pnpm --filter web dev        # RSBuild dev server → localhost:12000, proxy /api → :12100
pnpm --filter web build      # production build → apps/web/dist/
rush update && rush build    # full monorepo build
```

### Docker Infrastructure
```bash
cd docker && docker compose up -d   # NewsNow(:4444), RSSHub(:1200), TrendRadar(:3333), Miniflux(:8380)
```

## Architecture

### Backend — DDD 四层架构 (依赖外层→内层)

```
backend/
├── main.py                     # 入口: 加载 .env → create_app() → lifespan → uvicorn
├── conf/config.yaml            # 运行时配置 (DB, RSS源, API keys)
├── conf/settings.py            # Pydantic config 单例 → app_config
└── src/
    ├── api/                    # API 层 — HTTP 端点
    │   ├── router/             #   30 个 Router 文件, 前缀 /api/v1/
    │   ├── handler/            #   请求处理器
    │   ├── middleware/         #   LoggingMiddleware, TraceIdMiddleware
    │   └── model/              #   请求/响应 Pydantic 模型
    ├── application/            # 应用层 — 组合领域+基础设施, 跨域编排
    │   ├── dto/                #   数据传输对象
    │   └── use_cases/          #   用例 (IntelUseCase, SubscriptionUseCase...)
    ├── domain/                 # 领域层 — 核心业务 (禁止导入 api/infra/conf)
    │   ├── market/             #   交易核心: strategy, intel, cache, sync, providers, news
    │   ├── file/               #   文件解析 (PDF)
    │   ├── llm/                #   LLM 配置领域
    │   ├── user/               #   用户管理
    │   └── product/            #   产品
    ├── crossdomain/            # 防腐层 — 跨领域接口, 防止领域间直接耦合
    ├── infra/                  # 基础设施层 — 实现 domain 定义的接口
    │   ├── database/           #   按域分子目录: agent/, alert/, blog/, intel/, llm/, mcp/, skill/, subscription/, user/
    │   │   └── sql_engine/     #   引擎: engine.py, dsn.py, base_repository.py, timescale_client.py
    │   ├── search/             #   Elasticsearch
    │   ├── storage/            #   MinIO
    │   ├── notification/       #   飞书通知
    │   └── scheduler.py        #   APScheduler (14 个定时任务)
    ├── data/                   # 数据定义: consts/, errno/, ddl/
    ├── pkg/                    # 零依赖工具包: exceptions/, logging/, responses/, utils/
    ├── llm/                    # LLM 客户端 (MiniMax, OpenAI 兼容协议)
    └── typings/errno/          # 错误码 IntEnum + 消息映射
```

### Layer Rules

| 层 | 职责 | 可依赖 | 禁止导入 |
|---|------|--------|---------|
| `api/` | HTTP 端点 | application, domain, infra | — |
| `application/` | 组合领域对象+基础设施 | domain, crossdomain | api, infra |
| `domain/` | 核心业务规则 | pkg, data | api, infra, conf |
| `crossdomain/` | 跨领域接口 | domain | api, infra |
| `infra/` | 实现基础设施契约 | domain (接口), conf | api |
| `pkg/` | 纯工具函数 | nothing | everything |

### Repository Pattern (核心规范)

1. **接口**: `domain/<domain>/repository_interface.py` → `I<Domain>Repository(ABC)` — 仅依赖 abc
2. **实现**: `infra/database/<domain>/repository.py` → `<Domain>Repository(I<Domain>Repository)` + `create_<domain>_repository()` 工厂
3. **消费**: `application/` use_case 只 import 接口和工厂函数, 不 import 实现类
4. **领域服务**: 接收 `I<Domain>Repository | None` 参数

参考范例: Intel 模块 — 接口 `domain/market/intel/repository_interface.py` → `IIntelRepository`; 实现 `infra/database/intel/repository.py`

### Router 规范

- SQLModel ORM 访问数据库, 禁止手写 SQL / 用 psycopg2 直接连接
- 表模型: `class Xxx(SQLModel, table=True)` + `Field()`
- 复杂查询可用 `session.execute(text(...))` 回退原始 SQL
- 统一响应: `{"code": 0, "msg": "ok", "data": {...}}`
- Helper: `from src.pkg.responses import ok, fail, error, ...`

### Scheduler (14 个定时任务)

| 定时任务 | 频率 | ID |
|---------|------|-----|
| 每日市场统计刷新 | 每日 16:05 | `daily_stats_refresh` |
| 价格告警检查 | 工作日 9-14 点每5分 + 15:00,15:05 | `alert_price_check` / `alert_price_check_15` |
| 策略自动执行 | 工作日 9-14 点每15分 | `strategy_auto_execute` |
| 资讯采集-社会热点 | 每10分 | `intel_collect_hotlist` |
| 资讯采集-财经情报 | 每15分 | `intel_collect_finance` |
| 资讯采集-未来前沿 | 每6小时 | `intel_collect_future_tech` |
| 资讯采集-央视新闻 | 每30分 | `intel_collect_cctv_news` |
| 资讯数据清理-5年 | 每日 03:07 | `intel_daily_cleanup` |
| 博客每日自动生成 | 每日 08:07 | `blog_daily_generation` |
| 资讯深度分析 (Agent) | 每30分 | `intel_agent_analysis` |
| 央视新闻-事件检测 | 每30分 | `cctv_event_detection` |
| 央视新闻-市场关联 | 每30分 | `cctv_market_correlation` |
| 订阅源同步 | 每15分 | `subscription_sync` |
| WeWe RSS 健康监控 | 每30分 | `wewe_health_check` |

### Startup Sequence (main.py lifespan)

1. 后台线程预热 DB (Intel repository)
2. Agent 表迁移 + 种子数据
3. APScheduler 启动所有定时任务
4. MiniMax API key 自动迁移到 llm_config 表
5. WebSocket tick_broadcaster 线程启动
6. 中间件: Logging → TraceId → CORS
7. 异常处理器: BaseAppException → RequestValidationError → 全局 Exception

## Frontend — Rush Monorepo

```
frontend/
├── apps/web/src/               # @ytrader/web — 应用入口
│   ├── App.tsx                 #   React Router v7: 18 条路由
│   ├── pages/                  #   页面: .tsx + .css 成对, 暗色主题
│   ├── components/             #   共享组件: Layout, Chart...
│   └── lib/api.ts              #   getApiBase() → 默认 /api/v1, 可被 Settings 覆盖
├── packages/
│   ├── arch/        (foundation)  API client, hooks, i18n, utils — 零外部依赖
│   ├── common/      (common)      通用组件 (Card, PnlBadge), 通用工具
│   └── trading/     (domain)      策略/组合/行情业务组件
└── config/          (tooling)     eslint, tsconfig, rsbuild
```

### Frontend Routes (18 pages)

`/dashboard`, `/market`, `/trading`, `/strategies`, `/portfolio`, `/analytics`, `/alerts`, `/settings`, `/ai-chat`, `/risk`, `/backtest`, `/financial`, `/factors`, `/reports`, `/intel`, `/celebrities`, `/blog`, `/subscriptions`

### Frontend Conventions

- React functional components + hooks, 2-space indent, single quotes
- CSS BEM-like: `intel-card__title`, `dashboard__card-value`
- 暗色主题, CSS 变量 + rgba 半透明背景
- API 消费: 检查 `json.code === 0` → 读 `json.data`

## Data Stores

| Store | Purpose | Client |
|-------|---------|--------|
| PostgreSQL (`localhost:5432`) | Primary data | SQLModel ORM |
| TimescaleDB (`172.19.0.4:5432`) | OHLCV time-series | asyncpg (timescale_client.py) |
| Elasticsearch (`localhost:9200`) | Full-text search | elasticsearch-py |
| MinIO (`localhost:9000`) | File storage | minio client |

## Coding Conventions

### Python

- PEP 8, line-length 79, 4-space indent
- 类型注解强制: 所有函数签名需标注参数+返回类型
- Formatter: black + isort; Linter: flake8
- 命名: 模块 snake_case, 类 PascalCase, 函数 snake_case, 常量 UPPER_SNAKE, 私有 `_` 前缀
- 配置: 所有 URL/端口/密码在 `conf/config.yaml`, 禁止硬编码; 通过 `from conf import app_config` 访问
- 数据库: 统一走 `infra/database/sql_engine/dsn.py` → `get_dsn()`
- 表模型: SQLModel 自动 create_all, 不需要手写 DDL
- 新增 API: router 文件 → `main.py` 注册 `app.include_router(..., prefix="/api/v1")`

### TypeScript / React

- 2-space indent, single quotes, 100 char width
- React functional components + hooks
- API base: `getApiBase()` from `src/lib/api.ts`; WebSocket: `getWsBase()`
- Monorepo 包按分层: `@ytrader/{layer}-{name}`, 跨包引用用 `workspace:*`

## Intel Module (资讯采集)

```
domain/market/intel/
├── collector.py                # NewsCollectorService + build_providers_from_config()
├── processor.py                # AI processing (sentiment, summary)
├── analysis/                   # 事件检测, 市场关联
├── agents/                     # LangGraph Agent 深度分析
├── blog/                       # 博客自动生成 (LangGraph)
└── providers/
    ├── base.py                 # BaseNewsProvider ABC
    ├── finnhub_provider.py
    ├── miniflux_provider.py
    ├── newsnow_provider.py
    └── wewe_provider.py        # WeWe RSS (微信公众号)
```

5 个采集类别: `hotlist`, `finance`, `future_tech`, `cctv_news`, 以及订阅源同步

## Error Codes

| 段 | 范围 | 示例 |
|----|------|------|
| 成功 | 0 | `SUCCESS = 0` |
| 通用 | 1-999 | `FAIL=1`, `INVALID_PARAM=100` |
| 文件 | 1000-1999 | `FILE_NOT_FOUND=1001` |
| 认证 | 2000-2999 | `UNAUTHORIZED=2001` |
| 业务 | 3000-3999 | 策略/交易/资讯 |
| 外部 | 4000-4999 | API 调用失败 |
| 内部 | 5000-5999 | DB 连接失败 |

## API Response Helpers

`from src.pkg.responses import ok, fail, error, validate_error, unauthorized, forbidden, not_found, page_success`

分页: `page_success(data, total, page, size)` → `{"code": 0, "data": {"records": [...], "total": N, "page": N, "size": N}}`

## Testing

### Backend (pytest)
```bash
cd backend
make test                    # 全量
.venv/bin/python -m pytest tests/path/test_file.py::test_name -v  # 单个
make test-cov                # 带覆盖率
```

测试目录结构镜像 `src/`。DB 测试用 cursor fixture 自动 rollback。类名 `Test{Resource}`, 方法名 `test_{action}_{expected}`。

### Frontend
暂无测试。如需添加: Vitest + React Testing Library, `pnpm --filter <pkg> test`。

## Environment

- `.env` 或系统环境变量: `MINIMAX_API_KEY`, `FEISHU_APP_ID`, `FEISHU_APP_SECRET`
- 数据库 URL 在 `conf/config.yaml`, 不通过环境变量

## Key Files

- `backend/main.py` — 应用入口
- `backend/conf/settings.py` — Pydantic config
- `backend/src/infra/scheduler.py` — 14 个定时任务
- `backend/src/infra/database/sql_engine/dsn.py` — DB 连接串
- `backend/src/infra/database/sql_engine/engine.py` — DBConnection + session_scope
- `backend/src/domain/market/intel/` — 资讯采集系统
- `frontend/apps/web/src/App.tsx` — 路由定义
- `frontend/apps/web/src/lib/api.ts` — API base URL
- `frontend/apps/web/rsbuild.config.ts` — Dev proxy config
- `docker/docker-compose.yml` — Docker 基础设施

## Notes
