# BI 自定义对比看板(自由叠加画布)设计

日期:2026-09-02
状态:待评审
来源:用户需求——"独立页面,类似 BI 的自定义看板,叠加不同的卡片做对比分析;
卡片可无限多;卡片之间可设置透明度、互相叠加"。

## 目标

- 新独立页面 `/board`(导航「看板」):自由画布,卡片可拖拽、缩放、重叠、
  调透明度,支持任意数量卡片,做跨标的/跨口径对比分析。
- 交互模型(用户已确认):**混合**——默认网格吸附对齐,按住 Alt 拖动脱离
  网格自由定位即可叠加;点击置顶;透明度 0.15–1.0。
- 四种卡片(MVP,用户已确认全要):K 线卡(含成交量)、财务趋势卡、
  指标数值卡、指数估值 PE 卡。
- 时间范围(用户已确认):**仅全局**,顶栏统一时间轴,所有卡片跟随,
  无单卡覆盖。
- 持久化(用户已确认):**后端多看板** CRUD,布局 JSON 整存整取;
  自动保存(防抖 PUT)。
- 基金范围(用户已确认):场内 ETF 即可(与股票同端点);场外基金不做。

## 非目标(YAGNI)

- 不做场外公募基金净值(无数据源,二期若有需求再评估)。
- 不做分钟线卡片(日线 MVP;`/market/kline` 虽支持分钟,卡片先固定 1d)。
- 不做卡片配置编辑(改参数=删除重加;卡片头仅展示标题)。
- 不做看板协作/分享/导出图片、卡片联动十字光标。
- 不做单卡时间范围覆盖(用户明确选择仅全局)。
- 不做用户/鉴权(全站单用户无鉴权惯例,同 watchlist)。

## 数据事实(已核实 2026-09-02)

- K 线:`GET /api/v1/market/kline/{symbol}?interval&start&end&limit`
  (market_router.py),指数/股票/ETF 统一端点,服务端按 symbol 分表
  (`_resolve_kline_table`);bars={trade_date,open,close,high,low,volume,amount}。
- 标的搜索:`GET /market/search?q=&market=A&limit=20`(market_router.py:448),
  查 stock_info,代码前缀>代码>名称排序;前端参考 MarketPage/api.ts。
- 财务:`GET /financial/detail/{symbol}?statement_type=income|balance|
  cashflow|abstract&period=quarter&start_date&end_date&limit`(真实数据,
  financial_detail_handler.py);series 最新期在前,含 revenue/net_profit/
  gross_margin/ocf 等。**不用** `/financial/statement`(模拟数据)与
  `/financial/ratios`(含硬编码模拟字段)。
- 指数 PE:`GET /financial/index-pe/{code}?years=`(2026-08-31 设计已落地),
  前端 `useIndexPe` hook + `IndexPeChart` 可参考;9 宽基清单 `MCG_INDICES`
  (Indices.tsx:53)。
- 后端 CRUD 模板:watchlist——thin router(body: dict 无 Pydantic)+ 纯函数
  handler + repository 工厂/双检锁单例 + SQLModel 表;JSON 文档存 JSONB 列
  有先例(strategy/models.py PortfolioBacktestResult.params)。
- 建表:无 Alembic,`DBConnection(auto_create_tables=True)` 启动
  create_all;新模型必须在 main.py lifespan import 块注册(main.py:160-163
  watchlist 先例)。
- 前端:React 18 + rsbuild(dev 12000 代理 /api→12100);react-router v7
  (App.tsx Routes + Layout.tsx navGroups 两处注册);无 antd/tailwind,
  自建 ui 组件 + CSS 变量暗色主题;图表三套:lightweight-charts 5.1(K线)/
  recharts 2.13(财务);图表配色必须用 `lib/chartTheme.ts` 常量。
- **无任何拖拽库**(package.json 无 react-grid-layout/dnd-kit/rnd);
  packages 的 `KlineChart.tsx` 自带 interval/timeRange 切换 UI 与 WebSocket,
  与"全局时间轴、卡片无自带时间控件"冲突,不复用,Board 内轻封装。
- localStorage 工具:`@ytrader/common-utils` storage,key 惯例 `ytrader_` 前缀。
- 前端无测试基建(无 jest/vitest);后端 pytest 有 TestClient+本地 PG 先例
  (tests/api/test_watchlist_router.py)。

## 方案取舍

| 方案 | 结论 |
|---|---|
| A. 自研绝对定位画布 + pointer events + 网格吸附(本设计) | **采纳**:叠加/透明度/z 序是通用网格库不覆盖的语义;吸附=坐标取整、Alt=不取整,实现直白;无新依赖 |
| B. react-grid-layout | 否:库核心假设是卡片不重叠(自动挤压),叠加需绕开库 hack,语义拧巴、升级易碎 |
| C. react-rnd + 自写吸附 | 否:省了拖拽引擎但网格单位换算、Alt 动态切换仍要自写,且引入维护一般的新依赖 |

