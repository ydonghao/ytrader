# Indices 页筛选条件 — 设计文档

- **日期**: 2026-08-05
- **页面**: `/indices`（`http://localhost:12000/indices`）
- **目标**: 给指数页增加筛选条件，重点是**时间范围筛选**
- **涉及文件**:
  - 前端: `frontend/apps/web/src/pages/Indices.tsx`、`Indices.css`
  - 后端: `backend/src/api/router/market_router.py`（`/market/indices` 端点）

---

## 1. 背景与现状

当前 `/indices` 页三块内容：

| 区块 | 内容 | 数据来源 |
|---|---|---|
| ① 核心指数卡片 | 4 个硬编码宽基（上证/深成/沪深300/创业板指）的**当日**收盘 + 日涨跌 | `/market/indices` |
| ② 列表 + K 线图 | 左侧全量指数列表，右侧 400 根写死的日 K | `/market/indices` + `/market/kline/{symbol}?limit=400` |
| ③ 涨跌幅排行表 | 全部指数按**当日**涨跌幅排序 | `/market/indices` |

**问题**:
- 没有任何筛选（无搜索 / 无分类切换 / 无方向过滤 / 无时间筛选）。
- 时间维度是写死的：列表/排行永远是「当日涨跌」，K 线永远是最近 400 根。
- 后端 `/market/indices` **不接受任何参数**，永远返回最新交易日快照。

**已确认的需求**（来自与用户澄清）:
- 时间筛选要覆盖三种语义：**K 线图区间**、**排行榜涨跌幅周期**、**历史快照「截至某日」**。
- 其他筛选：**名称/代码搜索框**、**分类切换（宽基 / 申万行业）**、**涨跌幅方向筛选（涨/跌/全部）**。

---

## 2. 方案选型：统一日期范围（方案 A）

三种时间语义用一个统一的「日期范围 [start, end]」控件驱动，而非三个独立控件：

| 用户意图 | 用统一范围如何表达 |
|---|---|
| 看某段时间的 K 线 | K 线请求带 `start`/`end`，区间 = 选定范围 |
| 看某段时间的累计涨跌排行 | 列表/卡片的涨跌幅 = `close@end ÷ close@(start 前一交易日) − 1` |
| 回看历史某一天的快照 | end 设为过去某天即可（start = end 前一交易日 ⇒ 等价当日涨跌） |

**为什么选 A**:
- 后端改动最小：`/market/indices` 只加两个可选参数 `start`/`end`；K 线端点**本就支持** `start`/`end`，前端拼接即可，零后端改动。
- 一个心智模型，三个控件不会互相打架（B 方案里「快照日期」与「今日排行」天然冲突）。
- 完全向后兼容：不传参时行为与现状逐字相同。

**默认预设 = 今日**：首屏等价于当前页面（最新交易日收盘 + 当日涨跌幅 + 最近 400 根日 K），不破坏现有体验。

---

## 3. 后端设计

### 3.1 端点签名

```python
@router.get("/indices", response_model=dict)
def list_indices(
    start: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD；不传=最新交易日"),
    end:   Optional[str] = Query(None, description="结束日期 YYYY-MM-DD；不传=最新交易日"),
):
```

### 3.2 行为矩阵

| `start` | `end` | close 取值 | prev 取值（涨跌幅分母） | 含义 |
|---|---|---|---|---|
| 都不传 | 都不传 | 最新交易日 close | 倒数第 2 个交易日 close | **现状**：当日涨跌 |
| 传 | 传 | `≤ end` 的最新 close | `< start` 的最新 close | 区间累计涨跌 |
| 传 | 不传 | 最新交易日 close | `< start` 的最新 close | 从 start 至今 |
| 不传 | 传 | `≤ end` 的最新 close | 历史最早 close | 从上市/end（极少用，但定义清楚） |

> 规则一句话：**close = 区间内（含 end）最新一条；prev = start 之前（不含 start）最新一条。** start 留空时 prev 退化为「最早一条」；end 留空时 close 退化为「最新一条」。这样统一覆盖「当日 / 区间 / 截至某日 / 至今」。

### 3.3 实现（新增辅助函数，复用现有窗口函数风格）

参数缺失时走现有 `_latest_sql`（毫秒级，保持现状）；参数存在时走一个新的 `_range_sql`，按 `market` 分组分别查 `INDEX` / `SW`：

