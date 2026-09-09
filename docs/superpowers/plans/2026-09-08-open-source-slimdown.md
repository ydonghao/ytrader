# ytrader 开源准备瘦身 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按已批准的设计（`docs/superpowers/specs/2026-09-08-open-source-slimdown-design.md`）分五阶段退役情报线、AI 写作线、模拟/重叠功能，把 ytrader 收缩为纯量化研究工作站（router 40→23、菜单 28→21、净删 ~2.4 万行）。**2026-09-08 新增的财报雷达（boom）功能全线保留**（见 F13）。

**Architecture:** 每阶段（P0~P4）一条短分支 `slim/pN`，完成后合回 master；删除型任务以"引用清零 + 接线冒烟 + 测试基线对照"为验收门。所有代码删除走 git（可 revert），DB 数据一律不动。

**Tech Stack:** 后端 FastAPI + APScheduler + psycopg2 + uv；前端 React 18 + rsbuild + pnpm/Rush monorepo。

## Global Constraints

- 只删代码，不动数据：禁止任何 `DROP TABLE` / `DELETE FROM` 类操作。
- 每个后端任务完成后必须通过接线门：`cd backend && uv run python -c "import main; print('ok')"` 输出 `ok`。
- 每个前端任务完成后必须通过构建门：`cd frontend/apps/web && pnpm build` 退出码 0。
- 测试基线：全量回归存在 52 个既有失败 + 6 个收集错误（历史存量）。每阶段跑 `uv run pytest tests/api -q`，失败数不得超过本计划 Task 1 记录的基线值。
- 分支命名 `slim/p0` ~ `slim/p4`；Phase -1 的提交直接落 master。
- 行号会漂移：本计划给出的行号是 2026-09-08 快照，执行时以 grep 锚点为准。
- 提交信息格式：`refactor(slim/pN): …` / `chore(slim/pN): …`。

## 背景事实（已逐一验证，执行时可直接依赖）

| # | 事实 |
|---|---|
| F1 | `ai_chat_router.py` 零 LLM 依赖（docstring 自述 "No external LLM"），保留 |
| F2 | `agent/skill/prompt/mcp/tracing` 五个 router 复用 `domain/market/intel/blog/agent/blog_agent` 基建，随 blog 退役 |
| F3 | `domain/market/intel/macro/` 对 intel 兄弟模块零 import，独立保留 |
| F4 | macro 周度 LLM job 依赖 `infra/llm` + `domain/llm` + `llm_config_router`，全部保留 |
| F5 | `factors_router.py` 主体为真实计算，仅 FF5 类端点用 `random` 模拟并带 `_SIMULATED_WARNING`；只删模拟端点，不动主干 |
| F6 | `financial_router.py` docstring "simulated" 是过时文档，需修正；代码本身接真实数据，保留 |
| F7 | `market_router.py` 的 `/market/fund-flow` 端点（约 L1399）直连 akshare，与死页面 FundFlow.tsx 无关，保留 |
| F8 | `tests/domain/test_backtest.py` 测的是 `/strategy/backtest`（strategy_router，保留），**不删** |
| F9 | `Settings.tsx` AI tab 内：LLM 配置段（约 L233-271 调 `/llm/configs`）保留；MCP（L315-430）、Prompt（L461-490）、Agent（L495-525）、Skill（L556-600）四段删除 |
| F10 | `pages/blog/` 下的 PromptConsole/ModelConsole/ToolConsole/CodeEditor 被 `Settings.tsx` 和 `ai-workspace/WorkspaceSettings.tsx` 引用，必须先做 Settings 手术再删目录 |
| F11 | 前端验证无单测，验收 = `pnpm build` + 人工冒烟（启动 dev server 逐页点） |
| F12 | `frontend/pnpm-workspace.yaml` 用 `packages/**/*` 通配，直接删除包目录即解除注册；`apps/web/package.json` 显式依赖 `@ytrader/arch-api` 需同步移除 |
| F13 | **财报雷达（boom，2026-09-08 新落地，21 个 commit）必须保护**。其代码（`boom_router`、`domain/market/boom/`、`EarningsRadar` 页面、`infra/database/market/boom.py`、`financial_full.py`）均不在删除清单，但它有三个跨线依赖必须保留：① `domain/market/intel/agents/base.py`（`llm_analyst.py` 从中导入 `load_prompt_from_db_or`/`render_prompt`；该文件仅依赖 loguru+jinja2，均为 pyproject 显式依赖）；② `domain/market/news/` 整目录（`sync_service.py`+`models.py`+`news_provider.py`+`repository.py`，boom 用它同步新闻文本源）；③ `infra/database/news_repository.py`。相应地 `scripts/news_backfill.py`（新闻数据回填）与其测试也保留。boom 前端路由 `/earnings-radar`、菜单"财报雷达"（研究组）保留 |

---

## Phase -1：落盘当前未提交工作（master 直接提交）

### Task 1: 提交工作区 37 文件改动并记录测试基线

**Files:**
- Modify: 工作区全部未提交文件（见下方分组）
- Create: `/tmp/pytest_api_baseline.txt`（基线记录，不进 git）

**Steps:**

- [ ] **Step 1: 确认工作区状态**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader && git status --short`
Expected: 37 个 modified + 4 个 untracked（`backend/scripts/fix_market_data_quality.py`、`backend/src/domain/market/sync/jobs/valuation_guard.py`、`backend/tests/api/test_market_search_index_merge.py`、`frontend/apps/web/src/hooks/useIntervalWhenVisible.ts`）。

- [ ] **Step 2: 提交后端数据管线组（国家队回填/估值守卫/数据质量/市场端点）**

先粗扫各组 diff 确认主题归属（`git diff <file> | head -40`）：若某文件改动明显属于其他主题，挪到对应组——目标是全部落盘，分组准确性次之。

```bash
git add backend/src/domain/market/sync/jobs/national_team_backfill.py \
        backend/src/domain/market/sync/jobs/valuation_guard.py \
        backend/scripts/fix_market_data_quality.py \
        backend/conf/.national_team_backfill_quarters.json \
        backend/.news_backfill_progress.json \
        backend/src/api/router/market_router.py \
        backend/src/infra/scheduler.py \
        backend/scripts/backfill_history_gaps.py \
        backend/tests/api/test_market_search_index_merge.py
