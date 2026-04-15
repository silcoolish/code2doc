"""LLM 客户端封装 - 基于 LangChain.

该模块包含与业务无关的底层 LLM 连接和基础操作。
业务相关方法应放在 domain/llm/service.py 中的 LLMService。
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """LLM 提供商抽象基类."""

    # 内置的模型上下文窗口映射表（作为 API 查询失败的 fallback）
    CONTEXT_WINDOW_MAP: Dict[str, int] = {}

    @abstractmethod
    def get_chat_model(self) -> BaseChatModel:
        """获取聊天模型实例."""
        raise NotImplementedError

    @abstractmethod
    def get_embedding_model(self) -> Embeddings:
        """获取嵌入模型实例."""
        raise NotImplementedError

    @abstractmethod
    async def get_context_window(self) -> int:
        """获取当前模型的上下文窗口大小.

        Returns:
            上下文窗口的 token 数量
        """
        raise NotImplementedError

    def _get_fallback_context_window(self, model_name: str) -> int:
        """从内置映射表获取上下文窗口（fallback）.

        Args:
            model_name: 模型名称

        Returns:
            上下文窗口大小，默认 128K
        """
        return self.CONTEXT_WINDOW_MAP.get(model_name, 128000)


class QwenProvider(LLMProvider):
    """通义千问/Qwen 提供商 (通过 DashScope)."""

    # Qwen 模型上下文窗口映射（备用）
    CONTEXT_WINDOW_MAP = {
        "qwen3.5-turbo": 128000,
        "qwen3.5-plus": 128000,
        "qwen3.5-max": 128000,
        "qwen2.5-72b-instruct": 131072,
        "qwen2.5-14b-instruct": 131072,
        "qwen2.5-7b-instruct": 131072,
        "qwen-long": 10000000,  # 1千万 tokens
    }

    def __init__(self):
        self.settings = get_settings()
        self._chat_model: Optional[BaseChatModel] = None
        self._embedding_model: Optional[Embeddings] = None

    def _create_chat_model(self) -> BaseChatModel:
        """创建 Qwen 聊天模型."""
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(
                "langchain-openai is required for Qwen provider. "
                "Install it with: pip install langchain-openai"
            )

        if not self.settings.dashscope_api_key:
            raise ValueError("DASHSCOPE_API_KEY is required for Qwen provider")

        return ChatOpenAI(
            model=self.settings.qwen_model,
            api_key=self.settings.dashscope_api_key,
            base_url=self.settings.qwen_base_url,
            temperature=0.3,
            max_tokens=4096,
        )

    def _create_embedding_model(self) -> Embeddings:
        """创建 Qwen 嵌入模型."""
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError:
            raise ImportError(
                "langchain-openai is required for Qwen provider. "
                "Install it with: pip install langchain-openai"
            )

        if not self.settings.dashscope_api_key:
            raise ValueError("DASHSCOPE_API_KEY is required for Qwen provider")

        return OpenAIEmbeddings(
            model=self.settings.qwen_embedding_model,
            api_key=self.settings.dashscope_api_key,
            base_url=self.settings.qwen_base_url,
            # Note: DashScope 需要禁用 token 长度检查，否则会以 token 列表格式发送
            check_embedding_ctx_length=False,
        )

    def get_chat_model(self) -> BaseChatModel:
        """获取聊天模型实例（懒加载）."""
        if self._chat_model is None:
            self._chat_model = self._create_chat_model()
        return self._chat_model

    def get_embedding_model(self) -> Embeddings:
        """获取嵌入模型实例（懒加载）."""
        if self._embedding_model is None:
            self._embedding_model = self._create_embedding_model()
        return self._embedding_model

    async def get_context_window(self) -> int:
        """获取 Qwen 模型的上下文窗口.

        DashScope 兼容 OpenAI 接口，尝试调用 models.retrieve()，
        失败时使用内置映射表。
        """
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=self.settings.dashscope_api_key,
                base_url=self.settings.qwen_base_url,
            )

            model_id = self.settings.qwen_model

            # 尝试获取模型信息
            try:
                model_info = await client.models.retrieve(model_id)
                # 如果 API 返回 context_window 字段
                if hasattr(model_info, 'context_window') and model_info.context_window:
                    return model_info.context_window
            except Exception:
                pass  # 兼容模式可能不支持，使用 fallback

            # 使用内置映射表
            return self._get_fallback_context_window(model_id)

        except Exception as e:
            logger.warning(f"Failed to get context window for Qwen: {e}")
            return self._get_fallback_context_window(self.settings.qwen_model)


class OpenAIProvider(LLMProvider):
    """OpenAI 提供商."""

    # OpenAI 模型上下文窗口映射（备用）
    CONTEXT_WINDOW_MAP = {
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-4-turbo": 128000,
        "gpt-4": 8192,
        "gpt-3.5-turbo": 16385,
        "gpt-3.5-turbo-16k": 16385,
    }

    def __init__(self):
        self.settings = get_settings()
        self._chat_model: Optional[BaseChatModel] = None
        self._embedding_model: Optional[Embeddings] = None

    def _create_chat_model(self) -> BaseChatModel:
        """创建 OpenAI 聊天模型."""
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(
                "langchain-openai is required for OpenAI provider. "
                "Install it with: pip install langchain-openai"
            )

        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI provider")

        return ChatOpenAI(
            model=self.settings.openai_model,
            api_key=self.settings.openai_api_key,
            temperature=0.3,
            max_tokens=4096,
        )

    def _create_embedding_model(self) -> Embeddings:
        """创建 OpenAI 嵌入模型."""
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError:
            raise ImportError(
                "langchain-openai is required for OpenAI provider. "
                "Install it with: pip install langchain-openai"
            )

        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI provider")

        return OpenAIEmbeddings(
            model=self.settings.openai_embedding_model,
            api_key=self.settings.openai_api_key,
            dimensions=self.settings.embedding_dimensions,
        )

    def get_chat_model(self) -> BaseChatModel:
        """获取聊天模型实例（懒加载）."""
        if self._chat_model is None:
            self._chat_model = self._create_chat_model()
        return self._chat_model

    def get_embedding_model(self) -> Embeddings:
        """获取嵌入模型实例（懒加载）."""
        if self._embedding_model is None:
            self._embedding_model = self._create_embedding_model()
        return self._embedding_model

    async def get_context_window(self) -> int:
        """获取 OpenAI 模型的上下文窗口."""
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self.settings.openai_api_key)
            model_id = self.settings.openai_model

            # 尝试从 API 获取
            try:
                model_info = await client.models.retrieve(model_id)
                if hasattr(model_info, 'context_window') and model_info.context_window:
                    return model_info.context_window
            except Exception:
                pass

            return self._get_fallback_context_window(model_id)

        except Exception as e:
            logger.warning(f"Failed to get context window for OpenAI: {e}")
            return self._get_fallback_context_window(self.settings.openai_model)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude 提供商."""

    # Claude 模型上下文窗口映射（备用）
    CONTEXT_WINDOW_MAP = {
        "claude-opus-4-6": 200000,
        "claude-sonnet-4-6": 200000,
        "claude-haiku-4-5": 200000,
        "claude-3-opus-20240229": 200000,
        "claude-3-sonnet-20240229": 200000,
        "claude-3-haiku-20240307": 200000,
    }

    def __init__(self):
        self.settings = get_settings()
        self._chat_model: Optional[BaseChatModel] = None

    def _create_chat_model(self) -> BaseChatModel:
        """创建 Claude 聊天模型."""
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError(
                "langchain-anthropic is required for Anthropic provider. "
                "Install it with: pip install langchain-anthropic"
            )

        if not self.settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for Anthropic provider")

        return ChatAnthropic(
            model=self.settings.anthropic_model,
            api_key=self.settings.anthropic_api_key,
            temperature=0.3,
            max_tokens=4096,
        )

    def get_chat_model(self) -> BaseChatModel:
        """获取聊天模型实例（懒加载）."""
        if self._chat_model is None:
            self._chat_model = self._create_chat_model()
        return self._chat_model

    def get_embedding_model(self) -> Embeddings:
        """Anthropic 不提供嵌入模型，需要配合其他提供商使用."""
        raise NotImplementedError(
            "Anthropic does not provide embedding models. "
            "Please use 'openai' or 'qwen' as the embedding_provider."
        )

    async def get_context_window(self) -> int:
        """获取 Claude 模型的上下文窗口."""
        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=self.settings.anthropic_api_key)
            model_id = self.settings.anthropic_model

            # Anthropic 提供 models API (beta)
            try:
                model_info = await client.models.retrieve(model_id)
                if hasattr(model_info, 'context_window') and model_info.context_window:
                    return model_info.context_window
            except Exception:
                pass

            return self._get_fallback_context_window(model_id)

        except Exception as e:
            logger.warning(f"Failed to get context window for Anthropic: {e}")
            return self._get_fallback_context_window(self.settings.anthropic_model)


