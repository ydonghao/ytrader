# 宏观经济板块增强（两段式 AI 意见 + 人机留痕）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 `/macro` 板块上增量改造，实现 AI 两段式意见（客观解读 + 折叠立场）、人偶尔记录判断、双轨验证分开打分、指标按中美分组。

**Architecture:** 复用现有 `macro_view` 表（加 2 字段：`author` / `objective_reading`）+ 现有 `macro_analyst` agent（改 schema + prompt 为两段式）+ 现有 `validate_pending` job（对 user 记录扩展代表指数验证）。前端 Macro.tsx 改造指标分组、两段式渲染、折叠、记录表单、来源列。验证机制 AI 与人共用，零额外验证代码（仅 user 走代理验证分支）。

**Tech Stack:** Python 3.13 / FastAPI / SQLModel (PostgreSQL) / LangChain structured output / React 18 + TypeScript + recharts / APScheduler

## Global Constraints

- 无 Alembic，靠 `SQLModel.metadata.create_all` 自动建表/加列（Postgres 对已有表的新列需显式 ALTER——本计划用 `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN IF NOT EXISTS` 兜底）。
- 后端运行环境：`.venv/bin/python`（项目 venv，Python 3.13）。
- prompt 模板走 DB（`prompt_template` 表），seed 仅在不存在时插入；**更新已存在的 prompt 需用版本化迁移函数**（不覆盖用户编辑，通过提升 version + 写新行实现；本计划采用 `update_prompt_template` 仓库方法，它会归档旧版本到 `prompt_template_history`）。
- 统一返回格式 `responses.success/fail`（`src/pkg/responses`）。
- 前端 Apple Dark 设计 token，复用现有 `Indices.css`/`Intel.css` 的 token 命名。
- 提交信息格式：`feat(macro): ...` / `fix(macro): ...`。

## File Structure

**后端（修改）：**
- `backend/src/infra/database/market/macro_view.py` — MacroView 模型加 `author`/`objective_reading`；`_row_to_dict` 序列化；新增 `list_views` 的 author 过滤。
- `backend/src/domain/market/intel/macro/schemas.py` — `MacroViewResult` 加 `objective_reading` 字段。
- `backend/src/domain/market/intel/macro/agents/macro_analyst.py` — 返回值加 `objective_reading`；落库写 `author='ai'`。
- `backend/src/domain/market/intel/macro/snapshot.py` — `generate_snapshot` 落库加 author/objective_reading；新增 `validate_user_stance`；`validate_pending` 分支调用。
- `backend/src/infra/database/agent/repository.py` — `_MACRO_PROMPT_SEEDS` 更新为两段式；新增 `migrate_macro_prompts_v2`（更新已存在 prompt）。
- `backend/main.py` — 启动调用 `migrate_macro_prompts_v2`。
- `backend/src/api/handler/macro_handler.py` — 新增 `record_view`（人记录）；`list_views`/`dashboard` 返回 author。
- `backend/src/api/router/macro_router.py` — 新增 `POST /macro/views/record` 路由。

**前端（修改）：**
- `frontend/apps/web/src/pages/Macro.tsx` — 指标按 category 分组；两段式渲染（objective_reading 展开/立场折叠）；记录表单；历史表加来源列。
- `frontend/apps/web/src/pages/Macro.css` — 分组标题、客观/立场的视觉区分、折叠样式、记录表单样式。

---

## Task 1: macro_view 表加 author + objective_reading 字段

**Files:**
- Modify: `backend/src/infra/database/market/macro_view.py`

**Interfaces:**
- Produces: `MacroView.author` (str, default 'ai'), `MacroView.objective_reading` (str, default '')；`_row_to_dict` 输出含这两个字段。

- [ ] **Step 1: 在 MacroView 模型加两个字段**

在 `backend/src/infra/database/market/macro_view.py` 的 `MacroView` 类，`id` 字段后加 `author`；`summary` 字段后加 `objective_reading`。

找到（约第 40-42 行）：
```python
    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_date: date = Field(index=True)            # 判断时刻 T
    horizon_days: int = Field(default=63)              # 验证窗口（≈1 季度交易日）
```
改为：
```python
    id: Optional[int] = Field(default=None, primary_key=True)
    author: str = Field(default="ai", index=True)      # 'ai' / 'user'（留痕主体）
    snapshot_date: date = Field(index=True)            # 判断时刻 T
    horizon_days: int = Field(default=63)              # 验证窗口（≈1 季度交易日）
```

找到（约第 52 行）：
```python
    summary: str = Field(default="")                    # 宏观叙事自由文本
```
改为：
```python
    summary: str = Field(default="")                    # 立场理由叙事（AI）/ 判断理由（人）
    objective_reading: str = Field(default="")          # AI 客观解读（不下结论，逐指标解释）
```

- [ ] **Step 2: `_row_to_dict` 序列化新字段**

在 `_row_to_dict` 函数（约第 162 行），`"id": r.id,` 后加 `"author": r.author,`；`"summary": r.summary,` 后加 `"objective_reading": r.objective_reading,`。

找到：
```python
    return {
        "id": r.id,
        "snapshot_date": r.snapshot_date.isoformat() if r.snapshot_date else None,
```
改为：
```python
    return {
        "id": r.id,
        "author": r.author,
        "snapshot_date": r.snapshot_date.isoformat() if r.snapshot_date else None,
```

找到：
```python
        "summary": r.summary,
        "signals": r.signals or {},
```
改为：
```python
        "summary": r.summary,
        "objective_reading": r.objective_reading,
        "signals": r.signals or {},
```

- [ ] **Step 3: 新增 schema 迁移函数（ALTER TABLE 加列）**

在 `macro_view.py` 文件末尾、`create_macro_view_repository` 函数后，加一个迁移函数：

```python
def ensure_macro_view_columns() -> None:
    """为已存在的 macro_view 表补 author / objective_reading 列（无 Alembic 兜底）。

    SQLModel.metadata.create_all 不会给已存在的表加新列，故用 ALTER TABLE IF NOT EXISTS。
    幂等：列已存在时跳过。在 app 启动时调用。
    """
    from sqlalchemy import text
    db = _get_db_connection()
    with db.session_scope() as s:
        s.exec(text(
            "ALTER TABLE macro_view ADD COLUMN IF NOT EXISTS author VARCHAR DEFAULT 'ai'"
        ))
        s.exec(text(
            "ALTER TABLE macro_view ADD COLUMN IF NOT EXISTS objective_reading TEXT DEFAULT ''"
        ))
        # 给 author 建索引（若不存在）
        s.exec(text(
            "CREATE INDEX IF NOT EXISTS ix_macro_view_author ON macro_view (author)"
        ))
```