git commit -m "feat(market): 国家队回填推进+估值守卫+数据质量修复脚本"
```

- [ ] **Step 3: 提交后端 router/handler 通用改动组**

```bash
git add backend/main.py \
        backend/src/api/handler/intel_handler.py \
        backend/src/api/router/agent_router.py \
        backend/src/api/router/celebrity_router.py \
        backend/src/api/router/factors_router.py \
        backend/src/api/router/financial_router.py \
        backend/src/api/router/llm_config_router.py \
        backend/src/api/router/lt_backtest_router.py \
        backend/src/api/router/mcp_router.py \
        backend/src/api/router/news_router.py \
        backend/src/api/router/prompt_router.py \
        backend/src/api/router/signal_router.py \
        backend/src/api/router/skill_router.py \
        backend/src/api/router/strategy_router.py \
        backend/src/api/router/subscription_router.py \
        backend/src/api/router/ws_router.py \
        backend/tests/api/test_factors_router_simulated.py \
        backend/tests/api/test_valuation_percentile_exclude.py \
        backend/uv.lock
git commit -m "refactor(backend): router/handler 通用改动+factors模拟测试扩充"
```

- [ ] **Step 4: 提交前端轮询重构组**

```bash
git add frontend/apps/web/src/hooks/useIntervalWhenVisible.ts \
        frontend/apps/web/src/hooks/useFinancialOverlays.ts \
        frontend/apps/web/src/hooks/useValuationPercentile.ts \
        frontend/apps/web/src/components/ScreenerDrillModal.tsx \
        frontend/apps/web/src/components/ValuationPercentileChart.tsx \
        frontend/apps/web/src/pages/Analytics.tsx \
        frontend/apps/web/src/pages/Dashboard.tsx \
        frontend/apps/web/src/pages/Financial.tsx \
        frontend/apps/web/src/pages/Intel.tsx \
        frontend/apps/web/src/pages/Market.tsx \
        frontend/apps/web/src/pages/Reports.tsx \
        frontend/apps/web/src/pages/Screener.tsx \
        frontend/apps/web/src/pages/Trading.tsx \
        frontend/apps/web/src/pages/Watchlist.tsx
git commit -m "refactor(web): useIntervalWhenVisible 页面可见性轮询重构+估值分位增强"
```

- [ ] **Step 5: 确认干净树 + 记录测试基线**

```bash
git status --short   # Expected: 空（或仅剩本计划文档之外无内容）
cd backend && uv run pytest tests/api -q 2>&1 | tail -3 | tee /tmp/pytest_api_baseline.txt
```
Expected: pytest 汇总行（如 `X passed, Y failed`）。**记下 Y，后续所有阶段的 tests/api 失败数不得超过 Y。**

---

## Phase P0：零风险死代码清除

### Task 2: 前端死文件与死包删除

**Files:**
- Delete: `frontend/apps/web/src/pages/FundFlow.tsx`、`FundFlow.css`、`SectorScan.tsx`、`SectorScan.css`、`Valuation.tsx`
- Delete: `frontend/apps/web/src/components/IndexFinancialChart.tsx`
- Delete: `frontend/packages/arch/api/`（整包）
- Delete: `frontend/packages/arch/hooks/src/{useTrading,useStrategy,useMarketData,useWebSocket}.ts`
- Modify: `frontend/packages/arch/hooks/src/index.ts`（保留 useTheme 导出）
- Delete: `frontend/packages/common/utils/`（整包）
- Delete: `frontend/packages/trader/`（误建的嵌套目录）
- Modify: `frontend/apps/web/package.json`（移除 `@ytrader/arch-api` 依赖）

**Steps:**

- [ ] **Step 1: 删除前引用确认（防误删）**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend
grep -rn "FundFlow\|SectorScan\|pages/Valuation\|IndexFinancialChart" apps/web/src --include="*.tsx" --include="*.ts" | grep -v "pages/FundFlow\|pages/SectorScan\|pages/Valuation.tsx\|IndexFinancialChart.tsx"
grep -rn "useTrading\|useStrategy\|useMarketData\|useWebSocket\|@ytrader/arch-api\|@ytrader/common-utils" apps/web/src packages --include="*.ts" --include="*.tsx" | grep -v "packages/arch/api/\|packages/arch/hooks/src/use\|packages/common/utils/"
```
Expected: 两条命令均无输出（即除待删文件自身外零引用）。若出现引用，停下来检查——`useTheme` 的引用是预期内的（它保留），过滤条件已排除。

- [ ] **Step 2: 删除文件**

```bash
git rm apps/web/src/pages/FundFlow.tsx apps/web/src/pages/FundFlow.css \
       apps/web/src/pages/SectorScan.tsx apps/web/src/pages/SectorScan.css \
       apps/web/src/pages/Valuation.tsx \
       apps/web/src/components/IndexFinancialChart.tsx
git rm -r packages/arch/api packages/common/utils
git rm packages/arch/hooks/src/useTrading.ts packages/arch/hooks/src/useStrategy.ts \
       packages/arch/hooks/src/useMarketData.ts packages/arch/hooks/src/useWebSocket.ts
rm -rf packages/trader   # 未跟踪的误建目录
```

- [ ] **Step 3: 清理 arch/hooks 出口**

编辑 `packages/arch/hooks/src/index.ts`：删除 `useTrading/useStrategy/useMarketData/useWebSocket` 四个 export 行，仅保留 `useTheme` 相关导出。若该文件只有这四个 hook 的导出加 useTheme，改完后应只剩 useTheme。

- [ ] **Step 4: 移除 arch-api 依赖**

编辑 `apps/web/package.json`，删除 `    "@ytrader/arch-api": "0.0.1",` 一行。然后在 `frontend/` 下执行 `pnpm install` 刷新 lockfile。

- [ ] **Step 5: 构建门**

```bash
cd frontend/apps/web && pnpm build
```
Expected: 构建成功，退出码 0。

