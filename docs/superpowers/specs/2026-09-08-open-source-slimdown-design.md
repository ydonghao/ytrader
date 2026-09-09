# ytrader 开源准备瘦身设计

- 日期：2026-09-08
- 状态：待用户评审
- 决策人：yuandonghao（四项方向决策已拍板，见下）
- 执行策略：方案 A——master 分阶段落地（用户未明确选择时按推荐项执行）

## 1. 背景与目标

ytrader 经多轮功能沉积（课程体系化、国家队全景、组合回测增强、AI 写作/Agent 平台、资讯采集等），已形成"量化主线 + 实验沉积层"的混合形态：后端 `src` 74,718 行 / 40 个 router；前端 `apps/web` 45,612 行 / 28 条路由 / 菜单 6 组 28 项；另有 1.2G 未跟踪的 `references/` 参考仓库克隆。

**目标**：收缩为纯 A 股量化研究工作站，使 master 成为可直接导出 public 孤儿分支的干净基底（public 分支沿用既定"零密钥孤儿导出"方案，本设计不重写 git 历史）。

### 用户已拍板的四项决策（2026-09-08）

| 决策点 | 结论 |
|---|---|
| 瘦身首要目标 | 为开源做准备 |
| AI/Agent 线 | 删写作线（blog 全家桶），留 AIChat 交易助手 |
| 资讯情报线 | 整体退役（Intel/Subscriptions/Celebrity/news + 7 个 scheduler job） |
| 模拟/重叠功能 | 激进清理（删模拟端点、合并回测三页、Brinson 归并） |

### 三条原则

1. **只删代码，不动数据**：DB 表与数据一律保留；全部删除走 git、可 revert。
2. **数字必须真**：瘦身后产品内不允许存在模拟数据端点。
3. **每阶段独立可验证**：一阶段一提交序列；测试跑子集并对照既有失败基线（全量回归存在 52 个既有失败 + 6 个收集错误，属历史存量，不以本次删除为由放行新增失败）。

## 2. 关键依赖事实（已逐一验证，实施时可直接引用）

| # | 事实 | 验证方式 |
|---|---|---|
| F1 | AIChat 后端（`ai_chat_router.py`）零 LLM 依赖：纯 psycopg2 + 关键词意图 + 模板回复 | 读文件头与 import 列表，docstring 自述 "No external LLM" |
| F2 | `agent_router.py` 复用 `intel/blog/agent/blog_agent` 基建；agent/skill/prompt/mcp/tracing 五件套与 blog 共生 | grep `intel.blog` 引用方清单 |
| F3 | `domain/market/intel/macro/` 对 intel 兄弟模块（fetch/providers/agents/blog）零 import，可随宏观线独立保留 | grep `from src.domain.market.intel` 于 macro/ 目录 |
| F4 | macro 周度 LLM 快照 job 使用 `infra/llm` + `domain/llm`（自研 provider），故 LLM 基建必须保留；`llm_config_router` 保留 | grep `infra.llm\|domain.llm` 全库引用方 |
| F5 | `factors_router` 为真实数据管线（psycopg2 + numpy，多数端点真算），仅 FF5 因子收益为 random 模拟且带 `_SIMULATED_WARNING` 告警；工作区有未提交改动（活跃开发中）→ **不整删** | 读文件头 + `git diff --stat` |
| F6 | `financial_router` docstring 自述 "simulated" 是**过时文档**，实际经 `financial_detail_handler`（2,443 行）接真实 fundamental 域，前端 27 处调用 | 读文件头 + handler 链路 |
| F7 | 工作区有 37 文件未提交改动（+971/−379，国家队回填/估值守卫/前端轮询等） | `git diff --stat` |
| F8 | `references/` 1.2G 中仅 24 个文件被 git 跟踪（.gitignore 类文件），主体为外部仓库克隆 | `git ls-files references | wc -l` |
| F9 | 死代码双证据项：`executor_router`（scheduler job 已注释 + 前端 0 调用）；`signal_router`（前端 0 调用，且是 `domain/market/news` 唯一消费者） | 探查报告交叉验证 |
| F10 | `report_router` / `ws_router` 均为纯 psycopg2 独立实现，不依赖情报线 |
| F11 | **财报雷达（boom）2026-09-08 落地（21 commit），全线保留**。其跨线依赖保留集：`domain/market/intel/agents/base.py`（boom llm_analyst 用 `load_prompt_from_db_or`/`render_prompt`）、`domain/market/news/` 整目录 + `infra/database/news_repository.py`（新闻文本源管线）、`scripts/news_backfill.py` 及其测试；前端路由 `/earnings-radar` + 菜单"财报雷达"保留 | 读 import 列表 |

