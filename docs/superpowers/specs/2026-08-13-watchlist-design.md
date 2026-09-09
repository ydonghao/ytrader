# 自选股（Watchlist）设计文档

- **日期**：2026-08-13
- **分支**：`feat/dividend-value-screener`（承接，新功能不冲突）
- **状态**：已评审，待出实施计划

## 1. 目标与范围

做一个带**分组**的自选股页面：用户把股票/ETF/指数/港股归到若干分组，用**标签页切换分组**查看每只股票的**行情 + 估值**，每个分组给出一个一眼可见的**概览**（平均涨跌幅、涨跌平家数、总市值合计）。

支持：分组的新建/重命名/删除/排序；组内股票的添加/删除/备注/拖拽排序/跨组移动；行情 30s 轮询刷新。

### 关键决策（已与用户确认）

| 决策点 | 选择 |
|---|---|
| 视图形态 | 标签页（Tabs）切换分组 |
| 个股数据列 | 行情（现价/涨跌额/涨跌幅）+ 估值（PE/PB/股息率/总市值） |
| 数据时效 | 快照 + 30s 轮询 |
| 标的范围 | A 股 + ETF + 指数 + 港股 |
| 备注与排序 | 每股可写备注；组内拖拽排序 |
| 架构方案 | 方案 A：独立 watchlist 模块（只管成员关系）+ 通用批量报价接口 |

### 站立假设

- **单用户 / 全局**：这是个人交易工具，自选股表不带 `user_id`。未来要多用户隔离时加一列 `owner` 即可。
- **港股数据可能不全**：`stock_ohlcv` 对港股覆盖未必完整；报价查询对缺失数据返回 `null`，前端显示「—」，不报错。
- **前端无测试基建**：本次不引入前端测试框架，前端验证靠手动冒烟清单。

## 2. 架构总览（方案 A）

```
watchlist 模块（只管"成员关系"，纯持久化）
  WatchlistGroup ──< WatchlistItem >── symbol（sh600000 等）
        ↑ 薄 CRUD，不碰行情

market 模块新增通用批量报价端点（可复用）
  POST /market/quotes  →  行情 + 估值（读 stock_ohlcv + stock_valuation）

前端 Watchlist 页：拿成员 → 批量报价 → 渲染；30s 只重打报价
```

职责切分：watchlist 表不存任何行情快照，行情/估值永远现算。批量报价端点独立于 watchlist，别的页面（如 Screener 下钻）将来可复用，填补项目目前缺批量报价端点的空白。

## 3. 后端设计

### 3.1 数据模型（`src/infra/database/watchlist/models.py`，SQLModel）

镜像 `perm_portfolio` 的 group + item 结构与主键/时间戳约定。

**`WatchlistGroup`**（分组）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | 自增 |
| `name` | str | 分组名，全局唯一（`UniqueConstraint(name)`） |
| `sort_index` | int | 分组排列顺序，默认按创建顺序递增 |
| `created_at` / `updated_at` | datetime | 时间戳 |

**`WatchlistItem`**（组内股票）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | 自增 |
| `group_id` | int FK→`WatchlistGroup.id` | `ON DELETE CASCADE`，删组连删成员 |
| `symbol` | str | `sh600000` / `sz159934` / `sh000300` / `02800` |
| `note` | str? | 备注，如「等回踩 60 日线」 |
| `sort_index` | int | 组内拖拽顺序，加入时取当前组末尾 +1 |
| `created_at` / `updated_at` | datetime | 时间戳 |

约束：`UniqueConstraint(group_id, symbol)` —— 同组不能重复；跨组可重复同一 symbol。

### 3.2 分层（沿用项目惯例）

- `models.py` —— 上面两张表。
- `repository.py` —— `WatchlistRepository` 类 + 模块级单例 `DBConnection` + `create_watchlist_repository()` 工厂（拷贝 portfolio 的骨架）。每个方法 `with self._db.session_scope() as s:`。
- `watchlist_handler.py`（`src/api/handler/`）—— 参数校验 + `responses.success/fail`，函数体内惰性 import + 工厂创建 repo（同 perm_portfolio_handler）。
- `watchlist_router.py`（`src/api/router/`）—— `router = APIRouter(prefix="/watchlist", tags=["watchlist"])`，薄包装，body 统一 `dict`，path/query 为基本类型。

### 3.3 wire-up（`backend/main.py`）

