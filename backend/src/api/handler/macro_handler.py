"""宏观板块 API handler — 仪表盘 / 指标 / 判断快照 / 验证对照。

遵循 router → handler → repository 分层，统一用 src.pkg.responses 返回。
"""
from datetime import date, datetime
from typing import Any, Optional

from src.pkg import responses


# ── 仪表盘（聚合视图）──────────────────────────────────────────
def dashboard() -> Any:
    """聚合视图：最新宏观指标卡片 + 最新快照 + 历史命中率。"""
    from src.infra.database.market.macro_indicator import (
        create_macro_indicator_repository,
    )
    from src.infra.database.market.macro_view import (
        create_macro_view_repository,
    )

    ind_repo = create_macro_indicator_repository()
    view_repo = create_macro_view_repository()

    # 最新指标读数（带元数据）
    meta_map = {m["code"]: m for m in ind_repo.list_meta()}
    latest = ind_repo.get_latest_values()
    # 查各指标数据量，过滤 ≤2 期的（种子数据不可靠）
    import psycopg2 as _psy
    from src.infra.database.sql_engine.dsn import get_dsn as _get_dsn
    valid_codes: set = set()
    data_start_map: dict = {}
    try:
        _conn = _psy.connect(_get_dsn())
        with _conn.cursor() as _cur:
            _cur.execute(
                "SELECT indicator_code, MIN(report_date) FROM macro_indicator "
                "GROUP BY indicator_code HAVING count(*) > 2"
            )
            for r in _cur.fetchall():
                valid_codes.add(r[0])
                data_start_map[r[0]] = r[1].isoformat() if r[1] else None
        _conn.close()
    except Exception:
        valid_codes = {v["indicator_code"] for v in latest}

    indicators = []
    for v in latest:
        if v["indicator_code"] not in valid_codes:
            continue
        m = meta_map.get(v["indicator_code"], {})
        indicators.append({**v, "meta": m,
                           "data_start": data_start_map.get(v["indicator_code"])})
    # 过滤掉长历史变体（_long），避免仪表盘出现重复卡片
    indicators = [i for i in indicators if not i["indicator_code"].endswith("_long")]

    # 最新快照
    latest_view = view_repo.get_latest()

    # 历史命中率（已评分快照的平均 accuracy）
    scored = view_repo.list_views(status="scored", limit=200)
    macro_accs = [s["macro_accuracy"] for s in scored if s["macro_accuracy"] is not None]
    asset_accs = [s["asset_accuracy"] for s in scored if s["asset_accuracy"] is not None]
    avg_macro = round(sum(macro_accs) / len(macro_accs), 3) if macro_accs else None
    avg_asset = round(sum(asset_accs) / len(asset_accs), 3) if asset_accs else None

    return responses.success({
        "indicators": indicators,
        "latest_view": latest_view,
        "hit_rate": {
            "macro_avg": avg_macro,
            "asset_avg": avg_asset,
            "scored_count": len(scored),
        },
    })


# ── 宏观指标 ──────────────────────────────────────────────────
def latest_indicators(
    category: Optional[str] = None, group: Optional[str] = None
) -> Any:
    """全部关键指标最新值（含趋势/阈值线/状态徽章）。

    category 过滤 cn/us/global；group 过滤 growth/inflation/employment/monetary。
    过滤掉数据量不足（≤2 期）的指标，避免展示不可靠的种子数据。
    """
    from src.infra.database.market.macro_indicator import (
        create_macro_indicator_repository,
    )
    repo = create_macro_indicator_repository()
    meta_list = repo.list_meta(category=category, group=group)
    meta_map = {m["code"]: m for m in meta_list}
    codes = list(meta_map.keys())
    latest = repo.get_latest_values(codes=codes) if codes else []

    # 查各指标数据量，过滤 ≤2 期的（种子数据不可靠）
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn
    valid_codes: set = set()
    try:
        conn = psycopg2.connect(get_dsn())
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indicator_code FROM macro_indicator "
                "GROUP BY indicator_code HAVING count(*) > 2"
            )
            valid_codes = {r[0] for r in cur.fetchall()}
        conn.close()
    except Exception:
        valid_codes = set(codes)  # 查询失败时不过滤

    out = []
    for v in latest:
        code = v["indicator_code"]
        if code not in valid_codes:
            continue   # 跳过数据量不足的
        m = meta_map.get(code, {})
        out.append({**v, "meta": m})
    return responses.success(out)