## 3. 瘦身后产品形态

### 3.1 前端导航：6 组 28 项 → 5 组 21 项（含财报雷达）

| 分组 | 页面 |
|---|---|
| 总览 | Dashboard、Market、Indices、Watchlist |
| 研究 | Financial、**财报雷达（新功能，保留）**、Screener、Factors、Macro、NationalTeam、Reports |
| 交易 | Trading、回测实验室（LongTermBacktest 为主 + TTrading 收为 Tab）、PermPortfolio |
| 分析 | Analytics、Board、Risk、Alerts |
| AI / 系统 | AI 交易助手（AIChat）、Settings、SystemLogs |

### 3.2 后端 router：40 → 23

退役 17 个：`product`、`file`、`user`（脚手架三件套）、`intel`、`subscription`、`news`、`celebrity`（情报线）、`agent`、`skill`、`prompt`、`mcp`、`tracing`（Agent 五件套，随 blog 基建共生退役）、`signal`、`backtest`、`portfolio`、`executor`（模拟/边缘）、`blog`（此前已注释下线，本设计彻底删除）。

### 3.3 保留但注记

- **Reports + 飞书通知**：保留。喂的是 alerts + 行情真数据；密钥全在 `config.local.yaml`，代码无敏感物。
- **Trading 模拟盘**：保留。产品定位即模拟下单，属功能而非假数据。
- **Factors**：保留真实端点与页面主干；FF5 模拟子端点（`/factors/portfolio/factors` 的 random 因子收益、ff5 回归、alpha/signals 中 random 生成部分）**直接删除**，前端 Factors 页对应 Tab 同步移除——原则是"数字必须真"，不做标注保留。
- **AIChat**：保留现状（关键词引擎）；如未来要接真 LLM，走 `infra/llm`，与本设计无关。

## 4. 分阶段删除清单

### Phase -1（前置）：落盘当前工作

将工作区 37 文件的未提交改动按主题拆分提交（国家队回填、估值守卫、前端 `useIntervalWhenVisible` 轮询重构等）。瘦身自干净树开始。

### P0：零风险清除（行为零变化）

**前端死代码**（无路由、无引用）：
- `pages/FundFlow.tsx` + css（339 行）
- `pages/SectorScan.tsx` + css（575 行）
- `pages/Valuation.tsx`（181 行，功能已被 Financial 页内嵌 ValuationPercentileChart 取代）
- `components/IndexFinancialChart.tsx`（47 行，0 importer）
- `packages/arch/api` 全包（仅被死 hook 引用）
- `packages/arch/hooks` 中 `useTrading/useStrategy/useMarketData/useWebSocket`（625 行，仅 `useTheme` 被 App.tsx 使用，保留 useTheme）
- `packages/common/utils` 全包（app 0 引用）
- 误建深层嵌套目录 `frontend/packages/trader/ytrader/frontend/packages/trading/portfolio/`（shell 事故产物）

**后端死代码**：
- `domain/market/cache/`（368 行，全库 0 引用）
- `domain/market/strategy/agents/`（705 行，`fundamental/agents/__init__.py` 注释自证废弃）
- `domain/market/news/`（479 行，仅 signal_router 消费，随 P2 一起删亦可，此处预留）

