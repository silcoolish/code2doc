"""语义分析阶段测试接口.

提供单独的接口用于测试语义分析阶段，假设结构图构建阶段已完成，
为Method、Class、File节点生成语义摘要。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.pipeline import PipelineContext
from app.core.stages import SemanticAnalysisStage
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import get_graph_db_client

logger = logging.getLogger(__name__)

router = APIRouter()


class TestSemanticAnalysisRequest(BaseModel):
    """测试语义分析请求."""

    repo_id: str = Field(..., description="仓库ID")
    repo_name: Optional[str] = Field(None, description="仓库名称，不传则使用repo_id")
    repo_path: Optional[str] = Field(None, description="仓库路径，不传则使用默认值")


class TestSemanticAnalysisResponse(BaseModel):
    """测试语义分析响应."""

    success: bool
    repo_id: str
    stage_status: str
    message: str
    methods_summarized: int
    classes_summarized: int
    files_summarized: int
    duration_seconds: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


@router.post("/semantic-analysis", response_model=TestSemanticAnalysisResponse)
async def test_semantic_analysis(
    request: TestSemanticAnalysisRequest,
) -> TestSemanticAnalysisResponse:
    """单独测试语义分析阶段.

    假设结构图构建阶段已完成，为Method、Class、File节点生成语义摘要。

    Args:
        request: 测试请求，包含repo_id

    Returns:
        测试结果，包含生成的摘要统计信息
    """
    repo_id = request.repo_id
    repo_name = request.repo_name or repo_id
    repo_path = request.repo_path or f"D:/WorkSpace/{repo_name}"

    logger.info(f"Starting semantic analysis test for repo: {repo_id}")

    try:
        # 1. 检查是否存在Method/Class节点
        graph_db = get_graph_db_client()
        node_counts = await _get_node_counts(graph_db, repo_id)

        if node_counts["methods"] == 0 and node_counts["classes"] == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No Method or Class nodes found for repo: {repo_id}. "
                       "Please ensure structure graph build stage is completed.",
            )

        logger.info(
            f"Found {node_counts['methods']} methods, {node_counts['classes']} classes, "
            f"{node_counts['files']} files for repo: {repo_id}"
        )

        # 2. 创建PipelineContext，模拟结构图构建已完成
        context = _create_test_context(repo_id, repo_name, repo_path)

        # 3. 执行语义分析阶段
        stage = SemanticAnalysisStage()
        start_time = datetime.utcnow()

        result = await stage.execute(context)

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        # 4. 构建响应
        metadata = result.metadata or {}
        semantic_analysis = context.data.get("semantic_analysis", {})

        return TestSemanticAnalysisResponse(
            success=result.status == PipelineStatus.COMPLETED,
            repo_id=repo_id,
            stage_status=result.status.value,
            message=result.message,
            methods_summarized=semantic_analysis.get("methods_summarized", 0),
            classes_summarized=semantic_analysis.get("classes_summarized", 0),
            files_summarized=semantic_analysis.get("files_summarized", 0),
            duration_seconds=duration,
            metadata=metadata,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Semantic analysis test failed for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Semantic analysis test failed: {str(e)}",
        )


async def _get_node_counts(graph_db, repo_id: str) -> Dict[str, int]:
    """获取仓库的节点数量统计.

    Args:
        graph_db: 图数据库客户端
        repo_id: 仓库ID

    Returns:
        节点数量统计
    """
    # 查询Method数量
    method_query = """
    MATCH (m:Method)
    WHERE m.repoId = $repo_id
    RETURN count(m) as count
    """
    method_results = await graph_db._execute_query(method_query, {"repo_id": repo_id})
    method_count = method_results[0]["count"] if method_results else 0

    # 查询Class数量
    class_query = """
    MATCH (c:Class)
    WHERE c.repoId = $repo_id
    RETURN count(c) as count
    """
    class_results = await graph_db._execute_query(class_query, {"repo_id": repo_id})
    class_count = class_results[0]["count"] if class_results else 0

    # 查询File数量
    file_query = """
    MATCH (f:File)
    WHERE f.repoId = $repo_id
    RETURN count(f) as count
    """
    file_results = await graph_db._execute_query(file_query, {"repo_id": repo_id})
    file_count = file_results[0]["count"] if file_results else 0

    return {
        "methods": method_count,
        "classes": class_count,
        "files": file_count,
    }


def _create_test_context(
    repo_id: str,
    repo_name: str,
    repo_path: str,
) -> PipelineContext:
    """创建测试用的PipelineContext.

    模拟结构图构建阶段已完成的状态。

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

    # 模拟结构图构建阶段的输出（node_ids）
    # 语义分析阶段会从Neo4j查询实际节点，这里只需要占位
    context.data["node_ids"] = {
        "repository_id": f"repo_{repo_name}",
        "directory_ids": [],
        "file_ids": [],
        "class_ids": [],
        "method_ids": [],
    }

    # 设置当前阶段
    context.current_stage = PipelineStage.SEMANTIC_ANALYSIS
    context.overall_status = PipelineStatus.RUNNING

    # 模拟已完成的阶段
    context.stages[PipelineStage.STRUCTURE_GRAPH_BUILD] = StageResult(
        stage=PipelineStage.STRUCTURE_GRAPH_BUILD,
        status=PipelineStatus.COMPLETED,
        message="Mocked structure graph build for test",
    )

    return context


