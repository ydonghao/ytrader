# 国家队动向监控 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `/national-team` 页面提供「每日 ETF 护盘信号」+「2015 年至今季报持仓历年对比」两个 Tab，让用户每天看到国家队动向。

**Architecture:** 单页两 Tab。后端两条管道:(1) ETF 每日信号走 TTL 内存缓存(仿 `market_router /fund-flow`),不落库;(2) 季报持仓走持久化表 `national_team_holding` + repository + 回填 job(仿 macro 栈),通过定时同步从 akshare 拉前十大流通股东。

**Tech Stack:** FastAPI + SQLModel + akshare(后端);React 18 + react-router v7 + recharts(前端)。

## Global Constraints

- 数据源**只用 akshare**,不引入新外部依赖。
- 后端分层:router → handler → repository,统一 `src.pkg.responses` 返回 `{code,msg,data}`。
- 持久化表靠 `SQLModel.metadata.create_all` 自动建表(项目无 Alembic);新增列用 `ALTER TABLE ADD COLUMN IF NOT EXISTS` 幂等补列。
- 前端用原生 `fetch` + `useEffect`/`useState`,响应读 `j.data`;图表用 recharts + `ResponsiveContainer`;颜色用 CSS vars(`--color-accent` 等),动画 `isAnimationActive={false}`。
- 国家队主体匹配用**前缀匹配**,名单配置化存于 `backend/conf/national_team_entities.yaml`。
- 不扫全市场;回填范围 = 沪深300 + 银行 + 非银成分股。
- 模仿对象:`macro_indicator.py`(repository)、`macro_handler.py`+`macro_router.py`(API)、`market_router.py /fund-flow`(TTL 缓存)、`sw_index_backfill_all.py`(回填 job)、`FundFlow.tsx`/`Macro.tsx`(前端页面)。

## File Structure

**后端(创建):**
- `backend/conf/national_team_entities.yaml` — 国家队主体名单 + 监控 ETF 列表(配置)
- `backend/src/infra/database/market/national_team_holding.py` — 持仓表 entity + repository + 行业关联表
- `backend/src/api/handler/national_team_handler.py` — 5 个 API handler
- `backend/src/api/router/national_team_router.py` — router
- `backend/src/domain/market/sync/jobs/national_team_backfill.py` — 回填 job

**后端(修改):**
- `backend/src/domain/market/sync/providers/akshare_provider.py` — 加 2 个 provider 方法
- `backend/main.py` — 注册 `national_team_router`

**前端(创建):**
- `frontend/apps/web/src/pages/NationalTeam.tsx` — 单页两 Tab
- `frontend/apps/web/src/pages/NationalTeam.css` — 样式

**前端(修改):**
- `frontend/apps/web/src/components/Layout.tsx` — 加菜单项(O40 后)
- `frontend/apps/web/src/App.tsx` — 加路由

---

## Task 1: 国家队配置文件

**Files:**
- Create: `backend/conf/national_team_entities.yaml`

**Interfaces:**
- Produces: `national_team_entities.yaml`,被 Task 3/4(provider 读名单)、Task 5(job 读名单与ETF)、Task 6(handler 读 ETF 列表)消费。

- [ ] **Step 1: 写配置文件**

创建 `backend/conf/national_team_entities.yaml`:

```yaml
# 国家队主体名单 + 监控 ETF
# 主体用前缀匹配(资管计划/社保组合后缀多变)
# holder_categories: 键 = category 标识; 值 = 前缀列表
holder_categories:
  huijin:
    - 中央汇金投资有限责任公司
    - 中央汇金资产管理有限责任公司
  zhengjin:
    - 中国证券金融股份有限公司
    - 中证金融资产管理计划
  safe:
    - 梧桐树投资平台有限责任公司
    - 北京凤山投资有限责任公司
    - 北京坤藤投资有限责任公司
  social_security:
    - 全国社保基金

# 每日动向监控的核心宽基 ETF
# index_code 用于"抗跌判定"(ETF 涨跌 vs 对应指数涨跌)
watch_etfs:
  - etf_code: "510300"
    etf_name: "沪深300ETF(华泰柏瑞)"
    index_code: "sh000300"
  - etf_code: "510050"
    etf_name: "上证50ETF(华夏)"
    index_code: "sh000016"
  - etf_code: "510500"
    etf_name: "中证500ETF(南方)"
    index_code: "sh000905"
  - etf_code: "560010"
    etf_name: "中证1000ETF(广发)"
    index_code: "sh000852"
  - etf_code: "159915"
    etf_name: "创业板ETF(易方达)"
    index_code: "sz399006"
  - etf_code: "563360"
    etf_name: "中证A500ETF(华泰柏瑞)"
    index_code: "sh932000"

# 回填范围:成分股来源
backfill_scope:
  # 沪深300成分股
  - index_code: "000300"
    index_name: "沪深300"
  # 银行 + 非银金融板块(申万一级行业代码)
  - sw_sector_code: "801192"
    sw_sector_name: "银行"
  - sw_sector_code: "801193"
    sw_sector_name: "非银金融"

# 回填时间范围
backfill_from: "2015-01-01"  # 从 2015Q1 起
```

- [ ] **Step 2: 验证 YAML 可解析**

Run:
```bash
cd backend && python -c "import yaml; d=yaml.safe_load(open('conf/national_team_entities.yaml')); print('categories:', list(d['holder_categories'].keys())); print('etfs:', len(d['watch_etfs'])); print('scope:', len(d['backfill_scope']))"
```
Expected: `categories: ['huijin', 'zhengjin', 'safe', 'social_security']` / `etfs: 6` / `scope: 3`

- [ ] **Step 3: Commit**

```bash
git add backend/conf/national_team_entities.yaml
git commit -m "feat(national-team): add entities config (holders + watch etfs)"
```

---

## Task 2: 持仓表 + 行业关联表 + Repository

**Files:**
- Create: `backend/src/infra/database/market/national_team_holding.py`

**Interfaces:**
- Consumes: `src.infra.database.sql_engine.engine` 的 `DBConnection`/`create_db_connection`、`src.infra.database.sql_engine.dsn.get_dsn`(同 `macro_indicator.py`)。
- Produces:
  - `NationalTeamHolding`(SQLModel entity,表 `national_team_holding`)
  - `NationalTeamSymbolSector`(SQLModel entity,表 `national_team_symbol_sector`)
  - `NationalTeamHoldingRepository`,方法:
    - `upsert(record: dict) -> None`
    - `bulk_upsert(rows: list[dict]) -> int`
    - `get_summary_series(category: str|None, from_date: date|None) -> list[dict]` — 按 report_date×category 聚合总市值
    - `get_changes(period: date, vs_period: date, category: str|None, change_type: str|None) -> list[dict]`
    - `get_sector_distribution(from_date: date|None) -> list[dict]`
    - `get_top_holdings(period: date|None, limit: int) -> list[dict]`
    - `get_symbol_history(symbol: str) -> list[dict]`
    - `upsert_sector(symbol: str, sector: str) -> None`
    - `get_coverage() -> dict` — 已覆盖的 (report_date 数, symbol 数, 最新报告期) 用于进度展示
  - `create_national_team_repository(db_connection=None) -> NationalTeamHoldingRepository`

- [ ] **Step 1: 写 entity + repository**

创建 `backend/src/infra/database/market/national_team_holding.py`,模仿 `macro_indicator.py` 结构:

