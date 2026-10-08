# 时光机 v3「拟真考核模式」设计 spec

日期:2026-09-29
状态:设计经口头确认(方案B),待用户审阅本文档
前置:v1(6007148)/v2(acaf80c)已合并 main;本文档为 v3

## 1. 背景与目标

用户反馈:时光机"符合练决策的需求,但不够真实"。四个失真点全中:

1. **盘中过程缺失** —— 按日推进、收盘价一击成交,看不到分时,没有挂单等待;
2. **决策太轻松** —— 下单前已看到当日完整K线(知道涨跌结果),AI建组合/筛选器全程加持;
3. **没有心态压力** —— 亏了重开一局,零代价;
4. **市场机制太理想** —— 分红送转不落账。

目标:新增 `exam`(拟真考核)模式,四点全灭,形成完整训练闭环:盲盒开局 → 盘中逐段推进 → 限价/市价撮合 + 强制留痕 → 揭晓评分入榜。

核心洞察:**盘中拟真不需要真实分钟数据**。用日线 OHLC 合成当日盘中路径(确定性随机),训练价值在于信息结构(看不到收盘、按"当前时刻"成交、限价单要等),而非每一笔波动是否真实发生过。真实分钟线覆盖年限短、导入成本高,收益边际低,不做。

## 2. 非目标

- 不改 `free` 模式的既有行为(它成为新引擎的特例:每天1段、段价=收盘、市价即时成交);
- 不做反作弊系统(UI 脱敏挡君子不挡 F12,文档明示);
- 不做匿名标的模式、流动性上限、真实分钟线导入、GTD隔日挂单(方案C储备,见 §11);
- 不做盘中新闻冲击(新闻仍按日供给,as-of 复用)。

## 3. 游戏机制

### 3.1 开局

- 会话新增 `mode`:`free` / `exam`;
- `exam` 开局仅选:**资金规模**(默认 100,000)+ **旅行长度** `length_days`(120 / 250 / 500 个交易日,对应半年/一年/两年)+ **时代偏好** `era_pref`(完全随机 / 牛顶区 / 熊底区 / 震荡区);
- 服务端用 `eras.py` 从基准指数历史划分时代池并随机抽起点日期;约束:起点前 ≥300 个交易日历史(K线上下文),后 ≥ `length_days` 个交易日数据;抽中日期落库,会话元数据端点(lists/get)在 exam+active 期间对 start_date/current_date 脱敏(返回 null + `day_ordinal`);行情/估值类响应仍含真实日期(前端调用需要),由 UI 脱敏挡君子,详见 §6;
- 全程日期脱敏("第N天"):K线横轴天序、新闻标题+相对天数、事件卡。用户可能从新闻内容猜出年代——可接受,防的是"记得历史剧本",不是防猜。

### 3.2 盘中循环

- 一天 = **8 段**(上午 9:30-11:30 四段 + 下午 13:00-15:00 四段,对应 30 分钟槽位);
- 每段给到:该段合成 OHLC + 截至目前的当日"分时"迷你图;池内个股与四指数同步按段推进(各自独立合成路径);
- **step=seg 逐段推进 = 盯盘日**;**step=day 快进 = 今日不看盘**(剩余段一次走完,当日不可再下单;挂单照常后台逐段检查可能成交;跳到下一交易日 seg0,记 `skipped_days`);
- 停牌日:无 bar 即无段,cursor 跳到下一交易日,事件卡提示"停牌",持仓冻结。

### 3.3 订单

| 类型 | 行为 |
|---|---|
| 市价单 | 当前段价 × (1±滑点) 立即成交;滑点为确定性伪随机 0~0.15%(方向不利;种子 = `f"{session_id}:{symbol}:{date}:{seg}:{side}"`) |
| 限价单 | 服务端在后续每段检查:买 `seg.low ≤ 限价` 触发、卖 `seg.high ≥ 限价` 触发;成交价买单 `min(限价, seg.open)`、卖单 `max(限价, seg.open)`;当日收盘未触发**自动撤销**并解冻 |

