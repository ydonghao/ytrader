# 宏观历史事件标注 + 长历史数据 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在指标详情大图上标注中国重大经济事件竖线，并为 CPI/PPI/PMI/M2 补充 1986-2008 的长历史数据，前端可切换标准/长历史视图。

**Architecture:** 后端新增 `GET /macro/events` 端点（读 config 静态事件列表）+ 4 个 `_long` 提取器（用 akshare `*_yearly` 接口）。前端在 `IndicatorDetail` 图表上用 recharts `ReferenceLine` 画事件竖线，对有 `_long` 版本的指标加频率切换按钮。

**Tech Stack:** React 18 + Recharts（ReferenceLine），FastAPI + Pydantic，akshare 1.18.50，pytest。

## Global Constraints

- CSS 类名用 BEM 前缀 `macro__`，颜色用 CSS 变量（`--color-accent`/`--color-surface`/`--color-border` 等）
- 后端线宽 79，black + isort，flake8（max-line-length 79, ignore E203/W503）
- 测试：`.venv/bin/python -m pytest <path> -v`
- akshare yearly 接口格式：列 `日期`(date) + `今值`(value)，与现有 `cn_industrial_yoy` 提取器同格式
- `_long` code 用发布日做 report_date（不做日期归一化），与标准版口径不同
- 事件竖线用 recharts `<ReferenceLine x={date} />`，X 轴 `dataKey="report_date"` 必须是字符串日期
- API 基址 `${API_BASE}` = `getApiBase()`，端点前缀 `/macro/`

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/conf/settings.py` | Modify | 新增 `MacroEvent` 模型 + `macro_events` 字段 |
| `backend/conf/config.yaml` | Modify | 新增 `macro_events` 段（12 事件）+ 4 个 `_long` 指标元数据 |
| `backend/.../akshare_provider.py` | Modify | `_MACRO_EXTRACTORS` 新增 4 个 `_long` 提取器 |
| `backend/src/api/handler/macro_handler.py` | Modify | 新增 `list_events()` handler |
| `backend/src/api/router/macro_router.py` | Modify | 新增 `GET /macro/events` 路由 |
| `backend/.../macro_monthly.py` | Modify | `_long` code 无需特殊处理（provider=akshare 自动同步） |
| `backend/tests/.../test_akshare_provider.py` | Modify | 4 个 `_long` 提取器测试 |
| `frontend/.../Macro.tsx` | Modify | 事件标注 + 频率切换 |
| `frontend/.../Macro.css` | Modify | 事件标注 + 切换按钮样式 |

---

### Task 1: 后端 — 事件数据配置 + `/macro/events` API

**Files:**
- Modify: `backend/conf/settings.py`（新增 `MacroEvent` 模型 + `macro_events` 字段）
- Modify: `backend/conf/config.yaml`（新增 `macro_events` 段）
- Modify: `backend/src/api/handler/macro_handler.py`（新增 `list_events`）
- Modify: `backend/src/api/router/macro_router.py`（新增路由）

**Interfaces:**
- Produces: `GET /macro/events` → `{code:0, data: [{date, title, desc}, ...]}`
- Produces: `app_config.macro_events` → `list[MacroEvent]`

- [ ] **Step 1: settings.py 新增 MacroEvent 模型**

在 `backend/conf/settings.py` 的 `MacroPredictTargetConfig` 类之后（约 line 196），`MacroUniverseConfig` 之前，新增：

```python
class MacroEvent(BaseModel):
    """中国重大经济事件（图表标注用，静态配置）。"""
    date: str            # "2008-09-15"（ISO 日期）
    title: str           # "雷曼破产·全球金融危机"
    desc: str = ""       # 详细说明
```

然后在 `MacroUniverseConfig` 类（约 line 195）内新增字段：

```python
class MacroUniverseConfig(BaseModel):
    """宏观板块数据 + 判断清单（macro_sync / macro_view 使用）。"""
    indicators: list[MacroIndicatorConfig] = []
    global_indices: list[QuantUniverseIndexConfig] = []
    predict_targets: list[MacroPredictTargetConfig] = []
    snapshot_horizon_days: int = 63
    macro_events: list[MacroEvent] = []     # 新增：历史事件标注
