# 宏观页面重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把宏观页面从"卡片网格+判断三段式"重构为"Tab 分维度浏览 + 指标详情展开面板"，并先灌入 38 个指标的真实数据。

**Architecture:** 纯前端重构。先手动跑 `macro_monthly` 灌数据（后端不改），再重构 `Macro.tsx`：顶部 Tab 栏按 `meta.group`/`category` 分维度，指标卡片点击展开详情面板（大折线图+关键数值+指标解释+历史表格），判断快照/验证功能迁移到独立 tab。

**Tech Stack:** React 18 + TypeScript, Recharts（折线图）, CSS（BEM `macro__` 前缀），FastAPI 后端（现有 API 不改）。

## Global Constraints

- CSS 类名统一用 BEM 前缀 `macro__`（与现有一致），状态修饰符用 `--`
- 颜色用 CSS 变量：`--color-accent`/`--color-surface`/`--color-border`/`--color-text`/`--color-text-secondary`/`--color-text-tertiary`；涨跌色：`.is-up`(#ff453a 红)/`.is-down`(#30d158 绿)/`.is-flat`(灰)
- API 基址通过 `getApiBase()` 获取（`src/lib/api.ts`），所有 fetch 用 `${API_BASE}/macro/...`
- 不加新路由/URL 参数——Tab 切换纯 React state
- 后端 API 已全部就绪，不改后端：
  - `GET /macro/dashboard` → `{indicators: IndicatorValue[], latest_view, hit_rate}`
  - `GET /macro/indicators/{code}?limit=N` → `{code, meta, series: [{report_date, value}]}`
  - `GET /macro/views?limit=50` → `MacroView[]`
  - `POST /macro/views/generate` / `POST /macro/views/record`
- 指标 `meta.group` 值域：`growth`/`inflation`/`employment`/`monetary`/`realestate`/`global`
- 指标 `meta.category` 值域：`cn`/`us`
- 线宽/格式：TypeScript 严格模式，`eslint src --ext .ts,.tsx`

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/` (一次性) | 运行 | `python -m src.domain.market.sync.jobs.macro_monthly` |
| `apps/web/src/pages/Macro.tsx` | 重构 | Tab 栏 + 指标卡片网格 + 详情展开面板 + 判断验证 tab |
| `apps/web/src/pages/Macro.css` | 重构 | Tab 样式 + 详情面板 + 历史表格样式 |

**组件分解（Macro.tsx 内部）：**
```
Macro (页面壳 + Tab state + 数据获取)
├── TabBar               (Tab 栏：7 个 tab)
├── IndicatorTab         (指标浏览：卡片网格 + 详情面板)
│   ├── IndicatorCard    (单个指标卡片，点击展开)
│   └── IndicatorDetail  (详情面板：大图+数值+解释+表格)
├── JudgmentTab          (判断与验证：迁移现有快照/验证/记录)
│   ├── LatestSnapshot   (最新判断快照)
│   ├── RecordForm       (手动记录)
│   ├── ViewsTable       (历史验证表)
│   └── ViewDetail       (快照详情侧栏 + K 线)
```

---

### Task 0: 灌入宏观数据（前置，非代码）

**Files:** 无（运行后端 job）

**Interfaces:** 产出一台运行中的后端 + DB 里 ≥30 个指标数据

- [ ] **Step 1: 确保后端在运行**

```bash
curl -s http://localhost:12100/api/v1/macro/dashboard | head -c 100
```
预期：返回 JSON（`{"code":0,...}`）。若未响应，先 `cd backend && .venv/bin/python main.py &`。

- [ ] **Step 2: 运行 macro_monthly 灌数据**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend
.venv/bin/python -m src.domain.market.sync.jobs.macro_monthly 2>&1 | tail -20
```
预期：日志输出每个指标的拉取结果（`[akshare:cn_m1_yoy] +N 行`、`[csv_seed:cn_unemp.csv] +N 行`），最后 `macro_monthly 完成`。部分 akshare 接口可能超时/失败（记 error），不阻塞。

- [ ] **Step 3: 验证数据入库**

```bash
curl -s http://localhost:12100/api/v1/macro/dashboard | python3 -c "
import sys, json
d = json.load(sys.stdin)
inds = d.get('data',{}).get('indicators',[])
print(f'指标数: {len(inds)}')
codes = [i['indicator_code'] for i in inds]
for c in ['cn_m1_yoy','cn_retail_yoy','cn_house_sales_amt','cn_unemp_1624','cn_loan_household']:
    print(f'  {\"✅\" if c in codes else \"❌\"} {c}')
"
```
预期：指标数 ≥ 30，新指标 ✅。

- [ ] **Step 4: 无需 commit（数据写入 DB，非代码变更）**

---

### Task 1: Macro.tsx 重构——Tab 栏 + 指标浏览骨架

**Files:**
- Modify: `apps/web/src/pages/Macro.tsx`（整体重构，保留 types/helpers/判断功能代码）
- Modify: `apps/web/src/pages/Macro.css`（新增 tab 样式）

**Interfaces:**
- Produces: `Macro` 组件的新结构——Tab state (`activeTab`) + `TabBar` + 指标卡片网格。后续 Task 2 加详情面板，Task 3 迁移判断功能。

**背景**：现有 `Macro` 组件（line 276-642）的数据获取逻辑（`fetchDashboard`、`handleGenerate`、`openView`）全部保留。重构的是 render 部分：把指标卡片网格包进 Tab，判断快照/验证先临时保留在页面底部（Task 3 再迁移）。

- [ ] **Step 1: 定义 Tab 配置常量**

在 `Macro.tsx` 的 helpers 区（约 line 170，`IndicatorCard` 组件之前）新增：

```typescript
// ── Tab 配置 ──────────────────────────────────────────────────────────────────
interface TabConfig {
  key: string;
  label: string;
  filter: (ind: IndicatorValue) => boolean;
}

const INDICATOR_TABS: TabConfig[] = [
  {key: 'inflation', label: '通胀',
    filter: (i) => i.meta?.group === 'inflation' && i.meta?.category !== 'us'},
  {key: 'growth', label: '增长·就业',
    filter: (i) => ['growth', 'employment'].includes(i.meta?.group || '')
              && i.meta?.category !== 'us'},
  {key: 'monetary', label: '货币·社融',
    filter: (i) => i.meta?.group === 'monetary' && i.meta?.category !== 'us'},
  {key: 'realestate', label: '房地产',
    filter: (i) => i.meta?.group === 'realestate'},
  {key: 'global', label: '贸易',
    filter: (i) => i.meta?.group === 'global'},
  {key: 'us', label: '美国',
    filter: (i) => i.meta?.category === 'us'},
];
// 判断与验证是特殊 tab，不在 INDICATOR_TABS 里，单独处理
```

- [ ] **Step 2: 重构 Macro 组件——加 Tab state + TabBar**

把现有 `Macro` 组件的 render 部分（line 380-641）替换为以下结构。**保留**所有 useState/useCallback/handlers 不变，只改 JSX：

```typescript
export const Macro: React.FC = () => {
  // ... 所有现有 useState/useCallback/handlers 保持不变 ...
  const [activeTab, setActiveTab] = useState('inflation');
  const [expandedCode, setExpandedCode] = useState<string | null>(null);

  // ... fetchDashboard / handleGenerate / openView / handleRecord 不变 ...

  const indicators = dash?.indicators || [];
  const latestView = dash?.latest_view || null;
  const hitRate = dash?.hit_rate;
  const isJudgmentTab = activeTab === 'judgment';

  // 当前 tab 的指标
  const tabConfig = INDICATOR_TABS.find((t) => t.key === activeTab);
  const tabIndicators = tabConfig
    ? indicators.filter(tabConfig.filter)
    : [];

  return (
    <div className="macro">
      <header className="macro__header">
        <div>
          <h1 className="macro__title">宏观经济</h1>
          <p className="macro__subtitle">
            宏观状态判断 · 美林时钟定位 · 回看验证判断准确性
          </p>
        </div>
      </header>

      {/* ── Tab 栏 ── */}
      <nav className="macro__tabs">
        {INDICATOR_TABS.map((tab) => {
          const count = indicators.filter(tab.filter).length;
          return (
            <button
              key={tab.key}
              className={`macro__tab ${activeTab === tab.key ? 'is-active' : ''}`}
              onClick={() => { setActiveTab(tab.key); setExpandedCode(null); }}
            >
              {tab.label}
              {count > 0 && <span className="macro__tab-count">{count}</span>}
            </button>
          );
        })}
        <button
          className={`macro__tab ${isJudgmentTab ? 'is-active' : ''}`}
          onClick={() => { setActiveTab('judgment'); setExpandedCode(null); }}
        >
          判断与验证
        </button>
      </nav>

      {/* ── 指标浏览区（非判断 tab）── */}
      {!isJudgmentTab && (
        <section className="macro__section">
          {loading ? (
            <div className="macro__indicator-grid">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="macro__indicator-card skeleton"
                     style={{height: 100}} />
              ))}
            </div>
          ) : tabIndicators.length === 0 ? (
            <div className="macro__empty">该分类暂无指标数据</div>
          ) : (
            <div className="macro__indicator-grid">
              {tabIndicators.map((ind) => (
                <IndicatorCard
                  key={ind.indicator_code}
                  ind={ind}
                  expanded={expandedCode === ind.indicator_code}
                  onToggle={() => setExpandedCode(
                    expandedCode === ind.indicator_code
                      ? null : ind.indicator_code)}
                />
              ))}
            </div>
          )}
        </section>
      )}

      {/* ── 判断与验证 tab（Task 3 迁移，暂时占位）── */}
      {isJudgmentTab && (
        <div className="macro__empty">判断与验证（待 Task 3 迁移）</div>
      )}
    </div>
  );
};
```

- [ ] **Step 3: 修改 IndicatorCard 接受 expanded + onToggle props**

现有 `IndicatorCard`（line 172）签名改为：

```typescript
const IndicatorCard: React.FC<{
  ind: IndicatorValue;
  expanded?: boolean;
  onToggle?: () => void;
}> = ({ind, expanded, onToggle}) => {
```

在卡片的根 `<div>` 加 `onClick` 和类名：

```typescript
  return (
    <div
      className={`macro__indicator-card ${expanded ? 'is-expanded' : ''}`}
      onClick={onToggle}
      style={onToggle ? {cursor: 'pointer'} : undefined}
    >
      {/* ... 现有内容不变 ... */}
      {/* Task 2 在这里插入详情面板 */}
    </div>
  );
```

- [ ] **Step 4: 新增 Tab CSS**

在 `Macro.css` 末尾追加：

```css
/* ── Tab 栏 ── */
.macro__tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--color-border);
  margin-bottom: 20px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
.macro__tab {
  padding: 10px 16px;
  border: none;
  background: none;
  color: var(--color-text-secondary);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  border-bottom: 2px solid transparent;
  transition: color 0.15s, border-color 0.15s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.macro__tab:hover { color: var(--color-text); }
.macro__tab.is-active {
  color: var(--color-accent);
  border-bottom-color: var(--color-accent);
}
.macro__tab-count {
  font-size: 11px;
  background: var(--color-surface-raised);
  color: var(--color-text-tertiary);
  padding: 1px 6px;
  border-radius: 8px;
  font-weight: 400;
}
.macro__indicator-card.is-expanded {
  border-color: var(--color-accent);
}
```

- [ ] **Step 5: 验证编译**

```bash
cd apps/web && node_modules/.bin/rsbuild build 2>&1 | tail -5
```
预期：`built in X.Xs`，无 error。若有 TS 报错修复后继续。

- [ ] **Step 6: 验证页面**

```bash
curl -s http://localhost:12000 -o /dev/null -w "%{http_code}"
```
预期：200。

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/pages/Macro.tsx apps/web/src/pages/Macro.css
git commit -m "feat(macro): add tab bar + indicator browse skeleton"
```

---

### Task 2: 指标详情展开面板（大图 + 数值 + 解释 + 表格）

**Files:**
- Modify: `apps/web/src/pages/Macro.tsx`（新增 `IndicatorDetail` 组件，嵌入 `IndicatorCard`）
- Modify: `apps/web/src/pages/Macro.css`（详情面板 + 表格样式）

**Interfaces:**
- Consumes: `IndicatorValue`（Task 1 已定义）、`GET /macro/indicators/{code}?limit=500`
- Produces: `IndicatorDetail` 组件，props `{ ind: IndicatorValue }`

**背景**：详情面板在卡片展开时渲染（`expanded === true`），懒加载完整时序数据。包含 4 个区域：关键数值+徽章、大折线图、指标解释+溯源、历史表格（倒序）。

- [ ] **Step 1: 新增 IndicatorDetail 组件**

在 `IndicatorCard` 组件之后（约 line 274）新增：

```typescript
// ── 指标详情面板（展开时显示）──────────────────────────────────────────────────
const IndicatorDetail: React.FC<{ind: IndicatorValue}> = ({ind}) => {
  const [series, setSeries] = useState<SeriesPoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetch(`${API_BASE}/macro/indicators/${ind.indicator_code}?limit=500`)
      .then((r) => r.json())
      .then((j) => { if (alive) setSeries(j.data?.series || []); })
      .catch(() => { if (alive) setSeries([]); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [ind.indicator_code]);

  const badge = badgeFor(ind);
  const meta = ind.meta;

  // Y 轴区间
  const rangeLow = meta?.range_low ?? null;
  const rangeHigh = meta?.range_high ?? null;
  const dataMin = series.length ? Math.min(...series.map((s) => s.value)) : 0;
  const dataMax = series.length ? Math.max(...series.map((s) => s.value)) : 1;
  const yLow = rangeLow ?? (dataMin - (dataMax - dataMin) * 0.1);
  const yHigh = rangeHigh ?? (dataMax + (dataMax - dataMin) * 0.1);

  // 表格数据：倒序（最新在上）
  const tableRows = [...series].reverse().slice(0, 30);

  return (
    <div className="macro__detail-panel" onClick={(e) => e.stopPropagation()}>
      {/* ① 关键数值 + 徽章 */}
      <div className="macro__detail-head">
        <div className="macro__detail-value">
          <span className="macro__detail-num">
            {fmtNum(ind.value, Math.abs(ind.value) < 10 ? 2 : 0)}
          </span>
          <span className="macro__detail-unit">{meta?.unit}</span>
        </div>
        <div className="macro__detail-meta">
          <span className="macro__detail-date">{ind.report_date}</span>
          {badge && (
            <span className={`macro__detail-badge ${badge.cls}`}>
              {badge.text}
            </span>
          )}
        </div>
      </div>

      {/* ② 完整历史折线图 */}
      <div className="macro__detail-chart">
        {loading ? (
          <div className="macro__empty">加载中…</div>
        ) : series.length < 2 ? (
          <div className="macro__empty">历史数据不足（{series.length} 条）</div>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={series} margin={{top: 10, right: 20, bottom: 10, left: 10}}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis dataKey="report_date" tick={{fontSize: 11, fill: 'var(--color-text-tertiary)'}} />
              <YAxis domain={[yLow, yHigh]} tick={{fontSize: 11, fill: 'var(--color-text-tertiary)'}} />
              <Tooltip
                contentStyle={{
                  background: 'var(--color-surface)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 8,
                  fontSize: 12,
                }}
                labelStyle={{color: 'var(--color-text-secondary)'}}
              />
              {(meta?.reference_lines || []).map((rl, i) => (
                <ReferenceLine
                  key={i}
                  y={rl.value}
                  stroke={refLineColor(rl.severity)}
                  strokeDasharray="4 3"
                  label={{value: rl.label, fill: refLineColor(rl.severity),
                          fontSize: 10, position: 'insideTopLeft'}}
                />
              ))}
              <Line type="monotone" dataKey="value" stroke="var(--color-accent)"
                    strokeWidth={2} dot={{r: 2, fill: 'var(--color-accent)'}} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ③ 指标解释 + 溯源 */}
      {(meta?.explanation || meta?.doc_url || ind.source) && (
        <div className="macro__detail-explain">
          {meta?.explanation && (
            <p className="macro__detail-explain-text">{meta.explanation}</p>
          )}
          <div className="macro__detail-explain-links">
            {meta?.doc_url && (
              <a href={meta.doc_url} target="_blank" rel="noopener noreferrer">
                了解更多 →
              </a>
            )}
            {ind.source && (
              <span className="macro__detail-source">
                数据源：
                {ind.source_url ? (
                  <a href={ind.source_url} target="_blank"
                     rel="noopener noreferrer">{ind.source} ↗</a>
                ) : ind.source}
              </span>
            )}
          </div>
        </div>
      )}

      {/* ④ 历史数值表格 */}
      {tableRows.length > 0 && (
        <div className="macro__detail-table-wrap">
          <table className="macro__detail-table">
            <thead>
              <tr>
                <th>报告日期</th>
                <th>数值</th>
                <th>单位</th>
              </tr>
            </thead>
            <tbody>
              {tableRows.map((row) => (
                <tr key={row.report_date}>
                  <td>{row.report_date}</td>
                  <td>{fmtNum(row.value, Math.abs(row.value) < 10 ? 2 : 0)}</td>
                  <td>{meta?.unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 2: 在 IndicatorCard 展开时渲染详情面板**

修改 `IndicatorCard` 的 return（Task 1 改过的），在卡片内容末尾、闭合 `</div>` 之前插入：

```typescript
      {/* 展开时显示详情面板 */}
      {expanded && <IndicatorDetail ind={ind} />}
```

- [ ] **Step 3: 新增详情面板 CSS**

在 `Macro.css` 末尾追加：

```css
/* ── 指标详情面板 ── */
.macro__detail-panel {
  grid-column: 1 / -1;          /* 占满网格整行 */
  padding: 16px 0 0;
  margin-top: 12px;
  border-top: 1px solid var(--color-border);
}
.macro__detail-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 12px;
}
.macro__detail-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.macro__detail-num {
  font-size: 28px;
  font-weight: 700;
  color: var(--color-text);
}
.macro__detail-unit {
  font-size: 14px;
  color: var(--color-text-tertiary);
}
.macro__detail-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}
.macro__detail-date {
  font-size: 13px;
  color: var(--color-text-secondary);
}
.macro__detail-badge {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--color-surface-raised);
}
.macro__detail-chart {
  margin-bottom: 16px;
}
.macro__detail-explain {
  padding: 12px;
  background: var(--color-surface);
  border-radius: 8px;
  margin-bottom: 16px;
}
.macro__detail-explain-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text-secondary);
  margin: 0 0 8px;
}
.macro__detail-explain-links {
  display: flex;
  gap: 16px;
  align-items: center;
  font-size: 12px;
}
.macro__detail-explain-links a {
  color: var(--color-accent);
  text-decoration: none;
}
.macro__detail-explain-links a:hover { text-decoration: underline; }
.macro__detail-source { color: var(--color-text-tertiary); }
.macro__detail-source a { color: var(--color-text-secondary); }

/* 历史数值表格 */
.macro__detail-table-wrap {
  max-height: 300px;
  overflow-y: auto;
  border: 1px solid var(--color-border);
  border-radius: 8px;
}
.macro__detail-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.macro__detail-table thead {
  position: sticky;
  top: 0;
  background: var(--color-surface-raised);
  z-index: 1;
}
.macro__detail-table th {
  padding: 8px 12px;
  text-align: left;
  font-weight: 600;
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
}
.macro__detail-table td {
  padding: 6px 12px;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border);
}
.macro__detail-table tbody tr:hover {
  background: var(--color-surface);
}
```

- [ ] **Step 4: 验证编译**

```bash
cd apps/web && node_modules/.bin/rsbuild build 2>&1 | tail -5
```
预期：无 error。

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/pages/Macro.tsx apps/web/src/pages/Macro.css
git commit -m "feat(macro): add indicator detail panel with chart+table+explanation"
```

---

### Task 3: 判断与验证功能迁移到独立 Tab

**Files:**
- Modify: `apps/web/src/pages/Macro.tsx`（把判断快照/记录/历史验证的 JSX 迁移到 judgment tab）

**Interfaces:**
- Consumes: Task 1 的 `isJudgmentTab` / `activeTab` state + 所有现有 handlers
- Produces: 完整的 judgment tab 内容（快照 + 记录 + 验证表 + 详情侧栏）

**背景**：现有判断功能代码（`Macro.tsx` line 426-641 的 section 2/2.5/3 + `ViewDetail`/`TrackChart` 组件 line 644-800）全部保留，只把它们的 JSX 从页面主体迁移到 `{isJudgmentTab && (...)}` 块内。Task 1 里这个位置目前是占位 `<div>`。

- [ ] **Step 1: 替换 judgment tab 的占位内容**

找到 Task 1 中写的占位：
```typescript
      {/* ── 判断与验证 tab（Task 3 迁移，暂时占位）── */}
      {isJudgmentTab && (
        <div className="macro__empty">判断与验证（待 Task 3 迁移）</div>
      )}
```

替换为完整的判断功能 JSX（从原版 `Macro` 组件的 section 2、2.5、3 原样搬入，保持 `header` 里移除生成按钮放这里）：

```typescript
      {/* ── 判断与验证 tab ── */}
      {isJudgmentTab && (
        <>
          <div className="macro__judgment-actions">
            <button
              className="macro__generate-btn"
              onClick={handleGenerate}
              disabled={generating}
            >
              {generating ? '生成中…' : '+ 生成判断快照'}
            </button>
          </div>

          {/* 最新判断快照 */}
          <section className="macro__section">
            <h2 className="macro__section-title">最新判断快照</h2>
            {latestView ? (
              <div className="macro__snapshot">
                {/* ── 此处粘贴原版 line 431-506 的快照 JSX（snapshot-header / reading / stance）── */}
              </div>
            ) : (
              <div className="macro__empty">
                {loading ? '加载中…' : '暂无快照。点击上方「生成判断快照」创建第一条。'}
              </div>
            )}
          </section>

          {/* 人记录判断 */}
          <section className="macro__section macro__record-section">
            {/* ── 此处粘贴原版 line 515-566 的记录表单 JSX ── */}
          </section>

          {/* 历史验证对照 */}
          <section className="macro__section">
            <h2 className="macro__section-title">
              历史判断与验证对照
              {hitRate && hitRate.scored_count > 0 && (
                <span className="macro__hitrate">
                  {/* ── 此处粘贴原版 line 573-582 的命中率 JSX ── */}
                </span>
              )}
            </h2>
            {views.length === 0 ? (
              <div className="macro__empty">
                {loading ? '加载中…' : '暂无历史快照'}
              </div>
            ) : (
              <div className="macro__views-table">
                {/* ── 此处粘贴原版 line 589-627 的历史表 JSX ── */}
              </div>
            )}
            {selectedView && (
              <ViewDetail
                view={selectedView}
                trackData={trackData}
                trackLoading={trackLoading}
                onClose={() => setSelectedView(null)}
              />
            )}
          </section>
        </>
      )}
```

**实现说明**：上面标注"粘贴原版 line XXX"的位置，实现时需打开当前 `Macro.tsx`，把对应 section 的 JSX 原样复制进来（这些 JSX 引用的变量 `latestView`/`views`/`selectedView`/`trackData`/`hitRate`/handlers 都在组件作用域内，不需改动）。`ViewDetail` 和 `TrackChart` 组件定义（文件底部）保持原位不动。

- [ ] **Step 2: 移除 header 里的生成按钮**

Task 1 的 header 已经不含生成按钮（只有标题），确认生成按钮只在 judgment tab 的 `.macro__judgment-actions` 里。

新增 `.macro__judgment-actions` 的 CSS（在 `Macro.css` 末尾）：

```css
.macro__judgment-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 16px;
}
```

- [ ] **Step 3: 验证编译**

```bash
cd apps/web && node_modules/.bin/rsbuild build 2>&1 | tail -5
```
预期：无 error。若有"使用了未声明变量"报错，确认对应 JSX 引用的变量都在组件作用域内。

- [ ] **Step 4: 验证页面——指标 tab + 判断 tab 都能正常切换**

```bash
curl -s http://localhost:12000 -o /dev/null -w "%{http_code}"
```
预期：200。

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/pages/Macro.tsx apps/web/src/pages/Macro.css
git commit -m "feat(macro): migrate judgment/validation to dedicated tab"
```

---

### Task 4: 端到端验证 + 最终调整

**Files:** 无（验证性任务，可能有微调）

- [ ] **Step 1: 完整功能验证清单**

手动在浏览器 `http://localhost:12000/macro` 验证：
1. 默认显示"通胀"tab，下方有 CPI/PPI 等卡片
2. 点击其他 tab（增长·就业/货币·社融/房地产/贸易/美国），卡片切换
3. 点击任一指标卡片，展开详情面板（大图+数值+解释+表格）
4. 再点同一卡片，详情收起
5. 点另一卡片，前一个收起、新的展开
6. 点击"判断与验证"tab，能看到快照/记录/历史验证
7. Tab 上有数字角标显示指标数量

- [ ] **Step 2: 检查控制台无报错**

```bash
# 通过 curl 确认页面 HTML 正常返回
curl -s http://localhost:12000/macro | /usr/bin/grep -o '<title>[^<]*</title>'
```

- [ ] **Step 3: 修复发现的问题（如有）**

常见问题及修复：
- Tab 切换后 expandedCode 残留 → Task 1 已在 onClick 里 `setExpandedCode(null)` 处理
- 详情面板 `grid-column: 1/-1` 不生效 → 确认 `macro__indicator-grid` 是 `display: grid`
- 表格在卡片内溢出 → 确认 `macro__detail-table-wrap` 有 `overflow-y: auto`

- [ ] **Step 4: 最终 Commit（如有调整）**

```bash
git status
# 若有改动：
git add apps/web/src/pages/Macro.tsx apps/web/src/pages/Macro.css
git commit -m "fix(macro): e2e adjustments after tab+detail refactor"
```

---

## Self-Review 记录

**Spec 覆盖性**：
- ✅ 问题1（没数据）→ Task 0（灌库）
- ✅ 问题2（时间顺序）→ Task 2 Step 1（表格 `[...series].reverse()` 倒序，最新在上）
- ✅ 问题3（Tab + 详情页）→ Task 1（Tab 栏）+ Task 2（详情面板）+ Task 3（判断迁移）
- ✅ 详情面板四要素（数值+徽章/大图/解释+溯源/表格）→ Task 2 Step 1 全部覆盖
- ✅ 现有功能保留 → Task 3 迁移到 judgment tab

**Placeholder 扫描**：
- Task 3 Step 1 标注"粘贴原版 line XXX"——这是因为原版 JSX 量大（~200 行），完整复制会使计划过长。实现时需对照当前文件复制。这不是占位，是明确的迁移指令。

**类型一致性**：
- `IndicatorValue`/`IndicatorMeta`/`SeriesPoint` 等类型在 Task 1 前已定义（现有代码），Task 2 的 `IndicatorDetail` 引用一致
- `TabConfig` interface 在 Task 1 Step 1 定义，`INDICATOR_TABS` 使用一致
- `expanded`/`onToggle` props 在 Task 1 Step 3 定义，Task 2 Step 2 使用一致

**已知风险**：
1. Task 0 的 `macro_monthly` 可能有部分 akshare 接口超时——不影响整体，失败的指标显示为该 tab 指标数偏少
2. CSV 种子数据只有 2 行，详情面板的历史图表/表格对种子指标会很少——符合预期（后续补数据）
3. Task 3 的"粘贴原版 JSX"需要实现者仔细对照行号——建议实现时先 git diff 确认原版 JSX 范围
