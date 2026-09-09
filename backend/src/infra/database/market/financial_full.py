"""stock_financial_detail + stock_earnings_forecast 表：akshare 全量财务数据。

两大用途：
  1. stock_financial_detail —— 三大报表（利润/资产负债/现金流）全科目。
     固定列存 ~25 个高频查询指标（营收/净利/货币资金/总资产/经营现金流 …），
     detail JSONB 存全部 195 个明细科目（akshare 列名经常变动，JSONB 不怕加字段）。
     覆盖 A 股（同花顺宽表）/ 港股（东财长表归一化）/ 美股（东财宽表）。
  2. stock_earnings_forecast —— 业绩预告（stock_yjyg_em）+ 业绩快报（stock_yjbb_em）。
     这两个接口是「全市场批量」（按 date 一次拉回数千行），与按 symbol 的三大表模式不同。

与 stock_financials（新浪源，已失效，5 字段）共存：新表替代，旧表保留不影响在用功能。
与 financial_statements（financial_router 的 mock demo 表）无关。

无 Alembic，靠 SQLModel.metadata.create_all 自动建表（与 valuation/macro_indicator 一致）。
JSONB 列用 sa_column=Column(JSON) 声明（与 macro_indicator_meta.reference_lines 一致）。
"""
import json
import math
import threading
import datetime as dt
from datetime import datetime
from typing import Any, Optional

import psycopg2
from psycopg2.extras import Json, execute_values


class _FinJSONEncoder(json.JSONEncoder):
    """财务 JSON 编码器：处理 date/datetime + NaN/Inf → null。

    akshare 返回的 dict 可能含：
      - date/datetime 对象（标准 json 不支持，default=str 兜底）
      - float('nan')/float('inf')（pandas 缺失值，JSONB 解析器拒绝 NaN token）
    """

    def default(self, o):
        if isinstance(o, (dt.date, dt.datetime)):
            return o.isoformat()
        return str(o)

    def iterencode(self, o, **kw):
        # 重写以拦截 float NaN/Inf（在 encode 阶段转 null）
        return super().iterencode(_sanitize_floats(o), **kw)


def _sanitize_floats(obj):
    """递归把 dict/list 中的 NaN/Inf 浮点数替换为 None（JSON null）。"""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_floats(v) for v in obj]
    return obj


def _json_dumps(obj) -> str:
    """JSON 序列化（psycopg2 Json 适配器用）：date→ISO，NaN/Inf→null。"""
    return json.dumps(obj, cls=_FinJSONEncoder, ensure_ascii=False)

# 字段名 `date` 会遮蔽 datetime.date，用模块别名 dt.date 引用类型注解。
from sqlalchemy import JSON, Column, DateTime, func
from sqlmodel import Session, SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection,
    create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn


# ════════════════════════════════════════════════════════════════════════════
#  表 1：stock_financial_detail —— 三大报表全科目（固定列 + JSONB）
# ════════════════════════════════════════════════════════════════════════════