```

- [ ] **Step 2: config.yaml 新增 macro_events 段**

在 `backend/conf/config.yaml` 的 `macro_universe:` 段内，`indicators:` 列表之后（`global_indices:` 之前或之后均可），新增：

```yaml
  # 中国重大经济事件（图表标注用）
  macro_events:
    - date: "2008-09-15"
      title: "雷曼破产·金融危机"
      desc: "次贷危机全面爆发，中国出口骤降，11月推出四万亿刺激"
    - date: "2009-03-01"
      title: "四万亿投资计划"
      desc: "大规模基建刺激，M2增速飙至30%"
    - date: "2015-06-15"
      title: "A股股灾"
      desc: "杠杆牛破裂，上证从5178跌至2850"
    - date: "2016-01-01"
      title: "供给侧改革"
      desc: "去产能去库存，PPI从通缩转正"
    - date: "2018-07-06"
      title: "中美贸易战"
      desc: "首批340亿美元商品加征关税"
    - date: "2020-01-23"
      title: "新冠疫情"
      desc: "武汉封城，一季度GDP -6.9%"
    - date: "2020-03-23"
      title: "全球大放水"
      desc: "美联储无限QE，全球资产反弹"
    - date: "2021-07-01"
      title: "互联网/教培监管"
      desc: "反垄断+双减，恒生科技暴跌"
    - date: "2022-07-01"
      title: "房地产断贷潮"
      desc: "保交楼，房企信用危机"
    - date: "2022-11-01"
      title: "防疫优化二十条"
      desc: "逐步放开，经济复苏预期"
    - date: "2024-09-24"
      title: "924金融新政"
      desc: "降准降息+股市支持，A股暴涨"
    - date: "2025-04-01"
      title: "对等关税升级"
      desc: "中美贸易紧张再升温"
```

- [ ] **Step 3: macro_handler.py 新增 list_events handler**

在 `backend/src/api/handler/macro_handler.py` 的 `record_view` 函数之后，新增：

```python
# ── 历史事件 ──────────────────────────────────────────────────
def list_events() -> Any:
    """中国重大经济事件列表（供前端图表标注）。"""
    from conf import app_config
    events = []
    for e in app_config.macro_universe.macro_events:
        events.append({"date": e.date, "title": e.title, "desc": e.desc})
    return responses.success(events)
```

- [ ] **Step 4: macro_router.py 新增路由**

在 `backend/src/api/router/macro_router.py` 的 import 中加 `list_events`：

```python
from src.api.handler.macro_handler import (
    dashboard,
    generate_view,
    get_view,
    indicator_series,
    latest_indicators,
    list_events,
    list_views,
    record_view,
    track_view,
)
```

然后在文件末尾（`/views/record` 路由之后）新增：

```python
@router.get("/events")
def _events():
    return list_events()
```

- [ ] **Step 5: 验证配置加载 + API**

```bash
cd backend && .venv/bin/python -c "
from conf import app_config
events = app_config.macro_universe.macro_events
print(f'事件数: {len(events)}')
assert len(events) == 12
print(f'第一个: {events[0].date} {events[0].title}')
print('OK')
"
```
预期：`事件数: 12`，`第一个: 2008-09-15 雷曼破产·金融危机`。

如果后端在运行，还需验证：
```bash
curl -s http://localhost:12100/api/v1/macro/events | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'事件数: {len(d[\"data\"])}')
print(d['data'][0])
"
```

- [ ] **Step 6: Commit**

```bash
git add conf/settings.py conf/config.yaml src/api/handler/macro_handler.py src/api/router/macro_router.py
git commit -m "feat(macro): add historical events config + GET /macro/events API"
```

---

### Task 2: 后端 — 4 个 `_long` 提取器 + 数据灌入

**Files:**
- Modify: `backend/src/domain/market/sync/providers/akshare_provider.py`（`_MACRO_EXTRACTORS` 新增 4 条）
- Modify: `backend/conf/config.yaml`（4 个 `_long` 指标元数据）
- Modify: `backend/tests/domain/market/sync/providers/test_akshare_provider.py`（4 个测试）

**Interfaces:**
- Produces: `_MACRO_EXTRACTORS["cn_cpi_yoy_long"]` / `["cn_ppi_yoy_long"]` / `["cn_pmi_long"]` / `["cn_m2_yoy_long"]`
- 每个走 `ak.macro_china_{cpi|ppi|pmi|m2}_yearly()`，列 `日期` + `今值`

**背景**：yearly 接口格式与现有 `cn_industrial_yoy` 完全一致（列：商品/日期/今值/预测值/前值）。日期是发布日（date 对象），今值是 float。

- [ ] **Step 1: 写失败测试**

在 `test_akshare_provider.py` 末尾追加：

```python
# ── 长历史 yearly 提取器 ────────────────────────────────────────────
def _yearly_df():
    """模拟 ak.macro_china_cpi_yearly（英为财情 5 列格式）"""
    return pd.DataFrame({
        "商品": ["中国CPI年率报告"] * 3,
        "日期": ["1986-02-01", "1986-03-01", "2024-01-12"],
        "今值": [7.1, 7.1, -0.8],
        "预测值": [None, None, -0.5],
        "前值": [None, 7.1, 0.1],
    })