## 布局数据模型

看板 layout JSON(整体存 JSONB,version 预留升级):

```json
{
  "version": 1,
  "timeRange": { "preset": "1y", "start": null, "end": null },
  "maxZ": 7,
  "cards": [
    { "id": "uuid", "type": "kline", "title": "贵州茅台",
      "symbol": "sh600519", "config": {},
      "x": 0, "y": 0, "w": 6, "h": 14, "z": 3, "opacity": 1 }
  ]
}
```

- 网格:12 列,行高 32px;`x/y/w/h` 为网格单位,**允许小数**(Alt 自由
  定位的产物;吸附=拖/缩结束时四舍五入取整)。
- `type ∈ {kline, financial_trend, metric, index_pe}`;`config` 为类型
  特定参数(见卡片设计)。
- `z` 全局递增计数器 `maxZ`;点击卡片 → `z = ++maxZ`。
- `opacity ∈ [0.15, 1.0]`,作用于卡片容器整体。
- `timeRange.preset ∈ {3m, 6m, 1y, 3y, 5y, all, custom}`;custom 时
  start/end 必填(YYYY-MM-DD)。

## 后端设计

### 表 `analysis_board`(src/infra/database/board/models.py)

`id PK autoincrement / name str unique / layout dict(JSONB) /
sort_index int / created_at / updated_at`(字段与建法仿
watchlist/models.py 的 watchlist_group)。

### repository(board/repository.py)

`AnalysisBoardRepository`:list_boards()(轻量,不取 layout)、get(id)、
create(name)(sort_index=MAX+1,重名抛 ValueError)、update(id, name?,
layout?)(layout 整体替换,updated_at 刷新)、delete(id)。工厂
`create_analysis_board_repository()` + 模块级单例 + 双检锁(仿
watchlist/repository.py 底部范本)。

### handler + router

- `src/api/handler/board_handler.py`:纯函数,延迟 import repository 工厂,
  `responses.success/fail` 统一返回。
- `src/api/router/board_router.py`:`APIRouter(prefix="/board",
  tags=["board"])`,body 用 dict:
  - `GET  /board/boards` → 列表 `[{id, name, sort_index, updated_at}]`
  - `POST /board/boards` `{name}` → 新建空看板(layout 为空板初值);
    重名 → fail
  - `GET  /board/boards/{id}` → 含 layout
  - `PUT  /board/boards/{id}` `{name?, layout?}` → 全量保存
  - `DELETE /board/boards/{id}`
- main.py:lifespan import 块加 models 注册(建表)+ `include_router(
  board_router, prefix="/api/v1")`。

空板初值:`{"version":1, "timeRange":{"preset":"1y","start":null,
"end":null}, "maxZ":0, "cards":[]}`。

## 前端设计

### 文件结构(pages/Board/,遵循页面目录+独立 css 惯例)

```
pages/Board/
  index.tsx            # 页面壳:顶栏 + 画布,路由注册 /board
  BoardCanvas.tsx      # 画布:网格底纹、卡片渲染、拖拽/缩放引擎
  BoardCardShell.tsx   # 卡片框:头部(标题/⋯菜单)+ 内容插槽
  AddCardModal.tsx     # 添加卡片弹窗:类型选择 + 配置表单
  cards/
    KlineCard.tsx        # lightweight-charts 蜡烛图+成交量副图
    FinancialTrendCard.tsx # recharts 多指标线
    MetricCard.tsx       # 大字数值 + 同比
    IndexPeCard.tsx      # 复用 useIndexPe 数据,PE 线+均值/±σ
  boardTypes.ts        # BoardLayout/BoardCardData 等类型 + 默认值
  useBoards.ts         # zustand store + CRUD api + 自动保存
  Board.css
```

App.tsx 加 `<Route path="/board" element={<Board />} />`(lazy+Suspense,
重页面惯例);Layout.tsx navGroups 加「看板」。

### 顶栏

`[看板切换▾(列表+新建)] [重命名] [删除] │ 时间范围chips(近3月/6月/1年/
3年/5年/全部/自定义起止) │ [+添加卡片] [保存状态●]`

保存状态:已保存(灰)/保存中…/保存失败·点击重试(红)。

### 拖拽/缩放引擎(BoardCanvas,自研)

- 卡片容器 `position:absolute`,`left = x/12*100%`,`top = y*32px`,
  `width = w/12*100%`,`height = h*32px`。
