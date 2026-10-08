# 自动建组合(课程组合) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把课程23(风险偏好配比红利/蓝筹/创新)与课程24(PE估值带+层层狙击建仓+周检视)做成"自动建组合"功能:输入资金与风险偏好→自动选股分类、生成配比与分批建仓档位→落库跟踪→周检视建议→档位成交回写。

**Architecture:** 纯函数域模块(course_builder/course_review)+ 2张新SQLModel表 + repository + FastAPI router;前端React新页面(向导+详情检视)。复用既有:data_loader取数、valuation_band(μ±1σ四态)、course_allocation.RISK_PROFILES(配比表)、index_constituent(沪深300)、stock_valuation(PE/股息率)、stock_ohlcv收盘价(裸SQL)。

**Tech Stack:** Python 3 / FastAPI / SQLModel / psycopg2(裸SQL)/ pytest;React 18 / TypeScript / rsbuild / vitest。

**Spec:** `docs/superpowers/specs/2026-09-20-course-portfolio-design.md`

## Global Constraints

- 全部新领域逻辑为纯函数,市场数据由调用方注入(项目惯例,便于单测)。
- 派息率(小数) = dv_ttm/100 × pe_ttm;营收增速 = 最新年报营收/上一年报营收 − 1;roe_weighted/dv_ttm 单位为 %。
- 分类规则:红利=派息≥0.30 且 增速<0.10 且 股息率≥3.0%;创新=增速≥0.10 且 派息<0.30 且 ROE≥10.0%;蓝筹=沪深300成分 且 ROE≥10.0%;优先级 红利>创新>蓝筹。
- 配比(defensive/balanced/aggressive/radical)直接用 `course_allocation.RISK_PROFILES`,前端镜像常量,两处不得再写第三份。
- 档位:底仓30% + 23%/23%/24%;合理偏低/超跌按现价回落 0/5/10/15%;合理偏高锚定 μ/μ−0.5σ/μ−1σ/μ−1.5σ;虚高或样本<24个月(月度降采样)不生成档位;金额按100股整手向下取整,不足一手丢档。
- 现金预留 10%;类内等权;stock_count ∈ [5,8] 默认8。
- 后端响应统一 `{"code": 0, "msg": "ok", "data": ...}`(同 screener_router)。
- 前端UI用全站令牌(styles/global.css 的 `--color-*` 变量),A股红涨绿跌口径(涨=success红?——遵循项目现状: 涨用 `--color-danger` 红色系)。注意: 本功能不涉及涨跌色, 徽章语义色: 便宜=success绿/贵=danger红。
- 既有pytest有52个预存失败(见 memory),新测试必须独立全绿;跑子集验证。
- DB为PostgreSQL;stock_ohlcv无SQLModel表,收盘价用 `text()` 裸SQL(照抄 perm repo 写法)。

---

### Task 1: 数据加载扩展——年报营收与标的名称

**Files:**
- Modify: `backend/src/domain/market/strategy/longterm/data_loader.py`(文件末尾追加)
- Test: 无独立单测(SQL薄封装,与既有 fetch_* 同模式),由 Task 5 的假仓储 router 测试间接覆盖

**Interfaces:**
- Produces:
  - `fetch_annual_revenues(symbols: list[str], as_of: Optional[date] = None) -> dict[str, list[dict]]` — `{symbol: [{"report_date": date, "revenue": float}, ...]}` 按报告期降序、每标的最多2条年报
  - `fetch_symbol_names(symbols: list[str]) -> dict[str, str]` — `{symbol: name}`

- [ ] **Step 1: 追加两个取数函数**

在 `data_loader.py` 末尾追加(与既有 `_get_conn`/`RealDictCursor`/`_as_date` 惯例一致,直接使用同文件既有私有工具):

```python
def fetch_annual_revenues(
    symbols: list[str],
    as_of: Optional[date] = None,
    lag_days: int = FINANCIAL_LAG_DAYS,
) -> dict[str, list[dict]]:
    """批量取每个标的最近两份年报营收(12-31报告期, 供营收同比)。

    Returns:
        {symbol: [{"report_date": date, "revenue": float}, ...]} 按报告期降序,
        每标的最多 2 条;无年报的标的不出现。
    """
    if not symbols:
        return {}
    as_of = as_of or date.today()
    cutoff = as_of - __import__("datetime").timedelta(days=lag_days)
    out: dict[str, list[dict]] = {}
    try:
        conn = _get_conn()
    except Exception:
        return out
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT symbol, report_date, revenue FROM (
                    SELECT symbol, report_date, revenue,
                           ROW_NUMBER() OVER (
                               PARTITION BY symbol
                               ORDER BY report_date DESC
                           ) AS rn
                    FROM stock_financial_detail
                    WHERE statement_type = 'income'
                      AND report_date <= %s
                      AND EXTRACT(MONTH FROM report_date) = 12
                      AND revenue IS NOT NULL
                      AND symbol = ANY(%s)
                ) t
                WHERE rn <= 2
                ORDER BY symbol, report_date DESC
                """,
                (cutoff, list(symbols)),
            )
            for r in cur.fetchall():
                out.setdefault(r["symbol"], []).append(
                    {"report_date": _as_date(r["report_date"]),
                     "revenue": r.get("revenue")}
                )
    except Exception as e:
        log.warning(f"fetch_annual_revenues 失败: {e}")
    finally:
        conn.close()
    return out


def fetch_symbol_names(symbols: list[str]) -> dict[str, str]:
    """批量取标的中文名。{symbol: name};查不到的不出现。"""
    if not symbols:
        return {}
    try:
        conn = _get_conn()
    except Exception:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, name FROM stock_info WHERE symbol = ANY(%s)",
                (list(symbols),),
            )
            return {r[0]: r[1] for r in cur.fetchall()}
    except Exception as e:
        log.warning(f"fetch_symbol_names 失败: {e}")
    finally:
        conn.close()
    return {}
```

- [ ] **Step 2: 语法验证**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "from src.domain.market.strategy.longterm.data_loader import fetch_annual_revenues, fetch_symbol_names; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/src/domain/market/strategy/longterm/data_loader.py
git commit -m "feat(course-portfolio): data_loader新增年报营收/标的名称批量取数"
```

---

### Task 2: 课程组合表 + repository

**Files:**
- Create: `backend/src/infra/database/portfolio/course_models.py`
- Create: `backend/src/infra/database/portfolio/course_portfolio_repository.py`
- Test: 由 Task 5 假仓储覆盖 CRUD 语义;本任务以导入+建表冒烟验证

**Interfaces:**
- Produces:
  - `CoursePortfolio` / `CoursePortfolioLeg`(SQLModel,字段见代码)
  - `CoursePortfolioRepository`:`create_plan(portfolio, legs) -> int`、`list_plans() -> list[dict]`、`get_plan(id) -> Optional[dict]`(`{"portfolio", "legs"}`)、`delete_plan(id) -> bool`、`get_leg(portfolio_id, leg_id)`、`save_leg_fill(leg_id, entry_plan, shares_delta, fill_price, fill_value, status=None)`、`set_plan_status(id, status)`、`get_close_price(symbol, on_or_before) -> Optional[float]`
  - `create_course_portfolio_repository() -> CoursePortfolioRepository`

- [ ] **Step 1: 写表定义 `course_models.py`**

```python
"""课程组合(自动建组合)SQLModel 表定义。

2 张表:
- CoursePortfolio:    组合计划(风险偏好/资金/现金预留/状态)
- CoursePortfolioLeg: 计划腿(类别/目标权重/估值带快照JSONB/建仓档位JSONB)

通过 SQLModel.metadata.create_all 自动建表;main.py 启动链路经
course_portfolio_router → repository → 本模块完成注册(参考 models.py 说明)。
"""
import datetime as dt
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field, UniqueConstraint


class CoursePortfolio(SQLModel, table=True):
    """课程组合计划(课程23/24: 风险偏好配比 + 分批建仓)。"""

    __tablename__ = "course_portfolio"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    risk_profile: str                     # defensive|balanced|aggressive|radical
    total_capital: float
    cash_reserve_pct: float = 0.10
    target_stock_count: int = 8
    status: str = "planned"               # planned|building|complete
    notes: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class CoursePortfolioLeg(SQLModel, table=True):
    """课程组合计划腿: 一只标的的目标配比 + 估值带 + 分批建仓档位。"""

    __tablename__ = "course_portfolio_leg"

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="course_portfolio.id", index=True)
    symbol: str = Field(index=True)
    name: str = ""
    category: str                         # dividend|bluechip|growth
    target_weight: float
    target_amount: float
    pe_band: Any = Field(default=None, sa_column=Column(JSON))
    # {mean,std,z_score,state,sample_count,current_pe}
    entry_plan: Any = Field(default=None, sa_column=Column(JSON))
    # [{rung_index,drop_pct,price_level,amount,executed,executed_at,fill_price,fill_shares}]
    shares: int = 0
    invested_amount: float = 0.0
    avg_cost: float = 0.0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "symbol", name="uq_course_leg_port_symbol"
        ),
    )
```

- [ ] **Step 2: 写 `course_portfolio_repository.py`**

```python
"""课程组合 repository: 计划/腿 CRUD + 档位成交回写 + 收盘价查询。

遵循项目 Repository Pattern(参考 portfolio/repository.py):
- 工厂 create_course_portfolio_repository();
- stock_ohlcv 收盘价为裸 SQL 表, 用 text() 查询(同 perm repo)。
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlmodel import select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn

from .course_models import CoursePortfolio, CoursePortfolioLeg


class CoursePortfolioRepository:
    """课程组合计划数据访问。"""

    def __init__(self, db: DBConnection):
        self._db = db

    # ── 计划 CRUD ────────────────────────────────────────────────
    def create_plan(
        self, portfolio: CoursePortfolio, legs: list[CoursePortfolioLeg]
    ) -> int:
        """落库计划+腿, 返回 portfolio.id。"""
        with self._db.session_scope() as s:
            s.add(portfolio)
            s.flush()
            for leg in legs:
                leg.portfolio_id = portfolio.id
                s.add(leg)
            s.flush()
            return portfolio.id

    def list_plans(self) -> list[dict]:
        """全部计划(不含腿), 按 created_at 降序。"""
        with self._db.session_scope() as s:
            rows = list(
                s.exec(
                    select(CoursePortfolio)
                    .order_by(CoursePortfolio.created_at.desc())
                ).all()
            )
            for r in rows:
                s.expunge(r)
            return [
                {
                    "id": p.id,
                    "name": p.name,
                    "risk_profile": p.risk_profile,
                    "total_capital": p.total_capital,
                    "cash_reserve_pct": p.cash_reserve_pct,
                    "target_stock_count": p.target_stock_count,
                    "status": p.status,
                    "notes": p.notes,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in rows
            ]

    def get_plan(self, portfolio_id: int) -> Optional[dict]:
        """计划 + legs(ORM对象);不存在返回 None。"""
        with self._db.session_scope() as s:
            p = s.get(CoursePortfolio, portfolio_id)
            if p is None:
                return None
            legs = list(
                s.exec(
                    select(CoursePortfolioLeg)
                    .where(CoursePortfolioLeg.portfolio_id == portfolio_id)
                    .order_by(CoursePortfolioLeg.category, CoursePortfolioLeg.symbol)
                ).all()
            )
            for l in legs:
                s.expunge(l)
            s.expunge(p)
            return {"portfolio": p, "legs": legs}

    def delete_plan(self, portfolio_id: int) -> bool:
        """删除计划及全部腿。存在并删除返回 True。"""
        with self._db.session_scope() as s:
            p = s.get(CoursePortfolio, portfolio_id)
            if p is None:
                return False
            for l in list(
                s.exec(
                    select(CoursePortfolioLeg).where(
                        CoursePortfolioLeg.portfolio_id == portfolio_id
                    )
                ).all()
            ):
                s.delete(l)
            s.delete(p)
            return True

    # ── 腿与成交回写 ─────────────────────────────────────────────
    def save_leg_fill(
        self,
        leg_id: int,
        entry_plan: list[dict],
        shares_delta: int,
        fill_price: float,
        fill_value: float,
        status: Optional[str] = None,
    ) -> None:
        """回写某腿档位执行: entry_plan JSONB / shares / invested / avg_cost。

        status 非空时同步更新所属计划状态(不改 complete)。
        """
        with self._db.session_scope() as s:
            l = s.get(CoursePortfolioLeg, leg_id)
            if l is None:
                return
            new_shares = (l.shares or 0) + shares_delta
            new_invested = (l.invested_amount or 0.0) + fill_value
            l.entry_plan = entry_plan
            l.shares = new_shares
            l.invested_amount = new_invested
            l.avg_cost = (new_invested / new_shares) if new_shares > 0 else 0.0
            l.updated_at = datetime.now()
            if status:
                p = s.get(CoursePortfolio, l.portfolio_id)
                if p and p.status != "complete":
                    p.status = status
                    p.updated_at = datetime.now()

    def set_plan_status(self, portfolio_id: int, status: str) -> None:
        with self._db.session_scope() as s:
            p = s.get(CoursePortfolio, portfolio_id)
            if p:
                p.status = status
                p.updated_at = datetime.now()

    # ── stock_ohlcv 收盘价(裸 SQL, 同 perm repo) ─────────────────
    def get_close_price(self, symbol: str, on_or_before: date) -> Optional[float]:
        """on_or_before 当天或最近交易日的收盘价;无数据返回 None。"""
        with self._db.session_scope() as s:
            row = s.execute(
                text(
                    "SELECT close_ FROM stock_ohlcv "
                    "WHERE symbol = :symbol AND trade_date <= :d "
                    "ORDER BY trade_date DESC LIMIT 1"
                ),
                {"symbol": symbol, "d": on_or_before},
            ).first()
            return float(row[0]) if row else None


def create_course_portfolio_repository() -> CoursePortfolioRepository:
    return CoursePortfolioRepository(create_db_connection(get_dsn()))
```

- [ ] **Step 3: 导入与建表冒烟**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -c "from src.infra.database.portfolio.course_models import CoursePortfolio, CoursePortfolioLeg; from src.infra.database.portfolio.course_portfolio_repository import create_course_portfolio_repository; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/src/infra/database/portfolio/course_models.py backend/src/infra/database/portfolio/course_portfolio_repository.py
git commit -m "feat(course-portfolio): 课程组合两张SQLModel表+repository(计划/腿/成交回写/收盘价)"
```

---

### Task 3: 域模块 course_builder(分类/配额/档位,纯函数)

**Files:**
- Create: `backend/src/domain/market/portfolio/course_builder.py`
- Test: `backend/tests/domain/test_course_builder.py`(目录不存在则创建,补 `__init__.py` 参照 `backend/tests/` 既有子目录惯例——先 `ls backend/tests` 确认;若无 domain 子目录且其他子目录无 `__init__.py`,则同样不建)

**Interfaces:**
- Consumes: `valuation_band(series, current) -> Optional[dict]`(键 `mean/std/z_score/state`,state为中文四态)
- Produces(供 Task 4/5/6 使用):
  - 常量 `CATEGORIES = ("dividend","bluechip","growth")`、`LOT_SIZE=100`、`STATE_INSUFFICIENT="insufficient"`
  - `CandidateRow` / `ClassifiedStock` / `LadderRungPlan` / `PlanLegDraft` / `CoursePlanDraft` dataclass
  - `derive_revenue_growth(list[float]) -> Optional[float]`(小数)
  - `derive_payout_ratio(dv_ttm_pct, pe_ttm) -> Optional[float]`(小数)
  - `classify_stock(CandidateRow) -> Optional[str]`
  - `classify_candidates(list[CandidateRow]) -> list[ClassifiedStock]`
  - `pick_top_n(classified, category, n) -> list[ClassifiedStock]`
  - `allocate_slots(stock_count, weights) -> dict[str, int]`
  - `select_pools(classified, slots, multiplier=3) -> dict[str, list[ClassifiedStock]]`
  - `round_to_lot_amount(amount, price, lot_size=100) -> float`
  - `plan_pe_band(pe_series, current_pe) -> Optional[dict]`(state 为英文码)
  - `plan_ladder(band, current_price, target_amount, lot_size=100) -> list[LadderRungPlan]`
  - `assemble_plan(...) -> CoursePlanDraft`
  - `LadderRungPlan.to_dict() -> dict`

- [ ] **Step 1: 写失败测试 `backend/tests/domain/test_course_builder.py`**

```python
"""course_builder 纯函数测试: 分类/配额/估值带/档位/装配。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.domain.market.portfolio.course_builder import (
    CandidateRow,
    allocate_slots,
    classify_candidates,
    classify_stock,
    derive_payout_ratio,
    derive_revenue_growth,
    pick_top_n,
    plan_ladder,
    plan_pe_band,
    round_to_lot_amount,
    select_pools,
    assemble_plan,
    LOT_SIZE,
)