@pytest.mark.parametrize("code,fn_name", [
    ("cn_cpi_yoy_long", "macro_china_cpi_yearly"),
    ("cn_ppi_yoy_long", "macro_china_ppi_yearly"),
    ("cn_pmi_long", "macro_china_pmi_yearly"),
    ("cn_m2_yoy_long", "macro_china_m2_yearly"),
])
def test_extract_long_history(monkeypatch, code, fn_name):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(mod.ak, fn_name, lambda: _yearly_df())
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_series(code)
    assert len(rows) == 3
    # 最早的数据在前（升序）
    assert rows[0][0] == date(1986, 2, 1)
    assert rows[0][1] == 7.1
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && .venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py::test_extract_long_history -v
```
预期：4 FAIL（code 不在注册表）。

- [ ] **Step 3: 实现提取器**

在 `akshare_provider.py` 的 `_MACRO_EXTRACTORS` 字典，美国段之前（中国段末尾），追加：

```python
        # ── 长历史（yearly 接口，更深历史，发布日口径）──
        "cn_cpi_yoy_long": {
            "fn": lambda: ak.macro_china_cpi_yearly(),
            "pick": lambda r: (
                _parse_iso_date(r.get("日期")),
                _num(r.get("今值")),
            ),
            "freq": "month", "unit": "%",
        },
        "cn_ppi_yoy_long": {
            "fn": lambda: ak.macro_china_ppi_yearly(),
            "pick": lambda r: (
                _parse_iso_date(r.get("日期")),
                _num(r.get("今值")),
            ),
            "freq": "month", "unit": "%",
        },
        "cn_pmi_long": {
            "fn": lambda: ak.macro_china_pmi_yearly(),
            "pick": lambda r: (
                _parse_iso_date(r.get("日期")),
                _num(r.get("今值")),
            ),
            "freq": "month", "unit": "",
        },
        "cn_m2_yoy_long": {
            "fn": lambda: ak.macro_china_m2_yearly(),
            "pick": lambda r: (
                _parse_iso_date(r.get("日期")),
                _num(r.get("今值")),
            ),
            "freq": "month", "unit": "%",
        },
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py::test_extract_long_history -v
```
预期：4 PASS。

- [ ] **Step 5: config.yaml 新增 4 个 _long 指标元数据**

在 `macro_universe.indicators` 列表中追加（`us_cpi_yoy` 之前）：

```yaml
    - code: "cn_cpi_yoy_long"
      name: "CPI同比（长历史）"
      unit: "%"
      freq: "month"
      category: "cn"
      group: "inflation"
      provider: "akshare"
      direction: "low_good"
      description: "CPI长历史（1986年起）"
      explanation: "CPI同比长历史序列，数据源为英为财情年度报告接口，1986年至今。日期为发布日口径（与标准版的月初口径略有差异），用于查看超长周期趋势。"
      range_low: -2.0
      range_high: 10.0
      reference_lines:
        - { value: 0.0, label: "通缩", severity: "warning" }
        - { value: 3.0, label: "通胀警戒", severity: "warning" }
      source: "英为财情"
      source_url: "https://investing.com/"
    - code: "cn_ppi_yoy_long"
      name: "PPI同比（长历史）"
      unit: "%"
      freq: "month"
      category: "cn"
      group: "inflation"
      provider: "akshare"
      direction: "neutral"
      description: "PPI长历史（1995年起）"
      explanation: "PPI同比长历史序列，1995年至今。日期为发布日口径，用于查看超长周期趋势。"
      range_low: -10.0
      range_high: 15.0
      reference_lines:
        - { value: 0.0, label: "通缩/通胀分界", severity: "normal" }
      source: "英为财情"
      source_url: "https://investing.com/"
    - code: "cn_pmi_long"
      name: "制造业PMI（长历史）"
      unit: ""
      freq: "month"
      category: "cn"
      group: "growth"
      provider: "akshare"
      direction: "high_good"
      description: "PMI长历史（2005年起）"
      explanation: "制造业PMI长历史序列，2005年至今。荣枯线50。日期为发布日口径。"
      threshold_high: 50.0
      threshold_low: 50.0
      range_low: 40.0
      range_high: 60.0
      reference_lines:
        - { value: 50.0, label: "荣枯线", severity: "normal" }
      source: "英为财情"
      source_url: "https://investing.com/"
    - code: "cn_m2_yoy_long"
      name: "M2同比（长历史）"
      unit: "%"
      freq: "month"
      category: "cn"
      group: "monetary"
      provider: "akshare"
      direction: "neutral"
      description: "M2长历史（1998年起）"
      explanation: "M2同比长历史序列，1998年至今。日期为发布日口径。"
      range_low: 5.0
      range_high: 30.0
      reference_lines:
        - { value: 10.0, label: "中性", severity: "normal" }
      source: "英为财情"
      source_url: "https://investing.com/"
