"""MacroSnapshotJob
==================
宏观判断快照：生成（每周/手动）+ 验证（每日打分）。

generate_snapshot():
  调 macro_analyst_node 产出结构化判断 → 落库 macro_view（status=pending）。
  走 tracing 记录 run_id，可回查完整 prompt/response。

validate_pending():
  扫描到期 pending 快照，双轨打分：
    第一层（宏观状态）：用到期日的宏观指标实际值对照判断方向。
    第二层（资产方向）：用预测期内指数/汇率/商品实际收益对照预测方向。
  回写 validation + accuracy + status=scored。

调用：
  python -m src.domain.market.intel.macro.snapshot
"""
import asyncio
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent.parent  # backend/
sys.path.insert(0, str(_BACKEND))

from conf import app_config  # noqa: E402
from loguru import logger  # noqa: E402

from src.domain.market.intel.macro.agents.macro_analyst import macro_analyst_node  # noqa: E402
from src.infra.database.market.macro_view import (  # noqa: E402
    create_macro_view_repository,
)


# ── 维度 → 验证指标的映射 ──────────────────────────────────────
# 第一层每个宏观维度用哪个指标的实际值来验证其方向判断。
# macro_indicator 中 code → 该维度方向的实际代理变量。
_DIM_TO_INDICATOR = {
    "growth": "cn_pmi",        # PMI↑ = 增长扩张
    "inflation": "cn_cpi_yoy", # CPI↑ = 通胀上行
    "liquidity": "cn_m2_yoy",  # M2↑ = 流动性宽松
    # leverage / regime / recession_risk 无单一客观指标，跳过量化验证（定性维度）
}


def generate_snapshot() -> dict:
    """生成一条宏观判断快照并落库。返回 {view_id, run_id, errors}。"""
    from src.infra.tracing.recorder import (
        record_run_start, record_run_end, set_run_id,
    )

    mu = app_config.macro_universe
    snapshot_date = date.today()
    horizon = mu.snapshot_horizon_days

    state = {
        "indicator_codes": [i.code for i in mu.indicators],
        "predict_targets": [
            {"symbol": t.symbol, "name": t.name, "asset_class": t.asset_class}
            for t in mu.predict_targets
        ],
        "snapshot_date": snapshot_date,
        "horizon_days": horizon,
    }

    # 开 tracing run（捕获完整 prompt/response，可回查）
    run_id = record_run_start(pipeline="macro_snapshot", topic=f"宏观判断 {snapshot_date}")
    if run_id:
        set_run_id(run_id)

    start_t = datetime.now()
    try:
        result = asyncio.run(macro_analyst_node(state))
    except Exception as e:
        logger.error(f"[macro_snapshot] agent 失败: {e}")
        record_run_end(run_id, "failed", error=str(e),
                       duration_ms=int((datetime.now() - start_t).total_seconds() * 1000))
        return {"view_id": None, "run_id": run_id, "errors": [str(e)]}

    if result.get("errors"):
        record_run_end(run_id, "failed", error="; ".join(result["errors"]),
                       duration_ms=int((datetime.now() - start_t).total_seconds() * 1000))
        return {"view_id": None, "run_id": run_id, "errors": result["errors"]}

    # 落库
    repo = create_macro_view_repository()
    view_id = repo.create({
        "snapshot_date": snapshot_date,
        "author": "ai",
        "horizon_days": horizon,
        "objective_reading": result.get("objective_reading", ""),
        "macro_judgments": result.get("macro_judgments", []),
        "regime_quadrant": result.get("regime_quadrant", ""),
        "overall_stance": result.get("overall_stance", "neutral"),
        "confidence": result.get("confidence", 5.0),
        "summary": result.get("summary", ""),
        "signals": result.get("signals", {}),
        "asset_predictions": result.get("asset_predictions", []),
        "status": "pending",
        "llm_run_id": run_id,
    })

    record_run_end(run_id, "success",
                   duration_ms=int((datetime.now() - start_t).total_seconds() * 1000))
    logger.info(f"[macro_snapshot] 生成快照 #{view_id} (run={run_id}, "
                f"regime={result.get('regime_quadrant')})")
    return {"view_id": view_id, "run_id": run_id, "errors": []}


# ═══════════════════════════════════════════════════════════
# 验证（双轨打分）
# ═══════════════════════════════════════════════════════════
def _direction_from_values(old: float, new: float, threshold_pct: float = 1.0) -> str:
    """两个值对比定方向：变化幅度 < threshold_pct 视为 flat。"""
    if old == 0 or old is None or new is None:
        return "flat"
    pct = abs((new - old) / abs(old)) * 100
    if pct < threshold_pct:
        return "flat"
    return "up" if new > old else "down"