- [ ] **Step 4: 验证字段加成功**

Run:
```bash
cd backend && timeout 60 .venv/bin/python -c "
import logging; logging.disable(logging.CRITICAL)
from src.infra.database.market.macro_view import ensure_macro_view_columns, create_macro_view_repository
ensure_macro_view_columns()
repo = create_macro_view_repository()
latest = repo.get_latest()
if latest:
    print('author:', latest.get('author'), '| objective_reading:', repr(latest.get('objective_reading'))[:30])
else:
    print('no views yet (OK)')
print('MIGRATION OK')
"
```
Expected: 输出 `MIGRATION OK`，老数据 author 显示 `ai`。

- [ ] **Step 5: Commit**

```bash
cd backend && git add src/infra/database/market/macro_view.py
git commit -m "feat(macro): add author + objective_reading columns to macro_view"
```

---

## Task 2: MacroViewResult schema 加 objective_reading 字段

**Files:**
- Modify: `backend/src/domain/market/intel/macro/schemas.py`

**Interfaces:**
- Produces: `MacroViewResult.objective_reading: str`（客观解读，禁下结论）。

- [ ] **Step 1: 在 MacroViewResult 加 objective_reading 字段**

在 `backend/src/domain/market/intel/macro/schemas.py` 的 `MacroViewResult` 类，`macro_judgments` 字段前加 `objective_reading`：

找到（约第 43 行）：
```python
class MacroViewResult(BaseModel):
    """宏观分析师 agent 的完整结构化输出。"""

    macro_judgments: list[MacroJudgment] = Field(
```
改为：
```python
class MacroViewResult(BaseModel):
    """宏观分析师 agent 的完整结构化输出。"""

    objective_reading: str = Field(
        description=(
            "客观解读（第一段，不下结论）：逐指标解释当前值含义、趋势方向、"
            "与历史/阈值对比、指标间关系。禁止结论性判断（不说偏多/偏空、不说利好/利空）。"
        ),
    )
    macro_judgments: list[MacroJudgment] = Field(
```

- [ ] **Step 2: 验证 schema 可实例化**

Run:
```bash
cd backend && .venv/bin/python -c "
import logging; logging.disable(logging.CRITICAL)
from src.domain.market.intel.macro.schemas import MacroViewResult
r = MacroViewResult(
    objective_reading='PMI回升至50.3，处于扩张区间',
    macro_judgments=[], regime_quadrant='recovery',
    overall_stance='bullish', confidence=7.0, summary='test', asset_predictions=[],
)
print('objective_reading:', r.objective_reading)
print('SCHEMA OK')
"
```
Expected: `SCHEMA OK`

- [ ] **Step 3: Commit**

```bash
cd backend && git add src/domain/market/intel/macro/schemas.py
git commit -m "feat(macro): add objective_reading to MacroViewResult schema"
```

---

## Task 3: macro_analyst agent 返回 objective_reading

**Files:**
- Modify: `backend/src/domain/market/intel/macro/agents/macro_analyst.py`

**Interfaces:**
- Produces: `macro_analyst_node` 返回 dict 含 `objective_reading` 键。

- [ ] **Step 1: 返回值加 objective_reading**

在 `backend/src/domain/market/intel/macro/agents/macro_analyst.py` 的 `macro_analyst_node` 返回 dict（约第 108 行）：

找到：
```python
    return {
        "macro_judgments": [j.model_dump() for j in result.macro_judgments],
        "regime_quadrant": result.regime_quadrant,
```
改为：
```python
    return {
        "objective_reading": result.objective_reading,
        "macro_judgments": [j.model_dump() for j in result.macro_judgments],
        "regime_quadrant": result.regime_quadrant,
```

- [ ] **Step 2: 验证 agent 返回结构（不调 LLM，mock 验证字段路径）**

Run:
```bash
cd backend && .venv/bin/python -c "
import logging; logging.disable(logging.CRITICAL)
# 验证 import 无误 + 返回 dict 构造逻辑含 objective_reading（不实际调 LLM）
from src.domain.market.intel.macro.agents.macro_analyst import macro_analyst_node
print('node importable:', macro_analyst_node.__name__)
# 构造 mock 返回验证字段路径
mock = {'objective_reading':'x','macro_judgments':[],'regime_quadrant':'r','overall_stance':'bullish','confidence':7.0,'summary':'s','asset_predictions':[],'signals':{}}
assert 'objective_reading' in mock
print('RETURN STRUCT OK')
"
```
Expected: `RETURN STRUCT OK`

- [ ] **Step 3: Commit**

```bash
cd backend && git add src/domain/market/intel/macro/agents/macro_analyst.py
git commit -m "feat(macro): return objective_reading from macro_analyst_node"
```

---

## Task 4: generate_snapshot 落库 author + objective_reading

**Files:**
- Modify: `backend/src/domain/market/intel/macro/snapshot.py`

**Interfaces:**
- Consumes: Task 1 的 `ensure_macro_view_columns`、Task 3 的 `objective_reading` 返回。

- [ ] **Step 1: generate_snapshot 落库加字段**

在 `backend/src/domain/market/intel/macro/snapshot.py` 的 `generate_snapshot` 函数，落库 dict（约第 88-99 行）：

找到：
```python
    view_id = repo.create({
        "snapshot_date": snapshot_date,
        "horizon_days": horizon,
        "macro_judgments": result.get("macro_judgments", []),
        "regime_quadrant": result.get("regime_quadrant", ""),
        "overall_stance": result.get("overall_stance", "neutral"),
        "confidence": result.get("confidence", 5.0),
        "summary": result.get("summary", ""),
        "signals": result.get("signals", {}),
        "asset_predictions": result.get("asset_predictions", []),
        "status": "pending",
        "llm_run_id": run_id,
    })
```
改为：
```python
    view_id = repo.create({
        "snapshot_date": snapshot_date,
        "author": "ai",
        "horizon_days": horizon,
        "objective_reading": result.get("objective_reading", ""),
        "macro_judgments": result.get("macro_judgments", []),
        "regime_quadrant": result.get("regime_quadrant", ""),
        "overall_stance": result.get("overall_stance", "neutral"),
        "confidence": result.get("confidence", 5.0),
        "summary": result.get("summary", ""),
        "signals": result.get("signals", {}),
        "asset_predictions": result.get("asset_predictions", []),
        "status": "pending",
        "llm_run_id": run_id,
    })
```

