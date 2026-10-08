"""mine_sweep 纯函数测试。"""
from src.domain.market.fundamental.mine_sweep import assess_mine


def test_high_by_any_strong_signal():
    for args in [("distress", None, None), (None, "manipulator", None),
                 (None, None, "high_risk")]:
        r = assess_mine(*args)
        assert r["risk_level"] == "high"
        assert len(r["reasons"]) >= 1


def test_medium_by_watch_signals():
    r = assess_mine("grey", "watch", "watch")
    assert r["risk_level"] == "medium"
    assert len(r["reasons"]) == 3


def test_clean():
    r = assess_mine("safe", "clean", "clean")
    assert r["risk_level"] == "clean" and r["reasons"] == []


def test_none_sources_do_not_trigger():
    r = assess_mine(None, "manipulator", None)
    assert r["risk_level"] == "high"
    r2 = assess_mine(None, None, None)
    assert r2["risk_level"] == "clean"
    assert any("缺失" in x for x in r2["reasons"])


def test_high_beats_medium():
    r = assess_mine("distress", "watch", "clean")
    assert r["risk_level"] == "high"
