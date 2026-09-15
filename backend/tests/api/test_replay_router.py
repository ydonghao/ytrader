"""时光机 replay router 集成测试 — TestClient 打本地 PG，自带清理。

依赖本地 Postgres（见 tests/conftest.py）。只跑本文件：
python -m pytest tests/api/test_replay_router.py -v
"""

import datetime as dt
import re

import psycopg2
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import create_app

    return TestClient(create_app())


def _create(client, **kw):
    body = {
        "name": "TS_旅程",
        "start_date": "2020-03-13",
        "initial_capital": 1_000_000,
    }
    body.update(kw)
    return client.post("/api/v1/replay/sessions", json=body)


def _cleanup(client, sid):
    client.delete(f"/api/v1/replay/sessions/{sid}")


class TestReplayTables:
    """Task 1 冒烟: lifespan create_all 应建好两张 replay 表。"""

    def test_replay_tables_created(self, client, db_connection):
        with client:  # 进入 lifespan, 触发 SQLModel.metadata.create_all
            cur = db_connection.cursor()
            cur.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE tablename IN ('replay_session', 'replay_trade')"
            )
            assert {row[0] for row in cur.fetchall()} == {
                "replay_session",
                "replay_trade",
            }


class TestReplaySession:
    def test_session_lifecycle(self, client):
        sid = None
        try:
            r = _create(client)
            assert r.status_code == 200 and r.json()["code"] == 0, r.text
            data = r.json()["data"]
            sid = data["id"]
            # 2020-03-13 是交易日，不 snap
            assert data["current_date"] == "2020-03-13"
            assert data["status"] == "active"
            assert data["state"] == {"pool": [], "positions": [], "nav": []}

            r = client.get("/api/v1/replay/sessions")
            assert any(s["id"] == sid for s in r.json()["data"])
            # 列表不带 state
            assert "state" not in next(
                s for s in r.json()["data"] if s["id"] == sid
            )

            # 存档往返
            r = client.put(
                f"/api/v1/replay/sessions/{sid}/state",
                json={
                    "current_date": "2020-03-16",
                    "cash": 900000.5,
                    "state": {
                        "pool": ["600519"],
                        "positions": [
                            {
                                "symbol": "600519",
                                "shares": 100,
                                "cost_price": 996.0,
                                "buy_date": "2020-03-13",
                            }
                        ],
                        "nav": [{"date": "2020-03-16", "value": 999000.5}],
                    },
                },
            )
            assert r.json()["code"] == 0, r.text
            r = client.get(f"/api/v1/replay/sessions/{sid}")
            got = r.json()["data"]
            assert got["current_date"] == "2020-03-16"
            assert got["cash"] == 900000.5
            assert got["state"]["pool"] == ["600519"]
            assert got["state"]["positions"][0]["shares"] == 100

            # 成交记录
            r = client.post(
                f"/api/v1/replay/sessions/{sid}/trades",
                json={
                    "trade_date": "2020-03-13",
                    "symbol": "600519",
                    "side": "buy",
                    "price": 996.0,
                    "shares": 100,
                    "fee": 24.9,
                    "tax": 0,
                    "note": "TS_理由",
                },
            )
            assert r.json()["code"] == 0, r.text
            r = client.get(f"/api/v1/replay/sessions/{sid}/trades")
            trades = r.json()["data"]
            assert len(trades) == 1
            assert trades[0]["note"] == "TS_理由"
            assert trades[0]["side"] == "buy"

            # 揭晓不可逆 + 揭晓后拒绝记成交
            r = client.post(f"/api/v1/replay/sessions/{sid}/reveal")
            assert r.json()["data"]["status"] == "revealed"
            r = client.post(
                f"/api/v1/replay/sessions/{sid}/trades",
                json={
                    "trade_date": "2020-03-16",
                    "symbol": "600519",
                    "side": "sell",
                    "price": 1000.0,
                    "shares": 100,
                    "fee": 25.0,
                    "tax": 50.0,
                },
            )
            assert r.json()["code"] != 0
        finally:
            if sid is not None:
                _cleanup(client, sid)
        r = client.get(f"/api/v1/replay/sessions/{sid}")
        assert r.json()["code"] != 0

    def test_create_validation(self, client):
        # 起始日不能是今天/未来
        today = dt.date.today().isoformat()
        assert _create(client, start_date=today).json()["code"] != 0
        # 非交易日 snap 到下一交易日：2020-03-14(周六) → 2020-03-16(周一)
        sid = None
        try:
            r = _create(client, name="TS_snap", start_date="2020-03-14")
            assert r.json()["code"] == 0, r.text
            data = r.json()["data"]
            sid = data["id"]
            assert data["current_date"] >= "2020-03-14"
            assert data["start_date"] == data["current_date"]
        finally:
            if sid is not None:
                _cleanup(client, sid)
        # 非法参数
        assert _create(client, initial_capital=0).json()["code"] != 0
        assert _create(client, name="").json()["code"] != 0
        # end_date 不能晚于今天（终审 I2）
        assert _create(client, name="TS_end", start_date="2020-03-13",
                       end_date="2999-01-01").json()["code"] != 0


@pytest.fixture(scope="module")
def dyn_symbol():
    """动态选一只 2019-06 前就有数据的 A 股，避免硬编码依赖。"""
    from src.infra.database.sql_engine.dsn import get_dsn
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol FROM stock_ohlcv "
                "WHERE trade_date::date < '2019-06-01' "
                "GROUP BY symbol ORDER BY COUNT(*) DESC LIMIT 1"
            )
            row = cur.fetchone()
            assert row, "stock_ohlcv 无 2019-06 之前的数据"
            return row[0]
    finally:
        conn.close()


