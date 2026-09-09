# ytrader

量化交易服务

## 项目信息

- **作者**: yuandonghao
- **项目版本**: 0.1.0
- **Python版本要求**: 3.13
- **创建年份**: 2025

## 快速开始

查看详细的 [快速开始指南](GETTING_STARTED.md) 了解如何安装和运行项目。

### 简单启动步骤

1. **安装依赖**:
   ```bash
   # 使用 uv (推荐)
   make install-dev

   # 或使用 pip
   pip install -e ".[dev]"
   ```

2. **运行应用**:
   ```bash
   make run
   ```

3. **访问API文档**:
   打开浏览器访问 `http://localhost:8000/docs`

## 项目架构

本项目基于领域驱动设计（DDD）原则架构设计：
```
ytrader/
│
├── main.py                          # 启动入口
│
├── conf/                            # 配置文件
│   ├── config.yaml                  # 配置文件
│   └── settings.py                  # 配置加载器
│
├── src/
│   ├── api/                         # API 层
│   │   ├── handler/                 # HTTP 请求处理器
│   │   ├── middleware/              # 中间件组件
│   │   ├── model/                   # API 模型定义
│   │   ├── router/                  # 路由定义
│   │   └── internal/                # 内部工具
│   │
│   ├── application/                  # 应用层，组合领域对象和基础设施实现
│   │   ├── file/                    # 文件分析应用
│   │   │   ├── dto/                 # 数据传输对象
│   │   │   └── use_cases/           # 用例实现
│   │   ├── user/                    # 用户应用
│   │   │   ├── dto/
│   │   │   └── use_cases/
│   │   └── product/                 # 产品应用
│   │       ├── dto/
│   │       └── use_cases/
│   │
│   ├── domain/                       # 领域层，包含核心业务逻辑
│   │   ├── file/                    # 文件领域
│   │   │   ├── entities/            # 领域实体
│   │   │   └── services/            # 领域服务
│   │   ├── user/                    # 用户领域
│   │   │   ├── entities/
│   │   │   └── services/
│   │   └── product/                 # 产品领域
│   │       ├── entities/
│   │       └── services/
│   │
│   ├── crossdomain/                 # 跨领域防腐层
│   │   ├── file_contract.py          # 跨领域接口定义
│   │   └── impl/                    # 跨领域接口实现
│   │
│   ├── infra/                       # 基础设施层
│   │   ├── parser/                  # 解析器
│   │   │   ├── parser_interface.py   # 解析器接口
│   │   │   └── impl/                # 解析器实现
│   │   ├── storage/                 # 存储服务
│   │   │   ├── storage_interface.py  # 存储接口
│   │   │   ├── avatar_storage_interface.py
│   │   │   └── impl/                # 存储实现
│   │   ├── database/                # 数据库
│   │   │   ├── database_interface.py # 数据库接口
│   │   │   └── impl/                # 数据库实现
│   │   └── search/                  # 搜索引擎
│   │       ├── search_interface.py   # 搜索接口
│   │       └── impl/                 # 搜索实现
│   │
│   ├── pkg/                         # 工具包
│   │   ├── logging/                 # 日志工具
│   │   ├── exceptions/              # 异常处理
│   │   └── responses/               # 统一响应格式
│   │
│   └── types/                       # 类型定义层
│       ├── consts/                  # 常量定义
│       ├── errno/                   # 错误码定义
│       └── ddl/                     # 数据定义语言
│
└── tests/                           # 测试目录
    ├── api/
    ├── application/
    ├── domain/
    ├── crossdomain/
    └── types/
```

### 架构层次说明

| 层次 | 目录 | 说明 |
|------|------|------|
| **API 层** | `src/api/` | 实现 HTTP 端点，处理请求/响应，包含中间件组件 |
| **应用层** | `src/application/` | 组合领域对象和基础设施实现，提供 API 服务 |
| **领域层** | `src/domain/` | 包含核心业务逻辑，定义领域实体和值对象 |
| **跨领域防腐层** | `src/crossdomain/` | 定义跨领域接口，防止领域间直接依赖 |
| **基础设施层** | `src/infra/` | 实现外部依赖，如数据库、缓存、存储、搜索等 |
| **类型定义层** | `src/types/` | 常量定义、错误码、数据定义语言 |
| **工具包** | `src/pkg/` | 无外部依赖的工具方法 |
| **配置** | `conf/` | 配置文件 |

## 统一响应格式

