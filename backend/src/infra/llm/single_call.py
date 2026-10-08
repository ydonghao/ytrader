"""共享的单轮 LLM 调用（带推理模型兜底重试）。

2026-10 从 argument_handler 抽出：论证库与年报 MD&A 承诺抽取共用。
推理模型（GLM 系）偶发把全文写进思维链、正文只吐 "#"（finish 仍
stop）——正文过短自动重试，第二次尝试携带 enable_thinking=false
（部分网关支持，不支持则忽略）。
"""
from __future__ import annotations

from typing import Optional


async def complete_with_retry(
    prompt: str, *,
    max_tokens: int = 8000,
    min_chars: int = 50,
    temperature: float = 0.3,
    attempts: int = 3,
) -> tuple[str, Optional[str]]:
    """返回 (content, model)。provider 缺位退化旧 MiniMax 客户端
    （需 MINIMAX_API_KEY）；两路都不可用抛 RuntimeError。"""
    from src.infra.database.llm.repository import create_llm_repository
    from src.infra.llm.manager import LLMManager

    manager = LLMManager(create_llm_repository())
    provider = manager.get_provider()
    if provider is None:
        return await _legacy_complete(prompt, max_tokens=max_tokens)
    result = None
    for attempt in range(attempts):
        # 逐次加码：推理模型的思维链与正文共享预算，正文被截短时
        # 提高预算比原样重试更有效（实测 6000 预算下正文只剩 '{"'）
        budget = max_tokens if attempt == 0 else max_tokens * (2 * attempt)
        kwargs = {"temperature": temperature, "max_tokens": budget}
        if attempt == 1:
            kwargs["extra_body"] = {"enable_thinking": False}
        try:
            result = await provider.complete(prompt, **kwargs)
        except Exception:  # noqa: BLE001  网关不认 enable_thinking 等
            if attempt == 1:
                continue
            raise
        content = (result.content or "").strip()
        if len(content) >= min_chars:
            return result.content, getattr(result, "model", None)
    return ((result.content if result else ""),
            getattr(result, "model", None) if result else None)


async def _legacy_complete(prompt: str, *, max_tokens: int) \
        -> tuple[str, Optional[str]]:
    import asyncio
    import os

    if not os.environ.get("MINIMAX_API_KEY"):
        raise RuntimeError(
            "LLM provider not configured（设置页配置默认模型，"
            "或设 MINIMAX_API_KEY 走旧客户端）")
    from src.llm.client import get_llm_client

    content = await asyncio.to_thread(
        lambda: get_llm_client().chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=max_tokens))
    return content, "minimax-legacy"
