"""向量库存储阶段测试接口.

提供单独的接口用于测试向量库存储阶段，假设结构图构建、语义分析、
依赖图构建和模块检测阶段已完成，将节点摘要生成向量并存储到向量数据库。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.pipeline import PipelineContext
from app.core.stages import VectorDBStoreStage
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import get_graph_db_client

logger = logging.getLogger(__name__)

router = APIRouter()


class TestVectorDBStoreRequest(BaseModel):
    """测试向量库存储请求."""

    repo_id: str = Field(..., description="仓库ID")
    repo_name: Optional[str] = Field(None, description="仓库名称，不传则使用repo_id")


class TestVectorDBStoreResponse(BaseModel):
    """测试向量库存储响应."""

    success: bool
    repo_id: str
    stage_status: str
    message: str
    file_vectors: int
    class_vectors: int
    method_vectors: int
    semantic_vectors: int
    total_vectors: int
    duration_seconds: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


@router.post("/vector-db-store", response_model=TestVectorDBStoreResponse)
async def test_vector_db_store(
    request: TestVectorDBStoreRequest,
) -> TestVectorDBStoreResponse:
    """单独测试向量库存储阶段.

    假设前面阶段已完成，从Neo4j查询节点摘要，生成embedding并存储到向量数据库。

    Args:
        request: 测试请求，包含repo_id

    Returns:
        测试结果，包含向量存储统计信息
    """
    repo_id = request.repo_id
    repo_name = request.repo_name or repo_id

    logger.info(f"Starting vector db store test for repo: {repo_id}")

    try:
        # 1. 检查是否存在需要存储向量的节点
        graph_db = get_graph_db_client()
        node_counts = await _get_nodes_with_summary(graph_db, repo_id)

        total_nodes = sum(node_counts.values())
        if total_nodes == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No nodes with summary found for repo: {repo_id}. "
                       "Please ensure structure graph build and semantic analysis stages are completed.",
            )

        logger.info(
            f"Found {node_counts.get('files', 0)} files, {node_counts.get('classes', 0)} classes, "
            f"{node_counts.get('methods', 0)} methods, {node_counts.get('modules', 0)} modules, "
            f"{node_counts.get('workflows', 0)} workflows with summary for repo: {repo_id}"
        )

        # 2. 创建PipelineContext，模拟前面阶段已完成
        context = _create_test_context(repo_id, repo_name)

        # 3. 执行向量库存储阶段
        stage = VectorDBStoreStage()
        start_time = datetime.utcnow()

        result = await stage.execute(context)

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        # 4. 构建响应
        metadata = result.metadata or {}
        vector_storage = context.data.get("vector_storage", {})

        return TestVectorDBStoreResponse(
            success=result.status == PipelineStatus.COMPLETED,
            repo_id=repo_id,
            stage_status=result.status.value,
            message=result.message,
            file_vectors=vector_storage.get("file_vectors", 0),
            class_vectors=vector_storage.get("class_vectors", 0),
            method_vectors=vector_storage.get("method_vectors", 0),
            semantic_vectors=vector_storage.get("semantic_vectors", 0),
            total_vectors=vector_storage.get("total_vectors", 0),
            duration_seconds=duration,
            metadata=metadata,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Vector db store test failed for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Vector db store test failed: {str(e)}",
        )


async def _get_nodes_with_summary(graph_db, repo_id: str) -> Dict[str, int]:
    """获取仓库中具有summary的节点数量统计.

    Args:
        graph_db: 图数据库客户端
        repo_id: 仓库ID

    Returns:
        各类型节点数量统计
    """
    stats: Dict[str, int] = {}
    node_types = ["File", "Class", "Method", "Module", "Workflow"]

    for node_type in node_types:
        key = f"{node_type.lower()}s"
        try:
            query = f"""
            MATCH (n:{node_type})
            WHERE n.repoId = $repo_id AND n.summary IS NOT NULL AND n.summary <> ''
            RETURN count(n) as count
            """
            results = await graph_db._execute_query(query, {"repo_id": repo_id})
            stats[key] = results[0]["count"] if results else 0
        except Exception as e:
            logger.warning(f"Failed to count {node_type} nodes for repo {repo_id}: {e}")
            stats[key] = 0

    return stats


def _create_test_context(
    repo_id: str,
    repo_name: str,
) -> PipelineContext:
    """创建测试用的PipelineContext.

    模拟前面阶段已完成的状态。

    Args:
        repo_id: 仓库ID
        repo_name: 仓库名称

    Returns:
        配置好的PipelineContext
    """
    pipeline_id = str(uuid4())

    # 创建上下文
    context = PipelineContext(
        pipeline_id=pipeline_id,
        repo_id=repo_id,
        repo_path="",  # 向量库存储不需要实际路径
        repo_name=repo_name,
        config={},
    )

    # 模拟结构图构建阶段的输出
    context.data["node_ids"] = {
        "repository_id": f"repo_{repo_name}",
        "directory_ids": [],
        "file_ids": [],
        "class_ids": [],
        "method_ids": [],
    }

    # 设置当前阶段
    context.current_stage = PipelineStage.VECTOR_DB_STORE
    context.overall_status = PipelineStatus.RUNNING

    # 模拟已完成的阶段
    context.stages[PipelineStage.STRUCTURE_GRAPH_BUILD] = StageResult(
        stage=PipelineStage.STRUCTURE_GRAPH_BUILD,
        status=PipelineStatus.COMPLETED,
        message="Mocked structure graph build for test",
    )
    context.stages[PipelineStage.DEPENDENCY_GRAPH_BUILD] = StageResult(
        stage=PipelineStage.DEPENDENCY_GRAPH_BUILD,
        status=PipelineStatus.COMPLETED,
        message="Mocked dependency graph build for test",
    )
    context.stages[PipelineStage.SEMANTIC_ANALYSIS] = StageResult(
        stage=PipelineStage.SEMANTIC_ANALYSIS,
        status=PipelineStatus.COMPLETED,
        message="Mocked semantic analysis for test",
    )
    context.stages[PipelineStage.MODULE_DETECTION] = StageResult(
        stage=PipelineStage.MODULE_DETECTION,
        status=PipelineStatus.COMPLETED,
        message="Mocked module detection for test",
    )

    return context


@router.get("/vector-db-store/status/{repo_id}")
async def get_vector_db_store_status(repo_id: str) -> Dict[str, Any]:
    """获取仓库的向量库存储状态.

    查询Neo4j中各类型节点的embeddingId存储情况。

    Args:
        repo_id: 仓库ID

    Returns:
        向量库存储状态信息
    """
    try:
        graph_db = get_graph_db_client()

        node_types = ["File", "Class", "Method", "Module", "Workflow"]
        type_stats = {}
        total_nodes = 0
        total_with_embedding = 0

        for node_type in node_types:
            query = f"""
            MATCH (n:{node_type})
            WHERE n.repoId = $repo_id
            RETURN
                count(n) as total,
                count(CASE WHEN n.embeddingId IS NOT NULL AND n.embeddingId <> '' THEN 1 END) as with_embedding
            """
            results = await graph_db._execute_query(query, {"repo_id": repo_id})
            stats = results[0] if results else {"total": 0, "with_embedding": 0}

            key = f"{node_type.lower()}s"
            type_stats[key] = {
                "total": stats["total"],
                "with_embedding": stats["with_embedding"],
                "completion_percentage": (
                    round((stats["with_embedding"] / stats["total"]) * 100, 2)
                    if stats["total"] > 0 else 0
                ),
            }
            total_nodes += stats["total"]
            total_with_embedding += stats["with_embedding"]

        overall_completion = 0
        if total_nodes > 0:
            overall_completion = round((total_with_embedding / total_nodes) * 100, 2)

        return {
            "repo_id": repo_id,
            "by_type": type_stats,
            "overall": {
                "total_nodes": total_nodes,
                "nodes_with_embedding": total_with_embedding,
                "completion_percentage": overall_completion,
            },
            "can_run_query": total_with_embedding > 0,
        }

    except Exception as e:
        logger.exception(f"Failed to get vector db store status for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get status: {str(e)}",
        )


@router.get("/vector-db-store/nodes/{repo_id}")
async def get_nodes_with_embedding(
    repo_id: str,
    node_type: str = "Method",
    has_embedding: Optional[bool] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """获取带有embeddingId的节点详情.

    分页查询指定类型的节点及其embedding信息。

    Args:
        repo_id: 仓库ID
        node_type: 节点类型 (File, Class, Method, Module, Workflow)
        has_embedding: 是否只返回有/无embeddingId的节点，None表示全部
        limit: 每页数量
        offset: 偏移量

    Returns:
        节点列表和分页信息
    """
    try:
        graph_db = get_graph_db_client()

        # 验证节点类型
        valid_types = ["File", "Class", "Method", "Module", "Workflow"]
        if node_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid node type: {node_type}. Must be one of {valid_types}",
            )

        # 构建查询条件
        embedding_condition = ""
        if has_embedding is True:
            embedding_condition = "AND n.embeddingId IS NOT NULL AND n.embeddingId <> ''"
        elif has_embedding is False:
            embedding_condition = "AND (n.embeddingId IS NULL OR n.embeddingId = '')"

        # 查询总数
        count_query = f"""
        MATCH (n:{node_type})
        WHERE n.repoId = $repo_id {embedding_condition}
        RETURN count(n) as total
        """
        count_results = await graph_db._execute_query(count_query, {"repo_id": repo_id})
        total = count_results[0]["total"] if count_results else 0

        # 查询节点列表
        if node_type in ["File", "Class", "Method"]:
            nodes_query = f"""
            MATCH (n:{node_type})
            WHERE n.repoId = $repo_id {embedding_condition}
            RETURN n.id as id, n.name as name, n.filePath as file_path,
                   n.summary as summary, n.embeddingId as embedding_id, n.language as language
            ORDER BY n.filePath, n.name
            SKIP $offset LIMIT $limit
            """
        else:  # Module, Workflow
            nodes_query = f"""
            MATCH (n:{node_type})
            WHERE n.repoId = $repo_id {embedding_condition}
            RETURN n.id as id, n.name as name,
                   n.summary as summary, n.embeddingId as embedding_id
            ORDER BY n.name
            SKIP $offset LIMIT $limit
            """

        nodes_results = await graph_db._execute_query(
            nodes_query, {"repo_id": repo_id, "offset": offset, "limit": limit}
        )

        nodes = []
        for record in nodes_results:
            node_data = {k: v for k, v in record.items() if v is not None}
            # 截断过长的summary用于展示
            if "summary" in node_data and node_data["summary"]:
                summary = node_data["summary"]
                if len(summary) > 200:
                    node_data["summary_preview"] = summary[:200] + "..."
                else:
                    node_data["summary_preview"] = summary
            nodes.append(node_data)

        return {
            "repo_id": repo_id,
            "node_type": node_type,
            "has_embedding_filter": has_embedding,
            "total": total,
            "offset": offset,
            "limit": limit,
            "nodes": nodes,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get nodes with embedding for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get nodes: {str(e)}",
        )
