# 财报季景气雷达(Earnings Boom Radar)设计文档

- 日期:2026-09-08
- 状态:已实施(2026-09)
- 来源:用户提供的选股方法截图——「财报季(1/4/7/10 月)看业绩大增公司的财报/交流/调研,若出现 *供不应求、行业高景气度上行、市场超预期拓展、新品上市持续超预期、产品价格中枢持续上涨、供给偏紧、需求旺盛* 等表述,叠加业绩大增即可重点关注」

## 1. 背景与目标

把上述人工方法产品化,两个目标(用户确认两者都要):

1. **发现工具**:财报季期间,每日自动筛出「业绩大增 + 文本景气信号」的候选股,集中呈现、人工把关、一键入自选。
2. **策略验证**:用历史数据回测该逻辑(业绩大增+关键词 → 未来 N 月收益 vs 基准),量化回答「这套方法是否有超额收益、哪类信号词最有效」。

### 现状复用(已核实)

- 业绩预告/快报全市场数据已落库(`stock_earnings_forecast`,含 `change_pct`/预告类型,`raw` JSONB 保存 akshare 原始整行),每日 17:00 增量 job 在跑;`/financial/forecast` API 已存在。
- 个股新闻含正文(`news_articles`,东财源),但同步为按需触发、无定时 job;规则情绪词典(`sentiment.py`)无景气词。
- LLM 基础设施完整:LLMManager、DB prompt 模板(版本管理)、`fundamental_analyst.py` 的 `@agent_node` 结构化输出范式可照抄。
- scheduler 有成熟的「进程内闭包 job」模式;watchlist 分组模型可直接写入。

### 非目标(本期不做)

- 财报原文 PDF 解析(投入产出比最低)。
- signal 持久化与自动推送(现 signal 无表,属另一个工程,三期后再议)。
- 自动交易/下单。

## 2. 总体架构(方案 A)

新建独立域模块 `backend/src/domain/market/boom/`,与 screener/intel 松耦合;后续可在 screener 加「含雷达命中」条件做联动,但不在本设计内。

数据流:

```
每日 17:00 业绩预告 job(已有)
        │ 昨日新披露、预增、change_pct ≥ 阈值(默认 50,可配)
        ▼
boom_radar_daily job(新,17:30)
        ├─ 同步候选股个股新闻(7 天)          ← 复用 akshare stock_news_em
        ├─ 文本源采集:预告 raw 原因文本 + 新闻正文
        ├─ 规则扫描(景气词典 pure fn)──→ boom_scan_hit 命中明细
        ├─ 候选入池(upsert)──────────→ boom_candidate
        └─(二期)候选 → LLM 深读 → boom_score/结论 回写候选
                     ▼
前端 EarningsRadar.tsx(新页面,「研究」导航组)
        └─ 一键入自选 → watchlist「财报季雷达」分组
(三期)历史回测端点:重放同一套规则扫描,严防前视偏差
```

核心原则:**规则词典负责召回与可回测(确定性、零成本);LLM 只对候选池做语境纠错与深读(token 可控)。回测只走规则,不走 LLM。**

## 3. 数据模型(3 张新表)

### 3.1 `boom_keyword` —— 景气词典(DB 可配置)

| 列 | 说明 |
|---|---|
| id / category / keyword / weight / enabled | 分类 7 类;weight 强度 1-3;停用开关 |

7 个信号分类及种子词(代码内常量 seed,启动时播种,API 可增删改):

| 分类 | 种子词(含同义词扩展) |
|---|---|
| 供给紧张 | 供不应求、供给偏紧、供应紧张、紧缺、排队提货 |
| 景气上行 | 高景气、景气度上行、景气周期向上、行业景气 |
| 超预期 | 超预期、好于预期、超出预期、大超预期 |
| 价格上行 | 价格中枢上涨、价格中枢上移、提价、涨价、量价齐升 |
| 需求旺盛 | 需求旺盛、产销两旺、满产满销、订单饱满、需求强劲 |
| 新品放量 | 新品上市、新品放量、渗透率提升、产品结构升级 |
| 拓展替代 | 市场拓展、超预期拓展、国产替代、新客户突破 |

