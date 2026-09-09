"""
AkshareProvider
===============
AKShare 数据源 SyncProvider 实现（A股ETF + 美股 + 汇率，统一走 akshare）。
"""
import re
from datetime import datetime, date
from typing import Optional

import akshare as ak
import pandas as pd

from conf import app_config
from src.domain.market.sync.sync_provider import OHLCVBar, SyncProvider

__all__ = ["AkshareProvider"]


# 美股 ticker：1-5 个大写字母（VOO / TLT / GLD / AAPL / BRK.B 不在此版支持）
_US_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
# A股 ETF：sh/sz + 6 位数字（sh510300 / sz159934）
_A_PREFIX_RE = re.compile(r"^(sh|sz)(\d{6})$")
# 港股：纯 5 位数字（02800 盈富基金 / 02819 国债ETF）。与 A 股(sh/sz 前缀)
# 和美股(字母)互斥, 不会碰撞。
_HK_TICKER_RE = re.compile(r"^\d{5}$")


def _num(v):
    """宽松数值转换：去千分位/百分号/空白，失败或 NaN/空 → None。"""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    try:
        s = str(v).strip().replace(",", "").rstrip("%")
        if s in ("", "nan", "NaN", "None", "--"):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_iso_date(v):
    """'2026-06-22' / datetime / '2026-06-22 00:00:00' → date；失败 None。"""
    from datetime import date as _date, datetime as _dt
    if v is None:
        return None
    if isinstance(v, _dt):
        return v.date()
    if isinstance(v, _date):
        return v
    s = str(v).strip()[:10]
    try:
        return _dt.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


