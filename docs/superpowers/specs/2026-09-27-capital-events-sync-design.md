# 增减持/回购同步（第 6 期 V2）设计 spec

日期：2026-09-27
接口实测（本机 akshare）：`stock_repurchase_em()` 全量 5,523 行 ≈5s；
`stock_ggcg_em(symbol="全部")` 全量 146,692 行 ≈90s（294 页分页）。
字段：回购含已回购金额(元)/数量/实施进度/最新公告日期；增减持含
股东名称/增减/变动数量(万股)/占总股本比例(%)/公告日。

## 1. 范围

akshare → `capital_event` 表（回购+增减持合一）→ 资本配置报告并入
"管理层行为"子块（近 24 个月）+ 详情页事件列表。**不计入 V1 四维
评分**（数据新、口径待观察，只做事实呈现 + 破位级 flag）。

## 2. 数据模型（1 张新表）

`capital_event`：`symbol(index), event_type(buyback|hold_increase|
hold_decrease), announce_date(index), holder_name(增减持股东，回购空串),
start_date(变动开始日/回购起始), shares_wan, amount(元，回购), ratio_pct,
progress(回购实施进度), raw JSON`；UNIQUE(symbol, event_type,
announce_date, holder_name, start_date) 幂等。

symbol 映射：6→sh，0/2/3→sz，其余→bj。

## 3. 纯函数（domain/market/thesis/capital_events.py）

- `normalize_repurchase(records) / normalize_ggcg(records)`：
  原始行(dict)→标准行；字段缺失置 None；日期字符串/None 容错。
- `summarize_mgmt_events(events, months=24, now=None)`：近 N 月
  回购实施金额合计、净增减持占股本比（增持Σ−减持Σ）、label
  （回购实施/净增持/净减持/平静）；**净减持 >1% → flag**
  （"近24个月净减持超总股本1%"）。

## 4. 同步链路

- Provider：`AkshareProvider.fetch_capital_events()` → 拉两源 →
  normalize → 标准行。
- Job `capital_event_sync`：**周六 06:30**（mine_market_scan 06:00 后），
  全量拉、批量幂等 upsert（每周全量可接受，146k 行 execute_values 秒级；
  后续可加增量过滤）。

## 5. API + 前端

- `GET /thesis/capital-events/{symbol}?months=24`：近 N 月事件列表。
- `capital_allocation_report` 输出新增 `mgmt_behavior` 子块
  （summarize 结果，含 flag）；详情页资本配置区块下加"近期资本事件"
  表（类型/日期/股东/数量/金额/占股本%）。

## 6. 测试与验收

- normalize：字段映射/缺失容错/symbol 前缀。
- summarize：方向合计/月份过滤/1% flag。
- repo upsert 幂等（sqlite）。
- job 注册；端点 mock。
- 验收：手动触发同步落库；详情页显示行为摘要与事件列表；
  后端测试 + 前端 build 通过。
