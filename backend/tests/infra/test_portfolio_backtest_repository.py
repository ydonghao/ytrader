"""组合回测结果 repository 集成测试（真实 PG，cursor 回滚）。"""
import pytest

from src.domain.market.strategy.portfolio_backtest_repository_interface import (
    PortfolioBacktestRecord,
)
from src.infra.database.sql_engine.engine import create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn
from src.infra.database.strategy.models import PortfolioBacktestResult
from src.infra.database.strategy.repository import (
    PortfolioBacktestRepository,
)


@pytest.fixture
def repo():
    """用真实 DB 连接的仓储（不单例，便于隔离）。"""
    db = create_db_connection(get_dsn())
    return PortfolioBacktestRepository(db)


def _sample_record(name="test-run", strategy="risk_parity", source="lt_backtest"):
    return PortfolioBacktestRecord(
        name=name,
        source=source,
        strategy=strategy,
        symbols=["sh510300", "sh518880"],
        params={"lookback": 120, "max_weight": 0.4},
        benchmark="sh000300",
        start_date="2020-01-01",
        end_date="2024-12-31",
        status="completed",
        initial_capital=1_000_000.0,
        final_equity=1_350_000.0,
        total_return_pct=35.0,
        cagr=7.8,
        sharpe_ratio=1.12,
        max_drawdown=12.5,
        volatility=15.3,
        alpha=0.03,
        beta=0.85,
        equity_curve=[
            {"date": "2020-01-01", "equity": 1_000_000},
            {"date": "2024-12-31", "equity": 1_350_000},
        ],
        rebalances=[{"date": "2020-04-01", "target_weights": {"sh510300": 0.6}}],
        trades=[{"symbol": "sh510300", "action": "BUY", "shares": 100}],
        final_weights={"sh510300": 0.6, "sh518880": 0.35},
    )


@pytest.fixture
def cleanup_ids(repo):
    """收集本测试创建的 id，测试后清理（避免污染真实库）。"""
    ids = []
    yield ids
    for rid in ids:
        try:
            repo.delete(rid)
        except Exception:
            pass


class TestPortfolioBacktestRepository:
    def test_save_and_get_roundtrip(self, repo, cleanup_ids):
        rec = _sample_record()
        rid = repo.save(rec)
        cleanup_ids.append(rid)
        assert rid > 0

        got = repo.get(rid)
        assert got is not None
        assert got.name == "test-run"
        assert got.strategy == "risk_parity"
        assert got.total_return_pct == pytest.approx(35.0)
        assert got.sharpe_ratio == pytest.approx(1.12)
        assert got.symbols == ["sh510300", "sh518880"]
        # JSONB 完整还原
        assert len(got.equity_curve) == 2
        assert got.final_weights["sh510300"] == pytest.approx(0.6)
        assert len(got.trades) == 1

    def test_list_results_filter_and_pagination(self, repo, cleanup_ids):
        for i in range(3):
            rid = repo.save(
                _sample_record(name=f"rp-{i}", strategy="risk_parity")
            )
            cleanup_ids.append(rid)
        other = repo.save(
            _sample_record(name="mv", strategy="min_variance")
        )
        cleanup_ids.append(other)

        # 全部
        all_recs, total = repo.list_results(page=1, size=50)
        assert total >= 4
        # 过滤 strategy
        rp, rp_total = repo.list_results(strategy="risk_parity", size=50)
        assert all(r.strategy == "risk_parity" for r in rp)
        assert rp_total >= 3
        # 分页
        page1, _ = repo.list_results(page=1, size=2)
        page2, _ = repo.list_results(page=2, size=2)
        assert len(page1) == 2
        # 两页不重叠
        ids1 = {r.id for r in page1}
        ids2 = {r.id for r in page2}
        assert not (ids1 & ids2)

    def test_list_results_summary_has_no_heavy_jsonb(self, repo, cleanup_ids):
        rid = repo.save(_sample_record())
        cleanup_ids.append(rid)
        recs, _ = repo.list_results(strategy="risk_parity", size=50)
        mine = [r for r in recs if r.id == rid]
        assert mine, "刚存的记录应出现在列表"
        # 摘要 record 的 snapshots 为空（省 JSONB）
        assert mine[0].equity_curve == []
        assert mine[0].trades == []
        # 但指标在
        assert mine[0].total_return_pct == pytest.approx(35.0)

    def test_get_many(self, repo, cleanup_ids):
        id1 = repo.save(_sample_record(name="a"))
        id2 = repo.save(_sample_record(name="b"))
        cleanup_ids.extend([id1, id2])
        got = repo.get_many([id1, id2, 999999])
        assert len(got) == 2
        assert {g.id for g in got} == {id1, id2}

    def test_delete(self, repo):
        rid = repo.save(_sample_record(name="to-delete"))
        assert repo.delete(rid) is True
        assert repo.get(rid) is None
        # 再删返回 False
        assert repo.delete(rid) is False

    def test_update_status(self, repo, cleanup_ids):
        rid = repo.save(_sample_record())
        cleanup_ids.append(rid)
        repo.update_status(rid, "failed", error_msg="boom")
        got = repo.get(rid)
        assert got.status == "failed"
        assert got.error_msg == "boom"


class TestRecordFromResult:
    def test_from_result_builds_record(self):
        from src.domain.market.strategy.longterm.models import LongTermResult

        result = LongTermResult(
            strategy="risk_parity",
            symbols=["sh510300", "sh518880"],
            start_date="2020-01-01",
            end_date="2024-12-31",
            initial_capital=1_000_000.0,
            final_equity=1_350_000.0,
            total_return_pct=35.0,
            cagr=7.8,
            sharpe_ratio=1.12,
            equity_curve=[{"date": "2020-01-01", "equity": 1000000}],
            rebalances=[
                {"date": "2020-04-01", "target_weights": {"sh510300": 0.6}}
            ],
        )
        rec = PortfolioBacktestRecord.from_result(
            result, source="lt_backtest", strategy="risk_parity",
            benchmark="sh000300",
        )
        assert rec.strategy == "risk_parity"
        assert rec.total_return_pct == pytest.approx(35.0)
        assert rec.sharpe_ratio == pytest.approx(1.12)
        assert rec.source == "lt_backtest"
        assert rec.final_weights == {"sh510300": 0.6}
        assert rec.name  # 自动生成非空