```python
def _range_sql(table, time_col, start, end, where=""):
    """区间涨跌幅：close = ≤end 最新一条，prev = <start 最新一条。

    用两次 ROW_NUMBER 窗口，分别取 close 端点和 prev 端点，再按 symbol 拼接。
    与 _latest_sql 同风格，仅 WHERE 条件不同。
    """
    conds = []
    if where.strip():
        conds.append(where)
    # close 端点：trade_date <= end (end 缺省时不加约束=取最新)
    close_cond = f"{time_col} <= '{end}'" if end else None
    # prev 端点：trade_date < start (start 缺省时取历史最早一条作为基准)
    prev_cond = f"{time_col} < '{start}'" if start else None
    # 详见实现；表数据量小（指数 ~15 + 申万 ~31 行/日），无性能顾虑。
```

返回结构不变：`{ code, msg, data: { market_index: [...], sw_index: [...] } }`，每行仍是 `{symbol, name, close, change_pct}`。前端无需改类型定义。

### 3.4 安全 / 校验

- `start`/`end` 必须为 `YYYY-MM-DD` 格式，否则 400（FastAPI 用 `datetime.date` 解析更稳：把参数类型改成 `Optional[datetime.date]`，框架自动校验 + 序列化为 `YYYY-MM-DD`，免手写正则）。
- `start > end` 时返回 400 + 友好错误信息。
- 参数直接来自 URL，**不可字符串拼接进 SQL** —— 用 psycopg 参数化（`%s`）传值。现有 `_latest_sql` 是字符串 format，但那些是写死的表名/列名；**新代码涉及用户输入的日期，必须用参数化**。

### 3.5 缓存

不加 TTL 缓存。原因：
- 现状 `/indices` 本就无缓存（数据小、查询毫秒级）。
- 加 `start`/`end` 后缓存键维度爆炸，命中率极低，得不偿失。
- `/market/categories` 的缓存是针对无参固定分类设计的，不适用。

---

## 4. 前端设计

### 4.1 新增筛选条（页面顶部，header 下方、卡片上方）

单行布局，分组：

```
[ 全部 | 宽基 | 申万行业 ]   [ 搜索名称/代码... ]   [ 今日 | 近1月 | 近3月 | 近6月 | 近1年 | 今年 | 自定义 ]
                                                                  [开始日期][结束日期][应用]
                                                                 [ 仅涨 | 仅跌 | 全部 ]
```

- **分类切换**：三个分段按钮（segmented control），复用现有 `.indices__list-item` 选中态的视觉语言（`--color-accent` 边框 + `--color-accent-light` 底）。默认「全部」。
- **搜索框**：受控 `<input>`，placeholder「搜索指数名称或代码」，实时过滤（无防抖，列表 ~46 项，纯前端 filter 毫秒级）。复用 Market 页 `.market-cat__search` 的样式思路。
- **时间预设**：一排 pill 按钮。选中态高亮。点「自定义」展开两个 `<input type="date">` + 应用按钮。
- **方向筛选**：三个小 pill（涨/跌/全部），默认「全部」。

### 4.2 状态新增

```tsx
// 筛选条状态
const [category, setCategory] = useState<'all' | 'index' | 'sw'>('all');
const [query, setQuery] = useState('');
const [preset, setPreset] = useState<PresetKey>('today');  // today/1m/3m/6m/1y/ytd/custom
const [customRange, setCustomRange] = useState<{start: string; end: string}>({start:'', end:''});
const [direction, setDirection] = useState<'all' | 'up' | 'down'>('all');
```

`preset` 切换时同步计算 `start`/`end` 字符串：

| preset | start | end |
|---|---|---|
| `today` | 空 | 空（= 最新交易日，等价现状） |
| `1m` / `3m` / `6m` / `1y` | 今天 − N 天（自然日，非交易日） | 空（= 最新交易日） |
| `ytd` | 当年 1 月 1 日 | 空 |
| `custom` | 取 `customRange.start` | 取 `customRange.end` |

实际驱动请求的 `range = preset === 'custom' ? customRange : presetToRange(preset)`。

**边界**：`preset='custom'` 但 `customRange.start` 和 `end` 都为空时，视为「今日」（不发 start/end），避免空请求。

### 4.3 数据流

```
range (start/end) 变化
  ├─ fetchQuotes(range)  → GET /market/indices?start=..&end=..  （重新拉全量带区间涨跌）
  └─ fetchBars(selected, range) → GET /market/kline/{symbol}?start=..&end=..&interval=1d
                                                                   （替换原 ?limit=400）

category / query / direction 变化 → 纯前端 filter，不发请求
```

- `fetchQuotes` 依赖 `range`（useEffect / useCallback 依赖数组加 range）。
- `fetchBars` 依赖 `[selected, range]`。
- **保持现状兼容**：preset=「今日」时不带 `start`/`end`，等价当前请求。
- **去抖**：自定义日期输入时，点「应用」才触发请求（不在每次输入时拉），避免连打字狂发请求。