- [ ] **Step 6: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader && \
git add -A frontend && git commit -m "refactor(slim/p0): 删除前端死页面/死组件/死包(FundFlow/SectorScan/Valuation/arch-api/common-utils)"
```

### Task 3: 后端死代码与脚本归档

**Files:**
- Delete: `backend/src/domain/market/cache/`、`backend/src/domain/market/strategy/agents/`
- Delete: `backend/tests/domain/market/strategy/test_agents.py`、`backend/tests/test_fundamental_analyst.py`、`backend/tests/test_pdf_parser.py`、`backend/tests/test_file_analysis.py`、`backend/tests/api/handler/test_file_handler.py`（若属 file 脚手架）
- Delete: `backend/scripts/` 下一次性脚本与 4 个进度 log/json
- Move: `references/` 与 `TradingAgents-CN/` 移出仓库目录

**Steps:**

- [ ] **Step 1: 引用确认**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
grep -rn "market.cache\|market\.strategy\.agents\|strategy.agents" src/ --include="*.py" | grep -v "src/domain/market/cache/\|src/domain/market/strategy/agents/"
head -30 tests/test_fundamental_analyst.py   # 确认 import 的是 strategy/agents（死代码）
head -30 tests/api/handler/test_file_handler.py  # 确认测的是 file_handler 脚手架
```
Expected: grep 无输出；两个测试文件的 import 指向待删模块。若 `test_file_handler.py` 实际测试仍在用的代码，把它从删除列表去掉。

- [ ] **Step 2: 删除死代码与对应测试**

```bash
git rm -r src/domain/market/cache src/domain/market/strategy/agents
git rm tests/domain/market/strategy/test_agents.py tests/test_fundamental_analyst.py tests/test_pdf_parser.py tests/test_file_analysis.py
```
（`test_file_handler.py` 视 Step 1 结果决定是否 `git rm tests/api/handler/test_file_handler.py`。）

- [ ] **Step 3: 脚本归档**

```bash
mkdir -p scripts/archive
git mv scripts/fix_intel_sources.py scripts/cleanup_provider_conflict.py \
       scripts/nt_backfill_2024q4.py scripts/nt_backfill_sectors.py \
       scripts/macro_probe_gildata.py scripts/verify_fred_series.py \
       scripts/migrate_feeds_to_miniflux.py scripts/archive/
git rm scripts/backfill_all.py scripts/backfill_ohlcv.py scripts/backfill_minute.py \
       scripts/backfill_tencent.py scripts/backfill_stock_info.py
git ls-files scripts/ | grep -E "\.(log|json)$" | grep -v news_backfill | xargs -r git rm
```
注意：`fix_market_data_quality.py`、`backfill_history_gaps.py` 是近期数据质量工作，**不归档**；`scripts/news_backfill.py` 与 `.news_backfill_progress.json` **保留**（F13：boom 的新闻数据回填管线）；`macro_backfill_30y.py` 保留（宏观线）；`watch_sina_and_backfill.py`、`sina_watcher.sh`、`seed_portfolio.py`、`market_dashboard.py`、`debug_blog_agent.py`（P2 随 blog 删）、`quant_schema.sql`、`seed/` 保留。

- [ ] **Step 4: references 归档移出**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git ls-files references TradingAgents-CN | xargs -r git rm --cached
mkdir -p ~/references-archive
mv references ~/references-archive/ytrader-references
mv TradingAgents-CN ~/references-archive/ 2>/dev/null || true
git commit -m "chore(slim/p0): references/1.2G与TradingAgents-CN移出仓库归档至~/references-archive"
```

- [ ] **Step 5: 接线门 + 测试门**

```bash
cd backend && uv run python -c "import main; print('ok')"
uv run pytest tests/api -q 2>&1 | tail -1
```
Expected: 输出 `ok`；pytest 失败数 ≤ 基线。

- [ ] **Step 6: Commit（脚本与死代码）**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader && \
git add -A backend && git commit -m "refactor(slim/p0): 删除后端死代码(cache/strategy-agents)+一次性脚本归档"
```

---

## Phase P1：情报线退役（intel/subscription/news/celebrity）

### Task 4: 后端情报线删除

**Files:**
- Delete: `backend/src/api/router/{intel,subscription,news,celebrity}_router.py`、`backend/src/api/handler/intel_handler.py`
- Delete: `backend/src/application/intel/`（整目录）
- Delete: `backend/src/domain/market/intel/` 下 `fetch/`、`providers/`、`agents/`、`market/`、`collector.py`、`processor.py`、`subscription.py`
- Modify: `backend/main.py`（删 import 与 include）、`backend/src/infra/scheduler.py`（删 7 job）
- Delete tests: `backend/tests/agents/test_celebrity.py`、`backend/tests/scripts/test_news_backfill.py`、`backend/tests/infra/database/test_news_repository.py`

**Steps:**

- [ ] **Step 1: 开分支**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader && git checkout -b slim/p1
```

- [ ] **Step 2: 删除 router/handler/domain/application**

```bash
git rm backend/src/api/router/intel_router.py backend/src/api/router/subscription_router.py \
       backend/src/api/router/news_router.py backend/src/api/router/celebrity_router.py \
       backend/src/api/handler/intel_handler.py
git rm -r backend/src/application/intel
git rm -r backend/src/domain/market/intel/fetch backend/src/domain/market/intel/providers
git rm backend/src/domain/market/intel/agents/tagging.py \
       backend/src/domain/market/intel/agents/skill_executor.py \
       backend/src/domain/market/intel/agents/mcp_tool_node.py \
       backend/src/domain/market/intel/agents/repository_interface.py \
       backend/src/domain/market/intel/agents/models.py
git rm -r backend/src/domain/market/intel/market
git rm backend/src/domain/market/intel/collector.py \
       backend/src/domain/market/intel/processor.py \
       backend/src/domain/market/intel/subscription.py