def _validate_macro_judgments(
    judgments: list[dict], snapshot_date: date, as_of: date,
) -> tuple[list[dict], float | None]:
    """第一层验证：用 [snapshot_date, as_of] 间指标实际方向对照判断。

    对每个有对应指标的维度：取快照日附近值 vs 验证日附近值，定实际方向，对照预测。
    返回 (validation_list, accuracy)。无任何可验证维度时 accuracy=None。
    """
    from src.infra.database.market.macro_indicator import (
        create_macro_indicator_repository,
    )
    repo = create_macro_indicator_repository()
    validated_at = datetime.now().isoformat()
    results: list[dict] = []
    hits = 0
    total = 0
    for j in judgments:
        dim = j.get("dimension")
        predicted = j.get("stance")
        code = _DIM_TO_INDICATOR.get(dim)
        if not code or not predicted:
            # 无客观指标的定性维度（leverage/regime/recession_risk），记录但不计入命中率
            results.append({
                "dimension": dim, "predicted": predicted,
                "actual_value": None, "actual_dir": None,
                "hit": None, "validated_at": validated_at,
                "note": "定性维度，无单一客观指标量化验证",
            })
            continue
        series = repo.get_series(code, start_date=snapshot_date - timedelta(days=45),
                                  end_date=as_of, limit=500)
        if len(series) < 2:
            results.append({
                "dimension": dim, "predicted": predicted,
                "actual_value": None, "actual_dir": None,
                "hit": None, "validated_at": validated_at,
                "note": "验证区间内数据不足",
            })
            continue
        # 起点（接近 snapshot_date 的最近值）vs 终点（as_of 前最近值）
        old_val = series[0]["value"]
        new_val = series[-1]["value"]
        actual_dir = _direction_from_values(old_val, new_val)
        hit = (predicted == actual_dir)
        results.append({
            "dimension": dim, "predicted": predicted,
            "actual_value": new_val, "actual_dir": actual_dir,
            "hit": hit, "validated_at": validated_at,
            "old_value": old_val,
        })
        total += 1
        if hit:
            hits += 1
    accuracy = (hits / total) if total > 0 else None
    return results, accuracy


def _validate_asset_predictions(
    predictions: list[dict], snapshot_date: date, as_of: date,
) -> tuple[list[dict], float | None]:
    """第二层验证：用预测期内实际收益对照预测方向。

    返回 (validation_list, accuracy)。
    """
    from src.domain.market.intel.macro.context import _query_ohlcv_return
    validated_at = datetime.now().isoformat()
    results: list[dict] = []
    hits = 0
    total = 0
    for p in predictions:
        sym = p.get("symbol")
        predicted = p.get("predicted")
        # 取 snapshot_date 当日收盘 → as_of 当日收盘的收益
        ret = _period_return(sym, snapshot_date, as_of)
        if ret is None:
            results.append({
                "symbol": sym, "predicted": predicted,
                "actual_return": None, "actual_dir": None,
                "hit": None, "validated_at": validated_at,
                "note": "价格数据不足",
            })
            continue
        actual_dir = "up" if ret > 0.01 else ("down" if ret < -0.01 else "flat")
        hit = (predicted == actual_dir)
        results.append({
            "symbol": sym, "predicted": predicted,
            "actual_return": round(ret * 100, 2), "actual_dir": actual_dir,
            "hit": hit, "validated_at": validated_at,
        })
        total += 1
        if hit:
            hits += 1
    accuracy = (hits / total) if total > 0 else None
    return results, accuracy


# 人记录验证用的代表指数组合（沪深300 + 标普500 等权）
_USER_STANCE_PROXY_SYMBOLS = ["sh000300", "US.INX"]


