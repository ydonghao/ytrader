# 多 LLM Provider 集成架构

**项目**: YTrader 量化交易平台
**模块**: Multi-LLM Provider Integration
**版本**: 1.0
**日期**: 2026-03-31
**状态**: 草稿

---

## 一、模块概述

多 LLM Provider 集成架构支持同时接入多个大模型提供商（OpenAI、DeepSeek、DashScope、百度千帆等），实现：
- **Provider 自由切换**：无需改代码，通过配置切换模型
- **混合调用模式**：深度思考（deep_think）和快速思考（quick_think）可使用不同 Provider
- **Token 用量追踪**：精确统计每个 Provider 的调用量和费用
- **降级容错**：Provider 不可用时自动切换到备用 Provider

---

## 二、支持的 Provider

### 2.1 Provider 矩阵

| Provider | 模型示例 | 特色 | 适用场景 |
|----------|---------|------|---------|
| OpenAI | gpt-4o, o1-preview, o4-mini | 通用能力强 | 默认主力 |
| DeepSeek | DeepSeek-V3, DeepSeek-Coder | 性价比高 | 成本敏感场景 |
| DashScope | qwen-plus, qwen-max | 阿里生态 | 国内部署 |
| Qianfan | ernie-4.0, ernie-speed | 百度生态 | 国内部署 |
| Google AI | gemini-pro, gemini-flash | 多模态 | 特殊任务 |
| Zhipu | glm-4, glm-3 | 国产基座 | 国内部署 |
| Ollama | llama3, mistral | 本地部署 | 隐私敏感 |
| SiliconFlow | 聚合多个模型 | 统一接口 | 成本优化 |

### 2.2 模型角色

| 角色 | 说明 | 推荐模型 |
|------|------|---------|
| `deep_think` | 深度推理任务（策略分析、多空辩论） | o1-preview, DeepSeek-V3, qwen-max |
| `quick_think` | 快速响应任务（摘要、情感分类） | gpt-4o-mini, DeepSeek-Coder, qwen-plus |

---

## 三、架构设计

### 3.1 Provider 工厂模式

```python
# llm_adapters/base.py
class BaseLLMAdapter(ABC):
    @abstractmethod
    async def complete(self, prompt: str, **kwargs) -> str:
        """同步补全"""

    @abstractmethod
    async def stream_complete(self, prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        """流式补全"""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @property
    def token_count(self) -> int:
        """累计 Token 用量"""
        return self._total_tokens
```

```python
# llm_adapters/factory.py
class LLMFactory:
    PROVIDERS = {
        "openai": ChatOpenAI,
        "deepseek": ChatDeepSeek,
        "dashscope": ChatDashScope,
        "qianfan": ChatQianfan,
        "google": ChatGoogle,
        "zhipu": ChatZhipu,
        "ollama": ChatOllama,
    }

    @classmethod
    def create(
        cls,
        provider: str,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs
    ) -> BaseLLMAdapter:
        if provider not in cls.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")

        adapter_class = cls.PROVIDERS[provider]
        return adapter_class(
            model=model,
            api_key=api_key,
            base_url=base_url,
            **kwargs
        )
```

### 3.2 Provider 配置持久化

存储在数据库中，支持运行时修改：

```python
# MongoDB: llm_providers collection
{
    "provider": "deepseek",
    "model": "deepseek-chat",
    "api_key": "sk-xxx",
    "base_url": "https://api.deepseek.com",
    "enabled": true,
    "is_default": true,
    "tags": ["deep_think", "quick_think"],
    "rate_limit": {
        "requests_per_minute": 60,
        "tokens_per_minute": 100000
    },
    "created_at": "2026-03-31T00:00:00Z",
    "updated_at": "2026-03-31T00:00:00Z"
}
```

### 3.3 混合调用模式

