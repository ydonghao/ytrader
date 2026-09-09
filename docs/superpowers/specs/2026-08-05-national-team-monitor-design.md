# 国家队动向监控 — 设计文档

- **日期**: 2026-08-05
- **状态**: 设计待审
- **作者**: 与用户共同 brainstorm

## 1. 目标

提供一个统一页面,让用户每天都能看到国家队的操作动向,并回溯历年(2015 年至今)的持仓变化,支持逐年/逐季对比。

**成功标准**:
1. 侧边栏「财务报表」后新增「国家队」菜单,点击进入 `/national-team`。
2. 默认 Tab「每日动向」盘后可见当日宽基 ETF 护盘信号(放量倍数 + 抗跌判定)。
3. 「历年持仓」Tab 提供 4 个视图:总市值趋势线、季度环比变动、行业分布、个股 Top 榜(可下钻)。
4. 历年数据回溯至 2015Q1,通过定时同步任务增量补齐。
5. 数据全部来自 akshare,不引入新外部依赖。

## 2. 数据现实说明(写入页面的免责声明)

国家队持仓分两个口径,用户需理解:

- **每日动向**:基于宽基 ETF 的放量与抗跌行为推断「疑似护盘」,是**行为信号**,不点名国家队。盘后(15:30 后)即可见,**今天**可得。
- **历年持仓**:来自上市公司季报/半年报/年报的「前十大流通股东」,是**权威快照**,**季度颗粒度**,有 3-4 周披露滞后。

这两个口径互补:每日看信号,季度看实锤。页面需在显眼位置写明此区别,避免误解。

## 3. 范围

### 3.1 国家队主体名单(配置化)

存于 `backend/conf/national_team_entities.yaml`,便于后续扩充:

```yaml
# 中央汇金
huijin:
  - 中央汇金投资有限责任公司
  - 中央汇金资产管理有限责任公司

# 证金公司 + 十个资管计划
zhengjin:
  - 中国证券金融股份有限公司
  - 中证金融资产管理计划  # 匹配前缀,覆盖十个资管计划(中证金融-XX银行-资产管理计划)

# 外管局三大平台
safe:
  - 梧桐树投资平台有限责任公司
  - 北京凤山投资有限责任公司
  - 北京坤藤投资有限责任公司

# 社保基金
social_security:
  - 全国社保基金  # 匹配前缀,覆盖各组合(全国社保基金XXX组合)
```

匹配策略:**前缀匹配**(因资管计划/社保组合后缀多变)。回填任务读取此配置。

### 3.2 回填范围(历年持仓)

沪深 300 成分股 + 银行板块 + 非银金融板块(证券 + 保险),约 400 只股票。覆盖国家队 95%+ 仓位。

成分股来源:akshare 的指数成分接口(`ak.index_stock_cons_csindex` 或 `ak.index_stock_cons`)。银行/非银来自申万一级行业或板块分类。

### 3.3 监控 ETF(每日动向)

| 代码 | 名称 | 对应指数 | index_code |
|---|---|---|---|
| 510300 | 沪深300ETF(华泰柏瑞) | 沪深300 | sh000300 |
| 510050 | 上证50ETF(华夏) | 上证50 | sh000016 |
| 510500 | 中证500ETF(南方) | 中证500 | sh000905 |
| 560010 | 中证1000ETF(广发) | 中证1000 | sh000852 |
| 159915 | 创业板ETF(易方达) | 创业板指 | sz399006 |
| 563360 | 中证A500ETF(华泰柏瑞) | 中证A500 | sh932000 |

> 注:中证1000 主力 ETF 也可选 512100(万家)等规模相近产品,默认用 560010(广发,规模居前)。中证A500 是 2024-09 才上市的新品种,历史信号自此点起才有。

ETF 列表同样配置化,存于 `national_team_entities.yaml` 的 `watch_etfs` 段,含 `etf_code → index_code` 映射(用于抗跌判定)。

## 4. 系统架构

```
┌─────────────────────────────────────────────────────────┐
│ 前端 /national-team (单页两 Tab)                          │
│  Tab1 每日动向  |  Tab2 历年持仓(4 子视图)               │
└──────────────┬──────────────────────────────────────────┘
               │ fetch {code,msg,data}
┌──────────────▼──────────────────────────────────────────┐
│ 后端 API (national_team_router.py + handler)             │
│  /daily-signals      (TTL 缓存,不落库)                   │
│  /holdings/summary   /changes  /sector-distribution      │
│  /holdings/top-holdings                                  │
└──────┬───────────────────────┬───────────────────────────┘
       │                       │
┌──────▼───────┐    ┌──────────▼──────────────────────────┐
│ AkshareProvider │    │ national_team_holding 表           │
│ 新增方法:        │    │ (report_date, holder, symbol, ...)│
│ - fetch_etf_   │    │ Repository: upsert / 查询           │
│   daily_signal │    └──────────▲──────────────────────────┘
│ - fetch_top10_ │               │ upsert
│   float_holders│    ┌──────────┴──────────────────────────┐
└────────────────┘    │ national_team_backfill.py (sync job)│
                      │ 定时增量回填 2015→今                │
                      └─────────────────────────────────────┘
```

