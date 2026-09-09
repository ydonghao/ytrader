# 宏观经济数据月度同步 — 设计文档

> 日期：2026-07-23
> 状态：待评审
> 范围：每月定时用 akshare 拉取 20 项宏观经济指标入库；下载《产业结构调整指导目录（2024年本）》PDF 存档。

## 1. 背景与目标

项目已有每周六 04:00 的 `macro_sync` job，但当前只覆盖 10 个指标（CPI/PPI/PMI/M2/社融/LPR + 美国 4 项）。用户需要扩展到 **20 项**覆盖就业/收入/存款/地产/人口/工业/贸易/货币政策的完整宏观图景，并按月定时拉取。

**目标**：
1. 用 akshare 自动拉取其支持的指标（约 11 项稳定可用）
2. akshare 缺失的指标（约 9 项）通过 CSV 种子数据补齐历史，保证 20 项齐全
3. 每月 1 日定时执行
4. 下载《产业结构调整指导目录（2024年本）》PDF 存档到 `docs/`

## 2. 指标清单与数据源映射（地基）

实测 akshare 1.18.50，按可用性分三档：

### A. akshare 稳定可用（11 项）— 自动月度拉取

| code | 指标 | akshare 接口 | freq | unit | group |
|---|---|---|---|---|---|
| `cn_cpi_yoy` | CPI 同比（总） | `macro_china_cpi` | month | % | inflation |
| `cn_ppi_yoy` | PPI 同比 | `macro_china_ppi` | month | % | inflation |
| `cn_pmi` | 制造业 PMI | `macro_china_pmi` | month | | growth |
| `cn_m1_yoy` | M1 同比 | `macro_china_money_supply` | month | % | monetary |
| `cn_m2_yoy` | M2 同比 | `macro_china_money_supply` | month | % | monetary |
| `cn_lpr_1y` | 1 年期 LPR | `macro_china_lpr` | day | % | monetary |
| `cn_sf` | 社融增量 | `macro_china_shrzgm` | month | 亿元 | monetary |
| `cn_retail_yoy` | 社零同比 | `macro_china_consumer_goods_retail` | month | % | growth |
| `cn_house_sales_amt` | 商品房销售额（累计） | `macro_china_hk_building_amount` | month | 亿元 | realestate |
| `cn_house_sales_area` | 商品房销售面积（累计） | `macro_china_hk_building_volume` | month | 万平 | realestate |
| `cn_industrial_yoy` | 规上工业增加值同比 | `macro_china_industrial_production_yoy` | month | % | growth |

社融结构分项（人民币贷款/委托贷款/信托贷款/未贴现银承/企业债券/股票融资）随 `macro_china_shrzgm` 一起拉取，拆成多个 `cn_sf_*` 子 code 入库，复用同一接口。政府债券分项 akshare 无，走 CSV（见 C 档）。

### B. akshare 接口存在但数据停更（2 项）— 种子 + 尽力增量

| code | 指标 | 接口 | 问题 |
|---|---|---|---|
| `cn_fai_yoy` | 固定资产投资增速 | `macro_china_gdzctz` | 数据停在 2012-04 |
| `cn_realestate_inv_yoy` | 房地产开发投资增速 | `macro_china_gdzctz`（同源，不同列） | 数据停在 2012-04 |

注：两者口径不同（固投是全行业，开发投资是地产子项），各占一个 code。处理：CSV 种子提供 2013 至今的历史值；job 仍调接口做增量（有新数据则覆盖，无则不动）。

### C. akshare 完全没有（11 个 code）— 纯 CSV 种子

| code | 指标 | 数据来源（CSV） |
|---|---|---|
| `cn_unemp_1624` | 16-24 岁城镇调查失业率 | 国家统计局月度数据，手工整理 |
| `cn_unemp_2529` | 25-29 岁城镇调查失业率 | 国家统计局月度数据，手工整理 |
| `cn_disp_income_median_yoy` | 居民可支配收入中位数同比 | 国家统计局季度公报 |
| `cn_birth` | 新生人口（年度） | 国家统计年鉴 |
| `cn_industrial_profit_yoy` | 规上工业企业利润同比 | 国家统计局月度数据 |
| `cn_trade_us_amt` | 对美进出口金额 | 海关总署月度数据 |
| `cn_cpi_food` | CPI 食品烟酒类指数 | 国家统计局（NBS 直连当前 IP 级 403，CSV 补） |
| `cn_cpi_consumer` | CPI 消费品类指数 | 国家统计局（同上） |
| `cn_sf_govbond` | 社融-政府债券融资 | 央行《社会融资规模增量统计表》（akshare 社融接口无此分项） |
| `cn_loan_household` | 金融机构-住户贷款增量 | 央行《金融机构信贷收支表》（akshare 无住户/企业贷款拆分） |
| `cn_loan_enterprise` | 金融机构-企(事)业贷款增量 | 央行《金融机构信贷收支表》（同上） |