def indicator_series(
    code: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 500,
) -> Any:
    """单指标历史时序（画图用，升序）。"""
    from src.infra.database.market.macro_indicator import (
        create_macro_indicator_repository,
    )
    repo = create_macro_indicator_repository()
    sd = datetime.strptime(start, "%Y-%m-%d").date() if start else None
    ed = datetime.strptime(end, "%Y-%m-%d").date() if end else None
    series = repo.get_series(code, start_date=sd, end_date=ed, limit=limit)
    meta_list = repo.list_meta()
    meta = next((m for m in meta_list if m["code"] == code), {})
    return responses.success({"code": code, "meta": meta, "series": series})


# ── 课程簇 4：宏观周期信号（规则驱动，与 LLM 快照互补）─────────────────────

# macro_indicator code(带 cn_ 前缀) → 本模块裸 key 的映射。
_CN_CODE_MAP = {
    "cn_pmi": "pmi",
    "cn_ppi_yoy": "ppi_yoy",
    "cn_cpi_yoy": "cpi_yoy",
    "cn_m2_yoy": "m2_growth",
    "cn_m1_yoy": "m1_growth",
    "cn_lpr_1y": "lpr",
    "cn_industrial_yoy": "industrial_profit",  # 工业增加值 proxy 工业利润增速方向
    "cn_fai_yoy": "fai_invest",
    "cn_realestate_inv_yoy": "real_estate_invest",
    "cn_retail_yoy": "retail_sales",
    "cn_gdp_yoy": "gdp_growth",  # 若已同步 GDP
}


def cycle_signals() -> Any:
    """宏观周期规则信号（《股票投资课程》02/31 集）。

    读取 macro_indicator 最新读数，按课程规则输出：
      - phase：PMI × PPI 四象限定周期（低迷/复苏/过热/滞胀）
      - rotation：该周期阶段的行业轮动建议（超配行业）
      - money_supply_gap：M2 vs GDP 货币超发判断（loose/neutral/tight）
      - sector_checklist：三部门景气度体检（居民/企业/政府）

    与 LLM 快照(macro_view)互补：本端点为确定性规则，可复现、无幻觉。
    """
    from src.domain.market.intel.macro.cycle_signals import (
        business_cycle_phase,
        industry_rotation,
        money_supply_gap,
        three_sector_checklist,
    )
    from src.domain.market.intel.macro.cycle_stages import m1_m2_scissors
    from src.infra.database.market.macro_indicator import (
        create_macro_indicator_repository,
    )

    repo = create_macro_indicator_repository()
    try:
        latest = repo.get_latest_values(codes=list(_CN_CODE_MAP.keys()))
    except Exception as e:  # noqa: BLE001
        return responses.error(f"读取宏观指标失败: {e}")

    # 指标值：百分比类统一转小数（macro_indicator 多以 % 存储）。
    readings: dict[str, float] = {}
    pct_codes = {"cpi_yoy", "ppi_yoy", "m2_growth", "m1_growth",
                 "industrial_profit", "fai_invest", "real_estate_invest",
                 "retail_sales", "gdp_growth"}
    for row in latest or []:
        code = row.get("indicator_code")
        bare = _CN_CODE_MAP.get(code)
        if not bare:
            continue
        v = row.get("value")
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if bare in pct_codes and abs(fv) > 1.0:
            fv = fv / 100.0  # 5.0 (%) → 0.05
        readings[bare] = fv

    phase = business_cycle_phase(readings.get("pmi"), readings.get("ppi_yoy"))
    rotation = industry_rotation(phase["phase"]) if phase else None
    msg = money_supply_gap(
        readings.get("m2_growth"), readings.get("gdp_growth"),
        cpi=readings.get("cpi_yoy"),
    )
    checklist = three_sector_checklist(readings)
    scissors = m1_m2_scissors(readings.get("m1_growth"), readings.get("m2_growth"))

    return responses.success({
        "readings": readings,
        "phase": phase,
        "rotation": rotation,
        "money_supply_gap": msg,
        "m1_m2_scissors": scissors,
        "sector_checklist": checklist,
        "note": (
            "phase 由 PMI×PPI 四象限确定；rotation 为该阶段建议超配行业；"
            "money_supply_gap 需 GDP 数据，未同步时 real_gap/nominal 可能为空；"
            "m1_m2_scissors>0 资金活化(利好股市)，<0 定期化/空转。"
        ),
    })


