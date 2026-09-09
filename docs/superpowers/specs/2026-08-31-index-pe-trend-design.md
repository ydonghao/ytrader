# 指数整体法市盈率趋势（宽基 PE + 均值/±σ 参考线）设计

日期：2026-08-31
状态：待评审
参考：用户提供的自研产品截图——弹窗"沪深300市盈率趋势 / 近八年数据"：
蓝色 PE 折线 + 黄色均值虚线 + 红色高估线（均值+标准差）+ 绿色低估线
（均值−标准差），右侧标注当前值。算法为用户自述：成分股业绩转 TTM 汇总、
市值汇总，两者相除得市场整体市盈率，按时间成折线，参考线为窗口内
PE 样本的 mean / mean±σ（常数线，非滚动）。
前置：`2026-08-27-market-cap-growth-design.md`（成分表/财务聚合/市值回填
链路与其设计惯例——本设计的全部数据基础设施来自它）。

## 目标

- 新端点 `GET /financial/index-pe/{code}?years=8` → 整体法 PE 月度序列 +
  窗口统计 `{mean, std, high=mean+σ, low=mean−σ, sample_size}` + 当前值。
- 周度 job 把 PE 算好落库（`index_valuation_daily.pe_ttm`，
  source='computed'），端点只读表——延续"job 入库 + handler 读"惯例。
- 前端：Indices 页新增"市盈率趋势"区块（紧邻 mcg 区块），9 宽基切换
  （默认沪深300）+ 窗口 chips（3y/5y/8y/10y/全部，默认 8y 对齐参考图），
  图表与参考图同构。
- 顺带激活：`index-valuation-percentile?scope=index&metrics=pe_ttm`
  （financial_detail_handler.py:750）读同表 pe_ttm，Indices 页宽基卡
  "PE_TTM 10y 分位徽章"从空数据自动变亮（月度样本 ~120 ≥ SAMPLE_MIN=30），
  该端点零改动。

## 非目标（YAGNI）

- 不做日度 PE——mcg 市值链路为月末粒度（stock_valuation 日线全量拉取
  量级不可控），8 年 96 点折线形态与参考图无实质差别。
- 不做滚动均值/带宽——参考线为窗口内全样本常数线（用户自述算法）。
- 不做 PB/PS/股息率扩展——参考图与算法仅 PE；表列将来要用再说。
- 不做历史成分回溯/公告日对齐——同 mcg 口径：当前成分近似历史
  （幸存者偏差，source='computed'），TTM 净利按报告期 YYYY-MM ≤ 月末
  YYYY-MM 对齐（轻微前视，与 mcg `align_mv` 语义一致，接受）。
- 不做申万行业版 PE——sw 表已有 backfill 调和加权链路（index_valuation_
  backfill.py），口径不同不合并。

## 数据事实（已核实 2026-08-31）

- `index_financial_quarterly`（index_financial.py:26）：scope_type='index'
  分支已有周更数据——`revenue_sum/net_profit_sum`（**亿**，net_profit_sum
  为归母净利和，**累计口径**）+ `sample_count`；
  `get_series(scope_type, scope_code, start=None, end=None)`（:80）。
- `index_valuation_daily`（index_valuation.py:26）：mcg job 周更写入月末
  `total_mv`（亿，80% 覆盖率门控后，source='computed'）；`pe_ttm` 列存在
  但 index 口径**无写入方**（本设计补位）。
  `get_index_range(symbol, start, end)`（:122）、
  `bulk_upsert_index_mv`（:155，现只写 total_mv+source）、
  `delete_index_mv`（:182，删 source='computed' 行，job 删旧重写用）。
- `to_ttm(rows)`（market_cap_growth.py:69）：`TTM = FY_{y-1} + YTD_y −
  YTD_{y-1同期}`，年报期即 TTM，依赖缺失→None 不外推；只喂
  net_profit（revenue 缺省 None）可直接复用。
- `sync_index_market_cap(years=10)`（index_market_cap_sync.py:60）：
  成分 `get_range_batch(monthly=True)` → `_monthly_mv_sum`（元）→
  `_filter_covered`（MIN_COVER_RATIO=0.8）→ 删旧重写；调度挂
  `index_panorama_weekly` 周六链（成分→财务聚合→市值回填），无需改调度。
