# LLM 统一配置与调用切面设计

> 日期: 2026-06-03
> 状态: Draft

## 概述

设计一个统一的 LLM 调用切面，支持 OpenAI Chat Completions、OpenAI Responses API、Anthropic Messages 三种协议。所有模型配置存后端数据库（API Key AES 加密），前端 Settings 页面可增删改查。

所有后端场景（信号生成、资讯 AI 处理、AI 对话、策略 Agent）通过统一接口调用，不直接依赖具体 SDK。

## 需求

1. **三种协议并行**：OpenAI Chat、OpenAI Response、Anthropic Messages，每个 Provider 直接调用对应官方 SDK
2. **后端数据库存储**：模型配置（name、provider_type、base_url、api_key、model、extra_params）存 PostgreSQL
3. **API Key 加密**：AES-256 对称加密存数据库，前端 GET 请求返回 `****`，编辑不传则保留原值
4. **前端可编辑**：Settings 页面新增 LLM 模型配置区块，支持增删改查 + 设默认 + 测试连接
5. **纯自定义**：用户自行填写 endpoint、模型名等，无预置模板
6. **统一调用切面**：所有后端场景通过 `LLMManager` 获取 Provider 实例调用

## 后端架构

### 领域层 — 接口与模型

```
src/domain/llm/
├── __init__.py
├── models.py               # LLMResponse, LLMConfig, TokenUsage, TestResult
├── provider_interface.py   # LLMProvider(ABC)
└── repository_interface.py # ILLMConfigRepository(ABC)
```

**LLMProvider 接口** (`provider_interface.py`):

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator

class LLMProvider(ABC):
    """统一大模型调用接口。所有 Provider 必须实现此接口。"""

    @abstractmethod
    async def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        """多轮对话。messages 格式: [{"role": "user", "content": "..."}]"""

    @abstractmethod
    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        """单次补全。"""

    @abstractmethod
    async def chat_stream(self, messages: list[dict], **kwargs) -> AsyncIterator[LLMChunk]:
        """流式多轮对话。"""
```

**数据模型** (`models.py`):

```python
from dataclasses import dataclass, field

@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

@dataclass
class LLMResponse:
    content: str
    model: str
    usage: TokenUsage | None = None
    raw_response: dict | None = None

@dataclass
class LLMChunk:
    content: str
    model: str
    finish_reason: str | None = None

@dataclass
class LLMConfig:
    """一条模型配置（领域模型，api_key 为明文）。"""
    id: str
    name: str                          # 显示名称，如 "GPT-4o"
    provider_type: str                 # "openai_chat" | "openai_response" | "anthropic"
    base_url: str                      # API 端点
    api_key: str                       # 明文 API Key（仅在内存中）
    model: str                         # 模型标识，如 "gpt-4o"
    is_default: bool = False
    extra_params: dict = field(default_factory=dict)  # temperature, max_tokens 等
    created_at: str | None = None
    updated_at: str | None = None

@dataclass
class TestResult:
    success: bool
    message: str
    latency_ms: float | None = None
```

**仓储接口** (`repository_interface.py`):

```python
from abc import ABC, abstractmethod

class ILLMConfigRepository(ABC):
    @abstractmethod
    async def list_configs(self) -> list[LLMConfig]: ...

    @abstractmethod
    async def get_config(self, config_id: str) -> LLMConfig | None: ...

    @abstractmethod
    async def get_default_config(self) -> LLMConfig | None: ...

    @abstractmethod
    async def create_config(self, config: LLMConfig) -> LLMConfig: ...

    @abstractmethod
    async def update_config(self, config_id: str, updates: dict) -> LLMConfig | None: ...

    @abstractmethod
    async def delete_config(self, config_id: str) -> bool: ...

    @abstractmethod
    async def set_default(self, config_id: str) -> None: ...
```

### 基础设施层 — Provider 实现

```
src/infra/llm/
├── __init__.py
├── providers/
│   ├── __init__.py
│   ├── openai_chat_provider.py       # openai SDK → Chat Completions API
│   ├── openai_response_provider.py   # openai SDK → Responses API
│   └── anthropic_provider.py         # anthropic SDK → Messages API
├── provider_factory.py               # create_provider(config) → LLMProvider
├── key_encryptor.py                  # AES-256 加解密
└── manager.py                        # LLMManager 统一入口
```

**三个 Provider 的职责**:

| Provider | SDK | 核心方法 |
|----------|-----|---------|
| `OpenAIChatProvider` | `openai` | `client.chat.completions.create()` |
| `OpenAIResponseProvider` | `openai` | `client.responses.create()` |
| `AnthropicProvider` | `anthropic` | `client.messages.create()` |

每个 Provider 构造函数接收 `LLMConfig`（含明文 api_key），在内部创建 SDK client 实例。`chat()` 和 `complete()` 将 SDK 返回结果统一转为 `LLMResponse`。

**Provider 工厂** (`provider_factory.py`):

```python
PROVIDER_MAP = {
    "openai_chat": OpenAIChatProvider,
    "openai_response": OpenAIResponseProvider,
    "anthropic": AnthropicProvider,
}

