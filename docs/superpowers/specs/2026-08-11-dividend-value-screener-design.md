# 红利低估值选股 + 通用下钻 — 设计文档

**日期**: 2026-08-11
**状态**: 待评审
**作者**: brainstorming session 产物

---

## 1. 背景与动机

现有选股器 `/screener` 已有 `dividend`（红利）模式，但它是"半成品"：
- 股息率缺失时**退化用 PB 倒数兜底**，并非真正的"红利"选股。
- 估值只做**横截面**比较（今天 5000 只之间谁更便宜），不反映"相对自己历史有多便宜"。
- 选股结果表**行不可点击**，没有任何下钻能力。

用户需求：新增一个**真正的"红利低估值"**选股策略，把"红利"和"低估"作为两个并列因子，且"低估"采用**时间序列分位**口径（相对自身历史），并支持**全市场通用的炒作区间剔除**；同时给所有选股模式补上**通用下钻**（点任意行看个股详情）。

---

## 2. 范围总览

| 模块 | 改动 | 新/改 |
|---|---|---|
| 新选股模式 `dividend_value` | 双因子：股息率（横截面）+ 低估分位（横截面，源自时间序列） | 新增 |
| 批量个股分位服务 | 给选股用，5000 只一次算完 | **新增（关键）** |
| 区间剔除 — 全局 | UI 可编辑 + 持久化 config，选股时统一应用 | 新增 |
| 区间剔除 — 单只 | 下钻页日期输入框，重算分位 | 新增 |
| 通用下钻 Modal | 所有模式行可点击；5 区块：画像/估值分位/财务趋势/K线+股息率/入选拆解 | 新增 |
| 单股分位接口扩展 | `/financial/valuation-percentile/{symbol}` 加 `exclude` 参数 | 改 |

**关键洞察**：把"低估"从"今天市场里谁便宜"（横截面）升级成"相对自己历史有多便宜"（时间序列分位）。现有选股器只有横截面排名，没有时间序列分位能力，且没有批量个股分位接口——这两块是本次最大的后端新增。

---

## 3. 选股模式：`dividend_value`

### 3.1 双因子定义

- **红利因子** = 股息率 `dv_ttm`（必须有真实值，**不再用 PB 倒数兜底**）
- **低估因子** = 当前估值在历史中的分位（0~1，越低越便宜）
  - 估值指标**前端可切换**：`PB` / `PE_TTM` / `PB+PE`
  - 时间窗口**前端可切换**：`10y` / `20y`
  - 选 `PB`：当前 PB 在历史 PB 序列的分位
  - 选 `PE_TTM`：当前 PE_TTM 在历史 PE_TTM 序列的分位
  - 选 `PB+PE`：**双分位等权平均** `(PB分位 + PE分位) / 2`（两者量纲一致，均在 0~1，可直接平均）

### 3.2 硬门槛（前端可覆盖，默认值）

- 股息率 `dy_min ≥ 3%`
- `pb ≤ 3` 且 `pe_ttm > 0 且 ≤ 60`（安全阀，防亏损/周期顶）
- `roe ≥ 8%`、`debt_ratio ≤ 70%`（质量底线，防价值陷阱）
- 分位样本数 ≥ 30（次新股样本不足直接淘汰）

### 3.3 排名

- 股息率排名（全市场，降序，越高越好）
- 低估分位排名（全市场，升序，越低越便宜）
- 两者名次相加，取 top_n（复用现有 `_finalize` 双排名机制）

### 3.4 ScreenItem 扩展

新增可选 `factor_breakdown` 字段，供下钻"入选拆解"区块用：
```jsonc
{
  "dy_value": 5.2, "dy_rank": 3,
  "value_metric": "pb",         // pb | pe_ttm | pb_pe
  "value_window": "10y",         // 10y | 20y
  "value_percentile": 0.15,
  "value_percentile_pe": null,   // pb_pe 模式下非空
  "value_rank": 5,
  "exclude_applied": [["2015-06-15","2015-12-31"]]  // 本次选股应用的全局剔除区间
}
```

---

## 4. 后端：批量个股分位 + 区间剔除

这是本次最大块的新增。现有 `StockValuationRepository.get_range` 是单符号的，跑 5000 只要 5000 次查询，不可接受。

### 4.1 新增仓库方法 `get_range_batch`

位置：`backend/src/infra/database/market/valuation.py`

```python
def get_range_batch(
    self,
    symbols: list[str],
    start: date,
    end: date,
    exclude_ranges: list[tuple[date, date]] | None = None,
    monthly: bool = True,
) -> dict[str, list[StockValuation]]:
    """
    批量拉多符号历史估值，SQL 层按月降采样（每月留最后交易日）。
    exclude_ranges 下推成 NOT (trade_date BETWEEN x AND y) 子句。
    返回 {symbol: [StockValuation, ...]}（每符号按日期升序）。
    """
```

