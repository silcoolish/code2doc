"""模块检测阶段测试接口.

提供单独的接口用于测试模块检测阶段，假设结构图构建和语义分析阶段已完成。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.pipeline import PipelineContext
from app.core.stages.module_detection import ModuleDetectionStage
from app.core.stages.module_detection.strategies import ModuleDetectionStrategyFactory
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import get_graph_db_client

logger = logging.getLogger(__name__)

router = APIRouter()


class TestModuleDetectionRequest(BaseModel):
    """测试模块检测请求."""

    repo_id: str = Field(..., description="仓库ID")
    repo_name: Optional[str] = Field(None, description="仓库名称，不传则使用repo_id")
    repo_path: Optional[str] = Field(None, description="仓库路径，不传则使用默认值")
    strategy: str = Field(
        default="simple",
        description="模块检测策略: simple(简单截断) | clustering(聚类策略)"
    )
    strategy_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="策略特定配置参数\n"
                    "simple策略: {max_files: int} 默认100\n"
                    "clustering策略: {max_cluster_size: int, max_concurrency: int} 默认80, 5"
    )


class TestModuleDetectionResponse(BaseModel):
    """测试模块检测响应."""

    success: bool
    repo_id: str
    stage_status: str
    message: str
    modules_detected: int
    workflows_detected: int
    strategy: str
    duration_seconds: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


@router.post("/module-detection", response_model=TestModuleDetectionResponse)
async def test_module_detection(
    request: TestModuleDetectionRequest,
) -> TestModuleDetectionResponse:
    """单独测试模块检测阶段.

    假设结构图构建和语义分析阶段已完成，直接从Neo4j查询File节点的summary，
    执行模块检测阶段。

    Args:
        request: 测试请求，包含repo_id

    Returns:
        测试结果，包含检测到的模块和工作流信息
    """
    repo_id = request.repo_id
    repo_name = request.repo_name or repo_id
    repo_path = request.repo_path or f"D:/WorkSpace/{repo_name}"

    logger.info(f"Starting module detection test for repo: {repo_id}")

    try:
        # 1. 从Neo4j查询File节点的summary
        graph_db = get_graph_db_client()
        file_summaries = await _get_file_summaries(graph_db, repo_id)

        if not file_summaries:
            raise HTTPException(
                status_code=404,
                detail=f"No File nodes with summary found for repo: {repo_id}. "
                       "Please ensure structure graph build and semantic analysis stages are completed.",
            )

        logger.info(f"Found {len(file_summaries)} files with summary for repo: {repo_id}")

        # 2. 创建PipelineContext，模拟结构图构建和语义分析已完成
        context = _create_test_context(repo_id, repo_name, repo_path, file_summaries)

        # 3. 执行模块检测阶段（使用指定的策略）
        strategy_name = request.strategy
        strategy_config = request.strategy_config or {}

        stage = ModuleDetectionStage(
            strategy_name=strategy_name,
            strategy_config=strategy_config,
        )
        start_time = datetime.utcnow()

        result = await stage.execute(context)

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        # 4. 构建响应
        metadata = result.metadata or {}
        module_ids = context.data.get("module_ids", [])
        workflow_ids = context.data.get("workflow_ids", [])

        return TestModuleDetectionResponse(
            success=result.status == PipelineStatus.COMPLETED,
            repo_id=repo_id,
            stage_status=result.status.value,
            message=result.message,
            modules_detected=len(module_ids),
            workflows_detected=len(workflow_ids),
            strategy=metadata.get("strategy", "unknown"),
            duration_seconds=duration,
            metadata=metadata,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Module detection test failed for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Module detection test failed: {str(e)}",
        )


async def _get_file_summaries(graph_db, repo_id: str) -> Dict[str, str]:
    """从Neo4j查询File节点的summary.

    Args:
        graph_db: 图数据库客户端
        repo_id: 仓库ID

    Returns:
        文件ID到摘要的映射字典
    """
    # 查询所有有summary的File节点
    query = """
    MATCH (f:File)
    WHERE f.repoId = $repo_id AND f.summary IS NOT NULL AND f.summary <> ''
    RETURN f.id as file_id, f.summary as summary
    """

    results = await graph_db._execute_query(query, {"repo_id": repo_id})

    file_summaries = {}
    for record in results:
        file_id = record.get("file_id")
        summary = record.get("summary")
        if file_id and summary:
            file_summaries[file_id] = summary

    return file_summaries


def _create_test_context(
    repo_id: str,
    repo_name: str,
    repo_path: str,
    file_summaries: Dict[str, str],
) -> PipelineContext:
    """创建测试用的PipelineContext.

    模拟结构图构建和语义分析阶段已完成的状态。

    Args:
        repo_id: 仓库ID
        repo_name: 仓库名称
        repo_path: 仓库路径
        file_summaries: 文件摘要字典

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

    # 模拟语义分析阶段的输出
    context.data["file_summaries"] = file_summaries

    # 设置当前阶段为MODULE_DETECTION
    context.current_stage = PipelineStage.MODULE_DETECTION
    context.overall_status = PipelineStatus.RUNNING

    # 模拟已完成的阶段
    context.stages[PipelineStage.STRUCTURE_GRAPH_BUILD] = StageResult(
        stage=PipelineStage.STRUCTURE_GRAPH_BUILD,
        status=PipelineStatus.COMPLETED,
        message="Mocked structure graph build for test",
    )
    context.stages[PipelineStage.SEMANTIC_ANALYSIS] = StageResult(
        stage=PipelineStage.SEMANTIC_ANALYSIS,
        status=PipelineStatus.COMPLETED,
        message="Mocked semantic analysis for test",
    )

    return context