**社融结构说明**：用户要"政府债券融资、居民和企业融资"，但 `macro_china_shrzgm` 只提供贷款类 7 个分项（人民币贷款/委托/信托/未贴现银承/企业债券/股票融资），**无政府债券、无居民/企业贷款拆分**。处理：
- 贷款类 7 分项：随 akshare 接口自动拉取入库（`cn_sf_rmb_loan` / `cn_sf_entrust_loan` / `cn_sf_trust_loan` / `cn_sf_undiscounted_ba` / `cn_sf_corp_bond` / `cn_sf_equity`）
- 政府债券 (`cn_sf_govbond`)：走 CSV 种子，来源央行《社会融资规模增量统计表》
- 居民/企业融资拆分 (`cn_loan_household` / `cn_loan_enterprise`)：走 CSV 种子，来源央行《金融机构信贷收支表》中的"住户贷款"和"企(事)业单位贷款"分项。这是信贷收支表口径，与社融口径略有差异（社融是流量增量，信贷收支表是存量余额），CSV 中取增量值对齐。

**存款占比**：`macro_china_supply_of_money` 提供"活期存款/定期存款/储蓄存款"绝对值，派生两个占比指标：
- `cn_deposit_demand_ratio` = 活期 / (活期+定期+储蓄+其他)
- `cn_deposit_term_ratio` = 定期 / 同分母

派生逻辑在 provider 的 `pick` 函数里完成，不单独拉接口。

**美联储利率影响**：存两项原始数据，用户自看相关性，不算派生指标：
- `us_fed_funds_rate`（美国联邦基金目标利率，akshare `macro_usa_*` 系列或 fred）
- `USDCNY` 汇率已由 `quant_daily` 同步，不重复

## 3. 架构设计（方案 A：扩展 macro_sync）

### 3.1 改动点总览

```
backend/
├── conf/config.yaml                          # 追加 ~15 条指标元数据到 macro_universe.indicators
├── src/domain/market/sync/providers/
│   └── akshare_provider.py                   # _MACRO_EXTRACTORS 注册表新增 ~15 条提取器
├── src/domain/market/sync/jobs/
│   └── macro_monthly.py                      # 【新】月度同步 job（含 CSV 种子导入）
├── src/infra/scheduler.py                    # 新增"每月 1 日 04:30"cron
├── scripts/seed/macro/                       # 【新】CSV 种子数据目录
│   ├── README.md                             # 各 CSV 的来源、口径、更新方法
│   ├── cn_unemp.csv                          # 含 16-24 / 25-29 两列
│   ├── cn_disp_income.csv
│   ├── cn_birth.csv
│   ├── cn_industrial_profit.csv
│   ├── cn_trade_us.csv
│   ├── cn_cpi_classified.csv                 # 食品烟酒 + 消费品
│   ├── cn_sf_govbond.csv
│   ├── cn_loan_split.csv                     # 住户贷款 + 企事业贷款两列
│   ├── cn_fai.csv                            # 固投 + 地产开发投资两列
docs/
└── 产业结构调整指导目录-2024年本.pdf          # 【新】发改委官方 PDF 存档
```

### 3.2 Provider 扩展（`_MACRO_EXTRACTORS` 注册表）

现有注册表是 `{code: {fn, pick, freq, unit}}` 字典。新增条目遵循同样格式。关键提取器：

```python
# 示例：M1 同比（与现有 M2 同接口不同列）
"cn_m1_yoy": {
    "fn": lambda: ak.macro_china_money_supply(),
    "pick": lambda r: (
        AkshareProvider._parse_cn_month(r.get("月份")),
        _num(r.get("货币(M1)-同比增长")),
    ),
    "freq": "month", "unit": "%",
},
# 示例：商品房销售额（macro_china_hk_building_amount，英为财情 4 列格式）
"cn_house_sales_amt": {
    "fn": lambda: ak.macro_china_hk_building_amount(),
    "pick": lambda r: (
        _parse_iso_date(r.get("发布日期")),   # 或时间列
        _num(r.get("现值")),
    ),
    "freq": "month", "unit": "亿元",
},
```

