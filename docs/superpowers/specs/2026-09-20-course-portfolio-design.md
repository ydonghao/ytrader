# 自动建组合(课程组合·仓位管理)设计

日期:2026-09-20
来源:课程字幕 `docs/策略/xhzl2/股票投资从入门到精通/` 第23讲(投资组合配比建议)与第24讲(投资组合的仓位管理思路)

## 背景与目标

两讲课程的核心方法论:

- **第23讲(配比)**:按风险偏好把权益仓位配到三类公司——红利股/蓝筹股/创新类。四档配比:防御 7:3:0、稳健 5:4:1、积极 3:5:2、激进 0:3:7。"成长性×股东回报"四象限用于给公司分类(成熟红利/现金奶牛/成长再投入/价值陷阱,价值陷阱回避)。
- **第24讲(仓位管理)**:组合 5–8 家、预留 10% 现金;用个股 PE 均值±1σ 判估值四状态(虚高/合理偏高/合理偏低/超跌);按风险偏好定建仓时机;"层层狙击"分批建仓(底仓 30% + 越跌越买);横盘/超涨/破位三种情况的应对;提前规划、拒绝盘中临时起意;周检视。

目标:把这套方法论做成**自动建组合**功能——输入资金与风险偏好,系统自动选股分类、按配比定金额、按估值带生成分批建仓档位,落库后支持周检视跟踪闭环。

## 已确认的决策

| 决策点 | 结论 |
|---|---|
| 产出形态 | 计划 + 落库跟踪(非只读建议,不直接建模拟持仓) |
| 建仓口径 | PE 估值带驱动(μ±1σ 四状态),档位按现价回落百分比 |
| 前端入口 | 新页面 `/course-portfolio`,菜单"自动建组合" |
| 跟踪闭环 | 做周检视(买入触发/超配减仓/破位复查) |

## 架构选型

**方案A(采纳):独立新表** `course_portfolio` + `course_portfolio_leg`。课程组合全是股票且大量腿尚未建仓(shares=0),与既有 `portfolio_definition/holding`(股/债/金/现金四类资产、持仓制核算)语义不同,不混用。SQLModel `metadata.create_all` 自动建表(同 `infra/database/portfolio/models.py` 惯例,main.py 启动时 import)。

方案B(否决):复用 `portfolio_definition` 加 `strategy_type='course'`。`portfolio_instrument.asset_class` 无红利/蓝筹/创新维度,且 PermPortfolio 页会混列出课程计划。

## 选股与分类规则

Universe 复用选股器取数惯例(`domain/market/strategy/longterm/data_loader.py`):全 A 剔 ST,要求有最新 `stock_valuation` 快照;财务数据缺失者排除。

| 类别 | 规则 | 排序 | 数据来源 |
|---|---|---|---|
| 红利股 dividend | 派息率≥30% 且 营收增速<10%(成熟红利象限)且 股息率≥3% | 股息率降序 | `stock_valuation`(派息率≈dv_ttm×pe_ttm÷100)、`stock_financial_detail` 算营收YoY |
| 蓝筹股 bluechip | 沪深300成分 ∩ 最新ROE≥10% | 指数权重降序 | `index_constituent`(000300)、`stock_financials.roe_weighted` |
| 创新类 growth | 营收增速≥10% 且 派息率<30% 且 ROE≥10%(成长再投入看ROE) | 增速降序 | 同上 |

- 四象限标签展示复用 `course_allocation.growth_dividend_quadrant`。
- 每类选取数量:股票总数按风险偏好配比比例分配到三类(如 8 只×积极 3:5:2 → 红2/蓝4/创2),配比为 0 的类别不分配;单类可用候选不足时少配并警告。
- 类内等权(课程口径"每家公司 5–6 万"):单腿目标金额 = 类别权重 × 可投资资金 ÷ 该类腿数。
- 可投资资金 = 总资金 × (1 − 现金预留10%)。

## 估值带与建仓档位

复用 `fundamental/valuation_band.valuation_band`(μ±1σ 四分类)。每腿取近 5 年 PE_TTM(自 `stock_valuation.get_range`,月度降采样,样本≥24 个月才算有效):

| 生成时状态 | 行为 |
|---|---|
| 合理偏低 / 超跌 | 即建底仓 30%,其余三档各约 23%:档位价 = 生成日收盘 × (1−5% / −10% / −15%) |
| 合理偏高 | 等待状态:四档锚定 μ 对应价、μ−0.5σ、μ−1σ、μ−1.5σ(跌入合理偏低才开买) |
| 虚高 | 暂不建仓,仅观察提示(课程:估值虚高买入无安全性可言) |

- 档位金额按 100 股整数手向下取整(复用 `strategy/position_sizing` 的 lot 工具),不足一手不建该档。
- 档位价格在生成时固化(课程:"提前规划,凡事预则立");行情破位或估值体系变化后用户可删除重建。
- 激进型可在底部状态适当超配的取舍不在本期(保持等权简单口径)。

