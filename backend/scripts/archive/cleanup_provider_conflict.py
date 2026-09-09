"""清理 provider 切换后的脏数据（akshare 发布日口径与 FRED 月初口径冲突的同月双行）。

背景：us_unemp / us_core_pce 切到 FRED 后，旧 akshare 行（report_date=发布日，如 2025-07-03）
与 FRED 行（report_date=报告月初，如 2025-07-01）按 (code, date) 主键视为不同行，导致同月
出现两条记录，趋势图产生毛刺。

清理规则（精准，保留有用历史）：
  - us_unemp / us_core_pce：删除全部 akshare 行（FRED 2016-07 起 10 年窗口已为主数据源，
    这两个指标的早期历史重要性低于口径一致性；保留 fred 行即可）
  - us_cpi_yoy：保留 akshare 的 2008-2016 历史（FRED 10 年窗口之外的有用数据，0 主键冲突）

用法：
  python scripts/cleanup_provider_conflict.py           # dry-run，只预览不删
  python scripts/cleanup_provider_conflict.py --apply   # 实际执行删除
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from sqlalchemy import text  # noqa: E402
from src.infra.database.market.macro_indicator import _get_db_connection  # noqa: E402

# 全删 akshare 行的指标（FRED 已完整覆盖，口径冲突需清理）
_FULL_DROP = ["us_unemp", "us_core_pce"]
# 保留 akshare 历史的指标（FRED 窗口外的有用数据）
_KEEP_HISTORY = ["us_cpi_yoy"]


def main():
    apply = "--apply" in sys.argv
    db = _get_db_connection()

    print(f"模式：{'🟢 实际删除' if apply else '🟡 dry-run（加 --apply 执行删除）'}\n")

    total_deleted = 0
    for code in _FULL_DROP:
        with db.session_scope() as s:
            row = s.exec(text(
                f"SELECT count(*) FROM macro_indicator WHERE indicator_code='{code}' AND provider='akshare'"
            )).fetchall()[0][0]
            fred_row = s.exec(text(
                f"SELECT count(*) FROM macro_indicator WHERE indicator_code='{code}' AND provider='fred'"
            )).fetchall()[0][0]
            print(f"[{code}] akshare 残留 {row} 行，fred 现有 {fred_row} 行 → {'删除 akshare 全部' if row else '无残留'}")
            if row and apply:
                s.exec(text(
                    f"DELETE FROM macro_indicator WHERE indicator_code='{code}' AND provider='akshare'"
                ))
            total_deleted += row if apply else 0

    print()
    for code in _KEEP_HISTORY:
        with db.session_scope() as s:
            row = s.exec(text(
                f"SELECT count(*) FROM macro_indicator WHERE indicator_code='{code}' AND provider='akshare'"
            )).fetchall()[0][0]
            print(f"[{code}] akshare {row} 行（2008-2016 历史，FRED 窗口外）→ 保留 ✅")

    print()
    if apply:
        print(f"✅ 完成，实际删除 {total_deleted} 行")
    else:
        print("（dry-run 未删除。确认无误后加 --apply 执行）")


if __name__ == "__main__":
    main()
