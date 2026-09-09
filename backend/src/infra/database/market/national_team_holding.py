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
from sqlalchemy import func, BigInteger, Column

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
    hold_shares: int = Field(default=0, sa_column=Column(BigInteger))        # 持股数(可超 int32,如汇金持工行 1240 亿股)
    hold_value: float = Field(default=0.0)     # 持股市值(元)
    pct_of_float: float = Field(default=0.0)   # 占流通股比例 %
    ranking: int = Field(default=0)            # 第几大流通股东
    is_new: Optional[bool] = Field(default=None)          # 本期是否新进
    change_shares: Optional[int] = Field(default=None, sa_column=Column(BigInteger))    # 本期变动股数
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
        categories: Optional[list[str]] = None,
    ) -> list[dict]:
        """按 report_date × holder_category 聚合持股市值(画总市值趋势用)。
        返回 [{report_date, holder_category, total_value, total_count}]。

        过滤:category(单个,向后兼容)或 categories(多选,任一命中)。
        同时传时以 categories 为准。"""
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
            cats = categories if categories else ([category] if category else None)
            if cats:
                stmt = stmt.where(NationalTeamHolding.holder_category.in_(cats))
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
        categories: Optional[list[str]] = None,
    ) -> list[dict]:
        """对比两个报告期,返回 [(symbol, holder_name, ...)] 的变动明细。
        change_type: new/increase/decrease/exit(None=全部)。
        逻辑:对同一 (symbol, holder_name) 比对两期 hold_shares。

        过滤:category(单个,向后兼容)或 categories(多选,任一命中)。
        同时传时以 categories 为准。"""
        with self._db.session_scope() as s:
            base_q = select(NationalTeamHolding)
            cats = categories if categories else ([category] if category else None)
            if cats:
                base_q = base_q.where(NationalTeamHolding.holder_category.in_(cats))

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

    def get_sector_flow(self) -> dict:
        """行业资金流向原始数据:按 (report_date, sector) 聚合持股数 + 市值。
        前端据此算环比增减/占比/排行。用持股数(shares)做增减口径,剔除股价波动。
        返回 {quarters:[...], sectors:[...], series:[{report_date, sector, shares, value}]}。"""
        with self._db.session_scope() as s:
            rows = s.exec(
                select(
                    NationalTeamHolding.report_date,
                    NationalTeamSymbolSector.sector,
                    func.sum(NationalTeamHolding.hold_shares).label("shares"),
                    func.sum(NationalTeamHolding.hold_value).label("value"),
                )
                .join(
                    NationalTeamSymbolSector,
                    NationalTeamHolding.symbol == NationalTeamSymbolSector.symbol,
                )
                .where(NationalTeamSymbolSector.sector != "")  # 排除"未知"
                .group_by(
                    NationalTeamHolding.report_date,
                    NationalTeamSymbolSector.sector,
                )
                .order_by(NationalTeamHolding.report_date)
            ).all()
            quarters_set: list[str] = []
            sectors_set: list[str] = []
            series = []
            for r in rows:
                rd = r.report_date.isoformat() if r.report_date else None
                sec = r.sector
                if rd and rd not in quarters_set:
                    quarters_set.append(rd)
                if sec and sec not in sectors_set:
                    sectors_set.append(sec)
                series.append({
                    "report_date": rd,
                    "sector": sec,
                    "shares": int(r.shares or 0),
                    "value": float(r.value or 0),
                })
            return {"quarters": quarters_set, "sectors": sectors_set, "series": series}

    def get_sector_stocks(
        self, sector: str, period: Optional[dt.date] = None,
    ) -> list[dict]:
        """某行业在某报告期的国家队持仓个股(按 symbol 聚合,降序),含环比加/减仓。
        period=None 取最新报告期。返回 [{symbol, company_name, report_date,
        total_value, total_shares, delta_shares, delta_pct, is_new, holders:[...]}]。"""
        with self._db.session_scope() as s:
            if period is None:
                latest = s.exec(
                    select(func.max(NationalTeamHolding.report_date))
                ).one()
                if latest is None:
                    return []
                period = latest
            # 上一个报告期(最近一个 < period)
            prev_period = s.exec(
                select(func.max(NationalTeamHolding.report_date)).where(
                    NationalTeamHolding.report_date < period
                )
            ).one()
            rows = s.exec(
                select(NationalTeamHolding)
                .join(
                    NationalTeamSymbolSector,
                    NationalTeamHolding.symbol == NationalTeamSymbolSector.symbol,
                )
                .where(
                    NationalTeamHolding.report_date == period,
                    NationalTeamSymbolSector.sector == sector,
                )
            ).all()
            # 上期同行业的 symbol → 总持股数(用于算环比)
            prev_shares_by_symbol: dict[str, int] = {}
            if prev_period is not None:
                prev_rows = s.exec(
                    select(NationalTeamHolding)
                    .join(
                        NationalTeamSymbolSector,
                        NationalTeamHolding.symbol == NationalTeamSymbolSector.symbol,
                    )
                    .where(
                        NationalTeamHolding.report_date == prev_period,
                        NationalTeamSymbolSector.sector == sector,
                    )
                ).all()
                for r in prev_rows:
                    prev_shares_by_symbol[r.symbol] = (
                        prev_shares_by_symbol.get(r.symbol, 0) + int(r.hold_shares or 0)
                    )
            by_symbol: dict[str, dict] = {}
            for r in rows:
                d = by_symbol.setdefault(r.symbol, {
                    "symbol": r.symbol, "company_name": r.company_name,
                    "report_date": period.isoformat() if isinstance(period, dt.date) else period,
                    "total_value": 0.0, "total_shares": 0, "holders": [],
                })
                d["total_value"] += float(r.hold_value or 0)
                d["total_shares"] += int(r.hold_shares or 0)
                d["holders"].append({
                    "holder_name": r.holder_name, "holder_category": r.holder_category,
                    "hold_value": float(r.hold_value or 0),
                    "hold_shares": int(r.hold_shares or 0),
                    "pct_of_float": float(r.pct_of_float or 0),
                })
            for d in by_symbol.values():
                d["holders"].sort(key=lambda h: h["hold_value"], reverse=True)
                # 环比变动(持股数口径)
                prev = prev_shares_by_symbol.get(d["symbol"], 0)
                if prev > 0:
                    d["delta_shares"] = d["total_shares"] - prev
                    d["delta_pct"] = round((d["total_shares"] - prev) / prev * 100, 1)
                    d["is_new"] = False
                else:
                    d["delta_shares"] = d["total_shares"]
                    d["delta_pct"] = None
                    d["is_new"] = True
            return sorted(by_symbol.values(), key=lambda x: x["total_value"], reverse=True)

    def get_top_holdings(
        self, period: Optional[dt.date] = None, limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """按报告期 × symbol 聚合持仓市值,降序取 Top。period=None 取最新报告期。
        offset/limit 分页。返回 [{symbol, company_name, sector, total_value, holders: [...]}]。"""
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
                            key=lambda x: x["total_value"], reverse=True)
            total = len(ranked)
            ranked = ranked[offset:offset + limit]
            # 给每条加 total(该季度国家队持仓个股总数),供前端分页判断"加载更多"
            for d in ranked:
                d["_total"] = total
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

    def search_symbols(self, q: str, limit: int = 20) -> list[dict]:
        """按代码或名称模糊搜索国家队持仓个股(去重)。返回最新报告期的市值用于排序。
        q: 关键词(代码或名称片段)。返回 [{symbol, company_name, latest_value, latest_period}]。"""
        q = (q or "").strip()
        if not q:
            return []
        with self._db.session_scope() as s:
            from sqlalchemy import or_
            # 每只股最新报告期的聚合市值(子查询)
            latest = (
                select(
                    NationalTeamHolding.symbol,
                    func.max(NationalTeamHolding.report_date).label("max_date"),
                )
                .group_by(NationalTeamHolding.symbol)
            ).subquery()
            rows = s.exec(
                select(
                    NationalTeamHolding.symbol,
                    NationalTeamHolding.company_name,
                    NationalTeamHolding.report_date,
                    NationalTeamHolding.hold_value,
                )
                .join(
                    latest,
                    (NationalTeamHolding.symbol == latest.c.symbol)
                    & (NationalTeamHolding.report_date == latest.c.max_date),
                )
                .where(
                    or_(
                        NationalTeamHolding.symbol.contains(q),
                        NationalTeamHolding.company_name.contains(q),
                    )
                )
            ).all()
            # 同一 symbol 可能多个 holder,聚合市值
            agg: dict[str, dict] = {}
            for r in rows:
                d = agg.setdefault(r[0], {"symbol": r[0], "company_name": r[1] or "",
                                          "latest_value": 0.0, "latest_period": r[2].isoformat() if r[2] else None})
                d["latest_value"] += float(r[3] or 0)
            out = sorted(agg.values(), key=lambda x: x["latest_value"], reverse=True)[:limit]
            return out


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


