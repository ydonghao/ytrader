"""回填脚本纯函数测试 —— 行映射/URL 构造/去重。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from replay_news_backfill import rows_from_cctv, rows_from_economic, \
    make_url  # noqa: E402


def test_make_url_stable():
    assert make_url("cctv", "2020-03-13", "标题A") == \
        make_url("cctv", "2020-03-13", "标题A")
    assert make_url("cctv", "2020-03-13", "标题A") != \
        make_url("cctv", "2020-03-13", "标题B")
    # 不同源/不同日不同 URL
    assert make_url("cctv", "2020-03-13", "标题A") != \
        make_url("economic", "2020-03-13", "标题A")
    assert make_url("cctv", "2020-03-13", "标题A") != \
        make_url("cctv", "2020-03-14", "标题A")


def test_rows_from_cctv():
    # 实测列名(spike 2026-09): news_cctv 返回英文列 date/title/content
    df_rows = [{"date": "20200313", "title": "联播头条", "content": "正文"}]
    out = rows_from_cctv("2020-03-13", df_rows)
    assert len(out) == 1
    r = out[0]
    assert r["title"] == "联播头条"
    assert r["url"] == make_url("cctv", "2020-03-13", "联播头条")
    assert r["category"] == "cctv_news"
    assert r["source_type"] == "backfill"
    assert r["published_at"] == "2020-03-13 19:30:00+08"


def test_rows_from_cctv_skips_empty_title():
    df_rows = [{"date": "20200313", "title": "   ", "content": "x"},
               {"date": "20200313", "title": "有效标题"}]
    out = rows_from_cctv("2020-03-13", df_rows)
    assert len(out) == 1
    assert out[0]["title"] == "有效标题"


def test_rows_from_economic_skips_empty_title():
    df_rows = [{"日期": "2020-03-13", "事件": "美联储降息"},
               {"日期": "2020-03-13", "事件": ""}]
    out = rows_from_economic("2020-03-13", df_rows)
    assert len(out) == 1
    r = out[0]
    assert r["title"] == "美联储降息"
    assert r["category"] == "finance"
    assert r["published_at"] == "2020-03-13 08:00:00+08"
