"""财报季窗口判定测试。"""
import datetime as dt

from src.domain.market.boom.season import (
    announce_window, formal_report_dates, is_formal_window, prev_quarter_end,
)


def test_prev_quarter_end():
    assert prev_quarter_end(dt.date(2026, 1, 15)) == dt.date(2025, 12, 31)
    assert prev_quarter_end(dt.date(2026, 4, 2)) == dt.date(2026, 3, 31)
    assert prev_quarter_end(dt.date(2026, 7, 31)) == dt.date(2026, 6, 30)
    assert prev_quarter_end(dt.date(2026, 10, 1)) == dt.date(2026, 9, 30)


def test_october_is_announce_season():
    s = announce_window(dt.date(2026, 10, 15))
    assert s.in_season
    assert s.window_start == dt.date(2026, 10, 1)
    assert s.window_end == dt.date(2026, 10, 31)
    assert s.report_date == dt.date(2026, 9, 30)
    assert s.window_name == "2026Q3预告窗"


def test_september_off_season_with_countdown():
    s = announce_window(dt.date(2026, 9, 8))
    assert not s.in_season
    assert s.report_date is None
    assert s.next_window_start == dt.date(2026, 10, 1)


def test_december_countdown_to_next_january():
    s = announce_window(dt.date(2026, 12, 20))
    assert not s.in_season
    assert s.next_window_start == dt.date(2027, 1, 1)


def test_in_season_next_window_starts_next_quarter():
    s = announce_window(dt.date(2026, 10, 15))
    assert s.next_window_start == dt.date(2027, 1, 1)
    s2 = announce_window(dt.date(2026, 1, 10))
    assert s2.next_window_start == dt.date(2026, 4, 1)


def test_january_window_reports_prior_year_q4():
    s = announce_window(dt.date(2026, 1, 10))
    assert s.in_season
    assert s.window_name == "2025Q4预告窗"
    assert s.report_date == dt.date(2025, 12, 31)


def test_formal_windows():
    # 披露季整月(中报 8 月整月、一季报+年报尾 4 月整月)
    assert is_formal_window(dt.date(2026, 8, 25))
    assert is_formal_window(dt.date(2026, 8, 10))
    assert is_formal_window(dt.date(2026, 4, 30))
    assert is_formal_window(dt.date(2026, 4, 1))
    assert is_formal_window(dt.date(2026, 3, 5))    # 年报早批月
    assert not is_formal_window(dt.date(2026, 9, 21))   # 9月无正式报表


def test_formal_report_dates_mapping():
    assert formal_report_dates(dt.date(2026, 3, 15)) == [dt.date(2025, 12, 31)]
    # 4月一期多报:一季报 + 年报尾
    assert formal_report_dates(dt.date(2026, 4, 10)) == [
        dt.date(2026, 3, 31), dt.date(2025, 12, 31)]
    assert formal_report_dates(dt.date(2026, 8, 5)) == [dt.date(2026, 6, 30)]
    assert formal_report_dates(dt.date(2026, 10, 8)) == [dt.date(2026, 9, 30)]
    assert formal_report_dates(dt.date(2026, 9, 8)) == []
