"""时光机历史新闻回填 —— akshare 新闻联播/经济日历 → intel_news。

用法:
  uv run python scripts/replay_news_backfill.py \
      --start 2020-01-01 --end 2020-03-31 [--dry-run] \
      [--source cctv|economic|both]

列名以 2026-09 实测为准: news_cctv 返回英文列 date/title/content;
news_economic_baidu 预期中文列(当前环境 Baidu cookie 握手失败,不可达,
mapper 保留 事件/标题 双兜底)。历史深度: cctv 约 2016-02 起,
更早日期返回空表(empty 计数,不算错误)。

进度: backend/.replay_news_backfill_progress.json (真实落库时更新)
"""
import argparse
import hashlib
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

# python scripts/... 直跑时 sys.path[0] 是 scripts/,补 backend 根
# 使 src/conf 可导入(与 tests/conftest.py 同口径)。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.infra.database.sql_engine.dsn import get_dsn  # noqa: E402

PROGRESS = Path(__file__).resolve().parent.parent / \
    ".replay_news_backfill_progress.json"
RATE_LIMIT_SEC = 0.6  # 相邻两次上游请求之间的间隔


def make_url(source: str, day: str, title: str) -> str:
    h = hashlib.md5(title.encode("utf-8")).hexdigest()[:16]
    return f"bk:{source}:{day}:{h}"


def _to_iso_ts(day: str, hhmm: str = "09:00") -> str:
    return f"{day} {hhmm}:00+08"


def rows_from_cctv(day: str, records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        # 实测列名: title(2026-09 spike);保留"标题"兜底以防上游改回中文列
        title = str(r.get("title") or r.get("标题") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "url": make_url("cctv", day, title),
            "source": "央视新闻联播",
            "source_type": "backfill",
            "category": "cctv_news",
            "published_at": _to_iso_ts(day, "19:30"),
        })
    return out


def rows_from_economic(day: str, records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        title = str(r.get("事件") or r.get("标题") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "url": make_url("economic", day, title),
            "source": "百度经济日历",
            "source_type": "backfill",
            "category": "finance",
            "published_at": _to_iso_ts(day, "08:00"),
        })
    return out


def _upsert(conn, rows: list[dict]) -> int:
    """ON CONFLICT (url) DO NOTHING,返回实际新插入行数。"""
    if not rows:
        return 0
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO intel_news (title, url, source, source_type,
                                    category, published_at, fetched_at)
            VALUES %s
            ON CONFLICT (url) DO NOTHING
        """, [(r["title"], r["url"], r["source"], r["source_type"],
               r["category"], r["published_at"],
               datetime.now(timezone.utc))
              for r in rows])
        return cur.rowcount


def backfill(start: date, end: date, source: str, dry: bool):
    import akshare as ak

    fetchers = {
        "cctv": (ak.news_cctv, rows_from_cctv),
        "economic": (ak.news_economic_baidu, rows_from_economic),
    }
    names = ["cctv", "economic"] if source == "both" else [source]
    # per-source 进度: {source: {oldest_ok, newest_ok, done_days, failed_days, rows}}
    prog = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {}
    stats = {n: {"oldest_ok": None, "newest_ok": None, "done_days": 0,
                 "failed_days": 0, "rows": 0, "empty_days": 0} for n in names}
    conn = psycopg2.connect(get_dsn()) if not dry else None
    n_requests = 0
    try:
        d = start
        while d <= end:
            ds = d.strftime("%Y%m%d")
            for name in names:
                fetch, mapper = fetchers[name]
                # 限速: 只在两次请求"之间"等待,dry-run 也不额外拖尾
                # (dry-run 依然打上游,限速不能省)
                if n_requests:
                    time.sleep(RATE_LIMIT_SEC)
                n_requests += 1
                try:
                    df = fetch(date=ds)
                    # 映射与落库共用同一路径,dry-run 仅跳过写库
                    rows = mapper(d.isoformat(), df.to_dict("records"))
                    if not dry:
                        stats[name]["rows"] += _upsert(conn, rows)
                        conn.commit()
                    else:
                        # dry-run 也统计映射行数(即"将要写入"的行,去重前)
                        stats[name]["rows"] += len(rows)
                    stats[name]["done_days"] += 1
                    stats[name]["empty_days"] += (0 if rows else 1)
                    if rows:
                        s = stats[name]
                        if s["oldest_ok"] is None:
                            s["oldest_ok"] = ds
                        s["newest_ok"] = ds
                except Exception as e:
                    stats[name]["failed_days"] += 1
                    print(f"  [{name}] {ds} ERR {str(e)[:80]}", flush=True)
            d += timedelta(days=1)
        if not dry:
            for name in names:
                prog[name] = {"start": start.isoformat(),
                              "end": end.isoformat(),
                              "dry_run": False,
                              "updated_at": datetime.now(timezone.utc)
                              .isoformat(),
                              **stats[name]}
            PROGRESS.write_text(json.dumps(prog, ensure_ascii=False,
                                           indent=2))
        for name in names:
            s = stats[name]
            print(f"[{name}] {start}..{end} => "
                  f"ok_days={s['done_days']} empty={s['empty_days']} "
                  f"failed={s['failed_days']} rows={s['rows']}"
                  + (" (dry-run)" if dry else ""), flush=True)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="时光机历史新闻回填")
    ap.add_argument("--start", required=True, help="起始日 YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="结束日 YYYY-MM-DD")
    ap.add_argument("--source", default="both",
                    choices=["cctv", "economic", "both"])
    ap.add_argument("--dry-run", action="store_true",
                    help="只拉取统计不写库")
    a = ap.parse_args()
    backfill(date.fromisoformat(a.start), date.fromisoformat(a.end),
             a.source, a.dry_run)
