"""/market/search 指数维度合并测试。

不依赖真实 PG：fake 连接 + 游标按 SQL 子串路由预制行
（参考 tests/api/test_factors_router_simulated.py）。

背景：stock_info 只有股票/ETF，指数（中证500/1000 等）此前搜不到；
方案 B 在 search_symbols 内并入 conf quant_universe.indices ∩
index_ohlcv 有行情的指数，并支持同花顺风格别名（1B0905→sh000905）。
"""
import pytest

from src.api.router import market_router as mr


# ── Fake DB ──────────────────────────────────────────────────────────

class _FakeCursor:
    """按 SQL 子串返回预制行；记录执行次数供缓存断言。"""

    def __init__(self, conn) -> None:
        self._conn = conn
        self._rows: list = []

    def execute(self, sql: str, params=None) -> None:
        self._conn.executed_sqls.append(sql)
        self._rows = self._conn._lookup(sql, params)  # noqa: SLF001

    def fetchall(self) -> list:
        return list(self._rows)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self) -> None:
        self.executed_sqls: list[str] = []
        # stock_info 行（search 主查询返回）
        self.stock_rows: list[dict] = [
            {"symbol": "sh510500", "name": "中证500ETF南方", "market": "A"},
            {"symbol": "sh512500", "name": "中证500ETF华夏", "market": "A"},
            {"symbol": "sz000905", "name": "厦门港务", "market": "A"},
            {"symbol": "sh600519", "name": "贵州茅台", "market": "A"},
        ]
        # index_ohlcv 有行情的指数（sh932000 有配置但无数据 → 必须被排除）
        self.index_symbols: list[dict] = [
            {"symbol": "sh000001"}, {"symbol": "sz399001"},
            {"symbol": "sh000300"}, {"symbol": "sh000016"},
            {"symbol": "sh000905"}, {"symbol": "sh000852"},
            {"symbol": "sh000985"}, {"symbol": "sz399006"},
            {"symbol": "sz399106"}, {"symbol": "sz399005"},
            {"symbol": "sh000010"}, {"symbol": "sh000015"},
            {"symbol": "sh000903"}, {"symbol": "sh000688"},
        ]

    def _lookup(self, sql: str, params=None) -> list:  # noqa: SLF001
        s = sql.lower()
        if "from index_ohlcv" in s:
            return list(self.index_symbols)
        if "from stock_info" in s:
            # 模拟 SQL 的 WHERE + priority 计算（exact=代码前缀0/包含1/名称2）
            p = params or {}
            kw = str(p.get("like", "%")).strip("%")
            exact = str(p.get("exact", ""))
            out = []
            for r in self.stock_rows:
                sym = r["symbol"].lower()
                hit = kw in sym or kw in r["name"]
                if not hit:
                    continue
                if exact and sym.startswith(exact.rstrip("%")):
                    pr = 0
                elif kw in sym:
                    pr = 1
                else:
                    pr = 2
                out.append({**r, "priority": pr})
            return out
        return []

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self)

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_index_cache():
    """每个用例重置指数清单缓存，避免用例间串数据。"""
    mr._INDEX_SEARCH_CACHE["items"] = []
    mr._INDEX_SEARCH_CACHE["ts"] = 0.0
    yield
    mr._INDEX_SEARCH_CACHE["items"] = []
    mr._INDEX_SEARCH_CACHE["ts"] = 0.0


@pytest.fixture
def fake_conn(monkeypatch):
    conn = _FakeConn()
    monkeypatch.setattr(mr, "get_conn", lambda: conn)
    return conn


def _search(q: str, market=None, limit=20):
    return mr.search_symbols(q, market, limit)


# ── 名称/代码搜索 ────────────────────────────────────────────────────