1. `create_app()` 里 `app.include_router(watchlist_router, prefix="/api/v1")`。
2. `lifespan` 里导入 watchlist models（与 portfolio/agent 模型导入并列），让 `SQLModel.metadata.create_all` 建表。

### 3.4 API 端点

**watchlist router（`/api/v1/watchlist`）—— 只管成员关系**

| 方法 | 路径 | 入参 | 出参 data |
|---|---|---|---|
| GET | `/watchlist/groups` | — | `[{id, name, sort_index, item_count}]`（按 sort_index 排） |
| POST | `/watchlist/groups` | `{name}` | `{id, name, sort_index}` |
| PUT | `/watchlist/groups/{id}` | `{name}` | `{id, name}` |
| DELETE | `/watchlist/groups/{id}` | — | `{id}`（级联删成员） |
| PUT | `/watchlist/groups/order` | `{ids:[...]}` | `{ids}` |
| GET | `/watchlist/groups/{id}/items` | — | `[{id, symbol, name, note, sort_index}]`（join `stock_info` 带 name，按 sort_index 排） |
| POST | `/watchlist/groups/{id}/items` | `{symbol, note?}` | `{id, symbol, name, note, sort_index}`（校验 symbol 存在于 stock_info，插到末尾） |
| DELETE | `/watchlist/items/{item_id}` | — | `{id}` |
| PUT | `/watchlist/items/{item_id}` | `{note}` | `{id, note}` |
| PUT | `/watchlist/groups/{id}/items/order` | `{ids:[...]}` | `{ids}` |
| POST | `/watchlist/items/move` | `{item_id, to_group_id, sort_index?}` | `{id, group_id, sort_index}` |

校验规则：`name` 非空且不与现有分组重名（重名返回 `fail`）；`symbol` 加成员时必须在 `stock_info` 中存在，否则 `fail`；`(group_id, symbol)` 唯一冲突返回友好提示「已在组内」。

**通用批量报价（`market_router`，`/api/v1/market`）—— 可复用**

| 方法 | 路径 | 入参 | 出参 data |
|---|---|---|---|
| POST | `/market/quotes` | `{symbols:[...]}` | `[{symbol, name, price, change, change_pct, pe, pe_ttm, pb, dv_ratio, dv_ttm, total_mv}]` |

实现：复用 `market_router._latest_sql`（`stock_ohlcv` 用窗口函数取每个 symbol 最新收盘 + 前日收盘算涨跌额/幅）+ `LEFT JOIN stock_valuation`（取 pe/pb/dv_ratio/total_mv 等）。`WHERE symbol = ANY(:syms)` 过滤。缺失字段返回 `null`；查不到的 symbol 从结果略过（前端用成员列表做主键 join，故略过无妨）。单次查询，避免 N+1。

## 4. 前端设计

### 4.1 文件与接入

- 新增 `frontend/apps/web/src/pages/Watchlist.tsx` + 同目录 `Watchlist.css`，跟随 Macro 的 **Pattern B**（`const API_BASE = getApiBase()` + raw `fetch` + `{code,msg,data}`、`code===0` 为成功 + 同目录 CSS + `styles/global.css` 主题 token）。
- `App.tsx`：`<Route path="/watchlist" element={<Watchlist />} />`。
- `components/Layout.tsx`：在 `Overview` 分组加 `{path:'/watchlist', label:'自选股', icon: Icons.<star/bookmark>}`（icons.tsx 取或补一个图标）。

### 4.2 页面布局

```
┌─────────────────────────────────────────────────────────────┐
│ [高股息] [科技ETF] [港股通] [指数]  + 新建分组   ✎编辑(改名/删/排)│  Tabs + 管理
├─────────────────────────────────────────────────────────────┤
│ 分组概览:  平均 +1.23%   涨 8 / 跌 3 / 平 1   总市值 12.4万亿      │  客户端算
├─────────────────────────────────────────────────────────────┤
│ [搜索添加股票 ▼ StockSelect]  备注[______]  [加入]              │  复用 StockSelect
├────┬──────────┬──────┬───────┬───────┬────┬────┬──────┬────┬──┤
│ ⠿│贵州茅台 sh600519│1689 │+12.0 │+0.72% │ 25 │ 9 │ 1.8% │…│⋯││
│ ⠿│沪深300  sh000300│  …  │  —   │  —    │ … │   │      │  │  │  缺数据→「—」
└────┴──────────┴──────┴───────┴───────┴────┴────┴──────┴────┴──┘
   ⠿ = 拖拽手柄(组内排序)          ⋯ = 删除 / 移到其它分组 / 改备注
```

