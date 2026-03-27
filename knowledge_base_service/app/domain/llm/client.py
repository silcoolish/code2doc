"""LLM 客户端封装 - 基于 LangChain."""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """LLM 提供商抽象基类."""

    @abstractmethod
    def get_chat_model(self) -> BaseChatModel:
        """获取聊天模型实例."""
        raise NotImplementedError

    @abstractmethod
    def get_embedding_model(self) -> Embeddings:
        """获取嵌入模型实例."""
        raise NotImplementedError


class QwenProvider(LLMProvider):
    """通义千问/Qwen 提供商 (通过 DashScope)."""

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


class OpenAIProvider(LLMProvider):
    """OpenAI 提供商."""

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


class AnthropicProvider(LLMProvider):
    """Anthropic Claude 提供商."""

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


class LLMService:
    """LLM 服务 - 统一接口封装."""

    def __init__(self):
        self.settings = get_settings()
        self._llm_provider: Optional[LLMProvider] = None
        self._embedding_provider: Optional[LLMProvider] = None

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

    async def generate_summary(
        self,
        code: str,
        docstring: str = "",
        callee_summaries: Optional[List[str]] = None,
        node_type: str = "method",
        language: str = "python",
    ) -> str:
        """生成代码摘要.

        Args:
            code: 代码片段
            docstring: 文档字符串
            callee_summaries: 被调用者的摘要（用于方法）
            node_type: 节点类型
            language: 编程语言

        Returns:
            生成的摘要
        """
        prompt = self._build_summary_prompt(
            code=code,
            docstring=docstring,
            callee_summaries=callee_summaries,
            node_type=node_type,
            language=language,
        )

        summary = await self.complete(
            prompt=prompt,
            system_prompt="You are a code analysis expert. Generate concise, informative summaries of code.",
            max_tokens=1024,
            temperature=0.3,
        )

        return summary.strip()

    async def generate_embeddings(
        self,
        texts: List[str],
        batch_size: int = 100,
    ) -> List[List[float]]:
        """批量生成嵌入向量.

        Args:
            texts: 文本列表
            batch_size: 批处理大小

        Returns:
            嵌入向量列表
        """
        results = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            # 重试逻辑
            for attempt in range(self.settings.max_retries):
                try:
                    embeddings = await self.embed(batch)
                    results.extend(embeddings)
                    break
                except Exception as e:
                    if attempt == self.settings.max_retries - 1:
                        raise
                    wait_time = (2 ** attempt) * self.settings.retry_delay
                    logger.warning(f"Embedding failed, retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)

        return results

    async def detect_modules(
        self,
        structure_json: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """检测功能模块.

        Args:
            structure_json: 代码结构 JSON

        Returns:
            模块列表
        """
        prompt = f"""
        Analyze the following code repository structure and identify functional modules and workflows.

        Repository Structure:
        ```json
        {json.dumps(structure_json, indent=2, ensure_ascii=False)}
        ```

        Please identify:
        1. High-level functional modules (e.g., "Authentication", "Database", "API")
        2. Business workflows within each module (e.g., "User Login", "Data Sync")

        Return your analysis in JSON format:
        {{
            "modules": [
                {{
                    "name": "Module Name",
                    "description": "What this module does",
                    "files": ["file1.py", "file2.py"],
                    "workflows": [
                        {{
                            "name": "Workflow Name",
                            "description": "What this workflow does",
                            "files": ["file1.py"]
                        }}
                    ]
                }}
            ]
        }}
        """

        response = await self.complete(
            prompt=prompt,
            system_prompt="You are a software architecture expert. Analyze code structure and identify modules.",
            max_tokens=4096,
            temperature=0.2,
        )

        # 解析 JSON 响应
        try:
            # 尝试提取 JSON
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            else:
                json_str = response

            result = json.loads(json_str.strip())
            return result.get("modules", [])
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse module detection response: {e}")
            return []

    def _build_summary_prompt(
        self,
        code: str,
        docstring: str = "",
        callee_summaries: Optional[List[str]] = None,
        node_type: str = "method",
        language: str = "python",
    ) -> str:
        """构建摘要生成提示词."""
        parts = [
            f"请为以下 {language} {node_type} 生成中文摘要。",
            "",
            "代码:",
            "```",
            code[:3000],  # 限制代码长度
            "```",
        ]

        if docstring:
            parts.extend([
                "",
                "文档注释:",
                docstring,
            ])

        if callee_summaries:
            parts.extend([
                "",
                "此代码调用了以下函数（及其摘要）:",
            ])
            for i, summary in enumerate(callee_summaries[:5], 1):  # 限制数量
                parts.append(f"{i}. {summary}")

        parts.extend([
            "",
            "请用 1-2 句话的中文描述以下内容:",
            "- 这段代码的功能",
            "- 主要用途或目的",
            "",
            "摘要（中文）:",
        ])

        return "\n".join(parts)


# 全局服务实例
_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """获取 LLM 服务实例."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
