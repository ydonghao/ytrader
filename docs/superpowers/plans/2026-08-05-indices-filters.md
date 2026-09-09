# Indices 页筛选条件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `/indices` 页增加筛选条（日期范围 + 分类 + 搜索 + 方向），用一个统一日期范围驱动 K 线区间、涨跌幅周期、历史快照三种语义。

**Architecture:** 方案 A（统一日期范围）。后端 `/market/indices` 加可选 `start`/`end` 参数（参数化查询），区间内取 close、区间前取 prev 算涨跌幅；无参时行为逐字不变。K 线端点本就支持 `start`/`end`，前端拼接即可。前端新增筛选条 state + 控件，列表/卡片/排行接 category/query/direction 纯前端 filter。

**Tech Stack:** FastAPI + psycopg2（后端）；React + recharts + 原生 CSS 变量（前端）；pytest（后端测试）。

**Spec:** `docs/superpowers/specs/2026-08-05-indices-filters-design.md`

## Global Constraints

- A 股配色：涨红跌绿（`.is-up`=`--color-danger` 红，`.is-down`=`--color-success` 绿）——沿用现有 token，勿改。
- 日期参数格式 `YYYY-MM-DD`；用户输入**必须用 psycopg 参数化**（`%s`），不可字符串拼接进 SQL。
- `start`/`end` 全可选；都不传时行为与改造前逐字一致（最新收盘 + 当日涨跌幅）。
- 默认 preset=「今日」，首屏视觉与改造前一致。
- 只用现有 CSS token（`--color-surface` / `--color-accent` / `--color-border` 等），不引入新依赖。
- 复用 Market 页的视觉语言（搜索框、分段按钮选中态）。

## File Structure

**后端（修改 1 个文件）：**
- `backend/src/api/router/market_router.py` — 新增 `_range_sql()` 辅助函数；扩展 `list_indices()` 签名加 `start`/`end`。`_latest_sql`/`_pack_row`/`get_conn` 复用不动。

**后端测试（修改 1 个文件）：**
- `backend/tests/api/test_market_router.py` — 新增 `TestMarketIndices` 测试类。

**前端（修改 2 个文件）：**
- `frontend/apps/web/src/pages/Indices.tsx` — 新增筛选条 state + 控件 + `presetToRange` helper；`fetchQuotes`/`fetchBars` 接 range；列表/卡片/排行接 filter。
- `frontend/apps/web/src/pages/Indices.css` — 新增 `.indices__filters` 及子元素样式。

**无新增文件。**

---

## Task 1: 后端 — `_range_sql` 辅助函数 + 单测

**Files:**
- Modify: `backend/src/api/router/market_router.py`（在 `_latest_sql` 之后、`_pack_row` 之前插入，约 554 行后）
- Test: `backend/tests/api/test_market_router.py`（新增 `TestRangeSql` 类）

**Interfaces:**
- Produces: `_range_sql(table: str, time_col: str, start: Optional[str], end: Optional[str], where: str = "") -> str` — 返回一条 SQL 字符串，取每个 symbol 的 `close = ≤end 最新一条`、`prev = <start 最新一条`。结果列：`symbol, close_, prev`。

