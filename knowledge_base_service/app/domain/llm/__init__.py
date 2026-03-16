"""LLM 处理模块.

基于 LangChain 的统一 LLM 接口，支持多种提供商：
- Qwen (通义千问) - 默认
- OpenAI
- Anthropic (Claude)

示例:
    >>> from app.domain.llm import get_llm_service
    >>> service = get_llm_service()
    >>> summary = await service.generate_summary(code="def foo(): pass")
"""

from app.domain.llm.client import (
    LLMProvider,
    QwenProvider,
    OpenAIProvider,
    AnthropicProvider,
    ProviderFactory,
    LLMService,
    get_llm_service,
)

__all__ = [
    "LLMProvider",
    "QwenProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "ProviderFactory",
    "LLMService",
    "get_llm_service",
]
