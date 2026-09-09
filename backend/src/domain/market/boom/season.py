"""财报季窗口判定(纯函数)。

预告窗:1/4/7/10 月整月(对应报告期 = 上一季末;深市中报/三季报
预告截止 7-15/10-15,整月为安全超集)。
正式报表窗:3/4/8/10 月整月——对齐真实披露季(中报 8 月整月、
一季报+年报尾 4 月整月,截止日均为月末;年报早批 3 月起)。
"""
import datetime as dt
from dataclasses import dataclass

ANNOUNCE_MONTHS = (1, 4, 7, 10)
FORMAL_MONTHS = (3, 4, 8, 10)


@dataclass(frozen=True)
class SeasonStatus:
    in_season: bool
    window_name: str          # 如 "2026Q3预告窗";非财报季为 ""
    window_start: dt.date
    window_end: dt.date
    report_date: dt.date | None   # 当季报告期(季末);非财报季 None
    next_window_start: dt.date


def _month_end(y: int, m: int) -> dt.date:
    return dt.date(y + (m == 12), (m % 12) + 1, 1) - dt.timedelta(days=1)


def prev_quarter_end(d: dt.date) -> dt.date:
    q_month = ((d.month - 1) // 3) * 3        # 本季度首月的前一月;0 表示上一年12月
    if q_month == 0:
        return dt.date(d.year - 1, 12, 31)
    # 上一季末 = 本季度首日的前一天
    return dt.date(d.year, q_month + 1, 1) - dt.timedelta(days=1)


def _next_announce_start(d: dt.date) -> dt.date:
    """d 之后下一个预告月(1/4/7/10)的首日。"""
    for delta_month in range(1, 13):
        y, m = d.year, d.month + delta_month
        y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        if m in ANNOUNCE_MONTHS:
            return dt.date(y, m, 1)
    raise AssertionError("unreachable")


def announce_window(today: dt.date) -> SeasonStatus:
    if today.month in ANNOUNCE_MONTHS:
        start = dt.date(today.year, today.month, 1)
        end = _month_end(today.year, today.month)
        rd = prev_quarter_end(start)
        quarter = (rd.month + 2) // 3          # 季末月份→季度号:3→Q1 6→Q2 9→Q3 12→Q4
        return SeasonStatus(True, f"{rd.year}Q{quarter}预告窗", start, end, rd, _next_announce_start(end))
    # 非财报季:倒计时到下一个预告窗首日
    return SeasonStatus(False, "", today, today, None, _next_announce_start(today))


def is_formal_window(today: dt.date) -> bool:
    return today.month in FORMAL_MONTHS


def formal_report_dates(today: dt.date) -> list[dt.date]:
    """正式报表窗要查的报告期列表(季末);与是否在预告季无关,3/8 月可达。

    3月→年报早批(上一年12-31);4月→一季报(3-31)+年报尾(上一年12-31);
    8月→中报(6-30);10月→三季报(9-30)。一期可多报。
    """
    m, y = today.month, today.year
    if m == 3:
        return [dt.date(y - 1, 12, 31)]
    if m == 4:
        return [dt.date(y, 3, 31), dt.date(y - 1, 12, 31)]
    if m == 8:
        return [dt.date(y, 6, 30)]
    if m == 10:
        return [dt.date(y, 9, 30)]
    return []
