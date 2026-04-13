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

class GetProjectStructureRequest(BaseModel):
    repo_id: str = Field(..., description="仓库ID")


class SearchCodeNodesRequest(BaseModel):
    repo_id: str = Field(..., description="仓库ID")
    query: str = Field(..., description="查询关键字")
    node_types: list[str] = Field(
        default=["File", "Class", "Method"],
        description="代码节点类型列表: File, Class, Method",
    )
    top_k: int = Field(default=10, description="返回结果数量")


class SearchSemanticNodesRequest(BaseModel):
    repo_id: str = Field(..., description="仓库ID")
    query: str = Field(..., description="查询关键字")
    node_types: list[str] = Field(
        default=["Module", "Workflow"],
        description="语义节点类型列表: Module, Workflow",
    )
    top_k: int = Field(default=10, description="返回结果数量")


class GetModulesRequest(BaseModel):
    repo_id: str = Field(..., description="仓库ID")


class GetModuleWorkflowsRequest(BaseModel):
    repo_id: str = Field(..., description="仓库ID")
    module_id: str = Field(..., description="模块ID")


class GetNodeDependenciesRequest(BaseModel):
    node_id: str = Field(..., description="节点ID")
    depth: int = Field(default=1, description="依赖深度")


class BatchDownloadFlowchartsRequest(BaseModel):
    method_ids: list[str] = Field(..., description="Method节点ID列表")


# ========== 响应模型 ==========

class ToolResponse(BaseModel):
    success: bool = Field(..., description="是否成功")
    data: Any | None = Field(default=None, description="返回数据")
    error: str | None = Field(default=None, description="错误信息")


# ========== 工具端点 ==========

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


@router.post("/tools/search_code_nodes", response_model=ToolResponse)
async def search_code_nodes(
    request: SearchCodeNodesRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """根据关键字语义查询代码节点 (FILE, METHOD, CLASS)."""
    try:
        result = await tools.search_code_nodes(
            repo_id=request.repo_id,
            query=request.query,
            node_types=request.node_types,
            top_k=request.top_k,
        )
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"search_code_nodes failed: {e}")
        return ToolResponse(success=False, error=str(e))


@router.post("/tools/search_semantic_nodes", response_model=ToolResponse)
async def search_semantic_nodes(
    request: SearchSemanticNodesRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """根据关键字语义查询语义节点 (MODULE, WORKFLOW)."""
    try:
        result = await tools.search_semantic_nodes(
            repo_id=request.repo_id,
            query=request.query,
            node_types=request.node_types,
            top_k=request.top_k,
        )
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"search_semantic_nodes failed: {e}")
        return ToolResponse(success=False, error=str(e))


@router.post("/tools/get_modules", response_model=ToolResponse)
async def get_modules(
    request: GetModulesRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """获取项目的 Module 列表."""
    try:
        result = await tools.get_modules(repo_id=request.repo_id)
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"get_modules failed: {e}")
        return ToolResponse(success=False, error=str(e))


@router.post("/tools/get_module_workflows", response_model=ToolResponse)
async def get_module_workflows(
    request: GetModuleWorkflowsRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """获取 Module 对应的 Workflow 列表."""
    try:
        result = await tools.get_module_workflows(
            repo_id=request.repo_id,
            module_id=request.module_id,
        )
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"get_module_workflows failed: {e}")
        return ToolResponse(success=False, error=str(e))


@router.post("/tools/get_node_dependencies", response_model=ToolResponse)
async def get_node_dependencies(
    request: GetNodeDependenciesRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """获取节点的依赖关系图."""
    try:
        result = await tools.get_node_dependencies(
            node_id=request.node_id,
            depth=request.depth,
        )
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"get_node_dependencies failed: {e}")
        return ToolResponse(success=False, error=str(e))


@router.post("/tools/batch_download_flowcharts", response_model=ToolResponse)
async def batch_download_flowcharts(
    request: BatchDownloadFlowchartsRequest,
    tools: KnowledgeBaseTools = Depends(get_tools),
) -> ToolResponse:
    """根据method节点ID列表批量下载流程图图片."""
    try:
        result = await tools.batch_download_flowcharts(
            method_ids=request.method_ids,
        )
        return ToolResponse(success=True, data=json.loads(result))
    except Exception as e:
        logger.exception(f"batch_download_flowcharts failed: {e}")
        return ToolResponse(success=False, error=str(e))


# ========== 工具列表端点 ==========

@router.get("/tools")
async def list_tools() -> dict:
    """列出可用的 MCP 工具."""
    return {
        "tools": [
            {
                "name": "get_project_structure",
                "description": "获取项目目录结构",
                "endpoint": "/mcp/tools/get_project_structure",
                "method": "POST",
                "parameters": {
                    "repo_id": {"type": "string", "required": True},
                },
            },
            {
                "name": "search_code_nodes",
                "description": "根据关键字语义查询代码节点 (FILE, METHOD, CLASS)",
                "endpoint": "/mcp/tools/search_code_nodes",
                "method": "POST",
                "parameters": {
                    "repo_id": {"type": "string", "required": True},
                    "query": {"type": "string", "required": True},
                    "node_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["File", "Class", "Method"],
                    },
                    "top_k": {"type": "integer", "default": 10},
                },
            },
            {
                "name": "search_semantic_nodes",
                "description": "根据关键字语义查询语义节点 (MODULE, WORKFLOW)，返回结果包含 detail 字段",
                "endpoint": "/mcp/tools/search_semantic_nodes",
                "method": "POST",
                "parameters": {
                    "repo_id": {"type": "string", "required": True},
                    "query": {"type": "string", "required": True},
                    "node_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["Module", "Workflow"],
                    },
                    "top_k": {"type": "integer", "default": 10},
                },
            },
            {
                "name": "get_modules",
                "description": "获取项目的 Module 列表",
                "endpoint": "/mcp/tools/get_modules",
                "method": "POST",
                "parameters": {
                    "repo_id": {"type": "string", "required": True},
                },
            },
            {
                "name": "get_module_workflows",
                "description": "获取 Module 对应的 Workflow 列表",
                "endpoint": "/mcp/tools/get_module_workflows",
                "method": "POST",
                "parameters": {
                    "repo_id": {"type": "string", "required": True},
                    "module_id": {"type": "string", "required": True},
                },
            },
            {
                "name": "get_node_dependencies",
                "description": "获取节点的依赖关系图",
                "endpoint": "/mcp/tools/get_node_dependencies",
                "method": "POST",
                "parameters": {
                    "node_id": {"type": "string", "required": True},
                    "depth": {"type": "integer", "default": 1},
                },
            },
            {
                "name": "batch_download_flowcharts",
                "description": "根据method节点ID列表批量下载流程图图片",
                "endpoint": "/mcp/tools/batch_download_flowcharts",
                "method": "POST",
                "parameters": {
                    "method_ids": {"type": "array", "items": {"type": "string"}, "required": True},
                },
            },
        ]
    }
