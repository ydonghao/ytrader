# 宏观经济数据月度同步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每月 1 日定时用 akshare 拉取 24 个宏观经济指标入库，CSV 种子补齐 akshare 缺失的 11 个指标，并下载《产业结构调整指导目录(2024年本)》PDF 存档。

**Architecture:** 扩展现有 `macro_sync` 架构（方案 A）。在 `AkshareProvider._MACRO_EXTRACTORS` 注册表新增 15 条提取器；在 `conf/config.yaml` 的 `macro_universe.indicators` 追加指标元数据；新建 `macro_monthly.py` job 编排 akshare 拉取 + CSV 种子导入；调度器加每月 cron；PDF 单独下载存档。

**Tech Stack:** Python 3.13, akshare 1.18.50, SQLModel/SQLAlchemy, APScheduler (AsyncIOScheduler), pytest, PyYAML config.

## Global Constraints

- 线宽 79，black + isort（skip-string-normalization: false），flake8（max-line-length 79, ignore E203/W503）
- 测试框架 pytest，命令 `.venv/bin/python -m pytest <path> -v`
- 不新增数据库表，复用 `macro_indicator` / `macro_indicator_meta`
- akshare 接口失败时记日志跳过，不阻塞其他指标（沿用现有 try/except 模式）
- CSV 种子写入时 `source`/`provider` 字段标明出处，与 akshare 数据可区分溯源
- 多个 akshare 接口返回时间倒序，提取器末端统一 `out.sort(key=lambda x: x[0])` 升序
- 配置项 schema 严格对齐 `conf/settings.py:MacroIndicatorConfig`（line 166）

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/src/domain/market/sync/providers/akshare_provider.py` | Modify | `_MACRO_EXTRACTORS` 新增 15 条 + `_MACRO_DERIVED` 派生指标方法 |
| `backend/conf/config.yaml` | Modify | `macro_universe.indicators` 追加 15 条指标元数据 |
| `backend/src/domain/market/sync/jobs/macro_monthly.py` | Create | 月度同步 job：akshare 拉取 + 社融拆解 + 派生 + CSV 种子 + meta |
| `backend/src/domain/market/sync/jobs/__init__.py` | n/a | 已存在 |
| `backend/src/infra/scheduler.py` | Modify | 追加 `macro_monthly` cron job |
| `backend/scripts/seed/macro/*.csv` + `README.md` | Create | 9 个 CSV 种子文件 + 说明 |
| `backend/tests/domain/market/sync/jobs/test_macro_monthly.py` | Create | job 集成测试 |
| `backend/tests/domain/market/sync/providers/test_akshare_provider.py` | Modify | 新提取器单测 |
| `docs/产业结构调整指导目录-2024年本.pdf` | Create | 发改委官方 PDF 存档 |

**数据流：**
```
scheduler (cron day=1 04:30)
  → macro_monthly.run()
    → AkshareProvider.fetch_macro_series(code)  [A/B 档]
    → AkshareProvider.fetch_macro_derived(code) [存款占比]
    → _seed_from_csv()                          [C 档]
    → MacroIndicatorRepository.upsert()         [统一落库]
    → _sync_indicator_meta()                    [元数据]
```

---

### Task 1: 下载《产业结构调整指导目录(2024年本)》PDF 存档

**Files:**
- Create: `docs/产业结构调整指导目录-2024年本.pdf`

**Interfaces:** 无（独立交付物）

- [ ] **Step 1: 下载 PDF**

```bash
curl -L -o "docs/产业结构调整指导目录-2024年本.pdf" \
  "https://www.ndrc.gov.cn/xxgk/zcfb/fzggwl/202312/P020231229700886191069.pdf"
```

- [ ] **Step 2: 验证文件完整**

```bash
ls -lh "docs/产业结构调整指导目录-2024年本.pdf"
file "docs/产业结构调整指导目录-2024年本.pdf"
```
预期：文件大小 > 1MB，`file` 输出含 `PDF document`。

- [ ] **Step 3: Commit**

```bash
git add "docs/产业结构调整指导目录-2024年本.pdf"
git commit -m "docs: add 产业结构调整指导目录(2024年本) PDF archive"
```

---

### Task 2: akshare_provider 新增 M1/社零/商品房销售额/面积/工业增加值 提取器

**Files:**
- Modify: `backend/src/domain/market/sync/providers/akshare_provider.py`（`_MACRO_EXTRACTORS` 字典，约 line 534-617）
- Test: `backend/tests/domain/market/sync/providers/test_akshare_provider.py`

**Interfaces:**
- Produces: `AkshareProvider._MACRO_EXTRACTORS["cn_m1_yoy"]` / `["cn_retail_yoy"]` / `["cn_house_sales_amt"]` / `["cn_house_sales_area"]` / `["cn_industrial_yoy"]` —— 后续 macro_monthly job 按 code 调 `fetch_macro_series(code)` 拉取。

**背景**：这些接口的 DataFrame 列名已在探测阶段确认：
- `macro_china_money_supply`：列含 `月份`、`货币(狭义货币M1)`、`货币(狭义货币M1)同比增长`
- `macro_china_consumer_goods_retail`：列含 `月份`、`当月-同比增长`
- `macro_china_hk_building_amount`：列含 `发布日期`（或`时间`）、`现值`
- `macro_china_hk_building_volume`：同上结构
- `macro_china_industrial_production_yoy`：列含 `日期`、`今值`（英为财情 5 列格式）

- [ ] **Step 1: 写失败测试**

在 `test_akshare_provider.py` 末尾追加：

```python
# ── macro_monthly 新增提取器 ────────────────────────────────────────
def _money_supply_df():
    """模拟 ak.macro_china_money_supply（含 M1 列）"""
    return pd.DataFrame({
        "月份": ["2026年05月份", "2026年06月份"],
        "货币和准货币（M2）同比增长": [8.1, 7.8],
        "货币(狭义货币M1)同比增长": [1.2, 1.5],
    })


def test_extract_cn_m1_yoy(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(mod.ak, "macro_china_money_supply", lambda: _money_supply_df())
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_series("cn_m1_yoy")
    assert len(rows) == 2
    # 升序：5月在6月前
    assert rows[0][0] == date(2026, 5, 1)
    assert rows[0][1] == 1.2
    assert rows[1][0] == date(2026, 6, 1)
    assert rows[1][1] == 1.5


def _retail_df():
    """模拟 ak.macro_china_consumer_goods_retail"""
    return pd.DataFrame({
        "月份": ["2026年05月份", "2026年06月份"],
        "当月-同比增长": [2.4, 3.1],
    })


def test_extract_cn_retail_yoy(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(mod.ak, "macro_china_consumer_goods_retail",
                        lambda: _retail_df())
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_series("cn_retail_yoy")
    assert len(rows) == 2
    assert rows[0][0] == date(2026, 5, 1)
    assert rows[0][1] == 2.4


def _building_amt_df():
    """模拟 ak.macro_china_hk_building_amount（英为财情 4 列）"""
    return pd.DataFrame({
        "时间": ["2026-05", "2026-06"],
        "前值": [78000, 80000],
        "现值": [80000, 82845],
        "发布日期": ["2026-06-15", "2026-07-15"],
    })


def test_extract_cn_house_sales_amt(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(mod.ak, "macro_china_hk_building_amount",
                        lambda: _building_amt_df())
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_series("cn_house_sales_amt")
    assert len(rows) == 2
    # 用发布日期作为 report_date，现值作为 value
    assert rows[0][0] == date(2026, 6, 15)
    assert rows[0][1] == 80000.0


def _industrial_df():
    """模拟 ak.macro_china_industrial_production_yoy（英为财情 5 列）"""
    return pd.DataFrame({
        "商品": ["中国工业生产年率"] * 2,
        "日期": ["2026-06-10", "2026-07-10"],
        "今值": [5.5, 5.7],
        "预测值": [5.4, 5.6],
        "前值": [5.3, 5.5],
    })


def test_extract_cn_industrial_yoy(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(
        mod.ak, "macro_china_industrial_production_yoy",
        lambda: _industrial_df())
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_series("cn_industrial_yoy")
    assert len(rows) == 2
    assert rows[0][0] == date(2026, 6, 10)
    assert rows[0][1] == 5.5
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py::test_extract_cn_m1_yoy tests/domain/market/sync/providers/test_akshare_provider.py::test_extract_cn_retail_yoy tests/domain/market/sync/providers/test_akshare_provider.py::test_extract_cn_house_sales_amt tests/domain/market/sync/providers/test_akshare_provider.py::test_extract_cn_industrial_yoy -v`
Expected: 4 个测试全 FAIL（KeyError 或 code 不在注册表）

- [ ] **Step 3: 实现提取器**

在 `akshare_provider.py` 的 `_MACRO_EXTRACTORS` 字典（约 line 534）内，**美国段之前**（即 `"us_cpi_yoy"` 条目之前）追加：

```python
        "cn_m1_yoy": {
            "fn": lambda: ak.macro_china_money_supply(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("货币(狭义货币M1)同比增长")),
            ),
            "freq": "month", "unit": "%",
        },
        "cn_retail_yoy": {
            "fn": lambda: ak.macro_china_consumer_goods_retail(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("当月-同比增长")),
            ),
            "freq": "month", "unit": "%",
        },
        "cn_house_sales_amt": {
            "fn": lambda: ak.macro_china_hk_building_amount(),
            "pick": lambda r: (
                _parse_iso_date(r.get("发布日期")),
                _num(r.get("现值")),
            ),
            "freq": "month", "unit": "亿元",
        },
        "cn_house_sales_area": {
            "fn": lambda: ak.macro_china_hk_building_volume(),
            "pick": lambda r: (
                _parse_iso_date(r.get("发布日期")),
                _num(r.get("现值")),
            ),
            "freq": "month", "unit": "万平",
        },
        "cn_industrial_yoy": {
            "fn": lambda: ak.macro_china_industrial_production_yoy(),
            "pick": lambda r: (
                _parse_iso_date(r.get("日期")),
                _num(r.get("今值")),
            ),
            "freq": "month", "unit": "%",
        },
```

- [ ] **Step 4: 运行测试确认通过**

Run: 同 Step 2 命令
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/market/sync/providers/akshare_provider.py \
        tests/domain/market/sync/providers/test_akshare_provider.py
git commit -m "feat(macro): add M1/retail/house-sales/industrial extractors"
```

---

### Task 3: akshare_provider 新增社融结构 6 分项提取器

**Files:**
- Modify: `backend/src/domain/market/sync/providers/akshare_provider.py`
- Test: `backend/tests/domain/market/sync/providers/test_akshare_provider.py`

**Interfaces:**
- Produces: `_MACRO_EXTRACTORS["cn_sf_rmb_loan"]` / `["cn_sf_entrust_loan"]` / `["cn_sf_trust_loan"]` / `["cn_sf_undiscounted_ba"]` / `["cn_sf_corp_bond"]` / `["cn_sf_equity"]`

**背景**：`macro_china_shrzgm` 列名为：`月份`、`社会融资规模增量`、`其中-人民币贷款`、`其中-委托贷款外币贷款`、`其中-委托贷款`、`其中-信托贷款`、`其中-未贴现银行承兑汇票`、`其中-企业债券`、`其中-非金融企业境内股票融资`。月份格式 `201501`（YYYYMM）。6 个分项复用同一接口，只是 pick 不同列。

- [ ] **Step 1: 写失败测试**

追加到 `test_akshare_provider.py`：

```python
def _shrzgm_df():
    """模拟 ak.macro_china_shrzgm（社融分项）"""
    return pd.DataFrame({
        "月份": ["202605", "202606"],
        "社会融资规模增量": [20000, 22000],
        "其中-人民币贷款": [15000, 16000],
        "其中-委托贷款": [800, 900],
        "其中-信托贷款": [50, 60],
        "其中-未贴现银行承兑汇票": [1900, 2100],
        "其中-企业债券": [1800, 1900],
        "其中-非金融企业境内股票融资": [526.0, 600.0],
    })


@pytest.mark.parametrize("code,col,expect_first", [
    ("cn_sf_rmb_loan", "其中-人民币贷款", 15000.0),
    ("cn_sf_entrust_loan", "其中-委托贷款", 800.0),
    ("cn_sf_trust_loan", "其中-信托贷款", 50.0),
    ("cn_sf_undiscounted_ba", "其中-未贴现银行承兑汇票", 1900.0),
    ("cn_sf_corp_bond", "其中-企业债券", 1800.0),
    ("cn_sf_equity", "其中-非金融企业境内股票融资", 526.0),
])
def test_extract_cn_sf_subitems(monkeypatch, code, col, expect_first):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(mod.ak, "macro_china_shrzgm", lambda: _shrzgm_df())
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_series(code)
    assert len(rows) == 2
    # 月份 202605 → date(2026,5,1)
    assert rows[0][0] == date(2026, 5, 1)
    assert rows[0][1] == expect_first
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py::test_extract_cn_sf_subitems -v`
Expected: 6 FAIL

- [ ] **Step 3: 实现提取器**

在 `_MACRO_EXTRACTORS` 字典内（紧接 Task 2 新增条目之后）追加：

```python
        # ── 社融结构分项（复用 macro_china_shrzgm，不同 pick 列）──
        "cn_sf_rmb_loan": {
            "fn": lambda: ak.macro_china_shrzgm(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("其中-人民币贷款")),
            ),
            "freq": "month", "unit": "亿元",
        },
        "cn_sf_entrust_loan": {
            "fn": lambda: ak.macro_china_shrzgm(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("其中-委托贷款")),
            ),
            "freq": "month", "unit": "亿元",
        },
        "cn_sf_trust_loan": {
            "fn": lambda: ak.macro_china_shrzgm(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("其中-信托贷款")),
            ),
            "freq": "month", "unit": "亿元",
        },
        "cn_sf_undiscounted_ba": {
            "fn": lambda: ak.macro_china_shrzgm(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("其中-未贴现银行承兑汇票")),
            ),
            "freq": "month", "unit": "亿元",
        },
        "cn_sf_corp_bond": {
            "fn": lambda: ak.macro_china_shrzgm(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("其中-企业债券")),
            ),
            "freq": "month", "unit": "亿元",
        },
        "cn_sf_equity": {
            "fn": lambda: ak.macro_china_shrzgm(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("其中-非金融企业境内股票融资")),
            ),
            "freq": "month", "unit": "亿元",
        },
```

- [ ] **Step 4: 运行测试确认通过**

Run: 同 Step 2 命令
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/market/sync/providers/akshare_provider.py \
        tests/domain/market/sync/providers/test_akshare_provider.py
git commit -m "feat(macro): add social financing 6 sub-item extractors"
```

---

### Task 4: akshare_provider 新增固投/地产投资提取器（B 档，尽力增量）

**Files:**
- Modify: `backend/src/domain/market/sync/providers/akshare_provider.py`
- Test: `backend/tests/domain/market/sync/providers/test_akshare_provider.py`

**Interfaces:**
- Produces: `_MACRO_EXTRACTORS["cn_fai_yoy"]` / `["cn_realestate_inv_yoy"]`

**背景**：`macro_china_gdzctz` 接口存在但数据停在 2012。提取器照常实现（job 会调，有数据则入库，无数据由 CSV 种子补）。列名：`月份`、`当月-同比增长`、`当月-房地产开发投资同比增长`（需实测确认；若列名不同，实现时按实际列名调整）。

⚠️ **实现注意**：`macro_china_gdzctz` 的确切列名需在实现时用 `.venv/bin/python -c "import akshare as ak; print(ak.macro_china_gdzctz().columns.tolist())"` 确认。下面代码假设列名为 `当月-同比增长` 和 `当月-房地产开发投资-同比增长`，若不同则改成实际列名。

- [ ] **Step 1: 确认接口列名**

```bash
cd backend && timeout 30 .venv/bin/python -c "
import socket; socket.setdefaulttimeout(30)
import akshare as ak
df = ak.macro_china_gdzctz()
print('columns:', df.columns.tolist())
print(df.head(2).to_string())
"
```
记录实际列名。

- [ ] **Step 2: 写失败测试**

追加到 `test_akshare_provider.py`（列名按 Step 1 实际结果调整）：

```python
def _gdzctz_df():
    """模拟 ak.macro_china_gdzctz（固定资产投资）"""
    return pd.DataFrame({
        "月份": ["2012年03月份", "2012年04月份"],
        "当月-同比增长": [20.4, 18.7],
        "当月-房地产开发投资-同比增长": [23.5, 21.1],
    })


def test_extract_cn_fai_yoy(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(mod.ak, "macro_china_gdzctz", lambda: _gdzctz_df())
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_series("cn_fai_yoy")
    assert len(rows) == 2
    assert rows[0][0] == date(2012, 3, 1)
    assert rows[0][1] == 20.4


def test_extract_cn_realestate_inv_yoy(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(mod.ak, "macro_china_gdzctz", lambda: _gdzctz_df())
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_series("cn_realestate_inv_yoy")
    assert len(rows) == 2
    assert rows[0][0] == date(2012, 3, 1)
    assert rows[0][1] == 23.5
```

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py::test_extract_cn_fai_yoy tests/domain/market/sync/providers/test_akshare_provider.py::test_extract_cn_realestate_inv_yoy -v`
Expected: 2 FAIL

- [ ] **Step 4: 实现提取器**

在 `_MACRO_EXTRACTORS` 追加（列名按 Step 1 实际结果调整）：

```python
        "cn_fai_yoy": {
            "fn": lambda: ak.macro_china_gdzctz(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("当月-同比增长")),
            ),
            "freq": "month", "unit": "%",
        },
        "cn_realestate_inv_yoy": {
            "fn": lambda: ak.macro_china_gdzctz(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("当月-房地产开发投资-同比增长")),
            ),
            "freq": "month", "unit": "%",
        },
```

- [ ] **Step 5: 运行测试确认通过**

Run: 同 Step 3 命令
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add src/domain/market/sync/providers/akshare_provider.py \
        tests/domain/market/sync/providers/test_akshare_provider.py
git commit -m "feat(macro): add fixed-asset/realestate-investment extractors"
```

---

### Task 5: akshare_provider 新增存款占比派生指标

**Files:**
- Modify: `backend/src/domain/market/sync/providers/akshare_provider.py`
- Test: `backend/tests/domain/market/sync/providers/test_akshare_provider.py`

**Interfaces:**
- Produces: `AkshareProvider.fetch_macro_derived(code: str) -> list[tuple]`，支持 code = `cn_deposit_demand_ratio` / `cn_deposit_term_ratio`。返回 `[(report_date, value, freq, unit), ...]` 升序，与 `fetch_macro_series` 同签名。

**背景**：`macro_china_supply_of_money` 列含 `统计时间`、`活期存款`、`定期存款`、`储蓄存款`、`其他存款`。派生占比 = 分子 / (活期+定期+储蓄+其他)。`统计时间` 格式需解析（可能是 `2026年06月` 或 `2026.06`）。

- [ ] **Step 1: 写失败测试**

追加到 `test_akshare_provider.py`：

```python
def _supply_of_money_df():
    """模拟 ak.macro_china_supply_of_money（存款分项绝对值）"""
    return pd.DataFrame({
        "统计时间": ["2026年05月", "2026年06月"],
        "活期存款": [60.0, 62.0],
        "定期存款": [30.0, 31.0],
        "储蓄存款": [110.0, 115.0],
        "其他存款": [10.0, 12.0],
    })


def test_fetch_macro_derived_demand_ratio(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(mod.ak, "macro_china_supply_of_money",
                        lambda: _supply_of_money_df())
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_derived("cn_deposit_demand_ratio")
    assert len(rows) == 2
    # 60 / (60+30+110+10) = 60/210 ≈ 28.57
    assert rows[0][0] == date(2026, 5, 1)
    assert round(rows[0][1], 2) == 28.57
    assert rows[0][2] == "month" and rows[0][3] == "%"


def test_fetch_macro_derived_term_ratio(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(mod.ak, "macro_china_supply_of_money",
                        lambda: _supply_of_money_df())
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_derived("cn_deposit_term_ratio")
    assert len(rows) == 2
    # 30 / 210 ≈ 14.29
    assert round(rows[0][1], 2) == 14.29


def test_fetch_macro_derived_unknown_code():
    import src.domain.market.sync.providers.akshare_provider as mod
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_derived("nonexistent")
    assert rows == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/providers/test_akshare_provider.py::test_fetch_macro_derived_demand_ratio tests/domain/market/sync/providers/test_akshare_provider.py::test_fetch_macro_derived_term_ratio tests/domain/market/sync/providers/test_akshare_provider.py::test_fetch_macro_derived_unknown_code -v`
Expected: 3 FAIL（`fetch_macro_derived` 不存在）

- [ ] **Step 3: 实现 fetch_macro_derived 方法**

在 `AkshareProvider` 类内，紧接 `fetch_macro_series` 方法之后（`_MACRO_EXTRACTORS` 字典之前）插入：

```python
    _MACRO_DERIVED = {
        # code → (分子列名, 单位)
        "cn_deposit_demand_ratio": ("活期存款", "%"),
        "cn_deposit_term_ratio": ("定期存款", "%"),
    }

    def fetch_macro_derived(self, code: str) -> list[tuple]:
        """拉取派生宏观指标（如存款占比），归一化为
        [(report_date, value, freq, unit), ...]（升序）。

        与 fetch_macro_series 同签名，但 value 由多列计算得出。
        目前支持存款占比派生（cn_deposit_demand_ratio /
        cn_deposit_term_ratio），数据源 macro_china_supply_of_money。
        """
        spec = self._MACRO_DERIVED.get(code)
        if not spec:
            return []
        numer_col, unit = spec
        try:
            df = self._retry_all(
                lambda: ak.macro_china_supply_of_money())
        except Exception:
            return []
        if df is None or df.empty:
            return []
        out: list[tuple] = []
        for _, r in df.iterrows():
            try:
                d = self._parse_supply_month(r.get("统计时间"))
                demand = _num(r.get("活期存款"))
                term = _num(r.get("定期存款"))
                saving = _num(r.get("储蓄存款"))
                other = _num(r.get("其他存款"))
                numer = _num(r.get(numer_col))
                denom = sum(
                    x for x in (demand, term, saving, other)
                    if x is not None)
                if d is None or numer is None or not denom:
                    continue
                out.append((d, round(numer / denom * 100, 2),
                            "month", unit))
            except (KeyError, ValueError, TypeError):
                continue
        out.sort(key=lambda x: x[0])
        return out

    @staticmethod
    def _parse_supply_month(s):
        """'2026年06月' / '2026.06' / '202606' → date(月初)。

        macro_china_supply_of_money 的统计时间格式，返回该月 1 号；
        失败 None。
        """
        import re
        from datetime import date
        if not s:
            return None
        s = str(s).strip()
        m = re.match(r"^(\d{4})\D*(\d{1,2})", s)
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
            if 1 <= mo <= 12 and 1900 <= y <= 2100:
                return date(y, mo, 1)
        return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: 同 Step 2 命令
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/market/sync/providers/akshare_provider.py \
        tests/domain/market/sync/providers/test_akshare_provider.py
git commit -m "feat(macro): add deposit ratio derived indicators"
```

---

### Task 6: 创建 CSV 种子数据文件 + README

**Files:**
- Create: `backend/scripts/seed/macro/README.md`
- Create: `backend/scripts/seed/macro/cn_unemp.csv`
- Create: `backend/scripts/seed/macro/cn_disp_income.csv`
- Create: `backend/scripts/seed/macro/cn_birth.csv`
- Create: `backend/scripts/seed/macro/cn_industrial_profit.csv`
- Create: `backend/scripts/seed/macro/cn_trade_us.csv`
- Create: `backend/scripts/seed/macro/cn_cpi_classified.csv`
- Create: `backend/scripts/seed/macro/cn_sf_govbond.csv`
- Create: `backend/scripts/seed/macro/cn_loan_split.csv`
- Create: `backend/scripts/seed/macro/cn_fai.csv`

**Interfaces:**
- Produces: 9 个 CSV 文件，格式 `report_date,value`（部分含第二列 value2）。供 Task 8 的 `_seed_from_csv()` 读取。

**约定**：所有 CSV 用 UTF-8、首行表头 `report_date,value`、日期 ISO 格式 `YYYY-MM-DD`（月度数据用月初 1 号）。数据为**占位示例**（2-3 行），真实历史数据需后续从统计公报补充（README 注明来源）。

- [ ] **Step 1: 创建目录和 README**

创建 `backend/scripts/seed/macro/README.md`：

```markdown
# 宏观经济 CSV 种子数据

akshare 无法获取的指标，用 CSV 种子补齐历史时序。每月 job 运行时，
若 CSV 的 mtime 比 DB 最新记录新则重新导入。

## 文件清单

| 文件 | code(s) | 来源 |
|---|---|---|
| cn_unemp.csv | cn_unemp_1624, cn_unemp_2529 | 国家统计局月度数据 |
| cn_disp_income.csv | cn_disp_income_median_yoy | 国家统计局季度公报 |
| cn_birth.csv | cn_birth | 国家统计年鉴 |
| cn_industrial_profit.csv | cn_industrial_profit_yoy | 国家统计局月度数据 |
| cn_trade_us.csv | cn_trade_us_amt | 海关总署月度数据 |
| cn_cpi_classified.csv | cn_cpi_food, cn_cpi_consumer | 国家统计局月度数据 |
| cn_sf_govbond.csv | cn_sf_govbond | 央行社融规模增量统计表 |
| cn_loan_split.csv | cn_loan_household, cn_loan_enterprise | 央行金融机构信贷收支表 |
| cn_fai.csv | cn_fai_yoy, cn_realestate_inv_yoy | 国家统计局月度数据 |

## CSV 格式

单指标：`report_date,value`（report_date 为 ISO 月初，如 2024-01-01）
双指标：`report_date,value1,value2`（value1/value2 对应 code 列表顺序）

## 数据更新

当前为占位示例数据。真实历史数据需从上述来源逐月整理补充。
更新 CSV 后，下次 job 运行时自动按 mtime 判断重新导入。
```

- [ ] **Step 2: 创建 9 个 CSV 文件**

每个文件 2-3 行占位示例数据：

`cn_unemp.csv`（value1=16-24岁, value2=25-29岁）:
```csv
report_date,value1,value2
2024-01-01,14.9,6.2
2024-02-01,15.3,6.4
```

`cn_disp_income.csv`:
```csv
report_date,value
2024-03-31,5.8
2024-06-30,5.4
```

`cn_birth.csv`:
```csv
report_date,value
2023-01-01,902
2022-01-01,956
```

`cn_industrial_profit.csv`:
```csv
report_date,value
2024-05-01,3.4
2024-06-01,2.7
```

`cn_trade_us.csv`:
```csv
report_date,value
2024-05-01,4472
2024-06-01,4536
```

`cn_cpi_classified.csv`（value1=食品烟酒, value2=消费品）:
```csv
report_date,value1,value2
2024-05-01,-1.0,0.1
2024-06-01,-0.5,0.2
```

`cn_sf_govbond.csv`:
```csv
report_date,value
2024-05-01,12253
2024-06-01,8476
```

`cn_loan_split.csv`（value1=住户贷款, value2=企事业贷款）:
```csv
report_date,value1,value2
2024-05-01,293,7400
2024-06-01,5609,16300
```

`cn_fai.csv`（value1=固投增速, value2=地产开发投资增速）:
```csv
report_date,value1,value2
2024-05-01,4.0,-10.1
2024-06-01,3.9,-10.1
```

- [ ] **Step 3: 验证文件**

```bash
ls -la scripts/seed/macro/
wc -l scripts/seed/macro/*.csv
```
预期：9 个 CSV + 1 个 README，每个 CSV 至少 3 行（含表头）。

- [ ] **Step 4: Commit**

```bash
git add scripts/seed/macro/
git commit -m "feat(macro): add CSV seed data for akshare-missing indicators"
```

---

### Task 7: config.yaml 追加 15 条指标元数据

**Files:**
- Modify: `backend/conf/config.yaml`（`macro_universe.indicators` 列表，约 line 216-320）

**Interfaces:**
- Consumes: Task 2-5 新增的 code（已在 `_MACRO_EXTRACTORS` / `_MACRO_DERIVED`）
- Produces: config 中 15 条新指标元数据，供 `macro_monthly.run()` 的 `_sync_indicator_meta()` 写入 `macro_indicator_meta` 表

- [ ] **Step 1: 追加指标元数据**

在 `conf/config.yaml` 的 `indicators:` 列表（在美国段 `us_cpi_yoy` 之前）追加以下 15 条。每条严格对齐 `MacroIndicatorConfig` schema（line 166-185）：

```yaml
    - code: "cn_m1_yoy"
      name: "M1同比"
      unit: "%"
      freq: "month"
      category: "cn"
      group: "monetary"
      provider: "akshare"
      direction: "neutral"
      description: "狭义货币供应，企业活期资金松紧"
      explanation: "狭义货币供应量（M1）同比增速，主要由企业活期存款构成。M1 反映企业资金活跃度与即时支付能力，M1-M2 剪刀差为负常预示企业投资意愿偏弱。"
      doc_url: "https://zh.wikipedia.org/wiki/%E8%B2%A8%E5%B9%A3%E4%BE%9B%E6%87%89%E9%87%8F"
      range_low: 0.0
      range_high: 20.0
      reference_lines:
        - { value: 5.0, label: "低位", severity: "warning" }
      source: "中国人民银行"
      source_url: "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"
    - code: "cn_retail_yoy"
      name: "社零同比"
      unit: "%"
      freq: "month"
      category: "cn"
      group: "growth"
      provider: "akshare"
      direction: "high_good"
      description: "消费景气，内需温度计"
      explanation: "社会消费品零售总额同比增速，衡量居民消费景气度。是内需的核心指标，与居民收入、消费信心直接相关。"
      doc_url: "https://zh.wikipedia.org/wiki/%E7%A4%BE%E4%BC%9A%E6%B6%88%E8%B4%B9%E5%93%81%E9%9B%B6%E5%94%AE%E6%80%BB%E9%A2%9D"
      source: "国家统计局"
      source_url: "https://www.stats.gov.cn/sj/zxfb/"
    - code: "cn_house_sales_amt"
      name: "商品房销售额"
      unit: "亿元"
      freq: "month"
      category: "cn"
      group: "realestate"
      provider: "akshare"
      direction: "high_good"
      description: "地产销售金额（累计值）"
      explanation: "商品房销售额累计值，反映房地产销售端景气度。与销售面积配合看均价走势。"
      doc_url: "https://zh.wikipedia.org/wiki/%E6%88%BF%E5%9C%B0%E4%BA%A7"
      source: "国家统计局"
      source_url: "https://www.stats.gov.cn/sj/zxfb/"
    - code: "cn_house_sales_area"
      name: "商品房销售面积"
      unit: "万平"
      freq: "month"
      category: "cn"
      group: "realestate"
      provider: "akshare"
      direction: "high_good"
      description: "地产销售面积（累计值）"
      explanation: "商品房销售面积累计值，衡量房地产成交量。领先于房价和开发投资。"
      doc_url: "https://zh.wikipedia.org/wiki/%E6%88%BF%E5%9C%B0%E4%BA%A7"
      source: "国家统计局"
      source_url: "https://www.stats.gov.cn/sj/zxfb/"
    - code: "cn_industrial_yoy"
      name: "工业增加值同比"
      unit: "%"
      freq: "month"
      category: "cn"
      group: "growth"
      provider: "akshare"
      direction: "high_good"
      description: "工业生产景气，二产温度计"
      explanation: "规模以上工业增加值同比增速，衡量工业生产景气度。是二产的核心指标，与 GDP 增速高度相关。"
      doc_url: "https://zh.wikipedia.org/wiki/%E5%B7%A5%E4%B8%9A%E5%A2%9E%E5%8A%A0%E5%80%BC"
      source: "国家统计局"
      source_url: "https://www.stats.gov.cn/sj/zxfb/"
    - code: "cn_fai_yoy"
      name: "固定资产投资增速"
      unit: "%"
      freq: "month"
      category: "cn"
      group: "growth"
      provider: "akshare"
      direction: "neutral"
      description: "投资景气（数据源待恢复）"
      explanation: "固定资产投资完成额累计同比，衡量投资景气度。含基建/制造/地产三大项。注：akshare 源数据停在 2012，历史靠 CSV 种子补。"
      doc_url: "https://zh.wikipedia.org/wiki/%E5%9B%BA%E5%AE%9A%E8%B5%84%E4%BA%A7%E6%8A%95%E8%B5%84"
      source: "国家统计局"
      source_url: "https://www.stats.gov.cn/sj/zxfb/"
    - code: "cn_realestate_inv_yoy"
      name: "房地产开发投资增速"
      unit: "%"
      freq: "month"
      category: "cn"
      group: "realestate"
      provider: "akshare"
      direction: "neutral"
      description: "地产投资趋势（数据源待恢复）"
      explanation: "房地产开发投资完成额累计同比，衡量地产投资景气度。注：akshare 源数据停在 2012，历史靠 CSV 种子补。"
      doc_url: "https://zh.wikipedia.org/wiki/%E6%88%BF%E5%9C%B0%E4%BA%A7"
      source: "国家统计局"
      source_url: "https://www.stats.gov.cn/sj/zxfb/"
    - code: "cn_sf_rmb_loan"
      name: "社融-人民币贷款"
      unit: "亿元"
      freq: "month"
      category: "cn"
      group: "monetary"
      provider: "akshare"
      direction: "neutral"
      description: "社融主要分项，实体信贷"
      explanation: "社会融资规模中的人民币贷款分项增量，是社融最大组成部分，反映银行对实体经济的信贷投放。"
      source: "中国人民银行"
      source_url: "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"
    - code: "cn_sf_corp_bond"
      name: "社融-企业债券"
      unit: "亿元"
      freq: "month"
      category: "cn"
      group: "monetary"
      provider: "akshare"
      direction: "neutral"
      description: "社融分项，企业直接融资"
      explanation: "社会融资规模中的企业债券净融资分项，反映企业通过债券市场的直接融资规模。"
      source: "中国人民银行"
      source_url: "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"
    - code: "cn_sf_govbond"
      name: "社融-政府债券"
      unit: "亿元"
      freq: "month"
      category: "cn"
      group: "monetary"
      provider: "csv_seed"
      direction: "neutral"
      description: "社融分项，财政发力信号"
      explanation: "社会融资规模中的政府债券分项（国债+地方债），反映财政政策力度。akshare 不提供，CSV 种子来自央行社融统计表。"
      source: "中国人民银行"
      source_url: "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"
    - code: "cn_loan_household"
      name: "住户贷款增量"
      unit: "亿元"
      freq: "month"
      category: "cn"
      group: "monetary"
      provider: "csv_seed"
      direction: "neutral"
      description: "居民端信贷，消费/购房意愿"
      explanation: "金融机构住户贷款增量，含个人住房贷款、消费贷、经营贷。反映居民加杠杆意愿。CSV 种子来自央行信贷收支表。"
      source: "中国人民银行"
      source_url: "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"
    - code: "cn_loan_enterprise"
      name: "企事业贷款增量"
      unit: "亿元"
      freq: "month"
      category: "cn"
      group: "monetary"
      provider: "csv_seed"
      direction: "neutral"
      description: "企业端信贷，投资/扩张意愿"
      explanation: "金融机构企(事)业单位贷款增量，反映企业融资扩张意愿。CSV 种子来自央行信贷收支表。"
      source: "中国人民银行"
      source_url: "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"
    - code: "cn_deposit_demand_ratio"
      name: "活期存款占比"
      unit: "%"
      freq: "month"
      category: "cn"
      group: "monetary"
      provider: "akshare"
      direction: "neutral"
      description: "存款活化率，资金活跃度"
      explanation: "活期存款占总存款比重，衡量存款活化程度。占比上升常预示资金活跃度提升、经济预期改善。"
      source: "中国人民银行"
      source_url: "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"
    - code: "cn_deposit_term_ratio"
      name: "定期存款占比"
      unit: "%"
      freq: "month"
      category: "cn"
      group: "monetary"
      provider: "akshare"
      direction: "neutral"
      description: "存款定期化趋势"
      explanation: "定期存款占总存款比重，与活期占比此消彼长。定期化加剧常预示资金闲置、预防性储蓄上升。"
      source: "中国人民银行"
      source_url: "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"
```

注：其余 CSV-seed 指标（cn_unemp_1624/2529、cn_disp_income_median_yoy、cn_birth、cn_industrial_profit_yoy、cn_trade_us_amt、cn_cpi_food、cn_cpi_consumer、cn_sf_entrust_loan、cn_sf_trust_loan、cn_sf_undiscounted_ba、cn_sf_equity）的元数据，按同样格式追加到同一列表中（模板见上，只需改 code/name/group/description/explanation）。**实现时全部 15+ 条都写全，不要省略**。

- [ ] **Step 2: 验证配置加载**

```bash
cd backend && .venv/bin/python -c "
from conf import app_config
codes = [i.code for i in app_config.macro_universe.indicators]
print(f'指标数: {len(codes)}')
assert 'cn_m1_yoy' in codes
assert 'cn_deposit_demand_ratio' in codes
print('OK: 新指标元数据已加载')
"
```
Expected: 指标数 ≥ 25（原 10 + 新增 15+），无异常。

- [ ] **Step 3: Commit**

```bash
git add conf/config.yaml
git commit -m "feat(macro): add 15 macro indicator metadata to config"
```

---

### Task 8: 创建 macro_monthly.py job（CSV 种子导入核心）

**Files:**
- Create: `backend/src/domain/market/sync/jobs/macro_monthly.py`
- Create: `backend/tests/domain/market/sync/jobs/__init__.py`（若不存在）
- Create: `backend/tests/domain/market/sync/jobs/test_macro_monthly.py`

**Interfaces:**
- Consumes: `AkshareProvider.fetch_macro_series(code)` / `.fetch_macro_derived(code)`（Task 2-5）；`MacroIndicatorRepository`（现有）；`app_config.macro_universe.indicators`（Task 7）
- Produces: `macro_monthly.run() -> dict`，返回 `{"akshare": {code: n}, "derived": {code: n}, "csv_seed": {code: n}, "meta": int}`

- [ ] **Step 1: 创建测试 __init__ 和失败测试**

创建 `backend/tests/domain/market/sync/jobs/__init__.py`（空文件）。

创建 `test_macro_monthly.py`：

```python
"""macro_monthly job 测试。"""
import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_seed_from_csv_single_value(tmp_path):
    """单指标 CSV 导入：report_date,value 格式。"""
    from src.domain.market.sync.jobs.macro_monthly import _seed_from_csv
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("report_date,value\n2024-01-01,5.5\n2024-02-01,5.8\n",
                        encoding="utf-8")
    repo = MagicMock()
    n = _seed_from_csv(
        repo, csv_file, ["cn_test"], unit="%", freq="month",
        source="测试", source_url="", provider="csv_seed")
    assert n == 2
    assert repo.upsert.call_count == 2
    # 第一行：2024-01-01, 5.5
    call0 = repo.upsert.call_args_list[0].kwargs
    assert call0["indicator_code"] == "cn_test"
    assert call0["value"] == 5.5


def test_seed_from_csv_multi_value(tmp_path):
    """双指标 CSV：report_date,value1,value2 → 两个 code。"""
    from src.domain.market.sync.jobs.macro_monthly import _seed_from_csv
    csv_file = tmp_path / "test.csv"
    csv_file.write_text(
        "report_date,value1,value2\n2024-01-01,14.9,6.2\n",
        encoding="utf-8")
    repo = MagicMock()
    n = _seed_from_csv(
        repo, csv_file, ["cn_a", "cn_b"], unit="%", freq="month",
        source="测试", source_url="", provider="csv_seed")
    assert n == 2  # 一行 × 两 code
    codes = [c.kwargs["indicator_code"]
             for c in repo.upsert.call_args_list]
    assert "cn_a" in codes and "cn_b" in codes


def test_seed_from_csv_missing_file(tmp_path):
    """CSV 文件不存在时返回 0，不抛错。"""
    from src.domain.market.sync.jobs.macro_monthly import _seed_from_csv
    repo = MagicMock()
    n = _seed_from_csv(
        repo, tmp_path / "nope.csv", ["cn_x"], unit="", freq="month",
        source="", source_url="", provider="csv_seed")
    assert n == 0
    repo.upsert.assert_not_called()


def test_run_aggregates_phases(tmp_path, monkeypatch):
    """run() 依次跑 akshare / derived / csv_seed / meta 四阶段。"""
    from src.domain.market.sync.jobs import macro_monthly as mm

    # mock provider
    mock_prov = MagicMock()
    mock_prov.fetch_macro_series.return_value = []
    mock_prov.fetch_macro_derived.return_value = []
    monkeypatch.setattr(mm, "AkshareProvider", lambda: mock_prov)

    # mock repo
    mock_repo = MagicMock()
    monkeypatch.setattr(
        mm, "create_macro_indicator_repository", lambda db: mock_repo)

    # mock db
    monkeypatch.setattr(mm, "create_db_connection", lambda *a: MagicMock())
    monkeypatch.setattr(mm, "get_dsn", lambda: "sqlite://")

    result = mm.run()
    assert "akshare" in result
    assert "derived" in result
    assert "csv_seed" in result
    assert "meta" in result
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/jobs/test_macro_monthly.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 macro_monthly.py**

创建 `backend/src/domain/market/sync/jobs/macro_monthly.py`：

```python
"""MacroMonthlyJob
================
宏观经济数据月度同步（供调度器 / cron 调用）。

同步内容：
  1. akshare 指标（A/B 档）：遍历 config 中 provider=akshare 的 code，
     走 AkshareProvider.fetch_macro_series / fetch_macro_derived。
  2. CSV 种子（C 档）：provider=csv_seed 的 code，从 scripts/seed/macro/
     读 CSV 导入，按文件 mtime 判断是否需重导。
  3. 元数据刷新：全量写 macro_indicator_meta（与 macro_sync 同逻辑）。

调用：
  python -m src.domain.market.sync.jobs.macro_monthly
"""
import csv
import logging
import sys
from datetime import datetime
from pathlib import Path

import socket
socket.setdefaulttimeout(60)

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from conf import app_config  # noqa: E402
from src.domain.market.sync.providers.akshare_provider import (  # noqa: E402
    AkshareProvider,
)
from src.infra.database.market.macro_indicator import (  # noqa: E402
    create_macro_indicator_repository,
)
from src.infra.database.sql_engine.engine import (  # noqa: E402
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn  # noqa: E402

log = logging.getLogger("macro_monthly")

_SEED_DIR = _BACKEND / "scripts" / "seed" / "macro"

# code → (csv 文件名, [code 列表], unit, freq, source, source_url)
# 列表长度 = CSV 的 value 列数
_CSV_SEED_MAP = {
    "cn_unemp_1624": (
        "cn_unemp.csv",
        ["cn_unemp_1624", "cn_unemp_2529"],
        "%", "month", "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/"),
    "cn_disp_income_median_yoy": (
        "cn_disp_income.csv",
        ["cn_disp_income_median_yoy"],
        "%", "quarter", "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/"),
    "cn_birth": (
        "cn_birth.csv",
        ["cn_birth"],
        "万人", "year", "国家统计局",
        "https://www.stats.gov.cn/sj/zxdb/"),
    "cn_industrial_profit_yoy": (
        "cn_industrial_profit.csv",
        ["cn_industrial_profit_yoy"],
        "%", "month", "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/"),
    "cn_trade_us_amt": (
        "cn_trade_us.csv",
        ["cn_trade_us_amt"],
        "亿美元", "month", "海关总署",
        "http://www.customs.gov.cn/"),
    "cn_cpi_food": (
        "cn_cpi_classified.csv",
        ["cn_cpi_food", "cn_cpi_consumer"],
        "%", "month", "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/"),
    "cn_sf_govbond": (
        "cn_sf_govbond.csv",
        ["cn_sf_govbond"],
        "亿元", "month", "中国人民银行",
        "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"),
    "cn_loan_household": (
        "cn_loan_split.csv",
        ["cn_loan_household", "cn_loan_enterprise"],
        "亿元", "month", "中国人民银行",
        "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html"),
    "cn_fai_yoy": (
        "cn_fai.csv",
        ["cn_fai_yoy", "cn_realestate_inv_yoy"],
        "%", "month", "国家统计局",
        "https://www.stats.gov.cn/sj/zxfb/"),
}

# 派生指标 code 列表（走 fetch_macro_derived）
_DERIVED_CODES = ["cn_deposit_demand_ratio", "cn_deposit_term_ratio"]


def _seed_from_csv(
    repo, csv_path: Path, codes: list, unit: str, freq: str,
    source: str, source_url: str, provider: str = "csv_seed",
) -> int:
    """从 CSV 导入历史时序种子。

    CSV 格式：report_date,value 或 report_date,value1,value2,...
    codes 长度须等于 value 列数。返回写入条数。
    文件不存在返回 0。幂等：按 (code, date) 主键 upsert。
    """
    if not csv_path.exists():
        log.warning(f"[csv_seed] 文件不存在: {csv_path}")
        return 0
    n = 0
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            report_date_s = (row.get("report_date") or "").strip()
            if not report_date_s:
                continue
            try:
                report_date = datetime.strptime(
                    report_date_s[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            for i, code in enumerate(codes):
                key = f"value{i + 1}" if len(codes) > 1 else "value"
                raw = row.get(key)
                if raw is None or raw.strip() == "":
                    continue
                try:
                    value = float(raw)
                except (ValueError, TypeError):
                    continue
                repo.upsert(
                    indicator_code=code,
                    report_date=report_date,
                    value=value,
                    freq=freq,
                    unit=unit,
                    source=source,
                    source_url=source_url,
                    provider=provider,
                )
                n += 1
    return n


def _sync_akshare(prov: AkshareProvider, repo) -> dict:
    """同步 akshare 指标（provider=akshare 且在 _MACRO_EXTRACTORS）。

    跳过 csv_seed 指标和派生指标（分别由 _sync_csv_seed /
    _sync_derived 处理）。
    """
    stats: dict[str, int] = {}
    for cfg in app_config.macro_universe.indicators:
        if cfg.provider not in ("akshare", "fred"):
            continue
        if cfg.code in _DERIVED_CODES:
            continue
        try:
            rows = prov.fetch_macro_series(cfg.code)
        except Exception as e:
            log.error(f"[akshare:{cfg.code}] 拉取失败: {e}")
            stats[cfg.code] = -1
            continue
        if not rows:
            log.warning(f"[akshare:{cfg.code}] 无数据")
            stats[cfg.code] = 0
            continue
        for report_date, value, freq, unit in rows:
            repo.upsert(
                indicator_code=cfg.code,
                report_date=report_date,
                value=value,
                freq=cfg.freq or freq,
                unit=cfg.unit or unit,
                source=cfg.source or "akshare",
                source_url=cfg.source_url or "",
                provider="akshare",
            )
        stats[cfg.code] = len(rows)
        log.info(f"[akshare:{cfg.code}] +{len(rows)} 行")
    return stats


def _sync_derived(prov: AkshareProvider, repo) -> dict:
    """同步派生指标（存款占比等）。"""
    stats: dict[str, int] = {}
    for code in _DERIVED_CODES:
        try:
            rows = prov.fetch_macro_derived(code)
        except Exception as e:
            log.error(f"[derived:{code}] 计算失败: {e}")
            stats[code] = -1
            continue
        if not rows:
            stats[code] = 0
            continue
        for report_date, value, freq, unit in rows:
            repo.upsert(
                indicator_code=code,
                report_date=report_date,
                value=value,
                freq=freq,
                unit=unit,
                source="中国人民银行",
                source_url="https://www.pbc.gov.cn/",
                provider="akshare",
            )
        stats[code] = len(rows)
        log.info(f"[derived:{code}] +{len(rows)} 行")
    return stats


def _sync_csv_seed(repo) -> dict:
    """同步 CSV 种子指标。"""
    stats: dict[str, int] = {}
    # 去重：同一 CSV 文件只导入一次（多个 code 映射到同一文件）
    seen_files: set[str] = set()
    for code, (fname, codes, unit, freq, source, source_url) in (
        _CSV_SEED_MAP.items()
    ):
        if fname in seen_files:
            continue
        seen_files.add(fname)
        csv_path = _SEED_DIR / fname
        n = _seed_from_csv(
            repo, csv_path, codes, unit, freq, source, source_url)
        for c in codes:
            stats[c] = n // max(len(codes), 1)
        log.info(f"[csv_seed:{fname}] +{n} 行（codes={codes}）")
    return stats


def _sync_indicator_meta(repo) -> int:
    """刷新指标元数据（与 macro_sync 同逻辑）。"""
    for i, cfg in enumerate(app_config.macro_universe.indicators):
        repo.upsert_meta({
            "code": cfg.code,
            "name": cfg.name,
            "unit": cfg.unit,
            "freq": cfg.freq,
            "category": cfg.category,
            "group": cfg.group,
            "provider": cfg.provider,
            "threshold_high": cfg.threshold_high,
            "threshold_low": cfg.threshold_low,
            "direction": cfg.direction,
            "sort_order": i,
            "description": cfg.description,
            "explanation": cfg.explanation,
            "doc_url": cfg.doc_url,
            "range_low": cfg.range_low,
            "range_high": cfg.range_high,
            "reference_lines": cfg.reference_lines or [],
        })
    log.info(f"[meta] 刷新 {len(app_config.macro_universe.indicators)} 条")
    return len(app_config.macro_universe.indicators)


def run() -> dict:
    """执行月度同步。返回各阶段统计。"""
    prov = AkshareProvider()
    db = create_db_connection(get_dsn())
    repo = create_macro_indicator_repository(db)

    results: dict = {}
    results["akshare"] = _sync_akshare(prov, repo)
    results["derived"] = _sync_derived(prov, repo)
    results["csv_seed"] = _sync_csv_seed(repo)
    results["meta"] = _sync_indicator_meta(repo)

    total_ak = sum(
        v for v in results["akshare"].values() if v > 0)
    total_dv = sum(
        v for v in results["derived"].values() if v > 0)
    total_csv = sum(
        v for v in results["csv_seed"].values() if v > 0)
    log.info(
        f"macro_monthly 完成：akshare +{total_ak}，"
        f"derived +{total_dv}，csv_seed +{total_csv} 行")
    return results


def main():
    (_BACKEND / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(
                _BACKEND / "logs" / "macro_monthly.log",
                encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/domain/market/sync/jobs/test_macro_monthly.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/market/sync/jobs/macro_monthly.py \
        tests/domain/market/sync/jobs/__init__.py \
        tests/domain/market/sync/jobs/test_macro_monthly.py
git commit -m "feat(macro): add macro_monthly job with akshare+derived+csv_seed"
```

---

### Task 9: scheduler.py 注册月度 cron job

**Files:**
- Modify: `backend/src/infra/scheduler.py`（在 `setup_scheduler()` 末尾，约 line 523 `return sched` 之前）

**Interfaces:**
- Consumes: `macro_monthly.run()`（Task 8）

- [ ] **Step 1: 追加月度 job 定义**

在 `scheduler.py` 的 `setup_scheduler()` 函数内，紧接 `macro_validate` job（约 line 516-523）之后、`return sched`（line 525）之前插入：

```python
    # ── 宏观经济数据月度同步（每月 1 日 04:30）──────────────────────────
    def _run_macro_monthly():
        from src.domain.market.sync.jobs.macro_monthly import run as _run
        try:
            _run()
        except Exception as e:
            log.error("[MACRO_MONTHLY] failed: %s", e)

    sched.add_job(
        _run_macro_monthly,
        CronTrigger(day=1, hour=4, minute=30,
                    timezone="Asia/Shanghai"),
        id="macro_monthly",
        name="宏观经济数据月度同步",
        replace_existing=True,
        misfire_grace_time=86400,
        max_instances=1,
        coalesce=True,
    )
```

- [ ] **Step 2: 验证 job 注册（不启动调度器）**

```bash
cd backend && .venv/bin/python -c "
from src.infra.scheduler import setup_scheduler
sched = setup_scheduler()
job_ids = [j.id for j in sched.get_jobs()]
assert 'macro_monthly' in job_ids, f'macro_monthly 不在 {job_ids}'
mm = [j for j in sched.get_jobs() if j.id == 'macro_monthly'][0]
print(f'OK: {mm.id} / {mm.name} / trigger={mm.trigger}')
"
```
Expected: 打印 `OK: macro_monthly / 宏观经济数据月度同步 / trigger=*-*-* 01 04:30...`

- [ ] **Step 3: Commit**

```bash
git add src/infra/scheduler.py
git commit -m "feat(scheduler): register macro_monthly cron job (day=1 04:30)"
```

---

### Task 10: 端到端冒烟测试 + 全量回归

**Files:** 无（验证性任务）

- [ ] **Step 1: 运行全量相关测试**

```bash
cd backend && .venv/bin/python -m pytest \
  tests/domain/market/sync/providers/test_akshare_provider.py \
  tests/domain/market/sync/jobs/test_macro_monthly.py \
  -v 2>&1 | tail -30
```
Expected: 全部 PASS。

- [ ] **Step 2: 干跑 macro_monthly.run()（mock 网络，验证流程不报错）**

```bash
cd backend && .venv/bin/python -c "
# 验证模块可导入、函数签名正确、CSV 映射完整
from src.domain.market.sync.jobs import macro_monthly as mm
print('CSV_SEED_MAP codes:', sorted(mm._CSV_SEED_MAP.keys()))
print('DERIVED_CODES:', mm._DERIVED_CODES)
from src.domain.market.sync.providers.akshare_provider import AkshareProvider
prov = AkshareProvider()
print('EXTRACTORS cn codes:', sorted(
    [c for c in prov._MACRO_EXTRACTORS if c.startswith('cn_')]))
print('DERIVED keys:', sorted(prov._MACRO_DERIVED.keys()))
print('OK: 所有模块可导入')
"
```
Expected: 打印各 code 列表，无 ImportError。

- [ ] **Step 3: 检查 config 指标完整性**

```bash
cd backend && .venv/bin/python -c "
from conf import app_config
codes = {i.code: i.provider for i in app_config.macro_universe.indicators}
print(f'总指标数: {len(codes)}')
ak = [c for c,p in codes.items() if p == 'akshare']
csv = [c for c,p in codes.items() if p == 'csv_seed']
print(f'akshare: {len(ak)} 个 → {sorted(ak)}')
print(f'csv_seed: {len(csv)} 个 → {sorted(csv)}')
# 验证用户清单 20 项主题全覆盖
required = ['cn_cpi_yoy','cn_pmi','cn_m1_yoy','cn_m2_yoy','cn_lpr_1y',
            'cn_sf','cn_house_sales_amt','cn_industrial_yoy',
            'cn_deposit_demand_ratio','cn_loan_household']
for r in required:
    assert any(r in c or c in r for c in codes), f'缺失: {r}'
print('OK: 关键指标全覆盖')
"
```
Expected: 总指标 ≥ 25，关键指标校验通过。

- [ ] **Step 4: 最终 commit（若有残留改动）**

```bash
git status
# 若有未提交的改动：
# git add -A && git commit -m "test(macro): e2e smoke test passes"
```

---

## Self-Review 记录（plan 作者填写）

**Spec 覆盖性**：
- ✅ A 档 11 项（akshare 自动）→ Task 2（5项）+ Task 3（社融6分项）+ 现有 cn_cpi/ppi/pmi/m2/sf/lpr（已在）
- ✅ B 档 2 项（固投/地产投资，接口停更）→ Task 4
- ✅ C 档 11 项（CSV 种子）→ Task 6（CSV）+ Task 8（导入逻辑）
- ✅ 派生 2 项（存款占比）→ Task 5
- ✅ config 元数据 → Task 7
- ✅ 月度 job 编排 → Task 8
- ✅ 调度注册 → Task 9
- ✅ PDF 下载 → Task 1

**placeholder 扫描**：Task 7 Step 1 注明"其余指标元数据按同样格式追加，实现时全部写全"——这是有意的，因为完整 YAML 太长，模板已给全字段。实现者须写全。

**类型一致性**：`fetch_macro_series` / `fetch_macro_derived` 返回 `list[tuple]`，元素 `(report_date, value, freq, unit)`，job 中解包一致。`_seed_from_csv` 签名在测试和实现中一致。

**已知风险**（实现者注意）：
1. Task 4 的 `macro_china_gdzctz` 列名需实测确认（已注明）
2. Task 6 的 CSV 是占位数据，真实历史数据需后续补充（README 已注明）
3. `macro_china_hk_building_amount` 的日期列名（`发布日期` vs `时间`）需在 Task 2 实现时确认
