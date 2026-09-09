# 申万行业截面基础设施（SW Industry Cross-Section）设计

日期：2026-08-18
状态：待评审
关联：`2026-08-18-ratio-analysis-design.md` 明确将"同行批量取数基础设施"留给独立立项——本设计即该项目。它是"波特五力个股分析"两阶段规划的**子项目1**（子项目2 = 五力评分模块 + 前端 Tab，消费本项目的端点，另开 spec）。

## 目标

- 新表 `sw_industry_member`：全市场申万一级/二级行业成分股快照（含权重、计入日期）。
- 新表 `sw_industry_cross_section`：行业截面指标**按报告期预计算落表**——
  集中度（CR4/CR8/HHI，营收口径）、盈利分布（毛利率/净利率/ROE 的
  mean/median/std/p25/p75）、行业营收与净利总和、行业营收同比。
- 计算范围：2016 年以来全部年报期 + 最近 8 个季度（去重后约 13~16 期/行业，
  131 个二级 + 31 个一级 ≈ 2×1700 行）。**历史截面可回溯**是本方案核心价值
  （支撑五力"竞争格局演变"趋势，如 CR4 五年走势）。
- 两个 API 端点：个股行业归属查询、个股→同行截面（时序 + 同行明细 + 目标股
  相对位置），供子项目2 五力 Tab 与未来选股器消费。

## 非目标（YAGNI）

- 不做三级行业（成分股常 <10 只，截面统计失义，akshare 三级接口稳定性未验证）。
- 不做前端可视化——留给子项目2 五力 Tab 一起做，避免基础设施无消费方空转。
- 不做五力评分逻辑——子项目2 基于本项目原始截面数据计算。
- 不做市值口径集中度——只做营收口径（市值口径需联动 stock_valuation 日频快照，出现消费方再加）。
- 不做成分股调入调出的历史变迁审计——只存最新快照（included_date 字段保留 akshare 给的计入日期）。
- 不做实时聚合路径——已选全预计算方案，akshare 不进请求路径。

## 数据事实（已实测 2026-08-18）

- `ak.sw_index_first_info()`：31 个一级行业。列：行业代码(`801010.SI`)/行业名称/
  成份个数/静态市盈率/TTM市盈率/市净率/静态股息率。
- `ak.sw_index_second_info()`：131 个二级行业，**自带"上级行业"列**（一级归属
  映射内置，无需单独拉一级成分，消除两来源不一致）。
- `ak.index_component_sw('801120')`：实测返回 122 只成分股。列：序号/证券代码
  (纯6位)/证券名称/最新权重/计入日期。
  （执行期真跑修正的映射：**801120 = 食品饮料（一级）**，801125 = 白酒Ⅱ
  （二级）——成分 122 只即食品饮料一级口径；本设计全链路数据驱动、不硬编码
  行业代码，故无需改代码。）
- 成分股财务覆盖率：122 只中 112 只（92%）在 `stock_financial_detail` 有数据，
  未覆盖的疑似北交所/次新股。
- `stock_financial_detail`：40.5 万行 income，毛利率列覆盖 75%、营收 77%；
  PK `(symbol, report_date, statement_type)`。
- **ROE 非固定列**（`roe` 属于 forecast 模型；income detail JSONB 实测亦无
  净资产收益率科目）→ 取数路径 = income 行 `net_profit` ⋈ balance 行 `equity`
  同报告期 JOIN，`roe = net_profit / equity × 100`（报告期累计未年化、
  全口径非归母，与 index_financial_sync 口径一致）。
- 按成分股过滤 + 聚合单报告期截面实测 **3ms**——明细拉取（数万行）轻量。
- 现有 `index_financial_quarterly` 的 `scope_code` 不带 `.SI` 后缀（如
  `801010`），新表保持一致（akshare 返回的 `801016.SI` 入库前剥后缀）。
- symbol 前缀规则（项目既有惯例）：`6*`→`sh`、`0*/3*`→`sz`、`4*/8*`→`bj`。

## 方案取舍