- 规则沿用 v1(移植服务端):涨跌停禁买卖(ST 5%/创业科创 20%/北交 30%/主板 10%)、T+1(按首笔 buy_date,宽松口径文档已记录)、买入整手/卖出零股、佣金 max(5, 万2.5)、印花税卖出(2023-08-28 前千1后万5);
- 限价买单冻结资金 `max(金额×1.002, 金额+5)`(佣金 5 元下限余量,防小额单成交把 cash 打负),限价卖单冻结股数(可卖 = 持股 − 冻结卖股,T+1 校验在下单时与触发时各做一次);
- 限价委托价必须落在当日 [跌停价, 涨停价] 区间;
- **每笔下单强制写理由**(1~140 字),exam 模式无理由不可提交;
- 回看态(stepBack 只移动视角)不可下单,沿用现状。

### 3.4 分红送转落账

- 交易日跨越 `stock_dividend.ex_date` 时(日切、开盘 seg0 前)对持仓应用:
  - 现金:`cash += div_per_share × shares × (1 − 税率)`;持有期税档:>1年 0% / 1月~1年 10% / <1月 20%(与论点体系同规则;按该持仓首笔 buy_date 起算);
  - 送转:`shares × (1 + stock_div + convert)`,`cost_price ÷ (1 + stock_div + convert)`;送转股本身不征税(简化,文档记录);
- 事件写入 `state.dividends_received[]` 并在当日事件卡展示(日期脱敏);
- 未复权价格 + 落账 ⇒ NAV 天然连续,无需额外调整。

### 3.5 揭晓与评分

- 触发:走满 `length_days` 或用户主动"收摊";揭晓后真实日期/时代身份/全程对照公开(ReviewView 增强);
- **总分(0~100)= 超额收益分(80) + 换手纪律分(20)**:
  - 超额收益分 = `clamp(40 + 8 × 年化超额收益百分点, 0, 80)`(基准 = 会话基准指数同期;年化超额 = 组合年化 − 基准年化;0% → 40 分,+5% → 满 80,−5% → 0);
  - 换手纪律分 = 年化换手 ≤2x 满 20,线性衰减至 10x 为 0(换手 = Σ(买额+卖额)/2 ÷ 平均NAV,按 length_days 年化);
  - 只披露不打分:单票最大仓位、平均现金占比、已平仓胜率、组合与基准最大回撤(集中持仓是价值投资的合法选择);
- 一局定档:同一 `exam` 会话不可重开、不可删后重建同起点(起点由服务端随机,用户无从指定,天然满足);揭晓分数写 `state.score`;
- 拟真榜:`GET /replay/leaderboard` 返回 mode=exam 且 revealed 的会话按分排序(前50)。

## 4. 架构

### 4.1 统一引擎

`free` 模式 = 引擎特例:1 段/天、段价 = 收盘、仅市价即时成交——与现行为一致。一套引擎服务两种模式,撮合规则不重复实现。

### 4.2 撮合后移(关键决策)

现撮合在前端 `fill.ts` 计算。限价单需要"预知后续段价"才能触发,且客户端算账存在作弊面 ⇒ **成交计算全部后移服务端权威**,fill.ts 退役(仅保留输入框本地校验)。

### 4.3 后端新组件(纯函数先行,均带单测)

| 组件 | 契约 |
|---|---|
| `domain/replay/synthetic.py` | `segments(symbol, date, bar{o,h,l,c}, seed) -> [8×{o,h,l,c}]`;确定性(`random.Random(f"{seed}:{symbol}:{date}")`,str seed 走 sha512,跨进程稳定);段间连续(seg[i+1].open = seg[i].close);seg0.open=日open、末段close=日close;全局 low/high 必达日 low/high;所有价格 ∈ [日low, 日high];一字板自然退化为 8 段同价。异常输入(OHLC 缺失/倒挂)降级 1 段=全天 |
| `domain/replay/engine.py` | fill.ts 规则移植 + `fill_market(state, order, seg, slippage_seed)` + `check_pending(state, pending, seg)`(逐段) + `apply_day_roll(state, dividends)`(落账+税档) + 资金/股数冻结解冻 |
| `domain/replay/scoring.py` | `score(nav[], benchmark[], trades[], length_days) -> {total, excess_score, turnover_score, disclosures{...}}` |
| `domain/replay/eras.py` | `pools(benchmark_bars) -> {bull_top:[dates], bear_bottom:[dates], range:[dates]}`;牛顶 = 前250日涨幅入前10%分位 且 后120日回撤>20%;熊底反之(前250日跌幅前10% 且 后120日反弹>15%);其余入震荡;池内日期间隔 ≥60 交易日;数据不足的池回退全量日期 |

