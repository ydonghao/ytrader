"""管理层言行追踪纯函数测试：预告兑现评估 + 信用档案。"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from src.domain.market.fundamental.management_promise import (  # noqa: E402
    assess_forecast_promise,
    direction_broken,
    promise_credit_summary,
)


class TestAssessForecastPromise:
    def test_fulfilled_within_tolerance(self):
        r = assess_forecast_promise(100.0, 105.0, label="预增")
        assert r["status"] == "fulfilled"
        assert r["deviation_pct"] == 5.0

    def test_beat_above_tolerance(self):
        r = assess_forecast_promise(100.0, 120.0)
        assert r["status"] == "beat"
        assert r["deviation_pct"] == 20.0

    def test_broken_below_tolerance(self):
        r = assess_forecast_promise(100.0, 85.0)
        assert r["status"] == "broken"
        assert r["deviation_pct"] == -15.0

    def test_pending_when_actual_missing(self):
        r = assess_forecast_promise(100.0, None)
        assert r["status"] == "pending" and r["deviation_pct"] is None
        r2 = assess_forecast_promise(None, 100.0)
        assert r2["status"] == "pending"

    def test_zero_forecast_not_assessable(self):
        r = assess_forecast_promise(0.0, 100.0)
        assert r["status"] == "pending"


class TestDirectionBroken:
    def test_promised_growth_but_declined(self):
        # 预增：预告 100 > 上年 80，但实际 75 < 80 → 方向性失约
        assert direction_broken(100.0, 80.0, 75.0, "预增") is True

    def test_promised_growth_and_delivered(self):
        assert direction_broken(100.0, 80.0, 95.0, "预增") is False

    def test_decline_label_ignored(self):
        # 预减类预告不适用方向性修正
        assert direction_broken(50.0, 80.0, 75.0, "略减") is False

    def test_missing_values(self):
        assert direction_broken(None, 80.0, 75.0, "预增") is False
        assert direction_broken(100.0, None, 75.0, "续盈") is False


class TestPromiseCreditSummary:
    def test_counts_and_credit(self):
        rows = [
            {"status": "fulfilled"}, {"status": "beat"},
            {"status": "broken"}, {"status": "broken"},
            {"status": "pending"},
        ]
        s = promise_credit_summary(rows)
        assert s["total"] == 5 and s["pending"] == 1
        assert s["verified"] == 4
        assert (s["fulfilled"], s["beat"], s["broken"]) == (1, 1, 2)
        assert s["credit_pct"] == 50.0   # (1+1)/4

    def test_all_pending_no_credit(self):
        s = promise_credit_summary([{"status": "pending"}])
        assert s["credit_pct"] is None
        assert s["verified"] == 0


# ── V2: MD&A 切片与 JSON 解析纯函数 ───────────────────────────────────────
from src.domain.market.fundamental.annual_mda import (  # noqa: E402
    parse_promises_json,
    slice_mda,
)


class TestSliceMda:
    def test_slice_between_sections(self):
        filler = "经营情况讨论填充文本" * 80   # MD&A 切片要求 >500 字
        text = ("第一节 释义 …… 第二节 公司简介和主要财务指标 …… "
                "第三节 管理层讨论与分析 2024年公司实现营业收入X亿元，"
                f"同比增长Y%。{filler}管理层预计2025年营业总收入增长9%左右。"
                "第四节 公司治理 ……")
        seg = slice_mda(text)
        assert seg is not None
        assert "管理层讨论与分析" in seg
        assert "增长9%" in seg
        assert "公司治理" not in seg

    def test_no_mda_returns_none(self):
        assert slice_mda("第一节 释义 全文没有目标章节") is None


class TestParsePromisesJson:
    def test_plain_and_fenced(self):
        raw = ('```json\n{"promises": [{"content": "分红率不低于75%",'
               '"category": "分红", "period": "未来三年"}]}\n```')
        out = parse_promises_json(raw)
        assert len(out) == 1 and out[0]["category"] == "分红"

    def test_garbage_and_empty(self):
        assert parse_promises_json("not json") == []
        assert parse_promises_json("") == []
        assert parse_promises_json('{"promises": []}') == []
        # 内容过短被滤
        assert parse_promises_json(
            '{"promises": [{"content": "短", "category": "其他"}]}') == []
