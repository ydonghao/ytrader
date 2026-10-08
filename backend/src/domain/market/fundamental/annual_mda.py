"""年报 MD&A 管理层承诺抽取（言行追踪 V2）。

管道：巨潮年报公告列表 → PDF 下载（本地缓存）→ pypdf 抽文本 →
"管理层讨论与分析"章节切片 → LLM 抽取量化承诺/指引（JSON 纪律：
只抽原文明确的表述，禁止编造）→ 入 management_promise（source=
annual_report，待人工验证）。

与 V1 的业绩预告自动判兑现互补：预告是量化承诺可直接对数；年报里的
"预计/力争/计划"类承诺先抽出来，兑现与否由人工验证闭环。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import requests

log = logging.getLogger(__name__)

_PDF_CACHE = Path("data/annual_reports")
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

_EXTRACT_PROMPT = """你是投资研究助理。下面是 {{symbol}} {{year}} 年年度报告的
"管理层讨论与分析"章节文本。抽取其中**管理层对未来的明确承诺、指引与
量化计划**，例如："预计/力争/计划/目标 实现营业收入/净利润/产量/销量
X"、"未来三年分红率不低于 X%"、"资本开支 X 亿元投向 Y"、"新增产能 X"。

纪律：
1) 只抽原文明确的前瞻表述，不推断、不编造；每条尽量保留原文数字；
2) category 只能取：业绩指引/资本开支/分红/回购/增持/其他；
3) period 填目标期间（如 "2025年度"/"未来三年"），原文没有就留空字符串；
4) 没有可抽的就返回空数组，不要硬凑；
5) 只输出 JSON，形如
{"promises": [{"content": "…", "category": "业绩指引", "period": "2025年度"}]}
（Jinja 模板中单花括号是字面量，勿写成双花括号）

