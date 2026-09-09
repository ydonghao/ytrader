"""
选股器路由
==========
GET  /api/v1/screener/modes   — 4 种筛选模式说明
POST /api/v1/screener/screen  — 运行选股，返回今日清单（不回测）

纯选股：按已定规则产出"今天该买谁"的清单，直接可手动下单。
4 种模式：神奇公式 / 红利 / F-Score / 自定义多因子。
价值类模式需先同步基本面（python -m src.domain.market.sync.jobs.fundamentals）。
"""
import csv
import io
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.domain.market.strategy.longterm.screener import SCREENER_MODES, screen

log = logging.getLogger(__name__)

router = APIRouter(prefix="/screener", tags=["screener"])


# ── 请求/响应模型 ──────────────────────────────────────────────────────────────


class ScreenRequest(BaseModel):
    """选股请求。"""
    mode: str = "magic_formula"          # magic_formula|dividend|fscore|custom|dividend_value|quality
    symbols: Optional[list[str]] = None  # 空 = 全沪深A股剔ST
    top_n: int = 20                      # 返回前 N 只
    as_of: Optional[str] = None          # 截止日 YYYY-MM-DD（空=今天）
    filters: dict = Field(default_factory=dict)
    # custom 模式门槛：pe_max / pb_max / roe_min / dy_min / debt_max
    # 其他模式也可覆盖默认阈值


class ExcludeRangesRequest(BaseModel):
    """全局剔除区间更新请求。"""
    ranges: list[list[str]]   # [["2015-06-15","2015-12-31"], ...]


# ── 端点 ────────────────────────────────────────────────────────────────────────


@router.get("/modes")
def list_modes():
    """4 种筛选模式说明。"""
    return {
        "code": 0,
        "msg": "ok",
        "data": [
            {
                "mode": "magic_formula",
                "display_name": "神奇公式选股",
                "description": "低 PE + 高 ROE 双排名，挑又便宜又会赚钱的公司",
                "filters_default": {"roe_min": 2.0, "pe_max": 50.0, "pe_min": 3.0},
            },
            {
                "mode": "dividend",
                "display_name": "红利选股",
                "description": "高股息率（或低 PB 近似）+ 质量过滤，吃分红又抗跌",
                "filters_default": {
                    "dy_min": 3.0, "roe_min": 2.0, "debt_max": 95.0, "pb_max": 3.0,
                },
            },
            {
                "mode": "fscore",
                "display_name": "F-Score 选股",
                "description": "财务质量打分(F-Score) + 低 PB，避开价值陷阱",
                "filters_default": {"pb_max": 3.0, "min_fscore": 3},
            },
            {
                "mode": "custom",
                "display_name": "自定义多因子",
                "description": "自由组合门槛：PE/PB/ROE/股息率/负债率",
                "filters_default": {
                    "pe_max": 999, "pb_max": 999, "roe_min": -999,
                    "dy_min": -999, "debt_max": 999,
                },
            },
            {
                "mode": "dividend_value",
                "display_name": "红利低估值",
                "description": "高股息率 + 低估分位(PB/PE/PB+PE)双因子，剔除炒作区间",
                "filters_default": {"dy_min": 3.0, "pb_max": 3.0, "pe_min": 0.0,
                                    "pe_max": 60.0, "roe_min": 8.0, "debt_max": 70.0,
                                    "value_metric": "pb", "value_window": "10y"},
            },
            {
                "mode": "quality",
                "display_name": "财务质量诊断",
                "description": "三表健康度综合评分(现金/盈利质量/费用/杜邦/商誉) + 淘汰红线(现金覆盖<1/应收>现金/亏损)，先筛掉垃圾公司",
                "filters_default": {"min_quality_score": 0, "drop_review": False},
            },
        ],
    }


@router.post("/screen")
def run_screen(req: ScreenRequest):
    """
    运行选股，返回今日清单。

    流程：拉全市场估值+财务快照 → 按模式筛选排名 → 返回前 N。
    """
    mode = req.mode.lower()
    if mode not in SCREENER_MODES:
        return {
            "code": 1,
            "msg": f"未知模式 '{mode}'，可用: {list(SCREENER_MODES)}",
            "data": None,
        }

    as_of = None
    if req.as_of:
        try:
            as_of = date.fromisoformat(req.as_of)
        except ValueError:
            return {"code": 1, "msg": "as_of 格式应为 YYYY-MM-DD", "data": None}

    try:
        result = screen(
            mode=mode,
            symbols=req.symbols,
            as_of=as_of,
            top_n=req.top_n,
            filters=req.filters,
        )
    except Exception as e:  # noqa: BLE001
        log.error(f"[screener] {mode} 失败: {e}", exc_info=True)
        return {"code": 1, "msg": f"选股失败: {e}", "data": None}

    log.info(
        "[选股] %s as_of=%s universe=%d → top%d",
        mode, result.as_of, result.universe_size, len(result.ranked_list),
    )

    return {"code": 0, "msg": "ok", "data": result.to_dict()}