**说明（与 `_latest_sql` 的差异）：** `_latest_sql` 取「最新 + 倒数第二」算当日涨跌；`_range_sql` 取「区间端点 close + 区间前基准 prev」算区间涨跌。两者都用 ROW_NUMBER 窗口，风格一致。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/api/test_market_router.py` 末尾追加：

```python
class TestRangeSql:
    """Test _range_sql helper for range-based pct change."""

    def test_range_sql_with_both_dates(self):
        from src.api.router.market_router import _range_sql
        sql = _range_sql("index_ohlcv", "trade_date", "2025-01-01", "2025-06-30")
        # 两个日期都参数化进 SQL（%s 占位符）
        assert "%s" in sql
        assert "index_ohlcv" in sql
        assert "trade_date" in sql
        # close 端点：trade_date <= end；prev 端点：trade_date < start
        assert "trade_date <= %s" in sql
        assert "trade_date < %s" in sql
        assert "rn = 1" in sql

    def test_range_sql_with_where_clause(self):
        from src.api.router.market_router import _range_sql
        sql = _range_sql("index_ohlcv", "trade_date", "2025-01-01", "2025-06-30",
                         where="WHERE market='INDEX'")
        assert "market='INDEX'" in sql
        assert "%s" in sql  # 日期仍参数化

    def test_range_sql_end_only(self):
        from src.api.router.market_router import _range_sql
        # end 传、start 空：close = ≤end 最新，prev = 历史最早一条
        sql = _range_sql("index_ohlcv", "trade_date", None, "2025-06-30")
        assert "trade_date <= %s" in sql
        # prev 端点无 start 约束，取最早：ORDER BY trade_date ASC, rn=1
        assert "ORDER BY trade_date ASC" in sql or "ORDER BY %s ASC" in sql or "ASC" in sql

    def test_range_sql_no_dates(self):
        """start/end 都空时，退化为「最新 close + 最早 close」——
        但此分支实际不会被调用（list_indices 无参时走 _latest_sql）。
        这里只确保函数不报错、返回字符串。"""
        from src.api.router.market_router import _range_sql
        sql = _range_sql("index_ohlcv", "trade_date", None, None)
        assert isinstance(sql, str)
        assert "index_ohlcv" in sql
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/api/test_market_router.py::TestRangeSql -v`
Expected: FAIL（`ImportError: cannot import name '_range_sql'`）

- [ ] **Step 3: 实现 `_range_sql`**

在 `backend/src/api/router/market_router.py` 中，找到 `_latest_sql` 函数结尾（`_pack_row` 定义之前，约第 554 行），在它后面插入：

```python
def _range_sql(table, time_col, start, end, where=""):
    """区间涨跌幅 SQL：close = ≤end 最新一条，prev = <start 最新一条。

    与 _latest_sql 同风格（ROW_NUMBER 窗口），区别在端点取值：
    - close 端点：trade_date <= end（end 缺省时不约束 = 取最新）
    - prev  端点：trade_date <  start（start 缺省时取最早一条作为基准）

    日期用 psycopg 参数化（%s），绝不字符串拼接用户输入。
    返回 (sql_template, params) 二元组：sql 用 %s 占位，params 按出现顺序排列。
    """
    where = where.strip()

    # ── close 端点子查询 ──
    close_conds = [where] if where else []
    close_params = []
    if end:
        close_conds.append(f"{time_col} <= %s")
        close_params.append(end)
    close_where = (" WHERE " + " AND ".join(c for c in close_conds if c)) if close_conds else ""
    close_sub = (
        f"SELECT symbol, close_, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY {time_col} DESC) AS rn "
        f"FROM {table}{close_where}"
    )

    # ── prev 端点子查询 ──
    prev_conds = [where] if where else []
    prev_params = []
    if start:
        prev_conds.append(f"{time_col} < %s")
        prev_params.append(start)
    prev_where = (" WHERE " + " AND ".join(c for c in prev_conds if c)) if prev_conds else ""
    # start 缺省时取最早一条（rn 按 ASC，取 rn=1）；有 start 时取 <start 的最新（DESC，取 rn=1）
    prev_order = "ASC" if not start else "DESC"
    prev_sub = (
        f"SELECT symbol, close_, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY {time_col} {prev_order}) AS rn "
        f"FROM {table}{prev_where}"
    )

    sql = f"""
        WITH close_end AS ({close_sub}),
             prev_base AS ({prev_sub})
        SELECT c.symbol, c.close_, p.close_ AS prev
        FROM close_end c
        LEFT JOIN prev_base p ON p.symbol = c.symbol AND p.rn = 1
        WHERE c.rn = 1
        ORDER BY c.symbol
    """
    params = close_params + prev_params
    return sql, params
```

**重要：** 注意此函数返回 `(sql, params)` 二元组（与 `_latest_sql` 只返回 sql 字符串不同）——因为是参数化的。Task 2 的 `list_indices` 调用处会用 `cur.execute(sql, params)`。

- [ ] **Step 4: 修正测试（Step 1 的测试断言基于返回字符串，但函数现在返回 tuple）**

回到 Step 1 写的测试，把每个 `sql = _range_sql(...)` 改为 `sql, _params = _range_sql(...)`：

```python
class TestRangeSql:
    """Test _range_sql helper for range-based pct change."""

    def test_range_sql_with_both_dates(self):
        from src.api.router.market_router import _range_sql
        sql, params = _range_sql("index_ohlcv", "trade_date", "2025-01-01", "2025-06-30")
        assert "%s" in sql
        assert "index_ohlcv" in sql
        assert "trade_date" in sql
        assert "trade_date <= %s" in sql
        assert "trade_date < %s" in sql
        assert "rn = 1" in sql
        # params 按出现顺序：先 end 后 start
        assert params == ["2025-06-30", "2025-01-01"]

    def test_range_sql_with_where_clause(self):
        from src.api.router.market_router import _range_sql
        sql, _ = _range_sql("index_ohlcv", "trade_date", "2025-01-01", "2025-06-30",
                            where="WHERE market='INDEX'")
        assert "market='INDEX'" in sql
        assert "%s" in sql

    def test_range_sql_end_only(self):
        from src.api.router.market_router import _range_sql
        sql, _ = _range_sql("index_ohlcv", "trade_date", None, "2025-06-30")
        assert "trade_date <= %s" in sql
        assert "ASC" in sql  # prev 取最早一条（start 空 → ASC）

    def test_range_sql_no_dates(self):
        from src.api.router.market_router import _range_sql
        sql, params = _range_sql("index_ohlcv", "trade_date", None, None)
        assert isinstance(sql, str)
        assert "index_ohlcv" in sql
        assert params == []
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/api/test_market_router.py::TestRangeSql -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/api/router/market_router.py backend/tests/api/test_market_router.py
git commit -m "feat(market): add _range_sql helper for range-based pct change