def create_provider(config: LLMConfig) -> LLMProvider:
    """根据 provider_type 创建对应 Provider 实例。"""
    provider_cls = PROVIDER_MAP.get(config.provider_type)
    if not provider_cls:
        raise ValueError(f"Unknown provider type: {config.provider_type}")
    return provider_cls(config)
```

**AES 加密** (`key_encryptor.py`):

- 使用 `cryptography` 库的 `Fernet` 对称加密
- 加密密钥来源：`config.yaml` 中的 `llm.encryption_key`，首次启动自动生成
- 提供 `encrypt_key(plaintext) -> str` 和 `decrypt_key(ciphertext) -> str` 两个函数

**LLMManager** (`manager.py`):

```python
class LLMManager:
    """统一 LLM 调用管理器。应用层和 API 层通过此类获取 Provider。"""

    def __init__(self, repo: ILLMConfigRepository): ...

    def get_provider(self, config_id: str | None = None) -> LLMProvider | None:
        """获取指定配置的 Provider。config_id 为 None 时返回默认模型的 Provider。无配置时返回 None。"""

    async def test_connection(self, config_id: str) -> TestResult:
        """测试模型连接：发送 "Hi" 并检查响应。"""

    async def refresh(self) -> None:
        """清除缓存，强制下次调用重新加载配置。"""
```

Manager 内部维护 Provider 实例缓存（按 config_id 缓存），配置变更时调用 `refresh()` 清除。

### 数据库层

```
src/infra/database/impl/llm_db.py  →  LLMConfigRepository(ILLMConfigRepository)
```

**表结构**:

```python
class LLMConfigTable(SQLModel, table=True):
    __tablename__ = "llm_config"

    id: str = Field(default_factory=uuid4_str, primary_key=True)
    name: str = Field(index=True)
    provider_type: str                              # "openai_chat" | "openai_response" | "anthropic"
    base_url: str
    api_key_encrypted: str                          # AES 加密后的密文
    model: str
    is_default: bool = Field(default=False, index=True)
    extra_params: str = Field(default="{}")         # JSON 字符串
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID str | 主键 |
| `name` | str | 用户自定义的显示名称 |
| `provider_type` | str | 协议类型枚举：`openai_chat`, `openai_response`, `anthropic` |
| `base_url` | str | API 端点 URL |
| `api_key_encrypted` | str | AES-256 加密后的 API Key |
| `model` | str | 模型标识符 |
| `is_default` | bool | 是否为默认模型（全局只有一个） |
| `extra_params` | str | JSON 序列化的额外参数 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

仓储实现中：
- `create_config()` / `update_config()`：调用 `key_encryptor.encrypt_key()` 加密后存库
- `get_config()` / `list_configs()`：返回的 `LLMConfig` 中 `api_key` 为 `****`（脱敏）
- `get_default_config()` 内部使用 `decrypt_key()` 解密后返回完整 LLMConfig（供 Manager 创建 Provider）
- `set_default()`：先清除所有 `is_default=False`，再设置目标为 `True`

### API 路由

```
src/api/router/llm_config_router.py
```

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/api/v1/llm/configs` | 获取所有模型配置（api_key 返回 `****`） |
| `POST` | `/api/v1/llm/configs` | 新增模型配置 |
| `PUT` | `/api/v1/llm/configs/{id}` | 更新模型配置（api_key 为空则保留原值） |
| `DELETE` | `/api/v1/llm/configs/{id}` | 删除模型配置 |
| `PUT` | `/api/v1/llm/configs/{id}/default` | 设为默认模型 |
| `POST` | `/api/v1/llm/test` | 测试连接 |

**请求/响应模型** (`src/api/model/llm_config_model.py`):

```python
class LLMConfigCreate(BaseModel):
    name: str
    provider_type: Literal["openai_chat", "openai_response", "anthropic"]
    base_url: str
    api_key: str
    model: str
    is_default: bool = False
    extra_params: dict = {}