```python
class HybridLLMManager:
    """混合模式：deep_think 和 quick_think 使用不同 Provider"""

    def __init__(self, config: dict):
        self.quick_provider = self._create_provider(config["quick_provider"])
        self.deep_provider = self._create_provider(config["deep_provider"])

    async def think_deep(self, prompt: str) -> str:
        """深度思考"""
        return await self.deep_provider.complete(
            prompt,
            temperature=0.7,
            max_tokens=4096
        )

    async def think_fast(self, prompt: str) -> str:
        """快速思考"""
        return await self.quick_provider.complete(
            prompt,
            temperature=0.3,
            max_tokens=1024
        )

    async def stream_deep(self, prompt: str) -> AsyncGenerator[str, None]:
        """深度思考流式"""
        async for chunk in self.deep_provider.stream_complete(prompt):
            yield chunk
```

---

## 四、降级策略

### 4.1 降级规则

```python
class FallbackManager:
    FALLBACK_CHAINS = {
        "deep_think": [
            ("openai", "o1-preview"),
            ("openai", "gpt-4o"),
            ("deepseek", "deepseek-chat"),
            ("dashscope", "qwen-max"),
        ],
        "quick_think": [
            ("openai", "gpt-4o-mini"),
            ("deepseek", "deepseek-chat"),
            ("dashscope", "qwen-plus"),
        ]
    }

    async def complete_with_fallback(
        self,
        role: str,
        prompt: str,
        **kwargs
    ) -> str:
        errors = []

        for provider, model in self.FALLBACK_CHAINS[role]:
            try:
                adapter = LLMFactory.create(provider, model)
                result = await adapter.complete(prompt, **kwargs)
                self._record_success(provider, model)
                return result
            except Exception as e:
                errors.append(f"{provider}/{model}: {e}")
                self._record_failure(provider, model, str(e))
                continue

        raise AllProvidersFailedError(errors)
```

---

## 五、Token 用量追踪

### 5.1 统计模型

```python
# Token 使用记录
{
    "_id": ObjectId,
    "provider": "deepseek",
    "model": "deepseek-chat",
    "prompt_tokens": 1200,
    "completion_tokens": 350,
    "total_tokens": 1550,
    "cost_usd": 0.002,
    "endpoint": "chat.completions",
    "user_id": "user123",  # 多租户追踪
    "timestamp": "2026-03-31T12:00:00Z"
}
```

### 5.2 查询接口

```python
class UsageTracker:
    async def get_usage_summary(
        self,
        provider: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None
    ) -> dict:
        pipeline = [
            {"$match": {
                **({"provider": provider} if provider else {}),
                **({"timestamp": {"$gte": start_date, "$lte": end_date}} if start_date else {})
            }},
            {"$group": {
                "_id": "$provider",
                "total_tokens": {"$sum": "$total_tokens"},
                "total_cost": {"$sum": "$cost_usd"},
                "request_count": {"$sum": 1}
            }}
        ]
        return await self.db.usage_logs.aggregate(pipeline).to_list()
```

---

## 六、API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `GET /llm/providers` | GET | 列出所有 Provider |
| `POST /llm/providers` | POST | 添加 Provider |
| `PUT /llm/providers/{id}` | PUT | 更新 Provider 配置 |
| `DELETE /llm/providers/{id}` | DELETE | 删除 Provider |
| `POST /llm/providers/{id}/test` | POST | 测试 Provider 连接 |
| `GET /llm/usage` | GET | Token 用量统计 |
| `GET /llm/models` | GET | 列出可用模型 |
| `POST /llm/complete` | POST | 直接调用 LLM |
| `POST /llm/stream` | POST | 流式调用 LLM |

---

## 七、核心组件

| 组件 | 职责 |
|------|------|
| `BaseLLMAdapter` | Provider 抽象基类 |
| `LLMFactory` | Provider 工厂，创建和缓存 Adapter |
| `HybridLLMManager` | 混合模式管理器 |
| `FallbackManager` | 降级策略执行器 |
| `UsageTracker` | Token 用量和费用统计 |
| `ProviderRepository` | MongoDB Provider 配置持久化 |

---

**文档版本**: 1.0
**最后更新**: 2026-03-31
