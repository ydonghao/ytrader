"""index-pe 端点测试（mock 仓储，模式抄 test_market_cap_growth.py）。"""
import json
import math
import os
import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


def _clear_cache():
    import src.api.handler.financial_detail_handler as h
    h._mcg_cache["data"].clear()
    h._mcg_cache["ts"].clear()


def _pe_row(td, pe, src="computed"):
    return SimpleNamespace(
        trade_date=date.fromisoformat(td), pe_ttm=pe, source=src)


_FROZEN_TODAY = date(2026, 8, 27)
_LEAP_TODAY = date(2028, 2, 29)


def _frozen_handler(today=_FROZEN_TODAY):
    import src.api.handler.financial_detail_handler as h

    class _FrozenDate(date):
        @classmethod
        def today(cls):
            return today

    return patch.object(h, "date", _FrozenDate)


class _IdxValRepo:
    """与真实仓储同语义：按 start/end 过滤。"""

    def __init__(self, rows):
        self._rows = rows

    def get_index_range(self, symbol, start, end, source=None):
        assert symbol == "000300"
        return [r for r in self._rows
                if (start is None or r.trade_date >= start)
                and (end is None or r.trade_date <= end)
                and (source is None or r.source == source)]


# years=8 且 today=2026-08-27 → start=2018-08-27，2016 点在窗口外
PE_ROWS = [
    _pe_row("2016-08-31", 9.0),
    _pe_row("2018-09-28", 10.0),
    _pe_row("2020-09-30", 11.0),
    _pe_row("2022-09-30", 12.0),
    _pe_row("2024-09-30", None),   # TTM 断档点
]


def _call(code="000300", rows=None, years=8, today=_FROZEN_TODAY):
    from src.api.handler.financial_detail_handler import index_pe_trend
    _clear_cache()
    with _frozen_handler(today), patch(
        "src.infra.database.market.index_valuation."
        "create_index_valuation_repository",
        return_value=_IdxValRepo(PE_ROWS if rows is None else rows),
    ):
        return json.loads(index_pe_trend(code, years=years).body)


def test_shape_stats_current():
    body = _call()
    assert body["code"] == 0
    d = body["data"]
    assert d["kind"] == "index_pe" and d["code"] == "000300"
    assert d["name"]                     # 配置名（沪深300）
    assert [p["date"] for p in d["series"]] == [
        "2018-09-28", "2020-09-30", "2022-09-30", "2024-09-30"]
    assert d["series"][-1]["pe"] is None
    # stats 对非空样本 {10,11,12}：mean=11、pstdev=√(2/3)
    s = d["stats"]
    assert s["sample_size"] == 3
    assert s["mean"] == 11.0
    assert s["std"] == round(math.sqrt(2 / 3), 2)
    assert s["high"] == round(11 + math.sqrt(2 / 3), 2)
    assert s["low"] == round(11 - math.sqrt(2 / 3), 2)
    # current = 最后一个非空点
    assert d["current"] == {"date": "2022-09-30", "pe": 12.0}
    assert "1个" in (d.get("note") or "")


def test_years_zero_returns_all():
    body = _call(years=0)
    assert body["code"] == 0
    assert len(body["data"]["series"]) == 5   # 含 2016 窗口外点


def test_unknown_code_error():
    body = _call(code="999999")
    assert body["code"] != 0


def test_empty_series_no_stats():
    body = _call(rows=[])
    assert body["code"] == 0
    d = body["data"]
    assert d["series"] == []
    assert d["stats"] is None
    assert d["current"] is None


def test_leap_today_no_value_error():
    body = _call(today=_LEAP_TODAY)
    assert body["code"] == 0


def test_legu_source_rows_excluded():
    """遗留 legu 日频外部口径行不得混入（口径纯净，统计只算 computed）。"""
    rows = [
        _pe_row("2016-08-31", 9.0, src="legu"),
        _pe_row("2020-09-30", 11.0),
        _pe_row("2021-09-30", 12.0, src="legu"),
        _pe_row("2022-09-30", 12.0),
    ]
    body = _call(rows=rows)
    assert body["code"] == 0
    assert [p["date"] for p in body["data"]["series"]] == [
        "2020-09-30", "2022-09-30"]


def test_routes_registered():
    from src.api.router.financial_router import router
    paths = {r.path for r in router.routes}
    assert "/financial/index-pe/{code}" in paths