**脚本与磁盘**：
- `scripts/` 一次性脚本删除或移入 `scripts/archive/`：`fix_intel_sources.py`、`fix_market_data_quality.py`（确认当前修复完成后）、`cleanup_provider_conflict.py`、`nt_backfill_2024q4.py`、`nt_backfill_sectors.py`、`macro_probe_gildata.py`、`verify_fred_series.py`、`migrate_feeds_to_miniflux.py`、已完成使命的 `backfill_*.py`（**`news_backfill.py` 除外**，F11：boom 新闻管线）及 log/json 进度文件
- `references/` 1.2G 整体移出仓库目录（如 `~/references-archive/`），属磁盘瘦身不动 git
- 根目录 `TradingAgents-CN/`（仅 12K 跟踪文件）确认后同上处理

### P1：情报线退役

**后端**：
- router：`intel_router`、`subscription_router`、`news_router`、`celebrity_router` + `intel_handler`
- domain：`intel/fetch/`、`intel/providers/`、`intel/collector.py`、`intel/processor.py`、`intel/subscription.py`、`intel/agents/`（**除 `base.py`**，F11：boom 依赖）、`intel/market/`（先确认 `fund_flow.py` 引用方，若 market_router 的 fund-flow 端点在用则保留该文件）、`application/intel/`
- infra：scheduler 砍 7 个 job（intel 采集×4、intel 清理、订阅同步、wewe 健康检查）及 `_run_intel_collect`/`_run_intel_cleanup`/`_run_subscription_sync`/`_run_wewe_health_check` 函数体；miniflux/wewe 相关 infra
- **明确保留**：`intel/macro/` 全部（F3）、macro 的 5 个 scheduler job

**前端**：`Intel.tsx`、`Subscriptions.tsx`、`SubscriptionResults.tsx`、`Celebrity.tsx` 四页及其菜单项。

### P2：AI 写作线 + Agent 五件套退役

**后端**：
- `domain/market/intel/blog/` 全部（2,376 行）
- `infra/database/blog/`（292 行）、`infra/image_gen`、`infra/image_search`、`api/handler/blog_handler.py`
- `main.py` 残留：blog_router 注释行、`migrate_blog_prompts()`、LangGraph `AsyncPostgresSaver` checkpointer 初始化
- router：`agent`、`skill`、`prompt`、`mcp`、`tracing`（F2 共生证据）+ `signal_router`
- **保留**：`domain/market/news/` + `infra/database/news_repository.py`（F11：news_router 删除后其唯一消费者是 boom；`sentiment.py` 若仅 signal 引用可单独摘除）
- **保留**：`infra/llm` + `domain/llm` + `llm_config_router`（F4：macro 周度 LLM job 依赖）、`ai_chat_router`（F1：零依赖）

**前端**：`BlogDraft.tsx`（2,089 行）、`pages/blog-themes/`（582 行）、`pages/blog/`（BlogChat/ExecutionLog）、`/ai-workspace/writer`、`/ai-workspace/llm-logs` 路由；WorkspaceSettings 三个 console（PromptConsole/ModelConsole/ToolConsole，970 行）裁掉，LLM 配置台并入 Settings。

### P3：模拟与重叠清理

- `backtest_router`（387 行，模拟收益）+ 前端 `Backtest.tsx` 页
- 前端 `Strategies.tsx`（纯前端 mock，零后端调用）+ `@ytrader/trading-strategy` 包
- `portfolio_router` 的模拟 Brinson 端点 + 前端 `Portfolio.tsx`（170 行，与 Dashboard/Analytics 重复）
- `executor_router`（F9 双证据）
- 回测合并：LongTermBacktest 为主页面改名"回测实验室"，TTrading（做T）收为 Tab；后端 `t_trading_router`、`lt_backtest_router` 均保留不动，仅前端合并入口
- factors 模拟子端点删除（见 3.3，含前端 Factors 页对应 Tab）；`financial_router` 过时 docstring 修正（F6）

