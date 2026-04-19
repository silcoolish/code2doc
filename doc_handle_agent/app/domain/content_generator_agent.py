"""内容生成器Agent - 负责LLM调用和工具执行."""

from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.infrastructure.mcp_client import MCPClient
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
            base_url = settings.dashscope_base_url.replace(
                "/api/v1", "/compatible-mode/v1"
            )

            self.model_name = settings.llm_model
            self.llm = ChatOpenAI(
                model=settings.llm_model,
                api_key=settings.dashscope_api_key,
                base_url=base_url,
                temperature=0.7,
                max_retries=3,
                timeout=120,
            )

            logger.info(
                "content_generator_agent_initialized",
                model=settings.llm_model,
            )

        # 初始化时获取模型上下文限制
        self._context_limit = self._init_context_limit()
        logger.info(
            "context_limit_initialized",
            model=self.model_name,
            context_limit=self._context_limit,
        )

    @property
    def context_limit(self) -> int:
        """获取模型上下文限制(token数)."""
        return self._context_limit

    def _get_model_name_from_client(self, llm_client: Any) -> str:
        """从LLM客户端获取模型名称."""
        if hasattr(llm_client, "model_name"):
            return llm_client.model_name
        if hasattr(llm_client, "model"):
            return llm_client.model
        return "unknown"

    def _init_context_limit(self) -> int:
        """初始化模型上下文限制.

        同步获取模型上下文限制，在初始化时调用。
        由于可能在异步环境中使用，这里使用同步HTTP请求。

        Returns:
            模型上下文限制的token数量
        """
        try:
            context_limit = self._fetch_model_context_limit_sync()
            logger.info(
                "context_limit_fetched",
                model=self.model_name,
                context_limit=context_limit,
            )
            return context_limit
        except Exception as e:
            default_limit = self._get_default_context_limit(self.model_name)
            logger.warning(
                "context_limit_fetch_failed",
                model=self.model_name,
                default_limit=default_limit,
                error=str(e),
            )
            return default_limit

    def _fetch_model_context_limit_sync(self) -> int:
        """同步获取模型上下文限制.

        Returns:
            上下文限制的token数量

        Raises:
            RuntimeError: 当获取失败时
        """
        import httpx

        settings = get_settings()

        # 根据模型名称判断使用哪个API
        if "qwen" in self.model_name.lower() or settings.llm_provider == "qwen":
            return self._fetch_dashscope_context_limit_sync()
        elif "claude" in self.model_name.lower():
            return self._fetch_anthropic_context_limit_sync()
        elif "gpt" in self.model_name.lower() or "openai" in self.model_name.lower():
            return self._fetch_openai_context_limit_sync()
        else:
            raise RuntimeError(f"Unsupported model: {self.model_name}")

    def _fetch_dashscope_context_limit_sync(self) -> int:
        """同步从DashScope API获取上下文限制."""
        import httpx

        settings = get_settings()
        api_key = settings.dashscope_api_key

        if not api_key:
            raise RuntimeError("DashScope API key not configured")

        url = "https://dashscope.aliyuncs.com/api/v1/models"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            models = data.get("data", [])
            for model in models:
                if model.get("name") == self.model_name or model.get("id") == self.model_name:
                    context_limit = model.get("max_context_length") or model.get("context_length")
                    if context_limit:
                        return int(context_limit)

            # 找不到具体模型，返回默认值
            return self._get_default_context_limit(self.model_name)

    def _fetch_anthropic_context_limit_sync(self) -> int:
        """同步从Anthropic API获取上下文限制."""
        import httpx

        settings = get_settings()
        api_key = getattr(settings, "anthropic_api_key", None)

        if not api_key:
            raise RuntimeError("Anthropic API key not configured")

        url = "https://api.anthropic.com/v1/models"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            models = data.get("data", [])
            for model in models:
                if model.get("id") == self.model_name:
                    context_limit = model.get("context_window")
                    if context_limit:
                        return int(context_limit)

            return 200000  # Claude默认

    def _fetch_openai_context_limit_sync(self) -> int:
        """同步从OpenAI API获取上下文限制."""
        import httpx

        settings = get_settings()
        api_key = getattr(settings, "openai_api_key", None)
        base_url = getattr(settings, "openai_base_url", "https://api.openai.com/v1")

        if not api_key:
            raise RuntimeError("OpenAI API key not configured")

        url = f"{base_url}/models"
        headers = {"Authorization": f"Bearer {api_key}"}

        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=headers)
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

    async def generate_with_tools(
        self,
        system_prompt: str,
        task_message: str,
        repo_id: str,
        max_iterations: int = 10,
    ) -> str:
        """使用工具生成内容.

        Args:
            system_prompt: 系统提示词
            task_message: 任务消息
            repo_id: 仓库ID
            max_iterations: 最大迭代次数

        Returns:
            生成的原始内容字符串
        """
        tools = await self._load_langchain_tools()
        llm_with_tools = self.llm.bind_tools(tools)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=task_message),
        ]

        for i in range(max_iterations):
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)

            if hasattr(response, "tool_calls") and response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})

                    if "repo_id" not in tool_args:
                        tool_args["repo_id"] = repo_id

                    try:
                        result = await self.mcp_client.call_tool(tool_name, tool_args)
                        if len(result) > 2000:
                            result = result[:2000] + "\n... (内容已截断)"
                    except Exception as e:
                        result = f"工具调用失败: {str(e)}"

                    messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_call.get("id", ""),
                        name=tool_name,
                    ))
            else:
                break

        final_response = messages[-1]
        return final_response.content if hasattr(final_response, "content") else str(final_response)

    async def call_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """调用MCP工具.

        Args:
            tool_name: 工具名称
            tool_args: 工具参数

        Returns:
            工具调用结果
        """
        try:
            result = await self.mcp_client.call_tool(tool_name, tool_args)
            if len(result) > 2000:
                result = result[:2000] + "\n... (内容已截断)"
            return result
        except Exception as e:
            return f"工具调用失败: {str(e)}"

    async def search_code_nodes(
        self,
        repo_id: str,
        query: str,
        node_types: List[str],
        top_k: int = 5,
    ) -> str:
        """搜索代码节点.

        Args:
            repo_id: 仓库ID
            query: 搜索查询
            node_types: 节点类型列表
            top_k: 返回结果数量

        Returns:
            搜索结果JSON字符串
        """
        return await self.call_tool(
            "search_code_nodes",
            {
                "repo_id": repo_id,
                "queries": [
                    {"query": query, "node_types": node_types, "top_k": top_k}
                ]
            }
        )

    async def batch_download_flowcharts(self, method_ids: List[str]) -> str:
        """批量下载流程图.

        Args:
            method_ids: 方法ID列表

        Returns:
            下载结果JSON字符串
        """
        return await self.call_tool(
            "batch_download_flowcharts",
            {"method_ids": method_ids}
        )
