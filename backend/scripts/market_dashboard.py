"""
Ytrader Market Dashboard
========================
Streamlit 市场看板 - K线展示、技术指标、涨跌排行
"""
import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# ── 配置 ─────────────────────────────────────────────────────────────────────
API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="Ytrader 市场看板",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 数据获取 ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_kline(symbol: str, interval="1d", limit=500):
    r = requests.get(f"{API_BASE}/market/kline/{symbol}", params={
        "interval": interval, "limit": limit
    }, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("code") != 0:
        return None
    bars = data["data"]["bars"]
    if not bars:
        return None
    df = pd.DataFrame(bars)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date")
    # 计算技术指标
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    # RSI
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, 0.001)
    df["rsi"] = 100 - (100 / (1 + rs))
    # 成交量均线
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    return df


@st.cache_data(ttl=300)
def fetch_symbols(market="A", limit=100):
    r = requests.get(f"{API_BASE}/market/symbols", params={
        "market": market, "limit": limit
    }, timeout=10)
    if r.status_code != 200:
        return []
    data = r.json()
    if data.get("code") != 0:
        return []
    return data.get("data", [])


@st.cache_data(ttl=60)
def fetch_overview():
    r = requests.get(f"{API_BASE}/market/overview", timeout=10)
    if r.status_code != 200:
        return {}
    return r.json().get("data", {})


# ── 侧边栏 ───────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📈 Ytrader")
    st.markdown("**市场数据看板**")
    st.divider()

    market = st.selectbox("市场", ["A", "HK"], index=0)
    symbols = fetch_symbols(market, limit=5000)
    symbol_map = {s["symbol"]: s["symbol"] for s in symbols}
    symbol_keys = list(symbol_map.keys())
    # 默认显示 sh600000（浦发银行），找不到则用第一个
    default_symbol = "sh600000" if "sh600000" in symbol_keys else symbol_keys[0]
    default_idx = symbol_keys.index(default_symbol) if symbol_keys else 0
    symbol = st.selectbox("股票代码", symbol_keys, index=default_idx)

    interval = st.selectbox("K线周期", ["1d", "60m", "30m", "15m", "5m"], index=0)

    with st.expander("技术指标", expanded=True):
        show_ma = st.checkbox("均线 MA5/10/20/60", value=True)
        show_rsi = st.checkbox("RSI", value=True)
        show_vol = st.checkbox("成交量", value=True)

    st.divider()
    st.caption(f"数据源: TimescaleDB | 更新: {datetime.now():%H:%M}")

# ── 主区域 ───────────────────────────────────────────────────────────────
st.title(f"📊 {symbol} {'A股' if market == 'A' else '港股'} K线")

df = fetch_kline(symbol, interval=interval)

if df is None or df.empty:
    st.warning(f"暂无 {symbol} 的 {interval} 数据")
    st.stop()

# 统计信息
col1, col2, col3, col4, col5 = st.columns(5)
latest = df.iloc[-1]
prev = df.iloc[-2] if len(df) > 1 else latest
change = latest["close"] - prev["close"]
change_pct = (change / prev["close"] * 100) if prev["close"] else 0

col1.metric("最新价", f"{latest['close']:.2f}", f"{change:+.2f}")
col2.metric("涨跌额", f"{change:+.2f}", f"{change_pct:+.1f}%")
col3.metric("成交量", f"{latest['volume']/1e6:.1f}M")
col4.metric("均价", f"{df['close'].mean():.2f}")
col5.metric("数据范围", f"{len(df)} bars")

# ── K线图 ──────────────────────────────────────────────────────────────
fig = make_subplots(
    rows=3, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.05,
    row_heights=[0.6, 0.2, 0.2],
    subplot_titles=("", "成交量", "RSI"),
)

# K线
fig.add_trace(go.Candlestick(
    x=df["trade_date"],
    open=df["open"], high=df["high"],
    low=df["low"], close=df["close"],
    name="OHLC",
    increasing_line_color="#26a69a",
    decreasing_line_color="#ef5350",
), row=1, col=1)

# 均线
if show_ma:
    for ma, color, width in [
        ("ma5", "#ff9800", 1),
        ("ma10", "#2196f3", 1),
        ("ma20", "#9c27b0", 1.5),
        ("ma60", "#ff5722", 1.5),
    ]:
        if ma in df.columns:
            fig.add_trace(go.Scatter(
                x=df["trade_date"], y=df[ma],
                mode="lines", name=ma.upper(),
                line=dict(color=color, width=width),
            ), row=1, col=1)

# 成交量
if show_vol:
    colors = ["#26a69a" if df.iloc[i]["close"] >= df.iloc[i]["open"]
               else "#ef5350" for i in range(len(df))]
    fig.add_trace(go.Bar(
        x=df["trade_date"], y=df["volume"],
        marker_color=colors, name="成交量",
    ), row=2, col=1)
    if "vol_ma5" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["trade_date"], y=df["vol_ma5"],
            mode="lines", name="量均线",
            line=dict(color="#ff9800", width=1),
        ), row=2, col=1)

# RSI
if show_rsi and "rsi" in df.columns:
    fig.add_trace(go.Scatter(
        x=df["trade_date"], y=df["rsi"],
        mode="lines", name="RSI(14)",
        line=dict(color="#9c27b0", width=1.5),
    ), row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#ef5350", row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#26a69a", row=3, col=1)
    fig.update_yaxes(range=[0, 100], row=3, col=1)

fig.update_layout(
    template="plotly_dark",
    height=700,
    showlegend=True,
    xaxis_rangeslider_visible=False,
    hovermode="x unified",
)

st.plotly_chart(fig, width="stretch")

# ── 数据表格 ───────────────────────────────────────────────────────────
with st.expander("📋 查看原始数据"):
    st.dataframe(
        df[["trade_date", "open", "high", "low", "close", "volume", "ma5", "ma20", "rsi"]]
        .rename(columns={"trade_date": "日期"})
        .tail(100)
        .style.format({
            "open": "{:.2f}", "high": "{:.2f}",
            "low": "{:.2f}", "close": "{:.2f}",
            "volume": "{:.0f}", "ma5": "{:.2f}",
            "ma20": "{:.2f}", "rsi": "{:.1f}",
        }),
        width="stretch", height=400,
    )
