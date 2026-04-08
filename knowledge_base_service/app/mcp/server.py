"""MCP 服务器实现 - 使用 SSE 传输."""

import logging
from typing import AsyncGenerator

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.routing import Route

from app.infrastructure.db import get_graph_db_client, get_vector_db_client
from app.mcp.tools import KnowledgeBaseTools

logger = logging.getLogger(__name__)


def create_mcp_server() -> Starlette:
    """创建 MCP SSE 服务器.

    Returns:
        Starlette ASGI 应用
    """
    # 创建 MCP Server 实例
    mcp_server = Server("knowledge-base-service")

    # 创建 SSE 传输
    sse = SseServerTransport("/mcp/message")

    # 获取数据库客户端
    graph_db = get_graph_db_client()
    vector_db = get_vector_db_client()
    tools = KnowledgeBaseTools(graph_db, vector_db)

    @mcp_server.list_tools()
    async def list_tools() -> list[Tool]:
        """列出可用工具."""
        return [
            Tool(
                name="get_project_structure",
                description="获取项目目录结构",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "repo_id": {
                            "type": "string",
                            "description": "仓库ID"
                        }
                    },
                    "required": ["repo_id"]
                }
            ),
            Tool(
                name="search_nodes",
                description="根据关键字语义查询节点信息",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "repo_id": {
                            "type": "string",
                            "description": "仓库ID"
                        },
                        "query": {
                            "type": "string",
                            "description": "查询关键字"
                        },
                        "node_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "节点类型列表: File, Class, Method, Module, Workflow",
                            "default": ["File", "Class", "Method"]
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "返回结果数量",
                            "default": 10
                        }
                    },
                    "required": ["repo_id", "query"]
                }
            ),
            Tool(
                name="get_modules",
                description="获取项目的 Module 列表",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "repo_id": {
                            "type": "string",
                            "description": "仓库ID"
                        }
                    },
                    "required": ["repo_id"]
                }
            ),
            Tool(
                name="get_module_workflows",
                description="获取 Module 对应的 Workflow 列表",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "repo_id": {
                            "type": "string",
                            "description": "仓库ID"
                        },
                        "module_id": {
                            "type": "string",
                            "description": "模块ID"
                        }
                    },
                    "required": ["repo_id", "module_id"]
                }
            ),
            Tool(
                name="get_node_by_id",
                description="根据节点 ID 获取节点信息",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "node_id": {
                            "type": "string",
                            "description": "节点ID"
                        }
                    },
                    "required": ["node_id"]
                }
            ),
            Tool(
                name="get_node_dependencies",
                description="获取节点的依赖关系图",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "node_id": {
                            "type": "string",
                            "description": "节点ID"
                        },
                        "depth": {
                            "type": "integer",
                            "description": "依赖深度",
                            "default": 1
                        }
                    },
                    "required": ["node_id"]
                }
            ),
            Tool(
                name="search_code",
                description="语义搜索代码",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "repo_id": {
                            "type": "string",
                            "description": "仓库ID"
                        },
                        "query": {
                            "type": "string",
                            "description": "查询关键字"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "返回结果数量",
                            "default": 10
                        }
                    },
                    "required": ["repo_id", "query"]
                }
            ),
        ]

    @mcp_server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """调用工具."""
        logger.info(f"MCP tool called: {name} with arguments: {arguments}")

        try:
            if name == "get_project_structure":
                result = await tools.get_project_structure(arguments["repo_id"])
            elif name == "search_nodes":
                result = await tools.search_nodes(
                    repo_id=arguments["repo_id"],
                    query=arguments["query"],
                    node_types=arguments.get("node_types", ["File", "Class", "Method"]),
                    top_k=arguments.get("top_k", 10)
                )
            elif name == "get_modules":
                result = await tools.get_modules(arguments["repo_id"])
            elif name == "get_module_workflows":
                result = await tools.get_module_workflows(
                    repo_id=arguments["repo_id"],
                    module_id=arguments["module_id"]
                )
            elif name == "get_node_by_id":
                result = await tools.get_node_by_id(arguments["node_id"])
            elif name == "get_node_dependencies":
                result = await tools.get_node_dependencies(
                    node_id=arguments["node_id"],
                    depth=arguments.get("depth", 1)
                )
            elif name == "search_code":
                result = await tools.search_code(
                    repo_id=arguments["repo_id"],
                    query=arguments["query"],
                    top_k=arguments.get("top_k", 10)
                )
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            return [TextContent(type="text", text=result)]

        except Exception as e:
            logger.exception(f"Tool execution failed: {name}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    # 创建 SSE 端点处理函数
    async def handle_sse(request) -> None:
        """处理 SSE 连接."""
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp_server.run(
                streams[0], streams[1], mcp_server.create_initialization_options()
            )

    # 创建 Starlette 应用
    app = Starlette(
        debug=False,
        routes=[
            Route("/mcp/sse", endpoint=handle_sse),
            Route("/mcp/message", endpoint=sse.handle_post_message),
        ]
    )

    return app