```python
"""national_team_holding 表:国家队季报持仓快照(前十大流通股东)。

按 (report_date, holder_name, symbol) 幂等 upsert。
靠 SQLModel.metadata.create_all 自动建表(项目无 Alembic)。
另含 national_team_symbol_sector:股票 → 申万一级行业(回填时落,查询零额外调用)。
"""
import threading
import datetime as dt
from datetime import datetime
from typing import Optional

from sqlmodel import Session, SQLModel, Field, select
from sqlalchemy import func

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


class NationalTeamHolding(SQLModel, table=True):
    """国家队单条持仓(某季度某股某股东)。"""

    __tablename__ = "national_team_holding"

    id: Optional[int] = Field(default=None, primary_key=True)
    report_date: dt.date           # 报告期(季度末)YYYY-MM-DD
    holder_name: str               # 股东全称(akshare 原始)
    holder_category: str           # huijin/zhengjin/safe/social_security
    symbol: str                    # 股票代码(无交易所前缀)
    company_name: str = Field(default="")
    hold_shares: int = Field(default=0)        # 持股数
    hold_value: float = Field(default=0.0)     # 持股市值(元)
    pct_of_float: float = Field(default=0.0)   # 占流通股比例 %
    ranking: int = Field(default=0)            # 第几大流通股东
    is_new: Optional[bool] = Field(default=None)          # 本期是否新进
    change_shares: Optional[int] = Field(default=None)    # 本期变动股数
    fetched_at: datetime = Field(default_factory=datetime.now)


class NationalTeamSymbolSector(SQLModel, table=True):
    """股票 → 申万一级行业(回填时写入,供行业分布查询)。"""

    __tablename__ = "national_team_symbol_sector"

    symbol: str = Field(primary_key=True)
    sector: str = Field(default="")           # 申万一级行业名


class NationalTeamHoldingRepository:
    """国家队持仓数据访问。"""

    def __init__(self, db: DBConnection):
        self._db = db

    # ── 写入 ─────────────────────────────────────────────────
    def upsert(self, record: dict) -> None:
        """按 (report_date, holder_name, symbol) upsert 一条。"""
        with self._db.session_scope() as s:
            existing = s.exec(
                select(NationalTeamHolding).where(
                    NationalTeamHolding.report_date == record["report_date"],
                    NationalTeamHolding.holder_name == record["holder_name"],
                    NationalTeamHolding.symbol == record["symbol"],
                )
            ).first()
            if existing:
                for k, v in record.items():
                    setattr(existing, k, v)
            else:
                s.add(NationalTeamHolding(**record))

    def bulk_upsert(self, rows: list[dict]) -> int:
        n = 0
        for r in rows:
            self.upsert(r)
            n += 1
        return n

    def upsert_sector(self, symbol: str, sector: str) -> None:
        with self._db.session_scope() as s:
            existing = s.exec(
                select(NationalTeamSymbolSector).where(
                    NationalTeamSymbolSector.symbol == symbol
                )
            ).first()
            if existing:
                existing.sector = sector
            else:
                s.add(NationalTeamSymbolSector(symbol=symbol, sector=sector))

    # ── 查询 ─────────────────────────────────────────────────
    def get_summary_series(
        self, category: Optional[str] = None,
        from_date: Optional[dt.date] = None,
    ) -> list[dict]:
        """按 report_date × holder_category 聚合持股市值(画总市值趋势用)。
        返回 [{report_date, holder_category, total_value, total_count}]。"""
        with self._db.session_scope() as s:
            stmt = (
                select(
                    NationalTeamHolding.report_date,
                    NationalTeamHolding.holder_category,
                    func.sum(NationalTeamHolding.hold_value).label("total_value"),
                    func.count(NationalTeamHolding.id).label("total_count"),
                )
                .group_by(
                    NationalTeamHolding.report_date,
                    NationalTeamHolding.holder_category,
                )
                .order_by(NationalTeamHolding.report_date)
            )
            if category:
                stmt = stmt.where(NationalTeamHolding.holder_category == category)
            if from_date:
                stmt = stmt.where(NationalTeamHolding.report_date >= from_date)
            rows = s.exec(stmt).all()
            return [
                {
                    "report_date": r.report_date.isoformat() if r.report_date else None,
                    "holder_category": r.holder_category,
                    "total_value": float(r.total_value or 0),
                    "total_count": int(r.total_count or 0),
                }
                for r in rows
            ]

    def get_changes(
        self,
        period: dt.date,
        vs_period: dt.date,
        category: Optional[str] = None,
        change_type: Optional[str] = None,
    ) -> list[dict]:
        """对比两个报告期,返回 [(symbol, holder_name, ...)] 的变动明细。
        change_type: new/increase/decrease/exit(None=全部)。
        逻辑:对同一 (symbol, holder_name) 比对两期 hold_shares。"""
        with self._db.session_scope() as s:
            base_q = select(NationalTeamHolding)
            if category:
                base_q = base_q.where(NationalTeamHolding.holder_category == category)

            cur = { (r.symbol, r.holder_name): r for r in
                    s.exec(base_q.where(NationalTeamHolding.report_date == period)).all() }
            prev = { (r.symbol, r.holder_name): r for r in
                     s.exec(base_q.where(NationalTeamHolding.report_date == vs_period)).all() }

            out = []
            all_keys = set(cur.keys()) | set(prev.keys())
            for key in all_keys:
                symbol, holder_name = key
                c = cur.get(key)
                p = prev.get(key)
                if c and not p:
                    ctype, delta = "new", c.hold_shares
                elif p and not c:
                    ctype, delta = "exit", -p.hold_shares
                elif c and p:
                    delta = c.hold_shares - p.hold_shares
                    if delta > 0:
                        ctype = "increase"
                    elif delta < 0:
                        ctype = "decrease"
                    else:
                        continue  # 无变动,跳过
                else:
                    continue
                if change_type and ctype != change_type:
                    continue
                ref = c or p
                out.append({
                    "symbol": symbol,
                    "company_name": ref.company_name,
                    "holder_name": holder_name,
                    "holder_category": ref.holder_category,
                    "cur_shares": c.hold_shares if c else 0,
                    "prev_shares": p.hold_shares if p else 0,
                    "change_shares": delta,
                    "change_type": ctype,
                    "cur_value": c.hold_value if c else 0.0,
                })
            # 按变动市值绝对值降序
            out.sort(key=lambda x: abs(x["change_shares"]), reverse=True)
            return out

    def get_sector_distribution(
        self, from_date: Optional[dt.date] = None,
    ) -> list[dict]:
        """按 report_date × 行业 聚合持股市值(行业分布时间序列)。
        返回 [{report_date, sector, total_value}]。"""
        with self._db.session_scope() as s:
            stmt = (
                select(
                    NationalTeamHolding.report_date,
                    NationalTeamSymbolSector.sector,
                    func.sum(NationalTeamHolding.hold_value).label("total_value"),
                )
                .join(
                    NationalTeamSymbolSector,
                    NationalTeamHolding.symbol == NationalTeamSymbolSector.symbol,
                )
                .group_by(
                    NationalTeamHolding.report_date,
                    NationalTeamSymbolSector.sector,
                )
                .order_by(NationalTeamHolding.report_date)
            )
            if from_date:
                stmt = stmt.where(NationalTeamHolding.report_date >= from_date)
            rows = s.exec(stmt).all()
            return [
                {
                    "report_date": r.report_date.isoformat() if r.report_date else None,
                    "sector": r.sector or "未知",
                    "total_value": float(r.total_value or 0),
                }
                for r in rows
            ]

    def get_top_holdings(
        self, period: Optional[dt.date] = None, limit: int = 50,
    ) -> list[dict]:
        """按报告期 × symbol 聚合持仓市值,降序取 Top。period=None 取最新报告期。
        返回 [{symbol, company_name, sector, total_value, holders: [...]}]。"""
        with self._db.session_scope() as s:
            if period is None:
                latest = s.exec(
                    select(func.max(NationalTeamHolding.report_date))
                ).one()
                if latest is None:
                    return []
                period = latest
            # 每个 symbol 聚合
            rows = s.exec(
                select(NationalTeamHolding)
                .where(NationalTeamHolding.report_date == period)
            ).all()
            by_symbol: dict[str, dict] = {}
            for r in rows:
                d = by_symbol.setdefault(r.symbol, {
                    "symbol": r.symbol,
                    "company_name": r.company_name,
                    "report_date": period.isoformat() if isinstance(period, dt.date) else period,
                    "total_value": 0.0,
                    "holders": [],
                })
                d["total_value"] += float(r.hold_value or 0)
                d["holders"].append({
                    "holder_name": r.holder_name,
                    "holder_category": r.holder_category,
                    "hold_value": float(r.hold_value or 0),
                    "hold_shares": int(r.hold_shares or 0),
                    "pct_of_float": float(r.pct_of_float or 0),
                    "ranking": int(r.ranking or 0),
                })
            # 补行业
            sectors = {
                ss.symbol: ss.sector for ss in s.exec(select(NationalTeamSymbolSector)).all()
            }
            for d in by_symbol.values():
                d["sector"] = sectors.get(d["symbol"], "未知")
                d["holders"].sort(key=lambda h: h["hold_value"], reverse=True)
            ranked = sorted(by_symbol.values(),
                            key=lambda x: x["total_value"], reverse=True)[:limit]
            return ranked

    def get_symbol_history(self, symbol: str) -> list[dict]:
        """单股的国家队持仓历史(按报告期升序),供下钻。"""
        with self._db.session_scope() as s:
            rows = s.exec(
                select(NationalTeamHolding)
                .where(NationalTeamHolding.symbol == symbol)
                .order_by(NationalTeamHolding.report_date)
            ).all()
            return [
                {
                    "report_date": r.report_date.isoformat() if r.report_date else None,
                    "holder_name": r.holder_name,
                    "holder_category": r.holder_category,
                    "hold_shares": int(r.hold_shares or 0),
                    "hold_value": float(r.hold_value or 0),
                    "pct_of_float": float(r.pct_of_float or 0),
                    "is_new": r.is_new,
                    "change_shares": r.change_shares,
                }
                for r in rows
            ]

    def get_coverage(self) -> dict:
        """回填进度:报告期数、symbol 数、最新报告期。"""
        with self._db.session_scope() as s:
            periods = s.exec(
                select(NationalTeamHolding.report_date).distinct()
            ).all()
            symbols = s.exec(
                select(NationalTeamHolding.symbol).distinct()
            ).all()
            latest = s.exec(
                select(func.max(NationalTeamHolding.report_date))
            ).one()
            return {
                "report_periods": sorted(p.isoformat() for p in periods if p),
                "symbol_count": len(symbols),
                "latest_period": latest.isoformat() if latest else None,
            }


# ======== 工厂函数(遵循 intel/blog/macro 单例 + 工厂约定) ========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_national_team_repository(
    db_connection: DBConnection | None = None,
) -> NationalTeamHoldingRepository:
    return NationalTeamHoldingRepository(db_connection or _get_db_connection())
```

- [ ] **Step 2: 验证 import 与建表**

Run:
```bash
cd backend && python -c "
from src.infra.database.market.national_team_holding import (
    NationalTeamHolding, NationalTeamSymbolSector,
    NationalTeamHoldingRepository, create_national_team_repository,
)
print('entities:', NationalTeamHolding.__tablename__, NationalTeamSymbolSector.__tablename__)
print('repo methods:', [m for m in dir(NationalTeamHoldingRepository) if not m.startswith('_')])
"
```
Expected: 打印两个表名 + `bulk_upsert`/`get_summary_series`/`get_changes`/`get_sector_distribution`/`get_top_holdings`/`get_symbol_history`/`get_coverage` 等方法名。

- [ ] **Step 3: Commit**

```bash
git add backend/src/infra/database/market/national_team_holding.py
git commit -m "feat(national-team): add holding table + repository"
```

---

## Task 3: 名单匹配工具 + 配置加载

**Files:**
- Create: `backend/src/domain/market/sync/providers/national_team_config.py`

