"""MCP HTTP API 路由."""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.infrastructure.db import get_graph_db_client, get_vector_db_client
from app.mcp.tools import KnowledgeBaseTools

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])


async def get_tools() -> KnowledgeBaseTools:
    """获取 KnowledgeBaseTools 实例."""
    graph_db = get_graph_db_client()
    vector_db = get_vector_db_client()
    return KnowledgeBaseTools(graph_db, vector_db)


# ========== 请求模型 ==========

class GetRepoStatsRequest(BaseModel):
    repo_id: str = Field(..., description="仓库ID")


class GetProjectStructureRequest(BaseModel):
    repo_id: str = Field(..., description="仓库ID")


class NodeSearchQuery(BaseModel):
    query: str = Field(..., description="搜索关键字")
    search_mode: str = Field(
        default="semantic",
        description="搜索模式: 'semantic' 语义搜索（按功能描述找代码）, 'name' 名称搜索（按确切名称找代码）",
    )
    node_types: list[str] = Field(
        default=["File", "Class", "Method"],
        description="代码节点类型列表: File, Class, Method",
    )
    top_k: int = Field(default=10, description="返回结果数量")
    fuzzy: bool = Field(default=True, description="仅 search_mode='name' 时有效，是否模糊匹配")
    returns: list[str] | None = Field(
        default=None,
        description="指定返回字段列表，如 ['node_id', 'name', 'summary']。默认返回: node_id, name, node_type, summary, file_path, distance",
    )


class SearchNodesRequest(BaseModel):
    repo_id: str = Field(..., description="仓库ID")
    queries: list[NodeSearchQuery] = Field(..., description="查询参数列表")


class RelatedNodeQuery(BaseModel):
    node_id: str = Field(..., description="节点ID")
    rel_type: str = Field(
        ...,
        description="关系类型枚举值: BELONG_TO(属于), CONTAIN(包含), CALL(调用), USE(使用)",
    )
    direction: str = Field(
        default="out",
        description="关系方向: 'out'( outgoing ), 'in'( incoming ), 'both'( 双向 )",
    )
    returns: list[str] | None = Field(
        default=None,
        description="指定返回字段列表，如 ['node_id', 'name', 'summary']。默认返回: node_id, name, node_type, summary, description",
    )


class GetRelatedNodesRequest(BaseModel):
    repo_id: str = Field(..., description="仓库ID")
    queries: list[RelatedNodeQuery] = Field(..., description="查询参数列表")


class NodeDependencyQuery(BaseModel):
    node_id: str = Field(..., description="节点ID")
    depth: int = Field(default=1, description="依赖深度")
    returns: list[str] | None = Field(
        default=None,
        description="指定返回字段列表，如 ['source', 'target', 'distance']。默认返回: source, target, relationships, distance",
    )


class GetNodeDependenciesRequest(BaseModel):
    queries: list[NodeDependencyQuery] = Field(..., description="查询参数列表")


class GetAllNodesRequest(BaseModel):
    repo_id: str = Field(..., description="仓库ID")
    node_types: list[str] = Field(
        default=["File", "Class", "Method"],
        description="节点类型列表: File, Class, Method, Module 等",
    )
    returns: list[str] | None = Field(
        default=None,
        description="指定返回字段列表，如 ['node_id', 'name', 'summary']。默认返回: node_id, name, node_type, file_path, summary",
    )


class BatchGetImageUrlsRequest(BaseModel):
    repo_id: str = Field(..., description="仓库ID")
    node_ids: list[str] = Field(..., description="节点ID列表")


class BatchGetNodeDetailsRequest(BaseModel):
    repo_id: str = Field(..., description="仓库ID")
    node_ids: list[str] = Field(..., description="节点ID列表")
    returns: list[str] | None = Field(
        default=None,
        description="指定返回字段列表，如 ['node_id', 'name', 'summary', 'code']。默认返回: node_id, name, node_type, file_path, code, summary, docstring, language, suffix",
    )


# ========== 响应模型 ==========

class ToolResponse(BaseModel):
    success: bool = Field(..., description="是否成功")
    data: Any | None = Field(default=None, description="返回数据")
    error: str | None = Field(default=None, description="错误信息")


# ========== 工具端点 ==========

