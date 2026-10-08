"""时光机 v3 拟真考核模式(exam)集成测试。

依赖本地 Postgres(同 test_replay_router.py)。只跑本文件:
  python -m pytest tests/api/test_replay_exam.py -v
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import create_app

    return TestClient(create_app())


@pytest.fixture
def db_conn():
    from src.infra.database.sql_engine.dsn import get_dsn
    import psycopg2
    conn = psycopg2.connect(get_dsn())
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def dyn_symbol():
    from src.infra.database.sql_engine.dsn import get_dsn
    import psycopg2
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol FROM stock_ohlcv "
                "WHERE trade_date::date < '2019-06-01' "
                "GROUP BY symbol ORDER BY COUNT(*) DESC LIMIT 1")
            row = cur.fetchone()
            assert row, "stock_ohlcv 无 2019-06 之前的数据"
            return row[0]
    finally:
        conn.close()


@pytest.fixture(scope="module")
def trade_day():
    from src.infra.database.sql_engine.dsn import get_dsn
    import psycopg2
    conn = psycopg2.connect(get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(trade_date::date) FROM index_ohlcv "
                "WHERE symbol = 'sh000001' "
                "AND trade_date::date <= '2020-03-13'")
            return cur.fetchone()[0].isoformat()
    finally:
        conn.close()


class TestExamMigration:
    def test_mode_and_order_type_columns_exist(self, client, db_conn):
        with client:  # 触发 lifespan → ensure_replay_columns
            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name, column_default FROM "
                    "information_schema.columns "
                    "WHERE table_name = 'replay_session' "
                    "AND column_name = 'mode'"
                )
                row = cur.fetchone()
                assert row is not None, "replay_session.mode 列不存在"
                assert "'free'" in (row[1] or "")
                cur.execute(
                    "SELECT column_name, column_default FROM "
                    "information_schema.columns "
                    "WHERE table_name = 'replay_trade' "
                    "AND column_name = 'order_type'"
                )
                row = cur.fetchone()
                assert row is not None, "replay_trade.order_type 列不存在"
                assert "'market'" in (row[1] or "")


class TestExamCreate:
    def test_create_masked_and_no_external_state(self, client, db_conn):
        sid = None
        try:
            r = client.post("/api/v1/replay/sessions", json={
                "mode": "exam", "initial_capital": 100000,
                "length_days": 120, "era_pref": "random"})
            assert r.json()["code"] == 0, r.text
            d = r.json()["data"]
            sid = d["id"]
            assert d["mode"] == "exam"
            assert d["start_date"] is None and d["current_date"] is None
            assert d["day_ordinal"] == 1 and d["length_days"] == 120
            assert "nav" not in d["state"]  # 元数据脱敏
            with db_conn.cursor() as cur:  # 库里有真实日期
                cur.execute("SELECT start_date, mode FROM replay_session "
                            "WHERE id = %s", (sid,))
                row = cur.fetchone()
            assert row[0] is not None and row[1] == "exam"
            g = client.get(f"/api/v1/replay/sessions/{sid}")
            assert g.json()["data"]["start_date"] is None
            x = client.put(f"/api/v1/replay/sessions/{sid}/state",
                           json={"current_date": "2020-01-01", "cash": 1,
                                 "state": {}})
            assert x.json()["code"] != 0  # 服务端记账
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_create_validation(self, client):
        base = {"mode": "exam", "initial_capital": 100000}
        assert client.post("/api/v1/replay/sessions",
                           json=base).json()["code"] != 0
        assert client.post("/api/v1/replay/sessions", json={
            **base, "length_days": 99}).json()["code"] != 0
        assert client.post("/api/v1/replay/sessions", json={
            **base, "length_days": 250,
            "era_pref": "hack"}).json()["code"] != 0
        assert client.post("/api/v1/replay/sessions",
                           json={"mode": "hack"}).json()["code"] != 0


class TestExamAdvance:
    def _make(self, client, symbol, length_days=120):
        r = client.post("/api/v1/replay/sessions", json={
            "mode": "exam", "initial_capital": 100000,
            "length_days": length_days, "era_pref": "random"})
        assert r.json()["code"] == 0, r.text
        sid = r.json()["data"]["id"]
        p = client.post(f"/api/v1/replay/sessions/{sid}/pool",
                        json={"symbols": [symbol]})
        assert p.json()["code"] == 0, p.text
        assert p.json()["data"]["pool"] == [symbol]
        return sid

    def test_view_and_seg_info_gate(self, client, dyn_symbol):
        sid = None
        try:
            sid = self._make(client, dyn_symbol)
            v = client.get(f"/api/v1/replay/sessions/{sid}/view").json()["data"]
            assert v["seg_idx"] == 0 and v["seg_count"] == 8
            assert len(v["segments"][dyn_symbol]) == 1  # 只到第0段
            r = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "seg"})
            v = r.json()["data"]
            assert v["seg_idx"] == 1
            assert len(v["segments"][dyn_symbol]) == 2  # 信息门:≤当前段
            assert (v["partial_bars"][dyn_symbol]["close"]
                    == v["segments"][dyn_symbol][-1]["close"])
            # 创业板指2010-06前无数据,随机起点可能早于此——只要求子集+
            # 日历指数(sh000001,1991年起)必在;每指数段数≤当前段(信息门)
            idx_syms = set(v["indices_segments"])
            assert idx_syms <= {"sh000001", "sz399001", "sz399006",
                                "sh000300"}
            assert "sh000001" in idx_syms
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_roll_at_seg7_and_dividend_path(self, client, dyn_symbol,
                                            db_conn):
        sid = None
        try:
            sid = self._make(client, dyn_symbol)
            for _ in range(7):
                client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "seg"})
            v = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "seg"}).json()["data"]
            assert v["seg_idx"] == 0 and v["day_ordinal"] == 2  # 日切
            with db_conn.cursor() as cur:
                # current_date 须加引号:裸写会被 PG 当作 CURRENT_DATE
                # 关键字(恒返回今天),遮蔽同名列 → 永远断言失败
                cur.execute('SELECT "current_date" FROM replay_session '
                            "WHERE id = %s", (sid,))
                assert cur.fetchone()[0].isoformat() == v["date"]
            assert len(v["nav"]) == 1  # 昨日 nav 已记
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_skip_day_and_travel_complete(self, client, dyn_symbol,
                                          db_conn):
        sid = None
        try:
            sid = self._make(client, dyn_symbol)
            # 直接把 length_days 改成 2,快进两日到终点
            with db_conn.cursor() as cur:
                cur.execute(
                    "UPDATE replay_session "
                    "SET state = jsonb_set(state, '{length_days}', '2') "
                    "WHERE id = %s", (sid,))
                db_conn.commit()
            a = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "day"}).json()["data"]
            assert a["day_ordinal"] == 2 and not a["travel_complete"]
            b = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "day"}).json()["data"]
            assert b["travel_complete"] is True
            c = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "day"})
            assert c.json()["code"] != 0  # 终点后拒绝推进
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_step_mode_mismatch(self, client, dyn_symbol, trade_day):
        sid = None
        try:
            sid = self._make(client, dyn_symbol)
            r = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "days": 1})
            assert r.json()["code"] != 0  # exam 缺 step
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")
        r = client.post("/api/v1/replay/sessions", json={
            "name": "TS_step", "start_date": trade_day,
            "initial_capital": 1e6})
        sid = r.json()["data"]["id"]
        try:
            r = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "seg"})
            assert r.json()["code"] != 0  # free 不接受 step
        finally:
            client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_pool_rejects_bad_symbol(self, client):
        r = client.post("/api/v1/replay/sessions", json={
            "mode": "exam", "initial_capital": 100000,
            "length_days": 120, "era_pref": "random"})
        sid = r.json()["data"]["id"]
        try:
            p = client.post(f"/api/v1/replay/sessions/{sid}/pool",
                            json={"symbols": ["sh999999"]})
            assert p.json()["code"] == 0
            assert p.json()["data"]["failed"] == ["sh999999"]
            assert p.json()["data"]["pool"] == []
        finally:
            client.delete(f"/api/v1/replay/sessions/{sid}")


class TestExamOrders:
    def _make(self, client, db_conn, symbol):
        r = client.post("/api/v1/replay/sessions", json={
            "mode": "exam", "initial_capital": 100000,
            "length_days": 250, "era_pref": "random"})
        sid = r.json()["data"]["id"]
        with db_conn.cursor() as cur:
            # 钉死确定性起点:订单测试的区间构造(×1.05/滑点断言)在随机
            # 抽到逼近涨停的day时会翻车——本类测端点机制,不测随机性
            cur.execute(
                'UPDATE replay_session SET start_date = %s, '
                '"current_date" = %s WHERE id = %s',
                ("2019-06-03", "2019-06-03", sid))
            db_conn.commit()
        client.post(f"/api/v1/replay/sessions/{sid}/pool",
                    json={"symbols": [symbol]})
        return sid

    def _view(self, client, sid):
        return client.get(
            f"/api/v1/replay/sessions/{sid}/view").json()["data"]

    def test_note_required(self, client, db_conn, dyn_symbol):
        sid = None
        try:
            sid = self._make(client, db_conn, dyn_symbol)
            r = client.post(f"/api/v1/replay/sessions/{sid}/orders",
                            json={"symbol": dyn_symbol, "side": "buy",
                                  "order_type": "market", "shares": 100})
            assert r.json()["code"] != 0 and "理由" in r.json()["msg"]
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_market_buy_fills_at_segment_price(self, client, db_conn,
                                                dyn_symbol):
        sid = None
        try:
            sid = self._make(client, db_conn, dyn_symbol)
            v = self._view(client, sid)
            seg_close = v["segments"][dyn_symbol][0]["close"]
            r = client.post(f"/api/v1/replay/sessions/{sid}/orders",
                            json={"symbol": dyn_symbol, "side": "buy",
                                  "order_type": "market", "shares": 100,
                                  "note": "低吸"})
            assert r.json()["code"] == 0, r.text
            d = r.json()["data"]
            assert d["status"] == "filled"
            # 成交价 = 段价×(1+滑点) ∈ [seg_close, seg_close*1.0015]
            assert seg_close <= d["trade"]["price"] <= seg_close * 1.0015 + 0.01
            assert d["positions"][0]["shares"] == 100
            trades = client.get(
                f"/api/v1/replay/sessions/{sid}/trades").json()["data"]
            assert len(trades) == 1
            assert trades[0]["order_type"] == "market"
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_limit_lifecycle(self, client, db_conn, dyn_symbol):
        sid = None
        try:
            sid = self._make(client, db_conn, dyn_symbol)
            v = self._view(client, sid)
            seg_close = v["segments"][dyn_symbol][0]["close"]
            # 激进买价:接近段价上方(区间内)——大概率后续段触发
            limit = round(min(seg_close * 1.05,
                              seg_close * 1.08), 2)
            r = client.post(f"/api/v1/replay/sessions/{sid}/orders",
                            json={"symbol": dyn_symbol, "side": "buy",
                                  "order_type": "limit", "shares": 100,
                                  "limit_price": limit, "note": "挂低点"})
            assert r.json()["code"] == 0, r.text
            d = r.json()["data"]
            assert d["status"] == "pending"
            assert d["frozen_cash"] > 0
            # 快进整日:要么日内成交,要么收盘撤销——终态不变量
            a = client.get("/api/v1/replay/advance",
                           params={"session_id": sid, "step": "day"}).json()["data"]
            assert a["pending"] == []
            assert a["frozen_cash"] == 0.0
            assert a["day_ordinal"] == 2
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_limit_out_of_range_rejected(self, client, db_conn, dyn_symbol):
        sid = None
        try:
            sid = self._make(client, db_conn, dyn_symbol)
            v = self._view(client, sid)
            seg_close = v["segments"][dyn_symbol][0]["close"]
            r = client.post(f"/api/v1/replay/sessions/{sid}/orders",
                            json={"symbol": dyn_symbol, "side": "buy",
                                  "order_type": "limit", "shares": 100,
                                  "limit_price": seg_close * 2,
                                  "note": "乱挂"})
            assert r.json()["code"] != 0 and "区间" in r.json()["msg"]
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_symbol_must_be_in_pool(self, client, db_conn, dyn_symbol):
        sid = None
        try:
            sid = self._make(client, db_conn, dyn_symbol)
            r = client.post(f"/api/v1/replay/sessions/{sid}/orders",
                            json={"symbol": "sh600000", "side": "buy",
                                  "order_type": "market", "shares": 100,
                                  "note": "x"})
            assert r.json()["code"] != 0 and "池" in r.json()["msg"]
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")


class TestExamReveal:
    def test_reveal_scores_and_unmasks(self, client, dyn_symbol, db_conn):
        sid = None
        try:
            r = client.post("/api/v1/replay/sessions", json={
                "mode": "exam", "initial_capital": 100000,
                "length_days": 250, "era_pref": "random"})
            sid = r.json()["data"]["id"]
            client.post(f"/api/v1/replay/sessions/{sid}/pool",
                        json={"symbols": [dyn_symbol]})
            with db_conn.cursor() as cur:
                cur.execute(
                    "UPDATE replay_session "
                    "SET state = jsonb_set(state, '{length_days}', '2') "
                    "WHERE id = %s", (sid,))
                db_conn.commit()
            client.get("/api/v1/replay/advance",
                       params={"session_id": sid, "step": "day"})
            client.get("/api/v1/replay/advance",
                       params={"session_id": sid, "step": "day"})
            r = client.post(f"/api/v1/replay/sessions/{sid}/reveal")
            assert r.json()["code"] == 0, r.text
            d = r.json()["data"]
            assert d["status"] == "revealed"
            sc = d["score"]
            assert 0 <= sc["total"] <= 100
            assert {"excess_score", "turnover_score",
                    "annual_excess_pct", "disclosures"} <= set(sc)
            # 揭晓后元数据不再脱敏
            g = client.get(f"/api/v1/replay/sessions/{sid}").json()["data"]
            assert g["start_date"] is not None
            # 榜上有名
            lb = client.get("/api/v1/replay/leaderboard").json()["data"]
            row = next(x for x in lb if x["id"] == sid)
            assert row["score"] == sc["total"] and row["days"] == 2
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_reveal_without_sailing_fails_gracefully(self, client):
        r = client.post("/api/v1/replay/sessions", json={
            "mode": "exam", "initial_capital": 100000,
            "length_days": 120, "era_pref": "random"})
        sid = r.json()["data"]["id"]
        try:
            x = client.post(f"/api/v1/replay/sessions/{sid}/reveal")
            assert x.json()["code"] != 0  # nav 不足,评分失败但会话仍在
        finally:
            client.delete(f"/api/v1/replay/sessions/{sid}")


class TestConfidenceAndTrainingLog:
    """决策日志补全: 下单信心度透传 + 外部记成交封堵 + 训练册。"""

    def _make(self, client, db_conn, symbol):
        r = client.post("/api/v1/replay/sessions", json={
            "mode": "exam", "initial_capital": 100000,
            "length_days": 250, "era_pref": "random"})
        sid = r.json()["data"]["id"]
        with db_conn.cursor() as cur:
            cur.execute(
                'UPDATE replay_session SET start_date = %s, '
                '"current_date" = %s WHERE id = %s',
                ("2019-06-03", "2019-06-03", sid))
            db_conn.commit()
        client.post(f"/api/v1/replay/sessions/{sid}/pool",
                    json={"symbols": [symbol]})
        return sid

    def test_confidence_validation_and_passthrough(
            self, client, db_conn, dyn_symbol):
        sid = None
        try:
            sid = self._make(client, db_conn, dyn_symbol)
            base = {"symbol": dyn_symbol, "side": "buy",
                    "order_type": "market", "shares": 100,
                    "note": "低吸"}
            bad = client.post(f"/api/v1/replay/sessions/{sid}/orders",
                              json={**base, "confidence": 9})
            assert bad.json()["code"] != 0
            ok = client.post(f"/api/v1/replay/sessions/{sid}/orders",
                             json={**base, "confidence": 4})
            assert ok.json()["code"] == 0, ok.text
            trades = client.get(
                f"/api/v1/replay/sessions/{sid}/trades").json()["data"]
            assert trades[0]["confidence"] == 4
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_add_trade_rejected_for_exam(self, client, db_conn,
                                         dyn_symbol):
        sid = None
        try:
            sid = self._make(client, db_conn, dyn_symbol)
            r = client.post(f"/api/v1/replay/sessions/{sid}/trades",
                            json={"trade_date": "2019-06-03",
                                  "symbol": dyn_symbol, "side": "buy",
                                  "price": 10.0, "shares": 100})
            assert r.json()["code"] != 0
            assert "服务端记账" in r.json()["msg"]
            trades = client.get(
                f"/api/v1/replay/sessions/{sid}/trades").json()["data"]
            assert trades == []
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")

    def test_training_log_aggregates(self, client, db_conn, dyn_symbol):
        sid = None
        try:
            sid = self._make(client, db_conn, dyn_symbol)
            r = client.post(f"/api/v1/replay/sessions/{sid}/orders",
                            json={"symbol": dyn_symbol, "side": "buy",
                                  "order_type": "market", "shares": 100,
                                  "note": "训练一笔", "confidence": 3})
            assert r.json()["code"] == 0, r.text
            with db_conn.cursor() as cur:   # 2 天即到终点,可揭晓
                cur.execute(
                    "UPDATE replay_session "
                    "SET state = jsonb_set(state, '{length_days}', '2') "
                    "WHERE id = %s", (sid,))
                db_conn.commit()
            client.get("/api/v1/replay/advance",
                       params={"session_id": sid, "step": "day"})
            client.get("/api/v1/replay/advance",
                       params={"session_id": sid, "step": "day"})
            rv = client.post(f"/api/v1/replay/sessions/{sid}/reveal")
            assert rv.json()["code"] == 0, rv.text
            tl = client.get("/api/v1/replay/training-log").json()["data"]
            sess = next(s for s in tl["sessions"] if s["id"] == sid)
            assert sess["trade_count"] == 1
            assert sess["score"] is not None
            trade = next(t for t in tl["trades"]
                         if t["session_id"] == sid)
            assert trade["note"] == "训练一笔"
            assert trade["confidence"] == 3
        finally:
            if sid:
                client.delete(f"/api/v1/replay/sessions/{sid}")
