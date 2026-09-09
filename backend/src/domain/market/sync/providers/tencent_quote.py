"""腾讯财经实时行情 provider — 国家队「实时全景」数据源。

为什么用腾讯:本环境东方财富 spot_em/数据接口不可达(见 akshare_provider 注释),
而腾讯 qt.gtimg.cn 公开接口稳定,且一次返回 88 字段,覆盖 PE/PB/市值/换手/量比/
52 周高低/振幅 等估值与盘口字段,正好支撑压缩包仪表盘的「实时行情叠加」需求。
ETF 行情同接口,vals[72] 为基金份额(份)。

口径与来源:
  - 行情字段:腾讯财经实时(qt.gtimg.cn),GBK 编码,批量 ≤50。
  - 所有返回字段附带 _source 标注,前端可展示「数据来源」以保持透明。

本模块只做「取数 + 解析 + 进程级 TTL 缓存」,不做业务聚合(留给 composer)。
"""
from __future__ import annotations

import threading
import time
import urllib.request
from typing import Iterable

# 进程级缓存:避免短时间多次调用把腾讯接口打爆。盘口数据 60s 内复用。
_CACHE_TTL = 60.0  # 秒
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_BATCH = 50  # 腾讯单次最多 ~50 个代码


def _prefix(code: str) -> str:
    """6 位纯代码 → 腾讯前缀代码(sh/sz/bj)。
    沪:6(股)/5(ETF基金)/9(B股); 深:0/3(股)/1(ETF基金)/2(B股); 北:4/8。"""
    code = str(code).strip()
    if code[:2] in ("sh", "sz", "bj"):
        return code
    if code.startswith(("5", "6", "9")):        # 沪市 + ETF/股票/B股
        return f"sh{code}"
    if code.startswith(("0", "1", "3")):        # 深市(1=ETF如159xxx)
        return f"sz{code}"
    if code.startswith(("4", "8")) or code.startswith("92"):  # 北交所
        return f"bj{code}"
    return f"sh{code}"  # 兜底


def _to_float(v, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if x == x else default  # NaN 兜底
    except (TypeError, ValueError):
        return default


def _fetch_raw(prefixed_codes: list[str]) -> dict[str, list[str]]:
    """一次请求一批前缀代码,返回 {prefixed_code: vals_list}。GBK 解码。"""
    if not prefixed_codes:
        return {}
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed_codes)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("gbk", errors="ignore")
    except Exception:
        return {}
    out: dict[str, list[str]] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or '="' not in part:
            continue
        head, body = part.split('="', 1)
        # head 形如 "v_sh601939" → 取 "v_" 之后的部分 = "sh601939"
        head = head.strip()
        code = head[2:] if head.startswith("v_") else head.split("/")[-1]
        vals = body.rstrip('",').split("~")
        if len(vals) >= 49:
            out[code] = vals
    return out


def _parse_stock(code: str, vals: list[str]) -> dict:
    """88 字段 → 标准化个股实时字段。"""
    g = lambda i: vals[i] if i < len(vals) else ""
    price = _to_float(g(3))
    last_close = _to_float(g(4))
    change_pct = _to_float(g(32))
    if price <= 0 and last_close > 0:
        price = last_close
    high_52w = _to_float(g(41))
    low_52w = _to_float(g(42))
    week_52_pos = (
        round((price - low_52w) / (high_52w - low_52w) * 100, 1)
        if high_52w > low_52w and price > 0 else 50.0
    )
    return {
        "code": code,
        "name": g(1),
        "price": round(price, 3),
        "last_close": round(last_close, 3),
        "change_pct": round(change_pct, 2),
        "change_amount": round(_to_float(g(31)), 3),
        "open": round(_to_float(g(5)), 3),
        "high": round(_to_float(g(33)), 3),
        "low": round(_to_float(g(34)), 3),
        "volume_hand": int(_to_float(g(6))),           # 成交量(手)
        "amount_wan": round(_to_float(g(37)), 1),      # 成交额(万)
        "turnover_pct": round(_to_float(g(38)), 2),    # 换手率 %
        "pe_ttm": round(_to_float(g(39)), 2),
        "pb": round(_to_float(g(46)), 2),
        "mcap_yi": round(_to_float(g(45)), 2),         # 总市值(亿)
        "float_mcap_yi": round(_to_float(g(44)), 2),   # 流通市值(亿)
        "high_52w": round(high_52w, 3),
        "low_52w": round(low_52w, 3),
        "week_52_position": week_52_pos,               # 52 周分位 0-100
        "amplitude": round(_to_float(g(43)), 2),       # 振幅 %
        "limit_up": round(_to_float(g(47)), 3),
        "limit_down": round(_to_float(g(48)), 3),
        "volume_ratio": round(_to_float(g(49)), 2),    # 量比
        "_source": "腾讯财经实时",
    }