# ── 派生指标 ──────────────────────────────────────────────────────
def test_derive_revenue_growth():
    assert derive_revenue_growth([220.0, 200.0]) == 0.10
    assert derive_revenue_growth([200.0]) is None
    assert derive_revenue_growth([100.0, 0.0]) is None


def test_derive_payout_ratio():
    # dv 5% × PE 10 → 派息率 0.5
    assert derive_payout_ratio(5.0, 10.0) == 0.5
    assert derive_payout_ratio(None, 10.0) is None
    assert derive_payout_ratio(5.0, None) is None


# ── 分类 ──────────────────────────────────────────────────────────
def _row(**kw) -> CandidateRow:
    base = dict(symbol="sh600000", dv_ttm=None, pe_ttm=None, total_mv=None,
                roe_pct=None, annual_revenues=[], in_csi300=False)
    base.update(kw)
    return CandidateRow(**base)


def test_classify_dividend():
    # 派息 0.48 ≥0.3, 增速 0.0526 <0.1, 股息率 6 ≥3 → 红利
    row = _row(dv_ttm=6.0, pe_ttm=8.0, annual_revenues=[105.0, 100.0])
    assert classify_stock(row) == "dividend"


def test_classify_growth():
    # 增速 1/3 ≥0.1, 派息 0.2 <0.3, ROE 15 ≥10 → 创新
    row = _row(dv_ttm=0.5, pe_ttm=40.0, annual_revenues=[200.0, 150.0], roe_pct=15.0)
    assert classify_stock(row) == "growth"


def test_classify_bluechip():
    # 沪深300 + ROE 12 → 蓝筹(增长派息都不满足红利/创新)
    row = _row(dv_ttm=2.0, pe_ttm=15.0, annual_revenues=[100.0, 99.0],
               roe_pct=12.0, in_csi300=True)
    assert classify_stock(row) == "bluechip"


def test_classify_dividend_beats_bluechip():
    # 高派息低增长的大盘银行: 同时满足红利与蓝筹 → 红利优先
    row = _row(dv_ttm=6.0, pe_ttm=8.0, annual_revenues=[103.0, 100.0],
               roe_pct=11.0, in_csi300=True)
    assert classify_stock(row) == "dividend"


def test_classify_none_when_insufficient():
    assert classify_stock(_row(dv_ttm=6.0, pe_ttm=8.0)) is None  # 无年报增速
    assert classify_stock(_row(annual_revenues=[200.0, 100.0])) is None  # 无估值


def test_classify_candidates_ranking():
    rows = [
        _row(symbol="A", dv_ttm=6.0, pe_ttm=8.0, annual_revenues=[105.0, 100.0]),
        _row(symbol="B", dv_ttm=8.0, pe_ttm=8.0, annual_revenues=[105.0, 100.0]),
    ]
    out = classify_candidates(rows)
    assert [c.symbol for c in pick_top_n(out, "dividend", 2)] == ["B", "A"]


# ── 配额 ──────────────────────────────────────────────────────────
def test_allocate_slots_balanced_5():
    # 稳健 5:4:1 × 5 → 2/2/1
    assert allocate_slots(5, {"dividend": 0.5, "bluechip": 0.4, "growth": 0.1}) == {
        "dividend": 2, "bluechip": 2, "growth": 1}


def test_allocate_slots_aggressive_8():
    # 积极 3:5:2 × 8 → 2/4/2
    assert allocate_slots(8, {"dividend": 0.3, "bluechip": 0.5, "growth": 0.2}) == {
        "dividend": 2, "bluechip": 4, "growth": 2}


def test_allocate_slots_zero_weight_excluded():
    # 防御 7:3:0 × 6 → 4/2/0
    assert allocate_slots(6, {"dividend": 0.7, "bluechip": 0.3, "growth": 0.0}) == {
        "dividend": 4, "bluechip": 2}


def test_allocate_slots_radical_5_recovers_overshoot():
    # 激进 0:3:7 × 5: min1 会导致 1+4=5 恰好;再验 0:3:7×6 → 2/4
    assert allocate_slots(6, {"dividend": 0.0, "bluechip": 0.3, "growth": 0.7}) == {
        "dividend": 0, "bluechip": 2, "growth": 4}


# ── 整手取整 ──────────────────────────────────────────────────────
def test_round_to_lot_amount():
    assert round_to_lot_amount(15000.0, 10.0) == 15000.0      # 1500股
    assert round_to_lot_amount(15000.0, 7.0) == 14980.0       # 2100股=14700? 7×2140=14980
    assert round_to_lot_amount(50.0, 10.0) == 0.0             # 不足一手


# ── 估值带 ────────────────────────────────────────────────────────
def test_plan_pe_band_low_fair():
    series = [10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0,
              11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0,
              9.0, 10.0, 11.0, 9.0]  # μ=10, σ≈0.868, current 9.5 → z<0
    band = plan_pe_band(series, 9.5)
    assert band["state"] == "low_fair"
    assert band["sample_count"] == 24
    assert abs(band["mean"] - 10.0) < 0.01


def test_plan_pe_band_insufficient():
    assert plan_pe_band([10.0, 11.0], 10.5)["state"] == "insufficient"
    assert plan_pe_band([], None)["state"] == "insufficient"


def test_plan_pe_band_overvalued():
    series = [10.0] * 30
    assert plan_pe_band(series, 20.0)["state"] == "overvalued"


# ── 档位 ──────────────────────────────────────────────────────────
def test_plan_ladder_low_fair_four_rungs():
    band = {"state": "low_fair", "mean": 10.0, "std": 0.87, "z_score": -0.5,
            "sample_count": 30, "current_pe": 9.5}
    rungs = plan_ladder(band, 10.0, 60000.0)
    assert [r.rung_index for r in rungs] == [0, 1, 2, 3]
    assert rungs[0].price_level == 10.0
    assert abs(rungs[1].price_level - 9.5) < 1e-9
    assert abs(rungs[2].price_level - 9.0) < 1e-9
    assert abs(rungs[3].price_level - 8.5) < 1e-9
    assert all(r.amount > 0 for r in rungs)
    assert not any(r.executed for r in rungs)


def test_plan_ladder_high_fair_anchors():
    band = {"state": "high_fair", "mean": 10.0, "std": 1.0, "z_score": 0.5,
            "sample_count": 30, "current_pe": 10.5}
    rungs = plan_ladder(band, 10.5, 60000.0)
    # 锚定 μ/μ-0.5σ/μ-1σ/μ-1.5σ: 10.0/9.5/9.0/8.5 (价格=现价×PE目标/现PE)
    levels = [r.price_level for r in rungs]
    assert abs(levels[0] - 10.5 * 10.0 / 10.5) < 1e-9
    assert levels == sorted(levels, reverse=True)
    assert levels[0] < 10.5  # 首档低于现价(等待回调)


def test_plan_ladder_waiting_states():
    assert plan_ladder({"state": "overvalued"}, 10.0, 60000.0) == []
    assert plan_ladder({"state": "insufficient"}, 10.0, 60000.0) == []
    assert plan_ladder(None, 10.0, 60000.0) == []


# ── 装配 ──────────────────────────────────────────────────────────
def test_assemble_plan_end_to_end():
    rows = [
        _row(symbol="sh600000", dv_ttm=6.0, pe_ttm=8.0,
             annual_revenues=[105.0, 100.0]),                       # 红利
        _row(symbol="sh601288", dv_ttm=7.0, pe_ttm=6.0,
             annual_revenues=[103.0, 100.0]),                       # 红利
        _row(symbol="sh600036", dv_ttm=2.0, pe_ttm=15.0,
             annual_revenues=[100.0, 99.0], roe_pct=12.0, in_csi300=True),  # 蓝筹
        _row(symbol="sz000858", dv_ttm=2.5, pe_ttm=12.0,
             annual_revenues=[100.0, 99.0], roe_pct=13.0, in_csi300=True),  # 蓝筹
        _row(symbol="sh300750", dv_ttm=0.5, pe_ttm=40.0,
             annual_revenues=[200.0, 150.0], roe_pct=15.0),         # 创新
    ]
    classified = classify_candidates(rows)
    weights = {"dividend": 0.5, "bluechip": 0.4, "growth": 0.1}
    slots = allocate_slots(5, weights)
    pools = select_pools(classified, slots, multiplier=3)
    names = {r.symbol: r.symbol for r in rows}
    prices = {r.symbol: 10.0 for r in rows}
    pe_series = {r.symbol: [10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0,
                            9.0, 10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0,
                            11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0, 9.0]
                 for r in rows}
    current_pes = {r.symbol: 9.5 for r in rows}
    draft = assemble_plan(
        pools=pools, slots=slots, weights=weights, total_capital=500000.0,
        cash_reserve_pct=0.10, names=names, prices=prices,
        pe_series=pe_series, current_pes=current_pes,
    )
    cats = {l.category for l in draft.legs}
    assert cats == {"dividend", "bluechip", "growth"}
    assert len(draft.legs) == 5
    for leg in draft.legs:
        assert leg.target_weight > 0
        assert leg.target_amount > 0
        assert leg.pe_band is not None
        assert len(leg.entry_plan) == 4  # low_fair → 4档
    assert abs(sum(l.target_weight for l in draft.legs) - 1.0) < 1e-6
    # investable = 45万;红利类 2 腿各 11.25万
    div_legs = [l for l in draft.legs if l.category == "dividend"]
    assert all(abs(l.target_amount - 112500.0) < 0.01 for l in div_legs)