- 披露率门控先例：mcg handler `_MCG_DISCLOSE_MIN_RATIO=0.8`
  （financial_detail_handler.py:2173，sample_count < 0.8×序列内 max 的期
  净利置 None）；`_mcg_index_names()`（:2180）code→name；
  `_mcg_cached(key, compute)`（:2215）1h 内存缓存。
- 前端：`MarketCapGrowthChart.tsx` ComposedChart + chartTheme 先例；
  `ValuationPercentileChart.tsx` ReferenceLine/ReferenceArea 先例；
  Indices.tsx `MCG_INDICES`（:53）9 指数清单 + segmented 切换先例（:558
  mcg section）。
- 路由遮蔽教训：新路径独立命名 `/index-pe/...`，与既有端点无前缀包含。

## 方案取舍

| 方案 | 结论 |
|---|---|
| A. 周度 job 落库 pe_ttm + 端点读表（本设计） | **采纳**：延续 mcg 惯例；请求轻（读一列）；分位徽章白捡复活；mv 与 pe 同 job 同行写入，删旧重写天然原子 |
| B. handler 实时计算不落库 | 否：每次缓存过期重算 to_ttm+对齐；与 mcg 模式割裂；分位徽章依旧空；门控口径分裂（job vs handler 两套窗口） |
| C. 抓 akshare 现成指数 PE 日线 | 否：那不是用户自述的成分股自汇总算法；引入新外部源；与 mcg 数据链割裂 |

## 后端设计

### 1. 纯函数模块 `src/domain/market/fundamental/index_pe.py`

零 IO、dict 进出、不抛异常（market_cap_growth 同惯例）：

- `gate_by_sample_count(rows, min_ratio=0.8) -> list[dict]`：
  输入 `[{report_date, net_profit, sample_count}]`；以序列内 max(sample_count)
  为满覆盖，不足比例的期 net_profit 置 None（与 mcg handler 同常数同语义，
  常数在本模块定义，handler/job 共用）。
- `compute_index_pe(monthly_mv, cum_rows, min_ratio=0.8) -> list[dict]`：
  `monthly_mv`=[{date, total_mv}]（亿，覆盖率门控后的月末点，与 mcg 落库点
  1:1），`cum_rows` 同上；流程 = 门控 → 映射喂 `to_ttm`（revenue=None）→
  对每个月末点双指针取 `report_date 的 YYYY-MM ≤ 该点 YYYY-MM` 的最近 TTM 期
  → `pe = total_mv / net_profit_ttm`（TTM 缺失或 ≤0 → None）。
  输出 `[{date, pe}]` 升序，与输入月度点一一对应（None 保留，前端断线）。
  单位约定：mv 与净利同单位（亿），PE 无量纲。
- `mean_std(values) -> dict | None`：非数值剔除；样本 <2 → None；
  `statistics.pstdev`（总体标准差，n≈96 时与样本 std 无实质差异）→
  `{mean, std, sample_size}`。

### 2. sync job 扩展（`index_market_cap_sync.py`）

`sync_index_market_cap` 每指数算完过滤后的 `monthly`（元）后：

- `fin_rows = create_index_financial_repository().get_series(
  "index", code, start=start−relativedelta(years=1))`（多取一年做 TTM
  年报基准；财务序列为空 → pe 全 None，mv 照写）。
- `pe_series = compute_index_pe(monthly_亿, fin_rows映射)`。
- bulk 行加 `pe_ttm`（round 2）；返回值与日志补 pe 有效点数。
- 模块 docstring 更新（市值+整体法 PE 双产出）。

### 3. repo 扩展（`index_valuation.py`）

`bulk_upsert_index_mv` 扩为写 `total_mv + pe_ttm + source`（INSERT 列与
DO UPDATE SET 各加一项，docstring 更新）。方法名保留——唯一调用方就是本
job，改名无收益。`delete_index_mv` 不变（同行删，job 内先删后写原子）。

### 4. Handler + 路由（financial_detail_handler.py / financial_router.py）

`index_pe_trend(code, years=8)`（mcg 函数群后新增）：

- code 不在 `_mcg_index_names()` → `responses.fail`（HTTP 200 + code=1，
  惯例同 mcg）。
- `_mcg_cached(f"ipe:{code}:{years}", compute)`。
- compute：`years=0` → 全部（start=date(1990,1,1)，同估值分位"all"惯例）；
  否则 `start = 今天 − relativedelta(years=years)`（锚定请求日，非数据末日，
  简单可预期）→ `get_index_range(code, start, end)` → series；
  `stats = mean_std(非空 pe)` 补 `high/low = mean±std`（round 2）；
  `current` = 最后一个非空点；null 点存在时 `note` 计数说明。