def ensure_national_team_bigint_columns() -> None:
    """把 hold_shares / change_shares 从 INTEGER(32位) 升级为 BIGINT(64位),
    并补关键查询索引。

    国家队持股数可超 int32 上限(如汇金持工行 1240 亿股)。SQLModel.metadata.create_all
    不会改已存在表的列类型/加索引,故用 ALTER TABLE / CREATE INDEX 幂等迁移。
    在 app 启动 / 回填前调用。
    """
    from sqlalchemy import text
    db = _get_db_connection()
    with db.session_scope() as s:
        s.exec(text("ALTER TABLE national_team_holding ALTER COLUMN hold_shares TYPE BIGINT"))
        s.exec(text("ALTER TABLE national_team_holding ALTER COLUMN change_shares TYPE BIGINT"))
        # 查询热路径索引:get_symbol_history(WHERE symbol)、
        # get_summary_series/get_changes(WHERE report_date)、
        # 联合(报告期+主体)聚合
        s.exec(text("CREATE INDEX IF NOT EXISTS idx_nth_symbol ON national_team_holding (symbol)"))
        s.exec(text("CREATE INDEX IF NOT EXISTS idx_nth_report_date ON national_team_holding (report_date)"))
        s.exec(text("CREATE INDEX IF NOT EXISTS idx_nth_date_cat ON national_team_holding (report_date, holder_category)"))


# 模块导入时自动迁移(幂等;表不存在时 create_all 先建表,此处的 ALTER 会失败但无害,
# 由下面的 try 兜住;实际生产应在 app startup 显式调用)。
try:
    ensure_national_team_bigint_columns()
except Exception:
    pass