class StockFinancialDetail(SQLModel, table=True):
    """个股三大报表记录（按 symbol + report_date + statement_type）。

    固定列覆盖跨市场通用的高频指标；detail JSONB 存原始全科目。
    statement_type: income(利润表) / balance(资产负债表) / cashflow(现金流量表) /
                    abstract(财务摘要)
    market: A / HK / US
    """

    __tablename__ = "stock_financial_detail"

    symbol: str = Field(primary_key=True)            # sh600519 / 00700 / AAPL
    report_date: dt.date = Field(primary_key=True)   # 报告期（季末/年末）
    statement_type: str = Field(primary_key=True)    # income / balance / cashflow / abstract
    market: str = Field(default="A")                 # A / HK / US

    # ── 利润表核心 ──
    revenue: Optional[float] = None                  # 营业总收入
    operating_cost: Optional[float] = None           # 营业成本
    gross_profit: Optional[float] = None             # 毛利润（营收-营业成本，计算）
    sell_expense: Optional[float] = None             # 销售费用
    admin_expense: Optional[float] = None            # 管理费用
    rd_expense: Optional[float] = None               # 研发费用
    fin_expense: Optional[float] = None              # 财务费用
    operating_profit: Optional[float] = None         # 营业利润
    net_profit: Optional[float] = None               # 净利润
    net_profit_parent: Optional[float] = None        # 归母净利润
    net_profit_deduct: Optional[float] = None        # 扣非净利润
    basic_eps: Optional[float] = None                # 基本每股收益

    # ── 资产负债表核心 ──
    monetary_funds: Optional[float] = None           # 货币资金
    accounts_receivable: Optional[float] = None      # 应收账款
    inventory: Optional[float] = None                # 存货
    fixed_assets: Optional[float] = None             # 固定资产合计
    goodwill: Optional[float] = None                 # 商誉
    total_assets: Optional[float] = None             # 资产合计
    total_liabilities: Optional[float] = None        # 负债合计
    equity: Optional[float] = None                   # 所有者权益合计
    equity_parent: Optional[float] = None            # 归母权益
    short_loan: Optional[float] = None               # 短期借款
    long_loan: Optional[float] = None                # 长期借款

    # ── 现金流量表核心 ──
    ocf: Optional[float] = None                      # 经营活动现金流净额
    icf: Optional[float] = None                      # 投资活动现金流净额
    fcf: Optional[float] = None                      # 筹资活动现金流净额(注:非FCF)
    capex: Optional[float] = None                    # 资本支出(购建固定资产等)
    free_cash_flow: Optional[float] = None           # 自由现金流=ocf-|capex|
    cash_end: Optional[float] = None                 # 期末现金及现金等价物余额

    # ── 派生指标（入库时计算，便于直接查询/排序）──
    gross_margin: Optional[float] = None             # 毛利率 = 毛利/营收
    net_margin: Optional[float] = None               # 净利率 = 净利/营收
    debt_ratio: Optional[float] = None               # 资产负债率 = 负债/总资产

    # ── 完整明细（JSONB，全部原始科目，不怕 akshare 加减列）──
    detail: Any = Field(default=None, sa_column=Column(JSON))

    created_at: Any = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime, server_default=func.now()),
    )


# ── 固定列名 ↔ 三大表原始中文科目名的映射 ──
# akshare 同花顺三大表的列名在不同公司/年份可能略有差异，
# 这里用 get 宽松取值，取不到留 None，不报错。
_INCOME_MAP = {
    "revenue":          ["一、营业总收入", "*营业总收入", "其中：营业收入", "营业收入"],
    "operating_cost":   ["其中：营业成本", "二、营业总成本", "*营业总成本", "营业成本"],
    "sell_expense":     ["销售费用"],
    "admin_expense":    ["管理费用"],
    "rd_expense":       ["研发费用"],
    "fin_expense":      ["财务费用"],
    "operating_profit": ["三、营业利润"],
    "net_profit":       ["五、净利润", "*净利润"],
    "net_profit_parent":["归属于母公司所有者的净利润", "*归属于母公司所有者的净利润"],
    "net_profit_deduct":["扣除非经常性损益后的净利润", "*扣除非经常性损益后的净利润"],
    "basic_eps":        ["（一）基本每股收益", "基本每股收益"],
}

_BALANCE_MAP = {
    "monetary_funds":     ["货币资金"],
    "accounts_receivable":["应收账款"],
    "inventory":          ["存货"],
    "fixed_assets":       ["固定资产合计", "其中：固定资产"],
    "goodwill":           ["商誉"],
    "total_assets":       ["资产合计", "*资产合计"],
    "total_liabilities":  ["负债合计", "*负债合计"],
    "equity":             ["所有者权益（或股东权益）合计", "*所有者权益（或股东权益）合计"],
    "equity_parent":      ["归属于母公司所有者权益合计", "*归属于母公司所有者权益合计"],
    "short_loan":         ["短期借款"],
    "long_loan":          ["长期借款"],
}

_CASHFLOW_MAP = {
    "ocf":      ["经营活动产生的现金流量净额", "*经营活动产生的现金流量净额"],
    "icf":      ["投资活动产生的现金流量净额", "*投资活动产生的现金流量净额"],
    "fcf":      ["筹资活动产生的现金流量净额", "*筹资活动产生的现金流量净额"],
    "capex":    [
        "购建固定资产、无形资产和其他长期资产支付的现金",
        "*购建固定资产、无形资产和其他长期资产支付的现金",
        "购建固定资产、无形资产及其他长期资产支付的现金",
    ],
    "cash_end": ["六、期末现金及现金等价物余额", "*期末现金及现金等价物余额", "期末现金及现金等价物余额"],
}

