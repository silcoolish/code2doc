"""MCP 服务器实现."""

import logging
from typing import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
)

from app.config import get_settings
from app.infrastructure.db import get_graph_db_client, get_vector_db_client
from app.mcp.tools import KnowledgeBaseTools

logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(server: Server) -> AsyncIterator[KnowledgeBaseTools]:
    """MCP 应用生命周期管理."""
    # 启动时
    logger.info("Starting MCP server...")

    neo4j = get_graph_db_client()
    milvus = get_vector_db_client()

    try:
        await neo4j.connect()
        await milvus.connect()
    except Exception as e:
        logger.error(f"Failed to connect to databases: {e}")
        raise

    tools = KnowledgeBaseTools(neo4j, milvus)

    yield tools

    # 关闭时
    logger.info("Shutting down MCP server...")
    await neo4j.close()
    await milvus.close()


# 创建 MCP 服务器
mcp_server = Server(
    "knowledge-base-service",
    lifespan=app_lifespan,
)


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    """列出可用的 MCP 工具."""
    return [
        Tool(
            name="get_project_structure",
            description="获取项目目录结构",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_name": {
                        "type": "string",
                        "description": "仓库名称",
                    },
                },
                "required": ["repo_name"],
            },
        ),
        Tool(
            name="search_nodes",
            description="根据关键字语义查询节点信息",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_name": {
                        "type": "string",
                        "description": "仓库名称",
                    },
                    "query": {
                        "type": "string",
                        "description": "查询关键字",
                    },
                    "node_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "节点类型列表: File, Class, Method, Module, Workflow",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量",
                        "default": 10,
                    },
                },
                "required": ["repo_name", "query"],
            },
        ),
        Tool(
            name="get_modules",
            description="获取项目的 Module 列表",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_name": {
                        "type": "string",
                        "description": "仓库名称",
                    },
                },
                "required": ["repo_name"],
            },
        ),
        Tool(
            name="get_module_workflows",
            description="获取 Module 对应的 Workflow 列表",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_name": {
                        "type": "string",
                        "description": "仓库名称",
                    },
                    "module_id": {
                        "type": "string",
                        "description": "模块ID",
                    },
                },
                "required": ["repo_name", "module_id"],
            },
        ),
        Tool(
            name="get_node_by_id",
            description="根据节点 ID 获取节点信息",
            inputSchema={
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "节点ID",
                    },
                },
                "required": ["node_id"],
            },
        ),
        Tool(
            name="get_node_dependencies",
            description="获取节点的依赖关系图",
            inputSchema={
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "节点ID",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "依赖深度",
                        "default": 1,
                    },
                },
                "required": ["node_id"],
            },
        ),
        Tool(
            name="get_file_content",
            description="获取文件内容",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "文件ID",
                    },
                },
                "required": ["file_id"],
            },
        ),
        Tool(
            name="search_code",
            description="语义搜索代码",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_name": {
                        "type": "string",
                        "description": "仓库名称",
                    },
                    "query": {
                        "type": "string",
                        "description": "查询关键字",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量",
                        "default": 10,
                    },
                },
                "required": ["repo_name", "query"],
            },
        ),
    ]


@mcp_server.call_tool()
async def call_tool(
    name: str,
    arguments: dict,
) -> list[TextContent | ImageContent | EmbeddedResource]:
    """调用 MCP 工具."""
    from mcp.server import request_context

    # 获取 tools 实例
    tools: KnowledgeBaseTools = request_context.get().request_context.lifespan_context

    try:
        if name == "get_project_structure":
            result = await tools.get_project_structure(
                repo_name=arguments["repo_name"],
            )
            return [TextContent(type="text", text=result)]

        elif name == "search_nodes":
            result = await tools.search_nodes(
                repo_name=arguments["repo_name"],
                query=arguments["query"],
                node_types=arguments.get("node_types", ["File", "Class", "Method"]),
                top_k=arguments.get("top_k", 10),
            )
            return [TextContent(type="text", text=result)]

        elif name == "get_modules":
            result = await tools.get_modules(
                repo_name=arguments["repo_name"],
            )
            return [TextContent(type="text", text=result)]

        elif name == "get_module_workflows":
            result = await tools.get_module_workflows(
                repo_name=arguments["repo_name"],
                module_id=arguments["module_id"],
            )
            return [TextContent(type="text", text=result)]

        elif name == "get_node_by_id":
            result = await tools.get_node_by_id(
                node_id=arguments["node_id"],
            )
            return [TextContent(type="text", text=result)]

        elif name == "get_node_dependencies":
            result = await tools.get_node_dependencies(
                node_id=arguments["node_id"],
                depth=arguments.get("depth", 1),
            )
            return [TextContent(type="text", text=result)]

        elif name == "get_file_content":
            result = await tools.get_file_content(
                file_id=arguments["file_id"],
            )
            return [TextContent(type="text", text=result)]

        elif name == "search_code":
            result = await tools.search_code(
                repo_name=arguments["repo_name"],
                query=arguments["query"],
                top_k=arguments.get("top_k", 10),
            )
            return [TextContent(type="text", text=result)]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        logger.exception(f"Tool {name} failed: {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


def main():
    """MCP 服务器入口."""
    import asyncio
    from mcp.server.stdio import stdio_server

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    asyncio.run(run())


if __name__ == "__main__":
    main()