```
注意：`intel/agents/base.py` **保留**（F13：boom 的 llm_analyst 依赖）；`intel/macro/`、`intel/blog/`（P2 处理）、`intel/models.py`、`intel/repository_interface.py`、`intel/__init__.py` 暂不动。若 `intel/agents/__init__.py` 或 `intel/__init__.py` 导入了已删子模块，把对应 import 行删除。

- [ ] **Step 3: main.py 摘线**

```bash
grep -n "intel_router\|subscription_router\|news_router\|celebrity_router" backend/main.py
```
删除匹配到的 import 行（约 L41/42/45/49）与 include 行（约 L371/372/375/379）。当前快照：
- `from src.api.router.news_router import router as news_router`
- `from src.api.router.intel_router import router as intel_router`
- `from src.api.router.celebrity_router import router as celebrity_router`
- `from src.api.router.subscription_router import router as subscription_router`
- `app.include_router(news_router, prefix="/api/v1")  # /api/v1/news`
- `app.include_router(intel_router, prefix="/api/v1")  # /api/v1/intel`
- `app.include_router(celebrity_router, prefix="/api/v1")  # /api/v1/celebrities`
- `app.include_router(subscription_router, prefix="/api/v1")  # /api/v1/subscriptions`

- [ ] **Step 4: scheduler 砍 7 个 job**

```bash
grep -n "_run_intel_collect\|_run_intel_cleanup\|_run_subscription_sync\|_run_wewe_health_check\|intel_collect_\|subscription_sync\|wewe_health_check" backend/src/infra/scheduler.py
```
按锚点删除（当前快照：闭包定义在 L248/319/336/364，job id 为 `intel_collect_hotlist` L285、`intel_collect_finance` L294、`intel_collect_future_tech` L303、`intel_collect_cctv_news` L312、intel 清理注册 L327 附近、`subscription_sync` L354、`wewe_health_check` L464）。整段删除从闭包 `def _run_intel_collect(categories...)` 起到对应 `scheduler.add_job(...)` 调用为止。删除后再 grep 一次，Expected: 无输出。

- [ ] **Step 5: 残留引用清剿**

```bash
cd backend && grep -rn "application.intel\|intel_router\|subscription_router\|news_router\|celebrity_router\|miniflux\|wewe\|WeWe" src/ main.py --include="*.py" | grep -v "intel/blog"
```
Expected: 无输出（`intel/blog` 里的 miniflux 引用留给 P2）。若 `main.py` lifespan 或别处残留 intel 初始化调用，一并删除。

- [ ] **Step 6: 删除对应测试 + 接线门 + 测试门**

```bash
git rm tests/agents/test_celebrity.py
rmdir tests/agents 2>/dev/null || true   # 目录空了才删，非空则保留
uv run python -c "import main; print('ok')"
uv run pytest tests/api -q 2>&1 | tail -1
```
注意：`tests/scripts/test_news_backfill.py` 与 `tests/infra/database/test_news_repository.py` **保留**（F13：news 管线随 boom 存续）。Expected: `ok`；失败数 ≤ 基线。

- [ ] **Step 7: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader && \
git add -A backend && git commit -m "refactor(slim/p1): 情报线退役——intel/subscription/news/celebrity router+domain+7个scheduler job"
```

### Task 5: 前端情报页删除

**Files:**
- Delete: `frontend/apps/web/src/pages/{Intel,Subscriptions,SubscriptionResults,Celebrity}.tsx` 及同名 `.css`
- Modify: `frontend/apps/web/src/App.tsx`（删 3 条路由）、`frontend/apps/web/src/components/Layout.tsx`（删 情报/名人持仓 菜单项）

**Steps:**

- [ ] **Step 1: 删除页面与引用确认**

```bash
cd frontend && git rm apps/web/src/pages/Intel.tsx apps/web/src/pages/Intel.css \
       apps/web/src/pages/Subscriptions.tsx apps/web/src/pages/Subscriptions.css \
       apps/web/src/pages/SubscriptionResults.tsx apps/web/src/pages/SubscriptionResults.css \
       apps/web/src/pages/Celebrity.tsx apps/web/src/pages/Celebrity.css
