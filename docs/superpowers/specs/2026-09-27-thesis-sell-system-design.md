# 持仓论点体系（卖出体检 + 财报联动重估）设计 spec

日期：2026-09-27
状态：已确认（用户批准三项关键决策与整体设计）
范围：价值投资闭环缺口 1（卖出体系）+ 2（持仓×财报联动重估）；3–7 期为附录路线图

## 1. 背景与目标

平台已有完整的"研究→估值→买入"链路（财务报表/财报雷达/行业分析/五法估值/买入体检/自动建组合），但闭环断在买入之后：没有卖出体检、没有持仓的假设跟踪、财报发布后没有针对持仓的自动重估。本设计补齐后半程：

- **卖出体系**：每条持仓 = 一条投资论点 + 一组可证伪的假设条件（论点破即卖）+ 目标卖出估值带 + 四区卖出体检报告。
- **财报联动重估**：持仓股发布新财报（正式/快报/预告）时自动重跑质量评分、五法估值、条件评估，产出对比报告与告警事件。

非目标：不做实盘下单，不做自动卖出信号执行（只做决策支持）。

## 2. 决策记录

| 决策点 | 结论 |
|---|---|
| "我的持仓"锚点 | 新建 `investment_thesis` 表，论点即持仓登记；不依赖 course_portfolio/positions |
| 前端入口 | 侧边栏新页"持仓体检"（/thesis）+ Financial/Watchlist 深链 |
| 提醒触达 | 复用预警中心（Alerts 页新增"持仓论点"分区），不接飞书 |

架构选型：论点条件驱动（方案 A）。弃选：静态 21 项卖出清单（卖出决策因股因人而异）；纯事件流无体检页（信息散落）。

## 3. 数据模型（4 张新表）

遵循现有惯例：SQLModel 表类 + Repository + `create_xxx_repository()` 工厂，置于
`backend/src/infra/database/portfolio/thesis_models.py`；`main.py` lifespan import 注册建表；无 Alembic。

### 3.1 investment_thesis（论点=持仓登记）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK auto | |
| symbol | str, indexed | sh/sz 前缀，如 sh600519 |
| status | str | active / closed |
| buy_date | date | 可空（纯论点跟踪） |
| buy_price | float | 可空 |
| shares | int | 可空；与 buy_price 齐则展示盈亏 |
| thesis_text | text | 买入核心逻辑 |
| snapshot | JSON | 登记时自动抓取（见 3.5） |
| target_band | JSON | 卖出估值带 `{metric, low, high}`，metric ∈ pe_ttm/pb/dv_ttm/price |
| decision | str | 可空：hold / reduce / sell |
| decision_note | text | 可空 |
| decision_at | datetime | 可空 |
| last_reviewed_at | datetime | 最近一次体检/重估时间 |
| close_reason | str | 可空：thesis_broken / valuation_reached / better_alt / manual |
| close_price | float | 可空 |
| closed_at | datetime | 可空 |
| created_at / updated_at | datetime | |

### 3.2 thesis_condition（假设条件，论点破即卖）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| thesis_id | FK → investment_thesis, indexed | 级联删除 |
| metric_key | str | 受控枚举，见 5.2 |
| operator | str | ">=" / ">" / "<=" / "<"（对齐 evaluate_thesis 算子集） |
| threshold | float | |
| label | str | 人话描述，自动生成可覆盖 |
| status | str | holding / breached / unknown（数据缺失） |
| breached_at | datetime | 可空 |

### 3.3 thesis_reeval（重估历史）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| thesis_id | FK, indexed | |
| report_date | date | 触发的财报期 |
| trigger | str | formal / express / preannounce / price_band / manual |
| quality_now | JSON | {score, verdict, red_flag_count, red_flags[]} |
| quality_delta | JSON | {score_diff, new_red_flags[]} vs 登记时或上次重估 |
| valuation_now | JSON | 五法摘要 {dcf_fair, ddm_fair, asset_fair, comps_fair, pe_percentile, price} |
| conditions_result | JSON | [{condition_id, metric_key, current, threshold, operator, status}] |
| verdict | str | pass / review / sell_signal |
| created_at | datetime | |