class LLMConfigUpdate(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    base_url: str | None = None
    api_key: str | None = None      # None 或空字符串表示保留原值
    model: str | None = None
    is_default: bool | None = None
    extra_params: dict | None = None

class LLMConfigResponse(BaseModel):
    id: str
    name: str
    provider_type: str
    base_url: str
    api_key: str                     # 返回 "****" 脱敏
    model: str
    is_default: bool
    extra_params: dict
    created_at: str
    updated_at: str

class LLMTestRequest(BaseModel):
    config_id: str | None = None     # None 则测试默认模型
```

## 前端设计

### Settings 页面 — LLM 配置区块

替换现有 "AI / LLM Configuration" 区块，新增完整的模型管理 UI。

**布局结构**:

```
┌─ LLM 模型配置 ─────────────────────────────────────────┐
│                                                          │
│  [+ 添加模型]                                [测试连接]  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │ ★ GPT-4o                           [编辑] [删除]  │ │
│  │   协议: OpenAI Chat | 模型: gpt-4o                 │ │
│  │   端点: https://api.openai.com/v1                  │ │
│  └────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────┐ │
│  │   Claude Sonnet                    [编辑] [删除]  │ │
│  │   协议: Anthropic | 模型: claude-sonnet-4-20250514 │ │
│  │   端点: https://api.anthropic.com                  │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**添加/编辑弹窗**:

| 字段 | 控件 | 说明 |
|------|------|------|
| 名称 | 文本输入 | 用户自定义名称 |
| 协议 | 下拉选择 | OpenAI Chat / OpenAI Response / Anthropic |
| Base URL | 文本输入 | API 端点地址 |
| API Key | 密码输入 | 编辑时显示占位符 |
| 模型 | 文本输入 | 模型标识符 |
| 设为默认 | 复选框 | 是否设为默认模型 |

**交互逻辑**:
- 星标 `★` 标记默认模型（`is_default=true`）
- 添加/编辑弹出 Modal 表单
- 删除需二次确认
- "测试连接"：对默认模型发送 "Hi"，显示成功/失败 + 延迟
- 编辑时 API Key 输入框为空，placeholder 提示 "留空则保留原值"

### 前端移除

- 移除现有 Settings 中的 MiniMax API Key 输入框（localStorage 存储方式）
- 移除 `signal_router.py` 中从 header 读取 `x-llm-api-key` 的逻辑

## 现有代码改造

### 改造清单

| 文件 | 改造内容 | 优先级 |
|------|---------|--------|
| `src/llm/client.py` | 标记 deprecated，保留向后兼容。MiniMax 作为 OpenAI Chat 兼容配置迁移 | P1 |
| `src/api/router/signal_router.py` | `get_llm_client()` → `llm_manager.get_default_provider()` | P1 |
| `src/domain/market/intel/processor.py` | 修复断裂的 LLM 导入 → `llm_manager.get_default_provider()` | P1 |
| `src/domain/market/strategy/agents/base.py` | `Agent.__init__(llm=...)` 改为接收 `LLMProvider` 接口 | P1 |
| `frontend/apps/web/src/pages/Settings.tsx` | 替换 MiniMax Key 区块为 LLM 模型配置区块 | P1 |
| `frontend/apps/web/src/pages/Settings.css` | 新增 LLM 配置相关样式 | P1 |
| `frontend/apps/web/src/pages/Market.tsx` | 移除 `x-llm-api-key` header 传递逻辑 | P2 |

### MiniMax 迁移

现有 MiniMax 配置（`MINIMAX_API_KEY` 环境变量）在首次启动时自动迁移：
- 检查 `llm_config` 表是否为空
- 如果为空且 `MINIMAX_API_KEY` 环境变量存在，自动创建一条配置：
  ```json
  {
    "name": "MiniMax",
    "provider_type": "openai_chat",
    "base_url": "https://api.minimaxi.com/v1",
    "api_key": "<from env>",
    "model": "MiniMax-M2.7",
    "is_default": true
  }
  ```

### 配置文件变更

`config.yaml` 新增:

```yaml
llm:
  encryption_key: ""   # AES 加密密钥，首次启动自动生成并回写
```

`settings.py` 新增:

```python
class LLMSettings(BaseModel):
    encryption_key: str = ""

class AppConfig(BaseModel):
    # ... existing fields ...
    llm: LLMSettings = LLMSettings()
```

## 错误处理

| 场景 | 处理方式 |
|------|---------|
| 无任何模型配置 | `get_provider()` 返回 None，调用方检查后返回 HTTP 503 + `LLM_NOT_CONFIGURED` |
| API Key 无效 | Provider 层捕获 SDK 认证异常，转为统一 `LLMProviderError` |
| 连接超时 | SDK 层 timeout（默认 30s），Manager 层捕获并返回 `TestResult(success=False)` |
| 加密密钥丢失 | 启动时检测，若无则自动生成新密钥（旧密文不可解密，需重新配置） |
| 无默认模型 | 设为默认时自动清除其他默认标记 |

## 新增依赖

```
# backend/pyproject.toml
[project]
dependencies = [
    # ... existing ...
    "anthropic>=0.40.0",       # Anthropic SDK
    "cryptography>=43.0.0",    # AES 加解密
]
# openai SDK 已有依赖，无需新增
```

## 不在范围内

- AI Chat 页面的真实 LLM 对话接入（保持关键词模板，后续迭代）
- 流式响应的前端展示（SSE/WebSocket）
- 模型用量统计和配额管理
- 多用户权限隔离（当前为单用户系统）
