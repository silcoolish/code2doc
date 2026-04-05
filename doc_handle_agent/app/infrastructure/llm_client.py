"""LLM客户端封装."""

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class LLMResponse:
    """LLM响应封装."""

    def __init__(
        self,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        usage: Optional[Dict] = None,
    ):
        """初始化响应.

        Args:
            content: 响应内容
            tool_calls: 工具调用列表
            usage: Token使用量
        """
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage = usage or {}

    @property
    def has_tool_calls(self) -> bool:
        """是否有工具调用."""
        return len(self.tool_calls) > 0


class BaseLLMClient(ABC):
    """LLM客户端基类."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
    ) -> LLMResponse:
        """生成文本.

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            tools: 可用工具列表

        Returns:
            LLM响应
        """
        pass


class QwenClient(BaseLLMClient):
    """通义千问LLM客户端."""

    def __init__(self):
        """初始化千问客户端."""
        settings = get_settings()
        self.api_key = settings.dashscope_api_key
        self.base_url = settings.dashscope_base_url
        self.model = settings.llm_model
        self.client = httpx.AsyncClient(timeout=120.0)

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
    ) -> LLMResponse:
        """生成文本.

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            tools: 可用工具列表

        Returns:
            LLM响应
        """
        logger.info(
            "llm_generate_start",
            model=self.model,
            prompt_length=len(prompt),
            has_system_prompt=system_prompt is not None,
            tool_count=len(tools) if tools else 0,
        )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        request_body: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        if tools:
            request_body["tools"] = tools
            request_body["tool_choice"] = "auto"

        try:
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            response.raise_for_status()

            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]

            # 提取内容
            content = message.get("content", "")

            # 提取工具调用
            tool_calls = None
            if "tool_calls" in message:
                tool_calls = message["tool_calls"]

            # 提取使用量
            usage = data.get("usage", {})

            logger.info(
                "llm_generate_success",
                model=self.model,
                content_length=len(content),
                tool_call_count=len(tool_calls) if tool_calls else 0,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            )

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                usage=usage,
            )

        except Exception as e:
            logger.error(
                "llm_generate_failed",
                model=self.model,
                error=str(e),
            )
            raise

    async def close(self):
        """关闭客户端."""
        await self.client.aclose()


class LLMClientFactory:
    """LLM客户端工厂."""

    @staticmethod
    def create(provider: Optional[str] = None) -> BaseLLMClient:
        """创建LLM客户端.

        Args:
            provider: 提供商名称，默认从配置读取

        Returns:
            LLM客户端实例
        """
        if provider is None:
            provider = get_settings().llm_provider

        if provider == "qwen":
            return QwenClient()
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