| 方案 | 结论 |
|---|---|
| A. 成分股落表 + 截面实时 SQL 聚合 | 否：查询毫秒级本可行，但**历史截面不可回溯**——五力要答"格局从混战走向集中"（课程14集宁德时代案例）必须逐历史期截面 |
| B. 运行时拉 akshare 成分股 + 缓存 | 否：akshare 依赖进请求路径；无快照可审计 |
| C. 成分股 + 截面指标**全预计算落表** | **采纳**：查询最快、任意历史期截面可回溯、财务回填后全量重算自动修正；代价是同步链路最长，但聚合实测毫秒级，全量重算约分钟级，可接受 |

## 后端设计

### 1. 表 DDL（两张，随 repo 模块建表，参照 `financial_full.py` 惰性建表惯例）

```sql
CREATE TABLE IF NOT EXISTS sw_industry_member (
    symbol        VARCHAR(16) NOT NULL,   -- sh600519（前缀规则见数据事实）
    code          VARCHAR(12) NOT NULL,   -- 纯6位
    name          VARCHAR(32),
    sw_code_l1    VARCHAR(12) NOT NULL,   -- '801080' 不带 .SI
    sw_name_l1    VARCHAR(32) NOT NULL,
    sw_code_l2    VARCHAR(12) NOT NULL,   -- '801120'
    sw_name_l2    VARCHAR(32) NOT NULL,
    weight        NUMERIC,                -- akshare 最新权重%
    included_date DATE,
    synced_at     TIMESTAMP DEFAULT now(),
    PRIMARY KEY (symbol, sw_code_l2)      -- 防御 akshare 偶发重复归属
);
CREATE INDEX IF NOT EXISTS idx_sw_member_l1 ON sw_industry_member(sw_code_l1);
CREATE INDEX IF NOT EXISTS idx_sw_member_l2 ON sw_industry_member(sw_code_l2);

CREATE TABLE IF NOT EXISTS sw_industry_cross_section (
    level          SMALLINT NOT NULL,     -- 1=一级 2=二级
    sw_code        VARCHAR(12) NOT NULL,
    sw_name        VARCHAR(32) NOT NULL,
    report_date    DATE NOT NULL,
    sample_count   INT,                   -- 该期有营收数据的成分股数
    revenue_sum    NUMERIC,               -- 元（不转亿，前端格式化，与 detail 惯例一致）
    net_profit_sum NUMERIC,
    cr4            NUMERIC,               -- 营收口径 0~1（前4大营收/总营收）
    cr8            NUMERIC,
    hhi            NUMERIC,               -- 0~10000（营收份额平方和×10000）
    revenue_yoy    NUMERIC,               -- 去年同期行业营收和同比-1；去年同期缺失→NULL
    distribution   JSONB,                 -- 见下方结构
    updated_at     TIMESTAMP DEFAULT now(),
    PRIMARY KEY (sw_code, report_date)
);
CREATE INDEX IF NOT EXISTS idx_sw_xs_level ON sw_industry_cross_section(level);
```

`distribution` JSONB 结构（加指标不改表）：

```json
{"gross_margin": {"mean": null, "median": null, "std": null, "p25": null, "p75": null},
 "net_margin": {"...": "同上"}, "roe": {"...": "同上"}}
```

口径约定：
- **样本剔除**：某指标为 None 的成分股从该指标分布中剔除，但保留在营收/集中度
  统计中（前提是其 revenue 非 None）；revenue 为 None 的行整个不进本期截面。
- **样本下限**：`sample_count < 4` → cr4/cr8/hhi/distribution 全 None（statistics
  下限防微小样本噪声），sample_count 照实存。
- **报告期集合**：`DISTINCT report_date` 中满足 `report_date >= '2016-01-01'` 且
  （12月31日年报 或 最近 8 个季度内，SQL 以 `report_date >= now() - interval
  '28 months'` 近似实现）的日期。
- **一级成分口径**：某一级的成分 = 其名下全部二级成分的**并集**（由 second_info
  上级行业列推导），与申万官方一级成分可能有个股级微小出入——已知口径差，接受。
- **revenue_yoy**：`当期revenue_sum / 去年同日report_date的revenue_sum - 1`；
  去年同期不在表中（2016 首年、季度期回溯不足）→ NULL。分母≤0 → NULL。