grep -rn "Subscriptions\|SubscriptionResults\|Celebrity\|pages/Intel\|from './Intel'" apps/web/src --include="*.tsx" | grep -v "pages/Subscriptions\|pages/SubscriptionResults\|pages/Celebrity"
```
Expected: grep 无输出。

- [ ] **Step 2: App.tsx 删路由**

删除（grep 锚点 `path="/intel"`、`path="/celebrities"` 及顶部 import）：
```tsx
<Route path="/intel" element={<Intel />} />
<Route path="/celebrities" element={<Celebrity />} />
```
保留 `/ai-chat` 重定向（它指向保留页）。

- [ ] **Step 3: Layout.tsx 删菜单项**

删除 研究 组中的两行：
```tsx
{path: '/intel', label: '情报', icon: Icon.intel},
{path: '/celebrities', label: '名人持仓', icon: Icon.reports},
```
若 `Icon.intel` 因此不再被引用，从 icons import 中移除（`Icon.intel` 在 AI 组的 AI交易助手 还在用，通常保留）。

- [ ] **Step 4: 构建门 + Commit**

```bash
cd apps/web && pnpm build && cd ../.. && \
git add -A frontend && git commit -m "refactor(slim/p1): 删除前端情报页(Intel/Subscriptions/Celebrity)+菜单路由收线"
```

### Task 6: P1 合并 master

- [ ] **Step 1: 冒烟**：`cd backend && uv run uvicorn main:app --port 8901 &`，起前端 `cd frontend/apps/web && pnpm dev`，逐页点过保留页面（Dashboard/Market/Indices/Watchlist/Financial/Screener/Factors/Macro/NationalTeam/Reports/Trading/TTrading/Strategies/Portfolio/Backtest/LtBacktest/PermPortfolio/Analytics/Board/Risk/Alerts/AIChat/Settings/SystemLogs），确认无 404/白屏，重点验证 **Macro 页正常**（宏观线保留的证明）。杀掉进程。
- [ ] **Step 2: 合并**：`git checkout master && git merge --no-ff slim/p1 -m "merge slim/p1: 情报线退役"`

---

## Phase P2：AI 写作线 + Agent 五件套退役

### Task 7: Settings.tsx 手术（保留 LLM 配置，裁四个 console）

**Files:**
- Modify: `frontend/apps/web/src/pages/Settings.tsx`（约 1560 行 → 预期 ~900 行）
- Delete: `frontend/apps/web/src/pages/ai-workspace/WorkspaceSettings.tsx` + `.css`
- Modify: `frontend/apps/web/src/App.tsx`、`frontend/apps/web/src/components/Layout.tsx`

**Steps:**

- [ ] **Step 1: 开分支**

```bash
git checkout master && git checkout -b slim/p2
```

- [ ] **Step 2: 删除 Settings.tsx 四个 console 段落**

依据 F9 的段落地图，逐段删除（每段 = state 定义 + handler 函数 + JSX 渲染块）：
- **MCP 段**：state `mcpForm/toolConsole*`（约 L74-81）、handlers `loadToolConsoleTools/executeToolConsole` 等（约 L315-430）、JSX 中 MCP servers 管理与 Tool Console 区块
- **Prompt 段**：`/prompts` 相关 fetch（约 L461-490）及渲染区块
- **Agent 段**：`/agent/configs`、`/agent/pipelines` 相关（约 L495-525）及渲染区块
- **Skill 段**：`/skills` 相关（约 L556-600）及渲染区块

保留：`/llm/configs` 全部逻辑（L130、L233-271 的 CRUD/test/default）、`/settings`、`/settings/feishu_open_id`、`/alerts/check`、`/system/health` 段。

操作方法：对每个待删 state 名与 endpoint 做 `grep -n` 定位全部出现点，从上到下删除；AI tab（`topTab === 'ai'` 区块，约 L710 起）删完后应只剩 LLM 配置卡片。

- [ ] **Step 3: 删除 WorkspaceSettings 页与路由/菜单**

```bash
git rm apps/web/src/pages/ai-workspace/WorkspaceSettings.tsx apps/web/src/pages/ai-workspace/WorkspaceSettings.css
```
App.tsx 删除：
```tsx
<Route path="/ai-workspace/settings" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><WorkspaceSettings /></Suspense>} />
```
及 `WorkspaceSettings` 的 lazy import。Layout.tsx 删除 AI 组的：
```tsx
{path: '/ai-workspace/settings', label: '工作台设置', icon: Icon.settings},
```
Settings.tsx 若有 `forceTab` prop 逻辑（L25-29），保留——`/agent-config` 重定向仍指向 `/settings`，该逻辑无害。

- [ ] **Step 4: 构建门 + Commit**

```bash
cd frontend/apps/web && pnpm build && cd ../.. && \
git add -A frontend && git commit -m "refactor(slim/p2): Settings裁掉MCP/Prompt/Agent/Skill四console,保留LLM配置;删WorkspaceSettings"
```
若 build 报 `pages/blog/` 下 console 组件的 import 错误，属预期（F10）：把 Settings.tsx 顶部对 `../blog/PromptConsole` 等的 import 一并删除即可——这些组件的 UI 已在 Step 2 被移除。

### Task 8: 后端 blog/agent 五件套删除

**Files:**
- Delete: `backend/src/domain/market/intel/blog/`、`backend/src/infra/database/blog/`、`backend/src/infra/image_gen*`、`backend/src/api/handler/blog_handler.py`、`backend/src/api/router/blog_router.py`
- Delete routers: `agent/skill/prompt/mcp/tracing/signal` 六个
- Modify: `backend/main.py`（blog 残留 + 六 router 摘线）、`backend/scripts/debug_blog_agent.py` 删除
- Delete tests: `backend/tests/blog/`
- **保留（F13 boom 依赖）**：`domain/market/news/` 整目录、`infra/database/news_repository.py` 及其测试——news_router 删除后它们唯一的消费者是 boom 的 `build_default_service()`

**Steps:**

- [ ] **Step 1: 删除 blog 域与基建**

```bash
cd backend
git rm -r src/domain/market/intel/blog src/infra/database/blog
ls src/infra/ | grep -i image    # 找到 image_gen/image_search 实际目录名
git rm -r src/infra/image_gen src/infra/image_search 2>/dev/null || true
git rm src/api/handler/blog_handler.py src/api/router/blog_router.py scripts/debug_blog_agent.py
```

- [ ] **Step 2: 删除 agent 五件套 + signal + news 域**

```bash
git rm src/api/router/agent_router.py src/api/router/skill_router.py \
       src/api/router/prompt_router.py src/api/router/mcp_router.py \
       src/api/router/tracing_router.py src/api/router/signal_router.py