# 各 statement_type 的映射表，供 pick 使用
_STATEMENT_MAPS = {
    "income":   _INCOME_MAP,
    "balance":  _BALANCE_MAP,
    "cashflow": _CASHFLOW_MAP,
}


# ── 港股专用映射表（东财港股报表科目名，与 A 股不同）──────────────────────
# 港股利润表用"营业额/溢利/开支"，资产负债表用"权益/借贷"；现金流量表是
# "业务净额"三行式（经营/投资/融资业务现金净额），与 A 股"活动"口径名不同。
# 候选名以 2026-08 现场 akshare stock_financial_hk_report_em 实测 STD_ITEM_NAME
# 为准（00700 60 科目验证），旧候选保留兜底。
_HK_INCOME_MAP = {
    "revenue":          ["营业额", "营业收益", "营业收入"],
    "operating_cost":   ["营运支出", "销售成本", "营业成本"],
    "sell_expense":     ["销售及分销费用", "销售及分销成本", "销售费用"],
    "admin_expense":    ["行政开支", "管理费用"],
    "rd_expense":       ["研发开支", "研发费用"],
    "fin_expense":      ["融资成本", "财务费用"],
    "operating_profit": ["经营溢利", "营业利润"],
    "net_profit":       ["除税后溢利", "净利润"],
    "net_profit_parent":["股东应占溢利", "归属于母公司所有者的净利润"],
    "net_profit_deduct":["核心净利润", "扣除非经常性损益后的净利润"],
    "basic_eps":        ["每股基本盈利", "每股盈利", "基本每股收益"],
}

_HK_BALANCE_MAP = {
    "monetary_funds":     ["现金及银行结余", "现金及等价物", "货币资金"],
    "accounts_receivable":["应收帐款", "贸易及其他应收款", "应收账款"],
    "inventory":          ["存货", "库存"],
    "fixed_assets":       ["物业厂房及设备", "固定资产", "物业、厂房及设备",
                           "固定资产合计"],
    "goodwill":           ["商誉"],
    "total_assets":       ["总资产", "资产总额", "资产合计"],
    "total_liabilities":  ["总负债", "负债总额", "负债合计"],
    "equity":             ["总权益", "权益总额", "所有者权益合计"],
    "equity_parent":      ["股东权益", "归属于母公司股东权益",
                           "归属于母公司所有者权益合计"],
    "short_loan":         ["短期贷款", "短期银行借款", "短期借款"],
    "long_loan":          ["长期贷款", "长期银行借款", "长期借款"],
}

_HK_CASHFLOW_MAP = {
    "ocf":      ["经营业务现金净额", "经营活动所得现金流量净额",
                 "经营活动产生的现金流量净额"],
    "icf":      ["投资业务现金净额", "投资活动所得现金流量净额",
                 "投资活动产生的现金流量净额"],
    "fcf":      ["融资业务现金净额", "融资活动所得现金流量净额",
                 "筹资活动产生的现金流量净额"],
    # 港股 capex 只有"购建固定资产"单行（另有"购建无形资产及其他资产"
    # 独立行，pick_metric 不支持求和 → 固定资产口径，偏保守）
    "capex":    ["购建固定资产", "购买物业、厂房及设备",
                 "购建固定资产、无形资产和其他长期资产支付的现金"],
    "cash_end": ["期末现金", "期末现金及现金等价物", "期末现金及现金等价物余额"],
}

_HK_STATEMENT_MAPS = {
    "income":   _HK_INCOME_MAP,
    "balance":  _HK_BALANCE_MAP,
    "cashflow": _HK_CASHFLOW_MAP,
}


def parse_amount(v) -> Optional[float]:
    """财务数值解析：支持中文单位 亿/万（同花顺返回 '547.03亿' 这种字符串）。

    '547.03亿' → 54703000000.0
    '281.54亿' → 28154000000.0
    '3500.25万' → 35002500.0
    '21.38' → 21.38
    '-5.2亿' → -520000000.0
    纯数值/nan/空/None → None。
    """
    if v is None:
        return None
    # 先用 _num 判空（复用它的 nan/空/-- 判断）
    from src.domain.market.sync.providers.akshare_provider import _num
    s = str(v).strip().replace(",", "").replace(" ", "")
    if s in ("", "nan", "NaN", "None", "--", "null"):
        return None
    # 检测末尾中文单位
    mult = 1.0
    if s.endswith("万亿"):
        mult = 1e12
        s = s[:-2]
    elif s.endswith("亿"):
        mult = 1e8
        s = s[:-1]
    elif s.endswith("万"):
        mult = 1e4
        s = s[:-1]
    # 去掉残留百分号
    s = s.rstrip("%")
    try:
        return float(s) * mult
    except (ValueError, TypeError):
        return None


