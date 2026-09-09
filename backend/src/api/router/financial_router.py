"""
Financial Data API Router
=========================
Provides financial statement analysis (income statement, balance sheet, cash flow)
for A-share stocks from TimescaleDB via financial_detail_handler (real data).
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
import threading
import psycopg2
from psycopg2.extras import RealDictCursor
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.infra.database.sql_engine.dsn import get_dsn
from src.pkg.responses import success

router = APIRouter(prefix="/financial", tags=["financial"])


# ── DB helpers ──────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(get_dsn())


def init_tables():
    """Create financial tables if they don't exist and seed sample data."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS financial_statements (
                    id SERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    company_name TEXT,
                    report_type TEXT NOT NULL,
                    fiscal_year INTEGER NOT NULL,
                    fiscal_quarter INTEGER DEFAULT 4,
                    revenue REAL,
                    gross_profit REAL,
                    operating_income REAL,
                    net_income REAL,
                    eps REAL,
                    total_assets REAL,
                    total_liabilities REAL,
                    equity REAL,
                    current_assets REAL,
                    current_liabilities REAL,
                    operating_cf REAL,
                    investing_cf REAL,
                    financing_cf REAL,
                    free_cash_flow REAL,
                    roe REAL,
                    debt_to_equity REAL,
                    current_ratio REAL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(symbol, report_type, fiscal_year, fiscal_quarter)
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS shareholder_info (
                    id SERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    holder_name TEXT NOT NULL,
                    holder_type TEXT NOT NULL,
                    shares_held REAL,
                    shares_pct REAL,
                    change_pct REAL,
                    ranking INTEGER,
                    as_of_date DATE,
                    UNIQUE(symbol, holder_name, as_of_date)
                );
            """)
        conn.commit()
    finally:
        conn.close()


def seed_data():
    """Seed realistic A-share financial data for sample companies."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Check if data already exists
            cur.execute("SELECT COUNT(*) FROM financial_statements")
            if cur.fetchone()[0] > 0:
                return  # already seeded

            companies = [
                {
                    "symbol": "sh600000", "name": "浦发银行",
                    # Annual 2023 data (Q4=annual)
                    "income_2023": {
                        "revenue": 1900e8, "gross_profit": 1520e8,
                        "operating_income": 580e8, "net_income": 540e8, "eps": 1.82
                    },
                    "balance_2023": {
                        "total_assets": 9.0e12, "total_liabilities": 8.2e12,
                        "equity": 0.8e12, "current_assets": 2.5e12, "current_liabilities": 4.0e12
                    },
                    "cashflow_2023": {
                        "operating_cf": 1200e8, "investing_cf": -300e8,
                        "financing_cf": -500e8, "free_cash_flow": 900e8
                    },
                    "ratios_2023": {"roe": 12.5, "debt_to_equity": 10.25, "current_ratio": 0.625}
                },
                {
                    "symbol": "sh600036", "name": "招商银行",
                    "income_2023": {
                        "revenue": 3200e8, "gross_profit": 2560e8,
                        "operating_income": 1600e8, "net_income": 1400e8, "eps": 5.58
                    },
                    "balance_2023": {
                        "total_assets": 10.5e12, "total_liabilities": 9.5e12,
                        "equity": 1.0e12, "current_assets": 3.2e12, "current_liabilities": 5.0e12
                    },
                    "cashflow_2023": {
                        "operating_cf": 2200e8, "investing_cf": -400e8,
                        "financing_cf": -800e8, "free_cash_flow": 1800e8
                    },
                    "ratios_2023": {"roe": 16.5, "debt_to_equity": 9.5, "current_ratio": 0.64}
                },
                {
                    "symbol": "sh600519", "name": "贵州茅台",
                    "income_2023": {
                        "revenue": 1500e8, "gross_profit": 1200e8,
                        "operating_income": 900e8, "net_income": 750e8, "eps": 59.0
                    },
                    "balance_2023": {
                        "total_assets": 2500e8, "total_liabilities": 500e8,
                        "equity": 2000e8, "current_assets": 1800e8, "current_liabilities": 300e8
                    },
                    "cashflow_2023": {
                        "operating_cf": 800e8, "investing_cf": -100e8,
                        "financing_cf": -700e8, "free_cash_flow": 700e8
                    },
                    "ratios_2023": {"roe": 30.0, "debt_to_equity": 0.25, "current_ratio": 6.0}
                },
                {
                    "symbol": "sh600016", "name": "民生银行",
                    "income_2023": {
                        "revenue": 1700e8, "gross_profit": 1360e8,
                        "operating_income": 480e8, "net_income": 350e8, "eps": 0.95
                    },
                    "balance_2023": {
                        "total_assets": 7.2e12, "total_liabilities": 6.7e12,
                        "equity": 0.5e12, "current_assets": 2.0e12, "current_liabilities": 3.5e12
                    },
                    "cashflow_2023": {
                        "operating_cf": 900e8, "investing_cf": -200e8,
                        "financing_cf": -400e8, "free_cash_flow": 700e8
                    },
                    "ratios_2023": {"roe": 8.5, "debt_to_equity": 13.4, "current_ratio": 0.57}
                },
                {
                    "symbol": "sh601318", "name": "中国平安",
                    "income_2023": {
                        "revenue": 9100e8, "gross_profit": 7280e8,
                        "operating_income": 1400e8, "net_income": 850e8, "eps": 4.90
                    },
                    "balance_2023": {
                        "total_assets": 11.4e12, "total_liabilities": 10.2e12,
                        "equity": 1.2e12, "current_assets": 2.8e12, "current_liabilities": 4.5e12
                    },
                    "cashflow_2023": {
                        "operating_cf": 1800e8, "investing_cf": -600e8,
                        "financing_cf": -900e8, "free_cash_flow": 1200e8
                    },
                    "ratios_2023": {"roe": 11.2, "debt_to_equity": 8.5, "current_ratio": 0.62}
                },
            ]

            # Generate 8 quarters of data (Q4 2021 through Q4 2023 = 8 quarters)
            years_quarters = [
                (2021, 4), (2022, 1), (2022, 2), (2022, 3), (2022, 4),
                (2023, 1), (2023, 2), (2023, 3), (2023, 4)
            ]

            for c in companies:
                for i, (year, q) in enumerate(years_quarters):
                    # Growth factor for quarterly data
                    if year == 2021 and q == 4:
                        growth = 1.0
                    else:
                        growth = 1.0 + 0.03 * i + 0.005 * (i % 3)

                    inc = c["income_2023"]
                    bal = c["balance_2023"]
                    cf = c["cashflow_2023"]
                    rat = c["ratios_2023"]

                    # Quarterly income
                    cur.execute("""
                        INSERT INTO financial_statements
                        (symbol, company_name, report_type, fiscal_year, fiscal_quarter,
                         revenue, gross_profit, operating_income, net_income, eps,
                         total_assets, total_liabilities, equity, current_assets, current_liabilities,
                         operating_cf, investing_cf, financing_cf, free_cash_flow,
                         roe, debt_to_equity, current_ratio)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (symbol, report_type, fiscal_year, fiscal_quarter) DO NOTHING
                    """, (
                        c["symbol"], c["name"], "income_statement", year, q,
                        inc["revenue"] * growth / 4, inc["gross_profit"] * growth / 4,
                        inc["operating_income"] * growth / 4, inc["net_income"] * growth / 4,
                        inc["eps"] * growth / 4,
                        bal["total_assets"] * growth, bal["total_liabilities"] * growth,
                        bal["equity"] * growth, bal["current_assets"] * growth,
                        bal["current_liabilities"] * growth,
                        cf["operating_cf"] * growth / 4, cf["investing_cf"] * growth / 4,
                        cf["financing_cf"] * growth / 4, cf["free_cash_flow"] * growth / 4,
                        rat["roe"], rat["debt_to_equity"], rat["current_ratio"]
                    ))

                    # Balance sheet only for annual (Q4)
                    if q == 4:
                        cur.execute("""
                            INSERT INTO financial_statements
                            (symbol, company_name, report_type, fiscal_year, fiscal_quarter,
                             revenue, gross_profit, operating_income, net_income, eps,
                             total_assets, total_liabilities, equity, current_assets, current_liabilities,
                             operating_cf, investing_cf, financing_cf, free_cash_flow,
                             roe, debt_to_equity, current_ratio)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (symbol, report_type, fiscal_year, fiscal_quarter) DO NOTHING
                        """, (
                            c["symbol"], c["name"], "balance_sheet", year, q,
                            None, None, None, None, None,
                            bal["total_assets"] * growth, bal["total_liabilities"] * growth,
                            bal["equity"] * growth, bal["current_assets"] * growth,
                            bal["current_liabilities"] * growth,
                            None, None, None, None,
                            rat["roe"], rat["debt_to_equity"], rat["current_ratio"]
                        ))

                        # Cash flow only for annual
                        cur.execute("""
                            INSERT INTO financial_statements
                            (symbol, company_name, report_type, fiscal_year, fiscal_quarter,
                             revenue, gross_profit, operating_income, net_income, eps,
                             total_assets, total_liabilities, equity, current_assets, current_liabilities,
                             operating_cf, investing_cf, financing_cf, free_cash_flow,
                             roe, debt_to_equity, current_ratio)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (symbol, report_type, fiscal_year, fiscal_quarter) DO NOTHING
                        """, (
                            c["symbol"], c["name"], "cash_flow", year, q,
                            None, None, None, None, None,
                            bal["total_assets"] * growth, bal["total_liabilities"] * growth,
                            bal["equity"] * growth, bal["current_assets"] * growth,
                            bal["current_liabilities"] * growth,
                            cf["operating_cf"] * growth, cf["investing_cf"] * growth,
                            cf["financing_cf"] * growth, cf["free_cash_flow"] * growth,
                            rat["roe"], rat["debt_to_equity"], rat["current_ratio"]
                        ))

            # Seed shareholder data
            shareholders_data = {
                "sh600036": [
                    ("招商局集团有限公司", "state", 52.2e8, 20.8, 0.0, 1),
                    ("中国远洋海运集团有限公司", "state", 28.5e8, 11.3, 0.0, 2),
                    ("中国证券金融股份有限公司", "institution", 15.2e8, 6.0, -0.5, 3),
                    ("香港中央结算有限公司", "institution", 12.0e8, 4.8, 0.3, 4),
                    ("易方达价值成长混合型基金", "fund", 5.5e8, 2.2, 0.8, 5),
                    ("景顺长城新兴成长混合型基金", "fund", 4.8e8, 1.9, 0.5, 6),
                    ("兴全趋势投资混合型基金", "fund", 4.2e8, 1.7, -0.2, 7),
                    ("富国天惠精选成长混合型基金", "fund", 3.9e8, 1.5, 0.3, 8),
                    ("广发稳健增长混合型基金", "fund", 3.5e8, 1.4, 0.6, 9),
                    ("李嘉诚", "individual", 3.2e8, 1.3, 1.0, 10),
                ],
                "sh600519": [
                    ("中国贵州茅台酒厂(集团)有限责任公司", "state", 6.78e8, 54.0, 0.0, 1),
                    ("贵州省国有资产监督管理委员会", "state", 1.2e8, 9.5, 0.0, 2),
                    ("香港中央结算有限公司", "institution", 0.95e8, 7.6, 0.5, 3),
                    ("中央汇金资产管理有限责任公司", "institution", 0.55e8, 4.4, 0.0, 4),
                    ("中国证券金融股份有限公司", "institution", 0.32e8, 2.5, -0.3, 5),
                    ("易方达消费行业股票型基金", "fund", 0.28e8, 2.2, 0.8, 6),
                    ("华夏上证50ETF", "fund", 0.22e8, 1.8, 0.4, 7),
                    ("景顺长城新兴成长混合型基金", "fund", 0.18e8, 1.4, 0.6, 8),
                    ("富国天惠精选成长混合型基金", "fund", 0.15e8, 1.2, 0.3, 9),
                    ("王健林", "individual", 0.12e8, 0.95, 0.95, 10),
                ],
                "sh600000": [
                    ("上海国际集团有限公司", "state", 38.5e8, 13.2, 0.0, 1),
                    ("中国移动通信集团有限公司", "state", 22.0e8, 7.5, 0.0, 2),
                    ("上海国有资产经营有限公司", "state", 15.8e8, 5.4, 0.0, 3),
                    ("香港中央结算有限公司", "institution", 12.0e8, 4.1, 0.8, 4),
                    ("中国证券金融股份有限公司", "institution", 8.5e8, 2.9, -0.2, 5),
                    ("易方达上证50指数基金", "fund", 5.5e8, 1.9, 0.5, 6),
                    ("华夏沪深300ETF", "fund", 4.8e8, 1.6, 0.3, 7),
                    ("南方中证500ETF", "fund", 4.2e8, 1.4, 0.6, 8),
                    ("嘉实中证500ETF", "fund", 3.8e8, 1.3, 0.2, 9),
                    ("刘永好", "individual", 3.2e8, 1.1, 0.8, 10),
                ],
                "sh600016": [
                    ("泛海集团有限公司", "state", 42.0e8, 11.4, 0.0, 1),
                    ("中国首钢集团有限公司", "state", 25.0e8, 6.8, 0.0, 2),
                    ("香港中央结算有限公司", "institution", 18.0e8, 4.9, 0.5, 3),
                    ("中国证券金融股份有限公司", "institution", 12.0e8, 3.3, -0.4, 4),
                    ("易方达价值精选混合型基金", "fund", 6.0e8, 1.6, 0.7, 5),
                    ("南方成分精选混合型基金", "fund", 5.5e8, 1.5, 0.3, 6),
                    ("华夏回报混合型基金", "fund", 4.8e8, 1.3, 0.2, 7),
                    ("兴全可转债混合型基金", "fund", 4.2e8, 1.1, 0.5, 8),
                    ("广发聚丰混合型基金", "fund", 3.9e8, 1.1, 0.1, 9),
                    ("史玉柱", "individual", 3.5e8, 0.95, 0.95, 10),
                ],
                "sh601318": [
                    ("香港中央结算有限公司", "institution", 35.0e8, 19.1, 0.5, 1),
                    ("深圳市投资控股有限公司", "state", 28.0e8, 15.3, 0.0, 2),
                    ("中国证券金融股份有限公司", "institution", 18.0e8, 9.8, -0.2, 3),
                    ("中央汇金资产管理有限责任公司", "institution", 12.0e8, 6.5, 0.0, 4),
                    ("易方达上证50指数增强型基金", "fund", 6.5e8, 3.5, 0.8, 5),
                    ("华夏沪深300ETF", "fund", 5.8e8, 3.2, 0.4, 6),
                    ("南方中证500ETF", "fund", 4.5e8, 2.5, 0.6, 7),
                    ("富国中证500指数增强型基金", "fund", 4.0e8, 2.2, 0.3, 8),
                    ("广发中证500ETF", "fund", 3.8e8, 2.1, 0.5, 9),
                    ("马明哲", "individual", 3.2e8, 1.75, 0.0, 10),
                ],
            }

            for symbol, holders in shareholders_data.items():
                for holder in holders:
                    h_name, h_type, shares, pct, change, rank = holder
                    cur.execute("""
                        INSERT INTO shareholder_info
                        (symbol, holder_name, holder_type, shares_held, shares_pct, change_pct, ranking, as_of_date)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,'2024-03-31')
                        ON CONFLICT (symbol, holder_name, as_of_date) DO NOTHING
                    """, (symbol, h_name, h_type, shares, pct, change, rank))

        conn.commit()
    finally:
        conn.close()