### 4.4 端点

| 端点 | 变更 |
|---|---|
| `POST /replay/sessions` | body 增 `mode/length_days/era_pref`;exam 时服务端选 start_date 并在响应与其后读取中脱敏 |
| `GET /replay/sessions(/{id})` | exam+active 时 start_date/current_date → null,返回 `day_ordinal`(已走天数)与 `length_days` |
| `GET /replay/advance` | 增 `step=seg|day`(legacy `days=N` 保留给 free);服务端权威 cursor=(current_date, seg_idx) 落库;**响应只含截至当前段的行情**(信息门);返回 `{seg_idx, day_ordinal, bars片段, indices片段, fills[], pending状态, events[], day_done}` |
| `POST /replay/sessions/{id}/orders` | 新增。`{side, symbol, order_type: market|limit, shares, limit_price?, note}`;market 即时撮合返回 trade;limit 校验区间后入挂单簿;拒绝时 code≠0 + msg |
| `GET /replay/leaderboard` | 新增 |
| kline/valuation/board/instrument/news | **零改动复用**(脱敏是 UI 层职责) |

### 4.5 数据模型(最小迁移)

- `ALTER TABLE replay_session ADD COLUMN mode VARCHAR DEFAULT 'free'`;
- `ALTER TABLE replay_trade ADD COLUMN order_type VARCHAR DEFAULT 'market'`(复盘查询要用,不塞 state);
- `state` JSONB 惰性扩展键:`seg_idx` / `pending_orders[]` / `dividends_received[]` / `skipped_days` / `day_ordinal` / `length_days` / `score`(揭晓时写)。

### 4.6 前端改造(`apps/web/src/pages/replay/`)

- `store.ts`:advance 改段级;positions/cash 以服务端响应为准;去掉本地 tryFill;
- `OrderTicket.tsx`:市价/限价切换、限价区间提示、理由必填(exam);
- 新 `BlindMask.tsx`:日期→"第N天"脱敏工具(exam+active 全局挂载;新闻/事件卡经它渲染);
- 新 `IntradayStrip`:8 段 OHLC 分时迷你图(纯 SVG,零新依赖);
- 新"今日事件"卡:分红/送转/停牌/挂单撤销;
- `SessionHome.tsx`:模式选择(free 卡片 + exam 配置);
- `ReviewView.tsx`:评分卡(总分/两项分/披露项)+ 真实时间轴对照 + 拟真榜入口。

## 5. 数据流(一次典型循环)

1. 用户点"推进一段" → `GET /advance?step=seg` → 服务端:cursor seg+1(或日切:落账→下一交易日 seg0)→ 逐段检查挂单簿(可能成交,写 replay_trade)→ 截断到当前段返回行情+成交+事件;
2. 客户端 store 合并片段、更新 positions/cash/pending、BlindMask 渲染;
3. 用户下限价单 → `POST /orders` → 服务端冻结资金/股数,返回 pending;
4. 后续每段 advance 内,服务端 check_pending 决定成交/继续等;日切未触发 → 撤单解冻,事件卡告知;
5. 快进:step=day 一次走完剩余段(挂单照查),跳至下一日 seg0。

## 6. 边界与错误处理