@router.get("/semantic-analysis/status/{repo_id}")
async def get_semantic_analysis_status(repo_id: str) -> Dict[str, Any]:
    """获取仓库的语义分析状态.

    查询Neo4j中各类节点的summary生成情况。

    Args:
        repo_id: 仓库ID

    Returns:
        语义分析状态信息
    """
    try:
        graph_db = get_graph_db_client()

        # 查询Method统计
        method_stats_query = """
        MATCH (m:Method)
        WHERE m.repoId = $repo_id
        RETURN
            count(m) as total,
            count(CASE WHEN m.summary IS NOT NULL AND m.summary <> '' THEN 1 END) as with_summary
        """
        method_results = await graph_db._execute_query(method_stats_query, {"repo_id": repo_id})
        method_stats = method_results[0] if method_results else {"total": 0, "with_summary": 0}

        # 查询Class统计
        class_stats_query = """
        MATCH (c:Class)
        WHERE c.repoId = $repo_id
        RETURN
            count(c) as total,
            count(CASE WHEN c.summary IS NOT NULL AND c.summary <> '' THEN 1 END) as with_summary
        """
        class_results = await graph_db._execute_query(class_stats_query, {"repo_id": repo_id})
        class_stats = class_results[0] if class_results else {"total": 0, "with_summary": 0}

        # 查询File统计
        file_stats_query = """
        MATCH (f:File)
        WHERE f.repoId = $repo_id
        RETURN
            count(f) as total,
            count(CASE WHEN f.summary IS NOT NULL AND f.summary <> '' THEN 1 END) as with_summary
        """
        file_results = await graph_db._execute_query(file_stats_query, {"repo_id": repo_id})
        file_stats = file_results[0] if file_results else {"total": 0, "with_summary": 0}

        # 计算完成百分比
        total_nodes = method_stats["total"] + class_stats["total"] + file_stats["total"]
        total_with_summary = (
            method_stats["with_summary"] + class_stats["with_summary"] + file_stats["with_summary"]
        )

        completion_percentage = 0
        if total_nodes > 0:
            completion_percentage = round((total_with_summary / total_nodes) * 100, 2)

        return {
            "repo_id": repo_id,
            "methods": {
                "total": method_stats["total"],
                "with_summary": method_stats["with_summary"],
                "completion_percentage": (
                    round((method_stats["with_summary"] / method_stats["total"]) * 100, 2)
                    if method_stats["total"] > 0 else 0
                ),
            },
            "classes": {
                "total": class_stats["total"],
                "with_summary": class_stats["with_summary"],
                "completion_percentage": (
                    round((class_stats["with_summary"] / class_stats["total"]) * 100, 2)
                    if class_stats["total"] > 0 else 0
                ),
            },
            "files": {
                "total": file_stats["total"],
                "with_summary": file_stats["with_summary"],
                "completion_percentage": (
                    round((file_stats["with_summary"] / file_stats["total"]) * 100, 2)
                    if file_stats["total"] > 0 else 0
                ),
            },
            "overall": {
                "total_nodes": total_nodes,
                "nodes_with_summary": total_with_summary,
                "completion_percentage": completion_percentage,
            },
            "can_run_module_detection": file_stats["with_summary"] > 0,
        }

    except Exception as e:
        logger.exception(f"Failed to get semantic analysis status for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get status: {str(e)}",
        )


