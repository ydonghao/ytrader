# 行业分析(Industry Analysis)设计文档

- 日期:2026-09-20
- 状态:待实施
- 来源:用户提供的行业研究学习笔记——五条原则(景气行业中找机会/同行业对比估值避免跨行业错标/理解产业链上下游/板块资金统计与择时/组合分散控仓)+ 申万31个一级行业框架 + 分行业投资难易度三层分级

## 1. 背景与目标

把笔记方法论产品化为一个「行业分析」页面,回答四个问题:

1. **现在是不是阶段性底部?**——全市场破净率 >10% 的宏观择时信号。
2. **哪些行业景气?**——31个申万一级行业的增长/估值/动量/资金原始指标矩阵(热力图)+ 一列透明加权的综合景气分。
3. **这个行业贵不贵、质地如何?**——行业内个股 PE/PB 分布、历史分位、同行对比、集中度。
4. **板块资金在往哪走?**——行业资金流排行与 5/20 日累计、RS 相对强弱 vs 沪深300。

外加两个知识性能力:每行业的**投资难易度与散户适宜度元数据**(笔记三层分级)、**产业链上下游图谱**、以及**LLM 景气解读**(手动触发)。

### 现状复用(已核实,2026-09-20 查库)

| 设施 | 现状 |
|---|---|
| 申万成分映射 | `sw_industry_member` 5218 只全覆盖,每周六 06:00 重灌 |
| 行业估值日线 | `sw_index_valuation_daily` 31 行业,1992 起 23-34 年/行业(source=computed 回填 + 2026-08 起 akshare 日更) |
| 行业指数价格 | `index_ohlcv` market='SW',1999-12 起,16:46 增量 job 在跑 |
| 个股 PB 日线 | `stock_valuation` 1034 万行,1991-01 起,5220 只,pb 非空 96% |
| 行业基本面截面 | `sw_industry_cross_section` CR4/CR8/HHI、营收总和/同比、毛利率净利 ROE 分布(JSON),至 2026-06-30 |
| RS 纯函数 | `strategy/relative_strength.py`(relative_strength/rs_line/rs_trend),基准 `sh000300` 在库 5996 根 |
| 行业资金流 | 仅即时内存缓存(`/market/fund-flow`,东财 90 行业口径),**无历史落库** |
| 破净率 | 仅个股级 below_book 标志,**全市场/行业级聚合不存在** |
| LLM 设施 | LLMManager + DB prompt 模板(`load_prompt_from_db_or`),boom `llm_analyst.py` 为完整范例 |

### 非目标(本期不做)

- 行业级新闻/公告文本扫描(boom 雷达已覆盖个股级,行业级舆情另议)。
- 基于板块择时的自动轮动策略与回测(先看数据,验证另立一期)。
- 二级/三级行业下钻(v1 仅一级行业;表结构预留 sw_code 不限层级)。
- 投资组合构建/仓位管理(笔记第 5 条,已有组合回测体系,不在本页范围)。

## 2. 总体架构

新建独立域 `backend/src/domain/market/industry_analysis/`,照 boom 域惯例;前端新增一页 `/industry-analysis`(「分析」导航组)。全部增量,不改既有表与端点。

```
现有表(只读)                         新增落库(3 张表)
─────────────                        ────────────────
stock_valuation(个股PB) ──聚合──→ industry_pb_break_daily(16:40 job)
sw_industry_member(成分) ──┘
东财行业资金流(akshare) ────────→ industry_fund_flow_daily(17:05 job)
sw_index_valuation_daily ─┐
index_ohlcv(SW+sh000300) ├─评分──→ industry_prosperity_daily(17:20 job)
sw_industry_cross_section┤   (纯函数,分项快照可回溯)
industry_fund_flow_daily ─┘
conf/industry_knowledge.yaml(静态知识,服务启动加载)
                    │
                    ▼
        industry_router(/industry,6 端点)
                    ▼
前端 IndustryAnalysis.tsx:宏观择时/景气热力图/板块强弱 三 Tab + 行业详情抽屉(含 LLM 解读按钮)
```

## 3. 数据模型

### 3.1 `industry_pb_break_daily` —— 破净率序列

PK(trade_date, scope, scope_code);scope ∈ {'market','industry'},market 行 scope_code='ALL'。列:total_count(有效个股数)、break_count(pb<1)、break_rate、median_pb。市场级=全市场当日 PB 聚合(**择时主信号,无偏差**);行业级=按 `sw_industry_member` **当前**成分聚合历史(**幸存者/成分漂移偏差,页面明示**)。回填深度随 stock_valuation 到 1991。

