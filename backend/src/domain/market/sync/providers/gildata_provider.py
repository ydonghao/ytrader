"""GildataProvider
=================
Gildata（恒生聚源）宏观数据源 —— 经 Moonshot agent-gw 网关访问。

为何引入：akshare 的社融结构分项（macro_china_shrzgm）、房地产开发投资增速、
失业率分年龄段、新增贷款住户/企事业分项等接口已停更或从未覆盖；
Wind EDB 网关侧权限不足。Gildata 的宏观 EDB 取数（聚源）可稳定补齐这些
中国宏观指标，以及美国 ISM 制造业 PMI。

设计约定（与 FredProvider / AkshareProvider 一致）：
  - fetch_macro_series(code) 返回 [(report_date, value, freq, unit), ...] 升序
  - 无凭证 / 网络异常 / 解析失败 → 返回 []（不抛错，不阻塞批量同步）

凭证注入：环境变量 KIMI_API_KEY / KIMI_BASE_URL，
缺省时回退读 ~/.kimi/agent-gw.json（与插件脚本同一约定）。
上游 Gildata 凭证由 datasource 后端持有，客户端不直连 Gildata。

取数语义：gildata_macro_industry_data 返回的 table_markdown 常同时包含
累计值/当期值/同比等多个系列，每个 code 用 name_filter 精确锁定目标系列；
量纲换算（如美元→亿美元、千美元→亿美元）在 value_transform 里显式声明。
"""
import csv
import io
import json
import logging
import os
from datetime import date
from pathlib import Path

import requests

__all__ = ["GildataProvider"]

log = logging.getLogger("gildata_provider")

_DEFAULT_BASE_URL = "https://agent-gw-dev.dev.kimi.team/coding"
_AGENT_GW_CONFIG = Path.home() / ".kimi" / "agent-gw.json"
_TOOLS_PATH = "/v1/tools"
_TIMEOUT = 90

_SOURCE_STATS = ("国家统计局", "https://www.stats.gov.cn/sj/zxfb/")
_SOURCE_PBOC = (
    "中国人民银行",
    "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html",
)
_SOURCE_CUSTOMS = ("海关总署", "https://www.customs.gov.cn/")
_SOURCE_ISM = ("ISM", "https://www.ismworld.org/")


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _year_start(d: date) -> date:
    return date(d.year, 1, 1)


def _ym_cn(d: date) -> str:
    """date → '2026年7月'（Gildata 自然语言查询里的中文日期段）。"""
    return f"{d.year}年{d.month}月"