@router.post("/tools/get_repo_stats", response_model=ToolResponse)
async def get_repo_stats(
    request: GetRepoStatsRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """获取仓库统计信息."""
    try:
        result = await tools.get_repo_stats(repo_id=request.repo_id)
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"get_repo_stats failed: {e}")
        return ToolResponse(success=False, error=str(e))


@router.post("/tools/get_project_structure", response_model=ToolResponse)
async def get_project_structure(
    request: GetProjectStructureRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """获取项目目录结构."""
    try:
        result = await tools.get_project_structure(repo_id=request.repo_id)
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"get_project_structure failed: {e}")
        return ToolResponse(success=False, error=str(e))


@router.post("/tools/search_nodes", response_model=ToolResponse)
async def search_nodes(
    request: SearchNodesRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """统一搜索代码节点入口（语义搜索 + 名称搜索）."""
    try:
        queries = [
            {
                "query": q.query,
                "search_mode": q.search_mode,
                "node_types": q.node_types,
                "top_k": q.top_k,
                "fuzzy": q.fuzzy,
                "returns": q.returns,
            }
            for q in request.queries
        ]
        result = await tools.search_nodes(
            repo_id=request.repo_id,
            queries=queries,
        )
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"search_nodes failed: {e}")
        return ToolResponse(success=False, error=str(e))


@router.post("/tools/get_related_nodes", response_model=ToolResponse)
async def get_related_nodes(
    request: GetRelatedNodesRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """批量获取与指定节点具有特定关系的所有节点."""
    try:
        queries = [
            {
                "node_id": q.node_id,
                "rel_type": q.rel_type,
                "direction": q.direction,
                "returns": q.returns,
            }
            for q in request.queries
        ]
        result = await tools.get_related_nodes(
            repo_id=request.repo_id,
            queries=queries,
        )
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"get_related_nodes failed: {e}")
        return ToolResponse(success=False, error=str(e))


@router.post("/tools/get_node_dependencies", response_model=ToolResponse)
async def get_node_dependencies(
    request: GetNodeDependenciesRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """批量获取节点的依赖关系图."""
    try:
        queries = [
            {
                "node_id": q.node_id,
                "depth": q.depth,
                "returns": q.returns,
            }
            for q in request.queries
        ]
        result = await tools.get_node_dependencies(queries=queries)
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"get_node_dependencies failed: {e}")
        return ToolResponse(success=False, error=str(e))


@router.post("/tools/get_all_nodes", response_model=ToolResponse)
async def get_all_nodes(
    request: GetAllNodesRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """获取仓库中所有指定类型的节点列表."""
    try:
        result = await tools.get_all_nodes(
            repo_id=request.repo_id,
            node_types=request.node_types,
            returns=request.returns,
        )
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"get_all_nodes failed: {e}")
        return ToolResponse(success=False, error=str(e))


@router.post("/tools/batch_get_image_urls", response_model=ToolResponse)
async def batch_get_image_urls(
    request: BatchGetImageUrlsRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """批量获取节点对应图片的 URL."""
    try:
        result = await tools.batch_get_image_urls(
            repo_id=request.repo_id,
            node_ids=request.node_ids,
        )
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"batch_get_image_urls failed: {e}")
        return ToolResponse(success=False, error=str(e))


@router.post("/tools/batch_get_node_details", response_model=ToolResponse)
async def batch_get_node_details(
    request: BatchGetNodeDetailsRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """批量根据节点ID获取节点详情."""
    try:
        result = await tools.batch_get_node_details(
            repo_id=request.repo_id,
            node_ids=request.node_ids,
            returns=request.returns,
        )
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"batch_get_node_details failed: {e}")
        return ToolResponse(success=False, error=str(e))


# ========== 工具列表端点 ==========