## 5. 后端详细设计

### 5.1 持仓表 `national_team_holding`

文件:`backend/src/infra/database/market/national_team_holding.py`,模仿 `macro_indicator.py`。

```python
class NationalTeamHolding(SQLModel, table=True):
    __tablename__ = "national_team_holding"
    id: int | None = Field(primary_key=True)
    report_date: date             # 报告期 YYYY-MM-DD(季度末)
    holder_name: str              # 股东全称(原始)
    holder_category: str          # huijin/zhengjin/safe/social_security
    symbol: str                   # 股票代码(无交易所前缀)
    company_name: str             # 上市公司名
    hold_shares: int              # 持股数
    hold_value: float             # 持股市值(元)
    pct_of_float: float           # 占流通股比例 %
    ranking: int                  # 第几大流通股东
    is_new: bool                  # 本期是否新进
    change_shares: int            # 本期变动股数(正增负减)
    fetched_at: datetime          # 抓取时间
```

唯一约束:`(report_date, holder_name, symbol)`。Repository 提供:
- `upsert_batch(records)` — 批量写入/更新
- `get_summary_series(from, to)` — 按 report_date × holder_category 聚合总市值
- `get_changes(period, vs_period, category, type)` — 季度环比变动
- `get_sector_distribution(from)` — 关联行业(用 `ak.sw_index_first_info` 的归属或预存行业字段)做分布
- `get_top_holdings(period, limit)` / `get_symbol_history(symbol)` — Top 榜与下钻

**行业归属**:成分股池在回填时一并存其申万一级行业到关联表 `national_team_symbol_sector(symbol, sector)`,避免每次查询再调 akshare。

### 5.2 AkshareProvider 新增方法

文件:`backend/src/domain/market/sync/providers/akshare_provider.py`

```python
def fetch_top10_float_holders(self, symbol: str, report_date: str) -> list[dict]:
    """ak.stock_gdfx_free_top_10_em(symbol=symbol, date=report_date)
    返回 [{holder_name, hold_shares, pct, ranking, ...}]"""
    # 注意:date 参数格式为 YYYYMMDD,需从 report_date 转换
    # akshare 该接口对未到报告期的股票返回空,需处理

def fetch_etf_daily_signal(self, etf_code: str, index_code: str, lookback_days: int = 20) -> dict:
    """计算单只 ETF 的当日护盘信号
    返回 {etf_code, etf_name, vol_ratio, etf_chg_pct, index_chg_pct, defend_flag, strength}
    逻辑:
      1. ak.fund_etf_hist_sina/em 取 ETF 近 30 日量价(已用接口)
      2. ak.stock_zh_index_daily 取对应指数当日涨跌
      3. vol_ratio = 今日量 / 过去20日均量
      4. defend_flag = (index_chg < 0 and etf_chg >= index_chg + 0.5)  # ETF 明显抗跌
      5. strength 映射: vol_ratio>=3 and defend → 'strong'; vol_ratio>=2 → 'suspect'; else 'none'
    """
```

**风险点**:akshare 的 `stock_gdfx_free_top_10_em` 对历史报告期需要逐季度调用,接口偶发不稳定,需复用 provider 已有的 `_retry_all` 重试机制。

### 5.3 API Handler & Router

文件:`backend/src/api/handler/national_team_handler.py` + `backend/src/api/router/national_team_router.py`

模仿 `macro_handler.py` / `macro_router.py`。Router `prefix="/national-team"`。

| 方法 | 路径 | 说明 | 缓存 |
|---|---|---|---|
| GET | `/national-team/daily-signals` | 当日 ETF 信号 + 近 20 日热力 | 5 分钟 TTL(模块级) |
| GET | `/national-team/holdings/summary?from=2015-01-01` | 总市值趋势(季度×主体) | 无(查库) |
| GET | `/national-team/holdings/changes?period=&vs=&category=&type=` | 季度环比变动明细 | 无 |
| GET | `/national-team/holdings/sector-distribution?from=` | 行业分布时间序列 | 无 |
| GET | `/national-team/holdings/top-holdings?period=&limit=50` | 个股 Top;`?symbol=` 下钻 | 无 |

注册:`main.py` 的 `create_app()` 内 `app.include_router(national_team_router, prefix="/api/v1")`。

### 5.4 回填任务(定时同步)

文件:`backend/src/domain/market/sync/jobs/national_team_backfill.py`

模仿 `sw_index_backfill_all.py`(增量回填模式)。

**策略:断点续传 + 定时增量**:
1. 读 `national_team_backfill_progress.yaml`(记录已完成的 `symbol × report_date` 组合)。
2. 任务启动时:算出「待补齐的 (symbol, quarter) 笛卡尔积」= 成分股池 × {2015Q1…最新季}。
3. 过滤掉已完成的,逐个调 `fetch_top10_float_holders`。
4. 过滤股东名 ∈ 名单 → upsert 到 `national_team_holding`。
5. 每完成一批(如 50 条)更新进度文件,防中断丢失。
6. **每次只跑一段**(如每次最多 1000 个调用),由调度器定期触发(如每日凌晨),多日跑完回填。回填完成后进入「每季报披露季增量更新」模式。