# CSV 导出列顺序（与 ScreenItem.to_dict() 对齐）
_CSV_COLUMNS = [
    "rank", "symbol", "score", "pe_ttm", "pb",
    "dv_ttm", "roe", "debt_ratio", "fscore", "reason",
]
_CSV_HEADERS_CN = [
    "排名", "代码", "评分", "PE_TTM", "PB",
    "股息率%", "ROE%", "负债率%", "F-Score", "入选理由",
]


@router.get("/export")
def export_screen(
    mode: str = Query("magic_formula", description="magic_formula|dividend|fscore|custom|dividend_value|quality"),
    top_n: int = Query(20, ge=1, le=500),
    as_of: Optional[str] = Query(None, description="YYYY-MM-DD，空=今天"),
    roe_min: Optional[float] = Query(None, description="custom 模式门槛"),
    pe_max: Optional[float] = Query(None),
    pb_max: Optional[float] = Query(None),
    dy_min: Optional[float] = Query(None),
    debt_max: Optional[float] = Query(None),
):
    """导出选股结果为 CSV（浏览器直接下载）。

    内部复用 screen()，把 ranked_list 序列化为 UTF-8 BOM CSV（Excel 友好）。
    """
    m = mode.lower()
    if m not in SCREENER_MODES:
        return {
            "code": 1,
            "msg": f"未知模式 '{mode}'，可用: {list(SCREENER_MODES)}",
            "data": None,
        }

    ao = None
    if as_of:
        try:
            ao = date.fromisoformat(as_of)
        except ValueError:
            return {"code": 1, "msg": "as_of 格式应为 YYYY-MM-DD", "data": None}

    # 组装 filters（非 None 的才纳入）
    filters: dict = {}
    for k, v in [("roe_min", roe_min), ("pe_max", pe_max),
                 ("pb_max", pb_max), ("dy_min", dy_min),
                 ("debt_max", debt_max)]:
        if v is not None:
            filters[k] = v

    try:
        result = screen(mode=m, as_of=ao, top_n=top_n, filters=filters)
    except Exception as e:  # noqa: BLE001
        log.error(f"[screener/export] {m} 失败: {e}", exc_info=True)
        return {"code": 1, "msg": f"选股失败: {e}", "data": None}

    # 序列化 CSV（UTF-8 BOM，Excel 中文不乱码）
    buf = io.StringIO()
    buf.write("\ufeff")  # BOM
    writer = csv.writer(buf)
    writer.writerow(_CSV_HEADERS_CN)
    for item in result.ranked_list:
        row = item.to_dict()
        writer.writerow([row.get(c, "") for c in _CSV_COLUMNS])

    filename = f"screener_{m}_{result.as_of}.csv"
    csv_bytes = buf.getvalue().encode("utf-8")

    log.info(
        "[选股导出] %s as_of=%s → %d 行 CSV",
        m, result.as_of, len(result.ranked_list),
    )

    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/exclude-ranges")
def get_exclude_ranges():
    """读取全局剔除区间（选股 + 单股分位默认剔除）。"""
    from conf import app_config
    ranges = app_config.screener.dividend_value.exclude_ranges
    return {"code": 0, "msg": "ok", "data": {"ranges": [list(r) for r in ranges]}}


@router.put("/exclude-ranges")
def put_exclude_ranges(req: ExcludeRangesRequest):
    """
    更新全局剔除区间（写入 sidecar JSON + 刷新内存配置）。

    前端 UI 编辑后调用，选股和单股分位立即生效。
    不再回写 config.yaml 以保留其注释。
    """
    from conf import app_config
    from conf.settings import _DEFAULT_CONFIG_PATH

    # 校验日期格式
    from datetime import date as _date
    for pair in req.ranges:
        if len(pair) != 2:
            return {"code": 1, "msg": f"每个区间必须是 [start, end]: {pair}", "data": None}
        try:
            _date.fromisoformat(pair[0])
            _date.fromisoformat(pair[1])
        except ValueError:
            return {"code": 1, "msg": f"日期格式错误(应为 YYYY-MM-DD): {pair}", "data": None}

    # Update in-memory
    app_config.screener.dividend_value.exclude_ranges = req.ranges

    # Persist to sidecar JSON (avoids destroying config.yaml comments)
    import json
    import os
    sidecar_path = os.path.join(os.path.dirname(_DEFAULT_CONFIG_PATH), ".screener_exclude_ranges.json")
    try:
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump({"exclude_ranges": req.ranges}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"[screener] 写入 sidecar 失败(内存已更新): {e}")

    log.info(f"[screener] 全局剔除区间更新: {req.ranges}")
    return {"code": 0, "msg": "ok", "data": {"ranges": req.ranges}}