**倒序陷阱**：多个接口返回时间倒序，`fetch_macro_series` 末尾已有 `out.sort(key=lambda x: x[0])` 统一升序，新提取器自动受益。

**派生指标（存款占比）**：`cn_deposit_demand_ratio` / `cn_deposit_term_ratio` 无法用单行 pick 表达，用专门的 `fetch_macro_derived(code)` 方法处理，内部拉一次 `macro_china_supply_of_money` 后按月计算占比序列。

### 3.3 CSV 种子导入（`macro_monthly.py`）

```python
def _seed_from_csv(repo, csv_path: Path, code: str, unit: str, freq: str, source: str):
    """从 CSV 导入历史时序种子。CSV 格式：report_date,value 两列。
    幂等：与 akshare 数据共用 (code, report_date) 主键 upsert。
    仅当该 code 在库中无数据或 CSV 有更新日期时写入。"""
```

种子导入在 job 首次运行时执行一次，后续按 CSV 文件的 mtime 判断是否需要重新导入（CSV 更新了才重跑）。

### 3.4 月度 Job 流程

```
macro_monthly.run()
  ├─ 1. akshare 指标同步（遍历 A 档 + B 档 code 列表）
  │     复用 AkshareProvider.fetch_macro_series + repo.upsert
  ├─ 2. 社融结构分项拆解（cn_sf → cn_sf_loans / cn_sf_trust / ...）
  ├─ 3. 派生指标计算（存款占比）
  ├─ 4. CSV 种子导入（C 档 + B 档历史补齐）
  └─ 5. 元数据刷新（复用 _sync_indicator_meta）
```

### 3.5 调度

在 `scheduler.py` 的 `setup_scheduler()` 末尾追加：

```python
def _run_macro_monthly():
    from src.domain.market.sync.jobs.macro_monthly import run as _run
    try:
        _run()
    except Exception as e:
        log.error("[MACRO_MONTHLY] failed: %s", e)

sched.add_job(
    _run_macro_monthly,
    CronTrigger(day=1, hour=4, minute=30, timezone="Asia/Shanghai"),
    id="macro_monthly",
    name="宏观经济数据月度同步",
    replace_existing=True,
    misfire_grace_time=86400,   # 容许跨天补跑
    max_instances=1,
    coalesce=True,
)
```

与现有周六 04:00 `macro_sync` 错开（月度在月初工作日，周度在周六），无冲突。

## 4. 数据模型

**不新增表**。全部复用现有：
- `macro_indicator`（indicator_code, report_date, value, freq, unit, source, source_url, provider）
- `macro_indicator_meta`（code, name, ...展示属性）

CSV 种子数据写入时 `source="国家统计局/海关总署"`, `provider="csv_seed"`, `source_url` 填具体公报页面，与 akshare 数据可区分溯源。

## 5. 错误处理

- 单个指标拉取失败：`try/except` 记日志，`stats[code] = -1`，不阻塞其他指标（沿用现有 `_sync_indicators` 模式）
- akshare 接口返回空：记 warning，跳过，种子数据不受影响
- CSV 文件缺失：记 warning，跳过该 code 的种子导入
- 整个 job 失败：scheduler 层捕获，`misfire_grace_time=86400` 保证次月仍能跑

## 6. 《产业结构调整指导目录（2024年本）》

- 下载发改委官方 PDF：`https://www.ndrc.gov.cn/xxgk/zcfb/fzggwl/202312/P020231229700886191069.pdf`
- 存到 `docs/产业结构调整指导目录-2024年本.pdf`
- 不解析、不入库、不写代码，仅存档（用户明确要求"只存 PDF 原文"）

## 7. 测试策略

- **Provider 提取器单元测试**：每个新 `pick` 函数用 mock DataFrame 行测试，验证日期解析 + 数值提取
- **CSV 种子导入测试**：用临时 CSV 验证 upsert 幂等性
- **Job 集成测试**：mock `AkshareProvider.fetch_macro_series`，验证 `macro_monthly.run()` 的 stats 返回值结构
- **调度注册测试**：验证 `setup_scheduler()` 后 `macro_monthly` job 存在且 trigger 正确

## 8. 不做的事（YAGNI）

- ❌ 不写 NBS 反爬客户端（当前 IP 级 403，投入产出比极低）
- ❌ 不解析产业结构目录 PDF（用户只要原文）
- ❌ 不新建独立 provider/模块（复用现有 AkshareProvider）
- ❌ 不算"美联储加息对汇率影响"的派生指标（存原始数据，用户自看）
- ❌ 不做前端改动（现有 macro_handler / 仪表盘自动读新指标）
