# 价值投资能力增强（P0–P2）— 实施完成

围绕「价值投资者决策链」补齐系统关键缺口，按「是否误导决策」分优先级。**10 项全部实现，204 测试通过，系统启动完整（233 路由）。**

## 最终验证

| 验证项 | 结果 |
|--------|------|
| 全局回归（所有新增测试） | **204 passed** |
| main.py 启动 + 路由注册 | **OK，233 路由** |
| 股息率端到端（真实股票） | 浦发 4.58%、茅台 3.84%（合理） |
| DCF handler 端到端 | 结构正确，数据缺失优雅降级 |

## 一、P0 止血：消除正在误导决策的虚假信号

| # | 问题 | 交付 |
|---|------|------|
| P0-1 | 个股股息率 `dv_ttm` 全 NULL，红利选股空跑 | `stock_dividend` 分红明细表 + `fetch_dividend_detail` + TTM 股息率纯函数（`dividend_yield`），同步回写 `dv_ttm`。集成验证修复 2 个 bug（`close_` 属性、每10股口径 ÷10） |
| P0-2 | FF5 因子 `random.gauss` 合成，alpha/beta 不可信 | `factor_returns.simulated` 列 + API warning + 合成数据不再落库 alpha_signals |
| P0-3 | `positions` 表无人写，风险/归因仪表盘空跑假数据 | `position_bridge.py`（domain 纯桥接），risk/portfolio router 接 perm-portfolio 真实持仓（`portfolio_id`），降级附 warning |
| P0-4 | `fcf` 实为筹资流，被误当自由现金流 | 新增 `capex` + `free_cash_flow`（= ocf−|capex|），映射/单季换算/建表全贯通 |

## 二、P1 核心能力

| # | 能力 | 交付 |
|---|------|------|
| P1-5 | 衍生指标层 + 真实神奇公式 | `derived_metrics`（ROIC/EBIT/EV/EBIT 收益率/FCF 收益率/ROA）；选股器 + 回测策略均优先真实 ROIC+EBIT/EV，缺数据降级 ROE+1/PE |
| P1-6 | DCF 绝对估值 + 安全边际 | `dcf` 两阶段模型；`GET /financial/dcf/{symbol}`（假设可调） |
| P1-7 | 个股基本面深度分析 Agent | `fundamental/agents/`（数据注入 + Jinja2 + Pydantic 结构化输出）；`GET /financial/fundamental-analysis/{symbol}`。**铁律禁止 LLM 臆测**，数据缺失标「无数据」 |

## 三、P2 组合与风险闭环

| # | 能力 | 交付 |
|---|------|------|
| P2-8/9 | 下行风险指标 + 因子驱动情景压力测试 | `risk_metrics`（Sortino/Calmar/相关性矩阵/Monte Carlo VaR）+ 10 场景（4 静态 + 2 因子驱动 + 4 历史危机重放 2008/2015/2018/2022，跌幅 web 核实） |
| P2-10 | 安全边际仓位 sizing + 执行闭环 | `position_sizing`（分档/max_weight/波动率缩放/分批建仓）；executor 成交回写 `positions`（加权均价/realized_pnl），margin 用估值分位近似，降级兼容写死 20% |

## 四、启用前必须执行：数据回填

新字段（`dv_ttm` / `free_cash_flow` / `capex` / 分红明细）历史数据需回填后功能才产出真实结果：

```bash
cd backend
python -m src.domain.market.sync.jobs.fundamentals --only all      # 全量（估值+财务+分红+股息率）
python -m src.domain.market.sync.jobs.fundamentals --only dividend  # 只补分红明细+股息率
```

- 启动时 `stock_dividend` / `stock_valuation` 等表由 `main.py` 自动 `create_all`；
- `stock_financial_detail` 的 `capex`/`free_cash_flow` 列由 `ensure_stock_financial_detail_columns()` 自动加列。

