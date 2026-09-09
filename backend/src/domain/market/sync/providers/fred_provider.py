"""FredProvider
===============
FRED（圣路易斯联储）数据源 —— 美国宏观指标的权威官方来源。

为何引入：akshare 经金十数据（jin10.com）抓取的美国宏观线（失业率/ISM PMI/
核心 PCE 等）自 2025 下半年起整体停更，缺口持续扩大。FRED 提供稳定、
官方、免费（需注册 API key）的替代。

设计约定（与 AkshareProvider 一致）：
  - fetch_macro_series(code) 返回 [(report_date, value, freq, unit), ...] 升序
  - 无 key / 网络异常 / 解析失败 → 返回 []（不抛错，不阻塞批量同步；上层 fallback 到 akshare）

API key 注入：环境变量 FRED_API_KEY（与项目 finnhub/feishu/minimax 范式一致）。
无 key 时直接返回 []，触发上层 fallback。
"""
import logging
import os
from datetime import date, timedelta

import requests

__all__ = ["FredProvider"]

log = logging.getLogger("fred_provider")

# FRED 观测值接口：拉取单个序列的全部历史观测
_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"
# 尽量拉长历史（FRED 支持数十年数据），设 50 年覆盖大多数宏观周期
_LOOKBACK_DAYS = 365 * 50
# 观测序列里 "." 表示缺失值
_MISSING = "."


def _to_float(v):
    """宽松转 float；FRED 缺失值 '.' / None / 空串 → None。"""
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", _MISSING, "nan", "NaN", "None"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_date(v):
    """'2026-06-01'（FRED observation 的 date 字段为 YYYY-MM-DD）→ date；失败 None。"""
    if v is None:
        return None
    s = str(v).strip()[:10]
    try:
        from datetime import datetime as _dt
        return _dt.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


class FredProvider:
    """FRED（圣路易斯联储）美国宏观经济指标数据源。

    与 AkshareProvider 同签名实现 fetch_macro_series，便于 macro_sync 按
    config 里的 provider 字段分发。不继承 SyncProvider（那是 OHLCV 抽象，
    宏观指标是标量时序）。
    """

    name = "fred"

    # code → (series_id, transform, freq, unit)
    # transform：None = 原值；"pc1" = 同比%（Percent Change from Year Ago）
    #   用 pc1 直接拿 CPI/PCE 同比，对齐 us_cpi_yoy / us_core_pce 的语义，无需本地换算
    # 注：ISM PMI 因版权从 FRED 下架（NPMI 失效），改走 akshare 金十源；
    #     另以 us_cap_util（CUMFNS 制造业产能利用率）作 FRED 侧的实时增长景气替代。
    _MACRO_SERIES = {
        "us_unemp":    ("UNRATE",   None,  "month", "%"),      # U-3 失业率（原值）
        "us_nfp":      ("PAYEMS",   None,  "month", "千人"),    # 非农就业总人数（原值，单位千人）
        "us_cpi_yoy":  ("CPIAUCSL", "pc1", "month", "%"),      # CPI 同比（pc1 换算）
        "us_core_pce": ("PCEPILFE", "pc1", "month", "%"),      # 核心 PCE 同比（pc1 换算）
        "us_cap_util": ("CUMFNS",   None,  "month", "%"),      # 制造业产能利用率（原值）
        "us_bond_10y": ("DGS10",    None,  "day",   "%"),      # 10年期国债收益率（原值，供中美利差）
    }

    def __init__(self, api_key: str | None = None, timeout: int = 20):
        self._api_key = (api_key or os.environ.get("FRED_API_KEY", "")).strip()
        self._timeout = timeout

    def fetch_macro_series(self, code: str) -> list[tuple]:
        """拉取单个美国宏观指标的全量历史，归一化为
        [(report_date, value, freq, unit), ...]（report_date 升序）。

        无 API key / 序列未注册 / 网络异常 → 返回 []（上层 fallback 到 akshare）。
        """
        series = self._MACRO_SERIES.get(code)
        if not series:
            log.debug(f"[fred:{code}] 未注册的序列")
            return []
        if not self._api_key:
            log.debug(f"[fred:{code}] 无 FRED_API_KEY，跳过（上层将 fallback）")
            return []

        series_id, transform, freq, unit = series
        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "observation_start": (date.today() - timedelta(days=_LOOKBACK_DAYS)).isoformat(),
        }
        if transform:
            params["units"] = transform  # FRED 参数名是 units（=transform）

        try:
            resp = requests.get(_OBS_URL, params=params, timeout=self._timeout)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            log.warning(f"[fred:{code}({series_id})] 请求失败: {e}")
            return []

        observations = payload.get("observations") or []
        out: list[tuple] = []
        for ob in observations:
            d = _parse_date(ob.get("date"))
            v = _to_float(ob.get("value"))
            if d is None or v is None:
                continue
            out.append((d, v, freq, unit))
        out.sort(key=lambda x: x[0])
        if not out:
            log.warning(f"[fred:{code}({series_id})] 观测值为空")
        return out