**Interfaces:**
- Produces:
  - `load_national_team_config() -> dict` — 读 `conf/national_team_entities.yaml`,带模块级缓存
  - `match_holder_category(holder_name: str) -> str | None` — 前缀匹配,返回 category 或 None
  - `get_watch_etfs() -> list[dict]`
  - `get_backfill_scope() -> list[dict]`

- [ ] **Step 1: 写模块**

创建 `backend/src/domain/market/sync/providers/national_team_config.py`:

```python
"""国家队配置加载 + 主体名前缀匹配。

配置文件:backend/conf/national_team_entities.yaml
"""
from functools import lru_cache
from pathlib import Path

import yaml

_CONF_PATH = Path(__file__).parent.parent.parent.parent.parent.parent / "conf" / "national_team_entities.yaml"


@lru_cache(maxsize=1)
def load_national_team_config() -> dict:
    """加载并缓存配置。"""
    with open(_CONF_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def match_holder_category(holder_name: str) -> str | None:
    """前缀匹配股东名,返回 category(huijin/zhengjin/safe/social_security)或 None。

    匹配规则:holder_name 以某个前缀开头(去除空格后比较)即命中。
    """
    if not holder_name:
        return None
    name = holder_name.strip()
    cfg = load_national_team_config()
    for category, prefixes in cfg.get("holder_categories", {}).items():
        for prefix in prefixes:
            if name.startswith(prefix.strip()):
                return category
    return None


def get_watch_etfs() -> list[dict]:
    return load_national_team_config().get("watch_etfs", [])


def get_backfill_scope() -> list[dict]:
    return load_national_team_config().get("backfill_scope", [])


def get_backfill_from() -> str:
    return load_national_team_config().get("backfill_from", "2015-01-01")
```

- [ ] **Step 2: 验证匹配**

Run:
```bash
cd backend && python -c "
from src.domain.market.sync.providers.national_team_config import (
    match_holder_category, get_watch_etfs, get_backfill_scope,
)
print('汇金:', match_holder_category('中央汇金资产管理有限责任公司'))
print('证金资管:', match_holder_category('中证金融资产管理计划-工商银行-1号'))
print('社保组合:', match_holder_category('全国社保基金一一八组合'))
print('非国家队:', match_holder_category('某某基金管理有限公司'))
print('etfs:', len(get_watch_etfs()), 'scope:', len(get_backfill_scope()))
"
```
Expected: `汇金: huijin` / `证金资管: zhengjin` / `社保组合: social_security` / `非国家队: None` / `etfs: 6 scope: 3`

- [ ] **Step 3: Commit**

```bash
git add backend/src/domain/market/sync/providers/national_team_config.py
git commit -m "feat(national-team): add config loader + holder-name matcher"
```

---

## Task 4: AkshareProvider 两个新方法

**Files:**
- Modify: `backend/src/domain/market/sync/providers/akshare_provider.py`(在类 `AkshareProvider` 内追加两个方法)

**Interfaces:**
- Consumes: `import akshare as ak`(已在文件顶部),`national_team_config.match_holder_category`(Task 3)。
- Produces:
  - `AkshareProvider.fetch_top10_float_holders(symbol: str, report_date: str) -> list[dict]` — 返回 `[{holder_name, hold_shares, hold_value, pct_of_float, ranking, ...}]`,**不过滤**国家队(过滤由 job 做)
  - `AkshareProvider.fetch_etf_daily_signal(etf_code: str, index_code: str, lookback_days: int = 20) -> dict` — 返回 `{etf_code, etf_name, vol_ratio, etf_chg_pct, index_chg_pct, defend_flag, strength, as_of_date}`

- [ ] **Step 1: 在 AkshareProvider 类内追加 `fetch_top10_float_holders`**

在 `akshare_provider.py` 的 `AkshareProvider` 类内(找一个现有 fetch 方法之后)追加:

```python
    def fetch_top10_float_holders(
        self, symbol: str, report_date: str
    ) -> list[dict]:
        """拉取某股某报告期前十大流通股东。

        Args:
            symbol: 股票代码(无交易所前缀,如 600519)
            report_date: 报告期 YYYYMMDD(akshare 要求)或 YYYY-MM-DD(内部转换)
        Returns:
            [{holder_name, hold_shares, hold_value, pct_of_float, ranking}],
            失败或无数据返回 []。
        """
        try:
            date_str = str(report_date).replace("-", "")  # YYYYMMDD
            df = ak.stock_gdfx_free_top_10_em(symbol=symbol, date=date_str)
            if df is None or len(df) == 0:
                return []
            out = []
            for _, r in df.iterrows():
                holder_name = str(r.get("股东名称", "")).strip()
                if not holder_name:
                    continue
                out.append({
                    "holder_name": holder_name,
                    "hold_shares": self._num(r.get("持股数量") or r.get("持股数量(股)")) ,
                    "hold_value": self._num(r.get("持股市值") or r.get("持股市值(元)")),
                    "pct_of_float": self._num(r.get("持股比例") or r.get("持股比例(%)")),
                    "ranking": self._num(r.get("排名") or r.get("序号")) or 0,
                })
            return out
        except Exception:
            return []
```

> 注:`_num`、`_parse_report_date` 等解析辅助已是 AkshareProvider 既有方法,直接复用。若列名有出入,以 akshare 实际返回为准——抓一只样本验证(下一步)。

- [ ] **Step 2: 验证 fetch_top10_float_holders 抓真实数据**

Run:
```bash
cd backend && python -c "
from src.domain.market.sync.sync_provider import get_provider
p = get_provider()
# 600519 茅台,2024Q4 报告期 20241231
rows = p.fetch_top10_float_holders('600519', '20241231')
print('rows:', len(rows))
for r in rows[:3]:
    print(r)
"
```
Expected: 打印若干行前十大流通股东(含 holder_name/hold_shares 等)。若为空,换 `20240930` 等报告期重试;若列名报错,按实际列名修正 Step 1 的 `r.get(...)` key。

- [ ] **Step 3: 追加 `fetch_etf_daily_signal`**

在 `fetch_top10_float_holders` 之后追加:

```python
    def fetch_etf_daily_signal(
        self, etf_code: str, index_code: str, lookback_days: int = 20,
    ) -> dict:
        """计算单只 ETF 当日护盘信号。

        信号逻辑:
          1. 取 ETF 近(lookback_days+10)日量价,算今日量 / 过去 N 日均量 = 放量倍数
          2. 取对应指数当日涨跌
          3. defend_flag: 指数跌 但 ETF 明显抗跌(etf_chg >= index_chg + 0.5)
          4. strength: vol_ratio>=3 and defend -> 'strong';
                       vol_ratio>=2 -> 'suspect'; else 'none'
        Returns:
            {etf_code, etf_name, as_of_date, vol_ratio, etf_chg_pct,
             index_chg_pct, defend_flag, strength, avg_vol_20d, today_vol}
        """
        import datetime as _dt
        try:
            # ETF 近 40 日量价(akshare fund_etf_hist_sina 已在用)
            df = ak.fund_etf_hist_sina(symbol=f"sz{etf_code}" if etf_code.startswith("1") else f"sh{etf_code}")
            if df is None or len(df) == 0:
                # 试另一个交易所前缀
                df = ak.fund_etf_hist_sina(symbol=f"sh{etf_code}" if etf_code.startswith("5") else f"sz{etf_code}")
            if df is None or len(df) == 0:
                return {"etf_code": etf_code, "strength": "error", "vol_ratio": 0.0}
            df = df.sort_values("date").tail(lookback_days + 10)
            today_vol = self._num(df.iloc[-1].get("volume") or df.iloc[-1].get("成交量"))
            prev_vols = [self._num(r.get("volume") or r.get("成交量")) for _, r in df.iloc[-(lookback_days+1):-1].iterrows()]
            avg_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 0
            vol_ratio = (today_vol / avg_vol) if avg_vol else 0.0
            # ETF 当日涨跌(用收盘价)
            etf_close = [self._num(x) for x in df["close"].tail(2).tolist()] if "close" in df else [0, 0]
            etf_chg_pct = ((etf_close[-1] - etf_close[-2]) / etf_close[-2] * 100) if len(etf_close) >= 2 and etf_close[-2] else 0.0
            as_of = str(df.iloc[-1].get("date"))
            # 对应指数当日涨跌
            index_chg_pct = 0.0
            try:
                idf = ak.stock_zh_index_daily(symbol=index_code)
                if idf is not None and len(idf) >= 2:
                    ic = [self._num(x) for x in idf["close"].tail(2).tolist()]
                    if len(ic) >= 2 and ic[-2]:
                        index_chg_pct = (ic[-1] - ic[-2]) / ic[-2] * 100
            except Exception:
                pass
            defend_flag = (index_chg_pct < 0) and (etf_chg_pct >= index_chg_pct + 0.5)
            if vol_ratio >= 3 and defend_flag:
                strength = "strong"
            elif vol_ratio >= 2:
                strength = "suspect"
            else:
                strength = "none"
            return {
                "etf_code": etf_code,
                "as_of_date": as_of,
                "vol_ratio": round(vol_ratio, 2),
                "etf_chg_pct": round(etf_chg_pct, 2),
                "index_chg_pct": round(index_chg_pct, 2),
                "defend_flag": bool(defend_flag),
                "strength": strength,
                "avg_vol_20d": int(avg_vol),
                "today_vol": int(today_vol),
            }
        except Exception as e:
            return {"etf_code": etf_code, "strength": "error", "vol_ratio": 0.0, "error": str(e)}
```

- [ ] **Step 4: 验证 ETF 信号**