- [ ] **Step 2: Commit**

```bash
cd backend && git add src/domain/market/intel/macro/snapshot.py
git commit -m "feat(macro): persist author + objective_reading in generated snapshots"
```

---

## Task 5: 新增人记录 API（POST /macro/views/record）

**Files:**
- Modify: `backend/src/api/handler/macro_handler.py`
- Modify: `backend/src/api/router/macro_router.py`

**Interfaces:**
- Produces: `macro_handler.record_view(body)` + `POST /macro/views/record`。

- [ ] **Step 1: handler 加 record_view 函数**

在 `backend/src/api/handler/macro_handler.py` 文件末尾，`generate_view` 函数后加：

```python
def record_view(body: dict) -> Any:
    """人记录自己的宏观判断（立场 + 置信度 + 理由）。

    创建一条 author='user' 的 macro_view，status='pending'，等待季度后验证。
    """
    from datetime import date as _date
    from conf import app_config
    from src.infra.database.market.macro_view import (
        create_macro_view_repository,
    )

    overall_stance = (body.get("overall_stance") or "").strip()
    summary = (body.get("summary") or "").strip()
    if overall_stance not in ("bullish", "bearish", "neutral"):
        return responses.fail(msg="overall_stance 必须为 bullish/bearish/neutral")
    if not summary:
        return responses.fail(msg="summary（判断理由）不能为空")

    confidence = body.get("confidence", 5.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 5.0
    confidence = max(0.0, min(10.0, confidence))

    repo = create_macro_view_repository()
    view_id = repo.create({
        "snapshot_date": _date.today(),
        "author": "user",
        "horizon_days": app_config.macro_universe.snapshot_horizon_days,
        "overall_stance": overall_stance,
        "confidence": confidence,
        "summary": summary,
        "macro_judgments": [],
        "asset_predictions": [],
        "signals": {},
        "status": "pending",
    })
    return responses.success({"view_id": view_id, "msg": "判断已记录，将在季度后验证"})
```

- [ ] **Step 2: router 加 POST /macro/views/record**

在 `backend/src/api/router/macro_router.py`：

顶部 import 改为（加 `record_view`）：
```python
from src.api.handler.macro_handler import (
    dashboard,
    generate_view,
    get_view,
    indicator_series,
    latest_indicators,
    list_views,
    record_view,
    track_view,
)
```

文件末尾（`_view_generate` 后）加：
```python
@router.post("/views/record")
def _view_record(body: dict):
    return record_view(body)
```

- [ ] **Step 3: 验证人记录端点**

Run:
```bash
cd backend && timeout 60 .venv/bin/python -c "
import logging; logging.disable(logging.CRITICAL)
from src.api.handler.macro_handler import record_view
from src.infra.database.market.macro_view import create_macro_view_repository, MacroView
from src.infra.database.sql_engine.engine import create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn
from sqlmodel import delete

# 合法记录
r = record_view({'overall_stance':'bullish','confidence':7,'summary':'PMI回升+社融转正，复苏信号'})
import json; d = json.loads(r.body)
print('record result:', d)
assert d['code'] == 0
vid = d['data']['view_id']

# 验证存入
repo = create_macro_view_repository()
got = repo.get(vid)
print('author:', got['author'], '| stance:', got['overall_stance'], '| summary:', got['summary'])

# 非法 stance
r2 = record_view({'overall_stance':'xxx','summary':'test'})
d2 = json.loads(r2.body)
print('invalid stance:', d2['code'], d2['msg'])
assert d2['code'] != 0

# 空 summary
r3 = record_view({'overall_stance':'bullish','summary':''})
d3 = json.loads(r3.body)
print('empty summary:', d3['code'])
assert d3['code'] != 0

# cleanup
db = create_db_connection(get_dsn())
with db.session_scope() as s:
    s.exec(delete(MacroView).where(MacroView.id == vid))
print('CLEANUP DONE')
"
```
Expected: 合法记录 code=0 且 author=user；非法 stance/空 summary code!=0；`CLEANUP DONE`。

- [ ] **Step 4: Commit**

```bash
cd backend && git add src/api/handler/macro_handler.py src/api/router/macro_router.py
git commit -m "feat(macro): add POST /macro/views/record for human judgments"
```

---

## Task 6: 人记录的验证（代表指数组合对照 stance）

**Files:**
- Modify: `backend/src/domain/market/intel/macro/snapshot.py`

**Interfaces:**
- Consumes: `_period_return`（已有，snapshot.py 内）。

- [ ] **Step 1: 新增 validate_user_stance 函数**

在 `backend/src/domain/market/intel/macro/snapshot.py` 的 `_validate_asset_predictions` 函数后，加：

```python
# 人记录验证用的代表指数组合（沪深300 + 标普500 等权）
_USER_STANCE_PROXY_SYMBOLS = ["sh000300", "US.INX"]


def validate_user_stance(
    stance: str, snapshot_date: date, as_of: date,
) -> tuple[list[dict], float | None]:
    """人记录的立场验证：用代表指数组合（沪深300+标普500）实际方向对照。

    人只填 overall_stance（bullish/bearish/neutral），无 macro_judgments 维度。
    bullish → 预期组合上涨、bearish → 预期下跌、neutral → 预期震荡。
    返回 (validation_list, accuracy)。accuracy 为 0.0 或 1.0（单命题）。
    """
    validated_at = datetime.now().isoformat()
    stance_to_dir = {"bullish": "up", "bearish": "down", "neutral": "flat"}
    predicted = stance_to_dir.get(stance, "flat")

    # 取组合各成分收益，等权平均
    returns = []
    details = []
    for sym in _USER_STANCE_PROXY_SYMBOLS:
        ret = _period_return(sym, snapshot_date, as_of)
        if ret is not None:
            returns.append(ret)
            details.append({"symbol": sym, "return_pct": round(ret * 100, 2)})

    if not returns:
        return [{
            "dimension": "overall_stance", "predicted": predicted,
            "actual_dir": None, "hit": None,
            "validated_at": validated_at, "note": "代表指数数据不足",
        }], None

    avg_ret = sum(returns) / len(returns)
    actual_dir = "up" if avg_ret > 0.01 else ("down" if avg_ret < -0.01 else "flat")
    hit = (predicted == actual_dir)
    return [{
        "dimension": "overall_stance", "predicted": predicted,
        "actual_dir": actual_dir, "actual_value": round(avg_ret * 100, 2),
        "hit": hit, "validated_at": validated_at,
        "proxy": details,
    }], (1.0 if hit else 0.0)
```