### 2. 纯函数模块 `src/domain/market/fundamental/industry_cross_section.py`

dict 进 dict 出、不读 DB、不发 HTTP、不抛异常（沿 fundamental 模块惯例，
docstring 引课程 14 集五力方法论为下游背景）：

```python
def cross_section_metrics(peers: list[dict]) -> dict:
    """单期截面。peers=[{symbol, revenue, net_profit, gross_margin,
    net_margin, roe}]（revenue None 的行应先行剔除）。
    返回 {sample_count, revenue_sum, net_profit_sum, cr4, cr8, hhi,
    distribution}。"""

def attach_yoy(sections: list[dict]) -> list[dict]:
    """sections 为同一行业按 report_date 升序的单期指标行（含 revenue_sum），
    就地补 revenue_yoy（同比期匹配不上或基数≤0 → None）。"""

def peer_ranks(peers: list[dict], target_symbol: str) -> dict:
    """最新期同行明细的排名与目标股位置：每行补 rank_revenue（营收降序名次）、
    rank_gross_margin；返回 {peers(含rank), target: {percentile_revenue,
    percentile_gross_margin, percentile_roe, revenue_share(市占率代理)}}。
    分位 = 值≥该股的样本数（含自身）/ 该指标有效样本数；指标 None 不参与
    该指标排名与分位。"""
```

工具复用：`_div`/`_r4` 语义本地实现（不 import ratio_analysis，模块间零耦合）。
分布统计用标准库 `statistics`（mean/median/stdev/quantiles）。

### 3. 同步 job（`src/domain/market/sync/jobs/`，镜像 `financial_full_sync` 组织）

**job1 `sw_industry_member_sync.py`**（约 120 行）：
- `sw_index_second_info()` 取 131 个二级（行业代码/名称/上级行业）→ 逐个
  `index_component_sw(code去.SI)`（0.3s 间隔防限流）→ 前缀转换 → 汇总。
- 单行业失败：记录跳过，收尾输出失败清单（全量清空重灌天然幂等，下轮补齐）。
- 写入：`DELETE 全表` + 批量 INSERT（约 5400 行）。

**job2 `sw_industry_cross_section_sync.py`**（约 150 行）：
- 读 member 表 → 一次 SQL JOIN 拉明细：`member × stock_financial_detail
  (income, 报告期集合内)` 数万行 `[{symbol, sw_code_l1, sw_code_l2,
  report_date, revenue, net_profit, gross_margin, net_margin, roe}]`。
- Python 侧按 `(level, sw_code, report_date)` 分组 → `cross_section_metrics`
  → 按行业时序 `attach_yoy` → `INSERT ... ON CONFLICT (sw_code, report_date)
  DO UPDATE` 全量重算 upsert（财务回填后重跑即修正）。
- 期间进度日志（ProgressTracker 既有模式）。

触发：与 financial_full_sync 相同的手动触发入口；频率建议周级（成分变更低频）。

### 4. 仓库层 `src/infra/database/market/sw_industry.py`

`create_sw_industry_repository()`（psycopg2 + `get_dsn()`，沿 market 目录惯例）：

- `upsert_members(rows)` / `replace_all_members(rows)`（job1 用）
- `fetch_members()`（job2 用，全量）
- `get_member(symbol) -> dict|None`（端点：个股归属）
- `fetch_sections(sw_codes, level) -> list[dict]`（端点：截面时序）
- `upsert_sections(rows)`（job2 用）
- `fetch_peer_details(sw_code, level, report_date) -> list[dict]`（端点：同行
  明细——member JOIN stock_financial_detail 最新期，实时查，3ms 级；revenue
  为 None 的行不返回——与纯函数层剔除口径一致）

### 5. Handler + 路由

`financial_detail_handler.py` 尾部新增两个函数，`financial_router.py` 注册
（已核对现有 31 条 /financial 路径零冲突——遮蔽教训 b661566）：

```python
def industry_members(symbol: str) -> Any
# GET /financial/industry-members/{symbol}
# → success({symbol, sw_l1:{code,name}, sw_l2:{code,name}, weight, included_date})
#   无归属（港股/美股/未覆盖）→ error("该股无申万行业归属")

def industry_peers(symbol: str, level: int = 2, limit: int = 13) -> Any
# GET /financial/industry-peers/{symbol}?level=2&limit=13
```