def _parse_etf(code: str, vals: list[str]) -> dict:
    """ETF 行情:复用个股字段 + 份额(vals[72],单位:份)。"""
    base = _parse_stock(code, vals)
    shares = _to_float(vals[72]) if len(vals) > 72 else 0.0
    base["shares"] = int(shares)                      # 基金份额(份)
    base["shares_yi"] = round(shares / 1e8, 2)        # 亿份
    price = base["price"]
    base["total_value_yi"] = round(shares * price / 1e8, 2)  # 规模(亿)
    base["_source"] = "腾讯财经实时"
    return base


def _batched(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def fetch_stock_quotes(codes: list[str]) -> dict[str, dict]:
    """批量取个股实时行情。codes = 6 位纯代码。返回 {code: fields}。"""
    return _fetch(codes, is_etf=False)


def fetch_etf_quotes(codes: list[str]) -> dict[str, dict]:
    """批量取 ETF 实时行情(含份额/规模)。codes = 6 位纯代码。"""
    return _fetch(codes, is_etf=True)


def _fetch(codes: list[str], is_etf: bool) -> dict[str, dict]:
    """统一取数:查缓存 → 批量请求 → 解析。"""
    codes = [str(c).strip() for c in codes if c]
    if not codes:
        return {}
    now = time.time()
    result: dict[str, dict] = {}
    miss: list[str] = []
    with _CACHE_LOCK:
        for c in codes:
            key = ("etf" if is_etf else "st") + "_" + c
            hit = _CACHE.get(key)
            if hit and now - hit[0] < _CACHE_TTL:
                result[c] = hit[1]
            else:
                miss.append(c)
    if not miss:
        return result
    parse = _parse_etf if is_etf else _parse_stock
    for chunk in _batched(miss, _BATCH):
        prefixed = [_prefix(c) for c in chunk]
        raw = _fetch_raw(prefixed)
        with _CACHE_LOCK:
            for c in chunk:
                vals = raw.get(_prefix(c))
                if vals:
                    rec = parse(c, vals)
                    result[c] = rec
                    _CACHE[("etf" if is_etf else "st") + "_" + c] = (now, rec)
        time.sleep(0.15)  # 批间礼貌等待
    return result


def fetch_one_kline(code: str, days: int = 30, adjust: str = "qfq") -> list[dict]:
    """前复权日 K(个股/ETF 通用),供详情弹窗蜡烛图 + 动量计算。
    走 akshare 新浪接口(本环境可达),返回 [{date,open,close,high,low}],升序。"""
    import akshare as ak
    prefix = _prefix(code)
    try:
        if code.startswith(("5", "1")) and len(code) == 6 and code[0] == "5":
            df = ak.fund_etf_hist_sina(symbol=prefix)  # ETF
        elif code.startswith("5"):
            df = ak.fund_etf_hist_sina(symbol=prefix)
        else:
            df = ak.stock_zh_a_daily(symbol=prefix, adjust=adjust)
        if df is None or len(df) == 0:
            return []
        df = df.sort_values("date").tail(days)
        out = []
        for _, r in df.iterrows():
            out.append({
                "date": str(r["date"])[:10],
                "open": round(float(r["open"]), 3),
                "close": round(float(r["close"]), 3),
                "high": round(float(r["high"]), 3),
                "low": round(float(r["low"]), 3),
            })
        return out
    except Exception:
        return []