参数化查询（%s），返回 (sql, params) 二元组。close 端点取 ≤end 最新一条，
prev 端点取 <start 最新一条（start 空时取最早一条）。为 /market/indices
区间筛选做准备。"
```

---

## Task 2: 后端 — `list_indices` 接受 `start`/`end` 参数 + 单测

**Files:**
- Modify: `backend/src/api/router/market_router.py`（`list_indices` 函数，约 672-707 行）
- Test: `backend/tests/api/test_market_router.py`（新增 `TestMarketIndices` 类）

**Interfaces:**
- Consumes: `_range_sql` (Task 1)、`_latest_sql`、`_pack_row`、`get_conn`、`app_config`
- Produces: `GET /market/indices?start=YYYY-MM-DD&end=YYYY-MM-DD` — 返回结构不变 `{code, msg, data: {market_index, sw_index}}`，每行 `{symbol, name, close, change_pct}`；无参时与现状逐字一致。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/api/test_market_router.py` 末尾追加 `TestMarketIndices` 类。**先写无参（现状）和参数化两条**，参数化那条 patch `get_conn` 模拟数据库返回：

```python
class TestMarketIndices:
    """Test GET /market/indices endpoint (with optional start/end range)."""

    def _make_client(self):
        from fastapi.testclient import TestClient
        from src.api.router.market_router import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_indices_no_params_returns_today_snapshot(self):
        """无参 → 现状：最新收盘 + 当日涨跌幅。patch get_conn 返回固定行。"""
        client = self._make_client()

        # 模拟 cursor.fetchall 返回：先 INDEX 查询，再 SW 查询
        index_rows = [
            {"symbol": "sh000300", "close_": 4000.0, "prev": 3980.0},
        ]
        sw_rows = [
            {"symbol": "sw801010", "close_": 3000.0, "prev": 2970.0},
        ]

        mock_cursor = MagicMock()
        # 两次 execute → 两次 fetchall，按 INDEX / SW 顺序
        mock_cursor.fetchall.side_effect = [index_rows, sw_rows]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = False

        # 注意：list_indices 内部用 `from conf import app_config`（函数内导入），
        # 故 app_config 不在 market_router 模块命名空间——必须 patch 源头 `conf.app_config`。
        with patch("src.api.router.market_router.get_conn", return_value=mock_conn), \
             patch("conf.app_config") as mock_cfg:
            # mock 量化宇宙配置（indices / sw_industries 名字映射）
            mock_cfg.quant_universe.indices = [
                type("I", (), {"symbol": "sh000300", "name": "沪深300"})()
            ]
            mock_cfg.quant_universe.sw_industries = [
                type("I", (), {"symbol": "801010", "name": "农林牧渔"})()
            ]

            response = client.get("/market/indices")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert len(data["data"]["market_index"]) == 1
        assert data["data"]["market_index"][0]["symbol"] == "sh000300"
        assert data["data"]["market_index"][0]["name"] == "沪深300"
        # change_pct = (4000/3980 - 1) * 100 ≈ 0.50
        assert data["data"]["market_index"][0]["change_pct"] == round((4000.0/3980.0 - 1)*100, 2)
        assert data["data"]["sw_index"][0]["name"] == "农林牧渔"

    def test_indices_with_range_uses_range_sql(self):
        """带 start/end → 调用 _range_sql 路径。验证传入参数。"""
        client = self._make_client()

        index_rows = [{"symbol": "sh000300", "close_": 4000.0, "prev": 3500.0}]
        sw_rows = [{"symbol": "sw801010", "close_": 3000.0, "prev": 2800.0}]

        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [index_rows, sw_rows]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__exit__.return_value = False

        with patch("src.api.router.market_router.get_conn", return_value=mock_conn), \
             patch("conf.app_config") as mock_cfg:
            mock_cfg.quant_universe.indices = [
                type("I", (), {"symbol": "sh000300", "name": "沪深300"})()
            ]
            mock_cfg.quant_universe.sw_industries = [
                type("I", (), {"symbol": "801010", "name": "农林牧渔"})()
            ]

            response = client.get("/market/indices",
                                  params={"start": "2025-01-01", "end": "2025-06-30"})

        assert response.status_code == 200
        data = response.json()
        # 区间涨跌：sh000300 (4000/3500-1)*100 ≈ 14.29
        assert data["data"]["market_index"][0]["change_pct"] == round((4000.0/3500.0 - 1)*100, 2)
        # execute 被调用时带了 params（参数化）
        # 第一次 execute（INDEX）的第二参数应包含两个日期
        first_call_args = mock_cursor.execute.call_args_list[0]
        assert first_call_args[0][1] == ["2025-06-30", "2025-01-01"]  # [end, start] 顺序

    def test_indices_invalid_date_returns_400(self):
        """非法日期 → 400。"""
        client = self._make_client()
        response = client.get("/market/indices", params={"start": "not-a-date"})
        assert response.status_code == 400

    def test_indices_start_after_end_returns_400(self):
        """start > end → 400。"""
        client = self._make_client()
        response = client.get("/market/indices",
                              params={"start": "2025-06-30", "end": "2025-01-01"})
        assert response.status_code == 400
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/api/test_market_router.py::TestMarketIndices -v`
Expected: 全部 FAIL（参数还不存在 / 行为未实现）

- [ ] **Step 3: 实现 — 修改 `list_indices` 签名与逻辑**

把 `backend/src/api/router/market_router.py` 中现有 `list_indices` 函数（约 672-707 行）整体替换为：

