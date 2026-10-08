# 决策日志与复盘（价值投资闭环第 3 期）设计 spec

日期：2026-09-27
状态：依据 2026-09-27-thesis-sell-system-design.md 附录路线执行
前置：第 1-2 期持仓论点体系已落地（a122ca6…6007c1c）

## 1. 目标

补齐"决策留痕 + 定期复盘"：每条论点的关键动作（登记/决策变更/关闭/手记）
自动落日志；组合级复盘视图（关闭论点按原因统计盈亏 + 最近决策流水）；
超 30 天未复盘提醒。

非目标：不改第 1-2 期表结构与端点语义（仅在其 handler 流程内挂钩子）。

## 2. 数据模型（2 张新表，portfolio/thesis_models.py 追加）

### thesis_journal（决策日志）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| thesis_id | FK → investment_thesis, indexed | 级联 |
| kind | str | created / decision / close / note |
| decision | str? | decision/close 时的值（hold/reduce/sell/原因） |
| note | text? | 备注（含手动 note 类） |
| price | float? | 决策时现价（created/decision 取最新收盘，close 取 close_price） |
| created_at | datetime | |

### thesis_review_log（复盘记录）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| note | text? | 本次复盘备注 |
| created_at | datetime | 每次"标记已复盘"一行 |

## 3. 纯函数（thesis_monitor.py 追加）

`build_review_summary(closed_theses, journal_rows, last_review_at, now=None) -> dict`：

- `stale_review`：last_review_at 为空或距今 >30 天
- `closed_stats`：按 close_reason 分组 → `{reason, count, avg_pnl_pct, win_count}`
  （pnl = (close_price/buy_price−1)×100，两者齐才计入）
- `recent_decisions`：kind ∈ decision/close 的日志最近 20 条（含 symbol）

## 4. API（thesis_router 追加 3 端点 + 3 处 handler 挂钩）

| 端点 | 方法 | 说明 |
|---|---|---|
| /thesis/{id}/journal | GET | 单论点日志时间线 |
| /thesis/{id}/journal | POST | 手动手记 {note} |
| /thesis/review | GET | 复盘汇总（含 stale_review） |
| /thesis/review | POST | 标记已复盘 {note?} → 落 review_log |

挂钩（在既有 handler 内追加，不动签名）：create_thesis → journal(created, price=最新收盘)；
update_thesis 且 decision 变更 → journal(decision, price=最新收盘)；close_thesis → journal(close, price=close_price)。
路由顺序注意 /review 须在 /{thesis_id} 之前。

## 5. 前端（/thesis 页内增强，不加新页）

- Detail：新增"决策日志"时间线区（kind 徽章 + decision/note/price/时间）；
  "记一笔"输入框（POST note）。
- 主页：顶部复盘横幅（>30 天未复盘 → "标记已复盘"按钮）+ "复盘"折叠区
  （关闭论点按原因统计表 + 最近决策流水表）。

## 6. 测试

- repo：journal/review_log CRUD（sqlite）。
- 纯函数：分组统计含/缺价格、win 判定、stale 阈值、recent 过滤。
- handler：create/decision/close 三挂钩落日志（mock repo 断言调用）。
- 回归：第 1-2 期全部测试不回退。

## 7. 验收

1. 登记/改决策/关闭论点后，Detail 日志时间线出现对应条目且带当时价格。
2. 复盘区正确显示按关闭原因的盈亏统计与最近决策。
3. 无复盘记录时横幅提醒，标记后 30 天内不再提醒。
4. 后端相关测试 + 前端 build 通过。