Run:
```bash
cd backend && python -c "
from src.domain.market.sync.sync_provider import get_provider
p = get_provider()
sig = p.fetch_etf_daily_signal('510300', 'sh000300')
print(sig)
"
```
Expected: 打印 dict,含 `vol_ratio`/`strength`(none/suspect/strong)/`as_of_date` 等字段。若 `fund_etf_hist_sina` 对该代码返回空,按 akshare 实际接受的 symbol 形式调整前缀逻辑。

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/sync/providers/akshare_provider.py
git commit -m "feat(national-team): add fetch_top10_float_holders + fetch_etf_daily_signal to provider"
```

---

## Task 5: 回填 Job

**Files:**
- Create: `backend/src/domain/market/sync/jobs/national_team_backfill.py`

**Interfaces:**
- Consumes: `get_provider()`(Task 4 方法)、`match_holder_category`/`get_backfill_scope`/`get_backfill_from`(Task 3)、`create_national_team_repository`(Task 2)。
- Produces: 可独立运行的 `python -m src.domain.market.sync.jobs.national_team_backfill`,支持 `--max-calls` 限批(定时调度每次跑一段)、`--from` 指定起点。

- [ ] **Step 1: 写回填 job**

创建 `backend/src/domain/market/sync/jobs/national_team_backfill.py`,模仿 `sw_index_backfill_all.py` 的 main/argparse/logging 结构:

```python
"""
NationalTeamBackfillJob
=======================
国家队季报持仓回填(沪深300 + 银行 + 非银成分股 × 各报告期)。

数据源:akshare stock_gdfx_free_top_10_em(个股前十大流通股东)。
匹配:股东名前缀匹配国家队名单 → 落 national_team_holding。

策略:断点续传 + 限批运行(每次最多 --max-calls 次调用),由调度定期触发,
多日跑完 2015→今。进度文件:backend/conf/.national_team_backfill_progress.json。

用法:
  # 每次跑 1000 次调用(约 1-2 小时)
  python -m src.domain.market.sync.jobs.national_team_backfill --max-calls 1000
  # 全量重跑(忽略进度)
  python -m src.domain.market.sync.jobs.national_team_backfill --reset
"""
import argparse
import json
import logging
import socket
import sys
import datetime as dt
from itertools import product
from pathlib import Path

socket.setdefaulttimeout(60)

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent  # backend/
sys.path.insert(0, str(_BACKEND))

import akshare as ak  # noqa: E402
from src.domain.market.sync.sync_provider import get_provider  # noqa: E402
from src.domain.market.sync.providers.national_team_config import (  # noqa: E402
    match_holder_category, get_backfill_scope, get_backfill_from,
)
from src.infra.database.market.national_team_holding import (  # noqa: E402
    create_national_team_repository,
)

log = logging.getLogger("national_team_backfill")
_PROGRESS = _BACKEND / "conf" / ".national_team_backfill_progress.json"


def _quarter_end_dates(from_year: int) -> list[str]:
    """生成从 from_year 各季度末到当前最近一个已披露季度的报告期(YYYYMMDD)。"""
    today = dt.date.today()
    out = []
    y, q = from_year, 1
    while True:
        month_day = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}[q]
        d = dt.date.fromisoformat(f"{y}-{month_day[:2]}-{month_day[2:]}")
        if d > today:
            break
        out.append(f"{y}{month_day}")
        q += 1
        if q > 4:
            q, y = 1, y + 1
    return out


def _fetch_scope_symbols() -> list[tuple[str, str]]:
    """返回 [(symbol, company_name)],去重。成分股来自沪深300 + 银行 + 非银。"""
    scope = get_backfill_scope()
    out: dict[str, str] = {}
    for item in scope:
        try:
            if "index_code" in item:
                df = ak.index_stock_cons_csindex(symbol=item["index_code"])
                # 列:成分券代码 / 成分券名称
                for _, r in df.iterrows():
                    code = str(r.get("成分券代码") or r.get("成份券代码") or "").strip()
                    name = str(r.get("成分券名称") or r.get("成份券名称") or "").strip()
                    if code:
                        out.setdefault(code, name)
            elif "sw_sector_code" in item:
                # 申万一级行业成分股
                df = ak.index_component_sw(symbol=item["sw_sector_code"])
                for _, r in df.iterrows():
                    code = str(r.get("证券代码") or r.get("股票代码") or "").strip()
                    name = str(r.get("证券名称") or r.get("股票名称") or "").strip()
                    if code:
                        out.setdefault(code, name)
        except Exception as e:
            log.warning(f"抓成分股失败 {item}: {e}")
    return [(k, v) for k, v in out.items()]