### P4：收尾与依赖卸载

- 导航重组为 3.1 的 5 组 20 项；`Layout.tsx` 菜单与 `App.tsx` 路由同步清理
- Settings（2,138 行）裁剪 AI 配置后精简
- 依赖卸载：`elasticsearch`、`pymupdf`、可选组 `nacos`、`minio`；`langchain`/`langgraph`/`langchain-openai`/`langchain-core`/`langchain-anthropic` 在验证仅 blog 线使用后卸载（macro 用自研 `infra/llm` provider，预期可卸）
- `pyproject.toml`、Docker 镜像、`docker/` 构建文件同步瘦身
- 全站冒烟 + 文档更新（README 功能清单）

## 5. 执行策略（方案 A）

1. 每阶段开短分支（`slim/p0` … `slim/p4`），完成 后合入 master；
2. 每阶段验证流程：
   - 后端：`uv run pytest tests/api tests/domain/market/<子域>` 等子集，对照基线（必要时基线 worktree 对照）；
   - 前端：`pnpm build` 通过 + 保留页面逐页冒烟（启动前后端手工走查）；
   - grep 复核：被删模块名在全库无残留引用；
3. 全部阶段完成后，从瘦身后的 master 重建 public 孤儿分支（既有零密钥导出流程）。

## 6. 规模预估与风险

**预估收益**：净删 ~2.4 万行（后端 ~1.2 万、前端 ~1.2 万，约占代码库 30%）；router 40→23；菜单 28→21；卸 5+ 依赖；磁盘减 1.2G+。

**风险与对策**：

| 风险 | 对策 |
|---|---|
| P1/P2 隐蔽引用（lifespan、scheduler、前端 import 链）漏删致启动失败 | 每阶段启动冒烟 + grep 复核；FastAPI 启动即挂载全部 router，启动成功即接线正确 |
| 删除导致既有测试收集错误范围扩大 | 删除对应功能的测试文件同步删（blog 2 个、agents 6 个等），基线对照不允许新增失败 |
| macro 误伤 | F3 已验证零依赖；P1 实施时 macro 相关测试（intel 3 个测试中 macro 部分）必须保持通过 |
| factors 误删活跃开发工作 | F5 已定性为保留；仅动模拟子端点，且放在独立小提交 |
| boom（财报雷达）误伤 | F11 已划定保留集（`intel/agents/base.py`、news 域、news_repository、news_backfill）；每阶段终验含 `from src.domain.market.boom.service import build_default_service` 导入门 + boom 测试全绿 |
| 用户对某保留项反悔 | git revert 单阶段即可，DB 数据全程未动，恢复成本低 |

## 7. 明确不做的事（Non-goals)

- 不重写 git 历史（历史密钥问题由 public 孤儿分支方案解决，与既定决策一致）
- 不动 25 个主线 scheduler job 与数据同步管线
- 不删任何 DB 表、不清任何业务数据
- 不做 UI 视觉改版（导航重组仅动菜单结构，不动设计体系）
- 不在本次给 AIChat 接真 LLM

## 8. 成功标准

1. master 上 `uv run uvicorn main:app` 启动无 blog/intel/agent 相关报错，23 个 router 全部挂载；
2. 前端 `pnpm build` 通过，5 组 21 项导航全部可达且无死链，财报雷达页正常；
3. 测试子集无新增失败（对照 52 个既有失败基线）；
4. 全库 grep `intel/blog|application/intel|langgraph|elasticsearch|minio` 无业务代码残留；
5. 从 master 重建 public 分支时，需人工剔除的目录/文件较现状显著减少（目标：仅需处理 `conf/*.local.yaml` 类密钥文件）。
