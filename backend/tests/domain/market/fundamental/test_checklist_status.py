"""checklist_status 纯函数测试(买入体检,课程21集)。"""
from datetime import date

from src.domain.market.fundamental.checklist_status import (
    BARGAIN_NOTE_KEY,
    MANUAL_ITEMS,
    build_checklist,
    manual_filled,
    progress,
    revenue_cagr,
    sanitize_items,
)


class TestConstants:
    def test_nine_manual_items(self):
        assert len(MANUAL_ITEMS) == 9

    def test_keys_unique(self):
        keys = [i["key"] for i in MANUAL_ITEMS]
        assert len(keys) == len(set(keys))

    def test_sections(self):
        assert {i["section"] for i in MANUAL_ITEMS} == {"company", "industry"}

    def test_bargain_note_key(self):
        assert BARGAIN_NOTE_KEY == "bargaining_power_note"


class TestRevenueCagr:
    def _annual(self, revs):
        # 2018..年报序列
        return [
            {"report_date": date(2017 + i, 12, 31), "revenue": v}
            for i, v in enumerate(revs)
        ]

    def test_flat_below_3pct(self):
        # 格力口径:1800亿→1800亿,CAGR=0
        assert revenue_cagr(self._annual([1800, 1800, 1800, 1800,
                                          1800, 1800, 1800, 1800])) < 0.03

    def test_growing(self):
        r = revenue_cagr(self._annual([100, 130, 170, 220, 290, 380, 500, 650, 850]))
        assert r > 0.20

    def test_too_few_points(self):
        assert revenue_cagr(self._annual([100])) is None

    def test_nonpositive_base(self):
        assert revenue_cagr(self._annual([0, 100, 200])) is None

    def test_exactly_365_days_not_rejected(self):
        # C4 回归:恰隔 365 天(2020-12-31→2021-12-31,非闰年)的两个年报点
        # 是有效窗口,应返回数值而非 None(旧实现 span=365/365.25<1 误拒)
        r = revenue_cagr([
            {"report_date": date(2020, 12, 31), "revenue": 100},
            {"report_date": date(2021, 12, 31), "revenue": 120},
        ])
        assert r is not None and 0 < r < 1

    def test_366_days_not_rejected(self):
        # C4 边界:2023-12-31→2024-12-31(经闰日 2024-02-29,366 天)同样返回数值
        r = revenue_cagr([
            {"report_date": date(2023, 12, 31), "revenue": 100},
            {"report_date": date(2024, 12, 31), "revenue": 130},
        ])
        assert r is not None and 0 < r < 1