- [ ] **Step 2: validate_pending 对 author='user' 分支调用**

在 `validate_pending` 函数（约第 200 行），找到循环体：

```python
    for v in pending:
        try:
            snap = v["snapshot_date"]
            snap_date = datetime.strptime(snap, "%Y-%m-%d").date() if isinstance(snap, str) else snap
            macro_val, macro_acc = _validate_macro_judgments(
                v.get("macro_judgments", []), snap_date, as_of)
            asset_val, asset_acc = _validate_asset_predictions(
                v.get("asset_predictions", []), snap_date, as_of)
```
改为：
```python
    for v in pending:
        try:
            snap = v["snapshot_date"]
            snap_date = datetime.strptime(snap, "%Y-%m-%d").date() if isinstance(snap, str) else snap
            if v.get("author") == "user":
                # 人记录：只验证 overall_stance（用代表指数组合）
                macro_val, macro_acc = validate_user_stance(
                    v.get("overall_stance", "neutral"), snap_date, as_of)
                asset_val, asset_acc = [], None
            else:
                macro_val, macro_acc = _validate_macro_judgments(
                    v.get("macro_judgments", []), snap_date, as_of)
                asset_val, asset_acc = _validate_asset_predictions(
                    v.get("asset_predictions", []), snap_date, as_of)
```

- [ ] **Step 3: 验证人记录的验证逻辑**

Run:
```bash
cd backend && timeout 60 .venv/bin/python -c "
import logging; logging.disable(logging.CRITICAL)
from datetime import date, timedelta
from src.domain.market.intel.macro.snapshot import validate_user_stance
# 用 120 天前做 snapshot，验证窗口已过
snap = date.today() - timedelta(days=120)
val, acc = validate_user_stance('bullish', snap, date.today())
print('validation:', val)
print('accuracy:', acc)
assert acc in (0.0, 1.0)
print('USER VALIDATION OK')
"
```
Expected: 输出验证详情 + accuracy 为 0.0 或 1.0 + `USER VALIDATION OK`。

- [ ] **Step 4: Commit**

```bash
cd backend && git add src/domain/market/intel/macro/snapshot.py
git commit -m "feat(macro): validate human stance via proxy index composite"
```

---

## Task 7: 更新 prompt 为两段式（版本化迁移）

**Files:**
- Modify: `backend/src/infra/database/agent/repository.py`
- Modify: `backend/main.py`

**注意：** 现有 `_MACRO_PROMPT_SEEDS` 只在不存在时插入。已存在的 prompt 需通过 `update_prompt_template` 更新（自动归档旧版本到 history）。本任务新增一个 v2 迁移函数，强制更新两段式 prompt。

- [ ] **Step 1: 更新 _MACRO_PROMPT_SEEDS 为两段式（供全新部署用）**

在 `backend/src/infra/database/agent/repository.py` 的 `_MACRO_PROMPT_SEEDS`（约第 1431 行），把 system prompt 的 template 替换为两段式版本：

找到 `"template": (` 开始到对应 `),` 结束的 system prompt 块（约第 1437-1457 行），替换为：

```python
        "template": (
            "你是一位严谨的宏观经济分析师，负责生成可证伪、可回测的宏观判断快照。\n\n"
            "【方法论·组合理论框架】你必须基于以下经典理论框架推理，不可凭直觉：\n"
            "1. 美林时钟（增长×通胀定位象限）：复苏→利股 / 过热→利商品 / 滞胀→利现金 / 衰退→利债。\n"
            "2. 货币主义（Friedman）：M2 增速领先通胀 12-18 个月。\n"
            "3. 达里奥债务周期：信贷扩张→繁荣→去杠杆，利率/社融是枢纽。\n"
            "4. 金融周期（BIS）：信贷缺口 + 杠杆累积，判断金融脆弱性。\n"
            "5. 收益率曲线倒挂：衰退先行指标。\n\n"
            "【三条铁律】\n"
            "1. 趋势比绝对值重要。\n2. 拐点比水平重要。\n3. 共振比单指标可靠。\n\n"
            "【输出·分两段，缺一不可】\n"
            "第一段·objective_reading（客观解读）：逐指标解释当前值含义、趋势方向、与历史/阈值对比、指标间关系。\n"
            "  ⚠️ 这一段【禁止任何结论性判断】：不说'偏多/偏空'，不说'利好/利空'，不下任何方向结论。\n"
            "  只陈述事实与含义，让读者自己形成判断。\n"
            "第二段·立场：基于客观解读，给出 overall_stance(bullish/bearish/neutral) + confidence + "
            "macro_judgments(各维度方向) + asset_predictions(资产方向) + summary(立场理由)。\n"
            "  立场理由须引用具体数据点 + 点明理论框架。\n\n"
            "【上下文数据】\n{{ context }}\n\n"
            "请严格按两段式输出。"
        ),
```

user prompt 的 template（约第 1464-1471 行）替换为：

```python
        "template": (
            "今天是 {{ snapshot_date }}。请基于上方上下文数据，生成未来 {{ horizon_days }} 个交易日（约1个季度）的宏观判断快照。\n\n"
            "务必分两段：\n"
            "1. objective_reading：先做客观解读，逐指标讲含义与关系，【不下任何结论】。\n"
            "2. 立场：再给 overall_stance + confidence + macro_judgments + asset_predictions + summary。\n"
            "用组合理论框架定位周期象限（regime_quadrant）。summary 是立场理由（非客观解读）。"
        ),
```

- [ ] **Step 2: 新增 migrate_macro_prompts_v2 函数（强制更新已存在 prompt）**

在 `migrate_macro_prompts` 函数后（约第 1515 行），加：