# ── 课程第五批：市场资金面 + 中美利差 ───────────────────────────────────────

def north_flow_signal_report(limit: int = 60) -> Any:
    """北向资金信号（《股票投资课程》31）。

    读 north_flow_daily 最近 N 个交易日净流入，判外资情绪：
    连续净流入>=3 日 sustained_inflow（外资看好，利好）。
    """
    from src.infra.database.market.market_sentiment import (
        create_market_sentiment_repository,
    )
    from src.domain.market.intel.market.fund_flow import north_flow_signal

    try:
        repo = create_market_sentiment_repository()
        rows = repo.get_north_flow(limit=limit)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询北向资金失败: {e}")
    flows = [r.net_buy for r in rows if r.net_buy is not None]
    if not flows:
        return responses.error("无北向资金数据（需先同步 market_sentiment）")
    sig = north_flow_signal(flows)
    return responses.success({
        "series_len": len(flows),
        "date_range": [
            rows[0].trade_date.isoformat() if rows[0].trade_date else None,
            rows[-1].trade_date.isoformat() if rows[-1].trade_date else None,
        ],
        "cumulative": sig.cumulative,
        "latest": sig.latest,
        "consecutive_inflow": sig.consecutive_inflow,
        "consecutive_outflow": sig.consecutive_outflow,
        "net_verdict": sig.net_verdict,
        "momentum": sig.momentum,
        "note": "sustained_inflow(连入>=3 外资看好利好) / sustained_outflow(连出>=3 撤离) / mixed。",
    })


def margin_sentiment_report(limit: int = 60) -> Any:
    """融资融券杠杆情绪（《股票投资课程》27）。

    读 margin_balance_daily 最近 N 日余额，判杠杆情绪：
    余额连续上升 levering_up（乐观加杠杆），下降 deleveraging。
    """
    from src.infra.database.market.market_sentiment import (
        create_market_sentiment_repository,
    )
    from src.domain.market.intel.market.fund_flow import margin_sentiment

    try:
        repo = create_market_sentiment_repository()
        rows = repo.get_margin_balance(limit=limit)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询两融余额失败: {e}")
    balances = [r.margin_balance for r in rows if r.margin_balance]
    if len(balances) < 2:
        return responses.error("无足够两融余额数据（需先同步 market_sentiment）")
    sig = margin_sentiment(balances)
    return responses.success({
        "series_len": len(balances),
        "latest_balance": sig.latest_balance,
        "latest_change": sig.latest_change,
        "consecutive_increase": sig.consecutive_increase,
        "consecutive_decrease": sig.consecutive_decrease,
        "verdict": sig.verdict,
        "note": "levering_up(余额连升=乐观加杠杆) / deleveraging(连降=去杠杆) / stable。",
    })


def rate_differential_report() -> Any:
    """中美利差（《股票投资课程》02/31）。

    读 macro_indicator 的 cn_bond_10y（中国 10Y 国债，已由 market_sentiment 同步）；
    美国 10Y 需 us_bond_10y（fred 同步，未就绪时仅返回中国端）。
    """
    from src.domain.market.intel.macro.rate_differential import (
        cn_us_yield_differential,
    )
    from src.infra.database.market.macro_indicator import (
        create_macro_indicator_repository,
    )

    repo = create_macro_indicator_repository()
    try:
        cn_rows = repo.get_series("cn_bond_10y", limit=2)
        us_rows = repo.get_series("us_bond_10y", limit=2)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"查询国债收益率失败: {e}")

    def _latest_pct(rows):
        # macro_indicator 以 % 存；转小数
        if not rows:
            return None, None
        cur = rows[-1].get("value") if isinstance(rows[-1], dict) else getattr(rows[-1], "value", None)
        prev = (rows[-2].get("value") if isinstance(rows[-2], dict)
                else getattr(rows[-2], "value", None)) if len(rows) >= 2 else None
        return (cur / 100.0 if cur is not None else None), (prev / 100.0 if prev is not None else None)

    cn_cur, _ = _latest_pct(cn_rows)
    us_cur, _ = _latest_pct(us_rows)
    diff = cn_us_yield_differential(cn_cur, us_cur)
    return responses.success({
        "cn_bond_10y": cn_cur,
        "us_bond_10y": us_cur,
        "differential": diff.differential if diff else None,
        "inverted": diff.inverted if diff else None,
        "note": "differential=中国10Y−美国10Y；<0 倒挂(资本流出压力)。"
                "us_bond_10y 需 fred 同步，未就绪时为 None。",
    })