class GildataProvider:
    """Gildata 宏观经济指标数据源（经 agent-gw）。

    与 FredProvider 同签名实现 fetch_macro_series，便于 job 层统一调用。
    每个 code 注册：query 模板（中文自然语言，按月滚动窗口）、
    name_filter（锁定 table_markdown 中的目标系列）、值/日期变换、
    频率/单位/溯源信息。
    """

    name = "gildata"

    # code → dict(query=按月窗口模板, filter=系列名包含, vfn=值变换,
    #             dfn=日期变换(默认月初), freq, unit, source, source_url,
    #             lookback_months=滚动窗口)
    _MACRO_QUERIES = {
        # ── 社融总量与结构分项（亿元·当月值）──────────────────────
        "cn_sf": {
            "query": "中国社会融资规模增量{range}月度当期值",
            "filter": "社会融资规模增量:当期值",
            "freq": "month", "unit": "亿元",
            "source": _SOURCE_PBOC, "lookback_months": 30,
        },
        "cn_sf_rmb_loan": {
            "query": "中国社会融资规模增量人民币贷款{range}月度当期值",
            "filter": "人民币贷款:当期值",
            "freq": "month", "unit": "亿元",
            "source": _SOURCE_PBOC, "lookback_months": 30,
        },
        "cn_sf_entrust_loan": {
            "query": "中国社会融资规模增量委托贷款{range}月度当期值",
            "filter": "委托贷款:当期值",
            "freq": "month", "unit": "亿元",
            "source": _SOURCE_PBOC, "lookback_months": 30,
        },
        "cn_sf_trust_loan": {
            "query": "中国社会融资规模增量信托贷款{range}月度当期值",
            "filter": "信托贷款:当期值",
            "freq": "month", "unit": "亿元",
            "source": _SOURCE_PBOC, "lookback_months": 30,
        },
        "cn_sf_undiscounted_ba": {
            "query": "中国社会融资规模增量未贴现银行承兑汇票{range}月度当期值",
            "filter": "未贴现银行承兑汇票:当期值",
            "freq": "month", "unit": "亿元",
            "source": _SOURCE_PBOC, "lookback_months": 30,
        },
        "cn_sf_corp_bond": {
            "query": "中国社会融资规模增量企业债券{range}月度当期值",
            "filter": "企业债券:当期值",
            "freq": "month", "unit": "亿元",
            "source": _SOURCE_PBOC, "lookback_months": 30,
        },
        "cn_sf_equity": {
            "query": "中国社会融资规模增量非金融企业境内股票融资"
                     "{range}月度当期值",
            "filter": "非金融企业境内股票融资:当期值",
            "freq": "month", "unit": "亿元",
            "source": _SOURCE_PBOC, "lookback_months": 30,
        },
        "cn_sf_govbond": {
            "query": "中国社会融资规模增量政府债券{range}月度数据",
            "filter": "政府债券:当期值",
            "freq": "month", "unit": "亿元",
            "source": _SOURCE_PBOC, "lookback_months": 30,
        },
        # ── 新增人民币贷款分项（亿元·当月值）─────────────────────
        "cn_loan_household": {
            "query": "中国金融机构新增人民币贷款住户部门{range}月度当期值",
            "filter": "住户贷款:当期值",
            "freq": "month", "unit": "亿元",
            "source": _SOURCE_PBOC, "lookback_months": 30,
        },
        "cn_loan_enterprise": {
            "query": "中国金融机构新增人民币贷款企事业单位{range}月度当期值",
            "filter": "企(事)业单位贷款:当期值",
            "freq": "month", "unit": "亿元",
            "source": _SOURCE_PBOC, "lookback_months": 30,
        },
        # ── 城镇调查失业率（新口径·不含在校生，%）────────────────
        "cn_unemp_1624": {
            "query": "中国城镇调查失业率16至24岁{range}月度",
            "filter": "16-24岁人群:期末值",
            "freq": "month", "unit": "%",
            "source": _SOURCE_STATS, "lookback_months": 30,
        },
        "cn_unemp_2529": {
            "query": "中国城镇调查失业率25至29岁{range}月度",
            "filter": "25-29岁人群:期末值",
            "freq": "month", "unit": "%",
            "source": _SOURCE_STATS, "lookback_months": 30,
        },
        # ── 居民收入（季·%）────────────────────────────────────
        "cn_disp_income_median_yoy": {
            "query": "中国居民人均可支配收入中位数累计同比{range}季度",
            "filter": "中位数:累计同比增长率:季",
            "dfn": None,  # 季度保留季末日（与既有种子一致）
            "freq": "quarter", "unit": "%",
            "source": _SOURCE_STATS, "lookback_months": 72,
        },
        # ── 出生人口（年·万人）──────────────────────────────────
        "cn_birth": {
            "query": "中国出生人口{range}年度数据",
            "filter": "出生人口数量:期末值:年",
            "dfn": _year_start,
            "freq": "year", "unit": "万人",
            "source": ("国家统计局", "https://www.stats.gov.cn/sj/zxdb/"),
            "lookback_months": 120, "year_query": True,
        },
        # ── 对美进出口（亿美元；Gildata 原始为千美元 → /1e5）───────
        "cn_trade_us_amt": {
            "query": "中国对美国进出口总额{range}月度",
            "filter": "美国:当期值",
            "vfn": lambda v: v / 1e5,
            "freq": "month", "unit": "亿美元",
            "source": _SOURCE_CUSTOMS, "lookback_months": 30,
        },
        # ── CPI 分类（月·%）─────────────────────────────────────
        "cn_cpi_food": {
            "query": "中国CPI食品烟酒当月同比{range}月度",
            "filter": "食品烟酒类:当期同比增长率",
            "freq": "month", "unit": "%",
            "source": _SOURCE_STATS, "lookback_months": 30,
        },
        "cn_cpi_consumer": {
            "query": "中国CPI消费品当月同比{range}月度",
            "filter": "消费品类:当期同比增长率",
            "freq": "month", "unit": "%",
            "source": _SOURCE_STATS, "lookback_months": 30,
        },
        # ── 增长类（月·%）──────────────────────────────────────
        "cn_realestate_inv_yoy": {
            "query": "中国房地产开发投资完成额累计同比{range}月度",
            "filter": "房地产开发投资额:累计同比增长率",
            "freq": "month", "unit": "%",
            "source": _SOURCE_STATS, "lookback_months": 30,
        },
        "cn_industrial_yoy": {
            "query": "中国规模以上工业增加值当月同比{range}月度",
            "filter": "工业增加值:规模以上工业企业:当期同比增长率",
            "freq": "month", "unit": "%",
            "source": _SOURCE_STATS, "lookback_months": 14,
        },
        # ── 美国 ISM 制造业 PMI（akshare 金十源已停更）────────────
        "us_ism_pmi": {
            "query": "美国ISM制造业PMI{range}月度",
            "filter": "制造业采购经理指数(制造业PMI):当期值",
            "freq": "month", "unit": "",
            "source": _SOURCE_ISM, "lookback_months": 14,
        },
        # ── 货币供应（月·%；akshare 同源，Gildata 作长历史回填/备用源）
        "cn_m2_yoy": {
            "query": "中国M2货币供应量同比{range}月度",
            "filter": "M2:期末同比:月",
            "freq": "month", "unit": "%",
            "source": _SOURCE_PBOC, "lookback_months": 30,
        },
        "cn_m1_yoy": {
            "query": "中国M1货币供应量同比{range}月度",
            "filter": "M1:期末同比:月",
            "freq": "month", "unit": "%",
            "source": _SOURCE_PBOC, "lookback_months": 30,
        },
        # ── 需求与价格（月·%；长历史回填/备用源）─────────────────
        "cn_retail_yoy": {
            "query": "中国社会消费品零售总额当月同比{range}月度",
            "filter": "社会消费品零售总额:当期同比增长率:月",
            "freq": "month", "unit": "%",
            "source": _SOURCE_STATS, "lookback_months": 30,
        },
        "cn_fai_yoy": {
            "query": "中国固定资产投资完成额累计同比{range}月度",
            "filter": "固定资产投资额:不含农户:累计同比增长率:月",
            "freq": "month", "unit": "%",
            "source": _SOURCE_STATS, "lookback_months": 30,
            # 30 年跨度的"某年某月至某年某月"格式上游解析失败，
            # 该指标日期段用年度格式（数据仍为月度）
            "year_span": True,
        },
        "cn_industrial_profit_yoy": {
            "query": "中国规模以上工业企业利润总额累计同比{range}月度",
            "filter": "规模以上工业企业利润总额:累计同比增长率:月",
            "freq": "month", "unit": "%",
            "source": _SOURCE_STATS, "lookback_months": 30,
        },
        "cn_cpi_yoy": {
            "query": "中国CPI当月同比{range}月度",
            "filter": "居民消费价格指数(CPI):上年同月=100:当期同比增长率:月",
            "freq": "month", "unit": "%",
            "source": _SOURCE_STATS, "lookback_months": 30,
        },
        "cn_ppi_yoy": {
            "query": "中国PPI当月同比{range}月度",
            "filter": "工业生产者出厂价格指数(PPI):上年同月=100:当期同比增长率:月",
            "freq": "month", "unit": "%",
            "source": _SOURCE_STATS, "lookback_months": 30,
        },
    }

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = _TIMEOUT,
    ):
        cfg = self._load_gw_config()
        self._api_key = (
            api_key or os.environ.get("KIMI_API_KEY", "")
            or str(cfg.get("api_key", "")).strip()
        )
        self._base_url = (
            base_url or os.environ.get("KIMI_BASE_URL", "")
            or str(cfg.get("base_url", "")).strip() or _DEFAULT_BASE_URL
        ).rstrip("/")
        self._timeout = timeout

    @staticmethod
    def _load_gw_config() -> dict:
        if not _AGENT_GW_CONFIG.is_file():
            return {}
        try:
            data = json.loads(
                _AGENT_GW_CONFIG.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    # ── 取数主流程 ──────────────────────────────────────────────
    def fetch_macro_series(
        self, code: str, lookback_months: int | None = None,
    ) -> list[tuple]:
        """拉取单个宏观指标（滚动窗口），归一化为
        [(report_date, value, freq, unit), ...]（升序）。

        lookback_months 传值时临时覆盖 spec 默认窗口（供一次性
        历史回填使用），日常调度不传，保持 spec 默认。
        无凭证 / 未注册 / 网络或解析失败 → 返回 []。
        """
        spec = self._MACRO_QUERIES.get(code)
        if not spec:
            log.debug(f"[gildata:{code}] 未注册的指标")
            return []
        if not self._api_key:
            log.warning(f"[gildata:{code}] 无 KIMI_API_KEY，跳过")
            return []

        query = spec["query"].format(
            range=self._range_cn(spec, lookback_months))
        csv_text = self._call_macro_industry(query)
        if not csv_text:
            return []

        rows = self.parse_table_csv(
            csv_text, spec["filter"], spec.get("vfn"),
            spec.get("dfn", _month_start))
        out = [
            (d, v, spec["freq"], spec["unit"]) for d, v in rows
        ]
        out.sort(key=lambda x: x[0])
        return out

    @staticmethod
    def _range_cn(spec: dict, lookback_months: int | None = None) -> str:
        """按 lookback 生成中文日期段：'2024年1月至2026年7月' 或 '2016年至2025年'。"""
        months = lookback_months or spec["lookback_months"]
        today = date.today()
        if spec.get("year_query") or spec.get("year_span"):
            start_year = today.year - months // 12
            return f"{start_year}年至{today.year}年"
        total = today.year * 12 + today.month - months
        y, m = divmod(total - 1, 12)
        start = date(y, m + 1, 1)
        return f"{_ym_cn(start)}至{_ym_cn(today)}"

    # ── agent-gw 传输层 ─────────────────────────────────────────
    def _call_macro_industry(self, query: str) -> str | None:
        """调用 gildata_macro_industry_data，返回 data_preview CSV 文本。

        响应可能是纯 JSON 或 SSE 流；文件内容在 result.assistant 的
        data_preview 字段（agent-gw 模式下上游文件不可达）。
        """
        body = {
            "method": "call_data_source_tool",
            "params": {
                "data_source_name": "gildata",
                "api_name": "gildata_macro_industry_data",
                "params": {"query": query, "file_path": "/tmp/gildata.csv"},
            },
        }
        try:
            resp = requests.post(
                f"{self._base_url}{_TOOLS_PATH}",
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            payload = self._response_json(resp.text)
        except Exception as e:
            log.warning(f"[gildata] 请求失败（{query[:20]}…）: {e}")
            return None
        return self._extract_preview(payload)

    @staticmethod
    def _response_json(text: str) -> dict:
        """解析 agent-gw 响应：纯 JSON 或 SSE（data: 行，取最后一个对象）。"""
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except ValueError:
            pass
        last = None
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            chunk = line[len("data:"):].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                parsed = json.loads(chunk)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                last = parsed
        return last or {}

    @staticmethod
    def _extract_preview(payload: dict) -> str | None:
        """从响应里提取 data_preview CSV 文本。"""
        result = payload.get("result") or payload
        items = result.get("assistant") if isinstance(result, dict) else None
        if items is None:
            items = payload.get("assistant") or []
        if isinstance(items, str):
            items = [{"text": items}]
        for item in items or []:
            text = item.get("text") if isinstance(item, dict) else None
            if not text:
                continue
            # text 可能是 JSON 字符串（含 data_preview 字段）
            try:
                inner = json.loads(text)
                preview = inner.get("data_preview")
                if preview:
                    return preview
            except ValueError:
                pass
            if "table_markdown" in text:
                return text
        return None

    # ── CSV / markdown 表格解析 ─────────────────────────────────
    @staticmethod
    def parse_table_csv(
        csv_text: str,
        name_filter: str,
        vfn=None,
        dfn=_month_start,
    ) -> list[tuple]:
        """解析 data_preview CSV → [(date, value)]。

        CSV 的 table_markdown 列内嵌 markdown 表格，列为：
        指标代码|指标名称|频率|单位|值|日期|数据来源。
        仅保留指标名称包含 name_filter 的行；vfn 为值变换；
        dfn 为日期归一（默认月初，None 保留原值）。
        """
        out: list[tuple] = []
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            md = row.get("table_markdown", "")
            for line in md.split("\n"):
                if not line.startswith("|"):
                    continue
                if "指标代码" in line or "---" in line:
                    continue
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) < 7:
                    continue
                name, val_s, date_s = cells[1], cells[4], cells[5]
                if name_filter not in name:
                    continue
                try:
                    d = date(int(date_s[:4]), int(date_s[5:7]),
                             int(date_s[8:10]))
                    v = float(val_s)
                except (ValueError, IndexError):
                    continue
                if vfn:
                    v = vfn(v)
                if dfn:
                    d = dfn(d)
                out.append((d, v))
        return out

    # ── 溯源信息（job 层 upsert 用）─────────────────────────────
    def source_info(self, code: str) -> tuple[str, str]:
        spec = self._MACRO_QUERIES.get(code) or {}
        return spec.get("source", ("聚源", ""))