- 拖动:卡片头 pointerdown → setPointerCapture → pointermove 位移换算
  网格单位 → 默认实时取整吸附(视觉上贴格),Alt 按下时保留小数自由移动
  → pointerup 写回 store。缩放:右下角手柄,同逻辑。最小尺寸 2×3。
- 边界:水平方向夹取 `x ∈ [0, 12−w]`(不出画布左右);纵向自由,卡片
  超出当前高度时画布自动增高(内容高度 = max(y+h)×32px + 底 padding)。
- z 序:pointerdown 置顶(z=++maxZ)。
- 新卡片落位:从 (0,0) 起按行扫描第一个不被整格占用的网格位(重叠摆放
  需 Alt 主动为之,自动落位永远找空位)。

### 卡片头「⋯」菜单

透明度滑杆(0.15–1.0)、复制卡片(同配置偏移 +1/+1 落位)、置顶/置底、
删除。标题=标的名称(添加时由搜索接口带回)。

### 四种卡片

| 卡片 | AddCardModal 配置 | 默认尺寸 | 数据与渲染 |
|---|---|---|---|
| kline | 标的搜索(指数/股票/ETF) | 6×14 | `GET /market/kline/{symbol}?interval=1d&start&end`;lightweight-charts 蜡烛 + 成交量直方副图,MA5/10/20/60;背景透明 |
| financial_trend | 标的 + 指标多选 | 6×14 | 指标池:营业收入/归母净利润/毛利率/净利率/经营现金流(均为 detail series 实有字段,无 roe——已核实 handler 固定列清单),默认营收+归母净利润;`GET /financial/detail/{symbol}?period=quarter&start_date&end_date`;recharts 多 Line,CHART_COLORS 逐线取色;报告期落在全局范围内过滤 |
| metric | 标的 + 单指标 | 2×3 | 同 detail 接口取范围内最新期,同比=与去年同季(单季口径)比较,大字数值 + 同比箭头(指标池同上) |
| index_pe | 9 宽基下拉(默认沪深300) | 6×14 | 复用 `useIndexPe`;PE 线+均值/±σ 参考线(参考 IndexPeChart 画法);取数按全局范围换算 years(向上取整,端点仅收整年),再客户端按 start 裁剪到精确范围(PE 为月度点,短档位也能对齐) |

标的话术搜索:300ms 防抖调 `/market/search`,下拉 symbol+名称;
无结果提示「无匹配标的」。

### 状态与保存(useBoards.ts)

- zustand store(不本地持久化,后端为唯一数据源):`{boards, activeId,
  layout, saveState}`,actions:loadBoards/selectBoard/createBoard/
  renameBoard/deleteBoard/addCard/removeCard/updateCard(位置/透明度/z/
  时间范围等)。
- 活跃看板 id 存 localStorage `ytrader_board_active`(仅便捷恢复)。
- 自动保存:任何 layout 变更后 800ms 防抖 `PUT /board/boards/{id}`;
  保存中置状态;失败置「失败·点击重试」不阻塞操作;切换/卸载前 flush。
- 时间范围换算:preset=1y → start=今天−1 年(锚定请求日);all →
  不传 start;custom → 表单起止。

### 错误处理

- 卡片内三态视图(StateView 惯例):loading/error(重试)/empty(如
  停牌/无财务数据标的),不影响其他卡片。
- 看板级:加载失败顶栏提示+重试;重名新建 → 后端 fail,前端提示;
  删除看板需确认弹窗(允许删除最后一个,删除后空态引导新建)。
- 布局容错:GET 回来的 layout 缺字段/旧 version → 按 version 兜底
  填默认值,不白屏。

## 测试(TDD)

- 后端 `tests/api/test_board_router.py`(仿 test_watchlist_router.py:
  TestClient + 本地 PG + 每例清理):CRUD 全路径、重名 400、layout 全量
  替换、列表不含 layout 字段。
- 前端无测试基建:类型层用 boardTypes.ts 收敛(card union type),
  逻辑验证靠浏览器走查(见验证)。

## 验证

- `pytest tests/api/test_board_router.py` 全绿(跑子集,全量回归有既有
  失败,见项目记忆)。
- `pnpm -F web build` EXIT=0。
- dev-start.sh 起服务,浏览器走查清单:新建看板 → 加 4 类卡片各一 →
  拖拽吸附/越界约束 → Alt 拖动叠加两张 K 线卡 + 调 60% 透明度透视对比 →
  切换时间范围全部卡片跟随 → 复制/删除/置顶置底 → 新建第二个看板切换 →
  刷新页面布局恢复。

## 预估

后端 models/repository/handler/router ~200 行 + 测试 ~150 行;前端
画布引擎+卡片壳 ~400 行,四卡片 ~450 行,store+类型+弹窗+页面 ~450 行。
约 2 个工作日。