class AkshareProvider(SyncProvider):
    """
    AKShare 数据源 Provider

    支持：
      - A股 ETF 日线（fund_etf_hist_em，吃纯数字代码 510300）
      - 美股日线（stock_us_daily）
      - 汇率日线（currency_boc_sina，中行折算价/100）

    不支持分钟线（P1 范围外）。
    """

    name = "akshare"
    supports_minute = False

    # ── 符号识别 / 规范化 ────────────────────────────────────────────────
    @staticmethod
    def _is_us_ticker(symbol: str) -> bool:
        """VOO → True；sh510300 → False"""
        return bool(_US_TICKER_RE.match(symbol))

    @staticmethod
    def _strip_exchange_prefix(symbol: str) -> str:
        """sh510300 → 510300（akshare fund_etf_hist_em 吃纯数字）"""
        m = _A_PREFIX_RE.match(symbol)
        return m.group(2) if m else symbol

    def validate_symbol(self, symbol: str) -> bool:
        """验证 symbol 是否为 AkshareProvider 支持的格式"""
        if not symbol:
            return False
        if _US_TICKER_RE.match(symbol):
            return True
        if _A_PREFIX_RE.match(symbol):
            return True
        if _HK_TICKER_RE.match(symbol):
            return True
        return False

    # ── fetch 方法 ──────────────────────────────────────────────────────
    def fetch_daily(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: int = 1300,
    ) -> list[OHLCVBar]:
        if self._is_us_ticker(symbol):
            return self._fetch_us(symbol, start_date, end_date)
        if _HK_TICKER_RE.match(symbol):
            # 港股(纯5位数字, 如 02800/02819/02840/02815)
            return self.fetch_hk_stock_daily(symbol, start_date, end_date)
        return self._fetch_a_etf(symbol, start_date, end_date)

    def _fetch_a_etf(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """A 股 ETF 日线（fund_etf_hist_sina，新浪、英文列、需 sh/sz 前缀）。
        无日期参数，返回全量历史后客户端切片。东财 fund_etf_hist_em 在本环境不可达。"""
        sym = symbol if _A_PREFIX_RE.match(symbol) else f"sh{self._strip_exchange_prefix(symbol)}"
        try:
            df = ak.fund_etf_hist_sina(symbol=sym)
        except Exception:
            return []
        if df is None or df.empty:
            return []
        bars = self._df_to_en_bars(df, symbol, market="A")
        return self._slice_bars(bars, start_date, end_date)

    def _fetch_us(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """美股日线（stock_us_daily，英文小写列，无 amount → 0.0）"""
        try:
            df = ak.stock_us_daily(symbol=symbol, adjust="qfq")
        except Exception:
            return []
        if df is None or df.empty:
            return []
        bars: list[OHLCVBar] = []
        for _, r in df.iterrows():
            try:
                t = r["date"]
                if hasattr(t, "to_pydatetime"):
                    t = t.to_pydatetime()
                elif isinstance(t, str):
                    t = datetime.strptime(t[:10], "%Y-%m-%d")
                bars.append(
                    OHLCVBar(
                        symbol=symbol,
                        trade_time=t,
                        open_=float(r["open"]),
                        close_=float(r["close"]),
                        high_=float(r["high"]),
                        low_=float(r["low"]),
                        volume=float(r["volume"]),
                        amount=0.0,            # akshare 美股接口无成交额
                        interval="1d",
                        market="US",
                        provider="akshare",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return bars

    @staticmethod
    def _df_to_a_bars(df: pd.DataFrame, symbol: str) -> list:
        """中文列 DataFrame → OHLCVBar 列表（中文列名映射）"""
        bars: list = []
        for _, r in df.iterrows():
            try:
                t = r["日期"]
                if isinstance(t, str):
                    t = datetime.strptime(t, "%Y-%m-%d")
                bars.append(
                    OHLCVBar(
                        symbol=symbol,
                        trade_time=t,
                        open_=float(r["开盘"]),
                        close_=float(r["收盘"]),
                        high_=float(r["最高"]),
                        low_=float(r["最低"]),
                        volume=float(r["成交量"]),
                        amount=float(r["成交额"]),
                        interval="1d",
                        market="A",
                        provider="akshare",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return bars

    def fetch_minute(
        self,
        symbol: str,
        interval: str = "5m",
        datalen: int = 3000,
    ) -> list[OHLCVBar]:
        raise NotImplementedError("P1 不支持分钟线")

    def get_stock_list(self, market: Optional[str] = None) -> list:
        """从 app_config.portfolio_universe 读标的，按 market 过滤。
        market 为 None/空串时返回全部（组合篮子固定清单，不扫全市场）。"""
        bars = app_config.portfolio_universe.bars
        if not market:
            return [b.symbol for b in bars]
        return [b.symbol for b in bars if b.market == market]

    # ── 汇率（Task 6）────────────────────────────────────────────────────
    def fetch_fx_daily(
        self,
        pair: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[tuple]:
        """拉汇率日线。返回 [(date, rate), ...]，rate = 中行折算价/100。

        支持所有 CNY 货币对(USDCNY/HKDCNY/EURCNY ...), 映射表见
        _FX_BOC_SYMBOL。USDCNY rate=中行折算价/100 ≈ 7.0;
        HKDCNY rate=中行折算价/100 ≈ 0.87。

        注意：与 fund_etf_hist_em 同理，显式传 start_date=None / end_date=None
        不安全（部分 akshare 版本返回陈旧默认窗口，实测停在 2023-11），
        故按需构建 kwargs；不传日期时 currency_boc_sina 会返回最近约 180 行
        默认窗口(可能陈旧, 生产应显式传日期)。
        """
        boc_symbol = self._FX_BOC_SYMBOL.get(pair)
        if not boc_symbol:
            return []
        # currency_boc_sina 的日期参数格式 YYYYMMDD
        kwargs = {"symbol": boc_symbol}
        if start_date:
            sd = start_date.replace("-", "") if isinstance(start_date, str) else start_date
            kwargs["start_date"] = sd
        if end_date:
            ed = end_date.replace("-", "") if isinstance(end_date, str) else end_date
            kwargs["end_date"] = ed
        try:
            df = ak.currency_boc_sina(**kwargs)
        except Exception:
            return []
        if df is None or df.empty:
            return []
        out = []
        for _, r in df.iterrows():
            try:
                d = r["日期"]
                if not isinstance(d, date):
                    d = datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
                rate = float(r["中行折算价"]) / 100.0
                out.append((d, rate))
            except (KeyError, ValueError, TypeError):
                continue
        return out

    # ── 日期工具 ─────────────────────────────────────────────────────────
    @staticmethod
    def _to_yyyymmdd(d: str) -> str:
        """ISO 日期 '2026-06-25' → akshare 日期参数 '20260625'。"""
        return str(d).replace("-", "")[:8]

    @staticmethod
    def _strip_hk_prefix(symbol: str) -> str:
        """hk00700 / 00700 → '00700'（akshare 港股接口吃纯 5 位）。"""
        s = symbol.lower()
        return s[2:] if s.startswith("hk") else symbol

    # ── A 股个股日线（stock_zh_a_daily，新浪、英文列、服务端日期）─────────
    def fetch_a_stock_daily(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """A 股个股日线，支持长历史（10 年+）。symbol: sh600000（需前缀）。
        走新浪 stock_zh_a_daily：服务端 start_date/end_date（YYYYMMDD），英文列。
        北交所 bj 代码新浪接口不支持，返回空。"""
        if symbol.lower().startswith("bj"):
            return []
        # stock_zh_a_daily 需要 sh/sz 前缀
        sym = symbol if _A_PREFIX_RE.match(symbol) else f"sh{self._strip_exchange_prefix(symbol)}"
        kwargs = {"symbol": sym, "adjust": "qfq"}
        if start_date:
            kwargs["start_date"] = self._to_yyyymmdd(start_date)
        if end_date:
            kwargs["end_date"] = self._to_yyyymmdd(end_date)
        try:
            df = ak.stock_zh_a_daily(**kwargs)
        except Exception:
            return []
        if df is None or df.empty:
            return []
        return self._df_to_en_bars(df, symbol, market="A")

    # ── A 股个股估值日线（stock_value_em，东财、完整历史）──────────────────
    def fetch_valuation(self, symbol: str) -> list[dict]:
        """
        A 股个股估值历史（PE/PB/PS/总市值），按交易日。

        来源：ak.stock_value_em（东方财富），返回从上市至今的完整历史。
        symbol: sh600000 / sz000001（带前缀，内部转纯 6 位数字）。

        注意：本接口无股息率字段，dv_ratio/dv_ttm 留空；
        个股股息率改由 fetch_dividend_detail（分红明细）+
        fundamental.dividend_yield 计算 TTM 后回写 stock_valuation。

        Returns:
            list[dict]，每条含:
              trade_date(datetime), pe, pe_ttm, pb, ps, ps_ttm,
              dv_ratio(None), dv_ttm(None), total_mv
        """
        code = self._strip_exchange_prefix(symbol)
        df = self._retry_all(lambda: ak.stock_value_em(symbol=code))
        if df is None or df.empty:
            return []

        out: list[dict] = []
        for _, r in df.iterrows():
            try:
                # 东财接口列名：数据日期 / PE(TTM) / PE(静) / 市净率 / 市销率 / 总市值
                td = r.get("数据日期")
                if hasattr(td, "to_pydatetime"):
                    td = td.to_pydatetime()
                elif isinstance(td, str):
                    td = datetime.strptime(td[:10], "%Y-%m-%d")
                elif isinstance(td, date) and not isinstance(td, datetime):
                    td = datetime(td.year, td.month, td.day)

                def _f(key):
                    v = r.get(key)
                    try:
                        return float(v) if v is not None else None
                    except (TypeError, ValueError):
                        return None

                out.append({
                    "trade_date": td,
                    "pe": _f("PE(静)"),
                    "pe_ttm": _f("PE(TTM)"),
                    "pb": _f("市净率"),
                    "ps": _f("市销率"),
                    "ps_ttm": _f("市销率"),
                    "dv_ratio": None,
                    "dv_ttm": None,
                    "total_mv": _f("总市值"),
                })
            except (KeyError, ValueError, TypeError):
                continue
        return out

    # ── A 股个股分红明细（stock_history_dividend_detail，新浪）──────────────
    def fetch_dividend_detail(self, symbol: str) -> list[dict]:
        """
        A 股个股分红明细历史（每次分红事件一行），按除权除息日。

        来源：ak.stock_history_dividend_detail(symbol, indicator="分红")。
        symbol: sh600000 / sz000001（带前缀，内部转纯 6 位数字）。

        只保留有「除权除息日」的记录（已实施/已除权的分红）；
        预案、未实施的通常无除权除息日，被跳过。

        Returns:
            list[dict]，每条含:
              ex_date(date), announce_date(date|None),
              div_per_share(元/股|None), stock_div|None,
              convert|None, progress|None
        """
        code = self._strip_exchange_prefix(symbol)
        df = self._retry_all(
            lambda: ak.stock_history_dividend_detail(
                symbol=code, indicator="分红"
            )
        )
        if df is None or df.empty:
            return []
        out: list[dict] = []
        for _, r in df.iterrows():
            try:
                ex = _parse_iso_date(r.get("除权除息日"))
                if ex is None:
                    continue  # 无除权除息日（仅预案），跳过
                _dps = _num(r.get("派息"))
                out.append({
                    "ex_date": ex,
                    "announce_date": _parse_iso_date(r.get("公告日期")),
                    # "派息"为每10股派现(税前)，转成每股(元/股)
                    "div_per_share": (
                        _dps / 10.0 if _dps is not None else None
                    ),
                    "stock_div": _num(r.get("送股")),
                    "convert": _num(r.get("转增")),
                    "progress": (
                        str(r.get("进度")).strip()
                        if r.get("进度") is not None else None
                    ),
                })
            except (KeyError, ValueError, TypeError):
                continue
        return out

    # ── 股东户数（筹码集中度，stock_zh_a_gdhs_detail_em）─────────────────────
    def fetch_shareholder_count(self, symbol: str) -> list[dict]:
        """A 股个股股东户数历史（每期报告一行），按统计截止日升序。

        来源：ak.stock_zh_a_gdhs_detail_em(symbol=code)。
        symbol: sh600519 / sz000001（带前缀，内部转纯 6 位）。

        Returns:
            list[dict]，每条含: report_date(date), holder_count(int),
            per_capita_holding(股|None), price_change_pct(小数|None)。
        """
        code = self._strip_exchange_prefix(symbol)
        df = self._retry_all(lambda: ak.stock_zh_a_gdhs_detail_em(symbol=code))
        if df is None or df.empty:
            return []
        out: list[dict] = []
        for _, r in df.iterrows():
            try:
                rd = _parse_iso_date(r.get("股东户数统计截止日"))
                if rd is None:
                    continue
                hc = r.get("股东户数-本次")
                hc = int(hc) if hc is not None and str(hc).strip() != "" else None
                pch = _num(r.get("区间涨跌幅"))
                out.append({
                    "report_date": rd,
                    "holder_count": hc,
                    "per_capita_holding": _num(r.get("户均持股数量")),
                    "price_change_pct": (pch / 100.0) if pch is not None else None,
                })
            except (KeyError, ValueError, TypeError):
                continue
        out.sort(key=lambda x: x["report_date"])
        return out

    # ── 北向资金（沪深港通，stock_hsgt_hist_em）──────────────────────────────
    def fetch_north_flow(self, symbol: str = "北向资金") -> list[dict]:
        """北向资金（沪深港通）历史净流入，按日期升序。

        来源：ak.stock_hsgt_hist_em(symbol="北向资金"/"沪股通"/"深股通")。

        Returns:
            list[dict]，每条含: trade_date(date), net_buy(元|None)。
        """
        df = self._retry_all(lambda: ak.stock_hsgt_hist_em(symbol=symbol))
        if df is None or df.empty:
            return []
        out: list[dict] = []
        for _, r in df.iterrows():
            try:
                d = _parse_iso_date(r.get("日期"))
                if d is None:
                    continue
                nb = _num(r.get("当日成交净买额"))
                if nb is None:
                    nb = _num(r.get("当日资金流入"))
                out.append({"trade_date": d, "net_buy": nb})
            except (KeyError, ValueError, TypeError):
                continue
        out.sort(key=lambda x: x["trade_date"])
        return out

    # ── 融资融券余额（上交所，stock_margin_sse）──────────────────────────────
    def fetch_margin_balance(self, start_date: str, end_date: str) -> list[dict]:
        """上交所融资融券余额历史（市场汇总），按日期升序。

        来源：ak.stock_margin_sse(start_date, end_date)。
        start/end: YYYYMMDD。文档列含 信用交易日期/融资余额/融券余额/融资融券余额。

        Returns:
            list[dict]，每条含: trade_date(date), margin_balance(元|None)。
            注：本接口在某些网络环境易被重置连接，失败返回 []。
        """
        df = self._retry_all(
            lambda: ak.stock_margin_sse(start_date=start_date, end_date=end_date)
        )
        if df is None or df.empty:
            return []
        out: list[dict] = []
        for _, r in df.iterrows():
            try:
                d = _parse_iso_date(r.get("信用交易日期") or r.get("日期"))
                if d is None:
                    continue
                mb = _num(r.get("融资融券余额")) or _num(r.get("融资余额"))
                out.append({"trade_date": d, "margin_balance": mb})
            except (KeyError, ValueError, TypeError):
                continue
        out.sort(key=lambda x: x["trade_date"])
        return out

    # ── 中国国债收益率（bond_china_yield）────────────────────────────────────
    def fetch_cn_bond_yield(
        self, start_date: str, end_date: str, tenor: str = "10年"
    ) -> list[dict]:
        """中国国债收益率曲线历史，按日期升序。

        来源：ak.bond_china_yield(start_date, end_date)，曲线名「中债国债收益率曲线」。
        start/end: YYYYMMDD。tenor: 3月/6月/1年/3年/5年/7年/10年/30年。

        Returns:
            list[dict]，每条含: trade_date(date), yield(小数, 0.017=1.7%)。
        """
        df = self._retry_all(
            lambda: ak.bond_china_yield(start_date=start_date, end_date=end_date)
        )
        if df is None or df.empty:
            return []
        if "曲线名称" in df.columns:
            df = df[df["曲线名称"] == "中债国债收益率曲线"]
        out: list[dict] = []
        for _, r in df.iterrows():
            try:
                d = _parse_iso_date(r.get("日期"))
                if d is None:
                    continue
                y = _num(r.get(tenor))
                out.append({
                    "trade_date": d,
                    "yield": (y / 100.0) if y is not None else None,
                })
            except (KeyError, ValueError, TypeError):
                continue
        out.sort(key=lambda x: x["trade_date"])
        return out

    # ── 股指期货主力连续（futures_main_sina，升贴水用）──────────────────────
    def fetch_index_futures_main(
        self, code: str = "IF0", days: int = 30
    ) -> list[dict]:
        """股指期货主力连续合约日线（新浪），按日期升序。

        来源：ak.futures_main_sina(symbol, start_date, end_date)。
        code: ``IF0`` 沪深300 / ``IH0`` 上证50 / ``IC0`` 中证500 / ``IM0`` 中证1000。

        Returns:
            list[dict]，每条含 trade_date(date), close(float)。
        """
        from datetime import date, timedelta
        end = date.today()
        start = end - timedelta(days=days + 30)
        df = self._retry_all(
            lambda: ak.futures_main_sina(
                symbol=code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        )
        if df is None or df.empty:
            return []
        out: list[dict] = []
        for _, r in df.iterrows():
            try:
                d = _parse_iso_date(r.get("日期"))
                if d is None:
                    continue
                out.append({"trade_date": d, "close": _num(r.get("收盘价"))})
            except (KeyError, ValueError, TypeError):
                continue
        out.sort(key=lambda x: x["trade_date"])
        return out[-days:] if len(out) > days else out

    # ── 申万一级行业估值快照（sw_index_first_info，legulegu，当天）────────
    def fetch_sw_index_valuation_snapshot(self) -> list[dict]:
        """申万一级 31 个行业的当天估值快照（PE/PB/股息率）。

        来源：ak.sw_index_first_info()，无历史，仅当天。
        用于财务页行业估值参考线（不做历史曲线）。

        Returns:
            list[dict]，每条含:
              sw_code('sw801010'), industry('农林牧渔'),
              company_count, pe_static, pe_ttm, pb, dividend_yield。
            失败返回 []。
        """
        df = self._retry_all(lambda: ak.sw_index_first_info())
        if df is None or df.empty:
            return []
        out: list[dict] = []
        for _, r in df.iterrows():
            try:
                code = str(r["行业代码"]).replace(".SI", "")
                name = str(r["行业名称"]).strip()

                def _f(key):
                    v = r.get(key)
                    try:
                        return float(v) if v is not None else None
                    except (TypeError, ValueError):
                        return None

                out.append({
                    "sw_code": f"sw{code}",
                    "industry": name,
                    "company_count": int(r["成份个数"])
                    if r.get("成份个数") else None,
                    "pe_static": _f("静态市盈率"),
                    "pe_ttm": _f("TTM(滚动)市盈率"),
                    "pb": _f("市净率"),
                    "dividend_yield": _f("静态股息率"),
                })
            except (KeyError, ValueError, TypeError):
                continue
        return out

    # ── A 股个股财务指标（stock_financial_analysis_indicator，新浪、按报告期）──
    def fetch_financials(self, symbol: str) -> list[dict]:
        """
        A 股个股财务质量指标历史（ROE 等），按报告期（季末）。

        来源：ak.stock_financial_analysis_indicator（新浪），返回多期财务指标。
        symbol: sh600000 / sz000001（带前缀，内部转纯 6 位数字）。

        注意：财务数据有披露滞后，调用方做点-in-time 查询时应预留
        report_date <= 决策日 - 60 天，避免用到未公开披露的财报。

        Returns:
            list[dict]，每条含:
              report_date(datetime), roe_weighted, roe_diluted,
              gross_margin, net_margin, debt_ratio（值可能为 None）
        """
        code = self._strip_exchange_prefix(symbol)
        df = self._retry_all(
            lambda: ak.stock_financial_analysis_indicator(
                symbol=code, start_year="2010"
            )
        )
        if df is None or df.empty:
            return []

        out: list[dict] = []
        for _, r in df.iterrows():
            try:
                # 新浪接口日期列为"日期"，ROE 等列名含中文
                td = r.get("日期")
                if hasattr(td, "to_pydatetime"):
                    td = td.to_pydatetime()
                elif isinstance(td, str):
                    td = datetime.strptime(td[:10], "%Y-%m-%d")
                elif isinstance(td, date) and not isinstance(td, datetime):
                    td = datetime(td.year, td.month, td.day)

                def _f(key):
                    v = r.get(key)
                    try:
                        return float(v) if v is not None else None
                    except (TypeError, ValueError):
                        return None

                out.append({
                    "report_date": td,
                    "roe_weighted": _f("加权净资产收益率(%)"),
                    "roe_diluted": _f("摊薄净资产收益率(%)"),
                    "gross_margin": _f("销售毛利率(%)"),
                    "net_margin": _f("销售净利率(%)"),
                    "debt_ratio": _f("资产负债率(%)"),
                })
            except (KeyError, ValueError, TypeError):
                continue
        return out

    # ── H 股个股日线（stock_hk_daily，新浪、英文列、客户端切片）──────────
    def fetch_hk_stock_daily(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """H 股个股日线，长历史。symbol: hk00700 / 00700，存储为纯 5 位。
        走新浪 stock_hk_daily：无日期参数，返回全量后客户端切片。"""
        code = self._strip_hk_prefix(symbol)
        try:
            df = ak.stock_hk_daily(symbol=code, adjust="qfq")
        except Exception:
            return []
        if df is None or df.empty:
            return []
        bars = self._df_to_en_bars(df, code, market="HK")
        return self._slice_bars(bars, start_date, end_date)

    # ── 全球指数日线（美股 / 港股，新浪源，英文列）──────────────────────
    # 复用 index_ohlcv 表，用 market 列区分（US_INDEX / HK_INDEX），
    # 与现有 SW / INDEX 的 market 列约定一致，前端按 symbol 区分。
    _GLOBAL_INDEX_MAP = {
        # symbol(stored) → (akshare symbol, market, display name)
        "US.DJI": (".DJI", "US_INDEX", "道琼斯"),
        "US.IXIC": (".IXIC", "US_INDEX", "纳斯达克"),
        "US.INX": (".INX", "US_INDEX", "标普500"),
        "HK.HSI": ("HSI", "HK_INDEX", "恒生指数"),
        "HK.HSCEI": ("HSCEI", "HK_INDEX", "国企指数"),
    }

    def fetch_global_index_daily(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """美股/港股指数日线（新浪 index_us_stock_sina / stock_hk_index_daily_sina）。

        symbol 为存储符号（US.DJI / HK.HSI …，带市场前缀以与 A 股 sh/sz 区分）。
        返回英文列 bar，market 置为 US_INDEX / HK_INDEX，存入 index_ohlcv。
        新浪源无日期参数，返回全量（~2004 至今）后客户端切片。
        """
        meta = self._GLOBAL_INDEX_MAP.get(symbol)
        if not meta:
            return []
        ak_sym, market, _name = meta
        fn = (
            (lambda: ak.index_us_stock_sina(symbol=ak_sym))
            if market == "US_INDEX"
            else (lambda: ak.stock_hk_index_daily_sina(symbol=ak_sym))
        )
        try:
            df = self._retry_all(fn)
        except Exception:
            return []
        if df is None or df.empty:
            return []
        bars = self._df_to_en_bars(df, symbol, market=market)
        return self._slice_bars(bars, start_date, end_date)

    @staticmethod
    def global_index_market(symbol: str) -> str:
        """存储符号 → market 列值（前端/仓储按 market 区分资产域）。未知返回 INDEX。"""
        meta = AkshareProvider._GLOBAL_INDEX_MAP.get(symbol)
        return meta[1] if meta else "INDEX"

    @staticmethod
    def supported_global_indices() -> list[str]:
        """返回所有受支持的全球指数存储符号。"""
        return list(AkshareProvider._GLOBAL_INDEX_MAP.keys())

    # ── 宏观经济指标（macro_china_* / macro_usa_*，中文/混合列，归一化）──
    # 每个指标由一个 (akshare 调用, 列提取函数) 描述。返回统一三元组列表
    # [(report_date: date, value: float, freq, unit)]，由调用方 upsert。
    # 注：akshare 返回排序不一致（部分降序、部分升序），统一按 report_date 升序返回。

    @staticmethod
    def _parse_cn_month(s: str):
        """'2008年01月份' / '202604' / '2026-06' → date(月初)。

        akshare 中文宏观月份列格式混杂：
          - CPI/PPI/PMI/M2: '2008年01月份'
          - 社融: '202604' (YYYYMM)
          - LPR: 已是日期列
        返回该月 1 号的 date；解析失败返回 None。
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
        # YYYYMM（如 202604）
        if re.match(r"^\d{6}$", s):
            y, mo = int(s[:4]), int(s[4:6])
            if 1 <= mo <= 12:
                return date(y, mo, 1)
        return None

    def fetch_macro_series(self, code: str) -> list[tuple]:
        """拉取单个宏观经济指标的全量历史，归一化为
        [(report_date, value, freq, unit), ...]（report_date 升序）。

        code 见 _MACRO_EXTRACTORS 注册表（cn_cpi_yoy / cn_pmi / cn_m2_yoy /
        cn_sf / cn_lpr_1y / us_cpi_yoy / us_ism_pmi / us_unemp / us_core_pce …）。
        网络异常或解析失败返回 []（与 fetch_* 约定一致，不抛错以不阻塞批量同步）。
        """
        extractor = self._MACRO_EXTRACTORS.get(code)
        if not extractor:
            return []
        try:
            df = self._retry_all(extractor["fn"])
        except Exception:
            return []
        if df is None or df.empty:
            return []
        out: list[tuple] = []
        for _, r in df.iterrows():
            try:
                d, v = extractor["pick"](r)
                if d is None or v is None or (isinstance(v, float) and pd.isna(v)):
                    continue
                out.append((d, float(v), extractor["freq"], extractor["unit"]))
            except (KeyError, ValueError, TypeError):
                continue
        out.sort(key=lambda x: x[0])
        return out

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

    # 各指标的 akshare 调用 + 列提取器（pick(row) -> (date, value|None)）。
    # pick 对"尚未发布的预测行"（现值 nan）返回 None 以跳过。
    _MACRO_EXTRACTORS = {
        # ── 中国 ──
        "cn_cpi_yoy": {
            "fn": lambda: ak.macro_china_cpi(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("全国-同比增长")),
            ),
            "freq": "month", "unit": "%",
        },
        "cn_ppi_yoy": {
            "fn": lambda: ak.macro_china_ppi(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("当月同比增长")),
            ),
            "freq": "month", "unit": "%",
        },
        "cn_pmi": {
            "fn": lambda: ak.macro_china_pmi(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("制造业-指数")),
            ),
            "freq": "month", "unit": "",
        },
        "cn_m2_yoy": {
            "fn": lambda: ak.macro_china_money_supply(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("货币和准货币(M2)-同比增长")),
            ),
            "freq": "month", "unit": "%",
        },
        "cn_sf": {  # 社会融资规模增量（亿元）
            "fn": lambda: ak.macro_china_shrzgm(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("社会融资规模增量")),
            ),
            "freq": "month", "unit": "亿元",
        },
        "cn_lpr_1y": {  # 1 年期 LPR（%），日频
            "fn": lambda: ak.macro_china_lpr(),
            "pick": lambda r: (
                _parse_iso_date(r.get("TRADE_DATE")),
                _num(r.get("LPR1Y")),
            ),
            "freq": "day", "unit": "%",
        },
        "cn_m1_yoy": {
            "fn": lambda: ak.macro_china_money_supply(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("货币(M1)-同比增长")),
            ),
            "freq": "month", "unit": "%",
        },
        "cn_retail_yoy": {
            "fn": lambda: ak.macro_china_consumer_goods_retail(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("同比增长")),
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
        # ── 固投 / 地产开发投资（macro_china_gdzctz，实测列名）──
        # 实测真实列 ['月份','当月','同比增长','环比增长','自年初累计']。
        # cn_fai_yoy 取 "同比增长"。设计文档预期的地产投资列
        # "当月-房地产开发投资-同比增长" 当前接口已不存在，故
        # cn_realestate_inv_yoy 在线增量恒空，历史值由 cn_fai.csv 种子补
        # （B 档"尽力增量"语义）。
        "cn_fai_yoy": {
            "fn": lambda: ak.macro_china_gdzctz(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("同比增长")),
            ),
            "freq": "month", "unit": "%",
        },
        "cn_realestate_inv_yoy": {
            # macro_china_gdzctz 只有整体固投增速，不含房地产开发投资分项。
            # 该指标保留在 config 里（前端展示），数据靠 CSV 种子或手动补。
            "fn": lambda: ak.macro_china_gdzctz(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                None,   # 无可用列，返回 None 跳过
            ),
            "freq": "month", "unit": "%",
        },
        "cn_industrial_profit_yoy": {
            # 规上工业企业利润同比（macro_china_gyzjz，203 期历史）
            "fn": lambda: ak.macro_china_gyzjz(),
            "pick": lambda r: (
                AkshareProvider._parse_cn_month(r.get("月份")),
                _num(r.get("同比增长")),
            ),
            "freq": "month", "unit": "%",
        },
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
        # ── 美国 ──
        "us_cpi_yoy": {
            "fn": lambda: ak.macro_usa_cpi_yoy(),
            "pick": lambda r: (
                _parse_iso_date(r.get("时间")),
                _num(r.get("现值")),
            ),
            "freq": "month", "unit": "%",
        },
        "us_ism_pmi": {
            "fn": lambda: ak.macro_usa_ism_pmi(),
            "pick": lambda r: (
                _parse_iso_date(r.get("日期")),
                _num(r.get("今值")),
            ),
            "freq": "month", "unit": "",
        },
        "us_unemp": {
            "fn": lambda: ak.macro_usa_unemployment_rate(),
            "pick": lambda r: (
                _parse_iso_date(r.get("日期")),
                _num(r.get("今值")),
            ),
            "freq": "month", "unit": "%",
        },
        "us_core_pce": {
            "fn": lambda: ak.macro_usa_core_pce_price(),
            "pick": lambda r: (
                _parse_iso_date(r.get("日期")),
                _num(r.get("今值")),
            ),
            "freq": "month", "unit": "%",
        },
    }

    @staticmethod
    def _df_to_en_bars(
        df: pd.DataFrame, symbol: str, market: str, interval: str = "1d"
    ) -> list[OHLCVBar]:
        """英文列 DataFrame（date/open/high/low/close/volume/amount）→ OHLCVBar。"""
        bars: list[OHLCVBar] = []
        for _, r in df.iterrows():
            try:
                t = r["date"]
                if hasattr(t, "to_pydatetime"):
                    t = t.to_pydatetime()
                elif isinstance(t, str):
                    t = datetime.strptime(t[:10], "%Y-%m-%d")
                elif isinstance(t, date) and not isinstance(t, datetime):
                    t = datetime(t.year, t.month, t.day)
                bars.append(
                    OHLCVBar(
                        symbol=symbol,
                        trade_time=t,
                        open_=float(r["open"]),
                        close_=float(r["close"]),
                        high_=float(r["high"]),
                        low_=float(r["low"]),
                        volume=float(r["volume"]),
                        amount=float(r.get("amount", 0.0) or 0.0),
                        interval=interval,
                        market=market,
                        provider="akshare",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return bars

    @staticmethod
    def _slice_bars(
        bars: list[OHLCVBar],
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> list[OHLCVBar]:
        """按 ISO 日期对 bar 列表做闭区间切片。"""
        sd = datetime.strptime(start_date[:10], "%Y-%m-%d").date() if start_date else None
        ed = datetime.strptime(end_date[:10], "%Y-%m-%d").date() if end_date else None
        out = []
        for b in bars:
            d = b.trade_time.date() if isinstance(b.trade_time, datetime) else b.trade_time
            if sd and d < sd:
                continue
            if ed and d > ed:
                continue
            out.append(b)
        return out

    # ── A 股 / H 股 分钟线（客户端切片，5/15/30/60m）────────────────────
    _MIN_PERIOD = {"5m": "5", "15m": "15", "30m": "30", "60m": "60"}

    @staticmethod
    def _retry(fn, *, retries: int = 4, base_delay: float = 1.5):
        """东财 push2his 会 flapping（时通时断 RemoteDisconnected），重试+退避提升成功率。"""
        import time
        for attempt in range(retries):
            try:
                return fn()
            except Exception as e:
                # 仅对连接类异常重试；其他直接抛
                if attempt == retries - 1 or "Connection" not in type(e).__name__:
                    raise
                time.sleep(base_delay * (2 ** attempt))
        return None

    @staticmethod
    def _retry_all(fn, *, retries: int = 3, base_delay: float = 2.0):
        """
        对所有异常重试（基本面接口用）。
        akshare 基本面接口(估值/财务)会因限流/超时/临时故障抛各类异常，
        简单重试+指数退避能显著提升全市场同步成功率。
        返回 fn() 的结果；全部失败返回 None。
        """
        import time
        for attempt in range(retries):
            try:
                return fn()
            except Exception:
                if attempt == retries - 1:
                    return None
                time.sleep(base_delay * (2 ** attempt))
        return None

    def fetch_a_stock_minute(
        self,
        symbol: str,
        interval: str = "5m",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """A 股分钟线。单次返回全部历史后按 [start,end] 客户端切片。
        1 分钟不可用（eastmoney ndays=5 限制），仅 5/15/30/60m。"""
        period = self._MIN_PERIOD.get(interval)
        if not period:
            return []
        code = self._strip_exchange_prefix(symbol)
        kwargs = {"symbol": code, "period": period, "adjust": "qfq"}
        if start_date:
            kwargs["start_date"] = f"{start_date[:10]} 09:30:00"
        if end_date:
            kwargs["end_date"] = f"{end_date[:10]} 15:00:00"
        try:
            df = self._retry(lambda: ak.stock_zh_a_hist_min_em(**kwargs))
        except Exception:
            return []
        if df is None or df.empty:
            return []
        return self._df_to_minute_bars(df, symbol, interval, market="A")

    def fetch_hk_stock_minute(
        self,
        symbol: str,
        interval: str = "5m",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """H 股分钟线，语义同 fetch_a_stock_minute。"""
        period = self._MIN_PERIOD.get(interval)
        if not period:
            return []
        code = self._strip_hk_prefix(symbol)
        kwargs = {"symbol": code, "period": period, "adjust": "qfq"}
        if start_date:
            kwargs["start_date"] = f"{start_date[:10]} 09:30:00"
        if end_date:
            kwargs["end_date"] = f"{end_date[:10]} 16:00:00"
        try:
            df = self._retry(lambda: ak.stock_hk_hist_min_em(**kwargs))
        except Exception:
            return []
        if df is None or df.empty:
            return []
        return self._df_to_minute_bars(df, code, interval, market="HK")

    @staticmethod
    def _df_to_minute_bars(
        df: pd.DataFrame, symbol: str, interval: str, market: str
    ) -> list[OHLCVBar]:
        """分钟线中文列 DataFrame → OHLCVBar（stock_zh_a_hist_min_em 列序）。"""
        bars: list[OHLCVBar] = []
        for _, r in df.iterrows():
            try:
                t = r["时间"]
                if isinstance(t, str):
                    t = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
                bars.append(
                    OHLCVBar(
                        symbol=symbol,
                        trade_time=t,
                        open_=float(r["开盘"]),
                        close_=float(r["收盘"]),
                        high_=float(r["最高"]),
                        low_=float(r["最低"]),
                        volume=float(r["成交量"]),
                        amount=float(r["成交额"]),
                        interval=interval,
                        market=market,
                        provider="akshare",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return bars

    # ── A 股指数日线（新浪源为主，腾讯源兜底，客户端日期切片）──────────────
    def fetch_index_daily(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """A 股指数日线（上证综指/沪深300/创业板指 等）。

        主走新浪 stock_zh_index_daily：返回全量历史（~2002 至今），列
        date/open/high/low/close/volume（无 amount，填 0）。客户端按日期切片。
        注：东财 stock_zh_index_daily_em / index_zh_a_hist 的 push2his 端点在本
        环境被稳定阻断（RemoteDisconnected），故改用新浪源。

        部分中证指数（如 sh000985 中证全指）新浪源存在数据断层（仅到 2016），
        此时自动 fallback 到腾讯 stock_zh_index_daily_tx（列
        date/open/close/high/low/amount，覆盖到最新）。

        申万行业指数（symbol 以 sw 开头，如 sw801010）委托给 fetch_sw_index_daily
        （走 index_hist_sw，swsresearch.com 源）。
        """
        if symbol.lower().startswith("sw"):
            return self.fetch_sw_index_daily(symbol, start_date, end_date)

        bars = self._fetch_index_daily_sina(symbol)

        # 新浪源数据不完整（空 / 最新日期过早，疑似断层）→ 腾讯源兜底
        today = date.today()
        latest = max((b.trade_time.date() for b in bars), default=date.min)
        if not bars or (today - latest).days > 30:
            tx_bars = self._fetch_index_daily_tencent(symbol)
            # 取数据量更多的一方
            if len(tx_bars) > len(bars):
                bars = tx_bars

        # 客户端按日期切片（新浪/腾讯源均不支持服务端日期参数）
        if start_date:
            sd = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
            bars = [b for b in bars if b.trade_time.date() >= sd]
        if end_date:
            ed = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
            bars = [b for b in bars if b.trade_time.date() <= ed]
        return bars

    def _fetch_index_daily_sina(self, symbol: str) -> list[OHLCVBar]:
        """新浪 stock_zh_index_daily → OHLCVBar（列 date/open/high/low/close/volume）。"""
        try:
            df = self._retry(lambda: ak.stock_zh_index_daily(symbol=symbol))
        except Exception:
            return []
        if df is None or df.empty:
            return []
        bars: list[OHLCVBar] = []
        for _, r in df.iterrows():
            try:
                d = r["date"]
                if isinstance(d, str):
                    d = datetime.strptime(d[:10], "%Y-%m-%d").date()
                elif isinstance(d, datetime):
                    d = d.date()
                bars.append(
                    OHLCVBar(
                        symbol=symbol,
                        trade_time=datetime(d.year, d.month, d.day),
                        open_=float(r["open"]),
                        close_=float(r["close"]),
                        high_=float(r["high"]),
                        low_=float(r["low"]),
                        volume=float(r["volume"]),
                        amount=0.0,
                        interval="1d",
                        market="INDEX",
                        provider="akshare",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return bars

    def _fetch_index_daily_tencent(self, symbol: str) -> list[OHLCVBar]:
        """腾讯 stock_zh_index_daily_tx → OHLCVBar（列 date/open/close/high/low/amount）。

        用于中证全指等新浪源数据断层的指数；中证2000 等腾讯未收录的会返回空。
        """
        try:
            df = self._retry(lambda: ak.stock_zh_index_daily_tx(symbol=symbol))
        except Exception:
            return []
        if df is None or df.empty:
            return []
        bars: list[OHLCVBar] = []
        for _, r in df.iterrows():
            try:
                d = r["date"]
                if isinstance(d, str):
                    d = datetime.strptime(d[:10], "%Y-%m-%d").date()
                elif isinstance(d, datetime):
                    d = d.date()
                bars.append(
                    OHLCVBar(
                        symbol=symbol,
                        trade_time=datetime(d.year, d.month, d.day),
                        open_=float(r["open"]),
                        close_=float(r["close"]),
                        high_=float(r["high"]),
                        low_=float(r["low"]),
                        volume=0.0,
                        amount=float(r.get("amount", 0.0) or 0.0),
                        interval="1d",
                        market="INDEX",
                        provider="tencent",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return bars

    # ── 申万一级行业指数日线（index_hist_sw，swsresearch.com 源）────────────
    def fetch_sw_index_daily(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """申万一级行业指数日线（801010 农林牧渔 / 801030 化工 / 801150 医药生物 ...）。

        走 index_hist_sw（swsresearch.com，非东财）：返回全量历史（~1999 至今），
        中文列 代码/日期/收盘/开盘/最高/最低/成交量/成交额。客户端按日期切片。
        symbol 传纯 6 位（如 801010），存储为 sw801010，market='SW'。
        """
        code = symbol[2:] if symbol.lower().startswith("sw") else symbol  # sw801010 → 801010
        try:
            df = self._retry(lambda: ak.index_hist_sw(symbol=code, period="day"))
        except Exception:
            return []
        if df is None or df.empty:
            return []
        stored = f"sw{code}"
        bars: list[OHLCVBar] = []
        for _, r in df.iterrows():
            try:
                d = r["日期"]
                if isinstance(d, str):
                    d = datetime.strptime(d[:10], "%Y-%m-%d").date()
                elif isinstance(d, datetime):
                    d = d.date()
                bars.append(
                    OHLCVBar(
                        symbol=stored,
                        trade_time=datetime(d.year, d.month, d.day),
                        open_=float(r["开盘"]),
                        close_=float(r["收盘"]),
                        high_=float(r["最高"]),
                        low_=float(r["最低"]),
                        volume=float(r["成交量"]),
                        amount=float(r["成交额"]),
                        interval="1d",
                        market="SW",
                        provider="akshare",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        if start_date:
            bars = [b for b in bars if b.trade_time.date() >= datetime.strptime(start_date[:10], "%Y-%m-%d").date()]
        if end_date:
            bars = [b for b in bars if b.trade_time.date() <= datetime.strptime(end_date[:10], "%Y-%m-%d").date()]
        return bars

    # ── 贵金属 / 原油日线（futures_foreign_hist，客户端切片）──────────────
    _COMMODITY_CLASS = {
        "XAU": "metal", "XAG": "metal", "XPT": "metal", "XPD": "metal",
        "GC": "metal", "SI": "metal",
        "OIL": "energy", "CL": "energy", "NG": "energy",
    }

    def fetch_commodity_daily(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """贵金属/原油日线。futures_foreign_hist 返回全量~10y，按日期切片。
        返回 market='CMD'，asset_class 通过 _COMMODITY_CLASS 查表（写入时由 job 附加）。"""
        try:
            df = ak.futures_foreign_hist(symbol=symbol)
        except Exception:
            return []
        if df is None or df.empty:
            return []
        bars: list[OHLCVBar] = []
        for _, r in df.iterrows():
            try:
                d = r["date"]
                if isinstance(d, str):
                    d = datetime.strptime(d[:10], "%Y-%m-%d")
                bars.append(
                    OHLCVBar(
                        symbol=symbol,
                        trade_time=d,
                        open_=float(r["open"]),
                        close_=float(r["close"]),
                        high_=float(r["high"]),
                        low_=float(r["low"]),
                        volume=float(r["volume"]),
                        amount=0.0,
                        interval="1d",
                        market="CMD",
                        provider="akshare",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        # 客户端按日期切片
        if start_date:
            bars = [b for b in bars if b.trade_time.date() >= datetime.strptime(start_date[:10], "%Y-%m-%d").date()]
        if end_date:
            bars = [b for b in bars if b.trade_time.date() <= datetime.strptime(end_date[:10], "%Y-%m-%d").date()]
        return bars

    # ── 货币日线（currency_boc_sina，中行折算价 close-only）──────────────
    # 东财 forex_hist_em 在本环境不可达；改走新浪中行汇率（仅 CNY 对，close-only）。
    # cross/offshore 对（EURUSD/USDCNH 等）需东财或 tushare，本环境暂不支持。
    _FX_BOC_SYMBOL = {
        "USDCNY": "美元", "EURCNY": "欧元", "JPYCNY": "日元",
        "GBPCNY": "英镑", "HKDCNY": "港币", "AUDCNY": "澳大利亚元",
        "SGDCNY": "新加坡元", "CADCNY": "加拿大元", "NZDCNY": "新西兰元",
    }

    def fetch_fx_ohlc(
        self,
        pair: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """货币对日线（close-only：open=high=low=close=中行折算价/100，无成交量）。
        pair: USDCNY/EURCNY/JPYCNY/GBPCNY/HKDCNY ...（仅 CNY 对）。"""
        boc_sym = self._FX_BOC_SYMBOL.get(pair)
        if not boc_sym:
            return []
        kwargs = {"symbol": boc_sym}
        if start_date:
            kwargs["start_date"] = self._to_yyyymmdd(start_date)
        if end_date:
            kwargs["end_date"] = self._to_yyyymmdd(end_date)
        try:
            df = ak.currency_boc_sina(**kwargs)
        except Exception:
            return []
        if df is None or df.empty:
            return []
        bars: list[OHLCVBar] = []
        for _, r in df.iterrows():
            try:
                d = r["日期"]
                if not isinstance(d, date):
                    d = datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
                rate = float(r["中行折算价"]) / 100.0
                bars.append(
                    OHLCVBar(
                        symbol=pair,
                        trade_time=datetime(d.year, d.month, d.day),
                        open_=rate, close_=rate, high_=rate, low_=rate,
                        volume=0.0, amount=0.0,
                        interval="1d", market="FX", provider="akshare",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return bars

    # ── 标的清单 ─────────────────────────────────────────────────────────
    def get_a_stock_list(self) -> list[str]:
        """A 股全市场（沪深京北），返回带前缀 symbol [sh600000, sz000001, bj430047 ...]。
        走新浪 stock_zh_a_spot（东财 spot_em 本环境不可达）。stock_zh_a_spot 的 代码 列
        已带 sh/sz/bj 前缀，直接用；纯数字则按规则补前缀。"""
        try:
            df = ak.stock_zh_a_spot()
        except Exception:
            return []
        if df is None or df.empty:
            return []
        code_col = next((c for c in df.columns if "代码" in c), None)
        if not code_col:
            return []
        out: list[str] = []
        for code in df[code_col].astype(str):
            c = code.strip().lower()
            if _A_PREFIX_RE.match(c) or c.startswith("bj"):
                out.append(c)                       # 已带前缀
            elif c.isdigit() and len(c) == 6:
                if c.startswith("6") or c.startswith("5") or c.startswith("9"):
                    out.append(f"sh{c}")
                elif c.startswith("00") or c.startswith("30"):
                    out.append(f"sz{c}")
                elif c.startswith("8") or c.startswith("4"):
                    out.append(f"bj{c}")
        return out

    def get_etf_list(self) -> list[str]:
        """A 股全市场 ETF，返回带前缀 symbol [sh510300, sz159934 ...]。
        走新浪 fund_etf_category_sina（东财 spot_em 本环境不可达）。其 代码 列已带
        sh/sz 前缀，直接用；纯数字则按规则补前缀。"""
        try:
            df = ak.fund_etf_category_sina(symbol="ETF基金")
        except Exception:
            return []
        if df is None or df.empty:
            return []
        code_col = next((c for c in df.columns if "代码" in c), None)
        if not code_col:
            return []
        out: list[str] = []
        for code in df[code_col].astype(str):
            c = code.strip().lower()
            if _A_PREFIX_RE.match(c):
                out.append(c)                       # 已带前缀
            elif c.isdigit() and len(c) == 6:
                out.append(f"sh{c}" if c.startswith(("5", "6")) else f"sz{c}")
        return out

    def get_hk_stock_list(self) -> list[str]:
        """H 股全市场，返回纯 5 位代码 [00700, 09988 ...]（与库内存储一致）。
        走新浪 stock_hk_spot（东财 spot_em 本环境不可达，较慢，~99 页）。
        代码列可能为纯数字或带 hk 前缀，统一归一到纯 5 位。"""
        try:
            df = ak.stock_hk_spot()
        except Exception:
            return []
        if df is None or df.empty:
            return []
        code_col = next((c for c in df.columns if "代码" in c), None)
        if not code_col:
            return []
        out: list[str] = []
        for code in df[code_col].astype(str):
            c = code.strip().lower()
            if c.startswith("hk"):
                c = c[2:]
            if c.isdigit():
                out.append(c.zfill(5))
        return out

    # ── 日期范围分派（供 SyncService.backfill_range 通用调用）────────────
    _COMMODITY_CODES = {"XAU", "XAG", "XPT", "XPD", "GC", "SI", "OIL", "CL", "NG"}

    def fetch_daily_range(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """按 symbol 模式分派到具体 akshare 日线接口。"""
        s = symbol.upper()
        # 商品（贵金属/原油）
        if s in self._COMMODITY_CODES:
            return self.fetch_commodity_daily(symbol, start_date, end_date)
        # 货币对（6 位大写，如 USDCNH/EURUSD）
        if len(s) == 6 and s.isalpha():
            return self.fetch_fx_ohlc(symbol, start_date, end_date)
        # 美股（1-5 位大写，非商品）
        if _US_TICKER_RE.match(symbol):
            return self._fetch_us(symbol, start_date, end_date)
        # H 股（纯 5 位数字或 hk 前缀）
        raw = self._strip_hk_prefix(symbol)
        if raw.isdigit() and len(raw) == 5:
            return self.fetch_hk_stock_daily(symbol, start_date, end_date)
        # A 股 ETF（sh5xxxx / sz159xxx）
        if _A_PREFIX_RE.match(symbol):
            code = self._strip_exchange_prefix(symbol)
            if code.startswith("5") or code.startswith("6") or code.startswith("159"):
                return self._fetch_a_etf(symbol, start_date, end_date)
            return self._fetch_a_etf(symbol, start_date, end_date)
        # A 股个股
        return self.fetch_a_stock_daily(symbol, start_date, end_date)

    def fetch_minute_range(
        self,
        symbol: str,
        interval: str = "5m",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[OHLCVBar]:
        """按 symbol 分派 A 股 / H 股分钟线。商品/货币/美股无分钟线。"""
        raw_hk = self._strip_hk_prefix(symbol)
        if raw_hk.isdigit() and len(raw_hk) == 5:
            return self.fetch_hk_stock_minute(symbol, interval, start_date, end_date)
        return self.fetch_a_stock_minute(symbol, interval, start_date, end_date)

    # ════════════════════════════════════════════════════════════════════
    #  全量财务数据（三大报表 + 摘要 + 业绩预告/快报 + 港美股）
    # ════════════════════════════════════════════════════════════════════

    @staticmethod
    def _parse_report_date(v) -> Optional[date]:
        """报告期列归一化：'2026-03-31' / '20260331' / datetime → date。"""
        if v is None:
            return None
        if hasattr(v, "date"):
            return v.date()
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        s = str(v).strip()
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
        if s.isdigit() and len(s) == 8:
            try:
                return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
            except ValueError:
                pass
        return None

    def _fetch_ths_statement(self, symbol: str, fn, statement_type: str) -> list[dict]:
        """同花顺三大表通用拉取（A 股）。fn=akshare接口，返回统一格式 list[dict]。"""
        from src.infra.database.market.financial_full import (
            _STATEMENT_MAPS, pick_metric, compute_derived, parse_amount,
        )
        code = self._strip_exchange_prefix(symbol)
        try:
            df = self._retry_all(lambda: fn(symbol=code))
        except Exception:
            return []
        if df is None or df.empty:
            return []
        metric_map = _STATEMENT_MAPS.get(statement_type, {})
        out: list[dict] = []
        for _, r in df.iterrows():
            row = r.to_dict()
            rd = self._parse_report_date(row.get("报告期"))
            if rd is None:
                continue
            d: dict = {"symbol": symbol, "report_date": rd,
                       "statement_type": statement_type, "market": "A"}
            for field, keys in metric_map.items():
                d[field] = pick_metric(row, keys)
            compute_derived(d)
            d["detail"] = {k: parse_amount(v) for k, v in row.items() if k != "报告期"}
            out.append(d)
        out.sort(key=lambda x: x["report_date"])
        return out

    def fetch_income_statement(self, symbol: str) -> list[dict]:
        """A 股利润表（stock_financial_benefit_ths，47 科目）。"""
        return self._fetch_ths_statement(symbol, ak.stock_financial_benefit_ths, "income")

    def fetch_balance_sheet(self, symbol: str) -> list[dict]:
        """A 股资产负债表（stock_financial_debt_ths，76 科目）。"""
        return self._fetch_ths_statement(symbol, ak.stock_financial_debt_ths, "balance")

    def fetch_cash_flow(self, symbol: str) -> list[dict]:
        """A 股现金流量表（stock_financial_cash_ths，72 科目）。"""
        return self._fetch_ths_statement(symbol, ak.stock_financial_cash_ths, "cashflow")

    def fetch_financial_abstract(self, symbol: str) -> list[dict]:
        """A 股财务摘要（stock_financial_abstract，东财横表 pivot 为纵表）。"""
        from src.infra.database.market.financial_full import (
            _INCOME_MAP, _BALANCE_MAP, _CASHFLOW_MAP, pick_metric, compute_derived,
            parse_amount,
        )
        code = self._strip_exchange_prefix(symbol)
        try:
            df = self._retry_all(lambda: ak.stock_financial_abstract(symbol=code))
        except Exception:
            return []
        if df is None or df.empty:
            return []
        report_cols = [c for c in df.columns if c not in ("选项", "指标")]
        out: list[dict] = []
        for col in report_cols:
            rd = self._parse_report_date(col)
            if rd is None:
                continue
            sub = df[df[col].notna()]
            if sub.empty:
                continue
            detail = {}
            for _, r in sub.iterrows():
                mn = str(r.get("指标", "")).strip()
                if mn:
                    detail[mn] = parse_amount(r[col])
            if not detail:
                continue
            d: dict = {"symbol": symbol, "report_date": rd,
                       "statement_type": "abstract", "market": "A", "detail": detail}
            for field, keys in {**_INCOME_MAP, **_BALANCE_MAP, **_CASHFLOW_MAP}.items():
                d[field] = pick_metric(detail, keys)
            compute_derived(d)
            out.append(d)
        out.sort(key=lambda x: x["report_date"])
        return out

    def fetch_hk_financial(self, symbol: str) -> list[dict]:
        """港股三大报表（stock_financial_hk_report_em，东财长表 pivot 为宽表）。"""
        from src.infra.database.market.financial_full import (
            _HK_STATEMENT_MAPS, pick_metric, compute_derived, parse_amount,
        )
        raw = self._strip_hk_prefix(symbol)
        code = raw.zfill(5) if raw.isdigit() else symbol
        type_map = {"income": "利润表", "balance": "资产负债表", "cashflow": "现金流量表"}
        out: list[dict] = []
        for st_type, em_label in type_map.items():
            try:
                df = self._retry_all(
                    lambda lbl=em_label: ak.stock_financial_hk_report_em(
                        stock=code, symbol=lbl, indicator="报告期"))
            except Exception:
                continue
            if df is None or df.empty:
                continue
            for rd_str, grp in df.groupby("REPORT_DATE"):
                rd = self._parse_report_date(rd_str)
                if rd is None:
                    continue
                row = {}
                for _, r in grp.iterrows():
                    name = str(r.get("STD_ITEM_NAME", "")).strip()
                    if name:
                        row[name] = parse_amount(r.get("AMOUNT"))
                d: dict = {"symbol": code, "report_date": rd,
                           "statement_type": st_type, "market": "HK", "detail": row}
                # P2: 港股专用科目映射（营业额/溢利/开支，与 A 股口径不同）
                for field, keys in _HK_STATEMENT_MAPS.get(st_type, {}).items():
                    d[field] = pick_metric(row, keys)
                compute_derived(d)
                out.append(d)
        out.sort(key=lambda x: (x["report_date"], x["statement_type"]))
        return out

    def fetch_us_financial(self, symbol: str) -> list[dict]:
        """美股三大报表（stock_financial_us_report_em，东财宽表）。"""
        from src.infra.database.market.financial_full import (
            _STATEMENT_MAPS, pick_metric, compute_derived, parse_amount,
        )
        type_map = {"income": "综合损益表", "balance": "资产负债表", "cashflow": "现金流量表"}
        out: list[dict] = []
        for st_type, em_label in type_map.items():
            try:
                df = self._retry_all(
                    lambda lbl=em_label: ak.stock_financial_us_report_em(
                        stock=symbol, symbol=lbl, indicator="年报"))
            except Exception:
                continue
            if df is None or df.empty:
                continue
            for _, r in df.iterrows():
                row = r.to_dict()
                rd = (self._parse_report_date(row.get("REPORT_DATE"))
                      or self._parse_report_date(row.get("报告日期"))
                      or self._parse_report_date(row.get("报告期")))
                if rd is None:
                    continue
                d: dict = {"symbol": symbol, "report_date": rd,
                           "statement_type": st_type, "market": "US",
                           "detail": {k: parse_amount(v) for k, v in row.items()}}
                for field, keys in _STATEMENT_MAPS.get(st_type, {}).items():
                    d[field] = pick_metric(row, keys)
                compute_derived(d)
                out.append(d)
        out.sort(key=lambda x: (x["report_date"], x["statement_type"]))
        return out

    def fetch_earnings_batch(self, report_date: str) -> dict:
        """业绩预告 + 业绩快报（全市场批量，按报告期 date）。"""
        d = str(report_date).replace("-", "")
        result: dict = {"preannounce": [], "express": []}
        # 业绩预告 stock_yjyg_em
        try:
            df = self._retry_all(lambda: ak.stock_yjyg_em(date=d))
        except Exception:
            df = None
        if df is not None and not df.empty:
            rd = self._parse_report_date(d)
            for _, r in df.iterrows():
                row = r.to_dict()
                announce = self._parse_report_date(row.get("公告日期"))
                result["preannounce"].append({
                    "symbol": str(row.get("股票代码", "")).strip(),
                    "forecast_type": "preannounce", "report_date": rd,
                    "metric": str(row.get("预测指标", "")).strip(),
                    "company_name": row.get("股票简称"), "announce_date": announce,
                    "forecast_value": _num(row.get("预测数值")),
                    "change_pct": _num(row.get("业绩变动幅度")),
                    "prev_value": _num(row.get("上年同期值")),
                    "forecast_type_label": row.get("预告类型"),
                    "raw": {k: v for k, v in row.items()},
                })
        # 业绩快报 stock_yjbb_em
        try:
            df = self._retry_all(lambda: ak.stock_yjbb_em(date=d))
        except Exception:
            df = None
        if df is not None and not df.empty:
            rd = self._parse_report_date(d)
            for _, r in df.iterrows():
                row = r.to_dict()
                announce = self._parse_report_date(row.get("最新公告日期"))
                result["express"].append({
                    "symbol": str(row.get("股票代码", "")).strip(),
                    "forecast_type": "express", "report_date": rd, "metric": "",
                    "company_name": row.get("股票简称"), "announce_date": announce,
                    "revenue": _num(row.get("营业总收入-营业总收入")),
                    "net_profit": _num(row.get("净利润-净利润")),
                    "roe": _num(row.get("净资产收益率")),
                    "eps": _num(row.get("每股收益")),
                    "raw": {k: v for k, v in row.items()},
                })
        return result

    # ── 机构调研/研报纪要(财报雷达景气文本源,Task 11)──────────────
    # Step 1 探测:akshare 1.18.50 中无 survey/diaoyan 命名接口;
    # stock_jgdy_detail_em 仅支持全市场按日期拉取(千页级、易中途失败),
    # 个股口径可用的是东财个股研报接口 stock_research_report_em(symbol=...)。
    _SURVEY_FN = "stock_research_report_em"

    def fetch_survey(self, symbol: str, months_back: int = 6) -> list[dict]:
        """机构调研/研报纪要文本(防御式):接口缺失/列名差异/异常一律返回 []。

        返回 [{survey_date, org_types, q_a_text}]。
        """
        import akshare as ak
        import datetime as dt
        fn = getattr(ak, self._SURVEY_FN, None)
        if fn is None:
            return []
        try:
            df = self._retry_all(lambda: fn(symbol=symbol))
        except Exception:
            return []
        if df is None or df.empty:
            return []
        cutoff = dt.date.today() - dt.timedelta(days=30 * months_back)
        date_cols = [c for c in df.columns if "日期" in str(c)]
        out = []
        for _, r in df.iterrows():
            row = r.to_dict()
            sd = None
            for c in date_cols:
                v = row.get(c)
                if isinstance(v, (dt.date, dt.datetime)):
                    sd = v.date() if isinstance(v, dt.datetime) else v
                    break
            if sd is None or sd < cutoff:
                continue
            text = "。".join(str(v) for v in row.values()
                            if isinstance(v, str) and len(v) > 8)
            org = next((str(v) for k, v in row.items()
                        if "机构" in str(k) and isinstance(v, str)), "")
            out.append({"survey_date": sd, "org_types": org, "q_a_text": text})
        return out

    # ── 国家队监控：前十大流通股东 + ETF 护盘信号（Task 4）────────────────
    def fetch_top10_float_holders(self, symbol: str, report_date: str) -> list[dict]:
        """拉取某股某报告期前十大流通股东。

        symbol: 股票代码(无前缀,如 600519)
        report_date: YYYYMMDD 或 YYYY-MM-DD
        返回 [{holder_name, hold_shares, hold_value, pct_of_float, ranking}],
            失败返回 []。hold_value = hold_shares × 季末收盘价(取不到则 0)。
        """
        try:
            date_str = str(report_date).replace("-", "")
            # 加交易所前缀:6 开头 sh,0/3 开头 sz
            prefix = "sh" if symbol.startswith("6") else "sz"
            full_sym = f"{prefix}{symbol}"
            df = ak.stock_gdfx_free_top_10_em(symbol=full_sym, date=date_str)
            if df is None or len(df) == 0:
                return []
            # 季末收盘价用于推算持股市值
            close_price = self._report_period_close(full_sym, date_str)
            out = []
            for _, r in df.iterrows():
                holder_name = str(r.get("股东名称", "")).strip()
                if not holder_name:
                    continue
                hold_shares = _num(r.get("持股数")) or 0
                pct = _num(r.get("占总流通股本持股比例")) or 0.0
                ranking = _num(r.get("名次")) or 0
                hold_value = float(hold_shares) * close_price if close_price else 0.0
                out.append({
                    "holder_name": holder_name,
                    "hold_shares": int(hold_shares),
                    "hold_value": hold_value,
                    "pct_of_float": float(pct),
                    "ranking": int(ranking),
                })
            return out
        except Exception:
            return []

    def _report_period_close(self, full_symbol: str, date_str: str) -> float:
        """取报告期(YYYYMMDD)前后几天的最后一个交易日收盘价,用于推算持股市值。失败返回 0。"""
        try:
            import datetime as _dt
            d = _dt.datetime.strptime(date_str, "%Y%m%d")
            start = (d - _dt.timedelta(days=10)).strftime("%Y%m%d")
            df = ak.stock_zh_a_daily(symbol=full_symbol, start_date=start,
                                     end_date=date_str, adjust="")
            if df is None or len(df) == 0:
                import logging as _lg
                _lg.getLogger("akshare_provider").warning(
                    "_report_period_close empty for %s @ %s", full_symbol, date_str
                )
                return 0.0
            return float(df.iloc[-1]["close"])
        except Exception as e:
            import logging as _lg
            _lg.getLogger("akshare_provider").warning(
                "_report_period_close failed for %s @ %s: %s", full_symbol, date_str, e
            )
            return 0.0

    # ── 国家队监控:全市场季报前十大流通股东(自实现分页,绕过 akshare bug)──
    # akshare 的 stock_gdfx_free_holding_detail_em(date) 同样走东方财富
    # datacenter-web 接口,但当某页 result 为 None 时会抛 TypeError。
    # 这里直接打 East Money API,自己做分页 + 单页重试,失败页跳过不毁整季。
    #
    # pageSize 选 1000 而非 500:East Money 的 pageNumber 有硬上限 100,
    # 超过 100 页的请求会稳定返回 success=False / result=None(与 akshare 的
    # 瞬时 None bug 不同,这是固定截断)。单季约 6 万行 → pageSize=500 时
    # 报 122 页但只能取回前 100 页(50000 行,静默丢 18%);pageSize=1000 时
    # 仅 61 页,全部 < 100,可完整取回。
    def fetch_market_holders_by_quarter(self, quarter: str) -> list[dict]:
        """东方财富全市场单季度前十大流通股东(自实现分页,绕过 akshare bug)。

        quarter: '20240930' 或 '2024-09-30'。
        返回 [{symbol, company_name, holder_name, hold_shares, hold_value,
               pct_of_float, ranking}] 全市场(不过滤国家队)。失败返回 [](尽力而为:
        单页失败重试3次后跳过,不毁掉整季)。
        """
        import requests
        date_str = f"{quarter[:4]}-{quarter[4:6]}-{quarter[6:8]}"
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        base_params = {
            "sortColumns": "UPDATE_DATE,SECURITY_CODE,HOLDER_RANK",
            "sortTypes": "-1,1,1",
            "pageSize": "1000",
            "reportName": "RPT_F10_EH_FREEHOLDERS",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "filter": f"(END_DATE='{date_str}')",
        }
        out: list[dict] = []
        try:
            # 第1页拿总页数
            total_pages = 0
            for attempt in range(3):
                params = {**base_params, "pageNumber": "1"}
                r = requests.get(url, params=params, timeout=30)
                j = r.json()
                res = j.get("result")
                if res and res.get("data"):
                    total_pages = res.get("pages", 1)
                    self._append_em_holders(out, res["data"])
                    break
            if total_pages == 0:
                return []
            # 第2页起
            for page in range(2, total_pages + 1):
                rows = None
                for attempt in range(3):
                    try:
                        params = {**base_params, "pageNumber": str(page)}
                        r = requests.get(url, params=params, timeout=30)
                        j = r.json()
                        res = j.get("result")
                        if res and res.get("data"):
                            rows = res["data"]
                            break
                    except Exception:
                        if attempt == 2:
                            rows = None
                if rows:
                    self._append_em_holders(out, rows)
            return out
        except Exception:
            return out

    @staticmethod
    def _append_em_holders(out: list, rows: list) -> None:
        for d in rows:
            try:
                out.append({
                    "symbol": str(d.get("SECURITY_CODE") or "").strip(),
                    "company_name": str(d.get("SECURITY_NAME_ABBR") or "").strip(),
                    "holder_name": str(d.get("HOLDER_NAME") or "").strip(),
                    "hold_shares": int(float(d.get("HOLD_NUM") or 0)),
                    "hold_value": float(d.get("HOLDER_MARKET_CAP") or 0),
                    "pct_of_float": float(d.get("FREE_HOLDNUM_RATIO") or 0),
                    "ranking": int(d.get("HOLDER_RANK") or 0),
                })
            except Exception:
                continue

    def fetch_etf_daily_signal(
        self, etf_code: str, index_code: str, lookback_days: int = 20
    ) -> dict:
        """计算单只 ETF 当日护盘信号。

        strength: vol_ratio>=3 and defend -> 'strong';
                  vol_ratio>=2 -> 'suspect'; else 'none'。
        """
        try:
            prefix = "sh" if etf_code.startswith("5") else "sz"
            df = ak.fund_etf_hist_sina(symbol=f"{prefix}{etf_code}")
            if df is None or len(df) == 0:
                return {"etf_code": etf_code, "strength": "error", "vol_ratio": 0.0}
            df = df.sort_values("date").tail(lookback_days + 10)
            today_vol = _num(df.iloc[-1].get("volume")) or 0
            prev_vols = [
                _num(r.get("volume")) or 0
                for _, r in df.iloc[-(lookback_days + 1):-1].iterrows()
            ]
            avg_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 0
            vol_ratio = (today_vol / avg_vol) if avg_vol else 0.0
            closes = [_num(x) or 0 for x in df["close"].tail(2).tolist()]
            etf_chg_pct = (
                (closes[-1] - closes[-2]) / closes[-2] * 100
            ) if len(closes) >= 2 and closes[-2] else 0.0
            as_of = str(df.iloc[-1].get("date"))
            # 对应指数当日涨跌
            index_chg_pct = 0.0
            try:
                idf = ak.stock_zh_index_daily(symbol=index_code)
                if idf is not None and len(idf) >= 2:
                    ic = [_num(x) or 0 for x in idf["close"].tail(2).tolist()]
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
            return {
                "etf_code": etf_code,
                "strength": "error",
                "vol_ratio": 0.0,
                "error": str(e),
            }

    def fetch_etf_signal_history(
        self, etf_code: str, index_code: str, days: int = 20,
        lookback_days: int = 20,
    ) -> list[dict]:
        """计算单只 ETF 过去 `days` 个交易日的护盘信号序列(oldest→newest)。

        复用 fetch_etf_daily_signal 的口径:
          - vol_ratio = 当日量 / 前 lookback_days 日均量
          - defend_flag = 指数跌且 ETF 跑赢指数 +0.5%
          - strong: ratio>=3 & defend; suspect: ratio>=2; else none

        ETF + 指数历史各拉一次,本地滚动窗口计算,避免逐日反复请求。
        任意一步失败 → 返回 [](由调用方降级)。
        """
        try:
            prefix = "sh" if etf_code.startswith("5") else "sz"
            df = ak.fund_etf_hist_sina(symbol=f"{prefix}{etf_code}")
            if df is None or len(df) == 0:
                return []
            df = df.sort_values("date").reset_index(drop=True)
            # 保留足够窗口:lookback_days 均量 + days 个交易日
            keep = df.tail(lookback_days + days).reset_index(drop=True)
            if len(keep) < 2:
                return []

            # 指数收盘序列:取与 ETF 重叠的尾部,按位置对齐尾段
            idx_close: list[float] = []
            try:
                idf = ak.stock_zh_index_daily(symbol=index_code)
                if idf is not None and len(idf) > 0:
                    idx_close = [_num(x) or 0.0 for x in idf["close"].tolist()]
            except Exception:
                idx_close = []

            vols = [_num(r.get("volume")) or 0 for _, r in keep.iterrows()]
            closes = [_num(x) or 0.0 for x in keep["close"].tolist()]
            dates = [str(x) for x in keep["date"].tolist()]
            n = len(keep)

            out: list[dict] = []
            # 从能算出 lookback_days 均量的位置开始,最多取最近 days 个交易日
            start = lookback_days  # i 处的均量用 [i-lookback_days, i)
            for i in range(start, n):
                prev_vols = vols[i - lookback_days:i]
                avg_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 0
                today_vol = vols[i]
                vol_ratio = (today_vol / avg_vol) if avg_vol else 0.0
                if i >= 1 and closes[i - 1]:
                    etf_chg_pct = (closes[i] - closes[i - 1]) / closes[i - 1] * 100
                else:
                    etf_chg_pct = 0.0
                # 指数当日涨跌:用 idx_close 尾部与 ETF 同位置对齐
                index_chg_pct = 0.0
                if idx_close:
                    # idf 至少与 df 等长或更长;取尾部第 (n-1-i) 个位置作昨日、当日
                    offset = len(idx_close) - n
                    if offset >= 0 and (offset + i) >= 1:
                        ic_prev = idx_close[offset + i - 1]
                        ic_cur = idx_close[offset + i]
                        if ic_prev:
                            index_chg_pct = (ic_cur - ic_prev) / ic_prev * 100
                defend_flag = (index_chg_pct < 0) and (etf_chg_pct >= index_chg_pct + 0.5)
                if vol_ratio >= 3 and defend_flag:
                    strength = "strong"
                elif vol_ratio >= 2:
                    strength = "suspect"
                else:
                    strength = "none"
                out.append({
                    "date": dates[i],
                    "vol_ratio": round(vol_ratio, 2),
                    "etf_chg_pct": round(etf_chg_pct, 2),
                    "index_chg_pct": round(index_chg_pct, 2),
                    "defend_flag": bool(defend_flag),
                    "strength": strength,
                })
            # 仅保留最近 days 个交易日,保持 oldest→newest
            return out[-days:] if len(out) > days else out
        except Exception:
            return []