# ── mock 表懒初始化 ─────────────────────────────────────────────────────────
# 原来在模块导入时直接 init_tables()+seed_data()（CREATE TABLE + ~150 INSERT）：
# 任何测试/工具 import 本模块都会触库，DB 不可用时整个应用起不来。
# 改为每进程首次命中遗留 mock 端点时执行一次（带锁防并发首击）。
_MOCK_TABLES_READY = False
_MOCK_INIT_LOCK = threading.Lock()


def _ensure_mock_tables():
    global _MOCK_TABLES_READY
    if _MOCK_TABLES_READY:
        return
    with _MOCK_INIT_LOCK:
        if _MOCK_TABLES_READY:
            return
        init_tables()
        seed_data()
        _MOCK_TABLES_READY = True


# ── Response Models ──────────────────────────────────────────────────────────
class FinancialData(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    report_type: str
    fiscal_year: int
    fiscal_quarter: int
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None
    eps: Optional[float] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    equity: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    operating_cf: Optional[float] = None
    investing_cf: Optional[float] = None
    financing_cf: Optional[float] = None
    free_cash_flow: Optional[float] = None
    roe: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None


class RatiosData(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    ps: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    gross_margin: Optional[float] = None
    net_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    revenue_yoy: Optional[float] = None
    net_income_yoy: Optional[float] = None
    eps_yoy: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None
    operating_cf: Optional[float] = None
    free_cash_flow: Optional[float] = None
    fcf_yield: Optional[float] = None
    dividend_yield: Optional[float] = None
    # Simulated market prices for ratio calculation
    market_price: Optional[float] = None
    shares_outstanding: Optional[float] = None


class ShareholderData(BaseModel):
    symbol: str
    holder_name: str
    holder_type: str
    shares_held: float
    shares_pct: float
    change_pct: float
    ranking: int
    as_of_date: str


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.get("/statement/{symbol}")
def get_financial_statement(symbol: str):
    """
    Get full financial statement (income, balance, cash flow) for a stock.
    Returns last 8 quarters of data.
    """
    _ensure_mock_tables()
    if symbol in ("sh000001", "000001"):
        return success({"symbol": symbol, "is_index": True, "message": "Index does not have financial statements"})

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT DISTINCT ON (report_type, fiscal_year, fiscal_quarter)
                    *
                FROM financial_statements
                WHERE symbol = %s
                ORDER BY report_type, fiscal_year DESC, fiscal_quarter DESC
            """, (symbol,))
            rows = cur.fetchall()

            if not rows:
                raise HTTPException(status_code=404, detail=f"No financial data found for {symbol}")

            company_name = rows[0]["company_name"]

            # Get income statement quarters
            cur.execute("""
                SELECT * FROM financial_statements
                WHERE symbol = %s AND report_type = 'income_statement'
                ORDER BY fiscal_year DESC, fiscal_quarter DESC
                LIMIT 9
            """, (symbol,))
            income_rows = cur.fetchall()

            cur.execute("""
                SELECT * FROM financial_statements
                WHERE symbol = %s AND report_type = 'balance_sheet'
                ORDER BY fiscal_year DESC, fiscal_quarter DESC
                LIMIT 4
            """, (symbol,))
            balance_rows = cur.fetchall()

            cur.execute("""
                SELECT * FROM financial_statements
                WHERE symbol = %s AND report_type = 'cash_flow'
                ORDER BY fiscal_year DESC, fiscal_quarter DESC
                LIMIT 4
            """, (symbol,))
            cashflow_rows = cur.fetchall()

            def clean_row(r: dict) -> dict:
                """Remove non-JSON-serializable fields."""
                for k in list(r.keys()):
                    if isinstance(r[k], (type(None), bool, int, float, str)):
                        pass
                    else:
                        r[k] = str(r[k]) if r[k] is not None else None
                return r

            return success({
                "symbol": symbol,
                "company_name": company_name,
                "income_statement": [clean_row(dict(r)) for r in income_rows],
                "balance_sheet": [clean_row(dict(r)) for r in balance_rows],
                "cash_flow": [clean_row(dict(r)) for r in cashflow_rows],
            })
    finally:
        conn.close()


@router.get("/ratios/{symbol}")
def get_financial_ratios(symbol: str):
    """Get computed financial ratios for a stock."""
    _ensure_mock_tables()
    if symbol in ("sh000001", "000001"):
        return success({"symbol": symbol, "is_index": True, "message": "Index does not have financial ratios"})

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get latest annual income statement data
            cur.execute("""
                SELECT * FROM financial_statements
                WHERE symbol = %s AND report_type = 'income_statement' AND fiscal_quarter = 4
                ORDER BY fiscal_year DESC LIMIT 2
            """, (symbol,))
            annual_rows = cur.fetchall()

            # Get latest balance sheet
            cur.execute("""
                SELECT * FROM financial_statements
                WHERE symbol = %s AND report_type = 'balance_sheet' AND fiscal_quarter = 4
                ORDER BY fiscal_year DESC LIMIT 1
            """, (symbol,))
            balance_rows = cur.fetchall()

            # Get latest cash flow
            cur.execute("""
                SELECT * FROM financial_statements
                WHERE symbol = %s AND report_type = 'cash_flow' AND fiscal_quarter = 4
                ORDER BY fiscal_year DESC LIMIT 1
            """, (symbol,))
            cf_rows = cur.fetchall()

            if not annual_rows:
                raise HTTPException(status_code=404, detail=f"No financial data found for {symbol}")

            latest = dict(annual_rows[0])
            prev = dict(annual_rows[1]) if len(annual_rows) > 1 else None
            balance = dict(balance_rows[0]) if balance_rows else {}
            cf = dict(cf_rows[0]) if cf_rows else {}

            company_name = latest.get("company_name")

            # Simulated market data for ratio calculations
            market_prices = {
                "sh600000": 8.50, "sh600036": 35.80, "sh600519": 1680.00,
                "sh600016": 3.85, "sh601318": 47.50,
            }
            shares_outstanding = {
                "sh600000": 295e8, "sh600036": 252e8, "sh600519": 12.6e8,
                "sh600016": 368e8, "sh601318": 183e8,
            }
            market_cap = {
                "sh600000": 295e8 * 8.50, "sh600036": 252e8 * 35.80,
                "sh600519": 12.6e8 * 1680.00, "sh600016": 368e8 * 3.85,
                "sh601318": 183e8 * 47.50,
            }

            price = market_prices.get(symbol, 10.0)
            shares = shares_outstanding.get(symbol, 100e8)
            mcap = market_cap.get(symbol, price * shares)

            revenue = latest.get("revenue") or 0
            net_income = latest.get("net_income") or 0
            eps = latest.get("eps") or 0
            total_assets = balance.get("total_assets") or 1
            equity = balance.get("equity") or 1
            operating_cf = cf.get("operating_cf") or 0
            free_cf = cf.get("free_cash_flow") or 0
            roe = latest.get("roe") or 0

            # YoY growth
            rev_yoy = None
            ni_yoy = None
            eps_yoy = None
            if prev:
                prev_rev = prev.get("revenue") or 1
                prev_ni = prev.get("net_income") or 1
                prev_eps = prev.get("eps") or 1
                if prev_rev > 0:
                    rev_yoy = round((revenue - prev_rev) / prev_rev * 100, 2)
                if prev_ni > 0:
                    ni_yoy = round((net_income - prev_ni) / prev_ni * 100, 2)
                if prev_eps > 0:
                    eps_yoy = round((eps - prev_eps) / prev_eps * 100, 2)

            pe_ttm = round(price / eps, 2) if eps > 0 else None
            pb = round(mcap / equity, 2) if equity > 0 else None
            ps = round(mcap / revenue, 2) if revenue > 0 else None
            roa = round(net_income / total_assets * 100, 2) if total_assets > 0 else None
            gross_margin = round(latest.get("gross_profit", 0) / revenue * 100, 2) if revenue > 0 else None
            net_margin = round(net_income / revenue * 100, 2) if revenue > 0 else None
            operating_margin = round(latest.get("operating_income", 0) / revenue * 100, 2) if revenue > 0 else None
            debt_to_equity = balance.get("debt_to_equity") or 0
            current_ratio = balance.get("current_ratio") or 0
            quick_ratio = round((balance.get("current_assets", 0) * 0.8) / max(balance.get("current_liabilities", 1), 1), 2)
            fcf_yield = round(free_cf / mcap * 100, 2) if mcap > 0 else None

            # Simulated dividend yield
            div_yields = {"sh600000": 3.8, "sh600036": 3.5, "sh600519": 1.8, "sh600016": 4.2, "sh601318": 2.8}
            dividend_yield = div_yields.get(symbol, 2.0)

            return success({
                "symbol": symbol,
                "company_name": company_name,
                "pe_ttm": pe_ttm,
                "pb": pb,
                "ps": ps,
                "roe": roe,
                "roa": roa,
                "gross_margin": gross_margin,
                "net_margin": net_margin,
                "operating_margin": operating_margin,
                "revenue_yoy": rev_yoy,
                "net_income_yoy": ni_yoy,
                "eps_yoy": eps_yoy,
                "debt_to_equity": debt_to_equity,
                "current_ratio": current_ratio,
                "quick_ratio": quick_ratio,
                "operating_cf": operating_cf,
                "free_cash_flow": free_cf,
                "fcf_yield": fcf_yield,
                "dividend_yield": dividend_yield,
                "market_price": price,
                "shares_outstanding": shares,
            })
    finally:
        conn.close()


@router.get("/compare")
def compare_stocks(symbols: str = Query(..., description="Comma-separated symbols, up to 5")):
    """
    Compare key financial metrics for multiple stocks side-by-side.
    """
    _ensure_mock_tables()
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()][:5]

    if not symbol_list:
        raise HTTPException(status_code=400, detail="At least one symbol required")

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            results = []
            for sym in symbol_list:
                cur.execute("""
                    SELECT * FROM financial_statements
                    WHERE symbol = %s AND report_type = 'income_statement' AND fiscal_quarter = 4
                    ORDER BY fiscal_year DESC LIMIT 1
                """, (sym,))
                inc = cur.fetchone()

                cur.execute("""
                    SELECT * FROM financial_statements
                    WHERE symbol = %s AND report_type = 'balance_sheet' AND fiscal_quarter = 4
                    ORDER BY fiscal_year DESC LIMIT 1
                """, (sym,))
                bal = cur.fetchone()

                cur.execute("""
                    SELECT * FROM financial_statements
                    WHERE symbol = %s AND report_type = 'cash_flow' AND fiscal_quarter = 4
                    ORDER BY fiscal_year DESC LIMIT 1
                """, (sym,))
                cf = cur.fetchone()

                if not inc:
                    continue

                market_prices = {
                    "sh600000": 8.50, "sh600036": 35.80, "sh600519": 1680.00,
                    "sh600016": 3.85, "sh601318": 47.50,
                }
                shares_outstanding = {
                    "sh600000": 295e8, "sh600036": 252e8, "sh600519": 12.6e8,
                    "sh600016": 368e8, "sh601318": 183e8,
                }
                price = market_prices.get(sym, 10.0)
                shares = shares_outstanding.get(sym, 100e8)
                eps = inc.get("eps") or 0
                revenue = inc.get("revenue") or 0
                net_income = inc.get("net_income") or 0
                equity = (bal.get("equity") or 1) if bal else 1
                mcap = price * shares

                results.append({
                    "symbol": sym,
                    "company_name": inc.get("company_name"),
                    "market_price": price,
                    "revenue": revenue,
                    "net_income": net_income,
                    "eps": eps,
                    "roe": inc.get("roe"),
                    "roa": round(net_income / max((bal.get("total_assets") or 1), 1) * 100, 2) if bal else None,
                    "gross_margin": round(inc.get("gross_profit", 0) / max(revenue, 1) * 100, 2),
                    "net_margin": round(net_income / max(revenue, 1) * 100, 2),
                    "pe": round(price / eps, 2) if eps > 0 else None,
                    "pb": round(mcap / equity, 2) if equity > 0 else None,
                    "debt_to_equity": bal.get("debt_to_equity") if bal else None,
                    "current_ratio": bal.get("current_ratio") if bal else None,
                    "operating_cf": cf.get("operating_cf") if cf else None,
                    "free_cash_flow": cf.get("free_cash_flow") if cf else None,
                    "total_assets": bal.get("total_assets") if bal else None,
                    "equity": equity,
                })

            return success({"stocks": results})
    finally:
        conn.close()


@router.get("/ownership/{symbol}")
def get_shareholder_info(symbol: str):
    """Get top 10 shareholders for a stock."""
    _ensure_mock_tables()
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM shareholder_info
                WHERE symbol = %s
                ORDER BY ranking ASC
                LIMIT 10
            """, (symbol,))
            rows = cur.fetchall()

            if not rows:
                raise HTTPException(status_code=404, detail=f"No shareholder data found for {symbol}")

            def clean_row(r: dict) -> dict:
                for k in list(r.keys()):
                    if not isinstance(r[k], (type(None), bool, int, float, str)):
                        r[k] = str(r[k]) if r[k] is not None else None
                return r

            return success({
                "symbol": symbol,
                "shareholders": [clean_row(dict(r)) for r in rows],
            })
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
#  真实财务数据端点（stock_financial_detail + stock_earnings_forecast）
#  与上方 mock demo 端点共存，用 /detail/ 前缀区分。
# ════════════════════════════════════════════════════════════════════════════

from src.api.handler.financial_detail_handler import (
    detail_series,
    forecast_list,
    industry_valuation_snapshot,
    stock_profile,
    valuation_history,
    valuation_percentile,
    index_valuation_percentile,
    index_financial_agg,
    index_valuation_percentile_batch,
    dcf_valuation,
    ddm_valuation,
    asset_value_report,
    comps_valuation,
    fundamental_analysis,
    fundamental_history,
    fundamental_report_detail,
    quality_report,
    valuation_band_report,
    bank_report,
    peg_report,
    moat_report,
    fraud_signals_report,
    efficiency_report,
    style_report,
    liquidity_report,
    z_score_report,
    m_score_report,
    concentration_report,
    common_size,
    ratios,
    cashflow_analysis,
    industry_members,
    industry_peers,
    five_forces_report,
    market_cap_growth_index,
    market_cap_growth_stock,
    index_pe_trend,
)


@router.get("/detail/{symbol}")
def _detail_series(
    symbol: str,
    statement_type: str = Query("income", description="income/balance/cashflow/abstract"),
    limit: int = Query(20, ge=1, le=200, description="返回最近 N 期（与 start/end 二选一）"),
    start_date: Optional[str] = Query(None, description="起始报告期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="截止报告期 YYYY-MM-DD"),
    period: str = Query("quarter", description="month=原始;quarter=单季换算;year=年报期"),
):
    """三大报表历史时序（真实数据，固定列 + detail JSONB）。"""
    return detail_series(symbol, statement_type, limit, start_date, end_date, period)


@router.get("/forecast")
def _forecast_list(
    report_date: Optional[str] = Query(None, description="YYYYMMDD，为空取最新"),
    type: Optional[str] = Query(None, description="preannounce/express"),
    limit: int = Query(50, ge=1, le=500),
):
    """业绩预告/快报全市场列表（真实数据）。"""
    return forecast_list(report_date, type, limit)


@router.get("/profile/{symbol}")
def _stock_profile(symbol: str):
    """股票基本信息概要（名称/市值/PE/PB/行业/经营范围）。"""
    return stock_profile(symbol)


@router.get("/valuation-history/{symbol}")
def _valuation_history(
    symbol: str,
    report_dates: str = Query(..., description="逗号分隔的报告期 YYYY-MM-DD"),
):
    """按报告期末对齐的个股估值历史（PE/PB/PS）。"""
    dates = [d.strip() for d in report_dates.split(",") if d.strip()]
    return valuation_history(symbol, dates)


@router.get("/industry-valuation-snapshot")
def _industry_valuation_snapshot(
    industry: Optional[str] = Query(None, description="行业名或sw_code；空=全部"),
):
    """申万一级行业估值当天快照（PE/PB/股息率）。"""
    return industry_valuation_snapshot(industry)


@router.get("/valuation-percentile/{symbol}")
def _valuation_percentile(
    symbol: str,
    windows: str = Query(
        "3y,5y,10y", description="逗号分隔，可选 3y/5y/10y/15y/20y/all",
    ),
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD，默认最新交易日"),
    metrics: str = Query(
        "pe_ttm,pb,ps_ttm,dv_ttm",
        description="逗号分隔的指标",
    ),
    exclude: Optional[str] = Query(
        None,
        description="剔除区间，格式 2020-06-01~2021-02-28,逗号分隔多段",
    ),
):
    """个股估值历史分位（PE/PB/PS/股息率 × 多窗口，支持区间剔除）。"""
    win_list = [w.strip() for w in windows.split(",") if w.strip()]
    met_list = [m.strip() for m in metrics.split(",") if m.strip()]
    return valuation_percentile(symbol, win_list, as_of, met_list, exclude)


@router.get("/index-valuation-percentile")
def _index_valuation_percentile(
    scope: str = Query(..., description="index | sw"),
    code: str = Query(..., description="指数代码或申万行业代码"),
    window: str = Query("10y", description="3y/5y/10y"),
    metrics: str = Query("pe_ttm,pb", description="逗号分隔"),
):
    """指数/行业估值历史分位。"""
    met_list = [m.strip() for m in metrics.split(",") if m.strip()]
    return index_valuation_percentile(scope, code, window, met_list)


@router.get("/index-financial-agg")
def _index_financial_agg(
    scope: str = Query(..., description="index | sw"),
    code: str = Query(...),
):
    """指数/行业季度财务聚合时序。"""
    return index_financial_agg(scope, code)


@router.get("/market-cap-growth/index/{code}")
def _market_cap_growth_index(
    code: str,
    years: int = Query(10, ge=1, le=30, description="回溯年数"),
):
    """指数市值与业绩增长趋势（营收/归母净利三口径 + 总市值折线）。"""
    return market_cap_growth_index(code, years)


@router.get("/market-cap-growth/stock/{symbol}")
def _market_cap_growth_stock(
    symbol: str,
    years: int = Query(10, ge=1, le=30, description="回溯年数"),
):
    """个股市值与业绩增长趋势（营收/归母净利三口径 + 总市值折线）。"""
    return market_cap_growth_stock(symbol, years)


@router.get("/index-pe/{code}")
def _index_pe(
    code: str,
    years: int = Query(8, ge=0, le=30, description="回溯年数，0=全部"),
):
    """指数整体法市盈率趋势（PE 月度序列 + 均值/±σ 参考线统计）。"""
    return index_pe_trend(code, years)


@router.get("/index-valuation-percentile/batch")
def _index_valuation_percentile_batch(
    scope: str = Query("sw"),
    window: str = Query("10y"),
    metric: str = Query("pe_ttm"),
):
    """批量返回所有行业/指数的单指标分位（排行用）。"""
    return index_valuation_percentile_batch(scope, window, metric)


@router.get("/dcf/{symbol}")
def _dcf_valuation(
    symbol: str,
    growth_rate: float = Query(
        0.08, ge=-0.5, le=1.0,
        description="显式预测期年增长率",
    ),
    terminal_growth: float = Query(
        0.03, ge=0.0, le=0.08,
        description="永续增长率",
    ),
    wacc: float = Query(
        0.09, ge=0.02, le=0.30,
        description="折现率(加权平均资本成本)",
    ),
    projection_years: int = Query(
        10, ge=1, le=30,
        description="显式预测年数",
    ),
):
    """DCF 内在价值 + 安全边际（基于最新自由现金流折现）。

    价值投资绝对估值锚：回答"公司值多少钱、现价贵不贵"。
    假设可调（增长率/折现率/年数），投资者应按公司实际设定。
    """
    return dcf_valuation(
        symbol, growth_rate, terminal_growth,
        wacc, projection_years,
    )


@router.get("/ddm/{symbol}")
def _ddm_valuation(
    symbol: str,
    growth_rate: float = Query(
        0.02, ge=0.0, le=0.08,
        description="永续股利增长率（默认 2%，≈长期通胀）",
    ),
    discount_rate: float = Query(
        0.055, ge=0.02, le=0.20,
        description="折现率（红利股参考 5.5%）",
    ),
):
    """股利折现模型 DDM（Gordon）内在价值 + 安全边际。

    《股票投资课程》15 集：适用于确定性高、成长性低的分红型公司
    （课程案例：长江电力 2024 分红 230 亿、r=5.5%、g=2%）。
    D₀ = TTM 每股派息 × 股本（兜底：市值 × 落地股息率）。
    """
    return ddm_valuation(symbol, growth_rate, discount_rate)


@router.get("/asset-value/{symbol}")
def _asset_value_report(
    symbol: str,
    years: int = Query(
        8, ge=1, le=30, description="PB 历史窗口年数（课程默认 8 年）",
    ),
):
    """净资产分析法：账面净资产底线 + PB 均值±1σ 通道四态。

    归母净资产为底线价值；隐含市值 = 净资产 × 历史 PB 中枢 μ。
    破净（PB<1）提示。课程茅台案例：8 年 PB 均值 4.33、σ 2.41。
    """
    return asset_value_report(symbol, years)


@router.get("/comps/{symbol}")
def _comps_valuation(
    symbol: str,
    level: int = Query(
        2, ge=1, le=2, description="申万行业层级（默认二级）",
    ),
):
    """类比估值法（跟同类型公司比）：同行乘数截面 + 隐含市值。

    同行业中位 PE/PB/PS/股息率反推隐含市值与上下行空间；
    课程局限：只判断相对高低，须与绝对估值交叉验证。
    """
    return comps_valuation(symbol, level)


@router.get("/fundamental-analysis/{symbol}")
def _fundamental_analysis(
    symbol: str,
    periods: int = Query(
        12, ge=1, le=40, description="取最近 N 期报表参与分析",
    ),
):
    """个股基本面深度分析（真实数据注入 + LLM 结构化报告）。

    注入三大报表时序 / 估值历史分位 / 价值衍生指标，由 LLM 产出
    盈利质量、财务健康、估值、资本回报、护城河、风险、综合评分。
    同步返回结构化报告。
    """
    return fundamental_analysis(symbol, periods)


@router.get("/fundamental-analysis/{symbol}/history")
def _fundamental_history(
    symbol: str,
    limit: int = Query(20, ge=1, le=100, description="返回最近 N 份历史报告"),
):
    """基本面分析历史（评分趋势 / 回看过往报告摘要）。"""
    return fundamental_history(symbol, limit)


@router.get("/fundamental-analysis/report/{report_id}")
def _fundamental_report_detail(report_id: int):
    """查看某份历史基本面分析报告的完整内容（回看）。"""
    return fundamental_report_detail(report_id)


@router.get("/quality/{symbol}")
def _quality_report(symbol: str):
    """财务质量诊断报告（三表健康度综合评分 + 淘汰红线）。

    《股票投资课程》08/19 集方法论：先用收现比/净现比/现金覆盖短期债务/
    应收 vs 现金/费用毛利比/杜邦/商誉等指标筛掉垃圾公司，再看估值。
    返回 quality_score(0~100) + red_flags + verdict(pass/review/eliminate)。
    """
    return quality_report(symbol)


@router.get("/valuation-band/{symbol}")
def _valuation_band(
    symbol: str,
    metric: str = Query(
        "pe_ttm", description="估值指标：pe / pe_ttm / pb / ps / ps_ttm",
    ),
    years: int = Query(8, ge=1, le=30, description="回溯年数（课程默认 8 年）"),
):
    """均值±1σ 估值带四分类（参数化估值，与历史分位互补）。

    《股票投资课程》21/24/25 集惯用方法：对 PE/PB 时序算 μ、σ，
    把当前值放入 ±1σ 通道判四态：超跌 / 合理偏低 / 合理偏高 / 虚高。
    """
    return valuation_band_report(symbol, metric, years)


@router.get("/bank-report/{symbol}")
def _bank_report(symbol: str):
    """银行业专项指标报告（存贷比/NIM/拨备/NPL/营收拆分）。

    《股票投资课程》20 集招行案例：通用质量诊断不覆盖银行监管指标，
    本端点从银行三大表 detail 抽取专项科目计算。仅银行股有数据。
    """
    return bank_report(symbol)


@router.get("/peg/{symbol}")
def _peg(
    symbol: str,
    growth: Optional[float] = Query(
        None, description="预期盈利增速（小数，如 0.20）；不传则尝试用历史 CAGR",
    ),
):
    """PEG 比率（PE / 盈利增速%）。

    《股票投资课程》15/17 成长股估值核心：<1 低估、1~2 合理、>2 偏贵。
    """
    return peg_report(symbol, growth)


@router.get("/moat/{symbol}")
def _moat(symbol: str):
    """定价权与护城河评分（毛利率水平+稳定性+趋势，+ROE+低杠杆）。

    《股票投资课程》09 商业模式/14 战略：好公司能持续赚高毛利。
    """
    return moat_report(symbol)


@router.get("/fraud-signals/{symbol}")
def _fraud_signals(symbol: str):
    """财务造假/异常红旗检测（营收-应收/净利-现金流/存货/毛利率突变）。

    《股票投资课程》21 检查清单：取最近两期对比，severity: clean/watch/high_risk。
    """
    return fraud_signals_report(symbol)


@router.get("/efficiency/{symbol}")
def _efficiency(symbol: str):
    """经营效率趋势（应收/存货/总资产周转率多期趋势）。

    《股票投资课程》08/13/19：周转率上升=效率改善，下降=竞争力衰退早期信号。
    """
    return efficiency_report(symbol)


@router.get("/style/{symbol}")
def _style(
    symbol: str,
    growth: Optional[float] = Query(
        None, description="预期盈利增速（小数，如 0.20）",
    ),
):
    """成长 vs 价值风格分类（growth/value/balanced + 质量标签 + PEG）。

    《股票投资课程》17：综合 PE+增速+ROE 判定投资风格。
    """
    return style_report(symbol, growth)


@router.get("/liquidity/{symbol}")
def _liquidity(symbol: str):
    """流动性比率四件套（流动/速动/现金/营运资本 + 综合偿债 verdict）。

    《股票投资课程》12/19：短期偿债能力基础分析。
    """
    return liquidity_report(symbol)


@router.get("/z-score/{symbol}")
def _z_score(symbol: str):
    """Altman Z-Score 破产预测（5 因子；safe/grey/distress）。

    《股票投资课程》21 检查清单补强：经典学术破产风险模型。
    """
    return z_score_report(symbol)


@router.get("/m-score/{symbol}")
def _m_score(symbol: str):
    """Beneish M-Score 盈余操纵检测（8 因子；manipulator/watch/clean）。

    《股票投资课程》21 检查清单补强：统计模型，与 fraud-signals 规则红旗互补。
    """
    return m_score_report(symbol)


@router.get("/concentration/{symbol}")
def _concentration(symbol: str):
    """筹码集中度（股东户数趋势：连减=主力收集利好 / 连增=散户化）。

    《股票投资课程》18/21：需先同步 shareholder_count。
    """
    return concentration_report(symbol)


@router.get("/common-size/{symbol}")
def _common_size(
    symbol: str,
    statement_type: str = Query("income", description="income/balance/cashflow"),
    period: str = Query("month", description="month=原始累计口径;year=年报期"),
    limit: int = Query(12, ge=1, le=60, description="返回最近 N 期"),
):
    """同型分析：三大报表全科目结构百分比（科目÷基准值，跨期对比）。"""
    return common_size(symbol, statement_type, period, limit)


@router.get("/ratio-analysis/{symbol}")
def _ratio_analysis(
    symbol: str,
    period: str = Query("month", description="month=原始累计口径;year=年报期"),
    limit: int = Query(12, ge=1, le=60, description="返回最近 N 期"),
):
    """比率分析：14 个核心财务比率（盈利/偿债/营运/成长）多期矩阵。

    独立路径——/ratios/{symbol} 已被上方遗留端点占用（FastAPI 同路径
    先注册优先，曾遮蔽本路由导致前端拿到旧结构崩溃）。
    """
    return ratios(symbol, period, limit)


@router.get("/industry-members/{symbol}")
def _industry_members(symbol: str):
    """个股申万行业归属（一级/二级 + 权重 + 计入日期）。"""
    return industry_members(symbol)


@router.get("/industry-peers/{symbol}")
def _industry_peers(
    symbol: str,
    level: int = Query(2, ge=1, le=2, description="2=申万二级(默认);1=一级"),
    limit: int = Query(13, ge=1, le=40, description="截面时序返回期数"),
):
    """同行截面：截面时序（CR4/HHI/分布）+ 同行明细 + 目标股分位。

    五力分析（课程 14 集）的数据底座；独立路径，与既有
    /industry-valuation-snapshot 无冲突。
    """
    return industry_peers(symbol, level, limit)


@router.get("/five-forces/{symbol}")
def _five_forces_report(symbol: str):
    """波特五力评分：三力量化（应付/应收/CR4趋势）+ 两力行业因子。

    handler 串调既有 ratio-analysis/cashflow-analysis/industry-peers
    取数（零重复 SQL）；子调用失败按力降级，ratio 与行业双缺才 error。
    """
    return five_forces_report(symbol)


@router.get("/cashflow-analysis/{symbol}")
def _cashflow_analysis(
    symbol: str,
    period: str = Query("month", description="month=原始累计口径;year=年报期"),
    limit: int = Query(12, ge=1, le=60, description="返回最近 N 期"),
):
    """现金流分析：11 个现金流指标（盈利质量/增长趋势/现金流结构）多期矩阵。

    独立路径——已核实与既有路径零冲突（router:477 遮蔽教训）。
    """
    return cashflow_analysis(symbol, period, limit)