@router.get("/module-detection/status/{repo_id}")
async def get_module_detection_status(repo_id: str) -> Dict[str, Any]:
    """获取仓库的模块检测状态.

    查询Neo4j中已检测到的Module和Workflow节点数量。

    Args:
        repo_id: 仓库ID

    Returns:
        模块检测状态信息
    """
    try:
        graph_db = get_graph_db_client()

        # 查询Module数量
        module_query = """
        MATCH (m:Module)
        WHERE m.repoId = $repo_id
        RETURN count(m) as count
        """
        module_results = await graph_db._execute_query(module_query, {"repo_id": repo_id})
        module_count = module_results[0]["count"] if module_results else 0

        # 查询Workflow数量
        workflow_query = """
        MATCH (w:Workflow)
        WHERE w.repoId = $repo_id
        RETURN count(w) as count
        """
        workflow_results = await graph_db._execute_query(workflow_query, {"repo_id": repo_id})
        workflow_count = workflow_results[0]["count"] if workflow_results else 0

        # 查询File节点数量
        file_query = """
        MATCH (f:File)
        WHERE f.repoId = $repo_id
        RETURN count(f) as count
        """
        file_results = await graph_db._execute_query(file_query, {"repo_id": repo_id})
        file_count = file_results[0]["count"] if file_results else 0

        # 查询有summary的File数量
        file_with_summary_query = """
        MATCH (f:File)
        WHERE f.repoId = $repo_id AND f.summary IS NOT NULL AND f.summary <> ''
        RETURN count(f) as count
        """
        file_summary_results = await graph_db._execute_query(
            file_with_summary_query, {"repo_id": repo_id}
        )
        file_with_summary_count = file_summary_results[0]["count"] if file_summary_results else 0

        return {
            "repo_id": repo_id,
            "files_total": file_count,
            "files_with_summary": file_with_summary_count,
            "modules_detected": module_count,
            "workflows_detected": workflow_count,
            "can_run_module_detection": file_with_summary_count > 0,
        }

    except Exception as e:
        logger.exception(f"Failed to get module detection status for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get status: {str(e)}",
        )


@router.get("/module-detection/strategies")
async def get_available_strategies() -> Dict[str, Any]:
    """获取可用的模块检测策略列表.

    Returns:
        可用策略列表及其配置说明
    """
    strategies = ModuleDetectionStrategyFactory.list_strategies()

    return {
        "strategies": [
            {
                "name": name,
                "description": description,
                "config_options": _get_strategy_config_options(name),
            }
            for name, description in strategies.items()
        ]
    }


def _get_strategy_config_options(strategy_name: str) -> Dict[str, Any]:
    """获取策略的配置选项说明.

    Args:
        strategy_name: 策略名称

    Returns:
        配置选项说明
    """
    if strategy_name == "simple":
        return {
            "max_files": {
                "type": "integer",
                "default": 100,
                "description": "简单策略最大处理文件数",
            }
        }
    elif strategy_name == "clustering":
        return {
            "max_cluster_size": {
                "type": "integer",
                "default": 80,
                "description": "聚类策略每簇最大文件数",
            },
            "max_concurrency": {
                "type": "integer",
                "default": 5,
                "description": "聚类策略最大并发数",
            }
        }
    return {}