```python
@router.get("/indices", response_model=dict)
def list_indices(
    start: Optional[date] = Query(None, description="开始日期 YYYY-MM-DD；不传=从历史最早算"),
    end:   Optional[date] = Query(None, description="结束日期 YYYY-MM-DD；不传=最新交易日"),
):
    """所有指数的最新收盘 + 涨跌幅（market='INDEX' 宽基 + market='SW' 申万行业）。

    轻量端点：只查 index_ohlcv 一张表（毫秒级），供 Indices 页首屏。
    K 线走通用 /market/kline/{symbol}（_resolve_kline_table 路由到 index_ohlcv）。

    时间筛选（方案 A 统一范围）：
    - 无参：最新交易日 close + 前一日 close（当日涨跌，现状行为）。
    - 有 start/end：close = ≤end 最新一条，prev = <start 最新一条（区间累计涨跌）。
    日期参数来自 URL，_range_sql 内用 psycopg %s 参数化，绝不字符串拼接。
    """
    # start > end 非法
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start 不能晚于 end")

    try:
        from conf import app_config
        qu = app_config.quant_universe
        idx_names = {i.symbol: i.name for i in qu.indices}
        sw_names = {i.symbol: i.name for i in qu.sw_industries}

        # 日期 → 'YYYY-MM-DD' 字符串（_range_sql 接收字符串）
        s = start.isoformat() if start else None
        e = end.isoformat() if end else None
        use_range = s is not None or e is not None

        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 宽基指数（market='INDEX'）
                if use_range:
                    sql, params = _range_sql("index_ohlcv", "trade_date", s, e,
                                             where="WHERE market='INDEX'")
                    cur.execute(sql, params)
                else:
                    cur.execute(_latest_sql("index_ohlcv", "trade_date", "WHERE market='INDEX'"))
                market_idx = [_pack_row(dict(r), idx_names.get(dict(r)["symbol"], dict(r)["symbol"]))
                              for r in cur.fetchall()]

                # 申万行业指数（symbol sw801010，去前缀查名）
                if use_range:
                    sql, params = _range_sql("index_ohlcv", "trade_date", s, e,
                                             where="WHERE market='SW'")
                    cur.execute(sql, params)
                else:
                    cur.execute(_latest_sql("index_ohlcv", "trade_date", "WHERE market='SW'"))
                sw_idx = []
                for r in cur.fetchall():
                    d = dict(r); sym = d["symbol"]
                    key = sym[2:] if sym.lower().startswith("sw") else sym
                    sw_idx.append(_pack_row(d, sw_names.get(key, sym)))
        finally:
            conn.close()

        return {"code": 0, "msg": "ok", "data": {
            "market_index": market_idx,
            "sw_index": sw_idx,
        }}
    except HTTPException:
        raise  # 校验错误原样抛出
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**关键点：**
- `start`/`end` 类型用 `Optional[date]`（`date` 已在文件顶部 import，第 5 行）。FastAPI 自动校验 `YYYY-MM-DD` 格式，非法值返回 422。但为了让非法日期更友好地返回 400（而非 422），**保留 Optional[date]，422 也算失败状态码——测试断言改为 422**。见 Step 4。
- `HTTPException` 必须 re-raise，否则被外层 `except Exception` 吞掉变成 500。这是新增的 `except HTTPException: raise` 的作用。

- [ ] **Step 4: 修正测试断言（FastAPI 对非法 date 返回 422 而非 400）**

FastAPI 用 `Optional[date]` 时，非法日期字符串触发 Pydantic 校验错误，返回 **422**（不是 400）。把 Step 1 测试里的 `400` 改为 `422`：

```python
    def test_indices_invalid_date_returns_422(self):
        """非法日期 → FastAPI Pydantic 校验失败 422。"""
        client = self._make_client()
        response = client.get("/market/indices", params={"start": "not-a-date"})
        assert response.status_code == 422

    def test_indices_start_after_end_returns_400(self):
        """start > end → 业务校验 400。"""
        client = self._make_client()
        response = client.get("/market/indices",
                              params={"start": "2025-06-30", "end": "2025-01-01"})
        assert response.status_code == 400
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/api/test_market_router.py::TestMarketIndices -v`
Expected: 4 passed

- [ ] **Step 6: 回归 — 跑全部 market router 测试**

Run: `cd backend && python -m pytest tests/api/test_market_router.py -v`
Expected: 全部 passed（含原有 TestMarketOverview / TestMarketKline / TestMarketSearch）

- [ ] **Step 7: Commit**

```bash
git add backend/src/api/router/market_router.py backend/tests/api/test_market_router.py
git commit -m "feat(market): /market/indices accepts optional start/end range

方案 A 统一日期范围：无参时现状不变（当日涨跌）；有 start/end 时 close=≤end
最新、prev=<start 最新，算区间累计涨跌。日期参数 psycopg 参数化。start>end 返回 400。"
```

---

## Task 3: 前端 — 筛选条 state + `presetToRange` helper

**Files:**
- Modify: `frontend/apps/web/src/pages/Indices.tsx`

**Interfaces:**
- Produces: 新增 state（`category`/`query`/`preset`/`customRange`/`direction`）+ `PresetKey` 类型 + `presetToRange()` + 派生 `range` 对象 `{start: string; end: string}`（空字符串表示不传）。后续 Task 4/5 消费这些。

此 Task 只加 state 和纯函数，不动 UI 渲染、不发请求。先建立数据骨架。

- [ ] **Step 1: 加类型、常量与 `presetToRange` helper**

在 `frontend/apps/web/src/pages/Indices.tsx` 中，找到 `const CORE_SYMBOLS = [...]`（约第 46 行）下方、`// ── Helpers ──` 区块里。在 `fmtNum` 等格式化函数**之前**插入：