```python
def migrate_macro_prompts_v2() -> None:
    """强制把 macro_analyst prompt 升级为两段式版本。

    与 migrate_macro_prompts（仅不存在时插入）不同，此函数用 update_prompt_template
    更新已存在的行（旧版本自动归档到 prompt_template_history）。
    幂等：通过 template 内容前缀判断是否已是 v2，已升级则跳过。
    """
    from src.infra.database.llm.entity import LLMConfigTable  # noqa: F401
    db = _get_db_connection()
    v2_marker = "【输出·分两段，缺一不可】"
    with db.session_scope() as session:
        updated = 0
        for seed in _MACRO_PROMPT_SEEDS:
            existing = session.exec(
                select(PromptTemplateTable).where(
                    PromptTemplateTable.name == seed["name"]
                )
            ).first()
            if not existing:
                # 全新部署：直接插入（走 seed 路径）
                _upsert_prompt_template(session, seed)
                updated += 1
                continue
            if v2_marker in (existing.template or ""):
                continue  # 已是 v2
            # 升级：update_prompt_template 归档旧版 + 写新版
            _update_prompt_template_inplace(session, existing, seed)
            updated += 1
        if updated:
            logger.info(f"[agent_db] Migrated macro prompts to v2: {updated} rows")


def _update_prompt_template_inplace(session, row, seed: dict) -> None:
    """就地更新 prompt template 行：归档旧版到 history，提升 version，写新内容。

    （简化版 update_prompt_template，避免循环 import；复用 prompt_template_history 表。）
    """
    from src.infra.database.agent.entity import PromptTemplateHistoryTable
    # 归档旧版
    session.add(PromptTemplateHistoryTable(
        template_id=row.id,
        name=row.name,
        template=row.template,
        variables=row.variables,
        category=row.category,
        version=row.version,
    ))
    # 写新版
    row.template = seed["template"]
    row.variables = seed["variables"]
    row.description = seed["description"]
    row.version = (row.version or 1) + 1
```

- [ ] **Step 3: main.py 启动调用 migrate_macro_prompts_v2**

在 `backend/main.py` 的 lifespan 启动块（约第 134-142 行）：

找到：
```python
        from src.infra.database.agent.repository import (
            seed_agent_data,
            migrate_blog_prompts,
            migrate_agent_tools,
            migrate_macro_prompts,
        )
        seed_agent_data()
        migrate_blog_prompts()
        migrate_agent_tools()
        migrate_macro_prompts()
```
改为：
```python
        from src.infra.database.agent.repository import (
            seed_agent_data,
            migrate_blog_prompts,
            migrate_agent_tools,
            migrate_macro_prompts,
            migrate_macro_prompts_v2,
        )
        seed_agent_data()
        migrate_blog_prompts()
        migrate_agent_tools()
        migrate_macro_prompts()
        migrate_macro_prompts_v2()
```

- [ ] **Step 4: 验证 prompt 升级**

Run:
```bash
cd backend && timeout 60 .venv/bin/python -c "
import logging; logging.disable(logging.CRITICAL)
from src.infra.database.sql_engine.engine import create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn
create_db_connection(get_dsn())  # trigger create_all
from src.infra.database.agent.repository import migrate_macro_prompts_v2, create_agent_repository
migrate_macro_prompts_v2()
repo = create_agent_repository()
tmpl = repo.get_prompt_template_by_name('macro_analyst_system')
print('has v2 marker:', '【输出·分两段，缺一不可】' in tmpl.template)
print('version:', tmpl.version if hasattr(tmpl,'version') else 'n/a')
assert '【输出·分两段，缺一不可】' in tmpl.template
print('PROMPT V2 OK')
"
```
Expected: `PROMPT V2 OK`。

- [ ] **Step 5: Commit**

```bash
cd backend && git add src/infra/database/agent/repository.py main.py
git commit -m "feat(macro): upgrade analyst prompt to two-tier (objective reading + stance)"
```

---

## Task 8: main.py 启动调用 ensure_macro_view_columns

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: lifespan 启动加列迁移**

在 `backend/main.py` 的 lifespan 启动块，agent 迁移之后（migrate_macro_prompts_v2 后），加：

找到（Task 7 Step 3 改后的块）：
```python
        migrate_macro_prompts_v2()
        app_logger.info("[Agent] tables migrated and seeded")
```
改为：
```python
        migrate_macro_prompts_v2()
        app_logger.info("[Agent] tables migrated and seeded")

    # macro_view 表加列兜底（无 Alembic）
    try:
        from src.infra.database.market.macro_view import ensure_macro_view_columns
        ensure_macro_view_columns()
        app_logger.info("[Macro] macro_view columns ensured")
    except Exception as e:
        app_logger.warning(f"[Macro] column migration failed: {e}")
```

- [ ] **Step 2: Commit**

```bash
cd backend && git add main.py
git commit -m "feat(macro): ensure macro_view columns at startup"
```

---

## Task 9: 前端 Macro.tsx — 指标按国家分组

**Files:**
- Modify: `frontend/apps/web/src/pages/Macro.tsx`
- Modify: `frontend/apps/web/src/pages/Macro.css`

**Interfaces:**
- Consumes: `GET /macro/indicators/latest` 返回 `meta.category`（'cn'/'us'）。

- [ ] **Step 1: 指标卡片按 category 分组渲染**

在 `frontend/apps/web/src/pages/Macro.tsx`，找到指标渲染区块（`{indicators.map((ind) => {` 那段，约在 "❶ 宏观指标读数" section）。

替换整个 `<div className="macro__indicator-grid">...</div>` 块为分组版本：

找到：
```tsx
        <div className="macro__indicator-grid">
          {loading
            ? [0, 1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="macro__indicator-card skeleton" style={{height: 100}} />
              ))
            : indicators.map((ind) => {
                const badge = badgeFor(ind);
                return (
                  <div key={ind.indicator_code} className="macro__indicator-card">
                    <div className="macro__indicator-name">
                      {ind.meta?.name || ind.indicator_code}
                      <span className="macro__indicator-cat">{ind.meta?.category?.toUpperCase()}</span>
                    </div>
                    <div className="macro__indicator-value">
                      {fmtNum(ind.value, ind.value < 10 ? 1 : 0)}
                      <span className="macro__indicator-unit">{ind.meta?.unit}</span>
                    </div>
                    <div className="macro__indicator-meta">
                      <span className="macro__indicator-date">{ind.report_date}</span>
                      {badge && (
                        <span className={`macro__indicator-badge ${badge.cls}`}>
                          {badge.text}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
        </div>
```