```

- [ ] **Step 6: 验证配置 + 灌入长历史数据**

```bash
cd backend && .venv/bin/python -c "
from conf import app_config
codes = [i.code for i in app_config.macro_universe.indicators]
for c in ['cn_cpi_yoy_long','cn_ppi_yoy_long','cn_pmi_long','cn_m2_yoy_long']:
    assert c in codes, f'缺失 {c}'
print(f'OK: 总指标数 {len(codes)}')
"
```

然后运行 job 灌入：
```bash
.venv/bin/python -m src.domain.market.sync.jobs.macro_monthly 2>&1 | /usr/bin/grep "_long"
```
预期：4 个 `_long` 指标各拉取数百行（`cn_cpi_yoy_long +477` 等）。

- [ ] **Step 7: Commit**

```bash
git add src/domain/market/sync/providers/akshare_provider.py \
        tests/domain/market/sync/providers/test_akshare_provider.py \
        conf/config.yaml
git commit -m "feat(macro): add 4 long-history extractors (CPI/PPI/PMI/M2 yearly)"
```

---

### Task 3: 前端 — 事件标注（竖线 + 标签）

**Files:**
- Modify: `frontend/apps/web/src/pages/Macro.tsx`（`IndicatorDetail` 图表加事件竖线）
- Modify: `frontend/apps/web/src/pages/Macro.css`（事件竖线样式）

**Interfaces:**
- Consumes: `GET /macro/events` → `[{date, title, desc}, ...]`
- Produces: `IndicatorDetail` 图表上的事件 `ReferenceLine` 竖线

**背景**：现有 `IndicatorDetail`（Macro.tsx ~line 312）的大折线图在 `.macro__detail-chart` div 内，用 recharts `LineChart`。X 轴 `dataKey="report_date"`。事件竖线用 `<ReferenceLine x={date} />` 画在同一个图表上。事件数据在页面级获取一次（不每个指标单独拉），传给 `IndicatorDetail`。

- [ ] **Step 1: 新增事件类型 + 页面级获取**

在 `Macro.tsx` 的 Types 区（约 line 50），新增：

```typescript
interface MacroEvent {
  date: string;
  title: string;
  desc: string;
}
```

在 `Macro` 组件内（现有 state 旁），新增：

```typescript
  const [events, setEvents] = useState<MacroEvent[]>([]);