- 月降采样用 `DISTINCT ON (symbol, date_trunc('month', trade_date))` + `ORDER BY ... trade_date DESC` 取月内最后一天
- 规模：5000 符号 × 10 年 ≈ 60 万行（可接受），避免 1250 万行全量
- `exclude_ranges` 在 SQL `WHERE` 层就过滤掉，减少回传

### 4.2 新增服务 `stock_percentile_batch`

位置：`backend/src/domain/market/fundamental/percentile_batch.py`（新文件）

```python
def stock_percentile_batch(
    symbols: list[str],
    metric: str,           # "pb" | "pe_ttm" | "pb_pe"
    window: str,           # "10y" | "20y"
    as_of: date,
    exclude_ranges: list[tuple[date, date]] | None = None,
) -> dict[str, dict]:
    """
    返回 {symbol: {percentile, sample_size, current,
                   pb_percentile?, pe_percentile?}}  # 复合模式带子项
    样本不足(<30)/负值自动跳过。metric="pb_pe" 时算 PB、PE 分位再等权平均。
    """
```

复用 `calc_percentile`（已有）。复合 `pb_pe` 在这层做：分别算 PB、PE 分位再等权平均。

### 4.3 单股接口扩展

`GET /financial/valuation-percentile/{symbol}` 增加 `exclude` 查询参数：

```
?exclude=2020-06-01~2021-02-28,2015-06-15~2015-12-31
```

- 在 `percentile_stats` 之前过滤样本
- **同时过滤分位统计和返回的 history series**，让图表也同步剔除
- 全局剔除区间在此接口也**默认带上**（用户可叠加单只手动区间）
- 改动点：`financial_router.py` 路由加 Query 参数；`financial_detail_handler.py` 的 `valuation_percentile` 解析区间并过滤

### 4.4 全局剔除区间 — UI 可编辑 + 持久化

- **配置**：`config.yaml` 新增 `screener.dividend_value.exclude_ranges`，启动时加载
- **运行时可改**：新增接口 `GET/PUT /screener/exclude-ranges`，PUT 时更新内存配置 + 回写 config.yaml
- **前端**：选股页配置区有区间编辑器（增删条目），改完 PUT 后端，本地 state 同步
- 选股时（`screen("dividend_value", ...)`）从内存配置读全局区间，传给 `stock_percentile_batch`
- 单股分位接口从同一内存配置读全局区间

---

## 5. 新模式实现 `_screen_dividend_value`

位置：`backend/src/domain/market/strategy/longterm/screener.py`

```python
def _screen_dividend_value(
    symbols, val_map, fin_map, as_of, top_n, filters,
) -> list[ScreenItem]:
    # 1. 读配置：metric/window/exclude_ranges
    metric = filters.get("value_metric", "pb")     # pb | pe_ttm | pb_pe
    window = filters.get("value_window", "10y")    # 10y | 20y
    exclude_ranges = _get_global_exclude_ranges()  # 从内存配置

    # 2. 第一遍：硬门槛（股息率/PB/PE/ROE/负债率）
    #    用现有 val_map + fin_map，筛出候选池
    candidates = [...]  # list[symbol]

    # 3. 批量算分位（只对候选池，省算力）
    pct_map = stock_percentile_batch(
        candidates, metric, window, as_of, exclude_ranges)

    # 4. 低估分位 map（越低越好）；剔除分位为 None 的（样本不足/负值）
    value_map = {sym: info["percentile"] for sym, info in pct_map.items()
                 if info["percentile"] is not None}

    # 5. 股息率 map
    dy_map = {sym: val_map[sym]["dv_ttm"] for sym in value_map}

    # 6. 双排名 → top_n（复用 _finalize，分位升序 + 股息率降序）
    items = _finalize(snap, dy_map, value_map, top_n,
                      roe_rank_desc=True,    # 股息率降序
                      ey_rank_desc=False,    # 分位升序（越低越好）
                      reason=f"高股息+低{metric.upper()}分位({window})")

    # 7. 填充 factor_breakdown
    for it in items:
        it.factor_breakdown = {...}  # dy_value/dy_rank/value_*/exclude_applied
    return items
```

注册到 `SCREENER_MODES`、`dispatch`、`list_modes()`（screener_router.py 的 `filters_default` 也要加 `value_metric`/`value_window`）。

---

## 6. 通用下钻（前端，所有模式受益）

复用 NationalTeam 的 `.nt-modal` 骨架，新建 `frontend/apps/web/src/components/ScreenerDrillModal.tsx`。所有模式表格行加 `onClick` 打开它。

### 6.1 五个区块

| 区块 | 内容 | 数据来源 |
|---|---|---|
| **a 个股画像** | 名称/行业/最新价/市值/PE/PB/股息率/ROE 快照 | 已有 `/financial/profile/{symbol}` |
| **b 估值历史分位** | PE/PB/PS/股息率 四张分位图，带区间剔除交互 | 已有 `/financial/valuation-percentile/{symbol}` + 新 `exclude` 参数；复用 `ValuationPercentileChart` 组件 |
| **c 财务趋势** | ROE/净利率/负债率/营收/净利润 近几期小折线 | 已有 `/financial/detail/{symbol}` |
| **d K线+股息率** | 近 1 年价格 + 股息率双轴图 | K线复用现有 Eastmoney 拉取（参考 national_team_handler 的 K 线带 8s 超时 + 进程缓存）；股息率从分位接口 series 取 |
| **e 入选拆解** | `dividend_value` 模式：股息率排名/分位/综合分；其他模式：`reason` 字段展开 | `factor_breakdown`（新） |

