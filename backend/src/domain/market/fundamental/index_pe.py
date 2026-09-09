"""指数整体法市盈率（纯函数）。

口径：PE = 成分股总市值和 ÷ 成分股 TTM 归母净利和（整体法）。
输入与 mcg 数据链同源同单位（亿元）。零 IO、dict 进出、不抛异常
（模块惯例同 market_cap_growth）。

披露断档语义：部分披露期（财报季 sample_count 不足）净利被门控置
None，经 to_ttm 传播——该期起至下一期完整披露前 PE 断线（pe=None），
周度任务随披露完善自动回填。
"""
from statistics import fmean, pstdev

from src.domain.market.fundamental.market_cap_growth import to_ttm

# 披露率门控：期样本数低于序列满覆盖的该比例 → 该期净利置 None
# （常数/语义同 financial_detail_handler._MCG_DISCLOSE_MIN_RATIO）
DISCLOSE_MIN_RATIO = 0.8


def gate_by_sample_count(rows: list[dict],
                         min_ratio: float = DISCLOSE_MIN_RATIO) -> list[dict]:
    """[{report_date, net_profit, sample_count}] → 同形列表。

    以序列内 max(sample_count) 为满覆盖基准，不足比例的期 net_profit
    置 None（None 经 to_ttm 传播到依赖期）。
    """
    max_cnt = max((r.get("sample_count") or 0 for r in rows), default=0)
    out = []
    for r in rows:
        partial = (max_cnt > 0
                   and (r.get("sample_count") or 0) < min_ratio * max_cnt)
        out.append({
            **r,
            "net_profit": None if partial else r.get("net_profit"),
        })
    return out


def compute_index_pe(monthly_mv: list[dict], cum_rows: list[dict],
                     min_ratio: float = DISCLOSE_MIN_RATIO) -> list[dict]:
    """月末市值点 × 累计净利序列 → 整体法 PE 月度序列。

    Args:
        monthly_mv: [{date: date|str, total_mv: float}]（亿，mcg 覆盖率
            门控后的月末点）。无市值/无日期的点跳过。
        cum_rows: [{report_date: date|str, net_profit: float|None,
            sample_count: int}]（亿，累计归母净利和）。
    Returns: [{date: "YYYY-MM-DD", pe: float|None}] 升序；
        TTM 净利缺失或 ≤0 → pe None。
    """
    ttm_rows = to_ttm([
        {"report_date": r.get("report_date"),
         "revenue": None,
         "net_profit": r.get("net_profit")}
        for r in gate_by_sample_count(cum_rows, min_ratio)
    ])
    reports = sorted(
        (str(r["report_date"])[:10], r["net_profit"])
        for r in ttm_rows if r.get("report_date") is not None
    )
    pts = sorted(
        (str(p["date"])[:10], p["total_mv"])
        for p in monthly_mv
        if p.get("date") is not None and p.get("total_mv") is not None
    )
    out = []
    j = 0
    cur_np = None
    for d_str, mv in pts:
        # 双指针：报告期 YYYY-MM ≤ 当月即视为已知（与 align_mv 同粒度语义）
        while j < len(reports) and reports[j][0][:7] <= d_str[:7]:
            cur_np = reports[j][1]
            j += 1
        pe = None
        if isinstance(cur_np, (int, float)) and cur_np > 0:
            # TTM 差分引入的浮点噪声（如 6100/6.1→1000.0000000000001）
            # 取整消除；精度与 db_quote 的 pe_ttm 口径一致（2 位小数）。
            pe = round(mv / cur_np, 2)
        out.append({"date": d_str, "pe": pe})
    return out


def mean_std(values) -> dict | None:
    """数值统计：{mean, std, sample_size}（总体标准差）；样本<2 → None。"""
    xs = [float(v) for v in values if isinstance(v, (int, float))]
    if len(xs) < 2:
        return None
    return {"mean": fmean(xs), "std": pstdev(xs), "sample_size": len(xs)}