def _load_progress() -> set:
    if _PROGRESS.exists():
        try:
            return set(json.loads(_PROGRESS.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def _save_progress(done: set) -> None:
    _PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    _PROGRESS.write_text(json.dumps(sorted(done)), encoding="utf-8")


def run(max_calls: int = 0, reset: bool = False) -> dict:
    """执行一轮回填。

    Args:
        max_calls: 本轮最多调用次数(0=不限,跑完所有)。建议定时调度设 1000。
        reset: True 则忽略进度,从头开始。
    Returns:
        {calls, matched, written, remaining}
    """
    from_year = int(get_backfill_from()[:4])
    quarters = _quarter_end_dates(from_year)
    symbols = _fetch_scope_symbols()
    log.info(f"待回填:{len(symbols)} 股 × {len(quarters)} 季 = {len(symbols)*len(quarters)} 组合")

    done = set() if reset else _load_progress()
    repo = create_national_team_repository()
    provider = get_provider()
    # 扇出顺序:优先扫最新季度(快速看到近期数据),再回溯历史
    tasks = [(s, q) for s, q in product(symbols, quarters) if f"{s}|{q}" not in done]
    tasks.sort(key=lambda x: x[1], reverse=True)  # 报告期降序

    calls = matched = written = 0
    for (symbol, company), q in [( (s, name), q) for (s, name), q in
                                  [(t[0], t[1]) for t in tasks]]:
        # tasks 元素是 ((symbol, q))... 修正:重新组织
        pass

    # 重新组织循环(tasks 元素是 (symbol_tuple, q))
    for sym_tuple, q in tasks:
        symbol, company = sym_tuple
        if max_calls and calls >= max_calls:
            log.info(f"达到本轮上限 {max_calls} 次调用,暂停。")
            break
        calls += 1
        try:
            holders = provider.fetch_top10_float_holders(symbol, q)
            # 落行业(用申万一级,这里简化:首次抓时一并记;若拿不到行业先留空)
            # 行业在 Task 6 查询时由 get_sector_distribution join;此处可选落库
            rows = []
            for h in holders:
                cat = match_holder_category(h["holder_name"])
                if not cat:
                    continue
                rows.append({
                    "report_date": dt.date.fromisoformat(
                        f"{q[:4]}-{q[4:6]}-{q[6:8]}"
                    ),
                    "holder_name": h["holder_name"],
                    "holder_category": cat,
                    "symbol": symbol,
                    "company_name": company,
                    "hold_shares": int(h.get("hold_shares") or 0),
                    "hold_value": float(h.get("hold_value") or 0),
                    "pct_of_float": float(h.get("pct_of_float") or 0),
                    "ranking": int(h.get("ranking") or 0),
                })
            if rows:
                repo.bulk_upsert(rows)
                written += len(rows)
                matched += 1
            done.add(f"{symbol}|{q}")
            if calls % 50 == 0:
                _save_progress(done)
                log.info(f"进度:{calls} 次调用, {matched} 股命中, {written} 条入库")
        except Exception as e:
            log.warning(f"失败 {symbol}@{q}: {e}")
            done.add(f"{symbol}|{q}")  # 失败也标记,避免反复重试卡死

    _save_progress(done)
    remaining = len(symbols) * len(quarters) - len(done)
    summary = {"calls": calls, "matched": matched, "written": written, "remaining": remaining}
    log.info(f"=== 本轮完成:{summary} ===")
    return summary


def main():
    parser = argparse.ArgumentParser(description="国家队持仓回填")
    parser.add_argument("--max-calls", type=int, default=0, help="本轮最多调用次数(0=不限)")
    parser.add_argument("--reset", action="store_true", help="忽略进度,从头开始")
    args = parser.parse_args()

    (_BACKEND / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(_BACKEND / "logs" / "national_team_backfill.log",
                                encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    run(max_calls=args.max_calls, reset=args.reset)


if __name__ == "__main__":
    main()
```

> **注意**:`tasks` 的元素组织在 Step 1 里有一段冗余的占位循环(标注 pass 那段),实现时**删掉它**,只保留下面的 `for sym_tuple, q in tasks:` 正式循环。这里列出是为了说明 tasks 元素是 `((symbol, company), quarter)`。实现时直接用正式循环。

- [ ] **Step 2: 小批量冒烟测试**

Run:
```bash
cd backend && python -m src.domain.market.sync.jobs.national_team_backfill --max-calls 5
```
Expected: 日志显示「待回填:N 股 × M 季」、跑 5 次调用后暂停、`progress.json` 生成、`remaining > 0`。确认 `national_team_holding` 表有数据:

```bash
python -c "
from src.infra.database.market.national_team_holding import create_national_team_repository
print(create_national_team_repository().get_coverage())
"
```
Expected: `report_periods` 非空,`symbol_count > 0`。

- [ ] **Step 3: Commit**

```bash
git add backend/src/domain/market/sync/jobs/national_team_backfill.py
git commit -m "feat(national-team): add backfill job with resume + batch limit"
```

---

## Task 6: API Handler(5 个端点)

**Files:**
- Create: `backend/src/api/handler/national_team_handler.py`

**Interfaces:**
- Consumes: `create_national_team_repository`(Task 2)、`get_provider`(Task 4)、`get_watch_etfs`(Task 3)。
- Produces: 5 个 handler 函数,签名:
  - `daily_signals() -> Any`
  - `holdings_summary(category: str|None, from_date: str|None) -> Any`
  - `holdings_changes(period: str, vs_period: str, category: str|None, change_type: str|None) -> Any`
  - `holdings_sector_distribution(from_date: str|None) -> Any`
  - `holdings_top(period: str|None, limit: int) -> Any`
  - `holdings_symbol_history(symbol: str) -> Any`
  - `coverage() -> Any`

- [ ] **Step 1: 写 handler**

创建 `backend/src/api/handler/national_team_handler.py`,模仿 `macro_handler.py`:

```python
"""国家队板块 API handler — 每日 ETF 信号 + 历年季报持仓。

遵循 router → handler → repository 分层,统一 src.pkg.responses 返回。
"""
import datetime as dt
import time
from typing import Any, Optional

from src.pkg import responses


# ── 每日 ETF 信号(TTL 内存缓存)──────────────────────────────
_DAILY_CACHE: dict = {"data": None, "ts": 0}
_DAILY_TTL = 300  # 5 分钟


def daily_signals() -> Any:
    """当日核心宽基 ETF 护盘信号 + 近 20 日热力。
    返回 {as_of, summary:{strong,suspect,none}, signals:[...], heatmap_20d:[...]}。"""
    now = time.time()
    if _DAILY_CACHE["data"] and now - _DAILY_CACHE["ts"] < _DAILY_TTL:
        return responses.success(_DAILY_CACHE["data"])

    try:
        from src.domain.market.sync.sync_provider import get_provider
        from src.domain.market.sync.providers.national_team_config import get_watch_etfs

        provider = get_provider()
        etfs = get_watch_etfs()
        signals = []
        for e in etfs:
            sig = provider.fetch_etf_daily_signal(e["etf_code"], e["index_code"])
            sig["etf_name"] = e["etf_name"]
            signals.append(sig)

        # 近 20 日热力:对每只 ETF 取过去 20 个交易日的 vol_ratio 历史
        # 简化:此处先返回当日信号;20 日热力由前端用缓存当日值近似,
        # 或后续扩展。先给空数组,前端做降级。
        as_of = signals[0]["as_of_date"] if signals else None
        summary = {
            "strong": sum(1 for s in signals if s.get("strength") == "strong"),
            "suspect": sum(1 for s in signals if s.get("strength") == "suspect"),
            "none": sum(1 for s in signals if s.get("strength") == "none"),
            "error": sum(1 for s in signals if s.get("strength") == "error"),
        }
        data = {"as_of": as_of, "summary": summary, "signals": signals, "heatmap_20d": []}
        _DAILY_CACHE["data"] = data
        _DAILY_CACHE["ts"] = now
        return responses.success(data)
    except Exception as e:
        return responses.fail(f"获取每日信号失败: {e}")


# ── 历年持仓 ──────────────────────────────────────────────────
def _parse_date(s: Optional[str]) -> Optional[dt.date]:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except Exception:
        return None


def holdings_summary(
    category: Optional[str] = None, from_date: Optional[str] = None,
) -> Any:
    """总市值趋势(按 report_date × holder_category 聚合)。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    series = repo.get_summary_series(category=category, from_date=_parse_date(from_date))
    return responses.success({"series": series})


def holdings_changes(
    period: str, vs_period: str,
    category: Optional[str] = None, change_type: Optional[str] = None,
) -> Any:
    """季度环比变动明细。period=当期, vs_period=对比期(YYYY-MM-DD)。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    p = _parse_date(period)
    vp = _parse_date(vs_period)
    if not p or not vp:
        return responses.fail("period / vs_period 需为 YYYY-MM-DD")
    repo = create_national_team_repository()
    changes = repo.get_changes(period=p, vs_period=vp, category=category, change_type=change_type)
    return responses.success({"changes": changes, "period": period, "vs_period": vs_period})


def holdings_sector_distribution(from_date: Optional[str] = None) -> Any:
    """行业分布时间序列。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    series = repo.get_sector_distribution(from_date=_parse_date(from_date))
    return responses.success({"series": series})


def holdings_top(period: Optional[str] = None, limit: int = 50) -> Any:
    """个股 Top 榜(period=None 取最新报告期)。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    rows = repo.get_top_holdings(period=_parse_date(period), limit=limit)
    return responses.success({"rows": rows, "period": period})


def holdings_symbol_history(symbol: str) -> Any:
    """单股国家队持仓历史(下钻)。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    rows = repo.get_symbol_history(symbol=symbol)
    return responses.success({"symbol": symbol, "history": rows})


def coverage() -> Any:
    """回填进度(前端展示数据覆盖度)。"""
    from src.infra.database.market.national_team_holding import (
        create_national_team_repository,
    )
    repo = create_national_team_repository()
    return responses.success(repo.get_coverage())
```

- [ ] **Step 2: 验证 handler 可调用(空库场景)**

Run:
```bash
cd backend && python -c "
from src.api.handler import national_team_handler as h
print('coverage:', h.coverance if hasattr(h,'coverance') else h.coverage())
print('top:', h.holdings_top())
print('summary:', h.holdings_summary())
"
```
Expected: 三个调用都返回 `{code:0, data:...}`(空库时 data 内 series/rows 为空列表),不抛异常。

- [ ] **Step 3: Commit**

```bash
git add backend/src/api/handler/national_team_handler.py
git commit -m "feat(national-team): add API handlers (signals + holdings endpoints)"
```

---

## Task 7: Router + 注册

**Files:**
- Create: `backend/src/api/router/national_team_router.py`
- Modify: `backend/main.py`(import + `app.include_router`)

**Interfaces:**
- Produces: `/api/v1/national-team/*` 路由。

- [ ] **Step 1: 写 router**

创建 `backend/src/api/router/national_team_router.py`,模仿 `macro_router.py`:

```python
"""国家队板块 API — 每日 ETF 信号 + 历年季报持仓。

GET  /national-team/daily-signals            当日 ETF 护盘信号
GET  /national-team/holdings/summary         总市值趋势(季度×主体)
GET  /national-team/holdings/changes         季度环比变动明细
GET  /national-team/holdings/sector-distribution  行业分布时间序列
GET  /national-team/holdings/top             个股 Top 榜
GET  /national-team/holdings/symbol/{symbol} 单股持仓历史(下钻)
GET  /national-team/coverage                 回填进度
"""
from typing import Optional

from fastapi import APIRouter, Query

from src.api.handler.national_team_handler import (
    coverage,
    daily_signals,
    holdings_changes,
    holdings_sector_distribution,
    holdings_summary,
    holdings_symbol_history,
    holdings_top,
)

router = APIRouter(prefix="/national-team", tags=["national-team"])


@router.get("/daily-signals")
def _daily_signals():
    return daily_signals()


@router.get("/holdings/summary")
def _summary(
    category: Optional[str] = Query(None, description="huijin/zhengjin/safe/social_security"),
    from_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    return holdings_summary(category=category, from_date=from_date)


@router.get("/holdings/changes")
def _changes(
    period: str = Query(..., description="当期 YYYY-MM-DD"),
    vs_period: str = Query(..., description="对比期 YYYY-MM-DD"),
    category: Optional[str] = Query(None),
    change_type: Optional[str] = Query(None, description="new/increase/decrease/exit"),
):
    return holdings_changes(period=period, vs_period=vs_period,
                            category=category, change_type=change_type)


@router.get("/holdings/sector-distribution")
def _sector(from_date: Optional[str] = Query(None)):
    return holdings_sector_distribution(from_date=from_date)


@router.get("/holdings/top")
def _top(
    period: Optional[str] = Query(None),
    limit: int = Query(50),
):
    return holdings_top(period=period, limit=limit)


@router.get("/holdings/symbol/{symbol}")
def _symbol(symbol: str):
    return holdings_symbol_history(symbol=symbol)


@router.get("/coverage")
def _coverage():
    return coverage()
```

- [ ] **Step 2: 在 main.py 注册**

在 `backend/main.py` 顶部 import 区加:

```python
from src.api.router.national_team_router import router as national_team_router
```

在 `create_app()` 的 router 注册段(macro_router 那行之后,`app_logger.info("Routers registered.")` 之前)加:

```python
    app.include_router(national_team_router, prefix="/api/v1")  # /api/v1/national-team
```

- [ ] **Step 3: 启动后端验证路由可达**

Run:
```bash
cd backend && (python main.py &) ; sleep 8 ; curl -s http://localhost:8000/api/v1/national-team/coverage ; curl -s http://localhost:8000/api/v1/national-team/holdings/top ; kill %1 2>/dev/null
```
Expected: 两个 curl 都返回 `{"code":0,"msg":"ok","data":{...}}` JSON(空库 data 内为空)。端口若非 8000,按实际调整。

- [ ] **Step 4: Commit**

```bash
git add backend/src/api/router/national_team_router.py backend/main.py
git commit -m "feat(national-team): add router + register in main"
```

---

## Task 8: 前端菜单 + 路由 + 页面骨架

**Files:**
- Modify: `frontend/apps/web/src/components/Layout.tsx`(O40 财务报表后加菜单项)
- Modify: `frontend/apps/web/src/App.tsx`(import + lazy Route)
- Create: `frontend/apps/web/src/pages/NationalTeam.tsx`(骨架:两 Tab 切换框架)
- Create: `frontend/apps/web/src/pages/NationalTeam.css`

**Interfaces:**
- Produces: `/national-team` 路由可访问,两 Tab 框架可见(内容为占位),后续 Task 9/10 填充。

- [ ] **Step 1: 菜单项**

在 `Layout.tsx` 第 40 行(`{path: '/financial', label: '财务报表', icon: Icon.financial},`)之后插入一行:

```tsx
      {path: '/national-team', label: '国家队', icon: Icon.analytics},
```

> 用 `Icon.analytics` 避免新增图标资源(与 spec 一致:不新增图标)。

- [ ] **Step 2: App.tsx 路由**

在 `App.tsx`:
- 顶部 lazy import 区(与 WriterAssistant 等并列)加:
```tsx
const NationalTeam = React.lazy(() => import('./pages/NationalTeam').then(m => ({default: m.NationalTeam})));
```
- 在 `<Routes>` 内,与其他 `<Route>` 并列(如 macro 路由后)加:
```tsx
          <Route path="/national-team" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><NationalTeam /></Suspense>} />
```

> 若 `Suspense`/`React.lazy` 未在文件顶部引入,补 `import React, {Suspense} from 'react';`(参考 App.tsx 现有 lazy 用法)。

- [ ] **Step 3: 页面骨架 NationalTeam.tsx**

创建 `frontend/apps/web/src/pages/NationalTeam.tsx`:

```tsx
/**
 * NationalTeam page — 国家队动向监控
 *
 * 两个 Tab:
 *   1. 每日动向  — 盘后宽基 ETF 放量+抗跌信号(今天可见)
 *   2. 历年持仓  — 2015 至今季报前十大流通股东快照 + 4 视图对比
 *
 * 口径说明:每日动向是"行为信号",历年持仓是"权威快照(季度颗粒度)"。
 */
import React, {useState} from 'react';
import './NationalTeam.css';

type TabKey = 'daily' | 'holdings';

export const NationalTeam: React.FC = () => {
  const [tab, setTab] = useState<TabKey>('daily');

  return (
    <div className="national-team">
      <div className="national-team__header">
        <h1 className="national-team__title">国家队动向</h1>
        <div className="national-team__subtitle">
          每日 ETF 护盘信号(实时推断) · 历年季报持仓(权威快照,2015 起)
        </div>
      </div>

      <div className="national-team__caveat">
        ⚠ 两套口径互补:「每日动向」是行为信号,不点名国家队,盘后可见;
        「历年持仓」来自季报前十大流通股东,季度颗粒度,有 3-4 周披露滞后。
      </div>

      <div className="national-team__tabs">
        <button
          className={`nt-tab ${tab === 'daily' ? 'nt-tab--active' : ''}`}
          onClick={() => setTab('daily')}
        >每日动向</button>
        <button
          className={`nt-tab ${tab === 'holdings' ? 'nt-tab--active' : ''}`}
          onClick={() => setTab('holdings')}
        >历年持仓</button>
      </div>

      <div className="national-team__body">
        {tab === 'daily' ? (
          <div className="nt-placeholder">[每日动向 — Task 9 填充]</div>
        ) : (
          <div className="nt-placeholder">[历年持仓 — Task 10 填充]</div>
        )}
      </div>
    </div>
  );
};

export default NationalTeam;
```

- [ ] **Step 4: 骨架样式 NationalTeam.css**

创建 `frontend/apps/web/src/pages/NationalTeam.css`(沿用项目 BEM + CSS var 约定,参考 FundFlow.css):

```css
.national-team {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
}
.national-team__header { margin-bottom: 16px; }
.national-team__title { font-size: 28px; font-weight: 600; margin: 0; color: var(--color-text); }
.national-team__subtitle { font-size: var(--text-sm); color: var(--color-text-secondary); margin-top: 4px; }
.national-team__caveat {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  padding: 10px 14px;
  margin-bottom: 16px;
  border-left: 3px solid var(--color-accent);
}
.national-team__tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.nt-tab {
  padding: 8px 16px;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border, rgba(255,255,255,0.08));
  border-radius: var(--radius-lg);
  cursor: pointer;
  font-size: var(--text-sm);
}
.nt-tab--active { color: var(--color-text); border-color: var(--color-accent); }
.nt-placeholder { color: var(--color-text-secondary); padding: 40px 0; text-align: center; }
.page-loading { padding: 40px; color: var(--color-text-secondary); text-align: center; }
```

- [ ] **Step 5: 验证页面可访问**

启动前端,访问 `/national-team`:
Run:
```bash
cd frontend/apps/web && (pnpm dev &) ; sleep 10 ; curl -s http://localhost:3000/national-team -o /dev/null -w "%{http_code}" ; kill %1 2>/dev/null
```
Expected: HTTP 200(页面渲染,两 Tab 可切换,显示占位)。端口按实际 rsbuild 配置调整。

- [ ] **Step 6: Commit**

```bash
git add frontend/apps/web/src/components/Layout.tsx frontend/apps/web/src/App.tsx frontend/apps/web/src/pages/NationalTeam.tsx frontend/apps/web/src/pages/NationalTeam.css
git commit -m "feat(national-team): add menu + route + page skeleton (two-tab)"
```

---

## Task 9: 前端 Tab1 — 每日动向

**Files:**
- Modify: `frontend/apps/web/src/pages/NationalTeam.tsx`(替换 daily 占位为完整组件)
- Modify: `frontend/apps/web/src/pages/NationalTeam.css`(追加 daily 样式)

**Interfaces:**
- Consumes: `GET /api/v1/national-team/daily-signals`。

- [ ] **Step 1: 在 NationalTeam.tsx 顶部加 import + 接口类型**

在文件 import 区加:

```tsx
import {getApiBase} from '../lib/api';

const API_BASE = getApiBase();

interface EtfSignal {
  etf_code: string;
  etf_name: string;
  as_of_date: string;
  vol_ratio: number;
  etf_chg_pct: number;
  index_chg_pct: number;
  defend_flag: boolean;
  strength: 'strong' | 'suspect' | 'none' | 'error';
}
interface DailyData {
  as_of: string;
  summary: {strong: number; suspect: number; none: number; error: number};
  signals: EtfSignal[];
  heatmap_20d: any[];
}
```

- [ ] **Step 2: 加 DailyTab 子组件**

在 `NationalTeam` 组件**之前**定义子组件:

```tsx
const strengthLabel: Record<string, string> = {
  strong: '强护盘', suspect: '疑似护盘', none: '无明显信号', error: '数据异常',
};
const strengthClass = (s: string) =>
  s === 'strong' ? 'signal-strong' : s === 'suspect' ? 'signal-suspect' : 'signal-none';

const DailyTab: React.FC = () => {
  const [data, setData] = useState<DailyData | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    setLoading(true);
    fetch(`${API_BASE}/national-team/daily-signals`)
      .then(r => r.json())
      .then(j => { if (alive) setData(j.data || null); })
      .catch(() => { if (alive) setErr('加载失败'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  if (loading) return <div className="nt-empty">加载中…</div>;
  if (err) return <div className="nt-empty">{err}</div>;
  if (!data) return <div className="nt-empty">暂无数据</div>;

  const sorted = [...data.signals].sort((a, b) => b.vol_ratio - a.vol_ratio);

  return (
    <div className="nt-daily">
      <div className="nt-summary">
        <div className="nt-stat signal-strong">强护盘 {data.summary.strong}</div>
        <div className="nt-stat signal-suspect">疑似护盘 {data.summary.suspect}</div>
        <div className="nt-stat signal-none">无明显信号 {data.summary.none}</div>
        <div className="nt-stat nt-asof">数据时点 {data.as_of || '-'}</div>
      </div>
      <div className="nt-table-wrap">
        <table className="nt-table">
          <thead>
            <tr>
              <th>ETF代码</th><th>名称</th><th>放量倍数</th>
              <th>ETF涨跌%</th><th>指数涨跌%</th><th>抗跌</th><th>信号强度</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(s => (
              <tr key={s.etf_code}>
                <td>{s.etf_code}</td>
                <td>{s.etf_name}</td>
                <td>{s.vol_ratio.toFixed(1)}x</td>
                <td className={s.etf_chg_pct >= 0 ? 'is-up' : 'is-down'}>
                  {s.etf_chg_pct >= 0 ? '+' : ''}{s.etf_chg_pct.toFixed(2)}
                </td>
                <td className={s.index_chg_pct >= 0 ? 'is-up' : 'is-down'}>
                  {s.index_chg_pct >= 0 ? '+' : ''}{s.index_chg_pct.toFixed(2)}
                </td>
                <td>{s.defend_flag ? '✓' : ''}</td>
                <td><span className={`nt-strength ${strengthClass(s.strength)}`}>
                  {strengthLabel[s.strength] || s.strength}
                </span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
```

并把 `NationalTeam` 里的 daily 占位替换为:
```tsx
        {tab === 'daily' ? <DailyTab /> : ( ... )}
```

- [ ] **Step 3: 追加 CSS**

在 `NationalTeam.css` 追加:

```css
.nt-daily {}
.nt-summary { display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; margin-bottom: 16px; }
.nt-stat { background: var(--color-surface); border-radius: var(--radius-lg); padding: 14px; font-size: var(--text-sm); color: var(--color-text-secondary); }
.nt-stat.nt-asof { color: var(--color-text-secondary); }
.nt-table-wrap { background: var(--color-surface); border-radius: var(--radius-lg); overflow: hidden; }
.nt-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
.nt-table th { text-align: left; padding: 10px 12px; color: var(--color-text-secondary); border-bottom: 1px solid var(--color-border, rgba(255,255,255,0.06)); font-weight: 500; }
.nt-table td { padding: 10px 12px; border-bottom: 1px solid var(--color-border, rgba(255,255,255,0.04)); }
.is-up { color: var(--color-up, #e54d4d); }
.is-down { color: var(--color-down, #2eb872); }
.nt-strength { padding: 2px 8px; border-radius: 6px; font-size: 12px; }
.signal-strong { color: #fff; background: rgba(229,77,77,0.8); }
.signal-suspect { color: #fff; background: rgba(229,160,77,0.7); }
.signal-none { color: var(--color-text-secondary); background: var(--color-surface); }
.nt-empty { padding: 40px; color: var(--color-text-secondary); text-align: center; }
```

- [ ] **Step 4: 验证**

启动前后端,访问 `/national-team` 默认 Tab:
- 应看到 4 张统计卡 + ETF 信号表(6 只 ETF)。
- 强制刷新不应每次重算(5 分钟缓存)。

Run(后端已起):
```bash
curl -s http://localhost:8000/api/v1/national-team/daily-signals | python -m json.tool | head -20
```
Expected: JSON 含 `summary` 与 `signals`(6 条)。

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/NationalTeam.tsx frontend/apps/web/src/pages/NationalTeam.css
git commit -m "feat(national-team): build daily-signals tab (summary cards + signal table)"
```

---

## Task 10: 前端 Tab2 — 历年持仓(4 视图)

**Files:**
- Modify: `frontend/apps/web/src/pages/NationalTeam.tsx`(加 HoldingsTab + 4 子视图)
- Modify: `frontend/apps/web/src/pages/NationalTeam.css`(追加 holdings 样式)

**Interfaces:**
- Consumes: `/holdings/summary`、`/holdings/changes`、`/holdings/sector-distribution`、`/holdings/top`、`/holdings/symbol/{symbol}`、`/coverage`。

- [ ] **Step 1: 顶部加 recharts import + 类型**

```tsx
import {LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, ComposedChart, Area, AreaChart, BarChart, Bar} from 'recharts';

const CATEGORY_COLORS: Record<string, string> = {
  huijin: 'var(--color-accent)',
  zhengjin: '#e54d4d',
  safe: '#2eb872',
  social_security: '#e5a04d',
};
const CATEGORY_LABEL: Record<string, string> = {
  huijin: '汇金', zhengjin: '证金', safe: '外管局', social_security: '社保',
};
```

- [ ] **Step 2: HoldingsTab 子组件(4 视图切换 + 主体筛选 + 进度)**

在 `NationalTeam` 之前定义 `HoldingsTab`:

```tsx
const fmtYi = (v: number) => (v / 1e8).toFixed(1);  // 元 → 亿

const HoldingsTab: React.FC = () => {
  const [view, setView] = useState<'trend' | 'changes' | 'sector' | 'top'>('trend');
  const [coverage, setCoverage] = useState<{report_periods: string[]; symbol_count: number; latest_period: string|null} | null>(null);

  React.useEffect(() => {
    fetch(`${API_BASE}/national-team/coverage`)
      .then(r => r.json())
      .then(j => setCoverage(j.data || null))
      .catch(() => setCoverage(null));
  }, []);

  return (
    <div className="nt-holdings">
      {coverage && (
        <div className="nt-coverage">
          数据覆盖:{coverage.report_periods.length} 个报告期 · {coverage.symbol_count} 只股 ·
          最新 {coverage.latest_period || '无'}
          {(coverage.report_periods.length < 40) && (
            <span className="nt-coverage-warn"> (历史回填进行中,展示已覆盖部分)</span>
          )}
        </div>
      )}
      <div className="nt-subtabs">
        <button className={`nt-subtab ${view==='trend'?'nt-subtab--active':''}`} onClick={()=>setView('trend')}>总市值趋势</button>
        <button className={`nt-subtab ${view==='changes'?'nt-subtab--active':''}`} onClick={()=>setView('changes')}>季度变动</button>
        <button className={`nt-subtab ${view==='sector'?'nt-subtab--active':''}`} onClick={()=>setView('sector')}>行业分布</button>
        <button className={`nt-subtab ${view==='top'?'nt-subtab--active':''}`} onClick={()=>setView('top')}>个股Top</button>
      </div>
      {view === 'trend' && <TrendView />}
      {view === 'changes' && <ChangesView />}
      {view === 'sector' && <SectorView />}
      {view === 'top' && <TopView />}
    </div>
  );
};
```

- [ ] **Step 3: TrendView(总市值趋势,堆叠面积)**

```tsx
const TrendView: React.FC = () => {
  const [series, setSeries] = useState<any[]>([]);
  React.useEffect(() => {
    fetch(`${API_BASE}/national-team/holdings/summary?from_date=2015-01-01`)
      .then(r => r.json())
      .then(j => {
        // 透视:report_date → {汇金:x, 证金:y, ...}
        const map: Record<string, any> = {};
        for (const s of (j.data?.series || [])) {
          const d = map[s.report_date] || {report_date: s.report_date};
          d[CATEGORY_LABEL[s.holder_category] || s.holder_category] = fmtYi(s.total_value);
          map[s.report_date] = d;
        }
        setSeries(Object.values(map).sort((a,b)=>a.report_date.localeCompare(b.report_date)));
      });
  }, []);
  const cats = ['汇金','证金','外管局','社保'];
  return (
    <div className="nt-chart-box">
      <div className="nt-chart-title">国家队总持股市值(亿元,按主体堆叠)</div>
      <ResponsiveContainer width="100%" height={360}>
        <ComposedChart data={series}>
          <CartesianGrid stroke="rgba(255,255,255,0.05)" />
          <XAxis dataKey="report_date" stroke="var(--color-text-secondary)" fontSize={11} />
          <YAxis stroke="var(--color-text-secondary)" fontSize={11} />
          <Tooltip contentStyle={{background:'var(--color-surface)',border:'none',borderRadius:8}} />
          {cats.map(c => (
            <Area key={c} type="monotone" dataKey={c} stackId="1"
                  stroke={CATEGORY_COLORS[Object.entries(CATEGORY_LABEL).find(([,v])=>v===c)![0]] || 'var(--color-accent)'}
                  fill={CATEGORY_COLORS[Object.entries(CATEGORY_LABEL).find(([,v])=>v===c)![0]] || 'var(--color-accent)'}
                  fillOpacity={0.4} isAnimationActive={false} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};
```

- [ ] **Step 4: ChangesView(季度环比变动表)**

```tsx
const ChangesView: React.FC = () => {
  const [periods, setPeriods] = useState<string[]>([]);
  const [period, setPeriod] = useState('');
  const [vs, setVs] = useState('');
  const [ctype, setCtype] = useState<string>('');
  const [rows, setRows] = useState<any[]>([]);

  React.useEffect(() => {
    fetch(`${API_BASE}/national-team/coverage`)
      .then(r=>r.json()).then(j=>{
        const ps = (j.data?.report_periods||[]).sort().reverse();
        setPeriods(ps);
        if (ps.length>=2){ setPeriod(ps[0]); setVs(ps[1]); }
      });
  }, []);

  const load = () => {
    if(!period||!vs) return;
    const params = new URLSearchParams({period, vs_period: vs});
    if(ctype) params.set('change_type', ctype);
    fetch(`${API_BASE}/national-team/holdings/changes?${params}`)
      .then(r=>r.json()).then(j=>setRows(j.data?.changes||[]));
  };

  return (
    <div className="nt-changes">
      <div className="nt-filter">
        <select value={period} onChange={e=>setPeriod(e.target.value)}>
          {periods.map(p=><option key={p} value={p}>{p}</option>)}
        </select>
        <span> vs </span>
        <select value={vs} onChange={e=>setVs(e.target.value)}>
          {periods.map(p=><option key={p} value={p}>{p}</option>)}
        </select>
        <select value={ctype} onChange={e=>setCtype(e.target.value)}>
          <option value="">全部类型</option>
          <option value="new">新进</option>
          <option value="increase">增持</option>
          <option value="decrease">减持</option>
          <option value="exit">退出</option>
        </select>
        <button className="nt-btn" onClick={load}>查询</button>
      </div>
      <table className="nt-table">
        <thead><tr><th>股票</th><th>股东</th><th>类别</th><th>本期持股</th><th>变动股数</th><th>类型</th></tr></thead>
        <tbody>
          {rows.map((r,i)=>(
            <tr key={i}>
              <td>{r.company_name}({r.symbol})</td>
              <td>{r.holder_name}</td>
              <td>{CATEGORY_LABEL[r.holder_category]||r.holder_category}</td>
              <td>{r.cur_shares.toLocaleString()}</td>
              <td className={r.change_shares>=0?'is-up':'is-down'}>{r.change_shares>=0?'+':''}{r.change_shares.toLocaleString()}</td>
              <td>{{new:'新进',increase:'增持',decrease:'减持',exit:'退出'}[r.change_type]||r.change_type}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
```

- [ ] **Step 5: SectorView(行业分布堆叠柱)**

```tsx
const SectorView: React.FC = () => {
  const [data, setData] = useState<any[]>([]);
  const [sectors, setSectors] = useState<string[]>([]);
  React.useEffect(()=>{
    fetch(`${API_BASE}/national-team/holdings/sector-distribution?from_date=2015-01-01`)
      .then(r=>r.json()).then(j=>{
        const map: Record<string, any> = {};
        const secs = new Set<string>();
        for (const s of (j.data?.series||[])){
          secs.add(s.sector);
          const d = map[s.report_date]||{report_date:s.report_date};
          d[s.sector] = fmtYi(s.total_value);
          map[s.report_date] = d;
        }
        setSectors([...secs]);
        setData(Object.values(map).sort((a,b)=>a.report_date.localeCompare(b.report_date)));
      });
  },[]);
  const palette = ['var(--color-accent)','#e54d4d','#2eb872','#e5a04d','#5b8def','#a06bd9'];
  return (
    <div className="nt-chart-box">
      <div className="nt-chart-title">行业分布变迁(亿元,按行业堆叠)</div>
      <ResponsiveContainer width="100%" height={360}>
        <BarChart data={data}>
          <CartesianGrid stroke="rgba(255,255,255,0.05)" />
          <XAxis dataKey="report_date" stroke="var(--color-text-secondary)" fontSize={11} />
          <YAxis stroke="var(--color-text-secondary)" fontSize={11} />
          <Tooltip contentStyle={{background:'var(--color-surface)',border:'none',borderRadius:8}} />
          {sectors.map((s,i)=>(
            <Bar key={s} dataKey={s} stackId="1" fill={palette[i%palette.length]} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};
```

- [ ] **Step 6: TopView(Top 榜 + 下钻)**

```tsx
const TopView: React.FC = () => {
  const [rows, setRows] = useState<any[]>([]);
  const [drill, setDrill] = useState<{symbol:string; name:string}|null>(null);
  React.useEffect(()=>{
    fetch(`${API_BASE}/national-team/holdings/top?limit=30`)
      .then(r=>r.json()).then(j=>setRows(j.data?.rows||[]));
  },[]);
  return (
    <div className="nt-top">
      <table className="nt-table">
        <thead><tr><th>#</th><th>股票</th><th>行业</th><th>持股市值(亿)</th><th>国家队成员</th></tr></thead>
        <tbody>
          {rows.map((r,i)=>(
            <tr key={r.symbol} className="nt-clickable" onClick={()=>setDrill({symbol:r.symbol, name:r.company_name})}>
              <td>{i+1}</td>
              <td>{r.company_name}({r.symbol})</td>
              <td>{r.sector}</td>
              <td className="is-up">{fmtYi(r.total_value)}</td>
              <td>{r.holders.map((h:any)=>CATEGORY_LABEL[h.holder_category]||h.holder_category).join('、')}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {drill && <SymbolDrill symbol={drill.symbol} name={drill.name} onClose={()=>setDrill(null)} />}
    </div>
  );
};

const SymbolDrill: React.FC<{symbol:string; name:string; onClose:()=>void}> = ({symbol,name,onClose}) => {
  const [hist, setHist] = useState<any[]>([]);
  React.useEffect(()=>{
    fetch(`${API_BASE}/national-team/holdings/symbol/${symbol}`)
      .then(r=>r.json()).then(j=>{
        // 透视:report_date → 总市值
        const map: Record<string, any> = {};
        for (const h of (j.data?.history||[])){
          map[h.report_date] = {report_date:h.report_date, value: fmtYi((map[h.report_date]?.value||0) + h.hold_value)};
        }
        setHist(Object.values(map).sort((a,b)=>a.report_date.localeCompare(b.report_date)));
      });
  },[symbol]);
  return (
    <div className="nt-modal" onClick={onClose}>
      <div className="nt-modal-box" onClick={e=>e.stopPropagation()}>
        <div className="nt-modal-head">{name}({symbol}) 国家队持仓历史</div>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={hist}>
            <CartesianGrid stroke="rgba(255,255,255,0.05)" />
            <XAxis dataKey="report_date" stroke="var(--color-text-secondary)" fontSize={11} />
            <YAxis stroke="var(--color-text-secondary)" fontSize={11} />
            <Tooltip contentStyle={{background:'var(--color-surface)',border:'none',borderRadius:8}} />
            <Line type="monotone" dataKey="value" stroke="var(--color-accent)" isAnimationActive={false} dot={false} />
          </LineChart>
        </ResponsiveContainer>
        <button className="nt-btn" onClick={onClose}>关闭</button>
      </div>
    </div>
  );
};
```

把 `NationalTeam` 的 holdings 占位替换为 `<HoldingsTab />`。

- [ ] **Step 7: 追加 CSS**

```css
.nt-holdings {}
.nt-coverage { font-size: var(--text-sm); color: var(--color-text-secondary); margin-bottom: 12px; }
.nt-coverage-warn { color: var(--color-accent); }
.nt-subtabs { display:flex; gap:6px; margin-bottom: 12px; flex-wrap: wrap; }
.nt-subtab { padding:6px 12px; background:var(--color-surface); color:var(--color-text-secondary); border:1px solid var(--color-border,rgba(255,255,255,0.08)); border-radius:6px; cursor:pointer; font-size:var(--text-sm); }
.nt-subtab--active { color:var(--color-text); border-color:var(--color-accent); }
.nt-chart-box { background:var(--color-surface); border-radius:var(--radius-lg); padding:16px; }
.nt-chart-title { font-size:var(--text-sm); color:var(--color-text-secondary); margin-bottom:12px; }
.nt-filter { display:flex; gap:8px; align-items:center; margin-bottom:12px; flex-wrap:wrap; }
.nt-filter select { background:var(--color-surface); color:var(--color-text); border:1px solid var(--color-border,rgba(255,255,255,0.08)); border-radius:6px; padding:6px 8px; }
.nt-btn { background:var(--color-accent); color:#fff; border:none; border-radius:6px; padding:6px 14px; cursor:pointer; }
.nt-clickable { cursor:pointer; }
.nt-clickable:hover { background:rgba(255,255,255,0.03); }
.nt-modal { position:fixed; inset:0; background:rgba(0,0,0,0.6); display:flex; align-items:center; justify-content:center; z-index:1000; }
.nt-modal-box { background:var(--color-surface); border-radius:var(--radius-lg); padding:20px; width:560px; max-width:90vw; }
.nt-modal-head { font-size:15px; font-weight:600; margin-bottom:12px; color:var(--color-text); }
```

- [ ] **Step 8: 验证**

- 切到「历年持仓」Tab:4 子视图可切换。
- 趋势图:若已回填数据则显示堆叠面积;空库显示空图(不报错)。
- 季度变动:选两个报告期 + 类型,点查询出表。
- 个股 Top:点行弹出下钻折线。

Run(后端已起,假设已有回填数据):
```bash
curl -s "http://localhost:8000/api/v1/national-team/holdings/summary?from_date=2015-01-01" | python -m json.tool | head
```
Expected: 返回 series(可能为空,需先跑回填)。

- [ ] **Step 9: Commit**

```bash
git add frontend/apps/web/src/pages/NationalTeam.tsx frontend/apps/web/src/pages/NationalTeam.css
git commit -m "feat(national-team): build holdings tab (trend/changes/sector/top + drilldown)"
```

---

## Task 11: 回填定时调度接入 + 联调验收

**Files:**
- Modify: `dev-start.sh` 或项目现有调度配置(确认接入点)

**Goal:** 把回填 job 接入定时调度,跑全量回填,端到端验收。

- [ ] **Step 1: 确认调度接入点**

查看 `dev-start.sh` 与项目是否有 cron / schedule 配置:
Run:
```bash
grep -rn "macro_sync\|backfill\|schedule\|cron\|crontab" dev-start.sh backend/ --include="*.sh" --include="*.yaml" --include="*.yml" --include="*.py" -l 2>/dev/null | head
```
Expected: 找到现有 sync job 的调度方式(如 dev-start.sh 里的后台命令,或独立 schedule 文件)。

- [ ] **Step 2: 接入调度**

按 Step 1 找到的模式,在调度配置里加一行(每日凌晨 2 点跑一批 1000 次调用):
```bash
# 例:若 dev-start.sh 里有后台 sync 任务段
0 2 * * * cd /home/yuandonghao/sidejob/sources/trader/ytrader/backend && python -m src.domain.market.sync.jobs.national_team_backfill --max-calls 1000 >> logs/national_team_backfill.cron.log 2>&1
```
(具体形式依项目现有调度而定;若用 systemd timer / pm2 / 自定义 scheduler,按对应格式)

- [ ] **Step 3: 触发首轮回填(不限批,跑完为止)**

Run(后台,可能数小时):
```bash
cd backend && nohup python -m src.domain.market.sync.jobs.national_team_backfill --max-calls 0 > logs/national_team_backfill.full.log 2>&1 &
echo "PID: $!"
```
监控:
```bash
tail -f backend/logs/national_team_backfill.full.log
```
Expected: 日志持续打印进度,`remaining` 递减;完成后 `national_team_holding` 有数万条数据。

- [ ] **Step 4: 端到端验收清单**

逐项验证:
- [ ] 侧边栏「国家队」菜单在「财务报表」后,点击进入 `/national-team`
- [ ] 默认「每日动向」Tab:4 张卡 + 6 只 ETF 信号表,数据时点为今日
- [ ] 切「历年持仓」Tab:显示覆盖度 + 4 子视图
- [ ] 趋势图:2015→今的总市值堆叠面积,4 主体分层
- [ ] 季度变动:选两期+类型查询出变动明细
- [ ] 行业分布:堆叠柱,见银行/非银等
- [ ] 个股 Top:点行弹出该股持仓历史折线
- [ ] 口径说明折叠条可见

- [ ] **Step 5: 最终 commit**

```bash
git add dev-start.sh  # 或调度配置文件
git commit -m "feat(national-team): wire backfill job to daily schedule + e2e verified"
```

---

## Self-Review(写完计划后自查)

**1. Spec 覆盖** — 逐条核对 spec §1 成功标准:
- ✅ 菜单在财务报表后 → Task 8 Step 1
- ✅ 默认 Tab 每日动向盘后可见 → Task 6 daily_signals + Task 9
- ✅ 历年持仓 4 视图 → Task 10
- ✅ 回溯 2015Q1 + 定时同步 → Task 5 + Task 11
- ✅ 纯 akshare → Global Constraints + Task 4

**2. 类型一致性** — `holder_category` 四值(huijin/zhengjin/safe/social_security)在 config(T1)、matcher(T3)、entity(T2)、handler(T6)、前端 CATEGORY_LABEL(T10)一致。`change_type` 四值(new/increase/decrease/exit)在 repository(T2)、handler(T6)、前端(T10)一致。

**3. 风险已标注** — Task 4 Step 2/4 注明列名以 akshare 实际为准需验证;Task 5 Step 1 注明删除占位循环;Task 11 Step 1 注明调度接入点需确认。