@router.get("/tools")
async def list_tools() -> dict:
    """列出可用的 MCP 工具."""
    return {
        "tools": [
            {
                "name": "get_repo_stats",
                "description": "获取仓库统计信息（规模、文件数、代码行数、语言分布等）。在制定文档生成策略、评估仓库复杂度、判断是否需要分模块处理时调用此工具。返回的 scale 字段自动判定仓库规模: small(小)/medium(中)/large(大)",
                "endpoint": "/mcp/tools/get_repo_stats",
                "method": "POST",
                "parameters": {
                    "repo_id": {"type": "string", "required": True},
                },
            },
            {
                "name": "get_project_structure",
                "description": "获取项目目录结构。用于了解仓库整体文件组织、生成项目结构概述类文档",
                "endpoint": "/mcp/tools/get_project_structure",
                "method": "POST",
                "parameters": {
                    "repo_id": {"type": "string", "required": True},
                },
            },
            {
                "name": "search_nodes",
                "description": "统一搜索节点入口（语义搜索 + 名称搜索）。支持代码节点（File/Class/Method）和语义节点（Module/Workflow）",
                "endpoint": "/mcp/tools/search_nodes",
                "method": "POST",
                "parameters": {
                    "repo_id": {"type": "string", "required": True},
                    "queries": {
                        "type": "array",
                        "required": True,
                        "items": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "required": True},
                                "search_mode": {"type": "string", "default": "semantic", "enum": ["semantic", "name"]},
                                "node_types": {"type": "array", "items": {"type": "string"}, "default": ["File", "Class", "Method"]},
                                "top_k": {"type": "integer", "default": 10},
                                "fuzzy": {"type": "boolean", "default": True},
                                "returns": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
            },
            {
                "name": "get_related_nodes",
                "description": "批量获取与指定节点具有特定关系的所有节点。通用关系查询工具，可替代获取子节点、获取模块工作流等专用操作",
                "endpoint": "/mcp/tools/get_related_nodes",
                "method": "POST",
                "parameters": {
                    "repo_id": {"type": "string", "required": True},
                    "queries": {
                        "type": "array",
                        "required": True,
                        "items": {
                            "type": "object",
                            "properties": {
                                "node_id": {"type": "string", "required": True},
                                "rel_type": {"type": "string", "required": True, "enum": ["BELONG_TO", "CONTAIN", "CALL", "USE"]},
                                "direction": {"type": "string", "default": "out", "enum": ["out", "in", "both"]},
                                "returns": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
            },
            {
                "name": "get_node_dependencies",
                "description": "批量获取节点的依赖关系图。用于生成模块间调用关系、依赖分析类文档",
                "endpoint": "/mcp/tools/get_node_dependencies",
                "method": "POST",
                "parameters": {
                    "queries": {
                        "type": "array",
                        "required": True,
                        "items": {
                            "type": "object",
                            "properties": {
                                "node_id": {"type": "string", "required": True},
                                "depth": {"type": "integer", "default": 1},
                                "returns": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
            },
            {
                "name": "get_all_nodes",
                "description": "获取仓库中所有指定类型的节点列表。用于枚举场景，如生成段落标题列表、获取完整的方法清单/类清单/模块清单",
                "endpoint": "/mcp/tools/get_all_nodes",
                "method": "POST",
                "parameters": {
                    "repo_id": {"type": "string", "required": True},
                    "node_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["File", "Class", "Method"],
                        "description": "节点类型枚举值: File(文件), Class(类), Method(方法), Module(模块), Workflow(工作流), Directory(目录)。可传入多个类型",
                    },
                    "returns": {"type": "array", "items": {"type": "string"}, "description": "可选枚举值: node_id, name, node_type, file_path, summary, language"},
                },
            },
            {
                "name": "batch_get_image_urls",
                "description": "批量获取节点对应图片的 URL。用于在文档中插入流程图、架构图",
                "endpoint": "/mcp/tools/batch_get_image_urls",
                "method": "POST",
                "parameters": {
                    "repo_id": {"type": "string", "required": True},
                    "node_ids": {"type": "array", "items": {"type": "string"}, "required": True},
                },
            },
            {
                "name": "batch_get_node_details",
                "description": "批量根据节点ID获取节点详情（代码、摘要、文档字符串等）。配合 search_nodes 或 get_all_nodes 使用",
                "endpoint": "/mcp/tools/batch_get_node_details",
                "method": "POST",
                "parameters": {
                    "repo_id": {"type": "string", "required": True},
                    "node_ids": {"type": "array", "items": {"type": "string"}, "required": True},
                    "returns": {"type": "array", "items": {"type": "string"}},
                },
            },
        ]
    }