git rm -r tests/blog
```
注意：**不要删除** `src/domain/market/news/` 与 `src/infra/database/news_repository.py`（F13）。signal_router 删除后，检查 `domain/market/news/` 中是否有仅被 signal 引用的模块（如 `sentiment.py`），有则单独摘除，`sync_service/models/news_provider/repository` 四件必须保留。

- [ ] **Step 3: main.py 残留清理**

依据 F2 前的 grep 结果删除：L47-48（blog_router 注释 import）、L193-199（`migrate_blog_prompts` import 与调用）、L233-239（LangGraph `AsyncPostgresSaver` checkpointer 初始化整段，含 warning 日志行）、L377-378（include 注释行）。再删除六 router 的 import（L44 `agent_router`、L46 `prompt_router`、L53-55 `mcp/skill/tracing`、L23 `signal_router`）与 include（L352、L374、L376、L380、L384-385）。

- [ ] **Step 4: 残留引用清剿**

```bash
grep -rn "intel.blog\|blog_agent\|image_gen\|image_search\|agent_router\|skill_router\|prompt_router\|mcp_router\|tracing_router\|signal_router\|langgraph\|AsyncPostgresSaver" src/ main.py --include="*.py"
```
Expected: 无输出。若 `llm_config_router` 或 `macro/` 之外出现 langchain 引用，记录文件名——P4 卸依赖前还要复核。

- [ ] **Step 5: 接线门 + 测试门 + Commit**

```bash
uv run python -c "import main; print('ok')"
uv run pytest tests/api -q 2>&1 | tail -1
cd .. && git add -A backend && git commit -m "refactor(slim/p2): AI写作线退役——blog域+agent/skill/prompt/mcp/tracing/signal六router+news域+LangGraph基建"
```
Expected: `ok`；失败数 ≤ 基线。

### Task 9: 前端 blog 全家桶删除

**Files:**
- Delete: `frontend/apps/web/src/pages/blog/`（整目录，含 consoles）、`BlogDraft.tsx/.css`、`pages/blog-themes/`
- Modify: `App.tsx`（删 /blog、/ai-workspace/writer、/ai-workspace/llm-logs 路由与 lazy import）、`Layout.tsx`（删 博客/写作助手/LLM日志 菜单项）

**Steps:**

- [ ] **Step 1: 删除文件**

```bash
cd frontend
git rm -r apps/web/src/pages/blog apps/web/src/pages/blog-themes
git rm apps/web/src/pages/BlogDraft.tsx apps/web/src/pages/BlogDraft.css
```

- [ ] **Step 2: 路由与菜单收线**

App.tsx 删除：
```tsx
<Route path="/ai-workspace/writer" element={...<WriterAssistant />...} />
<Route path="/ai-workspace/llm-logs" element={...<LlmLogs />...} />
<Route path="/blog" element={<BlogDraft />} />
```
及对应 lazy import（`WriterAssistant/LlmLogs/BlogDraft`）。Layout.tsx 删除：
```tsx
{path: '/blog', label: '博客', icon: Icon.blog},
{path: '/ai-workspace/writer', label: '写作助手', icon: Icon.blog},
{path: '/ai-workspace/llm-logs', label: 'LLM日志', icon: Icon.terminal},
```

- [ ] **Step 3: 残留引用清剿 + 构建门 + Commit**

```bash
grep -rn "BlogDraft\|BlogChat\|WriterAssistant\|LlmLogs\|blog-themes\|pages/blog" apps/web/src --include="*.tsx" --include="*.ts"
```
Expected: 无输出。
```bash
cd apps/web && pnpm build && cd ../.. && \
git add -A frontend && git commit -m "refactor(slim/p2): 删除前端blog全家桶(BlogDraft/BlogChat/主题渲染/三console)"
```

### Task 10: P2 合并 master

- [ ] **Step 1: 冒烟**（同 Task 6 的页面清单，另重点验证 Settings 页系统 tab 与 AI tab 的 LLM 配置卡仍可用）。
- [ ] **Step 2: 合并**：`git checkout master && git merge --no-ff slim/p2 -m "merge slim/p2: AI写作线+Agent五件套退役"`

---

## Phase P3：模拟/重叠清理 + 回测合并

### Task 11: 后端模拟 router 删除

**Files:**
- Delete: `backend/src/api/router/{backtest,portfolio,executor}_router.py`
- Modify: `backend/main.py`（三处 import/include：L30/31/33 与 L360/361/363）
- Delete: `backend/tests/infra/test_strategy_executor_positions.py`
- Modify: `backend/src/api/router/financial_router.py`（docstring 修正）

**Steps:**

- [ ] **Step 1: 开分支 + 引用确认**

```bash
git checkout master && git checkout -b slim/p3
cd backend && grep -rn "backtest_router\|portfolio_router\|executor_router\|/api/v1/backtest\|strategy_executor" src/ main.py --include="*.py" | grep -v "lt_backtest\|portfolio/backtester\|perm_portfolio\|portfolio/risk\|portfolio_repository"
```
Expected: 仅 main.py 的 import/include 行与三个待删文件自身。

- [ ] **Step 2: 删除**

```bash
git rm src/api/router/backtest_router.py src/api/router/portfolio_router.py src/api/router/executor_router.py
git rm tests/infra/test_strategy_executor_positions.py
```
main.py 删除：
```python
from src.api.router.portfolio_router import router as portfolio_router
from src.api.router.executor_router import router as executor_router
from src.api.router.backtest_router import router as backtest_router
app.include_router(portfolio_router, prefix="/api/v1")  # /api/v1/portfolio
app.include_router(executor_router, prefix="/api/v1")   # /api/v1/executor
app.include_router(backtest_router, prefix="/api/v1")  # /api/v1/backtest
```
scheduler 里 `strategy_auto_execute` 的注释行一并删除（grep `strategy_auto_execute`）。

- [ ] **Step 3: financial_router docstring 修正**

把 `backend/src/api/router/financial_router.py` 头部 docstring 中 `using simulated data` 改为 `from TimescaleDB via financial_detail_handler (real data)`。

- [ ] **Step 4: 接线门 + 测试门 + Commit**

```bash
uv run python -c "import main; print('ok')"
uv run pytest tests/api tests/domain -q 2>&1 | tail -1
cd .. && git add -A backend && git commit -m "refactor(slim/p3): 删模拟router(backtest/portfolio/executor)+financial docstring修正"
```
注意：`tests/domain/test_backtest.py` 测 `/strategy/backtest`（F8），**保留**。

### Task 12: factors 模拟端点收缩

**Files:**
- Modify: `backend/src/api/router/factors_router.py`（删 random 数据端点）
- Modify: `backend/tests/api/test_factors_router_simulated.py`（删对应端点测试）
- Modify: `frontend/apps/web/src/pages/Factors.tsx`（删对应 Tab/区块）

**Steps:**

- [ ] **Step 1: 定位模拟端点**

```bash
cd backend && grep -n "random\|_SIMULATED_WARNING" src/api/router/factors_router.py
```
判定规则：**handler 内使用 `random` 生成返回数据的端点 → 删**；仅用 psycopg2/numpy 真算的端点 → 留。按当前快照，预期删除候选：`/factors/portfolio/factors`（FF5 因子收益）、`/factors/portfolio/ff5/{symbol}`（FF5 回归）、以及 `alpha/signals`/`factor_correlation` 中依赖模拟收益的部分。逐一打开 handler 确认后删函数（连带 `_SIMULATED_WARNING` 常量若无消费方）。

- [ ] **Step 2: 同步删测试**

```bash
grep -n "portfolio/factors\|ff5\|alpha/signals\|factor_correlation" tests/api/test_factors_router_simulated.py
```
删除已删端点的测试函数（保留真实端点的测试）。

- [ ] **Step 3: 前端 Factors.tsx 同步**

```bash
cd ../frontend && grep -n "portfolio/factors\|ff5\|alpha/signals\|factor_correlation" apps/web/src/pages/Factors.tsx
```
删除调用已删端点的 fetch 与对应 Tab/图表区块。

- [ ] **Step 4: 双端门 + Commit**

```bash
cd apps/web && pnpm build && cd ../../backend && \
uv run python -c "import main; print('ok')" && uv run pytest tests/api/test_factors_router_simulated.py -q 2>&1 | tail -1
cd .. && git add -A backend frontend && git commit -m "refactor(slim/p3): factors模拟端点退役(FF5/alpha模拟收益),前后端同步收缩"
```

### Task 13: 前端回测合并为"回测实验室"+ 死页删除

**Files:**
- Modify: `frontend/apps/web/src/pages/LongTermBacktest.tsx`（加顶层 Tab）
- Delete: `frontend/apps/web/src/pages/{Backtest,Strategies,Portfolio}.tsx` 及 `.css`
- Delete: `frontend/packages/trading/strategy/`（整包，仅 Strategies 页使用）
- Modify: `App.tsx`、`Layout.tsx`

**Steps:**

- [ ] **Step 1: 删除三个死/mock 页**

```bash
cd frontend
git rm apps/web/src/pages/Backtest.tsx apps/web/src/pages/Backtest.css \
       apps/web/src/pages/Strategies.tsx apps/web/src/pages/Strategies.css \
       apps/web/src/pages/Portfolio.tsx apps/web/src/pages/Portfolio.css