- **分组 Tabs**：`@ytrader/common-components` 的 `Tabs`；右侧 `+` 新建分组（`Modal` + `Input`）；「编辑」进入管理态可改名/删/拖序。
- **分组概览条**：纯前端从当前组报价算 —— 平均涨跌幅、涨/跌/平家数、总市值合计。给「分组的情况」一个一眼结论。
- **添加股票**：复用 `components/MarketPage/StockSelect.tsx`（已带防抖服务端模糊搜索，调 `/market/search`）+ 备注 `Input`。
- **股票表**：`Table` + `PnlBadge` + `formatPrice/formatPercent`（镜像 `packages/trading/market-data/src/components/TickerTable.tsx` 写法）。列：拖柄 / 名称·代码 / 现价 / 涨跌额 / 涨跌幅 / PE / PB / 股息率 / 总市值 / 备注 / 操作。
- **拖拽排序**：原生 HTML5 drag-and-drop（**不引新依赖**），落位调 `PUT /groups/{id}/items/order`。跨组移动走操作菜单「移到…」→ `/items/move`。

### 4.3 数据流与刷新

1. **挂载** → `GET /watchlist/groups` → 渲染 Tabs，默认选中第一个分组。
2. **选中组** → `GET /groups/{id}/items`（成员）→ `POST /market/quotes`（用成员 symbols）→ 合并渲染表格 + 概览条。
3. **30s 轮询**：只对**当前组**重打 `/market/quotes`；`document.hidden` 时暂停；切组/卸载清 timer。
4. **写操作**：加/删/改名/排序/移动 → 调对应端点 → 成员变动则重取成员 + 报价；仅排序/备注则局部更新。

## 5. 边界与错误处理

- **没有任何分组**：引导空状态「新建第一个分组」。
- **组内无股票**：空状态提示「搜索添加股票」。
- **symbol 无行情/估值**（如港股缺数据）：对应格显示 `—`，不报错、不影响其它行。
- **删分组**：二次确认（级联删成员）。
- **同组重复加**：后端 unique 约束返回 fail，前端提示「已在组内」。
- **请求失败**：沿用 Macro 的错误提示 + 保留上次数据；轮询失败静默重试。
- **轮询清理**：切组、卸载、页面隐藏时正确清/停 timer，避免泄漏与无效请求。

## 6. 测试

- **后端（pytest，sqlite）**：
  - repository 层：分组 CRUD、成员 CRUD、级联删除、`(group_id,symbol)` 唯一约束、组内排序、跨组移动。
  - handler 层：参数校验（name 非空/不重名、symbol 存在性）。
  - `/market/quotes`：已知 symbol + 一个不存在的，校验缺失字段为 `null` 且不抛错、不存在的 symbol 被略过。
- **前端**：手动冒烟清单（建/删/改名分组、加/删/拖拽/跨组移动股票、轮询刷新、空状态、港股缺数据显示、错误提示）。前端测试框架不在本次范围。

## 7. 不做（YAGNI）

- 实时 WebSocket 推送（快照 + 轮询已够；估值本就是日频）。
- 价格提醒、买卖点信号（可后续接现有 `alert` 模块）。
- 多用户隔离、权限。
- 分组导入/导出、与外部自选股同步。
- 前端自动化测试基建。

## 8. 关键参考文件（实施时先读）

- 后端：`backend/main.py`（lifespan 模型导入 + 路由注册）、`backend/src/infra/database/portfolio/{models.py,repository.py}`（group+item 模板 + repo 工厂）、`backend/src/api/handler/perm_portfolio_handler.py` + `src/api/router/perm_portfolio_router.py`（handler/router 模板）、`backend/src/pkg/responses/__init__.py`（响应封装）、`backend/src/api/router/market_router.py`（`_latest_sql`/`_pack_row` 行情构建块、`search_symbols`）。
- 前端：`frontend/apps/web/src/pages/Macro.tsx`（fetch+CSS 模板）、`components/MarketPage/StockSelect.tsx` + `api.ts`（股票搜索）、`packages/trading/market-data/src/components/TickerTable.tsx`（行情表组合）、`packages/common/components/src/{Modal,Tabs,Table}/`（共享 UI）、`styles/global.css`（主题 token）。
