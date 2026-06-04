"""内容生成器Agent - 负责LLM调用和工具执行."""

import json
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.infrastructure.mcp_client import MCPClient
from app.utils.agent_logger import get_agent_logger
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ContentGeneratorAgent:
    """内容生成器Agent - 处理所有LLM调用和工具交互."""

    def __init__(self, mcp_client: MCPClient, llm_client: Any = None):
        """初始化内容生成器Agent.

        在初始化时获取模型名称和上下文限制。

        Args:
            mcp_client: MCP客户端实例
            llm_client: 可选的LLM客户端，如果为None则创建默认客户端
        """
        self.mcp_client = mcp_client
        self._custom_llm_client = llm_client

        if llm_client:
            self.llm = llm_client
            self.model_name = self._get_model_name_from_client(llm_client)
            logger.info("content_generator_agent_initialized", model="custom_llm_client")
        else:
            settings = get_settings()
            base_url = settings.llm_base_url.replace(
                "/api/v1", "/compatible-mode/v1"
            )

            self.model_name = settings.llm_model
            self.llm = ChatOpenAI(
                model=settings.llm_model,
                api_key=settings.llm_api_key,
                base_url=base_url,
                temperature=0.7,
                max_retries=3,
                timeout=settings.llm_request_timeout,
            )

            logger.info(
                "content_generator_agent_initialized",
                model=settings.llm_model,
            )

        # 延迟初始化：避免在 __init__ 中进行同步网络请求阻塞事件循环
        # 真实的上下文限制通过 ainitialize() 异步获取
        self._context_limit: Optional[int] = None

        # 工具结果缓存，避免同一会话中重复查询
        self._tool_result_cache: Dict[str, str] = {}
        self._cache_hits = 0
        self._cache_misses = 0

        # 当前文档生成流程的专属 agent 日志记录器，在 generate_with_tools 中绑定
        self._agent_logger = None

    @property
    def context_limit(self) -> int:
        """获取模型上下文限制(token数).

        如果尚未异步初始化，返回基于模型名称的保守默认值。
        """
        if self._context_limit is not None:
            return self._context_limit
        return self._get_default_context_limit(self.model_name)

    @property
    def timeout(self) -> float:
        """获取LLM请求超时时间(秒)."""
        if hasattr(self.llm, "request_timeout") and self.llm.request_timeout is not None:
            return float(self.llm.request_timeout)
        return get_settings().llm_request_timeout

    async def ainitialize(self) -> None:
        """异步初始化模型上下文限制.

        应在异步环境中创建 Agent 后立即调用，以获取真实的模型上下文限制。
        如果获取失败，则回退到默认值。
        """
        try:
            self._context_limit = await self._fetch_model_context_limit()
            logger.info(
                "context_limit_initialized",
                model=self.model_name,
                context_limit=self._context_limit,
            )
        except Exception as e:
            default_limit = self._get_default_context_limit(self.model_name)
            self._context_limit = default_limit
            logger.warning(
                "context_limit_fetch_failed",
                model=self.model_name,
                default_limit=default_limit,
                error=str(e),
            )

    def _get_model_name_from_client(self, llm_client: Any) -> str:
        """从LLM客户端获取模型名称."""
        if hasattr(llm_client, "model_name"):
            return llm_client.model_name
        if hasattr(llm_client, "model"):
            return llm_client.model
        return "unknown"

    async def _fetch_model_context_limit(self) -> int:
        """异步获取模型上下文限制.

        Returns:
            上下文限制的token数量

        Raises:
            RuntimeError: 当获取失败时
        """
        import httpx

        settings = get_settings()

        # 根据模型名称判断使用哪个API
        if "qwen" in self.model_name.lower() or settings.llm_provider == "qwen":
            return await self._fetch_dashscope_context_limit()
        elif "deepseek" in self.model_name.lower() or settings.llm_provider == "deepseek":
            # DeepSeek OpenAI-compatible 接口不稳定提供模型上下文元数据，直接使用内置保守默认值
            return self._get_default_context_limit(self.model_name)
        elif "claude" in self.model_name.lower():
            return await self._fetch_anthropic_context_limit()
        elif "gpt" in self.model_name.lower() or "openai" in self.model_name.lower():
            return await self._fetch_openai_context_limit()
        else:
            raise RuntimeError(f"Unsupported model: {self.model_name}")

    async def _fetch_dashscope_context_limit(self) -> int:
        """异步从DashScope API获取上下文限制."""
        import httpx

        settings = get_settings()
        api_key = settings.llm_api_key

        if not api_key:
            raise RuntimeError("LLM API key not configured")

        url = "https://dashscope.aliyuncs.com/api/v1/models"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            models = data.get("data", [])
            for model in models:
                if model.get("name") == self.model_name or model.get("id") == self.model_name:
                    context_limit = model.get("max_context_length") or model.get("context_length")
                    if context_limit:
                        return int(context_limit)

            return self._get_default_context_limit(self.model_name)

    async def _fetch_anthropic_context_limit(self) -> int:
        """异步从Anthropic API获取上下文限制."""
        import httpx

        settings = get_settings()
        api_key = settings.llm_api_key

        if not api_key:
            raise RuntimeError("LLM API key not configured")

        url = "https://api.anthropic.com/v1/models"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            models = data.get("data", [])
            for model in models:
                if model.get("id") == self.model_name:
                    context_limit = model.get("context_window")
                    if context_limit:
                        return int(context_limit)

            return 200000  # Claude默认

    async def _fetch_openai_context_limit(self) -> int:
        """异步从OpenAI API获取上下文限制."""
        import httpx

        settings = get_settings()
        api_key = settings.llm_api_key
        base_url = settings.llm_base_url.replace("/compatible-mode/v1", "/api/v1")

        if not api_key:
            raise RuntimeError("LLM API key not configured")

        url = f"{base_url}/models"
        headers = {"Authorization": f"Bearer {api_key}"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            models = data.get("data", [])
            for model in models:
                if model.get("id") == self.model_name:
                    context_limit = model.get("context_window")
                    if context_limit:
                        return int(context_limit)

            return self._get_default_context_limit(self.model_name)

    def _get_default_context_limit(self, model_name: str) -> int:
        """获取模型的默认上下文限制.

        Args:
            model_name: 模型名称

        Returns:
            默认上下文限制的token数量
        """
        # DashScope/通义千问模型
        if "qwen-max" in model_name.lower():
            return 200000
        elif "qwen-plus" in model_name.lower():
            return 131072
        elif "qwen-turbo" in model_name.lower():
            return 8192
        elif "qwen" in model_name.lower():
            return 131072

        # DeepSeek模型
        elif "deepseek-v2" in model_name.lower() or "deepseek-v2.5" in model_name.lower():
            return 128000
        elif "deepseek" in model_name.lower():
            return 64000

        # Claude模型
        elif "claude-3-opus" in model_name.lower():
            return 200000
        elif "claude-3-sonnet" in model_name.lower():
            return 200000
        elif "claude-3-haiku" in model_name.lower():
            return 200000
        elif "claude" in model_name.lower():
            return 200000

        # OpenAI模型
        elif "gpt-4-turbo" in model_name.lower() or "gpt-4-0125" in model_name.lower():
            return 128000
        elif "gpt-4-32k" in model_name.lower():
            return 32768
        elif "gpt-4" in model_name.lower():
            return 8192
        elif "gpt-3.5-turbo-16k" in model_name.lower():
            return 16385
        elif "gpt-3.5" in model_name.lower():
            return 4096

        # 默认保守值
        else:
            logger.warning(
                "unknown_model_using_default_context_limit",
                model=model_name,
                default_limit=128000,
            )
            return 128000

    async def _load_langchain_tools(self) -> List[Any]:
        """加载MCP工具."""
        if not self.mcp_client.client:
            raise RuntimeError("MCP client not connected")
        return self.mcp_client.get_available_tools()

    def _serialize_messages(self, messages: List[Any]) -> List[Dict[str, Any]]:
        """序列化消息列表为可 JSON 序列化的格式.

        Args:
            messages: 消息列表

        Returns:
            序列化后的字典列表
        """
        serialized = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                serialized.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                serialized.append({"role": "user", "content": msg.content})
            elif isinstance(msg, ToolMessage):
                serialized.append({
                    "role": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                    "name": msg.name,
                })
            elif hasattr(msg, "content"):
                # AI 消息响应
                tool_calls = None
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    tool_calls = [
                        {
                            "id": tc.get("id", ""),
                            "name": tc.get("name", ""),
                            "args": tc.get("args", {}),
                        }
                        for tc in msg.tool_calls
                    ]
                entry: Dict[str, Any] = {"role": "assistant", "content": msg.content}
                if tool_calls:
                    entry["tool_calls"] = tool_calls
                serialized.append(entry)
            else:
                serialized.append({"role": "unknown", "content": str(msg)})
        return serialized

    async def generate_with_tools(
        self,
        system_prompt: str,
        task_message: str,
        repo_id: str,
        task_name: str = "generate",
        max_iterations: int = 10,
        excluded_tools: Optional[List[str]] = None,
        extra_tools: Optional[List[Any]] = None,
        custom_tool_handler: Optional[Any] = None,
    ) -> str:
        """使用工具生成内容.

        Args:
            system_prompt: 系统提示词
            task_message: 任务消息
            repo_id: 仓库ID
            task_name: 任务名称，用于 agent 日志文件名
            max_iterations: 最大迭代次数
            excluded_tools: 禁止 LLM 使用的工具名称列表

        Returns:
            生成的原始内容字符串
        """
        # 生成会话唯一标识并创建专属日志记录器，绑定到当前流程
        session_id = str(uuid.uuid4())
        self._agent_logger = get_agent_logger(
            repo_id=repo_id, task_name=task_name, session_id=session_id
        )

        try:
            # 记录 agent 请求开始
            self._agent_logger.log_agent_request(
                session_id=session_id,
                system_prompt=system_prompt,
                task_message=task_message,
                repo_id=repo_id,
                max_iterations=max_iterations,
            )

            tools = await self._load_langchain_tools()
            if excluded_tools:
                excluded_set = set(excluded_tools)
                tools = [
                    t for t in tools
                    if t.get("function", {}).get("name") not in excluded_set
                ]
                logger.info(
                    "tools_filtered",
                    excluded=excluded_tools,
                    remaining=len(tools),
                )
            extra_tool_names: set[str] = set()
            if extra_tools:
                extra_tool_names = {
                    t.get("function", {}).get("name")
                    for t in extra_tools
                    if t.get("function")
                }
                tools = tools + extra_tools
                logger.info(
                    "tools_extended",
                    extra_count=len(extra_tools),
                    total=len(tools),
                )
            llm_with_tools = self.llm.bind_tools(tools)

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=task_message),
            ]

            final_iteration = 0
            end_reason = "completed"

            for i in range(max_iterations):
                final_iteration = i + 1

                # 记录 LLM 调用请求
                self._agent_logger.log_llm_call(
                    session_id=session_id,
                    iteration=final_iteration,
                    messages=self._serialize_messages(messages),
                    model_name=self.model_name,
                )

                response = await llm_with_tools.ainvoke(messages)
                messages.append(response)

                # 提取响应内容
                response_content = response.content if hasattr(response, "content") else str(response)

                # 提取工具调用信息
                tool_calls_data = None
                if hasattr(response, "tool_calls") and response.tool_calls:
                    tool_calls_data = [
                        {
                            "id": tc.get("id", ""),
                            "name": tc.get("name", ""),
                            "args": tc.get("args", {}),
                        }
                        for tc in response.tool_calls
                    ]

                # 记录 LLM 响应
                self._agent_logger.log_llm_response(
                    session_id=session_id,
                    iteration=final_iteration,
                    response_content=response_content,
                    tool_calls=tool_calls_data,
                    model_name=self.model_name,
                )

                if hasattr(response, "tool_calls") and response.tool_calls:
                    for tool_call in response.tool_calls:
                        tool_name = tool_call.get("name", "")
                        tool_args = tool_call.get("args", {})

                        if "repo_id" not in tool_args:
                            tool_args["repo_id"] = repo_id

                        # 记录工具调用请求
                        self._agent_logger.log_tool_call(
                            session_id=session_id,
                            iteration=final_iteration,
                            tool_name=tool_name,
                            arguments=tool_args,
                        )

                        try:
                            is_extra_tool = tool_name in extra_tool_names
                            if is_extra_tool and custom_tool_handler is not None:
                                result = await custom_tool_handler(tool_name, tool_args)
                            else:
                                result = await self.call_tool(tool_name, tool_args)
                            self._agent_logger.log_tool_response(
                                session_id=session_id,
                                iteration=final_iteration,
                                tool_name=tool_name,
                                response=result,
                                success=True,
                            )
                        except Exception as e:
                            result = f"工具调用失败: {str(e)}"
                            self._agent_logger.log_tool_response(
                                session_id=session_id,
                                iteration=final_iteration,
                                tool_name=tool_name,
                                response=result,
                                success=False,
                                error=str(e),
                            )

                        messages.append(ToolMessage(
                            content=result,
                            tool_call_id=tool_call.get("id", ""),
                            name=tool_name,
                        ))
                else:
                    break
            else:
                # 达到最大迭代次数
                end_reason = "max_iterations_reached"

            final_response = messages[-1]
            final_content = final_response.content if hasattr(final_response, "content") else str(final_response)

            # 记录 agent 请求完成
            self._agent_logger.log_agent_completion(
                session_id=session_id,
                total_iterations=final_iteration,
                final_content=final_content,
                reason=end_reason,
            )

            return final_content
        finally:
            # 流程结束，解绑日志记录器
            self._agent_logger = None

    @staticmethod
    def _sanitize_tool_args(tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """清洗工具参数，修复 LLM 常见的格式错误.

        部分模型会把数组参数输出为字符串（如 "\\n[File, Class, Method]\\n"），
        此函数在调用工具前将其转换为正确的类型。
        """
        sanitized: Dict[str, Any] = {}
        for key, value in tool_args.items():
            if isinstance(value, str):
                stripped = value.strip()
                # 检测字符串形式的列表: "[...]"
                if stripped.startswith("[") and stripped.endswith("]"):
                    try:
                        import json
                        parsed = json.loads(stripped)
                        if isinstance(parsed, list):
                            sanitized[key] = parsed
                            continue
                    except json.JSONDecodeError:
                        # 尝试按逗号分割
                        inner = stripped[1:-1].strip()
                        if inner:
                            sanitized[key] = [item.strip().strip('"').strip("'") for item in inner.split(",")]
                            continue
                        sanitized[key] = []
                        continue
            sanitized[key] = value
        return sanitized

    @staticmethod
    def _normalize_tool_args(tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """规范化工具参数，将 LLM 扁平调用转换为服务端期望的嵌套结构.

        部分工具（如 get_related_nodes、search_nodes）服务端期望 `queries` 数组包装，
        但 LLM 按提示词习惯以扁平参数调用。此函数在发送前做结构转换。
        """
        args = dict(tool_args)

        if tool_name in ("get_related_nodes", "search_nodes"):
            if "queries" not in args:
                repo_id = args.pop("repo_id", None)
                query = {k: v for k, v in args.items()}
                args = {"repo_id": repo_id, "queries": [query]}

        elif tool_name == "get_node_dependencies":
            if "queries" not in args:
                args.pop("repo_id", None)
                query = {k: v for k, v in args.items()}
                args = {"queries": [query]}

        return args

    async def call_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """调用MCP工具（带缓存）.

        相同参数的工具调用会在同一会话中缓存结果，避免重复查询数据库。

        Args:
            tool_name: 工具名称
            tool_args: 工具参数

        Returns:
            工具调用结果
        """
        # 清洗参数，修复 LLM 常见的格式错误
        tool_args = self._sanitize_tool_args(tool_args)

        # 规范化工具参数结构
        tool_args = self._normalize_tool_args(tool_name, tool_args)

        # 构造缓存键（基于工具名和排序后的参数）
        cache_key = self._build_tool_cache_key(tool_name, tool_args)

        if cache_key in self._tool_result_cache:
            self._cache_hits += 1
            if self._agent_logger:
                self._agent_logger.log_event(
                    "tool_cache_hit",
                    tool_name=tool_name,
                    cache_hits=self._cache_hits,
                    cache_misses=self._cache_misses,
                )
            return self._tool_result_cache[cache_key]

        self._cache_misses += 1

        try:
            result = await self.mcp_client.call_tool(tool_name, tool_args)

            # 缓存结果
            self._tool_result_cache[cache_key] = result
            return result
        except Exception as e:
            error_msg = f"工具调用失败: {str(e)}"

            # 失败结果也缓存，避免重复失败请求
            self._tool_result_cache[cache_key] = error_msg
            return error_msg

    def _build_tool_cache_key(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """构建工具缓存键.

        Args:
            tool_name: 工具名称
            tool_args: 工具参数

        Returns:
            缓存键字符串
        """
        try:
            sorted_args = json.dumps(tool_args, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            sorted_args = str(tool_args)
        return f"{tool_name}:{sorted_args}"

    def clear_tool_cache(self) -> None:
        """清空工具结果缓存."""
        self._tool_result_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        logger.info("tool_cache_cleared")

    def get_cache_stats(self) -> Dict[str, int]:
        """获取缓存统计信息.

        Returns:
            缓存统计字典
        """
        total = self._cache_hits + self._cache_misses
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "total": total,
            "hit_rate": round(self._cache_hits / total, 4) if total > 0 else 0.0,
        }