替换为（按 category 分组 + 去掉卡片内的 cat 标签）：
```tsx
        {loading
          ? (
            <div className="macro__indicator-grid">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="macro__indicator-card skeleton" style={{height: 100}} />
              ))}
            </div>
          )
          : (['cn', 'us'] as const).map((cat) => {
              const groupInds = indicators.filter((i) => (i.meta?.category || 'cn') === cat);
              if (groupInds.length === 0) return null;
              const groupLabel = cat === 'cn' ? '中国' : '美国';
              return (
                <div key={cat} className="macro__indicator-group">
                  <h3 className="macro__indicator-group-title">{groupLabel}</h3>
                  <div className="macro__indicator-grid">
                    {groupInds.map((ind) => {
                      const badge = badgeFor(ind);
                      return (
                        <div key={ind.indicator_code} className="macro__indicator-card">
                          <div className="macro__indicator-name">
                            {ind.meta?.name || ind.indicator_code}
                          </div>
                          <div className="macro__indicator-value">
                            {fmtNum(ind.value, ind.value < 10 ? 1 : 0)}
                            <span className="macro__indicator-unit">{ind.meta?.unit}</span>
                          </div>
                          <div className="macro__indicator-meta">
                            <span className="macro__indicator-date">{ind.report_date}</span>
                            {badge && (
                              <span className={`macro__indicator-badge ${badge.cls}`}>
                                {badge.text}
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
```

- [ ] **Step 2: CSS 加分组标题样式**

在 `frontend/apps/web/src/pages/Macro.css` 的 `.macro__indicator-grid` 规则前，加：

```css
.macro__indicator-group {
  margin-bottom: var(--space-5);
}

.macro__indicator-group:last-child {
  margin-bottom: 0;
}

.macro__indicator-group-title {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  margin-bottom: var(--space-3);
  padding-left: var(--space-2);
  border-left: 3px solid var(--color-accent);
}
```

- [ ] **Step 3: 验证前端构建**

Run:
```bash
cd frontend/apps/web && timeout 180 npx tsc --noEmit 2>&1 | grep -iE "Macro" | head
```
Expected: 无 Macro 相关错误（已有的 jest/vite/rootDir 配置错误不算）。

```bash
cd frontend/apps/web && timeout 300 npm run build 2>&1 | tail -3
```
Expected: `built in` 成功。

- [ ] **Step 4: Commit**

```bash
cd frontend && git add apps/web/src/pages/Macro.tsx apps/web/src/pages/Macro.css
git commit -m "feat(macro): group indicators by country (cn/us)"
```

---

## Task 10: 前端 Macro.tsx — 两段式渲染 + 立场折叠

**Files:**
- Modify: `frontend/apps/web/src/pages/Macro.tsx`
- Modify: `frontend/apps/web/src/pages/Macro.css`

- [ ] **Step 1: MacroView 类型加 objective_reading + author**

在 `frontend/apps/web/src/pages/Macro.tsx` 的 `MacroView` interface（约第 60 行），加字段：

找到：
```tsx
interface MacroView {
  id: number;
  snapshot_date: string;
  horizon_days: number;
```
改为：
```tsx
interface MacroView {
  id: number;
  author: string;
  snapshot_date: string;
  horizon_days: number;
  objective_reading: string;
```

找到：
```tsx
  macro_judgments: MacroJudgment[];
  regime_quadrant: string;
  overall_stance: string;
```
改为：
```tsx
  macro_judgments: MacroJudgment[];
  objective_reading: string;
  regime_quadrant: string;
  overall_stance: string;
```

（注：objective_reading 出现两次声明会冲突，只保留 interface 顶部那处。最终 MacroView interface 应只含一个 `objective_reading: string;` 字段。）

- [ ] **Step 2: 两段式渲染（客观解读展开 + 立场折叠）**

找到最新快照渲染区块（`{latestView ? (` 那段，`<div className="macro__snapshot">` 内部）。

在 `<div className="macro__snapshot-summary">{latestView.summary}</div>` 这行**之前**，插入客观解读区，并把原来的 summary 改成折叠的立场区。

找到：
```tsx
            <div className="macro__snapshot-summary">{latestView.summary}</div>
```
替换为：
```tsx
            {/* 第一段·客观解读（默认展开） */}
            {latestView.objective_reading && (
              <div className="macro__reading">
                <div className="macro__reading-label">客观解读</div>
                <div className="macro__reading-body">{latestView.objective_reading}</div>
              </div>
            )}

            {/* 第二段·立场（默认折叠） */}
            <details className="macro__stance">
              <summary className="macro__stance-summary">
                <span className="macro__reading-label">AI 立场</span>
                <span className={`macro__snapshot-regime-val ${STANCE_COLOR[latestView.overall_stance] || 'is-flat'}`}>
                  {STANCE_LABEL[latestView.overall_stance] || latestView.overall_stance} · {latestView.confidence.toFixed(1)}/10
                </span>
              </summary>
              <div className="macro__stance-body">
                <p className="macro__stance-reason">{latestView.summary}</p>
                <div className="macro__snapshot-cols">
                  <div className="macro__snapshot-col">
                    <h3 className="macro__snapshot-col-title">宏观状态判断<small>用下季度宏观数据验证</small></h3>
                    {latestView.macro_judgments.map((j, i) => (
                      <div key={i} className="macro__judgment">
                        <div className="macro__judgment-head">
                          <span className="macro__judgment-dim">{DIM_LABEL[j.dimension] || j.dimension}</span>
                          <span className={`macro__judgment-stance ${STANCE_COLOR[j.stance] || 'is-flat'}`}>
                            {STANCE_LABEL[j.stance] || j.stance} · {j.confidence.toFixed(0)}
                          </span>
                        </div>
                        <p className="macro__judgment-rationale">{j.rationale}</p>
                      </div>
                    ))}
                  </div>
                  <div className="macro__snapshot-col">
                    <h3 className="macro__snapshot-col-title">资产方向预测<small>用走势验证</small></h3>
                    {latestView.asset_predictions.map((p, i) => (
                      <div key={i} className="macro__judgment">
                        <div className="macro__judgment-head">
                          <span className="macro__judgment-dim">{p.name} <small>{p.symbol}</small></span>
                          <span className={`macro__judgment-stance ${STANCE_COLOR[p.predicted] || 'is-flat'}`}>
                            {STANCE_LABEL[p.predicted] || p.predicted}
                          </span>
                        </div>
                        <p className="macro__judgment-rationale">{p.rationale}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </details>
```