def pick_metric(row: dict, keys: list[str]) -> Optional[float]:
    """从一行 dict（akshare Series 转 dict）中按候选 key 列表宽松取值，转 float。

    多个候选 key 是为兼容 akshare 不同来源/版本的列名差异（带 * 前缀等）。
    用 parse_amount 解析（支持中文单位 亿/万）。
    """
    for k in keys:
        if k in row:
            v = parse_amount(row[k])
            if v is not None:
                return v
    return None


def compute_derived(d: dict) -> None:
    """在已填充核心字段的 dict 上就地计算派生指标（毛利率/净利率/资产负债率）。

    用营收、营业成本算毛利；保护除零。
    """
    revenue = d.get("revenue")
    op_cost = d.get("operating_cost")
    if revenue and op_cost is not None:
        d["gross_profit"] = revenue - op_cost
        d["gross_margin"] = round(d["gross_profit"] / revenue * 100, 4) if revenue else None
    net = d.get("net_profit")
    if net is not None and revenue:
        d["net_margin"] = round(net / revenue * 100, 4)
    liab = d.get("total_liabilities")
    assets = d.get("total_assets")
    if liab is not None and assets:
        d["debt_ratio"] = round(liab / assets * 100, 4)
    # 自由现金流 = 经营现金流 - 资本支出（取绝对值兼容正/负口径）
    ocf = d.get("ocf")
    capex = d.get("capex")
    if isinstance(ocf, (int, float)) and isinstance(capex, (int, float)):
        d["free_cash_flow"] = ocf - abs(capex)