@pytest.fixture(scope="module")
def trade_day():
    """≤2020-03-13 的最近一个交易日（动态，防硬编码）。"""
    from src.infra.database.sql_engine.dsn import get_dsn
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(trade_date::date) FROM index_ohlcv "
                "WHERE symbol = 'sh000001' "
                "AND trade_date::date <= '2020-03-13'"
            )
            d = cur.fetchone()[0]
            assert d is not None
            return d.isoformat()
    finally:
        conn.close()


class TestReplaySlicing:
    def test_kline_asof_cutoff(self, client, dyn_symbol, trade_day):
        r = client.get(
            f"/api/v1/replay/kline/{dyn_symbol}",
            params={"asof": trade_day, "limit": 10},
        )
        assert r.json()["code"] == 0, r.text
        bars = r.json()["data"]["bars"]
        assert 0 < len(bars) <= 10
        assert all(b["trade_date"] <= trade_day for b in bars)
        assert [b["trade_date"] for b in bars] == sorted(
            b["trade_date"] for b in bars)
        assert {"open", "close", "high", "low",
                "volume", "amount"} <= set(bars[0])

    def test_kline_reject_future_asof(self, client, dyn_symbol):
        tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        r = client.get(
            f"/api/v1/replay/kline/{dyn_symbol}",
            params={"asof": tomorrow},
        )
        assert r.json()["code"] != 0

    def test_advance(self, client, dyn_symbol, trade_day):
        sid = None
        try:
            r = _create(client, name="TS_adv", start_date=trade_day)
            assert r.json()["code"] == 0, r.text
            sid = r.json()["data"]["id"]
            assert r.json()["data"]["current_date"] == trade_day
            client.put(
                f"/api/v1/replay/sessions/{sid}/state",
                json={
                    "current_date": trade_day, "cash": 1e6,
                    "state": {"pool": [dyn_symbol],
                              "positions": [], "nav": []},
                },
            )
            r = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "days": 3})
            assert r.json()["code"] == 0, r.text
            data = r.json()["data"]
            assert len(data["dates"]) == 3
            assert data["dates"] == sorted(data["dates"])
            assert all(d > trade_day for d in data["dates"])
            # 池内标的 bar 只落在 dates 内
            for d in (b["trade_date"]
                      for b in data["bars"].get(dyn_symbol, [])):
                assert d in data["dates"]
            assert len(data["benchmark"]) >= 1
        finally:
            if sid is not None:
                _cleanup(client, sid)

    def test_advance_unknown_session(self, client):
        r = client.get("/api/v1/replay/advance",
                       params={"session_id": 99999999, "days": 1})
        assert r.json()["code"] != 0

    def test_advance_cursor_no_debounce_gap(self, client, dyn_symbol,
                                            trade_day):
        """两次 advance 中间不 PUT state，日期集必须不相交（终审 C1 回归）。"""
        sid = None
        try:
            r = _create(client, name="TS_cursor", start_date=trade_day)
            assert r.json()["code"] == 0, r.text
            sid = r.json()["data"]["id"]
            r1 = client.get("/api/v1/replay/advance",
                            params={"session_id": sid, "days": 2})
            r2 = client.get("/api/v1/replay/advance",
                            params={"session_id": sid, "days": 2})
            d1 = r1.json()["data"]["dates"]
            d2 = r2.json()["data"]["dates"]
            assert d1 and d2
            assert set(d1).isdisjoint(d2)
            assert min(d2) > max(d1)
            # 会话游标已被推进（无 PUT state 也生效）
            r = client.get(f"/api/v1/replay/sessions/{sid}")
            assert r.json()["data"]["current_date"] == max(d2)
        finally:
            if sid is not None:
                _cleanup(client, sid)


class TestReplayValuationBoard:
    def test_valuation(self, client, dyn_symbol, trade_day):
        r = client.get(
            f"/api/v1/replay/valuation/{dyn_symbol}",
            params={"asof": trade_day},
        )
        assert r.json()["code"] == 0, r.text
        data = r.json()["data"]
        assert data["as_of"] == trade_day
        assert set(data) >= {"pe_ttm", "pb"}
        for key in ("pe_ttm", "pb"):
            v = data[key]
            if v is not None:
                assert v["value"] > 0
                assert v["window"] == "10y"
                if v["percentile"] is not None:
                    assert 0 <= v["percentile"] <= 1

    def test_board_gainers(self, client, trade_day):
        r = client.get("/api/v1/replay/board",
                       params={"asof": trade_day, "type": "gainers"})
        assert r.json()["code"] == 0, r.text
        rows = r.json()["data"]
        assert len(rows) > 1
        pcts = [x["pct_chg"] for x in rows]
        assert pcts == sorted(pcts, reverse=True)
        # 榜单只含 A 股（stock_ohlcv 混有港股，须被前缀过滤）
        assert all(re.match(r"^(sh|sz|bj)\d{6}$", x["symbol"])
                   for x in rows)
        assert {"symbol", "name", "close",
                "pct_chg", "amount"} <= set(rows[0])

    def test_board_amount(self, client, trade_day):
        r = client.get("/api/v1/replay/board",
                       params={"asof": trade_day, "type": "amount"})
        assert r.json()["code"] == 0, r.text
        amts = [x["amount"] for x in r.json()["data"]]
        assert amts == sorted(amts, reverse=True)

    def test_board_bad_type(self, client, trade_day):
        r = client.get("/api/v1/replay/board",
                       params={"asof": trade_day, "type": "hack"})
        assert r.json()["code"] != 0