然后**删除**原来紧跟在 summary 后面的 `<div className="macro__snapshot-cols">...</div>` 整块（两列宏观/资产判断），因为已经移入折叠区内。

- [ ] **Step 3: CSS 加两段式 + 折叠样式**

在 `frontend/apps/web/src/pages/Macro.css` 的 `.macro__snapshot-summary` 规则**之前**，加：

```css
/* 客观解读区 */
.macro__reading {
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
  border-left: 3px solid var(--color-text-tertiary);
}

.macro__reading-label {
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: var(--space-2);
}

.macro__reading-body {
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text-secondary);
  white-space: pre-wrap;
}

/* 立场折叠区 */
.macro__stance {
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
  background: var(--color-surface-raised);
}

.macro__stance-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  cursor: pointer;
  font-size: var(--text-sm);
  list-style: none;
}

.macro__stance-summary::-webkit-details-marker {
  display: none;
}

.macro__stance-summary::before {
  content: '▸';
  color: var(--color-text-tertiary);
  margin-right: var(--space-2);
  transition: transform var(--transition-fast);
}

.macro__stance[open] .macro__stance-summary::before {
  transform: rotate(90deg);
}

.macro__stance-body {
  padding: 0 var(--space-4) var(--space-4);
  border-top: 1px solid var(--color-border);
}

.macro__stance-reason {
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text);
  margin: var(--space-3) 0;
}

.macro__stance .macro__snapshot-cols {
  margin-top: var(--space-3);
}
```

同时把原来 `.macro__snapshot-summary` 的样式保留（它现在用于其他地方若无引用可删，但保留无害）。

- [ ] **Step 4: 验证构建**

Run:
```bash
cd frontend/apps/web && timeout 300 npm run build 2>&1 | tail -3
```
Expected: `built in` 成功。

- [ ] **Step 5: Commit**

```bash
cd frontend && git add apps/web/src/pages/Macro.tsx apps/web/src/pages/Macro.css
git commit -m "feat(macro): two-tier AI view (objective reading + collapsible stance)"
```

---

## Task 11: 前端 Macro.tsx — 人记录表单 + 历史表来源列

**Files:**
- Modify: `frontend/apps/web/src/pages/Macro.tsx`
- Modify: `frontend/apps/web/src/pages/Macro.css`

- [ ] **Step 1: 加记录表单 state + 提交逻辑**

在 `frontend/apps/web/src/pages/Macro.tsx` 的 `Macro` 组件内，找到 `const [trackLoading, setTrackLoading] = useState(false);` 后，加：

```tsx
  const [showRecord, setShowRecord] = useState(false);
  const [recordForm, setRecordForm] = useState({
    overall_stance: 'neutral',
    confidence: 5,
    summary: '',
  });
  const [recording, setRecording] = useState(false);

  const handleRecord = async () => {
    if (!recordForm.summary.trim()) {
      alert('请填写判断理由');
      return;
    }
    setRecording(true);
    try {
      const res = await fetch(`${API_BASE}/macro/views/record`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(recordForm),
      });
      const j = await res.json();
      if (j.code === 0) {
        setShowRecord(false);
        setRecordForm({overall_stance: 'neutral', confidence: 5, summary: ''});
        await fetchDashboard();
      } else {
        alert(j.msg || '记录失败');
      }
    } catch (e) {
      alert('记录失败：' + e);
    } finally {
      setRecording(false);
    }
  };
```

- [ ] **Step 2: 渲染"我记一笔判断"按钮 + 表单**

找到 `{/* ── 3. 历史验证对照（核心）── */}` 之前，`{latestView ? (...) : (...)}` 块之后，加记录入口和表单。

在 `</section>` （最新快照 section 结束）之前、`{/* ── 3.` 之前，插入：

找到：
```tsx
        )}
      </section>

      {/* ── 3. 历史验证对照（核心）── */}
```
改为：
```tsx
        )}
      </section>

      {/* ── 2.5 人记录判断 ── */}
      <section className="macro__section macro__record-section">
        {!showRecord ? (
          <button className="macro__record-btn" onClick={() => setShowRecord(true)}>
            我记一笔判断
          </button>
        ) : (
          <div className="macro__record-form">
            <h3 className="macro__record-title">记下你的宏观判断</h3>
            <div className="macro__record-row">
              <label>你的立场</label>
              <div className="macro__record-stances">
                {(['bullish', 'bearish', 'neutral'] as const).map((s) => (
                  <label key={s} className={`macro__record-stance ${recordForm.overall_stance === s ? 'is-active' : ''}`}>
                    <input
                      type="radio"
                      name="stance"
                      value={s}
                      checked={recordForm.overall_stance === s}
                      onChange={(e) => setRecordForm({...recordForm, overall_stance: e.target.value})}
                    />
                    {STANCE_LABEL[s]}
                  </label>
                ))}
              </div>
            </div>
            <div className="macro__record-row">
              <label>置信度：{recordForm.confidence}/10</label>
              <input
                type="range" min="0" max="10" step="1"
                value={recordForm.confidence}
                onChange={(e) => setRecordForm({...recordForm, confidence: Number(e.target.value)})}
              />
            </div>
            <div className="macro__record-row">
              <label>理由</label>
              <textarea
                className="macro__record-textarea"
                placeholder="写下你的判断依据（可长可短）"
                value={recordForm.summary}
                onChange={(e) => setRecordForm({...recordForm, summary: e.target.value})}
                rows={3}
              />
            </div>
            <div className="macro__record-actions">
              <button className="macro__record-cancel" onClick={() => setShowRecord(false)}>取消</button>
              <button className="macro__record-save" onClick={handleRecord} disabled={recording}>
                {recording ? '保存中…' : '保存'}
              </button>
            </div>
          </div>
        )}
      </section>

      {/* ── 3. 历史验证对照（核心）── */}
```

- [ ] **Step 3: 历史表加"来源"列**

找到历史表头和行（`macro__views-row`），加来源列。