def test_assemble_plan_empty_category_warns():
    rows = [
        _row(symbol="sh600000", dv_ttm=6.0, pe_ttm=8.0,
             annual_revenues=[105.0, 100.0]),
    ]
    classified = classify_candidates(rows)
    weights = {"dividend": 0.5, "bluechip": 0.4, "growth": 0.1}
    slots = allocate_slots(5, weights)
    pools = select_pools(classified, slots)
    draft = assemble_plan(
        pools=pools, slots=slots, weights=weights, total_capital=500000.0,
        cash_reserve_pct=0.10, names={"sh600000": "sh600000"},
        prices={"sh600000": 10.0}, pe_series={"sh600000": []},
        current_pes={"sh600000": 8.0},
    )
    assert any("候选池为空" in w for w in draft.warnings)
    assert len(draft.legs) == 1
    assert draft.legs[0].entry_plan == []  # 样本不足 → 无档位
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/test_course_builder.py -v`
Expected: FAIL(`ModuleNotFoundError: src.domain.market.portfolio.course_builder`)

- [ ] **Step 3: 写实现 `course_builder.py`**

```python
"""自动建组合(课程23/24)——选股分类 + 配额分配 + 建仓档位规划(纯函数)。

课程口径:
- 23讲: 风险偏好 → 红利/蓝筹/创新三类目标配比(RISK_PROFILES);成长×股东回报
        四象限;类内等权;预留 10% 现金。
- 24讲: PE 均值±1σ 判估值四状态;合理偏低/超跌即建底仓 30% + 层层狙击
        (越跌越买);合理偏高等待回调(锚定 μ/μ-0.5σ/μ-1σ/μ-1.5σ);虚高不建仓;
        金额按 100 股整手取整。

全部纯函数: 市场数据(估值快照/财务/年报营收/指数成分/PE序列/收盘价)由调用方注入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.domain.market.fundamental.valuation_band import valuation_band

# ── 常量 ──────────────────────────────────────────────────────────────
CATEGORY_DIVIDEND = "dividend"
CATEGORY_BLUECHIP = "bluechip"
CATEGORY_GROWTH = "growth"
CATEGORIES = (CATEGORY_DIVIDEND, CATEGORY_BLUECHIP, CATEGORY_GROWTH)

PAYOUT_THRESHOLD = 0.30       # 派息率门槛(小数, 课程23)
GROWTH_THRESHOLD = 0.10       # 年报营收增速门槛(小数, 课程23)
DIVIDEND_YIELD_MIN = 3.0      # 红利股股息率门槛(dv_ttm, %)
ROE_MIN = 10.0                # 蓝筹/创新 ROE 门槛(roe_weighted, %)

LADDER_BASE_RATIO = 0.30
LADDER_REST_RATIOS = (0.23, 0.23, 0.24)   # 与底仓合计 1.00
LOW_FAIR_DROPS = (0.05, 0.10, 0.15)       # 第2/3/4档相对现价回落
HIGH_FAIR_ANCHORS = (0.0, 0.5, 1.0, 1.5)  # 相对 μ 的 σ 下移(首档=μ, 进入合理偏低)

LOT_SIZE = 100
PE_MIN_MONTHLY_SAMPLES = 24

STATE_MAP = {
    "超跌": "oversold",
    "合理偏低": "low_fair",
    "合理偏高": "high_fair",
    "虚高": "overvalued",
}
STATE_INSUFFICIENT = "insufficient"


# ── 数据结构 ──────────────────────────────────────────────────────────
@dataclass
class CandidateRow:
    """分类前单标的输入快照(调用方从 stock_valuation/stock_financials/
    stock_financial_detail/index_constituent 组装)。"""

    symbol: str
    dv_ttm: Optional[float] = None       # 股息率(%)
    pe_ttm: Optional[float] = None
    total_mv: Optional[float] = None     # 总市值(元)
    roe_pct: Optional[float] = None      # 最新 roe_weighted(%)
    annual_revenues: list[float] = field(default_factory=list)  # 年报营收, 降序≤2条
    in_csi300: bool = False


@dataclass
class ClassifiedStock:
    """分类结果 + 类内排序键。"""

    symbol: str
    category: str
    revenue_growth: Optional[float]
    payout_ratio: Optional[float]
    dv_ttm: Optional[float]
    total_mv: Optional[float]
    rank_metric: float


@dataclass
class LadderRungPlan:
    """建仓档位(课程24 层层狙击)。"""

    rung_index: int
    drop_pct: float          # 相对生成日现价的回落(0=首档)
    price_level: float
    amount: float
    executed: bool = False
    executed_at: Optional[str] = None
    fill_price: Optional[float] = None
    fill_shares: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "rung_index": self.rung_index,
            "drop_pct": round(self.drop_pct, 4),
            "price_level": round(self.price_level, 3),
            "amount": round(self.amount, 2),
            "executed": self.executed,
            "executed_at": self.executed_at,
            "fill_price": self.fill_price,
            "fill_shares": self.fill_shares,
        }


@dataclass
class PlanLegDraft:
    """计划腿草稿。"""

    symbol: str
    name: str
    category: str
    target_weight: float
    target_amount: float
    pe_band: Optional[dict]
    entry_plan: list[dict]
    current_price: Optional[float] = None


@dataclass
class CoursePlanDraft:
    """组合计划草稿(不落库)。"""

    risk_profile: str
    total_capital: float
    investable_capital: float
    slots: dict[str, int]
    legs: list[PlanLegDraft]
    warnings: list[str]
    candidates: dict[str, list[dict]]   # 换股备选(未入选部分)


# ── 派生指标 ──────────────────────────────────────────────────────────
def derive_revenue_growth(annual_revenues: list[float]) -> Optional[float]:
    """年报营收同比 = 最新/上一年 − 1(小数)。不足两年或基数≤0 → None。"""
    if annual_revenues is None or len(annual_revenues) < 2:
        return None
    cur, prev = annual_revenues[0], annual_revenues[1]
    if cur is None or not prev or prev <= 0:
        return None
    return cur / prev - 1.0


def derive_payout_ratio(
    dv_ttm_pct: Optional[float], pe_ttm: Optional[float]
) -> Optional[float]:
    """派息率(小数) = 股息率 × PE(D/MV × MV/NP = D/NP)。任一缺失 → None。"""
    if dv_ttm_pct is None or pe_ttm is None or pe_ttm <= 0:
        return None
    return (dv_ttm_pct / 100.0) * pe_ttm


# ── 分类(课程23 四象限落地的三类口径) ─────────────────────────────────
def classify_stock(row: CandidateRow) -> Optional[str]:
    """返回类别(优先级 红利 > 创新 > 蓝筹), 不匹配 → None。

    - 红利: 派息率≥30% 且 增速<10% 且 股息率≥3%(成熟红利象限)
    - 创新: 增速≥10% 且 派息率<30% 且 ROE≥10%(成长再投入看ROE)
    - 蓝筹: 沪深300成分 且 ROE≥10%
    """
    growth = derive_revenue_growth(row.annual_revenues)
    payout = derive_payout_ratio(row.dv_ttm, row.pe_ttm)
    if (payout is not None and payout >= PAYOUT_THRESHOLD
            and growth is not None and growth < GROWTH_THRESHOLD
            and row.dv_ttm is not None and row.dv_ttm >= DIVIDEND_YIELD_MIN):
        return CATEGORY_DIVIDEND
    if (growth is not None and growth >= GROWTH_THRESHOLD
            and (payout is None or payout < PAYOUT_THRESHOLD)
            and row.roe_pct is not None and row.roe_pct >= ROE_MIN):
        return CATEGORY_GROWTH
    if row.in_csi300 and row.roe_pct is not None and row.roe_pct >= ROE_MIN:
        return CATEGORY_BLUECHIP
    return None


def classify_candidates(rows: list[CandidateRow]) -> list[ClassifiedStock]:
    """分类整个候选宇宙, 附带类内排序键;未匹配的丢弃。"""
    out: list[ClassifiedStock] = []
    for r in rows:
        cat = classify_stock(r)
        if cat is None:
            continue
        growth = derive_revenue_growth(r.annual_revenues)
        payout = derive_payout_ratio(r.dv_ttm, r.pe_ttm)
        if cat == CATEGORY_DIVIDEND:
            metric = r.dv_ttm or 0.0
        elif cat == CATEGORY_GROWTH:
            metric = growth or 0.0
        else:
            metric = r.total_mv or 0.0
        out.append(ClassifiedStock(
            symbol=r.symbol, category=cat, revenue_growth=growth,
            payout_ratio=payout, dv_ttm=r.dv_ttm, total_mv=r.total_mv,
            rank_metric=metric,
        ))
    return out


def pick_top_n(
    classified: list[ClassifiedStock], category: str, n: int
) -> list[ClassifiedStock]:
    """某类按 rank_metric 降序取前 n。"""
    pool = [c for c in classified if c.category == category]
    pool.sort(key=lambda c: c.rank_metric, reverse=True)
    return pool[: max(n, 0)]


def select_pools(
    classified: list[ClassifiedStock],
    slots: dict[str, int],
    multiplier: int = 3,
) -> dict[str, list[ClassifiedStock]]:
    """每类取 max(slots,1)×multiplier 只备选池(头部将入选)。"""
    pools: dict[str, list[ClassifiedStock]] = {}
    for cat in CATEGORIES:
        n = max(slots.get(cat, 0), 1) * multiplier
        pools[cat] = pick_top_n(classified, cat, n)
    return pools


# ── 配额分配 ──────────────────────────────────────────────────────────
def allocate_slots(stock_count: int, weights: dict[str, float]) -> dict[str, int]:
    """按类别配比把 stock_count 分成各类腿数。

    最大余数法;配比>0 的类别至少 1 腿;配比为 0 的类别不分配;
    min-1 导致超配时从最大腿回收。weights 须非零维度 ≥1。
    """
    active = {k: w for k, w in (weights or {}).items() if w and w > 0}
    if not active or stock_count <= 0:
        return {}
    total_w = sum(active.values())
    quotas = {k: w / total_w for k, w in active.items()}
    base = {k: max(1, int(quotas[k] * stock_count)) for k in active}
    remaining = stock_count - sum(base.values())
    order = sorted(
        active,
        key=lambda k: quotas[k] * stock_count - base.get(k, 0),
        reverse=True,
    )
    i = 0
    while remaining > 0:
        base[order[i % len(order)]] += 1
        remaining -= 1
        i += 1
    while remaining < 0:
        victim = max(base, key=lambda k: base[k])
        if base[victim] <= 1:
            break
        base[victim] -= 1
        remaining += 1
    return base


# ── 整手取整 ──────────────────────────────────────────────────────────
def round_to_lot_amount(
    amount: float, price: float, lot_size: int = LOT_SIZE
) -> float:
    """金额按价格折算整手(向下取整), 返回实际投入金额;不足一手 → 0。"""
    if price is None or price <= 0 or amount <= 0:
        return 0.0
    lots = int(amount / price // lot_size)
    return lots * lot_size * price


# ── 估值带(课程24 μ±1σ 四态) ─────────────────────────────────────────
def plan_pe_band(
    pe_series: list[float], current_pe: Optional[float]
) -> Optional[dict]:
    """个股 PE 带: μ±1σ 四状态 + 样本量。

    - 样本(月度降采样后) < 24 或 current_pe 缺失 → {state: insufficient};
    - state 映射为英文码: oversold/low_fair/high_fair/overvalued。
    """
    series = [p for p in (pe_series or []) if p and p > 0]
    if current_pe is None or current_pe <= 0 or len(series) < PE_MIN_MONTHLY_SAMPLES:
        return {"state": STATE_INSUFFICIENT, "sample_count": len(series)}
    band = valuation_band(series, current_pe)
    if band is None:
        return {"state": STATE_INSUFFICIENT, "sample_count": len(series),
                "current_pe": current_pe}
    return {
        "mean": band["mean"],
        "std": band["std"],
        "z_score": band["z_score"],
        "state": STATE_MAP.get(band["state"], STATE_INSUFFICIENT),
        "sample_count": len(series),
        "current_pe": current_pe,
    }


# ── 档位规划(课程24 层层狙击) ─────────────────────────────────────────
def plan_ladder(
    band: Optional[dict],
    current_price: float,
    target_amount: float,
    lot_size: int = LOT_SIZE,
) -> list[LadderRungPlan]:
    """按估值状态生成分批建仓档位。

    - low_fair/oversold: 首档30%@现价 + 3档@回落5%/10%/15%;
    - high_fair: 4档锚定 μ/μ-0.5σ/μ-1σ/μ-1.5σ 对应价格
      (盈利不变假设 P_target = P_now × PE_target / PE_now, 等待回调);
    - overvalued/insufficient/None: 不建仓(空档位)。
    金额整手取整, 不足一手丢档。
    """
    if not band or current_price is None or current_price <= 0 or target_amount <= 0:
        return []
    state = band.get("state")
    ratios = (LADDER_BASE_RATIO,) + LADDER_REST_RATIOS
    if state in ("low_fair", "oversold"):
        drops = [0.0] + list(LOW_FAIR_DROPS)
        levels = [current_price * (1 - d) for d in drops]
    elif state == "high_fair":
        mean, std, cur_pe = band.get("mean"), band.get("std"), band.get("current_pe")
        if not mean or std is None or not cur_pe:
            return []
        levels = [current_price * (mean - k * std) / cur_pe
                  for k in HIGH_FAIR_ANCHORS]
        drops = [1 - lv / current_price for lv in levels]
    else:
        return []

    rungs: list[LadderRungPlan] = []
    for i, (lv, r) in enumerate(zip(levels, ratios)):
        amt = round_to_lot_amount(target_amount * r, lv, lot_size)
        if amt <= 0:
            continue
        rungs.append(LadderRungPlan(
            rung_index=i, drop_pct=drops[i], price_level=lv, amount=amt,
        ))
    return rungs


# ── 装配 ──────────────────────────────────────────────────────────────
def assemble_plan(
    *,
    pools: dict[str, list[ClassifiedStock]],
    slots: dict[str, int],
    weights: dict[str, float],
    total_capital: float,
    cash_reserve_pct: float,
    names: dict[str, str],
    prices: dict[str, float],
    pe_series: dict[str, list[float]],
    current_pes: dict[str, Optional[float]],
) -> CoursePlanDraft:
    """由备选池装配组合计划草稿。

    - investable = total_capital × (1 − cash_reserve_pct);
    - 每类取池头部 slots[cat] 只, 类内等权(单腿金额 = 类别权重×investable÷腿数);
    - 候选不足/为空 → warnings 且该类权重留现金;
    - 无收盘价 → 生成观察腿(空档位)并警告。
    """
    investable = total_capital * (1 - cash_reserve_pct)
    warnings: list[str] = []
    legs: list[PlanLegDraft] = []
    candidates: dict[str, list[dict]] = {}

    for cat in CATEGORIES:
        n = slots.get(cat, 0)
        pool = pools.get(cat, [])
        if n == 0:
            candidates[cat] = []
            continue
        if not pool:
            warnings.append(f"类别 {cat} 候选池为空, 对应权重保留为现金")
            candidates[cat] = []
            continue
        if len(pool) < n:
            warnings.append(f"类别 {cat} 候选不足: 需 {n} 只, 仅 {len(pool)} 只")
        per_amount = investable * (weights.get(cat, 0.0)) / n
        for c in pool[:n]:
            price = prices.get(c.symbol)
            band = plan_pe_band(
                pe_series.get(c.symbol, []), current_pes.get(c.symbol)
            )
            rungs = plan_ladder(band, price, per_amount) if price else []
            if price is None:
                warnings.append(f"{c.symbol} 无收盘价, 仅生成观察腿")
            legs.append(PlanLegDraft(
                symbol=c.symbol,
                name=names.get(c.symbol, c.symbol),
                category=cat,
                target_weight=round(weights.get(cat, 0.0) / n, 4),
                target_amount=round(per_amount, 2),
                pe_band=band,
                entry_plan=[r.to_dict() for r in rungs],
                current_price=price,
            ))
        candidates[cat] = [
            {
                "symbol": c.symbol,
                "dv_ttm": c.dv_ttm,
                "total_mv": c.total_mv,
                "revenue_growth": c.revenue_growth,
                "payout_ratio": c.payout_ratio,
            }
            for c in pool[n:]
        ]

    return CoursePlanDraft(
        risk_profile="",
        total_capital=total_capital,
        investable_capital=investable,
        slots=slots,
        legs=legs,
        warnings=warnings,
        candidates=candidates,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/test_course_builder.py -v`
Expected: 全部 PASS。注意 `test_round_to_lot_amount` 手算复核:15000/7=2142.85 → lot 2100 股 → 2100×7=14700;修正断言应为 `14700.0`。写测试时直接用 `14700.0`。

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/portfolio/course_builder.py backend/tests/domain/test_course_builder.py
git commit -m "feat(course-portfolio): course_builder纯函数——三类分类/配额分配/PE估值带/层层狙击档位/计划装配"
```

---

### Task 4: 域模块 course_review(周检视,纯函数)

**Files:**
- Create: `backend/src/domain/market/portfolio/course_review.py`
- Test: `backend/tests/domain/test_course_review.py`

**Interfaces:**
- Consumes: Task 3 的档位 dict 形状 `{rung_index, drop_pct, price_level, amount, executed, ...}`
- Produces:
  - `LegReviewInput` / `LegAdvice` / `PortfolioReview` dataclass
  - `review_leg(inp, total_capital, drift_threshold=0.03) -> LegAdvice`
  - `review_portfolio(legs, total_capital, cash_reserve_pct, drift_threshold=0.03) -> PortfolioReview`

- [ ] **Step 1: 写失败测试 `backend/tests/domain/test_course_review.py`**

```python
"""course_review 纯函数测试: 买入触发/超配减仓/破位/组合聚合。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.domain.market.portfolio.course_review import (
    LegReviewInput,
    review_leg,
    review_portfolio,
)


