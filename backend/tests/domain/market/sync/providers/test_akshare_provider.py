"""
AkshareProvider 骨架测试（符号识别 + 规范化）
"""
from datetime import datetime, date

import pandas as pd
import pytest

from src.domain.market.sync.providers.akshare_provider import (
    AkshareProvider,
)


@pytest.fixture
def prov():
    return AkshareProvider()


def test_validate_us_ticker_passes(prov):
    assert prov.validate_symbol("VOO") is True
    assert prov.validate_symbol("TLT") is True
    assert prov.validate_symbol("GLD") is True


def test_validate_a_etf_passes(prov):
    assert prov.validate_symbol("sh510300") is True
    assert prov.validate_symbol("sz159934") is True   # sz1 前缀（旧 Tencent 会挡）


def test_validate_rejects_garbage(prov):
    assert prov.validate_symbol("123abc") is False
    assert prov.validate_symbol("") is False
    assert prov.validate_symbol("TOOLONGSYMBOL") is False   # >5 字母


def test_is_us_ticker(prov):
    assert prov._is_us_ticker("VOO") is True
    assert prov._is_us_ticker("sh510300") is False


def test_strip_a_etf_prefix(prov):
    assert prov._strip_exchange_prefix("sh510300") == "510300"
    assert prov._strip_exchange_prefix("sz159934") == "159934"


# ── Task 4: A股ETF fetch_daily ───────────────────────────────────────────
def _a_etf_df():
    """模拟 ak.fund_etf_hist_em 返回（中文列，真实结构）"""
    return pd.DataFrame({
        "日期": ["2026-06-19", "2026-06-20"],
        "开盘": [1.0, 1.1],
        "收盘": [1.1, 1.2],
        "最高": [1.2, 1.3],
        "最低": [0.9, 1.0],
        "成交量": [100000, 110000],
        "成交额": [110000.0, 132000.0],
        "振幅": [30.0, 27.27],
        "涨跌幅": [10.0, 9.09],
        "涨跌额": [0.1, 0.1],
        "换手率": [1.0, 1.1],
    })


