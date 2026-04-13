"""MCP客户端封装 - 使用HTTP REST API (aiohttp)."""

import asyncio
from typing import Any, Dict, List, Optional

import aiohttp

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MCPClient:
    """MCP客户端封装 - 基于HTTP REST API."""

    def __init__(self, server_url: Optional[str] = None):
        """初始化MCP客户端.

        Args:
            server_url: MCP服务器HTTP地址 (如 http://localhost:8000/mcp)
                       默认从配置读取
        """
        settings = get_settings()
        self.server_url = server_url or settings.mcp_server_url
        self._session: Optional[aiohttp.ClientSession] = None
        self._tools: List[Dict[str, Any]] = []

    async def __aenter__(self) -> "MCPClient":
        """异步上下文管理器入口."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器退出."""
        await self.disconnect()

    async def connect(self) -> "MCPClient":
        """建立MCP连接.

        Returns:
            MCPClient: 连接后的客户端实例
        """
        logger.info(
            "mcp_connect_start",
            server_url=self.server_url,
        )

        try:
            # 创建aiohttp会话（禁用代理）
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=10,
                ttl_dns_cache=300,
                use_dns_cache=True,
            )
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                trust_env=False,  # 禁用环境变量（包括代理）
            )

            # 获取工具列表
            tools_url = f"{self.server_url}/tools"
            async with self._session.get(tools_url) as response:
                response.raise_for_status()
                data = await response.json()
                self._tools = data.get("tools", [])

            logger.info(
                "mcp_connect_success",
                tool_count=len(self._tools),
                tools=[t["name"] for t in self._tools],
            )

            return self

        except Exception as e:
            logger.error(
                "mcp_connect_failed",
                error=str(e),
            )
            raise

    async def disconnect(self) -> None:
        """断开连接."""
        if self._session:
            await self._session.close()
            self._session = None
            logger.info("mcp_disconnected")

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
        if not self._session:
            raise RuntimeError("MCP client not connected")

        logger.info(
            "tool_call_start",
            tool_name=tool_name,
            arguments=arguments,
        )

        try:
            # 调用工具端点
            tool_url = f"{self.server_url}/tools/{tool_name}"
            async with self._session.post(
                tool_url,
                json=arguments,
            ) as response:
                response.raise_for_status()
                result = await response.json()

            # 处理响应
            if result.get("success"):
                text_content = str(result.get("data", ""))
            else:
                error_msg = result.get("error", "Unknown error")
                raise RuntimeError(f"Tool execution failed: {error_msg}")

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
        if not self._tools:
            logger.warning("get_available_tools called before connect")
            return []

        # 转换为OpenAI函数调用格式
        tools = []
        for tool in self._tools:
            tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool.get("parameters", {}),
                },
            })

        return tools

    @property
    def client(self) -> Optional[aiohttp.ClientSession]:
        """获取HTTP会话实例."""
        return self._session