响应：

```json
{ "code": 0, "data": {
    "kind": "index_pe", "code": "000300", "name": "沪深300",
    "as_of": "2026-08-31",
    "series": [{"date": "2018-08-31", "pe": 11.82},
               {"date": "2018-09-28", "pe": null}],
    "stats": {"mean": 12.5, "std": 1.79, "high": 14.29,
              "low": 10.71, "sample_size": 95},
    "current": {"date": "2026-08-28", "pe": 12.34},
    "note": null } }
```

路由：`GET /financial/index-pe/{code}?years=8`（financial_router.py，
market-cap-growth 路由邻近）。

## 前端设计

- `hooks/useIndexPe.ts`：`useIndexPe(code, {years, enabled})` →
  `{data, loading, error}`；`GET /financial/index-pe/{code}?years=`；
  `json.code===0` 判定（useValuationPercentile 同款）。
- `components/IndexPeChart.tsx`（props `{title, subtitle, data, loading,
  error}`）：recharts `ComposedChart`——
  - `Line` PE，蓝 `CHART_COLORS[0]`，`connectNulls={false}`（TTM 断档/
    净利≤0 处断线，不插值误导）；
  - `ReferenceLine`×3 常数线：均值=黄（`#eab308`，组件内常量并注释——
    chartTheme 无黄 token）；高估 mean+σ=`colorUp` 红；低估 mean−σ=
    `colorDown` 绿；均 dashed + 右端数值 label；
  - legend：市盈率/均值/高估线/低估线；右上次新值徽章；
    axisProps/gridProps/tooltipProps 走 chartTheme。
- `pages/Indices.tsx`：mcg section（`indices__mcg`）之后新增
  「市盈率趋势」section——复用 `MCG_INDICES` 9 指数 segmented（默认
  000300）+ 窗口 chips `3y/5y/8y/10y/全部`（默认 8y）；脚注固定口径说明
  （整体法·成分股总市值÷TTM归母净利·月度·当前成分近似）；请求时机与
  mcg 区块一致。

## 错误处理

- job 层：财务序列空 → pe 全 None 照写 mv（图表空态+note 可解释）；单指数
  失败 warning 继续（既有 try/except 不变）。
- handler 层：未配置指数 fail；series 全空 → `series=[], stats=null,
  current=null`（HTTP 200 code=0，前端 StateView empty 非 error）。
- 纯函数层：None 传播（门控期/TTM 依赖断档/净利≤0 → 该点 None）。
- 前端：loading/error/empty 三态；断线不插值。

## 测试（TDD）

- `tests/domain/market/fundamental/test_index_pe.py`：门控期置 None 并
  经 to_ttm 传播到依赖期；TTM 跨年手算（FY+YTD−同期）；对齐拾取（报告期
  YYYY-MM ≤ 月末 YYYY-MM、早于首报告期 → None）；净利≤0 → None；
  `mean_std` 手算/样本<2 → None/非数值剔除。
- `tests/api/test_index_pe.py`：mock 两个 repo → 响应形状（series/stats/
  current/note）；未知 code fail；years=0 全部；null 点 note 计数；
  窗口统计与手算一致；路由注册回归（防遮蔽，mcg 惯例）。
- 既有 `test_market_cap_growth.py` 不回归（bulk_upsert_index_mv 加列，
  确认 mock 断言不受影响）。

## 验证

- 新增测试全绿（跑子集——全量回归有既有失败，见项目记忆）。
- 冒烟：手动跑 `sync_index_market_cap(10)` → `curl
  /financial/index-pe/000300|000905|000852` 三指数返回合理 PE 区间
  （沪深300 约 10~15 量级，与中证官网口径肉眼对照）；
  `index-valuation-percentile?scope=index&code=000300&metrics=pe_ttm`
  徽章非空。
- `pnpm -F web build` EXIT=0；浏览器目检 Indices 页新区块与参考图同构
  （蓝折线+黄均值+红/绿±σ虚线+窗口 chips）。

## 预估

纯函数 ~110 行；job+repo 改动 ~80 行；handler+路由 ~110 行；前端
hook+Chart+挂载 ~260 行；测试 ~260 行。约 1 个工作日。
