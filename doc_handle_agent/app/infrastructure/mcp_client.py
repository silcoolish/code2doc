"""MCP客户端封装."""

import json
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import TextContent

from app.utils.logger import get_logger

logger = get_logger(__name__)


class MCPClient:
    """MCP客户端封装."""

    def __init__(self, server_url: str):
        """初始化MCP客户端.

        Args:
            server_url: MCP服务器HTTP地址 (如 http://localhost:8000/sse)
        """
        self.server_url = server_url
        self.session: Optional[ClientSession] = None
        self._tools: List[Dict[str, Any]] = []

    @asynccontextmanager
    async def connect(self):
        """建立MCP连接.

        Yields:
            MCPClient: 连接后的客户端实例
        """
        logger.info(
            "mcp_connect_start",
            server_url=self.server_url,
        )

        try:
            async with sse_client(self.server_url) as (read, write):
                async with ClientSession(read, write) as session:
                    self.session = session
                    await session.initialize()
                    self._tools = await session.list_tools()

                    logger.info(
                        "mcp_connect_success",
                        tool_count=len(self._tools),
                    )

                    yield self

                    self.session = None
                    self._tools = []
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
        if not self.session:
            raise RuntimeError("MCP client not connected")

        logger.info(
            "tool_call_start",
            tool_name=tool_name,
            arguments=arguments,
        )

        try:
            result = await self.session.call_tool(tool_name, arguments)

            # 提取文本内容
            text_content = ""
            for content in result.content:
                if isinstance(content, TextContent):
                    text_content += content.text

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

        Returns:
            工具列表，格式符合OpenAI函数调用规范
        """
        tools = []
        for tool in self._tools:
            tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                },
            })
        return tools

    # ========== 便捷工具方法 ==========

    async def get_project_structure(self, repo_id: str) -> Dict[str, Any]:
        """获取项目目录结构.

        Args:
            repo_id: 仓库ID

        Returns:
            项目结构JSON
        """
        result = await self.call_tool(
            "get_project_structure",
            {"repo_id": repo_id},
        )
        return json.loads(result)

    async def search_nodes(
        self,
        repo_id: str,
        query: str,
        node_types: List[str],
        top_k: int = 10,
    ) -> Dict[str, Any]:
        """根据关键字语义查询节点.

        Args:
            repo_id: 仓库ID
            query: 查询关键字
            node_types: 节点类型列表
            top_k: 返回结果数量

        Returns:
            搜索结果JSON
        """
        result = await self.call_tool(
            "search_nodes",
            {
                "repo_id": repo_id,
                "query": query,
                "node_types": node_types,
                "top_k": top_k,
            },
        )
        return json.loads(result)

    async def get_modules(self, repo_id: str) -> Dict[str, Any]:
        """获取项目的模块列表.

        Args:
            repo_id: 仓库ID

        Returns:
            模块列表JSON
        """
        result = await self.call_tool(
            "get_modules",
            {"repo_id": repo_id},
        )
        return json.loads(result)

    async def get_module_workflows(
        self,
        repo_id: str,
        module_id: str,
    ) -> Dict[str, Any]:
        """获取模块对应的Workflow列表.

        Args:
            repo_id: 仓库ID
            module_id: 模块ID

        Returns:
            Workflow列表JSON
        """
        result = await self.call_tool(
            "get_module_workflows",
            {"repo_id": repo_id, "module_id": module_id},
        )
        return json.loads(result)

    async def get_node_by_id(self, node_id: str) -> Dict[str, Any]:
        """根据节点ID获取节点信息.

        Args:
            node_id: 节点ID

        Returns:
            节点信息JSON
        """
        result = await self.call_tool(
            "get_node_by_id",
            {"node_id": node_id},
        )
        return json.loads(result)

    async def get_node_dependencies(
        self,
        node_id: str,
        depth: int = 1,
    ) -> Dict[str, Any]:
        """获取节点的依赖关系图.

        Args:
            node_id: 节点ID
            depth: 依赖深度

        Returns:
            依赖关系JSON
        """
        result = await self.call_tool(
            "get_node_dependencies",
            {"node_id": node_id, "depth": depth},
        )
        return json.loads(result)

    async def get_file_content(self, file_id: str) -> Dict[str, Any]:
        """获取文件内容.

        Args:
            file_id: 文件ID

        Returns:
            文件内容JSON
        """
        result = await self.call_tool(
            "get_file_content",
            {"file_id": file_id},
        )
        return json.loads(result)

    async def search_code(
        self,
        repo_id: str,
        query: str,
        top_k: int = 10,
    ) -> Dict[str, Any]:
        """语义搜索代码.

        Args:
            repo_id: 仓库ID
            query: 查询关键字
            top_k: 返回结果数量

        Returns:
            搜索结果JSON
        """
        result = await self.call_tool(
            "search_code",
            {"repo_id": repo_id, "query": query, "top_k": top_k},
        )
        return json.loads(result)