class TestBuildChecklist:
    def test_all_sources_missing(self):
        out = build_checklist({}, {})
        secs = {s["key"]: s for s in out["sections"]}
        assert list(secs.keys()) == ["company", "industry", "finance", "price"]
        auto = [it for s in out["sections"] for it in s["items"]
                if it["type"] == "auto"]
        assert len(auto) == 12
        assert all(it["status"] == "missing" for it in auto)
        # 只展示不下结论:响应无 verdict/conclusion 键
        assert "verdict" not in out and "conclusion" not in out

    def test_full_sources(self):
        sources = {
            "profile": {"name": "贵州茅台", "industry": "白酒", "total_mv": 2.1e12},
            "income_annual": [
                {"report_date": date(2017 + i, 12, 31), "revenue": 300 + 60 * i,
                 "net_profit": 100 + 20 * i, "basic_eps": 30.0 + i}
                for i in range(9)
            ],
            "roe_annual": [30.0, 31.0, 32.0, 33.0],
            "roe_pctile": 0.9,
            "five_forces": {"forces": [
                {"key": "supplier", "label": "供应商议价力", "score": 65,
                 "evidence": []},
                {"key": "buyer", "label": "客户议价力", "score": 70, "evidence": []},
            ]},
            "sections_latest": {"cr4": 0.77, "hhi": 0.21},
            "liquidity": {"verdict": "healthy", "ratios": {}},
            "payout": {"ratio": 0.52},
            "fraud": {"severity": "clean", "red_flags": []},
            "z": {"z": 3.1, "verdict": "safe"},
            "m": {"m": -3.0, "verdict": "clean"},
            "band_pe": {"current": 25.0,
                        "band": {"mean": 30.0, "std": 5.0, "z_score": -1.0,
                                 "state": "合理偏低"}},
            "band_ps": {"current": 10.0,
                        "band": {"mean": 12.0, "std": 2.0, "z_score": -1.0,
                                 "state": "合理偏低"}},
            "kline_trend": {"state": "上升", "ma20": 1, "ma60": 1, "ma120": 1,
                            "slope_pct": 0.05},
            "concentration": {"verdict": "concentrating", "holder_counts": [1, 2]},
        }
        out = build_checklist(sources, {})
        by_key = {it["key"]: it for s in out["sections"] for it in s["items"]}
        assert by_key["industry"]["status"] == "ok"
        assert by_key["growth"]["status"] == "ok"       # CAGR>3%
        assert by_key["roe"]["status"] == "ok"
        assert by_key["dividend"]["status"] == "ok"     # 52% 慷慨
        assert by_key["redflag"]["status"] == "ok"
        assert by_key["bargain"]["status"] == "ok"      # 均分>=60
        # 议价项带可编辑备注字段
        assert by_key["bargain"]["editable"] is True
        assert by_key["bargain"]["note_key"] == BARGAIN_NOTE_KEY

    def test_threshold_edges(self):
        # 派息率>70% → risk(掏空家底)
        out = build_checklist({"payout": {"ratio": 0.71},
                               "eps": 1.0, "div_sum": 0.71}, {})
        by = {it["key"]: it for s in out["sections"] for it in s["items"]}
        assert by["dividend"]["status"] == "risk"
        # fraud high_risk → risk
        out = build_checklist({"fraud": {"severity": "high_risk"}}, {})
        by = {it["key"]: it for s in out["sections"] for it in s["items"]}
        assert by["redflag"]["status"] == "risk"
        # z grey → watch
        out = build_checklist({"z": {"z": 2.0, "verdict": "grey"}}, {})
        by = {it["key"]: it for s in out["sections"] for it in s["items"]}
        assert by["redflag"]["status"] == "watch"
        # 估值带虚高 → risk
        out = build_checklist({"band_pe": {"current": 50.0, "band": {
            "mean": 20.0, "std": 5.0, "z_score": 6.0, "state": "虚高"}}}, {})
        by = {it["key"]: it for s in out["sections"] for it in s["items"]}
        assert by["band_pe"]["status"] == "risk"
        # ROE 亏损 → risk
        out = build_checklist({"roe_annual": [5.0, 2.0, -1.0]}, {})
        by = {it["key"]: it for s in out["sections"] for it in s["items"]}
        assert by["roe"]["status"] == "risk"

    def test_manual_items_injected(self):
        saved = {"pricing_power": {"value_choice": "是",
                                   "value_text": None,
                                   "updated_at": "2026-09-01T00:00:00"},
                 "mission_vision": {"value_choice": None,
                                    "value_text": "用技术创新满足向往",
                                    "updated_at": "2026-09-01T00:00:00"}}
        out = build_checklist({}, saved)
        by = {it["key"]: it for s in out["sections"] for it in s["items"]}
        assert by["pricing_power"]["status"] == "filled"
        assert by["pricing_power"]["value_choice"] == "是"
        assert by["mission_vision"]["status"] == "filled"
        assert by["company_name"]["status"] == "pending"
        assert out["manual_progress"] == {"filled": 2, "total": 9}
        assert out["auto_progress"] == {"ok": 0, "watch": 0, "risk": 0,
                                        "missing": 12}

    def test_bargain_note_injected(self):
        saved = {BARGAIN_NOTE_KEY: {"value_text": "强甲方",
                                    "value_choice": None,
                                    "updated_at": "2026-09-01T00:00:00"}}
        out = build_checklist({}, saved)
        by = {it["key"]: it for s in out["sections"] for it in s["items"]}
        assert by["bargain"]["note_text"] == "强甲方"
        assert by["bargain"]["note_updated_at"] == "2026-09-01T00:00:00"


class TestManualFilled:
    def _item(self, t):
        return {"input_type": t}

    def test_choice_filled_by_choice(self):
        assert manual_filled(self._item("choice"),
                             {"value_choice": "成长期", "value_text": ""})

    def test_choice_plus_text_needs_choice(self):
        assert not manual_filled(self._item("choice+text"),
                                 {"value_choice": "", "value_text": "备注"})

    def test_text_filled_by_text(self):
        assert manual_filled(self._item("text"),
                             {"value_choice": None, "value_text": "内容"})

    def test_empty(self):
        assert not manual_filled(self._item("text"), {"value_text": "  "})
        assert not manual_filled(self._item("text"), None)


class TestSanitize:
    def test_filters_unknown_and_blank(self):
        raw = [
            {"item_key": "pricing_power", "value_choice": "是"},
            {"item_key": "hacker_key", "value_choice": "x"},   # 非法键丢弃
            {"item_key": "mission_vision", "value_text": "  "},  # 空白→None=清除
            {"item_key": BARGAIN_NOTE_KEY, "value_text": "强甲方"},
        ]
        out = sanitize_items(raw)
        keys = [r["item_key"] for r in out]
        assert keys == ["pricing_power", "mission_vision",
                        BARGAIN_NOTE_KEY]
        assert out[1]["value_text"] is None

    def test_non_string_values_coerced(self):
        # 前端可能传数字等非字符串值 → str() 防护,不抛异常
        out = sanitize_items([{"item_key": "pricing_power",
                               "value_choice": 1}])
        assert out[0]["value_choice"] == "1"
        out = sanitize_items([{"item_key": "core_products",
                               "value_text": 8848}])
        assert out[0]["value_text"] == "8848"
        out = sanitize_items([{"item_key": 123, "value_text": "x"}])
        assert out == []                        # 非法键仍丢弃

    def test_non_dict_elements_skipped(self):
        # 载荷元素非 dict(如 {"items": ["x"]})→ 跳过而非 AttributeError
        out = sanitize_items(["x", {"item_key": "pricing_power",
                                    "value_choice": "是"}])
        assert out == [{"item_key": "pricing_power", "value_text": None,
                        "value_choice": "是"}]