def futures_basis_report(code: str = "IF0") -> Any:
    """股指期货升贴水（《股票投资课程》27 交割日魔咒）。

    取股指期货主力连续（IF0=沪深300）最新价 + 沪深300 现货最新价，
    算 basis/升贴水率：大升水(>=2%) → 交割日卖压预警。
    """
    from src.domain.market.derivatives.leverage import futures_basis_signal
    from src.domain.market.sync.providers.akshare_provider import AkshareProvider

    # 期货主力价
    provider = AkshareProvider()
    try:
        fut = provider.fetch_index_futures_main(code=code, days=5)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"取期货行情失败: {e}")
    if not fut or fut[-1].get("close") is None:
        return responses.error(f"无 {code} 期货行情")
    futures_price = fut[-1]["close"]

    # 现货价：沪深300（IF 对应 000300）。用 index_ohlcv repo 取最新。
    spot_symbol = {"IF0": "sh000300", "IH0": "sh000016",
                   "IC0": "sh000905", "IM0": "sh000852"}.get(code, "sh000300")
    spot_price = None
    try:
        import psycopg2
        from src.infra.database.sql_engine.dsn import get_dsn
        conn = psycopg2.connect(get_dsn())
        with conn.cursor() as cur:
            cur.execute(
                "SELECT close_ FROM index_ohlcv WHERE symbol=%s "
                "ORDER BY trade_date DESC LIMIT 1",
                (spot_symbol,),
            )
            row = cur.fetchone()
            if row and row[0]:
                spot_price = float(row[0])
        conn.close()
    except Exception as e:  # noqa: BLE001
        return responses.error(f"取现货指数失败: {e}")

    if spot_price is None:
        return responses.error(f"无 {spot_symbol} 现货指数数据")

    basis = futures_basis_signal(futures_price, spot_price)
    if basis is None:
        return responses.error("升贴水计算失败（价格非法）")
    return responses.success({
        "code": code,
        "spot_symbol": spot_symbol,
        "futures_price": futures_price,
        "spot_price": spot_price,
        "basis": basis.basis,
        "basis_pct": basis.basis_pct,
        "contango": basis.contango,
        "delivery_sell_pressure": basis.delivery_sell_pressure,
        "note": "basis_pct>=2% 大升水→交割日卖压预警(交割日魔咒)。",
    })


# ── 判断快照 ──────────────────────────────────────────────────
def list_views(status: Optional[str] = None, limit: int = 50) -> Any:
    """历史快照列表（按 snapshot_date 倒序）。"""
    from src.infra.database.market.macro_view import (
        create_macro_view_repository,
    )
    repo = create_macro_view_repository()
    views = repo.list_views(status=status, limit=min(limit, 200))
    return responses.success(views)


def get_view(view_id: int) -> Any:
    """单快照详情（signals/predictions/validation 全量）。"""
    from src.infra.database.market.macro_view import (
        create_macro_view_repository,
    )
    repo = create_macro_view_repository()
    view = repo.get(view_id)
    if not view:
        return responses.not_found(msg=f"macro view #{view_id} not found")
    return responses.success(view)


