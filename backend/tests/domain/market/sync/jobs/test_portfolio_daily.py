"""portfolio_daily job 测试 — 验证 mode 判定 + sync_fx 增量逻辑。

不连真实 DB / akshare：通过 monkeypatch 替换模块级工厂函数。
"""
from datetime import date

import src.domain.market.sync.jobs.portfolio_daily as mod


class _FakeTracker:
    def __init__(self, last_sync_map):
        self._m = last_sync_map

    def get_last_sync(self, provider, symbol, interval):
        return self._m.get(symbol)


class _FakeService:
    def __init__(self):
        self.calls = []   # [(symbols, mode)]

    def backfill(self, symbols, interval="1d", mode="full", db_dsn=""):
        self.calls.append((symbols, mode))
        from src.domain.market.sync.sync_service import SyncResult
        return SyncResult(provider="akshare", interval=interval, mode=mode,
                          total_symbols=1, done_symbols=1)


class _FakeFxRepo:
    def __init__(self, latest):
        self._latest = latest
        self.upserts = []

    def get_latest_date(self, pair):
        return self._latest

    def upsert(self, d, pair, rate, source="akshare"):
        self.upserts.append((d, pair, rate))


def test_run_uses_full_for_new_symbol_incremental_for_existing(monkeypatch):
    bars = [
        type("B", (), {"symbol": "VOO", "market": "US"})(),
        type("B", (), {"symbol": "sh510300", "market": "A"})(),
    ]
    monkeypatch.setattr(mod, "_load_universe_bars", lambda: bars)
    fake_service = _FakeService()
    monkeypatch.setattr(mod, "_build_service",
                        lambda prov, tracker: fake_service)
    # VOO 有历史 → incremental；sh510300 无 → full
    monkeypatch.setattr(mod, "_build_tracker",
                        lambda: _FakeTracker({"VOO": "2026-06-19"}))
    # 汇率走空，避免干扰
    monkeypatch.setattr(mod, "sync_fx", lambda *a, **k: None)

    mod.run()

    calls = {sym: mode for (syms, mode) in fake_service.calls for sym in syms}
    assert calls["VOO"] == "incremental"
    assert calls["sh510300"] == "full"


def test_sync_fx_pulls_from_latest_date(monkeypatch):
    fx_repo = _FakeFxRepo(latest=date(2026, 6, 19))
    monkeypatch.setattr(mod, "create_fx_rate_repository",
                        lambda: fx_repo)

    provider = type("P", (), {
        "fetch_fx_daily": lambda self, pair, start_date=None, end_date=None:
            [(date(2026, 6, 20), 6.81)],
    })()
    monkeypatch.setattr(mod, "_build_provider", lambda: provider)

    mod.sync_fx("USDCNY")

    assert fx_repo.upserts == [(date(2026, 6, 20), "USDCNY", 6.81)]