`industry_peers` 流程：`get_member(symbol)` → 无归属 error；查截面时序
（level 默认 2，`sample_count < 8` 自动降一级并在响应标注）；截面最新期
`fetch_peer_details` → `peer_ranks(peers, symbol)`；返回：

```json
{"symbol": "sh600519",
 "industry": {"level": 2, "code": "801120", "name": "白酒II",
              "parent": {"code": "801080", "name": "..."},
              "degraded": false, "note": "二级样本不足已降一级"},
 "sections": [{"report_date": "2025-12-31", "sample_count": 112,
               "revenue_sum": 9.5e12, "cr4": 0.52, "cr8": 0.71, "hhi": 980.2,
               "revenue_yoy": 0.08, "distribution": {"gross_margin": {"..."}}}],
 "peers": [{"symbol": "sh600519", "name": "贵州茅台", "revenue": 1.7e11,
            "gross_margin": 91.6, "rank_revenue": 1, "rank_gross_margin": 2}],
 "target": {"percentile_gross_margin": 0.98, "percentile_roe": 0.95,
            "revenue_share": 0.178}}
```

sections 降序、`[:limit]`；目标股有归属但最新期财务缺失（不在 peers 明细中）
→ 正常返回截面与同行明细，target 为 None 并加 note（次新股财务未回填时出现，
子项目2 需容忍此形态）。

### 6. 路由注册回归测试

两路径存在且各仅注册一次、与 legacy 端点互异（`test_ratios.py:106` 模式）。

## 错误处理

- 纯函数层：全除法 `_div` 守卫；样本 <4/指标全 None → 对应统计 None；
  peers 空列表 → 全 None 指标行（不抛异常）。
- job 层：akshare 单行业失败跳过+清单汇总；SQL 失败整体中止报错（幂等可重跑）。
- Handler 层：repo 异常 → `responses.error`；无行业归属 → error 明确文案；
  截面表空（job 未跑）→ error 提示"行业截面数据未同步"。
- 前端（子项目2）消费守卫：`sections?.length`/`peers?.length` 纵深防御。

## 测试（TDD）

- `tests/domain/market/fundamental/test_industry_cross_section.py`（模式抄
  `test_ratio_analysis.py`，dict 字面量 + pytest.approx）：
  CR4/CR8/HHI 手算对照；分布 mean/median/p25/p75；指标 None 剔除但保留营收；
  样本 <4 全 None；`attach_yoy` 同比匹配/首期 None/基数≤0；`peer_ranks` 并列、
  目标股成分外、分位口径。
- `tests/api/test_industry_peers.py`（模式抄 `test_ratios.py`）：
  MagicMock + `patch create_sw_industry_repository`；归属缺失 error；
  二级样本不足降级 degraded=true；sections 截 limit；路由注册回归。
- job 转换逻辑单测：mock 小 DataFrame——`.SI` 剥离、前缀转换、上级行业映射、
  失败行业跳过汇总。

## 验证

- `uv run pytest tests/domain/market/fundamental/test_industry_cross_section.py tests/api/test_industry_peers.py -q`（注意既有全量回归存在 52 处失败，只看新增子集）。
- 真跑 job1：member 表约 5400 行、131 个二级行业全覆盖、无 sh/sz 前缀错位
  （抽查茅台 sh600519 → 白酒II）。
- 真跑 job2：茅台 peers——CR4（白酒前4大营收份额应 >0.5）、毛利率分位
  应 >0.9、revenue_share 与直觉相符（约 0.15~0.2）；截面含 2016-2025 年报期。
- 冒烟：`curl /financial/industry-peers/sh600519` 返回四块结构完整。

## 预估

DDL+repo ~160 行；job1 ~120 行 + job2 ~150 行；纯函数 ~180 行；handler ~150 行
+ 路由 ~20 行；测试 ~400 行。合计约 1200 行、两个工作日内（akshare 131 次调用
约 2~3 分钟为唯一慢环节）。