def track_view(view_id: int) -> Any:
    """该快照预测期内对应指数/汇率/商品 K 线（前端叠加判断点对照）。

    返回每个预测标的在 [snapshot_date, snapshot_date+horizon] 的日线，
    标注判断点 T 与验证点 T+horizon。
    """
    from src.infra.database.market.macro_view import (
        create_macro_view_repository,
    )
    from src.domain.market.intel.macro.snapshot import _period_return
    from datetime import timedelta
    import psycopg2
    from src.domain.market.sync.jobs.macro_sync import _get_dsn

    repo = create_macro_view_repository()
    view = repo.get(view_id)
    if not view:
        return responses.not_found(msg=f"macro view #{view_id} not found")

    snap_str = view["snapshot_date"]
    snap_date = datetime.strptime(snap_str, "%Y-%m-%d").date()
    horizon = view["horizon_days"]
    end_date = snap_date + timedelta(days=int(horizon * 1.6))  # 日历日宽放

    predictions = view.get("asset_predictions", [])
    tracks = []
    for p in predictions:
        sym = p["symbol"]
        bars = _fetch_period_bars(sym, snap_date, end_date)
        tracks.append({
            "symbol": sym,
            "name": p.get("name", sym),
            "predicted": p.get("predicted"),
            "bars": bars,
        })
    return responses.success({
        "view_id": view_id,
        "snapshot_date": snap_str,
        "horizon_days": horizon,
        "snapshot_point": snap_str,
        "tracks": tracks,
    })


def _fetch_period_bars(symbol: str, start: date, end: date) -> list[dict]:
    """取 [start, end] 区间日线 bar（index/fx/commodity 分派）。"""
    import psycopg2
    from src.domain.market.sync.jobs.macro_sync import _get_dsn

    is_fx = symbol.isalpha() and len(symbol) == 6
    is_commodity = symbol in {"XAU", "XAG", "XPT", "XPD", "GC", "SI", "OIL", "CL", "NG"}
    if is_fx:
        sql = ("SELECT date AS d, rate AS close FROM fx_rate "
               "WHERE pair = %s AND date BETWEEN %s AND %s ORDER BY date")
    elif is_commodity:
        sql = ("SELECT trade_date AS d, close_ AS close FROM commodity_ohlcv "
               "WHERE symbol = %s AND trade_date BETWEEN %s AND %s ORDER BY trade_date")
    else:
        sql = ("SELECT trade_date AS d, close_ AS close FROM index_ohlcv "
               "WHERE symbol = %s AND trade_date BETWEEN %s AND %s ORDER BY trade_date")
    try:
        with psycopg2.connect(_get_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (symbol, start, end))
                rows = cur.fetchall()
        return [{"date": str(r[0]), "close": float(r[1])} for r in rows if r[1] is not None]
    except Exception:
        return []


# ── 手动触发生成 ──────────────────────────────────────────────
def generate_view() -> Any:
    """手动触发：生成一条宏观判断快照（同步阻塞返回，含 view_id）。"""
    from src.domain.market.intel.macro.snapshot import generate_snapshot
    try:
        res = generate_snapshot()
    except Exception as e:
        return responses.fail(msg=f"生成失败: {e}")
    if res.get("errors"):
        return responses.fail(msg="; ".join(res["errors"]))
    return responses.success({
        "view_id": res["view_id"],
        "run_id": res["run_id"],
        "msg": "快照已生成",
    })


def record_view(body: dict) -> Any:
    """人记录自己的宏观判断（立场 + 置信度 + 理由）。

    创建一条 author='user' 的 macro_view，status='pending'，等待季度后验证。
    """
    from datetime import date as _date
    from conf import app_config
    from src.infra.database.market.macro_view import (
        create_macro_view_repository,
    )

    overall_stance = (body.get("overall_stance") or "").strip()
    summary = (body.get("summary") or "").strip()
    if overall_stance not in ("bullish", "bearish", "neutral"):
        return responses.fail(msg="overall_stance 必须为 bullish/bearish/neutral")
    if not summary:
        return responses.fail(msg="summary（判断理由）不能为空")

    confidence = body.get("confidence", 5.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 5.0
    confidence = max(0.0, min(10.0, confidence))

    repo = create_macro_view_repository()
    view_id = repo.create({
        "snapshot_date": _date.today(),
        "author": "user",
        "horizon_days": app_config.macro_universe.snapshot_horizon_days,
        "overall_stance": overall_stance,
        "confidence": confidence,
        "summary": summary,
        "macro_judgments": [],
        "asset_predictions": [],
        "signals": {},
        "status": "pending",
    })
    return responses.success({"view_id": view_id, "msg": "判断已记录，将在季度后验证"})


# ── 历史事件 ──────────────────────────────────────────────────
def list_events() -> Any:
    """中国重大经济事件列表（供前端图表标注）。"""
    from conf import app_config
    events = []
    for e in app_config.macro_universe.macro_events:
        events.append({"date": e.date, "title": e.title, "desc": e.desc})
    return responses.success(events)