## 周检视(课程24第九节量化)

`GET /course-portfolio/{id}/review` 现算(不落库),返回建议列表:

- **买入触发**:现价 ≤ 下一未执行档价格 → "建议买入第 N 档 ≈X 元(Y 股)"。
- **超配减仓**:腿实际权重 − 目标权重 > 阈值(默认 3pct,因上涨被动超配)→ "建议减仓至目标,释放资金"。
- **破位复查**:现价 < 最低档价格 → "破位提醒:先复查基本面逻辑,勿急于补仓"(课程:破位=业务分析失误,不是仓位技巧问题)。
- **组合层**:三类实际占比 vs 目标占比、建仓总进度(已投入/目标)、组合加权股息率、现金余额。

实际持仓价值 = 已执行档累计股数 × 最新收盘价(`stock_ohlcv`)。

## 数据层(2 张新表)

```
course_portfolio
  id PK / name / risk_profile / total_capital / cash_reserve_pct(0.10)
  target_stock_count / status(planned|building|complete) / notes
  created_at / updated_at

course_portfolio_leg
  id PK / portfolio_id FK / symbol / name
  category(dividend|bluechip|growth) / target_weight / target_amount
  pe_band JSONB  {mean, std, z_score, state, sample_count, as_of}
  entry_plan JSONB  [{rung_index, drop_pct, price_level, amount,
                      executed:false, executed_at, fill_price, fill_shares}]
  invested_amount / avg_cost
  created_at / updated_at
  UNIQUE(portfolio_id, symbol)
```

仓储:`infra/database/portfolio/course_portfolio_repository.py`(仿既有 repository 风格,DBConnection 注入)。

## API(新 `api/router/course_portfolio_router.py`,main.py 惯例注册)

```
POST   /api/v1/course-portfolio/generate        生成预览(不落库)
POST   /api/v1/course-portfolio                 保存计划(前端换股调整后的最终腿列表)
GET    /api/v1/course-portfolio                 列表
GET    /api/v1/course-portfolio/{id}            详情(含各腿与档位进度)
GET    /api/v1/course-portfolio/{id}/review     周检视建议
POST   /api/v1/course-portfolio/{id}/legs/{leg_id}/fills  标记某档已买(默认按最新收盘价折算股数,可传实际价/股数)
DELETE /api/v1/course-portfolio/{id}            删除(级联删腿)
```

generate 请求体:`{total_capital, risk_profile, stock_count=8, as_of?}`;响应除计划外附三类**候选池**(每类按排序多返回约 3 倍备选,供前端换股下拉)。换股调整在前端预览本地完成(仅允许同类替换),save 持久化最终腿列表。

领域模块(纯函数 + 仓储注入,便于单测):

- `domain/market/portfolio/course_builder.py` — 分类筛选(universe→三类候选)、配额分配(类内等权/按配比分腿数)、档位规划(lot 取整/等待态锚定)。
- `domain/market/portfolio/course_review.py` — 检视三态建议 + 组合层聚合。

既有 `course_allocation.py` 的 `RISK_PROFILES`、`growth_dividend_quadrant` 直接复用,不重复实现。

## 前端(React,贴现有模式)

- `pages/CoursePortfolio.tsx` + `CoursePortfolio.css`;`App.tsx` 加路由;`Layout.tsx` 菜单"自动建组合"置于选股器旁。
- 三步向导:①风险偏好四卡(展示配比)+资金/股票数 → ②预览(三类分组表:股票/四象限标签/权重/金额/PE状态徽章/档位表;每腿可从同类备选换股) → ③保存。
- 详情页:腿表(类别徽章/建仓进度条/下一档距离/估值状态)、检视面板(建议列表,红涨绿跌口径)、"标记已买"弹窗、删除。
- API 走 `lib/api.ts` 既有封装;UI 用全站令牌体系(`styles/`、`lib/chartTheme.ts`)。

## 测试与边界

- pytest:
  - 分类规则(象限边界、派息率推导、ROE 门槛、候选不足)
  - 配额分配(配比→腿数分配、类内等权、现金预留)
  - 档位规划(三状态分支、lot 取整、不足一手)
  - 检视三态(触发/超配/破位)与组合层聚合
  - router 假仓储测试(仿 `tests/api/test_screener_router.py`)
- 边界:
  - PE 历史样本 <24 个月 → 状态"数据不足",不生成档位,仅观察;
  - 某类候选池为空 → 该类权重留现金并在响应/检视中警告;
  - 收盘价缺失(停牌)→ 检视跳过该腿并提示;
  - 换股仅允许同类替换,保持类别配比不变。

## 非目标(本期不做)

- 不接模拟撮合/replay;不做自动定时检视(用户手动触发);不做 K 线支撑压力自动划线;不做申购/分红事件跟踪;激进型超配策略。
