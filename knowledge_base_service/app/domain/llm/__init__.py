"""LLM 领域层 - 业务相关服务."""

from app.domain.llm.service import LLMService, get_llm_service

__all__ = [
    "LLMService",
    "get_llm_service",
]