class TestIndexInSearch:

    def test_name_query_returns_index_first(self, fake_conn):
        """搜"中证500"：指数本身排第一，ETF 在其后（同优先级按 symbol 排序）。"""
        rows = _search("中证500")
        assert rows[0]["symbol"] == "sh000905"
        assert rows[0]["name"] == "中证500"
        assert any(r["symbol"] == "sh510500" for r in rows)

    def test_bare_code_matches_index_and_stock(self, fake_conn):
        """搜"000905"：sh000905(中证500) 与 sz000905(厦门港务) 都在，指数在前。"""
        rows = _search("000905")
        syms = [r["symbol"] for r in rows]
        assert "sh000905" in syms and "sz000905" in syms
        assert syms.index("sh000905") < syms.index("sz000905")

    def test_prefixed_code_prefix_priority(self, fake_conn):
        """搜"sh0009"：指数代码前缀命中，优先级 0 排最前。"""
        rows = _search("sh0009")
        assert rows[0]["symbol"] in {"sh000903", "sh000905"}
        assert all(r["symbol"].startswith("sh0009") for r in rows)

    def test_ths_alias_resolves(self, fake_conn):
        """同花顺代码 1B0905（大小写不敏感）→ sh000905 中证500。"""
        rows = _search("1B0905")
        assert len(rows) == 1
        assert rows[0]["symbol"] == "sh000905"
        assert rows[0]["name"] == "中证500"

    def test_csi1000_searchable(self, fake_conn):
        """中证1000 同样可搜（用户原始诉求之一）。"""
        rows = _search("中证1000")
        assert rows[0]["symbol"] == "sh000852"
        assert rows[0]["name"] == "中证1000"

    def test_index_without_ohlcv_data_excluded(self, fake_conn):
        """有配置但无行情的指数(sh932000 中证2000)不进搜索，避免空卡。"""
        for q in ("中证2000", "sh932000", "932000"):
            rows = _search(q)
            assert not any(r["symbol"] == "sh932000" for r in rows), q

    def test_market_hk_skips_indices(self, fake_conn):
        """market=HK 时并入的 A 股指数不应出现。"""
        rows = _search("中证500", market="HK")
        assert not any(r["symbol"] == "sh000905" for r in rows)

    def test_limit_applies_after_merge(self, fake_conn):
        """合并后统一截断 limit。"""
        rows = _search("中证500", limit=2)
        assert len(rows) == 2
        assert rows[0]["symbol"] == "sh000905"

    def test_response_shape_matches_stock_rows(self, fake_conn):
        """指数行与股票行同构（bars 兼容字段等）。"""
        rows = _search("中证500")
        idx = next(r for r in rows if r["symbol"] == "sh000905")
        assert idx["market"] == "A"
        assert idx["bars"] == 0

    def test_index_load_failure_degrades_to_stocks(self, fake_conn, monkeypatch):
        """指数清单加载异常时降级为纯股票结果，搜索不 500。"""
        def _boom(cur):
            raise RuntimeError("index_ohlcv unavailable")
        monkeypatch.setattr(mr, "_load_index_search_items", _boom)
        rows = _search("中证500")
        assert rows  # 股票(ETF)结果仍在
        assert not any(r["symbol"] == "sh000905" for r in rows)


# ── 指数清单加载/缓存 ────────────────────────────────────────────────

class TestIndexCatalog:

    def test_items_from_config_and_db(self, fake_conn):
        """清单 = quant_universe.indices ∩ index_ohlcv 有数据。"""
        items = mr._load_index_search_items(
            _FakeCursor(fake_conn))
        syms = {it["symbol"] for it in items}
        assert "sh000905" in syms          # 有配置有数据
        assert "sh932000" not in syms      # 有配置无数据
        names = {it["symbol"]: it["name"] for it in items}
        assert names["sh000852"] == "中证1000"  # 名称来自配置段

    def test_items_cached_within_ttl(self, fake_conn):
        """TTL 内二次调用不再查 index_ohlcv。"""
        cur = _FakeCursor(fake_conn)
        mr._load_index_search_items(cur)
        mr._load_index_search_items(cur)
        n = sum("from index_ohlcv" in s.lower()
                for s in fake_conn.executed_sqls)
        assert n == 1