## 五、新增 / 变更 API

| 端点 | 能力 |
|------|------|
| `GET /financial/dcf/{symbol}` | DCF 内在价值 + 安全边际（P1-6） |
| `GET /financial/fundamental-analysis/{symbol}` | 基本面深度报告（P1-7） |
| `GET /screener/screen?mode=magic_formula` | 真实 ROIC + EBIT/EV（P1-5） |
| `GET /risk/portfolio` | + sortino/calmar/相关性/Monte Carlo（P2-8） |
| `GET /risk/scenarios` | + 因子驱动 + 历史危机场景（P2-9） |
| `GET /risk/*`、`/portfolio/attribution` | + `portfolio_id` 接真实持仓（P0-3） |

## 六、新增测试（204 个，纯函数 sqlite/mock，不依赖真实 LLM/网络）

- `tests/domain/test_dividend_yield.py`、`test_derived_metrics.py`、`test_dcf.py`、`test_free_cash_flow.py`
- `tests/infra/database/market/test_dividend.py`
- `tests/domain/market/portfolio/test_position_bridge.py`（P0-3，13）
- `tests/domain/market/portfolio/test_risk_metrics.py`（P2-8/9，40）
- `tests/api/test_factors_router_simulated.py`（P0-2，8）
- `tests/test_fundamental_analyst.py`（P1-7，14）
- `tests/domain/market/strategy/test_position_sizing.py` + `tests/infra/test_strategy_executor_positions.py`（P2-10，41）

> 注：`tests/domain/market/strategy/test_memory.py` 等既有失败为 OpenAI api_key 环境问题，与本次改动无关。

## 七、新增模块（domain 纯函数，易测易复用）

- `fundamental/dividend_yield.py` — TTM 股息率
- `fundamental/derived_metrics.py` — ROIC/EBIT/EV/FCF Yield/ROA
- `fundamental/dcf.py` — DCF + 安全边际
- `fundamental/agents/` — 基本面分析 Agent（数据注入 + 结构化输出）
- `portfolio/position_bridge.py` — 持仓桥接
- `portfolio/risk_metrics.py` — 下行风险 + 情景测试
- `strategy/position_sizing.py` — 安全边际仓位 sizing
- `infra/database/market/dividend.py` — 分红明细表

## 八、前端页面接入

| 页面 | 接入内容 |
|------|----------|
| Financial | 新增「DCF估值」Tab（`DcfPanel`：调增长率/折现率/永续/年数假设 → 内在价值 + 安全边际）+「AI基本面」Tab（`FundamentalReportPanel`：综合评分/护城河/风险点等结构化报告，基于真实财报） |
| Screener | magic_formula 结果表新增 **ROIC%** / **EBIT收益率%** 列（真实 Greenblatt 指标，替换 ROE/1PE 近似） |
| Risk | 新增 **Sortino/Calmar/Monte Carlo VaR** 卡片 + 持仓**相关性矩阵**热力图（`CorrelationMatrix`，负相关蓝/正相关红）+ 压力测试**场景升级**（静态/因子驱动/历史危机分组 + 各仓位贡献展开） |

**新增前端文件**：`hooks/useDcf.ts`、`hooks/useFundamentalAnalysis.ts`、`components/DcfPanel.tsx(+.css)`、`components/FundamentalReportPanel.tsx(+.css)`、`components/CorrelationMatrix.tsx(+.css)`。

**验证**：`tsc --noEmit` 全量类型检查，上述所有前端改动文件**零类型错误**（项目预存的 tsconfig `rootDir`/`jest` 配置报错与本次无关）。`pnpm --filter web dev` 读源码可直接使用全部新功能。

> 注：若 `pnpm --filter web build` 产物未更新，检查 `apps/web/dist` 是否被历史 root 进程锁定（`ls -la dist/static/js` 若 owner=root 需 `sudo rm -rf dist` 后重建）；dev server 不受影响。