**首次回填预估**:400 股 × 40 季 ≈ 16000 次调用,每次含重试约 2-5 秒,串行约 9-22 小时。分多次定时任务跑,每次 1-2 小时,数日内补齐。进度可断点续传。

调度:接入项目现有调度机制(查 `dev-start.sh` / 现有 cron 配置位置,在实现计划阶段确认具体接入点)。

## 6. 前端详细设计

### 6.1 路由与菜单

- `App.tsx`:`import {NationalTeam} from './pages/NationalTeam';` + `<Route path="/national-team" element={<NationalTeam />} />`(可 `React.lazy` 包裹,与 WriterAssistant 等一致)。
- `Layout.tsx`:Overview 分组「财务报表」(line 40)后插入:
  ```ts
  {path: '/national-team', label: '国家队', icon: Icon.shield}
  ```
  (若无 `Icon.shield`,沿用最接近的现有图标,如 `Icon.analytics`,不新增图标资源)

### 6.2 页面结构 `NationalTeam.tsx` + `NationalTeam.css`

**单页两 Tab**,顶部 Tab 切换(用本地 state,不走路由参数,保持单 URL)。

#### Tab 1: 每日动向(默认)

```
NationalTeam
├── header (标题 + 数据时点 + 口径说明折叠条)
├── tab-bar [每日动向 | 历年持仓]
└── daily-tab
    ├── summary-cards (3 张卡:强护盘数 / 疑似护盘数 / 无信号数)
    ├── heatmap-20d (recharts:近20交易日每日信号强度,小色块/柱状)
    └── signal-table (ETF代码 名称 放量倍数 ETF涨跌 指数涨跌 抗跌 信号强度)
```

- 数据:`GET /daily-signals`
- 组件:复用 Macro.tsx 的 `useEffect + fetch + alive flag` 模式
- 图表:`ResponsiveContainer` + recharts;颜色用 CSS vars(`--color-accent` 等)
- 信号强度样式:`is-up/is-down/is-flat` 风格扩展 `signal-strong/signal-suspect/signal-none`

#### Tab 2: 历年持仓(4 个子视图,页内二级切换)

```
holdings-tab
├── sub-tab-bar [总市值趋势 | 季度变动 | 行业分布 | 个股Top]
├── filter-bar (主体多选下拉:汇金/证金/外管局/社保;全局生效)
└── 当前子视图
    ├── 趋势:ComposedChart 堆叠面积图,X=季度,Y=市值(亿),分主体堆叠
    ├── 变动:筛选(报告期 vs 报告期,类型多选) + 表格
    ├── 行业:堆叠柱状图,X=季度,分行业堆叠
    └── Top:表格(最新季度持仓市值降序) + 点击行 → 弹出该股国家队持仓历史折线(Modal 或下钻区)
```

- 数据:4 个 holdings 端点
- 图表均 recharts,样式遵循项目 CSS var 约定

### 6.3 错误与空状态

- 回填未完成时:「历年持仓」Tab 显示进度条 + 「数据回填中,已覆盖 X/Y 季度」,数据照常展示已回填部分。
- akshare 失败:`/daily-signals` 返回上次缓存或空数组 + 错误提示条,不崩页。

## 7. 实现顺序(给 writing-plans 的输入)

1. **后端持仓持久化层**:表 + repository(仿 macro_indicator)
2. **Provider 方法**:`fetch_top10_float_holders` + `fetch_etf_daily_signal`
3. **回填 job** + 名单/ETF 配置文件
4. **后端 API**:5 个端点 + router 注册
5. **前端骨架**:菜单 + 路由 + 两 Tab 框架
6. **前端 Tab1**(每日动向)
7. **前端 Tab2**(4 子视图)
8. **联调 + 口径说明文案**

## 8. 非目标(本期不做)

- 不做实时分时(盘中)ETF 预警,只做盘后信号。
- 不扫全市场,不做小盘股国家队持仓(沪深300+银行非银已覆盖 95%+)。
- 不做股指期货升贴水、龙虎榜等多信号融合(本期只用 ETF 放量+抗跌)。
- 不做国家队主体名单的自动发现(用配置化名单)。
- 不接入非 akshare 数据源。

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| `stock_gdfx_free_top_10_em` 历史报告期返回不全或不稳 | 用 provider 的 `_retry_all`;回填进度可断点续传;显示数据覆盖度 |
| 社保/证金资管组合后缀多变漏匹配 | 用前缀匹配;名单配置化可快速补 |
| ETF 放量误报(游资放量) | 已用「抗跌」二次过滤;信号分 strong/suspect 两档 |
| 首次回填耗时长 | 分多次定时任务,进度可断点续传,页面渐进展示 |
| 行业归属需额外查询 | 回填时一并落 `national_team_symbol_sector`,查询零额外调用 |
