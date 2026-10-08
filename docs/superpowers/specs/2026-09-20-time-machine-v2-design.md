# 时光机 v2（固定指数/大事件/股票信息/自动选股联动）设计文档

日期：2026-09-20
状态：已获用户确认，待实施
前置：v1 设计 `2026-09-14-time-machine-replay-design.md`（已合并 main `6007148`）

## 1. 背景与目标

v1 交付了盲盒训练/拟真撮合/揭晓复盘闭环。用户实测后提出四点增强：

1. **关键市场指数固定展示**——航行中看不到大盘
2. **当时外部大事件固定展示**——脱离时代背景做决策（2020 年 3 月看不到"疫情"）
3. **股票名称等信息补全**——池/持仓只显示代码，重开旅程名称丢失
4. **联动自动选股/自动建组合/回测**——选股器只能逐只加；新建的自动组合功能（feat/buy-checklist 分支）没被时光机引用

## 2. 关键决策（与用户逐项确认）

| 决策点 | 结论 |
|---|---|
| 大事件数据源 | **三层**：macro/events 12 条策划事件保底 + 新增新闻 as-of 端点 + akshare 历史新闻回填（尽接口历史深度，覆盖如实标注） |
| buy-checklist 分支 | **Phase 0 先合并 main**（独立验证门），再联动自动建组合 |
| 股票信息范围 | **中文名 + 申万一级行业**，入池取回并持久化到 state；行业标注"当前快照口径，轻微未来泄漏" |
| 指数数据流 | advance 端点一次带回 4 指数 bars（`symbol IN` 单查询），前端不做每步多请求 |

## 3. Phase 0：合并 feat/buy-checklist

跑该分支测试（course-portfolio 7 端点 + checklist）全绿后合并 main。预判冲突点：`main.py` lifespan import 块、`App.tsx` 路由、`Layout.tsx` 导航。合并是独立验证门，失败不牵连 v2 其他特性。合并后 main 具备：自动建组合（course_portfolio 两表 + builder 纯函数 + 7 端点）、买入体检（checklist）。

## 4. 指数带（顶栏固定展示）

- **后端**：`advance` 响应扩展 `indices: {symbol: [ReplayBar]}`，固定 4 指数：`sh000001 上证 / sz399001 深成 / sz399006 创业板 / sh000300 沪深300`（数据实测全覆盖 1990/1991/2010/2002 至今）。`index_ohlcv` 单查询 `symbol = ANY(...)`。kline 端点已支持任意指数，零改动。
- **前端**：store 加 `indexBars: Record<string, ReplayBar[]>`（openSession 并发拉 4 指数截断 K 线初始化；advance 增量合并去重）。TopBar 下固定**指数带**：名称+当日收盘+涨跌幅（红涨绿跌），全部按视角日截断——回看时大盘也回到那天。
- 基准指数（复盘对比用）与指数带数据同源，benchmarkBars 保留。

## 5. 时代背景条（大事件固定展示）

- **策划事件保底（零后端改动）**：前端拉 `GET /macro/events`（12 条 `{date,title,desc}`），按视角日裁剪展示"最近 60 天内已发生"的大事；事件当日高亮。永远有内容。
- **新闻 as-of 端点（新）**：`GET /replay/news?asof=&days=3&limit=20` → `intel_news` 查 `published_at ≤ asof 且 ≥ asof−N 天`，按 importance/heat_score 排序，返回 `{title, source, published_at, importance}`。红线：SQL 必须 `published_at ≤ asof`。覆盖密度如实标注（当前仅 2026 年密度可用，其余年份空结果属正常）。
- **历史新闻回填脚本（新）**：`backend/scripts/replay_news_backfill.py`。先 spike akshare 各新闻接口的历史深度（快讯类接口通常只有近期；`stock_news_em`/财联社电报/新浪全球快讯等逐个探测），能回填多远回填多远，写入 `intel_news`（source_type='backfill'），进度文件记录覆盖范围与来源映射。无新闻的日子 UI 只显示策划事件。
- UI：指数带下方/或驾驶舱左栏顶部一条**时代背景条**：策划事件卡片 + 当日近 3 天新闻标题列表（可折叠）。

## 6. 股票名称+行业补全

- **新端点**：`GET /replay/instrument/{symbol}?asof=` → `{symbol, name, industry}`（`stock_info` 取名 + `sw_industry_member` 取申万一级行业，一次请求）。
- **持久化**：state 增加 `names: Record<string,string>`、`industries: Record<string,string>`（v1 carry-forward R26 顺带解决）；openSession 恢复时直接用。
- **展示**：池列表（名称+行业小标签）、持仓表、下单台标题、复盘成交清单。行业标注轻微未来泄漏（sw_industry_member 为当前快照，同自选股导入先例）。
- **兼容**：旧旅程 state 无这两字段时容错显示代码，不迁移。
- `addSymbol`：kline 与 instrument 并发拉取。

## 7. 自动选股与组合/回测联动

- **批量入池**：选股器弹层加「top N 一键入池」（前端并发 addSymbol，弹层不关，完成提示）。
- **组合提案**：舱内新入口「AI 建组合」——以旅程当前日为 as_of 调合并后的 course-portfolio builder API，生成组合提案（标的+权重+理由）展示后勾选入池。API 形状在计划阶段对合并后代码确认。
- **回测联动**：舱内与复盘页加「丢给回测实验室」→ `/lt-backtest?symbols=池子&start=旅程起始&end=视角日`；LongTermBacktest 页面读 URL query 预填（现仅读 `?tab=`，小改造）。

## 8. 边界与测试

- 红线不变：指数/新闻/事件/行业全部 as-of 截断；news 端点测试含泄漏断言（构造 asof 之后的新闻断言不可见）。
- 旧 state 兼容容错；回填脚本支持干跑（`--dry-run` 只报可回填量不写库）。
- 测试：后端 advance.indices/news as-of/instrument 三端点 + 前端 store 多指数合并与视角截断、names 持久化往返、批量入池。
- YAGNI 不做：分钟级事件流、LLM 事件解读、指数可交易、新闻情感分析。

## 9. 任务分解预览（供计划阶段细化）

Phase 0 合并 buy-checklist → 指数带（后端+前端）→ 新闻端点+回填脚本 → 时代背景条 → instrument 端点+名称行业持久化展示 → 批量入池+组合提案+回测跳转 → 全链路验收。