### 3.4 thesis_event（轻事件表，供预警中心分区）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| thesis_id | FK, indexed | |
| kind | str | reeval_done / condition_breached / price_band_reached |
| detail | JSON | {verdict?, message} |
| read | bool | 默认 false |

### 3.5 snapshot 抓取内容（登记时服务端生成）

`{date, price, quality: {score, verdict, red_flag_count}, valuation: {dcf_fair, ddm_fair, asset_fair, comps_fair, pe_percentile}}`。
来源：`quality_report(symbol)` + 五法 handler（内部以 `json.loads(resp.body)["data"]` 调用，同 checklist_handler `_data()` 模式）。任一来源失败则对应键置 null，不阻塞登记。

## 4. 领域层（纯函数，零 IO）

新模块 `backend/src/domain/market/fundamental/thesis_monitor.py`：

1. **搬迁 `ThesisCondition` / `ThesisMonitorResult` / `evaluate_thesis`**：从
   `domain/market/portfolio/course_allocation.py`（现为无引用死代码）迁至本模块；
   course_allocation.py 原位 re-export 保持导入兼容。行为不变，已有语义：任一条件不成立
   → breached + recommend_sell；数据缺失该条件 → unknown。
2. **`METRIC_REGISTRY`**：metric_key → {label, unit, help}。首版枚举（现值取自
   `fetch_financial_snapshot` 扁平 dict，估值类取自 stock_valuation 最新行）：
   - 财务：`roe`（加权ROE%）、`revenue_yoy`、`net_profit_yoy`、`gross_margin`、
     `ocf_ratio`（经营现金流/净利润）、`debt_ratio`（资产负债率%）
   - 估值：`pe_ttm`、`pb`、`dv_ttm`（股息率%）
3. **`build_sell_check(...)`**：四区报告纯组装（输入由 handler 注入）：
   - A 论点体检：conditions × 现值 → evaluate_thesis + 距上次复检天数（>90 标记 stale）
   - B 估值到位：当前价/PE/PB vs target_band；五法现价 vs snapshot 公允价（安全边际消耗）
   - C 基本面变化：质量分与红旗 now vs snapshot；关键指标两期对比
   - D 卖出决策：三问（逻辑证伪/估值到位/更优替代）+ 当前 decision 展示
4. **`reeval_verdict(quality_now, quality_base, conditions_result)`**：
   - sell_signal：任一 condition breached，或质量 verdict 恶化至 eliminate
   - review：质量分降幅 >10，或新增红旗
   - 否则 pass
5. **`check_price_band(price, band)`**：price 型直接比价；pe/pb/dv 型取最新估值倍数比 band。

## 5. API 设计

新 `backend/src/api/router/thesis_router.py`，前缀 `/api/v1/thesis`，handler 层
`thesis_handler.py`（聚合模式同 checklist_handler）：

| 端点 | 方法 | 说明 |
|---|---|---|
| /thesis?status= | GET | 列表：实时盈亏（stock_ohlcv 最新价）、条件状态汇总、最近重估 verdict、>90 天未复检标记 |
| /thesis | POST | 登记（服务端抓 snapshot）；支持 source: course_leg 前端预填 buy_price/shares，后端不耦合 |
| /thesis/{id} | GET | 详情：thesis + conditions + snapshot + 重估历史 |
| /thesis/{id} | PUT | 更新基础字段/decision/decision_note |
| /thesis/{id}/close | POST | 关闭（reason/price）→ status=closed |
| /thesis/{id}/sell-check | GET | 四区卖出体检报告（实时聚合） |
| /thesis/{id}/reeval | POST | 手动重估（trigger=manual） |
| /thesis/{id}/conditions | PUT | 条件整表替换（全量提交） |
| /thesis/events?unread= | GET | 事件列表（预警中心分区数据源） |
| /thesis/events/{id}/read | PUT | 标记已读 |

## 6. 每日重估 job