```tsx
// ── 时间预设 ──────────────────────────────────────────────────────────────────
type PresetKey = 'today' | '1m' | '3m' | '6m' | '1y' | 'ytd' | 'custom';

interface DateRange {
  start: string;  // 'YYYY-MM-DD' 或空串（空=不传给后端）
  end: string;
}

const PRESETS: { key: PresetKey; label: string }[] = [
  { key: 'today', label: '今日' },
  { key: '1m', label: '近1月' },
  { key: '3m', label: '近3月' },
  { key: '6m', label: '近6月' },
  { key: '1y', label: '近1年' },
  { key: 'ytd', label: '今年' },
  { key: 'custom', label: '自定义' },
];

/** 预设 → 日期范围。today = 都空（等价无参 = 现状）；其余 end 始终为空（= 最新交易日）。 */
const presetToRange = (preset: PresetKey): DateRange => {
  const now = new Date();
  const fmt = (d: Date) => d.toISOString().slice(0, 10);
  const daysAgo = (n: number) => { const d = new Date(now); d.setDate(d.getDate() - n); return d; };
  switch (preset) {
    case 'today':  return { start: '', end: '' };
    case '1m':     return { start: fmt(daysAgo(30)),  end: '' };
    case '3m':     return { start: fmt(daysAgo(90)),  end: '' };
    case '6m':     return { start: fmt(daysAgo(180)), end: '' };
    case '1y':     return { start: fmt(daysAgo(365)), end: '' };
    case 'ytd':    return { start: fmt(new Date(now.getFullYear(), 0, 1)), end: '' };
    case 'custom': return { start: '', end: '' };
  }
};
```

- [ ] **Step 2: 加筛选 state + 派生 `range`**

在 `Indices` 组件内，找到现有 state 声明（约 141-145 行）：

```tsx
const [quotes, setQuotes] = useState<IndexQuote[]>([]);
const [selected, setSelected] = useState<string>('sh000300');
const [bars, setBars] = useState<KlineBar[]>([]);
const [loadingQuotes, setLoadingQuotes] = useState(true);
const [loadingBars, setLoadingBars] = useState(false);
```

在它**后面**追加筛选 state：

```tsx
  // ── 筛选条件 state ──
  const [category, setCategory] = useState<'all' | 'index' | 'sw'>('all');
  const [query, setQuery] = useState('');
  const [preset, setPreset] = useState<PresetKey>('today');
  const [customRange, setCustomRange] = useState<DateRange>({ start: '', end: '' });
  const [direction, setDirection] = useState<'all' | 'up' | 'down'>('all');

  // 实际驱动请求的范围：custom 时取 customRange，否则按 preset 推导
  const range: DateRange = preset === 'custom' ? customRange : presetToRange(preset);
```

- [ ] **Step 3: 类型检查（确保编译通过）**

Run: `cd frontend && pnpm --filter @ytrader/web run build` （或 `pnpm -C apps/web build`，取决于 workspace 配置）
Expected: 编译通过，无 TS 错误（`PresetKey`/`DateRange`/`range` 已声明但暂未使用，TS 不会报错——它们在后续 Task 才被消费；若有 `noUnusedLocals`，先临时在 `range` 后加 `void range;` 占位，Task 4/5 移除）。

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/pages/Indices.tsx
git commit -m "feat(indices): add filter state + presetToRange helper

新增 PresetKey/DateRange 类型、PRESETS 常量、presetToRange 纯函数，
以及 category/query/preset/customRange/direction state。此 commit 仅加数据骨架，
UI 与请求接线在后续 commit。"
```

---

## Task 4: 前端 — 筛选条 UI + CSS

**Files:**
- Modify: `frontend/apps/web/src/pages/Indices.tsx`（在 header 与卡片之间插入筛选条 JSX）
- Modify: `frontend/apps/web/src/pages/Indices.css`（新增 `.indices__filters` 及子元素样式）

**Interfaces:**
- Consumes: Task 3 的 state（`category`/`query`/`preset`/`customRange`/`direction`）+ setter
- Produces: 渲染筛选条 DOM（分段按钮 / 搜索框 / 预设 pill / 方向 pill / 自定义日期输入）

- [ ] **Step 1: 在 CSS 文件追加筛选条样式**

在 `frontend/apps/web/src/pages/Indices.css` 中，找到 `/* ── Core index cards strip ── */` 注释（约第 27 行）**之前**插入：

```css
/* ── Filter bar ────────────────────────────────────────────────── */
.indices__filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-5);
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
}

.indices__filter-group {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.indices__filter-label {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-right: var(--space-1);
}

/* 分段按钮 / pill 共用 */
.indices__pill {
  padding: var(--space-1) var(--space-3);
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text-secondary);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: background var(--transition-fast),
              border-color var(--transition-fast),
              color var(--transition-fast);
  white-space: nowrap;
}