def validate_user_stance(
    stance: str, snapshot_date: date, as_of: date,
) -> tuple[list[dict], float | None]:
    """人记录的立场验证：用代表指数组合（沪深300+标普500）实际方向对照。

    人只填 overall_stance（bullish/bearish/neutral），无 macro_judgments 维度。
    bullish → 预期组合上涨、bearish → 预期下跌、neutral → 预期震荡。
    返回 (validation_list, accuracy)。accuracy 为 0.0 或 1.0（单命题）。
    """
    validated_at = datetime.now().isoformat()
    stance_to_dir = {"bullish": "up", "bearish": "down", "neutral": "flat"}
    predicted = stance_to_dir.get(stance, "flat")

    # 取组合各成分收益，等权平均
    returns = []
    details = []
    for sym in _USER_STANCE_PROXY_SYMBOLS:
        ret = _period_return(sym, snapshot_date, as_of)
        if ret is not None:
            returns.append(ret)
            details.append({"symbol": sym, "return_pct": round(ret * 100, 2)})

    if not returns:
        return [{
            "dimension": "overall_stance", "predicted": predicted,
            "actual_dir": None, "hit": None,
            "validated_at": validated_at, "note": "代表指数数据不足",
        }], None

    avg_ret = sum(returns) / len(returns)
    actual_dir = "up" if avg_ret > 0.01 else ("down" if avg_ret < -0.01 else "flat")
    hit = (predicted == actual_dir)
    return [{
        "dimension": "overall_stance", "predicted": predicted,
        "actual_dir": actual_dir, "actual_value": round(avg_ret * 100, 2),
        "hit": hit, "validated_at": validated_at,
        "proxy": details,
    }], (1.0 if hit else 0.0)


def _period_return(symbol: str, start: date, end: date) -> float | None:
    """取 [start, end] 区间收盘收益（start收盘→end收盘）。

    分派 index/fx/commodity 三类表。返回小数收益率（0.05=5%）或 None。
    """
    import psycopg2
    from src.domain.market.sync.jobs.macro_sync import _get_dsn

    is_fx = symbol.isalpha() and len(symbol) == 6
    is_commodity = symbol in {"XAU", "XAG", "XPT", "XPD", "GC", "SI", "OIL", "CL", "NG"}

    if is_fx:
        sql = ("SELECT date, rate FROM fx_rate WHERE pair = %s AND date BETWEEN %s AND %s "
               "ORDER BY date")
    elif is_commodity:
        sql = ("SELECT trade_date AS date, close_ AS close FROM commodity_ohlcv "
               "WHERE symbol = %s AND trade_date BETWEEN %s AND %s ORDER BY trade_date")
    else:
        sql = ("SELECT trade_date AS date, close_ AS close FROM index_ohlcv "
               "WHERE symbol = %s AND trade_date BETWEEN %s AND %s ORDER BY trade_date")

    try:
        with psycopg2.connect(_get_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (symbol, start, end))
                rows = cur.fetchall()
        if len(rows) < 2:
            return None
        start_close = float(rows[0][1]) if not is_fx else float(rows[0][1])
        end_close = float(rows[-1][1])
        if start_close == 0:
            return None
        return (end_close - start_close) / start_close
    except Exception as e:
        logger.debug(f"[macro_validate] _period_return({symbol}) 失败: {e}")
        return None


def validate_pending(as_of: date | None = None) -> dict:
    """扫描到期 pending 快照，双轨打分并回写。返回 {validated, errors}。"""
    as_of = as_of or date.today()
    repo = create_macro_view_repository()
    pending = repo.list_pending_for_validation(as_of)
    logger.info(f"[macro_validate] {len(pending)} 条到期快照待验证")
    n_ok = 0
    for v in pending:
        try:
            snap = v["snapshot_date"]
            snap_date = datetime.strptime(snap, "%Y-%m-%d").date() if isinstance(snap, str) else snap
            if v.get("author") == "user":
                # 人记录：只验证 overall_stance（用代表指数组合）
                macro_val, macro_acc = validate_user_stance(
                    v.get("overall_stance", "neutral"), snap_date, as_of)
                asset_val, asset_acc = [], None
            else:
                macro_val, macro_acc = _validate_macro_judgments(
                    v.get("macro_judgments", []), snap_date, as_of)
                asset_val, asset_acc = _validate_asset_predictions(
                    v.get("asset_predictions", []), snap_date, as_of)
            # 状态：两层都有可验证项→scored；否则 partial
            status = "scored" if (macro_acc is not None or asset_acc is not None) else "partial"
            repo.update_validation(
                v["id"], macro_val, asset_val, macro_acc, asset_acc, status)
            n_ok += 1
            logger.info(f"[macro_validate] 快照 #{v['id']} {snap}: "
                        f"macro_acc={macro_acc} asset_acc={asset_acc} → {status}")
        except Exception as e:
            logger.error(f"[macro_validate] 快照 #{v.get('id')} 验证失败: {e}")
    return {"validated": n_ok, "total": len(pending)}


def main():
    (_BACKEND / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(_BACKEND / "logs" / "macro_snapshot.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--validate", action="store_true", help="只跑验证，不生成")
    args = p.parse_args()
    if args.validate:
        validate_pending()
    else:
        generate_snapshot()


if __name__ == "__main__":
    main()
