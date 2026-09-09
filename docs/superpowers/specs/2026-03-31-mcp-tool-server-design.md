# MCP 工具服务器 (MCP Tool Server)

**项目**: YTrader 量化交易平台
**模块**: MCP Tool Server
**版本**: 1.0
**日期**: 2026-03-31
**状态**: 草稿

---

## 一、模块概述

MCP 工具服务器通过 Model Context Protocol (MCP) 暴露 YTrader 平台的核心功能，使 AI Agent（如 Claude Desktop、Cursor、Cherry Studio）能够以标准化协议调用平台的行情查询、信号分析、舆情监控等工具。

核心价值：
- **标准化接口**：AI Agent 无需了解平台内部实现
- **工具发现**：MCP 动态发现机制，Agent 可探索可用工具
- **双向通信**：支持 STDIO（本地）和 HTTP（远程）两种传输模式

---

## 二、协议架构

### 2.1 MCP 协议概述

MCP (Model Context Protocol) 是一套 JSON-RPC 2.0 的工具调用协议：

```
AI Agent                              MCP Server
    │                                      │
    │ ─── initialize ────────────────────→ │
    │ ←── tools/list ──────────────────── │
    │ ─── tools/call ───────────────────→ │
    │ ←── tools/result ────────────────── │
    │ ─── tools/call ───────────────────→ │
    │ ←── tools/result ────────────────── │
    │              ...                     │
```

### 2.2 传输模式

| 模式 | 适用场景 | 端口 |
|------|---------|------|
| STDIO | 本地 AI 客户端（Claude Desktop、Cline） | 无 |
| HTTP | 生产环境、Cherry Studio 远程 | 3333 |

---

## 三、工具分类

### 3.1 工具清单

#### P0 - 核心数据查询

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `get_latest_news` | 最新舆情新闻 | `limit: int` |
| `get_news_by_date` | 按日期查询新闻 | `date: str`, `symbol: str` |
| `get_trending_topics` | 趋势主题列表 | `time_window: str` |
| `get_market_overview` | 市场概览 | `market: str` |

#### P1 - 智能搜索

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `search_news` | 关键词搜索新闻 | `keyword: str`, `mode: str` |
| `search_related_news_history` | 搜索历史相关新闻 | `topic: str` |

#### P2 - 进阶分析

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `analyze_topic_trend` | 主题趋势分析 | `topic: str`, `mode: str` |
| `analyze_data_insights` | 数据洞察分析 | `type: str` |
| `analyze_sentiment` | 情感分析 | `topic: str` |
| `find_similar_news` | 查找相似新闻 | `news_id: str` |
| `generate_summary_report` | 生成摘要报告 | `topic: str` |

#### P3 - 系统管理

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `get_current_config` | 获取当前配置 | - |
| `get_system_status` | 系统状态 | - |
| `trigger_crawl` | 触发数据采集 | `source: str` |

### 3.2 工具定义格式

```python
from fastmcp import FastMCP

mcp = FastMCP("ytrader-tools")

@mcp.tool()
async def get_latest_news(limit: int = 10) -> list[dict]:
    """获取最新的舆情新闻列表

    Args:
        limit: 返回数量上限

    Returns:
        list[dict]: 最新新闻列表，每条包含标题、平台、排名、时间
    """
    ...

@mcp.tool()
async def search_news(keyword: str, mode: str = "fuzzy") -> list[dict]:
    """按关键词搜索新闻

    Args:
        keyword: 搜索关键词
        mode: 搜索模式 (fuzzy/exact/entity)

    Returns:
        list[dict]: 匹配的新闻列表
    """
    ...
```

---

## 四、FastMCP 实现

### 4.1 服务端架构

```python
# mcp_server/server.py
from fastmcp import FastMCP

mcp = FastMCP(
    "ytrader",
    description="YTrader Quantitative Trading Platform Tools",
    dependencies=["httpx", "pandas"]
)


# 数据查询工具
@mcp.tool(category="Data Query")
async def get_latest_news(limit: int = 10) -> list[dict]:
    ...


@mcp.tool(category="Data Query")
async def get_trending_topics(time_window: str = "1h") -> list[dict]:
    ...


# 分析工具
@mcp.tool(category="Analytics")
async def analyze_sentiment(topic: str) -> dict:
    ...


@mcp.tool(category="Analytics")
async def analyze_topic_trend(topic: str, mode: str = "trend") -> dict:
    """分析主题趋势

    Args:
        topic: 主题名称
        mode: 分析模式 (trend/lifecycle/viral/predict)
    """
    ...


# 搜索工具
@mcp.tool(category="Search")
async def search_news(keyword: str, mode: str = "fuzzy") -> list[dict]:
    ...


# 系统工具
@mcp.tool(category="System")
async def get_system_status() -> dict:
    ...
```

### 4.2 启动方式

```bash
# STDIO 模式（默认，本地 AI 客户端）
python -m mcp_server.server

# HTTP 模式（生产环境）
python -m mcp_server.server --transport http --port 3333

# 指定工具分类
python -m mcp_server.server --default-categories "Data Query,Analytics"
```

---

## 五、AI 客户端集成

### 5.1 Claude Desktop

```json
// ~/.claude/desktop/settings.json
{
  "mcpServers": {
    "ytrader": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "env": {
        "YTRADER_API_KEY": "your-api-key"
      }
    }
  }
}
```

### 5.2 Cherry Studio

通过 HTTP 模式连接：`http://localhost:3333/mcp`

### 5.3 Cursor / Cline

在 `.cursor/mcp.json` 或 `.cline/mcp.json` 中配置：

```json
{
  "mcpServers": {
    "ytrader": {
      "command": "uvicorn",
      "args": ["mcp_server.server:app", "--host", "0.0.0.0", "--port", "3333"]
    }
  }
}
```

---

## 六、安全性

### 6.1 认证机制

```python
# API Key 认证
@app.middleware
async def auth_middleware(request: Request, call_next):
    if request.headers.get("Authorization") != f"Bearer {API_KEY}":
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)
```

### 6.2 限流

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@mcp.tool()
@limiter.limit("30/minute")
async def analyze_sentiment(topic: str) -> dict:
    ...
```

---

## 七、API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `GET /mcp/tools` | GET | 列出所有可用工具 |
| `POST /mcp/tools/call` | POST | 调用指定工具 |
| `GET /mcp/health` | GET | 健康检查 |

---

## 八、核心组件

| 组件 | 职责 |
|------|------|
| `FastMCP Server` | MCP 协议服务端实现 |
| `DataQueryTools` | P0 数据查询工具实现 |
| `AnalyticsTools` | P2 分析工具实现 |
| `SearchTools` | P1 搜索工具实现 |
| `AuthMiddleware` | API Key 认证 |
| `RateLimiter` | 限流控制 |

---

**文档版本**: 1.0
**最后更新**: 2026-03-31