### 4.4 三块内容如何受筛选影响

| 区块 | 受 range 影响 | 受 category/query/direction 影响 |
|---|---|---|
| ① 核心指数卡片 | 是（涨跌幅按区间；卡片固定显示 4 个核心宽基，不受 category 影响） | 不受（始终显示这 4 个） |
| ② 左侧列表 | 是 | 是（category + query + direction 过滤） |
| ② 右侧 K 线 | 是（区间 = range） | 不受（只随 selected 变） |
| ③ 排行表 | 是 | 是（category + query + direction 过滤，按区间 change_pct 排序） |

**派生数据**（useMemo）：

```tsx
const filtered = useMemo(() => {
  return quotes.filter(q => {
    if (category === 'index' && !q.symbol.match(/^(sh|sz)\d/)) return false;
    if (category === 'sw' && !q.symbol.toLowerCase().startsWith('sw')) return false;
    if (query) {
      const k = query.toLowerCase();
      if (!q.name.toLowerCase().includes(k) && !q.symbol.toLowerCase().includes(k)) return false;
    }
    if (direction === 'up' && q.change_pct <= 0) return false;
    if (direction === 'down' && q.change_pct >= 0) return false;
    return true;
  });
}, [quotes, category, query, direction]);

const sortedQuotes = useMemo(
  () => [...filtered].sort((a, b) => b.change_pct - a.change_pct),
  [filtered],
);
```

- 卡片、列表、排行表分别从 `coreQuotes`（仍按 CORE_SYMBOLS 过滤）、`filtered`、`sortedQuotes` 渲染。
- `coreQuotes` 不受 category/query/direction 影响（这 4 个是首屏核心指标，永远显示）。

### 4.5 空状态

- `filtered` 为空（例如「申万行业 + 搜索"沪深"」）时，列表和排行显示「无匹配结果」空态，复用 `.indices__empty` 样式。

### 4.6 样式（Indices.css 新增）

- 新增 `.indices__filters`（flex 容器，`gap: var(--space-3)`，`margin-bottom: var(--space-5)`）。
- `.indices__filter-group`（分段/搜索/预设各自一组，用 `var(--color-border)` 分隔）。
- `.indices__pill` / `.indices__pill--active`（小圆角按钮，复用 `--color-surface` / `--color-accent-light` token）。
- `.indices__search`（input，复用 Market 页 `.market-cat__search` 的视觉：`--color-surface` 底 + `--color-border` 边）。
- `.indices__date-input`（`<input type="date">`，暗色主题需调 `color-scheme: dark`）。
- 响应式：窄屏（<1100px）筛选条换行（`flex-wrap: wrap`），预设 pill 组可横向滚动。

---

## 5. 非目标（YAGNI）

明确**不做**的：
- 后端分页 / 服务端排序（46 项前端全量处理足够）。
- 申万二/三级行业分类（config 里只有一级，DB 不存级别；不引入）。
- 保存/恢复筛选偏好到 localStorage / URL（本轮先不做，保持简单；URL 同步可作后续增强）。
- 分钟级时间筛选（K 线 interval 仍固定 1d）。
- 缓存。

---

## 6. 测试

- **后端**（pytest，复用 `backend/tests/` 既有风格）：
  - `GET /market/indices` 无参 → 现状不变（最新收盘 + 当日涨跌）。
  - `?start=2025-01-01&end=2025-06-30` → close = ≤end 最新、prev = <start 最新；change_pct = 区间累计。
  - 非法日期 `?start=abc` → 400。
  - `start > end` → 400。
  - 参数化 SQL（不字符串拼接用户输入）——通过代码 review + 既有查询行为间接保证。
- **前端**（手动验证清单）：
  - 默认 preset=今日，三块内容与改造前视觉一致。
  - 切「近3月」：卡片/列表/排行涨跌幅变为近 3 月累计；K 线变为近 3 月区间。
  - 切「宽基」+ 搜索「300」：列表只剩沪深300。
  - 切「仅涨」：列表只剩上涨项。
  - 自定义日期 + 应用：请求带正确 start/end。
  - end 设为过去某天（如 2025-06-30）：全页回看那天快照。

---

## 7. 实现顺序（粗，详细步骤交由 writing-plans 产出）

1. 后端：给 `/market/indices` 加 `start`/`end` 参数 + `_range_sql` 辅助函数 + 校验。
2. 后端：补 pytest。
3. 前端：加筛选条 UI（state + 控件 + CSS）。
4. 前端：把 `fetchQuotes`/`fetchBars` 接到 range；列表/卡片/排行接 category/query/direction filter。
5. 手动验证清单逐项过。