### 6.2 b 区块的区间剔除交互（单只手动剔除）

- 分位图下方加两个日期输入框（start/end）+「剔除该区间并重算」按钮 + 已剔除区间列表（可删除）
- 点重算 → 带 `exclude` 参数重新请求 → 图表和分位数同步更新
- 默认带入全局剔除区间（从 `/screener/exclude-ranges` 拉），用户可叠加单只区间

### 6.3 选股页配置区扩展（新模式专用）

模式选 `dividend_value` 时，控制条额外显示：
- **低估指标切换**：`PB` / `PE_TTM` / `PB+PE` 三个 pill 按钮
- **窗口切换**：`10y` / `20y` 两个 pill 按钮
- **全局剔除区间编辑器**：列表 + 两条日期输入框 + 增/删按钮，改完 PUT `/screener/exclude-ranges`

---

## 7. 配置项

`backend/conf/config.yaml` 新增：
```yaml
screener:
  dividend_value:
    # 全局炒作区间（选股 + 单股分位默认剔除），UI 可编辑回写
    exclude_ranges:
      - ["2015-06-15", "2015-12-31"]   # 示例：2015 杠杆牛
    filters_default:
      dy_min: 3.0
      pb_max: 3.0
      pe_min: 0
      pe_max: 60
      roe_min: 8.0
      debt_max: 70.0
      value_metric: "pb"     # pb | pe_ttm | pb_pe
      value_window: "10y"    # 10y | 20y
```

---

## 8. 边界与降级

- **次新股（样本 < 30）**：该股淘汰，不参与低估排名（硬门槛已含）
- **负 PE / PE 缺失（当前值）**：当前 `pe_ttm ≤ 0` 的股票（亏损股）一律被 §3.2 安全阀淘汰，不进入任何低估排名
- **历史 PE 样本不足（pb_pe 模式特有降级）**：`pb_pe` 模式下，若某股 PB 分位可算但 PE 历史样本 <30（PE 子分位为 None），则**退化为纯 PB 分位**参与排名（`factor_breakdown.value_percentile_pe = null` 标注）；纯 `pe_ttm` 模式下 PE 样本不足则直接淘汰
- **股息率缺失**：`dividend_value` 模式淘汰（要求真实股息率，不兜底）
- **全局剔除后样本不足**：该股按"样本不足"处理，淘汰
- **窗口数据不全**（上市不足 10 年）：取上市以来的全部可用数据，只要 ≥30 样本就参与
- **批量分位超时/失败**：降级为"仅股息率排名"，`reason` 标注"分位计算失败，仅按股息率"

---

## 9. 测试计划

- **单元**
  - `get_range_batch`：多符号 + 月降采样 + exclude_ranges 下推正确性
  - `stock_percentile_batch`：含剔除、复合 pb_pe、样本不足降级、负值过滤
  - `_screen_dividend_value`：硬门槛、双排名、factor_breakdown 填充
  - 区间解析：`exclude` 字符串 → `list[tuple[date,date]]`
- **集成**
  - `POST /screener/screen`（新模式各 metric/window 组合）
  - `GET /financial/valuation-percentile/{symbol}?exclude=...`（带/不带 exclude 对比）
  - `GET/PUT /screener/exclude-ranges`（读取、更新、持久化）
- **前端**
  - 下钻 modal 五区块加载
  - b 区块剔除区间交互（增删/重算）
  - 选股页配置区：metric/window 切换 + 全局区间编辑器

---

## 10. 实现顺序建议（供后续 plan 参考）

1. 仓库 `get_range_batch` + 单测（基础能力，无依赖）
2. 服务 `stock_percentile_batch` + 单测
3. 单股接口 `exclude` 参数 + 单测（改动小，先验证剔除链路）
4. 新模式 `_screen_dividend_value` + 注册 + 单测
5. 全局区间配置加载 + `GET/PUT /screener/exclude-ranges`
6. 前端：选股页配置区（metric/window/全局区间编辑器）
7. 前端：`ScreenerDrillModal` 五区块
8. 端到端联调

---

## 11. 未做（YAGNI，留作后续迭代）

- 全局剔除区间的 **UI 模板/预设**（如"一键剔除 2015 牛市"）——第一版手填即可
- 分位图上**手绘框选**剔除——第一版用日期输入框
- 下钻里的 K 线改成**复权**切换——第一版用 Eastmoney 默认前复权
- 复合因子的**非等权加权**（如 60% PB + 40% PE）——第一版等权
- 新模式同步进**长期回测策略注册表**——第一版只在选股器