### 3.2 `boom_scan_hit` —— 扫描命中明细

| 列 | 说明 |
|---|---|
| source_type / source_ref | `forecast`(forecast 主键)/ `news`(news_articles.id)/ `survey`(二期) |
| symbol / source_date | 股票与文本日期 |
| keyword / category / snippet | 命中词、分类、上下文摘录(±30 字) |

唯一约束 (source_type, source_ref, keyword) 保证幂等。

### 3.3 `boom_candidate` —— 候选池(每股每报告期一行)

| 列 | 说明 |
|---|---|
| symbol + report_date(联合主键)/ forecast_type / change_pct / forecast_type_label | 业绩腿快照 |
| categories(JSONB)/ keyword_count / news_hit_count | 规则扫描汇总 |
| llm_score / llm_verdict(focus/watch/exclude)/ llm_summary / llm_analyzed_at | 二期 LLM 深读结果,可空 |
| status | new / confirmed / dismissed / added_watchlist |

## 4. 组件设计

### F1 词典与扫描器(`boom/keywords.py`、`boom/scanner.py`)

- 词典种子为代码常量;`scanner.scan_text(text, keywords) -> list[Hit]` 为**纯函数**,输入文本与词表,输出命中(词、分类、snippet)。否定语境做简单窗口处理(命中词前 8 字内含「未/不再/难」等否定词则丢弃),不做 NLP。
- 单测覆盖:命中、同义词、否定语境、空文本、繁简差异不做(数据源均为简体)。

### F2 文本源

- **预告原因文本**:`stock_earnings_forecast.raw` 已存 akshare 原始整行;若含「业绩变动原因说明」类字段直接扫描(实现时验证字段名,如缺失则该来源自动为空,不影响其他来源)。
- **个股新闻正文**:`news_articles.content`;雷达 job 内对当日候选股调用现有 `sync_stock_news` 同步近 7 天(不新建全局新闻定时 job,范围收敛在候选股)。
- **二期新增**:akshare 调研纪要接口(接入前验证字段与覆盖率,失败不影响主流程)。

### F3 财报季引擎(`boom/season.py` + scheduler job)

- `season.py`:财报季窗口判定纯函数。窗口口径:每年 1/4/7/10 月为预告/快报集中披露窗(与用户方法一致),3/4/8/10 月下旬为正式报表窗(二期用 detail 表补充候选)。输入日期 → 输出 {是否财报季, 窗口名, 起止, 当季报告期}。
- `boom_radar_daily` job(进程内闭包,17:30,在 17:00 预告 job 之后):非财报季或无新披露时秒完(照 `_run_financial_earnings_daily` 幂等风格);财报季时执行第 2 节数据流。阈值 `min_change_pct` 默认 50,读取配置。

### F4 LLM 深读(`boom/agents/boom_analyst.py`,二期)

- 照 `@agent_node` 范式:输入 = 预告摘要 + 命中摘录 top N;输出 = `{boom_score: 0-100, categories_confirmed, support_summary, risks, verdict}`。
- prompt 模板入 DB(key=`boom_analyst`),复用 prompt_router 版本管理。
- 成本护栏:每日 LLM 深读上限(默认 30 只,可配),超限按规则分排序截断。
- 触发:候选入池后由 job 异步调用;失败降级为「仅规则结果」,不阻塞入池。

### F5 前端(`pages/EarningsRadar.tsx`)

- 挂载:App.tsx lazy 路由 `/earnings-radar` + Layout「研究」组新增「财报雷达」。
- 页面结构:
  - **财报季状态条**:当前窗口/起止/本季预增家数/候选数;非财报季显示「休渔期」+ 下季倒计时 + 上季回顾统计。
  - **候选表**:代码/简称/预告类型/change_pct/命中分类标签/LLM 分/verdict/操作(入自选);筛选:报告期(近 4 季)、幅度阈值、分类多选。涨跌配色遵循全站「A股红涨绿跌」令牌。
  - **下钻 Modal**(参考 ScreenerDrillModal):命中原文摘录列表(来源可跳转)+ LLM 分析卡。
