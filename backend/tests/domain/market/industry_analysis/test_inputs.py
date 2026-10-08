# backend/tests/domain/market/industry_analysis/test_inputs.py
"""评分输入装配:假仓储注入,验证跨表拼装与分位/RS/资金映射逻辑。"""
import datetime as dt
from types import SimpleNamespace

from src.domain.market.industry_analysis.inputs import assemble_inputs

D = dt.date(2026, 9, 18)


def fake_repo():
    return SimpleNamespace(
        # cross_section:801780 三个报告期(去年同期/上季/最新);801120 只有一期
        get_cross_section_latest_two=lambda level=1, as_of=None: {
            "801780": [
                {"report_date": dt.date(2025, 6, 30),
                 "revenue_yoy": 3.0, "net_profit_sum": 180.0},
                {"report_date": dt.date(2025, 12, 31),
                 "revenue_yoy": 5.0, "net_profit_sum": 200.0},
                {"report_date": dt.date(2026, 6, 30),
                 "revenue_yoy": 8.0, "net_profit_sum": 120.0},
            ],
            "801120": [
                {"report_date": dt.date(2026, 6, 30),
                 "revenue_yoy": 12.0, "net_profit_sum": 100.0},
            ],
        },
        # 估值窗口:801780 的 PB 序列 [1,2,3,4] 当前 4 → 分位 100
        get_sw_valuation_window=lambda codes, start, end: {
            "801780": [{"trade_date": dt.date(2026, 9, i % 28 + 1),
                        "pe_ttm": 4.0, "pb": p} for i, p in
                       enumerate([1.0, 2.0, 3.0, 4.0])],
            "801120": [{"trade_date": dt.date(2026, 9, 18),
                        "pe_ttm": 20.0, "pb": 5.0}],
        },
        # 行情:801780 六根收盘 10→13(+30%),基准 sh000300 10→11(+10%)
        get_index_closes=lambda symbols, start, end: {
            "sw801780": [(dt.date(2026, 6, 1), 10.0)] +
                        [(dt.date(2026, 9, i), 10.0 + i * 0.6) for i in
                         range(1, 6)],
            "sh000300": [(dt.date(2026, 6, 1), 10.0)] +
                        [(dt.date(2026, 9, i), 10.0 + i * 0.2) for i in
                         range(1, 6)],
        },
        # 资金流:两行业两日。get_flow_rows 忽略 start 下界(契约只到 repo 层),
        # 且混入一行 as_of+1 的未来行——17:05 job 每日落库,装配层必须自行
        # 按 as_of 上界过滤,不得让未来行污染评分快照
        get_flow_rows=lambda start: [
            {"trade_date": dt.date(2026, 9, 17), "em_industry_name": "银行",
             "main_net_inflow": 100.0, "close_change_pct": 1.0},
            {"trade_date": dt.date(2026, 9, 18), "em_industry_name": "银行",
             "main_net_inflow": 50.0, "close_change_pct": -0.5},
            {"trade_date": dt.date(2026, 9, 18), "em_industry_name": "酿酒行业",
             "main_net_inflow": -30.0, "close_change_pct": 0.0},
            {"trade_date": dt.date(2026, 9, 19), "em_industry_name": "银行",
             "main_net_inflow": 777.0, "close_change_pct": 0.0},
        ],
    )


def test_assemble():
    out = assemble_inputs(fake_repo(), D, pct_window_years=8)
    bank = out["801780"]
    assert bank.revenue_yoy == 8.0                       # 最新报告期
    # 基期=一年前同期 2025-06-30(净利180),非上季(200)
    assert abs(bank.net_profit_yoy - (-100 / 3)) < 1e-6
    assert bank.pb == 4.0 and bank.pb_pct == 87.5   # [1,2,3,4] midrank
    assert bank.pe_ttm == 4.0
    assert bank.flow20 == 150.0  # 银行 100+50;9/19(as_of+1)未来行被上界剔除
    # rs60 = 标的61根首尾 − 基准同窗首尾
    assert abs(bank.rs60 - (0.3 - 0.1)) < 1e-9
    food = out["801120"]
    assert food.net_profit_yoy is None                   # 只有一期
    assert food.flow20 == -30.0                          # 酿酒→801120


def test_flow_cutoff_30_calendar_days():
    repo = fake_repo()
    old = {"trade_date": dt.date(2026, 1, 1), "em_industry_name": "银行",
           "main_net_inflow": 999.0, "close_change_pct": 0.0}
    repo.get_flow_rows = lambda start: (
        [] if start > dt.date(2026, 1, 1) else [old])
    out = assemble_inputs(repo, D)
    # start=D-30天(8/19) > 1/1 → 旧行被 repo 下界截断 → None
    assert out["801780"].flow20 is None
    out2 = assemble_inputs(fake_repo(), D)
    assert out2["801780"].flow20 == 150.0


def test_assemble_inputs_passes_as_of_to_cross_section():
    """历史评分前视修复: as_of 必须透传到截面查询。"""
    import datetime as dt
    from src.domain.market.industry_analysis.inputs import assemble_inputs

    captured = {}

    class _Repo:
        def get_cross_section_latest_two(self, level=1, as_of=None):
            captured["as_of"] = as_of
            return {}

        def get_sw_valuation_window(self, codes, start, end):
            return {}

        def get_rs60_window(self, start, end):
            return {}

        def get_flow_rows(self, since):
            return []

    try:
        assemble_inputs(_Repo(), dt.date(2024, 6, 30))
    except Exception:
        pass   # 其余数据缺失不阻断断言
    assert captured.get("as_of") == dt.date(2024, 6, 30)