def test_fetch_daily_a_etf_maps_chinese_columns(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod

    captured = {}

    def fake(symbol, period="daily", adjust="qfq", **kw):
        captured["symbol"] = symbol
        return _a_etf_df()

    monkeypatch.setattr(mod.ak, "fund_etf_hist_em", fake)
    prov = mod.AkshareProvider()
    bars = prov.fetch_daily("sh510300")

    # akshare 收到的是去前缀的纯数字
    assert captured["symbol"] == "510300"
    assert len(bars) == 2
    b0 = bars[0]
    assert isinstance(b0, mod.OHLCVBar)
    assert b0.symbol == "sh510300"
    assert b0.market == "A"
    assert b0.open_ == 1.0 and b0.close_ == 1.1
    assert b0.high_ == 1.2 and b0.low_ == 0.9
    assert b0.volume == 100000 and b0.amount == 110000.0
    assert b0.trade_time == datetime(2026, 6, 19)
    assert bars[1].trade_time == datetime(2026, 6, 20)


def test_fetch_daily_a_etf_empty_returns_empty(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(
        mod.ak, "fund_etf_hist_em",
        lambda *a, **k: pd.DataFrame(),
    )
    assert mod.AkshareProvider().fetch_daily("sh510300") == []


# ── Task 5: 美股 fetch_daily ──────────────────────────────────────────────
def _us_df():
    """模拟 ak.stock_us_daily 返回（英文小写列，Timestamp 日期）"""
    return pd.DataFrame({
        "date": pd.to_datetime(["2026-06-19", "2026-06-20"]),
        "open": [100.0, 101.0],
        "high": [102.0, 103.0],
        "low": [99.0, 100.0],
        "close": [101.0, 102.0],
        "volume": [50000.0, 51000.0],
    })


def test_fetch_daily_us_maps_english_columns(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod

    captured = {}
    def fake(symbol, adjust="qfq", **kw):
        captured["symbol"] = symbol
        return _us_df()

    monkeypatch.setattr(mod.ak, "stock_us_daily", fake)
    bars = mod.AkshareProvider().fetch_daily("VOO")

    assert captured["symbol"] == "VOO"
    assert len(bars) == 2
    b = bars[0]
    assert b.symbol == "VOO"
    assert b.market == "US"
    assert b.open_ == 100.0 and b.close_ == 101.0
    assert b.amount == 0.0                 # 美股接口无 amount
    assert b.volume == 50000.0
    assert b.trade_time == datetime(2026, 6, 19)


# ── Task 6: 汇率 fetch_fx_daily ──────────────────────────────────────────
def _fx_df():
    """模拟 ak.currency_boc_sina 返回（中行折算价 = 每百美元人民币）"""
    return pd.DataFrame({
        "日期": [date(2026, 6, 19), date(2026, 6, 20)],
        "中行汇买价": [676.47, 676.47],
        "中行钞买价": [676.47, 676.47],
        "中行钞卖价/汇卖价": [679.32, 679.32],
        "央行中间价": [None, None],
        "中行折算价": [681.3, 681.3],
    })


def test_fetch_fx_daily_returns_rate_divided_by_100(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(
        mod.ak, "currency_boc_sina",
        lambda *a, **k: _fx_df(),
    )
    rows = mod.AkshareProvider().fetch_fx_daily("USDCNY")

    assert len(rows) == 2
    assert rows[0] == (date(2026, 6, 19), 6.813)     # 681.3 / 100
    assert rows[1] == (date(2026, 6, 20), 6.813)


# ── Task 7: get_stock_list（从 app_config.portfolio_universe 读）──────────
def test_get_stock_list_reads_config_bars(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod

    class _FakeCfg:
        class portfolio_universe:
            bars = [
                type("B", (), {"symbol": "sh510300", "market": "A"})(),
                type("B", (), {"symbol": "VOO", "market": "US"})(),
                type("B", (), {"symbol": "TLT", "market": "US"})(),
            ]

    monkeypatch.setattr(mod, "app_config", _FakeCfg())
    prov = mod.AkshareProvider()
    assert prov.get_stock_list(market="A") == ["sh510300"]
    assert set(prov.get_stock_list(market="US")) == {"VOO", "TLT"}
    assert set(prov.get_stock_list()) == {"sh510300", "VOO", "TLT"}


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


# ── Task 3: 社融结构 6 分项（复用 macro_china_shrzgm，不同 pick 列）──────
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


# ── Task 4: 固投 / 地产开发投资（macro_china_gdzctz，实测列名）──────
# 实测真实列 ['月份','当月','同比增长','环比增长','自年初累计']。
# 设计文档假设的 "当月-房地产开发投资-同比增长" 列当前接口不存在，
# 故 cn_realestate_inv_yoy 在线增量恒空，历史值由 cn_fai.csv 种子补。
def _gdzctz_df():
    """模拟 ak.macro_china_gdzctz（实测真实列名）。"""
    return pd.DataFrame({
        "月份": ["2026年05月份", "2026年06月份"],
        "当月": [37219.0, 47858.0],
        "同比增长": [-17.15, -15.60],
        "环比增长": [-3.54, 28.58],
        "自年初累计": [178512.0, 226370.0],
    })


def test_extract_cn_fai_yoy(monkeypatch):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(mod.ak, "macro_china_gdzctz", lambda: _gdzctz_df())
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_series("cn_fai_yoy")
    assert len(rows) == 2
    # 升序：5月在6月前
    assert rows[0][0] == date(2026, 5, 1)
    assert rows[0][1] == -17.15
    assert rows[1][0] == date(2026, 6, 1)
    assert rows[1][1] == -15.60


def test_extract_cn_realestate_inv_yoy(monkeypatch):
    """注册条目存在但接口列缺失 → pick 恒 None → 空列表。"""
    import src.domain.market.sync.providers.akshare_provider as mod
    # 条目必须注册（与 cn_fai_yoy 同源 macro_china_gdzctz）
    assert "cn_realestate_inv_yoy" in mod.AkshareProvider._MACRO_EXTRACTORS
    monkeypatch.setattr(mod.ak, "macro_china_gdzctz", lambda: _gdzctz_df())
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_series("cn_realestate_inv_yoy")
    # 地产投资列当前接口不存在，在线增量恒为空
    assert rows == []


# ── Task 5: 存款占比派生指标（macro_china_supply_of_money，多列计算）──────
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


# ── 长历史 yearly 提取器 ────────────────────────────────────────────
def _yearly_df():
    """模拟 ak.macro_china_cpi_yearly（英为财情 5 列格式）"""
    return pd.DataFrame({
        "商品": ["中国CPI年率报告"] * 3,
        "日期": ["1986-02-01", "1986-03-01", "2024-01-12"],
        "今值": [7.1, 7.1, -0.8],
        "预测值": [None, None, -0.5],
        "前值": [None, 7.1, 0.1],
    })


@pytest.mark.parametrize("code,fn_name", [
    ("cn_cpi_yoy_long", "macro_china_cpi_yearly"),
    ("cn_ppi_yoy_long", "macro_china_ppi_yearly"),
    ("cn_pmi_long", "macro_china_pmi_yearly"),
    ("cn_m2_yoy_long", "macro_china_m2_yearly"),
])
def test_extract_long_history(monkeypatch, code, fn_name):
    import src.domain.market.sync.providers.akshare_provider as mod
    monkeypatch.setattr(mod.ak, fn_name, lambda: _yearly_df())
    prov = mod.AkshareProvider()
    rows = prov.fetch_macro_series(code)
    assert len(rows) == 3
    # 最早的数据在前（升序）
    assert rows[0][0] == date(1986, 2, 1)
    assert rows[0][1] == 7.1
