"""MCP客户端封装 - 使用langchain-mcp-adapters的MultiServerMCPClient."""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, List, Optional

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MCPClient:
    """MCP客户端封装 - 基于MultiServerMCPClient."""

    def __init__(self, server_url: Optional[str] = None):
        """初始化MCP客户端.

        Args:
            server_url: MCP服务器HTTP地址 (如 http://localhost:8000/sse)
                       默认从配置读取
        """
        settings = get_settings()
        self.server_url = server_url or settings.mcp_server_url
        self._client: Optional[MultiServerMCPClient] = None
        self._session: Optional[Any] = None

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator["MCPClient", None]:
        """建立MCP连接.

        Yields:
            MCPClient: 连接后的客户端实例
        """
        logger.info(
            "mcp_connect_start",
            server_url=self.server_url,
        )

        try:
            # 创建MultiServerMCPClient连接配置
            connections = {
                "knowledge_base": {
                    "url": self.server_url,
                    "transport": "http",
                }
            }

            # 初始化客户端并建立连接
            self._client = MultiServerMCPClient(connections)

            # 获取session（用于load_mcp_tools）
            async with self._client.session("knowledge_base") as session:
                self._session = session

                # 获取工具列表用于日志
                tools = await self._client.get_tools()
                logger.info(
                    "mcp_connect_success",
                    tool_count=len(tools),
                    tools=[t.name for t in tools],
                )

                yield self

                self._session = None
                self._client = None

        except Exception as e:
            logger.error(
                "mcp_connect_failed",
                error=str(e),
            )
            raise

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> str:
        """调用MCP工具.

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            工具返回的文本内容

        Raises:
            RuntimeError: 如果客户端未连接
        """
        if not self._client:
            raise RuntimeError("MCP client not connected")

        logger.info(
            "tool_call_start",
            tool_name=tool_name,
            arguments=arguments,
        )

        try:
            # 获取工具并执行
            tools = await self._client.get_tools()
            target_tool = None

            for tool in tools:
                if tool.name == tool_name:
                    target_tool = tool
                    break

            if not target_tool:
                raise ValueError(f"Tool not found: {tool_name}")

            # 执行工具调用
            result = await target_tool.ainvoke(arguments)

            # 处理结果
            if isinstance(result, str):
                text_content = result
            else:
                text_content = str(result)

            logger.info(
                "tool_call_success",
                tool_name=tool_name,
                result_length=len(text_content),
            )

            return text_content

        except Exception as e:
            logger.error(
                "tool_call_failed",
                tool_name=tool_name,
                arguments=arguments,
                error=str(e),
            )
            raise

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """获取可用工具列表 (用于LLM工具调用).

        注意：此方法需要在connect之后调用

        Returns:
            工具列表，格式符合OpenAI函数调用规范
        """
        if not self._session:
            logger.warning("get_available_tools called before connect")
            return []

        # 从session获取工具信息
        tools = []
        if hasattr(self._session, '_tools'):
            for tool in self._session._tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                })

        return tools

    @property
    def session(self) -> Optional[Any]:
        """获取当前MCP session (用于langchain-mcp-adapters)."""
        return self._session

    @property
    def client(self) -> Optional[MultiServerMCPClient]:
        """获取MultiServerMCPClient实例."""
        return self._client
