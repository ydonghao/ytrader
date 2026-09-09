"""申万成分股同步 job：二级行业成分 → sw_industry_member 全量重灌。

数据源（akshare 直连，仅 job 内消费；handler 不 import akshare）：
  sw_index_first_info()      31 个一级（行业名称 → 行业代码 映射）
  sw_index_second_info()     131 个二级（含"上级行业"名称列）
  index_component_sw(code)   每个二级的成分股（约 5400 行合计）

一级归属由 second_info 的上级行业**名称**经 first_info 映射为代码——
不单独拉一级成分（与申万官方一级成分可能有个股级微差，spec 已注明）。
单行业失败跳过（全量重灌幂等，下轮补齐）；0.3s 间隔防限流。
"""
import logging
import time

import akshare as ak
import pandas as pd

from src.infra.database.market.sw_industry import (
    create_sw_industry_repository,
)

log = logging.getLogger(__name__)


def _strip_si(code: str) -> str:
    return str(code).split(".")[0].strip()


def _to_prefixed(code: str) -> str:
    c = str(code).strip()
    if c.startswith(("sh", "sz", "bj")):
        return c
    if c.startswith("6"):
        return f"sh{c}"
    if c.startswith(("0", "3")):
        return f"sz{c}"
    if c.startswith(("8", "4")):
        return f"bj{c}"
    return c


def build_member_rows(first_info: pd.DataFrame,
                      second_info: pd.DataFrame,
                      cons_by_code: dict) -> list:
    """纯转换：一二级清单 + 各行业成分 DataFrame → member 行。

    cons_by_code 缺失的行业（拉取失败）整组跳过。
    """
    l1_code_by_name = {
        str(r["行业名称"]).strip(): _strip_si(r["行业代码"])
        for _, r in first_info.iterrows()
    }
    rows: list[dict] = []
    for _, sec in second_info.iterrows():
        l2_code = _strip_si(sec["行业代码"])
        l2_name = str(sec["行业名称"]).strip()
        l1_name = str(sec["上级行业"]).strip()
        l1_code = l1_code_by_name.get(l1_name)
        if not l1_code:
            log.warning("[sw_member] 一级映射缺失: %s", l1_name)
            continue
        cons = cons_by_code.get(l2_code)
        if cons is None or cons.empty:
            continue
        for _, c in cons.iterrows():
            inc = c.get("计入日期")
            rows.append({
                "symbol": _to_prefixed(c["证券代码"]),
                "sw_code_l2": l2_code,
                "code": str(c["证券代码"]).strip(),
                "name": c.get("证券名称"),
                "sw_code_l1": l1_code,
                "sw_name_l1": l1_name,
                "sw_name_l2": l2_name,
                "weight": float(c["最新权重"])
                if pd.notna(c.get("最新权重")) else None,
                "included_date": inc if isinstance(inc, str) else (
                    inc.isoformat() if hasattr(inc, "isoformat") else None
                ),
            })
    return rows


def run(interval: float = 0.3) -> dict:
    """全量同步。Returns {industries, failed: [sw_code...], members}。"""
    first_info = ak.sw_index_first_info()
    second_info = ak.sw_index_second_info()
    cons_by_code: dict = {}
    failed: list[str] = []
    for _, sec in second_info.iterrows():
        code = _strip_si(sec["行业代码"])
        try:
            cons_by_code[code] = ak.index_component_sw(code)
        except Exception as e:  # noqa: BLE001
            failed.append(code)
            log.warning("[sw_member] %s 拉取失败: %s", code, e)
        finally:
            time.sleep(interval)
    rows = build_member_rows(first_info, second_info, cons_by_code)
    wrote = create_sw_industry_repository().replace_all_members(rows)
    log.info("[sw_member] 成员 %d 行，失败行业 %d 个",
             wrote, len(failed))
    return {
        "industries": len(cons_by_code), "failed": failed, "members": wrote,
    }
