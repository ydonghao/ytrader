"""市值与业绩增长趋势口径换算（纯函数）。

输入序列：[{report_date: date|str, revenue: float|None,
net_profit: float|None}]，**累计口径**、升序。输出同形序列。
零 IO、不抛异常（模块惯例同 period_transform）。
"""
from typing import Any

from src.domain.market.fundamental.period_transform import transform_to_quarter


def _rd_key(report_date: Any) -> tuple[int, int] | None:
    """report_date（date|str）→ (year, month)；无效返回 None。"""
    if report_date is None:
        return None
    y = getattr(report_date, "year", None)
    m = getattr(report_date, "month", None)
    if y is None:
        parts = str(report_date)[:10].split("-")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            y, m = int(parts[0]), int(parts[1])
        else:
            return None
    return (int(y), int(m))


def to_quarterly(rows: list[dict]) -> list[dict]:
    """累计序列 → 单季序列（委托 transform_to_quarter，含跨年重置）。

    委托后会混入 transform 派生的多余键，这里收敛回三键。
    transform 的 _diff_or_keep 在基准为 None 时降级透出累计值
    （既有消费方依赖该语义，period_transform 不动）；本口径不外推，
    故后置处理：差分期（同年上一期存在）若基准字段缺值 → 该期置
    None（None 传播，与 to_ttm 文档承诺一致）。
    """
    stripped = [
        {"report_date": r.get("report_date"),
         "revenue": r.get("revenue"),
         "net_profit": r.get("net_profit")}
        for r in rows
    ]
    # 原始累计值快照：transform 就地差分，基准须用差分前的值。
    orig = [
        {"report_date": r.get("report_date"),
         "revenue": r.get("revenue"),
         "net_profit": r.get("net_profit")}
        for r in stripped
    ]
    out = transform_to_quarter(stripped)
    prev_by_year: dict[int, dict] = {}
    for r_out, r_prev_src in zip(out, orig):
        k = _rd_key(r_prev_src.get("report_date"))
        if k is None:
            continue
        prev = prev_by_year.get(k[0])
        if prev is not None:  # 差分期（非该年首期，与 transform 分组一致）
            for f in ("revenue", "net_profit"):
                if not isinstance(prev.get(f), (int, float)):
                    r_out[f] = None
        prev_by_year[k[0]] = r_prev_src
    return [
        {"report_date": r.get("report_date"),
         "revenue": r.get("revenue"),
         "net_profit": r.get("net_profit")}
        for r in out
    ]


def to_ttm(rows: list[dict]) -> list[dict]:
    """累计序列 → TTM 序列。

    TTM_t = FY_{y-1} + YTD_t − YTD_{y-1 同期}；
    年报期（month==12）TTM = 全年值本身；
    依赖期缺失或非数值 → 该期 None（不外推）。
    """
    cum: dict[tuple[int, int], dict] = {}
    for r in rows:
        k = _rd_key(r.get("report_date"))
        if k is not None:
            cum[k] = r
    out: list[dict] = []
    for r in rows:
        k = _rd_key(r.get("report_date"))
        item = {f: r.get(f) for f in ("report_date", "revenue", "net_profit")}
        if k is None:
            item["revenue"] = None
            item["net_profit"] = None
            out.append(item)
            continue
        y, m = k
        if m == 12:
            out.append(item)          # 年报即 TTM
            continue
        fy_prev = cum.get((y - 1, 12))
        same_prev = cum.get((y - 1, m))
        for f in ("revenue", "net_profit"):
            cur = r.get(f)
            base = fy_prev.get(f) if fy_prev else None
            prev = same_prev.get(f) if same_prev else None
            if all(isinstance(v, (int, float))
                   for v in (cur, base, prev)):
                item[f] = cur + base - prev
            else:
                item[f] = None
        out.append(item)
    return out


def align_mv(
    monthly_mv: list[dict], report_dates: list,
) -> list[dict]:
    """月度市值序列对齐报告期末：取 report_date 所在月及之前的最近月度点。

    月度点代表其所属整月（月度序列按 YYYY-MM 粒度对齐，
    而非按日比较）。

    Args:
        monthly_mv: [{date: date|str, total_mv: float|None}]（乱序可容忍）。
        report_dates: 报告期列表（date|str）。
    Returns:
        [{report_date: "YYYY-MM-DD", total_mv: float|None}]，
        早于首个月度点或无可用点 → total_mv None。
    """

    def _as_str(d: Any):
        if d is None:
            return None
        return d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]

    pts = sorted(
        [(_as_str(p.get("date")), p.get("total_mv"))
         for p in monthly_mv if _as_str(p.get("date"))],
        key=lambda t: t[0],
    )
    out = []
    for rd in report_dates:
        rd_str = _as_str(rd)
        mv = None
        if rd_str:
            for d_str, v in pts:
                if d_str[:7] <= rd_str[:7]:
                    mv = v
                else:
                    break
        out.append({"report_date": rd_str, "total_mv": mv})
    return out
