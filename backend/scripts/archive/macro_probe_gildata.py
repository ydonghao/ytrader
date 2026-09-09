"""探测 Gildata 宏观指标的可用系列名（一次性工具，辅助注册 filter）。

对候选指标各发一次短窗口查询，打印返回表中的全部指标名称，
用于确定 _MACRO_QUERIES 里每个 code 的精确 name_filter。

用法：.venv/bin/python scripts/macro_probe_gildata.py
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync.providers.gildata_provider import GildataProvider  # noqa: E402

# code → 探测用自然语言 query（30 月窗口，只为看列名）
PROBES = {
    "cn_m2_yoy": "中国M2货币供应量同比2024年1月至2026年7月月度",
    "cn_m1_yoy": "中国M1货币供应量同比2024年1月至2026年7月月度",
    "cn_retail_yoy": "中国社会消费品零售总额当月同比2024年1月至2026年7月月度",
    "cn_fai_yoy": "中国固定资产投资完成额累计同比2024年1月至2026年7月月度",
    "cn_industrial_profit_yoy": "中国规模以上工业企业利润总额累计同比2024年1月至2026年7月月度",
    "cn_cpi_yoy": "中国CPI当月同比2024年1月至2026年7月月度",
    "cn_ppi_yoy": "中国PPI当月同比2024年1月至2026年7月月度",
}


def main() -> None:
    p = GildataProvider()
    for code, query in PROBES.items():
        print(f"\n===== {code} =====")
        csv_text = p._call_macro_industry(query)
        if not csv_text:
            print("  (无返回)")
            continue
        names = set()
        import csv as _csv
        import io
        for row in _csv.DictReader(io.StringIO(csv_text)):
            md = row.get("table_markdown", "")
            for line in md.split("\n"):
                if not line.startswith("|"):
                    continue
                if "指标代码" in line or "---" in line:
                    continue
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) >= 7:
                    names.add(cells[1])
        for n in sorted(names):
            print(" ", n)


if __name__ == "__main__":
    main()