class ProviderFactory:
    """LLM 提供商工厂类."""

    _providers: Dict[str, type] = {
        "qwen": QwenProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
    }

    @classmethod
    def create(cls, provider_name: str) -> LLMProvider:
        """创建提供商实例.

        Args:
            provider_name: 提供商名称

        Returns:
            LLMProvider 实例

        Raises:
            ValueError: 如果提供商不存在
        """
        provider_name = provider_name.lower()
        if provider_name not in cls._providers:
            available = ", ".join(cls._providers.keys())
            raise ValueError(
                f"Unknown provider: {provider_name}. "
                f"Available providers: {available}"
            )
        return cls._providers[provider_name]()

    @classmethod
    def register(cls, name: str, provider_class: type):
        """注册新的提供商.

        Args:
            name: 提供商名称
            provider_class: 提供商类
        """
        cls._providers[name.lower()] = provider_class


class LLMClient:
    """LLM 客户端 - 提供底层 LLM 操作的统一接口."""

    def __init__(self):
        self.settings = get_settings()
        self._llm_provider: Optional[LLMProvider] = None
        self._embedding_provider: Optional[LLMProvider] = None
        self._context_window: Optional[int] = None  # 缓存上下文窗口大小

    async def initialize_context_window(self) -> int:
        """初始化上下文窗口大小（服务启动时调用）.

        尝试从 API 获取，失败则使用配置默认值。

        Returns:
            有效的上下文窗口大小
        """
        try:
            provider = self._get_llm_provider()
            context_window = await provider.get_context_window()
            logger.info(f"Successfully detected context window from API: {context_window}")
        except Exception as e:
            # API 获取失败，使用配置默认值
            context_window = self.settings.llm_context_window
            logger.warning(
                f"Failed to get context window from API: {e}. "
                f"Using default value from config: {context_window}"
            )

        # 预留空间给输出和系统提示词（10% 或至少 8192 tokens）
        reserved = max(int(context_window * 0.1), 8192)
        effective_window = context_window - reserved

        self._context_window = effective_window
        logger.info(
            f"Effective context window: {effective_window} "
            f"(raw: {context_window}, reserved: {reserved})"
        )

        return effective_window

    def get_context_window(self) -> int:
        """获取当前缓存的上下文窗口大小.

        必须在 initialize_context_window() 之后调用。

        Returns:
            有效的上下文窗口大小

        Raises:
            RuntimeError: 如果上下文窗口尚未初始化
        """
        if self._context_window is None:
            raise RuntimeError(
                "Context window not initialized. "
                "Call initialize_context_window() during service startup."
            )
        return self._context_window

    def get_context_window_or_default(self, default: int = 100000) -> int:
        """获取上下文窗口，如未初始化则返回默认值.

        Args:
            default: 未初始化时的默认值

        Returns:
            上下文窗口大小或默认值
        """
        return self._context_window if self._context_window is not None else default

    def _get_llm_provider(self) -> LLMProvider:
        """获取 LLM 提供商."""
        if self._llm_provider is None:
            self._llm_provider = ProviderFactory.create(self.settings.llm_provider)
        return self._llm_provider

    def _get_embedding_provider(self) -> LLMProvider:
        """获取嵌入模型提供商."""
        if self._embedding_provider is None:
            # 嵌入提供商可以独立配置
            embedding_provider = self.settings.embedding_provider or self.settings.llm_provider
            self._embedding_provider = ProviderFactory.create(embedding_provider)
        return self._embedding_provider

    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        """执行文本补全.

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            max_tokens: 最大生成 token 数
            temperature: 温度参数

        Returns:
            生成的文本
        """
        try:
            provider = self._get_llm_provider()
            chat_model = provider.get_chat_model()

            # 构建消息列表
            messages = []
            if system_prompt:
                messages.append(SystemMessage(content=system_prompt))
            messages.append(HumanMessage(content=prompt))

            # 调用模型（在异步上下文中运行同步方法）
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: chat_model.invoke(
                    messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ),
            )

            return response.content or ""

        except Exception as e:
            logger.error(f"LLM completion error: {e}")
            raise

    async def embed(
        self,
        texts: List[str],
        model: Optional[str] = None,
    ) -> List[List[float]]:
        """生成文本嵌入向量.

        Args:
            texts: 文本列表
            model: 嵌入模型名称（可选，由提供商决定）

        Returns:
            嵌入向量列表
        """
        try:
            # 过滤空文本并验证类型
            valid_texts = []
            for i, t in enumerate(texts):
                if not isinstance(t, str):
                    logger.warning(f"Skipping non-string text at index {i}: type={type(t)}, value={t!r}")
                    continue
                stripped = t.strip()
                if stripped:
                    valid_texts.append(stripped)

            if not valid_texts:
                logger.warning("No valid texts for embedding after filtering")
                return []

            logger.debug(f"Generating embeddings for {len(valid_texts)} texts")

            provider = self._get_embedding_provider()
            embedding_model = provider.get_embedding_model()

            # 调用嵌入模型（在异步上下文中运行同步方法）
            embeddings = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: embedding_model.embed_documents(valid_texts),
            )

            return embeddings

        except Exception as e:
            logger.error(f"Embedding error: {e}")
            raise
