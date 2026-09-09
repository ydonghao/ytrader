"""job2 编排纯函数测试（明细行 → 截面行，不发 HTTP 不读库）。"""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from src.domain.market.sync.jobs.sw_industry_cross_section_sync import (
    build_sections,
)


def _d(year):
    return dt.date(year, 12, 31)


def _detail(symbol, year, revenue, net_profit=1.0, gm=30.0, equity=10.0):
    return {
        "sw_code_l1": "801080", "sw_name_l1": "食品饮料",
        "sw_code_l2": "801120", "sw_name_l2": "白酒Ⅱ",
        "report_date": _d(year), "symbol": symbol,
        "revenue": revenue, "net_profit": net_profit,
        "gross_margin": gm, "net_margin": 10.0, "equity": equity,
    }


def _two_years():
    rows = []
    for year in (2024, 2025):
        for i in range(4):
            rows.append(_detail(f"s{i}", year, 40.0 - i * 10,
                                net_profit=4.0 - i, gm=80.0 - i * 20))
    return rows


class TestBuildSections:

    def test_two_levels_two_periods_with_yoy(self):
        out = build_sections(_two_years())
        # 2 级 × 2 年 = 4 行
        assert len(out) == 4
        keys = {(r["level"], r["sw_code"], r["report_date"]) for r in out}
        assert (2, "801120", _d(2025)) in keys
        assert (1, "801080", _d(2025)) in keys
        s25 = next(r for r in out
                   if r["level"] == 2 and r["report_date"] == _d(2025))
        s24 = next(r for r in out
                   if r["level"] == 2 and r["report_date"] == _d(2024))
        assert s25["sample_count"] == 4
        assert s25["revenue_sum"] == pytest.approx(100.0)
        # 营收两年同值 → yoy=0；首期 yoy=None
        assert s25["revenue_yoy"] == pytest.approx(0.0)
        assert s24["revenue_yoy"] is None
        assert s25["distribution"]["gross_margin"]["mean"] == (
            pytest.approx(50.0)
        )

    def test_roe_derived_from_equity(self):
        rows = [_detail("s0", 2025, 50.0, net_profit=10.0, equity=40.0)]
        out = build_sections(rows)
        # roe=10/40*100=25 进入样本（样本<4 分布 None，但不报错）
        assert out[0]["sample_count"] == 1

    def test_level1_is_union_of_level2(self):
        """一级成分=名下二级并集（本测试两组同规模→一级样本=二级样本）。"""
        rows = []
        for year in (2025,):
            for i in range(4):
                d = _detail(f"s{i}", year, 10.0)
                d["sw_code_l2"] = "801120" if i < 2 else "801125"
                d["sw_name_l2"] = "白酒Ⅱ" if i < 2 else "啤酒"
                rows.append(d)
        out = build_sections(rows)
        l1 = next(r for r in out if r["level"] == 1)
        assert l1["sample_count"] == 4  # 两个二级各 2 只并集

    def test_revenue_none_row_defensive(self):
        rows = _two_years()
        bad = _detail("s9", 2025, None)
        out = build_sections(rows + [bad])
        s25 = next(r for r in out
                   if r["level"] == 2 and r["report_date"] == _d(2025))
        assert s25["sample_count"] == 4