### 3.2 `industry_fund_flow_daily` —— 行业资金流历史

PK(trade_date, em_industry_name)(东财行业名,约 90 个)。列:main_net_inflow(主力净流入,元)、close_change_pct(行业涨跌幅)。17:05 job 收盘后抓一次(与 `/market/fund-flow` 同源 akshare 接口);5/20 日累计由查询时对日表求和,不另存。**不强行映射申万**:配 `backend/conf/em_flow_to_sw.yaml` 人工维护多对一近似映射(东财行业名 → 申万码,允许空),仅用于景气分的资金分项与热力图对齐展示;强弱 Tab 保留东财原生口径排行。

### 3.3 `industry_prosperity_daily` —— 景气分快照

PK(trade_date, sw_code)。列:score(0-100 或空)、score_profit/score_valuation/score_momentum/score_flow(分项)、inputs(JSONB:各原始输入值,保证分数可追溯可重算)。每日全量 31 行重算 upsert;历史回填按**月末采样**落库(上线后逐日自然积累)。

### 3.4 知识层 `backend/conf/industry_knowledge.yaml`(静态配置,非表)

31 个申万一级行业各一条,按用户笔记初拟,可随时手改:

```yaml
"801010.SI":            # 农林牧渔
  name: 农林牧渔
  tier: 2                # 投资难易度:1=消费者易分析/2=需专业分析/3=短时效消息驱动
  retail_suitable: medium  # 散户适宜度: high/medium/low
  approach: "猪周期主导,看能繁母猪存栏与猪价;种业看政策"
  upstream: [化肥, 农药]
  downstream: [食品加工, 餐饮]
  note: ""               # 自由备注
```

三层分级口径(笔记):tier1 消费/金融等易分析;tier2 需专业分析最好业内人士(医药/电力设备/中游制造等);tier3 消息短时效高精力(国防/环保等非盈利导向、部分主题行业)。approach 一句话写分析抓手(资源跟大宗商品/中游看下游地产建筑需求/消费看品牌渠道复购/金融标准化适合学习一次等)。加载器做 schema 校验(31 码齐全、枚举合法),坏配置启动即报错。

## 4. 组件设计

### F1 破净率聚合(`industry_analysis/pb_break.py`)

`aggregate_pb_break(valuations: list[tuple[symbol, pb, industry_l1_code | None]]) -> dict` 纯函数:输出总数/破净数/比率/中位 PB,market 与逐行业一次遍历算完。job 侧按日取 stock_valuation JOIN 成员映射,逐日 upsert;幂等可重跑补洞(stock_valuation 有历史漏跑缺口,缺日即缺,不插值)。

### F2 景气分(`industry_analysis/prosperity.py`,纯函数)

输入字典(某行业某日)→ 输出总分+分项,全部 0-100、缺项按剩余权重归一、全缺返回 None:

| 分项 | 输入 | 归一方法 | 权重 |
|---|---|---|---|
| 盈利 | cross_section 最新报告期 revenue_yoy + 净利同比(自 `net_profit_sum` 跨期计算,表内无现成列) | 跨行业当日截面分位 | 0.35 |
| 估值 | `sw_index_valuation_daily` 当前 PB/PE_ttm 在自身历史的分位,取反 | 1 − 分位 | 0.25 |
| 动量 | 60 日收益 vs sh000300 超额(复用 relative_strength 纯函数;RS 趋势仅作展示标签,不参与打分) | 跨行业截面分位 | 0.25 |
| 资金 | em_flow 映射后 20 日主力净流入合计(可缺) | 跨行业截面分位 | 0.15 |

权重入 `config.yaml`(`industry_analysis.weights`),估值分位窗口固定取 config 默认(8 年,可调)——**评分口径恒定**;热力图上 PE/PB 分位展示列才允许 5/8/10 年窗口切换,两者互不影响。页面分项拆解展示原始值+分项分,黑箱程度最低化。

### F3 产业链图谱(静态,前端渲染)

上下游即 knowledge yaml 的 upstream/downstream 列表,详情抽屉内以简单层级图渲染(echarts graph,无外部依赖数据)。v1 为人工整理的粗粒度链(每行业 2-6 节点),不做自动化推导。

### F4 LLM 解读(`industry_analysis/llm_analyst.py`)

照 boom `llm_analyst.py` 模式:prompt key=`industry_analyst`(`load_prompt_from_db_or` 可 DB 覆盖),输入=该行业景气拆解+估值分位+资金流+知识卡,输出 JSON `{summary, drivers[], risks[]}`(宽松解析同 boom)。**仅手动点击触发**,进程内当日缓存(query 参数变化即重算),provider 未配置时按钮可见、点击返回 503 提示文案——零后台成本。