def ensure_stock_financial_detail_columns() -> None:
    """无 Alembic 加列兜底：给 stock_financial_detail 补 capex /
    free_cash_flow 列（仅在缺失时 ADD COLUMN）。"""
    import psycopg2

    from src.infra.database.sql_engine.dsn import get_dsn

    cols = {
        "capex": "DOUBLE PRECISION",
        "free_cash_flow": "DOUBLE PRECISION",
    }
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            for col, typ in cols.items():
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                     WHERE table_name = 'stock_financial_detail'
                       AND column_name = %s
                    """,
                    (col,),
                )
                if cur.fetchone() is None:
                    cur.execute(
                        f"ALTER TABLE stock_financial_detail "
                        f"ADD COLUMN {col} {typ}"
                    )
        conn.commit()
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
#  表 2：stock_earnings_forecast —— 业绩预告 / 业绩快报
# ════════════════════════════════════════════════════════════════════════════

class StockEarningsForecast(SQLModel, table=True):
    """业绩预告 / 业绩快报（全市场批量，按报告期）。

    forecast_type: preannounce(stock_yjyg_em 预告) / express(stock_yjbb_em 快报)
    symbol 存纯 6 位数字代码（与 akshare 返回一致），不带 sh/sz 前缀。
    """

    __tablename__ = "stock_earnings_forecast"

    symbol: str = Field(primary_key=True)            # 纯 6 位 603378
    forecast_type: str = Field(primary_key=True)     # preannounce / express
    report_date: dt.date = Field(primary_key=True)   # 报告期
    metric: str = Field(default="", primary_key=True)# 预测指标（预告用，快报留空）

    company_name: Optional[str] = None               # 股票简称
    announce_date: Optional[dt.date] = None          # 公告日期
    forecast_value: Optional[float] = None           # 预测数值
    change_pct: Optional[float] = None               # 业绩变动幅度 %
    prev_value: Optional[float] = None               # 上年同期值
    forecast_type_label: Optional[str] = None        # 预告类型(预增/预亏/续亏...)

    # ── 快报额外字段（stock_yjbb_em 专有）──
    revenue: Optional[float] = None                  # 营业总收入
    net_profit: Optional[float] = None               # 净利润
    roe: Optional[float] = None                      # 净资产收益率
    eps: Optional[float] = None                      # 每股收益

    raw: Any = Field(default=None, sa_column=Column(JSON))  # 原始行
    created_at: Any = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime, server_default=func.now()),
    )


# ════════════════════════════════════════════════════════════════════════════
#  Repository
# ════════════════════════════════════════════════════════════════════════════

# 固定列清单（供 bulk_upsert 拼 SQL），顺序与 _BULK_VALUES 对齐
_DETAIL_COLUMNS = [
    "symbol", "report_date", "statement_type", "market",
    "revenue", "operating_cost", "gross_profit",
    "sell_expense", "admin_expense", "rd_expense", "fin_expense",
    "operating_profit", "net_profit", "net_profit_parent", "net_profit_deduct",
    "basic_eps",
    "monetary_funds", "accounts_receivable", "inventory", "fixed_assets",
    "goodwill", "total_assets", "total_liabilities", "equity", "equity_parent",
    "short_loan", "long_loan",
    "ocf", "icf", "fcf", "cash_end", "capex", "free_cash_flow",
    "gross_margin", "net_margin", "debt_ratio",
    "detail",
]

_FORECAST_COLUMNS = [
    "symbol", "forecast_type", "report_date", "metric",
    "company_name", "announce_date", "forecast_value", "change_pct",
    "prev_value", "forecast_type_label",
    "revenue", "net_profit", "roe", "eps",
    "raw",
]


class FinancialDetailRepository:
    """stock_financial_detail 数据访问（守 SQLModel ORM 规范）。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def get_latest_report_date(
        self, symbol: str, statement_type: str
    ) -> Optional[dt.date]:
        """返回指定个股某报表类型的最新报告期；无数据为 None。"""
        with self._db.session_scope() as s:
            row = s.exec(
                select(StockFinancialDetail)
                .where(
                    StockFinancialDetail.symbol == symbol,
                    StockFinancialDetail.statement_type == statement_type,
                )
                .order_by(StockFinancialDetail.report_date.desc())
            ).first()
            return row.report_date if row else None

    def get_history(
        self, symbol: str, statement_type: str,
        start: Optional[dt.date] = None,
        end: Optional[dt.date] = None,
        limit: int = 200,
    ) -> list[StockFinancialDetail]:
        """返回某 symbol 某报表的报告期序列（升序），可选区间。默认上限 200 期。"""
        limit = max(1, min(int(limit), 500))
        with self._db.session_scope() as s:
            stmt = select(StockFinancialDetail).where(
                StockFinancialDetail.symbol == symbol,
                StockFinancialDetail.statement_type == statement_type,
            )
            if start is not None:
                stmt = stmt.where(StockFinancialDetail.report_date >= start)
            if end is not None:
                stmt = stmt.where(StockFinancialDetail.report_date <= end)
            stmt = stmt.order_by(StockFinancialDetail.report_date.asc()).limit(limit)
            # 在 session 内 expunge，使对象可安全在 session 外使用
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    def bulk_upsert(self, rows: list[dict]) -> int:
        """批量插入/更新（一次 SQL，ON CONFLICT 覆盖）。

        Args:
            rows: 每条 dict 需含 symbol, report_date, statement_type；
                  其余固定列 + detail(JSONB) 可选。
        Returns:
            写入行数
        """
        if not rows:
            return 0
        col_list = ", ".join(_DETAIL_COLUMNS)
        placeholders = ", ".join(["%s"] * len(_DETAIL_COLUMNS))
        # detail 列用 psycopg2.extras.Json 适配器序列化 JSONB
        update_set = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in _DETAIL_COLUMNS if c not in
            ("symbol", "report_date", "statement_type")
        )
        sql = (
            f"INSERT INTO stock_financial_detail ({col_list}) "
            f"VALUES %s "
            f"ON CONFLICT (symbol, report_date, statement_type) DO UPDATE SET {update_set}"
        )
        values = []
        for r in rows:
            rd = r.get("report_date")
            if hasattr(rd, "date"):
                rd = rd.date()
            elif isinstance(rd, str):
                rd = dt.date.fromisoformat(rd[:10])
            row_vals = []
            for c in _DETAIL_COLUMNS:
                if c == "report_date":
                    row_vals.append(rd)
                elif c == "detail":
                    # JSONB 用 Json 适配器；None 也允许
                    detail = r.get("detail")
                    row_vals.append(Json(detail, dumps=_json_dumps) if detail is not None else None)
                else:
                    row_vals.append(r.get(c))
            values.append(tuple(row_vals))
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)


