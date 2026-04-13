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


class LLMService:
    """LLM 服务 - 统一接口封装."""

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
        # DashScope API 限制 batch size 不能超过 10
        provider_name = self.settings.embedding_provider or self.settings.llm_provider
        if provider_name.lower() == "qwen":
            batch_size = min(batch_size, 10)

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
        分析以下代码仓库结构，识别功能模块和业务流程。

        仓库结构:
        ```json
        {json.dumps(structure_json, indent=2, ensure_ascii=False)}
        ```

        请识别:
        1. 高层功能模块 (例如: "用户认证", "数据库操作", "API接口")
        2. 每个模块内的业务工作流 (例如: "用户登录流程", "数据同步流程")

        请用中文返回分析结果，JSON格式如下:
        {{
            "modules": [
                {{
                    "name": "模块名称(中文)",
                    "description": "该模块的简述(中文，50字以内)",
                    "detail": "该模块的详细说明(中文，200-500字，包含功能描述、职责、关键逻辑等)",
                    "files": ["file1.py", "file2.py"],
                    "workflows": [
                        {{
                            "name": "工作流名称(中文)",
                            "description": "该工作流的简述(中文，50字以内)",
                            "detail": "该工作流的详细说明(中文，200-500字，包含流程描述、处理步骤、关键逻辑等)",
                            "files": ["file1.py"]
                        }}
                    ]
                }}
            ]
        }}

        注意:
        - name、description、detail 字段必须使用中文
        - description 是简要描述，用于快速了解功能
        - detail 是详细说明，包含更多技术细节和实现逻辑
        """

        response = await self.complete(
            prompt=prompt,
            system_prompt="你是软件架构专家。分析代码结构并识别功能模块，所有描述必须使用中文。",
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

    def _calculate_batch_size(
        self,
        items: List[Dict[str, Any]],
        context_window: int,
    ) -> int:
        """根据代码总大小和上下文窗口计算每批节点数量.

        策略：
        1. 估算每个节点的 token 数（字符数 / 4）
        2. 每批输入 + 预留输出空间不超过上下文限制
        3. 每批最少 5 个，最多 50 个节点

        Args:
            items: 节点列表
            context_window: 当前模型的有效上下文窗口（已预留输出空间）
        """
        total_chars = sum(len(item.get("code", "")) for item in items)
        estimated_input_tokens = total_chars / 4

        # 预留输出空间（每个 summary 约 100 tokens）
        estimated_output_per_item = 100

        if estimated_input_tokens <= context_window * 0.7:  # 如果总量不大，一次处理
            return len(items)

        # 动态计算每批数量
        avg_input_tokens = estimated_input_tokens / len(items)
        # 每批 = 输入 tokens + 输出 tokens <= context_window
        batch_size = int(context_window / (avg_input_tokens + estimated_output_per_item))

        return max(5, min(batch_size, 50))  # 限制在 5-50 之间

    def _build_batch_summary_prompt(
        self,
        items: List[Dict[str, Any]],
        node_type: str = "method",
    ) -> str:
        """构建批量摘要生成提示词."""
        parts = [
            f"你是一个代码分析专家。请为以下多个 {node_type} 生成中文摘要。",
            "",
            f"对于每个代码片段，请生成 1-2 句话的中文描述，说明：",
            "- 这段代码的功能",
            "- 主要用途或目的",
            "",
            "请按以下 JSON 格式返回，确保 ID 与输入顺序一致：",
            "{\n"
            '  "summaries": [\n'
            '    {"id": "node_id_1", "summary": "摘要内容"},\n'
            '    {"id": "node_id_2", "summary": "摘要内容"},\n'
            "    ...\n"
            "  ]\n"
            "}",
            "",
        ]

        for i, item in enumerate(items, 1):
            node_id = item.get("id", "")
            code = item.get("code", "")[:3000]  # 限制代码长度
            docstring = item.get("docstring", "")
            language = item.get("language", "python")
            name = item.get("name", "")
            callee_summaries = item.get("callee_summaries", [])

            parts.append(f"=== 代码片段 {i} [ID: {node_id}] ===")
            parts.append(f"名称: {name}")
            parts.append(f"语言: {language}")

            if docstring:
                parts.append(f"文档注释: {docstring}")

            if callee_summaries:
                parts.append("调用的函数摘要:")
                for j, summary in enumerate(callee_summaries[:3], 1):
                    parts.append(f"  {j}. {summary}")

            parts.append("代码:")
            parts.append("```")
            parts.append(code)
            parts.append("```")
            parts.append("")

        parts.append("请返回 JSON 格式的摘要结果：")
        return "\n".join(parts)

    def _parse_batch_response(
        self,
        response: str,
        expected_ids: List[str],
    ) -> Dict[str, str]:
        """解析批量生成的响应.

        处理以下情况：
        1. 正常 JSON 返回
        2. JSON 格式损坏（尝试修复）
        3. 缺少某些 ID（返回空字符串）

        Args:
            response: LLM 响应内容
            expected_ids: 期望的节点 ID 列表

        Returns:
            节点 ID 到摘要的映射字典
        """
        result = {node_id: "" for node_id in expected_ids}

        # 提取 JSON 内容
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]

        try:
            data = json.loads(json_str.strip())
            summaries = data.get("summaries", [])

            for item in summaries:
                node_id = item.get("id", "")
                summary = item.get("summary", "").strip()
                if node_id in result:
                    result[node_id] = summary

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse batch response as JSON: {e}")
            # 尝试用正则提取
            import re
            pattern = r'"id"\s*:\s*"([^"]+)"\s*,\s*"summary"\s*:\s*"([^"]*)"'
            matches = re.findall(pattern, response)
            for node_id, summary in matches:
                if node_id in result:
                    result[node_id] = summary.strip()

        return result

    async def generate_summaries_batch(
        self,
        items: List[Dict[str, Any]],
        node_type: str = "method",
    ) -> List[str]:
        """批量生成代码摘要.

        使用启动时已获取的上下文窗口计算最优批次大小。

        Args:
            items: 节点列表，每个包含 id, code, docstring, name, language 等字段
            node_type: 节点类型 (method/class/file)

        Returns:
            生成的摘要列表，与 items 一一对应
        """
        if not items:
            return []

        # 获取上下文窗口（已在服务启动时初始化）
        context_window = self.get_context_window_or_default(default=100000)

        # 计算批次大小
        batch_size = self._calculate_batch_size(items, context_window)

        logger.info(
            f"Batch generating summaries for {len(items)} {node_type}s, "
            f"batch_size={batch_size}, context_window={context_window}"
        )

        results = []
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            batch_summaries = await self._generate_batch(batch, node_type)
            results.extend(batch_summaries)

        return results

    async def _generate_batch(
        self,
        items: List[Dict[str, Any]],
        node_type: str,
    ) -> List[str]:
        """生成一批节点的摘要.

        Args:
            items: 一批节点数据
            node_type: 节点类型

        Returns:
            摘要列表
        """
        if not items:
            return []

        expected_ids = [item.get("id", "") for item in items]

        try:
            prompt = self._build_batch_summary_prompt(items, node_type)

            response = await self.complete(
                prompt=prompt,
                system_prompt=(
                    "You are a code analysis expert. Generate concise, "
                    "informative summaries of code in Chinese. "
                    "Return results in valid JSON format."
                ),
                max_tokens=4096,
                temperature=0.3,
            )

            # 解析响应
            summaries_map = self._parse_batch_response(response, expected_ids)

            # 按输入顺序返回摘要
            return [summaries_map.get(node_id, "") for node_id in expected_ids]

        except Exception as e:
            logger.error(f"Failed to generate batch summaries: {e}")
            # 降级：逐个生成
            logger.info("Falling back to individual summary generation")
            results = []
            for item in items:
                try:
                    summary = await self.generate_summary(
                        code=item.get("code", ""),
                        docstring=item.get("docstring", ""),
                        callee_summaries=item.get("callee_summaries"),
                        node_type=node_type,
                        language=item.get("language", "python"),
                    )
                    results.append(summary)
                except Exception as inner_e:
                    logger.warning(f"Failed to generate summary for {item.get('id', '')}: {inner_e}")
                    results.append("")
            return results

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