grep -rn "pages/Backtest\|pages/Strategies\|pages/Portfolio\|@ytrader/trading-strategy" apps/web/src packages --include="*.ts*" | grep -v "packages/trading/strategy/"
```
Expected: 仅 App.tsx 的 import/路由与 Layout.tsx 菜单行（下一步处理）。确认 `packages/trading/strategy` 无其他消费者后：`git rm -r packages/trading/strategy`。

- [ ] **Step 2: LongTermBacktest 加顶层 Tab**

在 `LongTermBacktest.tsx`：顶部 import 增加 `import TTrading from './TTrading';`（确认 TTrading 的导出名，默认导出或命名导出按实际调整）。组件内加：

```tsx
const [topTab, setTopTab] = useState<'lt' | 'ttrading'>(() =>
  new URLSearchParams(window.location.search).get('tab') === 'ttrading' ? 'ttrading' : 'lt');
```

将现有返回 JSX 整体作为 `topTab === 'lt'` 分支，外包一层：

```tsx
<div className="lt-backtest-lab">
  <div className="lt-backtest-lab__tabs">
    <button
      className={`lab-tab${topTab === 'lt' ? ' lab-tab--active' : ''}`}
      onClick={() => setTopTab('lt')}>
      长期回测
    </button>
    <button
      className={`lab-tab${topTab === 'ttrading' ? ' lab-tab--active' : ''}`}
      onClick={() => setTopTab('ttrading')}>
      做T实验室
    </button>
  </div>
  {topTab === 'lt' ? (
    <>…原有 JSX 原样放这里…</>
  ) : (
    <TTrading />
  )}