`infra/scheduler.py` 新增 `thesis_reeval_daily`：工作日 **17:35**（排在 17:00 业绩同步、
17:30 boom 雷达之后），`misfire_grace_time`/`coalesce`/`max_instances=1` 沿用现有模式。

流程（服务函数置于 `backend/src/domain/market/thesis/service.py`——业务服务而非数据同步，不进 sync/jobs）：

1. 取 active 论点 symbol 集合；无 active 论点直接返回。
2. 新报告检测：`stock_financial_detail` 中 `report_date > 上次重估的 report_date`（首查用
   buy_date/created_at 兜底）；`stock_earnings_forecast` 新 announce_date 同理（trigger 区分）。
3. 有新数据 → 重跑 quality + 五法 + evaluate_thesis → 落 thesis_reeval + verdict 事件，更新
   thesis.last_reviewed_at 与 condition.status。
4. 估值带到价检测：全部 active 论点当前价（或倍数）vs target_band → price_band_reached 事件
   （同一 band 只告警一次，靠 detail 记录是否已提醒，避免每日重复）。

## 7. 前端

- **新页 `Thesis.tsx` / `Thesis.css`（/thesis）**：单页 master-detail。
  - 列表区：论点卡片行（symbol/名称/盈亏%/条件状态点汇总/估值带进度/最近重估 verdict 徽章/
    >90 天未复检高亮）+ 已关闭折叠区 + "登记论点"对话框（StockSearch、买入信息、论点文本、
    条件编辑器 metric 下拉+操作符+阈值、目标估值带）。
  - 详情区：假设条件表（现值 vs 阈值，holding/breached/unknown 着色）、登记时 vs 现在
    snapshot 对比卡、重估历史列表（verdict 着色）、卖出体检按钮（四区报告弹层）、
    决策记录（hold/reduce/sell + 备注）、关闭论点操作。
- **路由/菜单**：App.tsx 加 /thesis；Layout.tsx 交易分组加 {path:'/thesis', label:'持仓体检'}。
- **深链**：Financial.tsx、Watchlist.tsx 现有"买入体检"旁加"论点 →"（/thesis?symbol=xxx 预填登记框）。
- **预警中心**：Alerts.tsx 新增"持仓论点"分区，拉 /thesis/events，支持已读。

## 8. 测试计划

- 纯函数（重点）：evaluate_thesis 搬迁后行为不变；build_sell_check 四区组装与 stale 标记；
  reeval_verdict 三档规则；check_price_band 各 metric 型；METRIC_REGISTRY 完整性。
- repo：sqlite 内存库 CRUD（thesis+condition 级联删除、events 已读）。
- handler：mock 数据源聚合降级（snapshot 部分来源失败不阻塞）。
- 既有回归：`tests/strategy`、checklist 相关测试不受影响。

## 9. 验收标准

1. 从 Watchlist/Financial 任一股票可登记论点（含条件与目标带），登记后 snapshot 自动生成。
2. 打开持仓体检页可见实时盈亏、条件状态、复检提醒；卖出体检四区报告可生成并记录 decision。
3. 模拟新财报数据后手动重估产出 thesis_reeval 记录，verdict 规则正确。
4. 17:35 job 注册成功且幂等（重复运行不重复落事件，band 到价不重复告警）。
5. 预警中心"持仓论点"分区可见事件并可标记已读。
6. 后端 pytest 子集 + 前端 build 通过。

## 附录：3–7 期路线图（后续独立 spec）

- **3 决策日志与复盘**：thesis 已含 decision 字段，补 open/close/reduce 变更 journal + 定期
  复盘提醒页；1–2 落地后为最薄增量。
- **4 仓位与安全边际**：体检输出建议仓位（凯利折扣、单票上限），衔接 course_portfolio
  entry_plan 阶梯。
- **5 排雷筛选器**：z_score / m_score / fraud_signals 已聚合于买入体检，抽取为独立筛选器 +
  持仓自动排雷预警。
- **6 管理层与资本配置**：增减持/分红连续性/回购/ROIC 数据层依赖重，后置。
- **7 全市场温度计**：ERP（沪深300 E/P − 10Y 国债）/巴菲特指标 → 仓位水位建议，独立轻页。
