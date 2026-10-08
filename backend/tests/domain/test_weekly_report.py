"""P3 周报纯函数测试。"""
from src.domain.market.thesis.weekly_report import build_weekly_report


def test_build_weekly_report_sections():
    out = build_weekly_report({
        "week": "2026-W39",
        "temperature": {
            "now": {"level_label": "极冷（历史大底区）",
                    "erp_pct": 5.58, "erp_percentile": 17.1},
            "prev": {"level_label": "偏冷", "erp_pct": 5.0},
        },
        "reevals": {"total": 3, "sell_signal": 1, "review": 1},
        "events": [
            {"kind": "condition_breached", "symbol": "sh600519"},
        ],
        "pipeline": {"checked": 2, "holding": 1},
        "health": {"fail": 0, "warn": 1},
        "closed_perf": {"count": 2, "avg_pct": -3.2,
                        "sold_early_count": 0},
    })
    assert "2026-W39" in out["markdown"]
    assert "极冷" in out["markdown"]
    assert "1/3 重估触发卖出信号" in out["markdown"]
    assert "论点破位" in out["markdown"] or "sh600519" in out["markdown"]
    assert out["sections"]["temperature"]["now_erp"] == 5.58


# ── 2026-10 决策日志补全：新三段（错过复盘/承诺动态/记分卡） ──────────────
def test_build_weekly_report_new_sections():
    out = build_weekly_report({
        "week": "2026-W40",
        "pass_perf": {"count": 3, "avg_since_pct": 12.0,
                      "avg_bench_pct": 5.0, "avg_excess_pct": 7.0,
                      "missed_count": 2},
        "promises": {"week_new": 5, "week_new_report": 4,
                     "week_new_forecast": 1, "week_new_manual": 0,
                     "pending": 13, "verified": 2, "credit_pct": 100.0},
        "scorecard": {"active": 3, "closed": 1, "closed_win_rate": 100.0,
                      "pass": 3, "exam": 2, "exam_avg_score": 61.3},
    })
    md = out["markdown"]
    assert "错过复盘" in md and "踏空 2/3" in md
    assert "超额 7.0%" in md
    assert "管理层承诺动态" in md and "年报抽取 4" in md
    assert "信用 100.0%" in md
    assert "决策记分卡" in md and "持仓 3" in md
    assert "拟真已揭晓 2 局" in md and "平均分 61.3" in md
    assert out["sections"]["pass_perf"]["count"] == 3


def test_build_weekly_report_new_sections_omitted_when_empty():
    out = build_weekly_report({"week": "2026-W40"})
    md = out["markdown"]
    assert "错过复盘" not in md
    assert "管理层承诺动态" not in md
    assert "决策记分卡" not in md