@router.get("/semantic-analysis/nodes/{repo_id}")
async def get_nodes_with_summary(
    repo_id: str,
    node_type: str = "Method",
    has_summary: Optional[bool] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """获取带有摘要的节点详情.

    分页查询指定类型的节点及其摘要信息。

    Args:
        repo_id: 仓库ID
        node_type: 节点类型 (Method, Class, File)
        has_summary: 是否只返回有/无摘要的节点，None表示全部
        limit: 每页数量
        offset: 偏移量

    Returns:
        节点列表和分页信息
    """
    try:
        graph_db = get_graph_db_client()

        # 验证节点类型
        valid_types = ["Method", "Class", "File"]
        if node_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid node type: {node_type}. Must be one of {valid_types}",
            )

        # 构建查询条件
        summary_condition = ""
        if has_summary is True:
            summary_condition = "AND n.summary IS NOT NULL AND n.summary <> ''"
        elif has_summary is False:
            summary_condition = "AND (n.summary IS NULL OR n.summary = '')"

        # 查询总数
        count_query = f"""
        MATCH (n:{node_type})
        WHERE n.repoId = $repo_id {summary_condition}
        RETURN count(n) as total
        """
        count_results = await graph_db._execute_query(count_query, {"repo_id": repo_id})
        total = count_results[0]["total"] if count_results else 0

        # 查询节点列表
        if node_type == "Method":
            nodes_query = f"""
            MATCH (n:{node_type})
            WHERE n.repoId = $repo_id {summary_condition}
            RETURN n.id as id, n.name as name, n.filePath as file_path,
                   n.summary as summary, n.language as language
            ORDER BY n.filePath, n.name
            SKIP $offset LIMIT $limit
            """
        elif node_type == "Class":
            nodes_query = f"""
            MATCH (n:{node_type})
            WHERE n.repoId = $repo_id {summary_condition}
            RETURN n.id as id, n.name as name, n.filePath as file_path,
                   n.summary as summary, n.language as language
            ORDER BY n.filePath, n.name
            SKIP $offset LIMIT $limit
            """
        else:  # File
            nodes_query = f"""
            MATCH (n:{node_type})
            WHERE n.repoId = $repo_id {summary_condition}
            RETURN n.id as id, n.name as name, n.path as path,
                   n.summary as summary, n.fileType as file_type
            ORDER BY n.path
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
            "has_summary_filter": has_summary,
            "total": total,
            "offset": offset,
            "limit": limit,
            "nodes": nodes,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get nodes with summary for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get nodes: {str(e)}",
        )


@router.get("/semantic-analysis/summary/{repo_id}/{node_type}/{node_id:path}")
async def get_node_summary(
    repo_id: str,
    node_type: str,
    node_id: str,
) -> Dict[str, Any]:
    """获取单个节点的摘要详情.

    Args:
        repo_id: 仓库ID
        node_type: 节点类型 (Method, Class, File)
        node_id: 节点ID（支持包含斜杠的路径）

    Returns:
        节点详情和摘要
    """
    try:
        graph_db = get_graph_db_client()

        # 验证节点类型
        valid_types = ["Method", "Class", "File"]
        if node_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid node type: {node_type}. Must be one of {valid_types}",
            )

        # 查询节点详情
        if node_type == "Method":
            query = """
            MATCH (m:Method)
            WHERE m.repoId = $repo_id AND m.id = $node_id
            RETURN m.id as id, m.name as name, m.filePath as file_path,
                   m.summary as summary, m.code as code, m.docstring as docstring,
                   m.language as language, m.startLine as start_line, m.endLine as end_line
            """
        elif node_type == "Class":
            query = """
            MATCH (c:Class)
            WHERE c.repoId = $repo_id AND c.id = $node_id
            RETURN c.id as id, c.name as name, c.filePath as file_path,
                   c.summary as summary, c.code as code, c.docstring as docstring,
                   c.language as language, c.realType as real_type
            """
        else:  # File
            query = """
            MATCH (f:File)
            WHERE f.repoId = $repo_id AND f.id = $node_id
            RETURN f.id as id, f.name as name, f.path as path,
                   f.summary as summary, f.code as code,
                   f.fileType as file_type
            """

        results = await graph_db._execute_query(
            query, {"repo_id": repo_id, "node_id": node_id}
        )

        if not results:
            raise HTTPException(
                status_code=404,
                detail=f"{node_type} node not found: {node_id}",
            )

        node_data = {k: v for k, v in results[0].items() if v is not None}

        # 截断过长的code用于预览
        if "code" in node_data and node_data["code"]:
            code = node_data["code"]
            if len(code) > 500:
                node_data["code_preview"] = code[:500] + "..."
            else:
                node_data["code_preview"] = code

        return {
            "repo_id": repo_id,
            "node_type": node_type,
            "node": node_data,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get node summary for {node_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get node summary: {str(e)}",
        )