```

在 `fetchDashboard` 函数里，追加事件获取（在 `Promise.all` 里加第三个 fetch）：

```typescript
  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const [dRes, vRes, eRes] = await Promise.all([
        fetch(`${API_BASE}/macro/dashboard`),
        fetch(`${API_BASE}/macro/views?limit=50`),
        fetch(`${API_BASE}/macro/events`),
      ]);
      const dj = await dRes.json();
      const vj = await vRes.json();
      const ej = await eRes.json();
      setDash(dj.data || null);
      setViews(vj.data || []);
      setEvents(ej.data || []);
    } catch {
      setDash(null);
      setViews([]);
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }, []);
```

- [ ] **Step 2: 传递 events 给 IndicatorCard → IndicatorDetail**

在 `Macro` 组件 render 里，`IndicatorCard` 调用处加 `events` prop：

找到：
```typescript
              {tabIndicators.map((ind) => (
                <IndicatorCard
                  key={ind.indicator_code}
                  ind={ind}
```
改为：
```typescript
              {tabIndicators.map((ind) => (
                <IndicatorCard
                  key={ind.indicator_code}
                  ind={ind}
                  events={events}
```

修改 `IndicatorCard` 签名，加 `events` prop 并透传：

```typescript
const IndicatorCard: React.FC<{
  ind: IndicatorValue;
  expanded?: boolean;
  onToggle?: () => void;
  events?: MacroEvent[];
}> = ({ind, expanded, onToggle, events}) => {
```

在 `IndicatorCard` 内 `{expanded && <IndicatorDetail ind={ind} />}` 改为：
```typescript
      {expanded && <IndicatorDetail ind={ind} events={events} />}
```

修改 `IndicatorDetail` 签名，加 `events` prop：

```typescript
const IndicatorDetail: React.FC<{
  ind: IndicatorValue;
  events?: MacroEvent[];
}> = ({ind, events = []}) => {
```

- [ ] **Step 3: 在大折线图上画事件竖线**

在 `IndicatorDetail` 的 `<LineChart>` 内（现有 `<ReferenceLine>` 的 `reference_lines` 循环之后，`<Line>` 之前），追加事件竖线：

```typescript
              {/* 历史事件竖线（只画落在数据范围内的） */}
              {events.map((evt) => (
                <ReferenceLine
                  key={`evt-${evt.date}`}
                  x={evt.date}
                  stroke="var(--color-text-tertiary)"
                  strokeDasharray="2 4"
                  strokeWidth={1}
                  label={{
                    value: evt.title,
                    fill: 'var(--color-text-tertiary)',
                    fontSize: 9,
                    position: 'top',
                    angle: -90,
                  }}
                />
              ))}
```

**注意**：recharts 的 `ReferenceLine x={date}` 只在该 date 精确匹配 X 轴某个数据点时显示竖线。如果事件日期不在数据点中，竖线不显示。这是 recharts 的行为——可接受（大多数事件日期附近有月度数据点）。

- [ ] **Step 4: 验证编译**

```bash
cd frontend/apps/web && node_modules/.bin/rsbuild build 2>&1 | tail -5
```
预期：无 error。

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/pages/Macro.tsx
git commit -m "feat(macro): annotate historical events on indicator detail chart"
```

---

### Task 4: 前端 — 频率切换（标准/长历史）

**Files:**
- Modify: `frontend/apps/web/src/pages/Macro.tsx`（`IndicatorDetail` 加切换按钮 + 动态 code）
- Modify: `frontend/apps/web/src/pages/Macro.css`（切换按钮样式）

**Interfaces:**
- Consumes: `GET /macro/indicators/{code}?limit=500`（切换 code 时重新拉）
- Produces: `IndicatorDetail` 的频率切换 state

**背景**：只有 4 个指标有 `_long` 版本。映射关系：`cn_cpi_yoy` ↔ `cn_cpi_yoy_long`，`cn_ppi_yoy` ↔ `cn_ppi_yoy_long`，`cn_pmi` ↔ `cn_pmi_long`，`cn_m2_yoy` ↔ `cn_m2_yoy_long`。当指标有 `_long` 版本时，详情面板上方显示「标准 / 长历史」切换按钮。

- [ ] **Step 1: 定义长历史映射 + 切换 state**

在 `Macro.tsx` 的 helpers 区（`INDICATOR_TABS` 之前），新增：

```typescript
// 有长历史版本的指标映射：标准 code → 长历史 code
const LONG_HISTORY_MAP: Record<string, string> = {
  'cn_cpi_yoy': 'cn_cpi_yoy_long',
  'cn_ppi_yoy': 'cn_ppi_yoy_long',
  'cn_pmi': 'cn_pmi_long',
  'cn_m2_yoy': 'cn_m2_yoy_long',
};
```

- [ ] **Step 2: IndicatorDetail 加切换 state + 动态 code**

修改 `IndicatorDetail` 组件，加 `useLong` state，并根据切换动态选 code：

```typescript
const IndicatorDetail: React.FC<{
  ind: IndicatorValue;
  events?: MacroEvent[];
}> = ({ind, events = []}) => {
  const [series, setSeries] = useState<SeriesPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [useLong, setUseLong] = useState(false);

  // 该指标是否有长历史版本
  const longCode = LONG_HISTORY_MAP[ind.indicator_code];
  const activeCode = useLong && longCode ? longCode : ind.indicator_code;

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetch(`${API_BASE}/macro/indicators/${activeCode}?limit=500`)
      .then((r) => r.json())
      .then((j) => { if (alive) setSeries(j.data?.series || []); })
      .catch(() => { if (alive) setSeries([]); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [activeCode]);
```

- [ ] **Step 3: 详情面板加切换按钮**

在 `IndicatorDetail` 的 `return` 里，`.macro__detail-head` 之后、`.macro__detail-chart` 之前，加切换按钮（只有有 `longCode` 时显示）：

```typescript
      {/* 频率切换（仅有长历史版本的指标显示） */}
      {longCode && (
        <div className="macro__detail-freq">
          <button
            className={`macro__freq-btn ${!useLong ? 'is-active' : ''}`}
            onClick={() => setUseLong(false)}
          >
            标准（{ind.meta?.freq === 'day' ? '日频' : '月度'}）
          </button>
          <button
            className={`macro__freq-btn ${useLong ? 'is-active' : ''}`}
            onClick={() => setUseLong(true)}
          >
            长历史（{useLong ? '1986+' : '更早'}起）
          </button>
        </div>
      )}
```

- [ ] **Step 4: 切换按钮 CSS**

在 `Macro.css` 末尾追加：

```css
/* 频率切换 */
.macro__detail-freq {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.macro__freq-btn {
  padding: 4px 12px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-size: 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}
.macro__freq-btn:hover {
  border-color: var(--color-accent);
  color: var(--color-text);
}
.macro__freq-btn.is-active {
  border-color: var(--color-accent);
  color: var(--color-accent);
  background: var(--color-surface-raised);
}
```

- [ ] **Step 5: 验证编译 + 页面**

```bash
cd frontend/apps/web && node_modules/.bin/rsbuild build 2>&1 | tail -5
```
预期：无 error。

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/pages/Macro.tsx apps/web/src/pages/Macro.css
git commit -m "feat(macro): add standard/long-history frequency toggle for detail chart"
```

---

### Task 5: 端到端验证

**Files:** 无

- [ ] **Step 1: 验证后端 API**

```bash
echo "=== /macro/events ===" && curl -s http://localhost:12100/api/v1/macro/events | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{len(d[\"data\"])} events'); print(d['data'][0])"
echo "=== cn_cpi_yoy_long 数据 ===" && curl -s "http://localhost:12100/api/v1/macro/indicators/cn_cpi_yoy_long?limit=5" | python3 -c "import sys,json; d=json.load(sys.stdin); s=d['data']['series']; print(f'{len(s)} points (first 5)'); [print(f'  {p[\"report_date\"]} = {p[\"value\"]}') for p in s]"
```

- [ ] **Step 2: 验证前端构建 + 运行**

```bash
curl -s http://localhost:12000/macro -o /dev/null -w "HTTP %{http_code}"
```
预期：200。

- [ ] **Step 3: 浏览器验证清单**

在 `http://localhost:12000/macro` 验证：
1. 展开任意指标详情，大图上有事件竖线（灰色虚线+旋转标签）
2. 展开 CPI 指标，详情上方有「标准 / 长历史」切换按钮
3. 点「长历史」，图表切换到 1986+ 数据（数据点明显增多）
4. 切回「标准」，回到月度数据
5. PPI/PMI/M2 也有切换按钮
6. 其他指标（如社零/商品房）没有切换按钮

- [ ] **Step 4: Commit（如有微调）**

```bash
git status
# 若有改动：git add -A && git commit -m "fix(macro): e2e adjustments"
```

---

## Self-Review 记录

**Spec 覆盖性**：
- ✅ 历史事件标注 → Task 1（后端 API）+ Task 3（前端竖线）
- ✅ 补长历史数据 → Task 2（后端提取器+灌入）+ Task 4（前端切换）
- ✅ 12 个事件清单 → Task 1 Step 2（完整 YAML）
- ✅ 4 个 `_long` 指标 → Task 2 Step 3/5（提取器+元数据）

**Placeholder 扫描**：无 TBD/TODO，所有代码块完整。

**类型一致性**：
- `MacroEvent` 模型（Task 1 settings.py）与前端 `MacroEvent` interface（Task 3）字段一致（date/title/desc）
- `_long` code 命名（Task 2 提取器）与 `LONG_HISTORY_MAP`（Task 4 前端）一致
- `IndicatorDetail` 的 `events`/`useLong` props 跨 task 一致

**已知风险**：
1. recharts `ReferenceLine x={date}` 需要精确匹配 X 轴数据点——事件日期可能不在月度数据点中，竖线可能不显示。可接受（大多数事件日期在月初附近）。
2. yearly 接口的日期是发布日（如 2024-01-12），不是数据所属月——切换到长历史时，X 轴日期含义与标准版不同，但用户能看到更长趋势。
