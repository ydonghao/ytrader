# backend/tests/domain/market/industry_analysis/test_flow_summary.py
# 注: brief 原稿 dt.date(2026, 9, 16 - i) 在 i>15 时日为 0/负数,模块导入即
# ValueError;改为 timedelta 回溯,保持"27个交易日、每天一行"的原意。
# 相应地 flow20 断言按 20 日窗口口径(前20个交易日),而非全部行之和。
import datetime as dt

from src.domain.market.industry_analysis.flow_map import summarize_flow

ROWS = (
    [{"trade_date": dt.date(2026, 9, 18), "em_industry_name": "银行",
      "main_net_inflow": 100.0, "close_change_pct": 1.0},
     {"trade_date": dt.date(2026, 9, 17), "em_industry_name": "银行",
      "main_net_inflow": 50.0, "close_change_pct": 0.5}] +
    [{"trade_date": dt.date(2026, 9, 16) - dt.timedelta(days=i),
      "em_industry_name": "银行",
      "main_net_inflow": 10.0, "close_change_pct": 0.0} for i in range(25)]
    + [{"trade_date": dt.date(2026, 9, 18), "em_industry_name": "未知行业",
        "main_net_inflow": 5.0, "close_change_pct": 0.0}]
)


def test_summarize_flow_windows_and_map():
    out = summarize_flow(ROWS)
    bank = next(r for r in out if r["em_industry_name"] == "银行")
    assert bank["sw_code"] == "801780"
    assert bank["day"] == 100.0
    assert bank["flow5"] == 100.0 + 50.0 + 10.0 * 3     # 5个最近交易日
    assert bank["flow20"] == 100.0 + 50.0 + 10.0 * 18   # 20个最近交易日截断
    unk = next(r for r in out if r["em_industry_name"] == "未知行业")
    assert unk["sw_code"] is None
    assert out[0]["flow20"] >= out[-1]["flow20"]        # 按 flow20 降序