class EarningsForecastRepository:
    """stock_earnings_forecast 数据访问。"""

    def __init__(self, db: DBConnection):
        self._db = db

    def get_latest_report_date(
        self, symbol: str, forecast_type: str
    ) -> Optional[dt.date]:
        with self._db.session_scope() as s:
            row = s.exec(
                select(StockEarningsForecast)
                .where(
                    StockEarningsForecast.symbol == symbol,
                    StockEarningsForecast.forecast_type == forecast_type,
                )
                .order_by(StockEarningsForecast.report_date.desc())
            ).first()
            return row.report_date if row else None

    def get_by_report_date(
        self,
        report_date: Optional[dt.date] = None,
        forecast_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[StockEarningsForecast]:
        """按报告期查业绩预告/快报（全市场，可筛选类型）。

        report_date 为空时取最新报告期。按公告日期降序，便于看最新公告。
        """
        with self._db.session_scope() as s:
            stmt = select(StockEarningsForecast)
            if report_date is not None:
                stmt = stmt.where(StockEarningsForecast.report_date == report_date)
            if forecast_type is not None:
                stmt = stmt.where(StockEarningsForecast.forecast_type == forecast_type)
            if report_date is None:
                # 无指定报告期时，先取最新报告期
                latest_row = s.exec(
                    select(StockEarningsForecast.report_date)
                    .order_by(StockEarningsForecast.report_date.desc())
                ).first()
                if latest_row:
                    stmt = stmt.where(StockEarningsForecast.report_date == latest_row)
            stmt = stmt.order_by(
                StockEarningsForecast.announce_date.desc().nullslast()
            ).limit(limit)
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    def get_by_announce_date_range(
        self,
        start: dt.date,
        end: dt.date,
        forecast_type: Optional[str] = None,
        limit: int = 20000,
    ) -> list[StockEarningsForecast]:
        """按公告日期窗口查询(财报季雷达:拉当前预告窗内全部披露)。"""
        with self._db.session_scope() as s:
            stmt = select(StockEarningsForecast).where(
                StockEarningsForecast.announce_date >= start,
                StockEarningsForecast.announce_date <= end,
            )
            if forecast_type is not None:
                stmt = stmt.where(
                    StockEarningsForecast.forecast_type == forecast_type
                )
            stmt = stmt.order_by(
                StockEarningsForecast.change_pct.desc().nullslast()
            ).limit(limit)
            rows = list(s.exec(stmt).all())
            for r in rows:
                s.expunge(r)
            return rows

    # 正式窗候选:上年同季净利绝对额门槛(元),剔除低基数(上年几十万)导致的天文百分比
    _MIN_PREV_PROFIT = 10_000_000

    def get_quarter_yoy_growth(
        self, report_date: dt.date, min_pct: float,
    ) -> list[dict]:
        """正式报表窗候选:单季归母净利同比 ≥ min_pct(PG 专用)。

        Q1: 单季=Q1累计,直接比两年 Q1 累计;
        Q2-Q4: 单季=当期累计-上期累计,去年同单季同法差分。
        stock_financial_detail: statement_type='income', market='A'。
        """
        import psycopg2 as _pg
        from psycopg2.extras import RealDictCursor

        prev_month = {6: 3, 9: 6, 12: 9}
        if report_date.month == 3:
            sql = """
            SELECT c.symbol, c.np AS q_np, l.np AS q_np_prev
            FROM (
                SELECT symbol, SUM(net_profit_parent) AS np
                FROM stock_financial_detail
                WHERE report_date = %(rd)s
                  AND statement_type='income' AND market='A'
                GROUP BY symbol
            ) c JOIN (
                SELECT symbol, SUM(net_profit_parent) AS np
                FROM stock_financial_detail
                WHERE report_date = %(rd_ly)s
                  AND statement_type='income' AND market='A'
                GROUP BY symbol
            ) l USING (symbol)
            WHERE l.np >= %(min_prev)s AND c.np >= %(min_ratio)s * l.np
            """
            params = {
                "rd": report_date,
                "rd_ly": report_date.replace(year=report_date.year - 1),
                "min_ratio": 1 + min_pct / 100.0,
                "min_prev": self._MIN_PREV_PROFIT,
            }
        else:
            pm = prev_month[report_date.month]
            pq = dt.date(report_date.year, pm + 1, 1) - dt.timedelta(days=1)
            sql = """
            SELECT c.symbol, c.acc_rd - c.acc_prev AS q_np,
                   l.acc_rd_ly - l.acc_prev_ly AS q_np_prev
            FROM (
                SELECT symbol,
                       SUM(net_profit_parent) FILTER (WHERE report_date = %(rd)s) AS acc_rd,
                       SUM(net_profit_parent) FILTER (WHERE report_date = %(prev_rd)s) AS acc_prev
                FROM stock_financial_detail
                WHERE report_date IN (%(rd)s, %(prev_rd)s)
                  AND statement_type='income' AND market='A'
                GROUP BY symbol
            ) c JOIN (
                SELECT symbol,
                       SUM(net_profit_parent) FILTER (WHERE report_date = %(rd_ly)s) AS acc_rd_ly,
                       SUM(net_profit_parent) FILTER (WHERE report_date = %(prev_rd_ly)s) AS acc_prev_ly
                FROM stock_financial_detail
                WHERE report_date IN (%(rd_ly)s, %(prev_rd_ly)s)
                  AND statement_type='income' AND market='A'
                GROUP BY symbol
            ) l USING (symbol)
            WHERE c.acc_prev > 0 AND l.acc_prev_ly > 0
              AND l.acc_rd_ly - l.acc_prev_ly >= %(min_prev)s
              AND (c.acc_rd - c.acc_prev) >= %(min_ratio)s * (l.acc_rd_ly - l.acc_prev_ly)
            """
            params = {
                "rd": report_date, "prev_rd": pq,
                "rd_ly": report_date.replace(year=report_date.year - 1),
                "prev_rd_ly": pq.replace(year=pq.year - 1),
                "min_ratio": 1 + min_pct / 100.0,
                "min_prev": self._MIN_PREV_PROFIT,
            }
        conn = _pg.connect(get_dsn())
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
        for r in rows:
            q_np, q_prev = float(r["q_np"]), float(r["q_np_prev"])
            r["yoy_pct"] = round((q_np - q_prev) / abs(q_prev) * 100, 2)
            r["report_date"] = report_date
        return rows

    def bulk_upsert(self, rows: list[dict]) -> int:
        """批量插入/更新业绩预告/快报（ON CONFLICT 覆盖）。"""
        if not rows:
            return 0
        col_list = ", ".join(_FORECAST_COLUMNS)
        update_set = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in _FORECAST_COLUMNS if c not in
            ("symbol", "forecast_type", "report_date", "metric")
        )
        sql = (
            f"INSERT INTO stock_earnings_forecast ({col_list}) "
            f"VALUES %s "
            f"ON CONFLICT (symbol, forecast_type, report_date, metric) "
            f"DO UPDATE SET {update_set}"
        )
        values = []
        for r in rows:
            rd = r.get("report_date")
            if hasattr(rd, "date"):
                rd = rd.date()
            elif isinstance(rd, str):
                rd = dt.date.fromisoformat(rd[:10])
            ad = r.get("announce_date")
            if hasattr(ad, "date"):
                ad = ad.date()
            elif isinstance(ad, str) and ad:
                ad = dt.date.fromisoformat(ad[:10])
            row_vals = []
            for c in _FORECAST_COLUMNS:
                if c == "report_date":
                    row_vals.append(rd)
                elif c == "announce_date":
                    row_vals.append(ad)
                elif c == "raw":
                    raw = r.get("raw")
                    row_vals.append(Json(raw, dumps=_json_dumps) if raw is not None else None)
                else:
                    row_vals.append(r.get(c))
            values.append(tuple(row_vals))
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)


# ════════════════════════════════════════════════════════════════════════════
#  工厂函数（遵循 index_ohlcv / valuation 单例 + 工厂约定）
# ════════════════════════════════════════════════════════════════════════════

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_financial_detail_repository(
    db_connection: DBConnection | None = None,
) -> FinancialDetailRepository:
    """创建三大报表仓储实例。"""
    return FinancialDetailRepository(db_connection or _get_db_connection())


def create_earnings_forecast_repository(
    db_connection: DBConnection | None = None,
) -> EarningsForecastRepository:
    """创建业绩预告/快报仓储实例。"""
    return EarningsForecastRepository(db_connection or _get_db_connection())