- 一键入自选:写 `boom_candidate.status=added_watchlist`,watchlist 自动建「财报季雷达」分组并写入。

### F6 回测(`boom/backtest.py` + 端点,三期)

- 重放:对历史各报告期,`announce_date=T` 的预增样本(≥阈值)→ **只用 T 日前可得文本**(`news_articles.published_at ≤ T` + 预告 raw)做同一套规则扫描 → 命中组 vs 仅业绩组 vs 基准。
- 组合:T+1 开盘等权买入(开盘一字涨停记为不可成交并剔除),持有 N 月(默认 3,可配);基准沪深300/中证500(宽基指数日线已有)。
- 输出:分年度收益对比、平均超额、命中率(持有期正收益占比)、**分信号分类的分组收益对比**(哪类词最值钱,反哺调词典)。
- 已知口径限制(结果页明示):①个股新闻历史深度有限,文本腿仅近一两年可测,更早年份只有业绩腿;②A 股业绩预告有强制披露门槛(±50%/亏损/扭亏,创业板不强制),样本存在覆盖偏差;③幸存者偏差(退市股缺行情时剔除并计数)。

## 5. API 设计(`boom_router.py`,prefix=`/boom`)

| 端点 | 说明 |
|---|---|
| GET `/boom/radar` | query: report_date/min_change_pct/categories → 状态条 + 候选列表 |
| GET `/boom/radar/{symbol}` | 下钻:命中明细 + LLM 分析 |
| POST `/boom/radar/{symbol}/watchlist` | 一键入自选 |
| GET/POST/PUT/DELETE `/boom/keywords` | 词典管理 |
| POST `/boom/scan/run` | 手动触发当日扫描(补数/开发用) |
| POST `/boom/backtest` | 三期:回测参数 → 结果报告 |

## 6. 分期与交付

| 期 | 内容 | 交付物 |
|---|---|---|
| 一期(MVP) | F1 词典扫描 + F2 存量文本源 + F3 财报季引擎与每日 job + F5 雷达页(纯规则,无 LLM)+ 自选闭环 | 3 表、boom 域模块、`/boom` 端点(除 backtest)、EarningsRadar 页 |
| 二期 | F4 LLM 深读 + 下钻详情完善 + 调研纪要数据源 + 正式报表窗候选补充 | boom_analyst agent、raw 来源扩展 |
| 三期 | F6 回测 + 分信号分类 IC 分析 + 报告呈现 | `/boom/backtest` + 雷达页「策略验证」Tab |

成功标准:财报季每天打开雷达页,30 秒内看完当日新增候选并完成入自选决策;三期结束后,对「历史超额收益多少、哪类信号词最有效」有量化答案。

## 7. 测试策略

- 纯函数单测:scanner(命中/同义词/否定语境/幂等)、season 窗口边界(月末/跨年/2月非财报季)。
- job 幂等测试:同一日跑两遍,`boom_scan_hit`/`boom_candidate` 不变。
- API 契约测试:照 `backend/tests/api/` 现有模式。
- 回测前视守卫测试:构造「发布时间晚于 T 的新闻」,断言不进入 T 日信号集。

## 8. 风险与开放问题

- akshare 调研纪要接口字段/覆盖率未验证(二期第一件事,失败则该来源搁置)。
- 东财个股新闻仅近期可拉,文本腿回测深度受限——已在回测口径中明示,不试图修复。
- LLM 成本:护栏为每日上限 + 仅候选池深读;一期不含 LLM,天然零成本。
- 预告原因文本字段名以实现时 akshare 实际返回为准(raw 已整行保存,无 schema 风险)。