表头找到：
```tsx
            <div className="macro__views-row macro__views-row--head">
              <span>日期</span>
              <span>象限</span>
              <span>立场</span>
              <span>宏观命中</span>
              <span>资产命中</span>
              <span>状态</span>
              <span></span>
            </div>
```
改为（日期后加来源）：
```tsx
            <div className="macro__views-row macro__views-row--head">
              <span>日期</span>
              <span>来源</span>
              <span>象限</span>
              <span>立场</span>
              <span>宏观命中</span>
              <span>资产命中</span>
              <span>状态</span>
              <span></span>
            </div>
```

数据行找到：
```tsx
                <span className="macro__views-date">{v.snapshot_date}</span>
                <span className={STANCE_COLOR[v.regime_quadrant] || 'is-flat'}>
```
改为（日期后加来源）：
```tsx
                <span className="macro__views-date">{v.snapshot_date}</span>
                <span className={`macro__views-author macro__views-author--${v.author}`}>
                  {v.author === 'user' ? '我' : 'AI'}
                </span>
                <span className={STANCE_COLOR[v.regime_quadrant] || 'is-flat'}>
```

同时更新 grid-template-columns（多一列）。在 Macro.css 找到 `.macro__views-row`：

找到：
```css
.macro__views-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1.2fr 1.2fr 1fr 40px;
```
改为：
```css
.macro__views-row {
  display: grid;
  grid-template-columns: 1fr 0.7fr 1fr 1fr 1.2fr 1.2fr 1fr 40px;
```

- [ ] **Step 4: CSS 加记录表单 + 来源徽章样式**

在 `frontend/apps/web/src/pages/Macro.css` 末尾（`@media` 之前），加：

```css
/* 人记录表单 */
.macro__record-section {
  display: flex;
  justify-content: center;
}

.macro__record-btn {
  background: var(--color-surface);
  border: 1px dashed var(--color-border-strong);
  color: var(--color-text-secondary);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-6);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.macro__record-btn:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.macro__record-form {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  padding: var(--space-5);
  width: 100%;
  max-width: 560px;
}

.macro__record-title {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  margin-bottom: var(--space-4);
}

.macro__record-row {
  margin-bottom: var(--space-4);
}

.macro__record-row > label {
  display: block;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
}

.macro__record-stances {
  display: flex;
  gap: var(--space-2);
}

.macro__record-stance {
  flex: 1;
  text-align: center;
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: var(--text-sm);
}

.macro__record-stance input {
  display: none;
}

.macro__record-stance.is-active {
  border-color: var(--color-accent);
  background: var(--color-surface-raised);
  color: var(--color-accent);
}

.macro__record-textarea {
  width: 100%;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  color: var(--color-text);
  font-size: var(--text-sm);
  font-family: inherit;
  resize: vertical;
}

.macro__record-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.macro__record-cancel {
  background: none;
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-4);
  cursor: pointer;
}

.macro__record-save {
  background: var(--color-accent);
  color: #fff;
  border: none;
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-4);
  cursor: pointer;
}

.macro__record-save:disabled {
  opacity: 0.5;
}

/* 来源徽章 */
.macro__views-author {
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  padding: 2px 8px;
  border-radius: 10px;
  text-align: center;
  display: inline-block;
}

.macro__views-author--ai {
  background: var(--color-surface-raised);
  color: var(--color-text-secondary);
}

.macro__views-author--user {
  background: rgba(48, 209, 88, 0.15);
  color: #30d158;
}
```

- [ ] **Step 5: 更新响应式（多一列）**

在 Macro.css 的 `@media (max-width: 768px)` 内找到：
```css
  .macro__views-row {
    grid-template-columns: 1fr 1fr 1fr 40px;
    font-size: var(--text-xs);
  }
  .macro__views-row > span:nth-child(4),
  .macro__views-row > span:nth-child(5),
  .macro__views-row > span:nth-child(6) {
    display: none;
  }
```
改为：
```css
  .macro__views-row {
    grid-template-columns: 1fr 0.7fr 1fr 1fr 40px;
    font-size: var(--text-xs);
  }
  .macro__views-row > span:nth-child(3),
  .macro__views-row > span:nth-child(6),
  .macro__views-row > span:nth-child(7) {
    display: none;
  }
```

- [ ] **Step 6: 验证构建**

Run:
```bash
cd frontend/apps/web && timeout 300 npm run build 2>&1 | tail -3
```
Expected: `built in` 成功。

- [ ] **Step 7: Commit**

```bash
cd frontend && git add apps/web/src/pages/Macro.tsx apps/web/src/pages/Macro.css
git commit -m "feat(macro): human judgment record form + author column in history"
```

---

## Task 12: 端到端验证

- [ ] **Step 1: 后端全链路冒烟**

Run:
```bash
cd backend && timeout 90 .venv/bin/python -c "
import logging; logging.disable(logging.CRITICAL)
import json
# 1. 迁移
from src.infra.database.market.macro_view import ensure_macro_view_columns
from src.infra.database.agent.repository import migrate_macro_prompts_v2
ensure_macro_view_columns()
migrate_macro_prompts_v2()
# 2. 人记录 API
from src.api.handler.macro_handler import record_view, list_views
r = record_view({'overall_stance':'bullish','confidence':6,'summary':'测试人记录'})
d = json.loads(r.body); assert d['code']==0; vid=d['data']['view_id']
# 3. list_views 含 author
views = json.loads(list_views(limit=5).body)['data']
assert any(v['author']=='user' for v in views), 'no user view in list'
print('user view found, author=user OK')
# 4. prompt v2
from src.infra.database.agent.repository import create_agent_repository
t = create_agent_repository().get_prompt_template_by_name('macro_analyst_system')
assert '【输出·分两段，缺一不可】' in t.template
print('prompt v2 OK')
# cleanup
from src.infra.database.market.macro_view import MacroView, create_macro_view_repository
from src.infra.database.sql_engine.engine import create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn
from sqlmodel import delete
db = create_db_connection(get_dsn())
with db.session_scope() as s:
    s.exec(delete(MacroView).where(MacroView.id == vid))
print('E2E BACKEND OK')
"
```
Expected: `E2E BACKEND OK`。

- [ ] **Step 2: 前端最终构建**

Run:
```bash
cd frontend/apps/web && timeout 300 npm run build 2>&1 | tail -5
```
Expected: `built in` 成功，无 Macro 错误。

- [ ] **Step 3: 最终提交（若有未提交改动）**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader && git status
```
若有未提交改动，提交之；否则跳过。
