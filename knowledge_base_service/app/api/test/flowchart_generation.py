"""流程图生成阶段测试接口.

提供单独的接口用于测试流程图生成阶段，假设结构图构建阶段已完成，
为C/CPP语言的Method节点生成流程图。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings, resolve_runtime_path
from app.core.pipeline import PipelineContext
from app.core.stages import FlowchartGenerationStage
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import get_graph_db_client

logger = logging.getLogger(__name__)

router = APIRouter()


class TestFlowchartGenerationRequest(BaseModel):
    """测试流程图生成请求."""

    repo_id: str = Field(..., description="仓库ID")
    repo_name: Optional[str] = Field(None, description="仓库名称，不传则使用repo_id")


class TestFlowchartGenerationResponse(BaseModel):
    """测试流程图生成响应."""

    success: bool
    repo_id: str
    stage_status: str
    message: str
    total_methods: int
    generated_count: int
    skipped_count: int
    failed_count: int
    duration_seconds: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


@router.post("/flowchart-generation", response_model=TestFlowchartGenerationResponse)
async def test_flowchart_generation(
    request: TestFlowchartGenerationRequest,
) -> TestFlowchartGenerationResponse:
    """单独测试流程图生成阶段.

    假设结构图构建阶段已完成，为C/CPP语言的Method节点生成流程图。

    Args:
        request: 测试请求，包含repo_id

    Returns:
        测试结果，包含生成的流程图统计信息
    """
    repo_id = request.repo_id
    repo_name = request.repo_name or repo_id

    logger.info(f"Starting flowchart generation test for repo: {repo_id}")

    try:
        # 1. 检查是否存在C/CPP语言的Method节点
        graph_db = get_graph_db_client()
        settings = get_settings()
        supported_languages = settings.flowchart_supported_languages

        methods = await _get_methods_by_languages(graph_db, repo_id, supported_languages)

        if not methods:
            raise HTTPException(
                status_code=404,
                detail=f"No {supported_languages} methods found for repo: {repo_id}. "
                       "Please ensure structure graph build stage is completed.",
            )

        logger.info(f"Found {len(methods)} methods for flowchart generation in repo: {repo_id}")

        # 2. 创建PipelineContext，模拟前面的阶段已完成
        context = _create_test_context(repo_id, repo_name)

        # 3. 执行流程图生成阶段
        stage = FlowchartGenerationStage()
        start_time = datetime.utcnow()

        result = await stage.execute(context)

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        # 4. 构建响应
        metadata = result.metadata or {}
        flowchart_generation = context.data.get("flowchart_generation", {})

        return TestFlowchartGenerationResponse(
            success=result.status == PipelineStatus.COMPLETED,
            repo_id=repo_id,
            stage_status=result.status.value,
            message=result.message,
            total_methods=flowchart_generation.get("total_methods", 0),
            generated_count=flowchart_generation.get("generated_count", 0),
            skipped_count=flowchart_generation.get("skipped_count", 0),
            failed_count=flowchart_generation.get("failed_count", 0),
            duration_seconds=duration,
            metadata=metadata,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Flowchart generation test failed for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Flowchart generation test failed: {str(e)}",
        )


async def _get_methods_by_languages(
    graph_db, repo_id: str, languages: List[str]
) -> List[Dict[str, Any]]:
    """获取指定语言的Method节点.

    Args:
        graph_db: 图数据库客户端
        repo_id: 仓库ID
        languages: 语言列表

    Returns:
        Method节点列表
    """
    query = """
    MATCH (m:Method)
    WHERE m.repoId = $repo_id AND m.language IN $languages
    RETURN m.id as id, m.name as name, m.code as code,
           m.language as language, m.filePath as file_path, m.image as image,
           m.startLine as start_line
    """

    results = await graph_db._execute_query(
        query, {"repo_id": repo_id, "languages": languages}
    )
    return results


def _create_test_context(
    repo_id: str,
    repo_name: str,
) -> PipelineContext:
    """创建测试用的PipelineContext.

    模拟前面的阶段已完成的状态。

    Args:
        repo_id: 仓库ID
        repo_name: 仓库名称

    Returns:
        配置好的PipelineContext
    """
    pipeline_id = str(uuid4())
    settings = get_settings()

    # 创建上下文
    context = PipelineContext(
        pipeline_id=pipeline_id,
        repo_id=repo_id,
        repo_path="",  # 流程图生成不需要实际路径
        repo_name=repo_name,
        config={},
    )

    # 模拟前面阶段的输出
    context.data["node_ids"] = {
        "repository_id": f"repo_{repo_name}",
        "directory_ids": [],
        "file_ids": [],
        "class_ids": [],
        "method_ids": [],
    }

    # 设置当前阶段
    context.current_stage = PipelineStage.FLOWCHART_GENERATION
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


@router.get("/flowchart-generation/status/{repo_id}")
async def get_flowchart_generation_status(repo_id: str) -> Dict[str, Any]:
    """获取仓库的流程图生成状态.

    查询Neo4j中Method节点的流程图生成情况。

    Args:
        repo_id: 仓库ID

    Returns:
        流程图生成状态信息
    """
    try:
        graph_db = get_graph_db_client()
        settings = get_settings()
        supported_languages = settings.flowchart_supported_languages

        # 查询Method统计（按语言分组）
        method_stats_query = """
        MATCH (m:Method)
        WHERE m.repoId = $repo_id AND m.language IN $languages
        RETURN
            m.language as language,
            count(m) as total,
            count(CASE WHEN m.image IS NOT NULL AND m.image <> '' THEN 1 END) as with_image
        ORDER BY language
        """
        method_results = await graph_db._execute_query(
            method_stats_query, {"repo_id": repo_id, "languages": supported_languages}
        )

        # 按语言统计
        language_stats = {}
        total_methods = 0
        total_with_image = 0

        for record in method_results:
            lang = record.get("language", "unknown")
            total = record.get("total", 0)
            with_image = record.get("with_image", 0)

            language_stats[lang] = {
                "total": total,
                "with_image": with_image,
                "completion_percentage": round((with_image / total) * 100, 2) if total > 0 else 0,
            }
            total_methods += total
            total_with_image += with_image

        # 计算总体完成百分比
        overall_completion = 0
        if total_methods > 0:
            overall_completion = round((total_with_image / total_methods) * 100, 2)

        image_dir = resolve_runtime_path(settings.flowchart_image_dir) / repo_id / "image"
        image_files = []
        if image_dir.exists():
            # 获取前10个图片文件（支持png和svg）
            image_files = [f.name for f in sorted(image_dir.glob("*.png") | image_dir.glob("*.svg"))][:10]

        return {
            "repo_id": repo_id,
            "supported_languages": supported_languages,
            "by_language": language_stats,
            "overall": {
                "total_methods": total_methods,
                "methods_with_image": total_with_image,
                "completion_percentage": overall_completion,
            },
            "image_directory": str(image_dir),
            "image_files_sample": image_files,
            "image_files_count": len(list(image_dir.glob("*.png") | image_dir.glob("*.svg"))) if image_dir.exists() else 0,
        }

    except Exception as e:
        logger.exception(f"Failed to get flowchart generation status for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get status: {str(e)}",
        )


@router.get("/flowchart-generation/methods/{repo_id}")
async def get_methods_with_flowchart(
    repo_id: str,
    has_image: Optional[bool] = None,
    language: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """获取带有流程图的Method节点详情.

    分页查询Method节点及其流程图信息。

    Args:
        repo_id: 仓库ID
        has_image: 是否只返回有/无流程图的节点，None表示全部
        language: 过滤特定语言，None表示全部
        limit: 每页数量
        offset: 偏移量

    Returns:
        Method节点列表和分页信息
    """
    try:
        graph_db = get_graph_db_client()
        settings = get_settings()
        supported_languages = settings.flowchart_supported_languages

        # 构建查询条件
        language_condition = ""
        if language:
            language_condition = "AND m.language = $language"
        else:
            language_condition = "AND m.language IN $supported_languages"

        image_condition = ""
        if has_image is True:
            image_condition = "AND m.image IS NOT NULL AND m.image <> ''"
        elif has_image is False:
            image_condition = "AND (m.image IS NULL OR m.image = '')"

        # 查询总数
        count_query = f"""
        MATCH (m:Method)
        WHERE m.repoId = $repo_id {language_condition} {image_condition}
        RETURN count(m) as total
        """
        count_params = {"repo_id": repo_id, "supported_languages": supported_languages}
        if language:
            count_params["language"] = language

        count_results = await graph_db._execute_query(count_query, count_params)
        total = count_results[0]["total"] if count_results else 0

        # 查询Method列表
        methods_query = f"""
        MATCH (m:Method)
        WHERE m.repoId = $repo_id {language_condition} {image_condition}
        RETURN m.id as id, m.name as name, m.filePath as file_path,
               m.language as language, m.startLine as start_line, m.endLine as end_line,
               m.image as image, m.summary as summary
        ORDER BY m.filePath, m.name
        SKIP $offset LIMIT $limit
        """

        methods_results = await graph_db._execute_query(
            methods_query, {**count_params, "offset": offset, "limit": limit}
        )

        methods = []
        image_dir = resolve_runtime_path(settings.flowchart_image_dir) / repo_id / "image"

        for record in methods_results:
            method_data = {k: v for k, v in record.items() if v is not None}

            # 检查图片文件是否存在（支持png和svg）
            image_id = method_data.get("image")
            if image_id:
                image_path_png = image_dir / f"{image_id}.png"
                image_path_svg = image_dir / f"{image_id}.svg"
                method_data["image_exists"] = image_path_png.exists() or image_path_svg.exists()
                method_data["image_url"] = f"/api/test/flowchart-generation/image/{repo_id}/{image_id}"
            else:
                method_data["image_exists"] = False

            methods.append(method_data)

        return {
            "repo_id": repo_id,
            "has_image_filter": has_image,
            "language_filter": language,
            "total": total,
            "offset": offset,
            "limit": limit,
            "methods": methods,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get methods with flowchart for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get methods: {str(e)}",
        )


@router.get("/flowchart-generation/image/{repo_id}/{image_id}")
async def get_flowchart_image(repo_id: str, image_id: str):
    """获取流程图图片.

    Args:
        repo_id: 仓库ID
        image_id: 图片ID

    Returns:
        图片文件
    """
    try:
        settings = get_settings()
        image_dir = resolve_runtime_path(settings.flowchart_image_dir) / repo_id / "image"

        # 尝试查找 png 或 svg 格式的图片
        image_path = image_dir / f"{image_id}.png"
        media_type = "image/png"
        filename = f"{image_id}.png"

        if not image_path.exists():
            image_path = image_dir / f"{image_id}.svg"
            media_type = "image/svg+xml"
            filename = f"{image_id}.svg"

        if not image_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Image not found: {image_id}",
            )

        from fastapi.responses import FileResponse
        return FileResponse(
            path=str(image_path),
            media_type=media_type,
            filename=filename,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get flowchart image {image_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get image: {str(e)}",
        )
