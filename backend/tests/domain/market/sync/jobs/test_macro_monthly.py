"""macro_monthly job 测试。"""
import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_seed_from_csv_single_value(tmp_path):
    """单指标 CSV 导入：report_date,value 格式。"""
    from src.domain.market.sync.jobs.macro_monthly import _seed_from_csv
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("report_date,value\n2024-01-01,5.5\n2024-02-01,5.8\n",
                        encoding="utf-8")
    repo = MagicMock()
    n = _seed_from_csv(
        repo, csv_file, ["cn_test"], unit="%", freq="month",
        source="测试", source_url="", provider="csv_seed")
    assert n == 2
    assert repo.upsert.call_count == 2
    # 第一行：2024-01-01, 5.5
    call0 = repo.upsert.call_args_list[0].kwargs
    assert call0["indicator_code"] == "cn_test"
    assert call0["value"] == 5.5


def test_seed_from_csv_multi_value(tmp_path):
    """双指标 CSV：report_date,value1,value2 → 两个 code。"""
    from src.domain.market.sync.jobs.macro_monthly import _seed_from_csv
    csv_file = tmp_path / "test.csv"
    csv_file.write_text(
        "report_date,value1,value2\n2024-01-01,14.9,6.2\n",
        encoding="utf-8")
    repo = MagicMock()
    n = _seed_from_csv(
        repo, csv_file, ["cn_a", "cn_b"], unit="%", freq="month",
        source="测试", source_url="", provider="csv_seed")
    assert n == 2  # 一行 × 两 code
    codes = [c.kwargs["indicator_code"]
             for c in repo.upsert.call_args_list]
    assert "cn_a" in codes and "cn_b" in codes


def test_seed_from_csv_missing_file(tmp_path):
    """CSV 文件不存在时返回 0，不抛错。"""
    from src.domain.market.sync.jobs.macro_monthly import _seed_from_csv
    repo = MagicMock()
    n = _seed_from_csv(
        repo, tmp_path / "nope.csv", ["cn_x"], unit="", freq="month",
        source="", source_url="", provider="csv_seed")
    assert n == 0
    repo.upsert.assert_not_called()


def test_run_aggregates_phases(tmp_path, monkeypatch):
    """run() 依次跑 akshare / derived / csv_seed / meta 四阶段。"""
    from src.domain.market.sync.jobs import macro_monthly as mm

    # mock provider
    mock_prov = MagicMock()
    mock_prov.fetch_macro_series.return_value = []
    mock_prov.fetch_macro_derived.return_value = []
    monkeypatch.setattr(mm, "AkshareProvider", lambda: mock_prov)

    # mock repo
    mock_repo = MagicMock()
    monkeypatch.setattr(
        mm, "create_macro_indicator_repository", lambda db: mock_repo)

    # mock db
    monkeypatch.setattr(mm, "create_db_connection", lambda *a: MagicMock())
    monkeypatch.setattr(mm, "get_dsn", lambda: "sqlite://")

    result = mm.run()
    assert "akshare" in result
    assert "derived" in result
    assert "csv_seed" in result
    assert "meta" in result