def _leg(**kw) -> LegReviewInput:
    base = dict(
        symbol="sh600000", name="浦发银行", category="dividend",
        target_weight=0.125,
        entry_plan=[
            {"rung_index": 0, "drop_pct": 0.0, "price_level": 10.0,
             "amount": 18000.0, "executed": True, "fill_price": 10.0,
             "fill_shares": 1800},
            {"rung_index": 1, "drop_pct": 0.05, "price_level": 9.5,
             "amount": 13800.0, "executed": False},
            {"rung_index": 2, "drop_pct": 0.10, "price_level": 9.0,
             "amount": 13800.0, "executed": False},
            {"rung_index": 3, "drop_pct": 0.15, "price_level": 8.5,
             "amount": 14400.0, "executed": False},
        ],
        shares=1800, invested_amount=18000.0,
        current_price=10.0, dv_ttm=6.0, pe_state="low_fair",
    )
    base.update(kw)
    return LegReviewInput(**base)


def test_buy_rung_triggered():
    adv = review_leg(_leg(current_price=9.4), total_capital=500000.0)
    assert adv.code == "BUY_RUNG"
    assert adv.amount == 13800.0
    assert adv.shares == 1500  # 13800/9.4=1468 → 整手 1400? 1468//100*100=1400


def test_buy_rung_not_triggered():
    adv = review_leg(_leg(current_price=9.6), total_capital=500000.0)
    assert adv.code == "HOLD"
    assert "下一档" in adv.message


def test_breakdown_below_lowest_rung():
    adv = review_leg(_leg(current_price=8.4), total_capital=500000.0)
    assert adv.code == "BREAKDOWN"


def test_trim_after_complete_when_overweight():
    plan = [
        {"rung_index": 0, "drop_pct": 0.0, "price_level": 10.0,
         "amount": 60000.0, "executed": True, "fill_price": 10.0,
         "fill_shares": 6000},
    ]
    # 目标 12.5% × 50万 = 6.25万;现价涨到 12 → 市值 7.2万 = 14.4% > 12.5%+3%
    adv = review_leg(
        _leg(entry_plan=plan, shares=6000, current_price=12.0,
             target_weight=0.125),
        total_capital=500000.0,
    )
    assert adv.code == "TRIM"


def test_hold_after_complete_normal_weight():
    plan = [
        {"rung_index": 0, "drop_pct": 0.0, "price_level": 10.0,
         "amount": 60000.0, "executed": True, "fill_price": 10.0,
         "fill_shares": 6000},
    ]
    adv = review_leg(
        _leg(entry_plan=plan, shares=6000, current_price=10.2,
             target_weight=0.125),
        total_capital=500000.0,
    )
    assert adv.code == "HOLD"


def test_hold_when_no_price():
    adv = review_leg(_leg(current_price=None), total_capital=500000.0)
    assert adv.code == "HOLD"
    assert "停牌" in adv.message or "收盘价" in adv.message


def test_review_portfolio_aggregation():
    legs = [
        _leg(symbol="A", category="dividend", target_weight=0.25,
             shares=1800, invested_amount=18000.0, current_price=10.0,
             dv_ttm=6.0),
        _leg(symbol="B", category="bluechip", target_weight=0.20,
             shares=0, invested_amount=0.0, current_price=20.0,
             dv_ttm=2.0, entry_plan=[]),
    ]
    rev = review_portfolio(legs, total_capital=500000.0, cash_reserve_pct=0.10)
    assert rev.progress_invested == 18000.0
    assert rev.cash_remaining == 500000.0 * 0.9 - 18000.0
    assert rev.category_actual["dividend"] == 18000.0
    assert rev.category_actual["bluechip"] == 0.0
    assert rev.dividend_yield_weighted == 6.0  # 仅A有持仓
    codes = [a.code for a in rev.advices]
    assert len(codes) == 2