### F5 前端(`pages/IndustryAnalysis.tsx` + `components/industry/`)

- 挂载:App.tsx lazy 路由 + Layout「分析」组「行业分析」;hook `useIndustryAnalysis.ts`。
- **Tab1 宏观择时**:全市场破净率日线曲线(echarts),>10% 区间背景红标「阶段性底部参考区」;当前值/历史分位/破净家数卡片;下拉切换到任一行业破净率(带偏差提示)。1991 年前段数据稀疏,x 轴默认近 10 年可缩放。
- **Tab2 景气热力图**:31 行 × (营收同比/净利同比/PE+分位/PB+分位/RS60/20日资金/景气分/难易度)矩阵,单元格按值着色(全站红涨绿跌令牌,chartTheme 常量),任意列排序,默认景气分降序;列头可切换分位窗口(5/8/10 年)。估值分位列角标注历史起始年(各行业 1992-2003 不等)。
- **Tab3 板块强弱**:左=20日主力净流入排行条形图(东财口径;当日/5日数据API已返回,v1未绘制);右=31 行业 RS 排名 + 任选 ≤5 行业 RS 线叠加 vs 沪深300。
- **详情抽屉**(仿 BoomDrillModal,点热力图行/强弱条目开):知识卡(难易度徽章/适宜度/分析思路)、产业链小图谱、景气分拆解条、行业内个股 PE/PB 分布直方图(成分 JOIN stock_valuation 当日)、同行估值表(复用 `/financial/industry-peers` 既有端点数据)、AI 解读按钮(F4)。

### F6 回填与 job(`sync/jobs/`,手动脚本 + scheduler)

- job:16:40 破净率增量、17:05 资金流落库、17:20 景气分重算(闭包动态 import + try/except,`industry_analysis.enabled` 总开关,惯例参数照抄 boom)。
- 一次性脚本(手动,ProgressTracker 断点续传):破净率全历史回填(逐日聚合,预计分钟级)、景气分历史回填(依赖估值分位与 RS 的滑窗,按月末采样控制计算量,输入快照照存)。

交付顺序建议:数据层(3表+knowledge yaml+F1/F2 纯函数)→ 回填脚本跑通 → job + API → 前端三 Tab → 详情抽屉 + LLM 解读。每步可独立验证。

## 5. API 设计(`industry_router.py`,prefix=`/industry`)

| 端点 | 说明 |
|---|---|
| GET `/overview` | query: window(5/8/10,估值分位展示窗口) → 热力图全矩阵(31 行,含景气分与分项、难易度标签) |
| GET `/pb-break` | query: scope/scope_code/years(默认35) → 破净率序列 + 当前值/分位摘要 |
| GET `/flow` | 东财行业排行 + 5/20 日累计(固定近30自然日,无 window 参数) |
| GET `/{sw_code}` | 行业详情:cross_section(集中度/分布)、成分估值分布、知识卡、景气拆解 |
| GET `/{sw_code}/strength` | RS 数据:60 日超额、RS 线序列、趋势标签;query: compare(逗号分隔多行业) |
| POST `/{sw_code}/interpret` | LLM 解读(F4,手动触发) |

## 6. 测试策略

- pytest 纯函数:pb_break 聚合(空行业/全缺 PB)、prosperity 评分(缺项归一/全缺 None/权重和校验/可重算)、em↔sw 映射加载、knowledge yaml schema(31 码齐全/枚举合法/坏文件报错)。
- job 幂等:同日两跑三表不变。
- API 契约测试照 `backend/tests/api/` 模式;跑子集(库内既有 52 失败为历史遗留,不基线混淆)。
- 前端 vitest:useIndustryAnalysis hook、热力图单元格着色与排序逻辑、分位窗口切换。

## 7. 风险与口径明示

- **行业破净率历史=当前成分回溯**,存在成分漂移偏差;页面显著标注,宏观择时只认 market 口径。
- stock_valuation 历史漏跑缺口 → 破净率序列有缺日,不插值,job 幂等可后补。
- 东财资金流约 90 行业口径与申万不一致,映射为近似多对一,未匹配行业资金分项为缺项(评分自动按剩余权重归一)。
- 景气分为透明加权截面分位,非预测模型;权重默认值系经验拍定,config 可调,页面展示拆解防黑箱。
- cross_section 最新报告期滞后(财报披露节奏),盈利分项天然滞后 1-2 季,属设计内。
- 景气分/破净率的"每日" job 以 stock_valuation 最新日为锚(基本面周六批更),展示的评分日期随估值节奏,非逐日前滚;资金流为真实逐日。
