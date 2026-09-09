"""GildataProvider 解析逻辑单元测试（无网络）。"""
from datetime import date

from src.domain.market.sync.providers.gildata_provider import (
    GildataProvider,
)

_SAMPLE_CSV = (
    'vendor,tool_name,query,result_index,api_name,title,score,'
    'table_markdown,retrieved_at\n'
    'gildata,MacroIndustryData,q,1,EDB取数,,,"| 指标代码 | 指标名称 '
    '| 频率 | 单位 | 值 | 日期 | 数据来源 |\n'
    '| --- | --- | --- | --- | --- | --- | --- |\n'
    '| 1 | 中国:社会融资规模增量:政府债券:累计值:月 | 月 | 亿元 | '
    '64396.0 | 2026-06-30 | 聚源计算 |\n'
    '| 2 | 中国:社会融资规模增量:政府债券:当期值:月 | 月 | 亿元 | '
    '7683.0 | 2026-06-30 | 中国人民银行 |\n'
    '| 3 | 中国:社会融资规模增量:政府债券:当期值:月 | 月 | 亿元 | '
    'bad | 2026-05-31 | 中国人民银行 |\n'
    '| 4 | 中国:社会融资规模增量:政府债券:当期值:月 | 月 | 亿元 | '
    '12236.0 | 2026-05-31 | 中国人民银行 |\n'
    '",2026-08-03T11:00:00+08:00\n'
)


class TestParseTableCsv:
    def test_parse_filters_target_series(self):
        rows = GildataProvider.parse_table_csv(
            _SAMPLE_CSV, "政府债券:当期值")
        # 累计值被过滤；bad 行被跳过；剩 2 行
        assert len(rows) == 2
        assert rows[0] == (date(2026, 6, 1), 7683.0)   # 月末 → 月初
        assert rows[1] == (date(2026, 5, 1), 12236.0)

    def test_parse_with_value_transform(self):
        rows = GildataProvider.parse_table_csv(
            _SAMPLE_CSV, "政府债券:当期值", vfn=lambda v: v / 1e5)
        assert abs(rows[0][1] - 0.07683) < 1e-9

    def test_parse_keep_original_date(self):
        rows = GildataProvider.parse_table_csv(
            _SAMPLE_CSV, "政府债券:当期值", dfn=None)
        assert rows[0][0] == date(2026, 6, 30)

    def test_parse_empty_on_no_match(self):
        assert GildataProvider.parse_table_csv(
            _SAMPLE_CSV, "不存在的指标") == []


class TestRangeCn:
    def test_month_range(self):
        rng = GildataProvider._range_cn({"lookback_months": 30})
        assert "年至" not in rng
        assert "至" in rng and "年" in rng and "月" in rng

    def test_year_range(self):
        rng = GildataProvider._range_cn(
            {"lookback_months": 120, "year_query": True})
        y0, y1 = rng.replace("年", "").split("至")
        assert int(y1) - int(y0) == 10


class TestResponseParsing:
    def test_response_json_plain(self):
        assert GildataProvider._response_json('{"a": 1}') == {"a": 1}

    def test_response_json_sse(self):
        sse = 'data: {"x": 1}\ndata: {"x": 2}\ndata: [DONE]\n'
        assert GildataProvider._response_json(sse) == {"x": 2}

    def test_extract_preview_from_json_text(self):
        payload = {
            "result": {
                "assistant": [
                    {"type": "text",
                     "text": '{"data_preview": "a,b\\n1,2"}'}
                ]
            }
        }
        assert GildataProvider._extract_preview(payload) == "a,b\n1,2"

    def test_extract_preview_missing(self):
        assert GildataProvider._extract_preview({}) is None


class TestFetchMacroSeriesGuards:
    def test_unregistered_code_returns_empty(self):
        prov = GildataProvider(api_key="k", base_url="http://x")
        assert prov.fetch_macro_series("not_a_code") == []

    def test_no_api_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("KIMI_API_KEY", raising=False)
        prov = GildataProvider(api_key="", base_url="http://x")
        # api_key 为空且 config 读不到时应返回 []
        prov._api_key = ""
        assert prov.fetch_macro_series("cn_sf") == []