</div>
```

在 `LongTermBacktest.css` 追加：

```css
.lt-backtest-lab__tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.lab-tab {
  padding: 6px 16px; border: 1px solid var(--border-color, #333); border-radius: 6px;
  background: transparent; color: var(--text-secondary, #aaa); cursor: pointer;
}
.lab-tab--active { color: var(--text-primary, #fff); border-color: var(--accent, #e6b800); }
```
（若项目令牌名不同，参照该文件已有的 CSS 变量命名调整。）

- [ ] **Step 3: App.tsx / Layout.tsx 收线**

App.tsx：删除 `/strategies`、`/portfolio`、`/backtest` 三条路由与 import；`/t-trading` 改为重定向：
```tsx
<Route path="/t-trading" element={<Navigate to="/lt-backtest?tab=ttrading" replace />} />
```
`/lt-backtest` 路由与 LongTermBacktest import 保留。Layout.tsx 交易组改为：
```tsx
{path: '/trading', label: '交易', icon: Icon.trading},
{path: '/lt-backtest', label: '回测实验室', icon: Icon.backtest},
{path: '/perm-portfolio', label: '永久组合', icon: Icon.portfolio},
```
（删除 做T实验室/策略/组合/回测/长期回测 五个旧项。）

- [ ] **Step 4: 构建门 + Commit**

```bash
cd apps/web && pnpm build && cd ../.. && \
git add -A frontend && git commit -m "refactor(slim/p3): 回测三入口合并为回测实验室(长期回测+做T双Tab);删Backtest/Strategies/Portfolio死mock页"
```

### Task 14: P3 合并 master

- [ ] **Step 1: 冒烟**：重点走 `/lt-backtest` 双 Tab 切换、`/t-trading` 重定向、Factors 页剩余 Tab、Analytics（原先引用 `/strategy/backtest_results`，确认 strategy_router 仍在、该端点未删）。
- [ ] **Step 2: 合并**：`git checkout master && git merge --no-ff slim/p3 -m "merge slim/p3: 模拟清理+回测实验室合并"`

---

## Phase P4：导航重组 + 依赖卸载

### Task 15: 导航定版 5 组 21 项（含财报雷达）

**Files:**
- Modify: `frontend/apps/web/src/components/Layout.tsx`

**Steps:**

- [ ] **Step 1: 开分支**

```bash
git checkout master && git checkout -b slim/p4
```

- [ ] **Step 2: 菜单组定版**

Layout.tsx 的菜单数组整体替换为（保留原变量名与类型定义，仅改内容；前序阶段已删项自然不存在）：

```tsx
// 总览
{path: '/dashboard', label: '总览', icon: Icon.dashboard},
{path: '/market', label: '行情', icon: Icon.market},
{path: '/indices', label: '指数', icon: Icon.globe},
{path: '/watchlist', label: '自选股', icon: Icon.star},
// 研究
{path: '/financial', label: '财务报表', icon: Icon.financial},
{path: '/earnings-radar', label: '财报雷达', icon: Icon.analytics},
{path: '/screener', label: '选股器', icon: Icon.strategies},
{path: '/factors', label: '因子', icon: Icon.factors},
{path: '/macro', label: '宏观政策', icon: Icon.analytics},
{path: '/national-team', label: '国家队', icon: Icon.analytics},
{path: '/reports', label: '报告', icon: Icon.reports},
// 交易
{path: '/trading', label: '交易', icon: Icon.trading},
{path: '/lt-backtest', label: '回测实验室', icon: Icon.backtest},
{path: '/perm-portfolio', label: '永久组合', icon: Icon.portfolio},
// 分析
{path: '/analytics', label: '分析', icon: Icon.analytics},
{path: '/board', label: '看板', icon: Icon.dashboard},
{path: '/risk', label: '风险', icon: Icon.risk},
{path: '/alerts', label: '预警', icon: Icon.alerts},
// AI / 系统
{path: '/ai-workspace/trader', label: 'AI交易助手', icon: Icon.intel},
{path: '/settings', label: '设置', icon: Icon.settings},
{path: '/system-logs', label: '系统日志', icon: Icon.terminal},
```

- [ ] **Step 3: 构建门 + Commit**

```bash
cd frontend/apps/web && pnpm build && cd ../.. && \
git add -A frontend && git commit -m "refactor(slim/p4): 侧边栏定版5组21项(含财报雷达)"
```

### Task 16: 后端依赖卸载

**Files:**
- Modify: `backend/pyproject.toml`、`backend/uv.lock`（uv sync 自动）、`docker/` 下引用文件（如有）、README 功能清单

**Steps:**

- [ ] **Step 1: 卸载前逐一验证无消费者**

```bash
cd backend
for dep in pymupdf elasticsearch langgraph langchain langchain-openai langchain-core langchain-anthropic mcp feedparser; do
  echo "== $dep =="; grep -rln "$dep" src/ main.py --include="*.py" | head -5
done
```
Expected: 全部无输出。任何有输出的依赖（如 `langchain` 被 `domain/llm` 引用），**从卸载列表移除并记录**。

- [ ] **Step 2: 编辑 pyproject.toml**

从 `[project] dependencies` 删除：`pymupdf`、`elasticsearch`、`langgraph`、`langchain`、`langchain-openai`、`langchain-core`、`langchain-anthropic`、`mcp`、`feedparser`（仅删 Step 1 验证通过的）。删除可选组 `[project.optional-dependencies]` 的 `nacos = [...]` 与 `minio = [...]` 两个整组（若文件/user 脚手架仍引用 nacos/minio，那些属于 P2/P3 应删而未删的残留，先处理）。

- [ ] **Step 3: 同步锁file + 接线门**

```bash
uv sync && uv run python -c "import main; print('ok')" && uv run pytest tests/api -q 2>&1 | tail -1
```
Expected: `ok`；失败数 ≤ 基线。

- [ ] **Step 4: docker/cicd 引用清理**

```bash
cd .. && grep -rn "elasticsearch\|minio\|langchain\|langgraph\|nacos" docker/ backend/cicd/ backend/Dockerfile* 2>/dev/null
```
有匹配则删除对应行/服务定义；无匹配跳过。

- [ ] **Step 5: README 功能清单更新**

在根 README（或 `backend/README.md`、`frontend/apps/web/README.md` 中列出功能/页面的那份）把功能清单更新为瘦身后形态（5 组 20 页、23 router），并注明"资讯采集/AI 写作/模拟回测已退役"。

- [ ] **Step 6: Commit**

```bash
git add -A backend docker && git commit -m "chore(slim/p4): 卸载pymupdf/elasticsearch/langchain全家桶/mcp/feedparser+可选组nacos/minio;README更新"
```

### Task 17: 终验 + 合并 + public 重建提示

**Steps:**

- [ ] **Step 1: 全库残留终验（spec 成功标准 4）+ boom 存活验证**

```bash
cd backend && grep -rn "intel/blog\|application/intel\|langgraph\|elasticsearch\|minio" src/ main.py --include="*.py"
cd ../frontend && grep -rn "pages/blog\|BlogDraft\|pages/Intel\|SubscriptionResults\|Celebrity\|pages/Backtest\|pages/Strategies\|pages/Portfolio" apps/web/src --include="*.ts*"
cd ../backend && uv run python -c "from src.domain.market.boom.service import build_default_service; print('boom ok')"
uv run pytest tests/domain/boom tests/api/test_boom_router -q 2>&1 | tail -1
```
Expected: 前两条 grep 无输出；`boom ok`；boom 测试全绿（财报雷达功能完好）。

- [ ] **Step 2: 启动终验（spec 成功标准 1/2）**

```bash
cd backend && timeout 20 uv run uvicorn main:app --port 8902 2>&1 | grep -i "error\|traceback\|Application startup complete"
```
Expected: 出现 `Application startup complete`，无 error。前端 `cd frontend/apps/web && pnpm build` 成功。

- [ ] **Step 3: 测试终验（spec 成功标准 3）**

```bash
cd backend && uv run pytest tests/api -q 2>&1 | tail -1
```
Expected: 失败数 ≤ `/tmp/pytest_api_baseline.txt` 记录值。

- [ ] **Step 4: 合并**

```bash
git checkout master && git merge --no-ff slim/p4 -m "merge slim/p4: 导航定版+依赖卸载"
```

- [ ] **Step 5: 提示用户**

public 孤儿分支重建不在本计划内（属既有开源流程）：提示用户"master 已完成瘦身，可用既有零密钥导出流程重建 public 分支，需人工剔除项应只剩 `conf/*.local.yaml` 类密钥文件"。

---

## Self-Review 记录

- **Spec 覆盖**：spec §4 Phase -1→Task 1；P0→Task 2/3；P1→Task 4/5/6；P2→Task 7/8/9/10；P3→Task 11/12/13/14；P4→Task 15/16/17；§3.3 例外（Reports/Trading/factors/financial docstring）→ Task 11 Step 3、Task 12；§8 成功标准 → Task 17 Steps 1-3。无缺口。
- **占位符扫描**：无 TBD/TODO；所有删除步骤给出确切路径与命令；两处"视 grep 结果决定"（test_file_handler、依赖消费者检查）为设计内的判定门，附明确判定规则。
- **一致性**：分支名统一 `slim/pN`；接线门/构建门/基线门命令全文一致；Task 13 的 Tab 状态变量 `topTab`、组件名 `TTrading`、query 参数 `tab=ttrading` 前后引用一致。
- **2026-09-08 修订（boom 保护）**：财报雷达落地后复核，Task 3/4/8 的 news 域、news_repository、news_backfill 脚本与测试、`intel/agents/base.py` 改为保留；Task 1 纳入 `backfill_history_gaps.py`；Task 15 菜单 20→21 项（+财报雷达）；Task 17 增加 boom 存活验证门（`build_default_service` 可导入 + boom 测试全绿）。
