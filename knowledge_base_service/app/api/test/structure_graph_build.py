"""结构图构建阶段测试接口.

提供单独的接口用于测试结构图构建阶段，直接执行仓库遍历、代码解析和结构图构建。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.pipeline import PipelineContext
from app.core.stages import StructureGraphBuildStage
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import get_graph_db_client

logger = logging.getLogger(__name__)

router = APIRouter()


class TestStructureGraphBuildRequest(BaseModel):
    """测试结构图构建设请求."""

    repo_id: str = Field(..., description="仓库ID")
    repo_name: Optional[str] = Field(None, description="仓库名称，不传则使用repo_id")
    repo_path: Optional[str] = Field(None, description="仓库路径，不传则使用默认值")


class TestStructureGraphBuildResponse(BaseModel):
    """测试结构图构建响应."""

    success: bool
    repo_id: str
    stage_status: str
    message: str
    repositories: int
    directories: int
    files: int
    classes: int
    methods: int
    duration_seconds: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


@router.post("/structure-graph-build", response_model=TestStructureGraphBuildResponse)
async def test_structure_graph_build(
    request: TestStructureGraphBuildRequest,
) -> TestStructureGraphBuildResponse:
    """单独测试结构图构建阶段.

    执行仓库遍历、代码解析和结构图构建，创建Repository、Directory、File、Class、Method节点。

    Args:
        request: 测试请求，包含repo_id和repo_path

    Returns:
        测试结果，包含创建的节点统计信息
    """
    repo_id = request.repo_id
    repo_name = request.repo_name or repo_id
    repo_path = request.repo_path or f"D:/WorkSpace/{repo_name}"

    logger.info(f"Starting structure graph build test for repo: {repo_id}")

    try:
        # 检查仓库路径是否存在
        from pathlib import Path
        if not Path(repo_path).exists():
            raise HTTPException(
                status_code=404,
                detail=f"Repository path not found: {repo_path}",
            )

        # 1. 创建PipelineContext
        context = _create_test_context(repo_id, repo_name, repo_path)

        # 2. 执行结构图构建阶段
        stage = StructureGraphBuildStage()
        start_time = datetime.utcnow()

        result = await stage.execute(context)

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        # 3. 构建响应
        metadata = result.metadata or {}
        node_ids = context.data.get("node_ids", {})

        return TestStructureGraphBuildResponse(
            success=result.status == PipelineStatus.COMPLETED,
            repo_id=repo_id,
            stage_status=result.status.value,
            message=result.message,
            repositories=metadata.get("repositories", 0),
            directories=metadata.get("directories", 0),
            files=metadata.get("files", 0),
            classes=metadata.get("classes", 0),
            methods=metadata.get("methods", 0),
            duration_seconds=duration,
            metadata={
                **metadata,
                "node_ids": {
                    "repository_id": node_ids.get("repository_id"),
                    "directory_ids_count": len(node_ids.get("directory_ids", [])),
                    "file_ids_count": len(node_ids.get("file_ids", [])),
                    "class_ids_count": len(node_ids.get("class_ids", [])),
                    "method_ids_count": len(node_ids.get("method_ids", [])),
                }
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Structure graph build test failed for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Structure graph build test failed: {str(e)}",
        )


def _create_test_context(
    repo_id: str,
    repo_name: str,
    repo_path: str,
) -> PipelineContext:
    """创建测试用的PipelineContext.

    Args:
        repo_id: 仓库ID
        repo_name: 仓库名称
        repo_path: 仓库路径

    Returns:
        配置好的PipelineContext
    """
    pipeline_id = str(uuid4())

    # 创建上下文
    context = PipelineContext(
        pipeline_id=pipeline_id,
        repo_id=repo_id,
        repo_path=repo_path,
        repo_name=repo_name,
        config={},
    )

    # 设置当前阶段
    context.current_stage = PipelineStage.STRUCTURE_GRAPH_BUILD
    context.overall_status = PipelineStatus.RUNNING

    return context


@router.get("/structure-graph-build/status/{repo_id}")
async def get_structure_graph_build_status(repo_id: str) -> Dict[str, Any]:
    """获取仓库的结构图构建状态.

    查询Neo4j中已创建的各类节点数量。

    Args:
        repo_id: 仓库ID

    Returns:
        结构图构建状态信息
    """
    try:
        graph_db = get_graph_db_client()

        # 查询Repository数量
        repo_query = """
        MATCH (r:Repository)
        WHERE r.repoId = $repo_id
        RETURN count(r) as count
        """
        repo_results = await graph_db._execute_query(repo_query, {"repo_id": repo_id})
        repo_count = repo_results[0]["count"] if repo_results else 0

        # 查询Directory数量
        dir_query = """
        MATCH (d:Directory)
        WHERE d.repoId = $repo_id
        RETURN count(d) as count
        """
        dir_results = await graph_db._execute_query(dir_query, {"repo_id": repo_id})
        dir_count = dir_results[0]["count"] if dir_results else 0

        # 查询File数量
        file_query = """
        MATCH (f:File)
        WHERE f.repoId = $repo_id
        RETURN count(f) as count
        """
        file_results = await graph_db._execute_query(file_query, {"repo_id": repo_id})
        file_count = file_results[0]["count"] if file_results else 0

        # 查询Class数量
        class_query = """
        MATCH (c:Class)
        WHERE c.repoId = $repo_id
        RETURN count(c) as count
        """
        class_results = await graph_db._execute_query(class_query, {"repo_id": repo_id})
        class_count = class_results[0]["count"] if class_results else 0

        # 查询Method数量
        method_query = """
        MATCH (m:Method)
        WHERE m.repoId = $repo_id
        RETURN count(m) as count
        """
        method_results = await graph_db._execute_query(method_query, {"repo_id": repo_id})
        method_count = method_results[0]["count"] if method_results else 0

        # 查询各类文件类型数量
        file_type_query = """
        MATCH (f:File)
        WHERE f.repoId = $repo_id
        RETURN f.fileType as file_type, count(f) as count
        """
        file_type_results = await graph_db._execute_query(file_type_query, {"repo_id": repo_id})
        file_type_stats = {}
        for record in file_type_results:
            file_type = record.get("file_type") or "unknown"
            file_type_stats[file_type] = record.get("count", 0)

        # 查询支持语言的文件数量（有代码内容的）
        code_files_query = """
        MATCH (f:File)
        WHERE f.repoId = $repo_id AND f.code IS NOT NULL AND f.code <> ''
        RETURN count(f) as count
        """
        code_files_results = await graph_db._execute_query(code_files_query, {"repo_id": repo_id})
        code_files_count = code_files_results[0]["count"] if code_files_results else 0

        return {
            "repo_id": repo_id,
            "repositories": repo_count,
            "directories": dir_count,
            "files": {
                "total": file_count,
                "with_code": code_files_count,
                "by_type": file_type_stats,
            },
            "classes": class_count,
            "methods": method_count,
            "can_run_semantic_analysis": method_count > 0 or class_count > 0,
        }

    except Exception as e:
        logger.exception(f"Failed to get structure graph build status for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get status: {str(e)}",
        )


@router.get("/structure-graph-build/nodes/{repo_id}")
async def get_structure_graph_nodes(
    repo_id: str,
    node_type: str = "File",
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """获取结构图中的节点详情.

    分页查询指定类型的节点列表。

    Args:
        repo_id: 仓库ID
        node_type: 节点类型 (Repository, Directory, File, Class, Method)
        limit: 每页数量
        offset: 偏移量

    Returns:
        节点列表和分页信息
    """
    try:
        graph_db = get_graph_db_client()

        # 验证节点类型
        valid_types = ["Repository", "Directory", "File", "Class", "Method"]
        if node_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid node type: {node_type}. Must be one of {valid_types}",
            )

        # 查询总数
        count_query = f"""
        MATCH (n:{node_type})
        WHERE n.repoId = $repo_id
        RETURN count(n) as total
        """
        count_results = await graph_db._execute_query(count_query, {"repo_id": repo_id})
        total = count_results[0]["total"] if count_results else 0

        # 查询节点列表
        # 根据节点类型选择不同的返回字段
        if node_type == "Method":
            nodes_query = f"""
            MATCH (n:{node_type})
            WHERE n.repoId = $repo_id
            RETURN n.id as id, n.name as name, n.filePath as file_path,
                   n.language as language, n.startLine as start_line, n.endLine as end_line
            ORDER BY n.filePath, n.name
            SKIP $offset LIMIT $limit
            """
        elif node_type == "Class":
            nodes_query = f"""
            MATCH (n:{node_type})
            WHERE n.repoId = $repo_id
            RETURN n.id as id, n.name as name, n.filePath as file_path,
                   n.language as language, n.realType as real_type
            ORDER BY n.filePath, n.name
            SKIP $offset LIMIT $limit
            """
        elif node_type == "File":
            nodes_query = f"""
            MATCH (n:{node_type})
            WHERE n.repoId = $repo_id
            RETURN n.id as id, n.name as name, n.path as path,
                   n.fileType as file_type, n.suffix as suffix
            ORDER BY n.path
            SKIP $offset LIMIT $limit
            """
        elif node_type == "Directory":
            nodes_query = f"""
            MATCH (n:{node_type})
            WHERE n.repoId = $repo_id
            RETURN n.id as id, n.name as name, n.path as path
            ORDER BY n.path
            SKIP $offset LIMIT $limit
            """
        else:  # Repository
            nodes_query = f"""
            MATCH (n:{node_type})
            WHERE n.repoId = $repo_id
            RETURN n.id as id, n.name as name, n.path as path
            SKIP $offset LIMIT $limit
            """

        nodes_results = await graph_db._execute_query(
            nodes_query, {"repo_id": repo_id, "offset": offset, "limit": limit}
        )

        nodes = []
        for record in nodes_results:
            node_data = {k: v for k, v in record.items() if v is not None}
            nodes.append(node_data)

        return {
            "repo_id": repo_id,
            "node_type": node_type,
            "total": total,
            "offset": offset,
            "limit": limit,
            "nodes": nodes,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get nodes for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get nodes: {str(e)}",
        )
