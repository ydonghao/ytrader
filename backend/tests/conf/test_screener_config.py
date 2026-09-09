"""ScreenerConfig 配置模型测试。"""
import sys
import os
import datetime as dt
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest


def test_screener_config_defaults():
    """AppConfig.screener 有默认值，缺省时也能构建。"""
    from conf.settings import ScreenerConfig, DividendValueConfig
    cfg = ScreenerConfig()
    assert cfg.dividend_value.filters_default.dy_min == 3.0
    assert cfg.dividend_value.filters_default.value_metric == "pb"
    assert cfg.dividend_value.filters_default.value_window == "10y"


def test_get_global_exclude_ranges():
    """_get_global_exclude_ranges 返回 list[tuple[date,date]]。"""
    from src.domain.market.fundamental.percentile_batch import _get_global_exclude_ranges
    ranges = _get_global_exclude_ranges()
    assert isinstance(ranges, list)
    for r in ranges:
        assert len(r) == 2
        assert isinstance(r[0], dt.date)
        assert isinstance(r[1], dt.date)
