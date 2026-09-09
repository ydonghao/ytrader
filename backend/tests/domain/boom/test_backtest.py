"""回测样本构建 + 前视守卫测试。"""
import datetime as dt

import pytest

from src.domain.market.boom.backtest import SampleEvent, build_samples, with_text_only


class FakeBoomRepo:
    def get_hits_as_of(self, symbols, max_source_date):
        # 600001:公告日前命中(有效);600002:公告日后才命中(前视,必须排除)
        rows = []
        if "600001" in symbols:
            rows.append(type("H", (), {"symbol": "600001", "category": "supply_tight",
                                       "keyword": "供不应求",
                                       "source_date": dt.date(2025, 1, 5)})())
        if "600002" in symbols:
            rows.append(type("H", (), {"symbol": "600002", "category": "boom_up",
                                       "keyword": "高景气",
                                       "source_date": dt.date(2025, 1, 20)})())
        return rows


class FakeForecastRepo:
    def get_by_announce_date_range(self, start, end, forecast_type=None, limit=20000):
        def fc(sym, ann, pct):
            return type("F", (), {"symbol": sym, "forecast_type": "preannounce",
                                  "report_date": dt.date(2024, 12, 31),
                                  "announce_date": ann, "change_pct": pct,
                                  "forecast_type_label": "预增"})()
        return [fc("600001", dt.date(2025, 1, 10), 80.0),
                fc("600002", dt.date(2025, 1, 15), 90.0),
                fc("600003", dt.date(2025, 1, 18), 20.0)]   # 幅度不足


def test_build_samples_lookahead_guard():
    events = build_samples(FakeBoomRepo(), FakeForecastRepo(), 2025, 2025, 50.0)
    by_sym = {e.symbol: e for e in events}
    assert set(by_sym) == {"600001", "600002"}     # 600003 被幅度过滤
    assert by_sym["600001"].categories == ["supply_tight"]
    assert by_sym["600002"].categories == []       # 1-20 命中晚于 1-15 公告 → 剔除


def test_with_text_only():
    events = [
        SampleEvent("600001", dt.date(2024, 12, 31), dt.date(2025, 1, 10),
                    80.0, ("supply_tight",), "preannounce"),
        SampleEvent("600002", dt.date(2024, 12, 31), dt.date(2025, 1, 15),
                    90.0, (), "preannounce"),
    ]
    assert [e.symbol for e in with_text_only(events)] == ["600001"]


# ---- Task 14: 回测引擎 ----
from src.domain.market.boom.backtest import _months_after, run_backtest


def _mk_ev(sym, ann):
    return SampleEvent(sym, dt.date(2024, 12, 31), ann, 80.0,
                       ("supply_tight",), "preannounce")


def test_months_after():
    assert _months_after(dt.date(2025, 1, 31), 3) == dt.date(2025, 4, 30)
    assert _months_after(dt.date(2025, 8, 31), 6) == dt.date(2026, 2, 28)


def test_run_backtest_basic_flow():
    ev = _mk_ev("600001", dt.date(2025, 1, 10))
    bars = [
        (dt.date(2025, 1, 10), 10.0, 10.0),   # T 日收盘 10
        (dt.date(2025, 1, 13), 10.0, 10.5),   # T+1 入场开盘 10
        (dt.date(2025, 4, 14), 11.0, 11.0),   # 3个月后首个交易日,出场收盘 11
    ]
    bench = [(dt.date(2025, 1, 13), 4000.0), (dt.date(2025, 4, 14), 4200.0)]
    out = run_backtest([ev], lambda s, a, b: bars, lambda a, b: bench,
                       hold_months=3)
    assert out["n_traded"] == 1
    assert out["avg_ret"] == pytest.approx(10.0)      # 10→11 = +10%
    assert out["avg_bench_ret"] == pytest.approx(5.0)
    assert out["avg_excess"] == pytest.approx(5.0)
    assert out["hit_rate"] == 1.0
    assert out["by_category"][0]["category"] == "supply_tight"


def test_run_backtest_skips_limit_up_open():
    ev = _mk_ev("600001", dt.date(2025, 1, 10))
    bars = [
        (dt.date(2025, 1, 10), 10.0, 10.0),
        (dt.date(2025, 1, 13), 11.0, 11.0),   # 开盘 +10% ≥ 9.7% → 一字涨停跳过
    ]
    out = run_backtest([ev], lambda s, a, b: bars, lambda a, b: [],
                       hold_months=3)
    assert out["n_traded"] == 0
    assert out["n_skipped_limitup"] == 1


def test_run_backtest_no_data_counts():
    ev = _mk_ev("600001", dt.date(2025, 1, 10))
    out = run_backtest([ev], lambda s, a, b: [], lambda a, b: [], hold_months=3)
    assert out["n_no_data"] == 1 and out["n_traded"] == 0