- **一字涨跌停**:8 段同价=涨/跌停价 → 禁买/禁卖沿用;涨停价限价买单只在开板段(段价<涨停)成交;
- **市价单资金校验**按"段价+最大滑点"预扣,不足即拒(防滑点穿透);
- **advance 失败**:游标不前移(沿用服务端自洽推进语义,终审 C1 教训);
- **挂单遇停牌/一字无成交**:日切自动撤销,资金解冻,事件卡说明;
- **提前收摊**:按已走天数评分(NAV 与基准对齐到已走区间),旅行即结束,不补走;
- **并发**:单人单会话;服务端单事务内完成推进+撮合+落库;前端沿用 advancing 防抖;
- **作弊边界**:as-of 端点与 advance 响应仍含真实日期(客户端要拿去查估值等),UI 脱敏;F12 可见,明示"训练拟真,非反作弊";
- **时代池空池**:回退全量日期随机(短历史基准亦可开);
- **数据终点**:池内某股在途中退市/长停 → 有 bar 才有段;最后成交价按最后可得收盘价计入 NAV(简化,与现状一致)。

## 7. 测试计划

- `synthetic`(pytest):同 seed 同路径;端点对齐 O/C;必经 H/L;全程有界;段间连续;一字板退化;坏数据降级;
- `engine`(pytest):fill.ts 用例语义 1:1 移植(涨跌停五档/T+1/整手零股/费税/资金不足);市价滑点方向;限价触发(穿越/开盘优于限价)/区间外拒单/收盘撤单解冻;冻结与 T+1 复检;分红三税档 + 送转股数/成本/NAV 连续;
- `scoring`:空仓/亏损/负超额/满超额/换手边界/提前收摊;
- `eras`:池划分抽样断言(牛顶池起点后确实大跌等);短历史回退;
- 前端 vitest:store 段级推进与快进合并/BlindMask 脱敏/OrderTicket 校验;TS 类型沿用独立 strict 探针 + build(仓内 tsconfig 既知问题);
- 手动验收清单:盲盒开局看不到任何日期 → 逐段推进下单 → 挂单次日触发 → 分红日事件卡+现金到账 → 揭晓评分入榜 → free 模式回归不变。

## 8. 验收清单(人工)

1. exam 开局 3 种长度 × 4 种时代偏好可开局,响应与 UI 均无真实日期;
2. 盯盘日逐段推进,分时迷你图渐进,收盘价在下单前不可见;
3. 市价单即时成交含滑点;限价单挂单→穿越触发/收盘撤销两路径;
4. 无理由提交被前端与服务端双重拒绝;
5. 分红除权日现金到账金额=税后口径,送转后股数/成本正确,NAV 无跳空;
6. 揭晓评分公式抽查一条会话手算一致;榜单排序正确;
7. free 模式全流程回归(现有测试不红)。

## 9. 实施顺序建议(供 writing-plans 展开)

1. 迁移 + eras + synthetic(纯函数层,先行可测);
2. engine 移植与段级撮合(含对齐测试);
3. advance/orders 端点改造(服务端权威 cursor);
4. scoring + leaderboard + reveal 增强;
5. 前端 store/OrderTicket/BlindMask/IntradayStrip/事件卡/SessionHome/ReviewView;
6. 手动验收与回归。

## 10. 风险与对策

- **合成路径失真感**:用户若反馈"分时形状假",升级 synthetic 为带量能/波动聚集的路径(接口不变,纯函数替换);
- **撮合后移回归风险**:free 特例用 1:1 移植测试锚定;灰度期间 free 走新引擎跑全量旧用例;
- **段级推进请求量**:8×播放频率,沿用 4 req/s 压测口径,psycopg2 显式 close(v1 follow-up 一并做);
- **评分争议**:公式全部披露在揭晓页,只披露不打分的项明确标注"不参与评分"。

## 11. Follow-up 储备(本期不做,方案C遗珠)

- 流动性上限(单笔 ≤ 当日成交额 x%)、停牌事件更真实化;
- 匿名标的模式(名称代号化,揭晓公开身份,与基本面工作流的冲突待解);
- 真实分钟线导入(28GB 存量,仅近年覆盖);
- 盘中新闻冲击、GTD 隔日挂单、多空(融券)模拟。