```

注意 `test_buy_rung_triggered` 手算:13800/9.4 = 1468.08 → `int(1468.08 // 100) × 100 = 1400`。断言写 `1400`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/test_course_review.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 写实现 `course_review.py`**

```python
"""课程组合周检视(课程24第九节量化, 纯函数)。

单腿四态建议(优先级从高到低):
- BREAKDOWN: 现价 < 最低档价格 → 破位, 先复查基本面勿急于补仓
- BUY_RUNG:  现价 ≤ 下一未执行档价格 → 建议按档买入
- TRIM:      实际权重 − 目标权重 > 阈值(上涨被动超配) → 建议减仓至目标
- HOLD:      其他(含距下一档距离/建仓完成权重正常/无档位观察/停牌跳过)

组合层: 建仓进度、现金余额、类别实际市值 vs 目标权重、加权股息率。
当前估值状态与收盘价由调用方注入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

TRIM_WEIGHT_DRIFT = 0.03   # 超配阈值(3pct)


@dataclass
class LegReviewInput:
    """单腿检视输入。"""

    symbol: str
    name: str
    category: str
    target_weight: float
    entry_plan: list[dict]
    shares: int
    invested_amount: float
    current_price: Optional[float]
    dv_ttm: Optional[float]
    pe_state: Optional[str]


@dataclass
class LegAdvice:
    """单腿建议。"""

    symbol: str
    code: str          # BUY_RUNG | TRIM | BREAKDOWN | HOLD
    message: str
    amount: Optional[float] = None
    shares: Optional[int] = None


@dataclass
class PortfolioReview:
    """组合层检视结果。"""

    advices: list[LegAdvice] = field(default_factory=list)
    progress_invested: float = 0.0
    progress_target: float = 0.0
    cash_remaining: float = 0.0
    category_actual: dict[str, float] = field(default_factory=dict)
    category_target: dict[str, float] = field(default_factory=dict)
    dividend_yield_weighted: Optional[float] = None


def review_leg(
    inp: LegReviewInput,
    total_capital: float,
    drift_threshold: float = TRIM_WEIGHT_DRIFT,
) -> LegAdvice:
    """单腿检视(优先级 破位 > 买入触发 > 超配 > 持有)。"""
    plan = inp.entry_plan or []
    price = inp.current_price
    if not plan:
        return LegAdvice(inp.symbol, "HOLD", "该腿无建仓档位(估值数据不足或虚高), 持续观察")
    if price is None or price <= 0:
        return LegAdvice(inp.symbol, "HOLD", "无最新收盘价(可能停牌), 跳过检视")

    lowest = min(r["price_level"] for r in plan)
    if lowest > 0 and price < lowest:
        return LegAdvice(inp.symbol, "BREAKDOWN",
                         "现价跌破最低建仓档: 先复查基本面逻辑是否变化, 勿急于补仓")

    pending = [r for r in plan if not r.get("executed")]
    if pending:
        nxt = min(pending, key=lambda r: r["price_level"])
        if price <= nxt["price_level"]:
            shares = int(nxt["amount"] / price // 100) * 100
            return LegAdvice(inp.symbol, "BUY_RUNG",
                             f"触发第 {nxt['rung_index'] + 1} 档买点"
                             f"(≤{nxt['price_level']:.2f}), 建议买入约 {nxt['amount']:.0f} 元",
                             amount=nxt["amount"], shares=shares)
        # 未触发买入 → 检查中途超配
        pv = inp.shares * price
        actual_w = pv / total_capital if total_capital > 0 else 0.0
        if inp.shares > 0 and actual_w - inp.target_weight > drift_threshold:
            return LegAdvice(inp.symbol, "TRIM",
                             f"被动超配(实际 {actual_w:.1%} vs 目标 "
                             f"{inp.target_weight:.1%}), 建议适度减仓至目标")
        dist = (price / nxt["price_level"] - 1) * 100
        return LegAdvice(inp.symbol, "HOLD",
                         f"距下一档({nxt['price_level']:.2f})还有 {dist:.1f}%")

    # 档位全部执行 → 权重检查
    pv = inp.shares * price
    actual_w = pv / total_capital if total_capital > 0 else 0.0
    if actual_w - inp.target_weight > drift_threshold:
        return LegAdvice(inp.symbol, "TRIM",
                         f"被动超配(实际 {actual_w:.1%} vs 目标 "
                         f"{inp.target_weight:.1%}), 建议适度减仓至目标")
    return LegAdvice(inp.symbol, "HOLD", "建仓完成, 权重正常")


def review_portfolio(
    legs: list[LegReviewInput],
    total_capital: float,
    cash_reserve_pct: float,
    drift_threshold: float = TRIM_WEIGHT_DRIFT,
) -> PortfolioReview:
    """组合层检视: 单腿建议 + 进度/现金/类别结构/加权股息率。"""
    advices = [review_leg(l, total_capital, drift_threshold) for l in legs]
    invested = sum(l.invested_amount or 0.0 for l in legs)
    target_total = 0.0
    cat_actual: dict[str, float] = {}
    cat_target: dict[str, float] = {}
    wsum = 0.0
    wdv = 0.0
    for l in legs:
        target_total += sum((r.get("amount", 0.0) for r in (l.entry_plan or [])), 0.0)
        pv = (l.shares or 0) * l.current_price if l.current_price else 0.0
        cat_actual[l.category] = cat_actual.get(l.category, 0.0) + pv
        cat_target[l.category] = cat_target.get(l.category, 0.0) + l.target_weight
        if l.dv_ttm is not None and pv > 0:
            wsum += pv
            wdv += l.dv_ttm * pv
    investable = total_capital * (1 - cash_reserve_pct)
    return PortfolioReview(
        advices=advices,
        progress_invested=invested,
        progress_target=target_total,
        cash_remaining=investable - invested,
        category_actual=cat_actual,
        category_target=cat_target,
        dividend_yield_weighted=(wdv / wsum) if wsum > 0 else None,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/domain/test_course_review.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/portfolio/course_review.py backend/tests/domain/test_course_review.py
git commit -m "feat(course-portfolio): course_review周检视纯函数——破位/买入触发/超配减仓/组合聚合"
```

---

### Task 5: router + main.py 注册

**Files:**
- Create: `backend/src/api/router/course_portfolio_router.py`
- Modify: `backend/main.py`(import + include_router,约 line 316-339 区域)
- Test: `backend/tests/api/test_course_portfolio_router.py`

**Interfaces:**
- Consumes: Task 1 data_loader 函数、Task 2 repository、Task 3/4 域函数
- Produces: `/api/v1/course-portfolio` 7个端点(见 Step 2)
- 供测试猴补的模块级函数: `_course_repo()`、`_csi300_members()`、`_load_pe_series(symbols)`、以及 router 命名空间内的 `fetch_*` 名字

- [ ] **Step 1: 写失败测试 `backend/tests/api/test_course_portfolio_router.py`**

```python
"""course_portfolio_router 测试: 全链路用假数据源(不触DB)。"""
import sys, os
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import src.api.router.course_portfolio_router as mod
from src.infra.database.portfolio.course_models import (
    CoursePortfolio,
    CoursePortfolioLeg,
)

# 假数据: 3红利/2蓝筹/1创新(足够 稳健5只 2/2/1 配额)
FAKE_VALS = {
    "sh600000": {"trade_date": date(2026, 9, 18), "pe": 8.0, "pe_ttm": 8.0,
                 "pb": 0.6, "ps": None, "ps_ttm": None, "dv_ratio": 6.0,
                 "dv_ttm": 6.0, "total_mv": 2.0e11},
    "sh601288": {"trade_date": date(2026, 9, 18), "pe": 6.0, "pe_ttm": 6.0,
                 "pb": 0.55, "ps": None, "ps_ttm": None, "dv_ratio": 7.0,
                 "dv_ttm": 7.0, "total_mv": 1.5e11},
    "sh601398": {"trade_date": date(2026, 9, 18), "pe": 6.5, "pe_ttm": 6.5,
                 "pb": 0.6, "ps": None, "ps_ttm": None, "dv_ratio": 6.5,
                 "dv_ttm": 6.5, "total_mv": 2.5e11},
    "sh600036": {"trade_date": 0, "pe": 15.0, "pe_ttm": 15.0, "pb": 1.2,
                 "ps": None, "ps_ttm": None, "dv_ratio": 2.0, "dv_ttm": 2.0,
                 "total_mv": 9.0e11},  # trade_date 用 date 对象
    "sz000858": {"trade_date": date(2026, 9, 18), "pe": 12.0, "pe_ttm": 12.0,
                 "pb": 2.0, "ps": None, "ps_ttm": None, "dv_ratio": 2.5,
                 "dv_ttm": 2.5, "total_mv": 5.0e11},
    "sz300750": {"trade_date": date(2026, 9, 18), "pe": 40.0, "pe_ttm": 40.0,
                 "pb": 5.0, "ps": None, "ps_ttm": None, "dv_ratio": 0.5,
                 "dv_ttm": 0.5, "total_mv": 8.0e11},
}
FAKE_VALS["sh600036"]["trade_date"] = date(2026, 9, 18)

FAKE_FINS = {
    "sh600000": {"roe_weighted": 11.0}, "sh601288": {"roe_weighted": 10.5},
    "sh601398": {"roe_weighted": 10.8}, "sh600036": {"roe_weighted": 14.0},
    "sz000858": {"roe_weighted": 25.0}, "sz300750": {"roe_weighted": 22.0},
}

FAKE_REVS = {
    "sh600000": [{"report_date": date(2025, 12, 31), "revenue": 1030.0},
                 {"report_date": date(2024, 12, 31), "revenue": 1000.0}],
    "sh601288": [{"report_date": date(2025, 12, 31), "revenue": 1030.0},
                 {"report_date": date(2024, 12, 31), "revenue": 1000.0}],
    "sh601398": [{"report_date": date(2025, 12, 31), "revenue": 1020.0},
                 {"report_date": date(2024, 12, 31), "revenue": 1000.0}],
    "sh600036": [{"report_date": date(2025, 12, 31), "revenue": 1010.0},
                 {"report_date": date(2024, 12, 31), "revenue": 1000.0}],
    "sz000858": [{"report_date": date(2025, 12, 31), "revenue": 1015.0},
                 {"report_date": date(2024, 12, 31), "revenue": 1000.0}],
    "sz300750": [{"report_date": date(2025, 12, 31), "revenue": 1300.0},
                 {"report_date": date(2024, 12, 31), "revenue": 1000.0}],
}

PE_SERIES = {s: [10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0,
                 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0, 9.0, 10.0, 11.0,
                 9.0, 10.0, 11.0, 9.0] for s in FAKE_VALS}
NAMES = {s: f"名称{s}" for s in FAKE_VALS}
CLOSES = {s: 10.0 for s in FAKE_VALS}


class FakeRepo:
    """内存版 CoursePortfolioRepository。"""

    def __init__(self):
        self.plans: dict[int, CoursePortfolio] = {}
        self.legs: dict[tuple[int, int], CoursePortfolioLeg] = {}
        self._next_pid = 1
        self._next_lid = 1

    def get_close_price(self, symbol, on_or_before):
        return CLOSES.get(symbol)

    def create_plan(self, portfolio, legs):
        pid = self._next_pid
        self._next_pid += 1
        portfolio.id = pid
        self.plans[pid] = portfolio
        for l in legs:
            l.id = self._next_lid
            self._next_lid += 1
            l.portfolio_id = pid
            self.legs[(pid, l.id)] = l
        return pid

    def list_plans(self):
        return [
            {"id": p.id, "name": p.name, "risk_profile": p.risk_profile,
             "total_capital": p.total_capital,
             "cash_reserve_pct": p.cash_reserve_pct,
             "target_stock_count": p.target_stock_count,
             "status": p.status, "notes": p.notes, "created_at": None}
            for p in self.plans.values()
        ]

    def get_plan(self, pid):
        if pid not in self.plans:
            return None
        legs = [l for (p, _), l in self.legs.items() if p == pid]
        return {"portfolio": self.plans[pid], "legs": legs}

    def delete_plan(self, pid):
        if pid not in self.plans:
            return False
        self.plans.pop(pid)
        for k in [k for k in self.legs if k[0] == pid]:
            self.legs.pop(k)
        return True

    def save_leg_fill(self, leg_id, entry_plan, shares_delta, fill_price,
                      fill_value, status=None):
        for (pid, lid), l in self.legs.items():
            if lid == leg_id:
                l.entry_plan = entry_plan
                l.shares = (l.shares or 0) + shares_delta
                l.invested_amount = (l.invested_amount or 0.0) + fill_value
                l.avg_cost = l.invested_amount / l.shares if l.shares else 0.0
                if status:
                    self.plans[pid].status = status
                return

    def set_plan_status(self, pid, status):
        self.plans[pid].status = status


@pytest.fixture
def client(monkeypatch):
    fake = FakeRepo()
    monkeypatch.setattr(mod, "_course_repo", lambda: fake)
    monkeypatch.setattr(mod, "_csi300_members",
                        lambda: ["sh600036", "sz000858", "sh600000"])
    monkeypatch.setattr(mod, "fetch_universe_symbols",
                        lambda *a, **k: list(FAKE_VALS.keys()))
    monkeypatch.setattr(mod, "fetch_latest_valuations",
                        lambda symbols, as_of=None: FAKE_VALS)
    monkeypatch.setattr(mod, "fetch_latest_financials",
                        lambda symbols, as_of=None, lag_days=45: FAKE_FINS)
    monkeypatch.setattr(mod, "fetch_annual_revenues",
                        lambda symbols, as_of=None: FAKE_REVS)
    monkeypatch.setattr(mod, "fetch_symbol_names",
                        lambda symbols: NAMES)
    monkeypatch.setattr(mod, "_load_pe_series",
                        lambda symbols: {s: list(PE_SERIES[s]) for s in symbols})

    app = FastAPI()
    app.include_router(mod.router, prefix="/api/v1")
    with TestClient(app) as c:
        yield c


def _gen_body():
    return {
        "total_capital": 500000.0,
        "risk_profile": "balanced",
        "stock_count": 5,
    }


def test_generate_rejects_unknown_profile(client):
    body = _gen_body()
    body["risk_profile"] = "nope"
    resp = client.post("/api/v1/course-portfolio/generate", json=body)
    assert resp.status_code == 400


def test_generate_returns_grouped_legs(client):
    resp = client.post("/api/v1/course-portfolio/generate", json=_gen_body())
    assert resp.status_code == 200
    data = resp.json()["data"]
    cats = {l["category"] for l in data["legs"]}
    assert cats == {"dividend", "bluechip", "growth"}
    assert data["slots"] == {"dividend": 2, "bluechip": 2, "growth": 1}
    # 红利类按股息率降序: sh601288(7.0) > sh600000(6.0) > sh601398(6.5) → 取7.0/6.5
    div_syms = [l["symbol"] for l in data["legs"] if l["category"] == "dividend"]
    assert set(div_syms) == {"sh601288", "sh601398"}
    # 全部 low_fair(当前PE 9.5 vs μ10σ0.87) → 4档
    for l in data["legs"]:
        assert l["pe_band"]["state"] == "low_fair"
        assert len(l["entry_plan"]) == 4
    assert data["candidates"]["dividend"]  # 有备选
    assert abs(sum(l["target_weight"] for l in data["legs"]) - 1.0) < 1e-6


def test_save_and_get_and_review_and_fill(client):
    # 1. generate
    gen = client.post("/api/v1/course-portfolio/generate",
                      json=_gen_body()).json()["data"]
    legs_in = [{"symbol": l["symbol"], "category": l["category"],
                "target_weight": l["target_weight"],
                "target_amount": l["target_amount"]} for l in gen["legs"]]
    # 2. save
    resp = client.post("/api/v1/course-portfolio", json={
        "name": "稳健测试组合", "total_capital": 500000.0,
        "risk_profile": "balanced", "stock_count": 5, "legs": legs_in,
    })
    assert resp.status_code == 200
    pid = resp.json()["data"]["id"]
    # 3. detail
    detail = client.get(f"/api/v1/course-portfolio/{pid}").json()["data"]
    assert len(detail["legs"]) == 5
    assert detail["status"] == "planned"
    # 4. review(现价10 > 最低档8.5, ≤ 首档10 → 触发第1档买入)
    review = client.get(f"/api/v1/course-portfolio/{pid}/review")
    assert review.status_code == 200
    advices = {a["symbol"]: a for a in review.json()["data"]["advices"]}
    assert any(a["code"] == "BUY_RUNG" for a in advices.values())
    # 5. fill 第一档
    leg0 = next(l for l in detail["legs"] if l["symbol"] == "sh601288")
    fill = client.post(
        f"/api/v1/course-portfolio/{pid}/legs/{leg0['id']}/fills",
        json={"rung_index": 0})
    assert fill.status_code == 200
    assert fill.json()["data"]["fill_shares"] > 0
    detail2 = client.get(f"/api/v1/course-portfolio/{pid}").json()["data"]
    leg0b = next(l for l in detail2["legs"] if l["symbol"] == "sh601288")
    assert leg0b["shares"] > 0
    assert detail2["status"] == "building"
    # 6. list + delete
    assert any(p["id"] == pid for p in
               client.get("/api/v1/course-portfolio").json()["data"])
    assert client.delete(f"/api/v1/course-portfolio/{pid}").status_code == 200
    assert client.get(f"/api/v1/course-portfolio/{pid}").status_code == 404


def test_fill_rejects_double_execution(client):
    gen = client.post("/api/v1/course-portfolio/generate",
                      json=_gen_body()).json()["data"]
    legs_in = [{"symbol": l["symbol"], "category": l["category"],
                "target_weight": l["target_weight"],
                "target_amount": l["target_amount"]} for l in gen["legs"]]
    pid = client.post("/api/v1/course-portfolio", json={
        "name": "x", "total_capital": 500000.0, "risk_profile": "balanced",
        "stock_count": 5, "legs": legs_in,
    }).json()["data"]["id"]
    detail = client.get(f"/api/v1/course-portfolio/{pid}").json()["data"]
    leg0 = detail["legs"][0]
    r1 = client.post(f"/api/v1/course-portfolio/{pid}/legs/{leg0['id']}/fills",
                     json={"rung_index": 0})
    assert r1.status_code == 200
    r2 = client.post(f"/api/v1/course-portfolio/{pid}/legs/{leg0['id']}/fills",
                     json={"rung_index": 0})
    assert r2.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/api/test_course_portfolio_router.py -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 写 `course_portfolio_router.py`**

```python
"""课程组合(自动建组合)router: /api/v1/course-portfolio。

- generate: 市场快照 → course_builder 纯函数生成草稿(不落库);
- save:     服务端重算估值带+档位后落库(前端仅传 symbol/category/配额);
- review:   现算周检视建议(不落库);
- fills:    回写档位成交(整手折算, 状态推进 planned→building→complete)。

供测试猴补的接缝: _course_repo / _csi300_members / _load_pe_series /
fetch_*(router 命名空间内)。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.domain.market.portfolio.course_allocation import risk_profile_weights
from src.domain.market.portfolio.course_builder import (
    CandidateRow,
    PE_MIN_MONTHLY_SAMPLES,
    allocate_slots,
    assemble_plan,
    classify_candidates,
    plan_ladder,
    plan_pe_band,
    select_pools,
)
from src.domain.market.portfolio.course_review import (
    LegReviewInput,
    review_portfolio,
)
from src.domain.market.strategy.longterm.data_loader import (
    fetch_annual_revenues,
    fetch_latest_financials,
    fetch_latest_valuations,
    fetch_symbol_names,
    fetch_universe_symbols,
)
from src.infra.database.market.index_constituent import (
    create_index_constituent_repository,
)
from src.infra.database.market.valuation import (
    create_stock_valuation_repository,
)
from src.infra.database.portfolio.course_models import (
    CoursePortfolio,
    CoursePortfolioLeg,
)
from src.infra.database.portfolio.course_portfolio_repository import (
    create_course_portfolio_repository,
)

router = APIRouter(prefix="/course-portfolio", tags=["course-portfolio"])

PE_HISTORY_YEARS = 5
CASH_RESERVE_PCT = 0.10


# ── 接缝(测试猴补点) ──────────────────────────────────────────────────
def _course_repo():
    return create_course_portfolio_repository()


def _csi300_members() -> list[str]:
    return create_index_constituent_repository().get_members("000300")


def _load_pe_series(symbols: list[str]) -> dict[str, list[float]]:
    """逐标的取近5年 PE_TTM 并降采样为每月末值(供 μ±1σ)。"""
    if not symbols:
        return {}
    repo = create_stock_valuation_repository()
    end = date.today()
    start = end - dt.timedelta(days=int(PE_HISTORY_YEARS * 365.25))
    out: dict[str, list[float]] = {}
    for sym in symbols:
        try:
            rows = repo.get_range(sym, start, end)
        except Exception:
            rows = []
        out[sym] = _monthly_last_pes(rows)
    return out


def _monthly_last_pes(rows: list) -> list[float]:
    """估值日线 ORM 行 → 每月最后一个有效 pe_ttm(升序)。"""
    monthly: dict[tuple, float] = {}
    for r in rows:
        v = getattr(r, "pe_ttm", None)
        td = getattr(r, "trade_date", None)
        if v is None or v <= 0 or td is None:
            continue
        monthly[(td.year, td.month)] = v
    return list(monthly.values())


# ── 请求模型 ──────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    total_capital: float = Field(gt=0)
    risk_profile: str
    stock_count: int = Field(default=8, ge=5, le=8)
    as_of: Optional[str] = None


class LegIn(BaseModel):
    symbol: str
    category: str
    target_weight: float = Field(gt=0, le=1)
    target_amount: float = Field(gt=0)


class SaveRequest(BaseModel):
    name: str = ""
    total_capital: float = Field(gt=0)
    risk_profile: str
    stock_count: int = Field(default=8, ge=5, le=8)
    legs: list[LegIn]


class FillRequest(BaseModel):
    rung_index: int = Field(ge=0)
    fill_price: Optional[float] = None
    fill_shares: Optional[int] = None


# ── 内部组装 ──────────────────────────────────────────────────────────
def _load_universe_rows(
    symbols: list[str], csi300: set, as_of: date
) -> tuple[list[CandidateRow], dict[str, Optional[float]]]:
    """universe → 分类输入快照;同时返回 {symbol: 当前pe_ttm}。"""
    vals = fetch_latest_valuations(symbols, as_of)
    fins = fetch_latest_financials(symbols, as_of)
    revs = fetch_annual_revenues(symbols, as_of)
    rows: list[CandidateRow] = []
    current_pes: dict[str, Optional[float]] = {}
    for sym in symbols:
        v = vals.get(sym)
        if not v:
            continue
        pe = v.get("pe_ttm")
        current_pes[sym] = pe
        if not pe or pe <= 0:
            continue
        annual = [x["revenue"] for x in revs.get(sym, [])[:2] if x.get("revenue")]
        rows.append(CandidateRow(
            symbol=sym,
            dv_ttm=v.get("dv_ttm"),
            pe_ttm=pe,
            total_mv=v.get("total_mv"),
            roe_pct=(fins.get(sym) or {}).get("roe_weighted"),
            annual_revenues=annual,
            in_csi300=sym in csi300,
        ))
    return rows, current_pes


def _close_prices(repo, symbols: list[str], as_of: date) -> dict[str, float]:
    out = {}
    for s in dict.fromkeys(symbols):
        p = repo.get_close_price(s, as_of)
        if p is not None:
            out[s] = p
    return out


# ── 端点 ──────────────────────────────────────────────────────────────
@router.post("/generate")
def generate_portfolio(req: GenerateRequest):
    weights = risk_profile_weights(req.risk_profile)
    if weights is None:
        raise HTTPException(status_code=400,
                            detail=f"未知风险偏好: {req.risk_profile}")
    as_of = date.fromisoformat(req.as_of) if req.as_of else date.today()
    symbols = fetch_universe_symbols("A", exclude_st=True)
    if not symbols:
        raise HTTPException(status_code=503,
                            detail="标的池不可用(stock_info 为空)")
    rows, current_pes = _load_universe_rows(symbols, set(_csi300_members()), as_of)
    classified = classify_candidates(rows)
    slots = allocate_slots(req.stock_count, weights)
    pools = select_pools(classified, slots)
    pool_syms = sorted({c.symbol for pl in pools.values() for c in pl})
    names = fetch_symbol_names(pool_syms)
    prices = _close_prices(_course_repo(), pool_syms, as_of)
    pe_series = _load_pe_series(pool_syms)
    draft = assemble_plan(
        pools=pools, slots=slots, weights=weights,
        total_capital=req.total_capital, cash_reserve_pct=CASH_RESERVE_PCT,
        names=names, prices=prices, pe_series=pe_series,
        current_pes=current_pes,
    )
    draft.risk_profile = req.risk_profile
    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "risk_profile": req.risk_profile,
            "profile_weights": weights,
            "total_capital": req.total_capital,
            "investable_capital": draft.investable_capital,
            "slots": draft.slots,
            "legs": [asdict(l) for l in draft.legs],
            "warnings": draft.warnings,
            "candidates": draft.candidates,
        },
    }


@router.post("")
def save_portfolio(req: SaveRequest):
    weights = risk_profile_weights(req.risk_profile)
    if weights is None:
        raise HTTPException(status_code=400,
                            detail=f"未知风险偏好: {req.risk_profile}")
    if not req.legs:
        raise HTTPException(status_code=400, detail="legs 为空")
    seen: set[str] = set()
    for l in req.legs:
        if l.category not in ("dividend", "bluechip", "growth"):
            raise HTTPException(status_code=400, detail=f"非法类别: {l.category}")
        if l.symbol in seen:
            raise HTTPException(status_code=400, detail=f"重复标的: {l.symbol}")
        seen.add(l.symbol)

    as_of = date.today()
    repo = _course_repo()
    syms = [l.symbol for l in req.legs]
    vals = fetch_latest_valuations(syms, as_of)
    names = fetch_symbol_names(syms)
    prices = _close_prices(repo, syms, as_of)
    pe_series = _load_pe_series(syms)

    leg_models: list[CoursePortfolioLeg] = []
    for l in req.legs:
        pe = (vals.get(l.symbol) or {}).get("pe_ttm")
        band = plan_pe_band(pe_series.get(l.symbol, []), pe)
        price = prices.get(l.symbol)
        rungs = plan_ladder(band, price, l.target_amount) if price else []
        leg_models.append(CoursePortfolioLeg(
            symbol=l.symbol,
            name=names.get(l.symbol, l.symbol),
            category=l.category,
            target_weight=l.target_weight,
            target_amount=l.target_amount,
            pe_band=band,
            entry_plan=[r.to_dict() for r in rungs],
        ))
    portfolio = CoursePortfolio(
        name=req.name or f"{req.risk_profile}-课程组合",
        risk_profile=req.risk_profile,
        total_capital=req.total_capital,
        cash_reserve_pct=CASH_RESERVE_PCT,
        target_stock_count=req.stock_count,
        status="planned",
    )
    pid = repo.create_plan(portfolio, leg_models)
    return {"code": 0, "msg": "ok", "data": {"id": pid}}


@router.get("")
def list_portfolios():
    return {"code": 0, "msg": "ok", "data": _course_repo().list_plans()}


@router.get("/{portfolio_id}")
def get_portfolio(portfolio_id: int):
    plan = _course_repo().get_plan(portfolio_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="组合不存在")
    p, legs = plan["portfolio"], plan["legs"]
    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "id": p.id,
            "name": p.name,
            "risk_profile": p.risk_profile,
            "total_capital": p.total_capital,
            "cash_reserve_pct": p.cash_reserve_pct,
            "target_stock_count": p.target_stock_count,
            "status": p.status,
            "notes": p.notes,
            "legs": [
                {
                    "id": l.id,
                    "symbol": l.symbol,
                    "name": l.name,
                    "category": l.category,
                    "target_weight": l.target_weight,
                    "target_amount": l.target_amount,
                    "pe_band": l.pe_band,
                    "entry_plan": l.entry_plan or [],
                    "shares": l.shares,
                    "invested_amount": l.invested_amount,
                    "avg_cost": l.avg_cost,
                }
                for l in legs
            ],
        },
    }


@router.delete("/{portfolio_id}")
def delete_portfolio(portfolio_id: int):
    if not _course_repo().delete_plan(portfolio_id):
        raise HTTPException(status_code=404, detail="组合不存在")
    return {"code": 0, "msg": "ok", "data": {"deleted": portfolio_id}}


@router.get("/{portfolio_id}/review")
def review(portfolio_id: int):
    repo = _course_repo()
    plan = repo.get_plan(portfolio_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="组合不存在")
    p, legs = plan["portfolio"], plan["legs"]
    as_of = date.today()
    syms = [l.symbol for l in legs]
    vals = fetch_latest_valuations(syms, as_of)
    sv_repo = create_stock_valuation_repository()
    start = as_of - dt.timedelta(days=int(PE_HISTORY_YEARS * 365.25))
    inputs: list[LegReviewInput] = []
    for l in legs:
        price = repo.get_close_price(l.symbol, as_of)
        try:
            series = _monthly_last_pes(sv_repo.get_range(l.symbol, start, as_of))
        except Exception:
            series = []
        band = plan_pe_band(series, (vals.get(l.symbol) or {}).get("pe_ttm"))
        v = vals.get(l.symbol) or {}
        inputs.append(LegReviewInput(
            symbol=l.symbol, name=l.name, category=l.category,
            target_weight=l.target_weight, entry_plan=l.entry_plan or [],
            shares=l.shares, invested_amount=l.invested_amount,
            current_price=price, dv_ttm=v.get("dv_ttm"),
            pe_state=(band or {}).get("state"),
        ))
    rev = review_portfolio(inputs, p.total_capital, p.cash_reserve_pct)
    data = asdict(rev)
    return {"code": 0, "msg": "ok", "data": data}


@router.post("/{portfolio_id}/legs/{leg_id}/fills")
def record_fill(portfolio_id: int, leg_id: int, req: FillRequest):
    repo = _course_repo()
    plan = repo.get_plan(portfolio_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="组合不存在")
    leg = next((l for l in plan["legs"] if l.id == leg_id), None)
    if leg is None:
        raise HTTPException(status_code=404, detail="腿不存在")
    entry = [dict(r) for r in (leg.entry_plan or [])]
    target = next((r for r in entry if r.get("rung_index") == req.rung_index), None)
    if target is None:
        raise HTTPException(status_code=400, detail=f"档位不存在: {req.rung_index}")
    if target.get("executed"):
        raise HTTPException(status_code=400, detail="该档已执行")

    price = req.fill_price or repo.get_close_price(leg.symbol, date.today())
    if not price or price <= 0:
        raise HTTPException(status_code=400,
                            detail="无可用成交价(停牌?), 请手动传入 fill_price")
    shares = req.fill_shares or int(target["amount"] / price // 100) * 100
    if shares <= 0:
        raise HTTPException(status_code=400, detail="金额不足一手, 无法成交")

    target["executed"] = True
    target["executed_at"] = datetime.now().isoformat(timespec="seconds")
    target["fill_price"] = price
    target["fill_shares"] = shares

    def _done(l, entry_override):
        e = entry_override if l.id == leg_id else (l.entry_plan or [])
        return bool(e) and all(r.get("executed") for r in e)

    if all(_done(l, entry) for l in plan["legs"]):
        status = "complete"
    elif plan["portfolio"].status == "planned":
        status = "building"
    else:
        status = None
    repo.save_leg_fill(leg_id, entry, shares, price, shares * price, status)
    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "fill_price": price,
            "fill_shares": shares,
            "status": status or plan["portfolio"].status,
        },
    }
```

注意:测试里的 `FAKE_VALS["sh600036"]` 初始字典把 `trade_date` 写成 `0` 再覆盖为 date——直接在字面量里写 `date(2026, 9, 18)` 即可,不要复刻这个绕弯。

- [ ] **Step 4: main.py 注册**

在 main.py 顶部 router import 区(参照 `from src.api.router.boom_router import ...` 所在行)加:

```python
from src.api.router.course_portfolio_router import router as course_portfolio_router
from src.infra.database.portfolio import course_models  # noqa: F401  # create_all 注册
```

在 `app.include_router(boom_router, prefix="/api/v1")  # /api/v1/boom`(约 line 335)之后加:

```python
    app.include_router(course_portfolio_router, prefix="/api/v1")  # /api/v1/course-portfolio
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/api/test_course_portfolio_router.py tests/domain/test_course_builder.py tests/domain/test_course_review.py -v`
Expected: 全部 PASS。若 `test_generate_returns_grouped_legs` 失败,核对假数据:sh601398 dv 6.5 → 红利排序应为 sh601288(7.0) > sh601398(6.5) > sh600000(6.0),断言选中的是 7.0/6.5 两只。

- [ ] **Step 6: 全链路真机冒烟(有DB时)**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/api/test_course_portfolio_router.py -q && .venv/bin/python -c "from src.main import app; print('app ok')"`
Expected: 测试 PASS;app 导入成功(建表在启动时由 create_all 完成)。若 `src.main` 导入有副作用风险,改为仅确认 router 可导入。

- [ ] **Step 7: Commit**

```bash
git add backend/src/api/router/course_portfolio_router.py backend/main.py backend/tests/api/test_course_portfolio_router.py
git commit -m "feat(course-portfolio): /api/v1/course-portfolio 7端点+假仓储测试+main注册"
```

---

### Task 6: 前端类型与API封装 + vitest

**Files:**
- Create: `frontend/apps/web/src/lib/coursePortfolio.ts`
- Test: `frontend/apps/web/src/lib/coursePortfolio.test.ts`

**Interfaces:**
- Consumes: Task 5 的响应形状(`code/msg/data` 包装)
- Produces: `RISK_PROFILES`、`CATEGORY_LABEL`、`PE_STATE_LABEL`、`PE_STATE_TONE`、类型(`PlanLeg`/`GenerateResponse`/`PlanDetail`/`ReviewResponse`)、`api<T>(path, init?)`

- [ ] **Step 1: 确认 vitest 现状**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web && cat vitest.config.ts && grep -n '"test"' package.json`
Expected: vitest 已配置(replay 引入)。若 `test` script 缺失,按 replay 时的配置补(参照仓库内已有 test script 惯例)。

- [ ] **Step 2: 写失败测试 `coursePortfolio.test.ts`**

```ts
import {describe, expect, it} from 'vitest';
import {
  CATEGORY_LABEL,
  PE_STATE_LABEL,
  RISK_PROFILES,
  categoryOf,
  fmtMoney,
  fmtPct,
} from './coursePortfolio';

describe('coursePortfolio lib', () => {
  it('四档风险配比之和为1且覆盖课程23数值', () => {
    expect(RISK_PROFILES.map(p => p.key)).toEqual(
      ['defensive', 'balanced', 'aggressive', 'radical']);
    for (const p of RISK_PROFILES) {
      const sum = p.weights.dividend + p.weights.bluechip + p.weights.growth;
      expect(Math.abs(sum - 1)).toBeLessThan(1e-9);
    }
    expect(RISK_PROFILES[0].weights).toEqual({dividend: 0.7, bluechip: 0.3, growth: 0.0});
    expect(RISK_PROFILES[3].weights).toEqual({dividend: 0.0, bluechip: 0.3, growth: 0.7});
  });

  it('状态与类别中文标签齐全', () => {
    for (const s of ['oversold', 'low_fair', 'high_fair', 'overvalued', 'insufficient']) {
      expect(PE_STATE_LABEL[s]).toBeTruthy();
    }
    for (const c of ['dividend', 'bluechip', 'growth'] as const) {
      expect(CATEGORY_LABEL[c]).toBeTruthy();
    }
  });

  it('categoryOf 归一化非法类别', () => {
    expect(categoryOf('dividend')).toBe('dividend');
    expect(categoryOf('whatever')).toBe('bluechip');
  });

  it('格式化工具', () => {
    expect(fmtPct(0.125)).toBe('12.5%');
    expect(fmtPct(null)).toBe('—');
    expect(fmtMoney(500000)).toBe('500,000');
    expect(fmtMoney(null)).toBe('—');
  });
});
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web && npx vitest run src/lib/coursePortfolio.test.ts`
Expected: FAIL(模块不存在)

- [ ] **Step 4: 写 `coursePortfolio.ts`**

```ts
/**
 * 自动建组合(课程组合)——类型 + 课程23常量 + API 封装。
 * 配比常量与后端 course_allocation.RISK_PROFILES 镜像, 不得单方面修改。
 */
import {getApiBase} from './api';

export type Category = 'dividend' | 'bluechip' | 'growth';

export interface ProfileWeights {
  dividend: number;
  bluechip: number;
  growth: number;
}

export const RISK_PROFILES: ReadonlyArray<{
  key: 'defensive' | 'balanced' | 'aggressive' | 'radical';
  label: string;
  desc: string;
  weights: ProfileWeights;
}> = [
  {key: 'defensive', label: '防御型', desc: '资产保值为主, 跑赢通胀即可',
   weights: {dividend: 0.7, bluechip: 0.3, growth: 0.0}},
  {key: 'balanced', label: '稳健型', desc: '本金相对安全下取市场平均回报',
   weights: {dividend: 0.5, bluechip: 0.4, growth: 0.1}},
  {key: 'aggressive', label: '积极型', desc: '高于市场平均, 能容忍短期波动',
   weights: {dividend: 0.3, bluechip: 0.5, growth: 0.2}},
  {key: 'radical', label: '激进型', desc: '追求数倍回报, 可接受大幅回撤',
   weights: {dividend: 0.0, bluechip: 0.3, growth: 0.7}},
];

export const CATEGORY_LABEL: Record<Category, string> = {
  dividend: '红利股',
  bluechip: '蓝筹股',
  growth: '创新类',
};

export const PE_STATE_LABEL: Record<string, string> = {
  oversold: '超跌',
  low_fair: '合理偏低',
  high_fair: '合理偏高',
  overvalued: '虚高',
  insufficient: '数据不足',
};

export const PE_STATE_TONE: Record<string, string> = {
  oversold: 'success',
  low_fair: 'accent',
  high_fair: 'warning',
  overvalued: 'danger',
  insufficient: 'muted',
};

export interface LadderRung {
  rung_index: number;
  drop_pct: number;
  price_level: number;
  amount: number;
  executed: boolean;
  executed_at?: string | null;
  fill_price?: number | null;
  fill_shares?: number | null;
}

export interface PeBand {
  mean?: number;
  std?: number;
  z_score?: number;
  state: string;
  sample_count: number;
  current_pe?: number;
}

export interface PlanLeg {
  symbol: string;
  name: string;
  category: Category;
  target_weight: number;
  target_amount: number;
  pe_band: PeBand | null;
  entry_plan: LadderRung[];
  current_price?: number | null;
}

export interface Candidate {
  symbol: string;
  dv_ttm?: number | null;
  total_mv?: number | null;
  revenue_growth?: number | null;
  payout_ratio?: number | null;
}

export interface GenerateResponse {
  risk_profile: string;
  profile_weights: ProfileWeights;
  total_capital: number;
  investable_capital: number;
  slots: Record<string, number>;
  legs: PlanLeg[];
  warnings: string[];
  candidates: Record<Category, Candidate[]>;
}

export interface PlanSummary {
  id: number;
  name: string;
  risk_profile: string;
  total_capital: number;
  cash_reserve_pct: number;
  target_stock_count: number;
  status: string;
  notes: string;
  created_at?: string | null;
}

export interface DetailLeg extends PlanLeg {
  id: number;
  shares: number;
  invested_amount: number;
  avg_cost: number;
}

export interface PlanDetail extends PlanSummary {
  legs: DetailLeg[];
}

export interface Advice {
  symbol: string;
  code: 'BUY_RUNG' | 'TRIM' | 'BREAKDOWN' | 'HOLD';
  message: string;
  amount?: number | null;
  shares?: number | null;
}

export interface ReviewResponse {
  advices: Advice[];
  progress_invested: number;
  progress_target: number;
  cash_remaining: number;
  category_actual: Record<string, number>;
  category_target: Record<string, number>;
  dividend_yield_weighted?: number | null;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${getApiBase()}/course-portfolio${path}`, {
    headers: {'Content-Type': 'application/json'},
    ...init,
  });
  const body = await resp.json();
  if (!resp.ok || body.code !== 0) {
    throw new Error(body.msg || body.detail || `HTTP ${resp.status}`);
  }
  return body.data as T;
}

export function categoryOf(c: string): Category {
  return c === 'dividend' || c === 'bluechip' || c === 'growth'
    ? c : 'bluechip';
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  return v == null ? '—' : `${(v * 100).toFixed(digits)}%`;
}

export function fmtMoney(v: number | null | undefined): string {
  return v == null ? '—' : v.toLocaleString('zh-CN', {maximumFractionDigits: 0});
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web && npx vitest run src/lib/coursePortfolio.test.ts`
Expected: 4个测试 PASS

- [ ] **Step 6: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add frontend/apps/web/src/lib/coursePortfolio.ts frontend/apps/web/src/lib/coursePortfolio.test.ts
git commit -m "feat(course-portfolio): 前端lib——课程23配比常量镜像/类型/检视API封装+vitest"
```

---

### Task 7: 前端页面 + 路由 + 菜单

**Files:**
- Create: `frontend/apps/web/src/pages/CoursePortfolio.tsx`
- Create: `frontend/apps/web/src/pages/CoursePortfolio.css`
- Modify: `frontend/apps/web/src/App.tsx`(路由)
- Modify: `frontend/apps/web/src/components/Layout.tsx`(菜单,约 line 44-52 研究组)

**Interfaces:**
- Consumes: Task 6 lib 全部导出;Task 5 的 7 个端点

- [ ] **Step 1: 写 `CoursePortfolio.tsx`**

```tsx
/**
 * 自动建组合(课程组合): 风险偏好配比 → 生成预览 → 落库 → 周检视闭环。
 * 课程23: 红利/蓝筹/创新三类配比; 课程24: PE估值带档位+层层狙击+周检视。
 */
import {useCallback, useEffect, useState} from 'react';
import './CoursePortfolio.css';
import {
  api,
  CATEGORY_LABEL,
  categoryOf,
  fmtMoney,
  fmtPct,
  PE_STATE_LABEL,
  PE_STATE_TONE,
  RISK_PROFILES,
  type Category,
  type DetailLeg,
  type GenerateResponse,
  type PlanDetail,
  type ReviewResponse,
  type RiskProfile,
} from '../lib/coursePortfolio';

type View = 'list' | 'wizard' | 'detail';

const STATUS_LABEL: Record<string, string> = {
  planned: '待建仓', building: '建仓中', complete: '已建成',
};

export default function CoursePortfolio() {
  const [view, setView] = useState<View>('list');
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [detail, setDetail] = useState<PlanDetail | null>(null);
  const [review, setReview] = useState<ReviewResponse | null>(null);
  const [error, setError] = useState('');

  const loadPlans = useCallback(async () => {
    try {
      setPlans(await api<PlanSummary[]>(''));
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    if (view === 'list') {
      loadPlans();
    }
  }, [view, loadPlans]);

  const openDetail = useCallback(async (id: number) => {
    try {
      setError('');
      const [d, r] = await Promise.all([
        api<PlanDetail>(`/${id}`),
        api<ReviewResponse>(`/${id}/review`),
      ]);
      setDetail(d);
      setReview(r);
      setView('detail');
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const refreshDetail = useCallback(async (id: number) => {
    const [d, r] = await Promise.all([
      api<PlanDetail>(`/${id}`),
      api<ReviewResponse>(`/${id}/review`),
    ]);
    setDetail(d);
    setReview(r);
  }, []);

  return (
    <div className="page course-portfolio">
      <div className="page-header">
        <h1>自动建组合</h1>
        <p className="page-subtitle">
          风险偏好配比(课程23)× PE估值带分批建仓(课程24):红利/蓝筹/创新,预留10%现金,层层狙击,周检视
        </p>
        <div className="cp-actions">
          {view === 'list' && (
            <button className="btn-primary" onClick={() => setView('wizard')}>
              + 新建组合
            </button>
          )}
          {view !== 'list' && (
            <button className="btn-ghost" onClick={() => setView('list')}>
              ← 返回列表
            </button>
          )}
        </div>
      </div>
      {error && <div className="cp-error">{error}</div>}
      {view === 'list' && (
        <PlanList plans={plans} onOpen={openDetail} onDeleted={loadPlans} />
      )}
      {view === 'wizard' && (
        <Wizard
          onSaved={async (id) => {
            setView('list');
            await openDetail(id);
          }}
        />
      )}
      {view === 'detail' && detail && (
        <PlanDetailView
          detail={detail}
          review={review}
          onChanged={() => refreshDetail(detail.id)}
        />
      )}
    </div>
  );
}

function PlanList(props: {
  plans: PlanSummary[];
  onOpen: (id: number) => void;
  onDeleted: () => void;
}) {
  const {plans, onOpen, onDeleted} = props;
  const del = async (id: number) => {
    if (!window.confirm('确认删除该组合计划?')) {
      return;
    }
    await api(`/${id}`, {method: 'DELETE'});
    onDeleted();
  };
  if (!plans.length) {
    return <div className="cp-empty">还没有组合计划,点右上角"新建组合"开始。</div>;
  }
  return (
    <table className="cp-table">
      <thead>
        <tr>
          <th>名称</th><th>风险偏好</th><th>资金</th><th>股票数</th>
          <th>状态</th><th>创建时间</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        {plans.map((p) => (
          <tr key={p.id}>
            <td><a onClick={() => onOpen(p.id)} className="cp-link">{p.name}</a></td>
            <td>{RISK_PROFILES.find((r) => r.key === p.risk_profile)?.label ?? p.risk_profile}</td>
            <td>{fmtMoney(p.total_capital)}</td>
            <td>{p.target_stock_count}</td>
            <td><span className={`cp-badge cp-badge--${p.status}`}>{STATUS_LABEL[p.status] ?? p.status}</span></td>
            <td>{p.created_at?.slice(0, 10) ?? '—'}</td>
            <td>
              <button className="btn-ghost btn-sm" onClick={() => del(p.id)}>删除</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Wizard(props: {onSaved: (id: number) => void}) {
  const {onSaved} = props;
  const [step, setStep] = useState<1 | 2>(1);
  const [profile, setProfile] = useState<RiskProfile['key']>('balanced');
  const [capital, setCapital] = useState(500000);
  const [stockCount, setStockCount] = useState(8);
  const [gen, setGen] = useState<GenerateResponse | null>(null);
  const [legs, setLegs] = useState<PlanLeg[]>([]);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const generate = async () => {
    setBusy(true);
    setError('');
    try {
      const data = await api<GenerateResponse>('/generate', {
        method: 'POST',
        body: JSON.stringify({
          total_capital: capital,
          risk_profile: profile,
          stock_count: stockCount,
        }),
      });
      setGen(data);
      setLegs(data.legs);
      setStep(2);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const swapLeg = (cat: Category, symbol: string, idx: number) => {
    const cand = gen?.candidates?.[cat]?.find((c) => c.symbol === symbol);
    if (!cand) {
      return;
    }
    setLegs((prev) => prev.map((l, i) => (
      i === idx ? {
        ...l,
        symbol: cand.symbol,
        name: cand.symbol,
        pe_band: null,
        entry_plan: [],
      } : l
    )));
  };

  const save = async () => {
    setBusy(true);
    setError('');
    try {
      const {id} = await api<{id: number}>('', {
        method: 'POST',
        body: JSON.stringify({
          name: name || undefined,
          total_capital: capital,
          risk_profile: profile,
          stock_count: stockCount,
          legs: legs.map((l) => ({
            symbol: l.symbol,
            category: l.category,
            target_weight: l.target_weight,
            target_amount: l.target_amount,
          })),
        }),
      });
      onSaved(id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  if (step === 1) {
    return (
      <div className="cp-wizard">
        <h2>第一步 · 风险偏好与资金</h2>
        <div className="cp-profiles">
          {RISK_PROFILES.map((p) => (
            <button
              key={p.key}
              className={`cp-profile-card${profile === p.key ? ' is-active' : ''}`}
              onClick={() => setProfile(p.key)}
            >
              <div className="cp-profile-name">{p.label}</div>
              <div className="cp-profile-desc">{p.desc}</div>
              <div className="cp-profile-weights">
                红{Math.round(p.weights.dividend * 100)}% ·
                蓝{Math.round(p.weights.bluechip * 100)}% ·
                创{Math.round(p.weights.growth * 100)}%
              </div>
            </button>
          ))}
        </div>
        <div className="cp-form-row">
          <label>总资金(元)
            <input type="number" value={capital} min={10000} step={10000}
              onChange={(e) => setCapital(Number(e.target.value))} />
          </label>
          <label>股票数量(5–8, 课程24建议8)
            <input type="number" value={stockCount} min={5} max={8}
              onChange={(e) => setStockCount(Number(e.target.value))} />
          </label>
          <label>组合名称(可选)
            <input type="text" value={name} placeholder="留空自动命名"
              onChange={(e) => setName(e.target.value)} />
          </label>
        </div>
        {error && <div className="cp-error">{error}</div>}
        <button className="btn-primary" disabled={busy} onClick={generate}>
          {busy ? '生成中…' : '生成组合预览'}
        </button>
      </div>
    );
  }

  const cats: Category[] = ['dividend', 'bluechip', 'growth'];
  return (
    <div className="cp-wizard">
      <h2>第二步 · 预览并保存</h2>
      {gen && (
        <div className="cp-summary">
          可投资金 {fmtMoney(gen.investable_capital)}(预留10%现金)
          · 配额 {cats.map((c) => `${CATEGORY_LABEL[c]}${gen.slots[c] ?? 0}`).join(' / ')}
        </div>
      )}
      {gen?.warnings.map((w, i) => (
        <div key={i} className="cp-warning">{w}</div>
      ))}
      {cats.map((cat) => {
        const group = legs.filter((l) => l.category === cat);
        if (!group.length) {
          return null;
        }
        return (
          <section key={cat} className="cp-cat">
            <h3>{CATEGORY_LABEL[cat]}</h3>
            <table className="cp-table">
              <thead>
                <tr>
                  <th>标的</th><th>目标权重</th><th>目标金额</th>
                  <th>估值状态</th><th>建仓档位</th><th>换股</th>
                </tr>
              </thead>
              <tbody>
                {group.map((l) => {
                  const idx = legs.indexOf(l);
                  return (
                    <tr key={l.symbol}>
                      <td>{l.name}({l.symbol})</td>
                      <td>{fmtPct(l.target_weight)}</td>
                      <td>{fmtMoney(l.target_amount)}</td>
                      <td>
                        {l.pe_band && (
                          <span className={`cp-badge cp-tone--${PE_STATE_TONE[l.pe_band.state] ?? 'muted'}`}>
                            {PE_STATE_LABEL[l.pe_band.state] ?? l.pe_band.state}
                          </span>
                        )}
                      </td>
                      <td>
                        <RungsCell rungs={l.entry_plan} />
                      </td>
                      <td>
                        <select
                          value=""
                          onChange={(e) => swapLeg(cat, e.target.value, idx)}
                        >
                          <option value="">换成…</option>
                          {(gen?.candidates?.[cat] ?? []).map((c) => (
                            <option key={c.symbol} value={c.symbol}>
                              {c.symbol} 股息{c.dv_ttm?.toFixed(1) ?? '—'}%
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        );
      })}
      {error && <div className="cp-error">{error}</div>}
      <div className="cp-actions">
        <button className="btn-ghost" onClick={() => setStep(1)}>← 上一步</button>
        <button className="btn-primary" disabled={busy || !legs.length} onClick={save}>
          {busy ? '保存中…' : '确认落库'}
        </button>
      </div>
    </div>
  );
}

function RungsCell(props: {rungs: {rung_index: number; price_level: number; amount: number; executed?: boolean}[]}) {
  const {rungs} = props;
  if (!rungs?.length) {
    return <span className="cp-muted">无档位(等待/数据不足)</span>;
  }
  return (
    <span className="cp-rungs">
      {rungs.map((r) => (
        <span key={r.rung_index} className={`cp-rung${r.executed ? ' is-done' : ''}`}>
          {r.rung_index === 0 ? '底' : `+${r.rung_index}`}
          @{r.price_level.toFixed(2)}
        </span>
      ))}
    </span>
  );
}

function PlanDetailView(props: {
  detail: PlanDetail;
  review: ReviewResponse | null;
  onChanged: () => void;
}) {
  const {detail, review, onChanged} = props;
  const [filling, setFilling] = useState<{leg: DetailLeg; rungIndex: number} | null>(null);
  const [error, setError] = useState('');

  const doFill = async (price?: number) => {
    if (!filling) {
      return;
    }
    setBusy(true);
    try {
      await api(`/${detail.id}/legs/${filling.leg.id}/fills`, {
        method: 'POST',
        body: JSON.stringify({rung_index: filling.rungIndex, fill_price: price}),
      });
      setFilling(null);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const adviceBySymbol = new Map((review?.advices ?? []).map((a) => [a.symbol, a]));

  return (
    <div className="cp-detail">
      <div className="cp-summary">
        {detail.name} · {STATUS_LABEL[detail.status] ?? detail.status}
        · 总资金 {fmtMoney(detail.total_capital)}
        · 已投入 {fmtMoney(review?.progress_invested)}
        / 目标 {fmtMoney(review?.progress_target)}
        · 可用现金 {fmtMoney(review?.cash_remaining)}
        {review?.dividend_yield_weighted != null &&
          ` · 组合股息率 ${review.dividend_yield_weighted.toFixed(2)}%`}
      </div>
      {error && <div className="cp-error">{error}</div>}
      {review?.advices.filter((a) => a.code !== 'HOLD').length ? (
        <div className="cp-advices">
          {review!.advices.filter((a) => a.code !== 'HOLD').map((a) => (
            <div key={a.symbol} className={`cp-advice cp-advice--${a.code}`}>
              <b>{a.symbol}</b> {a.message}
            </div>
          ))}
        </div>
      ) : (
        <div className="cp-empty">本周无触发项, 按兵不动(课程24: 拒绝盘中临时起意)。</div>
      )}
      <table className="cp-table">
        <thead>
          <tr>
            <th>标的</th><th>类别</th><th>权重</th><th>进度</th>
            <th>成本/现值</th><th>档位</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          {detail.legs.map((l) => {
            const done = l.entry_plan.filter((r) => r.executed).length;
            const total = l.entry_plan.length;
            const advice = adviceBySymbol.get(l.symbol);
            return (
              <tr key={l.id}>
                <td>{l.name}({l.symbol})</td>
                <td>{CATEGORY_LABEL[categoryOf(l.category)]}</td>
                <td>{fmtPct(l.target_weight)}</td>
                <td>{total ? `${done}/${total}档` : '观察'}</td>
                <td>
                  {l.shares > 0
                    ? `${l.avg_cost.toFixed(2)} / 市值${fmtMoney(l.shares * (advice ? 0 : 0) || l.invested_amount)}`
                    : '—'}
                </td>
                <td><RungsCell rungs={l.entry_plan} /></td>
                <td>
                  {l.entry_plan.filter((r) => !r.executed).map((r) => (
                    <button key={r.rung_index} className="btn-ghost btn-sm"
                      onClick={() => setFilling({leg: l, rungIndex: r.rung_index})}>
                      标记买{r.rung_index === 0 ? '底仓' : `第${r.rung_index + 1}档`}
                    </button>
                  ))}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {filling && (
        <div className="cp-modal-mask" onClick={() => setFilling(null)}>
          <div className="cp-modal" onClick={(e) => e.stopPropagation()}>
            <h3>标记成交</h3>
            <p>
              {filling.leg.symbol} 第{filling.rungIndex + 1}档
              · 计划金额 {fmtMoney(filling.leg.entry_plan[filling.rungIndex]?.amount)}
            </p>
            <p className="cp-muted">不填价格将按最新收盘价折算整手股数。</p>
            <FillForm onSubmit={doFill} busy={false} onCancel={() => setFilling(null)} />
          </div>
        </div>
      )}
    </div>
  );
}

function FillForm(props: {onSubmit: (price?: number) => void; busy: boolean; onCancel: () => void}) {
  const [price, setPrice] = useState('');
  return (
    <div className="cp-form-row">
      <label>成交价(可选)
        <input type="number" step={0.01} min={0} value={price}
          onChange={(e) => setPrice(e.target.value)} />
      </label>
      <button className="btn-primary" disabled={props.busy}
        onClick={() => props.onSubmit(price ? Number(price) : undefined)}>
        确认
      </button>
      <button className="btn-ghost" onClick={props.onCancel}>取消</button>
    </div>
  );
}
```

注意两处需修正:
1. `RiskProfile` 类型:lib 中 RISK_PROFILES 元素类型未导出,在 `coursePortfolio.ts` 里加 `export type RiskProfile = (typeof RISK_PROFILES)[number];`,页面 import 它。
2. `PlanSummary` 类型要从 lib 导入(页面顶部 import 列表补上)。
3. `PlanDetailView` 成本/现值列的 `l.shares * (advice ? 0 : 0)` 是无意义表达式,直接写 `fmtMoney(l.invested_amount)`,列名改为"成本/已投入":`${l.avg_cost.toFixed(2)} / ${fmtMoney(l.invested_amount)}`。
4. `setBusy` 在 `PlanDetailView` 里未定义:加 `const [busy, setBusy] = useState(false);`。

- [ ] **Step 2: 写 `CoursePortfolio.css`**

```css
/* 自动建组合页 —— 全站令牌体系 */
.course-portfolio .page-header {display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px;}
.cp-actions {display: flex; gap: 8px; margin-left: auto;}
.cp-error {color: var(--color-danger); background: var(--color-danger-light); padding: 8px 12px; border-radius: 8px; margin: 8px 0;}
.cp-warning {color: var(--color-orange); background: var(--color-orange-light); padding: 6px 10px; border-radius: 8px; margin: 4px 0; font-size: 13px;}
.cp-empty {color: var(--color-text-tertiary); padding: 32px 0; text-align: center;}
.cp-muted {color: var(--color-text-tertiary);}
.cp-link {color: var(--color-accent); cursor: pointer;}
.btn-primary {background: var(--color-accent); color: #fff; border: none; border-radius: 8px; padding: 8px 16px; cursor: pointer;}
.btn-primary:disabled {opacity: 0.5; cursor: default;}
.btn-ghost {background: var(--color-fill); color: var(--color-text); border: 1px solid var(--color-border); border-radius: 8px; padding: 6px 12px; cursor: pointer;}
.btn-sm {padding: 2px 8px; font-size: 12px;}
.cp-table {width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px;}
.cp-table th, .cp-table td {text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--color-border);}
.cp-table th {color: var(--color-text-secondary); font-weight: 500;}
.cp-badge {display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 12px;}
.cp-badge--planned {background: var(--color-accent-light); color: var(--color-accent);}
.cp-badge--building {background: var(--color-warning-light); color: var(--color-orange);}
.cp-badge--complete {background: var(--color-success-light); color: var(--color-success);}
.cp-tone--success {background: var(--color-success-light); color: var(--color-success);}
.cp-tone--accent {background: var(--color-accent-light); color: var(--color-accent);}
.cp-tone--warning {background: var(--color-warning-light); color: var(--color-orange);}
.cp-tone--danger {background: var(--color-danger-light); color: var(--color-danger);}
.cp-tone--muted {background: var(--color-fill); color: var(--color-text-tertiary);}
.cp-wizard h2 {font-size: 16px; margin: 16px 0 8px;}
.cp-profiles {display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 12px 0;}
.cp-profile-card {text-align: left; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 12px; padding: 14px; cursor: pointer; color: var(--color-text);}
.cp-profile-card.is-active {border-color: var(--color-accent); background: var(--color-accent-light);}
.cp-profile-name {font-weight: 600; margin-bottom: 4px;}
.cp-profile-desc {font-size: 12px; color: var(--color-text-secondary); margin-bottom: 8px;}
.cp-profile-weights {font-size: 13px; color: var(--color-accent);}
.cp-form-row {display: flex; flex-wrap: wrap; gap: 16px; margin: 12px 0; align-items: end;}
.cp-form-row label {display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--color-text-secondary);}
.cp-form-row input, .cp-form-row select {background: var(--color-fill); border: 1px solid var(--color-border); color: var(--color-text); border-radius: 8px; padding: 6px 10px;}
.cp-summary {background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 10px; padding: 10px 14px; font-size: 13px; margin: 8px 0;}
.cp-cat h3 {font-size: 14px; margin: 14px 0 4px;}
.cp-rungs {display: flex; flex-wrap: wrap; gap: 4px;}
.cp-rung {background: var(--color-fill); border-radius: 6px; padding: 1px 6px; font-size: 12px; font-family: monospace;}
.cp-rung.is-done {background: var(--color-success-light); color: var(--color-success); text-decoration: line-through;}
.cp-advices {display: flex; flex-direction: column; gap: 6px; margin: 10px 0;}
.cp-advice {padding: 8px 12px; border-radius: 8px; font-size: 13px;}
.cp-advice--BUY_RUNG {background: var(--color-success-light); color: var(--color-success);}
.cp-advice--TRIM {background: var(--color-warning-light); color: var(--color-orange);}
.cp-advice--BREAKDOWN {background: var(--color-danger-light); color: var(--color-danger);}
.cp-modal-mask {position: fixed; inset: 0; background: var(--color-overlay); display: flex; align-items: center; justify-content: center; z-index: 100;}
.cp-modal {background: var(--color-surface-elevated); border-radius: 14px; padding: 20px; min-width: 320px;}
```

- [ ] **Step 3: 注册路由与菜单**

`App.tsx`:仿 NationalTeam 的 lazy 模式(grep `const NationalTeam` 找到准确写法),加:

```tsx
const CoursePortfolio = lazy(() => import('./pages/CoursePortfolio'));
```

Routes 中(放在 screener 路由旁):

```tsx
<Route path="/course-portfolio" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><CoursePortfolio /></Suspense>} />
```

`Layout.tsx` 研究组(约 line 46 选股器之后)加:

```tsx
      {path: '/course-portfolio', label: '自动建组合', icon: Icon.portfolio},
```

- [ ] **Step 4: 类型检查与构建**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web && npx tsc --noEmit -p tsconfig.json && npm run build 2>&1 | tail -5`
Expected: tsc 0 错误;build 成功。若 tsconfig 既有失效问题(memory 提到),以 build 结果为准。

- [ ] **Step 5: Commit**

```bash
cd /home/yuandonghao/sidejob/sources/trader/ytrader
git add frontend/apps/web/src/pages/CoursePortfolio.tsx frontend/apps/web/src/pages/CoursePortfolio.css frontend/apps/web/src/App.tsx frontend/apps/web/src/components/Layout.tsx frontend/apps/web/src/lib/coursePortfolio.ts
git commit -m "feat(course-portfolio): 前端页面——向导(偏好/预览/换股)+详情检视+档位成交+路由菜单"
```

---

### Task 8: 全量验证

**Files:** 无新文件

- [ ] **Step 1: 后端测试子集**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/api/test_course_portfolio_router.py tests/domain/test_course_builder.py tests/domain/test_course_review.py -q`
Expected: 全绿(新功能测试不依赖DB)

- [ ] **Step 2: 回归无新增破坏**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && .venv/bin/python -m pytest tests/ -q 2>&1 | tail -3`
Expected: 失败数 ≤ 既有基线(52失败+6收集错误, memory 记录)。新增失败必须修复。

- [ ] **Step 3: 前端构建**

Run: `cd /home/yuandonghao/sidejob/sources/trader/ytrader/frontend/apps/web && npm run build 2>&1 | tail -3 && npx vitest run 2>&1 | tail -5`
Expected: build 成功;vitest 全绿(含既有+新增)。

- [ ] **Step 4: 手工验收清单(启动 dev 后)**

1. 菜单出现"自动建组合";2. 新建向导四卡可选、生成预览三类分组;3. 保存后详情可见档位;4. 标记成交后进度推进、状态变"建仓中";5. 检视建议随现价出现 BUY_RUNG。

- [ ] **Step 5: 最终提交(如有零星修复)**

```bash
git add -A && git commit -m "fix(course-portfolio): 验收修复" || true
```

---

## Self-Review 结论

- **覆盖度:** spec 8节 ↔ 任务映射:选股分类(T3)、配额(T3)、估值带档位(T3)、周检视(T4)、数据层(T2)、API(T5)、前端(T6/T7)、测试边界(T3/T4/T5内)、数据加载(T1)。规格"边界"条目:样本不足→insufficient(T3 plan_pe_band)、候选池空→警告留现金(T3 assemble_plan)、停牌→跳过检视(T4)、换股仅同类(T7 swapLeg 按类别取候选)——均有对应。
- **占位符:** 无 TBD/TODO;Task 7 Step 1 内列出的4处"需修正"是编写时已知的错误清单,执行者必须落实(已给出正确写法)。
- **类型一致性:** `plan_pe_band` 返回 dict(state英文码)贯穿 T3/T5/T6;`entry_plan` rung dict 形状在 T2/T3/T4/T5 一致;`LegIn`/`SaveRequest` 与前端 save payload 字段一致;`api<T>` 包装与后端 `{code,msg,data}` 一致。