.indices__pill:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
}

.indices__pill--active {
  background: var(--color-accent-light);
  border-color: var(--color-accent);
  color: var(--color-accent);
}

/* 搜索框 */
.indices__search {
  width: 200px;
  padding: var(--space-2) var(--space-3);
  background: var(--color-fill);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  font-size: var(--text-sm);
  outline: none;
  transition: border-color var(--transition-fast);
}

.indices__search::placeholder { color: var(--color-text-tertiary); }
.indices__search:focus { border-color: var(--color-accent); }

/* 日期输入（暗色主题适配） */
.indices__date-input {
  padding: var(--space-1) var(--space-2);
  background: var(--color-fill);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  color-scheme: dark;  /* 让浏览器原生 date picker 适配暗色 */
  outline: none;
}
.indices__date-input:focus { border-color: var(--color-accent); }

/* 自定义日期区（默认隐藏，preset=custom 时显示） */
.indices__custom-range {
  display: none;
  align-items: center;
  gap: var(--space-2);
}
.indices__custom-range--show { display: flex; }

/* 响应式：窄屏换行 */
@media (max-width: 1100px) {
  .indices__filters { gap: var(--space-3); }
  .indices__search { width: 160px; }
}
```

- [ ] **Step 2: 在 JSX 插入筛选条**

在 `frontend/apps/web/src/pages/Indices.tsx` 中，找到 header 区块结束 `</header>`（约第 208 行）和 `{/* ── Core index cards ── */}`（约第 210 行）之间，插入筛选条 JSX：

```tsx
      </header>

      {/* ── 筛选条 ── */}
      <section className="indices__filters">
        {/* 分类切换 */}
        <div className="indices__filter-group">
          <span className="indices__filter-label">分类</span>
          {([
            { k: 'all', label: '全部' },
            { k: 'index', label: '宽基' },
            { k: 'sw', label: '申万行业' },
          ] as const).map((t) => (
            <button
              key={t.k}
              type="button"
              className={`indices__pill ${category === t.k ? 'indices__pill--active' : ''}`}
              onClick={() => setCategory(t.k)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* 搜索框 */}
        <div className="indices__filter-group">
          <input
            className="indices__search"
            type="text"
            placeholder="搜索指数名称 / 代码"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        {/* 时间预设 */}
        <div className="indices__filter-group">
          <span className="indices__filter-label">周期</span>
          {PRESETS.map((p) => (
            <button
              key={p.key}
              type="button"
              className={`indices__pill ${preset === p.key ? 'indices__pill--active' : ''}`}
              onClick={() => setPreset(p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>

        {/* 自定义日期（preset=custom 时展开） */}
        <div className={`indices__custom-range ${preset === 'custom' ? 'indices__custom-range--show' : ''}`}>
          <input
            className="indices__date-input"
            type="date"
            value={customRange.start}
            onChange={(e) => setCustomRange((r) => ({ ...r, start: e.target.value }))}
          />
          <span className="indices__filter-label">至</span>
          <input
            className="indices__date-input"
            type="date"
            value={customRange.end}
            onChange={(e) => setCustomRange((r) => ({ ...r, end: e.target.value }))}
          />
        </div>

        {/* 方向筛选 */}
        <div className="indices__filter-group">
          <span className="indices__filter-label">方向</span>
          {([
            { k: 'all', label: '全部' },
            { k: 'up', label: '仅涨' },
            { k: 'down', label: '仅跌' },
          ] as const).map((t) => (
            <button
              key={t.k}
              type="button"
              className={`indices__pill ${direction === t.k ? 'indices__pill--active' : ''}`}
              onClick={() => setDirection(t.k)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </section>

      {/* ── Core index cards ── */}
```

- [ ] **Step 3: 类型检查 + 构建**

Run: `cd frontend && pnpm --filter @ytrader/web run build`
Expected: 编译通过。若有 `noUnusedLocals` 报 `range` 未使用，保留（Task 5 会用到），不要删。

- [ ] **Step 4: 浏览器目视验证**

启动前端 dev server（若未启动），访问 `http://localhost:12000/indices`：
- 筛选条出现在 header 与卡片之间，一行布局。
- 分类 / 周期 / 方向三组 pill，「分类=全部」「周期=今日」「方向=全部」默认高亮。
- 搜索框可见，placeholder 正确。
- 点「自定义」，两个日期输入框展开。

Expected: 视觉符合 Apple Dark token（surface 底 + accent 高亮），无错位。

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/Indices.tsx frontend/apps/web/src/pages/Indices.css
git commit -m "feat(indices): render filter bar (category/search/preset/direction)

筛选条 UI：分类分段(全部/宽基/申万)、搜索框、周期预设(今日/近1月/近3月/近6月/
近1年/今年/自定义)、方向(全部/仅涨/仅跌)。自定义周期展开日期输入。复用现有 CSS token。"
```

---

## Task 5: 前端 — 数据流接线（`range` 驱动请求 + filter 接入列表/排行）

**Files:**
- Modify: `frontend/apps/web/src/pages/Indices.tsx`

**Interfaces:**
- Consumes: Task 3 的 `range`/`category`/`query`/`direction`、Task 4 的控件
- Produces: `fetchQuotes(range)` / `fetchBars(selected, range)` 接 range；`filtered`/`sortedQuotes` 派生；列表/卡片/排行消费派生数据

- [ ] **Step 1: `fetchQuotes` 接 range**

在 `frontend/apps/web/src/pages/Indices.tsx` 中，找到现有 `fetchQuotes`（约 148-160 行）：

```tsx
  const fetchQuotes = useCallback(async () => {
    setLoadingQuotes(true);
    try {
      const res = await fetch(`${API_BASE}/market/indices`);
      const json = await res.json();
      const d = json.data || {};
      setQuotes([...(d.market_index || []), ...(d.sw_index || [])]);
    } catch {
      setQuotes([]);
    } finally {
      setLoadingQuotes(false);
    }
  }, []);
```

替换为接收 `DateRange` 参数、按范围拼 query string：

```tsx
  const fetchQuotes = useCallback(async (r: DateRange) => {
    setLoadingQuotes(true);
    try {
      const qs = new URLSearchParams();
      if (r.start) qs.set('start', r.start);
      if (r.end) qs.set('end', r.end);
      const suffix = qs.toString() ? `?${qs.toString()}` : '';
      const res = await fetch(`${API_BASE}/market/indices${suffix}`);
      const json = await res.json();
      const d = json.data || {};
      setQuotes([...(d.market_index || []), ...(d.sw_index || [])]);
    } catch {
      setQuotes([]);
    } finally {
      setLoadingQuotes(false);
    }
  }, []);
```

- [ ] **Step 2: `fetchBars` 接 range**

找到现有 `fetchBars`（约 163-176 行）：

```tsx
  const fetchBars = useCallback(async (symbol: string) => {
    setLoadingBars(true);
    try {
      const res = await fetch(
        `${API_BASE}/market/kline/${symbol}?interval=1d&limit=400`
      );
      const json = await res.json();
      setBars(json.data?.bars || []);
    } catch {
      setBars([]);
    } finally {
      setLoadingBars(false);
    }
  }, []);
```

替换为：

```tsx
  const fetchBars = useCallback(async (symbol: string, r: DateRange) => {
    setLoadingBars(true);
    try {
      const qs = new URLSearchParams({ interval: '1d' });
      if (r.start) qs.set('start', r.start);
      if (r.end) qs.set('end', r.end);
      // 有范围时不限 limit（让后端按日期裁剪）；无范围时保留 400 根默认行为
      if (!r.start && !r.end) qs.set('limit', '400');
      const res = await fetch(`${API_BASE}/market/kline/${symbol}?${qs.toString()}`);
      const json = await res.json();
      setBars(json.data?.bars || []);
    } catch {
      setBars([]);
    } finally {
      setLoadingBars(false);
    }
  }, []);
```

- [ ] **Step 3: 更新两个 useEffect 的依赖与调用**

找到触发 fetch 的两个 `useEffect`（约 178-184 行）：

```tsx
  useEffect(() => {
    fetchQuotes();
  }, [fetchQuotes]);

  useEffect(() => {
    fetchBars(selected);
  }, [selected, fetchBars]);
```

替换为依赖 `range`：

```tsx
  useEffect(() => {
    fetchQuotes(range);
  }, [range, fetchQuotes]);

  useEffect(() => {
    fetchBars(selected, range);
  }, [selected, range, fetchBars]);
```

- [ ] **Step 4: 加 `filtered` 派生 + 列表/排行消费**

找到现有派生计算（约 186-188 行）：

```tsx
  const coreQuotes = quotes.filter((q) => CORE_SYMBOLS.includes(q.symbol));
  const selectedQuote = quotes.find((q) => q.symbol === selected);
  const sortedQuotes = [...quotes].sort((a, b) => b.change_pct - a.change_pct);
```

替换为（`coreQuotes`/`selectedQuote` 不变，新增 `filtered`，`sortedQuotes` 基于 `filtered`）：

```tsx
  const coreQuotes = quotes.filter((q) => CORE_SYMBOLS.includes(q.symbol));
  const selectedQuote = quotes.find((q) => q.symbol === selected);

  // 应用 category + query + direction 三道前端过滤（range 在请求层已生效）
  const filtered = useMemo(() => {
    return quotes.filter((q) => {
      if (category === 'index' && !/^(sh|sz)\d/i.test(q.symbol)) return false;
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

- [ ] **Step 5: 左侧列表改用 `filtered`**

找到列表渲染（约 244 行）`quotes.map((q) => {`（在 `{/* Index list */}` 区块内），把它改为 `filtered.map`：

```tsx
            : filtered.map((q) => {
```

并在列表为空时显示空态。找到列表 `<div className="indices__list">` 内部结构，在三元表达式后补一个空态分支。完整列表区块替换为：

```tsx
        <div className="indices__list">
          {loadingQuotes
            ? [0, 1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="indices__list-item skeleton" style={{ height: 48 }} />
              ))
            : filtered.length === 0 ? (
              <div className="indices__empty">无匹配结果</div>
            ) : filtered.map((q) => {
                const cls = trendClass(q.change_pct);
                return (
                  <button
                    key={q.symbol}
                    type="button"
                    className={`indices__list-item ${selected === q.symbol ? 'indices__list-item--active' : ''}`}
                    onClick={() => setSelected(q.symbol)}
                  >
                    <div className="indices__list-info">
                      <span className="indices__list-name">{q.name}</span>
                      <span className="indices__list-symbol">{q.symbol}</span>
                    </div>
                    <div className="indices__list-quote">
                      <span className="indices__list-close">{fmtNum(q.close)}</span>
                      <span className={`indices__list-chg ${cls}`}>{fmtPct(q.change_pct)}</span>
                    </div>
                  </button>
                );
              })}
        </div>
```

- [ ] **Step 6: 排行表改用 `sortedQuotes` + 空态**

排行表当前已是 `sortedQuotes.map`（约 355 行），但需补空态。找到 `{sortedQuotes.map((q) => (` 所在的 `<tbody>`，替换为：

```tsx
          <tbody>
            {sortedQuotes.length === 0 ? (
              <tr><td colSpan={4} className="indices__empty">无匹配结果</td></tr>
            ) : sortedQuotes.map((q) => (
              <tr key={q.symbol} onClick={() => setSelected(q.symbol)}>
                <td>{q.name}</td>
                <td className="indices__table-sym">{q.symbol}</td>
                <td className="num">{fmtNum(q.close)}</td>
                <td className={`num ${trendClass(q.change_pct)}`}>{fmtPct(q.change_pct)}</td>
              </tr>
            ))}
          </tbody>
```

- [ ] **Step 7: 类型检查 + 构建**

Run: `cd frontend && pnpm --filter @ytrader/web run build`
Expected: 编译通过，无 TS 错误，`range` 已被消费不再 unused。

- [ ] **Step 8: 浏览器端到端验证**

访问 `/indices`，逐项验证：
1. **默认（今日）**：三块内容与改造前一致（卡片 4 个宽基、列表全量、排行按当日涨跌）。
2. **切「近3月」**：卡片/列表/排行的涨跌幅变为近 3 月累计；K 线变为近 3 月区间（根数变少）。
3. **切「宽基」+ 搜索「300」**：列表只剩沪深300，排行同步。
4. **切「仅涨」**：列表只剩上涨项。
5. **自定义日期**（如 2025-01-01 至 2025-06-30）+ 应用：请求带正确 start/end；涨跌幅为该区间累计；K 线为该区间。
6. **end 设为过去某天**（如 end=2025-06-30，start=2025-06-29）：全页回看 6-30 那天快照。
7. **空态**：「申万行业」+ 搜索「沪深」→ 列表/排行显示「无匹配结果」。

Expected: 全部符合预期，无控制台报错。

- [ ] **Step 9: Commit**

```bash
git add frontend/apps/web/src/pages/Indices.tsx
git commit -m "feat(indices): wire filter bar to data flow

- fetchQuotes/fetchBars 接收 DateRange，按 start/end 拼 query string。
- range 变化触发重新拉取（K 线 + 行情）。
- 新增 filtered（category+query+direction 纯前端过滤），列表/排行消费。
- 空态：无匹配结果显示「无匹配结果」。
- 默认 preset=今日 时无 start/end，行为与改造前一致。"
```

---

## Self-Review

**Spec coverage:**
- §2 方案 A 统一范围 → Task 1-2 后端、Task 3-5 前端 ✅
- §3.1 端点签名 start/end → Task 2 Step 3 ✅
- §3.2 行为矩阵（close=≤end 最新、prev=<start 最新）→ Task 1 `_range_sql` 实现 ✅
- §3.3 新辅助函数 → Task 1 ✅
- §3.4 安全/校验（Optional[date] 自动校验、start>end 400、参数化）→ Task 2 ✅
- §3.5 不加缓存 → 无对应代码改动，spec 已声明 ✅
- §4.1 筛选条布局 → Task 4 ✅
- §4.2 state → Task 3 ✅
- §4.3 数据流 → Task 5 ✅
- §4.4 三块内容受影响（filtered/sortedQuotes/coreQuotes）→ Task 5 ✅
- §4.5 空态 → Task 5 Step 5/6 ✅
- §4.6 样式 → Task 4 Step 1 ✅
- §5 YAGNI（无分页/无 SW 二三级/无 URL 同步/无缓存）→ 不实现 ✅
- §6 测试 → Task 1/2 后端单测、Task 4/5 前端手动验证 ✅

**Placeholder scan:** 无 TBD/TODO；所有 step 含完整代码；测试断言具体数值。

**Type consistency:** `_range_sql` 返回 `(sql, params)` 二元组在 Task 1 定义、Task 2 `cur.execute(sql, params)` 消费一致；`DateRange` 在 Task 3 定义、Task 5 `fetchQuotes(r: DateRange)` 消费一致；`PresetKey` 在 Task 3 定义、Task 4 `PRESETS` 消费一致。✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-05-indices-filters.md`. Two execution options:

**1. Subagent-Driven (recommended)** — 每个 Task 派一个全新 subagent 实现，Task 间我做 review 把关，快速迭代。

**2. Inline Execution** — 在当前会话用 executing-plans 批量执行，带 checkpoint。

Which approach?