本项目遵循 HTTP/JSON 接口的事实标准：**接口字段使用 camelCase，内部代码使用 snake_case**。

### 非分页响应

**成功响应：**

```json
{
  "code": 0,
  "msg": "success",
  "data": { ... }
}
```

**失败响应：**

```json
{
  "code": 10001,
  "msg": "参数错误",
  "data": null
}
```

**使用示例：**

```python
from src.pkg.responses import success, fail

# 成功响应
return success(data={"id": 1, "name": "张三"})

# 失败响应
return fail(msg="用户不存在", code=10001)
```

### 分页响应 PageResponse

**响应格式：**

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "records": [...],
    "total": 100,
    "page": 1,
    "size": 20,
    "pageSize": 5
  }
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| code | int | 响应码 (0=成功) |
| msg | string | 响应消息 |
| data.records | array | 数据列表 |
| data.total | int | 总记录数 |
| data.page | int | 当前页码（从1开始） |
| data.size | int | 每页大小 |
| data.pageSize | int | 总页数 |

**使用示例：**

```python
from src.pkg.responses import PageResponse, page_success

# 方式一：使用类方法
response = PageResponse.of(users, total=100, size=20, page=1)
return response.to_json_response()

# 方式二：使用便捷函数
return page_success(users, total=100, size=20, page=1)

# 创建空分页响应
return PageResponse.empty(size=20, page=1).to_json_response()

# 创建失败响应
return PageResponse.failure(code=10001, msg="查询失败").to_json_response()
```

**位置：** `src/pkg/responses/__init__.py`

### SSE (Server-Sent Events) 响应

用于服务器向客户端推送实时事件流。

**HTTP 响应头：**

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

**事件格式：**

```
event: message
data: {"code":0,"msg":"success","event":"message","data":{...}}

```

**事件类型：**

| 事件类型 | 说明 |
|----------|------|
| `start` | 流开始 |
| `message` | 消息事件 |
| `error` | 错误事件 |
| `done` | 流结束 |

**使用示例：**

```python
from src.pkg.responses.sse import SseResponse, StreamEvent
from fastapi.responses import StreamingResponse

# 创建事件
event = SseResponse.message({"content": "Hello"})
sse_string = event.to_sse_string()

# 在 FastAPI 中使用
@app.get("/stream")
async def stream():
    async def event_generator():
        yield SseResponse.start({"session_id": "123"}).to_sse_string()
        yield SseResponse.message({"content": "Hello"}).to_sse_string()
        yield SseResponse.done().to_sse_string()
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

**位置：** `src/pkg/responses/sse.py`

### Streamable HTTP 响应

基于 MCP (Model Context Protocol) 的 Streamable HTTP transport 规范。

**响应格式：**

```json
{
  "jsonrpc": "2.0",
  "id": "req_123",
  "result": {...}
}
```

**使用示例：**

```python
from src.pkg.responses.sse import StreamableResponse

# 创建消息响应
response = StreamableResponse.message("req_123", {"content": "Hello"})

# 创建完成响应
done = StreamableResponse.done("req_123")

# 创建错误响应
error = StreamableResponse.error("req_123", 10001, "处理失败")
```

**位置：** `src/pkg/responses/sse.py`

## 开发工具配置

`uv add pytest pytest-asyncio --dev` or `pip install pytest pytest-asyncio`

### EditorConfig
本项目包含 `.editorconfig` 文件，用于在不同编辑器和IDE之间维护一致的代码风格。建议安装 EditorConfig 插件以自动应用这些设置。

### 代码格式化
- 使用 Black 进行代码格式化
- 使用 isort 进行导入排序
- 使用 flake8 进行代码检查

### 代码格式化

```bash
make format
```

### 代码检查

```bash
make lint
```

## 代码质量工具

模板包含以下工具的配置：

- **Black**: 代码格式化工具，确保一致的代码风格
- **isort**: 导入排序工具，按字母顺序组织导入并将其分组
- **flake8**: 代码检查工具，检查 PEP 8 合规性和常见 Python 错误
- **EditorConfig**: 在不同编辑器和 IDE 之间维护一致的编码风格

这些工具有助于维护项目的代码质量和一致性。

## 模板开发

如果您想修改此模板本身：

1. 克隆或下载此仓库
2. 修改 `ytrader` 目录中的文件
3. 通过在根目录运行 `cookiecutter .` 来测试您的更改
4. 提交包含您改进的 pull request