【MD&A 文本】
{{mda}}
"""


def _bare(symbol: str) -> str:
    s = symbol.strip().lower()
    return s[2:] if s[:2] in ("sh", "sz", "bj") and len(s) == 8 else s


def fetch_annual_reports(symbol: str, years: int = 2) -> list[dict]:
    """巨潮年报公告列表（akshare 封装），过滤英文版/摘要/修订。

    返回 [{title, announce_date, announcement_id, pdf_url}] 按时间倒序。
    """
    import akshare as ak

    end = dt.date.today()
    start = end.replace(year=end.year - years - 1)  # 多留一年余量
    df = ak.stock_zh_a_disclosure_report_cninfo(
        symbol=_bare(symbol), market="沪深京", category="年报",
        start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
    )
    out = []
    for _, r in df.iterrows():
        title = str(r.get("公告标题") or "")
        if ("年度报告" not in title or "英文" in title or "摘要" in title
                or "修订" in title or "已取消" in title):
            continue
        link = str(r.get("公告链接") or "")
        m = re.search(r"announcementId=(\d+)", link)
        date_s = str(r.get("公告时间") or "")
        if not m or not date_s:
            continue
        out.append({
            "title": title,
            "announce_date": date_s,
            "announcement_id": m.group(1),
            "pdf_url": (f"http://static.cninfo.com.cn/finalpage/"
                        f"{date_s}/{m.group(1)}.PDF"),
        })
    # 同一年多份(如更正后重发)取最新；按年份去重
    seen_year: dict[str, dict] = {}
    for item in out:
        ym = re.search(r"(20\d{2})年.*年度报告", item["title"])
        year = ym.group(1) if ym else item["announce_date"][:4]
        if year not in seen_year:   # 列表本身倒序，先见即最新
            item["year"] = year
            seen_year[year] = item
    rows = sorted(seen_year.values(), key=lambda x: -int(x["year"]))
    return rows[:years]


def download_pdf(pdf_url: str, cache_key: str) -> Optional[Path]:
    """下载年报 PDF 到本地缓存（已存在直接复用）。"""
    _PDF_CACHE.mkdir(parents=True, exist_ok=True)
    path = _PDF_CACHE / f"{cache_key}.pdf"
    if path.exists() and path.stat().st_size > 10_000:
        return path
    try:
        r = requests.get(pdf_url, headers=_UA, timeout=120)
        r.raise_for_status()
        if not r.content[:5].startswith(b"%PDF"):
            log.warning("mda download 非 PDF: %s", pdf_url)
            return None
        path.write_bytes(r.content)
        return path
    except Exception as e:  # noqa: BLE001
        log.warning("mda download 失败 %s: %s", pdf_url, e)
        return None


def extract_pdf_text(pdf_path: Path) -> str:
    """pypdf 抽全文（年报为原生 PDF，文本层通常完整）。"""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001  个别页解析失败跳过
            continue
    return "\n".join(parts)


def slice_mda(full_text: str, *, max_chars: int = 40000) -> Optional[str]:
    """切"管理层讨论与分析"章节：从标题起至下一节（第X节/公司治理）。

    纯函数。目录页也会出现该标题（后面紧跟下一节目录项，段落极短），
    因此遍历全部命中、取第一段达到实质长度的真章节。
    """
    text = re.sub(r"\s+", " ", full_text)
    best: Optional[str] = None
    for m in re.finditer(r"管\s*理\s*层\s*讨\s*论\s*与\s*分\s*析", text):
        rest = text[m.start():]
        # 终点只认正文节标题"第X节"，且排除"详见第X节"类交叉引用
        nxt = None
        for c in re.finditer(
                r"第\s*[一二三四五六七八九十]+\s*节", rest[100:]):
            ctx = rest[max(0, 100 + c.start() - 3):100 + c.start()]
            if "见" in ctx:            # 详见/参见/见第X节 → 交叉引用
                continue
            nxt = c
            break
        end = (100 + nxt.start()) if nxt else len(rest)
        seg = rest[:min(end, max_chars)]
        if len(seg) > 2000:            # 真章节（目录项只有几十字）
            return seg
        if best is None or len(seg) > len(best):
            best = seg
    return best if best and len(best) > 500 else None


def parse_promises_json(raw: str) -> list[dict]:
    """解析 LLM 输出的 {"promises":[...]}（容忍 markdown 代码围栏）。"""
    if not raw:
        return []
    body = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", body, re.S)
    if not m:
        return []
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return []
    out = []
    for p in obj.get("promises") or []:
        if not isinstance(p, dict):
            continue
        content = str(p.get("content") or "").strip()
        if len(content) < 6:
            continue
        out.append({
            "content": content[:300],
            "category": str(p.get("category") or "其他"),
            "period": str(p.get("period") or "")[:40],
        })
    return out[:12]   # 单份年报上限，防 LLM 撒豆子


async def extract_promises(symbol: str, *, years: int = 2) -> dict:
    """端到端：下载年报 → 切 MD&A → LLM 抽承诺。返回分报告明细。"""
    from src.infra.llm.single_call import complete_with_retry

    reports = fetch_annual_reports(symbol, years=years)
    result: dict[str, Any] = {
        "symbol": symbol, "reports": [], "promises": [],
    }
    for rep in reports:
        entry = {"title": rep["title"], "year": rep["year"],
                 "announce_date": rep["announce_date"],
                 "promises": [], "skipped": None}
        pdf = download_pdf(rep["pdf_url"],
                           f"{_bare(symbol)}_{rep['year']}")
        if pdf is None:
            entry["skipped"] = "PDF 下载失败"
            result["reports"].append(entry)
            continue
        try:
            mda = slice_mda(extract_pdf_text(pdf))
        except Exception as e:  # noqa: BLE001
            log.warning("mda extract %s 失败: %s", rep["title"], e)
            mda = None
        if not mda:
            entry["skipped"] = "未定位到 MD&A 章节"
            result["reports"].append(entry)
            continue
        from src.domain.market.intel.agents.base import (
            load_prompt_from_db_or, render_prompt,
        )
        prompt = render_prompt(
            load_prompt_from_db_or("argument_mda_extract",
                                   _EXTRACT_PROMPT),
            symbol=symbol, year=rep["year"], mda=mda)
        raw, model = await complete_with_retry(
            prompt, max_tokens=12000, min_chars=10)
        promises = parse_promises_json(raw)
        entry["promises"] = promises
        entry["model"] = model
        for p in promises:
            p["announce_date"] = rep["announce_date"]
            p["year"] = rep["year"]
        result["promises"].extend(promises)
        result["reports"].append(entry)
    return result
